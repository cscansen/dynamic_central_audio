"""Fancy Audio view — pure, no Home Assistant imports (unit-testable).

Opt-in (`rebuild_dashboard` with `style: fancy`). Needs these frontend cards installed (HACS):
button-card, card-mod and mini-media-player. `__init__.py` checks for them and falls back to the
standard layout when any is missing.

Layout (sections view, three columns on wide screens, stacked on phones):
  1. "Audio" header + who's playing, album-art hero per playing source (or a "Nothing playing"
     placeholder), then each system's whole-house toggles.
  2-3. One panel per zone (split across two columns): status header, Speaker / Follow me / In party
     toggles, and the Volume (offset) slider. An active zone's panel glows.

Colours come from optional `--glow-*` theme variables (see README, "Fancy dashboard") and fall back to
the standard HA theme variables, so it renders sensibly with any theme.
"""

from __future__ import annotations

import json

# Mirrors const.py (kept literal so this module stays importable without the package).
ACTIVE_ZONE = ["following", "party_active", "atv_override"]
STATUS_TEXT = {"following": "Playing", "party_active": "Party", "atv_override": "Apple TV",
               "standby": "Standby", "follow_me_off": "Follow me off",
               "system_inactive": "Central audio off", "no_system": "Not linked", "idle": "Idle"}
REQUIRED_CARDS = ("button-card", "card-mod", "mini-media-player")

_FALLBACK = {
    "glow-card": "var(--ha-card-background, var(--card-background-color))",
    "glow-card-hi": "var(--secondary-background-color)",
    "glow-line": "var(--divider-color)",
    "glow-accent": "var(--primary-color)",
    "glow-fill": "rgba(var(--rgb-primary-color), 0.18)",
    "glow-border": "rgba(var(--rgb-primary-color), 0.40)",
    "glow-border-strong": "rgba(var(--rgb-primary-color), 0.55)",
    "glow-shadow": "none",
    "glow-card-shadow": "none",
    "glow-blur": "none",
    "glow-text": "var(--primary-text-color)",
    "glow-muted": "var(--secondary-text-color)",
    "glow-faint": "var(--disabled-text-color)",
}


def v(name: str) -> str:
    """CSS var() for a --glow-* variable, falling back to the standard HA theme variable."""
    return f"var(--{name}, {_FALLBACK[name]})"


def _css(rules: dict[str, list[str]]) -> dict[str, list[dict]]:
    """button-card styles: each rule as a {property: value} mapping."""
    return {part: [dict([r.split(": ", 1)]) for r in lst] for part, lst in rules.items()}


GLOW = _css({"card": [f"background: {v('glow-fill')}", f"border: 1px solid {v('glow-border')}",
                      f"box-shadow: {v('glow-shadow')}"],
             "icon": [f"color: {v('glow-accent')}"]})
IS_ON = "[[[ return !!entity && !['off','unavailable','unknown','standby'].includes(entity.state) ]]]"

TEMPLATES = {
    "dca_base": {
        "show_label": True, "show_state": False,
        "styles": _css({
            "card": ["padding: 14px 16px", "border-radius: 20px", f"background: {v('glow-card')}",
                     f"border: 1px solid {v('glow-line')}", f"box-shadow: {v('glow-card-shadow')}", "height: 100%",
                     f"backdrop-filter: {v('glow-blur')}", f"-webkit-backdrop-filter: {v('glow-blur')}"],
            "grid": ['grid-template-areas: "i n" "i l"', "grid-template-columns: 36px 1fr",
                     "grid-template-rows: min-content min-content", "column-gap: 12px", "align-content: center"],
            "img_cell": ["justify-content: center"],
            "icon": ["width: 24px", f"color: {v('glow-muted')}"],
            "name": ["justify-self: start", "font-size: 15px", "font-weight: 500", f"color: {v('glow-text')}"],
            "label": ["justify-self: start", "font-size: 13px", f"color: {v('glow-muted')}"],
        }),
        "state": [{"id": "active", "operator": "template", "value": IS_ON, "styles": GLOW}],
    },
    "dca_toggle": {
        "template": "dca_base", "tap_action": {"action": "toggle"}, "hold_action": {"action": "more-info"},
        "label": "[[[ return !entity ? 'Missing' : ['off','unavailable','unknown','standby']"
                 ".includes(entity.state) ? 'Off' : 'On' ]]]",
    },
    "dca_pill": {
        "template": "dca_toggle", "show_label": False,
        "styles": _css({"card": ["padding: 10px 6px", "border-radius: 16px", f"background: {v('glow-card-hi')}"],
                        "grid": ['grid-template-areas: "i" "n"', "grid-template-columns: 1fr",
                                 "grid-template-rows: min-content min-content", "row-gap: 4px"],
                        "img_cell": ["height: 26px"], "icon": ["width: 22px"],
                        "name": ["justify-self: center", "font-size: 12px"]}),
    },
    "dca_heading": {
        "show_icon": False, "show_label": True, "tap_action": {"action": "none"},
        "styles": _css({"card": ["background: none", "border: none", "box-shadow: none", "padding: 4px 4px 0"],
                        "grid": ['grid-template-areas: "n l"', "grid-template-columns: max-content 1fr",
                                 "column-gap: 10px", "align-items: end"],
                        "name": ["justify-self: start", "font-size: 22px", "font-weight: 500",
                                 f"color: {v('glow-text')}"],
                        "label": ["justify-self: start", "font-size: 14px", f"color: {v('glow-muted')}",
                                  "padding-bottom: 3px"]}),
    },
}


def _btn(template: str, **cfg) -> dict:
    return {"type": "custom:button-card", "template": template, **cfg}


def _audio_column(systems: list[dict], zones: list[dict]) -> dict:
    pairs = json.dumps([[z["status"], z["title"]] for z in zones])
    header = _btn("dca_heading", name="Audio", grid_options={"columns": 12},
                  label=(f"[[[ const z = {pairs}.filter(([e]) => {json.dumps(ACTIVE_ZONE)}.includes("
                         "states[e]?.state)).map(([, t]) => t); "
                         "return z.length ? 'Playing in ' + z.join(' · ') : 'Nothing playing' ]]]"),
                  styles=_css({"name": ["font-size: 40px", "font-weight: 300", "letter-spacing: -0.5px"],
                               "grid": ['grid-template-areas: "n" "l"', "grid-template-columns: 1fr",
                                        "row-gap: 2px"]}))
    cards = [header]
    watchers = [(src["watcher"], src["name"]) for s in systems for src in s["sources"] if src.get("watcher")]
    for ent, name in watchers:
        cards.append({
            "type": "custom:mini-media-player", "entity": ent, "name": name, "artwork": "full-cover",
            "info": "scroll", "grid_options": {"columns": 12},
            "hide": {"power": True, "volume": True, "source": True, "sound_mode": True, "icon": True,
                     "progress": False, "runtime": False},
            "card_mod": {"style": f"ha-card {{ border-radius: 24px; min-height: 240px; overflow: hidden;"
                                  f" border: 1px solid {v('glow-line')}; }}"},
            "visibility": [{"condition": "state", "entity": ent, "state": "playing"}],
        })
    if watchers:
        cards.append(_btn(
            "dca_base", icon="mdi:music-note-outline", name="Nothing playing", grid_options={"columns": 12},
            label="Start a source and it shows here", tap_action={"action": "none"},
            styles=_css({"card": ["min-height: 150px", "border-style: dashed"],
                         "grid": ['grid-template-areas: "i" "n" "l"', "grid-template-columns: 1fr",
                                  "row-gap: 6px"],
                         "icon": ["width: 36px", f"color: {v('glow-faint')}"],
                         "name": ["justify-self: center", "font-size: 18px", f"color: {v('glow-muted')}"],
                         "label": ["justify-self: center", f"color: {v('glow-faint')}"]}),
            visibility=[{"condition": "not", "conditions": [{"condition": "or", "conditions": [
                {"condition": "state", "entity": e, "state": "playing"} for e, _ in watchers]}]}],
        ))
    for s in systems:
        cards.append(_btn("dca_heading", name="Whole house" if len(systems) == 1 else s["title"],
                          grid_options={"columns": 12},
                          label=f"[[[ return states['{s['active']}']?.state === 'on' ? 'active' : 'off' ]]]"))
        toggles = [(s["active"], "Central audio", "mdi:power"), (s["party"], "Party mode", "mdi:party-popper")]
        toggles += [(src["follow_me"], f"{src['name']} follow me", "mdi:music-note-plus") for src in s["sources"]]
        cards += [_btn("dca_toggle", entity=e, name=n, icon=i, grid_options={"columns": 6}) for e, n, i in toggles]
    return {"type": "grid", "column_span": 1, "cards": cards}


def _zone_panel(zone: dict) -> dict:
    header = _btn(
        "dca_heading", entity=zone["status"], name=zone["title"], tap_action={"action": "more-info"},
        label=(f"[[[ const t = {json.dumps(STATUS_TEXT)}; const o = Math.round(parseFloat("
               f"states['{zone['volume']}']?.state || 0) * 100); return (t[entity?.state] || entity?.state || '—')"
               " + ' · vol ' + (o > 0 ? '+' : '') + o ]]]"),
        state=[{"id": "active", "operator": "template",
                "value": f"[[[ return {json.dumps(ACTIVE_ZONE)}.includes(entity?.state) ]]]",
                "styles": _css({"label": [f"color: {v('glow-accent')}"]})}],
        styles=_css({"name": ["font-size: 19px"]}),
    )
    toggles = ([(zone["speaker"], "Speaker", "mdi:speaker")] if zone.get("speaker") else []) + [
        (zone["follow_me"], "Follow me", "mdi:walk"), (zone["party"], "In party", "mdi:party-popper")]
    volume = {"type": "tile", "entity": zone["volume"], "name": "Volume vs. source", "icon": "mdi:volume-high",
              "features": [{"type": "numeric-input", "style": "slider"}],
              "card_mod": {"style": f"ha-card {{ background: {v('glow-card-hi')}; border-radius: 16px; }}"}}
    active = f"states('{zone['status']}') in {ACTIVE_ZONE}"
    panel_css = (f"#root {{ background: {v('glow-card')}; border: 1px solid {v('glow-line')};"
                 " border-radius: 24px; padding: 10px 12px 12px; gap: 8px !important;"
                 f" box-shadow: {v('glow-card-shadow')}; backdrop-filter: {v('glow-blur')};"
                 f" -webkit-backdrop-filter: {v('glow-blur')};"
                 f"{{% if {active} %}} border-color: {v('glow-border-strong')};"
                 f" box-shadow: {v('glow-shadow')};{{% endif %}} }}")
    return {"type": "vertical-stack", "grid_options": {"columns": 12}, "card_mod": {"style": panel_css},
            "cards": [header, {"type": "horizontal-stack",
                               "cards": [_btn("dca_pill", entity=e, name=n, icon=i) for e, n, i in toggles]},
                      volume]}


def build_fancy_main(systems: list[dict], zones: list[dict]) -> tuple[dict, dict]:
    """Return (button_card_templates, sections) for the fancy Audio view."""
    half = (len(zones) + 1) // 2
    sections = [_audio_column(systems, zones)]
    sections += [{"type": "grid", "cards": [_zone_panel(z) for z in col]} for col in (zones[:half], zones[half:])
                 if col]
    return TEMPLATES, sections
