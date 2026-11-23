"""Stage 4: LLM consolidation via OpenAI-compatible chat completions.

Reference: docs/vendor/openai-chat-completions-create.md + docs/vendor/openai-chat-completions-notes.md
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import deque

import simplemma

PROMPTS = {
    7: {
        "system": (
            "You are a German lexicography assistant creating flashcards for a "
            "advanced German learner. You receive dictionary entries for one "
            "German word (possibly from several dictionaries, marked === name "
            "===; Langenscheidt = learner senses with examples, Duden = "
            "meanings with literary citations) and the sentence context where "
            "the user encountered it while reading. When the word is a "
            "multi-word phrase ('so tun als ob'), the entries may belong to a "
            "related headword and only document the phrase inside their text; "
            "use that part of the entry and do not offer senses of the "
            "headword that the phrase does not share. Consolidate ALL senses and "
            "common expressions from ALL provided dictionaries into a single "
            "JSON object with exactly this schema:\n"
            '{"lemma": string, "meanings": [{"sense": int, "definition": string '
            '(German, copied from dictionary), "example": string (full German '
            'sentence from the dictionary, or "" if none exists), '
            '"example_source": "dict" | "none", '
            '"in_context": bool (does this sense fit the given context?)}], '
            '"expressions": [{"expression": string, "meaning": string}], '
            '"chosen_meaning_for_context": string}\n'
            "Rules: merge duplicate senses ACROSS dictionaries — Langenscheidt's "
            "learner-graded sense list is the backbone; map each Duden "
            "fine-grained sense onto a Langenscheidt sense instead of listing "
            "both. If a Duden sense has no Langenscheidt counterpart, append it. "
            "The result should list each DISTINCT meaning exactly once (typically "
            "2-5 senses, not one line per dictionary). Copy definitions VERBATIM "
            "from whichever dictionary you took the sense from. Mark exactly one "
            "sense as in_context=true when possible; if no dictionary entry was "
            "provided, derive the meaning from the context alone.\n"
            "Example field — STRICT but GENEROUS: every meaning SHOULD have an "
            "example taken VERBATIM from the provided dictionary entries — "
            "prefer Langenscheidt's example sentences (italic sentences after "
            "the definition); Duden usage citations (the phrases after ':' "
            "inside the definition, e.g. 'die A. wurde vernichtet') also count "
            "as examples when they show the word in real use. What counts: any "
            "real usage instance containing the word. What does NOT count: "
            "naked collocation labels like 'ein Abgeordneter' with no "
            "predicate, or the definition's own abstract gloss. Only if the "
            "dictionary truly shows no usage instance for that sense, set "
            "\"example\": \"\" and \"example_source\": \"none\". Never invent "
            "or modify sentences — copying the definition's citation phrase "
            "verbatim is allowed and encouraged.\n"
            "Expressions — STRICT: list only genuine idioms or fixed "
            "collocations that ADD meaning (e.g. 'jemandem etwas abschwören'). "
            "EXCLUDE: inflected forms of the word itself ('der Abgeordnete', "
            "'dem Abgeordneten'), derivative words already covered by a sense "
            "('abergläubisch' belongs as an expression only if its meaning "
            "isn't derivable), and entries whose meaning equals the expression "
            "itself. Do NOT repeat or restate the "
            "dictionary entries in your reasoning — reason briefly over the "
            "senses only (a few lines), then emit the JSON. Return ONLY the "
            "JSON object — no markdown code fences, no prose before or after. "
            "no other text."
        ),
        "user": "Dictionary entries (may be empty):\n{entry}\n\nWord: {word}\nContext: {context}",
    },
    8: {
        "system": (
            "You are a German lexicography assistant creating flashcards for an "
            "advanced German learner. You receive dictionary entries for one "
            "German word (possibly from several dictionaries, marked === name "
            "===; Langenscheidt = learner senses with examples, Duden = "
            "meanings with literary citations) and a French translation the "
            "learner recorded for that word. The learner wants a GERMAN-to-GERMAN "
            "card: every definition and example you output MUST be in German. "
            "The French line is only a hint to disambiguate which sense is "
            "meant; never copy French into the output. When the word is a "
            "multi-word phrase ('so tun als ob'), the entries may belong to a "
            "related headword and only document the phrase inside their text; "
            "use that part of the entry and do not offer senses of the "
            "headword that the phrase does not share. Consolidate ALL senses "
            "and common expressions from ALL provided dictionaries into a "
            "single JSON object with exactly this schema:\n"
            '{"lemma": string, "meanings": [{"sense": int, "definition": string '
            '(German, copied from dictionary), "example": string (full German '
            'sentence from the dictionary, or "" if none exists), '
            '"example_source": "dict" | "none", '
            '"in_context": bool (does this sense match the French hint?)}], '
            '"expressions": [{"expression": string, "meaning": string}], '
            '"chosen_meaning_for_context": string}\n'
            "Rules: merge duplicate senses ACROSS dictionaries — Langenscheidt's "
            "learner-graded sense list is the backbone; map each Duden "
            "fine-grained sense onto a Langenscheidt sense instead of listing "
            "both. If a Duden sense has no Langenscheidt counterpart, append it. "
            "The result should list each DISTINCT meaning exactly once (typically "
            "2-5 senses, not one line per dictionary). Copy definitions VERBATIM "
            "from whichever dictionary you took the sense from. Mark as "
            "in_context=true the sense(s) matching the French hint; mark exactly "
            "one sense when possible, and if the hint is empty or no dictionary "
            "entry was provided, derive the meaning from the hint alone.\n"
            "Example field — STRICT but GENEROUS: every meaning SHOULD have an "
            "example taken VERBATIM from the provided dictionary entries — "
            "prefer Langenscheidt's example sentences (italic sentences after "
            "the definition); Duden usage citations (the phrases after ':' "
            "inside the definition, e.g. 'die A. wurde vernichtet') also count "
            "as examples when they show the word in real use. What counts: any "
            "real usage instance containing the word. What does NOT count: "
            "naked collocation labels like 'ein Abgeordneter' with no "
            "predicate, or the definition's own abstract gloss. Only if the "
            "dictionary truly shows no usage instance for that sense, set "
            "\"example\": \"\" and \"example_source\": \"none\". Never invent "
            "or modify sentences — copying the definition's citation phrase "
            "verbatim is allowed and encouraged.\n"
            "Expressions — STRICT: list only genuine idioms or fixed "
            "collocations that ADD meaning (e.g. 'jemandem etwas abschwören'). "
            "EXCLUDE: inflected forms of the word itself ('der Abgeordnete', "
            "'dem Abgeordneten'), derivative words already covered by a sense "
            "('abergläubisch' belongs as an expression only if its meaning "
            "isn't derivable), and entries whose meaning equals the expression "
            "itself. Do NOT repeat or restate the "
            "dictionary entries in your reasoning — reason briefly over the "
            "senses only (a few lines), then emit the JSON. Return ONLY the "
            "JSON object — no markdown code fences, no prose before or after. "
            "no other text."
        ),
        "user": "Dictionary entries (may be empty):\n{entry}\n\nWord: {word}\n"
                "French hint (may be empty): {hint}\nContext: {context}",
    },
}

VALIDATION = "Output JSON must have: lemma (str), non-empty meanings[] with sense:int, definition:str, example:str, in_context:bool, expressions[] (may be empty), chosen_meaning_for_context:str."

# --- Card text redaction -----------------------------------------------------
# Division of labour: the model only marks WHICH spans are the word, by
# wrapping each form in square brackets; Python turns every marked span into
# one underscore per character. Deciding what is "the word" needs judgement
# (Partizip II of inseparable verbs, nominalizations, compounds, detached
# prefixes, abbreviations like 'g.'), which a lemma matcher got wrong; the
# substitution itself is purely mechanical and stays in Python.
#
# Both card texts go through this: examples and definitions. A Langenscheidt
# definition is itself a usage frame built around the headword
# ('etwas irgendwohin halten etwas in eine bestimmte Position ... bringen'), so
# redacting only the example left the target word visible in plain sight.

# Deliberately still 6: prompt v6 marked example sentences, and this prompt
# does the same for them — only the definition instructions are new. Bumping
# the version would invalidate every cached example blank and pay for it
# again. Definition texts are new keys, so they cannot collide with old ones.
_REDACT_VERSION = 6

REDACT_SYSTEM = (
    "You mark one German word in numbered dictionary texts that describe that "
    "word — example sentences and definitions. An advanced German learner must "
    "still be able to read each text, but must not see the word, so every form "
    "of the word must be marked and nothing else may change.\n"
    "Wrap each form in square brackets: 'Die Polizei [entführte] den Täter.' "
    "Change nothing else — same wording, same word order, same punctuation, "
    "same capitalisation. Punctuation directly after a marked form stays "
    "outside the closing bracket ('Sie hat [geirrt].'). Never write "
    "underscores; Python replaces the bracketed text with blanks.\n"
    "Definitions are grammatical frames rather than sentences ('etwas "
    "irgendwohin halten etwas in eine bestimmte Position bringen', 'sich "
    "(mit/in etwas) irren, etwas Falsches für wahr halten') and often contain "
    "the word more than once — mark every occurrence in them, not only the "
    "first or last.\n"
    "What counts as the word: inflections ('entführt', 'verurteilt'), "
    "Partizip II, nominalizations ('Verurteilung'), the target part of a "
    "compound (target 'Begräbnis' in '[Leichenbegräbnis]' — mark the whole "
    "compound), abbreviations ('[g.]' for 'geisteskrank'), detached separable "
    "prefixes ('[treibt] ... [an]' for 'antreiben'), and every content word of "
    "a multi-word phrase ('so [tun] als ob'). For a phrase a text may contain "
    "only one of its words, without the rest of the phrase: 'so tun als ob' in "
    "'Er [tut] sehr selbstsicher' — mark that word.\n"
    "What does not count: words that are merely related in meaning, and "
    "prefixed derivatives, which are different words ('anhalten', 'behalten', "
    "'verhalten' for 'halten'; 'Leichenbegräbnis' is a compound, not a "
    "derivative). A text that contains no form of the word comes back "
    "unchanged — never mark the whole text.\n"
    "Return only the JSON object {\"marked\": {\"1\": string, \"2\": string, "
    "...}} with one entry per numbered text, using the same numbers. Do not "
    "merge, split, reorder or omit texts."
)

REDACT_USER = "Word: {word}\nTexts:\n{texts}"

_MARKED = re.compile(r"\[([^\[\]]*)\]")

# Dictionary texts occasionally contain literal square brackets
# ('jmdn. [durch sein Verhalten] eifersüchtig machen'). They would be
# indistinguishable from marks, so they are swapped for these characters
# before the text goes to the model and restored afterwards.
_LB, _RB = "⟦", "⟧"


def _shield(text: str) -> str:
    return text.replace("[", _LB).replace("]", _RB)


def _unshield(text: str) -> str:
    return text.replace(_LB, "[").replace(_RB, "]")

# Function words of a phrase lemma ('sich', 'etwas', 'so ... als ob') that say
# nothing about whether a text mentions the word itself.
_LEMMA_SKIP = {
    "sich", "etwas", "jemand", "jemanden", "jemandem", "jmd", "jmdm", "jmdn",
    "irgendwie", "irgendwo", "irgendwohin", "irgendwoher", "irgendein",
    "der", "die", "das", "dem", "den", "ein", "eine", "einen", "einem",
    "mit", "in", "auf", "zu", "für", "von", "als", "ob", "und", "oder",
}
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+")


def _blank(marked: str) -> str:
    """Replace each [form] with '[____]' — one underscore per character."""
    return _MARKED.sub(lambda m: "[" + "_" * len(m.group(1)) + "]", marked)


def _is_faithful(original: str, marked: str) -> bool:
    """True if `marked` is `original` with only non-empty spans bracketed.

    The model is told to change nothing but the brackets, and it usually
    does — but for phrases it also rewrites: 'so tun als ob' turned
    'sich so benehmen,' into 'sich [__] [___] als ob,'. A rewrite would put
    invented text on the card, so it is rejected instead of blanked.
    Comparison ignores case: capitalising a sentence's first word is a
    harmless normalisation, not a rewrite.
    """
    original, marked = original.lower(), marked.lower()
    segs = re.split(r"\[[^\[\]]*\]", marked)
    if len(segs) < 2:
        return False  # nothing marked
    pos = 0
    for i, s in enumerate(segs):
        if i == 0:
            if not original.startswith(s):
                return False
            pos = len(s)
        elif i == len(segs) - 1:
            if s and not original.endswith(s):
                return False
            if len(original) - len(s) <= pos:
                return False  # trail keeps no room for the blanked span
        else:
            j = original.find(s, pos)
            if j <= pos:
                return False  # segment missing, or nothing was blanked
            pos = j + len(s)
    return True


def _mentions_word(texts: list[str], lemma: str) -> bool:
    """True if any text contains a form of `lemma`, judged token by token.

    Used only to tell a model failure (nothing marked although the word is
    there) from a legitimately word-free text. Lemmatisation catches inflected
    and irregular forms a stem test misses ('hielt' → 'halten', 'tut' → 'tun').

    Deliberately no substring test: it cannot separate compounds
    ('Leichenbegräbnis' for 'Begräbnis') from prefixed derivatives
    ('behalten' for 'halten'), and derivatives must NOT be marked. A false
    positive here would reject a correct answer, so compounds and
    nominalizations go undetected — they stay visible in the card instead.
    """
    parts = {simplemma.lemmatize(p, lang="de")
             for p in re.split(r"[\s,()/|]+", lemma.lower())
             if len(p) > 2 and p.lower() not in _LEMMA_SKIP}
    if not parts:
        return False
    tokens = _WORD.findall(" ".join(texts).lower())
    return bool(parts & {simplemma.lemmatize(t, lang="de") for t in tokens})


class Redactor:
    """LLM-backed redaction of card texts, cached like consolidation.

    The model returns each text with the word's forms bracketed; Python turns
    each bracket pair into underscores. All texts of one card go in a single
    request (one sentence per definition is not worth a call each). A failed
    call returns the texts unredacted with a warning — a visible leak that the
    operator can act on beats a silently wrong patch.
    """

    def __init__(self, consolidator: "Consolidator"):
        self.cons = consolidator

    def redact_many(self, texts: list[str], lemma: str) -> list[str]:
        """Return `texts` with every form of `lemma` blanked, order preserved."""
        if not texts or not lemma:
            return list(texts)
        keys, fixed = {}, {}
        for t in texts:
            if t and t not in keys:
                keys[t] = self.cons._cache_key(
                    f"REDACT:{lemma}", t, f"v{_REDACT_VERSION}")
                if keys[t] in self.cons.cache:
                    fixed[t] = self.cons.cache[keys[t]]
        pending = [t for t in keys if t not in fixed]
        if pending:
            fixed.update(self._redact_batch(pending, lemma, keys))
        return [fixed.get(t, t) for t in texts]

    def _redact_batch(self, texts: list[str], lemma: str,
                      keys: dict[str, str]) -> dict[str, str]:
        """One request for all pending texts; returns the ones that succeeded.

        A text without a marked span passes through unchanged: about half of
        the card texts (paraphrased definitions, examples using an unrelated
        inflected form) genuinely contain no form of the word, so requiring a
        mark per text would fail most batches. The batch as a whole is
        rejected when nothing is marked although a text contains a form of
        the word — that is a model failure, not a word-free text.
        """
        numbered = "\n".join(f"{i}. {_shield(t)}" for i, t in enumerate(texts, 1))
        messages = [
            {"role": "system", "content": REDACT_SYSTEM},
            {"role": "user", "content": REDACT_USER.format(word=lemma, texts=numbered)},
        ]
        expect_mark = _mentions_word(texts, lemma)
        err = None
        for temp in (0.0, 0.0):
            try:
                obj = json.loads(self.cons._call(messages, temp))
                marked = obj.get("marked")
                if not isinstance(marked, dict):
                    raise ValueError("marked must be an object keyed by number")
                out = {}
                for i, t in enumerate(texts, 1):
                    s = marked.get(str(i))
                    if not isinstance(s, str) or not s.strip():
                        raise ValueError(f"missing text {i}")
                    # Stay shielded until after blanking: a restored literal
                    # bracket would otherwise be blanked as if it were a mark.
                    if not _MARKED.search(s):
                        out[t] = t  # genuinely word-free, keep
                    elif _is_faithful(_shield(t), s):
                        out[t] = _unshield(_blank(s))
                    else:
                        # The model rewrote the text instead of marking it.
                        # Keep the original: it is at least true to the
                        # dictionary, and it is not a text this run can cache.
                        print(f"WARNING: unfaithful redaction for {lemma!r}, "
                              f"left unredacted: {_unshield(s)[:120]!r}",
                              file=sys.stderr)
                        continue
                if expect_mark and all(k == v for k, v in out.items()):
                    raise ValueError("nothing marked")
                for t, b in out.items():
                    self.cons.cache[keys[t]] = b
                return out
            except (ValueError, KeyError, AttributeError,
                    json.JSONDecodeError, urllib.error.URLError, OSError) as e:
                err = e
        print(f"WARNING: redaction failed for {lemma!r}: {err}", file=sys.stderr)
        return {}


def _normalize(obj: dict) -> None:
    """Coerce tolerable model deviations into the expected shape, in place.

    The model sometimes names the dictionary it took an example from
    ("duden", "langenscheidt") instead of the generic "dict". Example sources
    are not used downstream, so map any non-empty source to "dict" rather
    than failing and paying for a regeneration.
    """
    if not isinstance(obj, dict):
        return
    for m in obj.get("meanings") or []:
        if isinstance(m, dict) and m.get("example_source") not in ("dict", "context", "none"):
            m["example_source"] = "dict" if m.get("example") else "none"


def _validate(obj: dict) -> str | None:
    """Return error string or None if valid."""
    if not isinstance(obj, dict):
        return "not an object"
    if not isinstance(obj.get("lemma"), str):
        return "missing lemma"
    ms = obj.get("meanings")
    if not isinstance(ms, list) or not ms:
        return "meanings must be a non-empty list"
    for m in ms:
        if not isinstance(m, dict) or not isinstance(m.get("sense"), int) \
                or not isinstance(m.get("definition"), str) \
                or not isinstance(m.get("example"), str) \
                or m.get("example_source") not in ("dict", "context", "none") \
                or not isinstance(m.get("in_context"), bool):
            return "bad meaning entry"
    if not isinstance(obj.get("expressions"), list):
        return "expressions must be a list"
    if not isinstance(obj.get("chosen_meaning_for_context"), str):
        return "missing chosen_meaning_for_context"
    return None


class RateLimiter:
    """Sliding-window cap of N requests per 60 s. N <= 0 means no cap.

    A plain token bucket would allow a full burst after 60 s of idling; the
    provider counts requests per wall-clock minute, so the window is what it
    enforces. The timestamps deque holds at most N entries.
    """

    WINDOW = 60.0

    def __init__(self, rpm: int):
        self.rpm = max(0, int(rpm))
        self._sent: deque[float] = deque()

    def acquire(self) -> None:
        if self.rpm <= 0:
            return
        while True:
            now = time.monotonic()
            while self._sent and now - self._sent[0] >= self.WINDOW:
                self._sent.popleft()
            if len(self._sent) < self.rpm:
                self._sent.append(now)
                return
            wait = self.WINDOW - (now - self._sent[0])
            print(f"\r\033[Krate limit: {self.rpm} req/min reached, "
                  f"waiting {wait:.1f}s", file=sys.stderr)
            time.sleep(max(wait, 0.05))


class Consolidator:
    def __init__(self, llm_cfg: dict):
        self._load_dotenv()
        self.url = llm_cfg["base_url"]
        self.model = llm_cfg["model"]
        self.api_key = llm_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        self.temperature = llm_cfg["temperature"]
        self.max_tokens = llm_cfg["max_completion_tokens"]
        self.prompt_version = llm_cfg["prompt_version"]
        self.cache_path = llm_cfg.get("cache")
        self.thinking = llm_cfg.get("thinking", True)
        # Every request goes through _call(), so one limiter covers
        # consolidation, batched redaction and their retries.
        self.limiter = RateLimiter(llm_cfg.get("rpm") or 0)
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if not self.cache_path:
            return {}
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            # Never silently start from {}: the next _save_cache() would
            # overwrite a recoverable file. Keep a copy and tell the user.
            backup = f"{self.cache_path}.corrupt-{int(time.time())}"
            os.replace(self.cache_path, backup)
            print(f"WARNING: cache unreadable, moved to {backup}; starting empty",
                  file=sys.stderr)
            return {}

    @staticmethod
    def _load_dotenv(path: str = ".env.local") -> None:
        """Populate os.environ from a gitignored key=value file (no shell leak)."""
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        except FileNotFoundError:
            pass

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        # Atomic write: a kill mid-dump must not truncate the only cache copy.
        tmp = f"{self.cache_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.cache_path)

    def _cache_key(self, word: str, entry: str, hint: str = "") -> str:
        # Model is deliberately NOT part of the key: the gateway can swap the
        # backing model behind a stable model name, so the name cannot reliably
        # identify the model. Keying on it only meant that changing
        # config.toml invalidated the whole cache while a gateway-side switch
        # silently reused it. Delete the cache file to regenerate.
        h = hashlib.sha256()
        h.update(f"{word}|{entry}|{self.prompt_version}".encode())
        # Append the source-language hint only when present, so KOReader keys
        # (hint="") stay identical to the pre-hint cache format.
        if hint:
            h.update(f"|{hint}".encode())
        return h.hexdigest()

    def _call(self, messages: list[dict], temperature: float) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if not self.thinking:
            # NOTE (docs/session-summary-2026-11-09.md): AxonHub accepts but
            # has historically IGNORED both fields. Sent anyway so it works
            # the day the gateway honours them; verify via usage.completion_tokens.
            body["reasoning_effort"] = "none"
            body["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {
            "Content-Type": "application/json",
            # gateway 403s non-browser UA strings; full string required
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.url, json.dumps(body).encode(), headers, method="POST")
        self.limiter.acquire()
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
        # 2xx with an empty/absent choices list = gateway quirk (e.g. an
        # {"error": ...} body sent with status 200); raise so the retry loop
        # in consolidate() handles it instead of crashing with IndexError.
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"response has no choices: {json.dumps(data)[:500]}")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ValueError("response truncated (finish_reason=length)")
        message = choice["message"]
        content = message.get("content") or ""
        # Known Gemma-4 26B-A4B failure: JSON lands in reasoning_content with
        # empty content — fall back to extracting it from there.
        if not content.strip() and message.get("reasoning_content"):
            content = message["reasoning_content"]
        # reasoning distills may prepend a think block before the JSON
        open_tag = "<" + "think" + ">"
        close_tag = "<" + "/think" + ">"
        if close_tag in content:
            content = content.split(close_tag, 1)[1]
        elif open_tag in content:  # unterminated think block
            content = content.split(open_tag, 1)[0]
        # strip markdown code fences if present
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3]
        return stripped.strip()

    def is_cached(self, word: str, entry: str, hint: str = "") -> bool:
        return self._cache_key(word, entry, hint) in self.cache

    def consolidate(self, word: str, entry: str, context: str, hint: str = "") -> dict:
        """Return validated card JSON; raises ValueError after one retry."""
        key = self._cache_key(word, entry, hint)
        if key in self.cache:
            return self.cache[key]
        tmpl = PROMPTS[self.prompt_version]
        messages = [
            {"role": "system", "content": tmpl["system"]},
            {"role": "user", "content": tmpl["user"].format(
                entry=entry or "(none)", word=word, context=context, hint=hint)},
        ]
        for attempt, temp in enumerate((self.temperature, 0.0)):
            content = None
            try:
                content = self._call(messages, temp)
                obj = json.loads(content)
                _normalize(obj)
                err = _validate(obj)
                if err is None:
                    self.cache[key] = obj
                    return obj
                raise ValueError(f"validation: {err}")
            except (ValueError, KeyError, IndexError,
                    json.JSONDecodeError) as e:
                if attempt == 1:
                    raw_preview = (content or "")[:500]
                    raise ValueError(f"LLM consolidation failed for {word!r}: {e}\n"
                                     f"raw: {raw_preview!r}") from e
                time.sleep(1)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:200]
                if e.code == 400 or attempt == 1:
                    raise ValueError(f"HTTP {e.code} for {word!r}: {detail}") from e
                time.sleep(2 ** attempt)
            # URLError/OSError covers RemoteDisconnected, connection resets and
            # timeouts — transient gateway drops; HTTPError is a URLError
            # subclass so this must come after the HTTPError clause.
            except (urllib.error.URLError, OSError) as e:
                if attempt == 1:
                    raise ValueError(f"network error for {word!r}: {e}") from e
                time.sleep(2 ** attempt)
        raise ValueError(f"unreachable: {word!r}")
