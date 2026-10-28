# -*- coding: utf-8 -*-
"""Webshare file_info details of the listed files: the real length, resolution and audio tracks.

A compact copy of the parse_file_info output per ident is cached for the Kodi session (home window
property) and on disk (addon_data JSON, TTL and size capped); missing ones are fetched anonymously
by at most WORKERS threads (HTTP only, the GUI stays on the caller's main thread), with a time limit
and without retries once Webshare answers 403 or a request fails. The length is checked against the
TMDb runtime: a file far off the runtime is most likely another film, an episode, a trailer or a part.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree

from resources.lib import preview

WORKERS = 4
# Request starts at least this far apart: Webshare answered single HTTP 403 at ~17 requests/s sustained
START_INTERVAL = 0.06
REQUEST_TIMEOUT = (2.05, 3)
REQUEST_WAIT = 4.0
# Rows that get details: the list (background script), the TMDb Helper picker and the auto-play candidates
LIST_COUNT = 15
PICKER_COUNT = 10
AUTOPLAY_COUNT = 5
# Seconds: the background script of a list starts no request later than LIST_BUDGET after its start;
# the picker and the auto-play wait at most their deadline and show or check what arrived by then
LIST_BUDGET = 6.0
PICKER_DEADLINE = 1.2
AUTOPLAY_DEADLINE = 2.0
# After HTTP 403/429 (rate limit) no file_info request for this long (session window property)
BLOCK_SECONDS = 300

CACHE_FILE = "file_details.json"
CACHE_VERSION = 1
CACHE_TTL = 14 * 24 * 3600
CACHE_MAX = 2000
SESSION_PROPERTY = "kodisimplestream.details"
SESSION_MAX = 300
# "No details" (not analysed, not OK) is remembered for the session only, shorter: Webshare analyses files later
MISS_TTL = 15 * 60
BLOCK_PROPERTY = "kodisimplestream.details_blocked"

# Length / runtime ratios accepted as the same video (measured on the benchmark files: 92 % of the right
# films within +-10 %; parts CD1/CD2 and short cuts are the few false alarms)
MOVIE_RANGE = (0.8, 1.5)
EPISODE_RANGE = (0.45, 1.5)
_KEEP_STREAMS = 12
_STOP_STATUSES = (403, 429)


# --- details of one file ---

def compact(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The cached part of parse_file_info output: without the name (the list has it), streams capped."""
    if not isinstance(info, dict):
        return None
    kept = {key: value for key, value in info.items() if key not in ("name", "video", "audio") and isinstance(value, str)}
    for kind in ("video", "audio"):
        streams = [stream for stream in info.get(kind) or [] if isinstance(stream, dict)]
        kept[kind] = [{key: value for key, value in stream.items() if isinstance(value, str)}
                      for stream in streams[:_KEEP_STREAMS]]
    return kept


def length_seconds(info: Optional[Dict[str, Any]]) -> Optional[float]:
    return preview._number((info or {}).get("length"))


def runtime_minutes(value: Any) -> Optional[float]:
    """TMDb runtime in minutes; 0, missing or absurd values are unknown."""
    number = preview._number(value)
    return number if number and 1 <= number <= 1000 else None


def length_mismatch(info: Optional[Dict[str, Any]], runtime: Any, mediatype: str = "movie") -> Optional[bool]:
    """True when the file length is far off the TMDb runtime (minutes), None when either is unknown."""
    seconds, minutes = length_seconds(info), runtime_minutes(runtime)
    if not seconds or not minutes:
        return None
    low, high = EPISODE_RANGE if str(mediatype).lower() == "episode" else MOVIE_RANGE
    ratio = seconds / (minutes * 60)
    return not low <= ratio <= high


def resolution(info: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """("FHD", "1920×800") from the real frame size; the width decides for wide films, the height for 4:3."""
    video = preview._main_video(info or {})
    width, height = preview._number(video["width"]), preview._number(video["height"])
    if not width or not height:
        return None
    if width >= 3200 or height >= 1800:
        quality = "4K"
    elif width >= 1700 or height >= 1000:
        quality = "FHD"
    elif width >= 1200 or height >= 700:
        quality = "HD"
    else:
        quality = "SD"
    return quality, f"{int(width)}×{int(height)}"


def _audio(info: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [stream for stream in (info or {}).get("audio") or [] if isinstance(stream, dict)]


def audio_languages(info: Optional[Dict[str, Any]]) -> List[str]:
    """Two-letter codes of the tagged audio tracks (CZ, EN …), unknown (UND) left out.
    A CZE track is reliable evidence of a Czech dub; a missing one is not (mp4/avi tag their only track ENG or UND)."""
    codes: List[str] = []
    for stream in _audio(info):
        code = preview.language_code(stream.get("language"))
        if code != "?" and code not in codes:
            codes.append(code)
    return codes


def audio_text(info: Optional[Dict[str, Any]], limit: int = 4) -> str:
    """"CZ 5.1, EN" – the language and the channel layout when it is more than stereo."""
    parts: List[str] = []
    for stream in _audio(info):
        channels = preview.format_channels(stream.get("channels"))
        part = preview.language_code(stream.get("language"))
        if channels and channels not in ("1.0", "2.0"):
            part += f" {channels}"
        if part not in parts:
            parts.append(part)
    if len(parts) > limit:
        parts = parts[:limit] + [f"+{len(parts) - limit}"]
    return ", ".join(parts)


def video_stream(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Arguments of xbmc.VideoStreamDetail for the skin's stream flags, None without a frame size or codec."""
    video = preview._main_video(info or {})
    width, height = preview._number(video["width"]), preview._number(video["height"])
    codec = preview._clip(str(video["format"] or "")).lower()
    if not (width and height) and not codec:
        return None
    return {"width": int(width or 0), "height": int(height or 0), "codec": codec,
            "duration": int(length_seconds(info) or 0)}


def audio_streams(info: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Arguments of xbmc.AudioStreamDetail: channels, codec (lower case like Kodi's own), ISO 639-2 language."""
    streams = []
    for stream in _audio(info):
        language = preview._clip(str(stream.get("language") or "")).lower()
        if language.upper() in preview._UNKNOWN_LANGUAGES or not language.isalpha():
            language = ""
        channels = preview._number(stream.get("channels"))
        streams.append({"channels": int(channels) if channels else -1,
                        "codec": preview._clip(str(stream.get("format") or "")).lower(), "language": language})
    return streams


# --- cache ---

def _fresh(entry: Any, now: float) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        age = now - float(entry.get("t"))
    except (TypeError, ValueError):
        return False
    has_info = isinstance(entry.get("info"), dict)
    return 0 <= age < (CACHE_TTL if has_info else MISS_TTL)


def _newest(entries: Dict[str, Dict[str, Any]], keep: int) -> Dict[str, Dict[str, Any]]:
    if len(entries) <= keep:
        return entries
    newest = sorted(entries.items(), key=lambda item: float(item[1].get("t") or 0), reverse=True)[:keep]
    return dict(newest)


class DetailsCache:
    """ident -> details: the session window property first, then addon_data/<CACHE_FILE>, then the
    info.json of a video preview (special://temp); new details are written to both on save()."""

    def __init__(self, window: Any = None, folder: str = "", preview_root: str = "", now: Optional[float] = None):
        self.window = window
        self.path = os.path.join(folder, CACHE_FILE) if folder else ""
        self.preview_root = preview_root
        self.now = time.time() if now is None else now
        self.session = self._read_session()
        self._disk: Optional[Dict[str, Dict[str, Any]]] = None
        self.new: Dict[str, Dict[str, Any]] = {}

    def _read_session(self) -> Dict[str, Dict[str, Any]]:
        if self.window is None:
            return {}
        try:
            data = json.loads(self.window.getProperty(SESSION_PROPERTY) or "{}")
        except ValueError:
            return {}
        return {ident: entry for ident, entry in data.items() if _fresh(entry, self.now)} if isinstance(data, dict) else {}

    def _read_disk(self) -> Dict[str, Dict[str, Any]]:
        if not self.path:
            return {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("entries"), dict):
            return {}
        return {ident: entry for ident, entry in data["entries"].items()
                if preview.is_valid_ident(ident) and _fresh(entry, self.now) and isinstance(entry.get("info"), dict)}

    def lookup(self, ident: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """(known, details): known also for a fresh "no details" entry, which is not requested again."""
        for entries in (self.new, self.session):
            entry = entries.get(ident)
            if _fresh(entry, self.now):
                return True, entry.get("info")
        if self._disk is None:
            self._disk = self._read_disk()
        entry = self._disk.get(ident)
        if entry is not None:
            return True, entry["info"]
        if self.preview_root and preview.is_valid_ident(ident):
            info = preview.cached_file_info(os.path.join(self.preview_root, ident))
            if info is not None and preview.is_analysed(info):
                return True, compact(info)
        return False, None

    def get(self, ident: str) -> Optional[Dict[str, Any]]:
        return self.lookup(ident)[1]

    def known(self, ident: str) -> bool:
        return self.lookup(ident)[0]

    def put(self, ident: str, info: Optional[Dict[str, Any]]) -> None:
        """Stores fetched details; None or an unanalysed file is a "no details" entry for the session."""
        if not preview.is_valid_ident(ident):
            return
        entry: Dict[str, Any] = {"t": int(self.now)}
        if isinstance(info, dict) and preview.is_analysed(info):
            entry["info"] = compact(info)
        self.new[ident] = entry

    def save(self) -> None:
        """Writes the new entries: the window property (main thread only) and the merged disk file."""
        if not self.new:
            return
        if self.window is not None:
            # Read again: another plugin call (preview, picker) may have saved since this one started
            session = _newest({**self._read_session(), **self.new}, SESSION_MAX)
            self.window.setProperty(SESSION_PROPERTY, json.dumps(session, ensure_ascii=False, separators=(",", ":")))
            self.session = session
        positive = {ident: entry for ident, entry in self.new.items() if "info" in entry}
        if self.path and positive:
            # Read again: another plugin call may have written meanwhile; the last writer wins otherwise
            entries = _newest({**self._read_disk(), **positive}, CACHE_MAX)
            temp = f"{self.path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(temp, "w", encoding="utf-8") as handle:
                    json.dump({"version": CACHE_VERSION, "entries": entries}, handle, ensure_ascii=False, separators=(",", ":"))
                os.replace(temp, self.path)
                self._disk = entries
            except OSError:
                try:
                    os.remove(temp)
                except OSError:
                    pass
        self.new = {}


def blocked(window: Any, now: Optional[float] = None) -> bool:
    """True for BLOCK_SECONDS after Webshare refused file_info with 403/429 (set by block())."""
    if window is None:
        return False
    try:
        return 0 <= (time.time() if now is None else now) - float(window.getProperty(BLOCK_PROPERTY) or "x") < BLOCK_SECONDS
    except ValueError:
        return False


def block(window: Any) -> None:
    if window is not None:
        window.setProperty(BLOCK_PROPERTY, str(int(time.time())))


# --- fetching ---

class Fetcher:
    """file_info of the idents, in their order, by at most `workers` threads doing HTTP only.

    One Fetcher serves one plugin call: request() can add idents later (the picker after the auto-play
    check, the picker again after a cancelled new search), but an ident is never requested twice (in
    flight, answered or failed) and at most `workers` requests run at once in total. Requests start no
    later than `start_window` seconds after the request() that queued them, starts are START_INTERVAL
    apart, and after HTTP 403/429, a timeout or a network error no further request starts (no retry);
    a broken answer of one file only skips that file. results: ident -> details or None (an answer
    without details); idents missing in results failed or were not requested.
    """

    def __init__(self, idents: Iterable[str], start_window: float, fetch: Optional[Callable[[str], Any]] = None,
                 workers: int = WORKERS, interval: float = START_INTERVAL):
        self.results: Dict[str, Optional[Dict[str, Any]]] = {}
        self.errors: Dict[str, BaseException] = {}
        self.blocked = False  # Webshare limits the rate: the caller blocks requests for a while
        self.stopped = threading.Event()
        self._queue: List[str] = []
        self._requested: set = set()  # queued, in flight, answered or failed: never requested again
        self._lock = threading.Lock()
        self._interval = interval
        self._workers = workers
        self.started = time.monotonic()
        self._start_until = self.started
        self._next_start = self.started
        self._own_fetch = fetch is None
        self._session_ready = False
        self._fetch = fetch or (lambda ident: preview.fetch_file_info(ident, REQUEST_TIMEOUT, REQUEST_WAIT))
        self._threads: List[threading.Thread] = []
        self._active = 0  # workers that still take idents; one that found nothing to start has left
        self.request(idents, start_window)

    def request(self, idents: Iterable[str], start_window: float) -> None:
        """Queues the valid idents not requested yet and lets requests start for `start_window` seconds
        from now; nothing after a failure or stop(). Main thread only (it starts the threads)."""
        if self.stopped.is_set():
            return
        with self._lock:
            new = [ident for ident in dict.fromkeys(idents)
                   if preview.is_valid_ident(ident) and ident not in self._requested]
            self._requested.update(new)
            self._queue.extend(new)
            self._start_until = max(self._start_until, time.monotonic() + start_window)
            count = min(self._workers - self._active, len(self._queue))
        if count <= 0:
            return  # the running workers take the new idents
        if self._own_fetch and not self._session_ready:
            try:
                preview._http()  # build the shared session once, before the threads use it
                self._session_ready = True
            except Exception as exc:  # no session (TLS setup failed): no details, the rows keep the name guesses
                self.errors[""] = exc
                self.stopped.set()
                return
        with self._lock:
            self._active += count
        threads = [threading.Thread(target=self._run, daemon=True) for _ in range(count)]
        self._threads = [thread for thread in self._threads if thread.is_alive()] + threads
        for thread in threads:
            thread.start()

    def _take(self) -> Tuple[Optional[str], float]:
        """The next ident and the delay before its start; (None, 0) and the worker leaves (counted under
        the same lock, so request() starts a new worker for idents queued after this decision)."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            if self.stopped.is_set() or not self._queue or start > self._start_until:
                self._active -= 1
                return None, 0.0
            self._next_start = start + self._interval
            return self._queue.pop(0), start - now

    def _leave(self) -> None:
        with self._lock:
            self._active -= 1

    def _run(self) -> None:
        while True:
            ident, delay = self._take()
            if ident is None:
                return
            if delay > 0 and self.stopped.wait(delay):
                self._leave()
                return
            try:
                info = self._fetch(ident)
            except ElementTree.ParseError as exc:  # one broken answer: that file has no details
                with self._lock:
                    self.errors[ident] = exc
                    self.results[ident] = None
                continue
            except Exception as exc:  # HTTP 403/429, timeout, no connection: stop, no retry
                if isinstance(exc, preview.FileInfoStatusError) and getattr(exc, "status", None) not in _STOP_STATUSES:
                    # One file answered with an error (404, 500): no details for it, the others go on;
                    # kept as a miss, so the next visit does not stop on it again
                    with self._lock:
                        self.errors[ident] = exc
                        self.results[ident] = None
                    continue
                with self._lock:
                    self.errors[ident] = exc
                    if getattr(exc, "status", None) in _STOP_STATUSES:
                        self.blocked = True
                    self._active -= 1
                self.stopped.set()
                return
            with self._lock:
                self.results[ident] = info

    def done(self) -> bool:
        return not any(thread.is_alive() for thread in self._threads)

    def wait(self, timeout: float, abort: Optional[Callable[[], bool]] = None,
             idents: Optional[Iterable[str]] = None) -> Dict[str, Optional[Dict[str, Any]]]:
        """Waits until all requests ended (with `idents`: the requested ones of them) or `timeout` seconds
        from now, returns what arrived. abort(): checked between short waits (Kodi exit, a newer job)."""
        end = time.monotonic() + timeout
        wanted = None if idents is None else set(idents)
        while True:
            if wanted is not None:
                with self._lock:
                    if not (wanted & self._requested) - set(self.results) - set(self.errors):
                        break
            alive = [thread for thread in self._threads if thread.is_alive()]
            remaining = end - time.monotonic()
            if not alive or remaining <= 0 or (abort is not None and abort()):
                break
            alive[0].join(min(0.05, remaining))
        return self.snapshot()

    def snapshot(self) -> Dict[str, Optional[Dict[str, Any]]]:
        with self._lock:
            return dict(self.results)

    def cancel_pending(self) -> None:
        """Requests not started yet are dropped (never sent, so a later request() may queue them again);
        the ones in flight go on and their answers land in results."""
        with self._lock:
            self._requested.difference_update(self._queue)
            self._queue.clear()

    def stop(self) -> None:
        """No new request starts; the ones in flight end by their timeout (Kodi waits for them at the script end)."""
        self.stopped.set()
