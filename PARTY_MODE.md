# DCA Party Mode
## Dynamic Central Audio v0.5.0

---

## Context

Normally, when a zone's local Apple TV starts playing, `ZoneCoordinator._process_atv_change` treats that as an exclusion: it cuts central audio off from that zone's HTD amp (and optionally hands the room over to a local `amp_switch`). Party Mode is a way to say "no, actually — keep central audio going in this zone too" without touching occupancy gating or anything else about how the zone normally behaves.

**This is deliberately not AirPlay 2 grouping.** An earlier version of this design (see git history — `pyatv_bridge.py`, now removed) tried to synchronize the central source and every zone's local ATV into one AirPlay 2 group via `pyatv`. That depended on MRP protocol credentials which none of this household's paired Apple TVs actually have (confirmed directly against `core.config_entries` — only AirPlay/Companion/RAOP creds exist), and HA's `apple_tv` integration offered no way to re-pair MRP through its reconfigure flow. Rather than keep chasing that, Party Mode was simplified to what it actually needs to do: stop excluding.

## What it does

- **System-level** `switch.dynamic_central_audio_<system>_party_mode`: when on, every zone's ATV-exclusion gate is suspended (see the amp_switch exception below).
- **Zone-level** `switch.dynamic_central_audio_<zone>_party_mode`: same, scoped to just that zone.
- A zone's central routing resumes as normal (occupied → follows the active source, unoccupied → standby) — Party Mode only removes the ATV-exclusion veto, nothing else in the decision tree changes.
- Central and the zone's local ATV play **independently and unsynced** — no AirPlay grouping, no shared clock. If they're audible in the same room, expect to hear both, out of sync. That's an inherent limitation of not doing AirPlay 2 grouping, not a bug.

## Safety rule: amp_switch-guarded zones are exempt

Some zones (e.g. Garage) have an ATV exclusion rule with an `amp_switch` configured — the local ATV drives an alternate physical amp for that same room instead of the HTD zone amp. Suspending that zone's exclusion during Party Mode would try to drive the same room's speakers from two amps at once. `ZoneCoordinator._party_suspends_exclusion()` checks this: **a zone's exclusion is only suspended if none of its currently-active exclusion rules have an `amp_switch` set.** Those zones keep their normal exclusion behavior — their room still gets audio through the ATV + amp_switch path, just not synchronized with anything else.

## Auto-trigger (system-level only)

`SystemCoordinator._async_check_party_trigger` can turn Party Mode on/off automatically based on the configured source ATV's app — **only** AirPlay or apps in an allow-list (`party_mode_trigger_apps`, default `["AirPlay", "Music"]`), never a generic "playing" state, so a video app never starts a party. Configure via the system's options flow ("Party Mode" step): source ATV, trigger apps, auto-trigger, auto-off. Zone-level Party Mode is manual-only (just the switch) — there was nothing left to configure once target-ATV selection was dropped.

## Turns off when everything turns off

- Turning the system's master **Active** switch off clears system Party Mode and every zone's Party Mode.
- Turning a zone's **Follow Me** switch off clears that zone's own Party Mode.
- Party Mode switches are **not** `RestoreEntity` — they always start off after a HA restart, regardless of what they were before. A stale "on" shouldn't silently resume.

## Entities

| Entity | Level | Type | Behavior |
|--------|-------|------|----------|
| `switch.dynamic_central_audio_<system>_party_mode` | System | Switch | ON suspends every zone's ATV exclusion (amp_switch zones excepted) |
| `sensor.dynamic_central_audio_<system>_party_mode_status` | System | Sensor | `party_active` / `idle`; attributes: `party_mode_active`, `source_atv` |
| `switch.dynamic_central_audio_<zone>_party_mode` | Zone | Switch | ON suspends this zone's own ATV exclusion (unless amp_switch-guarded) |

Zone-level party status is exposed as `zone_party_active` and `party_mode_suspends_exclusion` attributes on the existing `sensor.dynamic_central_audio_<zone>_status` sensor, plus a `(party mode)` suffix on its `reasoning`/status text when the exclusion is being bypassed.

## Config

System options flow, "Party Mode" step:
- `party_mode_source_atv` — the ATV whose app state drives auto-trigger
- `party_mode_trigger_apps` — allow-list (default AirPlay, Music)
- `party_mode_auto_trigger` / `party_mode_auto_off` — booleans

No zone-level config — the zone switch is standalone.

## Dashboard

`create_dashboard.py` adds the Party Mode switch to every zone's entities card (both that zone's own switch and the whole-house one, so it's reachable without navigating to the system card), and the system's Party Mode switch + status sensor to the system card. Zones are grouped under an HA-floor heading where the area/floor registry gives a confident name match, otherwise listed flat under "Zones". The generator also now preserves any manually-added "Speaker" row (a zone's raw media_player, added directly to the live dashboard at some point) since its entity_id isn't derivable from the zone slug.
