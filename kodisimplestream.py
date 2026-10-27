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

def list_search_results(search_terms: List[str]) -> None:
    """
    Displays search results for a list of search terms using WebshareAPI.
    Adds each result as a playable item.
    """
    api = get_api()
    if not api:
        return

    try:
        for term in search_terms:
            response = api.search(term)["response"]
            if int(response.get("total", 0)) == 0:
                xbmcgui.Dialog().notification(
                    _addon.getAddonInfo("name"),
                    _addon.getLocalizedString(30007).format(_addon.getLocalizedString(30008)),
                    xbmcgui.NOTIFICATION_ERROR,
                    5000,
                )
                continue

            files = response.get("file", [])
            if isinstance(files, dict):
                files = [files]

            for file_info in files:
                source = normalize_source(file_info)
                item = xbmcgui.ListItem(
                    label=source_title_label(source),
                    label2=metadata_line(source, include_score=True, include_quality=True),
                )
                item.setInfo("video", {
                    "title": source.get("title") or file_info.get("name", term),
                    "size": source.get("size_bytes", 0),
                    "mediatype": "video",
                })
                item.setArt(_resolution_badge_art(source, file_info.get("img", "")))
                xbmc.log(
                    f"[KodiSimpleStream] normalized Webshare source quality={source['quality_label']} "
                    f"resolution={source['resolution_label']} name={source['original_name']}",
                    xbmc.LOGDEBUG,
                )

                video_url = api.get_download_link(file_info["ident"])
                if not video_url:
                    continue

                item.setProperty("IsPlayable", "true")
                xbmcplugin.addDirectoryItem(_handle, get_url(action="play", video=video_url), item, isFolder=False)

        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.setContent(_handle, "videos")
        xbmcplugin.endOfDirectory(_handle)
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30007).format(str(exc)),
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )

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
            response = api.search(term).get("response", {})
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

    sorted_items = sorted(
        merged.values(),
        key=lambda x: (x["score"], x["quality_pref"], x["size"]),
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
    api = get_api()
    if not api:
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return
    video_url = api.get_download_link(ident)
    if not video_url:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "Unable to resolve selected source", xbmcgui.NOTIFICATION_ERROR, 5000)
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
        label=source_title_label(source),
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
            label=source_title_label(source),
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
        raw_query = params["query"]
        try:
            query_list = ast.literal_eval(raw_query)
            if not isinstance(query_list, list):
                query_list = [raw_query]
        except (ValueError, SyntaxError):
            query_list = [raw_query]
        list_search_results([str(q) for q in query_list])
    else:
        raise ValueError(f"Invalid paramstring: {paramstring}!")

# ----------------------------------------------------------------------------
if __name__ == "__main__":
    # Kodi passes plugin parameters in `sys.argv[2]`, including the leading '?'
    # This may be missing during CLI testing – handle gracefully.
    router(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else "")