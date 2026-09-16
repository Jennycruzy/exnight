import datetime as dt

import httpx

from exnight.market import BitgetPublic


def test_reality_instrument_selection_does_not_infer_a_token_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/spot/public/symbols":
            return httpx.Response(200, json={"code": "00000", "data": [
                {"symbol": "ASSETUSDT", "makerFeeRate": "0.001", "takerFeeRate": "0.001"},
            ]})
        if request.url.path == "/api/v3/market/instruments":
            return httpx.Response(200, json={"code": "00000", "data": [
                {"symbol": "ASSETUSDT", "baseCoin": "asset-token", "quoteCoin": "USDT",
                 "pricePrecision": "2", "quantityPrecision": "4", "minOrderAmount": "10",
                 "status": "online", "launchTime": "1780000000000", "symbolType": "stock",
                 "isReality": "yes"},
            ]})
        if request.url.path == "/api/v3/reality/market/stock-info":
            return httpx.Response(200, json={"code": "00000", "data": [{
                "symbol": "ASSETUSDT", "code": "ASSET",
            }]})
        raise AssertionError(request.url)

    api = BitgetPublic(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitget.com"))
    token = api.rtoken_symbol("ASSETUSDT")
    assert token.base_coin == "asset-token"
    assert token.underlying == "ASSET"
    assert token.is_rwa is None


def test_reality_and_legacy_corporate_action_envelopes_are_validated():
    def handler(request: httpx.Request) -> httpx.Response:
        payloads = {
            "/api/v3/reality/market/dividends": {"list": [{"type": "cash_dividend"}], "cursor": "next"},
            "/api/v3/market/cash-dividend-records": {"list": [{"cashDividendPerShare": "0.15"}], "cursor": "next"},
            "/api/v3/market/split-records": [{"symbol": "ASSETUSDT", "adjustmentRatio": "2"}],
        }
        if request.url.path in payloads:
            return httpx.Response(200, json={"code": "00000", "data": payloads[request.url.path]})
        raise AssertionError(request.url)

    api = BitgetPublic(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitget.com"))
    assert api.reality_dividends("ASSET")["list"][0]["type"] == "cash_dividend"
    assert api.cash_dividend_records("ASSETUSDT")["list"][0]["cashDividendPerShare"] == "0.15"
    assert api.split_records()[0]["adjustmentRatio"] == "2"


def test_market_requests_have_explicit_market_type():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"code": "00000", "data": [
            [str(int(dt.datetime(2026, 9, 16, tzinfo=dt.UTC).timestamp() * 1000)),
             "1", "1", "1", "1", "1", "1"],
        ]})

    api = BitgetPublic(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitget.com"))
    api.candles_v3("ASSETUSDT", "1m", dt.datetime(2026, 9, 16, tzinfo=dt.UTC),
                   dt.datetime(2026, 9, 16, 0, 1, tzinfo=dt.UTC))
    assert seen and seen[0]["type"] == "market"
