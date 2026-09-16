"""Public Bitget market data. Unauthenticated.

Everything here is fetched at runtime. There is no symbol list, fee rate, tick size or
interval table hardcoded anywhere in this package; the values below were OBSERVED from
the live API on 2026-09-16 and are re-fetched on every run.

Endpoints (OBSERVED working, see docs/verification.md):
  GET /api/v2/spot/public/symbols            symbol list with fees and precisions
  GET /api/v3/market/candles                 UTA v3 candles, max 1000, 1m/5m/15m/1H/4H/1D
  GET /api/v2/spot/market/history-candles    spot v2 history, endTime required
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pandas as pd

from .errors import BitgetAPIError

BASE_URL = "https://api.bitget.com"

# OBSERVED 2026-09-16: rToken base coins are 'r' + upper-case ticker (rAAPL, rMU, rQQQ)
# and the spot symbol is upper(baseCoin) + quoteCoin (RAAPLUSDT). This regex identifies
# the rToken universe from the live symbol list rather than from any stored list.
_RTOKEN_BASE = re.compile(r"^r[A-Z][A-Z0-9.]*$")

# OBSERVED 2026-09-16: v3 rejects limit=1001 (code 40020) and interval=3m (code 48001).
V3_MAX_LIMIT = 1000
V3_INTERVALS = ("1m", "5m", "15m", "1H", "4H", "1D")

CANDLE_COLUMNS = ["ts", "open", "high", "low", "close", "volume", "quote_volume"]


@dataclass(frozen=True)
class SpotSymbol:
    symbol: str
    base_coin: str
    quote_coin: str
    maker_fee: Decimal
    taker_fee: Decimal
    price_precision: int
    quantity_precision: int
    min_trade_usdt: Decimal
    status: str
    open_time: dt.datetime

    @property
    def is_rtoken(self) -> bool:
        return bool(_RTOKEN_BASE.match(self.base_coin))

    @property
    def underlying(self) -> str:
        if not self.is_rtoken:
            raise ValueError(f"{self.symbol} is not an rToken")
        return self.base_coin[1:]

    @property
    def tick_size(self) -> Decimal:
        return Decimal(1).scaleb(-self.price_precision)


class BitgetPublic:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

    def _get(self, path: str, params: dict) -> list | dict:
        r = self._client.get(path, params=params)
        try:
            body = r.json()
        except ValueError as e:
            raise BitgetAPIError(path, str(r.status_code), r.text[:200]) from e
        if body.get("code") != "00000":
            raise BitgetAPIError(path, str(body.get("code")), str(body.get("msg")))
        return body["data"]

    # ---- symbols -------------------------------------------------------------------

    def spot_symbols(self) -> list[SpotSymbol]:
        rows = self._get("/api/v2/spot/public/symbols", {})
        out = []
        for x in rows:
            out.append(
                SpotSymbol(
                    symbol=x["symbol"],
                    base_coin=x["baseCoin"],
                    quote_coin=x["quoteCoin"],
                    maker_fee=Decimal(x["makerFeeRate"]),
                    taker_fee=Decimal(x["takerFeeRate"]),
                    price_precision=int(x["pricePrecision"]),
                    quantity_precision=int(x["quantityPrecision"]),
                    min_trade_usdt=Decimal(x["minTradeUSDT"]),
                    status=x["status"],
                    open_time=dt.datetime.fromtimestamp(int(x["openTime"]) / 1000, dt.UTC),
                )
            )
        return out

    def rtokens(self) -> dict[str, SpotSymbol]:
        """Live rToken universe keyed by base coin (e.g. 'rMU')."""
        return {s.base_coin: s for s in self.spot_symbols() if s.is_rtoken}

    def rtoken_symbol(self, ticker: str) -> SpotSymbol:
        """Resolve an underlying ticker ('MU') to its live rToken spot symbol."""
        universe = self.rtokens()
        key = f"r{ticker.upper()}"
        if key not in universe:
            raise KeyError(f"no rToken for {ticker!r} in live symbol list ({len(universe)} rTokens)")
        return universe[key]

    # ---- candles -------------------------------------------------------------------

    def candles_v3(
        self,
        symbol: str,
        interval: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> pd.DataFrame:
        """All v3 SPOT candles in [start, end], paginating backwards in 1000-bar pages.

        Returns a frame sorted by ts ascending with Decimal-safe float columns. Raises if
        the endpoint errors. Does NOT fill gaps: a missing bar stays missing so that the
        caller can detect it (see DataGapError in the event-study layer).
        """
        if interval not in V3_INTERVALS:
            raise ValueError(f"interval {interval!r} not in {V3_INTERVALS}")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        pages: list[list] = []
        cursor_end = int(end.timestamp() * 1000)
        start_ms = int(start.timestamp() * 1000)
        while True:
            rows = self._get(
                "/api/v3/market/candles",
                dict(category="SPOT", symbol=symbol, interval=interval,
                     endTime=cursor_end, limit=V3_MAX_LIMIT),
            )
            if not rows:
                break
            rows = [r for r in rows if int(r[0]) >= start_ms]
            pages.append(rows)
            oldest = int(rows[0][0]) if rows else None
            if oldest is None or oldest <= start_ms or len(rows) < V3_MAX_LIMIT:
                break
            cursor_end = oldest - 1
        flat = [r for page in reversed(pages) for r in page]
        df = pd.DataFrame(flat, columns=CANDLE_COLUMNS)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
        for c in CANDLE_COLUMNS[1:]:
            df[c] = df[c].astype(float)
        return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
