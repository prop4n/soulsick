"""Plus de mode « me demander » ni de profil par artiste : ce que devient une installation
existante, et le profil choisi dans les réglages."""

from test_flow import ctx  # noqa: F401

from soulsick import migrations
from soulsick.messages import M, set_reason
from soulsick.models import AlbumStatus, Artist, QualityProfile, ReleaseGroup


async def _old_install(core, *, profiles, artists):
    """Une base d'avant : ses profils (nom, formats), ses artistes (suivi, nom du profil)."""
    async with core.db.session() as s:
        for p in list((await s.execute(QualityProfile.__table__.select())).all()):
            await s.delete(await s.get(QualityProfile, p.id))
        await s.flush()
        ids = {}
        for name, formats in profiles:
            row = QualityProfile(name=name, formats=formats, upgrade_until="flac")
            s.add(row)
            await s.flush()
            ids[name] = row.id
        for i, (monitored, profile) in enumerate(artists):
            s.add(Artist(mbid=f"a{i}", name=f"A{i}", mode="validation", monitored=monitored,
                         quality_profile_id=ids.get(profile)))
        await s.commit()
    await core.settings.set_raw(migrations.KEY, {"done": []})
    return ids


async def _album(core, status, reason):
    async with core.db.session() as s:
        artist = (await s.execute(Artist.__table__.select().limit(1))).first()
        rg = ReleaseGroup(
            mbid=f"rg-{reason.key}", title=reason.key, artist_id=artist.id, status=status, monitored=True,
        )
        set_reason(rg, "status_reason", reason)
        s.add(rg)
        await s.commit()
        return rg.id


async def test_le_profil_le_plus_utilise_par_les_suivis_reste_celui_de_tous(ctx):  # noqa: F811
    _client, core, *_ = ctx
    ids = await _old_install(
        core,
        profiles=[("Lossless", ["flac-24", "flac"]), ("MP3 320", ["mp3-320"])],
        # Les artistes pas suivis ne comptent pas
        artists=[(True, "MP3 320"), (True, "MP3 320"), (True, "Lossless"), (False, "Lossless"),
                 (False, "Lossless")],
    )
    assert await migrations.run(core) == ["everything_automatic"]
    assert (await core.settings.get()).hunter.profile_id == ids["MP3 320"]
    async with core.db.session() as s:
        assert (await core.catalog.quality_profile(s)).name == "MP3 320"


async def test_un_profil_qualite_cd_est_ajoute_une_seule_fois(ctx):  # noqa: F811
    client, core, *_ = ctx
    await _old_install(core, profiles=[("Lossless", ["flac-24", "flac"])], artists=[(True, None)])
    await migrations.run(core)
    async with core.db.session() as s:
        names = {p.name: p.formats for p in (await s.execute(QualityProfile.__table__.select())).all()}
    assert names["CD quality"][0] == "flac"
    # Sans profil le plus utilisé : le premier, comme avant
    assert (await core.settings.get()).hunter.profile_id is None
    async with core.db.session() as s:
        assert (await core.catalog.quality_profile(s)).name == "Lossless"
        by_name = QualityProfile.__table__.select().where(QualityProfile.name == "CD quality")
        cd = (await s.execute(by_name)).first()
        await s.delete(await s.get(QualityProfile, cd.id))
        await s.commit()
    # Supprimé par toi : il ne revient pas au démarrage suivant
    assert await migrations.run(core) == []
    async with core.db.session() as s:
        names = {p.name for p in (await s.execute(QualityProfile.__table__.select())).all()}
    assert "CD quality" not in names


async def test_les_albums_en_attente_de_validation_repartent_en_chasse(ctx):  # noqa: F811
    _client, core, *_ = ctx
    await _old_install(core, profiles=[("CD", ["flac"])], artists=[(True, "CD")])
    waiting = await _album(core, AlbumStatus.PENDING_APPROVAL, M("reason.awaiting", n=3))
    failed = await _album(core, AlbumStatus.PENDING_APPROVAL, M("reason.chosen_failed"))
    incomplete = await _album(core, AlbumStatus.PENDING_APPROVAL, M("reason.incomplete_action", reason="2/3"))
    await migrations.run(core)
    async with core.db.session() as s:
        for rid in (waiting, failed):
            rg = await s.get(ReleaseGroup, rid)
            assert (rg.status, rg.last_searched_at, rg.status_reason) == (AlbumStatus.WANTED, None, None)
        # Un import incomplet attend vraiment ta décision : il reste
        assert (await s.get(ReleaseGroup, incomplete)).status == AlbumStatus.PENDING_APPROVAL


async def test_le_profil_choisi_ne_se_supprime_pas(ctx):  # noqa: F811
    client, core, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    profiles = (await client.get("/api/profiles")).json()
    first, other = profiles[0]["id"], profiles[1]["id"]
    r = await client.delete(f"/api/profiles/{first}")
    assert r.status_code == 409 and r.json()["detail"]["key"] == "error.profile_chosen"
    # Un autre, même encore attaché à un artiste d'avant, part sans histoire
    async with core.db.session() as s:
        s.add(Artist(mbid="old", name="Old", quality_profile_id=other))
        await s.commit()
    assert (await client.delete(f"/api/profiles/{other}")).status_code == 200
    async with core.db.session() as s:
        artist = (await s.execute(Artist.__table__.select().where(Artist.mbid == "old"))).first()
    assert artist.quality_profile_id is None
