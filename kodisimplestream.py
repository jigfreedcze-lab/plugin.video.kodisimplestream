# -*- coding: utf-8 -*-
# Module: kodisimplestream
# Author: Kecerim24
# Created on: 28.04.2025
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html

from __future__ import annotations  # Enables forward references in older Python versions

# Kodi plugin boilerplate and plugin-specific modules
import ast
import os
import sys
from typing import Any, Dict, List, Optional

import re
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib.webshare import WebshareAPI
from resources.lib.csfd import CSFD
from resources.lib.source_ui import (
    compact_label,
    language_tag,
    matches_language_preference,
    metadata_line,
    normalize_source,
    source_icon_name,
    source_title_label,
)
from resources.lib.matching import (
    build_tmdbh_queries,
    parse_quality,
    parse_size,
    score_episode_result,
    score_movie_result,
)

# ----------------------------------------------------------------------------
# Global variables – provided by Kodi during plugin initialization
# ----------------------------------------------------------------------------
_url: str = sys.argv[0]
_handle: int = int(sys.argv[1])
_addon: xbmcaddon.Addon = xbmcaddon.Addon()
_api: Optional[WebshareAPI] = None

# ----------------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------------

def get_url(**kwargs: Any) -> str:
    """Returns a plugin URL with encoded parameters for recursive calls."""
    return f"{_url}?{urlencode(kwargs)}"


def _icon_path(filename: str) -> str:
    """Resolve a bundled image from the add-on icons directory."""
    if not filename:
        return ""
    return os.path.join(_addon.getAddonInfo("path"), "icons", filename)


def _resolution_badge_art(source: Dict[str, Any], fallback_image: str = "") -> Dict[str, str]:
    """Artwork for source rows, using bundled resolution badges as primary art."""
    badge = _icon_path(source_icon_name(source))
    return {
        "icon": badge,
        "thumb": badge,
        "poster": badge,
        "fanart": fallback_image or badge,
    }

# Index of the "lang_pref" setting → preference understood by matches_language_preference()
LANG_PREFS = ["", "cz_audio", "cz_subs"]
# Bonus to the TMDb Helper match score when sorting, the shown score stays unchanged
LANG_PREF_BONUS = 15

def language_preference() -> str:
    """Returns the preferred language variant from add-on settings ("" = no preference)."""
    try:
        index = int(_addon.getSetting("lang_pref") or 0)
    except ValueError:
        index = 0
    return LANG_PREFS[index] if 0 <= index < len(LANG_PREFS) else ""

def _source_label(source: Dict[str, Any]) -> str:
    """Title label with a Czech/Slovak dub or subtitles tag in front, e.g. "[CZ dabing] Film"."""
    title = source_title_label(source)
    lang, kind = language_tag(source)
    if not lang:
        return title
    word = _addon.getLocalizedString(30042 if kind == "audio" else 30043)  # "dabing" / "titulky"
    return f"[{lang} {word}] {title}"

def get_api() -> Optional[WebshareAPI]:
    """
    Returns an authenticated instance of WebshareAPI.
    Shows error notification on failure.
    """
    global _api

    if _api is not None:
        return _api

    username: str = _addon.getSetting("username")
    password: str = _addon.getSetting("password")

    if not (username and password):
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30009),  # "Please enter username and password…"
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return None

    try:
        _api = WebshareAPI()
        _api.login(username, password)
        if not getattr(_api, "_token", ""):
            raise RuntimeError("Webshare returned an empty token – check credentials.")
        return _api
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30006).format(str(exc)),  # "Login failed…"
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return None

# ----------------------------------------------------------------------------
# Root menu
# ----------------------------------------------------------------------------

def list_categories() -> None:
    """Creates items for the plugin's main menu."""
    for action, label_id in (
        ("search_webshare", 30011),
        ("search_csfd_movie", 30012),
        ("search_csfd_series", 30013),
    ):
        item = xbmcgui.ListItem(label=_addon.getLocalizedString(label_id))
        item.setArt({"icon": "DefaultAddonsSearch.png"})
        xbmcplugin.addDirectoryItem(_handle, get_url(action=action), item, isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

# ----------------------------------------------------------------------------
# Playback
# ----------------------------------------------------------------------------

def play_video(path: str) -> None:
    """Passes the video URL to Kodi’s internal player."""
    xbmcplugin.setResolvedUrl(_handle, True, xbmcgui.ListItem(path=path))

# ----------------------------------------------------------------------------
# Webshare: search & listing
# ----------------------------------------------------------------------------

PAGE_SIZE = 30
# Index of the "ws_sort" setting → Webshare API "sort" value.
# "" (no sort) orders by match with the query – undocumented, but it is the API default.
SORT_VALUES = ["", "rating", "recent", "largest", "smallest"]
SORT_LABELS = [30030, 30031, 30032, 30033, 30034]

def default_sort() -> int:
    """Returns the default sort index from add-on settings."""
    try:
        index = int(_addon.getSetting("ws_sort") or 0)
    except ValueError:
        index = 0
    return index if 0 <= index < len(SORT_VALUES) else 0

def _as_list(value: Any) -> List[Any]:
    """xmltodict returns a dict for a single <file>, a list for more and nothing for none."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def list_search_results(
    search_terms: List[str],
    sort: Optional[int] = None,
    offset: int = 0,
    replace: bool = False,
) -> None:
    """
    Displays one page of search results for a list of search terms using WebshareAPI.
    The same file found by more terms is shown once, the download link is resolved on playback.
    """
    api = get_api()
    if not api:
        return
    if sort is None or not 0 <= sort < len(SORT_VALUES):
        sort = default_sort()
    offset = max(0, offset)

    try:
        seen = set()
        rows = []
        has_more = False
        next_offset = offset + PAGE_SIZE
        for term in search_terms:
            response = api.search(term, limit=PAGE_SIZE, offset=offset, sort=SORT_VALUES[sort])["response"]
            files = _as_list(response.get("file"))
            # "total" is unreliable for small result sets, trust it only after a full page
            if len(files) == PAGE_SIZE and int(response.get("total", 0)) > next_offset:
                has_more = True

            for file_info in files:
                ident = file_info.get("ident")
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                rows.append(file_info)

        if not rows and offset:
            xbmcgui.Dialog().notification(
                _addon.getAddonInfo("name"),
                _addon.getLocalizedString(30041),  # "No more results"
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
            # Kodi goes back to the previous page
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
            return
        if not rows:
            xbmcgui.Dialog().notification(
                _addon.getAddonInfo("name"),
                _addon.getLocalizedString(30007).format(_addon.getLocalizedString(30008)),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )

        # Sort switch on top – applies only to this search, the default is in settings
        item = xbmcgui.ListItem(label=_addon.getLocalizedString(30037).format(_addon.getLocalizedString(SORT_LABELS[sort])))
        item.setArt({"icon": "DefaultAddonsSearch.png", "thumb": "DefaultAddonsSearch.png"})
        item.setProperty("SpecialSort", "top")
        url = get_url(action="choose_sort", query=str(search_terms), sort=sort)
        xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=False)

        sources = [(file_info, normalize_source(file_info)) for file_info in rows]
        preference = language_preference()
        if preference:
            # Preferred dub/subtitles first, otherwise keep the Webshare order (stable sort)
            sources.sort(key=lambda pair: not matches_language_preference(pair[1], preference))

        for file_info, source in sources:
            item = xbmcgui.ListItem(
                label=_source_label(source),
                label2=metadata_line(source, include_score=True, include_quality=True),
            )
            item.setInfo("video", {
                "title": source.get("title") or file_info.get("name", ""),
                "size": source.get("size_bytes", 0),
                "mediatype": "video",
            })
            item.setArt(_resolution_badge_art(source, file_info.get("img", "")))
            xbmc.log(
                f"[KodiSimpleStream] normalized Webshare source quality={source['quality_label']} "
                f"resolution={source['resolution_label']} name={source['original_name']}",
                xbmc.LOGDEBUG,
            )
            item.setProperty("IsPlayable", "true")
            xbmcplugin.addDirectoryItem(_handle, get_url(action="play_ident", ident=file_info["ident"]), item, isFolder=False)

        if has_more:
            item = xbmcgui.ListItem(label=_addon.getLocalizedString(30038).format(next_offset // PAGE_SIZE + 1))
            item.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
            item.setProperty("SpecialSort", "bottom")
            url = get_url(action="list_search_results", query=str(search_terms), sort=sort, offset=next_offset)
            xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=True)

        # Kodi sorting (side menu) only reorders the loaded page
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_SIZE)
        xbmcplugin.setContent(_handle, "videos")
        # replace: a new order of the same search takes the place of the old one in history
        xbmcplugin.endOfDirectory(_handle, updateListing=replace)
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30007).format(str(exc)),
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )

def choose_sort(search_terms: List[str], current: int) -> None:
    """Lets the user pick a different order for the current search and reloads the list."""
    labels = [_addon.getLocalizedString(label_id) for label_id in SORT_LABELS]
    selected = xbmcgui.Dialog().select(_addon.getLocalizedString(30039), labels, preselect=current)
    if 0 <= selected != current:
        url = get_url(action="list_search_results", query=str(search_terms), sort=selected, replace=1)
        xbmc.executebuiltin(f"Container.Update({url})")
    # Opened as a folder or by the Play button – close it and stay in the list
    if _handle >= 0:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

# ----------------------------------------------------------------------------
# Generic input dialog for searching
# ----------------------------------------------------------------------------

def _keyboard_search(label_id: int) -> Optional[str]:
    """Displays Kodi’s virtual keyboard and returns input text if confirmed."""
    keyboard = xbmc.Keyboard("", _addon.getLocalizedString(label_id))
    keyboard.doModal()
    return keyboard.getText() if keyboard.isConfirmed() else None

# ----------------------------------------------------------------------------
# Webshare – search dialog entry point
# ----------------------------------------------------------------------------

def search_webshare() -> None:
    """Handles interactive Webshare search via on-screen keyboard."""
    term = _keyboard_search(30001)
    if term:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30002).format(term),
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        list_search_results([term])

# ----------------------------------------------------------------------------
# CSFD – search results
# ----------------------------------------------------------------------------

def list_csfd_results(results: List[Dict[str, Any]], search_type: str) -> None:
    """Displays CSFD search results as Kodi menu items."""
    for result in results:
        title = result["title"]
        year = result.get("year")
        label = f"{title} ({year})" if year else title

        item = xbmcgui.ListItem(label=label)
        item.setInfo("video", {
            "title": title,
            "year": year,
            "plot": result.get("plot"),
            "rating": result.get("rating"),
        })
        item.setArt({"poster": result.get("poster", ""), "fanart": result.get("poster", "")})

        url = get_url(action="select_csfd", csfd_id=result["id"], search_type=search_type)
        xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

# ----------------------------------------------------------------------------
# CSFD – selection and detailed episode listing
# ----------------------------------------------------------------------------

def handle_csfd_selection(csfd_id: str, search_type: str) -> None:
    """Handles selection from CSFD and delegates search or episode listing."""
    csfd = CSFD()
    details = csfd.get_detail(csfd_id)

    if search_type == "movie":
        queries: List[str] = [f"{details['title']} {details['year']}"]
        if details.get("original_title") and details["original_title"] != details["title"]:
            queries.append(details["original_title"])
        list_search_results(queries)
        return

    # Series → show list of seasons
    seasons = csfd.get_seasons(csfd_id)
    list_seasons(seasons, details["title"], details.get("original_title"), csfd_id)

# ----------------------------------------------------------------------------
# CSFD – episode navigation
# ----------------------------------------------------------------------------

def list_seasons(
    seasons: List[Dict[str, Any]],
    series_title: str,
    original_title: Optional[str],
    csfd_id: str,
) -> None:
    """Displays list of seasons for a series."""
    for season in seasons:
        label = season["title"] if season["title"] != "Season" else f"Season {season['number']}"
        url = get_url(
            action="list_episodes",
            csfd_id=csfd_id,
            season_id=season["id"],
            series_title=series_title,
            original_title=original_title or "",
        )
        xbmcplugin.addDirectoryItem(_handle, url, xbmcgui.ListItem(label=label), isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

def list_episodes(
    csfd_id: str,
    season_id: str,
    series_title: str,
    original_title: str,
) -> None:
    """Displays episode list for a given season."""
    csfd = CSFD()
    episodes = csfd.get_episodes(csfd_id, season_id)

    for ep in episodes:
        season_no = ep.get("season") or 0
        ep_no = ep.get("number") or 0
        label = f"{ep_no}. {ep['title']}"

        queries: List[str] = [f"{series_title} S{season_no:02d}E{ep_no:02d}"]
        if original_title and original_title != series_title:
            queries.append(f"{original_title} S{season_no:02d}E{ep_no:02d}")

        url = get_url(action="list_search_results", query=str(queries))
        xbmcplugin.addDirectoryItem(_handle, url, xbmcgui.ListItem(label=label), isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

# ----------------------------------------------------------------------------
# CSFD – search entry points
# ----------------------------------------------------------------------------

def search_csfd_movie() -> None:
    """Search dialog for CSFD movie titles."""
    term = _keyboard_search(30014)
    if term:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30002).format(term),
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        results = CSFD().search(term, type="movie")
        list_csfd_results(results, "movie")

def search_csfd_series() -> None:
    """Search dialog for CSFD TV series titles."""
    term = _keyboard_search(30015)
    if term:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30002).format(term),
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        results = CSFD().search(term, type="series")
        list_csfd_results(results, "series")



def _prefer_quality_value(name: str) -> int:
    setting = (_addon.getSetting("tmdbh_prefer_quality") or "1080p_or_best").lower()
    order = {"2160p": 4, "1080p": 3, "720p": 2, "sd": 1}
    base = order.get(name, 0)
    if setting == "highest":
        return base
    if setting == "720p_or_best":
        return base if base >= 2 else 0
    # default 1080p_or_best
    return base if base >= 3 else 0


def search_and_score_tmdbh(params: Dict[str, Any], search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    api = get_api()
    if not api:
        return []

    queries = [search_query] if search_query else build_tmdbh_queries(params)
    if not queries:
        return []

    max_results = int(_addon.getSetting("tmdbh_max_results") or "20")
    mediatype = (params.get("mediatype") or "movie").lower()
    merged: Dict[str, Dict[str, Any]] = {}

    xbmc.log(f"[KodiSimpleStream] TMDbH queries: {queries}", xbmc.LOGINFO)

    for term in queries:
        try:
            # Best-match order: search words are OR-ed, other orders bring files sharing just one word
            response = api.search(term, sort="").get("response", {})
        except Exception as exc:
            xbmc.log(f"[KodiSimpleStream] search failed for term '{term}': {exc}", xbmc.LOGWARNING)
            continue

        files = response.get("file", [])
        if isinstance(files, dict):
            files = [files]

        for file_info in files:
            ident = file_info.get("ident")
            name = file_info.get("name", "")
            if not ident or not name:
                continue
            score = score_episode_result(file_info, params) if mediatype == "episode" else score_movie_result(file_info, params)
            quality = parse_quality(name)
            size_bytes = parse_size(file_info.get("size"))
            item = {
                "ident": ident,
                "name": name,
                "img": file_info.get("img", ""),
                "size": size_bytes,
                "quality": quality.get("quality", "sd"),
                "score": score,
                "quality_pref": _prefer_quality_value(quality.get("quality", "sd")),
            }
            source = normalize_source(item)
            source["score"] = score
            item["source"] = source
            xbmc.log(
                f"[KodiSimpleStream] normalized source quality={source['quality_label']} "
                f"resolution={source['resolution_label']} score={score} name={name}",
                xbmc.LOGDEBUG,
            )
            prev = merged.get(ident)
            if prev is None or item["score"] > prev["score"]:
                merged[ident] = item

    preference = language_preference()
    sorted_items = sorted(
        merged.values(),
        key=lambda x: (
            x["score"] + (LANG_PREF_BONUS if matches_language_preference(x["source"], preference) else 0),
            x["quality_pref"],
            x["size"],
        ),
        reverse=True,
    )
    debug_scores = _addon.getSettingBool("tmdbh_show_debug_scores")
    for it in sorted_items[:10]:
        if debug_scores:
            xbmc.log(
                f"[KodiSimpleStream] score={it['score']} quality={it['quality']} size={it['size']} name={it['name']}",
                xbmc.LOGINFO,
            )
    return sorted_items[:max_results]


def play_ident(ident: str) -> None:
    """Asks Webshare for the download link only when the file is played."""
    api = get_api()
    if not api:
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return
    try:
        video_url = api.get_download_link(ident)
    except Exception as exc:
        xbmc.log(f"[KodiSimpleStream] file_link failed for {ident}: {exc}", xbmc.LOGWARNING)
        video_url = ""
    if not video_url:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30040),  # "Webshare returned no download link"
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return
    play_video(video_url)


def _tmdbh_source(result: Dict[str, Any]) -> Dict[str, Any]:
    source = result.get("source") or normalize_source(result)
    source["score"] = result.get("score", source.get("score"))
    return source


def _tmdbh_source_label(result: Dict[str, Any]) -> str:
    return compact_label(_tmdbh_source(result), include_score=True)


def _tmdbh_source_listitem(result: Dict[str, Any]) -> xbmcgui.ListItem:
    source = _tmdbh_source(result)
    item = xbmcgui.ListItem(
        label=_source_label(source),
        label2=metadata_line(source, include_score=True, include_quality=True),
    )
    item.setInfo("video", {
        "title": source.get("title") or result.get("name", ""),
        "size": source.get("size_bytes", result.get("size", 0)),
        "mediatype": "video",
    })
    item.setArt(_resolution_badge_art(source, result.get("img", "")))
    return item


def _select_tmdbh_dialog(labels: List[str], listitems: List[xbmcgui.ListItem]) -> int:
    dialog = xbmcgui.Dialog()
    try:
        return dialog.select("Select Webshare source", listitems, 0, -1, True)
    except TypeError:
        xbmc.log(
            "[KodiSimpleStream] detailed source picker unavailable; falling back to compact labels",
            xbmc.LOGDEBUG,
        )
        return dialog.select("Select Webshare source", labels)


def _primary_tmdbh_query(params: Dict[str, Any]) -> str:
    queries = build_tmdbh_queries(params)
    return queries[0] if queries else ""


def prompt_change_search(current_query: str) -> Optional[str]:
    """Prompt for a replacement Webshare search query."""
    value = xbmcgui.Dialog().input("Change search", current_query or "")
    new_query = (value or "").strip()
    if not new_query or new_query == (current_query or "").strip():
        xbmc.log("[KodiSimpleStream] search query change cancelled or unchanged", xbmc.LOGDEBUG)
        return None
    xbmc.log(f"[KodiSimpleStream] search query changed from '{current_query}' to '{new_query}'", xbmc.LOGINFO)
    return new_query


def select_tmdbh_source(params: Dict[str, Any]) -> None:
    """Shows a modal source picker for TMDb Helper and resolves the selected item."""
    current_query = _primary_tmdbh_query(params)
    active_query: Optional[str] = None

    while True:
        results = search_and_score_tmdbh(params, active_query)
        if not results:
            xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
            new_query = prompt_change_search(current_query)
            if new_query:
                current_query = new_query
                active_query = new_query
                continue
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return

        labels = [f"Search query: {current_query or 'Webshare'}  •  Change search"]
        labels.extend(_tmdbh_source_label(result) for result in results)
        listitems = [xbmcgui.ListItem(label=f"Search query: {current_query or 'Webshare'}", label2="Change search")]
        listitems[0].setArt({"icon": "DefaultAddonsSearch.png", "thumb": "DefaultAddonsSearch.png"})
        listitems.extend(_tmdbh_source_listitem(result) for result in results)
        selected = _select_tmdbh_dialog(labels, listitems)
        if selected < 0:
            xbmc.log("[KodiSimpleStream] TMDbH source selection cancelled", xbmc.LOGINFO)
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        if selected == 0:
            new_query = prompt_change_search(current_query)
            if new_query:
                current_query = new_query
                active_query = new_query
            continue

        chosen = results[selected - 1]
        xbmc.log(f"[KodiSimpleStream] TMDbH selected source score={chosen['score']} name={chosen['name']}", xbmc.LOGINFO)
        play_ident(chosen["ident"])
        return


def list_tmdbh_sources(params: Dict[str, Any]) -> None:
    results = search_and_score_tmdbh(params)
    if not results:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.endOfDirectory(_handle)
        return

    for result in results:
        source = result.get("source") or normalize_source(result)
        item = xbmcgui.ListItem(
            label=_source_label(source),
            label2=metadata_line(source, include_score=True, include_quality=True),
        )
        item.setInfo("video", {"title": source["title"], "size": result["size"], "mediatype": "video"})
        item.setArt(_resolution_badge_art(source, result.get("img", "")))
        item.setProperty("IsPlayable", "true")
        xbmcplugin.addDirectoryItem(_handle, get_url(action="play_ident", ident=result["ident"]), item, isFolder=False)

    xbmcplugin.setContent(_handle, "videos")
    xbmcplugin.endOfDirectory(_handle)


def play_best_tmdbh_source(params: Dict[str, Any]) -> None:
    results = search_and_score_tmdbh(params)
    if not results:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return

    min_score = int(_addon.getSetting("tmdbh_auto_play_min_score") or "80")
    best = results[0]
    if best["score"] >= min_score:
        xbmc.log(f"[KodiSimpleStream] Autoplaying best source score={best['score']} name={best['name']}", xbmc.LOGINFO)
        play_ident(best["ident"])
        return

    xbmc.log(f"[KodiSimpleStream] Best score {best['score']} below threshold {min_score}, showing source picker", xbmc.LOGINFO)
    select_tmdbh_source(params)


def tmdbh_play(params: Dict[str, Any]) -> None:
    queries = build_tmdbh_queries(params)
    if not queries:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "Missing required metadata for TMDb Helper search", xbmcgui.NOTIFICATION_ERROR, 4000)
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return

    if _addon.getSettingBool("tmdbh_auto_play_best"):
        play_best_tmdbh_source(params)
    else:
        select_tmdbh_source(params)

# ----------------------------------------------------------------------------
# Placeholder for unimplemented features
# ----------------------------------------------------------------------------

def list_videos(category: str) -> None:
    """Stub for future content browsing by category."""
    xbmcgui.Dialog().notification(
        _addon.getAddonInfo("name"),
        _addon.getLocalizedString(30016),  # "This function is not implemented yet."
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )

# ----------------------------------------------------------------------------
# Routing
# ----------------------------------------------------------------------------

def _parse_query(raw_query: str) -> List[str]:
    """Search terms are passed in the URL as a Python list literal (or a plain string)."""
    try:
        query_list = ast.literal_eval(raw_query)
        if not isinstance(query_list, list):
            query_list = [raw_query]
    except (ValueError, SyntaxError):
        query_list = [raw_query]
    return [str(q) for q in query_list]

def _int_param(params: Dict[str, str], name: str) -> Optional[int]:
    """Returns an integer URL parameter, None when missing or invalid."""
    try:
        return int(params[name])
    except (KeyError, ValueError):
        return None

def router(paramstring: str) -> None:
    """Dispatches actions based on plugin paramstring."""
    params = dict(parse_qsl(paramstring))
    action = params.get("action")

    if action is None:
        list_categories()
        return

    if action == "listing":
        list_videos(params["category"])
    elif action == "play":
        play_video(params["video"])
    elif action == "search_webshare":
        search_webshare()
    elif action == "play_ident":
        play_ident(params["ident"])
    elif action == "tmdbh_play":
        tmdbh_play(params)
    elif action == "search_csfd_movie":
        search_csfd_movie()
    elif action == "search_csfd_series":
        search_csfd_series()
    elif action == "select_csfd":
        handle_csfd_selection(params["csfd_id"], params["search_type"])
    elif action == "list_episodes":
        list_episodes(
            params["csfd_id"],
            params["season_id"],
            params["series_title"],
            params.get("original_title", ""),
        )
    elif action == "list_search_results":
        list_search_results(
            _parse_query(params["query"]),
            _int_param(params, "sort"),
            _int_param(params, "offset") or 0,
            params.get("replace") == "1",
        )
    elif action == "choose_sort":
        choose_sort(_parse_query(params["query"]), _int_param(params, "sort") or 0)
    else:
        raise ValueError(f"Invalid paramstring: {paramstring}!")

# ----------------------------------------------------------------------------
if __name__ == "__main__":
    # Kodi passes plugin parameters in `sys.argv[2]`, including the leading '?'
    # This may be missing during CLI testing – handle gracefully.
    router(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else "")