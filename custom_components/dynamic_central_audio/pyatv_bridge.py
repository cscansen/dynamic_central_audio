"""pyatv wrapper for Party Mode AirPlay 2 grouping.

Isolated so the rest of the integration degrades gracefully (Party Mode
entities simply become unavailable) if pyatv is missing or fails to import —
no other part of Dynamic Central Audio depends on this module.
"""

import asyncio
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
    # HA's apple_tv config entry stores a list of equivalent identifiers (MAC,
    # UUID, and MAC-without-colons) under "identifiers" — not a single "identifier"
    # key — since pyatv's own OutputDevice.identifier may report any one of these
    # forms depending on protocol.
    return {
        "address": config_entry.data.get("address"),
        "identifiers": config_entry.data.get("identifiers", []),
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
        loop = asyncio.get_running_loop()
        # Filter by host only — the identifiers list has multiple formats (MAC,
        # UUID, MAC-without-colons) and passing the wrong one to scan's identifier=
        # filter would just exclude the device instead of finding it.
        atvs = await pyatv.scan(
            loop=loop,
            hosts=[credentials["address"]] if credentials.get("address") else None,
        )
        if not atvs:
            _LOGGER.warning("pyatv scan found no device for %s", credentials.get("name"))
            return None
        config = atvs[0]
        for protocol, creds in (credentials.get("credentials") or {}).items():
            # HA's apple_tv config entry stores credential keys as the protocol's
            # numeric enum value (e.g. "3"), not its name — Protocol["3"] raises
            # KeyError every time, which a bare except previously swallowed silently,
            # leaving the connection with no credentials applied at all (hence
            # pyatv.exceptions.NotSupportedError: output_devices is not supported —
            # the unauthenticated relay doesn't expose the multi-room audio interface).
            try:
                proto = Protocol(int(protocol))
            except (ValueError, TypeError):
                try:
                    proto = Protocol[str(protocol).upper()]
                except KeyError:
                    _LOGGER.warning("Unrecognized pyatv protocol key %r for %s — skipping", protocol, credentials.get("name"))
                    continue
            config.set_credentials(proto, creds)
        return await pyatv.connect(config, loop=loop)
    except Exception:
        _LOGGER.exception("Failed to connect to ATV %s", credentials.get("name"))
        return None


async def group_atvs(source_connection, target_credentials: list[dict]) -> bool:
    """Add target ATVs to the source ATV's AirPlay 2 output group."""
    if not source_connection:
        return False
    try:
        # output_devices is a property (returns the current list directly), not
        # an async method — and set_output_devices takes *devices variadic args,
        # not a single list argument.
        available = source_connection.audio.output_devices
        # pyatv.interface.OutputDevice only has identifier/name/volume — no address —
        # so match on identifier. HA's apple_tv config entry stores THREE equivalent
        # formats per device (MAC, UUID, MAC-without-colons) since pyatv's own
        # OutputDevice.identifier may report any one of them; match against all.
        target_identifiers = {
            ident for c in target_credentials for ident in (c.get("identifiers") or [])
        }
        selected = [d for d in available if getattr(d, "identifier", None) in target_identifiers]
        if not selected:
            _LOGGER.warning(
                "Party Mode: no matching output devices found among targets. "
                "Available: %s. Target identifiers: %s",
                [(d.name, d.identifier) for d in available], target_identifiers,
            )
            return False
        await source_connection.audio.set_output_devices(*selected)
        return True
    except Exception:
        _LOGGER.exception("Failed to group ATVs for Party Mode")
        return False


async def ungroup_atvs(source_connection) -> bool:
    """Remove all added output devices, restoring source-only playback."""
    if not source_connection:
        return False
    try:
        # No args = clear the group (see group_atvs — *devices is variadic, so
        # passing [] as a single positional arg is wrong here too).
        await source_connection.audio.set_output_devices()
        return True
    except Exception:
        _LOGGER.exception("Failed to ungroup ATVs for Party Mode")
        return False
