"""Number entities for Dynamic Central Audio."""

import re

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ENTRY_TYPE_ZONE,
    DEFAULT_VOLUME_OFFSET,
    VOLUME_OFFSET_MIN,
    VOLUME_OFFSET_MAX,
    VOLUME_OFFSET_STEP,
)
from .coordinator import ZoneCoordinator


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get("entry_type") != ENTRY_TYPE_ZONE:
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    zone_name = entry.data.get("zone_name", "Zone")
    async_add_entities([ZoneVolumeOffsetNumber(coordinator, zone_name)])


class ZoneVolumeOffsetNumber(CoordinatorEntity, RestoreEntity, NumberEntity):
    """Live-tunable volume offset for a zone (applied on top of source base volume)."""

    def __init__(self, coordinator: ZoneCoordinator, zone_name: str) -> None:
        super().__init__(coordinator)
        slug = _slugify(zone_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_volume_offset"
        self.entity_id = f"number.{DOMAIN}_{slug}_volume_offset"
        self._attr_has_entity_name = True
        self._attr_name = "Volume Offset"
        self._attr_icon = "mdi:volume-plus"
        self._attr_native_min_value = VOLUME_OFFSET_MIN
        self._attr_native_max_value = VOLUME_OFFSET_MAX
        self._attr_native_step = VOLUME_OFFSET_STEP
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_unit_of_measurement = None
        self.zone_name = zone_name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            try:
                self.coordinator._volume_offset = float(last.state)
            except (ValueError, TypeError):
                self.coordinator._volume_offset = DEFAULT_VOLUME_OFFSET
        else:
            self.coordinator._volume_offset = DEFAULT_VOLUME_OFFSET

    @property
    def native_value(self) -> float:
        return self.coordinator._volume_offset

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

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_volume_offset(round(value, 2))
        self.async_write_ha_state()
