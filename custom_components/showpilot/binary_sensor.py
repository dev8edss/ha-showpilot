"""ShowPilot binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator, ShowPilotData
from .entity import ShowPilotEntity


@dataclass(frozen=True, kw_only=True)
class ShowPilotBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[ShowPilotData], bool | None]
    needs_token: bool = False


BINARY_SENSORS: tuple[ShowPilotBinaryDescription, ...] = (
    ShowPilotBinaryDescription(
        key="playing",
        translation_key="playing",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: bool(d.state.get("nowPlaying")),
    ),
    ShowPilotBinaryDescription(
        key="requests_open",
        translation_key="requests_open",
        value_fn=lambda d: d.state.get("viewerControlMode") in ("VOTING", "JUKEBOX", "RACE"),
    ),
    ShowPilotBinaryDescription(
        key="location_check",
        translation_key="location_check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: bool(d.state.get("requiresLocation")),
    ),
    ShowPilotBinaryDescription(
        key="access_code",
        translation_key="access_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: bool(d.state.get("requiresLocationCode")),
    ),
    ShowPilotBinaryDescription(
        key="live_updates",
        translation_key="live_updates",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.live,
    ),
    ShowPilotBinaryDescription(
        key="plugin_connected",
        translation_key="plugin_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        needs_token=True,
        value_fn=lambda d: d.plugin_connected,
    ),
    ShowPilotBinaryDescription(
        key="interrupt_schedule",
        translation_key="interrupt_schedule",
        needs_token=True,
        value_fn=lambda d: None if d.peek is None else bool(d.peek.get("interruptSchedule")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ShowPilotBinarySensor(coordinator, desc)
        for desc in BINARY_SENSORS
        if coordinator.client.has_token or not desc.needs_token
    )


class ShowPilotBinarySensor(ShowPilotEntity, BinarySensorEntity):
    entity_description: ShowPilotBinaryDescription

    def __init__(self, coordinator: ShowPilotCoordinator, desc: ShowPilotBinaryDescription) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
