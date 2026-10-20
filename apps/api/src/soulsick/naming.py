"""Modèle de nommage des fichiers importés dans la bibliothèque."""

import re
import string
import unicodedata
from dataclasses import dataclass

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Usual limit of a file or folder name, in bytes (ext4, btrfs, ZFS, NTFS via most drivers…).
# Titles stacking combining marks ("zalgo") easily go over it.
MAX_NAME_BYTES = 255


def fit_name(stem: str, ext: str = "", limit: int = MAX_NAME_BYTES) -> str:
    """`stem + ext`, the stem shortened on a character boundary so the whole name fits in `limit` bytes."""
    budget = limit - len(ext.encode())
    if len(stem.encode()) > budget:
        stem = stem.encode()[:budget].decode("utf-8", "ignore").rstrip(" .") or "_"
    return stem + ext


def sanitize(part: str) -> str:
    """Nettoie un segment de chemin (caractères interdits, points/espaces finaux)."""
    part = unicodedata.normalize("NFC", part)
    part = _FORBIDDEN.sub("_", part)
    part = re.sub(r"\s+", " ", part).strip().rstrip(".")
    return part or "_"


def safe_component(part: str) -> str:
    """Segment de chemin venant du réseau (pseudo, dossier, fichier) : jamais de séparateur ni de `..`."""
    part = sanitize(part.replace("/", "_").replace("\\", "_"))
    if part in {".", ".."} or part.startswith(".."):
        part = "_" + part.lstrip(".")
    stem, dot, ext = part.rpartition(".")
    # Keep a short extension when shortening (a file name); a folder has none to keep
    return fit_name(stem, dot + ext) if dot and stem and len(ext) <= 5 else fit_name(part)


@dataclass
class TrackNaming:
    albumartist: str
    artist: str
    album: str
    year: str
    title: str
    track: int
    disc: int
    disc_count: int
    ext: str
    release_type: str = ""


class _SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        return kwargs.get(key, "") if isinstance(key, str) else super().get_value(key, args, kwargs)


def render_path(template: str, t: TrackNaming) -> str:
    """Rend un chemin relatif à partir du modèle, ex. `{albumartist}/{year} - {album}/{track:02} - {title}`.

    Variables : albumartist, artist, album, year, title, track, disc, disc_prefix, release_type.
    `disc_prefix` vaut « 1-» pour un album multi-disques, vide sinon.
    """
    values = {
        "albumartist": sanitize(t.albumartist),
        "artist": sanitize(t.artist),
        "album": sanitize(t.album),
        "year": t.year or "0000",
        "title": sanitize(t.title),
        "track": t.track,
        "disc": t.disc,
        "disc_prefix": f"{t.disc}-" if t.disc_count > 1 else "",
        "release_type": sanitize(t.release_type) if t.release_type else "",
    }
    rendered = _SafeFormatter().format(template, **values)
    parts = [p.strip() for p in rendered.split("/") if p.strip()]
    # Les segments issus des variables sont déjà nettoyés ; on nettoie aussi le texte du modèle
    parts = [sanitize(p) for p in parts]
    # Every name must fit the filesystem; the file keeps its extension
    parts = [fit_name(p) for p in parts[:-1]] + [fit_name(parts[-1], f".{t.ext.lower()}")]
    return "/".join(parts)
