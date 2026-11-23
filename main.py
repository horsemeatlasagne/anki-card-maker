"""CLI entry: python main.py extract|generate|export [--intype koreader|quizlet]"""

import argparse
import sys

import export as export_mod
import quizlet
import vocab
from config import load


def extract_records(cfg, args) -> list[dict]:
    """Return normalized records from the selected input type.

    Both producers emit the same shape: word (card term), lookup (dictionary
    key), hint (source-language gloss, may be empty), context, book.
    """
    if args.intype == "quizlet":
        records = quizlet.extract(args.infile)
    else:
        records = vocab.extract(cfg.paths["vocab_db"])
        for r in records:
            r["lookup"] = r["word"]
            r["hint"] = ""
    if args.word:
        records = [r for r in records if r["word"].lower() == args.word.lower()]
    if args.limit:
        records = records[: args.limit]
    if args.verbose:
        for r in records:
            hint = f" [{r['hint']}]" if r["hint"] else ""
            print(f"{r['word']!r:30} [{r['book'][:40]}]{hint} {r['context'][:60]}")
        print()
    print(f"{len(records)} records")
    return records


def cmd_generate(cfg, args) -> list[dict]:
    from consolidate import Consolidator, Redactor
    from lookup import DictLookup

    records = extract_records(cfg, argparse.Namespace(
        limit=args.limit, word=args.word, dry_run=args.dry_run,
        verbose=args.verbose, intype=args.intype, infile=args.infile))
    dicts = DictLookup(cfg.paths["langenscheidt"], cfg.paths["duden"])
    llm_cfg = {**cfg.llm, "cache": cfg.paths["cache"],
               "thinking": not args.no_think,
               # CLI flag > [llm].rpm > 20
               "rpm": args.rpm if args.rpm is not None else cfg.llm.get("rpm", 20)}
    if args.intype == "quizlet":
        # Prompt 8 adds the French-hint/German-output rules. Pin it for this
        # input type so it does not change KOReader cache keys.
        llm_cfg["prompt_version"] = 8
    if args.model:
        llm_cfg["model"] = args.model
    cons = Consolidator(llm_cfg)
    redactor = Redactor(cons)

    cards = []
    failures = []
    cached = 0
    for i, rec in enumerate(records):
        hits = dicts.lookup(rec["lookup"])
        entries = "\n\n".join(f"=== {name} ===\n{txt}" for name, txt in hits.items())
        src = "+".join(hits) if hits else "none"
        if args.dry_run:
            if cons.is_cached(rec["lookup"], entries, rec["hint"]):
                cached += 1
            else:
                failures.append((rec["word"], "not cached (dry run)"))
            continue
        try:
            card = cons.consolidate(rec["lookup"], entries, rec["context"], rec["hint"])
        except ValueError as e:
            failures.append((rec["word"], e))
            print(f"\r\033[K  FAILED {rec['word']}: {e}", file=sys.stderr)
            continue
        cards.append(export_mod.render_card(rec, card, redactor.redact_many))
        # single in-place progress line instead of one line per word
        print(f"\r\033[K[{i+1}/{len(records)}] {rec['word']} (dict: {src}) ok",
              end="", flush=True)
        cons._save_cache()  # persist every word so re-runs stay cheap
    print()
    if args.dry_run:
        print(f"{cached} cached, {len(failures)} missing (no LLM calls made)")
        return []
    for word, e in failures:
        print(f"FAILED {word}: {e}", file=sys.stderr)
    print(f"{len(cards)} cards generated, {len(failures)} failed")
    return cards


def cmd_export(cfg, args) -> None:
    cards = cmd_generate(cfg, args)
    if cfg.paths["output"].endswith(".csv"):
        export_mod.export_csv(cards, cfg.paths["output"])
    else:
        export_mod.export_json(cards, cfg.paths["output"])
    print(f"exported to {cfg.paths['output']}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Vocab source -> German Anki flashcards")
    p.add_argument("mode", choices=["extract", "generate", "export"])
    p.add_argument("--intype", choices=["koreader", "quizlet"], default="koreader",
                   help="input format: KOReader DB (default) or Quizlet CSV")
    p.add_argument("--infile", help="Quizlet CSV path (required for --intype quizlet)")
    p.add_argument("--config", default="config.toml")
    p.add_argument("--limit", type=int, help="only first N words (smoke test)")
    p.add_argument("--word", help="single word")
    p.add_argument("--dry-run", action="store_true", help="cache only; never call the LLM")
    p.add_argument("--no-think", action="store_true",
                   help="ask the gateway to disable reasoning tokens")
    p.add_argument("--model", help="override [llm].model for this run")
    p.add_argument("--rpm", type=int, default=None,
                   help="max LLM requests per minute (default 20, 0 = unlimited)")
    p.add_argument("-v", "--verbose", action="store_true", help="also list extracted words")
    args = p.parse_args(argv)
    if args.intype == "quizlet" and not args.infile:
        p.error("--intype quizlet requires --infile PATH")

    cfg = load(args.config)
    if args.mode == "extract":
        extract_records(cfg, args)
    elif args.mode == "generate":
        cmd_generate(cfg, args)
    else:
        cmd_export(cfg, args)


if __name__ == "__main__":
    main()
