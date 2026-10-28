# -*- coding: utf-8 -*-
"""Webshare search queries and match scoring of file names against TMDb metadata.

Webshare ORs the query words, so the results contain a lot of noise sharing a word with the title.
A file name is read like a person would: any of the known titles (Czech, original, English) matched
word by word in any order and with typos, the year only together with the title (by the shared part when
the title matches only partly), penalties for another part of a series, another year, another episode
and words that do not belong to the title.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from resources.lib.source_ui import matches_language_preference, normalize_source

NOISE_TOKENS = {"sample", "trailer", "cam", "telesync", "ts", "hdcam", "subforced"}
QUALITY_ORDER = ["2160p", "1080p", "720p", "sd"]
# Added to the match score for sorting when the file has the preferred dub/subtitles, the shown score stays
LANG_PREF_BONUS = 15
MAX_QUERIES = 4

MOVIE_TITLE_POINTS = 70
EPISODE_SHOW_POINTS = 55
TITLE_OK = 0.75
FUZZY_MATCH = 0.85
FUZZY_ALONE_LENGTH = 7
MAIN_PART_WEIGHT = 0.85
YEAR_MATCH = 20
YEAR_NEAR = 0
# A title sharing only some words with a known one (another language): the year counts by the shared part
PARTIAL_TITLE = 0.3
YEAR_OTHER = -25
OTHER_PART = -35
OTHER_PART_MARKER = -15
EPISODE_IN_MOVIE = -40
SEASON_IN_MOVIE = -20
EXTRA_WORDS = -40
EXTRA_WORDS_MAX = 3
TAG_MATCH = 80
TAG_X_LESS = -5
TAG_OTHER = -50
SEASON_OTHER = -30
NO_SHOW_FACTOR = 0.3
ABSOLUTE_MATCH = 50
ABSOLUTE_OTHER = -30
EPISODE_TITLE_POINTS = 40
BAD_TOKEN = -60

ARTICLES = frozenset("the a an der die das le la les l el il lo los las".split())
STOPWORDS = frozenset(
    "the a an of and in on at to for by with from or "
    "a i o u v ve z ze s se k ke na do po pro za od ani "
    "der die das den dem und von zu le la les l de du des et el los las il lo di da del no".split()
)
# Release, language, genre and site words: a title followed by them is still the same title
TECH_TOKENS = frozenset("""
mkv avi mp4 m4v wmv mov mpg mpeg m2ts iso vob webm flv divx xvid x264 x265 h264 h265 264 265 hevc avc av1 vp9
10bit 8bit hdr hdr10 dv dovi sdr 2160p 1440p 1080p 1080i 720p 576p 480p 360p 4k uhd fhd hd sd hq lq
bluray blu ray bdrip brrip bdremux remux bd web webdl webrip dl hdtv hdrip dvdrip dvd dvdscr dvd5 dvd9 tvrip dvb
satrip vhsrip vhs rip nf amzn hmax dsnp atvp max hulu pcok skyshowtime
aac aac2 aac5 ac3 eac3 dd dd2 dd5 ddp ddp2 ddp5 ddp7 dts hdma ma truehd atmos flac opus mp3 2ch 6ch 8ch stereo mono
cz sk en eng cze czech ces cesky slo svk slovak ger german de fr fre french ita it spa es pl pol hun rus ru
jap jpn japanese kor korean chi chn ukr multi dual audio dabing dab dub dubbed dubbing titulky titulek tit tits
sub subs subtitles forced czsub cztit czdab sktit skdab czsk czen encz usa uk vb cssr csfr
extended directors director cut unrated remastered remaster edition uncut theatrical imax special proper repack
internal limited complete final restored restoration criterion 3d sbs hsbs ou version verze
by www com org net eu film movie serial serie series tv cd cd1 cd2 cd3 disc full top kvalita
komedie drama thriller akcni horor fantasy scifi sci fi animovany animated rodinny dokument dokumentarni krimi
romanticky valecny western muzikal pohadka anime
""".split())
BAD_TOKENS = frozenset(
    "sample trailer trailers teaser cam hdcam telesync ts soundtrack ost featurette recenze review upoutavka "
    "parodie parody reaction interview rozhovor".split()
)
GENERIC_EPISODE_WORDS = frozenset("episode epizoda epizody dil cast kapitola chapter part pilot pilotni".split())
PART_MARKERS = frozenset("part pt cast dil chapter kapitola volume vol".split())
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "jedna": 1, "dva": 2, "tri": 3, "ctyri": 4,
                "prvni": 1, "druha": 2, "druhy": 2, "treti": 3}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_ROMAN_OF = {str(value): roman for roman, value in ROMAN.items() if len(roman) > 1}

SHOW_KEYS = ["showname", "tvshowtitle", "show_title"]
SHOW_ORIGINAL_KEYS = ["show_originaltitle", "tvshoworiginaltitle", "show_original"]
SHOW_ENGLISH_KEYS = ["show_englishtitle", "show_english"]
EPISODE_TITLE_KEYS = ["episode_title", "title", "episodetitle"]
MOVIE_TITLE_KEYS = ["title", "name", "label"]
MOVIE_ORIGINAL_KEYS = ["originaltitle", "original_title"]
MOVIE_ENGLISH_KEYS = ["englishtitle", "english_title", "title_en"]

_SPECIAL_LETTERS = str.maketrans({
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i", "ħ": "h",
})
_CYRILLIC = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяєіїґўђјљњћџ",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
     "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "ye", "i", "yi", "g", "u", "dj", "j",
     "lj", "nj", "c", "dz"],
))
_APOSTROPHES = re.compile("['’`´ʼ]")
_LATIN = re.compile(r"[a-z0-9]")
_TOKEN = re.compile(r"[^\W_]+|[\[\](){}|/]|\s-+\s|\s-+(?=\S)|-{2,}")
_EXTENSION = re.compile(r"\.[a-z0-9]{2,4}$", re.IGNORECASE)
_YEAR = re.compile(r"^(19\d{2}|20\d{2})$")
_TECHNICAL = re.compile(r"^\d+[a-z]{1,2}\d*$|^s\d{1,2}(e\d{1,3})?$|^e\d{1,3}$|^\d{1,2}x\d{2,3}$")
_EPISODE_TAG = re.compile(r"(?<![a-z0-9])s(\d{1,2})\s?[ ._-]?\s?e(\d{1,3})((?:\s?-\s?e?\d{1,3}|e\d{1,3})*)(?![0-9])")
_EPISODE_X = re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?:-(\d{2,3}))?(?![0-9a-z])")
_EPISODE_AFTER = re.compile(r"(?<![a-z0-9])(?:e|ep|episode|epizoda|dil)\s*(\d{1,3})(?![0-9])")
_EPISODE_BEFORE = re.compile(r"(?<![a-z0-9])(\d{1,3})\s*(?:dil|epizoda|episode)(?![a-z])")
_SEASON_ONLY = re.compile(r"(?<![a-z0-9])(?:s(\d{1,2})(?![0-9]|\s?[ ._-]?\s?e\d)"
                          r"|(?:season|serie|series|rada)\s*(\d{1,2})(?![0-9])|(\d{1,2})\s*(?:season|serie|rada)(?![a-z]))")
# Czech "making of" ("Film o filmu", "Film o seriálu"); after + or & it is a bonus in the file of the film
_CZECH_MAKING_OF = re.compile(r"([+&]?)[\s._-]*(?<![^\W_])film[\s._-]+o[\s._-]+(filmu|serialu)(?![^\W_])")


def normalize_title(value: str) -> str:
    value = (value or "").lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[._-]+", " ", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    parts = [p for p in value.split() if p and p not in NOISE_TOKENS]
    return " ".join(parts)


def fold_text(value: Any) -> str:
    """Lower case without diacritics, Cyrillic transliterated, apostrophes dropped (Jack's -> jacks)."""
    text = _APOSTROPHES.sub("", str(value or "")).casefold().translate(_SPECIAL_LETTERS)
    text = "".join(_CYRILLIC.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _separators(text: str) -> str:
    """Dots and underscores between words become spaces, decimal dots (5.1, H.264) stay."""
    return re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text.replace("_", " "))


def tokenize(value: Any) -> List[str]:
    """Words of a title or a file name: letters and digits of any script, folded."""
    return [t for t in _TOKEN.findall(_separators(fold_text(value))) if t[0].isalnum()]


def czech_to_hepburn(text: str) -> str:
    """Czech transcription of Japanese to the Hepburn romanization of fansubs (Kódži no čidžin -> Kóji no chijin)."""
    text = text or ""
    for czech, hepburn in (("j", "y"), ("J", "Y"), ("dž", "j"), ("Dž", "J"), ("DŽ", "J"), ("c", "ts"), ("C", "Ts"),
                           ("č", "ch"), ("Č", "Ch"), ("š", "sh"), ("Š", "Sh")):
        text = text.replace(czech, hepburn)
    return text


def _as_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _first_non_empty(params: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = (params.get(key) or "")
        if str(value).strip():
            return str(value).strip()
    return ""


def _season_episode(params: Dict[str, Any]) -> Tuple[int, int]:
    """Season (0 = specials, -1 = unknown) and episode number (0 = unknown)."""
    season = str(params.get("season") if params.get("season") is not None else "").strip()
    return (int(season) if season.isdigit() else -1), max(0, _as_int(params.get("episode")))


# ----------------------------------------------------------------------------
# Webshare queries
# ----------------------------------------------------------------------------

def _has_searchable_words(text: str) -> bool:
    """Webshare ignores words it cannot read (Japanese, Chinese, Korean): such a query finds only the year or SxxEyy."""
    return any(word.isdigit() or re.search(r"[a-z]", word) for word in tokenize(text))


def _other_title(title: str, other: str) -> str:
    """The other title when it differs and Webshare can search it."""
    if other and _has_searchable_words(other) and tokenize(other) != tokenize(title):
        return other
    return ""


def _main_part(title: str) -> str:
    """Title before a subtitle: "Island 2: The Return" -> "Island 2"."""
    for separator in (":", " - ", " – "):
        if separator in title:
            head = title.split(separator, 1)[0].strip()
            if tokenize(head):
                return head
    return ""


def _dedup_queries(queries: Iterable[str]) -> List[str]:
    dedup: List[str] = []
    seen = set()
    for query in queries:
        key = " ".join(tokenize(query))
        if key and key not in seen:
            seen.add(key)
            dedup.append(query)
    return dedup[:MAX_QUERIES]


def _specific_episode_title(title: str) -> bool:
    """Placeholder titles ("1. epizoda", "Chapter 3", "001") say nothing about the episode."""
    return any(not t.isdigit() and t not in GENERIC_EPISODE_WORDS and t not in STOPWORDS and len(t) > 1
               for t in tokenize(title))


def _episode_queries(params: Dict[str, Any]) -> List[str]:
    """SxxEyy with the show titles, the show title before a colon (the full title may be blocked),
    the show title with the episode title (Czech series are often named so), 1x02 for a free slot."""
    showname = _first_non_empty(params, SHOW_KEYS)
    season, episode = _season_episode(params)
    if not showname or season < 0 or episode <= 0:
        return []
    tag = f"S{season:02d}E{episode:02d}"
    original = _other_title(showname, _first_non_empty(params, SHOW_ORIGINAL_KEYS))
    episode_title = _first_non_empty(params, EPISODE_TITLE_KEYS)
    queries = [f"{showname} {tag}"]
    if original:
        queries.append(f"{original} {tag}")
    main = _main_part(showname)
    if main:
        queries.append(f"{main} {tag}")
    if episode_title and _specific_episode_title(episode_title):
        queries.append(f"{showname} {episode_title}")
    if season > 0:
        queries.append(f"{showname} {season}x{episode:02d}")
    return _dedup_queries(queries)


def build_tmdbh_queries(params: Dict[str, Any]) -> List[str]:
    """Queries of the TMDb Helper search: both titles with and without the year, episodes as build_search_queries."""
    if (params.get("mediatype") or "").lower() == "episode":
        return _episode_queries(params)
    title = _first_non_empty(params, MOVIE_TITLE_KEYS)
    if not title:
        return []
    year = _first_non_empty(params, ["year", "premiered"])[:4]
    original = _other_title(title, _first_non_empty(params, MOVIE_ORIGINAL_KEYS))
    queries = [f"{title} {year}" if year else title, title]
    if original:
        queries += [f"{original} {year}" if year else original, original]
    return _dedup_queries(queries)


def build_search_queries(match: Dict[str, Any]) -> List[str]:
    """Queries of the TMDb search in the add-on: a movie by both titles with the year, an episode by SxxEyy."""
    if str(match.get("mediatype") or "").lower() == "episode":
        return _episode_queries(match)
    title = _first_non_empty(match, MOVIE_TITLE_KEYS)
    if not title:
        return []
    year = str(match.get("year") or "").strip()[:4]
    original = _other_title(title, _first_non_empty(match, MOVIE_ORIGINAL_KEYS))
    queries = [f"{title} {year}" if year else title]
    if original:
        queries.append(f"{original} {year}" if year else original)
    return _dedup_queries(queries)


# ----------------------------------------------------------------------------
# File name parts
# ----------------------------------------------------------------------------

def parse_quality(filename: str) -> Dict[str, Any]:
    text = normalize_title(filename)
    quality = "sd"
    score = 0
    if "2160p" in text:
        quality, score = "2160p", 30
    elif "1080p" in text:
        quality, score = "1080p", 20
    elif "720p" in text:
        quality, score = "720p", 10
    return {"quality": quality, "quality_score": score}


def parse_size(size_value: Any) -> int:
    try:
        return int(float(size_value))
    except (TypeError, ValueError):
        return 0


def _has_bad_tokens(text: str, vocabulary: Optional[Set[str]] = None) -> bool:
    """Trailer, sample, soundtrack, making of, film o filmu... unless the words belong to the title."""
    vocabulary = vocabulary or set()
    words = set(tokenize(_EXTENSION.sub("", text or ""))) - vocabulary
    if words & BAD_TOKENS or ("making" in words and "of" in words):
        return True
    return any(not found.group(1) and not {"film", "o", found.group(2)} <= vocabulary
               for found in _CZECH_MAKING_OF.finditer(fold_text(text)))


def _sxe_tags(text: str) -> Set[Tuple[int, int]]:
    episodes: Set[Tuple[int, int]] = set()
    for found in _EPISODE_TAG.finditer(text):
        season, first = int(found.group(1)), int(found.group(2))
        numbers = [first] + [int(n) for n in re.findall(r"\d{1,3}", found.group(3) or "")]
        last = max(numbers)
        if last - first <= 30:
            episodes.update((season, e) for e in range(first, last + 1))
        else:
            episodes.update((season, e) for e in numbers)
    return episodes


def _x_tags(text: str) -> Set[Tuple[int, int]]:
    episodes: Set[Tuple[int, int]] = set()
    for found in _EPISODE_X.finditer(text):
        season, first = int(found.group(1)), int(found.group(2))
        last = int(found.group(3)) if found.group(3) else first
        if season == 0 or first > 300:
            continue
        if first <= last <= first + 30:
            episodes.update((season, e) for e in range(first, last + 1))
        episodes.add((season, first))
    return episodes


def _season_tags(text: str) -> Set[int]:
    return {int(next(g for g in found.groups() if g)) for found in _SEASON_ONLY.finditer(text)}


def _episode_numbers(text: str) -> Set[int]:
    """Episode 5, E05 first, then 5. dil (Season 2 Episode 5 is not episode 2)."""
    return {int(n) for n in _EPISODE_AFTER.findall(text)} or {int(n) for n in _EPISODE_BEFORE.findall(text)}


def _all_tags(text: str) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]], Set[int], Set[int]]:
    """SxxEyy episodes, all episodes, season tags and episode numbers without a season of a folded name."""
    sxe = _sxe_tags(text)
    episodes = sxe | _x_tags(text)
    if episodes:
        return sxe, episodes, set(), set()
    seasons, numbers = _season_tags(text), _episode_numbers(text)
    if len(seasons) == 1 and numbers:
        # Season 2 Episode 5, 2. serie 5. dil
        return sxe, {(season, number) for season in seasons for number in numbers}, set(), set()
    return sxe, episodes, seasons, numbers


def parse_episode_tags(name: str) -> Tuple[Set[Tuple[int, int]], Set[int]]:
    """Episodes as (season, episode) - S01E02, s01.e02, S01 E02, 1x02, ranges S01E01-E03, S01E01E02, 1x02-03,
    Season 1 Episode 2 - and bare season tags (S02, Season 2, 2. rada) of a name."""
    _, episodes, seasons, _ = _all_tags(_separators(fold_text(name)))
    return episodes, seasons


def parse_episode_numbers(name: str) -> Set[int]:
    """Episode numbers without a season (E05, ep05, 2. dil, 1dil) when the name has no full episode tag."""
    return _all_tags(_separators(fold_text(name)))[3]


def _osa_distance(a: str, b: str, limit: int) -> int:
    """Optimal string alignment distance (typos incl. swapped letters), limit + 1 when above limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous2: List[int] = []
    previous = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], previous2[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        previous2, previous = previous, current
    return previous[-1]


class _FileName:
    """Words of a file name with the separators ( - [ ( ) before them, positions for title matching and tags."""

    def __init__(self, name: str):
        self.name = name or ""
        text = _separators(fold_text(_EXTENSION.sub("", self.name)))
        self.tokens: List[str] = []
        self.boundary_before: List[bool] = []
        self.in_brackets: List[bool] = []
        self.decimal: List[bool] = []
        depth = 0
        pending_boundary = False
        for found in _TOKEN.finditer(text):
            raw = found.group()
            if raw[0].isalnum():
                start, end = found.span()
                self.tokens.append(raw)
                self.boundary_before.append(pending_boundary)
                self.in_brackets.append(depth > 0)
                self.decimal.append((start >= 2 and text[start - 1] == "." and text[start - 2].isdigit())
                                    or (text[end:end + 1] == "." and text[end + 1:end + 2].isdigit()))
                pending_boundary = False
            else:
                pending_boundary = True
                if raw in "[({":
                    depth += 1
                elif raw in "])}":
                    depth = max(0, depth - 1)
        self.compact = "".join(self.tokens)
        self.positions: Dict[str, List[int]] = {}
        for index, token in enumerate(self.tokens):
            self.positions.setdefault(token, []).append(index)
        for index, token in enumerate(self.tokens):
            if not token.isalpha() and not token.isdigit():
                # Island2, 1Island
                for part in re.findall(r"[^\W\d_]{2,}|\d+", token):
                    if part != token:
                        self.positions.setdefault(part, []).append(index)
        self.joined: Dict[str, int] = {}
        for index in range(len(self.tokens) - 1):
            self.joined.setdefault(self.tokens[index] + self.tokens[index + 1], index)
        self.sxe, self.episodes, self.seasons, self.episode_numbers = _all_tags(_separators(fold_text(self.name)))
        self.lead = self._lead_start()
        first = self.tokens[0] if self.tokens and not self.in_brackets[0] else ""
        self.leading_number = int(first) if first.isdigit() and len(first) <= 3 else 0

    def _lead_start(self) -> int:
        """Index of the first word after leading [group] tags and track numbers."""
        index = 0
        while index < len(self.tokens) and (self.in_brackets[index] or self.tokens[index].isdigit()):
            if not self.in_brackets[index] and _YEAR.match(self.tokens[index]):
                break
            index += 1
        return index

    def years(self, ignore: Set[str]) -> List[int]:
        return [int(t) for t in self.tokens if _YEAR.match(t) and t not in ignore]

    def number_at(self, index: int) -> int:
        """Small number or Roman numeral at a position (sequel or episode number), 0 otherwise."""
        if index >= len(self.tokens) or self.decimal[index]:
            return 0
        return _number_value(self.tokens[index])


def _number_value(token: str) -> int:
    if token.isdigit():
        return int(token) if len(token) <= 2 else 0
    return ROMAN.get(token, 0) if len(token) > 1 else 0


class _Title:
    """One title variant: its distinct words with weights (articles and stop words count less, digits fully)."""

    def __init__(self, title: str, weight: float = 1.0):
        self.text = title
        self.weight = weight
        self.tokens: List[str] = []
        for token in tokenize(title):
            if token not in self.tokens:
                self.tokens.append(token)
        significant = [t for t in self.tokens if not self._is_minor(t)]
        self.weights = {t: 1.0 for t in self.tokens}
        if significant:
            for t in self.tokens:
                if self._is_minor(t):
                    self.weights[t] = 0.3
            if self.tokens[0] in ARTICLES:
                self.weights[self.tokens[0]] = 0.1
        self.total = sum(self.weights.values())
        self.significant = len(significant) or len(self.tokens)
        self.fuzzy_allowed = len(significant) >= 2
        self.numbers = {t for t in self.tokens if t.isdigit() or (t in ROMAN and len(t) > 1)}

    @staticmethod
    def _is_minor(token: str) -> bool:
        return token in STOPWORDS or (len(token) == 1 and not token.isdigit())


class _TitleMatch:
    __slots__ = ("coverage", "start", "end", "title")

    def __init__(self, coverage: float, start: int, end: int, title: _Title):
        self.coverage, self.start, self.end, self.title = coverage, start, end, title

    @property
    def strength(self) -> float:
        return self.coverage * self.title.weight


@lru_cache(maxsize=1024)
def _file_name(name: str) -> _FileName:
    return _FileName(name)


@lru_cache(maxsize=128)
def _title_variants(texts: Tuple[str, ...], movie: bool) -> Tuple[_Title, ...]:
    """Each title, its part before a subtitle (weighted less) and the Hepburn form of a Czech transcription.
    A movie title before a subtitle needs two words or a number: "Island" of "Island: The Return" is the first film."""
    titles: List[_Title] = []
    seen: Set[Tuple[str, ...]] = set()
    for text in texts:
        if not text:
            continue
        hepburn = czech_to_hepburn(text)
        for variant, weight in ((text, 1.0), (_main_part(text), MAIN_PART_WEIGHT), (hepburn, 1.0),
                                (_main_part(hepburn), MAIN_PART_WEIGHT)):
            key = tuple(tokenize(variant))
            if not key or key in seen:
                continue
            title = _Title(variant, weight)
            if movie and weight < 1.0 and title.significant < 2 and not title.numbers:
                continue
            seen.add(key)
            titles.append(title)
    return tuple(titles)


def _vocabulary(titles: Iterable[_Title]) -> Set[str]:
    return {token for title in titles for token in title.tokens}


def _token_position(token: str, file: _FileName, allow_fuzzy: bool) -> Tuple[float, int]:
    """Match strength (1, FUZZY_MATCH or 0) of one title word and its position in the file name."""
    if token in file.positions:
        return 1.0, file.positions[token][0]
    numeral = _ROMAN_OF.get(token) or (str(ROMAN[token]) if token in _ROMAN_OF.values() else "")
    if numeral in file.positions:
        return 1.0, file.positions[numeral][0]
    if token in file.joined:
        return 1.0, file.joined[token]
    if not _LATIN.search(token):
        # scripts without spaces between words (Japanese, Chinese): part of the name
        return (1.0, 0) if token in file.compact else (0.0, -1)
    if allow_fuzzy and len(token) >= 3 and not token.isdigit():
        limit = 1 if len(token) < 8 else 2
        for candidate, places in file.positions.items():
            if (candidate.isdigit() or candidate in TECH_TOKENS or abs(len(candidate) - len(token)) > limit
                    or (len(token) == 3 and len(candidate) <= 3)):
                continue
            if _osa_distance(token, candidate, limit) <= limit:
                return FUZZY_MATCH, places[0]
    return 0.0, -1


def _match_title(title: _Title, file: _FileName) -> Optional[_TitleMatch]:
    """Weighted share of the title words found in the name, in any order. Typos next to an exact word
    or in long words (inflected ostrovy / ostrov)."""
    if not title.tokens:
        return None
    found = {token: _token_position(token, file, allow_fuzzy=False) for token in title.tokens}
    if title.fuzzy_allowed:
        anchored = any(found[t][0] == 1.0 and title.weights[t] == 1.0 for t in title.tokens)
        for token, value in found.items():
            if value[0] == 0.0 and (anchored or len(token) >= FUZZY_ALONE_LENGTH):
                found[token] = _token_position(token, file, allow_fuzzy=True)
    for first, second in zip(title.tokens, title.tokens[1:]):
        if (found[first][0] == 0.0 or found[second][0] == 0.0) and first + second in file.positions:
            found[first] = found[second] = (1.0, file.positions[first + second][0])
    places = [position for strength, position in found.values() if strength > 0]
    if not places:
        return _TitleMatch(0.0, -1, -1, title)
    coverage = sum(title.weights[t] * found[t][0] for t in title.tokens) / title.total
    significant = [found[t][1] for t in title.tokens if found[t][0] > 0 and title.weights[t] == 1.0] or places
    return _TitleMatch(coverage, min(significant), max(places), title)


def _best_title(titles: Sequence[_Title], file: _FileName) -> Optional[_TitleMatch]:
    best: Optional[_TitleMatch] = None
    for title in titles:
        result = _match_title(title, file)
        if result and (best is None or result.strength > best.strength
                       or (result.strength == best.strength and result.start < best.start)):
            best = result
    return best


def _title_points(match: Optional[_TitleMatch], full: int) -> float:
    if not match or match.coverage <= 0:
        return 0.0
    return full * match.title.weight * match.coverage ** 2


def _explained(token: str, vocabulary: Set[str]) -> bool:
    return (token in vocabulary or token in TECH_TOKENS or token in STOPWORDS or token.isdigit()
            or len(token) <= 1 or bool(_YEAR.match(token)) or bool(_TECHNICAL.match(token)))


def _extra_words(file: _FileName, match: _TitleMatch, vocabulary: Set[str]) -> float:
    """Share of unknown words before the title and right after it ("Island Matter", "Return to the Island")
    among the title words: one word more is a lot for a one-word title."""
    lead = sum(1 for index in range(file.lead, max(file.lead, match.start))
               if not file.in_brackets[index] and not _explained(file.tokens[index], vocabulary))
    after = 0
    index = match.end + 1
    while index < len(file.tokens) and after < EXTRA_WORDS_MAX:
        token = file.tokens[index]
        if file.boundary_before[index] or file.in_brackets[index] or token in PART_MARKERS:
            break
        if token in STOPWORDS or (token in vocabulary and token not in TECH_TOKENS):
            pass
        elif _explained(token, vocabulary):
            break
        else:
            after += 1
        index += 1
    extra = lead + after
    return extra / (extra + match.title.significant) if extra else 0.0


def _other_part(file: _FileName, match: _TitleMatch) -> int:
    """Points for a sequel number right after the title (Island 2, Island II.) or a part marker (Part Two,
    Island 2. část - a number before the marker is a part too, not a sequel)."""
    if match.title.numbers:
        return 0
    value = file.number_at(match.end + 1)
    if value >= 2:
        following = match.end + 2
        if following < len(file.tokens) and file.tokens[following] in PART_MARKERS:
            return OTHER_PART_MARKER
        return OTHER_PART
    if value == 1:
        return 0
    for index in range(match.end + 1, len(file.tokens) - 1):
        if file.tokens[index] in PART_MARKERS:
            following = file.tokens[index + 1]
            if (file.number_at(index + 1) or NUMBER_WORDS.get(following, 0)) >= 2:
                return OTHER_PART_MARKER
    return 0


def _quality_points(name: str, divisor: int) -> int:
    return parse_quality(name)["quality_score"] // divisor


def score_movie_result(file_info: Dict[str, Any], params: Dict[str, Any]) -> int:
    name = str(file_info.get("name") or "")
    file = _file_name(name)
    titles = _title_variants((_first_non_empty(params, MOVIE_TITLE_KEYS), _first_non_empty(params, MOVIE_ORIGINAL_KEYS),
                              _first_non_empty(params, MOVIE_ENGLISH_KEYS)), True)
    year = _as_int(str(params.get("year") or "")[:4])
    best = _best_title(titles, file)
    score = _title_points(best, MOVIE_TITLE_POINTS)

    title_ok = bool(best) and best.coverage >= TITLE_OK
    vocabulary = _vocabulary(titles)
    extra = _extra_words(file, best, vocabulary) if title_ok else 0.0
    years = file.years(ignore={t for t in vocabulary if _YEAR.match(t)})
    if year and years:
        if year in years:
            if title_ok:
                score += YEAR_MATCH * (1.0 - extra)
            elif best and best.coverage >= PARTIAL_TITLE:
                score += YEAR_MATCH * best.strength
        elif any(abs(year - y) == 1 for y in years):
            score += YEAR_NEAR * (1.0 - extra) if title_ok else 0
        else:
            score += YEAR_OTHER
    if title_ok:
        score += _other_part(file, best) + EXTRA_WORDS * extra
    if file.episodes:
        score += EPISODE_IN_MOVIE
    elif file.seasons:
        score += SEASON_IN_MOVIE

    if _has_bad_tokens(name, vocabulary):
        score += BAD_TOKEN
    score += _quality_points(name, 4)
    return int(round(score))


def _absolute_number(file: _FileName, match: _TitleMatch, vocabulary: Set[str]) -> int:
    """Episode number right after the full show title followed by tags, a separator or the episode title
    (anime "[Group] Title - 01 [hash]", "Title 1.avi", "Title 05 - Episode name"),
    not "Title 1 Subtitle" of a film series."""
    index = match.end + 1
    if match.title.weight < 1.0 or index >= len(file.tokens) or file.decimal[index]:
        return 0
    token = file.tokens[index]
    if not token.isdigit() or len(token) > 3:
        return 0
    following = index + 1
    if following < len(file.tokens):
        next_token = file.tokens[following]
        if not (file.in_brackets[following] or file.boundary_before[following] or next_token in TECH_TOKENS
                or next_token in vocabulary or _YEAR.match(next_token)):
            return 0
    return int(token)


def score_episode_result(file_info: Dict[str, Any], params: Dict[str, Any]) -> int:
    name = str(file_info.get("name") or "")
    file = _file_name(name)
    titles = _title_variants((_first_non_empty(params, SHOW_KEYS), _first_non_empty(params, SHOW_ORIGINAL_KEYS),
                              _first_non_empty(params, SHOW_ENGLISH_KEYS)), False)
    episode_texts = (_first_non_empty(params, EPISODE_TITLE_KEYS), _first_non_empty(params, ["episode_title_en"]))
    episode_titles = [_Title(t) for t in episode_texts if t and _specific_episode_title(t)]
    season, episode = _season_episode(params)

    best = _best_title(titles, file)
    score = _title_points(best, EPISODE_SHOW_POINTS)
    show_ok = bool(best) and best.coverage >= TITLE_OK
    vocabulary = _vocabulary(titles) | _vocabulary(episode_titles)
    episode_match = _best_title(episode_titles, file)
    episode_title_ok = bool(episode_match) and episode_match.coverage >= TITLE_OK
    # The episode title stands in for a missing show title ("S01E05 - Episode name.mkv" in a show folder)
    show_factor = 1.0 if show_ok or episode_title_ok else NO_SHOW_FACTOR

    if season >= 0 and episode > 0:
        if (season, episode) in file.episodes:
            score += (TAG_MATCH if (season, episode) in file.sxe else TAG_MATCH + TAG_X_LESS) * show_factor
        elif file.episodes:
            score += TAG_OTHER
        elif file.seasons and season not in file.seasons:
            score += SEASON_OTHER
        else:
            numbers = set(file.episode_numbers)
            if show_ok:
                numbers.add(_absolute_number(file, best, vocabulary))
            if show_ok or episode_title_ok:
                numbers.add(file.leading_number)
            numbers.discard(0)
            if episode in numbers:
                score += ABSOLUTE_MATCH * (1.0 if season == 1 else 0.5) * show_factor
            elif numbers:
                score += ABSOLUTE_OTHER

    if episode_title_ok:
        points = EPISODE_TITLE_POINTS * episode_match.coverage ** 2
        if episode_match.title.significant < 2:
            points /= 2 if show_ok else 4
        score += points

    if show_ok:
        score += EXTRA_WORDS * _extra_words(file, best, vocabulary)

    if _has_bad_tokens(name, vocabulary):
        score += BAD_TOKEN
    score += _quality_points(name, 5)
    return int(round(score))


_DISC_PART = re.compile(r"(?<![a-z0-9])(?:cd|disc|disk)\s?[1-9](?![0-9])|(?<![a-z0-9])[1-9]\s?(?:of|z)\s?[2-9](?![0-9a-z])")


def autoplay_concern(file_info: Dict[str, Any], params: Dict[str, Any]) -> str:
    """Why a file should not be played without asking: "extra" (trailer, sample, making of …), "part"
    (CD1, disc 2, 1of2 of a film) or "year" (a film year far from the wanted one: a remake or another film);
    "" when the name gives no reason. Scoring is not affected."""
    name = str(file_info.get("name") or "")
    episode = str(params.get("mediatype") or "").lower() == "episode"
    if episode:
        titles = _title_variants((_first_non_empty(params, SHOW_KEYS), _first_non_empty(params, SHOW_ORIGINAL_KEYS),
                                  _first_non_empty(params, SHOW_ENGLISH_KEYS)), False)
    else:
        titles = _title_variants((_first_non_empty(params, MOVIE_TITLE_KEYS), _first_non_empty(params, MOVIE_ORIGINAL_KEYS),
                                  _first_non_empty(params, MOVIE_ENGLISH_KEYS)), True)
    vocabulary = _vocabulary(titles)
    if _has_bad_tokens(name, vocabulary):
        return "extra"
    if episode:
        return ""
    if _DISC_PART.search(_separators(fold_text(_EXTENSION.sub("", name)))):
        return "part"
    year = _as_int(str(params.get("year") or "")[:4])
    years = _file_name(name).years(ignore={t for t in vocabulary if _YEAR.match(t)})
    if year and years and all(abs(year - other) > 1 for other in years):
        return "year"
    return ""


def rank_files(results_per_query: Sequence[Sequence[Dict[str, Any]]], match: Dict[str, Any],
               preference: str = "") -> List[Dict[str, Any]]:
    """Files of all queries (the first occurrence of an ident counts) sorted by the match score, equal scores
    keep the query order. The language preference adds LANG_PREF_BONUS for sorting only, "score" is the match score."""
    episode = str(match.get("mediatype") or "").lower() == "episode"
    seen: Set[str] = set()
    rows: List[Tuple[int, int, Dict[str, Any]]] = []
    for files in results_per_query:
        for file_info in files or []:
            ident = file_info.get("ident")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            score = score_episode_result(file_info, match) if episode else score_movie_result(file_info, match)
            bonus = LANG_PREF_BONUS if preference and matches_language_preference(normalize_source(file_info), preference) else 0
            rows.append((score + bonus, score, file_info))
    rows.sort(key=lambda row: row[0], reverse=True)
    return [dict(file_info, score=score) for _, score, file_info in rows]
