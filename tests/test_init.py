"""The integration in a real (test) Home Assistant, fed by a fake rusthinq."""

import asyncio
import json
from datetime import timedelta

import pytest
from conftest import AC, EMBEDDED
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CoreState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.rusthinq.const import DOMAIN, MODE_EMBEDDED, PLATFORMS


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    return


async def eventually(hass, check, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.01)
            await hass.async_block_till_done()


def climate_entity(hass) -> str | None:
    registry = er.async_get(hass)
    return next((e.entity_id for e in registry.entities.values() if e.platform == DOMAIN and e.domain == "climate"),
                None)


def appliances(hass, entry) -> list:
    """The entry's devices but the rusthinq service device."""
    return [d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
            if d.entry_type is not dr.DeviceEntryType.SERVICE]


def entry_platforms(hass, entry) -> list[str]:
    """The platforms now set up for the entry (`async_get_platforms` also lists the ones unloaded since)."""
    return [domain for domain in PLATFORMS
            if domain in hass.config.components and entry.entry_id in hass.data[domain]._platforms]


async def setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MODE_EMBEDDED, data=EMBEDDED)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_platforms_are_ildevices():
    from ildevice_ha.const import PLATFORMS as ILDEVICE_PLATFORMS

    assert PLATFORMS == ILDEVICE_PLATFORMS


async def test_a_device_appears_under_this_domain_and_takes_commands(hass, air_conditioner):
    entry = await setup(hass)
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)))
    entity_id = climate_entity(hass)
    state = hass.states.get(entity_id)
    assert state.attributes["temperature"] == 18
    assert state.attributes["current_temperature"] == 24

    devices = appliances(hass, entry)
    assert [d.identifiers for d in devices] == [{(DOMAIN, AC)}]

    await hass.services.async_call("climate", "set_temperature", {"entity_id": entity_id, "temperature": 22},
                                   blocking=True)
    await eventually(hass, lambda: air_conditioner.invokes)
    device_id, body = air_conditioner.invokes[0]
    assert device_id == AC
    assert json.loads(body["input"]) == {"prop": "target", "value": "22"}

    await air_conditioner.output(AC, f"rusthinq/{AC}/target", "22")
    await eventually(hass, lambda: hass.states.get(entity_id).attributes["temperature"] == 22)


async def test_entities_are_unavailable_while_the_daemon_is_unreachable(hass, air_conditioner):
    await setup(hass)
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)))
    entity_id = climate_entity(hass)
    await air_conditioner.stop()
    await eventually(hass, lambda: hass.states.get(entity_id).state == STATE_UNAVAILABLE)


async def test_unload(hass, air_conditioner):
    entry = await setup(hass)
    await eventually(hass, lambda: climate_entity(hass))
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(climate_entity(hass)).state == STATE_UNAVAILABLE


async def test_the_platform_modules_load_with_the_integration():
    """Forwarding the entry imports what is not loaded yet in the import executor, where it waits behind every other
    integration's imports while Home Assistant starts."""
    import sys

    import custom_components.rusthinq  # noqa: F401

    for platform in PLATFORMS:
        assert f"custom_components.rusthinq.{platform}" in sys.modules
        assert f"homeassistant.components.{platform}" in sys.modules


async def test_while_home_assistant_starts_the_platforms_are_set_up_in_setup(hass, air_conditioner):
    """Entities that appear only after the start are an `unavailable` -> value change to automations at every restart."""
    hass.set_state(CoreState.starting)
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert set(entry_platforms(hass, entry)) == set(PLATFORMS)
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)))


async def test_a_reload_sets_the_platforms_up_again(hass, air_conditioner):
    entry = await setup(hass)
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await eventually(hass, lambda: hass.states.get(climate_entity(hass)).state != STATE_UNAVAILABLE)


async def test_a_failed_start_is_retried_by_home_assistant_and_leaves_nothing_running(hass, air_conditioner,
                                                                                      monkeypatch):
    from conftest import StubDaemon

    from custom_components.rusthinq.client import ManagementClient

    real_start = ManagementClient.start
    calls = []

    async def failing_once(self):
        calls.append(self)
        if len(calls) == 1:
            raise RuntimeError("boom")
        await real_start(self)

    stopped = []

    async def counting_stop(self):
        stopped.append(self)

    monkeypatch.setattr(ManagementClient, "start", failing_once)
    monkeypatch.setattr(StubDaemon, "async_stop", counting_stop)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MODE_EMBEDDED, data=EMBEDDED)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not entry_platforms(hass, entry) and len(stopped) == 1

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
    await eventually(hass, lambda: entry.state is ConfigEntryState.LOADED)
    assert len(calls) == 2
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)).state
                     != STATE_UNAVAILABLE)


async def test_the_config_flow_offers_no_connection_to_a_running_rusthinq(hass):
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert menu["menu_options"] == ["embedded", "migrate"]


async def test_an_old_url_entry_is_not_set_up(hass, rusthinq):
    entry = MockConfigEntry(domain=DOMAIN, data={"url": rusthinq.url, "prefix": "rusthinq"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "no longer supported" in entry.reason


async def test_the_device_is_named_after_rusthinqs_name(hass, air_conditioner):
    air_conditioner.devices[AC]["name"] = "거실에어컨"
    entry = await setup(hass)
    await eventually(hass, lambda: climate_entity(hass))
    devices = appliances(hass, entry)
    assert [d.name for d in devices] == ["거실에어컨"]


async def test_a_command_rusthinq_refuses_fires_the_rejection_event(hass, air_conditioner):
    from ildevice_ha.const import EVENT_COMMAND_REJECTED

    events = []
    hass.bus.async_listen(EVENT_COMMAND_REJECTED, events.append)
    await setup(hass)
    await eventually(hass, lambda: climate_entity(hass) and hass.states.get(climate_entity(hass)))
    air_conditioner.cloud_failure = (503, "shutting down")
    await hass.services.async_call("climate", "set_temperature", {"entity_id": climate_entity(hass),
                                                                  "temperature": 22}, blocking=True)
    await eventually(hass, lambda: events)
    assert {k: events[0].data.get(k) for k in ("prop", "code")} == {"prop": "target", "code": "unavailable"}


async def test_an_image_property_creates_an_image_entity(hass, rusthinq):
    desc = {
        "il": 0,
        "id": "vac01",
        "props": {"map": {"type": "image", "label": "Cleaning Map"}},
    }
    rusthinq.add_device("vac01", [{"topic": "rusthinq/vac01/descriptor", "payload": json.dumps(desc)}])
    await setup(hass)
    registry = er.async_get(hass)
    await eventually(
        hass,
        lambda: any(e.domain == "image" for e in registry.entities.values()),
    )
    image_entity = next(e for e in registry.entities.values() if e.domain == "image")
    assert image_entity.platform == DOMAIN

