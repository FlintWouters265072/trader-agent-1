from __future__ import annotations

from urllib.parse import quote

import requests


class AlpacaError(RuntimeError):
    pass


def is_crypto(symbol: str) -> bool:
    return "/" in symbol


def normalize_crypto_symbol(symbol: str, asset_class: str | None) -> str:
    """Alpaca's positions/orders endpoints return crypto symbols without the '/' (e.g. 'XRPUSD'),
    but quotes, order placement, and our own is_crypto() all expect it ('XRP/USD') — a position
    held via a no-slash symbol silently fails every quote lookup (routed to the stock endpoint,
    which finds nothing), so a sell of it is permanently rejected as 'no usable live price'. Fix
    it once, right after fetching from Alpaca, using the asset_class Alpaca already gives us —
    so the prompt shown to the model, exposure/quantity math, and order placement all agree on
    one symbol, and the model naturally echoes back a form that actually works."""
    if asset_class == "crypto" and "/" not in symbol and symbol.endswith("USD"):
        return f"{symbol[:-3]}/USD"
    return symbol


class AlpacaClient:
    def __init__(self, base_url: str, data_url: str, api_key_id: str, api_secret_key: str):
        self.base_url = base_url
        self.data_url = data_url
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "Content-Type": "application/json",
        })

    def _request(self, base: str, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{base}{path}", timeout=15, **kwargs)
        if not resp.ok:
            raise AlpacaError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def get_account(self) -> dict:
        return self._request(self.base_url, "GET", "/v2/account")

    def get_clock(self) -> dict:
        return self._request(self.base_url, "GET", "/v2/clock")

    def get_positions(self) -> list[dict]:
        return self._request(self.base_url, "GET", "/v2/positions")

    def get_orders(self, status: str = "open") -> list[dict]:
        return self._request(self.base_url, "GET", "/v2/orders", params={"status": status, "limit": 50})

    def get_asset(self, symbol: str) -> dict:
        return self._request(self.base_url, "GET", f"/v2/assets/{quote(symbol, safe='')}")

    def get_quote(self, symbol: str) -> dict:
        if is_crypto(symbol):
            data = self._request(
                self.data_url, "GET", "/v1beta3/crypto/us/latest/quotes", params={"symbols": symbol}
            )
        else:
            data = self._request(
                self.data_url, "GET", "/v2/stocks/quotes/latest", params={"symbols": symbol}
            )
        return data.get("quotes", {}).get(symbol, {})

    def cancel_order(self, order_id: str) -> None:
        self._request(self.base_url, "DELETE", f"/v2/orders/{order_id}")

    def place_order(self, symbol: str, side: str, qty: float) -> dict:
        body = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "gtc" if is_crypto(symbol) else "day",
        }
        return self._request(self.base_url, "POST", "/v2/orders", json=body)
