"""Unit tests for dashboard.py — pure builder, no HA required."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "dynamic_central_audio"))

from dashboard import build_dashboard

D = "dynamic_central_audio"
SYSTEM = {
    "title": "Central Audio",
    "status": f"sensor.{D}_central_audio_status",
    "active": f"switch.{D}_central_audio_active",
    "party": f"switch.{D}_central_audio_party_mode",
    "party_status": f"sensor.{D}_central_audio_party_mode_status",
    "sources": [
        {"name": "AirPlay (Central)", "follow_me": f"switch.{D}_central_audio_airplay_central_follow_me",
         "watcher": "media_player.central_airplay"},
        {"name": "Living Room Apple TV", "follow_me": f"switch.{D}_central_audio_living_room_apple_tv_follow_me",
         "watcher": "media_player.living_room_apple_tv"},
    ],
}
ZONE = {
    "title": "Garage",
    "status": f"sensor.{D}_garage_status",
    "follow_me": f"switch.{D}_garage_follow_me",
    "volume": f"number.{D}_garage_volume_offset",
    "party": f"switch.{D}_garage_party_mode",
    "speaker": "media_player.garage",
}


def _entities(obj, skip=("visibility",)):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip:
                continue
            if k == "entity" and isinstance(v, str):
                yield v
            else:
                yield from _entities(v, skip)
    elif isinstance(obj, list):
        for v in obj:
            yield from _entities(v, skip)


def _main():
    return build_dashboard([SYSTEM], [ZONE])["views"][0]


def test_views():
    views = build_dashboard([SYSTEM], [ZONE])["views"]
    assert [v["title"] for v in views] == ["Audio", "Diagnostics"]
    assert views[0]["path"] == "main"  # existing links keep working


def test_whole_house_party_mode_only_once():
    ids = list(_entities(_main()))
    assert ids.count(SYSTEM["party"]) == 1


def test_zone_keeps_its_own_party_switch_speaker_and_volume():
    zone = _main()["sections"][1]
    ids = set(_entities(zone))
    assert {ZONE["party"], ZONE["speaker"], ZONE["follow_me"], ZONE["volume"], ZONE["status"]} <= ids
    vol = next(c for c in zone["cards"] if c.get("entity") == ZONE["volume"])
    assert vol["features"][0]["type"] == "numeric-input"


def test_now_playing_per_source_and_nothing_playing_fallback():
    cards = _main()["sections"][0]["cards"]
    media = [c for c in cards if c["type"] == "media-control"]
    assert [c["entity"] for c in media] == ["media_player.central_airplay", "media_player.living_room_apple_tv"]
    assert all(c["visibility"][0]["state"] == "playing" for c in media)
    fallback = next(c for c in cards if c["type"] == "markdown")
    assert {v["entity"] for v in fallback["visibility"]} == {s["watcher"] for s in SYSTEM["sources"]}
    assert all(v["state_not"] == "playing" for v in fallback["visibility"])


def test_reasoning_only_on_diagnostics():
    main, diag = build_dashboard([SYSTEM], [ZONE])["views"]
    assert "reasoning" not in str(main)
    assert str(diag).count("reasoning") == 2  # system + one zone


def test_zone_without_speaker():
    zone = build_dashboard([], [{**ZONE, "speaker": None}])["views"][0]["sections"][0]
    assert "media_player.garage" not in set(_entities(zone))


# --- fancy style -------------------------------------------------------------------------------------

def _fancy(zones=(ZONE,), theme=None):
    return build_dashboard([SYSTEM], list(zones), "fancy", theme)


def test_standard_is_default_and_has_no_custom_cards():
    cfg = build_dashboard([SYSTEM], [ZONE])
    assert "button_card_templates" not in cfg
    assert "custom:" not in json.dumps(cfg)


def test_fancy_keeps_views_and_adds_templates():
    cfg = _fancy()
    assert [v["path"] for v in cfg["views"]] == ["main", "diagnostics"]
    assert set(cfg["button_card_templates"]) == {"dca_base", "dca_toggle", "dca_pill", "dca_heading"}
    assert cfg["views"][1] == build_dashboard([SYSTEM], [ZONE])["views"][1]  # diagnostics unchanged


def test_fancy_controls_every_entity_once():
    ids = list(_entities(_fancy()["views"][0]))
    for e in (SYSTEM["active"], SYSTEM["party"], ZONE["speaker"], ZONE["follow_me"], ZONE["party"], ZONE["volume"]):
        assert ids.count(e) == 1, e


def test_fancy_hero_per_source_and_nothing_playing():
    cards = _fancy()["views"][0]["sections"][0]["cards"]
    heroes = [c for c in cards if c["type"] == "custom:mini-media-player"]
    assert [c["entity"] for c in heroes] == [s["watcher"] for s in SYSTEM["sources"]]
    idle = next(c for c in cards if c.get("name") == "Nothing playing")
    watched = {c["entity"] for c in idle["visibility"][0]["conditions"][0]["conditions"]}
    assert watched == {s["watcher"] for s in SYSTEM["sources"]}


def test_fancy_splits_zones_into_two_columns():
    zones = [{**ZONE, "title": f"Z{i}", "status": f"sensor.z{i}"} for i in range(5)]
    sections = _fancy(zones)["views"][0]["sections"]
    assert [len(s["cards"]) for s in sections[1:]] == [3, 2]
    assert len(_fancy([ZONE])["views"][0]["sections"]) == 2  # no empty column


def test_fancy_zone_panel_glows_only_when_active():
    panel = _fancy()["views"][0]["sections"][1]["cards"][0]
    assert panel["type"] == "vertical-stack"
    assert f"states('{ZONE['status']}') in" in panel["card_mod"]["style"]


def test_fancy_colours_fall_back_to_standard_theme_vars():
    assert "var(--glow-accent, var(--primary-color))" in json.dumps(_fancy())


def test_fancy_zone_without_speaker():
    panel = _fancy([{**ZONE, "speaker": None}])["views"][0]["sections"][1]["cards"][0]
    assert len(panel["cards"][1]["cards"]) == 2


def test_theme_applies_to_both_views():
    assert {v.get("theme") for v in _fancy(theme="Glass")["views"]} == {"Glass"}
    assert all("theme" not in v for v in build_dashboard([SYSTEM], [ZONE])["views"])
