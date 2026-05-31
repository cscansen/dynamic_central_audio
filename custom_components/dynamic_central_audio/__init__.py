"""Dynamic Central Audio integration."""

import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, ENTRY_TYPE_SYSTEM, ENTRY_TYPE_ZONE
from .coordinator import SystemCoordinator, ZoneCoordinator, _excl_entities

_LOGGER = logging.getLogger(__name__)

PLATFORMS_SYSTEM: Final[list[str]] = ["sensor", "switch"]
PLATFORMS_ZONE: Final[list[str]] = ["sensor", "switch", "number"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    entry_type = entry.data.get("entry_type")

    try:
        if entry_type == ENTRY_TYPE_SYSTEM:
            return await _setup_system_entry(hass, entry)
        elif entry_type == ENTRY_TYPE_ZONE:
            return await _setup_zone_entry(hass, entry)
        else:
            _LOGGER.error("Unknown entry_type: %s", entry_type)
            return False
    except Exception as e:
        _LOGGER.error("Error setting up entry %s: %s", entry.entry_id, e, exc_info=True)
        raise


async def _setup_system_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = {**entry.data, **entry.options}
    coordinator = SystemCoordinator(hass, config, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    # Watch source watcher entities and app_filter_entity entities
    watch_entities: set[str] = set()
    for source in coordinator.get_sources():
        watcher = source.get("watcher_entity")
        if watcher:
            watch_entities.add(watcher)
        app_filter = source.get("app_filter_entity")
        if app_filter:
            watch_entities.add(app_filter)

    if watch_entities:
        unsub = async_track_state_change_event(
            hass, list(watch_entities), coordinator.handle_source_change
        )
        entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_SYSTEM)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _setup_zone_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = {**entry.data, **entry.options}
    zone_name = entry.data.get("zone_name", "Zone")

    coordinator = ZoneCoordinator(hass, zone_name, config, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    # Watch occupancy sensors
    occ_sensors = config.get("occupancy_sensors", [])
    if occ_sensors:
        unsub = async_track_state_change_event(
            hass, occ_sensors, coordinator.handle_occupancy_change
        )
        entry.async_on_unload(unsub)

    # Watch ATV entities (supports both atv_entities list and legacy atv_entity)
    atv_entities = [
        entity
        for excl in config.get("atv_exclusions", [])
        for entity in _excl_entities(excl)
    ]
    if atv_entities:
        unsub = async_track_state_change_event(
            hass, atv_entities, coordinator.handle_atv_change
        )
        entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ZONE)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type")
    platforms = PLATFORMS_SYSTEM if entry_type == ENTRY_TYPE_SYSTEM else PLATFORMS_ZONE

    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(coord, ZoneCoordinator):
        coord._cancel_all_deactivate_timers()
        coord._cancel_all_restore_timers()
        coord._cancel_follow_me_reset()

    if await hass.config_entries.async_unload_platforms(entry, platforms):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
