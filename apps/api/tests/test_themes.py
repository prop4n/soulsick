from test_flow import ctx  # noqa: F401

THEME = {
    "id": "mon-theme", "name": "Mon thème", "base": {"hue": 200, "chroma": 0.01},
    "accent": {"dark": "oklch(0.8 0.1 200)", "light": "#225588"}, "coverAccent": False,
}


async def test_themes_enregistres_et_valides(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    assert (await client.get("/api/themes")).json() == []
    r = await client.put("/api/themes", json=[THEME])
    assert r.status_code == 200
    assert (await client.get("/api/themes")).json() == [THEME]
    # Injection CSS refusée
    evil = {**THEME, "accent": {"dark": "red;} body{display:none"}}
    assert (await client.put("/api/themes", json=[evil])).status_code == 400
    # Identifiants en double refusés
    assert (await client.put("/api/themes", json=[THEME, THEME])).status_code == 400
    assert (await client.get("/api/themes")).json() == [THEME]
