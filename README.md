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
- **Per-zone follow-me switch** — pull a room out of the rotation instantly; auto-re-enables at 07:00
- **Multi-device ATV exclusions** — one or more local streaming devices can override whole-house follow per zone, with configurable restore conditions and delay
- **App-aware exclusions** — optionally bypass the ATV exclusion for specific apps (e.g. let Apple Music follow-me while video still takes over local audio)
- **Per-source app filter** — restrict a source to only trigger follow-me when a specific app is active (e.g. Apple TV source only routes when Apple Music is playing)
- **Amp-only zones** — manage a dedicated amp switch without a whole-house zone; useful when a local device drives its own amplifier
- **Restore delay for all conditions** — configurable delay before a zone re-follows after a device stops or pauses
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
- **App filter entity** *(optional)* — a media_player entity (typically an Apple TV) to check for active app
- **App filter list** *(optional)* — one or more app names or bundle IDs (e.g. `Music`, `Spotify`, `com.apple.TVMusic`); if set, the source only triggers follow-me when the specified entity is showing one of these apps. Leave blank to follow on any playback.

Each source gets a `switch.<system>_<source>_follow_me` entity created automatically.
Toggle it off to stop that source from triggering whole-house follow without removing the source config.

### 3. Add Zones

For each room:
- **Zone name** — display name (e.g. "Main Floor")
- **Audio system** — which system this zone belongs to
- **Media player entity** — the zone's media_player (receives `turn_on`, `select_source`, `volume_set`). **Leave blank for amp-only zones** — the zone will not route central audio but ATV exclusions will still manage the amp switch based on occupancy and local playback.
- **Occupancy sensors** — one or more binary_sensors; zone activates when any is `on` (leave blank = always occupied)
- **Off delay** — seconds to wait after room empties before turning off (default 600s)
- **ATV exclusions** — optional: one or more local streaming devices that override whole-house follow. Each exclusion rule has:
  - **ATV entities** — one or more media_player entities to watch
  - **Restore condition** — `any_stopped`, `all_stopped`, or `occupied`
  - **Restore delay** — seconds to wait before re-following (pausing also starts the timer)
  - **AirPlay exception** — don't trigger the exclusion when AirPlay is the active source on the device
  - **Amp switch** — optional switch entity to turn on/off alongside the exclusion
  - **Bypass app IDs** — optional list of app names or bundle IDs; when the ATV is showing one of these apps, the exclusion is skipped entirely and central audio routes normally

#### Amp-only zones

If your room has a local streaming device (e.g. Apple TV) driving a dedicated amplifier with no whole-house zone to cut over, configure the zone with no media player and an ATV exclusion pointing at the device with the amp switch set. The integration will:
- Turn the amp on when the device starts playing and the room is occupied
- Turn the amp off when the device stops or pauses (after restore delay), or when the room empties (after off delay)

#### Apple TV: music vs. video

A common pattern is an Apple TV that should trigger whole-house follow-me when playing music but take over local audio when playing video. Configure both layers:

1. **Source (system level)** — add the Apple TV as a source with an app filter: set `app_filter_entity` to the ATV and `app_ids` to `com.apple.TVMusic` (and/or `Spotify`, etc.). The source only routes when music is playing.
2. **Zone (zone level)** — add the ATV to the zone's ATV exclusion with `bypass_app_ids: com.apple.TVMusic`. The exclusion only fires for non-music apps.

Result: Apple Music → follow-me everywhere. Video → local audio takes over.

## Entities

### Per system
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<system>_active` | Master on/off — disables all zones when off |
| `switch.dynamic_central_audio_<system>_<source>_follow_me` | Per-source follow-me toggle (one per configured source) |
| `sensor.dynamic_central_audio_<system>_status` | Active source name; `reasoning` attribute shows full decision |
| `switch.dynamic_central_audio_<system>_party_mode` | Party Mode — groups selected ATVs onto the source ATV via AirPlay 2 (see [PARTY_MODE.md](PARTY_MODE.md)) |
| `sensor.dynamic_central_audio_<system>_party_mode_status` | Party Mode grouping status (`party_active`/`idle`/`grouping`/`party_error`) |

### Per zone
| Entity | Description |
|--------|-------------|
| `switch.dynamic_central_audio_<zone>_follow_me` | Enable/disable follow-me for this zone |
| `sensor.dynamic_central_audio_<zone>_status` | Zone state; `reasoning` attribute explains why |
| `switch.dynamic_central_audio_<zone>_party_mode` | Zone-level Party Mode — groups this zone's selected target ATVs onto its own ATV |

### Party Mode

Groups Apple TVs into an AirPlay 2 multi-room set so local ATVs and HTD central zones can play together instead of the local ATV excluding the zone. Requires `pyatv` (installed automatically as a requirement) and existing `apple_tv` integration pairings for credential reuse. See [PARTY_MODE.md](PARTY_MODE.md) for the full design, including:
- Trigger scope is app-allowlisted (default: AirPlay, Music) — a video app never starts a party
- A zone's ATV exclusion is only bypassed if none of its exclusion rules use an `amp_switch` (avoids driving the same room's speakers from two amps at once)
- **Known limitation**: ATV-to-ATV sync is automatic via AirPlay 2, but there's no mechanism to sync an HTD zone's own central-audio playback against the AirPlay group — expect a slight, uncorrected lag between the two in a zone where both are active simultaneously
| `number.dynamic_central_audio_<zone>_volume_offset` | Fine-tune zone volume (−0.30 to +0.30, persists across restarts) |

## ATV Exclusion Restore Conditions

| Condition | Behavior |
|-----------|----------|
| `any_stopped` | Restore as soon as any device in this rule stops |
| `all_stopped` | Restore only when ALL devices in this rule have stopped |
| `occupied` | Restore after `restore_delay_seconds` only if zone is still occupied |

A `restore_delay_seconds` value > 0 applies a delay before re-following regardless of condition.
If a device resumes playing during the delay, the pending restore is cancelled automatically.
Pausing a device is treated the same as stopping — the restore timer starts immediately.

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
- Disabling a zone's follow-me switch schedules an automatic re-enable at 07:00 local time; toggling it back on manually cancels the timer; the timer survives HA restarts and integration reloads
- ATV exclusion restore triggers on `idle`, `off`, `paused`, and `standby` states

## Changelog

### v0.4.1
- **Fix:** `pyatv_bridge.connect_atv` passed `loop=None` to `pyatv.scan()`/`pyatv.connect()`, which crashed (`AttributeError: 'NoneType' object has no attribute 'create_datagram_endpoint'`) instead of using the running event loop. This made every Party Mode connection attempt fail silently, which is why a zone's Party Mode switch would flip on and immediately back off. Now passes the actual running loop.

### v0.4.0
- **Feat:** Party Mode — groups Apple TVs into an AirPlay 2 multi-room set so local ATVs and HTD central zones can play together instead of the local ATV excluding the zone. New `switch.dynamic_central_audio_<system>_party_mode` (system, multi-select target ATVs) and `switch.dynamic_central_audio_<zone>_party_mode` (zone-level, targets this zone's own ATV as source). Auto-trigger is app-allowlisted (default AirPlay, Music) so a video app never starts a party. See [PARTY_MODE.md](PARTY_MODE.md).
- **Feat:** A zone's ATV exclusion is only bypassed during Party Mode if none of its exclusion rules use an `amp_switch` — avoids driving the same room's speakers from two amps simultaneously. Zones with an `amp_switch` keep their existing exclusion behavior and still get synced party audio through it once their ATV is grouped.
- **Feat:** New `sensor.dynamic_central_audio_<system>_party_mode_status` reports grouping status (`party_active`/`idle`/`grouping`/`party_error`); zone status sensor reasoning now shows a `(party mode)` suffix when following with the exclusion bypassed.
- **Feat:** `create_dashboard.py` now adds Party Mode controls to both the system card and every zone card (so it's reachable without navigating away from a zone), and groups zone cards by HA floor when the area/floor registry gives a confident name match, falling back to a flat "Zones" list otherwise.
- **Chore:** Requires `pyatv` (added to `manifest.json` requirements); reuses existing `apple_tv` integration pairings for credentials — no re-pairing needed.
- **Known limitation:** ATV-to-ATV sync is automatic via AirPlay 2's grouping protocol, but there is no mechanism to sync an HTD zone's own central-audio playback against the AirPlay group — expect a slight, uncorrected lag between the two when both are active in the same zone simultaneously.

### v0.3.18
- **Feat:** Manual zone power-on now bypasses occupancy detection and activates source routing. When a zone's media player is powered on from the dashboard while the room is unoccupied, the coordinator immediately detects the state change, cancels any pending deactivation timers, selects the active source, and sets volume — exactly as if the zone were occupied. Status reports `following: <source> (manual override)`. Disabling Follow Me powers the zone back off as normal.
- **Feat:** Zone coordinators now subscribe to their own media player's state changes. Manual power-on triggers an immediate coordinator refresh rather than waiting for the 60-second polling interval, preventing race conditions where a pending occupancy-deactivate timer could shut the zone back off before the coordinator detected the manual activation.
- **Feat:** Zone status sensor reasoning now surfaces a distinct `following (manual override)` message when a zone is active but unoccupied, showing source, base volume, and offset — replacing the previous "Will activate when occupancy detected" text that gave no indication the manual override was working.

### v0.3.17
- **Fix:** Zone and system options flows now read existing config from `entry.options` first (falling back to `entry.data`). Previously, re-editing a zone or system would show stale original setup values instead of the most recently saved settings, causing all edits after the first to appear to reset.

### v0.3.16
- **Fix:** ATV override state now reconciled from current HA states on startup. Previously, if an ATV was already playing when HA restarted, the zone would briefly activate central audio before the first state-change event re-established the override, causing both central audio and local audio to play simultaneously.

### v0.3.15
- **Fix:** Amp no longer activates on zone entry when the ATV is paused or stopped. Previously, walking into a room while the ATV was mid-restore-delay (paused, override still tracked) would turn the amp on for a device that wasn't playing.

### v0.3.14
- **Feat:** ATV exclusion rules now support `bypass_app_ids` — when the ATV is playing an app in this list (matched against `app_id` or `app_name`), the exclusion is skipped and central audio routes normally. Combine with a source-level app filter to make the Apple TV follow-me for music but take over local audio for video.

### v0.3.13
- **Feat:** App filter list now pre-populates with the entity's current `app_id` and `app_name` when editing an existing source — no need to look up bundle IDs manually
- **Fix:** `source_off_delay_seconds` no longer silently dropped when saving system options

### v0.3.12
- **Fix:** All `async_call_later` timer callbacks now use `@callback`-decorated methods instead of bare lambdas. HA 2025.x+ raises `RuntimeError` on plain lambda callbacks and silently drops the scheduled task, causing occupancy deactivation timers, source-stop timers, follow-me reset timers, and ATV restore-delay timers to never fire.

### v0.3.11
- **Fix:** ATV playing while zone is unoccupied no longer causes both central audio and ATV to play simultaneously when someone enters. Override is now always tracked immediately; amp and zone player actions are deferred until occupancy. When the room empties, the exclusion is only cleared for ATVs that have stopped — streaming ATVs keep their override so the amp re-enables correctly on next entry.

### v0.3.10
- **Feat:** Per-source app filter — optionally restrict a source to only trigger follow-me when a specified media player (e.g. an Apple TV) is showing certain apps. Configure an app filter entity and one or more app names or bundle IDs; leave blank to follow on any playback. App state changes trigger immediate re-evaluation.

### v0.3.9
- **Feat:** Amp-only zones — media player is now optional. Leave it blank to create a zone that manages only an amp switch via ATV exclusions, with no central audio routing. Useful when a local streaming device drives a dedicated amplifier with no whole-house zone to cut over.

### v0.3.8
- **Fix:** Occupancy deactivation now reliably clears zones stuck in ATV override. Previously, if `media_player.turn_off` had no effect on the device (e.g. an active AirPlay stream), `_atv_excluded_by` was never cleared and the zone stayed in `atv_override` indefinitely with the amp switch left on. New `_clear_atv_overrides()` path forcibly cancels restore timers, turns off amp switches, and clears the exclusion state without waiting for the device to report a stop.

### v0.3.6
- **Feat:** Follow-me 07:00 reset timer now survives HA restarts and integration reloads (re-scheduled on startup)

### v0.3.5
- **Feat:** Per-source follow-me switch — disable individual sources from triggering whole-house follow without removing config
- **Feat:** Restore delay applies to all restore conditions (not just `occupied`)

### v0.3.4
- **Feat:** Multi-device ATV exclusions — a single rule can list multiple ATV entities
- **Feat:** `all_stopped` restore condition — wait until every device in the rule has stopped

### v0.3.3
- **Feat:** Volume offset `number` entity per zone — persists across restarts, applied on top of source base volume
- **Feat:** AirPlay exception flag on ATV exclusion rules — AirPlay from the same device does not trigger override

### v0.3.2
- **Feat:** Amp switch support in ATV exclusion rules — turn on/off an external amp when local device takes over
- **Fix:** Restore delay timer now cancelled if device resumes playing before delay expires

### v0.3.1
- **Feat:** ATV exclusion with restore conditions (`any_stopped`, `occupied`) and configurable restore delay
- **Feat:** `reasoning` attribute on all status sensors

### v0.3.0
- Initial HACS-installable release: multi-zone follow-me, per-zone follow-me switch, occupancy gating, source priority
