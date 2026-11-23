# Pipeline and cache

## Pipeline

1. `vocab.py` reads vocabulary records and joins book titles with a left join. It sorts records by the original database word. For `--intype quizlet`, `quizlet.py` instead reads a two-column CSV and reduces each German term to a dictionary headword.
2. It trims the word and context fragments. It joins the nonempty previous context, word, and next context with spaces.
3. `lookup.py` loads both MDX dictionaries into memory. It lowercases keys and combines duplicate headwords.
4. For each word, lookup tries the German lemma, the lowercase word, a possible separable-verb form, a Swiss `ss` → `ß` spelling, and the word without `|`. It returns the first match in each dictionary. It removes HTML tags and style blocks from the entries. If nothing matches, a multi-word phrase is resolved by candidate headword: entries whose lemma is a content word of the phrase are scored by how many of the phrase's tokens their text contains, and the best entry per dictionary is returned. This finds phrases the dictionaries store inside another headword's entry, for example `so tun als ob` → the `tun` entry or `jemand durchschauen` → `durchschauen`.
5. `consolidate.py` sends the word, context, and matching entries to the configured chat completions endpoint. If no entry matches, the prompt asks the model to use context alone.
6. `export.py` renders the result into note fields. The `export` mode writes CSV or JSON.

The program uses `simplemma` for German lemmatization and `mdict-utils` to read MDX files. It loads dictionary content at the start of each generation or export run.

## Model response

Prompt version `7` asks the model to merge dictionary senses and select the sense that fits the context. Both versions also handle multi-word phrases: the entries may belong to a related headword, and the prompt tells the model to use only the part of the entry that documents the phrase. They request a JSON object with `lemma`, `meanings`, `expressions`, and `chosen_meaning_for_context`.

Redaction is split between the model and the exporter, and it covers **both** card texts: definitions and examples. A Langenscheidt definition is itself a usage frame built around the headword (`etwas irgendwohin halten etwas in eine bestimmte Position bringen`), so redacting only the example left the word visible in plain sight. The model only decides **which** spans are the target word: it returns each text unchanged except that every surface form is wrapped in square brackets (`Die Polizei [entführte] den Täter.`). Deciding that requires judgement — inseparable Partizip II, nominalizations, the target part of a compound, detached separable prefixes, dictionary abbreviations like `g.` for `geisteskrank`, every content word of a multi-word phrase — and a lemma matcher (`simplemma`) was the source of leaks on exactly those cases. Prefixed derivatives (`anhalten`, `behalten` for `halten`) are different words and are not marked. The mechanical substitution then runs in Python: `export.py` replaces the text inside each `[...]` pair with one underscore per character, so `[geirrt]` becomes `[______]`. The LLM never writes underscores and never rewrites the sentence.

Redaction caches under `_REDACT_VERSION = 6`, the version that still marked example sentences word for word; definition instructions were added without bumping it, because definition texts are new keys and cannot collide, while a bump would throw away every cached example blank.

All texts of one card go in a single request, keyed by number: `{"marked": {"1": "...", "2": "..."}}`. Redaction state is cached per text and lemma, so a re-render is free. About half of the card texts genuinely contain no form of the word (paraphrased definitions, examples using a different lemma), and those come back unmarked and pass through unchanged. A batch is rejected only when nothing is marked although a text contains a form of the word.

Two guards protect the card from bad marks. A mark is accepted only if the returned text is the original with spans bracketed — the model sometimes rewrites instead of marking (`sich so benehmen,` became `sich [__] [___] als ob,` for `so tun als ob`), and such a text is left unredacted with a warning rather than filled with invented words; capitalisation differences are ignored. Dictionary texts that already contain literal square brackets (`jmdn. [durch sein Verhalten] eifersüchtig machen`) are swapped for `⟦ ⟧` before the request and restored after blanking, so they are never mistaken for marks. A failed or empty-marker response returns the texts unredacted with a warning. The `term` field keeps the full word; `expressions` and `raw_llm_json` are not redacted.

The validator checks that `lemma` and `chosen_meaning_for_context` are strings. It requires a nonempty `meanings` list. Each meaning must contain an integer `sense`, string `definition` and `example`, boolean `in_context`, and an `example_source` of `dict`, `context`, or `none`. It checks that `expressions` is a list, but it does not validate each expression. The exporter expects each expression to contain `expression` and `meaning` keys.

These checks do not establish that definitions or examples match the dictionaries. They also do not require exactly one context sense. Review the output before importing it.

The first request uses the configured temperature. On invalid output or supported network failures, the program makes at most one retry at temperature `0.0`. HTTP 400 is not retried. The client also handles code fences, some reasoning text, missing choices, and truncated responses.

Every request — consolidation, batched redaction and their retries — passes through one `RateLimiter` in `consolidate.py`, a sliding window of N timestamps that blocks until the oldest leaves the 60 s window. The window, not a token bucket, matches how providers count per minute: a bucket would allow a full burst after an idle minute. The limit is `--rpm`, then `[llm].rpm`, then 20; `0` disables it. Only requests that reach the network are counted, so cache hits cost nothing. Waiting prints a `rate limit` line to stderr.

## Cache behavior

Prompt version `8` is the Quizlet variant: it adds the French translation as a disambiguation hint and requires German-only output. The quizlet path always selects version `8` regardless of `[llm].prompt_version`, so KOReader cache keys and prompts are unchanged.

The cache is a JSON object stored at `[paths].cache`. A SHA-256 key combines the selected word, the combined dictionary text, and the prompt version. When a translation hint is present (Quizlet), it is appended to the key; KOReader keys keep the original format. The key does **not** include context, model, temperature, or other request settings. Changes to those values do not invalidate existing entries. Cached objects are returned without revalidation.

Successful generation saves the cache after each card through a temporary file and an atomic replacement. A missing cache starts empty. If the cache contains invalid JSON, the program moves it to a path ending in `.corrupt-<timestamp>` and starts with an empty cache. This can also happen during a dry run.

To regenerate entries, first back up the cache. Then select a new cache path in a separate configuration file, or remove selected entries from a copy. A new cache path causes all selected words to require new requests. Changing the model alone does not regenerate entries. Incrementing the prompt version only works if that version also exists in `PROMPTS` in `consolidate.py`.

## Module map

| File | Responsibility |
| --- | --- |
| `main.py` | Command-line parsing and pipeline orchestration. |
| `config.py` | TOML loading, defaults, and path resolution. |
| `vocab.py` | SQLite extraction and context assembly. |
| `quizlet.py` | Two-column Quizlet CSV extraction and headword reduction. |
| `lookup.py` | Lemmatization and MDX lookup. |
| `consolidate.py` | Prompts, API requests, response validation, and cache. |
| `export.py` | Note rendering, bracket-to-blank substitution in definitions and examples, and CSV or JSON export. |

The repository does not include an automated test suite or dependency manifest. Use a small selection and a separate output and cache path when checking changes. Avoid live requests unless you intend to send the input to the configured service.
