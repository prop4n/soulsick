"""Sorties partagées entre artistes (featurings, splits) : une sortie, plusieurs artistes."""

from test_flow import ctx  # noqa: F401


async def _add(client, mbid, monitor="none"):
    r = await client.post("/api/artists", json={"mbid": mbid, "mode": "validation", "primary_types": ["album", "single"], "monitor": monitor})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_deux_artistes_partagent_une_sortie(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    a = await _add(client, "artist-a", monitor="all")
    b = await _add(client, "artist-b")  # même discographie dans le faux MusicBrainz → toutes partagées

    rgs_a = {rg["title"]: rg for rg in (await client.get(f"/api/artists/{a}")).json()["release_groups"]}
    rgs_b = {rg["title"]: rg for rg in (await client.get(f"/api/artists/{b}")).json()["release_groups"]}
    assert rgs_a["Nevermind"]["id"] == rgs_b["Nevermind"]["id"], "une seule entrée partagée"
    # Ajouter B (rien suivi) ne touche pas au suivi décidé pour A
    assert rgs_b["Nevermind"]["monitored"] is True

    # Ne plus suivre B : les sorties restent, rattachées à A
    await client.delete(f"/api/artists/{b}")
    rgs_a = {rg["title"]: rg for rg in (await client.get(f"/api/artists/{a}")).json()["release_groups"]}
    assert "Nevermind" in rgs_a

    # Et dans l'autre sens : supprimer A garde les sorties de B si B existe
    b = await _add(client, "artist-b")
    await client.delete(f"/api/artists/{a}")
    rgs_b = {rg["title"]: rg for rg in (await client.get(f"/api/artists/{b}")).json()["release_groups"]}
    assert "Nevermind" in rgs_b
