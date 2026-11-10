"""Stages 2-3: lemmatization (simplemma) + MDX dictionary lookup (mdict-utils).

Import gotcha (CLAUDE.md): top-level `import mdict_utils` exposes nothing;
use `from mdict_utils.base.readmdict import MDX`.
"""

import html
import re
from functools import lru_cache

import simplemma
from mdict_utils.base.readmdict import MDX

_TAG_RE = re.compile(r"<[^>]+>")
_CSS_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


@lru_cache(maxsize=4096)
def lemmatize(word: str) -> str:
    """Normalize to lemma; fall back to the raw word (vocabsieve pattern)."""
    cleaned = word.strip().strip(".,;:!?\"'()[]«»")
    if not cleaned:
        return word
    try:
        return simplemma.lemmatize(cleaned, lang="de", greedy=True)
    except Exception:
        return word


def strip_html(entry: str) -> str:
    """Entry HTML -> readable plain text for the LLM prompt."""
    text = _CSS_RE.sub(" ", entry)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _separable_variants(word: str) -> list[str]:
    """'rief an' -> ['anrufen'] style candidates for dict keys (plain lemmas).

    KOReader may store the verb as it appeared in the sentence ('rief an'),
    so lemmatize the verb part and reassemble prefix + infinitive.
    """
    variants = []
    parts = word.split()
    if len(parts) == 2 and len(parts[1]) <= 4:  # plausible separable prefix
        verb = lemmatize(parts[0])
        variants.append(f"{parts[1]}{verb}")
    return variants


class DictLookup:
    """Loads both MDX dicts once; lookup falls back Langenscheidt -> Duden."""

    def __init__(self, langenscheidt_path: str, duden_path: str):
        self.dicts = {}
        for name, path in (("langenscheidt", langenscheidt_path), ("duden", duden_path)):
            entries: dict[str, str] = {}
            for key, value in MDX(path).items():
                key = key.decode("utf-8").lower()
                value = value.decode("utf-8")
                # merge duplicate headwords (vocabsieve parseMDX pattern)
                entries[key] = entries.get(key, "") + "\n" + value if key in entries else value
            self.dicts[name] = entries

    def lookup(self, word: str) -> dict[str, str]:
        """Return {dict_name: stripped_entry} for every dict that has the word.

        Tries lemma, raw, and separable variants. Both dicts are included when
        available (Langenscheidt = learner senses; Duden = citations/nuance).
        """
        candidates = [lemmatize(word), word.lower()]
        candidates += _separable_variants(word.lower())
        # Also try the word without '|' (dict keying note: antreiben, not an|treiben)
        candidates.append(word.lower().replace("|", ""))
        # Per-dict candidate set: each dict gets its own lookup without
        # cross-dict contamination (same candidate list for both dicts).
        unique = [c for c in dict.fromkeys(candidates) if c]
        hits: dict[str, str] = {}
        for name, entries in self.dicts.items():
            for cand in unique:
                if cand in entries:
                    hits[name] = strip_html(entries[cand])
                    break
        return hits
