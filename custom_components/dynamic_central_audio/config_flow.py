"""Config flow for Dynamic Central Audio."""

from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    ENTRY_TYPE_SYSTEM,
    ENTRY_TYPE_ZONE,
    DEFAULT_ACTIVE_STATE,
    DEFAULT_BASE_VOLUME,
    DEFAULT_OFF_DELAY,
    DEFAULT_RESTORE_DELAY,
    DEFAULT_SOURCE_OFF_DELAY,
    DEFAULT_PRIORITY,
    RESTORE_ANY_STOPPED,
    RESTORE_ALL_STOPPED,
    RESTORE_OCCUPIED,
    RESTORE_CONDITIONS,
)


def _source_list_for_entity(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Read source_list from a media_player entity's current state."""
    if not entity_id:
        return []
    state = hass.states.get(entity_id)
    if not state:
        return []
    return list(state.attributes.get("source_list") or [])


def _configured_systems(hass: HomeAssistant) -> list[dict]:
    """Return list of {entry_id, title} for all system entries."""
    return [
        {"value": e.entry_id, "label": e.title}
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("entry_type") == ENTRY_TYPE_SYSTEM
    ]


# ── Main config flow ──────────────────────────────────────────────────────────

class DynamicCentralAudioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Dynamic Central Audio."""

    VERSION = 1

    def __init__(self) -> None:
        self._setup_type: str = ""
        # System accumulation
        self._system_data: Dict[str, Any] = {}
        self._sources: List[dict] = []
        self._ref_entity: str = ""
        # Zone accumulation
        self._zone_data: Dict[str, Any] = {}
        self._atv_exclusions: List[dict] = []

    # ── Step 0: choose system or zone ─────────────────────────────────────────

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            self._setup_type = user_input["setup_type"]
            if self._setup_type == ENTRY_TYPE_SYSTEM:
                return await self.async_step_system()
            return await self.async_step_zone()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("setup_type"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=ENTRY_TYPE_SYSTEM, label="Audio System (controller)"),
                        selector.SelectOptionDict(value=ENTRY_TYPE_ZONE, label="Zone (room)"),
                    ])
                ),
            }),
        )

    # ── System: step 1 — name + reference entity ──────────────────────────────

    async def async_step_system(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            self._system_data["system_name"] = user_input["system_name"]
            self._system_data["source_off_delay_seconds"] = int(user_input.get("source_off_delay_seconds", DEFAULT_SOURCE_OFF_DELAY))
            self._ref_entity = user_input.get("reference_entity", "")
            self._sources = []
            return await self.async_step_add_source()

        return self.async_show_form(
            step_id="system",
            data_schema=vol.Schema({
                vol.Required("system_name"): str,
                vol.Optional("reference_entity", default=""): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player"),
                ),
                vol.Optional("source_off_delay_seconds", default=DEFAULT_SOURCE_OFF_DELAY): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=1800, step=30, unit_of_measurement="s")
                ),
            }),
            description_placeholders={
                "step_title": "Step 1: System Setup — pick any zone media player from your system; its source list will populate the input dropdown on the next step."
            },
        )

    # ── System: step 2 — add source (loops until done) ───────────────────────

    async def async_step_add_source(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            watcher = user_input.get("source_watcher_entity", "")
            if watcher:
                self._sources.append({
                    "display_name": user_input.get("source_display_name", "Source"),
                    "source_name": user_input.get("source_name", ""),
                    "watcher_entity": watcher,
                    "active_state": user_input.get("active_state", DEFAULT_ACTIVE_STATE),
                    "base_volume": float(user_input.get("base_volume", DEFAULT_BASE_VOLUME)),
                    "priority": int(user_input.get("priority", DEFAULT_PRIORITY)),
                })

            if user_input.get("add_another") and watcher:
                return await self.async_step_add_source()

            # Done — create system entry
            self._system_data["sources"] = self._sources
            return self.async_create_entry(
                title=self._system_data["system_name"],
                data={"entry_type": ENTRY_TYPE_SYSTEM, **self._system_data},
            )

        source_list = _source_list_for_entity(self.hass, self._ref_entity)
        source_num = len(self._sources) + 1

        source_name_field = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(options=source_list, custom_value=True)
            )
            if source_list
            else selector.TextSelector()
        )

        return self.async_show_form(
            step_id="add_source",
            data_schema=vol.Schema({
                vol.Optional("source_display_name", default=f"Source {source_num}"): str,
                vol.Optional("source_name", default=""): source_name_field,
                vol.Optional("source_watcher_entity", default=""): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Optional("active_state", default=DEFAULT_ACTIVE_STATE): str,
                vol.Optional("base_volume", default=DEFAULT_BASE_VOLUME): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05)
                ),
                vol.Optional("priority", default=source_num): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=20, step=1)
                ),
                vol.Optional("add_another", default=False): bool,
            }),
            description_placeholders={
                "step_title": f"Source {source_num}",
                "hint": "Leave watcher entity blank to finish without adding a source.",
            },
        )

    # ── Zone: step 1 — name + system ─────────────────────────────────────────

    async def async_step_zone(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        systems = _configured_systems(self.hass)
        errors: dict = {}

        if user_input is not None:
            if not systems and not user_input.get("system_entry_id"):
                errors["system_entry_id"] = "no_systems"
            else:
                self._zone_data = {
                    "zone_name": user_input["zone_name"],
                    "system_entry_id": user_input["system_entry_id"],
                }
                return await self.async_step_zone_player()

        if not systems:
            return self.async_abort(reason="no_systems_configured")

        return self.async_show_form(
            step_id="zone",
            data_schema=vol.Schema({
                vol.Required("zone_name"): str,
                vol.Required("system_entry_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=s["value"], label=s["label"]) for s in systems]
                    )
                ),
            }),
            errors=errors,
            description_placeholders={"step_title": "Step 1: Zone Identity"},
        )

    # ── Zone: step 2 — media player ──────────────────────────────────────────

    async def async_step_zone_player(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            self._zone_data["media_player"] = user_input["media_player"]
            return await self.async_step_zone_sensors()

        return self.async_show_form(
            step_id="zone_player",
            data_schema=vol.Schema({
                vol.Required("media_player"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
            }),
            description_placeholders={"step_title": "Step 2: Media Player"},
        )

    # ── Zone: step 3 — occupancy + off delay ─────────────────────────────────

    async def async_step_zone_sensors(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            self._zone_data["occupancy_sensors"] = user_input.get("occupancy_sensors", [])
            self._zone_data["off_delay_seconds"] = int(user_input.get("off_delay_seconds", DEFAULT_OFF_DELAY))
            self._atv_exclusions = []
            return await self.async_step_zone_atv()

        return self.async_show_form(
            step_id="zone_sensors",
            data_schema=vol.Schema({
                vol.Optional("occupancy_sensors", default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional("off_delay_seconds", default=DEFAULT_OFF_DELAY): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=3600, step=30, unit_of_measurement="s")
                ),
            }),
            description_placeholders={"step_title": "Step 3: Occupancy"},
        )

    # ── Zone: step 4 — ATV exclusion (optional, loops) ───────────────────────

    async def async_step_zone_atv(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            atvs = user_input.get("atv_entities", [])
            if atvs:
                self._atv_exclusions.append({
                    "atv_entities": atvs,
                    "restore_condition": user_input.get("restore_condition", RESTORE_ANY_STOPPED),
                    "restore_delay_seconds": int(user_input.get("restore_delay_seconds", 0)),
                    "airplay_exception": user_input.get("airplay_exception", True),
                    "amp_switch": user_input.get("amp_switch") or None,
                })

            if user_input.get("add_another") and atvs:
                return await self.async_step_zone_atv()

            self._zone_data["atv_exclusions"] = self._atv_exclusions
            await self.async_set_unique_id(f"{DOMAIN}_zone_{self._zone_data['zone_name']}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._zone_data["zone_name"],
                data={"entry_type": ENTRY_TYPE_ZONE, **self._zone_data},
            )

        return self.async_show_form(
            step_id="zone_atv",
            data_schema=vol.Schema({
                vol.Optional("atv_entities", default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=True)
                ),
                vol.Optional("restore_condition", default=RESTORE_ANY_STOPPED): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=RESTORE_ANY_STOPPED, label="Any stopped"),
                        selector.SelectOptionDict(value=RESTORE_ALL_STOPPED, label="All stopped"),
                        selector.SelectOptionDict(value=RESTORE_OCCUPIED, label="Occupied (with delay)"),
                    ])
                ),
                vol.Optional("restore_delay_seconds", default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1800, step=30, unit_of_measurement="s")
                ),
                vol.Optional("airplay_exception", default=True): bool,
                vol.Optional("amp_switch"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional("add_another", default=False): bool,
            }),
            description_placeholders={"step_title": "Step 4: ATV Exclusions (leave entities blank to skip)"},
        )

    # ── Options flows ─────────────────────────────────────────────────────────

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        if config_entry.data.get("entry_type") == ENTRY_TYPE_SYSTEM:
            return SystemOptionsFlow(config_entry)
        return ZoneOptionsFlow(config_entry)


# ── System options flow ───────────────────────────────────────────────────────

class SystemOptionsFlow(config_entries.OptionsFlow):
    """Edit an existing system entry."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._sources: List[dict] = []
        self._ref_entity: str = ""

    async def async_step_init(self, user_input=None) -> FlowResult:
        d = {**self._entry.data, **self._entry.options}

        if user_input is not None:
            self._ref_entity = user_input.get("reference_entity", "")
            self._sources = []
            return await self.async_step_edit_source()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("reference_entity", default=d.get("reference_entity", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional("source_off_delay_seconds", default=d.get("source_off_delay_seconds", DEFAULT_SOURCE_OFF_DELAY)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=1800, step=30, unit_of_measurement="s")
                ),
            }),
        )

    async def async_step_edit_source(self, user_input=None) -> FlowResult:
        if user_input is not None:
            watcher = user_input.get("source_watcher_entity", "")
            if watcher:
                self._sources.append({
                    "display_name": user_input.get("source_display_name", "Source"),
                    "source_name": user_input.get("source_name", ""),
                    "watcher_entity": watcher,
                    "active_state": user_input.get("active_state", DEFAULT_ACTIVE_STATE),
                    "base_volume": float(user_input.get("base_volume", DEFAULT_BASE_VOLUME)),
                    "priority": int(user_input.get("priority", DEFAULT_PRIORITY)),
                })
            if user_input.get("add_another") and watcher:
                return await self.async_step_edit_source()
            return self.async_create_entry(title="", data={"sources": self._sources})

        source_list = _source_list_for_entity(self.hass, self._ref_entity)
        existing = self._entry.data.get("sources", self._entry.options.get("sources", []))
        src = existing[len(self._sources)] if len(self._sources) < len(existing) else {}

        source_name_field = (
            selector.SelectSelector(selector.SelectSelectorConfig(options=source_list, custom_value=True))
            if source_list else selector.TextSelector()
        )

        return self.async_show_form(
            step_id="edit_source",
            data_schema=vol.Schema({
                vol.Optional("source_display_name", default=src.get("display_name", f"Source {len(self._sources)+1}")): str,
                vol.Optional("source_name", default=src.get("source_name", "")): source_name_field,
                vol.Optional("source_watcher_entity", default=src.get("watcher_entity", "")): selector.EntitySelector(selector.EntitySelectorConfig()),
                vol.Optional("active_state", default=src.get("active_state", DEFAULT_ACTIVE_STATE)): str,
                vol.Optional("base_volume", default=src.get("base_volume", DEFAULT_BASE_VOLUME)): selector.NumberSelector(selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05)),
                vol.Optional("priority", default=src.get("priority", DEFAULT_PRIORITY)): selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=20, step=1)),
                vol.Optional("add_another", default=False): bool,
            }),
        )


# ── Zone options flow ─────────────────────────────────────────────────────────

class ZoneOptionsFlow(config_entries.OptionsFlow):
    """Edit an existing zone entry."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._atv_exclusions: List[dict] = []

    async def async_step_init(self, user_input=None) -> FlowResult:
        d = {**self._entry.data, **self._entry.options}
        occ = d.get("occupancy_sensors", [])
        if isinstance(occ, str):
            occ = [occ] if occ else []

        if user_input is not None:
            self._zone_data = {
                "media_player": user_input["media_player"],
                "occupancy_sensors": user_input.get("occupancy_sensors", []),
                "off_delay_seconds": int(user_input.get("off_delay_seconds", DEFAULT_OFF_DELAY)),
            }
            self._atv_exclusions = []
            return await self.async_step_atv()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("media_player", default=d.get("media_player", "")): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional("occupancy_sensors", default=occ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional("off_delay_seconds", default=d.get("off_delay_seconds", DEFAULT_OFF_DELAY)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=3600, step=30, unit_of_measurement="s")
                ),
            }),
        )

    async def async_step_atv(self, user_input=None) -> FlowResult:
        existing = self._entry.data.get("atv_exclusions", [])
        idx = len(self._atv_exclusions)

        if user_input is not None:
            atvs = user_input.get("atv_entities", [])
            if atvs:
                self._atv_exclusions.append({
                    "atv_entities": atvs,
                    "restore_condition": user_input.get("restore_condition", RESTORE_ANY_STOPPED),
                    "restore_delay_seconds": int(user_input.get("restore_delay_seconds", 0)),
                    "airplay_exception": user_input.get("airplay_exception", True),
                    "amp_switch": user_input.get("amp_switch") or None,
                })
            if user_input.get("add_another") and atvs:
                return await self.async_step_atv()
            return self.async_create_entry(title="", data={**self._zone_data, "atv_exclusions": self._atv_exclusions})

        excl = existing[idx] if idx < len(existing) else {}
        existing_atvs = excl.get("atv_entities") or ([excl["atv_entity"]] if excl.get("atv_entity") else [])
        return self.async_show_form(
            step_id="atv",
            data_schema=vol.Schema({
                vol.Optional("atv_entities", default=existing_atvs): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=True)
                ),
                vol.Optional("restore_condition", default=excl.get("restore_condition", RESTORE_ANY_STOPPED)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=RESTORE_ANY_STOPPED, label="Any stopped"),
                        selector.SelectOptionDict(value=RESTORE_ALL_STOPPED, label="All stopped"),
                        selector.SelectOptionDict(value=RESTORE_OCCUPIED, label="Occupied (with delay)"),
                    ])
                ),
                vol.Optional("restore_delay_seconds", default=excl.get("restore_delay_seconds", 0)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1800, step=30, unit_of_measurement="s")
                ),
                vol.Optional("airplay_exception", default=excl.get("airplay_exception", True)): bool,
                **({
                    vol.Optional("amp_switch", default=excl["amp_switch"]): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    )
                } if excl.get("amp_switch") else {
                    vol.Optional("amp_switch"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    )
                }),
                vol.Optional("add_another", default=False): bool,
            }),
        )
