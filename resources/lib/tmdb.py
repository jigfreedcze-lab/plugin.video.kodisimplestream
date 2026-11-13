import unicodedata
from typing import Literal, Dict, List

import requests


class TMDBAuthError(Exception):
    """TMDb rejected the API key (HTTP 401)."""


class TMDB:
    """
    Client for The Movie Database API (https://developer.themoviedb.org/)

    Returns the same structures as the former CSFD scraper. IDs carry the media
    type ("movie:603", "tv:1399"), because TMDb numbers movies and series separately.
    """
    BASE_URL = "https://api.themoviedb.org/3/"
    IMAGE_URL = "https://image.tmdb.org/t/p/w500"

    def __init__(self, api_key: str, language: str = "cs-CZ", timeout: float = 15):
        # Users often copy the v4 token including the "Bearer " prefix
        parts = (api_key or "").split(None, 1)
        if parts and parts[0].lower() == "bearer":
            parts = parts[1:]
        api_key = parts[0].strip() if parts else ""
        if not api_key:
            raise ValueError("TMDb API key is not set")
        self._api_key = api_key
        self._language = language
        self._timeout = timeout
        # tv/{id} downloaded by get_detail() also contains seasons – reuse it in get_seasons()
        self._details: Dict[str, Dict] = {}

    def _get(self, path: str, **params) -> Dict:
        params.setdefault("language", self._language)
        headers = {"Accept": "application/json"}
        # v4 Read Access Token is a long JWT, v3 API key is 32 hex characters
        if len(self._api_key) > 40:
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            params["api_key"] = self._api_key
        response = requests.get(self.BASE_URL + path, params=params, headers=headers, timeout=self._timeout)
        if response.status_code == 401:
            raise TMDBAuthError("TMDb rejected the API key")
        if response.status_code >= 400:
            raise Exception(f"TMDb request {path} failed\nStatus code: {response.status_code}\nResponse: {response.text[:200]}")
        return response.json()

    @staticmethod
    def _is_latin(text: str) -> bool:
        """True when all letters are Latin – such title makes sense as a Webshare query."""
        return all(unicodedata.name(ch, "").startswith("LATIN") for ch in text if ch.isalpha())

    @staticmethod
    def _split_id(full_id: str):
        kind, _, tmdb_id = full_id.partition(":")
        if kind not in ("movie", "tv") or not tmdb_id:
            raise ValueError(f"Invalid TMDb id: {full_id}")
        return kind, tmdb_id

    def _to_result(self, item: Dict, kind: str) -> Dict:
        title = item.get("title") or item.get("name")
        original_title = item.get("original_title") or item.get("original_name")
        date = item.get("release_date") or item.get("first_air_date") or ""
        poster_path = item.get("poster_path")
        rating = item.get("vote_average")
        return {
            'id': f"{kind}:{item['id']}",
            'type': "movie" if kind == "movie" else "series",
            'title': title,
            'original_title': original_title if original_title != title else None,
            'year': date[:4] or None,
            'rating': round(rating, 1) if rating else None,
            'genres': [g["name"] for g in item.get("genres", [])],
            'plot': item.get("overview") or None,
            'poster': self.IMAGE_URL + poster_path if poster_path else None,
        }

    def search(self, query: str, type: Literal["movie", "series"] = "movie") -> List[Dict]:
        kind = "movie" if type == "movie" else "tv"
        data = self._get(f"search/{kind}", query=query, include_adult="false")
        return [self._to_result(item, kind) for item in data.get("results", [])]

    @staticmethod
    def _english_title(data: Dict) -> str:
        """English title from translations – US first, then any other non-empty English one."""
        english = [t for t in data.get("translations", {}).get("translations", []) if t.get("iso_639_1") == "en"]
        english.sort(key=lambda t: t.get("iso_3166_1") != "US")
        for translation in english:
            title = translation.get("data", {}).get("title") or translation.get("data", {}).get("name")
            if title:
                return title
        return ""

    def english_title(self, full_id: str) -> str:
        """English title of a movie or series ("movie:372058", "tv:1429"), "" without an English translation."""
        kind, tmdb_id = self._split_id(full_id)
        return self._english_title({"translations": self._get(f"{kind}/{tmdb_id}/translations")})

    def get_detail(self, full_id: str) -> Dict:
        kind, tmdb_id = self._split_id(full_id)
        data = self._get(f"{kind}/{tmdb_id}", append_to_response="translations")
        self._details[full_id] = data
        details = self._to_result(data, kind)

        # Titles in Japanese, Cyrillic etc. are useless for Webshare – use the English one.
        # Without a Czech translation TMDb returns the original title also in "title".
        title, original_title = details['title'], details['original_title']
        if not self._is_latin(title or "") or (original_title and not self._is_latin(original_title)):
            english = self._english_title(data)
            if not self._is_latin(title or "") and english:
                title = english
            if original_title and not self._is_latin(original_title):
                original_title = None
            if english and english != title and not original_title:
                original_title = english
            details['title'], details['original_title'] = title, original_title
        # Minutes, for the length check of the found files (movie/{id} has it already, no extra request);
        # series give their usual episode length only, the episodes have their own (get_episodes)
        details['runtime'] = data.get("runtime") if kind == "movie" else None
        return details

    def get_seasons(self, full_id: str) -> List[Dict]:
        kind, tmdb_id = self._split_id(full_id)
        data = self._details.get(full_id) or self._get(f"{kind}/{tmdb_id}")
        seasons = []
        for season in data.get("seasons", []):
            number = season.get("season_number")
            # Season 0 holds specials, they are not searchable by SxxEyy
            if not number:
                continue
            seasons.append({
                'id': str(number),
                'number': number,
                'title': season.get("name") or f"Season {number}",
                'year': (season.get("air_date") or "")[:4] or None,
                'episode_count': season.get("episode_count"),
            })
        seasons.sort(key=lambda x: x['number'])
        return seasons

    def get_episodes(self, full_id: str, season_id: str) -> List[Dict]:
        kind, tmdb_id = self._split_id(full_id)
        data = self._get(f"{kind}/{tmdb_id}/season/{season_id}")
        episodes = []
        for episode in data.get("episodes", []):
            episodes.append({
                'id': str(episode.get("id")),
                'title': episode.get("name") or "",
                'season': episode.get("season_number"),
                'number': episode.get("episode_number"),
                'runtime': episode.get("runtime"),  # minutes, None when TMDb does not know it
            })
        episodes.sort(key=lambda x: x['number'] or 0)
        return episodes

    # --- kids search helpers (raw TMDb data) ---

    def search_raw(self, query: str, kind: str, page: int = 1) -> List[Dict]:
        """Raw TMDb search results of search/{movie|tv} without adult titles."""
        if kind not in ("movie", "tv"):
            raise ValueError(f"Invalid TMDb kind: {kind}")
        data = self._get(f"search/{kind}", query=query, include_adult="false", page=page)
        return data.get("results", [])

    def details_with_ratings(self, kind: str, tmdb_id) -> Dict:
        """Details with certifications appended: release_dates (movie) or content_ratings (tv)."""
        if kind not in ("movie", "tv"):
            raise ValueError(f"Invalid TMDb kind: {kind}")
        append = "release_dates" if kind == "movie" else "content_ratings"
        return self._get(f"{kind}/{tmdb_id}", append_to_response=append)

    def find_by_imdb(self, imdb_id: str, kind: str):
        """TMDb id (int) of the movie or series (kind "movie" | "tv") with this IMDb id, None when TMDb does not know it.
        For a series an episode IMDb id leads to the series too."""
        if kind not in ("movie", "tv"):
            raise ValueError(f"Invalid TMDb kind: {kind}")
        data = self._get(f"find/{imdb_id}", external_source="imdb_id")
        if kind == "movie":
            found = (data.get("movie_results") or [{}])[0].get("id")
        else:
            found = (data.get("tv_results") or [{}])[0].get("id") or (data.get("tv_episode_results") or [{}])[0].get("show_id")
        return found if isinstance(found, int) and not isinstance(found, bool) else None

    def details_extras(self, kind: str, tmdb_id) -> Dict:
        """Posters and translations of a title (heavy, so only for titles that are listed)."""
        if kind not in ("movie", "tv"):
            raise ValueError(f"Invalid TMDb kind: {kind}")
        # posters in Czech, Slovak, English, then language-less ones; kids._best_poster picks in that order
        # (without the filter TMDb would show the original, e.g. Japanese, poster)
        return self._get(f"{kind}/{tmdb_id}", append_to_response="images,translations",
                         include_image_language="cs,sk,en,null")
