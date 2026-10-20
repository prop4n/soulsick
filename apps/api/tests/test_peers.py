"""Peer page: what we exchanged with a peer, and its network profile."""

from fakes import peer_with_album
from test_flow import ctx, wait_for  # noqa: F401


async def test_peer_history_and_profile(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={
        "mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da", "mode": "auto", "primary_types": ["album"], "monitor": "all",
    })
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    h = (await client.get("/api/peers/goodpeer")).json()
    assert h["downloads"]["complete"] == 3 and h["downloads"]["failed"] == 0 and h["downloads"]["bytes"] > 0
    assert h["uploads"] is None
    assert [(a["id"], a["candidate_status"], a["artist"]) for a in h["albums"]] == [(rid, "imported", "Nirvana")]
    assert len(h["recent"]) == 3

    unknown = (await client.get("/api/peers/nobody")).json()
    assert unknown["downloads"] is None and unknown["albums"] == [] and unknown["recent"] == []

    p = (await client.get("/api/peers/goodpeer/profile")).json()
    assert p["status"] == "online" and p["shared_files"] == 1234
    await client.get("/api/peers/goodpeer/profile")
    assert engine.profiles_asked == 1, "cached for a minute"
    await client.get("/api/peers/goodpeer/profile", params={"refresh": True})
    assert engine.profiles_asked == 2


async def test_browse_unreachable_peer_is_a_clear_error(ctx):  # noqa: F811
    from aioslsk.exceptions import PeerConnectionError

    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})

    async def fail(username, timeout=90):
        raise PeerConnectionError(f"failed to connect to peer {username}")

    async def status(username):
        return engine.status_of

    engine.browse = fail
    engine.user_status = status
    engine.status_of = "online"
    r = await client.get("/api/users/rubiksenjoyer/browse")
    assert r.status_code == 502 and r.json()["detail"]["key"] == "error.peer_unreachable"
    engine.status_of = "offline"
    r = await client.get("/api/users/rubiksenjoyer/browse")
    assert r.status_code == 502 and r.json()["detail"]["key"] == "error.peer_offline"
