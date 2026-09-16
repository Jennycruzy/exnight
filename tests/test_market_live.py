"""Live checks against the public Bitget API. These are the verification for the
symbol format, fee fields and candle endpoint; they are meant to fail if Bitget changes."""
import datetime as dt

import pytest

from exnight.market import BitgetPublic, V3_INTERVALS

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def api():
    return BitgetPublic()


def test_rtoken_universe_is_large_and_usdt_quoted(api):
    universe = api.rtokens()
    assert len(universe) > 500
    assert {s.quote_coin for s in universe.values()} == {"USDT"}
    assert all(s.symbol == s.base_coin.upper() + s.quote_coin for s in universe.values())


def test_known_batch_tokens_resolve(api):
    for t in ("MU", "QQQ", "TSM"):
        s = api.rtoken_symbol(t)
        assert s.underlying == t
        assert s.status == "online"


def test_one_minute_history_covers_july_batch(api):
    s = api.rtoken_symbol("MU")
    start = dt.datetime(2026, 7, 24, 0, 0, tzinfo=dt.UTC)
    end = dt.datetime(2026, 7, 25, 0, 0, tzinfo=dt.UTC)
    df = api.candles_v3(s.symbol, "1m", start, end)
    assert len(df) > 1000  # more than one page, so pagination ran
    assert df["ts"].is_monotonic_increasing
    assert df["ts"].iloc[0] <= start + dt.timedelta(minutes=5)
    assert df["ts"].iloc[-1] >= end - dt.timedelta(minutes=5)


def test_v3_rejects_unsupported_interval(api):
    from exnight.errors import BitgetAPIError
    with pytest.raises(BitgetAPIError):
        api._get("/api/v3/market/candles",
                 dict(category="SPOT", symbol="RMUUSDT", interval="3m", limit=10))
    assert "3m" not in V3_INTERVALS
