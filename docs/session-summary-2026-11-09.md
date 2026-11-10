# Session summary & lessons learned (2026-11-07 → 11-09)

Complete record of the implementation session for context compaction.
Everything below was verified against the live code/data during the session.

## What was built

Full pipeline per `plan/plan.md`, flat scripts (KISS, no framework):

- `config.py` — stdlib `tomllib` loader; precedence CLI > `config.toml` > defaults;
  all modules receive a `Config` object, never parse files/env themselves.
- `vocab.py` — Stage 1: reads `vocabulary`+`title` tables; reassembles
  `prev_context + word + next_context` into one sentence (vocabsieve pattern).
  1,201 words / 8 books.
- `lookup.py` — Stages 2-3: simplemma lemmatization (greedy=True, lru_cache,
  fallback to raw word) + MDX lookup via
  `from mdict_utils.base.readmdict import MDX`. `DictLookup.lookup(word)`
  returns `{dict_name: stripped_text}` for **both** dictionaries
  (Langenscheidt AND Duden — user explicitly wanted both, not fallback-only).
  Separable verbs handled: `rief an` → lemmatize verb part → `anrufen`.
- `consolidate.py` — Stage 4: OpenAI-compatible chat completions via urllib
  (no SDK). PROMPTS dict keyed by `prompt_version` (currently **7**).
  JSON validation (`_validate`), retry once at temp 0, cache keyed
  `sha256(word|entry|prompt_version|model)` persisted to `out/llm_cache.json`
  (saved after EVERY word so re-runs are free and resumable).
- `export.py` — Stage 5: `render_card()` → Anki note fields
  (term, definition, context, word type, notes, source, raw_llm_json);
  `export_csv()` (QUOTE_ALL, header maps to note fields) and `export_json()`.
- `main.py` — CLI: `extract|generate|export` + `--config --limit --word --dry-run`.
- `ab_test.py` — A/B harness: same N words through several models, writes
  human-readable per-model markdown to `out/ab/*.md` + shared `out/ab/cache.json`.
- `config.toml` — CURRENT: model=minimax-m3.1-flash, temperature=0.2,
  max_completion_tokens=8000, prompt_version=7, output=out/cards.csv.
- `.env.local` (gitignored) — `OPENAI_API_KEY=...`, loaded by
  `Consolidator._load_dotenv()` (setdefault, no shell history leak).
- `docs/` — openai-chat-completions-create.md (full official reference),
  openai-structured-outputs.md, simplemma-usage.html, mdict-utils-readme.md,
  openai-chat-completions-notes.md (working digest).

## Environment facts

- Python 3.15.2 (system + `.venv`), simplemma 2.0.0, mdict-utils 1.3.14.
- LLM gateway: **AxonHub** at `http://localhost:8090` (user-run, admin UI).
- Dict paths contain spaces/umlauts — quote in shell, fine in config.
- `Aberglauben` is NOT a Langenscheidt key (acc./dat. of Sg.-only noun) but IS
  a Duden key → raw-word fallback matters; simplemma deliberately won't
  lemmatize it. Plural→singular otherwise works (Wörter→Wort, Häuser→Haus...).

## Gateway quirks (CRITICAL — cost hours)

1. **User-Agent blocking**: bare urllib UA (and even short "Mozilla/5.0")
   → HTTP 403 on inference POST while `/v1/models` GET succeeds. REQUIRED UA:
   `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36`
   (set in `consolidate.py`). curl without UA also 403s.
2. **`reasoning_effort:"none"` and `chat_template_kwargs.enable_thinking:false`
   are accepted but IGNORED** — every model under this key is a reasoning
   model; you cannot disable thinking server-side.
3. **Models observed**: gemma-4-26b-a4b-it, step-5-preview, minimax-m3.1-flash,
   glm-4.7-flash (later 422 "model not found" — channel removed/renamed!),
   deepseek-r1-distill-qwen-32b (502 down), mistral-large-4 (300s timeouts,
   unusable). Model list CHANGES between sessions — don't trust cached lists.
4. **Channels can go down mid-run** (503 "No available channel", 524s).
   Retry later; monitor with a curl-until-200 loop.
5. HTTP 400 on json_schema response_format for unsupported models → we use
   `response_format: {"type":"json_object"}` everywhere.

## Model comparison results (A/B, 5 words each)

| model | verdict |
|---|---|
| **minimax-m3.1-flash** | ✅ CHOSEN: 5/5 in 69s (~14s/word); correct sense picks; light reasoning |
| gemma-4-26b-a4b-it | works, correct, but ~1 min/word — too slow (user decision) |
| step-5-preview | works, correct, but expensive (user decision) |
| glm-4.7-flash | failed sense-selection in subagent test AND later vanished from gateway |
| claude-haiku-4-5 | excellent quality (reserved by user for later "when stable") |

## Prompt evolution (v1→v7) — what each fix was for

- v2: "hard examples" → produced LLM slop ("unkontrollierbare Dynamik");
  user rejected. LLM-written German is reliably unidiomatic.
- v4: verbatim dict examples + `example_source` provenance field.
- v5: examples MUST be verbatim from dict (either one), never invented.
- v6: cross-dictionary sense DEDUPLICATION (Langenscheidt senses are the
  backbone, Duden fine-splits merge in — Abwehr went 10→5 senses);
  STRICT example rule BACKFIRED: 35/60 senses got NO example (model feared
  fragments); expressions rule banned declension-form spam
  ("der Abgeordnete: der Abgeordnete").
- v7 (current): example rule "STRICT but GENEROUS" — any real usage instance
  counts (Langenscheidt sentences preferred, Duden citation phrases after ':'
  explicitly allowed, copying definition's citation verbatim encouraged);
  empty example only if dict truly has nothing (`example_source: "none"`).
  **v7 output CSV existed but was NOT yet quality-reviewed by user.**
- Rendering: ticks/crosses (✓/✗) and ⚠ flags REMOVED from definition field
  (user: "UNACCEPTABLE" in CSV) — definition = `N. definition — example`
  lines; context-relevant sense lives in `notes` field.

## Bugs found & fixed (pattern: silent data corruption)

1. `lookup()` cross-dict seen-set bug: `seen.update()` ran per-dict AFTER the
   candidate loop → Duden candidates pre-marked seen → Duden silently never
   hit. Only Langenscheidt appeared. Fix: shared `unique` candidate list,
   per-dict loop.
2. `str.split("")` crashes with ValueError (empty separator) — happened when
   the `` tag literal got mangled in file writes TWICE (tags eaten by tooling).
   Fix: build tags via concatenation `"<" + "think" + ">"`.
3. `reasoning_content` fallback: Gemma-4 known failure — JSON lands in
   reasoning_content with empty content (and empty content + finish=length
   when budget too small). `_call()` falls back to reasoning_content.
4. Reasoning budget: model was copying entire dict entries into its reasoning
   trace (12.8k chars observed) → `finish_reason=length`, empty JSON.
   Fixes: prompt "Do NOT repeat or restate the dictionary entries in your
   reasoning — reason briefly" + max_completion_tokens 4000→8000.
5. Anki import needs **Allow HTML in fields** (definitions use `<br>`).

## Process lessons learned (user-driven)

1. **Config file over CLI flags** for stable settings; CLI only for
   per-run (mode, --limit, --word). Secrets via env/gitignored file, never
   argv, never committed files (permission classifier enforced this too).
2. **Cache everything, key by (word, dict-content, prompt_version, model)**
   — prompt/model changes invalidate deliberately; enables free re-runs and
   model A/B on identical inputs.
3. **User wants to be in the decision loop**: sample cards written to
   `out/` as human-readable files for review before big batches.
4. **No LLM-invented German.** Dict text verbatim only: definitions copied,
   examples copied (either dict). "Hard sentences" come from Duden citations,
   not the model.
5. **Flashcard ≠ dictionary page**: dedupe senses across dicts; cap sense
   count (~2-5); expressions only genuine idioms; no declension spam.
6. **Context sentence is sacred**: real book context always on the card;
   `chosen_meaning_for_context` marks which sense fits it.
7. Background runs + user notifications for long LLM batches; per-word cache
   persistence makes anything resumable.
8. When a tool call is denied by the permission classifier, find the safer
   path (e.g. Write tool instead of shell for credentials) — and when in
   doubt, ASK the user (AskUserQuestion) rather than work around.

## Current state / next steps

- 20-word prod test done on minimax v5 (pre-v6 quality fixes);
  v7 regeneration completed 2026-11-09 but **user review pending** —
  `out/cards.csv` ready for Anki import test (File→Import, allow HTML,
  term→field1, definition→field2, Vanilla Study note type).
- After user approves v7 quality: full 1,201-word run (~14s/word ≈ 4.5-5h,
  resumable via cache; expect some failures to retry).
- Export format decision recorded: CSV for import (user tests), AnkiConnect
  direct push still possible later (vocabsieve pattern).
- Old-orthography duplicates exist in data (Anlaß/Anlass) — no dict hit for
  `Anlaß`; potential future improvement (post-2006 spelling normalization).
