"""Catalogue : artistes suivis et discographie issue de MusicBrainz."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..messages import M, set_reason
from ..models import (
    AlbumStatus, Artist, ArtistReleaseGroup, LibraryFile, QualityProfile, Release, ReleaseGroup, Track, of_artist,
)
from ..musicbrainz import pick_default_release

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

# CD quality first: a 24-bit album often weighs over 1 GB for the same music, it only comes
# when nothing else is there
CD_QUALITY = ("CD quality", ["flac", "alac", "wav", "flac-24"], "flac")
DEFAULT_PROFILES = [
    CD_QUALITY,
    ("Hi-res", ["flac-24", "flac", "alac", "wav"], "flac"),
    ("MP3 320", ["mp3-320", "mp3-v0"], "mp3-320"),
]


def wants(artist: Artist, primary: str | None, secondary: list[str]) -> bool:
    """Le type de sortie fait-il partie de ce que l'artiste suit ?"""
    if (primary or "other") not in artist.primary_types:
        return False
    return all(s in artist.secondary_types for s in secondary)


# Étapes en cours ou terminées : on change le drapeau de suivi, jamais le statut
_KEEP_STATUS = {
    AlbumStatus.SEARCHING,
    AlbumStatus.DOWNLOADING,
    AlbumStatus.IMPORTING,
    AlbumStatus.NEEDS_REVIEW,
    AlbumStatus.IMPORTED,
}


def section_of(rg: ReleaseGroup) -> str:
    """Même regroupement que l'interface : premier type secondaire, sinon le type primaire."""
    return (rg.secondary_types or [None])[0] or rg.primary_type or "other"


def _set_monitored(rg: ReleaseGroup, monitored: bool) -> bool:
    if rg.monitored == monitored:
        return False
    rg.monitored = monitored
    if rg.status not in _KEEP_STATUS:
        rg.status = AlbumStatus.WANTED if monitored else AlbumStatus.IGNORED
        set_reason(rg, "status_reason", None)
    return True


class CatalogService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._from_library = asyncio.Lock()

    async def ensure_default_profiles(self) -> None:
        async with self.core.db.session() as s:
            if (await s.execute(select(QualityProfile.id).limit(1))).first():
                return
            for name, formats, until in DEFAULT_PROFILES:
                s.add(QualityProfile(name=name, formats=formats, upgrade_until=until, max_missing_tracks=0))
            await s.commit()

    async def quality_profile(self, s: AsyncSession) -> QualityProfile | None:
        """The profile every album is hunted, checked and imported with: the one chosen in the
        settings, otherwise the first one."""
        pid = (await self.core.settings.get()).hunter.profile_id
        profile = await s.get(QualityProfile, pid) if pid else None
        first = select(QualityProfile).order_by(QualityProfile.id).limit(1)
        return profile or (await s.execute(first)).scalars().first()

    async def add_artist(
        self,
        mbid: str,
        *,
        primary_types: list[str],
        secondary_types: list[str],
        follow: bool = True,
        monitor: str = "none",  # none | all : "all" veut aussi toute la discographie existante
    ) -> Artist:
        """Suivre = ses sorties à venir sont voulues. Le passé ne l'est que si tu le demandes."""
        a, created = await self._create_artist(
            mbid, primary_types=primary_types, secondary_types=secondary_types, monitored=follow,
        )
        if created:
            initial = "all" if monitor == "all" else "future" if follow else "none"
            await self.sync_artist(a.id, initial_monitor=initial)
        return a

    async def _create_artist(
        self, mbid: str, *, primary_types: list[str], secondary_types: list[str],
        monitored: bool = True, announce: bool = True,
    ) -> tuple[Artist, bool]:
        """Fiche de l'artiste seule (une requête MusicBrainz), sans sa discographie."""
        info = await self.core.mb.get_artist(mbid)
        async with self.core.db.session() as s:
            existing = (await s.execute(select(Artist).where(Artist.mbid == mbid))).scalar_one_or_none()
            if existing:
                return existing, False
            a = Artist(
                mbid=mbid,
                name=info["name"],
                sort_name=info["sort_name"],
                disambiguation=info["disambiguation"],
                country=info["country"],
                type=info["type"],
                primary_types=primary_types,
                secondary_types=secondary_types,
                monitored=monitored,
                followed_at=datetime.now(UTC) if monitored else None,
            )
            s.add(a)
            await s.commit()
            await s.refresh(a)
        if not announce:
            self.core.discover.soon()
            return a, True
        await self.core.journal.emit(
            "artist.added",
            M("artist.added", name=a.name),
            artist_id=a.id,
            data={"mbid": mbid, "primary_types": primary_types, "secondary_types": secondary_types},
        )
        self.core.discover.soon()
        return a, True

    async def add_artists(
        self, mbids: list[str], *, follow: bool = True, monitor: str = "none", **settings,
    ) -> int:
        """Follows several artists with the same settings (MusicBrainz allows one request per
        second). Every artist is created first, a second each, so they all show up quickly;
        the discographies, several requests each, come after. One that fails doesn't stop the others."""
        created: list[int] = []
        for mbid in mbids:
            try:
                a, new = await self._create_artist(mbid, monitored=follow, **settings)
            except Exception as e:
                await self.core.journal.emit(
                    "musicbrainz.sync_failed", M("musicbrainz.sync_failed", name=mbid, error=str(e)),
                    level="error",
                )
                continue
            if new:
                created.append(a.id)
        initial = "all" if monitor == "all" else "future" if follow else "none"
        for aid in created:
            await self.sync_artist(aid, initial_monitor=initial)  # gère ses propres erreurs
        return len(created)

    async def from_library(self) -> int:
        """Albums of /music tagged with MusicBrainz ids (beets, Picard…) but not in the catalog: added,
        with their artist, NOT followed — nothing is downloaded, no whole discography. A library
        plugged in shows up as it is; following an artist stays your choice. Returns how many."""
        async with self._from_library:
            async with self.core.db.session() as s:
                known = set((await s.execute(select(ReleaseGroup.mbid))).scalars())
                present = set((await s.execute(
                    select(LibraryFile.release_group_mbid).where(LibraryFile.release_group_mbid.is_not(None)).distinct()
                )).scalars())
            todo = sorted(present - known)
            touched: set[int] = set()
            artists_added = albums_added = 0
            for mbid in todo:
                try:
                    g = await self.core.mb.get_release_group(mbid)  # one request each (1/s): in the background
                    if not g.get("artist_mbid"):
                        continue
                    async with self.core.db.session() as s:
                        artist = (await s.execute(select(Artist).where(Artist.mbid == g["artist_mbid"]))).scalar_one_or_none()
                    if artist is None:
                        artist, _ = await self._create_artist(
                            g["artist_mbid"], primary_types=["album", "ep"], secondary_types=[],
                            monitored=False, announce=False,
                        )
                        artists_added += 1
                except Exception as e:  # MusicBrainz unavailable: this album is tried again next scan
                    log.info("catalog from library, %s: %s", mbid, e)
                    continue
                async with self.core.db.session() as s:
                    rg = ReleaseGroup(
                        mbid=mbid, artist_id=artist.id, title=g["title"], primary_type=g["primary_type"],
                        secondary_types=g["secondary_types"], first_release_date=g["first_release_date"],
                        monitored=False, status=AlbumStatus.IGNORED,
                    )
                    s.add(rg)
                    await s.flush()
                    s.add(ArtistReleaseGroup(artist_id=artist.id, release_group_id=rg.id))
                    await s.commit()
                touched.add(artist.id)
                albums_added += 1
            for aid in touched:
                await self.core.library.refresh_artist(aid)  # their files: « imported », where they are
        if albums_added:
            await self.core.journal.emit(
                "library.cataloged",
                M("library.cataloged", albums=albums_added, artists=artists_added),
                data={"albums": albums_added, "artists": artists_added},
            )
        return albums_added

    async def ensure_artist(self, mbid: str, follow: bool) -> Artist:
        """Artiste présent dans le catalogue. Créé ici : suivi seulement si demandé (seules ses
        sorties à venir sont alors voulues). Un artiste déjà là n'est jamais dé-suivi."""
        async with self.core.db.session() as s:
            a = (await s.execute(select(Artist).where(Artist.mbid == mbid))).scalar_one_or_none()
        if a is None:
            a = await self.add_artist(
                mbid, primary_types=["album", "ep"], secondary_types=[], follow=follow,
            )
        elif follow and not a.monitored:
            await self.follow(a.id)
        async with self.core.db.session() as s:
            row = await s.get(Artist, a.id)
            assert row
            return row

    async def ensure_album(self, mbid: str, artist_id: int) -> ReleaseGroup:
        async with self.core.db.session() as s:
            rg = (await s.execute(select(ReleaseGroup).where(ReleaseGroup.mbid == mbid))).scalar_one_or_none()
            if rg is None:
                # Sortie hors discographie officielle (bootleg, compilation…) : on la crée à la main
                g = await self.core.mb.get_release_group(mbid)
                rg = ReleaseGroup(
                    mbid=mbid, artist_id=artist_id, title=g["title"], primary_type=g["primary_type"],
                    secondary_types=g["secondary_types"], first_release_date=g["first_release_date"],
                )
                s.add(rg)
                await s.flush()
            linked = (
                await s.execute(
                    select(ArtistReleaseGroup).where(
                        ArtistReleaseGroup.artist_id == artist_id, ArtistReleaseGroup.release_group_id == rg.id
                    )
                )
            ).first()
            if not linked:
                s.add(ArtistReleaseGroup(artist_id=artist_id, release_group_id=rg.id))
            await s.commit()
            await s.refresh(rg)
            return rg

    async def follow(self, artist_id: int) -> bool:
        """Follows an artist from now on: its upcoming releases are wanted, its past stays as it is.

        An artist the catalog only knows by the albums on disk has its discography read first,
        with nothing wanted: otherwise the next sync would take all of it for new releases.
        False if MusicBrainz didn't answer: the artist stays as it was."""
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return False
            read = artist.last_synced_at is not None
        if not read:
            await self.sync_artist(artist_id, initial_monitor="none")
        today = datetime.now(UTC).date().isoformat()
        upcoming: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist or artist.last_synced_at is None:
                return False
            if not artist.monitored:
                artist.monitored = True
                artist.followed_at = datetime.now(UTC)
            for rg in (await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars():
                upcoming_type = wants(artist, rg.primary_type, rg.secondary_types)
                if (rg.first_release_date or "") >= today and upcoming_type and _set_monitored(rg, True):
                    upcoming.append(rg.title)
            await s.commit()
            name = artist.name
        await self.core.journal.emit(
            "artist.followed", M("artist.followed", name=name, n=len(upcoming)),
            artist_id=artist_id, data={"upcoming": upcoming},
        )
        return True

    async def unfollow(self, artist_id: int) -> None:
        """Its upcoming releases are no longer wanted; what you asked for yourself stays."""
        today = datetime.now(UTC).date().isoformat()
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return
            artist.monitored = False
            for rg in (await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars():
                if rg.status == AlbumStatus.WANTED and (rg.first_release_date or "9999") > today:
                    _set_monitored(rg, False)
            await s.commit()
            name = artist.name
        await self.core.journal.emit(
            "artist.unfollowed", M("artist.unfollowed", name=name), artist_id=artist_id,
        )

    async def sync_artist(self, artist_id: int, initial_monitor: str | None = None) -> None:
        """Récupère la discographie et marque comme recherchés les albums suivis non présents."""
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return
            mbid, name = artist.mbid, artist.name
        try:
            groups = await self.core.mb.artist_release_groups(mbid)
        except Exception as e:
            await self.core.journal.emit(
                "musicbrainz.sync_failed", M("musicbrainz.sync_failed", name=name, error=str(e)),
                level="error", artist_id=artist_id,
            )
            return

        added: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            assert artist
            # Recherche globale : une sortie peut déjà exister chez un autre artiste (featuring, split)
            mbids = [g["mbid"] for g in groups]
            existing = {
                rg.mbid: rg
                for rg in (await s.execute(select(ReleaseGroup).where(ReleaseGroup.mbid.in_(mbids)))).scalars()
            } if mbids else {}
            linked = set(
                (
                    await s.execute(
                        select(ArtistReleaseGroup.release_group_id).where(ArtistReleaseGroup.artist_id == artist_id)
                    )
                ).scalars()
            )
            new_rgs: list[ReleaseGroup] = []
            shared: list[str] = []
            now_str = datetime.now(UTC).date().isoformat()
            since = (artist.followed_at or artist.added_at or datetime.now(UTC)).date().isoformat()
            for g in groups:
                rg = existing.get(g["mbid"])
                if rg:
                    rg.title = g["title"]
                    rg.primary_type = g["primary_type"]
                    rg.secondary_types = g["secondary_types"]
                    rg.first_release_date = g["first_release_date"]
                    if rg.id not in linked:
                        # Déjà connue via un autre artiste : on la rattache, sans toucher à son suivi
                        s.add(ArtistReleaseGroup(artist_id=artist_id, release_group_id=rg.id))
                        linked.add(rg.id)
                        shared.append(rg.title)
                    continue
                follow = wants(artist, g["primary_type"], g["secondary_types"])
                if initial_monitor == "none":
                    follow = False
                elif initial_monitor == "future":
                    follow = follow and (g["first_release_date"] or "9999") >= now_str
                elif initial_monitor is None:
                    # Followed: only what comes out after you followed it. An old release added
                    # late to MusicBrainz is not wanted on its own
                    follow = follow and (g["first_release_date"] or "9999") >= since
                rg = ReleaseGroup(
                    mbid=g["mbid"],
                    artist_id=artist_id,
                    title=g["title"],
                    primary_type=g["primary_type"],
                    secondary_types=g["secondary_types"],
                    first_release_date=g["first_release_date"],
                    monitored=follow and artist.monitored,
                    status=AlbumStatus.WANTED if follow and artist.monitored else AlbumStatus.IGNORED,
                )
                s.add(rg)
                new_rgs.append(rg)
                if initial_monitor is None and follow:
                    added.append(g["title"])
            await s.flush()
            for rg in new_rgs:
                s.add(ArtistReleaseGroup(artist_id=artist_id, release_group_id=rg.id))
            artist.last_synced_at = datetime.now(UTC)
            await s.commit()

        await self.core.journal.emit(
            "musicbrainz.synced",
            M(
                "musicbrainz.synced", name=name, total=len(groups),
                details=[
                    *([M("musicbrainz.detail.added", n=len(added), titles=", ".join(added[:5]))] if added else []),
                    *([M("musicbrainz.detail.shared", n=len(shared), titles=", ".join(shared[:3]))] if shared else []),
                ],
            ),
            artist_id=artist_id,
            data={"total": len(groups), "new_monitored": added, "shared": shared},
        )
        # Ce qui est déjà dans /music passe en « importé »
        await self.core.library.refresh_artist(artist_id)

    async def ensure_releases(self, rg_id: int) -> None:
        """Charge les éditions + pistes du release group depuis MusicBrainz (une seule fois)."""
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            if not rg or rg.releases_fetched:
                return
            rg_mbid = rg.mbid
        releases = await self.core.mb.release_group_releases(rg_mbid)
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            assert rg
            known = {
                r.mbid: r
                for r in (await s.execute(select(Release).where(Release.release_group_id == rg_id))).scalars()
            }
            for r in releases:
                if r["mbid"] in known:
                    continue
                rel = Release(
                    mbid=r["mbid"],
                    release_group_id=rg_id,
                    title=r["title"],
                    date=r["date"],
                    country=r["country"],
                    status=r["status"],
                    disambiguation=r["disambiguation"],
                    formats=r["formats"],
                    track_count=r["track_count"],
                    disc_count=r["disc_count"],
                    label=r["label"],
                    barcode=r["barcode"],
                    tracks=[Track(**t) for t in r["tracks"]],
                )
                s.add(rel)
            await s.flush()
            default = pick_default_release(releases)
            if default and rg.selected_release_id is None:
                sel = (await s.execute(select(Release.id).where(Release.mbid == default["mbid"]))).scalar_one()
                rg.selected_release_id = sel
            rg.releases_fetched = True
            await s.commit()

    async def releases_with_tracks(self, rg_id: int) -> list[Release]:
        await self.ensure_releases(rg_id)
        async with self.core.db.session() as s:
            res = await s.execute(
                select(Release).where(Release.release_group_id == rg_id).options(selectinload(Release.tracks))
            )
            return list(res.scalars())

    async def set_album_monitored(self, rg_id: int, monitored: bool) -> ReleaseGroup | None:
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            if not rg:
                return None
            rg.monitored = monitored
            if monitored and rg.status == AlbumStatus.IGNORED:
                rg.status = AlbumStatus.WANTED
                set_reason(rg, "status_reason", None)
            elif not monitored and rg.status in (AlbumStatus.WANTED, AlbumStatus.FAILED):
                rg.status = AlbumStatus.IGNORED
            await s.commit()
            await s.refresh(rg)
        await self.core.journal.emit(
            "album.monitored" if monitored else "album.unmonitored",
            M("album.monitored" if monitored else "album.unmonitored", title=rg.title),
            artist_id=rg.artist_id,
            release_group_id=rg.id,
        )
        return rg

    async def bulk_monitor(self, artist_id: int, scope: str, section: str | None = None) -> int:
        """Vouloir en masse. scope : all | none. section : album, ep, single, live… (comme l'affichage)."""
        changed: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return 0
            rgs = list((await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars())
            for rg in rgs:
                if section and section_of(rg) != section:
                    continue
                if _set_monitored(rg, scope == "all"):
                    changed.append(rg.title)
            await s.commit()
            name = artist.name
        if changed:
            await self.core.journal.emit(
                "album.bulk",
                M(f"album.bulk.section.{scope}" if section else f"album.bulk.{scope}", name=name, n=len(changed), section=section),
                artist_id=artist_id,
                data={"scope": scope, "section": section, "titles": changed},
            )
        return len(changed)

    async def apply_type_filter(self, artist_id: int) -> int:
        """Après un changement des types suivis : les sorties à venir d'un type qui n'en fait plus
        partie ne sont plus voulues. Le reste ne bouge pas : ce que tu as demandé reste demandé.

        Ajouter un type ne lance rien automatiquement (pas d'avalanche de téléchargements).
        """
        today = datetime.now(UTC).date().isoformat()
        changed: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return 0
            rgs = list((await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars())
            for rg in rgs:
                upcoming = rg.status == AlbumStatus.WANTED and (rg.first_release_date or "9999") > today
                dropped = upcoming and not wants(artist, rg.primary_type, rg.secondary_types)
                if dropped and _set_monitored(rg, False):
                    changed.append(rg.title)
            await s.commit()
            name = artist.name
        if changed:
            await self.core.journal.emit(
                "album.bulk",
                M("album.bulk.types", name=name, n=len(changed)),
                artist_id=artist_id,
                data={"scope": "types", "titles": changed},
            )
        return len(changed)

    async def delete_artist(self, artist_id: int) -> None:
        async with self.core.db.session() as s:
            a = await s.get(Artist, artist_id)
            if not a:
                return
            name = a.name
            owned = list((await s.execute(select(ReleaseGroup).where(ReleaseGroup.artist_id == artist_id))).scalars())
            kept = 0
            for rg in owned:
                other = (
                    await s.execute(
                        select(ArtistReleaseGroup.artist_id).where(
                            ArtistReleaseGroup.release_group_id == rg.id, ArtistReleaseGroup.artist_id != artist_id
                        )
                    )
                ).scalars().first()
                if other is not None:
                    rg.artist_id = other
                    kept += 1
            await s.flush()
            await s.delete(a)
            await s.commit()
        await self.core.journal.emit(
            "artist.removed",
            M("artist.removed_shared", name=name, n=kept, kept=kept) if kept else M("artist.removed", name=name),
            artist_id=artist_id
        )
