"""Live updates from ShowPilot's socket.io feed (the same one the viewer page uses).

A minimal socket.io v4 client over aiohttp: connect, answer pings, and turn the
events that change what Home Assistant shows into an immediate refresh. Nothing
is ever sent to the server except the protocol's own handshake and pongs, and
the server only counts viewers from page heartbeats, so this never shows up as a
viewer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
from urllib.parse import urlsplit, urlunsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Events that change something Home Assistant shows. High-rate playback
# events (positionUpdate, fppPosition, fppSyncPoint, raceTapUpdate) are ignored.
REFRESH_EVENTS = frozenset({
    "nowPlaying", "nextScheduled", "queueUpdated", "viewerModeChanged", "viewerCount",
    "voteUpdate", "voteReset", "votingRoundEnded", "sequencesReordered", "sequencesSynced",
    "viewerTemplateChanged", "raceStarted", "raceEnded", "raceWinner",
    "tiebreakStarted", "tiebreakFailed",
})
# Events that also change plugin-side details (categories, viewer page).
EXTRAS_EVENTS = frozenset({"sequencesReordered", "viewerTemplateChanged"})

RETRY_MIN = 2
RETRY_MAX = 60


def socket_url(base: str) -> str:
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = parts.path.rstrip("/") + "/socket.io/"
    return urlunsplit((scheme, parts.netloc, path, "EIO=4&transport=websocket", ""))


def parse_packet(msg: str) -> tuple[str, str | None]:
    """Return ('ping'|'open'|'connect'|'event'|'close'|'other', event name)."""
    if msg == "2":
        return "ping", None
    if msg.startswith("0"):
        return "open", None
    if msg.startswith("1"):
        return "close", None
    if msg.startswith("40"):
        return "connect", None
    if msg.startswith("42"):
        body = msg[2:]
        # Optional ack id before the JSON array.
        i = 0
        while i < len(body) and body[i].isdigit():
            i += 1
        try:
            data = json.loads(body[i:])
        except ValueError:
            return "other", None
        if isinstance(data, list) and data and isinstance(data[0], str):
            return "event", data[0]
    return "other", None


def event_payload(msg: str) -> object:
    """The first argument of a 42 event packet, or None."""
    body = msg[2:].lstrip("0123456789")
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data[1] if isinstance(data, list) and len(data) > 1 else None


class LiveFeed:
    """Keeps a socket.io connection open and calls back on relevant events."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        on_event: Callable[[str], None],
        on_status: Callable[[bool], Awaitable[None] | None],
    ) -> None:
        self._session = session
        self._url = socket_url(base_url)
        self._on_event = on_event
        self._on_status = on_status
        self.connected = False
        self._stop = False
        self._last_count: object = None

    async def run(self) -> None:
        delay = RETRY_MIN
        while not self._stop:
            try:
                await self._connect_once()
                delay = RETRY_MIN
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                _LOGGER.debug("ShowPilot live feed: %s", err)
            except Exception:  # noqa: BLE001 - never let the feed task die silently
                _LOGGER.exception("ShowPilot live feed failed")
            await self._set_connected(False)
            if self._stop:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    def stop(self) -> None:
        self._stop = True

    async def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            res = self._on_status(value)
            if asyncio.iscoroutine(res):
                await res

    async def _connect_once(self) -> None:
        async with self._session.ws_connect(self._url, heartbeat=None, timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
            ping_timeout = 30.0
            while True:
                try:
                    msg = await ws.receive(timeout=ping_timeout)
                except asyncio.TimeoutError:
                    _LOGGER.debug("ShowPilot live feed: no ping, reconnecting")
                    return
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                    aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        return
                    continue
                kind, name = parse_packet(msg.data)
                if kind == "open":
                    try:
                        info = json.loads(msg.data[1:])
                        ping_timeout = (info.get("pingInterval", 25000) + info.get("pingTimeout", 20000)) / 1000 + 5
                    except ValueError:
                        pass
                    await ws.send_str("40")
                elif kind == "connect":
                    await self._set_connected(True)
                    # Catch up on anything missed while disconnected.
                    self._on_event("connect")
                elif kind == "ping":
                    await ws.send_str("3")
                elif kind == "close":
                    return
                elif kind == "event" and name in REFRESH_EVENTS:
                    if name == "viewerCount":
                        # Broadcast every few seconds; only a change matters.
                        count = event_payload(msg.data)
                        if count == self._last_count:
                            continue
                        self._last_count = count
                    self._on_event(name)
