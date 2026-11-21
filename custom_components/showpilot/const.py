"""Constants for the ShowPilot integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "showpilot"

CONF_TOKEN = "token"

# /api/state is cheap (one local SQLite read); 5 s keeps "now playing" close
# to live without loading the server. Plugin-side details (connection,
# categories, viewer pages) change rarely and are read every EXTRAS_EVERY polls.
SCAN_INTERVAL = timedelta(seconds=5)
EXTRAS_EVERY = 6

# The FPP plugin sends a heartbeat every 15 s by default.
PLUGIN_STALE_SECONDS = 90

# Server mode value -> option key used by the select / enum sensor.
MODES = {
    "VOTING": "voting",
    "JUKEBOX": "jukebox",
    "RACE": "race",
    "LISTEN": "listen",
    "OFF": "off",
}
MODE_TO_SERVER = {v: k for k, v in MODES.items()}

EVENT_SONG_CHANGED = f"{DOMAIN}_song_changed"
EVENT_SONG_REQUESTED = f"{DOMAIN}_song_requested"
