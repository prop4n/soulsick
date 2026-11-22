"""Une taille préférée par album, pas une limite : un dossier plus lourd que ce que tu préfères
passe derrière un dossier plus léger du même album, et il est quand même pris quand il est seul."""

from fakes import TRACKS, peer_with_album
from sqlalchemy import update
from test_flow import ctx, hunt_only  # noqa: F401

from soulsick.models import Artist
from soulsick.scoring import PeerResult, RemoteFile


def _hires(user: str = "hirespeer") -> PeerResult:
    """Le même album en 24 bits, à 100 Mo la piste."""
    files = [
        RemoteFile(
            f"@@hires\\Nirvana\\Nevermind [24-96]\\{i + 1:02d} - {t}.flac",
            size=100_000_000, bit_depth=24, duration=ln // 1000,
        )
        for i, (t, ln) in enumerate(TRACKS)
    ]
    return PeerResult(user, True, 1_500_000, 0, files)


async def _nevermind(client) -> int:
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={
        "mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da", "primary_types": ["album"], "monitor": "none",
    })
    albums = (await client.get(f"/api/artists/{r.json()['id']}")).json()["release_groups"]
    return next(rg["id"] for rg in albums if rg["title"] == "Nevermind")


async def _hunter(client, **values) -> None:
    settings = (await client.get("/api/settings")).json()
    settings["hunter"].update(values)
    assert (await client.put("/api/settings", json=settings)).status_code == 200


async def _profile(client, name: str) -> int:
    return next(p["id"] for p in (await client.get("/api/profiles")).json() if p["name"] == name)


async def test_par_defaut_la_qualite_cd_passe_devant_le_24_bits(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _nevermind(client)
    engine.results = [_hires(), peer_with_album()]
    await hunt_only(core, rid)
    cands = (await client.get(f"/api/albums/{rid}")).json()["candidates"]
    assert [c["username"] for c in cands] == ["goodpeer", "hirespeer"]
    assert all("size" not in c["score_detail"] for c in cands)


async def test_le_profil_choisi_vaut_pour_tous_les_albums(ctx):  # noqa: F811
    """Plus de profil par artiste : celui des réglages, même si l'artiste en avait un autre."""
    client, core, engine, env = ctx
    rid = await _nevermind(client)
    await _hunter(client, profile_id=await _profile(client, "Hi-res"))
    mp3 = await _profile(client, "MP3 320")
    async with core.db.session() as s:
        await s.execute(update(Artist).values(quality_profile_id=mp3))
        await s.commit()
    engine.results = [peer_with_album(), _hires()]
    await core.hunter.hunt(rid)
    # Le 24 bits passe devant, et part tout seul : rien à valider
    assert {d[0] for d in engine.downloads} == {"hirespeer"}


async def test_un_dossier_plus_lourd_passe_derriere_et_dit_pourquoi(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _nevermind(client)
    await _hunter(client, profile_id=await _profile(client, "Hi-res"), preferred_album_mb=250)
    engine.results = [peer_with_album(), _hires()]
    await hunt_only(core, rid)
    cands = (await client.get(f"/api/albums/{rid}")).json()["candidates"]
    assert [c["username"] for c in cands] == ["goodpeer", "hirespeer"]
    assert "size" not in cands[0]["score_detail"]
    assert cands[1]["score_detail"]["size"] == {"points": -40.0, "mb": 100 * len(TRACKS), "preferred": 250}
    assert cands[1]["score"] < cands[0]["score"]


async def test_seul_le_dossier_plus_lourd_est_quand_meme_pris(ctx):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _nevermind(client)
    await _hunter(client, preferred_album_mb=250)
    engine.results = [_hires()]
    await core.hunter.hunt(rid)
    # Une préférence ne laisse jamais un album sans source
    assert {d[0] for d in engine.downloads} == {"hirespeer"}
