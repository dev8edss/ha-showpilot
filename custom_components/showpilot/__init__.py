"""ShowPilot integration: now playing, requests, viewers and viewer control."""

from __future__ import annotations

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShowPilotClient
from .const import CONF_TOKEN
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> bool:
    client = ShowPilotClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN)
    )
    coordinator = ShowPilotCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
