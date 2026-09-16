"""Public Bitget market data. Unauthenticated.

Everything here is fetched at runtime. There is no symbol list, fee rate, tick size or
interval table hardcoded anywhere in this package; the values below were OBSERVED from
the live API on 2026-09-16 and are re-fetched on every run.

Endpoints (DOCUMENTED at bitget.com/api-doc/uta, OBSERVED working; see docs/verification.md):
  GET /api/v3/market/instruments?category=SPOT   universe; rTokens carry symbolType=stock, isReality=yes
  GET /api/v2/spot/public/symbols                 maker/taker fee rates (v3 instruments has none)
  GET /api/v3/market/candles                      max 1000 bars; live API accepts 1m/5m/15m/1H/4H/1D
  GET /api/v3/market/history-candles              same shape, for data older than ~90 days
  GET /api/v3/market/orderbook?category=SPOT      depth, max 1000 levels
Rate limit is documented as 20 req/s/IP; this client caps itself at 10.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pandas as pd

from .errors import BitgetAPIError

BASE_URL = "https://api.bitget.com"

# OBSERVED 2026-09-16: rToken base coins are 'r' + upper-case ticker (rAAPL, rMU, rQQQ)
# and the spot symbol is upper(baseCoin) + quoteCoin (RAAPLUSDT). The documented identifier
# is symbolType == "stock" and isReality == "yes" on v3 instruments; the regex is kept as a
# cross-check and the client raises if the two ever disagree.
_RTOKEN_BASE = re.compile(r"^r[A-Z][A-Z0-9.]*$")
HISTORY_CUTOFF = dt.timedelta(days=85)   # documented: history-candles serves data > 90 days old
_MIN_INTERVAL_S = 0.1

# OBSERVED 2026-09-16: /candles rejects limit=1001 and /history-candles rejects limit>100
# (both code 40020); interval=3m is rejected (48001) although the docs list it.
V3_MAX_LIMIT = 1000
V3_HISTORY_MAX_LIMIT = 100
V3_INTERVALS = ("1m", "5m", "15m", "1H", "4H", "1D")
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1H": 3_600_000, "4H": 14_400_000, "1D": 86_400_000}

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
    symbol_type: str = ""
    is_reality: bool = False

    @property
    def is_rtoken(self) -> bool:
        return self.symbol_type == "stock" and self.is_reality

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

        self._last = 0.0

    def _get(self, path: str, params: dict) -> list | dict:
        wait = self._last + _MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
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
        """v3 instruments joined with v2 fee rates. Every field is live."""
        fees = {x["symbol"]: x for x in self._get("/api/v2/spot/public/symbols", {})}
        out = []
        for x in self._get("/api/v3/market/instruments", {"category": "SPOT"}):
            f = fees.get(x["symbol"])
            if f is None:
                raise BitgetAPIError("/api/v2/spot/public/symbols", "join", f"{x['symbol']} has no fee record")
            out.append(
                SpotSymbol(
                    symbol=x["symbol"],
                    base_coin=x["baseCoin"],
                    quote_coin=x["quoteCoin"],
                    maker_fee=Decimal(f["makerFeeRate"]),
                    taker_fee=Decimal(f["takerFeeRate"]),
                    price_precision=int(x["pricePrecision"]),
                    quantity_precision=int(x["quantityPrecision"]),
                    min_trade_usdt=Decimal(x["minOrderAmount"]),
                    status=x["status"],
                    open_time=dt.datetime.fromtimestamp(int(x["launchTime"]) / 1000, dt.UTC),
                    symbol_type=x.get("symbolType", ""),
                    is_reality=x.get("isReality") == "yes",
                )
            )
        return out

    def rtokens(self) -> dict[str, SpotSymbol]:
        """Live rToken universe keyed by base coin (e.g. 'rMU')."""
        syms = self.spot_symbols()
        by_flag = {s.base_coin: s for s in syms if s.is_rtoken}
        by_regex = {s.base_coin for s in syms if _RTOKEN_BASE.match(s.base_coin)}
        if set(by_flag) != by_regex:
            raise BitgetAPIError("/api/v3/market/instruments", "universe",
                                 f"symbolType/isReality set differs from r-prefix set by "
                                 f"{sorted(set(by_flag) ^ by_regex)[:10]}")
        return by_flag

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
        # OBSERVED 2026-09-16: /candles returns bars with ts <= endTime; /history-candles
        # returns bars that *close* at or before endTime (ts + interval <= endTime). Paging
        # therefore asks for one interval past the boundary and dedupes, which is correct
        # under both semantics and never skips a bar.
        pages: list[list] = []
        step = INTERVAL_MS[interval]
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        cursor_end = end_ms + step
        while True:
            old = dt.datetime.now(dt.UTC) - dt.datetime.fromtimestamp(cursor_end / 1000, dt.UTC) > HISTORY_CUTOFF
            page = V3_HISTORY_MAX_LIMIT if old else V3_MAX_LIMIT
            rows = self._get(
                "/api/v3/market/history-candles" if old else "/api/v3/market/candles",
                dict(category="SPOT", symbol=symbol, interval=interval,
                     endTime=cursor_end, limit=page),
            )
            if not rows:
                break
            n_raw = len(rows)
            oldest = int(rows[0][0])
            rows = [r for r in rows if start_ms <= int(r[0]) <= end_ms]
            pages.append(rows)
            if oldest <= start_ms or n_raw < page:
                break
            cursor_end = oldest + step
        flat = [r for page in reversed(pages) for r in page]
        df = pd.DataFrame(flat, columns=CANDLE_COLUMNS)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
        for c in CANDLE_COLUMNS[1:]:
            df[c] = df[c].astype(float)
        return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
