"""Détection du format audio d'un fichier et classement selon un profil qualité."""

from dataclasses import dataclass

AUDIO_EXTENSIONS = {"flac", "mp3", "m4a", "aac", "ogg", "opus", "wav", "aiff", "aif", "wma", "alac", "ape", "wv"}
LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}

# Tous les formats connus, du meilleur au moins bon (ordre par défaut des profils)
ALL_FORMATS: list[tuple[str, str]] = [
    ("flac-24", "FLAC 24-bit"),
    ("flac", "FLAC 16-bit"),
    ("alac", "ALAC"),
    ("wav", "WAV / AIFF"),
    ("mp3-320", "MP3 320"),
    ("mp3-v0", "MP3 V0"),
    ("aac-256", "AAC ≥ 256"),
    ("mp3-256", "MP3 256"),
    ("opus", "Opus"),
    ("ogg", "Ogg Vorbis"),
    ("mp3-192", "MP3 192"),
    ("aac", "AAC < 256"),
    ("mp3-low", "MP3 < 192"),
]
FORMAT_LABELS = dict(ALL_FORMATS)


@dataclass(frozen=True)
class FileInfo:
    ext: str
    bitrate: int | None = None  # kbps
    bit_depth: int | None = None
    sample_rate: int | None = None
    vbr: bool = False


def extension_of(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_audio(filename: str) -> bool:
    return extension_of(filename) in AUDIO_EXTENSIONS


def detect_format(info: FileInfo) -> str | None:
    ext = info.ext.lower()
    br = info.bitrate or 0
    if ext == "flac":
        return "flac-24" if (info.bit_depth or 16) > 16 else "flac"
    if ext in {"wav", "aiff", "aif"}:
        return "wav"
    if ext == "alac":
        return "alac"
    if ext == "m4a":
        # m4a : ALAC si débit très élevé, sinon AAC
        if br >= 600:
            return "alac"
        return "aac-256" if br >= 250 else "aac" if br else "aac"
    if ext == "aac":
        return "aac-256" if br >= 250 else "aac"
    if ext == "opus":
        return "opus"
    if ext == "ogg":
        return "ogg"
    if ext == "mp3":
        if info.vbr and br >= 220:
            return "mp3-v0"
        if br >= 315:
            return "mp3-320"
        if br >= 220:
            return "mp3-v0" if info.vbr or br < 250 else "mp3-256"
        if br >= 250:
            return "mp3-256"
        if br >= 185:
            return "mp3-192"
        if br == 0:
            return "mp3-192"  # débit inconnu : on suppose moyen
        return "mp3-low"
    return None


def format_rank(fmt: str | None, profile_formats: list[str]) -> int | None:
    """Rang du format dans le profil (0 = meilleur). None = refusé par le profil."""
    if fmt is None or fmt not in profile_formats:
        return None
    return profile_formats.index(fmt)


def worst_format(formats: list[str | None], profile_formats: list[str]) -> str | None:
    """Le format le moins bon d'un ensemble de fichiers (celui qui détermine la qualité d'un album)."""
    order = [f for f, _ in ALL_FORMATS]
    known = [f for f in formats if f is not None]
    if not known or len(known) != len(formats):
        return None
    return max(known, key=lambda f: order.index(f) if f in order else len(order))


def is_better_or_equal(fmt: str | None, target: str | None) -> bool:
    if target is None:
        return True
    if fmt is None:
        return False
    order = [f for f, _ in ALL_FORMATS]
    return order.index(fmt) <= order.index(target)
