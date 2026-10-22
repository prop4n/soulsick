"""Qobuz comme source : recherche → candidat, téléchargement → import, bascule vers Soulseek."""

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fakes import TRACKS, peer_with_album, tiny_flac
from test_flow import ctx, wait_for  # noqa: F401

from soulsick.services.qobuz import file_sig, parse_bundle

APP_ID = "123456789"
SECRET = "abcdef0123456789abcdef0123456789"
TOKEN = "tok-good"


def _bundle() -> str:
    # Like the real web player: base64(seed + info + extras), the last 44 characters are padding
    full = base64.standard_b64encode(SECRET.encode()).decode() + "A" * 44
    seed, info, extras = full[:10], full[10:30], full[30:]
    wrong = base64.standard_b64encode(b"wrongwrongwrongwrongwrongwrong00").decode() + "B" * 44
    return (
        f'x=production:{{api:{{appId:"{APP_ID}",appSecret:"{"f" * 32}"}}}};'
        f'a.initialSeed("{wrong[:10]}",window.utimezone.london);'
        f'b.initialSeed("{seed}",window.utimezone.berlin);'
        f'{{name:"Europe/Berlin",info:"{info}",extras:"{extras}"}},'
        f'{{name:"Europe/London",info:"{wrong[10:30]}",extras:"{wrong[30:]}"}}'
    )


class FakeQobuz:
    def __init__(self, tmp_path):
        self.albums = {"111": self._album()}
        self.search_ids = ["111"]
        self.sample = False
        self.flac = {}
        for i, (title, length) in enumerate(TRACKS):
            p = tmp_path / f"q{i}.flac"
            tiny_flac(p, length // 1000)
            self.flac[str(1000 + i)] = p.read_bytes()
        self.downloads: list[str] = []

    @staticmethod
    def _album():
        return {
            "id": "111", "title": "Nevermind", "artist": {"name": "Nirvana"}, "streamable": True,
            "maximum_bit_depth": 24, "maximum_sampling_rate": 96, "upc": "0720642442517",
            "tracks": {"items": [
                {"id": 1000 + i, "title": t, "track_number": i + 1, "media_number": 1, "duration": ln // 1000, "streamable": True}
                for i, (t, ln) in enumerate(TRACKS)
            ]},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.netloc == "play.qobuz.com":
            if url.path == "/login":
                return httpx.Response(200, text='<script src="/resources/7.1.2-b012/bundle.js"></script>')
            return httpx.Response(200, text=_bundle())
        if url.netloc == "files.qobuz.test":
            tid = url.path.rsplit("/", 1)[-1]
            self.downloads.append(tid)
            return httpx.Response(200, content=self.flac[tid])
        if request.headers.get("X-App-Id") != APP_ID:
            return httpx.Response(400, json={"message": "bad app id"})
        if request.headers.get("X-User-Auth-Token") != TOKEN:
            return httpx.Response(401, json={"message": "User authentication is required."})
        endpoint = url.path.split("/api.json/0.2/", 1)[-1]
        if endpoint == "user/get":
            return httpx.Response(200, json={"display_name": "enzo", "credential": {"parameters": {"short_label": "Studio", "hires_streaming": True}}})
        if endpoint == "album/search":
            return httpx.Response(200, json={"albums": {"items": [{"id": i, "streamable": True} for i in self.search_ids]}})
        if endpoint == "album/get":
            return httpx.Response(200, json=self.albums[q["album_id"]])
        if endpoint == "track/getFileUrl":
            if q["request_sig"] != file_sig(q["track_id"], int(q["format_id"]), q["request_ts"], SECRET):
                return httpx.Response(400, json={"message": "Invalid Request Signature parameter (request_sig)"})
            if self.sample and q["track_id"] != "5966783":
                return httpx.Response(200, json={"sample": True, "url": "https://files.qobuz.test/sample"})
            return httpx.Response(200, json={"url": f"https://files.qobuz.test/{q['track_id']}", "mime_type": "audio/flac"})
        return httpx.Response(404)


@pytest.fixture
def qobuz(ctx, tmp_path):  # noqa: F811
    client, core, engine, env = ctx
    fake = FakeQobuz(tmp_path)
    core.qobuz.transport = httpx.MockTransport(fake.handler)
    return fake


async def _setup(client, source, mode="auto", token=TOKEN):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    cfg = (await client.get("/api/settings")).json()
    cfg["hunter"]["source"] = source
    cfg["qobuz"]["token"] = token
    assert (await client.put("/api/settings", json=cfg)).status_code == 200
    r = await client.post("/api/artists", json={"mbid": "x", "mode": mode, "primary_types": ["album"], "monitor": "all"})
    return next(rg["id"] for rg in (await client.get(f"/api/artists/{r.json()['id']}")).json()["release_groups"]
                if rg["title"] == "Nevermind")


async def _imported(client, rid):
    async def done():
        return (await client.get(f"/api/albums/{rid}")).json()["status"] == "imported"
    await wait_for(done)


def test_parse_bundle_trouve_app_id_et_secret():
    app_id, secrets = parse_bundle(_bundle())
    assert app_id == APP_ID and SECRET in secrets


async def test_qobuz_seulement_cherche_telecharge_et_range(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _setup(client, "qobuz")
    await core.hunter.hunt(rid)
    await _imported(client, rid)

    album = (await client.get(f"/api/albums/{rid}")).json()
    cand = next(c for c in album["candidates"] if c["status"] == "imported")
    assert cand["username"] == "Qobuz" and cand["directory"] == "qobuz:album-111" and cand["format"] == "flac-24"
    assert engine.downloads == [], "rien demandé sur Soulseek"
    assert sorted(qobuz.downloads) == ["1000", "1001", "1002"]
    assert (env.music_dir / "Nirvana" / "1991 - Nevermind" / "02 - In Bloom.flac").exists()
    t = album["transfers"][0]
    assert t["username"] == "Qobuz" and t["state"] == "complete"


async def test_qobuz_d_abord_passe_a_soulseek_si_rien_sur_qobuz(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    qobuz.search_ids = []
    rid = await _setup(client, "qobuz_first")
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)
    await _imported(client, rid)
    assert engine.downloads, "téléchargé sur Soulseek"
    assert qobuz.downloads == []


async def test_qobuz_d_abord_saute_soulseek_quand_qobuz_a_l_album(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    rid = await _setup(client, "qobuz_first")
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)
    await _imported(client, rid)
    assert engine.downloads == [] and len(qobuz.downloads) == 3


async def test_qobuz_echoue_puis_soulseek_prend_le_relais(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    qobuz.sample = True  # l'abonnement ne couvre que des extraits
    core.hunter.retry_delays = [0.01, 0.01]
    rid = await _setup(client, "qobuz_first")
    engine.results = [peer_with_album()]
    await core.hunter.hunt(rid)
    await _imported(client, rid)
    events = [e["kind"] for e in (await client.get("/api/events", params={"release_group_id": rid})).json()]
    assert "hunt.qobuz_fallback" in events
    assert engine.downloads


async def test_tester_la_connexion(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    await _setup(client, "qobuz")
    r = (await client.post("/api/settings/qobuz/test")).json()
    assert r["ok"] and r["subscription"] == "Studio" and r["app_id"] == APP_ID

    cfg = (await client.get("/api/settings")).json()
    assert cfg["qobuz"]["token"] == "••••••••", "jeton masqué"
    cfg["qobuz"]["token"] = "tok-revoked"
    await client.put("/api/settings", json=cfg)
    r = (await client.post("/api/settings/qobuz/test")).json()
    assert not r["ok"] and r["error_t"]["key"] == "qobuz.error.token"


async def test_jeton_masque_reste_en_place(ctx, qobuz):  # noqa: F811
    client, core, engine, env = ctx
    await _setup(client, "qobuz")
    cfg = (await client.get("/api/settings")).json()
    cfg["qobuz"]["quality"] = 6
    await client.put("/api/settings", json=cfg)
    assert (await core.settings.get()).qobuz.token == TOKEN
    assert json.dumps(cfg).count(TOKEN) == 0
