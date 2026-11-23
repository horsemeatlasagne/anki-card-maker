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


def _spelling_variants(word: str) -> list[str]:
    """Swiss/uppercase spellings -> standard German: 'ausserhalb' -> 'außerhalb'."""
    if "ss" not in word:
        return []
    return [word.replace("ss", "ß")]


_STOPWORDS = frozenset(
    "sich jemand jemandem jemanden etwas jmd jmdm jmdn man er sie es ihr ihm ich "
    "du wir der die das den dem des ein eine einer eines und oder aber als ob "
    "wenn wie für zu mit in an auf aus bei von ist sind sein war waren hat haben "
    "hatte wird werden wurde wurden worden nicht nur auch so doch noch schon "
    "sehr mehr".split())


def _tokens(term: str, drop_stop: bool) -> list[str]:
    """Split a phrase/conjugation row into lemmatized tokens.

    'so tun als ob' -> ['so','tun','als','ob'] (drop_stop=False), which lets
    an entry be scored on the whole phrase; with drop_stop=True the function
    words are removed to pick candidate headwords.
    """
    tokens = []
    for raw in re.split(r"[\s,/]+", term.replace("\n", " ")):
        tok = re.sub(r"[^\wäöüßÄÖÜ]", "", raw).strip().lower()
        if not tok or (drop_stop and tok in _STOPWORDS):
            continue
        lemma = lemmatize(tok)
        if lemma not in tokens:
            tokens.append(lemma)
    return tokens


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
        # lemma -> [(dict_name, headword)] to resolve multi-word phrases such as
        # 'so tun als ob' to the headword entry that documents them.
        self._lemma_index: dict[str, list[tuple[str, str]]] = {}
        for name, entries in self.dicts.items():
            for head in entries:
                self._lemma_index.setdefault(lemmatize(head), []).append((name, head))

    def _phrase_lookup(self, word: str) -> dict[str, str]:
        """For multi-word terms, return the best entry per dictionary.

        Dictionaries key fixed expressions under one headword and only mention
        the phrase inside its text ('als' has '(so) tun, als (ob, wenn)'; 'tun'
        has 'er tut [so], als ob ...'), so an exact phrase key never matches.
        Candidate headwords are those whose lemma is a content word of the
        phrase; each is scored by how many of the phrase's tokens its text
        contains, and the best entry per dictionary is returned.
        """
        content = _tokens(word, drop_stop=True)
        all_tokens = _tokens(word, drop_stop=False)
        if not content:
            return {}
        scored: dict[str, list[tuple[int, int, str]]] = {}
        for tok in content:
            for name, head in self._lemma_index.get(tok, ()):
                text_tokens = set(_tokens(strip_html(self.dicts[name][head]), drop_stop=False))
                score = sum(1 for t in all_tokens if t in text_tokens)
                if score < 1:
                    continue
                # rank: phrase coverage, then exact (non-inflected) headword,
                # then shortest entry (most focused)
                exact = 0 if head in content else 1
                scored.setdefault(name, []).append(
                    (score, -exact, -len(self.dicts[name][head]), head))
        hits: dict[str, str] = {}
        for name, entries in scored.items():
            best_score = max(e[0] for e in entries)
            if best_score < 2 and len(content) > 1:
                continue  # scattered single hits are noise, not a phrase
            _, _, _, head = max(entries, key=lambda e: e[:3])
            hits[name] = strip_html(self.dicts[name][head])
        return hits

    def lookup(self, word: str) -> dict[str, str]:
        """Return {dict_name: stripped_entry} for every dict that has the word.

        Tries lemma, raw, and separable variants. Both dicts are included when
        available (Langenscheidt = learner senses; Duden = citations/nuance).
        Falls back to phrase resolution for multi-word terms.
        """
        candidates = [lemmatize(word), word.lower()]
        candidates += _separable_variants(word.lower())
        candidates += _spelling_variants(word.lower())
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
        return hits or self._phrase_lookup(word)
