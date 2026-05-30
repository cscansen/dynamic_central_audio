# Dynamic Central Audio — Project Plan

## Overview
A generic Home Assistant HACS integration for find-me/follow-me whole-house audio.
Replaces the existing JSON automation stack with a proper HA integration.

**GitHub repo:** `dynamic_central_audio` (private)
**HA domain:** `dynamic_central_audio`
**HACS install:** private repo + PAT key

---

## Architecture

### Entry Types
- **system** — one per audio controller hardware (HTD, receiver, etc.)
- **zone** — one per room; each references a parent system entry

### Three-level hierarchy
```
System entry       → defines audio sources (watcher entities, source names, volumes)
  Zone entry       → defines room (media_player, occupancy sensors, ATV exclusions)
  Zone entry       → ...
System entry       → a second audio controller
  Zone entry       → ...
```

### Event-driven design
- `async_track_state_change_event` drives all decisions (not poll-based)
- DataUpdateCoordinator used for entity update bus + RestoreEntity machinery
- Fallback poll interval: 60s
- Deactivation delays handled via `async_call_later` with cancel handles

---

## Entities Created

### System entry
| Entity | Type | Notes |
|--------|------|-------|
| `switch.dynamic_central_audio_<system>_active` | Switch + RestoreEntity | Master kill switch |
| `sensor.dynamic_central_audio_<system>_status` | Sensor | routing_mode, active_source attrs |

### Zone entry (per zone)
| Entity | Type | Notes |
|--------|------|-------|
| `switch.dynamic_central_audio_<zone>_follow_me` | Switch + RestoreEntity | Per-zone enable toggle |
| `sensor.dynamic_central_audio_<zone>_status` | Sensor | following/excluded/idle/off |
| `number.dynamic_central_audio_<zone>_volume_offset` | Number + RestoreEntity | -0.20 to +0.20, step 0.01 |

---

## Source Config Model (per source in system entry)
```json
{
  "display_name": "AirPlay",
  "source_name": "AirPlay",
  "watcher_entity": "media_player.airplay_downstairs",
  "active_state": "playing",
  "base_volume": 0.80,
  "gate_entity": null,
  "gate_state": "on",
  "priority": 1
}
```
- `source_name` is the string passed to `media_player.select_source`
- `gate_entity` + `gate_state` = optional second condition (e.g., LR ATV follow-me toggle)
- `priority` = lower number wins when multiple sources active simultaneously
- `source_name` discovered dynamically from `source_list` attribute of reference entity

---

## Zone Config Model
```json
{
  "zone_name": "Main Floor",
  "system_entry_id": "<system_entry_id>",
  "media_player": "media_player.main_floor",
  "occupancy_sensors": ["binary_sensor.main_floor_common_area_occupied"],
  "off_delay_seconds": 600,
  "atv_exclusions": [
    {
      "atv_entity": "media_player.garage_apple_tv",
      "restore_condition": "occupied",
      "restore_delay_seconds": 300,
      "airplay_exception": false,
      "amp_switch": "switch.extra1"
    }
  ]
}
```

### Restore conditions for ATV exclusions
- `any_stopped` — restore as soon as this ATV is not playing
- `all_stopped` — restore only when ALL ATVs in this zone's exclusion list are not playing
- `occupied` — restore only if zone is still occupied (after restore_delay_seconds)

---

## Deactivation Logic
- **Source stops** → system coordinator resolves routing_mode = "none" → notifies zones → each zone schedules deactivation after `source_off_delay_seconds` (system-level, default 300s)
- **Occupancy off** → zone coordinator detects → schedules deactivation after `off_delay_seconds` (zone-level, default 600s)
- **Follow-me switch OFF** → immediate deactivation
- **ATV starts playing** → immediate zone deactivation (ATV exclusion)
- All pending deactivation timers cancelled when conditions change (source resumes, occupancy returns)

---

## Config Flow

### System setup (multi-step)
1. System name + reference entity (reads source_list for dropdown)
2. Source loop: display_name, source_name (dropdown from source_list), watcher_entity, active_state, base_volume, gate_entity, gate_state, priority, "Add another?" checkbox

### Zone setup (multi-step)
1. Zone name + system selection (dropdown of configured systems)
2. Media player entity selector
3. Occupancy sensors (multi-select binary_sensor) + off_delay_seconds
4. ATV exclusion (optional): atv_entity, restore_condition, restore_delay_seconds, amp_switch
5. "Add another ATV exclusion?" → loops

### Options flows mirror config flows (for editing)

---

## Files
```
adaptive_central_audio/              ← git repo root
  PROJECT_PLAN.md                    ← this file
  project_description.md
  hacs.json
  README.md
  .gitignore
  custom_components/
    dynamic_central_audio/
      __init__.py
      const.py
      coordinator.py
      config_flow.py
      switch.py
      sensor.py
      number.py
      manifest.json
      strings.json
      translations/
        en.json
```

---

## Zones to Configure (this installation)
| Zone | Media Player | Occupancy Sensor(s) | Off Delay | ATV Exclusion |
|------|-------------|--------------------|-----------|----|
| Main Floor | media_player.main_floor | binary_sensor.main_floor_common_area_occupied | 600s | — |
| Second Floor | media_player.second_floor | binary_sensor.family_room_occupied, binary_sensor.calebs_office_occupancy, binary_sensor.tias_office_presence_motion | 900s | Tia's ATV + Family Room ATV (all_stopped) |
| Master Bedroom | media_player.master_bedroom | binary_sensor.master_bedroom_occupied | 600s | Master Bedroom ATV (any_stopped) |
| Garage | media_player.garage | binary_sensor.garage_occupied | 600s | Garage ATV (occupied, 300s delay, no airplay exception, amp=switch.extra1) |
| Gazebo | media_player.gazebo | binary_sensor.yard_gazebo_slider_person_detected | 600s | — |
| Front Porch | media_player.front_porch | (none — no sensor yet) | 600s | — |

---

## Automations to Retire (after validation)
- speaker_zones_follow_updated.json (ID: 1768126562712)
- outdoor_gazebo_zone_follow.json (ID: outdoor_gazebo_zone_yard_person_presence)
- audio_zone_master_bedroom_atv_off / restore
- audio_zone_second_floor_atv_off / restore
- garage_atv_zone_off_independent / restore
- Speaker Zones - Volume Policy (ID: 1768687730669)

---

## v1 Scope — Deferred to v2
- Staircase prewarm (binary_sensor.stairs_occupied → pre-activate main_floor + second_floor)
- Sonos group-join zone activation mode
- Dynamic runtime source_list change detection
- Per-zone source_off_delay override

## Build Status
- [x] PROJECT_PLAN.md
- [x] manifest.json
- [x] hacs.json
- [x] const.py
- [x] coordinator.py
- [x] __init__.py
- [x] switch.py
- [x] sensor.py
- [x] number.py
- [x] config_flow.py
- [x] strings.json + translations/en.json
- [x] Git init + README (v0.1.0 committed)
- [ ] GitHub repo creation (private, push remote)
- [ ] HACS validation
- [ ] HA install + test
- [ ] Retire old automations
