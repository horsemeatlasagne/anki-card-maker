# Commands and output

Run commands from the project root. All modes accept the same options:

```text
python main.py {extract,generate,export} [--intype koreader|quizlet]
               [--infile PATH] [--config PATH] [--limit N]
               [--word WORD] [--dry-run] [--no-think] [--model MODEL]
               [--rpm N] [-v | --verbose]
```

Use `.venv/bin/python` instead of `python` if you followed the setup instructions.

## Input types

`--intype` selects where the words come from:

- `koreader` (default) reads `[paths].vocab_db`. Context is the sentence around the word, and there is no translation hint.
- `quizlet` reads a two-column Quizlet export CSV given with `--infile PATH`. Column 1 is the German term, column 2 a French translation. Context is empty and the French text is passed to the model as a hint.

For `quizlet`, the card `term` is the whole first column. Dictionary lookup and the cache key use a reduced headword: the first comma- or `=`-separated form, without a parenthetical note, article, or second line. For example `sich merken, er merkt sich, ...` becomes `sich merken`, and `Die Violine = Geige` becomes `Violine`. The French hint is used only to pick the matching sense: definitions and examples are still copied in German from the dictionaries. Quizlet runs use prompt version `8` so KOReader cache keys are unaffected.

## Modes

- `extract` reads the database and prints the number of selected records. Add `--verbose` to print each word, book, and context excerpt.
- `generate` extracts records, loads both dictionaries, and generates or reuses consolidated cards. It saves successful results in the cache. It does not write an export file.
- `export` runs the generation pipeline and writes the resulting cards to the configured output path. It replaces an existing output file, including when some words fail.

Generation reports per-word failures and continues. The export contains successful cards only. Check the reported failure count before importing the file.

## Options

| Option | Behavior |
| --- | --- |
| `--intype koreader\|quizlet` | Select input format. Default `koreader`. |
| `--infile PATH` | Quizlet CSV path. Required for `--intype quizlet`. |
| `--config PATH` | Read this TOML file instead of `config.toml`. |
| `--limit N` | Select the first N records after word filtering. Records follow the database word sort order. A zero value does not limit the selection. |
| `--word WORD` | Select records whose trimmed word matches `WORD`, ignoring case. |
| `--dry-run` | For `generate` or `export`, check cache membership without LLM requests. Both dictionaries still load. |
| `--no-think` | Request disabled reasoning through two provider-specific fields. The gateway may ignore them. |
| `--model MODEL` | Override the configured model for this run. Existing cache entries still apply. |
| `--rpm N` | Cap the number of LLM requests at N per rolling minute. Default `20` from `[llm].rpm`; `0` disables the cap. Only requests that actually go out are counted, so cached cards cost nothing. The flag wins over the config value. |
| `-v`, `--verbose` | Print selected records and context excerpts. |

**Do not use `export --dry-run` to preserve an existing export.** The dry run produces an empty card list, and `export` then writes that list to the output path. Use `generate --dry-run` to check the cache instead. Dry-run cache loading can also move a malformed cache aside, as described in [Pipeline and cache](architecture.md).

Examples:

```sh
.venv/bin/python main.py extract --word aufwühlen --verbose
.venv/bin/python main.py generate --word aufwühlen --dry-run
.venv/bin/python main.py generate --word aufwühlen --model dictionary-model
.venv/bin/python main.py export --limit 10
.venv/bin/python main.py export --intype quizlet --infile data/die_physiker.csv
```

## Export format

A path ending in lowercase `.csv` produces UTF-8 CSV with a header and quoted fields. Any other output path produces a UTF-8 JSON array. Both formats contain these fields:

| Field | Content |
| --- | --- |
| `term` | The trimmed word from KOReader. |
| `definition` | The synthesized card: definitions and examples for the meanings marked as relevant to the context, separated by `<br>`. In both, the target word is replaced by a bracketed blank — one underscore per character (`[______]` for `geirrt`). Dictionary definitions are usage frames that usually contain the headword, so they are redacted too, not just the examples. If no meaning is marked, it includes all meanings. The full multi-sense breakdown is dropped from the export. |
| `source` | The book title, or an empty string when no title matches. |
| `raw_llm_json` | The consolidated object serialized as a JSON string, with examples in their original, unredacted form. |

For Anki CSV import, enable **Allow HTML in fields** and map the columns to your note type. The first field is the term and the second is the definition. Review generated meanings and examples before study. The program checks the response structure but cannot guarantee the accuracy of model output.

## Troubleshooting

- **Database or table error:** Check the configured database path and the required tables and columns in [Setup](setup.md). SQLite can create an empty file if the database path does not exist and its parent exists.
- **Dictionary file error:** Check both MDX paths and file permissions. Both files are required for generation.
- **Cache or output file error:** Create the parent directories and check write permissions. Back up files before changing paths or regenerating data.
- **HTTP or network error:** Check the full endpoint URL, service availability, model name, and API key. HTTP 400 is not retried. Other supported failures receive one retry.
- **Invalid or truncated model response:** Check the service's JSON-mode support and token limit. The program retries once after invalid JSON, failed validation, or a truncated response.
- **Unexpected old meaning:** The cache key excludes context and model settings. See [Pipeline and cache](architecture.md) before regenerating.
