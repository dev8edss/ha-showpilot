"""ShowPilot sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import MODES
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator, ShowPilotData
from .entity import ShowPilotEntity


def _song_ends(d: ShowPilotData) -> datetime | None:
    s = d.state
    start = dt_util.parse_datetime(s.get("nowPlayingStartedAtIso") or "")
    dur = s.get("nowPlayingDurationSeconds")
    if start is None or not dur:
        return None
    return start + timedelta(seconds=float(dur))


def _leading_vote(d: ShowPilotData) -> str | None:
    counts = d.state.get("voteCounts") or []
    if d.state.get("viewerControlMode") != "VOTING" or not counts:
        return None
    best = max(counts, key=lambda c: c.get("count", 0))
    return best.get("sequence_name")


@dataclass(frozen=True, kw_only=True)
class ShowPilotSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ShowPilotData], Any]
    needs_token: bool = False
    without_token_only: bool = False


SENSORS: tuple[ShowPilotSensorDescription, ...] = (
    ShowPilotSensorDescription(
        key="now_playing",
        translation_key="now_playing",
        value_fn=lambda d: d.state.get("nowPlayingDisplayName") or d.state.get("nowPlaying"),
    ),
    ShowPilotSensorDescription(
        key="next_song",
        translation_key="next_song",
        value_fn=lambda d: d.state.get("nextScheduledDisplayName") or d.state.get("nextScheduled"),
    ),
    ShowPilotSensorDescription(
        key="song_ends",
        translation_key="song_ends",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_song_ends,
    ),
    ShowPilotSensorDescription(
        key="queue",
        translation_key="queue",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="requests",
        value_fn=lambda d: len(d.state.get("queue") or []),
    ),
    ShowPilotSensorDescription(
        key="viewers",
        translation_key="viewers",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="viewers",
        value_fn=lambda d: d.state.get("activeViewers"),
    ),
    ShowPilotSensorDescription(
        key="leading_vote",
        translation_key="leading_vote",
        value_fn=_leading_vote,
    ),
    ShowPilotSensorDescription(
        key="requests_tonight",
        translation_key="requests_tonight",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="requests",
        value_fn=lambda d: d.tonight.get("requests"),
    ),
    ShowPilotSensorDescription(
        key="votes_tonight",
        translation_key="votes_tonight",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="votes",
        value_fn=lambda d: d.tonight.get("votes"),
    ),
    ShowPilotSensorDescription(
        key="visitors_tonight",
        translation_key="visitors_tonight",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="visitors",
        value_fn=lambda d: d.tonight.get("visitors"),
    ),
    ShowPilotSensorDescription(
        key="songs_tonight",
        translation_key="songs_tonight",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="songs",
        value_fn=lambda d: d.tonight.get("played"),
    ),
    # With a token, viewer mode is a select instead.
    ShowPilotSensorDescription(
        key="viewer_mode",
        translation_key="viewer_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(MODES.values()),
        without_token_only=True,
        value_fn=lambda d: MODES.get(d.state.get("viewerControlMode") or ""),
    ),
    ShowPilotSensorDescription(
        key="plugin_last_seen",
        translation_key="plugin_last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        needs_token=True,
        value_fn=lambda d: d.plugin_last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    token = coordinator.client.has_token
    async_add_entities(
        ShowPilotSensor(coordinator, desc)
        for desc in SENSORS
        if (token or not desc.needs_token) and not (token and desc.without_token_only)
    )


class ShowPilotSensor(ShowPilotEntity, SensorEntity):
    entity_description: ShowPilotSensorDescription

    def __init__(self, coordinator: ShowPilotCoordinator, desc: ShowPilotSensorDescription) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        if self.entity_description.key == "leading_vote":
            return self.coordinator.label(value)[0]
        return value

    @property
    def entity_picture(self) -> str | None:
        s = self.coordinator.data.state
        if self.entity_description.key == "now_playing":
            return self.coordinator.client.absolute(s.get("nowPlayingImageUrl"))
        if self.entity_description.key == "next_song":
            return self.coordinator.client.absolute(s.get("nextScheduledImageUrl"))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self.coordinator.data.state
        key = self.entity_description.key
        if key == "now_playing":
            return {
                "sequence": s.get("nowPlaying"),
                "artist": s.get("nowPlayingArtist") or None,
                "started": s.get("nowPlayingStartedAtIso"),
                "duration": s.get("nowPlayingDurationSeconds"),
            }
        if key == "next_song":
            return {"sequence": s.get("nextScheduled"), "artist": s.get("nextScheduledArtist") or None}
        if key == "queue":
            return {
                "requests": [self.coordinator.label(q.get("sequence_name"))[0] for q in s.get("queue") or []]
            }
        if key == "leading_vote":
            counts = sorted(s.get("voteCounts") or [], key=lambda c: -c.get("count", 0))
            return {
                "votes": {self.coordinator.label(c.get("sequence_name"))[0]: c.get("count") for c in counts}
            }
        return None
