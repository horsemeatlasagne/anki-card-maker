"""CLI entry: python main.py extract|generate|export [--limit N] [--word W]"""

import argparse
import sys

import export as export_mod
import vocab
from config import load


def cmd_extract(cfg, args) -> list[dict]:
    records = vocab.extract(cfg.paths["vocab_db"])
    if args.word:
        records = [r for r in records if r["word"].lower() == args.word.lower()]
    if args.limit:
        records = records[: args.limit]
    if args.verbose:
        for r in records:
            print(f"{r['word']!r:30} [{r['book'][:40]}] {r['context'][:60]}")
        print()
    print(f"{len(records)} records")
    return records


def cmd_generate(cfg, args) -> list[dict]:
    from consolidate import Consolidator
    from lookup import DictLookup

    records = cmd_extract(cfg, argparse.Namespace(limit=args.limit, word=args.word,
                                                   dry_run=args.dry_run, verbose=args.verbose))
    dicts = DictLookup(cfg.paths["langenscheidt"], cfg.paths["duden"])
    llm_cfg = {**cfg.llm, "cache": cfg.paths["cache"],
               "thinking": not args.no_think}
    if args.model:
        llm_cfg["model"] = args.model
    cons = Consolidator(llm_cfg)

    cards = []
    failures = []
    cached = 0
    for i, rec in enumerate(records):
        hits = dicts.lookup(rec["word"])
        entries = "\n\n".join(f"=== {name} ===\n{txt}" for name, txt in hits.items())
        src = "+".join(hits) if hits else "none"
        if args.dry_run:
            if cons.is_cached(rec["word"], entries):
                cached += 1
            else:
                failures.append((rec["word"], "not cached (dry run)"))
            continue
        try:
            card = cons.consolidate(rec["word"], entries, rec["context"])
        except ValueError as e:
            failures.append((rec["word"], e))
            print(f"\r\033[K  FAILED {rec['word']}: {e}", file=sys.stderr)
            continue
        cards.append(export_mod.render_card(rec, card))
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
    p = argparse.ArgumentParser(description="KOReader vocab -> Anki flashcards")
    p.add_argument("mode", choices=["extract", "generate", "export"])
    p.add_argument("--config", default="config.toml")
    p.add_argument("--limit", type=int, help="only first N words (smoke test)")
    p.add_argument("--word", help="single word")
    p.add_argument("--dry-run", action="store_true", help="cache only; never call the LLM")
    p.add_argument("--no-think", action="store_true",
                   help="ask the gateway to disable reasoning tokens")
    p.add_argument("--model", help="override [llm].model for this run")
    p.add_argument("-v", "--verbose", action="store_true", help="also list extracted words")
    args = p.parse_args(argv)

    cfg = load(args.config)
    if args.mode == "extract":
        cmd_extract(cfg, args)
    elif args.mode == "generate":
        cmd_generate(cfg, args)
    else:
        cmd_export(cfg, args)


if __name__ == "__main__":
    main()
