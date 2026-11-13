"""Kid-safe search on top of TMDb data. Pure logic, no Kodi imports.

The only setting is the age of the child. Every certification TMDb knows for a country of the built-in table is
mapped to a minimum age. The strictest rating decides; only when it is below 16 and enough countries rate the title,
a percentile (setting) may discard stray strict outliers. A rating of 16+ is never discarded, and a rating of a
country outside the table that clearly reads as 16+ (18+, R18+, 19, X ...) rejects the title too.
"""
import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Tuple

IMAGE_URL = "https://image.tmdb.org/t/p/w500"
MIN_AGE, MAX_AGE = 3, 18
# Version of the decision logic (evaluate / evaluate_playback). Bump it with every change of the logic that is not
# visible in the tables below: it invalidates the in-memory caches of verdicts and search results (kids_memo.py).
CACHE_VERSION = 2  # 2: search records carry the summary of the hidden titles
# Horror, Thriller, Crime, War, Mystery, War & Politics
_STRONG_GENRES = frozenset({27, 53, 80, 10752, 9648, 10768})
_MILD_GENRES = frozenset({27, 10752})  # Horror, War


@dataclass(frozen=True)
class KidsConfig:
    age: int = 8
    unrated: str = "deny"  # "deny" | "allow"
    min_votes: int = 20  # setting kids_min_votes
    percentile: int = 50  # setting kids_percentile: 50 (median) .. 100 (strictest country decides)
    sort: str = "relevance"  # setting kids_sort: relevance (TMDb order) | popularity | rating | year
    limit: int = 20  # setting kids_limit: the most titles listed


def _clamp_age(age) -> int:
    try:
        age = int(age)
    except (TypeError, ValueError):
        return KidsConfig.age
    return max(MIN_AGE, min(MAX_AGE, age))


def blocked_genres_for_age(age) -> frozenset:
    age = _clamp_age(age)
    if age < 12:
        return _STRONG_GENRES
    if age < 16:
        return _MILD_GENRES
    return frozenset()


def config_from_settings(get_setting: Callable[[str], str]) -> KidsConfig:
    """Builds the config from add-on settings (strings). Empty or invalid values give the defaults; never raises."""
    defaults = KidsConfig()

    def read(key):
        try:
            value = get_setting(key)
        except Exception:
            return ""
        return str(value).strip() if value is not None else ""

    try:
        age = _clamp_age(int(float(read("kids_age"))))
    except (ValueError, OverflowError):
        age = defaults.age
    unrated = {"0": "deny", "1": "allow"}.get(read("kids_unrated"), defaults.unrated)
    try:
        min_votes = max(0, min(100000, int(float(read("kids_min_votes")))))
    except (ValueError, OverflowError):
        min_votes = defaults.min_votes
    try:
        percentile = max(50, min(100, int(float(read("kids_percentile")))))
    except (ValueError, OverflowError):
        percentile = defaults.percentile
    sort = {"0": "relevance", "1": "popularity", "2": "rating", "3": "year"}.get(read("kids_sort"), defaults.sort)
    try:
        limit = max(5, min(60, int(float(read("kids_limit")))))
    except (ValueError, OverflowError):
        limit = defaults.limit
    return KidsConfig(age=age, unrated=unrated, min_votes=min_votes, percentile=percentile, sort=sort, limit=limit)


def algorithm_digest() -> str:
    """Short digest of everything the decision depends on besides the settings (age table, genre lists, constants).
    Part of the cache fingerprint, so an edited table drops the cached verdicts even when CACHE_VERSION was not bumped."""
    parts = [
        repr(sorted((country, sorted(table.items())) for country, table in AGE_TABLE.items())),
        repr(sorted(_STRONG_GENRES)), repr(sorted(_MILD_GENRES)),
        repr(sorted(_NO_RATING)), repr(sorted((c, sorted(v)) for c, v in _NO_RATING_BY_COUNTRY.items())),
        repr(sorted(_ADULT_WORDS)), repr((MIN_AGE, MAX_AGE, MIN_COUNTRIES_FOR_PERCENTILE)),
    ]
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:16]


def _log(message):
    """Logs to the Kodi log when available, else to stdlib logging. Callers must not pass secrets (API key, URLs)."""
    try:
        import xbmc  # lazy: kids.py itself needs no Kodi
        xbmc.log(f"[KodiSimpleStream] {message}", getattr(xbmc, "LOGWARNING", 2))
    except ImportError:
        import logging
        logging.getLogger(__name__).warning(message)


def _number(value, default=0.0) -> float:
    """value as a finite float, else default (TMDb data must never break a search)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


# --- age table: certification -> minimum age, per country (movie and TV scales are merged: one table per country) ---

AGE_TABLE: Dict[str, Dict[str, int]] = {
    "CZ": {"U": 0, "G": 0, "0+": 0, "5+": 5, "6+": 6, "7+": 7, "9+": 9, "12+": 12, "15+": 15, "18+": 18,
           "0": 0, "12": 12, "15": 15, "18": 18, "PG-13": 13},
    "SK": {"U": 0, "7": 7, "12": 12, "15": 15, "18": 18},
    "DE": {"0": 0, "6": 6, "12": 12, "16": 16, "18": 18},
    "AT": {"AA": 0, "0": 0, "6": 6, "8": 8, "10": 10, "12": 12, "14": 14, "16": 16},
    "CH": {"U": 0, "0": 0, "6": 6, "7": 7, "8": 8, "10": 10, "12": 12, "14": 14, "16": 16, "18": 18},
    "US": {"G": 0, "PG": 8, "PG-13": 13, "R": 17, "NC-17": 18,
           "TV-Y": 0, "TV-Y7": 7, "TV-Y7-FV": 7, "TV-G": 0, "TV-PG": 8, "TV-14": 14, "TV-MA": 17},
    "GB": {"U": 0, "PG": 8, "12A": 12, "12": 12, "15": 15, "18": 18, "R18": 18},
    "FR": {"TP": 0, "U": 0, "10": 10, "12": 12, "16": 16, "18": 18},
    "ES": {"A": 0, "APTA": 0, "AI": 0, "TP": 0, "ERI": 0, "7": 7, "7I": 7, "10": 10, "12": 12, "13": 13, "16": 16, "18": 18, "X": 18},
    "IT": {"T": 0, "BA": 8, "6+": 6, "10+": 10, "14+": 14, "18+": 18, "VM12": 12, "VM14": 14, "VM18": 18},
    "NL": {"AL": 0, "6": 6, "9": 9, "12": 12, "14": 14, "16": 16, "18": 18},
    "SE": {"BTL": 0, "7": 7, "11": 11, "15": 15, "FRÅN 7 ÅR": 7, "FRÅN 11 ÅR": 11, "FRÅN 15 ÅR": 15},
    "NO": {"A": 0, "6": 6, "7": 7, "7 ÅR": 7, "9": 9, "11 ÅR": 11, "12": 12, "15": 15, "16": 16, "18": 18},
    "DK": {"A": 0, "7": 7, "11": 11, "15": 15},
    "FI": {"S": 0, "7": 7, "K-7": 7, "K7": 7, "K-8": 8, "K-10": 10, "K-12": 12, "11": 11, "12": 12, "K-11": 11, "K-13": 13, "K-14": 14, "K-6-4": 6, "16": 16, "18": 18, "K12": 12, "K-16": 16, "K16": 16, "K-18": 18, "K18": 18, "KK": 18},
    "CA": {"G": 0, "C": 2, "C8": 8, "PG": 8, "14A": 14, "14+": 14, "18A": 18, "18+": 18, "R": 18, "A": 18},
    "CA-QC": {"G": 0, "8+": 8, "13+": 13, "16+": 16, "18+": 18},
    "BR": {"L": 0, "10": 10, "12": 12, "14": 14, "16": 16, "18": 18},
    "AU": {"G": 0, "P": 0, "C": 5, "PG": 8, "M": 15, "MA 15+": 15, "MA15+": 15, "R 18+": 18, "X 18+": 18, "RC": 18},
    "NZ": {"G": 0, "PG": 8, "M": 16, "13": 13, "R13": 13, "RP13": 13, "R15": 15, "R16": 16, "RP16": 16,
           "R18": 18, "RP18": 18, "R": 18, "16": 16, "18": 18},
    "IE": {"G": 0, "PG": 8, "12A": 12, "12": 12, "15A": 15, "15": 15, "16": 16, "18": 18},
    "PL": {"AL": 0, "0": 0, "7": 7, "12": 12, "15": 15, "16": 16, "18": 18},
    "HU": {"KN": 0, "CHILDREN": 0, "6": 6, "6 ÉVEN ALULIAK SZÁMÁRA NEM AJÁNLOTT": 6, "12": 12, "16": 16, "18": 18, "X": 18},
}

# Values that say "no rating information" (they carry no age); a few are meaningful only in one country (exempt)
_NO_RATING = frozenset({"NR", "UR", "UNRATED", "NOT RATED", "N/A", "NA", "NONE", "-"})
_NO_RATING_BY_COUNTRY = {"CA": frozenset({"EXEMPT", "E"}), "DK": frozenset({"F"})}


def normalise(text) -> str:
    """Upper case, unified dashes and plus signs, collapsed whitespace: "pg–13" -> "PG-13", "12 +" -> "12+"."""
    text = str(text or "").strip().upper()
    text = re.sub(r"[‐-―−]", "-", text)
    text = text.replace("＋", "+")
    text = re.sub(r"\s*\+", "+", text)
    return re.sub(r"\s+", " ", text)


_ADULT_WORDS = frozenset({"X", "XXX", "AO", "NC-17", "NC17"})


def foreign_min_age(certification) -> Optional[int]:
    """Minimum age of a rating of a country outside the table when it reads unambiguously as 16 or more
    ("R18+", "19", "18+", "R-18", "X", "+16"); None for anything else (unreadable or younger, which is ignored)."""
    value = normalise(certification)
    if value in _ADULT_WORDS:
        return 18
    ages = [int(n) for n in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", value)]
    ages = [a for a in ages if 16 <= a <= 21]
    return max(ages) if ages else None


def is_no_rating(country, certification) -> bool:
    value = normalise(certification)
    return not value or value in _NO_RATING or value in _NO_RATING_BY_COUNTRY.get(str(country).upper(), ())


def ratings_of(kind, details) -> List[Tuple[str, str]]:
    """All non-empty ratings of all countries as (country, certification) from release_dates / content_ratings."""
    details = details or {}
    result = []
    if kind == "movie":
        for block in (details.get("release_dates") or {}).get("results") or []:
            country = str(block.get("iso_3166_1") or "").strip().upper()
            for release in block.get("release_dates") or []:
                cert = str(release.get("certification") or "").strip()
                if cert:
                    result.append((country, cert))
    else:
        for block in (details.get("content_ratings") or {}).get("results") or []:
            country = str(block.get("iso_3166_1") or "").strip().upper()
            cert = str(block.get("rating") or "").strip()
            if cert:
                result.append((country, cert))
    return result


def _genre_set(values) -> Optional[set]:
    """Genre ids as a set of ints, or None when the value is not a list of numeric ids (fail closed)."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return None
    result = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            return None
    return result


def prefilter(item, cfg: KidsConfig) -> Optional[str]:
    """Cheap checks on a TMDb search result. Returns a rejection reason or None."""
    if item.get("adult"):
        return "adult"
    genres = _genre_set(item.get("genre_ids"))
    if genres is None:
        return "no genres"
    if genres & blocked_genres_for_age(cfg.age):
        return "blocked genre"
    if (item.get("vote_count") or 0) < cfg.min_votes:
        return "few votes"
    return None


# With fewer countries than this the strictest one always decides (too little data to call anything an outlier)
MIN_COUNTRIES_FOR_PERCENTILE = 5


def _percentile_pick(entries, percentile):
    """Nearest-rank percentile of (age, label) entries sorted by age; 100 = the strictest."""
    ordered = sorted(entries, key=lambda e: e[0])
    rank = -(-len(ordered) * percentile // 100)  # ceil without floats
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str
    age: Optional[int] = None  # the effective minimum age
    label: str = ""  # e.g. "DE 6"


def evaluate(kind, details, cfg: KidsConfig) -> Verdict:
    """Final decision on a title using its full details (with release_dates / content_ratings)."""
    if details.get("adult"):
        return Verdict(False, "adult")
    raw_genres = details.get("genres")
    if not isinstance(raw_genres, list):
        return Verdict(False, "no genres")  # a degraded answer: never skip the genre check
    genres = _genre_set([g.get("id") if isinstance(g, dict) else None for g in raw_genres])
    if genres is None:
        return Verdict(False, "bad genres")
    if genres & blocked_genres_for_age(cfg.age):
        return Verdict(False, "blocked genre")
    if (details.get("vote_count") or 0) < cfg.min_votes:  # a missing count is 0
        return Verdict(False, "few votes")

    placed = {}  # country -> (age, label): the strictest rating we could place for that country
    foreign = None  # a real rating from a country outside the table
    foreign_adult = {}  # country -> (age, label): outside-table countries whose rating clearly reads as 16+
    for country, cert in ratings_of(kind, details):
        if is_no_rating(country, cert):
            continue
        table = AGE_TABLE.get(country)
        if table is None:
            foreign = foreign or f"{country} {cert}"  # cannot be placed, so it must not count as "unrated"
            read_age = foreign_min_age(cert)
            if read_age is not None and (country not in foreign_adult or read_age > foreign_adult[country][0]):
                foreign_adult[country] = (read_age, f"{country} {cert}")
            continue
        age = table.get(normalise(cert))
        if age is None:
            return Verdict(False, "unplaced rating", label=f"{country} {cert}")  # never guess: fail closed
        if country not in placed or age > placed[country][0]:
            placed[country] = (age, f"{country} {cert}")  # one vote per country: its strictest rating
    # Countries outside the table cast no vote on their own (RU rates The Simpsons 18+ while everyone else says 12).
    # But when two or more of them clearly agree on 16+, they cannot be ignored.
    too_high = [e for e in foreign_adult.values() if e[0] > cfg.age]
    if len(too_high) >= 2:
        strictest_foreign = max(too_high, key=lambda e: e[0])
        return Verdict(False, "age too high", strictest_foreign[0], strictest_foreign[1])
    if not placed:
        strictest = None
    else:
        entries = list(placed.values())
        # A percentile of the per-country ages, so a stray strict outlier (a CH 12, a data error) does not decide
        # alone. It must never fail open: when the strictest rating is 16+ it always decides (US R, 18+ ...),
        # and with few countries the strictest wins as well (too little data to call anything an outlier).
        strictest = max(entries, key=lambda e: e[0])
        if strictest[0] < 16 and len(placed) >= MIN_COUNTRIES_FOR_PERCENTILE:
            strictest = _percentile_pick(entries, cfg.percentile)
    if strictest is None:
        if foreign:
            return Verdict(False, "unplaced rating", label=foreign)  # rated only where we cannot read it: fail closed
        if cfg.unrated == "allow":
            return Verdict(True, "unrated allowed")
        return Verdict(False, "unrated")
    if strictest[0] > cfg.age:
        return Verdict(False, "age too high", strictest[0], strictest[1])
    return Verdict(True, "age ok", strictest[0], strictest[1])


def evaluate_playback(kind, details, cfg: KidsConfig) -> Verdict:
    """The decision at playback time: the same as evaluate(), but the minimum of votes does not count.
    It only hides obscure titles from a search list; it is no safety property, a title the child picked in
    another add-on must not be refused for being little known. Age and genres decide."""
    return evaluate(kind, details, replace(cfg, min_votes=0))


def _best_poster(item, details) -> Optional[str]:
    """Poster path: the best Czech one, else Slovak/English, else a language-less one, else the search result's
    own (never raises)."""
    try:
        posters = [p for p in (details.get("images") or {}).get("posters") or [] if p.get("file_path")]
        for lang in ("cs", "sk", "en", None):
            found = [p for p in posters if p.get("iso_639_1") == lang]
            if found:
                return max(found, key=lambda p: _number(p.get("vote_average")))["file_path"]
    except Exception:
        pass
    return item.get("poster_path")


def _display_title(item, details) -> str:
    """The title TMDb gives for Czech; when it is not in Latin script (no Czech title, original e.g. Japanese),
    the English translation if there is one. Never raises."""
    title = item.get("title") or item.get("name") or ""
    try:
        from resources.lib.tmdb import TMDB  # lazy: kids.py itself needs no HTTP library
        if title and not TMDB._is_latin(title):
            english = TMDB._english_title(details or {})
            if english:
                return english
    except Exception:
        pass
    return title


def _to_entry(kind, item, verdict, details=None) -> Dict:
    date = str(item.get("release_date") or item.get("first_air_date") or "")
    poster = _best_poster(item, details or {})
    poster = poster if isinstance(poster, str) else None
    rating = _number(item.get("vote_average"))
    return {
        "id": f"{kind}:{item['id']}",
        "kind": kind,
        "title": _display_title(item, details),
        "year": date[:4] or None,
        "plot": str(item.get("overview") or "") or None,
        "poster": IMAGE_URL + poster if poster else None,
        "rating": round(rating, 1) if rating else None,
        "certification": f"{verdict.age}+" if verdict.age is not None else "",
        "country": "",
    }


_UNFILTERED = Verdict(True, "unfiltered")  # no age: the entry shows no certification


def _sort_key(cfg: KidsConfig, item, rank=(0, 0)):
    """Sort key (ascending) of a search item for cfg.sort: TMDb relevance (rank = page, position), popularity,
    rating or release date, newest first."""
    popularity = _number(item.get("popularity"))
    if cfg.sort == "relevance":
        return (rank, -popularity)
    if cfg.sort == "rating":
        return (-_number(item.get("vote_average")), -popularity)
    if cfg.sort == "year":
        date = str(item.get("release_date") or item.get("first_air_date") or "")
        return (tuple(-ord(ch) for ch in date) or (0,), -popularity)  # a missing date sorts last
    return (-popularity,)


# Verdicts that hide a title because of its age rating (not because of its genre, votes or an adult flag)
HIDDEN_BY_AGE = "age too high"
HIDDEN_UNRATED = frozenset({"unrated", "unplaced rating"})


def empty_hidden() -> Dict[str, int]:
    return {"high": 0, "unrated": 0, "min_age": 0}


def hidden_total(hidden) -> int:
    """How many titles the summary counts (0 for None or anything that is not a summary)."""
    try:
        return max(0, int(hidden["high"])) + max(0, int(hidden["unrated"]))
    except (TypeError, KeyError, ValueError):
        return 0


def summarise_hidden(verdicts) -> Dict[str, int]:
    """Summary of the titles hidden because of their age rating: "high" = rated above the age (min_age = the lowest
    age that would let one through), "unrated" = no rating or one that cannot be placed. Counts only, no titles."""
    summary = empty_hidden()
    ages = []
    for verdict in verdicts:
        if verdict.reason == HIDDEN_BY_AGE:
            summary["high"] += 1
            if verdict.age is not None:
                ages.append(verdict.age)
        elif verdict.reason in HIDDEN_UNRATED:
            summary["unrated"] += 1
    summary["min_age"] = min(ages) if ages else 0
    return summary


def search_safe(tmdb, query, kinds, cfg: KidsConfig, limit=None, pages=None, workers=6,
                on_allowed=None, report=None) -> List[Dict]:
    """Searches TMDb and keeps only titles that pass evaluate(); any failing details call drops the title.
    limit and pages default to cfg.limit and a number of pages that can fill it.
    on_allowed(kind, tmdb_id, verdict) is called (in the calling thread, after the details are in) for every title
    evaluate() allowed, listed or not; a failing callback is only logged.
    report, when a dict, gets "failures": the number of failed or dropped-by-error calls (0 = the result is complete)
    and "hidden" (see search_report). A thin wrapper of search_report."""
    return search_report(tmdb, query, kinds, cfg, limit, pages, workers, on_allowed, report)[0]


def search_report(tmdb, query, kinds, cfg: KidsConfig, limit=None, pages=None, workers=6,
                  on_allowed=None, report=None) -> Tuple[List[Dict], Dict[str, int]]:
    """search_safe plus a summary of what the age rating hid: (results, {"high": n, "unrated": m, "min_age": a}).
    Only titles that passed the cheap pre-filter (adult, genre, votes) and were then refused by evaluate() because
    of their age or rating are counted; no titles or names are kept. Titles lost to an error are not counted."""
    report = report if report is not None else {}
    results = _search(tmdb, query, kinds, cfg, limit, pages, workers, filtered=True, on_allowed=on_allowed, report=report)
    return results, report.get("hidden") or empty_hidden()


def search_all(tmdb, query, kinds, cfg: KidsConfig, limit=None, pages=None, workers=6) -> List[Dict]:
    """The same search without the age filter (kids mode off): everything TMDb finds, except adult titles.
    Only cfg.sort and cfg.limit apply."""
    return _search(tmdb, query, kinds, cfg, limit, pages, workers, filtered=False)


def _search(tmdb, query, kinds, cfg: KidsConfig, limit, pages, workers, filtered, on_allowed=None, report=None) -> List[Dict]:
    if report is not None:
        report["failures"] = 0
        report["hidden"] = empty_hidden()
    if limit is None:
        limit = cfg.limit
    if pages is None:
        pages = min(5, max(2, -(-limit // 10)))
    candidates = []  # (kind, search item, (page, position)) in search order
    seen = set()
    pages_wanted = [(kind, page) for page in range(1, max(pages, 1) + 1) for kind in kinds]  # page-major: kinds interleave
    if not pages_wanted:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pages_wanted)))) as pool:
        fetched = list(pool.map(lambda wanted: tmdb.search_raw(query, wanted[0], wanted[1]) or [], pages_wanted))
    for (kind, page), results in zip(pages_wanted, fetched):
        for position, item in enumerate(results):
            try:
                key = (kind, item.get("id"))
                if key in seen or item.get("id") is None:
                    continue
                seen.add(key)
                if not filtered:
                    if item.get("adult"):
                        continue  # kids mode off still never lists adult titles
                    candidates.append((kind, item, (page, position)))
                elif prefilter(item, cfg) is None:
                    candidates.append((kind, item, (page, position)))
            except Exception:
                continue  # a malformed item drops only itself
    if not candidates:
        return []

    errors = []  # exceptions of the details calls (list.append is thread safe)
    allowed = []  # (kind, id, verdict) of every title evaluate() allowed
    refused = []  # verdicts of the titles evaluate() refused (only their reasons are used, see summarise_hidden)

    def check(candidate):
        kind, item, _rank = candidate
        if not filtered:
            return _UNFILTERED
        try:
            verdict = evaluate(kind, tmdb.details_with_ratings(kind, item["id"]), cfg)
        except Exception as exc:
            errors.append(exc)
            # type only, no str(exc): the message of an HTTP error may carry the request URL with the key
            _log(f"kids: details of {kind}:{item.get('id')} failed, title dropped: {type(exc).__name__}")
            return None  # fail closed
        if verdict.allowed:
            allowed.append((kind, item["id"], verdict))
            return verdict
        refused.append(verdict)
        return None

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(candidates)))) as pool:
        verdicts = list(pool.map(check, candidates))
    if errors and len(errors) == len(candidates):
        raise errors[0]  # every details call failed: a network/auth problem, not "nothing suitable"
    if report is not None:
        report["failures"] = len(errors)
        report["hidden"] = summarise_hidden(refused)
    if on_allowed is not None:
        for kind, tmdb_id, verdict in allowed:
            try:
                on_allowed(kind, tmdb_id, verdict)
            except Exception as exc:  # a callback (a cache) never breaks the search
                _log(f"kids: on_allowed failed: {type(exc).__name__}")
    ranked = sorted(((_sort_key(cfg, candidates[i][1], candidates[i][2]), i) for i, v in enumerate(verdicts) if v),
                    key=lambda t: t)
    chosen = [i for _, i in ranked][:max(limit, 0)]
    if not chosen:
        return []

    build_failures = []  # titles listed without posters or dropped: the result is incomplete

    def build(i):
        kind, item, _rank = candidates[i]
        try:  # the heavy part (posters, translations) only for the titles that are listed; its failure is harmless
            extras = tmdb.details_extras(kind, item["id"])
        except Exception:
            extras = None
            build_failures.append(i)
        try:
            return _to_entry(kind, item, verdicts[i], extras)
        except Exception as exc:  # a malformed item drops only itself
            build_failures.append(i)
            _log(f"kids: {kind}:{item.get('id')} could not be built: {type(exc).__name__}")
            return None

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chosen)))) as pool:
        entries = [entry for entry in pool.map(build, chosen) if entry]
    if report is not None:
        report["failures"] += len(build_failures)
    return entries
