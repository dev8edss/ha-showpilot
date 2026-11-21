"""Clear Queue button (needs the show token)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ShowPilotError
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator
from .entity import ShowPilotEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.client.has_token:
        async_add_entities([ClearQueueButton(coordinator)])


class ClearQueueButton(ShowPilotEntity, ButtonEntity):
    _attr_translation_key = "clear_queue"

    def __init__(self, coordinator: ShowPilotCoordinator) -> None:
        super().__init__(coordinator, "clear_queue")

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.clear_queue()
        except ShowPilotError as err:
            raise HomeAssistantError(f"ShowPilot couldn't clear the queue: {err}") from err
        await self.coordinator.async_refresh()
