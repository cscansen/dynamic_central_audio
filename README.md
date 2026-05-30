# Dynamic Central Audio

A Home Assistant custom integration for **find-me / follow-me** whole-house audio.

Automatically activates and deactivates multi-zone audio systems based on occupancy,
active playback source, and configurable rules — replacing manual automations with
a single, structured integration.

## Features

- **Multi-system support** — configure any number of audio controllers; zones are fully isolated per system
- **Generic media player interface** — works with HTD, Russound, receivers, or any HA media player
- **Dynamic source discovery** — reads `source_list` from a zone entity at setup time to populate input dropdowns
- **Per-source follow-me switch** — enable/disable individual sources from the HA UI without editing config
- **Per-zone follow-me switch** — pull a room out of the rotation instantly without touching config
- **Multi-device ATV exclusions** — one or more local streaming devices can override whole-house follow per zone, with configurable restore conditions and delay
- **Restore delay for all conditions** — configurable delay before a zone re-follows after a device stops
- **Amp switch support** — toggle an external amp when a local device takes over
- **Volume management** — per-source base volume + per-zone offset slider (persists across restarts)
- **Reasoning attribute** — every status sensor exposes a `reasoning` attribute explaining the full decision
- **Dashboard script** — `create_dashboard.py` auto-discovers your systems and zones and pushes a Lovelace dashboard

## Installation (HACS)

1. Add this repository as a custom HACS repository (Integration type)
2. Install **Dynamic Central Audio**
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Dynamic Central Audio**

## Setup

### 1. Add an Audio System

- **System name** — display name (e.g. "Whole House HTD")
- **Any zone media player** — pick any zone from your system; its `source_list` is used to discover available inputs (optional — leave blank if your system has no HA-exposed zone player)
- **Source-off delay** — seconds to wait before deactivating zones after playback stops (default 300s)

### 2. Add Sources

For each follow-me source:
- **Display name** — how it appears in HA (e.g. "AirPlay")
- **Input name** — the string passed to `media_player.select_source` (e.g. "AirPlay")
- **Watcher entity** — the HA entity to watch for active playback
- **Active state** — the state that means "playing" (default: `playing`)
- **Base volume** — volume applied when this source is active (0.0–1.0)
- **Priority** — lower number wins when multiple sources are active simultaneously

Each source gets a `switch.<system>_<source>_follow_me` entity created automatically.
Toggle it off to stop that source from triggering whole-house follow without removing the source config.

### 3. Add Zones

For each room:
- **Zone name** — display name (e.g. "Main Floor")
- **Audio system** — which system this zone belongs to
- **Media player entity** — the zone's media_player (receives `turn_on`, `select_source`, `volume_set`)
- **Occupancy sensors** — one or more binary_sensors; zone activates when any is `on` (leave blank = always occupied)
- **Off delay** — seconds to wait after room empties before turning off (default 600s)
- **ATV exclusions** — optional: one or more local streaming devices that override whole-house follow

## Entities

### Per system
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<system>_active` | Master on/off — disables all zones when off |
| `switch.dynamic_central_audio_<system>_<source>_follow_me` | Per-source follow-me toggle (one per configured source) |
| `sensor.dynamic_central_audio_<system>_status` | Active source name; `reasoning` attribute shows full decision |

### Per zone
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<zone>_follow_me` | Enable/disable follow-me for this zone |
| `sensor.dynamic_central_audio_<zone>_status` | Zone state; `reasoning` attribute explains why |
| `number.dynamic_central_audio_<zone>_volume_offset` | Fine-tune zone volume (−0.30 to +0.30, persists across restarts) |

## ATV Exclusion Restore Conditions

| Condition | Behavior |
|-----------|----------|
| `any_stopped` | Restore as soon as any device in this rule stops |
| `all_stopped` | Restore only when ALL devices in this rule have stopped |
| `occupied` | Restore after `restore_delay_seconds` only if zone is still occupied |

A `restore_delay_seconds` value > 0 applies a delay before re-following regardless of condition.
If a device resumes playing during the delay, the pending restore is cancelled automatically.

## Dashboard

After the integration is configured, run:

```bash
source ~/.secrets && python3 create_dashboard.py
```

This auto-discovers your systems and zones from HA entity states and pushes a Lovelace
dashboard to `/dashboard-audio` with per-zone reasoning cards, follow-me toggles, and
volume offset sliders.

## Notes

- Zones are fully isolated per system entry — an alt/room-specific system with no HA-exposed source stays idle and does not interact with other systems
- `select_source` is only called if the input name appears in the zone entity's `source_list`
- Volume offset is applied on top of the source's base volume and clamped to [0.0, 1.0]
- Follow-me switch states and volume offsets persist across HA restarts (RestoreEntity)
