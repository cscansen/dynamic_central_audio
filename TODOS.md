# Dynamic Central Audio — Deferred Work

## v0.2.0 — Changes after v0.1.0 testing

### UI / Label Fixes
- [ ] Rename "Reference zone entity" field label in system config flow to something like "Any zone media player" with description clarifying: pick any zone from your audio system — its `source_list` is used to discover available inputs. The current label implies a special entity that doesn't exist.

### Features
- [ ] Per-source follow-me switch — integration creates `switch.dynamic_central_audio_<system>_<source>_follow_me` for each source; replaces gate_entity/gate_state config fields; defaults ON; RestoreEntity. Coordinator checks switch state before treating source as active. **Note:** current gate_entity field is optional/skippable in v0.1.0 but is effectively required for sources like LR ATV — the per-source switch fixes this by always creating it.

## Future / v2+

- [ ] Staircase prewarm: `binary_sensor.stairs_occupied` → pre-activate main_floor + second_floor
- [ ] Sonos group-join zone activation mode
- [ ] Dynamic runtime `source_list` change detection
- [ ] Per-zone source_off_delay override
- [ ] Secondary gate condition per source — "only follow if X entity is in Y state" (e.g. person home, time of day); needed for exotic conditions beyond the per-source follow-me switch
