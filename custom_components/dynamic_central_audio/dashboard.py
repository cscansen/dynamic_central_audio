"""Lovelace dashboard builder — pure, no Home Assistant imports (unit-testable).

`build_dashboard()` returns a Lovelace config (`{"views": [...]}`) with two views:

  Audio        — whole-house controls and now playing, then one section per zone:
                 speaker power, Follow Me, Volume (the zone's offset) and zone Party Mode.
  Diagnostics  — the routing reasoning for the system and every zone.

Volume is the zone's volume offset, not the speaker's own volume. While a zone follows a
source, DCA re-applies base_volume + offset every scan, so a raw speaker slider would
snap back; the offset is the control that sticks.

Entity IDs are resolved by the caller from the entity registry and passed in. The
`dynamic_central_audio.rebuild_dashboard` action in `__init__.py` does that and saves it.
"""

from __future__ import annotations

FULL = {"columns": 12}
HALF = {"columns": 6}


def _toggle(entity: str, name: str, icon: str | None = None, **extra) -> dict:
    card = {"type": "tile", "entity": entity, "name": name, "tap_action": {"action": "toggle"},
            "grid_options": HALF, **extra}
    if icon:
        card["icon"] = icon
    return card


def _system_section(system: dict) -> dict:
    sources = system.get("sources", [])
    cards: list[dict] = [
        {"type": "heading", "heading": system["title"], "icon": "mdi:speaker-multiple",
         "badges": [{"type": "entity", "entity": system["status"], "show_state": True, "show_icon": True}]},
        _toggle(system["active"], "Central audio", "mdi:power"),
        _toggle(system["party"], "Party mode (whole house)", "mdi:party-popper"),
    ]
    cards += [_toggle(s["follow_me"], f"{s['name']} follow me", "mdi:music-note-plus") for s in sources]

    # Now playing: a media card per source while it plays, else a single "nothing playing" line.
    for s in sources:
        if s.get("watcher"):
            cards.append({"type": "media-control", "entity": s["watcher"], "name": s["name"],
                          "grid_options": FULL,
                          "visibility": [{"condition": "state", "entity": s["watcher"], "state": "playing"}]})
    watchers = [s["watcher"] for s in sources if s.get("watcher")]
    if watchers:
        cards.append({"type": "markdown", "content": "*Nothing playing*", "grid_options": FULL,
                      "visibility": [{"condition": "state", "entity": w, "state_not": "playing"} for w in watchers]})
    return {"type": "grid", "column_span": 2, "cards": cards}


def _zone_section(zone: dict) -> dict:
    cards: list[dict] = [
        {"type": "heading", "heading": zone["title"],
         "badges": [{"type": "entity", "entity": zone["status"], "show_state": True, "show_icon": True}]},
    ]
    if zone.get("speaker"):
        cards.append(_toggle(zone["speaker"], "Speaker", "mdi:speaker"))
    cards.append(_toggle(zone["follow_me"], "Follow me", "mdi:walk"))
    cards.append({"type": "tile", "entity": zone["volume"], "name": "Volume (vs. source)",
                  "icon": "mdi:volume-high", "grid_options": FULL,
                  "features": [{"type": "numeric-input", "style": "slider"}]})
    cards.append(_toggle(zone["party"], "Include in party", "mdi:party-popper"))
    return {"type": "grid", "cards": cards}


def _reasoning_markdown(title: str, status: str) -> dict:
    return {"type": "markdown", "grid_options": FULL, "content": (
        f"**{title}** — {{{{ states('{status}') }}}}\n"
        f"{{% set r = state_attr('{status}', 'reasoning') %}}"
        "{% if r %}\n```\n{{ r }}\n```{% else %}\n*No data*{% endif %}"
    )}


def build_dashboard(systems: list[dict], zones: list[dict]) -> dict:
    """systems: [{title, status, active, party, party_status, sources: [{name, follow_me, watcher}]}]
    zones:   [{title, status, follow_me, volume, party, speaker?}] — all resolved entity IDs."""
    diag = []
    for s in systems:
        diag.append(_reasoning_markdown(s["title"], s["status"]))
        if s.get("party_status"):
            diag.append({"type": "tile", "entity": s["party_status"], "name": "Party mode status",
                         "grid_options": FULL})
    diag += [_reasoning_markdown(z["title"], z["status"]) for z in zones]
    return {"views": [
        {"title": "Audio", "path": "main", "icon": "mdi:music-note", "type": "sections", "max_columns": 3,
         "sections": [*map(_system_section, systems), *map(_zone_section, zones)]},
        {"title": "Diagnostics", "path": "diagnostics", "icon": "mdi:stethoscope", "type": "sections",
         "max_columns": 2, "sections": [{"type": "grid", "column_span": 2, "cards": diag}]},
    ]}
