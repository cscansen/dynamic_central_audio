"""Sensors for Dynamic Central Audio."""

import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTRY_TYPE_SYSTEM, ENTRY_TYPE_ZONE, ROUTING_NONE, STATUS_PARTY_ACTIVE, STATUS_IDLE
from .coordinator import SystemCoordinator, ZoneCoordinator, _excl_entities


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


def _system_reasoning(coord: SystemCoordinator) -> str:
    if not coord._system_active:
        return "System disabled — master switch is off"

    sources = coord.get_sources()
    if not sources:
        return "No sources configured"

    lines = []
    active = coord.active_source

    for src in sorted(sources, key=lambda s: int(s.get("priority", 99))):
        name = src.get("display_name", "?")
        watcher = src.get("watcher_entity", "")
        follow_me = coord._source_follow_me.get(name, True)
        state = coord.hass.states.get(watcher) if watcher else None
        state_str = state.state if state else "unavailable"
        is_active = active and active.get("display_name") == name
        marker = "▶" if is_active else "◌"
        fm_str = "  [follow-me OFF]" if not follow_me else ""
        lines.append(f"{marker} {name}: {state_str}{fm_str}")

    if not active:
        lines.insert(0, "No source active\n")

    return "\n".join(lines)


def _zone_reasoning(coord: ZoneCoordinator) -> str:
    system = coord.get_system_coordinator()

    if not system:
        return "No parent system found"
    if not system._system_active:
        return "Parent system is inactive (master switch off)"
    if not coord._follow_me:
        return "Follow Me is disabled for this zone"

    if coord._atv_excluded_by and not coord._party_suspends_exclusion():
        exclusions = coord.config.get("atv_exclusions", [])
        details = []
        for excl in exclusions:
            active_atvs = [e for e in _excl_entities(excl) if e in coord._atv_excluded_by]
            if not active_atvs:
                continue
            condition = excl.get("restore_condition", "any_stopped")
            delay = int(excl.get("restore_delay_seconds", 0))
            restore_str = f"restores: {condition}"
            if delay:
                restore_str += f" + {delay}s delay"
            details.append(f"  • {', '.join(active_atvs)}\n    ({restore_str})")
        return "Excluded by local device:\n" + "\n".join(details)

    active_source = system.active_source
    occupied = coord._is_occupied()
    sensors = coord.config.get("occupancy_sensors", [])

    if active_source and occupied:
        base = float(active_source.get("base_volume", 0.7))
        offset = coord._volume_offset
        vol = round(max(0.0, min(1.0, base + offset)), 2)
        occ_str = "always occupied (no sensors configured)" if not sensors else "occupied"
        party_str = "\n  • Party Mode — ATV exclusion bypassed" if (coord._atv_excluded_by and coord._party_suspends_exclusion()) else ""
        return (
            f"Following: {active_source['display_name']}\n"
            f"  • Zone is {occ_str}\n"
            f"  • Volume: {vol:.2f}  (base {base:.2f}  offset {offset:+.2f}){party_str}"
        )

    if active_source and not occupied:
        if coord._zone_active:
            base = float(active_source.get("base_volume", 0.7))
            offset = coord._volume_offset
            vol = round(max(0.0, min(1.0, base + offset)), 2)
            return (
                f"Following: {active_source['display_name']} (manual override)\n"
                f"  • Manually powered on — occupancy bypassed\n"
                f"  • Volume: {vol:.2f}  (base {base:.2f}  offset {offset:+.2f})"
            )
        return (
            f"Source active ({active_source['display_name']}) — zone unoccupied\n"
            f"  • Will activate when occupancy detected"
        )

    return "Idle — no active source"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_type = entry.data.get("entry_type")
    coordinator = hass.data[DOMAIN][entry.entry_id]

    if entry_type == ENTRY_TYPE_SYSTEM:
        async_add_entities([SystemStatusSensor(coordinator), PartyModeStatusSensor(coordinator)])
    elif entry_type == ENTRY_TYPE_ZONE:
        zone_name = entry.data.get("zone_name", "Zone")
        async_add_entities([ZoneStatusSensor(coordinator, zone_name)])


class SystemStatusSensor(CoordinatorEntity, SensorEntity):
    """Reports the current routing mode and active source for a system."""

    def __init__(self, coordinator: SystemCoordinator) -> None:
        super().__init__(coordinator)
        slug = _slugify(coordinator.system_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_status"
        self.entity_id = f"sensor.{DOMAIN}_{slug}_status"
        self._attr_has_entity_name = True
        self._attr_name = "Status"
        self._attr_icon = "mdi:music-note"

    @property
    def native_value(self) -> str:
        if self.coordinator.data:
            return self.coordinator.data.get("routing_mode", ROUTING_NONE)
        return ROUTING_NONE

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        source = self.coordinator.data.get("active_source")
        attrs: dict = {
            "system_active": self.coordinator._system_active,
            "routing_mode": self.coordinator.routing_mode,
            "reasoning": _system_reasoning(self.coordinator),
        }
        if source:
            attrs["active_source"] = source.get("display_name")
            attrs["source_name"] = source.get("source_name")
            attrs["base_volume"] = source.get("base_volume")
            attrs["watcher_entity"] = source.get("watcher_entity")

        # Per-source app filters, so a silently-disabled filter (empty app_ids ⇒ this
        # source follows on ANY app, video included) is visible without digging through
        # the config entry storage.
        attrs["app_filters"] = {
            src.get("display_name", "?"): {
                "app_ids": list(src.get("app_ids") or []),
                "filter_entity": src.get("app_filter_entity") or src.get("watcher_entity"),
                "filtered": bool(src.get("app_ids")),
            }
            for src in self.coordinator.get_sources()
        }
        return attrs

    @property
    def device_info(self):
        slug = _slugify(self.coordinator.system_name)
        return {
            "identifiers": {(DOMAIN, f"system_{slug}")},
            "name": f"{self.coordinator.system_name}",
        }


class PartyModeStatusSensor(CoordinatorEntity, SensorEntity):
    """Reports Party Mode status for a system."""

    def __init__(self, coordinator: SystemCoordinator) -> None:
        super().__init__(coordinator)
        slug = _slugify(coordinator.system_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_party_mode_status"
        self.entity_id = f"sensor.{DOMAIN}_{slug}_party_mode_status"
        self._attr_has_entity_name = True
        self._attr_name = "Party Mode Status"
        self._attr_icon = "mdi:party-popper"

    @property
    def native_value(self) -> str:
        return STATUS_PARTY_ACTIVE if self.coordinator._party_mode_active else STATUS_IDLE

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "party_mode_active": self.coordinator._party_mode_active,
            "source_atv": self.coordinator.config.get("party_mode_source_atv"),
        }

    @property
    def device_info(self):
        slug = _slugify(self.coordinator.system_name)
        return {
            "identifiers": {(DOMAIN, f"system_{slug}")},
            "name": f"{self.coordinator.system_name}",
        }


class ZoneStatusSensor(CoordinatorEntity, SensorEntity):
    """Reports the current follow-me status for a zone."""

    def __init__(self, coordinator: ZoneCoordinator, zone_name: str) -> None:
        super().__init__(coordinator)
        slug = _slugify(zone_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_status"
        self.entity_id = f"sensor.{DOMAIN}_{slug}_status"
        self._attr_has_entity_name = True
        self._attr_name = "Status"
        self._attr_icon = "mdi:speaker"
        self.zone_name = zone_name

    @property
    def native_value(self) -> str:
        if self.coordinator.data:
            return self.coordinator.data.get("status", "idle")
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {
            "zone_active": self.coordinator._zone_active,
            "follow_me": self.coordinator._follow_me,
            "volume_offset": self.coordinator._volume_offset,
            "routing_mode": self.coordinator.data.get("routing_mode", ROUTING_NONE) if self.coordinator.data else ROUTING_NONE,
            "reasoning": _zone_reasoning(self.coordinator),
            "zone_party_active": self.coordinator._zone_party_active,
        }
        if self.coordinator._atv_excluded_by:
            attrs["atv_excluded_by"] = list(self.coordinator._atv_excluded_by)
            attrs["party_mode_suspends_exclusion"] = self.coordinator._party_suspends_exclusion()
        return attrs

    @property
    def device_info(self):
        slug = _slugify(self.zone_name)
        system = self.coordinator.get_system_coordinator()
        system_slug = _slugify(system.system_name) if system else "unknown"
        return {
            "identifiers": {(DOMAIN, f"zone_{slug}")},
            "name": f"{self.zone_name}",
            "via_device": (DOMAIN, f"system_{system_slug}"),
        }
