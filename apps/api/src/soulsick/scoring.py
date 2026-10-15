"""Regroupement des résultats de recherche en dossiers candidats et calcul d'un score explicable.

Score sur 100 :
- 50 pts : correspondance avec la tracklist MusicBrainz (titres, nombre de pistes, durées)
- 30 pts : rang du format dans le profil qualité
- 20 pts : disponibilité du pair (slot libre, file d'attente, vitesse)
"""

import re
from dataclasses import dataclass, field

from .matching import FileRef, MatchResult, TrackRef, match_files
from .quality import FORMAT_LABELS, FileInfo, detect_format, extension_of, format_rank, is_audio, worst_format

_DISC_DIR = re.compile(r"^(?:cd|disc|disk)\s*\d+$", re.I)
EXTRA_EXTENSIONS = {"jpg", "jpeg", "png", "cue", "log"}


@dataclass
class RemoteFile:
    filename: str
    size: int = 0
    bitrate: int | None = None
    duration: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    vbr: bool = False

    @property
    def ext(self) -> str:
        return extension_of(self.filename)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size": self.size,
            "bitrate": self.bitrate,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "vbr": self.vbr,
            "format": detect_format(self.info) if is_audio(self.filename) else None,
        }

    @property
    def info(self) -> FileInfo:
        return FileInfo(self.ext, self.bitrate, self.bit_depth, self.sample_rate, self.vbr)


@dataclass
class PeerResult:
    username: str
    has_free_slots: bool
    avg_speed: int
    queue_size: int
    files: list[RemoteFile]


@dataclass
class ReleaseOption:
    release_id: int
    title: str
    tracks: list[TrackRef]


@dataclass
class ScoredCandidate:
    username: str
    directory: str
    audio_files: list[RemoteFile]
    extra_files: list[RemoteFile]
    has_free_slots: bool
    avg_speed: int
    queue_size: int
    format: str | None = None
    score: float = 0.0
    detail: dict = field(default_factory=dict)
    reject_reason: str | None = None
    release_id: int | None = None

    @property
    def rejected(self) -> bool:
        return self.reject_reason is not None


def group_key(path: str) -> str:
    """Dossier d'album : le parent, ou le grand-parent si le parent est « CD1 », « Disc 2 »…

    Les chemins Soulseek utilisent `\\` comme séparateur.
    """
    p = path.replace("/", "\\")
    d = p.rsplit("\\", 1)[0] if "\\" in p else ""
    if "\\" in d:
        parent, last = d.rsplit("\\", 1)
        if _DISC_DIR.match(last.strip()):
            return parent
    return d


def group_results(results: list[PeerResult]) -> list[ScoredCandidate]:
    groups: dict[tuple[str, str], ScoredCandidate] = {}
    for r in results:
        for f in r.files:
            key = (r.username, group_key(f.filename))
            c = groups.get(key)
            if c is None:
                c = groups[key] = ScoredCandidate(
                    username=r.username,
                    directory=key[1],
                    audio_files=[],
                    extra_files=[],
                    has_free_slots=r.has_free_slots,
                    avg_speed=r.avg_speed,
                    queue_size=r.queue_size,
                )
            if any(x.filename == f.filename for x in c.audio_files + c.extra_files):
                continue
            if is_audio(f.filename):
                c.audio_files.append(f)
            elif f.ext in EXTRA_EXTENSIONS:
                c.extra_files.append(f)
    return [c for c in groups.values() if c.audio_files]


def peer_points(c: ScoredCandidate) -> tuple[float, dict]:
    slot = 10.0 if c.has_free_slots else 0.0
    queue = 5.0 / (1 + c.queue_size / 5)
    speed = 5.0 * min(1.0, c.avg_speed / 2_000_000)
    return slot + queue + speed, {
        "points": round(slot + queue + speed, 1),
        "max": 20,
        "free_slot": c.has_free_slots,
        "queue_size": c.queue_size,
        "avg_speed": c.avg_speed,
    }


def score_candidate(
    c: ScoredCandidate,
    releases: list[ReleaseOption],
    profile_formats: list[str],
    max_missing_tracks: int = 0,
    min_match: float = 0.6,
    artist_hint: str = "",
) -> ScoredCandidate:
    # Format : c'est le fichier le moins bon qui fixe la qualité de l'album
    formats = [detect_format(f.info) for f in c.audio_files]
    fmt = worst_format(formats, profile_formats)
    c.format = fmt
    distinct = {f for f in formats if f}
    rank = format_rank(fmt, profile_formats)
    n = max(1, len(profile_formats))
    fmt_points = 0.0 if rank is None else 30.0 * (1 - rank / n)
    c.detail["format"] = {
        "points": round(fmt_points, 1),
        "max": 30,
        "format": fmt,
        "label": FORMAT_LABELS.get(fmt or "", "inconnu"),
        "rank": rank,
        "mixed": len(distinct) > 1,
    }

    # Tracklist : on garde l'édition MusicBrainz qui correspond le mieux
    best: tuple[MatchResult, ReleaseOption] | None = None
    file_refs = [FileRef(path=f.filename, duration_s=f.duration) for f in c.audio_files]
    for rel in releases:
        m = match_files(rel.tracks, file_refs, artist_hint=artist_hint)
        if best is None or m.confidence > best[0].confidence:
            best = (m, rel)

    match_points = 0.0
    if best:
        m, rel = best
        c.release_id = rel.release_id
        match_points = 50.0 * m.confidence
        c.detail["match"] = {
            "points": round(match_points, 1),
            "max": 50,
            "release": rel.title,
            "release_id": rel.release_id,
            "tracks_expected": len(rel.tracks),
            "tracks_found": len(c.audio_files),
            "tracks_matched": len(m.assignments),
            "title_score": round(m.title_score, 3),
            "duration_score": None if m.duration_score is None else round(m.duration_score, 3),
            "confidence": round(m.confidence, 3),
            "missing": [rel.tracks[i].title for i in m.unmatched_tracks],
        }

    p_points, p_detail = peer_points(c)
    c.detail["peer"] = p_detail
    c.score = round(fmt_points + match_points + p_points, 1)

    # Raisons de rejet, dans l'ordre de gravité
    if rank is None:
        if fmt is None and len(distinct) > 0:
            c.reject_reason = "Format non reconnu sur certains fichiers"
        else:
            label = FORMAT_LABELS.get(fmt or "", fmt or "inconnu")
            c.reject_reason = f"Format {label} non autorisé par le profil"
    elif best is None:
        c.reject_reason = "Aucune tracklist MusicBrainz disponible"
    else:
        m, rel = best
        missing = len(m.unmatched_tracks)
        if missing > max_missing_tracks:
            c.reject_reason = f"{missing} piste(s) manquante(s) sur {len(rel.tracks)} (toléré : {max_missing_tracks})"
        elif m.title_score < min_match:
            c.reject_reason = f"Titres trop différents de la tracklist ({round(m.title_score * 100)} % < {round(min_match * 100)} %)"
    return c


def rank_candidates(
    results: list[PeerResult],
    releases: list[ReleaseOption],
    profile_formats: list[str],
    max_missing_tracks: int = 0,
    min_match: float = 0.6,
    artist_hint: str = "",
) -> list[ScoredCandidate]:
    cands = [
        score_candidate(c, releases, profile_formats, max_missing_tracks, min_match, artist_hint)
        for c in group_results(results)
    ]
    cands.sort(key=lambda c: (c.rejected, -c.score))
    return cands
