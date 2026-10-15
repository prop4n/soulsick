"""Partage / seeding : dossiers partagés, règles, statistiques d'indexation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..models import Share
from ..slsk.rules import ShareRules, scan_share

if TYPE_CHECKING:
    from ..core import Core


class ShareService:
    def __init__(self, core: Core) -> None:
        self.core = core

    async def rules(self) -> list[ShareRules]:
        """Règles effectives : dossiers configurés + bibliothèque si « partager /music » est activé."""
        settings = await self.core.settings.get()
        async with self.core.db.session() as s:
            shares = list((await s.execute(select(Share).where(Share.enabled.is_(True)))).scalars())
        out = [ShareRules(sh.path, sh.allowed_extensions, sh.exclude_patterns) for sh in shares]
        music = str(self.core.env.music_dir)
        if settings.soulseek.share_library and not any(os.path.abspath(r.path) == os.path.abspath(music) for r in out):
            out.append(ShareRules(music))
        return out

    async def rescan(self) -> None:
        """Recalcule les statistiques de chaque dossier et pousse les règles au moteur."""
        async with self.core.db.session() as s:
            shares = list((await s.execute(select(Share))).scalars())
            for sh in shares:
                if not os.path.isdir(sh.path):
                    sh.file_count = sh.total_size = sh.excluded_count = 0
                    continue
                res = await asyncio.to_thread(scan_share, ShareRules(sh.path, sh.allowed_extensions, sh.exclude_patterns), 0)
                sh.file_count = res.included
                sh.total_size = res.included_size
                sh.excluded_count = res.excluded
                sh.last_scan_at = datetime.now(UTC)
            await s.commit()
        rules = await self.rules()
        await self.core.engine.apply_shares(rules)
        total = sum(sh.file_count for sh in shares if sh.enabled)
        await self.core.journal.emit(
            "shares.applied",
            f"Partages mis à jour : {len(rules)} dossier(s) exposé(s) au réseau"
            + (f", {total} fichiers dans les dossiers configurés" if shares else ""),
            data={"paths": [r.path for r in rules]},
        )

    async def preview(self, share_id: int) -> dict:
        async with self.core.db.session() as s:
            sh = await s.get(Share, share_id)
            if not sh:
                raise KeyError(share_id)
            rules = ShareRules(sh.path, sh.allowed_extensions, sh.exclude_patterns)
        if not os.path.isdir(rules.path):
            return {"exists": False, "included": 0, "excluded": 0, "excluded_samples": [], "extensions": {}}
        res = await asyncio.to_thread(scan_share, rules, 300)
        return {
            "exists": True,
            "included": res.included,
            "included_size": res.included_size,
            "excluded": res.excluded,
            "excluded_samples": res.excluded_samples,
            "extensions": dict(sorted(res.extensions.items(), key=lambda kv: -kv[1])),
            "effective_extensions": sorted(rules.extensions),
        }
