"""Restarting the engine never leaves a second Soulseek client behind.

The VPN port loop and saving the settings both restart the engine; when two restarts overlap, the
client of the first must not stay logged in next to the new one (same port, wrong account)."""

import asyncio

import pytest

from soulsick.settings_store import SoulseekSettings
from soulsick.slsk import engine as engine_module
from soulsick.slsk.engine import SlskEngine


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, settings) -> None:
        self.settings = settings
        self.stopped = False
        self.shares = type("Shares", (), {"rules": {}})()
        self.events = type("Events", (), {"register": lambda self, event, handler: None})()
        FakeClient.instances.append(self)

    async def start(self) -> None:
        await asyncio.sleep(0.01)

    async def login(self) -> None:
        await asyncio.sleep(0.01)

    async def stop(self) -> None:
        # aioslsk closes its connections: other tasks run meanwhile
        await asyncio.sleep(0.01)
        self.stopped = True


@pytest.fixture
def engine(tmp_path, monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(engine_module, "_Client", FakeClient)
    return SlskEngine(str(tmp_path))


def alive() -> list[FakeClient]:
    return [c for c in FakeClient.instances if not c.stopped]


async def test_overlapping_restarts_leave_a_single_client(engine):
    old = SoulseekSettings(username="old", password="p")
    new = SoulseekSettings(username="new", password="p")
    await engine.start(old, [])
    await asyncio.sleep(0.05)
    assert len(alive()) == 1

    # The port changes while the settings are being saved
    await asyncio.gather(engine.start(old, []), engine.start(new, []))
    await asyncio.sleep(0.1)

    assert [c.settings.credentials.username for c in alive()] == ["new"]
    assert engine.client is alive()[0]

    await engine.stop()
    assert alive() == []


async def test_stop_during_connection_stops_the_client_being_connected(engine):
    await engine.start(SoulseekSettings(username="u", password="p"), [])
    await asyncio.sleep(0.005)  # inside client.start()
    await engine.stop()
    await asyncio.sleep(0.05)
    assert alive() == []
