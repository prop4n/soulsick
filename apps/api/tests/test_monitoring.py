"""Suivre un artiste, c'est vouloir ses sorties à venir. Un album se demande à part, que son
artiste soit suivi ou non."""

from datetime import UTC, datetime, timedelta

from fakes import FakeMB, peer_with_album
from test_flow import ctx, wait_for  # noqa: F401

from soulsick import migrations
from soulsick.models import AlbumStatus, Artist, ReleaseGroup


async def _artist(client, follow=True, types=("album", "single")):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "primary_types": list(types), "follow": follow})
    return r.json()["id"]


async def _rgs(client, aid):
    return {rg["title"]: rg for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]}


async def test_suivre_veut_seulement_les_sorties_a_venir(ctx):  # noqa: F811
    client, *_ = ctx
    aid = await _artist(client)
    rgs = await _rgs(client, aid)
    assert rgs["Future Single"]["monitored"] and rgs["Future Single"]["status"] == "wanted"
    for title in ("Nevermind", "Lithium", "MTV Unplugged"):
        assert not rgs[title]["monitored"] and rgs[title]["status"] == "ignored", title


async def test_un_album_demande_d_un_artiste_non_suivi_est_cherche(ctx):  # noqa: F811
    client, core, engine, env = ctx
    aid = await _artist(client, follow=False)
    rgs = await _rgs(client, aid)
    assert not any(rg["monitored"] for rg in rgs.values())
    engine.results = [peer_with_album()]
    r = await client.patch(f"/api/albums/{rgs['Nevermind']['id']}", json={"monitored": True})
    assert r.status_code == 200

    async def downloading():
        return len(engine.downloads) >= 3

    # Cherché tout de suite, pas au prochain passage, et téléchargé sans rien valider
    await wait_for(downloading)


async def test_la_chasse_reprend_un_album_demande_d_un_artiste_non_suivi(ctx):  # noqa: F811
    client, core, engine, env = ctx
    aid = await _artist(client, follow=False)
    rid = (await _rgs(client, aid))["Nevermind"]["id"]
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        rg.monitored, rg.status = True, AlbumStatus.WANTED
        await s.commit()
    engine.results = [peer_with_album()]
    assert await core.hunter.run_wanted(10) == 1


async def test_recuperer_les_manquants_d_une_section(ctx):  # noqa: F811
    client, core, engine, env = ctx
    aid = await _artist(client)
    r = await client.post(f"/api/artists/{aid}/monitor", json={"scope": "all", "section": "single"})
    assert r.json()["changed"] == 1  # Lithium, Future Single l'était déjà
    rgs = await _rgs(client, aid)
    assert rgs["Lithium"]["monitored"] and not rgs["Nevermind"]["monitored"]

    r = await client.post(f"/api/artists/{aid}/monitor", json={"scope": "none"})
    assert not any(rg["monitored"] for rg in (await _rgs(client, aid)).values())
    events = (await client.get("/api/events", params={"kind": "album.bulk"})).json()
    assert len(events) == 2, "une ligne de journal par action groupée"


async def test_suivre_un_artiste_de_la_bibliotheque_ne_cherche_pas_son_passe(ctx):  # noqa: F811
    """Un artiste venu des albums sur le disque : sa discographie n'a jamais été lue. Le suivre
    ne la prend pas pour des nouveautés."""
    client, core, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    artist, _ = await core.catalog._create_artist(
        "x", primary_types=["album", "single"], secondary_types=[], monitored=False, announce=False,
    )
    assert artist.followed_at is None
    assert (await client.post(f"/api/artists/{artist.id}/follow")).status_code == 200
    rgs = await _rgs(client, artist.id)
    assert [t for t, rg in rgs.items() if rg["monitored"]] == ["Future Single"]
    async with core.db.session() as s:
        row = await s.get(Artist, artist.id)
        assert row.monitored and row.followed_at is not None

    # La synchro suivante ne change rien : tout est déjà connu
    await core.catalog.sync_artist(artist.id)
    assert [t for t, rg in (await _rgs(client, artist.id)).items() if rg["monitored"]] == ["Future Single"]


async def test_une_sortie_parue_apres_le_suivi_est_voulue_une_ancienne_non(ctx):  # noqa: F811
    client, core, *_ = ctx
    aid = await _artist(client)
    soon = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    known = FakeMB.artist_release_groups

    async def more(self, mbid):
        return [*await known(self, mbid),
                {"mbid": "new-1", "title": "Nouveau", "primary_type": "album", "secondary_types": [],
                 "first_release_date": soon},
                {"mbid": "old-1", "title": "Bleach", "primary_type": "album", "secondary_types": [],
                 "first_release_date": "1989-06-15"}]

    core.mb.artist_release_groups = more.__get__(core.mb)
    await core.catalog.sync_artist(aid)
    rgs = await _rgs(client, aid)
    assert rgs["Nouveau"]["monitored"] and rgs["Nouveau"]["status"] == "wanted"
    assert not rgs["Bleach"]["monitored"], "ajoutée tard sur MusicBrainz, mais parue avant le suivi"


async def test_ne_plus_suivre_garde_ce_que_tu_as_demande(ctx):  # noqa: F811
    client, core, engine, env = ctx
    aid = await _artist(client)
    rgs = await _rgs(client, aid)
    await client.patch(f"/api/albums/{rgs['Lithium']['id']}", json={"monitored": True})
    assert (await client.delete(f"/api/artists/{aid}/follow")).status_code == 200
    rgs = await _rgs(client, aid)
    assert not rgs["Future Single"]["monitored"], "voulue seulement parce que tu suivais"
    assert rgs["Lithium"]["monitored"]
    assert not (await client.get(f"/api/artists/{aid}")).json()["monitored"]


async def test_changer_les_types_ne_touche_pas_a_ce_que_tu_as_demande(ctx):  # noqa: F811
    client, *_ = ctx
    aid = await _artist(client)
    rgs = await _rgs(client, aid)
    await client.patch(f"/api/albums/{rgs['Lithium']['id']}", json={"monitored": True})
    await client.patch(f"/api/artists/{aid}", json={"primary_types": ["album"]})
    rgs = await _rgs(client, aid)
    assert not rgs["Future Single"]["monitored"], "un single à venir n'est plus guetté"
    assert rgs["Lithium"]["monitored"]


async def test_un_artiste_en_pause_ne_se_met_pas_a_telecharger(ctx):  # noqa: F811
    """Avant, les albums voulus d'un artiste en pause n'étaient jamais cherchés. Ils ne le
    deviennent pas d'un coup : ils ne sont plus voulus."""
    client, core, *_ = ctx
    paused = await _artist(client, follow=False)
    async with core.db.session() as s:
        for rg in (await s.execute(ReleaseGroup.__table__.select())).all():
            row = await s.get(ReleaseGroup, rg.id)
            row.monitored, row.status = True, AlbumStatus.WANTED
        await s.commit()
    await core.settings.set_raw(migrations.KEY, {"done": ["everything_automatic"]})
    assert await migrations.run(core) == ["follow_means_upcoming"]
    assert not any(rg["monitored"] for rg in (await _rgs(client, paused)).values())
