# DCA Party Mode — Design Document
## Dynamic Central Audio v0.4.0

---

## Context

The current DCA system routes a central audio source (AirPlay or Apple TV Music) to HTD zone amps throughout the house via follow-me logic. Each room's amp plays the same source when occupied. However, this covers only the HTD central-audio zones — not the local amps attached to Apple TVs in individual rooms (master bedroom ATV, family room ATV, garage ATV). Those ATVs are currently treated as **exclusion targets** (when they're playing locally, they suppress the central zone).

**Party Mode inverts this relationship.** Instead of suppressing central audio when a local ATV plays, Party Mode makes all local ATVs join the primary ATV's AirPlay 2 group — so the source ATV becomes the master and broadcasts to every other ATV simultaneously, synchronized via AirPlay 2. Combined with the existing HTD zone follow-me, this gives true whole-house party audio: every HTD zone amp AND every local ATV amp plays the same source.

Target release: **v0.4.0**

---

## Configuration Scope: System vs. Zone

Party Mode can be configured at two levels with different semantics:

### System-Level Party Mode
**Blasts the whole house by default, but every target is deselectable.** As implemented, the target-ATV selector defaults to all currently-discovered ATVs (`party_mode_target_atvs`) so the common case is a single confirm, but any ATV can be excluded via the same multi-select entity picker used at zone level — there is no longer an implicit "always all, no selector" mode.

- Source ATV: configurable (`party_mode_source_atv`)
- Targets: multi-select `EntitySelector`, defaulted to all discovered ATVs
- Intent: one switch to rule them all, with an escape hatch per device

### Zone-Level Party Mode
**Assumes the zone's own ATV is the primary source.** Useful when a specific room starts playing and you want to extend it to select other rooms only.

- Source ATV: automatically the ATV associated with that zone's config
- Targets: checkboxes — select which other ATVs around the house join
- Intent: "I'm in the family room and want the garage and master bed to follow"
- Per-zone `switch.dynamic_central_audio_<zone>_party_mode` entity

Both levels can coexist — system party mode is the superset; zone party mode is targeted extension.

---

## Key Architecture Decision: pyatv Runs Inside HA

**No Docker container needed.**

HA's built-in `apple_tv` integration already depends on pyatv — it's installed in HA's Python venv. A custom component can import it directly by declaring it as a requirement. Crucially, the existing `apple_tv` config entries already store device credentials (MRP/Companion auth tokens) from initial pairing. DCA Party Mode reads those credentials from HA's config entry registry — no re-pairing required.

**Integration architecture:**
- `manifest.json` → add `"requirements": ["pyatv==X.Y.Z"]` (pin to match HA's apple_tv integration version)
- On party mode activation, `SystemCoordinator` uses pyatv to connect to the source ATV and call `interface.audio.set_output_devices()` to add target ATVs to the AirPlay 2 group
- One live pyatv connection per system, managed by `SystemCoordinator`, reused across mode changes
- Credentials pulled from `hass.config_entries.async_entries("apple_tv")` matched by `entity_id → config_entry → identifier`

---

## User-Facing Design

### System-Level Config (System Options Flow)

```
Party Mode
──────────
[ ] Enable Party Mode for this system

Source ATV (the device that broadcasts to all others):
  ● media_player.living_room_apple_tv  ← entity selector dropdown

Target ATVs (multi-select, defaults to all discovered):
  [x] media_player.garage_apple_tv
  [x] media_player.master_bedroom_atv
  [x] media_player.calebs_office_apple_tv
  ...

Trigger apps (default: AirPlay, Music):
  [AirPlay] [Music] [+ add app]

Auto-off when source ATV stops matching a trigger app:
  [x] Yes (recommended)

```

**Trigger scope is app-allowlisted, not "any playing state."** As implemented (`SystemCoordinator._async_check_party_trigger` / `party_mode_trigger_apps`), auto-trigger only fires when the source ATV is `playing` AND its `app_id`/`app_name` matches a configured allow-list (default `["AirPlay", "Music"]`) — reusing the same matching helper (`_app_matches`) as the existing per-source `app_ids` filter and `bypass_app_ids`. A video app playing on the source ATV will never start Party Mode.

**ATV exclusion behavior during party is automatic, not a config toggle.** As implemented, `CONF_PARTY_SUSPEND_EXCLUSIONS` was dropped in favor of a hardcoded safety rule (`ZoneCoordinator._party_suspends_exclusion()` in `coordinator.py`): a zone's ATV exclusion is only suspended during Party Mode if none of its currently-active exclusion rules have an `amp_switch` configured. Zones with an `amp_switch` (i.e. the local ATV drives an alternate physical amp for that same room) keep their exclusion as-is — driving the HTD zone amp and the amp_switch simultaneously risks a real electrical conflict on the same speakers, not just messy audio. Those rooms still get synced party audio through their existing amp_switch path once their ATV is grouped; nothing else needs to change for them.

### Zone-Level Config (Zone Options Flow)

```
Zone Party Mode
───────────────
[ ] Enable Party Mode for this zone

Source ATV for this zone (auto-populated from zone ATV config, editable):
  ● media_player.family_room_apple_tv

Additional ATVs to join (checkboxes):
  [x] media_player.garage_apple_tv       — Garage
  [x] media_player.master_bedroom_atv   — Master Bedroom
  [ ] media_player.living_room_apple_tv — Living Room

Trigger:
  ○ Manual only
  ● Auto-on when this zone's ATV starts playing

Auto-off when zone ATV stops:
  [x] Yes
```

### New Entities

| Entity | Level | Type | Behavior |
|--------|-------|------|----------|
| `switch.dynamic_central_audio_<system>_party_mode` | System | Switch | ON groups selected target ATVs to the source ATV |
| `sensor.dynamic_central_audio_<system>_party_mode_status` | System | Sensor | `party_active` / `idle` / `grouping` / `party_error`, with `source_atv`/`target_atvs` attributes |
| `switch.dynamic_central_audio_<zone>_party_mode` | Zone | Switch | ON groups this zone's selected target ATVs to its own ATV |

Zone-level party status is **not** a separate sensor entity — it's exposed as `zone_party_active` and `party_mode_suspends_exclusion` attributes on the existing `sensor.dynamic_central_audio_<zone>_status` sensor, alongside the updated `reasoning` text (`(party mode)` suffix when the exclusion is being bypassed).

---

## Data Model

### System config entry additions

```python
{
    # ... existing fields ...
    "party_mode_source_atv": "media_player.living_room_apple_tv",
    "party_mode_target_atvs": [              # Multi-select, defaults to all discovered ATVs
        "media_player.garage_apple_tv",
        "media_player.master_bedroom_atv",
    ],
    "party_mode_trigger_apps": ["AirPlay", "Music"],
    "party_mode_auto_trigger": True,
    "party_mode_auto_off": True,
}
```

No `party_mode_enabled` / `party_mode_suspend_exclusions` fields — enabling is just toggling the switch entity, and exclusion-suspend is the automatic amp_switch-based safety rule described above, not a config field.

### Zone config entry additions

```python
{
    # ... existing fields ...
    # zone party source ATV derived from the zone's own atv_exclusions config
    "zone_party_target_atvs": [             # Multi-select
        "media_player.garage_apple_tv",
        "media_player.master_bedroom_atv",
    ],
    "zone_party_trigger_apps": ["AirPlay", "Music"],
    "zone_party_auto_trigger": True,
    "zone_party_auto_off": True,
}
```

### const.py additions (as implemented)

```python
STATUS_PARTY_ACTIVE   = "party_active"
STATUS_PARTY_GROUPING = "grouping"
STATUS_PARTY_ERROR    = "party_error"

DEFAULT_PARTY_TRIGGER_APPS = ["AirPlay", "Music"]

CONF_PARTY_SOURCE_ATV       = "party_mode_source_atv"
CONF_PARTY_TARGET_ATVS      = "party_mode_target_atvs"
CONF_PARTY_TRIGGER_APPS     = "party_mode_trigger_apps"
CONF_PARTY_AUTO_TRIGGER     = "party_mode_auto_trigger"
CONF_PARTY_AUTO_OFF         = "party_mode_auto_off"

CONF_ZONE_PARTY_TARGET_ATVS  = "zone_party_target_atvs"
CONF_ZONE_PARTY_TRIGGER_APPS = "zone_party_trigger_apps"
CONF_ZONE_PARTY_AUTO_TRIGGER = "zone_party_auto_trigger"
CONF_ZONE_PARTY_AUTO_OFF     = "zone_party_auto_off"
```

---

## Implementation Plan

### Phase 1 — pyatv Bridge (new file: `pyatv_bridge.py`)

Isolated wrapper for all pyatv calls. Rest of integration degrades gracefully if pyatv isn't importable.

```python
async def get_atv_credentials(hass, media_player_entity_id) -> Optional[dict]:
    """Pull credentials from existing apple_tv config entry for this entity."""
    # entity_registry → entity_entry.config_entry_id → apple_tv config entry
    # Returns {"address": ..., "credentials": {...}}

async def connect_atv(credentials) -> Optional[pyatv.interface.AppleTV]:
    """Open pyatv connection. Returns None on failure."""

async def discover_all_atvs(hass) -> list[dict]:
    """Return credentials for all media_player entities backed by apple_tv integration."""

async def group_atvs(source_connection, target_credentials: list[dict]) -> bool:
    """
    Add targets to source ATV's AirPlay 2 output group.
    1. source_connection.audio.output_devices → available devices
    2. Match targets by identifier/address
    3. source_connection.audio.set_output_devices(selected_devices)
    """

async def ungroup_atvs(source_connection) -> bool:
    """Remove added output devices, restore source-only playback."""
```

### Phase 2 — SystemCoordinator Extensions

```python
self._party_mode_active: bool = False
self._party_atv_connection: Optional[pyatv.interface.AppleTV] = None
self._party_status: str = STATUS_IDLE

async def async_enable_party_mode(self) -> bool:
    # 1. Discover all ATVs via pyatv_bridge.discover_all_atvs()
    # 2. Connect to source ATV
    # 3. Group all discovered ATVs
    # 4. Set _party_mode_active = True, notify zones

async def async_disable_party_mode(self) -> None:
    # Ungroup, close connection, notify zones

def handle_source_change(self, event) -> None:
    # Existing logic +
    # If party_auto_trigger and source ATV now playing Music → enable party
    # If party_auto_off and source ATV stopped → disable party
```

### Phase 3 — ZoneCoordinator Extensions

```python
self._zone_party_active: bool = False
self._zone_party_connection: Optional[pyatv.interface.AppleTV] = None

async def async_enable_zone_party_mode(self) -> bool:
    # Connect to this zone's ATV, group selected target ATVs

async def async_disable_zone_party_mode(self) -> None:
    # Ungroup, close connection

def handle_atv_change(self, event) -> None:
    # Existing logic +
    # If zone_party_auto_trigger and this zone's ATV starts playing → enable zone party
    # If zone_party_auto_off and stops → disable zone party

async def _async_update_data(self) -> dict:
    # Existing logic +
    # If system party OR zone party active + suspend_exclusions → skip ATV override check
```

### Phase 4 — New Entities

**`switch.py`** — add `PartyModeSwitch` (system) and `ZonePartyModeSwitch` (zone), both `CoordinatorEntity + RestoreEntity + SwitchEntity`.

**`sensor.py`** — add `PartyModeStatusSensor` (system) and `ZonePartyStatusSensor` (zone).

### Phase 5 — Config Flow

**System options:** Add party mode section as a new conditional step — shown only when `party_mode_enabled = True`. Use `EntitySelector` for source ATV; no target selector needed (auto-discovers all).

**Zone options:** Add zone party mode section — source ATV pre-populated from zone's existing ATV exclusion config; target ATVs use `EntitySelector(multiple=True)`.

---

## pyatv Version Pinning

```bash
# On HA host, check current version:
pip show pyatv
```

```json
// manifest.json
"requirements": ["pyatv==0.15.1"]  // pin to match HA's apple_tv integration
```

Update pin whenever HA bumps its apple_tv integration version.

---

## Credential Discovery Pattern

```python
async def get_atv_credentials(hass, media_player_entity_id):
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(media_player_entity_id)
    if not entity_entry:
        return None
    config_entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if not config_entry or config_entry.domain != "apple_tv":
        return None
    return {
        "address": config_entry.data.get("address"),
        "credentials": config_entry.data.get("credentials", {}),
    }
```

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Source ATV not paired in HA | Party mode switch unavailable; config flow shows warning |
| Target ATV offline | Skip that ATV, log warning, continue with rest |
| pyatv import failure | Party mode entities hidden; log warning; rest of DCA unaffected |
| Zone party + system party both active | System party takes precedence; zone party noop |
| Local ATV starts playing video during party | ATV breaks out to local (bypass_app_ids doesn't match), zone goes `atv_override`, other zones unaffected |
| Zone has an `amp_switch`-guarded exclusion | Exclusion NOT suspended even during party mode (see amp_switch safety rule above); room still gets synced audio via its own ATV + amp_switch |
| HA restart with party mode ON | `RestoreEntity` restores switch → coordinator re-enables party on setup |
| AirPlay 2 group limit | ~50 devices max; not a practical concern |

---

## Latency / Sync — What's Actually Achievable

**ATV-to-ATV sync is automatic and needs no extra code.** AirPlay 2's `set_output_devices()` grouping is built on a shared clock/timestamp protocol between grouped devices specifically so they play in sample-accurate sync. Grouping ATVs via `pyatv_bridge.group_atvs()` is sufficient — there is no separate sync step to implement.

**HTD-central-zone-to-ATV sync is a separate, unsolved problem.** Central audio reaches HTD zone amps through a completely different signal path (whatever line-level/network distribution HTD uses, driven by the system's `watcher_entity`/source config) — it never passes through pyatv or the AirPlay 2 group. There is no shared clock between "HTD zone amp playing the central source" and "ATVs playing the AirPlay 2 group." A zone with **both** an HTD amp (central, exclusion suspended) and a grouped ATV playing the same source will likely have an audible, uncorrected delay between the two.

pyatv (as of the versions checked during this implementation) does not expose a per-device latency/offset control that could compensate for this. No synthetic delay-compensation feature was built, since there's no measurable ground truth to correct against without new instrumentation (e.g. mic-based measurement) — that's out of scope. **This is a known, documented limitation**, not an oversight: Party Mode syncs ATVs to each other; a zone's own HTD amp may lag slightly behind the AirPlay group.

---

## Version & Release

- **Target:** `v0.4.0` — first major feature beyond core follow-me architecture
- **Breaking changes:** None — fully additive, opt-in via config checkbox
- **CHANGELOG:** `Add Party Mode — AirPlay 2 multiroom grouping for local ATV amps, system-wide and per-zone`

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `pyatv_bridge.py` | **New** — credential discovery, connect, discover_all, group/ungroup |
| `coordinator.py` | System: `async_enable/disable_party_mode`, auto-trigger; Zone: zone party enable/disable |
| `switch.py` | `PartyModeSwitch` (system) + `ZonePartyModeSwitch` (zone) |
| `sensor.py` | `PartyModeStatusSensor` + `ZonePartyStatusSensor` |
| `config_flow.py` | System options: party mode section; Zone options: zone party section |
| `const.py` | `STATUS_PARTY_*`, `CONF_PARTY_*`, `CONF_ZONE_PARTY_*` |
| `manifest.json` | Add pyatv pinned requirement |
| `__init__.py` | Register new entities on platform setup |

---

## Verification

1. System party: enable via config, start playing Music on living room ATV → all ATVs join → confirm audio on garage, family, master bed ATVs
2. Zone party: enable for family room zone, select garage + master bed as targets → start family room ATV → only those two join
3. Auto-off: stop source ATV → party mode disables, ATVs leave group
4. Exclusion behavior: play video on garage ATV during party → garage breaks out to local, party continues elsewhere
5. HA restart: party was on → restores correctly on startup
6. System + zone party overlap: both enabled → system takes precedence, no double-grouping errors
