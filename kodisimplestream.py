# -*- coding: utf-8 -*-
# Module: kodisimplestream
# Author: Kecerim24
# Created on: 28.04.2025
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html

from __future__ import annotations  # Enables forward references in older Python versions

# Kodi plugin boilerplate and plugin-specific modules
import ast
import json
import os
import sys
from typing import Any, Dict, List, Optional

import re
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import preview
from resources.lib.webshare import WebshareAPI
from resources.lib.tmdb import TMDB, TMDBAuthError
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
    LANG_PREF_BONUS,
    build_search_queries,
    build_tmdbh_queries,
    parse_quality,
    parse_size,
    rank_files,
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


def _preview_thumbs() -> bool:
    """Video preview from Webshare instead of the quality badge (setting, on by default)."""
    return _addon.getSetting("preview_thumbs") != "false"

def _resolution_badge_art(source: Dict[str, Any], fallback_image: str = "") -> Dict[str, str]:
    """Artwork for source rows: the Webshare video preview, or the bundled resolution badge."""
    badge = _icon_path(source_icon_name(source))
    # Kodi downloads and caches the preview itself, only for the rows it shows
    thumb = fallback_image if fallback_image and _preview_thumbs() else badge
    return {
        "icon": thumb,
        "thumb": thumb,
        "poster": thumb,
        "landscape": thumb,
        "fanart": fallback_image or badge,
    }

# Index of the "lang_pref" setting → preference understood by matches_language_preference()
# LANG_PREF_BONUS (matching.py) is added to the match score when sorting, the shown score stays unchanged
LANG_PREFS = ["", "cz_audio", "cz_subs"]

def language_preference() -> str:
    """Returns the preferred language variant from add-on settings ("" = no preference)."""
    try:
        index = int(_addon.getSetting("lang_pref") or 0)
    except ValueError:
        index = 0
    return LANG_PREFS[index] if 0 <= index < len(LANG_PREFS) else ""

def _source_label(source: Dict[str, Any], image: str = "") -> str:
    """Title label with tags in front, e.g. "[FHD] [CZ dabing] Film".

    The quality tag is added when the preview replaces the quality badge; SD is left out,
    it mostly means "not in the file name".
    """
    title = source_title_label(source)
    lang, kind = language_tag(source)
    if lang:
        word = _addon.getLocalizedString(30042 if kind == "audio" else 30043)  # "dabing" / "titulky"
        title = f"[{lang} {word}] {title}"
    quality = source.get("quality_label") or ""
    if image and _preview_thumbs() and quality in ("4K", "FHD", "HD"):
        title = f"[{quality}] {title}"
    return title

def _add_preview_menu(item: xbmcgui.ListItem, file_info: Dict[str, Any], title: str) -> None:
    """Context menu "Video preview" for files with a Webshare preview stripe."""
    if not file_info.get("stripe"):
        return
    url = get_url(action="preview", ident=file_info.get("ident", ""), stripe=file_info["stripe"],
                  count=file_info.get("stripe_count") or "", title=title)
    item.addContextMenuItems([(_addon.getLocalizedString(30059), f"RunPlugin({url})")])  # "Video preview"

def show_preview(ident: str, stripe: str, count: int, title: str) -> None:
    """Downloads the preview stripe on request and shows its frames one by one."""
    folder = os.path.join(xbmcvfs.translatePath("special://temp/kodisimplestream/preview"), ident or "unknown")
    try:
        frames = preview.load_frames(stripe, count, folder)
    except Exception as exc:
        xbmc.log(f"[KodiSimpleStream] preview failed for {ident}: {exc}", xbmc.LOGWARNING)
        frames = []
    if frames:
        preview.show(frames, title, _icon_path_media("white.png"))
    else:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30060),  # "Video preview is not available"
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
    # Run from the context menu (handle -1); opened as a folder it must not hang
    if _handle >= 0:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

def _icon_path_media(filename: str) -> str:
    """Bundled image from resources/media."""
    return os.path.join(_addon.getAddonInfo("path"), "resources", "media", filename)

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

def get_tmdb() -> Optional[TMDB]:
    """
    Returns a TMDb client using the API key from settings.
    Shows error notification when the key is missing.
    """
    try:
        return TMDB(_addon.getSetting("tmdb_api_key"))
    except ValueError:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30051),  # "Enter TMDb API key in add-on settings"
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return None

def show_tmdb_error(exc: Exception) -> None:
    """Notifies about a failed TMDb request and closes the current directory."""
    if isinstance(exc, TMDBAuthError):
        message = _addon.getLocalizedString(30053)  # "TMDb rejected the API key…"
    else:
        message = _addon.getLocalizedString(30007).format(str(exc))
    xbmcgui.Dialog().notification(
        _addon.getAddonInfo("name"),
        message,
        xbmcgui.NOTIFICATION_ERROR,
        5000,
    )
    xbmcplugin.endOfDirectory(_handle, succeeded=False)

# ----------------------------------------------------------------------------
# Root menu
# ----------------------------------------------------------------------------

def list_categories() -> None:
    """Creates items for the plugin's main menu."""
    menu = [("search_webshare", 30011, "DefaultAddonsSearch.png", True)]
    # TMDb is optional – without an API key offer setup instead of the TMDb searches
    if _addon.getSetting("tmdb_api_key").strip():
        menu += [
            ("search_tmdb_movie", 30012, "DefaultAddonsSearch.png", True),
            ("search_tmdb_series", 30013, "DefaultAddonsSearch.png", True),
        ]
    else:
        # Action item, not a folder: Kodi runs it as a script (handle -1) without listing
        menu.append(("tmdb_setup", 30054, "DefaultAddonProgram.png", False))

    for action, label_id, icon, is_folder in menu:
        item = xbmcgui.ListItem(label=_addon.getLocalizedString(label_id))
        item.setArt({"icon": icon})
        xbmcplugin.addDirectoryItem(_handle, get_url(action=action), item, isFolder=is_folder)

    xbmcplugin.endOfDirectory(_handle)

def tmdb_setup() -> None:
    """Explains how to get a TMDb API key and offers to open the add-on settings."""
    name = _addon.getAddonInfo("name")
    xbmcgui.Dialog().textviewer(name, _addon.getLocalizedString(30055))  # How to get the key
    if xbmcgui.Dialog().yesno(name, _addon.getLocalizedString(30056)):  # "Open settings now?"
        _addon.openSettings()  # Modal, returns after OK/Cancel
        # Show the TMDb searches as soon as the key is saved
        xbmc.executebuiltin("Container.Refresh")
    # Opened as a folder (old cached menu) or by the Play button – close it and stay in the main menu
    if _handle >= 0:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

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

def _match_params(match: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """URL parameter with the TMDb metadata for match scoring (JSON, urlencode encodes its commas)."""
    return {"match": json.dumps(match, ensure_ascii=False, separators=(",", ":"))} if match else {}

def list_search_results(
    search_terms: List[str],
    sort: Optional[int] = None,
    offset: int = 0,
    replace: bool = False,
    match: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Displays one page of search results for a list of search terms using WebshareAPI.
    The same file found by more terms is shown once, the download link is resolved on playback.
    match: TMDb metadata (see matching.py) – in the best match order the results are sorted
    by the match score like in the TMDb Helper flow.
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
        pages = []
        has_more = False
        next_offset = offset + PAGE_SIZE
        for term in search_terms:
            response = api.search(term, limit=PAGE_SIZE, offset=offset, sort=SORT_VALUES[sort])["response"]
            files = _as_list(response.get("file"))
            pages.append(files)
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
        url = get_url(action="choose_sort", query=str(search_terms), sort=sort, **_match_params(match))
        xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=False)

        preference = language_preference()
        if match and sort == 0:
            # Webshare ORs the query words: noise sharing one word with the first query comes before
            # the right files found by the next one. Score against the TMDb titles like TMDb Helper does,
            # equal scores keep the Webshare order, the language bonus is not shown.
            sources = [(file_info, normalize_source(file_info)) for file_info in rank_files(pages, match, preference)]
        else:
            sources = [(file_info, normalize_source(file_info)) for file_info in rows]
            if preference:
                # Preferred dub/subtitles first, otherwise keep the Webshare order (stable sort)
                sources.sort(key=lambda pair: not matches_language_preference(pair[1], preference))

        for file_info, source in sources:
            item = xbmcgui.ListItem(
                label=_source_label(source, file_info.get("img", "")),
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
            _add_preview_menu(item, file_info, source_title_label(source))
            xbmcplugin.addDirectoryItem(_handle, get_url(action="play_ident", ident=file_info["ident"]), item, isFolder=False)

        if has_more:
            item = xbmcgui.ListItem(label=_addon.getLocalizedString(30038).format(next_offset // PAGE_SIZE + 1))
            item.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
            item.setProperty("SpecialSort", "bottom")
            url = get_url(action="list_search_results", query=str(search_terms), sort=sort, offset=next_offset, **_match_params(match))
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

def choose_sort(search_terms: List[str], current: int, match: Optional[Dict[str, Any]] = None) -> None:
    """Lets the user pick a different order for the current search and reloads the list."""
    labels = [_addon.getLocalizedString(label_id) for label_id in SORT_LABELS]
    selected = xbmcgui.Dialog().select(_addon.getLocalizedString(30039), labels, preselect=current)
    if 0 <= selected != current:
        url = get_url(action="list_search_results", query=str(search_terms), sort=selected, replace=1, **_match_params(match))
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
# TMDb – search results
# ----------------------------------------------------------------------------

def list_tmdb_results(results: List[Dict[str, Any]], search_type: str) -> None:
    """Displays TMDb search results as Kodi menu items."""
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

        url = get_url(action="select_tmdb", tmdb_id=result["id"], search_type=search_type)
        xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

# ----------------------------------------------------------------------------
# TMDb – selection and detailed episode listing
# ----------------------------------------------------------------------------

def handle_tmdb_selection(tmdb_id: str, search_type: str) -> None:
    """Handles selection from TMDb and delegates search or episode listing."""
    tmdb = get_tmdb()
    if not tmdb:
        return
    try:
        details = tmdb.get_detail(tmdb_id)
    except Exception as exc:
        show_tmdb_error(exc)
        return

    if search_type == "movie":
        # TMDb titles for the queries and the match score – files found by the original title should not end up below noise
        match = {
            "mediatype": "movie",
            "title": details["title"],
            "originaltitle": details.get("original_title") or "",
            "year": details.get("year") or "",
        }
        list_search_results(build_search_queries(match), match=match)
        return

    # Series → show list of seasons
    try:
        seasons = tmdb.get_seasons(tmdb_id)
    except Exception as exc:
        show_tmdb_error(exc)
        return
    list_seasons(seasons, details["title"], details.get("original_title"), tmdb_id)

# ----------------------------------------------------------------------------
# TMDb – episode navigation
# ----------------------------------------------------------------------------

def list_seasons(
    seasons: List[Dict[str, Any]],
    series_title: str,
    original_title: Optional[str],
    tmdb_id: str,
) -> None:
    """Displays list of seasons for a series."""
    for season in seasons:
        label = season["title"] if season["title"] != "Season" else f"Season {season['number']}"
        url = get_url(
            action="list_episodes",
            tmdb_id=tmdb_id,
            season_id=season["id"],
            series_title=series_title,
            original_title=original_title or "",
        )
        xbmcplugin.addDirectoryItem(_handle, url, xbmcgui.ListItem(label=label), isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

def list_episodes(
    tmdb_id: str,
    season_id: str,
    series_title: str,
    original_title: str,
) -> None:
    """Displays episode list for a given season."""
    tmdb = get_tmdb()
    if not tmdb:
        return
    try:
        episodes = tmdb.get_episodes(tmdb_id, season_id)
    except Exception as exc:
        show_tmdb_error(exc)
        return

    for ep in episodes:
        season_no = ep.get("season") or 0
        ep_no = ep.get("number") or 0
        label = f"{ep_no}. {ep['title']}"

        match = {
            "mediatype": "episode",
            "showname": series_title,
            "show_originaltitle": original_title or "",
            "season": season_no,
            "episode": ep_no,
            "episode_title": ep.get("title") or "",
        }
        url = get_url(action="list_search_results", query=str(build_search_queries(match)), **_match_params(match))
        xbmcplugin.addDirectoryItem(_handle, url, xbmcgui.ListItem(label=label), isFolder=True)

    xbmcplugin.endOfDirectory(_handle)

# ----------------------------------------------------------------------------
# TMDb – search entry points
# ----------------------------------------------------------------------------

def search_tmdb(label_id: int, search_type: str) -> None:
    """Search dialog for TMDb movie or TV series titles."""
    tmdb = get_tmdb()
    if not tmdb:
        return
    term = _keyboard_search(label_id)
    if term:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30002).format(term),
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        try:
            results = tmdb.search(term, type=search_type)
        except Exception as exc:
            show_tmdb_error(exc)
            return
        list_tmdb_results(results, search_type)


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
                "stripe": file_info.get("stripe") or "",
                "stripe_count": file_info.get("stripe_count") or "",
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
        label=_source_label(source, result.get("img", "")),
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
    # Without a Webshare login get_api() already told the user, "no sources" would be misleading
    if not get_api():
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    results = search_and_score_tmdbh(params)
    if not results:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.endOfDirectory(_handle)
        return

    for result in results:
        source = result.get("source") or normalize_source(result)
        item = xbmcgui.ListItem(
            label=_source_label(source, result.get("img", "")),
            label2=metadata_line(source, include_score=True, include_quality=True),
        )
        item.setInfo("video", {"title": source["title"], "size": result["size"], "mediatype": "video"})
        item.setArt(_resolution_badge_art(source, result.get("img", "")))
        item.setProperty("IsPlayable", "true")
        _add_preview_menu(item, result, source_title_label(source))
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
    # Without a Webshare login get_api() already told the user – do not report "no sources" or offer a new search
    if not get_api():
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

def _parse_match(raw_match: Optional[str]) -> Optional[Dict[str, Any]]:
    """TMDb metadata for match scoring is a JSON object in the URL, anything else is ignored."""
    if not raw_match:
        return None
    try:
        match = json.loads(raw_match)
    except ValueError:
        return None
    if not isinstance(match, dict):
        return None
    # matching.py expects text values, an edited URL must not break the listing
    return {str(key): "" if value is None else str(value) for key, value in match.items()}

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
    elif action == "preview":
        show_preview(params.get("ident", ""), params.get("stripe", ""), _int_param(params, "count") or 0, params.get("title", ""))
    elif action == "tmdbh_play":
        tmdbh_play(params)
    elif action == "search_tmdb_movie":
        search_tmdb(30014, "movie")
    elif action == "search_tmdb_series":
        search_tmdb(30015, "series")
    elif action == "tmdb_setup":
        tmdb_setup()
    elif action == "select_tmdb":
        handle_tmdb_selection(params["tmdb_id"], params["search_type"])
    elif action == "list_episodes":
        list_episodes(
            params["tmdb_id"],
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
            match=_parse_match(params.get("match")),
        )
    elif action == "choose_sort":
        choose_sort(_parse_query(params["query"]), _int_param(params, "sort") or 0, match=_parse_match(params.get("match")))
    else:
        raise ValueError(f"Invalid paramstring: {paramstring}!")

# ----------------------------------------------------------------------------
if __name__ == "__main__":
    # Kodi passes plugin parameters in `sys.argv[2]`, including the leading '?'
    # This may be missing during CLI testing – handle gracefully.
    router(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else "")