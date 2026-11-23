"""Discover: artists to follow, from the similar artists of those followed (ListenBrainz).

ListenBrainz (MetaBrainz, like MusicBrainz) answers from MusicBrainz ids, which every followed
artist already has: no name matching. Its similar artists are kept in the database and asked
again once a week; recommendations are computed from them, never from the network.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import delete, func, or_, select

from ..messages import M
from ..models import AlbumStatus, Artist, DiscoverProfile, DismissedArtist, ReleaseGroup, SimilarArtist
from ..musicbrainz import USER_AGENT, MusicBrainzError

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

URL = "https://labs.api.listenbrainz.org/similar-artists/json"
# Listening sessions over ~20 years: the broadest of the published algorithms
ALGORITHM = "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
KEEP = 30  # similar artists kept per followed artist
REFRESH = timedelta(days=7)
# Artist photos: MusicBrainz has none, Deezer has nearly every artist (no API key)
DEEZER_SEARCH = "https://api.deezer.com/search/artist"
NO_PHOTO_RETRY = 86400 * 7
# What MusicBrainz says of an artist to discover (see MusicBrainz.artist_profile), kept a week.
# ListenBrainz's popularity API would add listeners, but answers 401 without a token for most
# artists (seen in November 2026)
PROFILE_REFRESH = timedelta(days=7)
# A 30-second extract of its best-known track (Deezer, no key)
DEEZER_TOP = "https://api.deezer.com/artist/{id}/top"
DEEZER_TRACK = "https://api.deezer.com/track/{id}"
_DEEZER_ARTIST = re.compile(r"deezer\.com/(?:[a-z]{2}/)?artist/(\d+)")
# Discover is a deck: a few artists, from one angle, a different one each visit
DECK = 12
ANGLES = ("crossing", "wake", "further", "library")
STATE = "discover"
# Passed on a card: proposed again after this long (not interested: never again)
SNOOZE_DAYS = 30


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _sample(rng: random.Random, items: list[str], weights: dict[str, float], k: int) -> list[str]:
    """k items drawn without replacement, each as likely as its weight: the deck changes every
    visit, and the strongest still come up more often."""
    return sorted(items, key=lambda m: -(rng.random() ** (1 / max(weights.get(m, 0.0), 1e-6))))[:k]


def _same_name(a: str, b: str) -> bool:
    """Deezer is searched by name: accents, case and punctuation aside, the names must be equal."""
    def norm(v: str) -> str:
        v = unicodedata.normalize("NFKD", v.casefold())
        return re.sub(r"[\W_]+", "", "".join(c for c in v if not unicodedata.combining(c)))
    return norm(a) == norm(b)


class DiscoverService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self.client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30)
        self._photos = asyncio.Semaphore(8)  # Deezer allows 50 requests every 5 s
        self._prefetch: set[asyncio.Task] = set()
        self._photo_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._profile_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._wake = asyncio.Event()

    async def fetch(self, artist_id: int) -> bool:
        """Asks ListenBrainz for the similar artists of `artist_id`; False if it failed
        (the artist is then asked again on the next pass)."""
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return False
            mbid = artist.mbid
        try:
            r = await self.client.get(URL, params={"artist_mbids": mbid, "algorithm": ALGORITHM})
            r.raise_for_status()
            rows = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.info("ListenBrainz, similar artists of %s: %s", mbid, e)
            return False
        rows = [x for x in rows if isinstance(x, dict) and x.get("artist_mbid") not in (None, "", mbid)]
        rows.sort(key=lambda x: -(x.get("score") or 0))
        # The same artist sometimes comes twice: its best score only
        seen: set[str] = set()
        rows = [x for x in rows if not (x["artist_mbid"] in seen or seen.add(x["artist_mbid"]))]
        async with self.core.db.session() as s:
            await s.execute(delete(SimilarArtist).where(SimilarArtist.artist_id == artist_id))
            for x in rows[:KEEP]:
                s.add(SimilarArtist(
                    artist_id=artist_id, mbid=x["artist_mbid"], name=x.get("name") or "?",
                    comment=x.get("comment") or "", type=x.get("type"), score=int(x.get("score") or 0),
                ))
            artist = await s.get(Artist, artist_id)
            if artist:
                artist.similar_fetched_at = datetime.now(UTC)
            await s.commit()
        # Their photos, before the page asks for them (a page is ~60 cards)
        task = asyncio.create_task(self._prefetch_photos([x["artist_mbid"] for x in rows[:KEEP]]))
        self._prefetch.add(task)
        task.add_done_callback(self._prefetch.discard)
        return True

    async def _prefetch_photos(self, mbids: list[str]) -> None:
        await asyncio.gather(*(self.photo(m) for m in mbids), return_exceptions=True)

    async def refresh_stale(self, limit: int = 10) -> int:
        """Fetches the artists never asked, or asked more than a week ago; returns how many."""
        cutoff = datetime.now(UTC) - REFRESH
        async with self.core.db.session() as s:
            ids = list((await s.execute(
                select(Artist.id)
                .where(or_(Artist.similar_fetched_at.is_(None), Artist.similar_fetched_at < cutoff))
                .order_by(Artist.similar_fetched_at.is_not(None), Artist.similar_fetched_at)
                .limit(limit)
            )).scalars())
        done = 0
        for i, aid in enumerate(ids):
            if i:
                await asyncio.sleep(1)  # politeness towards a free service
            done += await self.fetch(aid)
        return done

    async def refresh_all(self) -> int:
        async with self.core.db.session() as s:
            ids = list((await s.execute(select(Artist.id))).scalars())
        return sum([await self.fetch(aid) for aid in ids])

    def soon(self) -> None:
        """An artist was just followed: its similar artists are asked now, not at the next pass."""
        self._wake.set()

    async def _pause(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def loop(self) -> None:
        await self._pause(120)
        while True:
            try:
                while await self.refresh_stale():  # 10 at a time: a bulk add can bring more
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("discover")
            await self._pause(1800)

    async def dismiss(self, mbid: str, days: int | None = None) -> None:
        """Not interested: never proposed again. `days`: passed for now, back after that long."""
        until = datetime.now(UTC) + timedelta(days=days) if days else None
        async with self.core.db.session() as s:
            row = await s.get(DismissedArtist, mbid)
            if row is None:
                s.add(DismissedArtist(mbid=mbid, until=until))
            elif row.until is not None:  # "never again" stays never again
                row.until, row.dismissed_at = until, datetime.now(UTC)
            await s.commit()

    async def _hidden(self, s) -> set[str]:
        """Set aside: for good, or passed and not back yet."""
        now = datetime.now(UTC)
        return {
            mbid for mbid, until in await s.execute(select(DismissedArtist.mbid, DismissedArtist.until))
            if until is None or _aware(until) > now
        }

    @staticmethod
    def _weigh(similar: list[SimilarArtist], excluded: set[str]):
        """Each artist of yours gives its similar ones a weight from 0 to 1 (relative to its best
        match), summed over all of them: an artist several of yours lead to comes first."""
        best: dict[int, int] = defaultdict(int)
        for x in similar:
            best[x.artist_id] = max(best[x.artist_id], x.score)
        weight: dict[str, float] = defaultdict(float)
        because: dict[str, list[tuple[float, int]]] = defaultdict(list)
        info: dict[str, SimilarArtist] = {}
        for x in similar:
            if x.mbid in excluded or not best[x.artist_id]:
                continue
            w = x.score / best[x.artist_id]
            weight[x.mbid] += w
            because[x.mbid].append((w, x.artist_id))
            info.setdefault(x.mbid, x)
        return weight, because, info

    async def recommendations(self, limit: int = 60) -> dict:
        """Artists similar to several of yours come first (see _weigh)."""
        async with self.core.db.session() as s:
            artists = {a.id: a for a in (await s.execute(select(Artist))).scalars()}
            similar = list((await s.execute(select(SimilarArtist))).scalars())
            dismissed = await self._hidden(s)
        followed = {a.mbid for a in artists.values()}
        weight, because, info = self._weigh(similar, followed | dismissed)
        ranked = sorted(weight, key=lambda m: (-weight[m], info[m].name.lower()))[:limit]
        top = weight[ranked[0]] if ranked else 1
        return {
            "recommendations": [
                {
                    "mbid": m,
                    "name": info[m].name,
                    "comment": info[m].comment,
                    "type": info[m].type,
                    "score": max(1, round(100 * weight[m] / top)),
                    "because": [
                        {"id": aid, "name": artists[aid].name}
                        for _, aid in sorted(because[m], key=lambda b: -b[0])
                    ],
                }
                for m in ranked
            ],
            "pending": sum(1 for a in artists.values() if a.similar_fetched_at is None),
            "followed": len(artists),
        }

    async def similar(self, artist_id: int) -> list[dict]:
        async with self.core.db.session() as s:
            rows = list((await s.execute(
                select(SimilarArtist)
                .where(SimilarArtist.artist_id == artist_id)
                .order_by(SimilarArtist.score.desc())
            )).scalars())
            rows_known = await s.execute(select(Artist.mbid, Artist.id, Artist.monitored))
            known = {mbid: (aid, f) for mbid, aid, f in rows_known}
        return [
            {
                "mbid": x.mbid, "name": x.name, "comment": x.comment, "type": x.type,
                # In the catalog (its page exists), and whether you follow it
                "followed_id": known[x.mbid][0] if x.mbid in known else None,
                "followed": known.get(x.mbid, (None, False))[1],
            }
            for x in rows
        ]

    async def photo(self, mbid: str) -> Path | None:
        """Photo of an artist (followed or recommended), from Deezer, kept on disk.

        Deezer is searched by name: among the artists with exactly that name, the one with
        the most fans (homonyms with a handful of fans are common). None if there is no photo.
        """
        async with self._photo_locks[mbid]:  # the page and the prefetch can ask at the same time
            return await self._photo(mbid)

    async def _photo(self, mbid: str) -> Path | None:
        covers = self.core.mb.covers_dir
        path, missing = covers / f"artist-{mbid}.jpg", covers / f"artist-{mbid}.missing"
        if path.exists():
            return path
        if missing.exists() and time.time() - missing.stat().st_mtime < NO_PHOTO_RETRY:
            return None
        async with self.core.db.session() as s:
            name = (await s.execute(select(Artist.name).where(Artist.mbid == mbid))).scalar() or (
                await s.execute(select(SimilarArtist.name).where(SimilarArtist.mbid == mbid).limit(1))
            ).scalar()
        if not name:
            return None
        async with self._photos:
            try:
                r = await self.client.get(DEEZER_SEARCH, params={"q": name, "limit": 25})
                r.raise_for_status()
                found = [
                    a for a in r.json().get("data", [])
                    if _same_name(a.get("name", ""), name)
                    and a.get("picture_big") and "/artist//" not in a["picture_big"]  # Deezer's placeholder
                ]
                if not found:
                    missing.touch()
                    return None
                best = max(found, key=lambda a: a.get("nb_fan", 0))
                img = await self.client.get(best["picture_big"])
                img.raise_for_status()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("artist photo %s: %s", name, e)
                return None  # network trouble: asked again next time
        covers.mkdir(parents=True, exist_ok=True)
        path.write_bytes(img.content)
        missing.unlink(missing_ok=True)
        return path

    # --- The deck: a few artists from one angle, a different one each visit ----------

    async def profile(self, mbid: str) -> dict | None:
        """Origin, genres, best-known albums and a track to listen to, kept a week.
        None when MusicBrainz couldn't be asked (and nothing was known before)."""
        async with self._profile_locks[mbid]:
            async with self.core.db.session() as s:
                row = await s.get(DiscoverProfile, mbid)
                if row and datetime.now(UTC) - _aware(row.fetched_at) < PROFILE_REFRESH:
                    return row.data
                known = row.data if row else None
            data = await self._fetch_profile(mbid)
            if data is None:
                return known
            async with self.core.db.session() as s:
                row = await s.get(DiscoverProfile, mbid)
                if row:
                    row.data, row.fetched_at = data, datetime.now(UTC)
                else:
                    s.add(DiscoverProfile(mbid=mbid, data=data))
                await s.commit()
            return data

    async def with_states(self, profiles: list[dict | None]) -> list[dict | None]:
        """Each best-known album says where it stands for you now: on your disk ("imported"),
        asked for ("wanted"), or nothing (null). Not kept: it changes as you go."""
        mbids = {r["mbid"] for p in profiles if p for r in p.get("releases", [])}
        async with self.core.db.session() as s:
            rows = (await s.execute(
                select(ReleaseGroup.mbid, ReleaseGroup.status, ReleaseGroup.monitored)
                .where(ReleaseGroup.mbid.in_(mbids))
            )).all() if mbids else []
        state = {
            mbid: "imported" if status == AlbumStatus.IMPORTED else "wanted" if monitored else None
            for mbid, status, monitored in rows
        }
        return [
            {**p, "releases": [{**r, "state": state.get(r["mbid"])} for r in p.get("releases", [])]}
            if p else p
            for p in profiles
        ]

    async def _fetch_profile(self, mbid: str) -> dict | None:
        try:
            profile = await self.core.mb.artist_profile(mbid)
        except MusicBrainzError as e:
            log.info("MusicBrainz, profile of %s: %s", mbid, e)
            return None
        link = _DEEZER_ARTIST.search(profile.pop("deezer_url", None) or "")
        deezer_id = int(link[1]) if link else None
        return {**profile, "deezer_id": deezer_id, "track": await self._top_track(deezer_id, mbid)}

    async def _top_track(self, deezer_id: int | None, mbid: str) -> dict | None:
        """Its best-known track on Deezer: found by its exact id when MusicBrainz links it,
        otherwise by name (the artist with that exact name and the most fans)."""
        async with self._photos:
            try:
                if deezer_id is None:
                    async with self.core.db.session() as s:
                        name = (await s.execute(
                            select(SimilarArtist.name).where(SimilarArtist.mbid == mbid).limit(1)
                        )).scalar()
                        followed = select(Artist.name).where(Artist.mbid == mbid)
                        name = name or (await s.execute(followed)).scalar()
                    if not name:
                        return None
                    r = await self.client.get(DEEZER_SEARCH, params={"q": name, "limit": 25})
                    data = r.raise_for_status().json().get("data", [])
                    found = [a for a in data if _same_name(a.get("name", ""), name)]
                    if not found:
                        return None
                    deezer_id = max(found, key=lambda a: a.get("nb_fan", 0))["id"]
                r = await self.client.get(DEEZER_TOP.format(id=deezer_id), params={"limit": 1})
                top = r.raise_for_status().json().get("data") or []
            except (httpx.HTTPError, ValueError, KeyError) as e:
                log.info("Deezer, top track of %s: %s", mbid, e)
                return None
        if not top or not top[0].get("preview"):
            return None
        return {"title": top[0].get("title") or "?", "deezer_id": top[0]["id"]}

    async def preview(self, mbid: str) -> bytes | None:
        """The 30-second extract, asked now (Deezer's links expire): the browser only talks to soulsick."""
        track = ((await self.profile(mbid)) or {}).get("track")
        if not track:
            return None
        async with self._photos:
            try:
                r = await self.client.get(DEEZER_TRACK.format(id=track["deezer_id"]))
                url = r.raise_for_status().json().get("preview")
                if not url:
                    return None
                audio = await self.client.get(url)
                return audio.raise_for_status().content
            except (httpx.HTTPError, ValueError) as e:
                log.info("Deezer, extract of %s: %s", mbid, e)
                return None

    async def deck(self, avoid: str | None = None, rng: random.Random | None = None) -> dict:
        """A few artists from one angle, never the angle of the last visit (or `avoid`)."""
        rng = rng or random.Random()
        async with self.core.db.session() as s:
            artists = {a.id: a for a in (await s.execute(select(Artist))).scalars()}
            similar = list((await s.execute(select(SimilarArtist))).scalars())
            hidden = await self._hidden(s)
            shelved = dict((await s.execute(
                select(ReleaseGroup.artist_id, func.count())
                .where(ReleaseGroup.status == AlbumStatus.IMPORTED)
                .group_by(ReleaseGroup.artist_id)
            )).all())
        catalog = {a.mbid for a in artists.values()}
        weight, because, info = self._weigh(similar, catalog | hidden)
        top = max(weight.values(), default=1) or 1

        def recommended(m: str) -> dict:
            return {
                "mbid": m, "name": info[m].name, "comment": info[m].comment, "type": info[m].type,
                "score": max(1, round(100 * weight[m] / top)),
                "because": [
                    {"id": aid, "name": artists[aid].name}
                    for _, aid in sorted(because[m], key=lambda b: -b[0])
                ],
                "artist_id": None, "shelved": 0,
            }

        def crossing():
            picks = _sample(rng, [m for m in weight if len(because[m]) >= 2], weight, DECK)
            leads = Counter(b["id"] for m in picks for b in recommended(m)["because"][:2]).most_common(2)
            return {"artists": [{"id": aid, "name": artists[aid].name} for aid, _ in leads]}, \
                [recommended(m) for m in picks]

        def wake():
            # One of yours, among the last followed: what sounds like it
            recent = sorted(
                (a for a in artists.values() if a.monitored),
                key=lambda a: _aware(a.followed_at or a.added_at), reverse=True,
            )[:8]
            leads = Counter(aid for links in because.values() for _, aid in links)
            fits = [a for a in recent if leads[a.id] >= 3]
            if not fits:
                return None
            seed = rng.choice(fits)
            own = {x.mbid: x.score for x in similar if x.artist_id == seed.id and x.mbid in weight}
            picks = sorted(own, key=lambda m: -own[m])[:DECK]
            return {"artist": {"id": seed.id, "name": seed.name}}, [recommended(m) for m in picks]

        def further():
            alone = [m for m in weight if len(because[m]) == 1]
            return {}, [recommended(m) for m in rng.sample(alone, min(DECK, len(alone)))]

        def library():
            # Their albums are on your disk, you don't follow them
            known = {
                a.mbid: a for a in artists.values()
                if not a.monitored and shelved.get(a.id) and a.mbid not in hidden
            }
            picks = _sample(rng, list(known), {m: float(shelved[known[m].id]) for m in known}, DECK)
            return {}, [
                {"mbid": m, "name": known[m].name, "comment": known[m].disambiguation, "type": known[m].type,
                 "score": None, "because": [], "artist_id": known[m].id, "shelved": shelved[known[m].id]}
                for m in picks
            ]

        builders = {"crossing": crossing, "wake": wake, "further": further, "library": library}
        options = []
        for kind in ANGLES:
            built = builders[kind]()
            if built and len(built[1]) >= 3:
                options.append((kind, built))
        last = avoid or (await self.core.settings.get_raw(STATE) or {}).get("last")
        meta = {
            "pending": sum(1 for a in artists.values() if a.similar_fetched_at is None),
            "followed": sum(1 for a in artists.values() if a.monitored),
        }
        if not options:
            return {"angle": None, "cards": [], **meta}
        kind, (params, cards) = rng.choice([o for o in options if o[0] != last] or options)
        await self.core.settings.set_raw(STATE, {"last": kind})
        # Profiles already known come with the cards; the others are asked in the background, in
        # the order of the deck (MusicBrainz: one request a second), and by the page as it goes
        async with self.core.db.session() as s:
            known = {
                p.mbid: p.data for p in (await s.execute(
                    select(DiscoverProfile).where(DiscoverProfile.mbid.in_([c["mbid"] for c in cards]))
                )).scalars()
            }
        for c, p in zip(cards, await self.with_states([known.get(c["mbid"]) for c in cards]), strict=True):
            c["profile"] = p
        missing = [c["mbid"] for c in cards if c["profile"] is None]
        task = asyncio.create_task(self._prefetch_profiles(missing))
        self._prefetch.add(task)
        task.add_done_callback(self._prefetch.discard)
        return {"angle": {"kind": kind, **params}, "cards": cards, **meta}

    async def _prefetch_profiles(self, mbids: list[str]) -> None:
        for mbid in mbids:
            try:
                await self.profile(mbid)
            except Exception:  # one that fails doesn't stop the others
                log.exception("profile of %s", mbid)

    async def want(self, artist_mbid: str, release_group_mbid: str) -> None:
        """An album seen in Discover, asked for: its artist enters the catalog without being
        followed, the album is wanted and hunted at once."""
        try:
            artist = await self.core.catalog.ensure_artist(artist_mbid, follow=False)
            rg = await self.core.catalog.ensure_album(release_group_mbid, artist.id)
        except Exception as e:  # MusicBrainz unreachable: said in the journal
            await self.core.journal.emit(
                "discover.want_failed", M("discover.want_failed", error=str(e)), level="error",
            )
            return
        await self.core.catalog.set_album_monitored(rg.id, True)
        await self.core.hunter.hunt(rg.id, trigger="manual")
