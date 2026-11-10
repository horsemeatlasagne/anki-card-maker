"""Stage 5: export consolidated cards as Anki-ready notes (Vanilla Study reads
plain notes: field 1 = term, field 2 = definition — anki_addon/539864050)."""

import json


def render_card(record: dict, card: dict) -> dict:
    """Record + validated LLM JSON -> Anki note fields (plan Stage 5)."""
    meanings = card["meanings"]
    in_ctx = [m for m in meanings if m["in_context"]] or meanings
    def_lines = []
    for m in meanings:
        line = f"{m['sense']}. {m['definition']}"
        if m.get("example"):
            line += f" — {m['example']}"
        def_lines.append(line)
    for e in card.get("expressions", []):
        def_lines.append(f"• {e['expression']}: {e['meaning']}")
    # "card" = context-related sense(s): definition + example (Vanilla Study).
    ctx_defs = []
    ctx_senses = {m["sense"] for m in in_ctx}
    for m in meanings:
        if m["sense"] in ctx_senses:
            line = f"{m['definition']}"
            if m.get("example"):
                line += f" — {m['example']}"
            ctx_defs.append(line)
    return {
        "term": record["word"],
        "definition": "<br>".join(def_lines),
        "context": record["context"],
        "word type": "",
        "card": "<br>".join(ctx_defs),
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
    fields = ["term", "definition", "context", "word type", "card", "source", "raw_llm_json"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=",", quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(cards)
