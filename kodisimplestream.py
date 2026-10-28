# -*- coding: utf-8 -*-
# Module: kodisimplestream
# Author: Kecerim24
# Created on: 28.04.2025
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html

from __future__ import annotations  # Enables forward references in older Python versions

# Kodi plugin boilerplate and plugin-specific modules
import ast
import hashlib
import json
import os
import ssl
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import re
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import file_details, preview, source_ui
from resources.lib.webshare import WebshareAPI, WebshareError, WebshareStatusError
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
    autoplay_concern,
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

def _file_details_enabled() -> bool:
    """Automatic Webshare file_info for lists, the TMDb Helper picker and auto-play (setting, on by default).
    The video preview asks for the details itself and is not affected."""
    return _addon.getSetting("file_details") != "false"

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

def _source_label(source: Dict[str, Any], image: str = "", quality_tag: bool = True) -> str:
    """Title label with tags in front, e.g. "[FHD] [CZ dabing] Film".

    The quality tag is added when the preview replaces the quality badge; SD is left out,
    it mostly means "not in the file name". quality_tag=False where label2 starts with the quality anyway.
    """
    title = source_title_label(source)
    lang, kind = language_tag(source)
    if lang:
        word = _addon.getLocalizedString(30042 if kind == "audio" else 30043)  # "dabing" / "titulky"
        title = f"[{lang} {word}] {title}"
    quality = source.get("quality_label") or ""
    # The real resolution from file_info is shown also when it is SD
    if quality_tag and image and _preview_thumbs() and (
            quality in ("4K", "FHD", "HD") or (quality and source.get("real_resolution"))):
        title = f"[{quality}] {title}"
    return title

# Orange (AARRGGBB) of the length warning (the length itself is in label2, see source_ui.metadata_line)
WARNING_COLOR = source_ui.WARNING_COLOR
# file_info audio languages added to a search result: normalize_source reads a field named like this
# as audio languages, so a CZE track counts as a Czech dub for the tag and the language preference
DETAILS_AUDIO_KEY = "audio_languages"

def _with_details(file_info: Dict[str, Any], info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The search result with the audio languages of its file_info (only those found; none removed)."""
    languages = file_details.audio_languages(info)
    return {**file_info, DETAILS_AUDIO_KEY: languages} if languages else file_info

def _apply_details(source: Dict[str, Any], info: Optional[Dict[str, Any]], runtime: Optional[float] = None,
                   mediatype: str = "movie") -> Dict[str, Any]:
    """Real resolution, length and the length check from file_info; without it the name guesses stay."""
    if not info:
        return source
    source["details"] = info
    real = file_details.resolution(info)
    if real:
        source["quality_label"], source["resolution_label"] = real
        source["real_resolution"] = True
    source["length_text"] = preview.format_duration(file_details.length_seconds(info))
    source["length_mismatch"] = file_details.length_mismatch(info, runtime, mediatype)
    source["runtime"] = runtime
    return source

def _set_stream_details(item: xbmcgui.ListItem, source: Dict[str, Any]) -> None:
    """Duration and stream flags (resolution, codecs, audio channels and languages) for the skin."""
    info = source.get("details")
    if not info:
        return
    seconds = file_details.length_seconds(info)
    video = file_details.video_stream(info)
    audios = file_details.audio_streams(info)
    if not hasattr(xbmc, "VideoStreamDetail"):
        # Kodi 19 (xbmc.python 3.0.0): the InfoTagVideo setters and the stream classes came in Kodi 20,
        # ListItem.addStreamInfo is there (deprecated since 20, reads every value as a string);
        # a video stream's duration is the length
        stream = dict(video or {}, duration=int(round(seconds or 0)))
        if video or seconds:
            item.addStreamInfo("video", {key: str(value) for key, value in stream.items() if value})
        for audio in audios:
            known = {key: str(value) for key, value in audio.items() if value and value != -1}
            if known:
                item.addStreamInfo("audio", known)
        return
    tag = item.getVideoInfoTag()
    if seconds:
        tag.setDuration(int(round(seconds)))
    if video:
        tag.addVideoStream(xbmc.VideoStreamDetail(width=video["width"], height=video["height"],
                                                  duration=video["duration"], codec=video["codec"]))
    for audio in audios:
        tag.addAudioStream(xbmc.AudioStreamDetail(audio["channels"], audio["codec"], audio["language"]))

def _details_lines(source: Dict[str, Any]) -> List[str]:
    """Plot lines with the real details: video, bitrate, length, audio tracks (one line), container."""
    info = source.get("details")
    if not info:
        return []
    labels = {key: _addon.getLocalizedString(string_id) for key, string_id in _DETAIL_LABELS.items()}
    lines: List[str] = []
    for label, value in preview.details_rows(info, "", labels):
        if label == labels["size"]:
            continue  # already on the second line
        if label or not lines:
            lines.append(f"{label}: {value}" if label else value)
        else:
            lines[-1] += f", {value}"  # the next audio track
    if source.get("length_mismatch") and source.get("runtime"):
        warning = _addon.getLocalizedString(30073).format(int(round(source["runtime"])))  # "Length does not match…"
        lines.append(f"[COLOR {WARNING_COLOR}]{warning}[/COLOR]")
    return lines

def _has_preview(file_info: Dict[str, Any]) -> bool:
    return preview.is_stripe_url(file_info.get("stripe")) and preview.is_valid_ident(file_info.get("ident"))

def _add_preview_menu(item: xbmcgui.ListItem, file_info: Dict[str, Any], title: str) -> None:
    """Context menu "Video preview" for files with a Webshare preview stripe."""
    if not _has_preview(file_info):
        return
    # The window shows the full file name and, until file_info arrives or when it fails, the size of the list
    url = get_url(action="preview", ident=file_info["ident"], stripe=file_info["stripe"],
                  count=file_info.get("stripe_count") or "", title=file_info.get("name") or title,
                  size=file_info.get("size") or "")
    item.addContextMenuItems([(_addon.getLocalizedString(30059), f"RunPlugin({url})")])  # "Video preview"

def _source_plot(source: Dict[str, Any], has_preview: bool = False) -> str:
    """Text for Kodi's Information dialog of a source row, from what the list already knows."""
    lines = [source.get("original_name") or source.get("title") or ""]
    quality, resolution = source.get("quality_label") or "SD", source.get("resolution_label") or "SD"
    if quality == resolution == "SD":
        quality = ""  # no quality in the file name: "SD" would be a guess, the preview shows the real one
    elif quality != resolution:
        quality = f"{quality} {resolution}"  # "FHD 1080p"
    lines.append(" · ".join(part for part in (quality, source.get("size_text")) if part))
    languages = []
    # The label's languages (file name + a CZE track from file_info), unless the file_info tracks below
    # already name all of them – an UND/ENG-tagged track must not hide a CZ known from the name
    tracks = file_details.audio_languages(source.get("details"))
    if source.get("audio_langs") and not set(source["audio_langs"]) <= set(tracks):
        languages.append(f"{_addon.getLocalizedString(30064)}: {'/'.join(source['audio_langs'])}")  # "Audio"
    if source.get("subtitle_langs"):
        languages.append(f"{_addon.getLocalizedString(30068)}: {'/'.join(source['subtitle_langs'])}")  # "Subtitles"
    lines.append(" · ".join(languages))
    lines.append(" · ".join(source[key] for key in ("source_type", "codec", "audio_format") if source.get(key)))
    lines.extend(_details_lines(source))
    if has_preview:
        lines.append(_addon.getLocalizedString(30069))  # "Context menu: Video preview"
    return "[CR]".join(line for line in lines if line)

_PREVIEW_PROPERTY = "kodisimplestream.preview"
# A guard older than this is left over from a script that did not get to its finally (killed invoker)
_PREVIEW_GUARD_SECONDS = 600

def _preview_running(home: xbmcgui.Window) -> bool:
    """True while another preview script holds the guard on the home window."""
    try:
        return time.time() - float(home.getProperty(_PREVIEW_PROPERTY) or 0) < _PREVIEW_GUARD_SECONDS
    except ValueError:
        return False

def show_preview(ident: str, stripe: str, count: int, title: str, size: str = "") -> None:
    """Downloads the preview stripe on request and shows its frames one by one."""
    # RunPlugin starts a new script per request: a second "Video preview" while the first one is
    # still downloading would cut the same files and stack a second window, so it is ignored
    home = xbmcgui.Window(10000)
    if _preview_running(home):
        xbmc.log("[KodiSimpleStream] preview already running, request ignored", xbmc.LOGINFO)
    else:
        home.setProperty(_PREVIEW_PROPERTY, str(time.time()))
        try:
            _show_preview(ident, stripe, count, title, size)
        finally:
            home.clearProperty(_PREVIEW_PROPERTY)
    # Run from the context menu (handle -1); opened as a folder it must not hang
    if _handle >= 0:
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

# Row names of the details panel in the preview window
_DETAIL_LABELS = {"video": 30061, "bitrate": 30062, "length": 30063, "audio": 30064,
                  "size": 30065, "container": 30066, "unavailable": 30067, "unanalysed": 30070}

def _show_preview(ident: str, stripe: str, count: int, title: str, size: str = "") -> None:
    """Busy dialog while the stripe and file_info load (in parallel), then the window;
    a failure of the frames ends in the 30060 notification, file_info only fills the details."""
    try:
        xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
        try:
            # Invalid ident or URL (edited plugin URL), download error, broken image or Pillow missing
            folder = preview.cache_folder(ident)
            details = preview.FileInfoRequest(ident, folder)  # HTTP in a background thread
            frames = preview.load_frames(stripe, count, folder)
            info = details.result() if frames else None
        finally:
            xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
        if frames:
            if info is None:
                reason = f"{type(details.error).__name__}: {details.error}" if details.error else "late or not OK"
                xbmc.log(f"[KodiSimpleStream] file_info unavailable for {ident!r}: {reason}", xbmc.LOGINFO)
            else:
                # The lists show the details of a previewed file too (the preview folders are pruned sooner)
                cache = _details_cache()
                cache.put(ident, info)
                cache.save()
            labels = {key: _addon.getLocalizedString(string_id) for key, string_id in _DETAIL_LABELS.items()}
            rows = preview.details_rows(info, size, labels)
            # A frame removed from special://temp meanwhile, a window error: a notification, not the script error dialog
            preview.show(frames, title or (info or {}).get("name", ""), _icon_path_media("white.png"), rows)
            return
    except Exception as exc:
        xbmc.log(f"[KodiSimpleStream] preview failed for {ident!r}: {type(exc).__name__}: {exc}", xbmc.LOGWARNING)
    xbmcgui.Dialog().notification(
        _addon.getAddonInfo("name"),
        _addon.getLocalizedString(30060),  # "Video preview is not available"
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )

def _icon_path_media(filename: str) -> str:
    """Bundled image from resources/media."""
    return os.path.join(_addon.getAddonInfo("path"), "resources", "media", filename)

# ----------------------------------------------------------------------------
# File details (Webshare file_info) for the result lists
# ----------------------------------------------------------------------------
#
# A listing is shown at once with what the cache knows. Kodi fetches a listing outside its main thread
# and then shows it only when the script has ended (Kodi 21 CScriptRunner::WaitOnScriptResult waits up
# to 30 s for the script after endOfDirectory, CPythonInvoker waits for the script's threads), so the
# missing details are not fetched by the listing itself:
# it starts a separate script (RunPlugin, handle -1) for the top rows and ends. That script fetches
# them (bounded time, at most 4 requests at once), caches them and refreshes the list once, only if
# the same listing is still open. The refreshed call finds the marker of this one refresh, uses the
# cached search answers and the cached details and never starts another fetch, so it cannot loop.

ENRICH_PROPERTY = "kodisimplestream.details_job"     # the job of the newest listing: token, listing key, idents
LISTING_PROPERTY = "kodisimplestream.details_listing"  # search answers of that listing for its refresh
REFRESH_PROPERTY = "kodisimplestream.details_refresh"  # marker: the next call of this listing is the refresh
# The same listing starts no second job within this time (Back and forth, a refresh without the marker)
ENRICH_GUARD_SECONDS = 60
# The details script refreshes the list only this long after the listing started it
REFRESH_WINDOW = 20
# The refreshed listing must run within this time after the marker was set
REFRESH_MARKER_SECONDS = 30
_LISTING_ACTIONS = ("list_search_results", "search_webshare", "select_tmdb")
_refresh_pass = False  # set by router(): this call is the one refresh of its listing

def _home() -> Optional[xbmcgui.Window]:
    try:
        return xbmcgui.Window(10000)
    except Exception:  # stubbed or failing GUI: the details just are not cached for the session
        return None

def _json_property(window: Optional[xbmcgui.Window], name: str) -> Dict[str, Any]:
    if window is None:
        return {}
    try:
        value = json.loads(window.getProperty(name) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}

def _details_cache() -> file_details.DetailsCache:
    """Session cache in the home window, persistent cache in addon_data, the preview's info.json as a fallback."""
    try:
        import xbmcvfs

        folder = xbmcvfs.translatePath(_addon.getAddonInfo("profile"))
        previews = xbmcvfs.translatePath(preview.CACHE_ROOT)
    except Exception:  # no xbmcvfs (tests) or no profile: the session cache only
        folder = previews = ""
    return file_details.DetailsCache(_home(), folder, previews)

def _listing_key(path: str) -> str:
    """A plugin URL with its parameters in a fixed order, for comparing with Container.FolderPath."""
    base, _, query = (path or "").partition("?")
    return f"{base.rstrip('/')}?{urlencode(sorted(parse_qsl(query)))}"

def _current_listing_key() -> str:
    return _listing_key(_url + (sys.argv[2] if len(sys.argv) > 2 else ""))

def _take_refresh_marker() -> Tuple[bool, Dict[str, Any]]:
    """(is the one refresh of this listing, the cached listing or {}); the marker is used up."""
    home = _home()
    marker = _json_property(home, REFRESH_PROPERTY)
    if not marker:
        return False, {}
    try:
        fresh = 0 <= time.time() - float(marker.get("time") or 0) < REFRESH_MARKER_SECONDS
    except (TypeError, ValueError):
        fresh = False
    key = _current_listing_key()
    if fresh and marker.get("key") != key:
        return False, {}  # for another listing, which may still come
    home.clearProperty(REFRESH_PROPERTY)
    if not fresh:
        return False, {}
    listing = _json_property(home, LISTING_PROPERTY)
    return True, listing if listing.get("key") == key else {}

def _start_details(idents: List[str], top: List[str], listing: Dict[str, Any]) -> None:
    """Starts the details script for the unknown ones (idents) of the top rows of the listing being built
    (not in its refresh)."""
    if _handle < 0 or _refresh_pass or not _file_details_enabled():
        return
    home = _home()
    if home is None:
        return
    job = _json_property(home, ENRICH_PROPERTY)
    if job and job.get("key") == listing["key"] and job.get("top") != top:
        # Another listing on the same URL (a new keyboard search): the job of the old one must not
        # refresh this one with the old search answers, its script ends on the token check
        home.clearProperty(ENRICH_PROPERTY)
        home.clearProperty(LISTING_PROPERTY)
        job = {}
    if not idents or file_details.blocked(home):
        return
    try:
        recent = 0 <= time.time() - float(job.get("time") or 0) < ENRICH_GUARD_SECONDS
    except (TypeError, ValueError):
        recent = False
    # The same rows of the same listing; a new keyboard search has the same URL but other rows
    if recent and job.get("key") == listing["key"] and job.get("idents") == idents:
        return
    token = hashlib.sha1(f"{listing['key']}|{time.time()}".encode("utf-8")).hexdigest()[:12]
    home.setProperty(LISTING_PROPERTY, json.dumps(listing, ensure_ascii=False, separators=(",", ":")))
    home.setProperty(ENRICH_PROPERTY, json.dumps({"token": token, "key": listing["key"], "idents": idents,
                                                   "top": top, "time": time.time()}, separators=(",", ":")))
    xbmc.executebuiltin(f"RunPlugin({get_url(action='file_details', token=token)})")

def fetch_details(token: str) -> None:
    """The details script of a listing (RunPlugin, handle -1): file_info of its top rows, then one refresh."""
    if _handle >= 0:  # opened as a folder (edited URL): nothing to list
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    home = _home()
    job = _json_property(home, ENRICH_PROPERTY)
    if not token or job.get("token") != token or not isinstance(job.get("idents"), list) or file_details.blocked(home):
        return
    cache = _details_cache()
    idents = [ident for ident in job["idents"][:file_details.LIST_COUNT]
              if isinstance(ident, str) and preview.is_valid_ident(ident) and not cache.known(ident)]
    if not idents:
        return
    monitor = xbmc.Monitor()

    def superseded() -> bool:
        # Kodi exits, or a newer listing started its own job (or a new search on the same URL cleared
        # this one): no further request starts here, so two jobs never run 4 workers each for long
        return monitor.abortRequested() or _json_property(home, ENRICH_PROPERTY).get("token") != token

    fetcher = file_details.Fetcher(idents, file_details.LIST_BUDGET)
    arrived = fetcher.wait(file_details.LIST_BUDGET + 1, superseded)
    fetcher.stop()
    found = _store_details(cache, fetcher, arrived, home)
    xbmc.log(f"[KodiSimpleStream] file_info for the list: {len(arrived)}/{len(idents)} answers, {found} with details, "
             f"{time.monotonic() - fetcher.started:.2f} s{_fetch_problem(fetcher)}", xbmc.LOGINFO)
    if found:
        _refresh_listing(home, job, monitor)

def _store_details(cache: file_details.DetailsCache, fetcher: file_details.Fetcher,
                   arrived: Dict[str, Optional[Dict[str, Any]]], home: Optional[xbmcgui.Window]) -> int:
    """Caches the answers (main thread), returns how many have details."""
    for ident, info in arrived.items():
        cache.put(ident, info)
    if fetcher.blocked:
        file_details.block(home)
    cache.save()
    return sum(1 for info in arrived.values() if info and preview.is_analysed(info))

def _fetch_problem(fetcher: file_details.Fetcher) -> str:
    if not fetcher.errors:
        return ""
    error = next(iter(fetcher.errors.values()))
    return f", stopped after {type(error).__name__}: {error}" + (" (rate limited)" if fetcher.blocked else "")

def _refresh_listing(home: Optional[xbmcgui.Window], job: Dict[str, Any], monitor: xbmc.Monitor) -> None:
    """Container.Refresh once the listing of the job is shown and no dialog is open over it; nothing when
    a newer listing took over, the user went elsewhere or REFRESH_WINDOW passed."""
    try:
        end = float(job.get("time") or 0) + REFRESH_WINDOW
    except (TypeError, ValueError):
        return
    while time.time() < end:
        if _json_property(home, ENRICH_PROPERTY).get("token") != job.get("token"):
            return
        if (_listing_key(xbmc.getInfoLabel("Container.FolderPath")) == job.get("key")
                and not xbmc.getCondVisibility("System.HasActiveModalDialog")):
            home.setProperty(REFRESH_PROPERTY, json.dumps({"key": job["key"], "time": time.time()}, separators=(",", ":")))
            xbmc.executebuiltin("Container.Refresh")
            return
        if monitor.waitForAbort(0.25):
            return

def get_api() -> WebshareAPI:
    """Returns the Webshare client of this plugin call. Searching needs no login, see login_api()."""
    global _api

    if _api is None:
        # TLS setup is the slow part of every request, its speed differs a lot between platforms
        xbmc.log(f"[KodiSimpleStream] {ssl.OPENSSL_VERSION}", xbmc.LOGDEBUG)
        _api = WebshareAPI()
    return _api

def _credentials() -> Optional[Tuple[str, str]]:
    """Returns the Webshare user name and password, None after asking the user to enter them."""
    username: str = _addon.getSetting("username")
    password: str = _addon.getSetting("password")
    if username and password:
        return username, password
    xbmcgui.Dialog().notification(
        _addon.getAddonInfo("name"),
        _addon.getLocalizedString(30009),  # "Please enter username and password…"
        xbmcgui.NOTIFICATION_ERROR,
        5000,
    )
    return None

# Window property with the login token, shared by the plugin calls (separate processes) of one Kodi session
TOKEN_PROPERTY = "kodisimplestream.wst"
# Not verified live that file_link rejects a revoked token with an error status (and so triggers a new
# login) – it might hand out a slow non-VIP link instead, so a cached token is used for a limited time only
TOKEN_MAX_AGE = 30 * 60

def login_api(reuse_token: bool = True) -> Tuple[Optional[WebshareAPI], bool]:
    """
    Returns the Webshare client with a login token and whether the token was reused from an earlier call.
    Playback then usually needs just the file_link request. reuse_token=False logs in again.
    The client is None after notifying the user (missing credentials, failed login).
    """
    credentials = _credentials()
    if not credentials:
        return None, False
    username, password = credentials
    api = get_api()
    window = xbmcgui.Window(10000)
    # The cached token belongs to one account – another user name logs in again
    account = hashlib.sha1(username.encode("utf-8")).hexdigest()[:16]
    if reuse_token:
        cached_account, _, rest = window.getProperty(TOKEN_PROPERTY).partition(":")
        saved, _, token = rest.partition(":")
        try:
            fresh = 0 <= time.time() - int(saved) < TOKEN_MAX_AGE
        except ValueError:
            fresh = False
        if token and fresh and cached_account == account:
            api.set_token(token)
            return api, True
    window.clearProperty(TOKEN_PROPERTY)

    try:
        api.login(username, password)
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30006).format(str(exc)),  # "Login failed…"
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return None, False
    window.setProperty(TOKEN_PROPERTY, f"{account}:{int(time.time())}:{api.token}")
    return api, False

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
    cached: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Displays one page of search results for a list of search terms using WebshareAPI.
    The same file found by more terms is shown once, the download link is resolved on playback.
    match: TMDb metadata (see matching.py) – in the best match order the results are sorted
    by the match score like in the TMDb Helper flow; its "runtime" (minutes) checks the file lengths.
    cached: the search answers of this listing kept for its one refresh after the file details arrived.
    """
    if sort is None or not 0 <= sort < len(SORT_VALUES):
        sort = default_sort()
    offset = max(0, offset)

    try:
        seen = set()
        rows = []
        pages = []
        answers = []
        has_more = False
        next_offset = offset + PAGE_SIZE
        if cached is not None:
            responses = [{"response": response} for response in cached]
        else:
            # Parallel requests, the responses keep the order of the terms (rank_files depends on it)
            responses = get_api().search_all(search_terms, limit=PAGE_SIZE, offset=offset, sort=SORT_VALUES[sort])
        for response in responses:
            if isinstance(response, Exception):
                raise response
            response = response["response"]
            files = _as_list(response.get("file"))
            pages.append(files)
            answers.append({"total": response.get("total", 0), "file": files})
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
        item.setInfo("video", {"plot": _addon.getLocalizedString(30071)})  # "Changes the order of the search results"
        item.setProperty("SpecialSort", "top")
        url = get_url(action="choose_sort", query=str(search_terms), sort=sort, **_match_params(match))
        xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=False)

        # file_info details known from earlier (cache); the missing ones are fetched after the listing is shown
        cache = _details_cache()
        details = {file_info["ident"]: cache.get(file_info["ident"]) for file_info in rows}
        runtime = file_details.runtime_minutes((match or {}).get("runtime"))
        mediatype = (match or {}).get("mediatype") or "movie"
        pages = [[_with_details(file_info, details.get(file_info.get("ident"))) for file_info in files] for files in pages]
        rows = [_with_details(file_info, details[file_info["ident"]]) for file_info in rows]

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
        # The order stays: moving files with a wrong length down made the benchmark worse (false alarms)
        for file_info, source in sources:
            _apply_details(source, details.get(file_info["ident"]), runtime, mediatype)

        for file_info, source in sources:
            item = xbmcgui.ListItem(
                label=_source_label(source, file_info.get("img", "")),
                label2=metadata_line(source, include_score=True, include_quality=True),
            )
            item.setInfo("video", {
                "title": source.get("title") or file_info.get("name", ""),
                "size": source.get("size_bytes", 0),
                "plot": _source_plot(source, _has_preview(file_info)),
                "mediatype": "video",
            })
            _set_stream_details(item, source)
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
            item.setInfo("video", {"plot": _addon.getLocalizedString(30072).format(PAGE_SIZE)})  # "Shows the next 30 results"
            item.setProperty("SpecialSort", "bottom")
            url = get_url(action="list_search_results", query=str(search_terms), sort=sort, offset=next_offset, **_match_params(match))
            xbmcplugin.addDirectoryItem(_handle, url, item, isFolder=True)

        # Kodi sorting (side menu) only reorders the loaded page
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_SIZE)
        xbmcplugin.setContent(_handle, "videos")
        top = [file_info["ident"] for file_info, _ in sources[:file_details.LIST_COUNT]]
        _start_details([ident for ident in top if not cache.known(ident)], top,
                       {"key": _current_listing_key(), "terms": search_terms, "sort": sort, "offset": offset,
                        "match": match, "responses": answers})
        # replace: a new order of the same search takes the place of the old one in history
        xbmcplugin.endOfDirectory(_handle, updateListing=replace)
    except Exception as exc:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30007).format(str(exc)),
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

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
        if details.get("runtime"):
            match["runtime"] = str(details["runtime"])  # minutes: checks the length of the found files
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
        if ep.get("runtime"):
            match["runtime"] = ep["runtime"]  # minutes: checks the length of the found files
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


def search_and_score_tmdbh(params: Dict[str, Any], search_query: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Searches Webshare for TMDb Helper and scores the files, best first.
    None when no query got an answer from Webshare (the user was notified)."""
    queries = [search_query] if search_query else build_tmdbh_queries(params)
    if not queries:
        return []

    max_results = int(_addon.getSetting("tmdbh_max_results") or "20")
    mediatype = (params.get("mediatype") or "movie").lower()
    merged: Dict[str, Dict[str, Any]] = {}

    xbmc.log(f"[KodiSimpleStream] TMDbH queries: {queries}", xbmc.LOGINFO)

    # Best-match order: search words are OR-ed, other orders bring files sharing just one word.
    # Parallel requests, merged in the order of the queries like before.
    try:
        responses = get_api().search_all(queries, sort="")
    except Exception as exc:  # the client setup (TLS context) failed, reported like failed queries
        responses = [exc] * len(queries)
    errors = []
    for term, response in zip(queries, responses):
        if isinstance(response, Exception):
            xbmc.log(f"[KodiSimpleStream] search failed for term '{term}': {response}", xbmc.LOGWARNING)
            errors.append(response)
            continue
        response = response.get("response", {})

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

    if len(errors) == len(queries):
        # Not "no sources" – Webshare did not answer (timeout, no connection)
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            _addon.getLocalizedString(30007).format(str(errors[0])),
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return None

    sorted_items = sorted(merged.values(), key=_tmdbh_sort_key(language_preference()), reverse=True)
    debug_scores = _addon.getSettingBool("tmdbh_show_debug_scores")
    for it in sorted_items[:10]:
        if debug_scores:
            xbmc.log(
                f"[KodiSimpleStream] score={it['score']} quality={it['quality']} size={it['size']} name={it['name']}",
                xbmc.LOGINFO,
            )
    return sorted_items[:max_results]


def _tmdbh_sort_key(preference: str):
    """Match score with the language bonus, then the preferred quality and the size (best first, reverse sort)."""
    return lambda x: (
        x["score"] + (LANG_PREF_BONUS if matches_language_preference(x["source"], preference) else 0),
        x["quality_pref"],
        x["size"],
    )


def _fetch_tmdbh_details(results: List[Dict[str, Any]], count: int, deadline: float,
                         cache: file_details.DetailsCache, fetcher: file_details.Fetcher) -> None:
    """file_info of the first `count` results that the cache does not know, waiting `deadline` seconds at most.
    fetcher: the one of this plugin call, so an ident in flight or failed after an earlier deadline is not
    requested again and at most WORKERS requests run in total; its late answers are cached now.
    Answers later than the deadline are left out (the rows show the name guesses); the requests still
    running end by their timeout. Run before a dialog opens: the GUI stays on this thread."""
    missing = [result["ident"] for result in results[:count] if not cache.known(result["ident"])]
    if not missing or not _file_details_enabled():
        return
    began = time.monotonic()
    home = _home()
    if not file_details.blocked(home):
        fetcher.request(missing, deadline)  # nothing after a failure, nothing requested twice
    fetcher.wait(deadline, idents=missing)
    fetcher.cancel_pending()
    arrived = {ident: info for ident, info in fetcher.snapshot().items() if not cache.known(ident)}
    found = _store_details(cache, fetcher, arrived, home) if arrived or fetcher.blocked else 0
    xbmc.log(f"[KodiSimpleStream] file_info for TMDb Helper: {sum(1 for ident in missing if ident in arrived)}/"
             f"{len(missing)} answers, {found} with details, {time.monotonic() - began:.2f} s{_fetch_problem(fetcher)}",
             xbmc.LOGINFO)


def _apply_tmdbh_details(results: List[Dict[str, Any]], params: Dict[str, Any], cache: file_details.DetailsCache) -> None:
    """Known details on the sources (real resolution, length, audio) and the order again: a CZE track
    counts for the Czech dub preference. Without details nothing changes."""
    runtime = file_details.runtime_minutes(params.get("runtime"))
    mediatype = (params.get("mediatype") or "movie").lower()
    changed = False
    for result in results:
        info = cache.get(result["ident"])
        if not info:
            continue
        plain = {key: value for key, value in result.items() if key not in ("source", "details")}
        source = normalize_source(_with_details(plain, info))
        source["score"] = result["score"]
        result["source"] = _apply_details(source, info, runtime, mediatype)
        result["details"] = info
        changed = True
    if changed:
        results.sort(key=_tmdbh_sort_key(language_preference()), reverse=True)  # stable


def _autoplay_rejection(result: Dict[str, Any], params: Dict[str, Any]) -> str:
    """Why the auto-play must not take this file: a trailer/sample, a part, another year (matching.autoplay_concern)
    or a length far off the runtime; "" when it may be played. An unknown length is no reason (12 % of files
    are not analysed, file_info may be late), a known runtime is needed for the length check."""
    concern = autoplay_concern(result, params)
    if concern:
        return concern
    runtime = file_details.runtime_minutes(params.get("runtime"))
    if file_details.length_mismatch(result.get("details"), runtime, params.get("mediatype") or "movie"):
        return "length"
    return ""


def play_ident(ident: str) -> None:
    """Asks Webshare for the download link only when the file is played."""
    video_url = ""
    reason = ""  # why there is no link, for the notification
    for reuse_token in (True, False):
        api, reused = login_api(reuse_token)
        if not api:
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
            return
        try:
            video_url = api.get_download_link(ident)
        except WebshareStatusError as exc:
            xbmc.log(f"[KodiSimpleStream] file_link failed for {ident}: {exc}", xbmc.LOGWARNING)
            # Webshare's own words, e.g. "File temporarily unavailable."
            reason = f"Webshare: {exc.message}" if exc.message else ""
        except Exception as exc:
            # Connection error or timeout – a new login would not help
            xbmc.log(f"[KodiSimpleStream] file_link failed for {ident}: {exc}", xbmc.LOGWARNING)
            # WebshareError texts are short ("Webshare did not respond in time"), anything else is not shown
            reason = str(exc) if isinstance(exc, WebshareError) else ""
            break
        if video_url or not reused:
            break
        # The token cached by an earlier call may have expired (error status or an empty link) – log in
        # again, only once (the second pass does not reuse the token)
    if not video_url:
        xbmcgui.Dialog().notification(
            _addon.getAddonInfo("name"),
            reason or _addon.getLocalizedString(30040),  # "Webshare returned no download link"
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
        # The select dialog shows label2 under every row and it starts with the quality: no [FHD] tag here
        label=_source_label(source, result.get("img", ""), quality_tag=False),
        label2=metadata_line(source, include_score=True, include_quality=True),
    )
    item.setInfo("video", {
        "title": source.get("title") or result.get("name", ""),
        "size": source.get("size_bytes", result.get("size", 0)),
        "plot": _source_plot(source),
        "mediatype": "video",
    })
    _set_stream_details(item, source)
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


def select_tmdbh_source(params: Dict[str, Any], results: Optional[List[Dict[str, Any]]] = None,
                        cache: Optional[file_details.DetailsCache] = None,
                        fetcher: Optional[file_details.Fetcher] = None) -> None:
    """Shows a modal source picker for TMDb Helper and resolves the selected item.
    results: already found sources for the primary queries (play_best_tmdbh_source), searched again only for a new query.
    The top rows get their file_info details before the dialog opens (PICKER_DEADLINE at most); cache and
    fetcher: those of the auto-play check, one fetcher for the whole plugin call."""
    current_query = _primary_tmdbh_query(params)
    active_query: Optional[str] = None
    cache = cache or _details_cache()
    if fetcher is None:
        fetcher = file_details.Fetcher([], 0)

    while True:
        if results is None:
            results = search_and_score_tmdbh(params, active_query)
            if results is None:
                xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
                return
        if results:
            # One constant for all devices: the wait ends as soon as all answers are in (about 0.3 s on a PC),
            # the deadline only caps slow ones (TV boxes with a slow TLS handshake)
            _fetch_tmdbh_details(results, file_details.PICKER_COUNT, file_details.PICKER_DEADLINE, cache, fetcher)
            _apply_tmdbh_details(results, params, cache)
        if not results:
            xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
            new_query = prompt_change_search(current_query)
            if new_query:
                current_query = new_query
                active_query = new_query
                results = None
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
                results = None
            # Cancelled change shows the same sources again
            continue

        chosen = results[selected - 1]
        xbmc.log(f"[KodiSimpleStream] TMDbH selected source score={chosen['score']} name={chosen['name']}", xbmc.LOGINFO)
        play_ident(chosen["ident"])
        return


def list_tmdbh_sources(params: Dict[str, Any]) -> None:
    # Searching needs no login, playing an item asks for it (play_ident)
    results = search_and_score_tmdbh(params)
    if results is None:
        # Webshare did not answer, the user was notified – "no sources" would be misleading
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    if not results:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.endOfDirectory(_handle)
        return

    # Not reachable from the router (TMDb Helper uses tmdbh_play): only the cached details, no fetching
    _apply_tmdbh_details(results, params, _details_cache())
    for result in results:
        source = result.get("source") or normalize_source(result)
        item = xbmcgui.ListItem(
            label=_source_label(source, result.get("img", "")),
            label2=metadata_line(source, include_score=True, include_quality=True),
        )
        item.setInfo("video", {"title": source["title"], "size": result["size"], "mediatype": "video",
                               "plot": _source_plot(source, _has_preview(result))})
        _set_stream_details(item, source)
        item.setArt(_resolution_badge_art(source, result.get("img", "")))
        item.setProperty("IsPlayable", "true")
        _add_preview_menu(item, result, source_title_label(source))
        xbmcplugin.addDirectoryItem(_handle, get_url(action="play_ident", ident=result["ident"]), item, isFolder=False)

    xbmcplugin.setContent(_handle, "videos")
    xbmcplugin.endOfDirectory(_handle)


def play_best_tmdbh_source(params: Dict[str, Any]) -> None:
    results = search_and_score_tmdbh(params)
    if results is None:
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return
    if not results:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "No matching sources found", xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return

    min_score = int(_addon.getSetting("tmdbh_auto_play_min_score") or "80")
    best = results[0]
    cache = _details_cache()
    fetcher = file_details.Fetcher([], 0)  # one for the check and the picker after it
    if best["score"] < min_score:
        xbmc.log(f"[KodiSimpleStream] Best score {best['score']} below threshold {min_score}, showing source picker", xbmc.LOGINFO)
        # The picker shows the same sources, no second search
        select_tmdbh_source(params, results, cache, fetcher)
        return

    # Details only when they can change the choice: the length check needs the runtime (TMDb Helper does
    # not pass one, see docs/tmdbhelper), a CZE track the Czech dub preference
    if file_details.runtime_minutes(params.get("runtime")) or language_preference() == "cz_audio":
        _fetch_tmdbh_details(results, file_details.AUTOPLAY_COUNT, file_details.AUTOPLAY_DEADLINE, cache, fetcher)
    _apply_tmdbh_details(results, params, cache)
    # The first of the best candidates above the threshold that is not a trailer, a part, another year
    # or of a wrong length; none -> the picker, never a doubtful file
    for candidate in results[:file_details.AUTOPLAY_COUNT]:
        if candidate["score"] < min_score:
            continue
        rejection = _autoplay_rejection(candidate, params)
        if not rejection:
            xbmc.log(f"[KodiSimpleStream] Autoplaying source score={candidate['score']} name={candidate['name']}", xbmc.LOGINFO)
            play_ident(candidate["ident"])
            return
        xbmc.log(f"[KodiSimpleStream] Autoplay skips ({rejection}) score={candidate['score']} name={candidate['name']}", xbmc.LOGINFO)

    xbmcgui.Dialog().notification(
        _addon.getAddonInfo("name"),
        _addon.getLocalizedString(30074),  # "The best sources do not fit, choose one"
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )
    select_tmdbh_source(params, results, cache, fetcher)


def tmdbh_play(params: Dict[str, Any]) -> None:
    queries = build_tmdbh_queries(params)
    if not queries:
        xbmcgui.Dialog().notification(_addon.getAddonInfo("name"), "Missing required metadata for TMDb Helper search", xbmcgui.NOTIFICATION_ERROR, 4000)
        xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        return
    # Searching needs no login, but playback does: without credentials ask for them now (30009),
    # do not search, report "no sources" or offer a new search. The login itself waits for play_ident.
    if not _credentials():
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
    global _refresh_pass
    params = dict(parse_qsl(paramstring))
    action = params.get("action")

    if action is None:
        list_categories()
        return

    if action in _LISTING_ACTIONS:
        # The one refresh after the file details arrived: same search answers, no new details job
        _refresh_pass, listing = _take_refresh_marker()
        if listing.get("terms") and isinstance(listing.get("responses"), list):
            # replace=False: the first listing already replaced the history entry; Kodi pops the
            # parent path again on every fetch with updateListing (GUIMediaWindow::GetDirectory)
            list_search_results([str(term) for term in listing["terms"]], _int_param(listing, "sort"),
                                _int_param(listing, "offset") or 0, False,
                                match=_parse_match(json.dumps(listing.get("match"))), cached=listing["responses"])
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
        show_preview(params.get("ident", ""), params.get("stripe", ""), _int_param(params, "count") or 0,
                     params.get("title", ""), params.get("size", ""))
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
    elif action == "file_details":
        fetch_details(params.get("token", ""))
    elif action == "choose_sort":
        choose_sort(_parse_query(params["query"]), _int_param(params, "sort") or 0, match=_parse_match(params.get("match")))
    else:
        raise ValueError(f"Invalid paramstring: {paramstring}!")

# ----------------------------------------------------------------------------
if __name__ == "__main__":
    # Kodi passes plugin parameters in `sys.argv[2]`, including the leading '?'
    # This may be missing during CLI testing – handle gracefully.
    router(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else "")