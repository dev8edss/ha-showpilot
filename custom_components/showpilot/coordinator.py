"""Polls the ShowPilot server and fires song / request events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ShowPilotAuthError, ShowPilotClient, ShowPilotError
from .const import (
    DOMAIN,
    EVENT_SONG_CHANGED,
    EVENT_SONG_REQUESTED,
    EXTRAS_EVERY,
    PLUGIN_STALE_SECONDS,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type ShowPilotConfigEntry = ConfigEntry["ShowPilotCoordinator"]


@dataclass
class ShowPilotData:
    """One poll's worth of data."""

    state: dict[str, Any]
    stats: dict[str, Any]
    version: str | None = None
    plugin: dict[str, Any] | None = None
    peek: dict[str, Any] | None = None
    categories: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tonight(self) -> dict[str, Any]:
        return self.stats.get("tonight") or {}

    @property
    def plugin_last_seen(self) -> datetime | None:
        if not self.plugin:
            return None
        return dt_util.parse_datetime(self.plugin.get("lastSeen") or "")

    @property
    def plugin_connected(self) -> bool | None:
        if self.plugin is None:
            return None
        seen = self.plugin_last_seen
        if seen is None:
            return False
        return dt_util.utcnow() - seen < timedelta(seconds=PLUGIN_STALE_SECONDS)


class ShowPilotCoordinator(DataUpdateCoordinator[ShowPilotData]):
    """Fetches /api/state + /api/page-stats every poll, plugin details less often."""

    config_entry: ShowPilotConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ShowPilotConfigEntry, client: ShowPilotClient) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL
        )
        self.client = client
        self._polls = 0
        self._extras: dict[str, Any] = {}
        self._names: dict[str, tuple[str, str]] = {}  # sequence -> (display name, artist)
        self._seen_requests: set[tuple[str, str]] | None = None
        self._prev_playing: str | None = None
        self._prev_requests: int | None = None
        self._first = True

    def refresh_extras_soon(self) -> None:
        """Make the next poll re-read plugin details (after a control action)."""
        self._polls = 0

    def label(self, sequence: str | None) -> tuple[str | None, str]:
        if not sequence:
            return None, ""
        return self._names.get(sequence, (sequence, ""))

    async def _async_update_data(self) -> ShowPilotData:
        try:
            state = await self.client.state()
            stats = await self.client.page_stats()
            if self._polls % EXTRAS_EVERY == 0:
                await self._read_extras()
        except ShowPilotAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ShowPilotError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1

        for seq in state.get("sequences") or []:
            name = seq.get("name")
            if name:
                self._names[name] = (seq.get("display_name") or name, seq.get("artist") or "")
        playing = state.get("nowPlaying")
        if playing and state.get("nowPlayingDisplayName"):
            self._names[playing] = (state["nowPlayingDisplayName"], state.get("nowPlayingArtist") or "")

        data = ShowPilotData(state=state, stats=stats, **self._extras)
        self._fire_events(data)
        return data

    async def _read_extras(self) -> None:
        extras: dict[str, Any] = {}
        try:
            extras["version"] = (await self.client.health()).get("version")
        except ShowPilotError:
            extras["version"] = self._extras.get("version")
        if self.client.has_token:
            extras["plugin"] = (await self.client.plugin_health()).get("plugin") or {}
            extras["peek"] = await self.client.plugin_peek()
            extras["categories"] = await self.client.categories()
            extras["pages"] = await self.client.viewer_pages()
        self._extras = extras

    def _fire_events(self, data: ShowPilotData) -> None:
        state = data.state
        queue = state.get("queue") or []
        keys = {(q.get("sequence_name") or "", q.get("requested_at") or "") for q in queue}
        playing = state.get("nowPlaying")
        requests = data.tonight.get("requests")

        if self._first:
            self._first = False
            self._seen_requests = keys
            self._prev_playing = playing
            self._prev_requests = requests
            return

        prior_queue = {k[0] for k in self._seen_requests or set()}
        new_keys = sorted((k for k in keys if k not in (self._seen_requests or set())), key=lambda k: k[1])
        changed = bool(playing) and playing != self._prev_playing
        was_requested = changed and playing in prior_queue

        # A request that starts playing straight away never shows in the queue;
        # the server's request count still goes up, so attribute the extra
        # request to the song that just started.
        extra = 0
        if isinstance(requests, int) and isinstance(self._prev_requests, int) and requests > self._prev_requests:
            extra = requests - self._prev_requests - len(new_keys)
        if extra > 0 and changed and not was_requested:
            was_requested = True
            self._fire_request(playing, playing_now=True, position=0)

        for i, (seq, _) in enumerate(new_keys):
            position = next(
                (n + 1 for n, q in enumerate(queue) if (q.get("sequence_name"), q.get("requested_at")) == new_keys[i]),
                None,
            )
            self._fire_request(seq, playing_now=False, position=position)

        if changed:
            name, artist = self.label(playing)
            self.hass.bus.async_fire(
                EVENT_SONG_CHANGED,
                {
                    "entry_id": self.config_entry.entry_id,
                    "sequence": playing,
                    "name": name,
                    "artist": artist,
                    "previous": self._prev_playing,
                    "requested": was_requested,
                    "mode": state.get("viewerControlMode"),
                },
            )

        # Remember everything seen recently so a song that leaves and re-enters
        # the queue later (a new request for it) counts again: entries are keyed
        # by request time too.
        self._seen_requests = keys
        if playing:
            self._prev_playing = playing
        self._prev_requests = requests

    def _fire_request(self, sequence: str, *, playing_now: bool, position: int | None) -> None:
        name, artist = self.label(sequence)
        self.hass.bus.async_fire(
            EVENT_SONG_REQUESTED,
            {
                "entry_id": self.config_entry.entry_id,
                "sequence": sequence,
                "name": name,
                "artist": artist,
                "position": position,
                "playing_now": playing_now,
            },
        )
