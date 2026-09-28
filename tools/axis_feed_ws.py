"""
Live tick stream for the live-charts feature, sourced ONLY from Axis
Direct's RAPID API WebSocket feed (raterefresh.axisdirect.in / UAT
sender-feed-api). No Upstox/Angel/yfinance fallback here by design - if
Axis is unreachable or a symbol has no cocode mapping, the caller gets
no ticks rather than a silently-substituted other-provider price.

Requires AXIS_API_CLIENT_ID / AXIS_AUTHORIZATION_KEY / AXIS_OAUTH_CLIENT_SECRET
(tools/axis_rapid_client.get_oauth_token) and AXIS_ENTITY_ID. Untested
against a live connection - Axis has not yet provisioned credentials.
"""

import os
import threading
import websocket
from dotenv import load_dotenv

from tools.axis_rapid_client import get_oauth_token, _hosts
from tools.axis_feed_decoder import decode_frame


def _subscribe_key(exchange: str, cocode) -> str:
    """Builds the RAPID subscription key, e.g. b_nse_5400 for NSE cash."""
    return f"b_{exchange}_{cocode}"


class AxisLiveFeed:
    """One WebSocket connection subscribed to a set of symbols (by cocode),
    dispatching decoded ticks to `on_tick(dict)`. Reconnection/backoff is
    intentionally left to the caller for now - this is a thin wrapper, not
    a production-hardened client, until it's been run against a real feed.
    """

    def __init__(self, on_tick):
        load_dotenv()
        self.on_tick = on_tick
        self._ws = None
        self._thread = None
        self._subscribed = set()

    def connect(self):
        token, _secret = get_oauth_token()
        entity_id = os.getenv("AXIS_ENTITY_ID")
        if not entity_id:
            raise ValueError("AXIS_ENTITY_ID is not set in .env")

        url = _hosts()["feed_ws"]
        headers = [
            f"token: {token}",
            f"ent_id: {entity_id}",
            "source: navrist",
        ]

        def _on_message(ws, message):
            if isinstance(message, (bytes, bytearray)):
                tick = decode_frame(message)
                if tick:
                    self.on_tick(tick)

        def _on_open(ws):
            for key in list(self._subscribed):
                ws.send(key)

        self._ws = websocket.WebSocketApp(
            url,
            header=headers,
            on_message=_on_message,
            on_open=_on_open,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()

    def subscribe(self, exchange: str, cocode):
        key = _subscribe_key(exchange, cocode)
        self._subscribed.add(key)
        if self._ws and self._ws.sock and self._ws.sock.connected:
            self._ws.send(key)

    def unsubscribe(self, exchange: str, cocode):
        key = _subscribe_key(exchange, cocode)
        self._subscribed.discard(key)

    def close(self):
        if self._ws:
            self._ws.close()
