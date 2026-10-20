"""One track of an album downloaded by hand: identified, tagged, shelved; the album shows as partial."""

from fakes import TRACKS, peer_with_album, tiny_flac
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.models import Transfer


async def _manual_track(core, env, title="In Bloom", position=2):
    folder = env.downloads_dir / "manual" / "bob" / "Nevermind"
    path = folder / f"{position:02d} - {title}.flac"
    tiny_flac(path, 254)
    async with core.db.session() as s:
        s.add(Transfer(direction="download", username="bob", remote_path=f"@@m\\Nevermind\\{path.name}",
                       local_path=str(path), size=path.stat().st_size, state="complete"))
        await s.commit()
    return folder


async def test_single_manual_track_is_shelved_and_album_partial(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    folder = await _manual_track(core, env)

    manual = (await client.get("/api/library/manual")).json()
    assert manual[0]["present"] == 1 and manual[0]["shelved"] == 0
    desc = (await client.get("/api/library/manual/folder", params={"dir": str(folder)})).json()
    assert desc["files"] == 1 and desc["guess"]["album"] == "Nevermind"

    res = (await client.post("/api/library/existing/identify", json={"dir": str(folder)})).json()
    best = res["proposals"][0]
    assert best["partial"] and best["matched"] == 1 and len(best["missing_tracks"]) == 2
    assert best["safe"], "a single well-matched track is a safe partial import"

    r = await client.post("/api/library/existing/apply", json={
        "dir": str(folder), "release_group_mbid": best["release_group_mbid"],
        "release_mbid": best["release_mbid"], "follow": False,
    })
    assert r.status_code == 200, r.text
    shelved = env.music_dir / "Nirvana" / "1991 - Nevermind" / "02 - In Bloom.flac"
    assert shelved.exists() and not folder.exists()

    rid = r.json()["release_group_id"]
    album = (await client.get(f"/api/albums/{rid}")).json()
    assert album["status"] == "imported", "not followed: shown in the library, nothing downloaded"
    assert (album["present_tracks"], album["total_tracks"]) == (1, 3)
    assert engine.downloads == []

    manual = (await client.get("/api/library/manual")).json()
    assert manual[0]["shelved"] == 1 and manual[0]["present"] == 0 and manual[0]["albums"] == [rid]


async def test_followed_partial_album_gets_completed(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    folder = await _manual_track(core, env)
    best = (await client.post("/api/library/existing/identify", json={"dir": str(folder)})).json()["proposals"][0]
    r = await client.post("/api/library/existing/apply", json={
        "dir": str(folder), "release_group_mbid": best["release_group_mbid"],
        "release_mbid": best["release_mbid"], "follow": True,
    })
    rid = r.json()["release_group_id"]
    await client.patch(f"/api/albums/{rid}", json={"monitored": True})
    await core.library.refresh_all()
    album = (await client.get(f"/api/albums/{rid}")).json()
    assert album["status"] == "wanted"
    assert album["status_reason_t"] == {"key": "reason.partial", "params": {"n": 1, "total": 3}}

    # The hunt completes it: same format is fine for a partial album, the hand-shelved track is replaced
    await client.patch(f"/api/artists/{album['artist_id']}", json={"mode": "auto"})
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)

    async def complete():
        a = (await client.get(f"/api/albums/{rid}")).json()
        return a["status"] == "imported" and a["present_tracks"] == 3

    await wait_for(complete)


async def test_completing_a_partial_album_never_duplicates_a_track(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    folder = await _manual_track(core, env)
    best = (await client.post("/api/library/existing/identify", json={"dir": str(folder)})).json()["proposals"][0]
    body = {"release_group_mbid": best["release_group_mbid"], "release_mbid": best["release_mbid"], "follow": False}
    await client.post("/api/library/existing/apply", json={"dir": str(folder), **body})
    album_dir = env.music_dir / "Nirvana" / "1991 - Nevermind"
    # The lone track ended up under another name (e.g. an MP3, or another edition's numbering)
    (album_dir / "02 - In Bloom.flac").rename(album_dir / "02 - In Bloom (single).flac")
    await core.library.scan()

    # Later, the whole album is downloaded by hand and shelved
    full = env.downloads_dir / "manual" / "alice" / "Nirvana - Nevermind"
    for i, (title, length) in enumerate(TRACKS):
        tiny_flac(full / f"{i + 1:02d} - {title}.flac", length // 1000)
    best = (await client.post("/api/library/existing/identify", json={"dir": str(full)})).json()["proposals"][0]
    r = await client.post("/api/library/existing/apply", json={"dir": str(full), **body})
    assert r.status_code == 200, r.text

    files = sorted(p.name for p in album_dir.glob("*.flac"))
    assert files == ["01 - Smells Like Teen Spirit.flac", "02 - In Bloom.flac", "03 - Come as You Are.flac"]
    album = (await client.get(f"/api/albums/{r.json()['release_group_id']}")).json()
    assert (album["present_tracks"], album["total_tracks"]) == (3, 3)


async def test_hunt_completes_around_a_hand_shelved_track(ctx):  # noqa: F811
    """One track shelved by hand, the others downloaded: the album imports without it, and keeps it."""
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    folder = await _manual_track(core, env)
    best = (await client.post("/api/library/existing/identify", json={"dir": str(folder)})).json()["proposals"][0]
    r = await client.post("/api/library/existing/apply", json={
        "dir": str(folder), "release_group_mbid": best["release_group_mbid"], "release_mbid": best["release_mbid"], "follow": True,
    })
    rid = r.json()["release_group_id"]
    album_dir = env.music_dir / "Nirvana" / "1991 - Nevermind"
    hand = album_dir / "02 - In Bloom.flac"
    hand_bytes = hand.read_bytes()

    # The peer only has the two other tracks
    peer = peer_with_album()
    peer.files = [f for f in peer.files if "In Bloom" not in f.filename]
    await client.patch(f"/api/albums/{rid}", json={"monitored": True})
    await core.library.refresh_all()
    await client.patch(f"/api/artists/{(await client.get(f'/api/albums/{rid}')).json()['artist_id']}", json={"mode": "auto"})
    engine.results = [peer]
    await core.hunter.hunt(rid)

    async def complete():
        a = (await client.get(f"/api/albums/{rid}")).json()
        return a["status"] == "imported" and a["present_tracks"] == 3

    await wait_for(complete)
    assert sorted(p.name for p in album_dir.glob("*.flac")) == [
        "01 - Smells Like Teen Spirit.flac", "02 - In Bloom.flac", "03 - Come as You Are.flac",
    ]
    assert hand.read_bytes() == hand_bytes, "the hand-shelved track is kept, untouched"


async def test_replace_one_lower_quality_track(ctx):  # noqa: F811
    """An MP3 among FLACs: only that track is taken from a peer that has it better, the old file goes."""
    from soulsick.models import LibraryFile

    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    folder = await _manual_track(core, env)
    best = (await client.post("/api/library/existing/identify", json={"dir": str(folder)})).json()["proposals"][0]
    r = await client.post("/api/library/existing/apply", json={
        "dir": str(folder), "release_group_mbid": best["release_group_mbid"], "release_mbid": best["release_mbid"], "follow": True,
    })
    rid = r.json()["release_group_id"]
    # Pretend the hand-shelved track is an MP3
    async with core.db.session() as s:
        from sqlalchemy import update
        await s.execute(update(LibraryFile).values(format="mp3-320"))
        await s.commit()

    # The album comes from a peer without that track; another peer has the whole album in FLAC
    partial = peer_with_album("partialpeer")
    partial.files = [f for f in partial.files if "In Bloom" not in f.filename]
    await client.patch(f"/api/albums/{rid}", json={"monitored": True})
    engine.results = [partial, peer_with_album("fullpeer")]
    await core.hunter.hunt(rid)
    album = (await client.get(f"/api/albums/{rid}")).json()
    by_user = {c["username"]: c["id"] for c in album["candidates"]}
    await client.post(f"/api/candidates/{by_user['partialpeer']}/approve")

    async def two_flacs():
        a = (await client.get(f"/api/albums/{rid}")).json()
        return a["present_tracks"] == 3 and a["status"] in ("imported", "wanted")

    await wait_for(two_flacs)
    async with core.db.session() as s:
        from sqlalchemy import update
        await s.execute(update(LibraryFile).where(LibraryFile.path.like("%In Bloom%")).values(format="mp3-320"))
        await s.commit()

    cov = (await client.get(f"/api/albums/{rid}/coverage")).json()
    bloom = next(t for t in cov["tracks"] if t["title"] == "In Bloom")
    assert bloom["upgrade"] and bloom["library_format"] == "mp3-320"
    up = next(u for u in cov["upgraders"] if u["username"] == "fullpeer")
    assert [t["title"] for t in up["tracks"]] == ["In Bloom"]

    downloads_before = len(engine.downloads)
    r = await client.post(f"/api/albums/{rid}/complete", json={"candidate_id": up["candidate_id"], "track_ids": [bloom["track_id"]]})
    assert r.status_code == 200 and r.json()["files"] == 1
    assert len(engine.downloads) == downloads_before + 1, "only that file is downloaded"

    async def upgraded():
        c = (await client.get(f"/api/albums/{rid}/coverage")).json()
        t = next(x for x in c["tracks"] if x["title"] == "In Bloom")
        return not t["upgrade"] and (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"

    await wait_for(upgraded)
    album_dir = env.music_dir / "Nirvana" / "1991 - Nevermind"
    assert len(list(album_dir.glob("*.flac"))) == 3
