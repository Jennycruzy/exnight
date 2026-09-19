"""Minimal signed Bitget UTA client for the guarded Reality order path.

The public market adapter remains unauthenticated. This client is used only after the
paper-trade script has sized an order, rechecked the book, checked available balance and
received the explicit live confirmation string.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.bitget.com"


class BitgetPrivateError(RuntimeError):
    pass


def _query_string(params: dict[str, object] | None) -> str:
    if not params:
        return ""
    return urlencode(sorted((str(k), str(v)) for k, v in params.items() if v is not None))


def _compact_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _signature(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    message = f"{timestamp}{method.upper()}{request_path}{body}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class BitgetPrivate:
    def __init__(self, api_key: str, secret_key: str, passphrase: str,
                 client: httpx.Client | None = None):
        if not all((api_key, secret_key, passphrase)):
            raise ValueError("Bitget private credentials are required")
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

    def request(self, method: str, path: str, *, params: dict[str, object] | None = None,
                body: dict | None = None) -> dict:
        method = method.upper()
        query = _query_string(params) if method == "GET" else ""
        signed_path = f"{path}?{query}" if query else path
        body_text = _compact_json(body or {}) if method != "GET" else ""
        timestamp = str(int(time.time() * 1000))
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": _signature(timestamp, method, signed_path, body_text, self.secret_key),
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        try:
            response = self._client.request(method, signed_path, content=body_text, headers=headers)
            payload = response.json()
        except httpx.HTTPError as exc:
            raise BitgetPrivateError(f"Bitget private request failed: {exc}") from exc
        except ValueError as exc:
            raise BitgetPrivateError(f"Bitget private request returned non-JSON status={response.status_code}") from exc
        if response.status_code >= 400:
            code = payload.get("code", response.status_code) if isinstance(payload, dict) else response.status_code
            message = payload.get("msg", "HTTP error") if isinstance(payload, dict) else "HTTP error"
            raise BitgetPrivateError(f"Bitget private request rejected: status={response.status_code} code={code} msg={message}")
        if not isinstance(payload, dict) or payload.get("code") != "00000":
            code = payload.get("code", "schema") if isinstance(payload, dict) else "schema"
            message = payload.get("msg", "invalid response") if isinstance(payload, dict) else "invalid response"
            raise BitgetPrivateError(f"Bitget private request rejected: code={code} msg={message}")
        return payload

    def assets(self, coin: str | None = None) -> dict:
        return self.request("GET", "/api/v3/account/assets", params={"coin": coin} if coin else None)

    def available(self, coin: str) -> str:
        payload = self.assets(coin)
        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if isinstance(row, dict) and str(row.get("coin", "")).upper() == coin.upper():
                return str(row.get("available", "0"))
        return "0"

    def place_reality_limit(self, symbol: str, side: str, qty: str, price: str,
                            client_oid: str) -> dict:
        return self.request("POST", "/api/v3/trade/place-reality-order", body={
            "category": "SPOT", "symbol": symbol, "side": side,
            "orderType": "limit", "qty": qty, "price": price, "clientOid": client_oid,
        })

    def order_info(self, order_id: str) -> dict:
        return self.request("GET", "/api/v3/trade/order-info", params={"orderId": order_id})

    def cancel_reality(self, symbol: str, order_id: str) -> dict:
        return self.request("POST", "/api/v3/trade/cancel-reality-order", body={
            "category": "SPOT", "symbol": symbol, "orderId": order_id,
        })
