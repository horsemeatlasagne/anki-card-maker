# Setup and configuration

## Install

Python 3.11 or later supplies `tomllib`, which reads the configuration file. Create a virtual environment and install the two external packages:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install simplemma mdict-utils
mkdir -p out
```

The project has no dependency lock file. The command installs the package versions available at that time.

## Supply input files

Copy your KOReader vocabulary database to `data/vocabulary_builder.sqlite3`, or configure another path. The program reads the `vocabulary` and `title` tables. It requires `word`, `prev_context`, `next_context`, and `title_id` in `vocabulary`, plus `id` and `name` in `title`.

Supply both MDX files configured in `[paths]`. The program opens both dictionaries for `generate` and `export`, even when one dictionary has no entry for a word. The Langenscheidt MDD resource file is not read by this program. The dictionaries are separate, licensed resources. Check their terms before obtaining or using them.

## Configure the service

Edit `config.toml` or provide another file with `--config PATH`. The selected TOML file must exist. The command resolves relative input, output, and cache paths against the project directory, not the configuration file directory. It resolves the `--config` path itself against the current working directory.

The checked-in configuration contains these settings:

| Section | Key | Purpose |
| --- | --- | --- |
| `paths` | `vocab_db` | KOReader SQLite database path. |
| `paths` | `langenscheidt` | Langenscheidt MDX path. |
| `paths` | `duden` | Duden MDX path. |
| `paths` | `output` | Export path. A `.csv` suffix selects CSV. Other suffixes select JSON. |
| `paths` | `cache` | JSON cache path. |
| `llm` | `base_url` | Full chat completions URL, not just the server root. |
| `llm` | `model` | Model name sent to the service. |
| `llm` | `temperature` | Temperature for the first request. A retry uses `0.0`. |
| `llm` | `max_completion_tokens` | Maximum completion tokens requested. |
| `llm` | `prompt_version` | Prompt identifier and part of the cache key. The current code defines version `7`. |
| `llm` | `api_key` | Optional key. A nonempty value takes precedence over `OPENAI_API_KEY`. |

Missing keys use the defaults in `config.py`. The built-in prompt version is `1`, but the current code only defines prompt version `7`. Set `prompt_version = 7` when using an alternate configuration.

The program reads `OPENAI_API_KEY` from the environment. It also reads simple `KEY=value` lines from `.env.local` in the current working directory. Existing environment variables take precedence over that file. This parser does not interpret shell quoting or `export` syntax. Do not commit keys or share them in configuration examples.

The default URL points to a local gateway. Start a compatible service separately and configure its model name. The request uses JSON mode and `max_completion_tokens`. The service must support the request format for generation to work.

## Privacy and storage

For each uncached word, the service receives the word, reading context, and available dictionary text. Check the service's privacy terms and the dictionary license before using a remote endpoint. The cache can contain dictionary-derived text and generated content. The export also contains reading context and raw model output. Protect these files as appropriate.

The program does not create parent directories for the output or cache. Create them before generating or exporting. The output and cache paths must not point to files you need to preserve without a backup.
