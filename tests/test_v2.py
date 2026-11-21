"""Live updates, media player, device triggers and visitor messages."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_get_device_automations,
)

from custom_components.showpilot.const import (
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    DOMAIN,
    EVENT_VISITOR_MESSAGE,
    LIVE_SCAN_INTERVAL,
    SCAN_INTERVAL,
)
from custom_components.showpilot.live import event_payload, parse_packet, socket_url

from .conftest import URL

P = "test_show"


async def _setup(hass, token=None, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Test Show", unique_id=URL,
                            data={CONF_URL: URL, CONF_TOKEN: token}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass, entry) -> None:
    entry.runtime_data.refresh_extras_soon()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


# ---------------- socket.io protocol ----------------

def test_protocol_helpers():
    assert socket_url("http://10.0.0.241:3100") == "ws://10.0.0.241:3100/socket.io/?EIO=4&transport=websocket"
    assert socket_url("https://show.example/sp/") == "wss://show.example/sp/socket.io/?EIO=4&transport=websocket"
    assert parse_packet("2") == ("ping", None)
    assert parse_packet('0{"sid":"x","pingInterval":5000}') == ("open", None)
    assert parse_packet('40{"sid":"y"}') == ("connect", None)
    assert parse_packet('42["queueUpdated"]') == ("event", "queueUpdated")
    assert parse_packet('42["nowPlaying",{"sequenceName":"A"}]') == ("event", "nowPlaying")
    assert parse_packet('4212["voteUpdate",{}]') == ("event", "voteUpdate")
    assert parse_packet("42not json") == ("other", None)
    assert event_payload('42["viewerCount",{"count":3}]') == {"count": 3}
    assert event_payload('42["queueUpdated"]') is None


# ---------------- live updates ----------------

async def test_live_push_refreshes_and_slows_polling(hass, server, fake_feed):
    entry = await _setup(hass)
    coord = entry.runtime_data
    feed = fake_feed.instances[-1]
    assert feed.url == URL
    assert coord.update_interval == SCAN_INTERVAL
    assert hass.states.get(f"binary_sensor.{P}_live_updates").state == "off"

    feed.on_status(True)
    await hass.async_block_till_done()
    assert coord.update_interval == LIVE_SCAN_INTERVAL
    assert hass.states.get(f"binary_sensor.{P}_live_updates").state == "on"

    # A push (a burst of three) leads to one refresh shortly after.
    server.request(1, "2026-11-21 11:00:01")
    calls_before = len(server.mock.mock_calls)
    for name in ("queueUpdated", "queueUpdated", "nowPlaying"):
        feed.on_event(name)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    state_calls = [c for c in server.mock.mock_calls[calls_before:] if str(c[1]).endswith("/api/state")]
    assert len(state_calls) == 1
    assert hass.states.get(f"sensor.{P}_queue").state == "1"

    feed.on_status(False)
    await hass.async_block_till_done()
    assert coord.update_interval == SCAN_INTERVAL

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert feed.stopped


# ---------------- media player ----------------

async def test_media_player(hass, server):
    await _setup(hass)
    mp = hass.states.get(f"media_player.{P}")
    assert mp.state == "idle"
    server.play(0)
    server.state["nextScheduledDisplayName"] = "APT"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await _poll(hass, entry)
    mp = hass.states.get(f"media_player.{P}")
    assert mp.state == "playing"
    assert mp.attributes["media_title"] == "Abracadabra"
    assert mp.attributes["media_artist"] == "Lady Gaga"
    assert mp.attributes["media_duration"] == 229
    assert mp.attributes["media_position"] == 0
    assert mp.attributes["media_position_updated_at"].isoformat() == "2026-11-21T11:00:00+00:00"
    assert mp.attributes["next_song"] == "APT"
    assert mp.attributes["entity_picture"].startswith("/api/media_player_proxy/")
    assert mp.attributes["supported_features"] == 0


# ---------------- device triggers ----------------

async def test_device_triggers(hass, server):
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    kinds = {t["type"] for t in triggers if t["domain"] == DOMAIN}
    assert kinds == {"song_requested", "song_started", "request_started"}  # no login: no messages

    assert await async_setup_component(hass, automation.DOMAIN, {automation.DOMAIN: [
        {"alias": "req", "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "song_requested"}],
         "actions": [{"event": "fired_req", "event_data": {"name": "{{ trigger.event.data.name }}"}}]},
        {"alias": "reqstart", "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "request_started"}],
         "actions": [{"event": "fired_reqstart"}]},
        {"alias": "start", "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "song_started"}],
         "actions": [{"event": "fired_start"}]},
    ]})
    req = async_capture_events(hass, "fired_req")
    reqstart = async_capture_events(hass, "fired_reqstart")
    start = async_capture_events(hass, "fired_start")

    server.request(1, "2026-11-21 11:00:01")
    await _poll(hass, entry)
    assert [e.data["name"] for e in req] == ["Anti-Hero"]

    server.play(1)  # the request starts
    await _poll(hass, entry)
    assert len(start) == 1 and len(reqstart) == 1

    server.play(5)  # a scheduled song
    await _poll(hass, entry)
    assert len(start) == 2 and len(reqstart) == 1

    # Another ShowPilot's events don't fire this device's triggers.
    hass.bus.async_fire("showpilot_song_requested", {"entry_id": "other", "name": "x"})
    await hass.async_block_till_done()
    assert len(req) == 1


# ---------------- visitor messages ----------------

async def test_options_login_flow(hass, server):
    entry = await _setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.FORM
    r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_USERNAME: "ha", CONF_PASSWORD: "wrong"})
    assert r["errors"] == {"base": "invalid_login"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_USERNAME: "ha", CONF_PASSWORD: "secret"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_USERNAME: "ha", CONF_PASSWORD: "secret"}
    # The reload added the messages sensor.
    assert hass.states.get(f"sensor.{P}_unread_messages").state == "0"

    # Saving again with an empty password keeps the saved one.
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_USERNAME: "ha"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PASSWORD] == "secret"

    # Clearing the user name removes the login and its sensor.
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {CONF_USERNAME: ""})
    await hass.async_block_till_done()
    assert entry.options == {}
    assert hass.states.get(f"sensor.{P}_unread_messages") is None


async def test_visitor_messages(hass, server):
    entry = await _setup(hass, options={CONF_USERNAME: "ha", CONF_PASSWORD: "secret"})
    events = async_capture_events(hass, EVENT_VISITOR_MESSAGE)
    assert hass.states.get(f"sensor.{P}_unread_messages").state == "0"
    assert not events  # the old message isn't replayed

    server.add_message("Sam", "Love the show!", allow_public=True)
    server.add_message(None, "Play Golden please")
    await _poll(hass, entry)
    assert [e.data["message"] for e in events] == ["Love the show!", "Play Golden please"]
    assert events[0].data["name"] == "Sam" and events[0].data["wants_on_wall"] is True
    assert events[1].data["name"] is None
    s = hass.states.get(f"sensor.{P}_unread_messages")
    assert s.state == "2"
    assert s.attributes["latest_message"] == "Play Golden please"

    # No repeats.
    await _poll(hass, entry)
    assert len(events) == 2

    # Session expired on the server: logs in again by itself.
    logins = server.logins
    server.admin_session = "sess-2"
    server.add_message("Kim", "Again")
    await _poll(hass, entry)
    assert server.logins == logins + 1
    assert events[-1].data["message"] == "Again"

    # Message triggers are offered once a login is set.
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    assert "visitor_message" in {t["type"] for t in triggers if t["domain"] == DOMAIN}


async def test_bad_login_doesnt_break_the_rest(hass, server):
    server.admin_user = ("ha", "changed")
    entry = await _setup(hass, options={CONF_USERNAME: "ha", CONF_PASSWORD: "secret"})
    assert entry.state.name == "LOADED"
    assert hass.states.get(f"sensor.{P}_now_playing") is not None
    assert hass.states.get(f"sensor.{P}_unread_messages").state == "unknown"
