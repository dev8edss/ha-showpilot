"""ShowPilot integration: now playing, requests, viewers and viewer control."""

from __future__ import annotations

from homeassistant.const import CONF_URL, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession

from .api import ShowPilotAdmin, ShowPilotClient
from .const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from .coordinator import ShowPilotConfigEntry, ShowPilotCoordinator
from .live import LiveFeed

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = ShowPilotClient(session, entry.data[CONF_URL], entry.data.get(CONF_TOKEN))
    coordinator = ShowPilotCoordinator(hass, entry, client)
    if entry.options.get(CONF_USERNAME) and entry.options.get(CONF_PASSWORD):
        # Its own session, so the admin cookie never mixes with anything else.
        coordinator.admin = ShowPilotAdmin(
            async_create_clientsession(hass), entry.data[CONF_URL],
            entry.options[CONF_USERNAME], entry.options[CONF_PASSWORD],
        )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _remove_other_mode_entities(hass, entry, client.has_token, coordinator.admin is not None)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    feed = LiveFeed(session, entry.data[CONF_URL], coordinator.live_event, coordinator.set_live)
    task = entry.async_create_background_task(hass, feed.run(), f"showpilot live feed {entry.title}")

    def _stop(*_args) -> None:
        feed.stop()
        task.cancel()
        coordinator.cancel_pending()

    entry.async_on_unload(_stop)
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


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
LOGIN_ONLY = {("sensor", "unread_messages")}


def _remove_other_mode_entities(
    hass: HomeAssistant, entry: ShowPilotConfigEntry, has_token: bool, has_login: bool
) -> None:
    """Drop entities left over from before the token or login was added or removed."""
    reg = er.async_get(hass)
    stale = set(WITHOUT_TOKEN_ONLY if has_token else TOKEN_ONLY)
    if not has_login:
        stale |= LOGIN_ONLY
    stale_ids = {(domain, f"{entry.entry_id}_{key}") for domain, key in stale}
    for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
        if (ent.domain, ent.unique_id) in stale_ids or (
            not has_token and ent.domain == "switch" and ent.unique_id.startswith(f"{entry.entry_id}_category_")
        ):
            reg.async_remove(ent.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ShowPilotConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
