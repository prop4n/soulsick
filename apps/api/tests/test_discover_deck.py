"""Découvrir en pile : quelques artistes vus sous un angle, un autre à chaque visite, chacun avec
sa fiche (d'où il vient, ses genres, ses albums phares) et un extrait à écouter."""

import random
from datetime import UTC, datetime, timedelta

import httpx
from fakes import RG_MBID, peer_with_album
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import AlbumStatus, Artist, DismissedArtist, ReleaseGroup, SimilarArtist
from soulsick.musicbrainz import MusicBrainz, MusicBrainzError

YOURS = ["00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2"]
SLOWDIVE = "20000000-0000-0000-0000-000000000001"


def _mbid(i: int) -> str:
    return f"10000000-0000-0000-0000-{i:012d}"


async def _taste(client, core):
    """Deux artistes suivis : 6 recommandés par les deux, 6 par un seul ; trois artistes de ta
    bibliothèque que tu ne suis pas (Slowdive a 3 albums rangés, les autres 1)."""
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    async with core.db.session() as s:
        ids = []
        for i, mbid in enumerate(YOURS):
            a = Artist(mbid=mbid, name=f"Toi {i}", sort_name=f"Toi {i}", monitored=True)
            s.add(a)
            await s.flush()
            ids.append(a.id)
        for i in range(1, 13):
            for aid in ids if i <= 6 else ids[:1]:
                s.add(SimilarArtist(artist_id=aid, mbid=_mbid(i), name=f"Reco {i}", score=100 - i))
        for mbid, name, albums in ((SLOWDIVE, "Slowdive", 3), (_mbid(90), "Ride", 1), (_mbid(91), "Lush", 1)):
            shelf = Artist(mbid=mbid, name=name, sort_name=name, monitored=False)
            s.add(shelf)
            await s.flush()
            for i in range(albums):
                s.add(ReleaseGroup(
                    mbid=f"{name}-{i}", title=f"Album {i}", artist_id=shelf.id, status=AlbumStatus.IMPORTED,
                ))
        await s.commit()


def _deezer(requests: list[str]) -> httpx.AsyncClient:
    """Deezer, offline: artist 42 has a best-known track with an extract."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if "api.deezer.com/artist/42/top" in url:
            top = {"id": 7, "title": "Alison", "preview": "https://cdn.test/old.mp3"}
            return httpx.Response(200, json={"data": [top]})
        if "api.deezer.com/track/7" in url:
            return httpx.Response(200, json={"id": 7, "preview": "https://cdn.test/fresh.mp3"})
        if url == "https://cdn.test/fresh.mp3":
            return httpx.Response(200, content=b"ID3 extract")
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _musicbrainz(env, requests: list[str], *, status=200) -> MusicBrainz:
    """MusicBrainz, offline, in its JSON shape: Slowdive, its genres and its albums."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if status != 200:
            return httpx.Response(status)
        if request.url.path.endswith(f"/artist/{SLOWDIVE}"):
            return httpx.Response(200, json={
                "id": SLOWDIVE, "name": "Slowdive", "type": "Group", "area": {"name": "United Kingdom"},
                "life-span": {"begin": "1989-10"},
                "genres": [{"name": "dream pop", "count": 21}, {"name": "shoegaze", "count": 26},
                           {"name": "rock", "count": 1}, {"name": "ambient pop", "count": 9}],
                "relations": [
                    {"type": "free streaming", "url": {"resource": "https://www.deezer.com/artist/42"}},
                ],
            })
        if request.url.path.endswith("/release-group"):
            def rg(mbid, title, date, votes, secondary=()):
                return {"id": mbid, "title": title, "first-release-date": date, "primary-type": "Album",
                        "secondary-types": list(secondary), "rating": {"votes-count": votes, "value": 4}}
            return httpx.Response(200, json={"release-groups": [
                rg("rg-just", "Just for a Day", "1991-09-02", 6),
                rg("rg-blue", "Blue Day", "1992-02", 40, ["Compilation"]),
                rg("rg-souvlaki", "Souvlaki", "1993-06-01", 12),
                rg("rg-pygmalion", "Pygmalion", "1995-02-06", 6),
                rg("rg-everything", "everything is alive", "2023-09-01", 4),
            ]})
        return httpx.Response(404)

    return MusicBrainz(env.covers_dir, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_la_pile_ecarte_tes_artistes_les_ecartes_et_les_passes(ctx):  # noqa: F811
    client, core, *_ = ctx
    await _taste(client, core)
    core.discover.client = _deezer([])
    await core.discover.dismiss(_mbid(1))  # pas intéressé
    await client.post("/api/discover/dismiss", json={"mbid": _mbid(2), "days": 30})  # passé
    seen = set()
    for seed in range(12):
        deck = await core.discover.deck(rng=random.Random(seed))
        seen |= {c["mbid"] for c in deck["cards"] if c["artist_id"] is None}
    assert seen and not seen & {_mbid(1), _mbid(2), *YOURS, SLOWDIVE, _mbid(90), _mbid(91)}


async def test_deux_visites_de_suite_n_ont_pas_le_meme_angle(ctx):  # noqa: F811
    client, core, *_ = ctx
    await _taste(client, core)
    core.discover.client = _deezer([])
    kinds = [(await client.get("/api/discover/deck")).json()["angle"]["kind"] for _ in range(6)]
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False)), kinds
    # « Un autre angle » : jamais celui qu'on quitte
    other = (await client.get("/api/discover/deck", params={"avoid": kinds[-1]})).json()["angle"]["kind"]
    assert other != kinds[-1]


async def test_chaque_angle_dit_d_ou_il_vient(ctx):  # noqa: F811
    client, core, *_ = ctx
    await _taste(client, core)
    core.discover.client = _deezer([])
    decks = {}
    for seed in range(40):
        d = await core.discover.deck(rng=random.Random(seed), avoid="none")
        decks.setdefault(d["angle"]["kind"], d)
    assert set(decks) == {"crossing", "wake", "further", "library"}
    crossing = decks["crossing"]
    assert all(len(c["because"]) == 2 for c in crossing["cards"])
    assert {a["name"] for a in crossing["angle"]["artists"]} == {"Toi 0", "Toi 1"}
    assert decks["wake"]["angle"]["artist"]["name"] in {"Toi 0", "Toi 1"}
    assert all(len(c["because"]) == 1 for c in decks["further"]["cards"])
    shelf = {c["name"]: c for c in decks["library"]["cards"]}
    assert set(shelf) == {"Slowdive", "Ride", "Lush"}
    assert shelf["Slowdive"]["shelved"] == 3 and shelf["Slowdive"]["artist_id"]


async def test_un_artiste_passe_revient_au_bout_de_30_jours(ctx):  # noqa: F811
    client, core, *_ = ctx
    await _taste(client, core)
    await client.post("/api/discover/dismiss", json={"mbid": _mbid(3), "days": 30})
    async with core.db.session() as s:
        assert _mbid(3) in await core.discover._hidden(s)
        (await s.get(DismissedArtist, _mbid(3))).until = datetime.now(UTC) - timedelta(days=1)
        await s.commit()
        assert _mbid(3) not in await core.discover._hidden(s)
    # « Pas intéressé » après coup : pour toujours, et un passage ne le rouvre pas
    await client.post("/api/discover/dismiss", json={"mbid": _mbid(4)})
    await client.post("/api/discover/dismiss", json={"mbid": _mbid(4), "days": 30})
    async with core.db.session() as s:
        assert (await s.get(DismissedArtist, _mbid(4))).until is None


async def test_la_fiche_vient_de_musicbrainz_et_se_garde(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    asked: list[str] = []
    core.mb.artist_profile = _musicbrainz(env, asked).artist_profile
    core.discover.client = _deezer([])
    p = (await client.get(f"/api/discover/profile/{SLOWDIVE}")).json()
    assert (p["area"], p["begin_year"], p["type"]) == ("United Kingdom", 1989, "Group")
    assert p["genres"] == ["shoegaze", "dream pop", "ambient pop"], "par votes"
    # Les albums studio d'abord, les plus notés en tête ; une compilation passe après
    assert [r["title"] for r in p["releases"]] == ["Souvlaki", "Just for a Day", "Pygmalion"]
    assert p["releases"][0] == {
        "mbid": "rg-souvlaki", "title": "Souvlaki", "year": "1993", "type": "Album", "state": None,
    }
    assert p["deezer_id"] == 42, "l'id exact, donné par MusicBrainz"
    assert p["track"] == {"title": "Alison", "deezer_id": 7}
    assert len(asked) == 2, "deux requêtes MusicBrainz"

    # Souvlaki rangé entre-temps, Pygmalion demandé : la fiche gardée le dit quand même
    async with core.db.session() as s:
        shelf = Artist(mbid=SLOWDIVE, name="Slowdive", sort_name="Slowdive", monitored=False)
        s.add(shelf)
        await s.flush()
        s.add(ReleaseGroup(
            mbid="rg-souvlaki", title="Souvlaki", artist_id=shelf.id, status=AlbumStatus.IMPORTED,
        ))
        s.add(ReleaseGroup(
            mbid="rg-pygmalion", title="Pygmalion", artist_id=shelf.id, status=AlbumStatus.WANTED,
            monitored=True,
        ))
        await s.commit()
    p = (await client.get(f"/api/discover/profile/{SLOWDIVE}")).json()
    assert len(asked) == 2, "gardée une semaine"
    assert [r["state"] for r in p["releases"]] == ["imported", None, "wanted"]


async def test_l_extrait_passe_par_soulsick(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    core.mb.artist_profile = _musicbrainz(env, []).artist_profile
    core.discover.client = _deezer([])
    r = await client.get(f"/api/discover/preview/{SLOWDIVE}")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3 extract", "le lien du moment, pas celui gardé dans la fiche"


async def test_la_pile_ne_fait_pas_attendre_musicbrainz(ctx):  # noqa: F811
    """Une requête par seconde : la pile part tout de suite avec ce qui est connu, les fiches
    suivent en arrière-plan, dans l'ordre des cartes."""
    client, core, engine, env = ctx
    await _taste(client, core)
    asked: list[str] = []

    async def profile(mbid):
        asked.append(mbid)
        raise MusicBrainzError("offline")

    core.mb.artist_profile = profile
    core.discover.client = _deezer([])
    deck = (await client.get("/api/discover/deck")).json()
    assert all(c["profile"] is None for c in deck["cards"])

    async def all_asked():
        return len(asked) == len(deck["cards"])

    await wait_for(all_asked)
    assert asked == [c["mbid"] for c in deck["cards"]]


async def test_musicbrainz_injoignable_la_pile_reste(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await _taste(client, core)

    async def down(mbid):
        raise MusicBrainzError("MusicBrainz unavailable")

    core.mb.artist_profile = down
    core.discover.client = _deezer([])
    deck = (await client.get("/api/discover/deck")).json()
    assert len(deck["cards"]) >= 3
    assert (await client.get(f"/api/discover/profile/{SLOWDIVE}")).json() == {}
    assert (await client.get(f"/api/discover/preview/{SLOWDIVE}")).status_code == 404


async def test_recuperer_un_album_depuis_decouvrir(ctx):  # noqa: F811
    """L'artiste entre au catalogue sans être suivi, l'album est voulu et part tout de suite."""
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    engine.results = [peer_with_album()]
    r = await client.post("/api/discover/want", json={"artist_mbid": SLOWDIVE, "release_group_mbid": RG_MBID})
    assert r.status_code == 200

    async def downloading():
        return len(engine.downloads) >= 3

    await wait_for(downloading)
    artist = next(a for a in (await client.get("/api/artists")).json() if a["mbid"] == SLOWDIVE)
    assert not artist["monitored"]
    album = next(rg for rg in (await client.get(f"/api/artists/{artist['id']}")).json()["release_groups"]
                 if rg["mbid"] == RG_MBID)
    assert album["monitored"]
