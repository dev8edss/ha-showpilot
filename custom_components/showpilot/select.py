"""Viewer mode and viewer page selects (need the show token)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ShowPilotError
from .const import MODE_TO_SERVER, MODES
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator
from .entity import ShowPilotEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.client.has_token:
        async_add_entities([ViewerModeSelect(coordinator), ViewerPageSelect(coordinator)])


class ViewerModeSelect(ShowPilotEntity, SelectEntity):
    _attr_translation_key = "viewer_mode"
    _attr_options = list(MODES.values())

    def __init__(self, coordinator: ShowPilotCoordinator) -> None:
        super().__init__(coordinator, "viewer_mode")

    @property
    def current_option(self) -> str | None:
        return MODES.get(self.coordinator.data.state.get("viewerControlMode") or "")

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.set_mode(MODE_TO_SERVER[option])
        except ShowPilotError as err:
            raise HomeAssistantError(f"ShowPilot refused the mode change: {err}") from err
        await self.coordinator.async_refresh()


class ViewerPageSelect(ShowPilotEntity, SelectEntity):
    _attr_translation_key = "viewer_page"

    def __init__(self, coordinator: ShowPilotCoordinator) -> None:
        super().__init__(coordinator, "viewer_page")

    @property
    def options(self) -> list[str]:
        return [p["name"] for p in self.coordinator.data.pages]

    @property
    def current_option(self) -> str | None:
        return next((p["name"] for p in self.coordinator.data.pages if p.get("active")), None)

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.set_viewer_page(option)
        except ShowPilotError as err:
            raise HomeAssistantError(f"ShowPilot couldn't switch the viewer page: {err}") from err
        self.coordinator.refresh_extras_soon()
        await self.coordinator.async_refresh()
