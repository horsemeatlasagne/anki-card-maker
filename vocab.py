"""Stage 1: extract (word, context, book) records from KOReader vocab DB."""

import sqlite3


def extract(db_path: str) -> list[dict]:
    """Return [{word, context, book}] joined from vocabulary + title.

    Context = prev_context + word + next_context reassembled (vocabsieve
    KoreaderVocabImporter.py:66-70 pattern), not separate fragments.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT v.word, v.prev_context, v.next_context, t.name AS book
           FROM vocabulary v LEFT JOIN title t ON v.title_id = t.id
           ORDER BY v.word"""
    ).fetchall()
    con.close()
    records = []
    for r in rows:
        prev = (r["prev_context"] or "").strip()
        nxt = (r["next_context"] or "").strip()
        word = r["word"]
        # Reassemble: prev + word + next, like vocabsieve does.
        parts = [p for p in (prev, word, nxt) if p]
        records.append({
            "word": word,
            "context": " ".join(parts),
            "book": r["book"] or "",
        })
    return records
