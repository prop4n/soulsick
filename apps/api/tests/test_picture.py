"""Photo de profil Soulseek : envoyée aux pairs, changée sans reconnexion."""

import base64

from test_flow import ctx  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_photo_de_profil(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    assert (await client.get("/api/profile/picture")).status_code == 404

    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    r = await client.put("/api/profile/picture", json={"data": data_url})
    assert r.status_code == 200, r.text
    assert env.profile_picture_path.read_bytes() == PNG
    assert engine.picture == PNG
    r = await client.get("/api/profile/picture")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"

    # Gardée au redémarrage du moteur
    engine.picture = None
    await core.restart_engine()
    assert engine.picture == PNG

    assert (await client.delete("/api/profile/picture")).status_code == 200
    assert engine.picture is None and not env.profile_picture_path.exists()
    assert (await client.get("/api/profile/picture")).status_code == 404


async def test_photo_refusee(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    bad = base64.b64encode(b"<svg></svg>").decode()
    r = await client.put("/api/profile/picture", json={"data": bad})
    assert r.status_code == 400 and r.json()["detail"]["key"] == "error.picture_invalid"
    assert (await client.put("/api/profile/picture", json={"data": "pas du base64!"})).status_code == 400
    big = base64.b64encode(PNG + b"\x00" * 1_100_000).decode()
    assert (await client.put("/api/profile/picture", json={"data": big})).status_code == 413
    assert not env.profile_picture_path.exists()
