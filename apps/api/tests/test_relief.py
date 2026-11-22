"""Une source qui n'envoie rien au bout d'une minute, même si le pair a accepté, est mise en
concurrence avec d'autres sources de la même édition : l'album passe à la première qui envoie,
sans aide manuelle, y compris quand tu avais choisi la source toi-même.

Cas réel (homelab, novembre 2026) : Minecraft - Volume Beta validé chez un pair qui avait accepté
19 pistes sur 30 et n'envoyait rien. Rien ne l'aurait jamais lâché : soulsick ne lâche que les
pairs qui n'acceptent rien. 25 autres sources de la même édition attendaient. Des sources qui ont
envoyé un jour, 92 % l'ont fait en moins d'une minute, et aucune après 5.
"""

from datetime import UTC, datetime, timedelta

from fakes import TRACKS, peer_with_album
from sqlalchemy import select
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import Candidate, Event, Transfer
from soulsick.scoring import RemoteFile

FILES = [f"{i + 1:02d} - {t}.flac" for i, (t, _) in enumerate(TRACKS)]


async def _approved(client, core, engine, peers, chosen, extra=()):
    """Album en mode validation, `chosen` approuvé à la main ; ses fichiers ne partent jamais."""
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    settings = await core.settings.get()
    settings.hunter.race_seconds = 1
    await core.settings.save(settings)
    core.hunter.race_poll = 0.02
    r = await client.post("/api/artists", json={"mbid": "x", "mode": "validation", "primary_types": ["album"], "monitor": "none"})
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    for f in FILES:
        engine.script[f"{chosen}:{f}"] = ["hold"]  # accepté, jamais envoyé
    engine.results = [*extra, *(peer_with_album(p) for p in peers)]
    await core.hunter.hunt(rid)
    cid = next(c["id"] for c in (await client.get(f"/api/albums/{rid}")).json()["candidates"] if c["username"] == chosen)
    await client.post(f"/api/candidates/{cid}/approve")
    async with core.db.session() as s:  # demandés il y a 2 minutes, comme dans le cas réel
        for t in (await s.execute(select(Transfer).where(Transfer.candidate_id == cid))).scalars():
            t.requested_at = datetime.now(UTC) - timedelta(minutes=2)
        await s.commit()
    return rid


async def _candidates(core, rid):
    async with core.db.session() as s:
        return {c.username: c for c in (await s.execute(select(Candidate).where(Candidate.release_group_id == rid))).scalars()}


async def _kinds(core):
    async with core.db.session() as s:
        return [e.kind for e in (await s.execute(select(Event).order_by(Event.id))).scalars()]


async def test_une_source_qui_n_envoie_rien_est_relevee_sans_toi(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _approved(client, core, engine, ["muet", "fiable"], chosen="muet")

    async def silent_long_enough():
        await core.hunter.check_silent()
        return "download.relief_started" in await _kinds(core)

    await wait_for(silent_long_enough)

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    cands = await _candidates(core, rid)
    assert cands["muet"].status == "failed"
    assert sorted(p.rsplit("\\", 1)[-1] for u, p, _ in engine.downloads if u == "fiable") == sorted(FILES)
    assert "download.relieved" in await _kinds(core)
    assert await core.peers.track_records({"muet"}) == {"muet": "silent"}  # retenu pour la prochaine fois


async def test_personne_ne_releve_la_source_garde_sa_place(ctx):  # noqa: F811
    client, core, engine, env = ctx
    for f in FILES:
        engine.script[f"lent:{f}"] = ["hold"]
    rid = await _approved(client, core, engine, ["muet", "lent"], chosen="muet")

    async def nobody():
        await core.hunter.check_silent()
        return "download.relief_none" in await _kinds(core)

    await wait_for(nobody)

    async def settled():
        return (await _candidates(core, rid))["lent"].status == "proposed"

    await wait_for(settled)
    assert (await _candidates(core, rid))["muet"].status == "chosen"
    # lent a déjà été essayé pour muet : le tour suivant ne le redemande pas
    await core.hunter.check_silent()
    assert (await _kinds(core)).count("download.relief_started") == 1


async def test_la_releve_garde_le_format_choisi(ctx):  # noqa: F811
    """Cas réel : Volume Beta choisi en FLAC 16 bits (663 Mo), relevé par une source en 24 bits
    (2,85 Go). Mieux, mais 4 fois plus lourd : la relève reste au format choisi."""
    client, core, engine, env = ctx
    heavy = peer_with_album("lourd")
    heavy.files = [RemoteFile(f.filename, size=f.size, bit_depth=24, sample_rate=96000, duration=f.duration)
                   for f in heavy.files]
    # en tête des résultats, et meilleur score
    rid = await _approved(client, core, engine, ["muet", "pareil"], chosen="muet", extra=[heavy])

    async def relieved():
        await core.hunter.check_silent()
        return "download.relieved" in await _kinds(core)

    await wait_for(relieved)
    assert not [u for u, _, _ in engine.downloads if u == "lourd"]
    assert (await _candidates(core, rid))["pareil"].status == "chosen"
