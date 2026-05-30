# Dynamic Central Audio

A Home Assistant custom integration for **find-me / follow-me** whole-house audio.

Automatically activates and deactivates multi-zone audio systems based on occupancy,
active playback source, and configurable rules — replacing manual automations with
a single, structured integration.

## Features

- **Multi-system support** — configure any number of audio controllers
- **Generic media player interface** — works with HTD, Russound, receivers, or any HA media player
- **Dynamic source discovery** — reads `source_list` from your zone entities at setup time
- **Per-zone follow-me switch** — disable individual zones without touching others
- **ATV exclusion rules** — local Apple TV / streaming device overrides whole-house follow with configurable restore conditions
- **Amp switch support** — toggle an external amp when a zone is activated by a local device
- **Volume management** — per-source base volume + per-zone offset slider
- **Graceful delays** — configurable off delays for occupancy and source-stop events

## Installation (HACS)

1. Add this repository as a custom HACS repository (Integration type)
2. Install **Dynamic Central Audio**
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Dynamic Central Audio**

## Setup

### 1. Add an Audio System

Configure your audio controller:
- **System name** — display name (e.g. "Whole House HTD")
- **Reference zone entity** — any media_player from your system (used to discover available inputs)
- **Source-off delay** — seconds to wait before deactivating zones after playback stops (default 300s)

### 2. Add Sources

For each follow-me source:
- **Display name** — how it appears in HA (e.g. "AirPlay")
- **Input name** — the string passed to `media_player.select_source` (e.g. "AirPlay")
- **Watcher entity** — the HA entity to watch for active playback
- **Active state** — the state that means "playing" (default: `playing`)
- **Base volume** — volume applied when this source is active (0.0–1.0)
- **Gate entity / state** — optional second condition (e.g. a follow-me toggle input_boolean)
- **Priority** — lower number wins when multiple sources are active simultaneously

### 3. Add Zones

For each room:
- **Zone name** — display name (e.g. "Main Floor")
- **Audio system** — which system this zone belongs to
- **Media player entity** — the zone's media_player
- **Occupancy sensors** — one or more binary_sensors; zone activates when any is `on`
- **Off delay** — seconds to wait after room empties before turning off (default 600s)
- **ATV exclusions** — optional: local streaming devices that override whole-house follow

## Entities

### Per system
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<system>_active` | Master on/off |
| `sensor.dynamic_central_audio_<system>_status` | Current routing mode and active source |

### Per zone
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<zone>_follow_me` | Enable/disable follow-me for this zone |
| `sensor.dynamic_central_audio_<zone>_status` | Zone state (following, standby, atv_override, idle) |
| `number.dynamic_central_audio_<zone>_volume_offset` | Fine-tune zone volume (-0.30 to +0.30) |

## ATV Exclusion Restore Conditions

| Condition | Behavior |
|-----------|---------|
| `any_stopped` | Restore as soon as this ATV is no longer playing |
| `all_stopped` | Restore only when ALL configured ATVs for this zone have stopped |
| `occupied` | Restore after `restore_delay_seconds` if zone is still occupied |

## Notes

- Zones with no occupancy sensors configured are always treated as occupied
- `select_source` is only called if the input name appears in the zone entity's `source_list`
- Volume offset changes apply immediately to active zones
- Follow-me switch state and volume offset persist across HA restarts
