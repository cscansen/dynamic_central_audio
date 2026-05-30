# Dynamic Central Audio — Project Plan

## Overview
A generic Home Assistant HACS custom integration for find-me/follow-me whole-house audio.
Replaces the existing JSON automation stack with a proper HA integration.

**GitHub repo:** `cscansen/dynamic_central_audio` (private)
**HA domain:** `dynamic_central_audio`
**HACS install:** private repo + PAT key
**Current version:** v0.3.4 (live in HA, under active testing)

---

## Current State (as of 2026-05-30)

- Integration installed via HACS and running in HA
- 2 systems configured: `central_audio` (HTD whole-house), `garage_gym`
- 7 zones configured: Main Floor, Family Room and Tia's Office, Master Bed and Bath, Gazebo and Yard, Garage, Garage Gym Zone, Front Porch
- Old automations **disabled** (not deleted) — pending validation before permanent retirement
- Dashboard live at `/dashboard-audio` with per-zone reasoning cards
- No error 500s for 2+ days pre-integration; clean testing phase ongoing

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
System entry       → a second audio controller (fully isolated — zones only follow their own system)
  Zone entry       → ...
```

### Event-driven design
- `async_track_state_change_event` drives all decisions (not poll-based)
- `DataUpdateCoordinator` used for entity update bus + RestoreEntity machinery
- Fallback poll interval: 60s
- Deactivation delays: `async_call_later` with cancel handles
- ATV restore timers: `_atv_restore_handles` dict — cancelled if device resumes mid-delay

---

## Entities Created

### System entry
| Entity | Type | Notes |
|--------|------|-------|
| `switch.dynamic_central_audio_<system>_active` | Switch + RestoreEntity | Master kill switch |
| `switch.dynamic_central_audio_<system>_<source>_follow_me` | Switch + RestoreEntity | Per-source follow-me toggle (one per source) |
| `sensor.dynamic_central_audio_<system>_status` | Sensor | routing_mode; `reasoning` attr = full decision text |

### Zone entry (per zone)
| Entity | Type | Notes |
|--------|------|-------|
| `switch.dynamic_central_audio_<zone>_follow_me` | Switch + RestoreEntity | Per-zone enable toggle |
| `sensor.dynamic_central_audio_<zone>_status` | Sensor | following/excluded/idle/off; `reasoning` attr |
| `number.dynamic_central_audio_<zone>_volume_offset` | Number + RestoreEntity | −0.30 to +0.30, step 0.01 |

---

## Source Config Model (v0.2.0+)
```json
{
  "display_name": "AirPlay",
  "source_name": "AirPlay",
  "watcher_entity": "media_player.airplay_downstairs",
  "active_state": "playing",
  "base_volume": 0.80,
  "priority": 1
}
```
- `gate_entity` / `gate_state` removed in v0.2.0 — replaced by per-source follow-me switch
- `source_name` is the string passed to `media_player.select_source`
- `priority` — lower number wins when multiple sources active simultaneously

---

## Zone Config Model (v0.3.0+)
```json
{
  "zone_name": "Garage",
  "system_entry_id": "<system_entry_id>",
  "media_player": "media_player.garage",
  "occupancy_sensors": ["binary_sensor.garage_occupied"],
  "off_delay_seconds": 600,
  "atv_exclusions": [
    {
      "atv_entities": ["media_player.garage_apple_tv"],
      "restore_condition": "occupied",
      "restore_delay_seconds": 300,
      "airplay_exception": false,
      "amp_switch": "switch.extra1"
    }
  ]
}
```

### Restore conditions
| Condition | Behavior |
|-----------|----------|
| `any_stopped` | Restore as soon as any device in the rule stops |
| `all_stopped` | Restore when ALL devices in the rule have stopped |
| `occupied` | Restore after `restore_delay_seconds` only if zone still occupied |

`restore_delay_seconds` (default 0) applies a delay before re-following on any condition.

---

## Deactivation Logic
- **Source stops** → system coordinator → notifies zones → each zone schedules deactivation after `source_off_delay_seconds` (default 300s)
- **Occupancy off** → zone schedules deactivation after `off_delay_seconds` (default 600s)
- **Follow-me switch OFF** → immediate deactivation
- **Source follow-me switch OFF** → source excluded from routing immediately
- **ATV starts playing** → immediate zone deactivation; amp switch turned on if configured
- **ATV stops** → restore after delay (if any); pending restore cancelled if ATV resumes
- All pending deactivation timers cancelled when conditions change

---

## Config Flow

### System setup (multi-step)
1. System name + optional reference zone player (reads `source_list` for dropdown)
2. Source loop: display_name, source_name, watcher_entity, active_state, base_volume, priority, "Add another?"

### Zone setup (multi-step)
1. Zone name + system selection
2. Media player entity
3. Occupancy sensors (multi-select) + off_delay_seconds
4. ATV exclusion: `atv_entities` (multi-select), restore_condition, restore_delay_seconds, airplay_exception, amp_switch
5. "Add another ATV exclusion?" → loops

### Options flows mirror config flows for editing

---

## Files
```
adaptive_central_audio/              ← git repo root
  PROJECT_PLAN.md                    ← this file
  TODOS.md                           ← deferred work by release
  project_description.md
  create_dashboard.py                ← one-shot Lovelace dashboard builder
  hacs.json
  README.md
  .gitignore
  custom_components/
    dynamic_central_audio/
      __init__.py
      const.py
      coordinator.py                 ← SystemCoordinator + ZoneCoordinator + _excl_entities()
      config_flow.py
      switch.py                      ← SystemActiveSwitch, SourceFollowMeSwitch, ZoneFollowMeSwitch
      sensor.py                      ← SystemStatusSensor, ZoneStatusSensor (with reasoning attr)
      number.py
      manifest.json
      strings.json
      translations/en.json
```

---

## This Installation — Zones Configured
| Zone | Media Player | Occupancy Sensor(s) | Off Delay | ATV Exclusion |
|------|-------------|--------------------|-----------|----|
| Main Floor | media_player.main_floor | binary_sensor.main_floor_common_area_occupied | 600s | — |
| Family Room + Tia's Office | media_player.second_floor | family_room_occupied, calebs_office_occupancy, tias_office_presence_motion | 900s | Family Room ATV + Tia's Office ATV (all_stopped) |
| Master Bed and Bath | media_player.master_bedroom | binary_sensor.master_bedroom_occupied | 600s | Master Bedroom ATV (any_stopped) |
| Garage | media_player.garage | binary_sensor.garage_occupied | 600s | Garage ATV (occupied, 300s delay, amp=switch.extra1) |
| Gazebo and Yard | media_player.gazebo | binary_sensor.yard_gazebo_slider_person_detected | 600s | — |
| Front Porch | media_player.front_porch | — | 600s | — |

---

## Automations to Retire (after validation complete)
All 9 are currently **disabled** in HA — not deleted.

| Automation | Entity ID |
|------------|-----------|
| Speaker Zones Follow | `automation.speaker_zones_follow_only_when_playing_airplay_lr_atv` |
| Speaker Zones Volume Policy | `automation.speaker_zones_volume_policy_auto_only` |
| Garage ATV Zone Off | `automation.garage_atv_zone_off_when_playing_independently` |
| Garage ATV Zone Restore | `automation.garage_atv_zone_restore_when_stopped` |
| Master Bedroom ATV Off | `automation.audio_zone_master_bedroom_off_atv_playing` |
| Master Bedroom ATV Restore | `automation.audio_zone_master_bedroom_restore_atv_stopped` |
| Second Floor ATV Off | `automation.audio_zone_second_floor_off_tia_or_family_room_atv_playing` |
| Second Floor ATV Restore | `automation.audio_zone_second_floor_restore_tia_family_room_atv_both_stopped` |
| Outdoor Gazebo Zone Follow | `automation.speaker_zones_outdoor_gazebo_yard_person_presence` |

After deletion: also audit `input_boolean.auto_audio_*`, `input_number.htd_vol_*`, and any
templates in `templates.yaml` that were only serving the old automation stack.

---

## Release History
| Version | Summary |
|---------|---------|
| v0.1.0 | Initial build — system/zone coordinators, config flow, all entities |
| v0.2.0 | Per-source follow-me switches; removed gate_entity/gate_state; reference entity label fix |
| v0.3.0 | Multi-entity ATV exclusions; restore delay for all conditions; cancel-safe restore timers |
| v0.3.1 | Fix amp_switch EntitySelector rejecting empty string default |
| v0.3.2 | Fix reference_entity EntitySelector rejecting empty string default |
| v0.3.3 | Fix source_watcher_entity EntitySelector rejecting empty string default |
| v0.3.4 | Reasoning attribute on status sensors; dashboard script (`create_dashboard.py`) |

---

## Build Status
- [x] All code files
- [x] GitHub repo (private, `cscansen/dynamic_central_audio`)
- [x] HACS install working
- [x] Integration configured in HA (2 systems, 7 zones)
- [x] Old automations disabled
- [x] Dashboard live at `/dashboard-audio`
- [x] README accurate for v0.3.4
- [ ] Validation complete
- [ ] Old automations + orphaned helpers/templates retired
- [ ] v0.4.0 (app-based ATV exclusion filtering, app-gated source condition)
