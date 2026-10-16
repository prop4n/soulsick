"""Catalogue : artistes suivis et discographie issue de MusicBrainz."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import AlbumStatus, Artist, ArtistReleaseGroup, QualityProfile, Release, ReleaseGroup, Track, of_artist
from ..musicbrainz import pick_default_release

if TYPE_CHECKING:
    from ..core import Core

DEFAULT_PROFILES = [
    ("Lossless", ["flac-24", "flac", "alac", "wav"], "flac"),
    ("Lossless puis MP3", ["flac-24", "flac", "alac", "mp3-320", "mp3-v0"], "flac"),
    ("Haute qualité (tout)", ["flac-24", "flac", "alac", "wav", "mp3-320", "mp3-v0", "aac-256", "opus"], "mp3-320"),
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
        rg.status_reason = None
    return True


class CatalogService:
    def __init__(self, core: Core) -> None:
        self.core = core

    async def ensure_default_profiles(self) -> None:
        async with self.core.db.session() as s:
            if (await s.execute(select(QualityProfile.id).limit(1))).first():
                return
            for name, formats, until in DEFAULT_PROFILES:
                s.add(QualityProfile(name=name, formats=formats, upgrade_until=until, max_missing_tracks=0))
            await s.commit()

    async def add_artist(
        self,
        mbid: str,
        *,
        mode: str,
        quality_profile_id: int | None,
        primary_types: list[str],
        secondary_types: list[str],
        monitor: str = "none",  # none | future | all — par défaut rien : tu choisis ensuite
    ) -> Artist:
        info = await self.core.mb.get_artist(mbid)
        async with self.core.db.session() as s:
            existing = (await s.execute(select(Artist).where(Artist.mbid == mbid))).scalar_one_or_none()
            if existing:
                return existing
            a = Artist(
                mbid=mbid,
                name=info["name"],
                sort_name=info["sort_name"],
                disambiguation=info["disambiguation"],
                country=info["country"],
                type=info["type"],
                mode=mode,
                quality_profile_id=quality_profile_id,
                primary_types=primary_types,
                secondary_types=secondary_types,
            )
            s.add(a)
            await s.commit()
            await s.refresh(a)
        await self.core.journal.emit(
            "artist.added",
            f"Artiste ajouté : {a.name} (mode {'automatique' if mode == 'auto' else 'validation'})",
            artist_id=a.id,
            data={"mbid": mbid, "primary_types": primary_types, "secondary_types": secondary_types},
        )
        await self.sync_artist(a.id, initial_monitor=monitor)
        return a

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
                "musicbrainz.sync_failed", f"Synchronisation MusicBrainz échouée pour {name} : {e}",
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
            f"Discographie de {name} synchronisée : {len(groups)} sorties sur MusicBrainz"
            + (f", {len(added)} nouvelle(s) suivie(s) : {', '.join(added[:5])}" if added else "")
            + (f", {len(shared)} partagée(s) avec un autre artiste suivi ({', '.join(shared[:3])})" if shared else ""),
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
                rg.status_reason = None
            elif not monitored and rg.status in (AlbumStatus.WANTED, AlbumStatus.FAILED):
                rg.status = AlbumStatus.IGNORED
            await s.commit()
            await s.refresh(rg)
        await self.core.journal.emit(
            "album.monitored" if monitored else "album.unmonitored",
            f"« {rg.title} » {'ajouté aux albums recherchés' if monitored else 'n’est plus suivi'}",
            artist_id=rg.artist_id,
            release_group_id=rg.id,
        )
        return rg

    async def bulk_monitor(self, artist_id: int, scope: str, section: str | None = None) -> int:
        """Suivi en masse. scope : all | none | future. section : album, ep, single, live… (comme l'affichage)."""
        today = datetime.now(UTC).date().isoformat()
        changed: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return 0
            rgs = list((await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars())
            for rg in rgs:
                if section and section_of(rg) != section:
                    continue
                want = scope == "all" or (scope == "future" and (rg.first_release_date or "9999") >= today)
                if _set_monitored(rg, want):
                    changed.append(rg.title)
            await s.commit()
            name = artist.name
        if changed:
            what = {"all": "suivies", "none": "plus suivies", "future": "suivies seulement si à venir"}[scope]
            await self.core.journal.emit(
                "album.bulk",
                f"{name} : {len(changed)} sortie(s){f' ({section})' if section else ''} {what}",
                artist_id=artist_id,
                data={"scope": scope, "section": section, "titles": changed},
            )
        return len(changed)

    async def apply_type_filter(self, artist_id: int) -> int:
        """Après un changement des types suivis : on arrête de suivre l'existant qui n'en fait plus partie.

        Ajouter un type ne lance rien automatiquement (pas d'avalanche de téléchargements) :
        les actions groupées servent à ça.
        """
        changed: list[str] = []
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return 0
            rgs = list((await s.execute(select(ReleaseGroup).where(of_artist(artist_id)))).scalars())
            for rg in rgs:
                if rg.monitored and not wants(artist, rg.primary_type, rg.secondary_types) and _set_monitored(rg, False):
                    changed.append(rg.title)
            await s.commit()
            name = artist.name
        if changed:
            await self.core.journal.emit(
                "album.bulk",
                f"{name} : {len(changed)} sortie(s) d'un type désormais non suivi ne sont plus suivies",
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
            f"Artiste retiré : {name} (les fichiers de /music sont conservés"
            + (f" ; {kept} sortie(s) partagée(s) restent chez l'autre artiste)" if kept else ")"),
            artist_id=artist_id
        )
