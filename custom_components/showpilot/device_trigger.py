"""Device triggers: pick "Song requested" etc. in the automation editor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_USERNAME,
    DOMAIN,
    EVENT_SONG_CHANGED,
    EVENT_SONG_REQUESTED,
    EVENT_VISITOR_MESSAGE,
)

# type -> (event, extra event_data to match)
TRIGGERS: dict[str, tuple[str, dict[str, Any]]] = {
    "song_requested": (EVENT_SONG_REQUESTED, {}),
    "song_started": (EVENT_SONG_CHANGED, {}),
    "request_started": (EVENT_SONG_CHANGED, {"requested": True}),
    "visitor_message": (EVENT_VISITOR_MESSAGE, {}),
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(TRIGGERS)})


def _entry_id(hass: HomeAssistant, device_id: str) -> str | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    return next((ident for dom, ident in device.identifiers if dom == DOMAIN), None)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    entry_id = _entry_id(hass, device_id)
    if entry_id is None:
        return []
    entry = hass.config_entries.async_get_entry(entry_id)
    has_login = bool(entry and entry.options.get(CONF_USERNAME))
    return [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: kind}
        for kind in TRIGGERS
        if kind != "visitor_message" or has_login
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    event_type, extra = TRIGGERS[config[CONF_TYPE]]
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: {"entry_id": _entry_id(hass, config[CONF_DEVICE_ID]), **extra},
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
