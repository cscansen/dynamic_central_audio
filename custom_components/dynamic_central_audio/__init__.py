"""Dynamic Central Audio integration."""

import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, ENTRY_TYPE_SYSTEM, ENTRY_TYPE_ZONE
from .coordinator import SystemCoordinator, ZoneCoordinator, _excl_entities
from .dashboard import STYLES, build_dashboard
from .dashboard_fancy import REQUIRED_CARDS
from .switch import _slugify

DEFAULT_DASHBOARD = "dashboard-audio"

_LOGGER = logging.getLogger(__name__)

PLATFORMS_SYSTEM: Final[list[str]] = ["sensor", "switch"]
PLATFORMS_ZONE: Final[list[str]] = ["sensor", "switch", "number"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def rebuild_dashboard(call: ServiceCall) -> None:
        await async_rebuild_dashboard(hass, call.data.get("dashboard", DEFAULT_DASHBOARD),
                                      call.data.get("style", "standard"), call.data.get("theme") or None)

    hass.services.async_register(DOMAIN, "rebuild_dashboard", rebuild_dashboard)
    return True


async def _missing_cards(lovelace) -> list[str]:
    """Frontend cards the fancy style needs that aren't registered as dashboard resources."""
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None:
        return list(REQUIRED_CARDS)
    if not getattr(resources, "loaded", True) and hasattr(resources, "async_load"):
        await resources.async_load()
    urls = " ".join(str(r.get("url", "")) for r in resources.async_items())
    return [card for card in REQUIRED_CARDS if card not in urls]


async def async_rebuild_dashboard(hass: HomeAssistant, url_path: str, style: str = "standard",
                                  theme: str | None = None) -> None:
    """Build the Audio dashboard from live config + entity registry and save it to a storage dashboard.

    Saving through lovelace (not by writing .storage) updates HA's in-memory copy and notifies open
    frontends, so the new layout shows up on refresh with no HA restart.
    """
    lovelace = hass.data.get("lovelace")
    dashboards = getattr(lovelace, "dashboards", None)
    if dashboards is None and isinstance(lovelace, dict):
        dashboards = lovelace.get("dashboards")
    target = (dashboards or {}).get(url_path)
    if target is None or not hasattr(target, "async_save") or getattr(target, "mode", "storage") != "storage":
        raise HomeAssistantError(
            f"No UI-managed dashboard at '/{url_path}'. Create one (Settings → Dashboards → Add, "
            f"URL '{url_path}') and run this again."
        )

    registry = er.async_get(hass)

    def eid(platform: str, unique_id: str) -> str | None:
        return registry.async_get_entity_id(platform, DOMAIN, unique_id)

    systems: list[dict] = []
    zones: list[dict] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if isinstance(coord, SystemCoordinator):
            slug = _slugify(coord.system_name)
            systems.append({
                "title": entry.title,
                "status": eid("sensor", f"{DOMAIN}_{slug}_status"),
                "active": eid("switch", f"{DOMAIN}_{slug}_active"),
                "party": eid("switch", f"{DOMAIN}_{slug}_party_mode"),
                "party_status": eid("sensor", f"{DOMAIN}_{slug}_party_mode_status"),
                "sources": [
                    {"name": src["display_name"],
                     "follow_me": eid("switch", f"{DOMAIN}_{slug}_{_slugify(src['display_name'])}_follow_me"),
                     "watcher": src.get("watcher_entity")}
                    for src in coord.get_sources() if src.get("display_name")
                ],
            })
        elif isinstance(coord, ZoneCoordinator):
            slug = _slugify(coord.zone_name)
            zones.append({
                "title": entry.title,
                "status": eid("sensor", f"{DOMAIN}_{slug}_status"),
                "follow_me": eid("switch", f"{DOMAIN}_{slug}_follow_me"),
                "volume": eid("number", f"{DOMAIN}_{slug}_volume_offset"),
                "party": eid("switch", f"{DOMAIN}_{slug}_party_mode"),
                "speaker": {**entry.data, **entry.options}.get("media_player"),
            })

    # Drop anything whose entities aren't registered (e.g. an entry that failed setup) rather than
    # writing cards for entities that don't exist.
    def complete(d: dict, keys: tuple[str, ...]) -> bool:
        if all(d.get(k) for k in keys):
            return True
        _LOGGER.warning("Audio dashboard: skipping %s, entities missing: %s", d["title"], d)
        return False

    systems = [s for s in systems if complete(s, ("status", "active", "party"))]
    for s in systems:
        s["sources"] = [src for src in s["sources"] if src["follow_me"]]
    zones = [z for z in zones if complete(z, ("status", "follow_me", "volume", "party"))]

    if style not in STYLES:
        raise HomeAssistantError(f"Unknown dashboard style '{style}' (use one of {', '.join(STYLES)}).")
    if style == "fancy" and (missing := await _missing_cards(lovelace)):
        _LOGGER.warning("Audio dashboard: fancy style needs %s (install via HACS); using standard",
                        ", ".join(missing))
        style = "standard"

    await target.async_save(build_dashboard(systems, zones, style, theme))
    _LOGGER.info("Dynamic Central Audio: rebuilt dashboard /%s (%s, %d zones)", url_path, style, len(zones))


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the current schema.

    minor_version 2 — repair sources that carry an app_ids allow-list but a blank
    app_filter_entity. The options flow could save the entity as "" (it had no default
    when the pre-existing entry.data source dict lacked the key), which silently
    disabled the filter and let every app trigger follow-me. Backfill the entity from
    the source's own watcher_entity, which is what the filter is meant to inspect.
    """
    if entry.minor_version >= 2:
        return True

    if entry.data.get("entry_type") != ENTRY_TYPE_SYSTEM:
        hass.config_entries.async_update_entry(entry, minor_version=2)
        return True

    def _repair(sources: list[dict]) -> tuple[list[dict], bool]:
        repaired: list[dict] = []
        changed = False
        for source in sources:
            source = dict(source)
            if source.get("app_ids") and not source.get("app_filter_entity"):
                watcher = source.get("watcher_entity")
                if watcher:
                    source["app_filter_entity"] = watcher
                    changed = True
                    _LOGGER.warning(
                        "Migrating source %s: app_filter_entity was blank despite "
                        "app_ids %s — backfilled from watcher_entity %s",
                        source.get("display_name", "?"), source["app_ids"], watcher,
                    )
            repaired.append(source)
        return repaired, changed

    new_data, data_changed = _repair(list(entry.data.get("sources") or []))
    new_options, options_changed = _repair(list(entry.options.get("sources") or []))

    updates: dict = {"minor_version": 2}
    if data_changed:
        updates["data"] = {**entry.data, "sources": new_data}
    if options_changed:
        updates["options"] = {**entry.options, "sources": new_options}

    hass.config_entries.async_update_entry(entry, **updates)
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

    # Watch the zone's own media player so manual power-on triggers an immediate
    # coordinator refresh (cancels pending deactivation timers and activates routing).
    zone_mp = config.get("media_player")
    if zone_mp:
        unsub = async_track_state_change_event(
            hass, [zone_mp], coordinator.handle_zone_mp_change
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
