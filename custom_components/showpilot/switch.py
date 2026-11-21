"""One switch per ShowPilot category (needs the show token)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from .api import ShowPilotError
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator
from .entity import ShowPilotEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if not coordinator.client.has_token:
        return
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [c["name"] for c in coordinator.data.categories if c.get("name") and c["name"] not in known]
        if new:
            known.update(new)
            async_add_entities(CategorySwitch(coordinator, name) for name in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class CategorySwitch(ShowPilotEntity, SwitchEntity):
    _attr_translation_key = "category"
    _attr_icon = "mdi:playlist-music"

    def __init__(self, coordinator: ShowPilotCoordinator, name: str) -> None:
        super().__init__(coordinator, f"category_{slugify(name)}")
        self._category = name
        self._attr_translation_placeholders = {"category": name}

    def _row(self) -> dict[str, Any] | None:
        return next(
            (c for c in self.coordinator.data.categories if c.get("name") == self._category), None
        )

    @property
    def available(self) -> bool:
        return super().available and self._row() is not None

    @property
    def is_on(self) -> bool | None:
        row = self._row()
        return None if row is None else bool(row.get("enabled"))

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.set_category(self._category, enabled)
        except ShowPilotError as err:
            raise HomeAssistantError(f"ShowPilot couldn't switch {self._category}: {err}") from err
        self.coordinator.refresh_extras_soon()
        await self.coordinator.async_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
