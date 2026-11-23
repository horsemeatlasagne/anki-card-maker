"""Config loading: CLI flag > config.toml > built-in defaults (plan: Configuration)."""

import tomllib
from pathlib import Path

_DEFAULTS = {
    "paths": {
        "vocab_db": "data/vocabulary_builder.sqlite3",
        "langenscheidt": "data/dicts/de-de/Langenscheidt Großwörterbuch Deutsch als Fremdsprache (MDX)/Langenscheidt Großwörterbuch Deutsch als Fremdsprache.mdx",
        "duden": "data/dicts/de-de/Duden Band 10 - Das Große Wörterbuch der deutschen Sprache.mdx",
        "output": "out/cards.json",
        "cache": "out/llm_cache.json",
    },
    "llm": {
        "base_url": "http://localhost:8090/v1/chat/completions",
        "model": "claude-haiku-4-5-20251001",
        "api_key": "",  # prefer env OPENAI_API_KEY, overridden by config if local
        "temperature": 0.2,
        "max_completion_tokens": 4000,
        "prompt_version": 7,
        "rpm": 20,  # LLM requests per minute; 0 disables the cap
    },
}


class Config:
    """Immutable view of merged config. Modules receive this; never parse files."""

    def __init__(self, data: dict):
        merged = {**_DEFAULTS}
        for section in ("paths", "llm"):
            merged[section].update(data.get(section, {}))
        self.paths = merged["paths"]
        self.llm = merged["llm"]

    def resolve_paths(self, base: Path) -> None:
        """Make relative paths absolute against the project root."""
        self.paths = {k: str(Path(v) if Path(v).is_absolute() else base / v)
                      for k, v in self.paths.items()}


def load(path: str | Path | None = None) -> Config:
    file_data = {}
    if path is not None:
        with open(path, "rb") as f:
            file_data = tomllib.load(f)
    cfg = Config(file_data)
    cfg.resolve_paths(Path(__file__).parent)
    return cfg
