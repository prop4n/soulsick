"""Tests de sécurité : chemins venant du réseau, partages interdits, brute force."""

import os

from test_flow import ctx  # noqa: F401  (fixture)

from soulsick.naming import safe_component
from soulsick.slsk.rules import ShareRules, forbidden_share_reason


def test_safe_component_neutralise_les_traversees():
    for evil in ["..", ".", "../..", "..\\..\\etc", "a/../../b", "/etc/passwd", ""]:
        out = safe_component(evil)
        assert "/" not in out and "\\" not in out
        assert out not in {".", ".."} and not out.startswith("..")


def test_regles_bloquent_les_fichiers_sensibles_meme_autorises():
    rules = ShareRules("/x", allowed_extensions=["db", "flac", "env", "json"])
    assert rules.check("soulsick.db") is not None
    assert rules.check("soulsick.db-wal") is not None
    assert rules.check("a/.env") is not None
    assert rules.check("settings.json") is not None
    assert rules.check("a/b.flac") is None


def test_partage_de_la_racine_ou_de_la_config_refuse(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    assert forbidden_share_reason("/", [str(config)])
    assert forbidden_share_reason(str(tmp_path), [str(config)])  # parent de la config
    assert forbidden_share_reason(str(config), [str(config)])
    assert forbidden_share_reason(str(config / "covers"), [str(config)])
    other = tmp_path / "music"
    other.mkdir()
    assert forbidden_share_reason(str(other), [str(config)]) is None


async def test_pseudo_malveillant_ne_sort_pas_de_downloads(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/downloads", json={
        "username": "../../../tmp/pwn",
        "files": ["@@share\\..\\..\\evil.flac", "@@share\\..\\x.flac"],
    })
    assert r.status_code == 200, r.text
    root = os.path.realpath(env.downloads_dir / "manual")
    for _, _, dest in engine.downloads:
        assert os.path.realpath(dest).startswith(root + os.sep)


async def test_partage_config_refuse_par_api(ctx):  # noqa: F811
    client, core, engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    r = await client.post("/api/shares", json={"path": str(env.config_dir)})
    assert r.status_code == 400
    r = await client.post("/api/shares", json={"path": "/"})
    assert r.status_code == 400


async def test_brute_force_bloque(ctx):  # noqa: F811
    client, *_ = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    codes = [
        (await client.post("/api/auth/login", json={"username": "admin", "password": f"mauvais{i}xx"})).status_code
        for i in range(7)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5:] == [429, 429]
