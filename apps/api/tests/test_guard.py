"""Library guard: nothing is shelved into, or forgotten because of, a library folder that isn't there."""

import os
import shutil

from fakes import peer_with_album
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.services import libguard
from soulsick.services.libguard import mount_kind

MOUNTINFO = (
    "193 180 0:50 / / rw,relatime - overlay overlay rw\n"
    "202 193 259:4 /propan/soulsick/data/music /music rw,relatime - ext4 /dev/nvme0n1p4 rw\n"
    "203 193 259:4 /propan/My\\040Music /media/my\\040music rw,relatime - ext4 /dev/nvme0n1p4 rw\n"
    "253 244 259:2 /var/lib/docker/volumes/" + "a1" * 32 + "/_data /downloads rw - ext4 /dev/nvme0n1p2 rw\n"
    "254 244 259:2 /var/lib/docker/volumes/soulsick_config/_data /config rw - ext4 /dev/nvme0n1p2 rw\n"
)


def test_mount_kind():
    assert mount_kind("/music", MOUNTINFO) == "host"
    assert mount_kind("/music/Nirvana", MOUNTINFO) == "host"
    assert mount_kind("/media/my music", MOUNTINFO) == "host"
    assert mount_kind("/downloads", MOUNTINFO) == "anonymous"
    assert mount_kind("/config", MOUNTINFO) == "host", "a named volume is a deliberate choice"
    assert mount_kind("/musicx", MOUNTINFO) == "none"
    assert mount_kind("/srv", MOUNTINFO) == "none"
    assert mount_kind("/music", None) is None


async def _imported_album(client, core, engine):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={
        "mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da", "mode": "auto", "primary_types": ["album"], "monitor": "all",
    })
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    return rid


async def test_unmounted_library_is_never_used(ctx, monkeypatch):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _imported_album(client, core, engine)
    # In a container, the library folder is only the container's own disk
    core.guard.require_mount = True
    monkeypatch.setattr(libguard, "_read_mountinfo", lambda: "1 0 0:1 / / rw - overlay overlay rw\n")

    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)

    async def held():
        a = (await client.get(f"/api/albums/{rid}")).json()
        return a["status"] == "needs_review" and a["status_reason_t"]["key"] == "reason.library_unavailable"

    await wait_for(held)
    assert not any(env.music_dir.rglob("*.flac")), "nothing shelved into the container"
    st = (await client.get("/api/status")).json()["library_guard"]
    assert not st["ok"] and st["problem_t"]["key"] == "library.guard.not_mounted"

    # The volume is fixed: the album is imported on its own
    mountinfo = f"1 0 0:1 / / rw - overlay overlay rw\n2 1 8:1 /home/me/music {env.music_dir} rw - ext4 /dev/sda1 rw\n"
    monkeypatch.setattr(libguard, "_read_mountinfo", lambda: mountinfo)
    assert (await client.post("/api/library/guard/check")).json()["ok"]

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    assert any(env.music_dir.rglob("*.flac"))


async def test_emptied_library_is_not_forgotten(ctx, tmp_path):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _imported_album(client, core, engine)
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    await core.library.scan()
    files = (await client.get("/api/status")).json()["library"]["files"]
    assert files == 3

    # Disk unplugged: the folder is there but empty
    away = tmp_path / "away"
    shutil.move(str(env.music_dir), away)
    os.makedirs(env.music_dir)
    assert (await core.library.scan()) == {"skipped": True}
    assert (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported", "album not forgotten"
    st = (await client.get("/api/status")).json()
    assert st["library"]["files"] == 3
    assert st["library_guard"]["problem_t"]["key"] == "library.guard.emptied"
    # Manual imports are refused too, with a translatable error
    r = await client.post(f"/api/albums/{rid}/import")
    assert r.status_code == 409 and r.json()["detail"]["key"] == "error.library_unavailable"

    # Plugged back: everything is as before
    shutil.rmtree(env.music_dir)
    shutil.move(str(away), env.music_dir)
    assert (await client.post("/api/library/guard/check")).json()["ok"]

    # Really emptied on purpose: the person confirms, the files are forgotten
    shutil.rmtree(env.music_dir)
    os.makedirs(env.music_dir)
    assert not (await client.post("/api/library/guard/check")).json()["ok"]
    r = await client.post("/api/library/guard/confirm-empty")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["removed"] == 3
    assert (await client.get("/api/status")).json()["library"]["files"] == 0
    assert (await client.get(f"/api/albums/{rid}")).json()["status"] == "wanted"


async def test_confirm_empty_refused_when_library_is_fine(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/library/guard/confirm-empty")
    assert r.status_code == 400 and r.json()["detail"]["key"] == "error.library_not_empty_case"
