"""Zone turn-off vs a fading speaker. Run: python3 tests/test_zone_off_race.py (no HA install needed).

The HTD speaker (htd_mc 1.3.0) fades down for ~6 s on turn_off and keeps reporting "on" (state
writes with fading=true) until it powers off. HA also serialises service calls per entity for
that platform (sync update -> PARALLEL_UPDATES 1), so a turn_on sent mid-fade runs right after
the off. Before v0.7.3 DCA marked the zone inactive as soon as the (non-blocking) turn_off was
queued, read the fade's "on" writes as a manual power-on and turned the speaker straight back
on, every off-delay, forever (2026-11-20).
"""
import asyncio
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(__file__), "..", "custom_components")
sys.path.insert(0, os.path.abspath(ROOT))

# ── Minimal homeassistant stubs ──
for name in ["homeassistant", "homeassistant.config_entries", "homeassistant.core",
             "homeassistant.helpers", "homeassistant.helpers.device_registry",
             "homeassistant.helpers.event", "homeassistant.helpers.update_coordinator",
             "homeassistant.util", "homeassistant.util.dt"]:
    sys.modules[name] = types.ModuleType(name)
sys.modules["homeassistant.config_entries"].ConfigEntry = object
sys.modules["homeassistant.core"].HomeAssistant = object
sys.modules["homeassistant.core"].callback = lambda f: f
dr = sys.modules["homeassistant.helpers.device_registry"]
dr.DeviceInfo = type("DeviceInfo", (), {"__annotations__": {}})
sys.modules["homeassistant.helpers"].device_registry = dr
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]


def async_call_later(hass, delay, cb):
    handle = asyncio.get_running_loop().call_later(delay, cb, None)
    return handle.cancel


sys.modules["homeassistant.helpers.event"].async_call_later = async_call_later


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_interval=None, config_entry=None):
        self.hass = hass
        self.data = None

    async def async_request_refresh(self):
        self.data = await self._async_update_data()

    def async_set_updated_data(self, data):
        self.data = data


sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = DataUpdateCoordinator

# The package __init__ pulls in all of HA; load only const + coordinator under a bare package.
pkg = types.ModuleType("dynamic_central_audio")
pkg.__path__ = [os.path.join(os.path.abspath(ROOT), "dynamic_central_audio")]
sys.modules["dynamic_central_audio"] = pkg
import importlib  # noqa: E402
coordinator = importlib.import_module("dynamic_central_audio.coordinator")

MP = "media_player.main_floor"
OCC = "binary_sensor.main_floor_common_area_occupied"
FADE_STEPS, STEP_SEC = 5, 0.05


class State:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class States:
    def __init__(self):
        self._s = {}

    def get(self, eid):
        return self._s.get(eid)

    def is_state(self, eid, st):
        s = self._s.get(eid)
        return s is not None and s.state == st


class FakeHass:
    """Speaker behaves like htd_mc 1.3.0: per-entity serialised calls, audible fade on off."""

    def __init__(self):
        self.states = States()
        self.data = {}
        self.listeners = []        # zone media player state-change callbacks
        self.calls = []            # (service, time) in the order the speaker ran them
        self._entity_lock = asyncio.Lock()
        self.services = types.SimpleNamespace(async_call=self.async_call)

    def async_create_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)

    def set_state(self, eid, state, attrs=None):
        self.states._s[eid] = State(state, attrs)
        if eid == MP:
            for cb in self.listeners:
                cb(types.SimpleNamespace(data={"entity_id": eid, "new_state": self.states._s[eid]}))

    async def _run(self, service, data):
        async with self._entity_lock:      # PARALLEL_UPDATES 1
            self.calls.append(service)
            cur = self.states.get(MP)
            attrs = dict(cur.attributes) if cur else {}
            if service == "turn_off" and cur and cur.state == "on":
                vol = attrs.get("volume_level", 0.8)
                for i in range(FADE_STEPS):    # fade down: still "on", fading, volume dropping
                    await asyncio.sleep(STEP_SEC)
                    self.set_state(MP, "on", {**attrs, "fading": True,
                                              "volume_level": round(vol * (1 - (i + 1) / FADE_STEPS), 2)})
                self.set_state(MP, "off", {"source_list": attrs.get("source_list"), "fading": False})
            elif service == "turn_on":
                self.set_state(MP, "on", {**attrs, "fading": False, "volume_level": 0.8,
                                          "source": "AirPlay", "source_list": ["AirPlay"]})
            elif service == "volume_set":
                if cur and cur.state == "on":
                    self.set_state(MP, "on", {**attrs, "volume_level": data["volume_level"]})
            elif service == "select_source":
                if cur and cur.state == "on":
                    self.set_state(MP, "on", {**attrs, "source": data["source"]})

    async def async_call(self, domain, service, data, blocking=False):
        if domain != "media_player":
            return
        task = self.async_create_task(self._run(service, data))
        if blocking:
            await task


SOURCE = {"display_name": "AirPlay (Central)", "source_name": "AirPlay", "base_volume": 0.8}


def make_zone():
    hass = FakeHass()
    system = types.SimpleNamespace(_system_active=True, _party_mode_active=False, active_source=SOURCE, config={})
    hass.data[coordinator.DOMAIN] = {"sys": system}
    zone = coordinator.ZoneCoordinator(
        hass, "Main Floor",
        {"system_entry_id": "sys", "media_player": MP, "occupancy_sensors": [OCC], "off_delay_seconds": 1},
        None)
    hass.listeners.append(zone.handle_zone_mp_change)
    hass.set_state(OCC, "on")
    hass.set_state(MP, "off", {"source_list": ["AirPlay"]})
    return hass, zone


async def settle(sec=0.6):
    await asyncio.sleep(sec)


async def test_occupancy_off_stays_off():
    """Room empties, off-delay fires, speaker fades down -> it must stay off."""
    hass, zone = make_zone()
    await zone.async_request_refresh()           # occupied: DCA turns it on
    await settle()
    assert hass.states.get(MP).state == "on" and zone._zone_active and not zone._manual_on

    hass.set_state(OCC, "off")
    await zone.async_request_refresh()           # empty: off-delay timer armed
    zone._schedule_occ_deactivate()
    assert "(manual)" not in zone.data["status"]

    await asyncio.sleep(1.0 + FADE_STEPS * STEP_SEC + 0.6)   # timer + fade + any re-on
    await zone.async_request_refresh()           # the 60 s poll
    await settle()

    after_off = hass.calls[hass.calls.index("turn_off") + 1:]
    assert "turn_on" not in after_off, f"speaker turned back on after the off: {hass.calls}"
    assert hass.states.get(MP).state == "off", hass.states.get(MP).state
    assert not zone._zone_active and not zone._manual_on
    assert "(manual)" not in zone.data["status"], zone.data["status"]


async def test_manual_on_still_detected():
    """A person powering the speaker on in an empty room is still honoured as manual."""
    hass, zone = make_zone()
    hass.set_state(OCC, "off")
    await zone.async_request_refresh()
    assert not zone._zone_active
    await hass._run("turn_on", {})               # someone presses power on the keypad/app
    await settle()
    assert zone._manual_on and zone._zone_active, (zone._manual_on, zone._zone_active)
    assert zone.data["status"].endswith("(manual)"), zone.data["status"]


async def test_reentry_during_fade_turns_back_on():
    """Someone walks back in while the speaker is fading out -> it comes back on (not manual)."""
    hass, zone = make_zone()
    await zone.async_request_refresh()
    await settle()
    hass.set_state(OCC, "off")
    zone._occ_deactivate_cb(None)                # off-delay fires
    await asyncio.sleep(STEP_SEC * 2)            # mid-fade
    hass.set_state(OCC, "on")
    zone.handle_occupancy_change(types.SimpleNamespace(data={"new_state": hass.states.get(OCC)}))
    await settle(1.0)
    assert hass.states.get(MP).state == "on", hass.calls
    assert zone._zone_active and not zone._manual_on, (zone._zone_active, zone._manual_on)


def main():
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and asyncio.iscoroutinefunction(fn):
            try:
                asyncio.run(fn())
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
