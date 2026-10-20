"""Musique déjà présente (ex. téléchargée avec slskd, sans tags MusicBrainz) : reconnaître, taguer, ranger."""

import os

from fakes import TRACKS, tiny_flac
from test_flow import ctx  # noqa: F401

from soulsick.audiotags import read_meta


async def test_import_de_l_existant(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    # Un album « brut » comme slskd le laisse : noms de fichiers du pair, aucun tag MusicBrainz
    raw = env.music_dir / "slskd" / "Nirvana - Nevermind (1991) [FLAC]"
    for i, (title, length) in enumerate(TRACKS):
        tiny_flac(raw / f"{i + 1:02d}. {title}.flac", length // 1000)
    (raw / "folder.jpg").write_bytes(b"jpg")
    await core.library.scan()

    groups = (await client.get("/api/library/existing")).json()["groups"]
    g = next(x for x in groups if x["dir"].endswith("Nevermind (1991) [FLAC]"))
    assert g["guess"] == {"artist": "Nirvana", "album": "Nevermind"}

    res = (await client.post("/api/library/existing/identify", json={"dir": g["dir"]})).json()
    best = res["proposals"][0]
    assert best["title"] == "Nevermind" and best["safe"] and best["matched"] == 3

    r = await client.post("/api/library/existing/apply", json={
        "dir": g["dir"], "release_group_mbid": best["release_group_mbid"],
        "release_mbid": best["release_mbid"], "follow": False,
    })
    assert r.status_code == 200, r.text
    dest = env.music_dir / "Nirvana" / "1991 - Nevermind"
    assert (dest / "02 - In Bloom.flac").exists()
    assert (dest / "folder.jpg").exists(), "les annexes suivent l'album"
    assert not raw.exists(), "l'ancien dossier vide est supprimé"
    assert not raw.parent.exists(), "le parent devenu vide aussi"
    assert env.music_dir.exists(), "jamais au-delà de /music"
    assert read_meta(dest / "02 - In Bloom.flac").release_group_mbid == best["release_group_mbid"]

    album = (await client.get(f"/api/albums/{r.json()['release_group_id']}")).json()
    assert album["status"] == "imported"
    artist = (await client.get(f"/api/artists/{album['artist_id']}")).json()
    assert artist["monitored"] is False, "suivre l'artiste n'était pas coché"
    assert (await client.get("/api/library/existing")).json()["groups"] == []
    assert engine.downloads == [], "rien n'est téléchargé"


async def test_dossier_hors_bibliotheque_refuse(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/library/existing/identify", json={"dir": "/etc"})
    assert r.status_code == 400
    assert os.path.exists("/etc")
