"""Server messages: English rendering, plurals, nesting, translatable API errors."""

from soulsick.messages import EN, M, render
from test_flow import ctx  # noqa: F401


def test_render_plural_and_nested():
    assert render("reason.no_valid", {"n": 1}) == "No valid candidate among 1 folder"
    assert render("reason.no_valid", {"n": 3}) == "No valid candidate among 3 folders"
    m = M("download.failed", label="A – B", reason=M("reason.stalled", minutes=30))
    assert m.text == "A – B: candidate dropped — no transfer started within 30 minutes (peer away or queue full)"
    assert m.to_json()["params"]["reason"] == {"key": "reason.stalled", "params": {"minutes": 30}}


def test_fragment_lists_concatenate():
    m = M("import.done", artist="A", title="B", n=2, dir="/m", details=[M("import.detail.tags"), M("import.detail.by_you")])
    assert m.text == "A – B imported: 2 files shelved in /m (MusicBrainz tags written); confirmed by you"


def test_every_template_renders():
    for key, tpl in EN.items():
        render(key, {"n": 2})  # no KeyError / format error
        assert tpl.count(" | ") <= 1, key


async def test_api_errors_are_translatable(ctx):  # noqa: F811
    client, *_ = ctx
    r = await client.get("/api/status")
    assert r.status_code == 401
    assert r.json()["detail"] == {"message": "Sign-in required", "key": "error.auth_required", "params": {}}


async def test_legacy_french_reasons_are_converted(ctx):  # noqa: F811
    from soulsick.legacy import convert_legacy_reasons
    from soulsick.models import Artist, ReleaseGroup

    _client, core, *_ = ctx
    async with core.db.session() as s:
        a = Artist(mbid="a-legacy", name="A")
        s.add(a)
        await s.flush()
        rg = ReleaseGroup(mbid="rg-legacy", title="T", artist_id=a.id, status_reason="5 proposition(s) en attente de validation")
        odd = ReleaseGroup(mbid="rg-odd", title="U", artist_id=a.id, status_reason="Une phrase inconnue")
        s.add_all([rg, odd])
        await s.commit()
        rid, oid = rg.id, odd.id
    assert await convert_legacy_reasons(core.db) == 1
    async with core.db.session() as s:
        rg, odd = await s.get(ReleaseGroup, rid), await s.get(ReleaseGroup, oid)
        assert rg.status_reason == "5 proposals awaiting approval"
        assert rg.status_reason_t == {"key": "reason.awaiting", "params": {"n": 5}}
        assert odd.status_reason == "Une phrase inconnue" and odd.status_reason_t is None


async def test_storage_reports_disks(ctx):  # noqa: F811
    client, core, _engine, env = ctx
    await client.post("/api/auth/setup", json={"username": "admin", "password": "motdepasse"})
    (env.downloads_dir / "x.bin").write_bytes(b"0" * 1000)
    data = (await client.get("/api/storage?refresh=true")).json()
    folders = {f["key"]: f for d in data["disks"] for f in d["folders"]}
    assert set(folders) >= {"music", "downloads", "config"}
    assert folders["downloads"]["size"] >= 1000
    disk = data["disks"][0]
    assert disk["total"] > 0 and disk["free"] >= 0 and disk["level"] in {"ok", "low", "critical"}
    assert (await client.get("/api/status")).json()["storage"] in {"ok", "low", "critical"}


def test_storage_levels():
    from soulsick.services.storage import level

    gb = 1024**3
    assert level(1000 * gb, 500 * gb) == "ok"
    assert level(1000 * gb, 4 * gb) == "low"
    assert level(1000 * gb, gb // 2) == "critical"
