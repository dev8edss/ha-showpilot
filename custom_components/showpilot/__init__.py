"""ShowPilot integration: now playing, requests, viewers and viewer control."""

from __future__ import annotations

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    _remove_other_mode_entities(hass, entry, client.has_token)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


# Entities that exist only with a token, and the one that exists only without.
TOKEN_ONLY = {
    ("binary_sensor", "plugin_connected"),
    ("binary_sensor", "interrupt_schedule"),
    ("sensor", "plugin_last_seen"),
    ("select", "viewer_mode"),
    ("select", "viewer_page"),
    ("button", "clear_queue"),
}
WITHOUT_TOKEN_ONLY = {("sensor", "viewer_mode")}


def _remove_other_mode_entities(hass: HomeAssistant, entry: ShowPilotConfigEntry, has_token: bool) -> None:
    """Drop entities left over from before the token was added or removed."""
    reg = er.async_get(hass)
    stale = WITHOUT_TOKEN_ONLY if has_token else TOKEN_ONLY
    stale_ids = {(domain, f"{entry.entry_id}_{key}") for domain, key in stale}
    for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
        if (ent.domain, ent.unique_id) in stale_ids or (
            not has_token and ent.domain == "switch" and ent.unique_id.startswith(f"{entry.entry_id}_category_")
        ):
            reg.async_remove(ent.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
