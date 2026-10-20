"""One-off conversion of reasons stored in French by older versions.

Before messages had keys, album and candidate reasons were stored as French
sentences. The common ones are recognised here and given their key, so they
show in the UI's language. Unknown sentences are left as they are.
"""

import re
from collections.abc import Callable

from sqlalchemy import select

from .db import Database
from .messages import M, Msg, set_reason
from .models import Candidate, ReleaseGroup

Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], Msg]]

_RG: list[Rule] = [
    (re.compile(r"^(\d+) proposition\(s\) en attente de validation$"), lambda m: M("reason.awaiting", n=int(m[1]))),
    (re.compile(r"^Aucun candidat valable parmi (\d+) dossiers$"), lambda m: M("reason.no_valid", n=int(m[1]))),
    (re.compile(r"^Depuis (.+)$"), lambda m: M("reason.from_peer", peer=m[1])),
    (re.compile(r"^Reprise depuis (.+)$"), lambda m: M("reason.resume_from", peer=m[1])),
    (re.compile(r"^Complément depuis (.+)$"), lambda m: M("reason.complement_from", peer=m[1])),
    (re.compile(r"^Recherche interrompue par un redémarrage$"), lambda m: M("reason.restart_interrupted")),
    (re.compile(r"^Propositions refusées$"), lambda m: M("reason.dismissed")),
    (re.compile(r"^Fichiers absents de la bibliothèque$"), lambda m: M("reason.files_missing")),
    (re.compile(r"^Aucune édition connue sur MusicBrainz$"), lambda m: M("reason.no_edition")),
    (re.compile(r"^Le candidat choisi a échoué, choisis-en un autre$"), lambda m: M("reason.chosen_failed")),
    (re.compile(r"^Présent en (.+), recherche d'une meilleure qualité$"), lambda m: M("reason.upgrading", format=m[1])),
    (re.compile(r"^Importé en (.+), recherche d'une meilleure qualité$"), lambda m: M("reason.imported_upgrading", format=m[1])),
]

_CANDIDATE: list[Rule] = [
    (
        re.compile(r"^(\d+) piste\(s\) manquante\(s\) sur (\d+) \(toléré : (\d+)\)$"),
        lambda m: M("reject.missing_tracks", n=int(m[1]), total=int(m[2]), allowed=int(m[3])),
    ),
    (re.compile(r"^Format (.+) non autorisé par le profil$"), lambda m: M("reject.format_refused", format=m[1])),
    (
        re.compile(r"^Titres trop différents de la tracklist \((\d+) % < (\d+) %\)$"),
        lambda m: M("reject.titles", score=int(m[1]), min=int(m[2])),
    ),
    (re.compile(r"^Aucune tracklist MusicBrainz disponible$"), lambda m: M("reject.no_tracklist")),
    (re.compile(r"^Format non reconnu sur certains fichiers$"), lambda m: M("reject.unknown_format")),
    (re.compile(r"^Pas mieux que la version présente \((.+)\)$"), lambda m: M("reject.not_better", format=m[1])),
    (
        re.compile(r"^aucun transfert n'a démarré en (\d+) minutes \(pair absent ou file pleine\)$"),
        lambda m: M("reason.stalled", minutes=int(m[1])),
    ),
]


def _convert(text: str, rules: list[Rule]) -> Msg | None:
    for pattern, build in rules:
        if m := pattern.match(text):
            return build(m)
    return None


async def convert_legacy_reasons(db: Database) -> int:
    changed = 0
    async with db.session() as s:
        for model, attr, rules in (
            (ReleaseGroup, "status_reason", _RG),
            (Candidate, "reject_reason", _CANDIDATE),
        ):
            column, column_t = getattr(model, attr), getattr(model, f"{attr}_t")
            rows = (await s.execute(select(model).where(column.is_not(None), column_t.is_(None)))).scalars()
            for row in rows:
                msg = _convert(getattr(row, attr), rules)
                if msg:
                    set_reason(row, attr, msg)
                    changed += 1
        await s.commit()
    return changed
