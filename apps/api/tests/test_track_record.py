"""Un pair resté muet la dernière fois passe après un pair qui envoie, à album égal.

Cas réel (homelab, novembre 2026) : les 107 sources retenues annonçaient toutes un slot libre,
et 58 n'ont rien envoyé. Ce que le pair a fait la fois d'avant prédisait la suivante 45 fois sur 48.
"""

from datetime import UTC, datetime, timedelta

from fakes import peer_with_album
from test_flow import ctx, hunt_only  # noqa: F401

from soulsick.models import Candidate, CandidateStatus, Transfer, TransferState


async def _album(client):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "primary_types": ["album"], "monitor": "all"})
    aid = r.json()["id"]
    return next(rg["id"] for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]
                if rg["title"] == "Nevermind")


async def _past_source(core, rid, username, *, sent: bool, waited: timedelta):
    """Une source d'avant, chez ce pair : il a envoyé, ou il n'a rien envoyé pendant `waited`."""
    asked = datetime.now(UTC) - timedelta(days=2)
    async with core.db.session() as s:
        c = Candidate(release_group_id=rid, username=username, directory="old", files=[],
                      status=CandidateStatus.DOWNLOADED if sent else CandidateStatus.FAILED)
        s.add(c)
        await s.flush()
        s.add(Transfer(
            direction="download", username=username, remote_path="old\\01.flac", candidate_id=c.id,
            release_group_id=rid, requested_at=asked, completed_at=asked + waited,
            state=TransferState.COMPLETE if sent else TransferState.ABORTED,
            bytes_transferred=100 if sent else 0, started_at=asked if sent else None,
        ))
        await s.commit()


async def _order(client, core, engine, rid):
    engine.results = [peer_with_album("muet"), peer_with_album("fiable")]
    await hunt_only(core, rid)
    return [c["username"] for c in await _proposals(client, rid)]


async def _proposals(client, rid):
    return [c for c in (await client.get(f"/api/albums/{rid}")).json()["candidates"] if c["status"] == "proposed"]


async def test_un_pair_muet_la_derniere_fois_passe_apres(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _album(client)
    await _past_source(core, rid, "muet", sent=False, waited=timedelta(minutes=30))

    assert (await _order(client, core, engine, rid))[:2] == ["fiable", "muet"]
    records = {c["username"]: c["score_detail"]["peer"]["record"] for c in await _proposals(client, rid)}
    assert records == {"fiable": None, "muet": "silent"}


async def test_un_pair_qui_a_deja_envoye_passe_devant_un_inconnu(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _album(client)
    await _past_source(core, rid, "fiable", sent=True, waited=timedelta(minutes=1))

    assert (await _order(client, core, engine, rid))[:2] == ["fiable", "muet"]


async def test_une_source_remplacee_vite_ne_rend_pas_le_pair_muet(ctx):  # noqa: F811
    """Abandonnée au bout de 30 secondes (tu as pris quelqu'un d'autre) : rien à en conclure."""
    client, core, engine, env = ctx
    rid = await _album(client)
    await _past_source(core, rid, "muet", sent=False, waited=timedelta(seconds=30))

    assert await core.peers.track_records({"muet"}) == {}
    assert (await _order(client, core, engine, rid))[:2] == ["muet", "fiable"]
