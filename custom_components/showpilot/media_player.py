"""Now playing as a media player (read-only: FPP runs the show, not ShowPilot)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator
from .entity import ShowPilotEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ShowPilotPlayer(entry.runtime_data)])


class ShowPilotPlayer(ShowPilotEntity, MediaPlayerEntity):
    _attr_name = None  # the device's own name
    _attr_media_content_type = MediaType.MUSIC
    _attr_media_image_remotely_accessible = False  # HA fetches the cover from the LAN
    _attr_app_name = "ShowPilot"

    def __init__(self, coordinator: ShowPilotCoordinator) -> None:
        super().__init__(coordinator, "media_player")

    @property
    def _s(self) -> dict:
        return self.coordinator.data.state

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.PLAYING if self._s.get("nowPlaying") else MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        return self._s.get("nowPlayingDisplayName") or self._s.get("nowPlaying")

    @property
    def media_artist(self) -> str | None:
        return self._s.get("nowPlayingArtist") or None

    @property
    def media_content_id(self) -> str | None:
        return self._s.get("nowPlaying")

    @property
    def media_image_url(self) -> str | None:
        return self.coordinator.client.absolute(self._s.get("nowPlayingImageUrl"))

    @property
    def media_duration(self) -> int | None:
        dur = self._s.get("nowPlayingDurationSeconds")
        return int(dur) if dur else None

    @property
    def _started(self) -> datetime | None:
        return dt_util.parse_datetime(self._s.get("nowPlayingStartedAtIso") or "")

    # Position is "0 at the moment the song started"; HA's frontend adds the
    # time since then itself, so the progress bar moves without updates.
    @property
    def media_position(self) -> int | None:
        return 0 if self._started and self._s.get("nowPlaying") else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        return self._started if self._s.get("nowPlaying") else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "viewer_mode": (self._s.get("viewerControlMode") or "").lower() or None,
            "next_song": self._s.get("nextScheduledDisplayName") or self._s.get("nextScheduled"),
        }
