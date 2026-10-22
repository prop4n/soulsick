"""Retenir une édition plus longue : l'album devient partiel et la piste en plus est cherchée.

Cas réel : « Batterie Faible » rangé en 11 pistes ; l'édition retirée « With Amnésie » en a 12.
La retenir ne changeait rien : le total venait des tags des fichiers (11), pas de l'édition choisie.
"""

from fakes import TRACKS, peer_with_album
from sqlalchemy import select
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import Release, Track


async def test_retenir_une_edition_plus_longue_rend_l_album_partiel(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "mode": "validation", "primary_types": ["album"], "monitor": "all"})
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{r.json()['id']}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)
    cid = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]["id"]
    await client.post(f"/api/candidates/{cid}/approve")

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)

    # Une autre édition, avec une piste en plus
    async with core.db.session() as s:
        rel = Release(mbid="rel-bonus", release_group_id=rid, title="Nevermind (with bonus)", track_count=4, disc_count=1)
        rel.tracks = [
            Track(mbid=f"tb{i}", recording_mbid=f"r{i}", disc=1, position=i + 1, number=str(i + 1), title=t, length_ms=ln)
            for i, (t, ln) in enumerate([*TRACKS, ("Endless, Nameless", 400000)])
        ]
        s.add(rel)
        await s.commit()
        bonus = rel.id

    hunts_before = len(engine.downloads)
    engine.results = []  # nobody has it yet: the hunt runs, finds nothing
    r = await client.patch(f"/api/albums/{rid}", json={"selected_release_id": bonus})
    assert r.status_code == 200, r.text
    album = r.json()
    assert (album["present_tracks"], album["total_tracks"]) == (3, 4)
    assert album["status"] == "wanted"
    assert album["status_reason_t"] == {"key": "reason.partial", "params": {"n": 3, "total": 4}}

    async def hunted():
        events = (await client.get("/api/events", params={"release_group_id": rid})).json()
        return sum(e["kind"] == "hunt.started" for e in events) >= 2

    await wait_for(hunted)
    assert len(engine.downloads) == hunts_before

    # Revenir à l'édition d'origine : complet de nouveau
    async with core.db.session() as s:
        first = (await s.execute(select(Release.id).where(Release.release_group_id == rid, Release.mbid != "rel-bonus"))).scalar_one()
    album = (await client.patch(f"/api/albums/{rid}", json={"selected_release_id": first})).json()
    assert (album["present_tracks"], album["total_tracks"]) == (3, 3)
    assert album["status"] == "imported"
