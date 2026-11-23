"""Améliorer un album déjà là : seules les pistes qui gagnent quelque chose sont demandées, et un
dossier qui n'apporte rien n'est plus repris (cas réel : un EP retéléchargé 47 fois)."""

from fakes import peer_with_album
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import LibraryFile, ReleaseGroup
from sqlalchemy import select


async def _imported(client, core, engine):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "primary_types": ["album"], "monitor": "all"})
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    engine.results = [peer_with_album("p1")]
    await core.hunter.hunt(rid)

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    return rid, imported


async def test_seule_la_piste_a_ameliorer_est_demandee_puis_plus_rien(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid, imported = await _imported(client, core, engine)
    # Track 2 is only there as an MP3: the album is to be upgraded
    async with core.db.session() as s:
        files = sorted((await s.execute(select(LibraryFile))).scalars(), key=lambda f: f.path)
        files[1].format = "mp3-192"
        rg = await s.get(ReleaseGroup, rid)
        rg.status, rg.imported_format = "wanted", "mp3-192"
        await s.commit()

    before = len(engine.downloads)
    await core.hunter.hunt(rid)
    await wait_for(imported)
    asked = engine.downloads[before:]
    assert len(asked) == 1, asked
    assert "02 - " in str(asked[0])

    # Everything is FLAC now: the same folder brings nothing, nothing is asked any more
    async with core.db.session() as s:
        formats = {f.format for f in (await s.execute(select(LibraryFile))).scalars()}
        rg = await s.get(ReleaseGroup, rid)
        rg.status = "wanted"
        await s.commit()
    assert formats == {"flac"}
    before = len(engine.downloads)
    await core.hunter.hunt(rid)
    assert len(engine.downloads) == before
    album = (await client.get(f"/api/albums/{rid}")).json()
    latest = max((c for c in album["candidates"] if c["status"] == "rejected"), key=lambda c: c["id"])
    assert latest["reject_reason_t"]["key"] == "reject.brings_nothing"
    assert album["status_reason_t"]["key"] == "reason.nothing_better"

    # The transfers page knows which album each file is for, and how many sources were tried
    rows = (await client.get("/api/transfers")).json()
    assert rows[0]["album"]["title"] == "Nevermind" and rows[0]["album"]["attempts"] == 2
