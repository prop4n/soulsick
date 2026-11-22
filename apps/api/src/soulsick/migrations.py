"""One-off changes to the data of an existing install, when soulsick's behaviour changes.

Each step runs once: the names of the steps already done are kept in the database, so a step
never redoes what you changed afterwards (a profile you deleted is not added back).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from .messages import set_reason
from .models import AlbumStatus, Artist, QualityProfile, ReleaseGroup
from .services.catalog import CD_QUALITY

if TYPE_CHECKING:
    from .core import Core

KEY = "migrations"

# Albums the hunt left waiting for your approval (artists in "ask me" mode). An import that
# lacks tracks also waits for you (reason.incomplete_action): that one is a real decision.
_AWAITING_REASONS = {"reason.awaiting", "reason.chosen_failed", "reason.abandoned_pick"}


async def _everything_automatic(core: Core) -> None:
    """No more "ask me" mode nor profile per artist: one profile for every album.

    The profile chosen is the one your followed artists used most, so nothing changes until you
    pick another. A CD-quality profile is added when none puts 16-bit FLAC first. Albums waiting
    for your approval are wanted again: the next hunt starts their best source."""
    async with core.db.session() as s:
        most_used = (await s.execute(
            select(Artist.quality_profile_id)
            .where(Artist.monitored.is_(True), Artist.quality_profile_id.is_not(None))
            .group_by(Artist.quality_profile_id)
            .order_by(func.count().desc(), Artist.quality_profile_id)
            .limit(1)
        )).scalar()
        profiles = list((await s.execute(select(QualityProfile))).scalars())
        cd_first = any(p.formats[:1] == ["flac"] for p in profiles)
        if not cd_first and all(p.name != CD_QUALITY[0] for p in profiles):
            name, formats, until = CD_QUALITY
            s.add(QualityProfile(name=name, formats=formats, upgrade_until=until, max_missing_tracks=0))
        waiting = list((await s.execute(
            select(ReleaseGroup).where(ReleaseGroup.status == AlbumStatus.PENDING_APPROVAL)
        )).scalars())
        for rg in waiting:
            if (rg.status_reason_t or {}).get("key") in _AWAITING_REASONS:
                rg.status = AlbumStatus.WANTED
                rg.last_searched_at = None
                set_reason(rg, "status_reason", None)
        await s.commit()
    settings = await core.settings.get()
    if settings.hunter.profile_id is None and most_used is not None:
        settings.hunter.profile_id = most_used
        await core.settings.save(settings)


async def _follow_means_upcoming(core: Core) -> None:
    """Following an artist now means wanting its upcoming releases; an album you ask for is
    hunted whether its artist is followed or not.

    Before, a paused artist's albums were never hunted, even when marked wanted: they stop
    being wanted, so that nothing starts downloading that didn't before. A followed artist
    counts as followed since it was added."""
    async with core.db.session() as s:
        paused = select(Artist.id).where(Artist.monitored.is_(False))
        rgs = list((await s.execute(select(ReleaseGroup).where(
            ReleaseGroup.artist_id.in_(paused), ReleaseGroup.monitored.is_(True),
            ReleaseGroup.status.in_([AlbumStatus.WANTED, AlbumStatus.FAILED]),
        ))).scalars())
        for rg in rgs:
            rg.monitored = False
            rg.status = AlbumStatus.IGNORED
            set_reason(rg, "status_reason", None)
        followed = select(Artist).where(Artist.monitored.is_(True), Artist.followed_at.is_(None))
        for a in (await s.execute(followed)).scalars():
            a.followed_at = a.added_at
        await s.commit()


STEPS: list[tuple[str, Callable[[Core], Awaitable[None]]]] = [
    ("everything_automatic", _everything_automatic),
    ("follow_means_upcoming", _follow_means_upcoming),
]


async def run(core: Core) -> list[str]:
    """Runs the steps not done yet; returns their names."""
    done = set((await core.settings.get_raw(KEY) or {}).get("done", []))
    ran = []
    for name, step in STEPS:
        if name in done:
            continue
        await step(core)
        done.add(name)
        ran.append(name)
        await core.settings.set_raw(KEY, {"done": sorted(done)})
    return ran
