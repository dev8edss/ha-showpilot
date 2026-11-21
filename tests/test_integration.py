"""End-to-end tests against the fake server (real /api/state snapshot)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.showpilot.const import CONF_TOKEN, DOMAIN, EVENT_SONG_CHANGED, EVENT_SONG_REQUESTED

from .conftest import URL

P = "test_show"


async def _setup(hass: HomeAssistant, token: str | None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Test Show", unique_id=URL, data={CONF_URL: URL, CONF_TOKEN: token})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


# ---------------- config flow ----------------

async def test_flow_read_only(hass, server):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: "showpilot.test:3100/"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "Test Show"
    assert r["data"] == {CONF_URL: URL, CONF_TOKEN: None}


async def test_flow_bad_token_then_good(hass, server):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: URL, CONF_TOKEN: "nope"})
    assert r["type"] is FlowResultType.FORM
    assert r["errors"] == {CONF_TOKEN: "invalid_auth"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: URL, CONF_TOKEN: "good-token"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"][CONF_TOKEN] == "good-token"


async def test_flow_cannot_connect(hass, server):
    server.down = True
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_URL: URL})
    assert r["errors"] == {"base": "cannot_connect"}


# ---------------- entities ----------------

async def test_read_only_entities(hass, server):
    server.play(0)
    server.state["activeViewers"] = 3
    await _setup(hass, None)
    s = hass.states.get(f"sensor.{P}_now_playing")
    assert s.state == "Abracadabra"
    assert s.attributes["artist"] == "Lady Gaga"
    assert s.attributes["entity_picture"].startswith(f"{URL}/covers/40.jpg")
    assert hass.states.get(f"sensor.{P}_viewers").state == "3"
    assert hass.states.get(f"sensor.{P}_viewer_mode").state == "off"
    assert hass.states.get(f"sensor.{P}_song_ends").state == "2026-11-21T11:03:49+00:00"
    assert hass.states.get(f"binary_sensor.{P}_location_check").state == "on"
    assert hass.states.get(f"binary_sensor.{P}_playing").state == "on"
    # Controls need the token.
    assert hass.states.get(f"select.{P}_viewer_mode") is None
    assert hass.states.get(f"button.{P}_clear_queue") is None
    assert hass.states.get(f"binary_sensor.{P}_fpp_connected") is None
    # Plugin endpoints never called without a token.
    assert not any("/api/plugin" in str(c[1]) for c in server.mock.mock_calls)


async def test_controls_with_token(hass, server):
    entry = await _setup(hass, "good-token")
    assert hass.states.get(f"sensor.{P}_viewer_mode") is None
    mode = hass.states.get(f"select.{P}_viewer_mode")
    assert mode.state == "off"
    assert mode.attributes["options"] == ["voting", "jukebox", "race", "listen", "off"]
    d = entry.runtime_data.data
    assert hass.states.get(f"binary_sensor.{P}_fpp_connected").state == "on", (d.plugin, d.plugin_last_seen, server.posts)
    assert hass.states.get(f"binary_sensor.{P}_interrupt_schedule").state == "on"

    await hass.services.async_call("select", "select_option", {"entity_id": f"select.{P}_viewer_mode", "option": "jukebox"}, blocking=True)
    await hass.async_block_till_done()
    assert ("/api/plugin/viewer-mode", {"mode": "JUKEBOX"}) in server.posts
    assert hass.states.get(f"select.{P}_viewer_mode").state == "jukebox"
    assert hass.states.get(f"binary_sensor.{P}_viewer_control").state == "on"

    assert hass.states.get(f"switch.{P}_category_kids").state == "on"
    assert hass.states.get(f"switch.{P}_category_classics").state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": f"switch.{P}_category_classics"}, blocking=True)
    await hass.async_block_till_done()
    assert ("/api/plugin/category", {"name": "Classics", "enabled": True}) in server.posts
    assert hass.states.get(f"switch.{P}_category_classics").state == "on"

    await hass.services.async_call("select", "select_option", {"entity_id": f"select.{P}_viewer_page", "option": "Off season"}, blocking=True)
    assert ("/api/plugin/viewer-page", {"name": "Off season"}) in server.posts

    server.request(1, "2026-11-21 11:00:01")
    await _poll(hass, entry)
    assert hass.states.get(f"sensor.{P}_queue").state == "1"
    await hass.services.async_call("button", "press", {"entity_id": f"button.{P}_clear_queue"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{P}_queue").state == "0"

    # A new category appears without a reload.
    server.categories.append({"name": "Hits", "enabled": 1})
    entry.runtime_data.refresh_extras_soon()
    await _poll(hass, entry)
    assert hass.states.get(f"switch.{P}_category_hits").state == "on"


async def test_fpp_stale(hass, server):
    server.last_seen = "2026-11-01T00:00:00+00:00"
    await _setup(hass, "good-token")
    assert hass.states.get(f"binary_sensor.{P}_fpp_connected").state == "off"


async def test_never_takes_a_request_from_fpp(hass, server):
    entry = await _setup(hass, "good-token")
    for _ in range(8):
        await _poll(hass, entry)
    plugin_state = [str(c[1]) for c in server.mock.mock_calls if "/api/plugin/state" in str(c[1])]
    assert plugin_state and all("peek=1" in u for u in plugin_state)


# ---------------- events ----------------

async def test_events(hass, server):
    server.play(0)
    entry = await _setup(hass, None)
    requested = async_capture_events(hass, EVENT_SONG_REQUESTED)
    changed = async_capture_events(hass, EVENT_SONG_CHANGED)

    # Two requests queue up behind the current song.
    server.request(1, "2026-11-21 11:00:01")
    server.request(2, "2026-11-21 11:00:02")
    await _poll(hass, entry)
    assert [e.data["sequence"] for e in requested] == [server.song(1)["name"], server.song(2)["name"]]
    assert [e.data["position"] for e in requested] == [1, 2]
    assert requested[0].data["name"] == "Anti-Hero"
    assert not changed

    # Nothing new: no repeat events.
    await _poll(hass, entry)
    assert len(requested) == 2

    # The first request starts.
    server.play(1)
    await _poll(hass, entry)
    assert len(changed) == 1 and changed[0].data["requested"] is True
    assert changed[0].data["previous"] == server.song(0)["name"]

    # A scheduled song (not requested).
    server.state["queue"] = []
    server.play(5)
    await _poll(hass, entry)
    assert changed[-1].data["requested"] is False

    # A request that starts straight away never shows in the queue.
    server.stats["tonight"]["requests"] += 1
    server.play(7)
    await _poll(hass, entry)
    assert requested[-1].data == {**requested[-1].data, "sequence": server.song(7)["name"], "playing_now": True}
    assert changed[-1].data["requested"] is True

    # Same song requested again later counts again.
    server.request(1, "2026-11-21 11:30:00")
    await _poll(hass, entry)
    assert requested[-1].data["sequence"] == server.song(1)["name"]
    assert len(requested) == 4


# ---------------- failures ----------------

async def test_unavailable_then_back(hass, server):
    entry = await _setup(hass, None)
    server.down = True
    await _poll(hass, entry)
    assert hass.states.get(f"sensor.{P}_now_playing").state == "unavailable"
    server.down = False
    await _poll(hass, entry)
    assert hass.states.get(f"sensor.{P}_now_playing").state != "unavailable"


async def test_token_revoked_starts_reauth(hass, server):
    entry = await _setup(hass, "good-token")
    server.token = "rotated"
    entry.runtime_data.refresh_extras_soon()
    await _poll(hass, entry)
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)
