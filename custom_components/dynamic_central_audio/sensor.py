"""Sensors for Dynamic Central Audio."""

import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTRY_TYPE_SYSTEM, ENTRY_TYPE_ZONE, ROUTING_NONE
from .coordinator import SystemCoordinator, ZoneCoordinator


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_type = entry.data.get("entry_type")
    coordinator = hass.data[DOMAIN][entry.entry_id]

    if entry_type == ENTRY_TYPE_SYSTEM:
        async_add_entities([SystemStatusSensor(coordinator)])
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
        }
        if source:
            attrs["active_source"] = source.get("display_name")
            attrs["source_name"] = source.get("source_name")
            attrs["base_volume"] = source.get("base_volume")
            attrs["watcher_entity"] = source.get("watcher_entity")
        return attrs

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
        }
        if self.coordinator._atv_excluded_by:
            attrs["atv_excluded_by"] = list(self.coordinator._atv_excluded_by)
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
