"""Console : les logs techniques sont consultables et classés par source."""

import logging

from test_flow import ctx  # noqa: F401


async def test_logs_classes_par_source(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    logging.getLogger("aioslsk.network.network").warning("failed to fulfill ConnectToPeer request : test")
    logging.getLogger("soulsick.search").info("« test » +1.2s : bob répond — 3 fichier(s)")
    data = (await client.get("/api/logs")).json()
    by_msg = {r["message"]: r for r in data["logs"]}
    assert by_msg["failed to fulfill ConnectToPeer request : test"]["source"] == "soulseek"
    assert by_msg["failed to fulfill ConnectToPeer request : test"]["level"] == "warning"
    assert by_msg["« test » +1.2s : bob répond — 3 fichier(s)"]["source"] == "search"
    last = data["logs"][-1]["id"]
    newer = (await client.get("/api/logs", params={"after": last})).json()["logs"]
    assert all(r["id"] > last for r in newer), "seulement les lignes plus récentes"
    act = (await client.get("/api/activity")).json()
    assert "searches" in act and "hunter" in act
