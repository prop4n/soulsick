"""Imports interrompus par un redémarrage, et deux albums qui demandent le même fichier."""

import os

from sqlalchemy import select
from test_flow import ctx, wait_for  # noqa: F401
from test_retry import _setup

from soulsick.models import AlbumStatus, Candidate, ReleaseGroup, Transfer


async def _status(client, rid):
    return (await client.get(f"/api/albums/{rid}")).json()["status"]


async def _set_status(core, rid, status):
    async with core.db.session() as s:
        (await s.get(ReleaseGroup, rid)).status = status
        await s.commit()


async def test_import_interrompu_apres_rangement_redevient_importe(ctx):  # noqa: F811
    """Cas réel : soulsick redémarré pendant le scan de la bibliothèque qui finit un import. Les
    fichiers étaient rangés, mais l'album restait « importing » pour toujours (0 fichier affiché)."""
    client, core, engine, env = ctx
    rid = await _setup(client, core, engine, mode="auto")

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)
    await _set_status(core, rid, AlbumStatus.IMPORTING)  # le redémarrage tombe là

    await core._recover()
    await core.library.scan()
    assert await _status(client, rid) == "imported"


async def test_import_interrompu_avant_rangement_est_relance(ctx):  # noqa: F811
    """Redémarrage avant le déplacement des fichiers : ils sont encore dans la réception, l'import
    est relancé au démarrage."""
    client, core, engine, env = ctx
    real_import = core.importer.import_candidate

    async def killed(candidate_id):  # le redémarrage tombe avant l'import
        return None

    core.importer.import_candidate = killed
    rid = await _setup(client, core, engine, mode="auto")

    async def received():
        async with core.db.session() as s:
            return (await s.execute(
                select(Candidate).where(Candidate.release_group_id == rid, Candidate.status == "downloaded")
            )).scalar_one_or_none() is not None

    await wait_for(received)
    await _set_status(core, rid, AlbumStatus.IMPORTING)
    core.importer.import_candidate = real_import

    await core._recover()

    async def imported():
        return await _status(client, rid) == "imported"

    await wait_for(imported)


async def test_deux_albums_demandent_le_meme_fichier(ctx):  # noqa: F811
    """Cas réel : MusicBrainz a deux fiches pour le même single ; les deux demandent le même
    morceau à la même source. Un seul téléchargement est suivi par fichier et par source : le
    second album attendait un fichier qui n'arrivait jamais dans son dossier."""
    client, core, engine, env = ctx
    engine.script = {name: ["hold"] for name in ("01 - Smells Like Teen Spirit.flac",)}
    rid = await _setup(client, core, engine)  # validation : rien ne démarre seul
    first = (await client.get(f"/api/albums/{rid}")).json()["candidates"][0]["id"]

    # La seconde fiche : même artiste, autre identifiant, et le même dossier chez le même pair
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        twin = ReleaseGroup(
            mbid="twin-rg", artist_id=rg.artist_id, title=rg.title, primary_type=rg.primary_type,
            secondary_types=[], first_release_date=rg.first_release_date, monitored=True,
            status=AlbumStatus.PENDING_APPROVAL,
        )
        s.add(twin)
        await s.flush()
        c = await s.get(Candidate, first)
        dup = Candidate(
            release_group_id=twin.id, username=c.username, directory=c.directory, files=c.files,
            format=c.format, score=c.score, score_detail=c.score_detail, status="proposed",
        )
        s.add(dup)
        await s.commit()
        second = dup.id

    await core.hunter.start_download(first)
    await core.hunter.start_download(second)
    asked = [p for _, p, _ in engine.downloads]
    assert len(asked) == len(set(asked)) == 3, "chaque fichier n'est demandé qu'une fois"

    # Le morceau retenu arrive enfin : les deux albums l'ont, chacun dans son dossier
    async with core.db.session() as s:
        held = (await s.execute(
            select(Transfer).where(Transfer.candidate_id == first, Transfer.remote_path.like("%Teen Spirit%"))
        )).scalar_one()
    await engine.emit(held.username, held.remote_path, held.local_path, "complete")

    async def both_received():
        async with core.db.session() as s:
            rows = (await s.execute(
                select(Transfer).where(Transfer.candidate_id.in_([first, second]))
            )).scalars()
            return all(t.state == "complete" for t in rows)

    await wait_for(both_received)
    async with core.db.session() as s:
        dup_rows = list((await s.execute(select(Transfer).where(Transfer.candidate_id == second))).scalars())
    # Le second album a reçu sa propre copie, dans son dossier, et n'attend plus rien
    teen = next(t for t in dup_rows if "Teen Spirit" in t.remote_path)
    assert teen.local_path != held.local_path
    assert os.path.isfile(teen.local_path)
    assert all(t.state == "complete" for t in dup_rows)
