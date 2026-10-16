"""Relances de transferts : une relance ne doit jamais perdre le lien avec l'album."""

import asyncio

from fakes import TRACKS, peer_with_album
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import Transfer
from sqlalchemy import select

FILE2 = f"02 - {TRACKS[1][0]}.flac"


async def _setup(client, core, engine, mode="validation"):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "mode": mode, "primary_types": ["album"], "monitor": "all"})
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    engine.results = [peer_with_album()]
    core.hunter.retry_delays = [0.05, 0.05]
    await core.hunter.hunt(rid)
    return rid


async def _rows(core):
    async with core.db.session() as s:
        return list((await s.execute(select(Transfer).order_by(Transfer.id))).scalars())


async def _status(client, rid):
    return (await client.get(f"/api/albums/{rid}")).json()["status"]


async def test_echec_temporaire_relance_automatiquement(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[FILE2] = ["fail"]  # 1er essai refusé, 2e essai OK
    rid = await _setup(client, core, engine, mode="auto")

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)
    rows = await _rows(core)
    assert len(rows) == 3, "une ligne par fichier, jamais de doublon"
    assert all(t.candidate_id is not None for t in rows)
    second = next(t for t in rows if t.remote_path.endswith(FILE2))
    assert second.attempts == 2


async def test_relance_manuelle_reutilise_la_ligne(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[FILE2] = ["fail", "fail", "fail"]  # épuise les essais automatiques
    rid = await _setup(client, core, engine)
    best = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]
    await client.post(f"/api/candidates/{best['id']}/approve")

    async def gave_up():
        return await _status(client, rid) in ("pending_approval", "wanted")

    await wait_for(gave_up)
    failed = next(t for t in await _rows(core) if t.remote_path.endswith(FILE2))
    assert failed.state == "failed"

    r = await client.post(f"/api/transfers/{failed.id}/retry")  # cette fois le pair accepte
    assert r.status_code == 200

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)
    rows = await _rows(core)
    assert len(rows) == 3
    assert next(t for t in rows if t.id == failed.id).state == "complete"


async def test_reprendre_un_candidat_ne_retelecharge_que_le_manquant(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[FILE2] = ["fail", "fail", "fail"]
    rid = await _setup(client, core, engine)
    cid = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]["id"]
    await client.post(f"/api/candidates/{cid}/approve")

    async def gave_up():
        return await _status(client, rid) in ("pending_approval", "wanted")

    await wait_for(gave_up)
    before = len(engine.downloads)
    r = await client.post(f"/api/candidates/{cid}/approve")  # « Reprendre »
    assert r.status_code == 200

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)
    assert len(engine.downloads) - before == 1, "seul le fichier manquant est redemandé"
    assert len(await _rows(core)) == 3


async def test_arrivee_tardive_apres_abandon(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[FILE2] = ["fail", "fail", "fail"]
    rid = await _setup(client, core, engine)
    cid = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]["id"]
    await client.post(f"/api/candidates/{cid}/approve")

    async def gave_up():
        return await _status(client, rid) in ("pending_approval", "wanted")

    await wait_for(gave_up)
    # aioslsk finit par recevoir le fichier tout seul (le pair a relancé de son côté)
    t = next(t for t in await _rows(core) if t.remote_path.endswith(FILE2))
    from fakes import tiny_flac
    from pathlib import Path
    tiny_flac(Path(t.local_path), TRACKS[1][1] // 1000)
    await engine.emit(t.username, t.remote_path, t.local_path, "queued")
    await engine.emit(t.username, t.remote_path, t.local_path, "complete")

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)
    assert len(await _rows(core)) == 3
    await asyncio.sleep(0)


async def test_reprise_au_demarrage_reactive_le_candidat(ctx):  # noqa: F811
    """Un fichier relancé au démarrage pour un candidat abandonné : l'album doit redevenir « téléchargement »."""
    client, core, engine, env = ctx
    engine.script[FILE2] = ["fail", "fail", "fail", "hold"]
    rid = await _setup(client, core, engine)
    cid = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]["id"]
    await client.post(f"/api/candidates/{cid}/approve")

    async def gave_up():
        return await _status(client, rid) in ("pending_approval", "wanted")

    await wait_for(gave_up)
    t = next(t for t in await _rows(core) if t.remote_path.endswith(FILE2))
    async with core.db.session() as s:
        row = await s.get(Transfer, t.id)
        row.state = "queued"  # comme après la réparation des orphelins
        await s.commit()

    await core._resume_downloads()
    album = (await client.get(f"/api/albums/{rid}")).json()
    assert album["status"] == "downloading"
    assert next(c for c in album["candidates"] if c["id"] == cid)["status"] == "chosen"
