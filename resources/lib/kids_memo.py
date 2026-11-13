"""In-memory, signed caches of the kids filter (age verdicts of titles, results of the kids search).

Pure logic, no Kodi imports: the store is a pair of callables (get_property, set_property), in the add-on the
properties of the Kodi home window. Nothing is written to disk and everything is gone with the Kodi session.

Safety rules (the age filter must never get weaker by caching):
- A record is signed with HMAC-SHA256. The key is derived from the TMDb API key and a fixed string, so a record
  written by anything that does not know the key (another add-on, a skin) does not verify and is ignored.
  The signature covers the whole payload, including the kind of the record, so a record cannot be moved to
  another cache either. The key and the signature are never logged.
- A record carries a fingerprint of the settings that decide the verdict (age, unrated policy, percentile,
  minimum of votes, ...) and of the algorithm (CACHE_VERSION and a digest of its tables). Another fingerprint,
  version, kind or id, an expired or unreadable record: a miss, the caller asks TMDb as it did before.
- Only real verdicts are stored, never an error (network, timeout, 429, invalid answer) nor a refusal caused by
  a degraded answer.
"""
import hashlib
import hmac
import json
import re
import time
import unicodedata
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from resources.lib import kids
from resources.lib.kids import CACHE_VERSION, KidsConfig, Verdict

VERDICT_TTL = 6 * 3600  # seconds
SEARCH_TTL = 15 * 60
CLOCK_SKEW = 60  # a record stamped this much in the future is still accepted, further than that it is not

VERDICT_PROPERTY = "kodisimplestream.kv."  # + "movie:603" / "tv:1399"
SEARCH_PROPERTY = "kodisimplestream.ks."  # + slot number
SEARCH_SLOTS = 4  # searches remembered at a time (about 10 kB each): the memory stays bounded

_KEY_CONTEXT = b"kodisimplestream.kids-cache.v1"
# Refusals that come from a degraded TMDb answer rather than from the title: not remembered
_UNCACHED_REASONS = frozenset({"no genres", "bad genres"})


def settings_fingerprint(cfg: KidsConfig, playback: bool) -> str:
    """Everything the decision depends on: the version and digest of the algorithm and the settings that go into it.
    For playback the minimum of votes does not count (evaluate_playback), so it is left out: a verdict of the
    search (which has it) and of the playback then share one fingerprint. The search adds sort and limit."""
    if playback:
        cfg = replace(cfg, min_votes=0, sort="", limit=0)
    parts = [f"v{CACHE_VERSION}", kids.algorithm_digest(), f"age={cfg.age}", f"unrated={cfg.unrated}",
             f"percentile={cfg.percentile}", f"min_votes={cfg.min_votes}"]
    if not playback:
        parts += [f"sort={cfg.sort}", f"limit={cfg.limit}"]
    return "|".join(parts)


def normalise_query(query) -> str:
    """Case, accents' composition and spaces do not make another search."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(query or "")).casefold()).strip()


def search_fingerprint(query, kinds, cfg: KidsConfig) -> str:
    text = "\x1f".join([settings_fingerprint(cfg, playback=False), ",".join(sorted(kinds)), normalise_query(query)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class KidsMemo:
    """get_property(name) -> str and set_property(name, value) of the home window; secret = the TMDb API key."""

    def __init__(self, secret: str, get_property: Callable[[str], str], set_property: Callable[[str, str], None],
                 clock: Callable[[], float] = time.time):
        self._key = hmac.new(_KEY_CONTEXT, str(secret or "").encode("utf-8"), hashlib.sha256).digest()
        self._get = get_property
        self._set = set_property
        self._clock = clock
        self.enabled = bool(str(secret or "").strip())  # no key, no signature: no cache

    # --- signed records ---

    def _sign(self, body: str) -> str:
        return hmac.new(self._key, body.encode("utf-8"), hashlib.sha256).hexdigest()

    def _seal(self, kind: str, data: Dict[str, Any]) -> str:
        data = dict(data, d=kind, v=CACHE_VERSION, t=self._clock())
        body = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        return f"{self._sign(body)}:{body}"

    def _open(self, kind: str, raw, ttl: float) -> Optional[Dict[str, Any]]:
        """The payload of a record that is signed by us, of this kind and version, and not expired; else None."""
        try:
            if not isinstance(raw, str) or ":" not in raw:
                return None
            signature, _, body = raw.partition(":")
            if not hmac.compare_digest(signature.encode("utf-8"), self._sign(body).encode("utf-8")):
                return None
            data = json.loads(body)
            if not isinstance(data, dict) or data.get("d") != kind or data.get("v") != CACHE_VERSION:
                return None
            stamp = data.get("t")
            if not _is_number(stamp):
                return None
            age = self._clock() - stamp
            if age < -CLOCK_SKEW or age >= ttl:
                return None
            return data
        except Exception:  # anything unreadable is a miss
            return None

    def _read(self, name: str):
        try:
            return self._get(name)
        except Exception:
            return None

    def _write(self, name: str, value: str) -> None:
        try:
            self._set(name, value)
        except Exception:
            pass  # a cache that cannot be written is just a miss next time

    # --- verdicts of titles ---

    @staticmethod
    def _title_key(kind, tmdb_id) -> Optional[str]:
        try:
            if kind not in ("movie", "tv") or isinstance(tmdb_id, bool):
                return None
            return f"{kind}:{int(str(tmdb_id).strip())}"
        except (TypeError, ValueError):
            return None

    def get_verdict(self, kind, tmdb_id, cfg: KidsConfig) -> Optional[Verdict]:
        """The remembered verdict of evaluate_playback for this title and these settings, None when unknown."""
        title = self._title_key(kind, tmdb_id)
        if not self.enabled or title is None:
            return None
        data = self._open("verdict", self._read(VERDICT_PROPERTY + title), VERDICT_TTL)
        if data is None or data.get("k") != title or data.get("f") != settings_fingerprint(cfg, playback=True):
            return None
        allowed, reason, age, label = data.get("a"), data.get("r"), data.get("g"), data.get("l")
        if (not isinstance(allowed, bool) or not isinstance(reason, str) or not isinstance(label, str)
                or not (age is None or (isinstance(age, int) and not isinstance(age, bool)))):
            return None
        return Verdict(allowed, reason, age, label)

    def put_verdict(self, kind, tmdb_id, cfg: KidsConfig, verdict: Verdict) -> bool:
        """Remembers a verdict (of evaluate_playback, or an allowing one of evaluate). False when it is not stored."""
        title = self._title_key(kind, tmdb_id)
        if not self.enabled or title is None or not isinstance(verdict, Verdict):
            return False
        if not verdict.allowed and verdict.reason in _UNCACHED_REASONS:
            return False
        self._write(VERDICT_PROPERTY + title, self._seal("verdict", {
            "k": title, "f": settings_fingerprint(cfg, playback=True),
            "a": verdict.allowed, "r": verdict.reason, "g": verdict.age, "l": verdict.label}))
        return True

    # --- results of the search ---

    @staticmethod
    def _valid_hidden(hidden) -> bool:
        """The summary of hidden titles: counts only (see kids.summarise_hidden)."""
        return (isinstance(hidden, dict) and set(hidden) == {"high", "unrated", "min_age"}
                and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in hidden.values()))

    def get_search(self, query, kinds, cfg: KidsConfig) -> Optional[List[Dict[str, Any]]]:
        """The remembered result list of this search with these settings, None when unknown."""
        found = self.get_search_report(query, kinds, cfg)
        return found[0] if found is not None else None

    def get_search_report(self, query, kinds, cfg: KidsConfig) -> Optional[Tuple[List[Dict[str, Any]], Optional[Dict[str, int]]]]:
        """The remembered (results, summary of hidden titles) of this search with these settings, None when unknown.
        The summary is None for a record stored without one; a malformed summary makes the whole record a miss."""
        if not self.enabled:
            return None
        fingerprint = search_fingerprint(query, kinds, cfg)
        for slot in range(SEARCH_SLOTS):
            data = self._open("search", self._read(f"{SEARCH_PROPERTY}{slot}"), SEARCH_TTL)
            if data is not None and data.get("f") == fingerprint:
                results, hidden = data.get("n"), data.get("h")
                valid = (isinstance(results, list) and all(
                    isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("kind") in ("movie", "tv")
                    for r in results)) and (hidden is None or self._valid_hidden(hidden))
                return (results, hidden) if valid else None
        return None

    def put_search(self, query, kinds, cfg: KidsConfig, results: List[Dict[str, Any]],
                   hidden: Optional[Dict[str, int]] = None) -> bool:
        """Remembers a complete result list with the summary of the titles the age hid (the caller never passes the
        result of an error). A malformed summary is not stored."""
        if not self.enabled or not isinstance(results, list) or not (hidden is None or self._valid_hidden(hidden)):
            return False
        fingerprint = search_fingerprint(query, kinds, cfg)
        payload = {"f": fingerprint, "n": results}
        if hidden is not None:
            payload["h"] = hidden
        try:
            record = self._seal("search", payload)
        except (TypeError, ValueError):
            return False  # not JSON
        target, oldest = None, None  # the slot of this very search, else a free one, else the oldest
        for slot in range(SEARCH_SLOTS):
            data = self._open("search", self._read(f"{SEARCH_PROPERTY}{slot}"), SEARCH_TTL)
            if data is not None and data.get("f") == fingerprint:
                target = slot
                break
            if data is None:
                target = slot if target is None else target  # empty, expired or not ours
            elif oldest is None or data["t"] < oldest[0]:
                oldest = (data["t"], slot)
        if target is None:
            target = oldest[1] if oldest else 0
        self._write(f"{SEARCH_PROPERTY}{target}", record)
        return True
