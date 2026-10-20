"""Règles de partage : quels fichiers d'un dossier partagé sont réellement exposés au réseau."""

import fnmatch
import os
from dataclasses import dataclass, field

from ..messages import M, Msg
from ..quality import AUDIO_EXTENSIONS, extension_of

DEFAULT_SHARE_EXTENSIONS = sorted(AUDIO_EXTENSIONS | {"jpg", "jpeg", "png", "cue", "log"})
# Jamais partagés, même si on les autorise explicitement
BLOCKED_EXTENSIONS = {
    "db", "sqlite", "sqlite3", "db-wal", "db-shm", "key", "pem", "p12", "pfx", "kdbx",
    "env", "ini", "conf", "cfg", "json", "yaml", "yml", "toml", "sh", "ssh",
}


@dataclass
class ShareRules:
    path: str
    allowed_extensions: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    @property
    def extensions(self) -> set[str]:
        exts = self.allowed_extensions or DEFAULT_SHARE_EXTENSIONS
        return {e.lower().lstrip(".") for e in exts}

    def check(self, relpath: str) -> Msg | None:
        """None when the file is shared, otherwise why it is excluded."""
        rel = relpath.replace("\\", "/")
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("."):
            return M("share.hidden_file")
        for pat in self.exclude_patterns:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
                return M("share.excluded_pattern", pattern=pat)
        ext = extension_of(name)
        if ext in BLOCKED_EXTENSIONS or name.endswith(("-wal", "-shm")):
            return M("share.blocked_ext", ext=ext)
        if ext not in self.extensions:
            return M("share.ext_not_allowed", ext=ext or "∅")
        return None


@dataclass
class ShareScan:
    included: int = 0
    included_size: int = 0
    excluded: int = 0
    excluded_samples: list[dict] = field(default_factory=list)
    extensions: dict[str, int] = field(default_factory=dict)


def scan_share(rules: ShareRules, sample_limit: int = 200) -> ShareScan:
    """Walks the folder and applies the rules (for the preview in the UI)."""
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
                    out.excluded_samples.append({"path": rel, "reason": reason.text, "reason_t": reason.to_json()})
    return out


def forbidden_share_reason(path: str, protected: list[str]) -> Msg | None:
    """Refuses to share the root, or a folder that contains (or is inside) a protected folder."""
    real = os.path.realpath(path)
    if real == os.path.sep:
        return M("share.root_forbidden")
    for p in protected:
        pr = os.path.realpath(p)
        if real == pr or pr.startswith(real + os.sep) or real.startswith(pr + os.sep):
            return M("share.protected", path=pr)
    return None
