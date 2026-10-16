"""Suivi en masse : ne pas avoir à décocher les sorties une par une."""

from test_flow import ctx  # noqa: F401


async def _artist(client, types=("album", "single")):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "mode": "validation", "primary_types": list(types), "monitor": "all"})
    return r.json()["id"]


async def _rgs(client, aid):
    return {rg["title"]: rg for rg in (await client.get(f"/api/artists/{aid}")).json()["release_groups"]}


async def test_ne_rien_suivre_puis_tout_suivre(ctx):  # noqa: F811
    client, *_ = ctx
    aid = await _artist(client)
    r = await client.post(f"/api/artists/{aid}/monitor", json={"scope": "none"})
    assert r.status_code == 200 and r.json()["changed"] == 3
    rgs = await _rgs(client, aid)
    assert not any(rg["monitored"] for rg in rgs.values())
    assert rgs["Nevermind"]["status"] == "ignored"

    r = await client.post(f"/api/artists/{aid}/monitor", json={"scope": "all", "section": "single"})
    rgs = await _rgs(client, aid)
    assert rgs["Lithium"]["monitored"] and rgs["Future Single"]["monitored"]
    assert not rgs["Nevermind"]["monitored"]
    events = (await client.get("/api/events", params={"kind": "album.bulk"})).json()
    assert len(events) == 2, "une ligne de journal par action groupée"


async def test_seulement_futures(ctx):  # noqa: F811
    client, *_ = ctx
    aid = await _artist(client)
    await client.post(f"/api/artists/{aid}/monitor", json={"scope": "future"})
    rgs = await _rgs(client, aid)
    assert rgs["Future Single"]["monitored"]
    assert not rgs["Nevermind"]["monitored"] and not rgs["Lithium"]["monitored"]


async def test_retirer_un_type_arrete_de_suivre_l_existant(ctx):  # noqa: F811
    client, *_ = ctx
    aid = await _artist(client)
    assert (await _rgs(client, aid))["Lithium"]["monitored"]
    await client.patch(f"/api/artists/{aid}", json={"primary_types": ["album"], "monitor": "all"})
    rgs = await _rgs(client, aid)
    assert not rgs["Lithium"]["monitored"] and rgs["Lithium"]["status"] == "ignored"
    assert rgs["Nevermind"]["monitored"]


async def test_par_defaut_rien_n_est_suivi(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/artists", json={"mbid": "x", "mode": "auto", "primary_types": ["album", "single"]})
    rgs = await _rgs(client, r.json()["id"])
    assert not any(rg["monitored"] for rg in rgs.values())
    assert all(rg["status"] == "ignored" for rg in rgs.values())
