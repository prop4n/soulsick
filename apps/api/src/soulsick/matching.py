"""Association fichiers ↔ pistes MusicBrainz.

Utilisé à deux endroits :
- pendant la chasse, sur les noms de fichiers distants (et durées annoncées par le pair) ;
- à l'import, sur les fichiers téléchargés (tags + durées réelles).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

_NUM_RE = re.compile(r"^\s*(?:(?:cd|disc|disk)\s*(\d+)\s*[-._ ]\s*)?(?:(\d)[-.](?=\d{2}))?(\d{1,3})(?!\d)")
_DISC_DIR_RE = re.compile(r"(?:cd|disc|disk)\s*(\d+)", re.I)


@dataclass
class TrackRef:
    disc: int
    position: int
    title: str
    length_s: float | None = None


@dataclass
class FileRef:
    path: str  # chemin (distant ou local), sert aussi à déduire numéro/disque
    duration_s: float | None = None
    tag_title: str | None = None
    tag_track: int | None = None
    tag_disc: int | None = None


@dataclass
class Assignment:
    file_index: int
    track_index: int
    score: float
    title_score: float
    number_match: bool
    duration_delta: float | None


@dataclass
class MatchResult:
    assignments: list[Assignment] = field(default_factory=list)
    unmatched_tracks: list[int] = field(default_factory=list)
    unmatched_files: list[int] = field(default_factory=list)
    title_score: float = 0.0  # moyenne sur toutes les pistes (0 pour une piste manquante)
    duration_score: float | None = None
    count_ratio: float = 0.0

    @property
    def confidence(self) -> float:
        """Confiance globale 0–1."""
        parts = [(self.title_score, 0.45), (self.count_ratio, 0.35)]
        if self.duration_score is not None:
            parts.append((self.duration_score, 0.20))
        total_w = sum(w for _, w in parts)
        return sum(v * w for v, w in parts) / total_w


@lru_cache(maxsize=65536)
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)  # (feat. …), [remaster]…
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def stem(path: str) -> str:
    name = basename(path)
    return name.rsplit(".", 1)[0] if "." in name else name


def parse_numbers(path: str) -> tuple[int | None, int | None]:
    """(disque, piste) déduits du nom de fichier et du dossier parent."""
    s = stem(path)
    disc = None
    track = None
    m = _NUM_RE.match(s)
    if m:
        disc = int(m.group(1) or m.group(2)) if (m.group(1) or m.group(2)) else None
        track = int(m.group(3))
    parts = path.replace("\\", "/").split("/")
    if disc is None and len(parts) >= 2:
        dm = _DISC_DIR_RE.search(parts[-2])
        if dm:
            disc = int(dm.group(1))
    return disc, track


_GENERIC_WORDS = {"track", "piste", "titre", "pista", "audio", "untitled"}


def has_title(path: str) -> bool:
    """Whether a file name says which song it is (\"06 - Song.flac\"), not only its number (\"Track 06.flac\")."""
    words = normalize(_title_from_filename(path)).split()
    return any(w not in _GENERIC_WORDS and not w.isdigit() for w in words)


def _title_from_filename(path: str) -> str:
    s = stem(path)
    s = _NUM_RE.sub("", s, count=1)
    return s.strip(" -._")


def match_files(
    tracks: list[TrackRef],
    files: list[FileRef],
    artist_hint: str = "",
    duration_tolerance: float = 3.0,
) -> MatchResult:
    if not tracks:
        return MatchResult(unmatched_files=list(range(len(files))))

    multi_disc = len({t.disc for t in tracks}) > 1
    artist_norm = normalize(artist_hint)
    track_titles = [normalize(t.title) for t in tracks]  # une fois, pas pour chaque fichier
    pairs: list[tuple[float, int, int, float, bool, float | None]] = []

    for fi, f in enumerate(files):
        p_disc, p_track = parse_numbers(f.path)
        num = f.tag_track if f.tag_track is not None else p_track
        disc = f.tag_disc if f.tag_disc is not None else p_disc
        raw_title = f.tag_title or _title_from_filename(f.path)
        ftitle = normalize(raw_title)
        if artist_norm and ftitle.startswith(artist_norm + " "):
            ftitle = ftitle[len(artist_norm) + 1 :]

        for ti, t in enumerate(tracks):
            title_score = fuzz.token_set_ratio(track_titles[ti], ftitle) / 100 if ftitle else 0.0
            if multi_disc:
                number_match = num == t.position and (disc is None or disc == t.disc)
            else:
                number_match = num == t.position
            delta = None
            dur_ok = 0.5
            if f.duration_s and t.length_s:
                delta = abs(f.duration_s - t.length_s)
                dur_ok = 1.0 if delta <= duration_tolerance else max(0.0, 1 - (delta - duration_tolerance) / 30)
            score = 0.6 * title_score + 0.25 * (1.0 if number_match else 0.0) + 0.15 * dur_ok
            pairs.append((score, fi, ti, title_score, number_match, delta))

    # Affectation gloutonne par meilleur score (suffisant pour des albums de quelques dizaines de pistes)
    pairs.sort(key=lambda p: p[0], reverse=True)
    used_f: set[int] = set()
    used_t: set[int] = set()
    result = MatchResult()
    for score, fi, ti, ts, nm, delta in pairs:
        if fi in used_f or ti in used_t:
            continue
        if score < 0.35:
            continue
        used_f.add(fi)
        used_t.add(ti)
        result.assignments.append(Assignment(fi, ti, round(score, 3), round(ts, 3), nm, delta))

    result.assignments.sort(key=lambda a: a.track_index)
    result.unmatched_tracks = [i for i in range(len(tracks)) if i not in used_t]
    result.unmatched_files = [i for i in range(len(files)) if i not in used_f]
    result.title_score = sum(a.title_score for a in result.assignments) / len(tracks)
    result.count_ratio = min(len(files), len(tracks)) / max(len(files), len(tracks))
    deltas = [a.duration_delta for a in result.assignments if a.duration_delta is not None]
    if deltas:
        result.duration_score = sum(1 for d in deltas if d <= duration_tolerance) / len(tracks)
    return result
