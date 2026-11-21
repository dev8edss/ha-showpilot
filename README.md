# ShowPilot for Home Assistant

Connects a [ShowPilot](https://github.com/ShowPilotFPP/ShowPilot) server to Home Assistant: what's playing, the request queue, viewers on the page and tonight's numbers, plus viewer control (mode, categories, viewer page, clear queue). Use it for automations like a notification when someone requests a song, or switching to Listen Only when the porch camera sees nobody.

This is for the ShowPilot **server** (the one FPP's ShowPilot plugin talks to). For ShowPilot Player, use [ha-showpilot-player](https://github.com/ShowPilotFPP/ha-showpilot-player).

## Install

Copy `custom_components/showpilot` into your Home Assistant `config/custom_components/` folder and restart Home Assistant. Or add this repository to HACS as a custom repository (type **Integration**).

## Setup

**Settings → Devices & services → Add integration → ShowPilot**

- **Server address:** e.g. `http://192.168.1.20:3100`
- **Show token (optional):** from ShowPilot admin → **Plugin** → **Show Token**. Without it you get the read-only entities. With it you also get the controls and FPP's connection status.

**Visitor messages (optional):** ShowPilot only lets its admin login read messages, so to get them in Home Assistant open the integration's **Configure** and enter a ShowPilot user name and password. A separate ShowPilot user just for Home Assistant is best. Leave the user name empty to remove it.

The token is the same one the FPP plugin uses. Anyone with it can control your show, so treat it like a password. If it changes, Home Assistant asks for the new one. **Reconfigure** on the integration changes the address or token in place.

## Entities

| Entity | Token | What it shows / does |
|---|---|---|
| Media player | | Now playing as a media card: title, artist, cover art and a moving progress bar (read-only) |
| Now playing | | Song name with cover art; artist, sequence, start time and length as attributes |
| Next song | | What's scheduled next |
| Song ends | | When the current song finishes |
| Queue | | Requests waiting; their names as an attribute |
| Viewers | | People on the viewer page now |
| Leading vote | | In Voting mode, the song ahead; all counts as an attribute |
| Requests / Votes / Visitors / Songs played tonight | | ShowPilot's "tonight" numbers |
| Playing | | On while a song plays |
| Viewer control | | On in Voting, Jukebox or Race (off in Listen Only and Off) |
| Location check, Access code | | Whether viewers must pass the GPS check or enter a code (diagnostic) |
| Viewer mode | sensor without, select with | Voting / Jukebox / Race / Listen only / Off |
| Viewer page | ✓ | Pick which viewer page is live |
| Category *name* | ✓ | One switch per category, same as the toggle in admin; new categories appear by themselves |
| Clear queue | ✓ | Empties the request queue (played history is kept) |
| FPP connected, FPP last seen | ✓ | Whether the FPP plugin's heartbeat is recent (within 90 s) |
| Interrupt schedule | ✓ | ShowPilot's Interrupt Schedule setting |
| Unread messages | login | Unread visitor messages; the newest one as attributes |
| Live updates | | Whether ShowPilot's live feed is connected (diagnostic) |

**Live updates:** the integration listens to ShowPilot's live feed (the one the viewer page uses), so a request, song change or mode change shows up within a moment. While the feed is connected it also checks every 30 seconds; if the feed drops it checks every 5 seconds until it's back. It never takes a request away from FPP: it only uses the plugin API's read-only `peek` mode, and it never counts as a viewer.

## Events

- `showpilot_song_requested`: someone requested a song. Data: `sequence`, `name`, `artist`, `position` (place in the queue), `playing_now` (true when it started straight away).
- `showpilot_song_changed`: a new song started. Data: `sequence`, `name`, `artist`, `previous`, `requested` (true if it was a viewer request), `mode`.
- `showpilot_visitor_message` (needs the login): a visitor sent a message. Data: `name` (if they gave one), `message`, `filtered` (the word filter masked something), `wants_on_wall`, `created`.

The same are in the automation editor as device triggers: **When → Device → your show → Song requested / Song started / Requested song started / Visitor message received**.

```yaml
automation:
  - alias: Tell me about requests
    triggers:
      - trigger: event
        event_type: showpilot_song_requested
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Request: {{ trigger.event.data.name }} ({{ trigger.event.data.artist }})"
```
