"""En mode auto, la première piste est demandée à plusieurs sources comparables : l'album va à la
première qui envoie, pas à celle qui a le meilleur score sur le papier.

Cas réel (homelab, novembre 2026) : la moitié des sources retenues n'a jamais rien envoyé, et un
album attendait jusqu'à 30 minutes par source muette avant de passer à la suivante.
"""

from fakes import TRACKS, peer_with_album
from sqlalchemy import select
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import Candidate, Event, Transfer, TransferState

FILE1 = f"01 - {TRACKS[0][0]}.flac"


async def _auto_album(client, core, engine, peers, race_seconds=180):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    settings = await core.settings.get()
    settings.hunter.race_seconds = race_seconds
    await core.settings.save(settings)
    core.hunter.race_poll = 0.02
    r = await client.post("/api/artists", json={"mbid": "x", "primary_types": ["album"], "monitor": "none"})
    aid = r.json()["id"]
    rid = next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
               if rg["title"] == "Nevermind")
    engine.results = [peer_with_album(p) for p in peers]
    await core.hunter.hunt(rid)
    return rid


async def _candidates(core, rid):
    async with core.db.session() as s:
        return {c.username: c for c in (await s.execute(select(Candidate).where(Candidate.release_group_id == rid))).scalars()}


async def _kinds(core):
    async with core.db.session() as s:
        return [e.kind for e in (await s.execute(select(Event).order_by(Event.id))).scalars()]


async def test_l_album_va_au_premier_pair_qui_envoie(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[f"muet:{FILE1}"] = ["hold"]  # accepte, n'envoie jamais
    rid = await _auto_album(client, core, engine, ["muet", "fiable"])

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    cands = await _candidates(core, rid)
    assert cands["muet"].status == "proposed"  # rendu aux propositions, pas en échec
    asked = [(u, p.rsplit("\\", 1)[-1]) for u, p, _ in engine.downloads]
    assert ("muet", FILE1) in asked and [n for u, n in asked if u == "muet"] == [FILE1]  # rien d'autre
    assert sorted(n for u, n in asked if u == "fiable") == sorted(f"{i + 1:02d} - {t}.flac" for i, (t, _) in enumerate(TRACKS))
    async with core.db.session() as s:
        probe = (await s.execute(select(Transfer).where(Transfer.username == "muet"))).scalar_one()
    assert probe.state == TransferState.ABORTED and probe.candidate_id is None
    assert "hunt.race_won" in await _kinds(core)


async def test_personne_n_envoie_l_album_reste_au_meilleur(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[f"muet:{FILE1}"] = ["hold"]
    engine.script[f"lent:{FILE1}"] = ["hold"]
    rid = await _auto_album(client, core, engine, ["muet", "lent"], race_seconds=1)

    async def decided():
        return "hunt.race_none" in await _kinds(core)

    await wait_for(decided)

    async def settled():
        # The other source given back, and the rest of the album asked from muet (a moment later)
        cands = await _candidates(core, rid)
        if not all(c.status != "chosen" or c.username == "muet" for c in cands.values()):
            return False
        async with core.db.session() as s:
            n = len(list((await s.execute(select(Transfer).where(Transfer.candidate_id == cands["muet"].id))).scalars()))
        return n == len(TRACKS)

    await wait_for(settled)
    cands = await _candidates(core, rid)
    assert cands["muet"].status == "chosen" and cands["lent"].status == "proposed"
    async with core.db.session() as s:
        rows = list((await s.execute(select(Transfer).where(Transfer.candidate_id == cands["muet"].id))).scalars())
    assert len(rows) == len(TRACKS)  # sa première piste gardée (toujours en attente), pas redemandée
    assert [p for u, p, _ in engine.downloads if u == "muet"].count(rows[0].remote_path) == 1


async def test_tous_refusent_le_meilleur_repart_de_zero(ctx):  # noqa: F811
    client, core, engine, env = ctx
    engine.script[f"muet:{FILE1}"] = ["fail:File not shared.", "complete"]
    engine.script[f"lent:{FILE1}"] = ["fail:File not shared."]
    rid = await _auto_album(client, core, engine, ["muet", "lent"])

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    async with core.db.session() as s:
        failed = list((await s.execute(select(Transfer).where(Transfer.state == TransferState.FAILED))).scalars())
    assert failed and all(t.candidate_id is None for t in failed)  # les essais refusés ne pèsent pas sur la source


async def test_un_seul_pair_pas_de_course(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _auto_album(client, core, engine, ["seul"])

    async def imported():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(imported)
    assert "hunt.race_started" not in await _kinds(core)
