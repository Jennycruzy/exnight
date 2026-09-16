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
import time
from dataclasses import dataclass, replace
from decimal import Decimal

import httpx
import pandas as pd

from .errors import BitgetAPIError

BASE_URL = "https://api.bitget.com"

HISTORY_CUTOFF = dt.timedelta(days=85)   # documented: history-candles serves data > 90 days old
_MIN_INTERVAL_S = 0.1
_ENDPOINT_INTERVAL_S = {
    "/api/v3/reality/market/stock-info": 1.05,
    "/api/v3/reality/market/dividends": 1.05,
}

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
    is_rwa: str | None = None
    reality_code: str | None = None

    @property
    def is_rtoken(self) -> bool:
        return self.symbol_type == "stock" and self.is_reality

    @property
    def underlying(self) -> str:
        if not self.is_rtoken:
            raise ValueError(f"{self.symbol} is not an rToken")
        if not self.reality_code:
            raise ValueError(f"{self.symbol} has no Reality code; resolve it from stock-info first")
        return self.reality_code

    @property
    def tick_size(self) -> Decimal:
        return Decimal(1).scaleb(-self.price_precision)


class BitgetPublic:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

        self._last = 0.0
        self._last_by_path: dict[str, float] = {}
        self._stock_info_cache: dict[str, dict] = {}
        self.last_fetch_at: dt.datetime | None = None
        self.last_request: dict | None = None
        self.last_raw_response: str | None = None

    def _get(self, path: str, params: dict) -> list | dict:
        now = time.monotonic()
        path_interval = _ENDPOINT_INTERVAL_S.get(path, _MIN_INTERVAL_S)
        wait = max(self._last + _MIN_INTERVAL_S,
                   self._last_by_path.get(path, 0.0) + path_interval) - now
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self._last_by_path[path] = self._last
        r = self._client.get(path, params=params)
        self.last_fetch_at = dt.datetime.now(dt.UTC)
        self.last_request = {"path": path, "params": dict(params)}
        self.last_raw_response = r.text
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
                    is_rwa=x.get("isRwa"),
                )
            )
        return out

    def rtokens(self) -> dict[str, SpotSymbol]:
        """Live Reality instruments keyed by the API-returned base coin."""
        syms = self.spot_symbols()
        return {s.base_coin: s for s in syms if s.is_rtoken}

    def rtoken_symbol(self, identifier: str) -> SpotSymbol:
        """Resolve an instrument identifier returned by instruments.

        identifier must be the live symbol or baseCoin value. The underlying equity
        code is loaded from Reality's public stock-info endpoint; it is never
        reconstructed from the token name.
        """
        universe = self.rtokens()
        needle = identifier.casefold()
        for candidate in universe.values():
            if needle in {candidate.symbol.casefold(), candidate.base_coin.casefold()}:
                info = self.reality_stock_info(candidate.symbol)
                code = info.get("code")
                if not code:
                    raise BitgetAPIError("/api/v3/reality/market/stock-info", "schema",
                                         f"{candidate.symbol} has no code")
                return replace(candidate, reality_code=str(code))
        raise KeyError(
            f"no rToken for identifier {identifier!r}; use a symbol or baseCoin returned by instruments"
        )

    # ---- Reality market data -------------------------------------------------------

    def _dict_data(self, path: str, params: dict) -> dict:
        data = self._get(path, params)
        if not isinstance(data, dict):
            raise BitgetAPIError(path, "schema", f"expected object, got {type(data).__name__}")
        return data

    def reality_stock_info(self, symbol: str) -> dict:
        if symbol not in self._stock_info_cache:
            data = self._get("/api/v3/reality/market/stock-info", {"symbol": symbol})
            if isinstance(data, dict):
                info = data
            elif isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                info = data[0]
            else:
                raise BitgetAPIError("/api/v3/reality/market/stock-info", "schema",
                                     "expected one stock-info object")
            self._stock_info_cache[symbol] = info
        return self._stock_info_cache[symbol]

    def reality_dividends(self, code: str, limit: int = 100, cursor: str | None = None) -> dict:
        params: dict[str, str | int] = {"code": code, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = self._dict_data("/api/v3/reality/market/dividends", params)
        if data.get("list") is not None and not isinstance(data.get("list"), list):
            raise BitgetAPIError("/api/v3/reality/market/dividends", "schema", "list is not an array or null")
        return data

    def cash_dividend_records(self, symbol: str, record_type: str = "paid",
                              limit: int = 100, cursor: str | None = None) -> dict:
        if record_type not in {"pending", "paid"}:
            raise ValueError("record_type must be 'pending' or 'paid'")
        params: dict[str, str | int] = {"symbol": symbol, "type": record_type, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = self._dict_data("/api/v3/market/cash-dividend-records", params)
        if data.get("list") is not None and not isinstance(data.get("list"), list):
            raise BitgetAPIError("/api/v3/market/cash-dividend-records", "schema", "list is not an array or null")
        return data

    def iter_reality_dividends(self, code: str, limit: int = 100):
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            data = self.reality_dividends(code, limit=limit, cursor=cursor)
            rows = data.get("list") or []
            yield data, rows
            next_cursor = data.get("cursor")
            if not next_cursor:
                return
            next_cursor = str(next_cursor)
            if next_cursor in seen:
                raise BitgetAPIError("/api/v3/reality/market/dividends", "cursor", "cursor repeated")
            seen.add(next_cursor)
            cursor = next_cursor

    def split_records(self) -> list[dict]:
        data = self._get("/api/v3/market/split-records", {})
        if not isinstance(data, list):
            raise BitgetAPIError("/api/v3/market/split-records", "schema", "expected array")
        return data

    def market_states(self) -> dict:
        return self._dict_data("/api/v3/reality/market/states", {})

    def market_calendar(self) -> dict:
        return self._dict_data("/api/v3/reality/market/calendar", {})

    def tickers(self, symbol: str | None = None) -> list[dict]:
        params = {"category": "SPOT"}
        if symbol:
            params["symbol"] = symbol
        data = self._get("/api/v3/market/tickers", params)
        if not isinstance(data, list):
            raise BitgetAPIError("/api/v3/market/tickers", "schema", "expected array")
        return data

    def orderbook(self, symbol: str, limit: int = 1000) -> dict:
        if not 1 <= limit <= V3_MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {V3_MAX_LIMIT}")
        data = self._dict_data(
            "/api/v3/market/orderbook", {"category": "SPOT", "symbol": symbol, "limit": limit}
        )
        # OBSERVED 2026-09-16: the live response uses short keys ``a``/``b`` (docs show
        # ``asks``/``bids``). Accept either and normalise to the documented names.
        asks = data.get("asks", data.get("a"))
        bids = data.get("bids", data.get("b"))
        if not isinstance(asks, list) or not isinstance(bids, list):
            raise BitgetAPIError("/api/v3/market/orderbook", "schema", "asks/bids are not arrays")
        return {"asks": asks, "bids": bids, "ts": data.get("ts")}

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
                     type="market", endTime=cursor_end, limit=page),
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
