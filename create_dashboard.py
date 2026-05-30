#!/usr/bin/env python3
"""Build and push the Dynamic Central Audio Lovelace dashboard."""

import asyncio
import json
import os
import re
import sys
import websockets

HA_URL = "ws://ha.iot.scansenconsulting.com:8123/api/websocket"
HA_TOKEN = os.environ.get("HA_TOKEN", "")
DASHBOARD_PATH = "dashboard-audio"
DOMAIN = "dynamic_central_audio"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


async def ws_send(ws, msg: dict) -> dict:
    await ws.send(json.dumps(msg))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg.get("id"):
            return data
        if data.get("type") == "event":
            continue


async def get_config_entries(ws) -> list[dict]:
    resp = await ws_send(ws, {"id": 2, "type": "config_entries/get", "domain": DOMAIN})
    return resp.get("result", [])


def zone_card(zone_name: str) -> dict:
    slug = slugify(zone_name)
    status_entity = f"sensor.{DOMAIN}_{slug}_status"
    follow_entity = f"switch.{DOMAIN}_{slug}_follow_me"
    volume_entity = f"number.{DOMAIN}_{slug}_volume_offset"

    return {
        "type": "vertical-stack",
        "cards": [
            {
                "type": "entities",
                "title": zone_name,
                "entities": [
                    {"entity": follow_entity, "name": "Follow Me"},
                    {"entity": status_entity, "name": "Status"},
                    {"entity": volume_entity, "name": "Volume Offset"},
                ],
            },
            {
                "type": "markdown",
                "content": (
                    f"{{% set r = state_attr('{status_entity}', 'reasoning') %}}"
                    "{% if r %}`{{ r }}`{% else %}No data{% endif %}"
                ),
            },
        ],
    }


def system_card(system_name: str, sources: list[dict]) -> dict:
    slug = slugify(system_name)
    status_entity = f"sensor.{DOMAIN}_{slug}_status"
    active_entity = f"switch.{DOMAIN}_{slug}_active"

    entities = [
        {"entity": active_entity, "name": "System Active"},
        {"entity": status_entity, "name": "Active Source"},
    ]
    for src in sources:
        src_slug = slugify(src.get("display_name", "source"))
        entities.append({
            "entity": f"switch.{DOMAIN}_{slug}_{src_slug}_follow_me",
            "name": f"{src.get('display_name', 'Source')} Follow Me",
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
                    "{% if r %}`{{ r }}`{% else %}No data{% endif %}"
                ),
            },
        ],
    }


def build_dashboard(systems: list[dict], zones: list[dict]) -> dict:
    cards = [{"type": "heading", "heading": "Dynamic Central Audio", "heading_style": "title"}]

    for sys_entry in systems:
        data = {**sys_entry.get("data", {}), **sys_entry.get("options", {})}
        sources = data.get("sources", [])
        cards.append(system_card(sys_entry["title"], sources))

    if zones:
        cards.append({"type": "heading", "heading": "Zones", "heading_style": "subtitle"})
        # Pair zones into rows of 2
        zone_cards = [zone_card(z["title"]) for z in zones]
        for i in range(0, len(zone_cards), 2):
            pair = zone_cards[i:i+2]
            if len(pair) == 2:
                cards.append({"type": "grid", "columns": 2, "square": False, "cards": pair})
            else:
                cards.append(pair[0])

    return {
        "title": "Audio",
        "path": DASHBOARD_PATH,
        "icon": "mdi:music-note",
        "views": [{"title": "Audio", "path": "main", "cards": cards}],
    }


async def main():
    if not HA_TOKEN:
        print("ERROR: HA_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    async with websockets.connect(HA_URL) as ws:
        # Auth
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth_result = json.loads(await ws.recv())
        assert auth_result["type"] == "auth_ok", f"Auth failed: {auth_result}"

        entries = await get_config_entries(ws)
        systems = [e for e in entries if e.get("data", {}).get("entry_type") == "system"]
        zones = [e for e in entries if e.get("data", {}).get("entry_type") == "zone"]

        print(f"Found {len(systems)} system(s), {len(zones)} zone(s)")
        for s in systems:
            print(f"  System: {s['title']}")
        for z in zones:
            print(f"  Zone:   {z['title']}")

        dashboard = build_dashboard(systems, zones)

        # Push to HA
        resp = await ws_send(ws, {
            "id": 10,
            "type": "lovelace/config/save",
            "url_path": DASHBOARD_PATH,
            "config": dashboard,
        })

        if resp.get("success"):
            print(f"\n✓ Dashboard pushed to /{DASHBOARD_PATH}")
        else:
            print(f"\n✗ Failed: {resp}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
