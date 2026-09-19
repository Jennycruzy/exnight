import json

import httpx

from exnight.trading import BitgetPrivate, _signature


def test_signature_matches_bitget_hmac_shape():
    value = _signature("16273667805456", "POST", "/api/v3/trade/place-order",
                       '{"category":"SPOT","symbol":"BTCUSDT"}', "secret")
    assert value == "oExyf4gC3KWZZxcIuZ4Pw3EBTe/94M6vYR/q2SyMH5M="


def test_private_client_sorts_get_query_and_validates_envelope(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.raw_path.decode()
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"code": "00000", "msg": "success", "data": [{"coin": "USDT", "available": "12"}]})

    monkeypatch.setattr("exnight.trading.time.time", lambda: 16273667805.456)
    client = BitgetPrivate("key", "secret", "pass", httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.bitget.com"))
    assert client.available("USDT") == "12"
    assert seen["path"] == "/api/v3/account/assets?coin=USDT"
    assert seen["headers"]["access-key"] == "key"
    assert seen["headers"]["access-sign"]


def test_place_reality_order_uses_documented_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "msg": "success", "data": {"orderId": "1"}})

    client = BitgetPrivate("key", "secret", "pass", httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.bitget.com"))
    out = client.place_reality_limit("rAAPLUSDT", "buy", "1", "100", "exnight-test")
    assert out["data"]["orderId"] == "1"
    assert seen == {"path": "/api/v3/trade/place-reality-order", "body": {
        "category": "SPOT", "symbol": "rAAPLUSDT", "side": "buy", "orderType": "limit",
        "qty": "1", "price": "100", "clientOid": "exnight-test",
    }}
