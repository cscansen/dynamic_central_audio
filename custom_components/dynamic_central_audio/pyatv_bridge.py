"""pyatv wrapper for Party Mode AirPlay 2 grouping.

Isolated so the rest of the integration degrades gracefully (Party Mode
entities simply become unavailable) if pyatv is missing or fails to import —
no other part of Dynamic Central Audio depends on this module.
"""

import logging
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

try:
    import pyatv
    from pyatv.const import Protocol
    PYATV_AVAILABLE = True
except ImportError:
    pyatv = None
    Protocol = None
    PYATV_AVAILABLE = False
    _LOGGER.warning("pyatv not available — Party Mode will be unavailable")


async def get_atv_credentials(hass: HomeAssistant, media_player_entity_id: str) -> Optional[dict]:
    """Pull address/credentials from the existing apple_tv config entry backing this entity."""
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(media_player_entity_id)
    if not entity_entry or not entity_entry.config_entry_id:
        return None
    config_entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if not config_entry or config_entry.domain != "apple_tv":
        return None
    return {
        "address": config_entry.data.get("address"),
        "identifier": config_entry.data.get("identifier"),
        "credentials": config_entry.data.get("credentials", {}),
        "name": config_entry.data.get("name", media_player_entity_id),
    }


async def discover_all_atvs(hass: HomeAssistant) -> list[dict]:
    """Return credential dicts for every media_player entity backed by the apple_tv integration."""
    if not PYATV_AVAILABLE:
        return []
    results = []
    entity_registry = er.async_get(hass)
    for entry in hass.config_entries.async_entries("apple_tv"):
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        media_player_entities = [e for e in entities if e.domain == "media_player"]
        if not media_player_entities:
            continue
        creds = await get_atv_credentials(hass, media_player_entities[0].entity_id)
        if creds:
            creds["entity_id"] = media_player_entities[0].entity_id
            results.append(creds)
    return results


async def connect_atv(credentials: dict):
    """Open a pyatv connection to the given ATV. Returns None on failure."""
    if not PYATV_AVAILABLE or not credentials:
        return None
    try:
        atvs = await pyatv.scan(
            loop=None,
            identifier=credentials.get("identifier"),
            hosts=[credentials["address"]] if credentials.get("address") else None,
        )
        if not atvs:
            _LOGGER.warning("pyatv scan found no device for %s", credentials.get("name"))
            return None
        config = atvs[0]
        for protocol, creds in (credentials.get("credentials") or {}).items():
            try:
                proto = Protocol[protocol.upper()]
                config.set_credentials(proto, creds)
            except (KeyError, ValueError):
                continue
        return await pyatv.connect(config, loop=None)
    except Exception:
        _LOGGER.exception("Failed to connect to ATV %s", credentials.get("name"))
        return None


async def group_atvs(source_connection, target_credentials: list[dict]) -> bool:
    """Add target ATVs to the source ATV's AirPlay 2 output group."""
    if not source_connection:
        return False
    try:
        available = await source_connection.audio.output_devices()
        target_addresses = {c["address"] for c in target_credentials if c.get("address")}
        selected = [d for d in available if getattr(d, "address", None) in target_addresses]
        if not selected:
            _LOGGER.warning("Party Mode: no matching output devices found among targets")
            return False
        await source_connection.audio.set_output_devices(selected)
        return True
    except Exception:
        _LOGGER.exception("Failed to group ATVs for Party Mode")
        return False


async def ungroup_atvs(source_connection) -> bool:
    """Remove all added output devices, restoring source-only playback."""
    if not source_connection:
        return False
    try:
        await source_connection.audio.set_output_devices([])
        return True
    except Exception:
        _LOGGER.exception("Failed to ungroup ATVs for Party Mode")
        return False
