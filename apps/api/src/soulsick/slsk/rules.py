"""Règles de partage : quels fichiers d'un dossier partagé sont réellement exposés au réseau."""

import fnmatch
import os
from dataclasses import dataclass, field

from ..quality import AUDIO_EXTENSIONS, extension_of

DEFAULT_SHARE_EXTENSIONS = sorted(AUDIO_EXTENSIONS | {"jpg", "jpeg", "png", "cue", "log"})


@dataclass
class ShareRules:
    path: str
    allowed_extensions: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    @property
    def extensions(self) -> set[str]:
        exts = self.allowed_extensions or DEFAULT_SHARE_EXTENSIONS
        return {e.lower().lstrip(".") for e in exts}

    def check(self, relpath: str) -> str | None:
        """None si le fichier est partagé, sinon la raison de l'exclusion."""
        rel = relpath.replace("\\", "/")
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("."):
            return "fichier caché"
        for pat in self.exclude_patterns:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
                return f"exclu par le motif « {pat} »"
        ext = extension_of(name)
        if ext not in self.extensions:
            return f"extension .{ext or '∅'} non autorisée"
        return None


@dataclass
class ShareScan:
    included: int = 0
    included_size: int = 0
    excluded: int = 0
    excluded_samples: list[dict] = field(default_factory=list)
    extensions: dict[str, int] = field(default_factory=dict)


def scan_share(rules: ShareRules, sample_limit: int = 200) -> ShareScan:
    """Parcourt le dossier et applique les règles (pour l'aperçu dans l'interface)."""
    out = ShareScan()
    root = rules.path
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            reason = rules.check(rel)
            if reason is None:
                out.included += 1
                try:
                    out.included_size += os.path.getsize(full)
                except OSError:
                    pass
                ext = extension_of(fn)
                out.extensions[ext] = out.extensions.get(ext, 0) + 1
            else:
                out.excluded += 1
                if len(out.excluded_samples) < sample_limit:
                    out.excluded_samples.append({"path": rel, "reason": reason})
    return out
