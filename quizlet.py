"""Stage 1 (quizlet): read a Quizlet export CSV with (German term, French
translation) rows into the same record shape as `vocab.extract`."""

import csv
import re
from pathlib import Path

_ARTICLE_RE = re.compile(r"^(?:der|die|das|den|dem|des)\s+", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")


def headword(term: str) -> str:
    """Reduce a Quizlet term to a dictionary lookup key.

    The first column often carries conjugation forms ('sich merken, er merkt
    sich, ...'), alternates ('Die Violine = Geige'), parenthetical notes
    ('sich beruhigen (hat sich beruhigt)') or line breaks ('tot sein\\ner war
    tot'). Keep the first form and drop the article the dict keys do not use.
    """
    head = term.replace("\n", ", ").split(",")[0]
    head = head.split("=")[0]
    head = _PAREN_RE.sub("", head)
    head = _ARTICLE_RE.sub("", head.strip())
    return re.sub(r"\s+", " ", head).strip()


def extract(path: str) -> list[dict]:
    """Return [{word, lookup, hint, context, book}] from a two-column CSV.

    `word` is the untouched first column (shown on the card), `lookup` the
    reduced form used for dictionary lookup, `hint` the French translation fed
    to the LLM, and `book` the file stem as the card source.
    """
    records = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            term, hint = row[0].strip(), row[1].strip()
            if not term or not hint:
                continue
            records.append({
                "word": term,
                "lookup": headword(term),
                "hint": hint,
                "context": "",
                "book": Path(path).stem,
            })
    return records