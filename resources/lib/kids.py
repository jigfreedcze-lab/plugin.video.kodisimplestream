"""Kid-safe search on top of TMDb data. Pure logic, no Kodi imports.

The only setting is the age of the child. Every certification TMDb knows for a country of the built-in table is
mapped to a minimum age; the strictest rating over all those countries decides.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

IMAGE_URL = "https://image.tmdb.org/t/p/w500"
MIN_AGE, MAX_AGE = 3, 18
# Horror, Thriller, Crime, War, Mystery, War & Politics
_STRONG_GENRES = frozenset({27, 53, 80, 10752, 9648, 10768})
_MILD_GENRES = frozenset({27, 10752})  # Horror, War


@dataclass(frozen=True)
class KidsConfig:
    age: int = 8
    unrated: str = "deny"  # "deny" | "allow"
    min_votes: int = 20  # setting kids_min_votes
    percentile: int = 75  # setting kids_percentile: 50 (median) .. 100 (strictest country decides)
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


# --- age table: certification -> minimum age, per country (movie and TV scales are merged: one table per country) ---

AGE_TABLE: Dict[str, Dict[str, int]] = {
    "CZ": {"U": 0, "G": 0, "0+": 0, "5+": 5, "6+": 6, "7+": 7, "9+": 9, "12+": 12, "15+": 15, "18+": 18,
           "0": 0, "12": 12, "15": 15, "18": 18},
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
    for country, cert in ratings_of(kind, details):
        if is_no_rating(country, cert):
            continue
        table = AGE_TABLE.get(country)
        if table is None:
            foreign = foreign or f"{country} {cert}"  # cannot be placed, so it must not count as "unrated"
            continue
        age = table.get(normalise(cert))
        if age is None:
            return Verdict(False, "unplaced rating", label=f"{country} {cert}")  # never guess: fail closed
        if country not in placed or age > placed[country][0]:
            placed[country] = (age, f"{country} {cert}")  # one vote per country: its strictest rating
    if not placed:
        strictest = None
    else:
        # A percentile of the per-country ages, so a stray outlier country (a CH 12, a data error) does not
        # decide alone; with few countries the strictest wins (stay cautious).
        percentile = cfg.percentile if len(placed) >= MIN_COUNTRIES_FOR_PERCENTILE else 100
        strictest = _percentile_pick(list(placed.values()), percentile)
    if strictest is None:
        if foreign:
            return Verdict(False, "unplaced rating", label=foreign)  # rated only where we cannot read it: fail closed
        if cfg.unrated == "allow":
            return Verdict(True, "unrated allowed")
        return Verdict(False, "unrated")
    if strictest[0] > cfg.age:
        return Verdict(False, "age too high", strictest[0], strictest[1])
    return Verdict(True, "age ok", strictest[0], strictest[1])


def _best_poster(item, details) -> Optional[str]:
    """Poster path: the best Czech one, else Slovak/English, else the search result's own (never raises)."""
    try:
        posters = [p for p in (details.get("images") or {}).get("posters") or [] if p.get("file_path")]
        for lang in ("cs", "sk", "en"):
            found = [p for p in posters if p.get("iso_639_1") == lang]
            if found:
                return max(found, key=lambda p: p.get("vote_average") or 0)["file_path"]
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
    date = item.get("release_date") or item.get("first_air_date") or ""
    poster = _best_poster(item, details or {})
    rating = item.get("vote_average")
    return {
        "id": f"{kind}:{item['id']}",
        "kind": kind,
        "title": _display_title(item, details),
        "year": date[:4] or None,
        "plot": item.get("overview") or None,
        "poster": IMAGE_URL + poster if poster else None,
        "rating": round(rating, 1) if rating else None,
        "certification": f"{verdict.age}+" if verdict.age is not None else "",
        "country": "",
    }


def _sort_key(cfg: KidsConfig, item, rank=(0, 0)):
    """Sort key (ascending) of a search item for cfg.sort: TMDb relevance (rank = page, position), popularity,
    rating or release date, newest first."""
    popularity = item.get("popularity") or 0
    if cfg.sort == "relevance":
        return (rank, -popularity)
    if cfg.sort == "rating":
        return (-(item.get("vote_average") or 0), -popularity)
    if cfg.sort == "year":
        date = item.get("release_date") or item.get("first_air_date") or ""
        return (tuple(-ord(ch) for ch in date) or (0,), -popularity)  # a missing date sorts last
    return (-popularity,)


def search_safe(tmdb, query, kinds, cfg: KidsConfig, limit=None, pages=None, workers=6) -> List[Dict]:
    """Searches TMDb and keeps only titles that pass evaluate(); any failing details call drops the title.
    limit and pages default to cfg.limit and a number of pages that can fill it."""
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
                if prefilter(item, cfg) is None:
                    candidates.append((kind, item, (page, position)))
            except Exception:
                continue  # a malformed item drops only itself
    if not candidates:
        return []

    def check(candidate):
        kind, item, _rank = candidate
        try:
            verdict = evaluate(kind, tmdb.details_with_ratings(kind, item["id"]), cfg)
        except Exception:
            return None  # fail closed
        return verdict if verdict.allowed else None

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(candidates)))) as pool:
        verdicts = list(pool.map(check, candidates))
    ranked = sorted(((_sort_key(cfg, candidates[i][1], candidates[i][2]), i) for i, v in enumerate(verdicts) if v),
                    key=lambda t: t)
    chosen = [i for _, i in ranked][:max(limit, 0)]
    if not chosen:
        return []

    def build(i):
        kind, item, _rank = candidates[i]
        try:  # the heavy part (posters, translations) only for the titles that are listed; its failure is harmless
            extras = tmdb.details_extras(kind, item["id"])
        except Exception:
            extras = None
        return _to_entry(kind, item, verdicts[i], extras)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chosen)))) as pool:
        return list(pool.map(build, chosen))
