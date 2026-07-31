"""Switches for Dynamic Central Audio."""

import re

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTRY_TYPE_SYSTEM, ENTRY_TYPE_ZONE
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
        # Options-first, matching how the coordinator builds its config
        # ({**entry.data, **entry.options}). Reading data first left these switches
        # keyed to stale display names, so they governed no source at all.
        sources = coordinator.get_sources()
        entities = [SystemActiveSwitch(coordinator), PartyModeSwitch(coordinator)]
        entities += [
            SourceFollowMeSwitch(coordinator, src["display_name"])
            for src in sources
            if src.get("display_name")
        ]
        async_add_entities(entities)
    elif entry_type == ENTRY_TYPE_ZONE:
        zone_name = entry.data.get("zone_name", "Zone")
        async_add_entities([
            ZoneFollowMeSwitch(coordinator, zone_name),
            ZonePartyModeSwitch(coordinator, zone_name),
        ])


class SystemActiveSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """Master on/off switch for a Dynamic Central Audio system."""

    def __init__(self, coordinator: SystemCoordinator) -> None:
        super().__init__(coordinator)
        slug = _slugify(coordinator.system_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_active"
        self.entity_id = f"switch.{DOMAIN}_{slug}_active"
        self._attr_has_entity_name = True
        self._attr_name = "Active"
        self._attr_icon = "mdi:music-circle"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.coordinator._system_active = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.coordinator._system_active

    @property
    def device_info(self):
        slug = _slugify(self.coordinator.system_name)
        return {
            "identifiers": {(DOMAIN, f"system_{slug}")},
            "name": f"{self.coordinator.system_name}",
        }

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_active(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_active(False)
        self.async_write_ha_state()


class ZoneFollowMeSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """Per-zone follow-me enable/disable switch."""

    def __init__(self, coordinator: ZoneCoordinator, zone_name: str) -> None:
        super().__init__(coordinator)
        slug = _slugify(zone_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_follow_me"
        self.entity_id = f"switch.{DOMAIN}_{slug}_follow_me"
        self._attr_has_entity_name = True
        self._attr_name = "Follow Me"
        self._attr_icon = "mdi:account-music"
        self.zone_name = zone_name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            enabled = last.state == "on"
            self.coordinator._follow_me = enabled
            if not enabled:
                self.coordinator._schedule_follow_me_reset()

    @property
    def is_on(self) -> bool:
        return self.coordinator._follow_me

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

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_follow_me(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_follow_me(False)
        self.async_write_ha_state()


class PartyModeSwitch(CoordinatorEntity, SwitchEntity):
    """System-level Party Mode: suspends ATV-exclusion gating so central audio keeps
    routing to a zone even while its local ATV plays (see ZoneCoordinator._party_suspends_exclusion).

    Always starts off on restart — deliberately not a RestoreEntity, since a stale
    "on" from before a restart isn't something that should silently resume.
    """

    def __init__(self, coordinator: SystemCoordinator) -> None:
        super().__init__(coordinator)
        slug = _slugify(coordinator.system_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_party_mode"
        self.entity_id = f"switch.{DOMAIN}_{slug}_party_mode"
        self._attr_has_entity_name = True
        self._attr_name = "Party Mode"
        self._attr_icon = "mdi:party-popper"

    @property
    def is_on(self) -> bool:
        return self.coordinator._party_mode_active

    @property
    def device_info(self):
        slug = _slugify(self.coordinator.system_name)
        return {
            "identifiers": {(DOMAIN, f"system_{slug}")},
            "name": f"{self.coordinator.system_name}",
        }

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_party_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_party_mode(False)
        self.async_write_ha_state()


class ZonePartyModeSwitch(CoordinatorEntity, SwitchEntity):
    """Zone-level Party Mode: suspends this zone's own ATV-exclusion gating.

    Always starts off on restart — not a RestoreEntity, same reasoning as
    PartyModeSwitch above.
    """

    def __init__(self, coordinator: ZoneCoordinator, zone_name: str) -> None:
        super().__init__(coordinator)
        slug = _slugify(zone_name)
        self._attr_unique_id = f"{DOMAIN}_{slug}_party_mode"
        self.entity_id = f"switch.{DOMAIN}_{slug}_party_mode"
        self._attr_has_entity_name = True
        self._attr_name = "Party Mode"
        self._attr_icon = "mdi:party-popper"
        self.zone_name = zone_name

    @property
    def is_on(self) -> bool:
        return self.coordinator._zone_party_active

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

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_zone_party_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_zone_party_mode(False)
        self.async_write_ha_state()


class SourceFollowMeSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """Per-source follow-me enable/disable switch."""

    def __init__(self, coordinator: SystemCoordinator, display_name: str) -> None:
        super().__init__(coordinator)
        system_slug = _slugify(coordinator.system_name)
        source_slug = _slugify(display_name)
        self._display_name = display_name
        self._attr_unique_id = f"{DOMAIN}_{system_slug}_{source_slug}_follow_me"
        self.entity_id = f"switch.{DOMAIN}_{system_slug}_{source_slug}_follow_me"
        self._attr_has_entity_name = True
        self._attr_name = f"{display_name} Follow Me"
        self._attr_icon = "mdi:music-note-plus"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        enabled = last.state == "on" if last is not None else True
        self.coordinator._source_follow_me[self._display_name] = enabled

    @property
    def is_on(self) -> bool:
        return self.coordinator._source_follow_me.get(self._display_name, True)

    @property
    def device_info(self):
        slug = _slugify(self.coordinator.system_name)
        return {
            "identifiers": {(DOMAIN, f"system_{slug}")},
            "name": f"{self.coordinator.system_name}",
        }

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_source_follow_me(self._display_name, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_source_follow_me(self._display_name, False)
        self.async_write_ha_state()
