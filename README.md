# KOReader Card Maker

Create German flashcards from a KOReader vocabulary database. The program looks up words in two MDX dictionaries, asks an OpenAI-compatible service to consolidate meanings, and exports notes for Anki.

## Requirements

- Python 3.11 or later.
- The Python packages `simplemma` and `mdict-utils`.
- A KOReader `vocabulary_builder.sqlite3` database.
- Langenscheidt and Duden MDX dictionary files.
- An OpenAI-compatible chat completions endpoint for uncached words.

The database, dictionaries, and generated files are not included in the repository. Obtain dictionary files separately and observe their license terms.

## Quick start

Run these commands from the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install simplemma mdict-utils
mkdir -p out
```

Place your database and dictionaries at the paths in `config.toml`, or change those paths. Set `[llm].base_url` to the full chat completions endpoint and set `[llm].model` to a model that endpoint accepts. If the endpoint needs a key, set `OPENAI_API_KEY` in your environment or in `.env.local`:

```text
OPENAI_API_KEY=your-key
```

Inspect the input before generating cards:

```sh
.venv/bin/python main.py extract --limit 5 --verbose
.venv/bin/python main.py generate --limit 5 --dry-run
.venv/bin/python main.py export --limit 5
```

The last command can send dictionary entries and reading context to the configured service. It can also incur service charges. It writes the configured output file and updates the cache. An export replaces the output file, so choose a safe output path first.

## Quizlet input

The default input is a KOReader database. To turn a Quizlet export into German-to-German cards, pass a two-column CSV (German term, French translation):

```sh
.venv/bin/python main.py export --intype quizlet --infile data/die_physiker.csv
```

The French column only hints which sense to use; definitions and examples stay German. See [Commands and output](docs/usage.md#input-types).

For CSV import in Anki, select **File → Import** and enable **Allow HTML in fields**. Map the CSV columns to fields in your note type. The first two columns are `term` and `definition`.

## Documentation

- [Setup and configuration](docs/setup.md)
- [Commands and output](docs/usage.md)
- [Pipeline and cache](docs/architecture.md)
