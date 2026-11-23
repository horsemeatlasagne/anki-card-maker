"""Stage 5: export consolidated cards as Anki-ready notes (Vanilla Study reads
plain notes: field 1 = term, field 2 = definition — anki_addon/539864050)."""

import json


def render_card(record: dict, card: dict, redact_many) -> dict:
    """Record + validated LLM JSON -> Anki note fields (plan Stage 5).

    One content field: the synthesized card (context-relevant senses +
    examples) is emitted as `definition`. Both parts are redacted, because a
    Langenscheidt definition is a usage frame that usually contains the
    headword itself ('etwas irgendwohin halten ...'). All texts of the card go
    through one `redact_many(texts, lemma)` call; the caller passes an
    LLM-backed redactor because lemma matching misses inseparable Partizip II,
    nominalizations and compounds.
    """
    meanings = card["meanings"]
    lemma = card.get("lemma") or record["word"]
    in_ctx = [m for m in meanings if m["in_context"]] or meanings
    ctx_senses = {m["sense"] for m in in_ctx}
    selected = [m for m in meanings if m["sense"] in ctx_senses]
    texts = []
    for m in selected:
        texts.append(m["definition"])
        if m.get("example"):
            texts.append(m["example"])
    texts = redact_many(texts, lemma)
    ctx_defs = []
    for m in selected:
        line = texts.pop(0)
        if m.get("example"):
            line += f" — {texts.pop(0)}"
        ctx_defs.append(line)
    return {
        "term": record["word"],
        "definition": "<br>".join(ctx_defs),
        "source": record["book"],
        "raw_llm_json": json.dumps(card, ensure_ascii=False),
    }


def export_json(cards: list[dict], out_path: str) -> None:
    """Write notes as JSON (AnkiConnect import handled later / or direct API)."""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=1)


def export_csv(cards: list[dict], out_path: str) -> None:
    """Anki text import file: header names map to note fields on import
    (Anki: File > Import, 'Allow HTML in fields' ON; field 1 = term,
    field 2 = definition per Vanilla Study)."""
    import csv
    fields = ["term", "definition", "source", "raw_llm_json"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=",", quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(cards)
