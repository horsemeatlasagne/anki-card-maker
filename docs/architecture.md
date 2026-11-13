# Pipeline and cache

## Pipeline

1. `vocab.py` reads vocabulary records and joins book titles with a left join. It sorts records by the original database word.
2. It trims the word and context fragments. It joins the nonempty previous context, word, and next context with spaces.
3. `lookup.py` loads both MDX dictionaries into memory. It lowercases keys and combines duplicate headwords.
4. For each word, lookup tries the German lemma, the lowercase word, a possible separable-verb form, and the word without `|`. It returns the first match in each dictionary. It removes HTML tags and style blocks from the entries.
5. `consolidate.py` sends the word, context, and matching entries to the configured chat completions endpoint. If no entry matches, the prompt asks the model to use context alone.
6. `export.py` renders the result into note fields. The `export` mode writes CSV or JSON.

The program uses `simplemma` for German lemmatization and `mdict-utils` to read MDX files. It loads dictionary content at the start of each generation or export run.

## Model response

Prompt version `7` asks the model to merge dictionary senses and select the sense that fits the context. It requests a JSON object with `lemma`, `meanings`, `expressions`, and `chosen_meaning_for_context`.

The validator checks that `lemma` and `chosen_meaning_for_context` are strings. It requires a nonempty `meanings` list. Each meaning must contain an integer `sense`, string `definition` and `example`, boolean `in_context`, and an `example_source` of `dict`, `context`, or `none`. It checks that `expressions` is a list, but it does not validate each expression. The exporter expects each expression to contain `expression` and `meaning` keys.

These checks do not establish that definitions or examples match the dictionaries. They also do not require exactly one context sense. Review the output before importing it.

The first request uses the configured temperature. On invalid output or supported network failures, the program makes at most one retry at temperature `0.0`. HTTP 400 is not retried. The client also handles code fences, some reasoning text, missing choices, and truncated responses.

## Cache behavior

The cache is a JSON object stored at `[paths].cache`. A SHA-256 key combines the selected word, the combined dictionary text, and the prompt version. The key does **not** include context, model, temperature, or other request settings. Changes to those values do not invalidate existing entries. Cached objects are returned without revalidation.

Successful generation saves the cache after each card through a temporary file and an atomic replacement. A missing cache starts empty. If the cache contains invalid JSON, the program moves it to a path ending in `.corrupt-<timestamp>` and starts with an empty cache. This can also happen during a dry run.

To regenerate entries, first back up the cache. Then select a new cache path in a separate configuration file, or remove selected entries from a copy. A new cache path causes all selected words to require new requests. Changing the model alone does not regenerate entries. Incrementing the prompt version only works if that version also exists in `PROMPTS` in `consolidate.py`.

## Module map

| File | Responsibility |
| --- | --- |
| `main.py` | Command-line parsing and pipeline orchestration. |
| `config.py` | TOML loading, defaults, and path resolution. |
| `vocab.py` | SQLite extraction and context assembly. |
| `lookup.py` | Lemmatization and MDX lookup. |
| `consolidate.py` | Prompts, API requests, response validation, and cache. |
| `export.py` | Note rendering and CSV or JSON export. |

The repository does not include an automated test suite or dependency manifest. Use a small selection and a separate output and cache path when checking changes. Avoid live requests unless you intend to send the input to the configured service.
