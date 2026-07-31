"""Coordinators for Dynamic Central Audio."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ENTRY_TYPE_ZONE,
    SCAN_INTERVAL_SECONDS,
    DEFAULT_OFF_DELAY,
    DEFAULT_SOURCE_OFF_DELAY,
    DEFAULT_VOLUME_OFFSET,
    DEFAULT_PARTY_TRIGGER_APPS,
    RESTORE_ANY_STOPPED,
    RESTORE_ALL_STOPPED,
    RESTORE_OCCUPIED,
    STATUS_FOLLOWING,
    STATUS_STANDBY,
    STATUS_ATV_OVERRIDE,
    STATUS_FOLLOW_ME_OFF,
    STATUS_SYSTEM_INACTIVE,
    STATUS_NO_SYSTEM,
    STATUS_IDLE,
    STATUS_PARTY_ACTIVE,
    ROUTING_NONE,
)

_LOGGER = logging.getLogger(__name__)


def _excl_entities(excl: dict) -> list[str]:
    """Return ATV entity list from an exclusion rule (supports atv_entities and legacy atv_entity)."""
    entities = excl.get("atv_entities")
    if entities:
        return list(entities)
    single = excl.get("atv_entity")
    return [single] if single else []


def _app_matches(hass: HomeAssistant, entity_id: str, app_ids: list[str]) -> bool:
    """Return True if the given media_player entity's current app_id/app_name matches any of app_ids.

    Shared by source app filters, ATV bypass_app_ids, and party-mode trigger apps —
    all three use the same case-insensitive *exact* match: a filter value must equal
    the entity's app_id or app_name outright. "Music" will not match "Apple Music";
    configure the full app_id (e.g. "com.apple.TVMusic").
    """
    if not app_ids:
        return False
    state = hass.states.get(entity_id)
    if not state:
        return False
    current_app_id = (state.attributes.get("app_id") or "").lower()
    current_app_name = (state.attributes.get("app_name") or "").lower()
    return any(f.lower() in (current_app_id, current_app_name) for f in app_ids)


class SystemCoordinator(DataUpdateCoordinator):
    """Coordinator for a single audio system entry."""

    def __init__(self, hass: HomeAssistant, config: dict, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Dynamic Central Audio - {config.get('system_name', 'System')}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
            config_entry=config_entry,
        )
        self.config = dict(config)
        self._config_entry = config_entry
        self._system_active: bool = True
        self.routing_mode: str = ROUTING_NONE
        self.active_source: Optional[dict] = None
        # Per-source follow-me state: keyed by source display_name
        self._source_follow_me: dict[str, bool] = {}
        # Sources already warned about a missing app_filter_entity, so the warning
        # fires once per source rather than on every coordinator refresh.
        self._app_filter_fallback_warned: set[str] = set()

        # Party mode state — a plain flag. Enabling it doesn't touch any ATV directly;
        # it just tells zones (via _party_suspends_exclusion) to stop treating a local
        # ATV's playback as a reason to cut off central audio for that zone.
        self._party_mode_active: bool = False

    @property
    def system_name(self) -> str:
        return self.config.get("system_name", "System")

    def get_sources(self) -> list[dict]:
        return self.config.get("sources", [])

    def resolve_routing(self) -> Optional[dict]:
        """Return the highest-priority active and follow-me-enabled source, or None."""
        sources = sorted(self.get_sources(), key=lambda s: int(s.get("priority", 99)))
        for source in sources:
            display_name = source.get("display_name", "")
            if not self._source_follow_me.get(display_name, True):
                continue
            watcher = source.get("watcher_entity")
            if not watcher:
                continue
            active_state = source.get("active_state", "playing")
            state = self.hass.states.get(watcher)
            if not state or state.state != active_state:
                continue
            # Optional app filter — only route if the specified entity is showing an allowed app.
            # An empty app_ids means "no filter". A populated app_ids with a blank
            # app_filter_entity is a misconfiguration, not permission to route everything:
            # fall back to the source's own watcher so the filter still applies.
            app_ids = source.get("app_ids") or []
            if app_ids:
                app_filter_entity = source.get("app_filter_entity")
                if not app_filter_entity:
                    app_filter_entity = watcher
                    if display_name not in self._app_filter_fallback_warned:
                        self._app_filter_fallback_warned.add(display_name)
                        _LOGGER.warning(
                            "%s: source %s has app_ids %s but no app_filter_entity — "
                            "falling back to its watcher entity %s. Set the app filter "
                            "entity in the integration options to silence this.",
                            self.system_name, display_name, app_ids, watcher,
                        )
                if not _app_matches(self.hass, app_filter_entity, app_ids):
                    _LOGGER.debug(
                        "%s: source %s skipped — app filter %s not matched on %s",
                        self.system_name, display_name, app_ids, app_filter_entity,
                    )
                    continue
            return source
        return None

    def set_source_follow_me(self, display_name: str, enabled: bool) -> None:
        self._source_follow_me[display_name] = enabled
        self.hass.async_create_task(self._async_source_changed())

    @callback
    def handle_source_change(self, event) -> None:
        """Called when any watcher entity changes state."""
        self.hass.async_create_task(self._async_source_changed())
        self.hass.async_create_task(self._async_check_party_trigger())

    async def _async_source_changed(self) -> None:
        await self.async_request_refresh()

    async def _async_check_party_trigger(self) -> None:
        """Auto-trigger/auto-off Party Mode based on the configured source ATV's app.

        Only ever fires off AirPlay or a configured app allow-list (party_mode_trigger_apps) —
        never off a generic "playing" state, so a video app on the source ATV can't start a party.
        """
        source_atv = self.config.get("party_mode_source_atv")
        if not source_atv:
            return
        trigger_apps = self.config.get("party_mode_trigger_apps") or DEFAULT_PARTY_TRIGGER_APPS
        state = self.hass.states.get(source_atv)
        is_playing = bool(state and state.state == "playing")
        matches = is_playing and _app_matches(self.hass, source_atv, trigger_apps)

        if matches and self.config.get("party_mode_auto_trigger", True) and not self._party_mode_active:
            await self.async_enable_party_mode()
        elif not matches and self.config.get("party_mode_auto_off", True) and self._party_mode_active:
            await self.async_disable_party_mode()

    async def async_enable_party_mode(self) -> None:
        self._party_mode_active = True
        _LOGGER.info("%s: Party Mode enabled — zone ATV exclusions suspended (amp_switch zones excepted)", self.system_name)
        self.async_set_updated_data(self.data)
        await self._notify_zones()

    async def async_disable_party_mode(self) -> None:
        self._party_mode_active = False
        _LOGGER.info("%s: Party Mode disabled", self.system_name)
        self.async_set_updated_data(self.data)
        await self._notify_zones()

    def set_party_mode(self, enabled: bool) -> None:
        if enabled:
            self.hass.async_create_task(self.async_enable_party_mode())
        else:
            self.hass.async_create_task(self.async_disable_party_mode())

    async def _async_update_data(self) -> dict:
        prev_source = self.active_source
        self.active_source = self.resolve_routing()
        self.routing_mode = self.active_source["display_name"] if self.active_source else ROUTING_NONE

        source_changed = (
            (prev_source is None) != (self.active_source is None)
            or (prev_source and self.active_source and prev_source.get("display_name") != self.active_source.get("display_name"))
        )

        if source_changed:
            _LOGGER.info(
                "%s: routing → %s",
                self.system_name,
                self.routing_mode,
            )
            await self._notify_zones(source_stopped=(self.active_source is None))

        return {
            "routing_mode": self.routing_mode,
            "active_source": self.active_source,
            "system_active": self._system_active,
            "party_mode_active": self._party_mode_active,
        }

    async def _notify_zones(self, source_stopped: bool = False) -> None:
        """Trigger a refresh on all zone coordinators belonging to this system."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get("entry_type") != ENTRY_TYPE_ZONE:
                continue
            if entry.data.get("system_entry_id") != self._config_entry.entry_id:
                continue
            coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not isinstance(coord, ZoneCoordinator):
                continue
            if source_stopped:
                coord.on_source_stopped()
            else:
                coord.on_source_changed()

    def set_active(self, active: bool) -> None:
        self._system_active = active
        if not active:
            # Party Mode has no meaning with everything off — clear it here (before
            # notifying listeners below) rather than leaving it stuck "on" for
            # whenever the system reactivates.
            self._party_mode_active = False
            self.hass.async_create_task(self._disable_all_zone_party_mode())
        self.async_set_updated_data({
            "routing_mode": self.routing_mode,
            "active_source": self.active_source,
            "system_active": self._system_active,
            "party_mode_active": self._party_mode_active,
        })
        self.hass.async_create_task(self._notify_zones(source_stopped=not active))

    async def _disable_all_zone_party_mode(self) -> None:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get("entry_type") != ENTRY_TYPE_ZONE:
                continue
            if entry.data.get("system_entry_id") != self._config_entry.entry_id:
                continue
            coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if isinstance(coord, ZoneCoordinator) and coord._zone_party_active:
                await coord.async_disable_zone_party_mode()


class ZoneCoordinator(DataUpdateCoordinator):
    """Coordinator for a single audio zone."""

    def __init__(self, hass: HomeAssistant, zone_name: str, config: dict, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Dynamic Central Audio - {zone_name}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
            config_entry=config_entry,
        )
        self.zone_name = zone_name
        self.config = dict(config)
        self._config_entry = config_entry

        self._follow_me: bool = True
        self._zone_active: bool = False
        self._volume_offset: float = DEFAULT_VOLUME_OFFSET

        # ATV exclusion tracking: set of atv entity_ids currently overriding this zone
        self._atv_excluded_by: set[str] = set()

        # Pending restore timer handles keyed by entity_id (cancelled if ATV resumes)
        self._atv_restore_handles: dict[str, Any] = {}

        # Pending deactivation timer handles
        self._occ_deactivate_handle = None
        self._source_deactivate_handle = None

        # Follow-me 7am auto-reset handle
        self._follow_me_reset_handle: Optional[Any] = None

        # Zone-level party mode state — a plain flag, same as system-level (see
        # SystemCoordinator.async_enable_party_mode).
        self._zone_party_active: bool = False

        self._lock = asyncio.Lock()

    async def async_config_entry_first_refresh(self) -> None:
        """Pre-populate ATV override state from current HA states before first update."""
        for excl in self.config.get("atv_exclusions", []):
            bypass_app_ids = excl.get("bypass_app_ids", [])
            for entity_id in _excl_entities(excl):
                state = self.hass.states.get(entity_id)
                if not state or state.state != "playing":
                    continue
                if bypass_app_ids:
                    app_id = (state.attributes.get("app_id") or "").lower()
                    app_name = (state.attributes.get("app_name") or "").lower()
                    if any(f.lower() in (app_id, app_name) for f in bypass_app_ids):
                        continue
                self._atv_excluded_by.add(entity_id)
                _LOGGER.info("%s: startup — %s already playing, override pre-loaded", self.zone_name, entity_id)
        await super().async_config_entry_first_refresh()

    # ── System lookup ─────────────────────────────────────────────────────────

    def get_system_coordinator(self) -> Optional[SystemCoordinator]:
        system_entry_id = self.config.get("system_entry_id")
        if not system_entry_id:
            return None
        return self.hass.data.get(DOMAIN, {}).get(system_entry_id)

    # ── Occupancy ─────────────────────────────────────────────────────────────

    def _is_occupied(self) -> bool:
        sensors = self.config.get("occupancy_sensors", [])
        if not sensors:
            return True
        return any(self.hass.states.is_state(s, "on") for s in sensors)

    # ── External event callbacks ───────────────────────────────────────────────

    @callback
    def handle_occupancy_change(self, event) -> None:
        """Called when an occupancy sensor for this zone changes."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == "on":
            self._cancel_occ_deactivate()
            if self._atv_excluded_by and not self._party_suspends_exclusion():
                # ATV was playing while zone was empty — activate amp now that someone entered.
                # Skipped while Party Mode is suspending this exclusion, since central routing
                # (not the amp override) should take over via the refresh below instead.
                self.hass.async_create_task(self._activate_atv_overrides())
            self.hass.async_create_task(self.async_request_refresh())
        else:
            if not self._is_occupied():
                self._schedule_occ_deactivate()

    @callback
    def handle_atv_change(self, event) -> None:
        """Called when an ATV entity for this zone changes state."""
        new_state = event.data.get("new_state")
        entity_id = event.data.get("entity_id")
        if new_state is None or not entity_id:
            return
        self.hass.async_create_task(self._process_atv_change(entity_id, new_state.state))

    @callback
    def handle_zone_mp_change(self, event) -> None:
        """Called when the zone's own media player changes state.

        Detects manual power-on (zone on while coordinator thinks it's off) and
        immediately requests a refresh so _async_update_data can activate source
        routing and cancel any pending deactivation timers before they fire.
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state not in ("off", "unavailable", "unknown") and not self._zone_active:
            _LOGGER.info("%s: manual power-on detected — triggering immediate refresh", self.zone_name)
            self.hass.async_create_task(self.async_request_refresh())

    @callback
    def on_source_changed(self) -> None:
        """Called by system coordinator when active source changes."""
        self._cancel_source_deactivate()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def on_source_stopped(self) -> None:
        """Called by system coordinator when source stops."""
        self._schedule_source_deactivate()

    # ── Deactivation timers ───────────────────────────────────────────────────

    @callback
    def _occ_deactivate_cb(self, _now) -> None:
        self.hass.async_create_task(self._deactivate_zone("unoccupied"))

    def _schedule_occ_deactivate(self) -> None:
        delay = int(self.config.get("off_delay_seconds", DEFAULT_OFF_DELAY))
        self._cancel_occ_deactivate()
        self._occ_deactivate_handle = async_call_later(
            self.hass, delay, self._occ_deactivate_cb,
        )
        _LOGGER.debug("%s: scheduled deactivation in %ds (unoccupied)", self.zone_name, delay)

    def _cancel_occ_deactivate(self) -> None:
        if self._occ_deactivate_handle:
            self._occ_deactivate_handle()
            self._occ_deactivate_handle = None

    @callback
    def _source_deactivate_cb(self, _now) -> None:
        self.hass.async_create_task(self._deactivate_zone("no active source"))

    def _schedule_source_deactivate(self) -> None:
        system = self.get_system_coordinator()
        delay = int(system.config.get("source_off_delay_seconds", DEFAULT_SOURCE_OFF_DELAY)) if system else DEFAULT_SOURCE_OFF_DELAY
        self._cancel_source_deactivate()
        self._source_deactivate_handle = async_call_later(
            self.hass, delay, self._source_deactivate_cb,
        )
        _LOGGER.debug("%s: scheduled deactivation in %ds (source stopped)", self.zone_name, delay)

    def _cancel_source_deactivate(self) -> None:
        if self._source_deactivate_handle:
            self._source_deactivate_handle()
            self._source_deactivate_handle = None

    def _cancel_all_deactivate_timers(self) -> None:
        self._cancel_occ_deactivate()
        self._cancel_source_deactivate()

    def _cancel_all_restore_timers(self) -> None:
        for cancel in self._atv_restore_handles.values():
            cancel()
        self._atv_restore_handles.clear()

    def _cancel_follow_me_reset(self) -> None:
        if self._follow_me_reset_handle:
            self._follow_me_reset_handle()
            self._follow_me_reset_handle = None

    @callback
    def _follow_me_reset_cb(self, _now) -> None:
        self.hass.async_create_task(self._async_reset_follow_me())

    def _schedule_follow_me_reset(self) -> None:
        self._cancel_follow_me_reset()
        now = dt_util.now()
        reset_time = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if reset_time <= now:
            reset_time = reset_time + timedelta(days=1)
        delay = (reset_time - now).total_seconds()
        self._follow_me_reset_handle = async_call_later(
            self.hass, delay, self._follow_me_reset_cb,
        )
        _LOGGER.info("%s: follow-me will auto-re-enable at 07:00 (in %.0fs)", self.zone_name, delay)

    async def _async_reset_follow_me(self) -> None:
        self._follow_me_reset_handle = None
        _LOGGER.info("%s: 07:00 reset — re-enabling follow-me", self.zone_name)
        self.set_follow_me(True)

    def _make_restore_cb(self, entity_id: str, excl: dict):
        @callback
        def _cb(_now) -> None:
            self.hass.async_create_task(self._restore_from_atv(entity_id, excl))
        return _cb

    # ── ATV exclusion ─────────────────────────────────────────────────────────

    async def _process_atv_change(self, entity_id: str, new_state_str: str) -> None:
        exclusions = self.config.get("atv_exclusions", [])
        excl = next((e for e in exclusions if entity_id in _excl_entities(e)), None)
        if not excl:
            return

        if new_state_str == "playing":
            # Check if the current app is in the bypass list — if so, clear any
            # existing exclusion and let central audio route normally
            bypass_app_ids = excl.get("bypass_app_ids", [])
            if bypass_app_ids and _app_matches(self.hass, entity_id, bypass_app_ids):
                _LOGGER.info(
                    "%s: ATV %s playing bypassed app — exclusion skipped",
                    self.zone_name, entity_id,
                )
                if entity_id in self._atv_excluded_by:
                    self._atv_excluded_by.discard(entity_id)
                    self.hass.async_create_task(self.async_request_refresh())
                return

            # Cancel any pending restore for this entity before re-excluding
            if entity_id in self._atv_restore_handles:
                self._atv_restore_handles.pop(entity_id)()

            self._atv_excluded_by.add(entity_id)
            _LOGGER.info("%s: ATV override by %s", self.zone_name, entity_id)

            if self._is_occupied():
                mp = self.config.get("media_player")
                async with self._lock:
                    if mp:
                        await self._deactivate_zone_immediate(f"ATV override: {entity_id}")
                    amp = excl.get("amp_switch")
                    if amp:
                        await self.hass.services.async_call("switch", "turn_on", {"entity_id": amp})
            else:
                _LOGGER.debug("%s: ATV %s override tracked; amp/zone deferred until occupancy", self.zone_name, entity_id)

        elif new_state_str in ("idle", "off", "paused", "standby"):
            if entity_id not in self._atv_excluded_by:
                return
            if self._should_restore(entity_id, excl):
                restore_delay = int(excl.get("restore_delay_seconds", 0))
                if restore_delay > 0:
                    handle = async_call_later(
                        self.hass, restore_delay,
                        self._make_restore_cb(entity_id, excl),
                    )
                    self._atv_restore_handles[entity_id] = handle
                else:
                    await self._restore_from_atv(entity_id, excl)

        self.async_set_updated_data(self.data)

    def _should_restore(self, entity_id: str, excl: dict) -> bool:
        condition = excl.get("restore_condition", RESTORE_ANY_STOPPED)
        if condition == RESTORE_ANY_STOPPED:
            return True
        if condition == RESTORE_ALL_STOPPED:
            for atv in _excl_entities(excl):
                state = self.hass.states.get(atv)
                if state and state.state == "playing":
                    return False
            return True
        if condition == RESTORE_OCCUPIED:
            return self._is_occupied()
        return True

    async def _restore_from_atv(self, entity_id: str, excl: dict) -> None:
        self._atv_restore_handles.pop(entity_id, None)

        condition = excl.get("restore_condition", RESTORE_ANY_STOPPED)
        # Re-check occupied condition after delay
        if condition == RESTORE_OCCUPIED and not self._is_occupied():
            self._atv_excluded_by.discard(entity_id)
            _LOGGER.info("%s: ATV restore skipped (zone empty)", self.zone_name)
            self.async_set_updated_data(self.data)
            return

        self._atv_excluded_by.discard(entity_id)
        amp = excl.get("amp_switch")
        if amp:
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": amp})
        _LOGGER.info("%s: ATV exclusion cleared for %s", self.zone_name, entity_id)
        await self.async_request_refresh()

    # ── Zone activation / deactivation ───────────────────────────────────────

    async def _activate_zone(self, source: dict) -> None:
        mp = self.config.get("media_player")
        if not mp:
            return

        base_volume = float(source.get("base_volume", 0.7))
        volume = round(max(0.0, min(1.0, base_volume + self._volume_offset)), 2)
        source_name = source.get("source_name")

        _LOGGER.info("%s: activating → source=%s vol=%.2f", self.zone_name, source_name or "none", volume)

        await self.hass.services.async_call("media_player", "turn_on", {"entity_id": mp})

        if source_name:
            state = self.hass.states.get(mp)
            if state and source_name in (state.attributes.get("source_list") or []):
                await self.hass.services.async_call(
                    "media_player", "select_source",
                    {"entity_id": mp, "source": source_name},
                )

        await self.hass.services.async_call(
            "media_player", "volume_set",
            {"entity_id": mp, "volume_level": volume},
        )
        self._zone_active = True

    async def _deactivate_zone(self, reason: str) -> None:
        if self._atv_excluded_by:
            # Zone is in ATV override — clear the override so zone goes dark regardless of
            # whether the ATV responds to turn_off (e.g. AirPlay streams ignore it).
            await self._clear_atv_overrides(reason)
            return
        if not self._zone_active:
            # Cross-check: if the media player is actually on, we still need to turn it off
            # (handles state-sync loss after reload/restart or ATV path)
            mp = self.config.get("media_player")
            if not mp:
                return
            state = self.hass.states.get(mp)
            if not state or state.state in ("off", "unavailable", "unknown"):
                return
        async with self._lock:
            await self._deactivate_zone_immediate(reason)

    async def _clear_atv_overrides(self, reason: str) -> None:
        """Turn off amp and zone when room empties. Only clears _atv_excluded_by for ATVs that
        are no longer playing — if still playing, keeps the override so the amp re-enables on
        next entry instead of letting central audio bleed back in."""
        self._cancel_all_restore_timers()
        exclusions = self.config.get("atv_exclusions", [])
        for entity_id in list(self._atv_excluded_by):
            excl = next((e for e in exclusions if entity_id in _excl_entities(e)), None)
            if excl:
                amp = excl.get("amp_switch")
                if amp:
                    await self.hass.services.async_call("switch", "turn_off", {"entity_id": amp})
            atv_state = self.hass.states.get(entity_id)
            if not atv_state or atv_state.state != "playing":
                self._atv_excluded_by.discard(entity_id)
        _LOGGER.info("%s: ATV amp off (%s); still tracking: %s", self.zone_name, reason, self._atv_excluded_by)
        mp = self.config.get("media_player")
        if mp:
            async with self._lock:
                await self._deactivate_zone_immediate(reason)
        self.hass.async_create_task(self.async_request_refresh())

    async def _activate_atv_overrides(self) -> None:
        """Called when zone becomes occupied while ATV overrides are already active.
        Deactivates central audio and powers amp switches on."""
        exclusions = self.config.get("atv_exclusions", [])
        mp = self.config.get("media_player")
        async with self._lock:
            if mp and self._zone_active:
                await self._deactivate_zone_immediate("ATV override active on entry")
            for entity_id in list(self._atv_excluded_by):
                atv_state = self.hass.states.get(entity_id)
                if not atv_state or atv_state.state != "playing":
                    _LOGGER.debug("%s: skipping amp activate for %s — state is %s", self.zone_name, entity_id, atv_state.state if atv_state else "unknown")
                    continue
                excl = next((e for e in exclusions if entity_id in _excl_entities(e)), None)
                if excl:
                    amp = excl.get("amp_switch")
                    if amp:
                        await self.hass.services.async_call("switch", "turn_on", {"entity_id": amp})
        _LOGGER.info("%s: ATV override amp switches activated on entry", self.zone_name)

    # ── Party mode ────────────────────────────────────────────────────────────

    def _party_suspends_exclusion(self) -> bool:
        """Whether Party Mode should currently bypass this zone's ATV-exclusion gate.

        Safety rule: only suspend the exclusion if NONE of the exclusion rules
        currently holding an override have an amp_switch configured. A configured
        amp_switch means the local ATV drives an alternate physical amp for this
        room — suspending the exclusion there would try to drive the same room
        from both the HTD zone amp and the local amp_switch simultaneously.
        """
        system = self.get_system_coordinator()
        party_active = self._zone_party_active or bool(system and system._party_mode_active)
        if not party_active or not self._atv_excluded_by:
            return party_active

        exclusions = self.config.get("atv_exclusions", [])
        for entity_id in self._atv_excluded_by:
            excl = next((e for e in exclusions if entity_id in _excl_entities(e)), None)
            if excl and excl.get("amp_switch"):
                return False
        return True

    async def async_enable_zone_party_mode(self) -> None:
        self._zone_party_active = True
        _LOGGER.info("%s: zone Party Mode enabled — ATV exclusion suspended (unless amp_switch-guarded)", self.zone_name)
        self.hass.async_create_task(self.async_request_refresh())

    async def async_disable_zone_party_mode(self) -> None:
        self._zone_party_active = False
        _LOGGER.info("%s: zone Party Mode disabled", self.zone_name)
        self.hass.async_create_task(self.async_request_refresh())

    def set_zone_party_mode(self, enabled: bool) -> None:
        if enabled:
            self.hass.async_create_task(self.async_enable_zone_party_mode())
        else:
            self.hass.async_create_task(self.async_disable_zone_party_mode())

    async def _deactivate_zone_immediate(self, reason: str) -> None:
        mp = self.config.get("media_player")
        if not mp:
            return
        _LOGGER.info("%s: deactivating — %s", self.zone_name, reason)
        await self.hass.services.async_call("media_player", "turn_off", {"entity_id": mp})
        self._zone_active = False

    async def _ensure_source(self, source: dict) -> None:
        """Update source/volume on an already-active zone if source changed."""
        mp = self.config.get("media_player")
        if not mp:
            return
        source_name = source.get("source_name")
        if not source_name:
            return
        state = self.hass.states.get(mp)
        if not state:
            return
        if state.attributes.get("source") != source_name:
            if source_name in (state.attributes.get("source_list") or []):
                await self.hass.services.async_call(
                    "media_player", "select_source",
                    {"entity_id": mp, "source": source_name},
                )
        base_volume = float(source.get("base_volume", 0.7))
        volume = round(max(0.0, min(1.0, base_volume + self._volume_offset)), 2)
        current_vol = state.attributes.get("volume_level")
        if current_vol is None or abs(float(current_vol) - volume) > 0.02:
            await self.hass.services.async_call(
                "media_player", "volume_set",
                {"entity_id": mp, "volume_level": volume},
            )

    # ── Main update ───────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict:
        system = self.get_system_coordinator()

        if not system:
            return {"status": STATUS_NO_SYSTEM, "active": False, "routing_mode": ROUTING_NONE}

        if not system._system_active:
            if self._zone_active:
                await self._deactivate_zone("system inactive")
            return {"status": STATUS_SYSTEM_INACTIVE, "active": False, "routing_mode": ROUTING_NONE}

        if not self._follow_me:
            if self._zone_active:
                await self._deactivate_zone("follow-me disabled")
            return {"status": STATUS_FOLLOW_ME_OFF, "active": False, "routing_mode": ROUTING_NONE}

        party_suspended = self._party_suspends_exclusion()
        if self._atv_excluded_by and not party_suspended:
            names = ", ".join(self._atv_excluded_by)
            return {"status": f"{STATUS_ATV_OVERRIDE}: {names}", "active": self._zone_active, "routing_mode": ROUTING_NONE}

        if not self.config.get("media_player"):
            # Amp-only zone — no central audio routing; ATV exclusions handle the amp
            return {"status": STATUS_IDLE, "active": False, "routing_mode": ROUTING_NONE}

        active_source = system.active_source
        occupied = self._is_occupied()

        if active_source and occupied:
            self._cancel_all_deactivate_timers()
            async with self._lock:
                if not self._zone_active:
                    await self._activate_zone(active_source)
                else:
                    await self._ensure_source(active_source)
            suffix = " (party mode)" if (self._atv_excluded_by and party_suspended) else ""
            return {
                "status": f"{STATUS_FOLLOWING}: {active_source['display_name']}{suffix}",
                "active": True,
                "routing_mode": active_source["display_name"],
            }

        if active_source and not occupied:
            # If the zone was manually powered on, honour it — activate source routing
            # so Follow Me works without presence detection.
            mp = self.config.get("media_player")
            if mp:
                mp_state = self.hass.states.get(mp)
                if mp_state and mp_state.state not in ("off", "unavailable", "unknown"):
                    self._cancel_all_deactivate_timers()
                    async with self._lock:
                        if not self._zone_active:
                            await self._activate_zone(active_source)
                        else:
                            await self._ensure_source(active_source)
                    return {
                        "status": f"{STATUS_FOLLOWING}: {active_source['display_name']} (manual)",
                        "active": True,
                        "routing_mode": active_source["display_name"],
                    }
            return {
                "status": STATUS_STANDBY,
                "active": False,
                "routing_mode": active_source["display_name"],
            }

        return {"status": STATUS_IDLE, "active": False, "routing_mode": ROUTING_NONE}

    # ── Public state setters ──────────────────────────────────────────────────

    def set_follow_me(self, enabled: bool) -> None:
        self._follow_me = enabled
        if enabled:
            self._cancel_follow_me_reset()
        else:
            self._schedule_follow_me_reset()
            if self._zone_party_active:
                # Zone Party Mode has no meaning with Follow Me off for this zone.
                self.hass.async_create_task(self.async_disable_zone_party_mode())
        self.hass.async_create_task(self.async_request_refresh())

    def set_volume_offset(self, offset: float) -> None:
        self._volume_offset = offset
        if self._zone_active:
            system = self.get_system_coordinator()
            if system and system.active_source:
                self.hass.async_create_task(self._ensure_source(system.active_source))
