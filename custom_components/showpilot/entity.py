"""Base entity for ShowPilot."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShowPilotCoordinator


class ShowPilotEntity(CoordinatorEntity[ShowPilotCoordinator]):
    """One device per ShowPilot server."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ShowPilotCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        data = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=(data.state.get("showName") if data else None) or entry.title,
            manufacturer="ShowPilot",
            model="ShowPilot server",
            sw_version=data.version if data else None,
            configuration_url=f"{coordinator.client.url}/admin",
        )
