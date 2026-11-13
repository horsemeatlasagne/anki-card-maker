# Commands and output

Run commands from the project root. All modes accept the same options:

```text
python main.py {extract,generate,export} [--config PATH] [--limit N]
               [--word WORD] [--dry-run] [--no-think] [--model MODEL]
               [-v | --verbose]
```

Use `.venv/bin/python` instead of `python` if you followed the setup instructions.

## Modes

- `extract` reads the database and prints the number of selected records. Add `--verbose` to print each word, book, and context excerpt.
- `generate` extracts records, loads both dictionaries, and generates or reuses consolidated cards. It saves successful results in the cache. It does not write an export file.
- `export` runs the generation pipeline and writes the resulting cards to the configured output path. It replaces an existing output file, including when some words fail.

Generation reports per-word failures and continues. The export contains successful cards only. Check the reported failure count before importing the file.

## Options

| Option | Behavior |
| --- | --- |
| `--config PATH` | Read this TOML file instead of `config.toml`. |
| `--limit N` | Select the first N records after word filtering. Records follow the database word sort order. A zero value does not limit the selection. |
| `--word WORD` | Select records whose trimmed word matches `WORD`, ignoring case. |
| `--dry-run` | For `generate` or `export`, check cache membership without LLM requests. Both dictionaries still load. |
| `--no-think` | Request disabled reasoning through two provider-specific fields. The gateway may ignore them. |
| `--model MODEL` | Override the configured model for this run. Existing cache entries still apply. |
| `-v`, `--verbose` | Print selected records and context excerpts. |

**Do not use `export --dry-run` to preserve an existing export.** The dry run produces an empty card list, and `export` then writes that list to the output path. Use `generate --dry-run` to check the cache instead. Dry-run cache loading can also move a malformed cache aside, as described in [Pipeline and cache](architecture.md).

Examples:

```sh
.venv/bin/python main.py extract --word aufwühlen --verbose
.venv/bin/python main.py generate --word aufwühlen --dry-run
.venv/bin/python main.py generate --word aufwühlen --model dictionary-model
.venv/bin/python main.py export --limit 10
```

## Export format

A path ending in lowercase `.csv` produces UTF-8 CSV with a header and quoted fields. Any other output path produces a UTF-8 JSON array. Both formats contain these fields:

| Field | Content |
| --- | --- |
| `term` | The trimmed word from KOReader. |
| `definition` | Numbered meanings, examples, and expressions separated by HTML `<br>` tags. |
| `context` | The previous context, word, and next context joined with spaces. |
| `word type` | An empty string. |
| `card` | Definitions and examples for meanings marked as relevant to the context. If none are marked, it includes all meanings. |
| `source` | The book title, or an empty string when no title matches. |
| `raw_llm_json` | The consolidated object serialized as a JSON string. |

For Anki CSV import, enable **Allow HTML in fields** and map the columns to your note type. The first field is the term and the second is the definition. Review generated meanings and examples before study. The program checks the response structure but cannot guarantee the accuracy of model output.

## Troubleshooting

- **Database or table error:** Check the configured database path and the required tables and columns in [Setup](setup.md). SQLite can create an empty file if the database path does not exist and its parent exists.
- **Dictionary file error:** Check both MDX paths and file permissions. Both files are required for generation.
- **Cache or output file error:** Create the parent directories and check write permissions. Back up files before changing paths or regenerating data.
- **HTTP or network error:** Check the full endpoint URL, service availability, model name, and API key. HTTP 400 is not retried. Other supported failures receive one retry.
- **Invalid or truncated model response:** Check the service's JSON-mode support and token limit. The program retries once after invalid JSON, failed validation, or a truncated response.
- **Unexpected old meaning:** The cache key excludes context and model settings. See [Pipeline and cache](architecture.md) before regenerating.
