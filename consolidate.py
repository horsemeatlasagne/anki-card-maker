"""Stage 4: LLM consolidation via OpenAI-compatible chat completions.

Reference: docs/vendor/openai-chat-completions-create.md + docs/vendor/openai-chat-completions-notes.md
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

PROMPTS = {
    7: {
        "system": (
            "You are a German lexicography assistant creating flashcards for a "
            "advanced German learner. You receive dictionary entries for one "
            "German word (possibly from several dictionaries, marked === name "
            "===; Langenscheidt = learner senses with examples, Duden = "
            "meanings with literary citations) and the sentence context where "
            "the user encountered it while reading. Consolidate ALL senses and "
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
    }
}

VALIDATION = "Output JSON must have: lemma (str), non-empty meanings[] with sense:int, definition:str, example:str, in_context:bool, expressions[] (may be empty), chosen_meaning_for_context:str."


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
                or m.get("example_source") not in ("dict", "none") \
                or not isinstance(m.get("in_context"), bool):
            return "bad meaning entry"
    if not isinstance(obj.get("expressions"), list):
        return "expressions must be a list"
    if not isinstance(obj.get("chosen_meaning_for_context"), str):
        return "missing chosen_meaning_for_context"
    return None


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
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if not self.cache_path:
            return {}
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
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
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=1)

    def _cache_key(self, word: str, entry: str) -> str:
        h = hashlib.sha256()
        h.update(f"{word}|{entry}|{self.prompt_version}|{self.model}".encode())
        return h.hexdigest()

    def _call(self, messages: list[dict], temperature: float) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            # gateway 403s non-browser UA strings; full string required
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.url, json.dumps(body).encode(), headers, method="POST")
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

    def consolidate(self, word: str, entry: str, context: str) -> dict:
        """Return validated card JSON; raises ValueError after one retry."""
        key = self._cache_key(word, entry)
        if key in self.cache:
            return self.cache[key]
        tmpl = PROMPTS[self.prompt_version]
        messages = [
            {"role": "system", "content": tmpl["system"]},
            {"role": "user", "content": tmpl["user"].format(
                entry=entry or "(none)", word=word, context=context)},
        ]
        for attempt, temp in enumerate((self.temperature, 0.0)):
            content = None
            try:
                content = self._call(messages, temp)
                obj = json.loads(content)
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
