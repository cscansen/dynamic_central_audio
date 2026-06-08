#!/usr/bin/env python3
"""Build and push the Dynamic Central Audio Lovelace dashboard."""

import asyncio
import json
import os
import re
import sys
import urllib.request

import websockets

_HA_HOST = os.environ.get("HA_HOST", "homeassistant.local:8123")
HA_WS  = f"ws://{_HA_HOST}/api/websocket"
HA_API = f"http://{_HA_HOST}/api"
HA_TOKEN = os.environ.get("HA_TOKEN", "")
DASHBOARD_PATH = "dashboard-audio"
DOMAIN = "dynamic_central_audio"
PREFIX = f"switch.{DOMAIN}_"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


def deslugify(slug: str) -> str:
    return slug.replace("_", " ").title()


def ha_get(path: str) -> list | dict:
    req = urllib.request.Request(
        f"{HA_API}{path}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# ── Discovery via entity states ───────────────────────────────────────────────

def discover_entities() -> tuple[list[str], list[str]]:
    """Return (system_slugs, zone_slugs) by scanning entity IDs."""
    states = ha_get("/states")
    system_slugs, zone_slugs = [], []

    for state in states:
        eid = state["entity_id"]
        if not eid.startswith(f"switch.{DOMAIN}_"):
            continue
        slug = eid[len(f"switch.{DOMAIN}_"):]
        if slug.endswith("_active"):
            system_slugs.append(slug[: -len("_active")])
        elif slug.endswith("_follow_me"):
            # Distinguish zone follow-me from source follow-me:
            # source pattern: <system_slug>_<source_slug>_follow_me
            # zone pattern:   <zone_slug>_follow_me
            # Heuristic: if there's no matching _status sensor with the full
            # slug, it's a source switch — skip it; zones always have a sensor.
            zone_candidate = slug[: -len("_follow_me")]
            sensor_id = f"sensor.{DOMAIN}_{zone_candidate}_status"
            volume_id = f"number.{DOMAIN}_{zone_candidate}_volume_offset"
            has_sensor = any(s["entity_id"] == sensor_id for s in states)
            has_volume = any(s["entity_id"] == volume_id for s in states)
            if has_sensor and has_volume:
                zone_slugs.append(zone_candidate)

    return system_slugs, zone_slugs


def source_slugs_for_system(system_slug: str) -> list[str]:
    """Return source follow-me switch slugs for a system."""
    states = ha_get("/states")
    prefix = f"switch.{DOMAIN}_{system_slug}_"
    suffix = "_follow_me"
    slugs = []
    for state in states:
        eid = state["entity_id"]
        if eid.startswith(prefix) and eid.endswith(suffix):
            inner = eid[len(prefix): -len(suffix)]
            slugs.append(inner)
    return slugs


# ── Card builders ─────────────────────────────────────────────────────────────

def zone_card(zone_slug: str) -> dict:
    zone_name = deslugify(zone_slug)
    status_entity = f"sensor.{DOMAIN}_{zone_slug}_status"
    follow_entity  = f"switch.{DOMAIN}_{zone_slug}_follow_me"
    volume_entity  = f"number.{DOMAIN}_{zone_slug}_volume_offset"

    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "entities",
                "title": zone_name,
                "entities": [
                    {"entity": follow_entity,  "name": "Follow Me"},
                    {"entity": status_entity,  "name": "Status"},
                    {"entity": volume_entity,  "name": "Volume Offset"},
                ],
            },
            {
                "type": "markdown",
                "content": (
                    f"{{% set r = state_attr('{status_entity}', 'reasoning') %}}"
                    "{% if r %}```\n{{ r }}\n```{% else %}*No data*{% endif %}"
                ),
            },
        ],
    }


def system_card(system_slug: str) -> dict:
    system_name   = deslugify(system_slug)
    status_entity = f"sensor.{DOMAIN}_{system_slug}_status"
    active_entity = f"switch.{DOMAIN}_{system_slug}_active"
    source_slugs  = source_slugs_for_system(system_slug)

    entities = [
        {"entity": active_entity, "name": "System Active"},
        {"entity": status_entity, "name": "Active Source"},
    ]
    for src_slug in source_slugs:
        entities.append({
            "entity": f"switch.{DOMAIN}_{system_slug}_{src_slug}_follow_me",
            "name": f"{deslugify(src_slug)} Follow Me",
        })

    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "entities",
                "title": system_name,
                "entities": entities,
            },
            {
                "type": "markdown",
                "content": (
                    f"{{% set r = state_attr('{status_entity}', 'reasoning') %}}"
                    "{% if r %}```\n{{ r }}\n```{% else %}*No data*{% endif %}"
                ),
            },
        ],
    }


NOW_PLAYING_SOURCES = [
    # (watcher_entity, active_state, label)
    ("media_player.living_room_apple_tv", "playing", "Apple TV"),
    ("media_player.airplay_downstairs",   "playing", "AirPlay"),
]


def now_playing_cards() -> list[dict]:
    """Conditional media-control cards for each source — only shown when active."""
    return [
        {
            "type": "conditional",
            "conditions": [{"entity": entity, "state": state}],
            "card": {
                "type": "media-control",
                "entity": entity,
                "name": label,
            },
        }
        for entity, state, label in NOW_PLAYING_SOURCES
    ]


def build_dashboard(system_slugs: list[str], zone_slugs: list[str]) -> dict:
    cards = [{"type": "heading", "heading": "Dynamic Central Audio", "heading_style": "title"}]

    # Now Playing section — shows cover art for whichever source is active
    cards.append({"type": "heading", "heading": "Now Playing", "heading_style": "subtitle"})
    cards.extend(now_playing_cards())

    for slug in system_slugs:
        cards.append(system_card(slug))

    if zone_slugs:
        cards.append({"type": "heading", "heading": "Zones", "heading_style": "subtitle"})
        for z in zone_slugs:
            cards.append(zone_card(z))

    return {
        "title": "Audio",
        "views": [{"title": "Audio", "path": "main", "cards": cards}],
    }


# ── Websocket helpers ─────────────────────────────────────────────────────────

_ws_id = 0


def next_id() -> int:
    global _ws_id
    _ws_id += 1
    return _ws_id


async def ws_call(ws, msg: dict) -> dict:
    msg["id"] = next_id()
    await ws.send(json.dumps(msg))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg["id"]:
            return data


async def ensure_dashboard(ws) -> None:
    """Create the dashboard if it doesn't exist."""
    resp = await ws_call(ws, {"type": "lovelace/dashboards/list"})
    existing = [d.get("url_path") for d in (resp.get("result") or [])]
    if DASHBOARD_PATH not in existing:
        create = await ws_call(ws, {
            "type": "lovelace/dashboards/create",
            "url_path": DASHBOARD_PATH,
            "mode": "storage",
            "title": "Audio",
            "icon": "mdi:music-note",
            "show_in_sidebar": True,
        })
        if create.get("success"):
            print(f"  Created dashboard /{DASHBOARD_PATH}")
        else:
            print(f"  Dashboard creation response: {create}", file=sys.stderr)


async def main():
    if not HA_TOKEN:
        print("ERROR: HA_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    system_slugs, zone_slugs = discover_entities()
    print(f"Found {len(system_slugs)} system(s): {system_slugs}")
    print(f"Found {len(zone_slugs)} zone(s):   {zone_slugs}")

    if not system_slugs and not zone_slugs:
        print("No Dynamic Central Audio entities found — is the integration installed and configured?")
        sys.exit(1)

    dashboard = build_dashboard(system_slugs, zone_slugs)

    async with websockets.connect(HA_WS) as ws:
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth = json.loads(await ws.recv())
        assert auth["type"] == "auth_ok", f"Auth failed: {auth}"

        await ensure_dashboard(ws)

        resp = await ws_call(ws, {
            "type": "lovelace/config/save",
            "url_path": DASHBOARD_PATH,
            "config": dashboard,
        })

        if resp.get("success"):
            print(f"\n✓ Dashboard pushed → /{DASHBOARD_PATH}")
        else:
            print(f"\n✗ Save failed: {resp}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
