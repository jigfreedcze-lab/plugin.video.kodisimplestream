# -*- coding: utf-8 -*-
"""Video preview: the frames of the Webshare preview stripe shown one by one in a window,
next to the real video and audio parameters from Webshare file_info."""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from resources.lib.source_ui import format_size

FRAME_SECONDS = 1.0
DOWNLOAD_TIMEOUT = (3.05, 10)
CACHE_ROOT = "special://temp/kodisimplestream/preview"
# A stripe has about 115 kB (10 frames of 320x180); limits against broken or foreign files
MAX_STRIPE_BYTES = 2 * 1024 * 1024
MAX_STRIPE_PIXELS = 20_000_000
MAX_FRAMES = 50
# Webshare serves the stripes from img.webshare.cz; other hosts are not downloaded (a hand-made plugin URL
# must not make Kodi fetch LAN addresses or feed foreign files to Pillow), redirects are checked the same way
STRIPE_HOST = "webshare.cz"
MAX_REDIRECTS = 3
# Formats Pillow may open: the stripe is a JPEG; anything else (EPS runs Ghostscript) is refused before decoding
STRIPE_FORMATS = ("JPEG", "PNG", "WEBP")
# Cached previews kept in CACHE_ROOT (about 130 kB each); older ones are deleted on the next download
MAX_CACHED = 50
# Actions that close the window – not every action, mouse moves would close it at once.
# Kodi passes mouse actions to onAction only while a control has focus, hence the focused button in show().
CLOSE_ACTIONS = {7, 9, 10, 13, 92, 100, 101, 117}  # select, parent dir, previous menu, stop, back, mouse clicks, context menu

# Webshare file_info, anonymous (no token): the real resolution, codecs and audio tracks of the file.
# Fetched in a background thread while the stripe downloads; the window waits for it at most
# FILE_INFO_WAIT seconds from the request and opens without it when it is late or fails.
FILE_INFO_URL = "https://webshare.cz/api/file_info/"
FILE_INFO_TIMEOUT = (3.05, 5)
FILE_INFO_WAIT = 8.0
MAX_FILE_INFO_BYTES = 256 * 1024  # a response has about 1.5 kB, 30 audio tracks about 5 kB
_INFO_FILE = "info.json"
_INFO_VERSION = 1
_INFO_FIELDS = ("name", "size", "type", "length", "bitrate", "format", "width", "height", "fps")
_STREAM_FIELDS = {"video": ("format", "width", "height", "fps"), "audio": ("format", "channels", "language")}
MAX_STREAMS = 40
# Cover art is listed among the video streams (an MKV attachment or an MP4 cover)
_IMAGE_FORMATS = {"MJPEG", "PNG", "BMP", "GIF", "JPEG", "WEBP", "TIFF"}
MAX_AUDIO_ROWS = 6

# Window layout. WindowDialog coordinates are stretched over the screen (the GUI render buffer, see
# gui_size), whatever its resolution:
# always 1280x720 (Kodi 21 has no Window.setCoordinateResolution), so one unit is 1.5 px at 1080p and
# a frame can be drawn up to 1 px off its size there. The sizes below are 1280x720 units.
SKIN_WIDTH, SKIN_HEIGHT = 1280, 720
DEFAULT_SCREEN = (1920, 1080)
DEFAULT_FRAME = (320, 180)
PANEL_GAP = 40
PANEL_LABEL_WIDTH = 150
PANEL_VALUE_WIDTH = 380
# A 1:1 frame larger than this (a stripe of big frames on a small screen) is scaled down to leave room for the panel
FRAME_MAX = (SKIN_WIDTH - 40 - PANEL_GAP - PANEL_LABEL_WIDTH - PANEL_VALUE_WIDTH, 440)
ROW_HEIGHT = 30
COUNTER_HEIGHT = 40
NAME_TOP, NAME_HEIGHT = 610, 80
LABEL_COLOR = "FF9E9E9E"

_IDENT_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_COUNT_FILE = "count"


def is_valid_ident(ident: str) -> bool:
    """Webshare idents are short alphanumeric codes; anything else must not become a folder name."""
    return isinstance(ident, str) and bool(_IDENT_RE.fullmatch(ident))


def is_stripe_url(url: str) -> bool:
    """Only http(s) URLs on webshare.cz or its subdomains are downloaded."""
    if not isinstance(url, str):
        return False
    # urlparse and urllib3 (which requests uses) read "\", "@" and control characters differently,
    # "http://lan-host\@img.webshare.cz/" would pass the check here and go to lan-host; stripes never contain them
    if any(char in url for char in "\\@") or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in url):
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:  # e.g. a malformed port or IPv6 address
        return False
    return parsed.scheme in ("http", "https") and (host == STRIPE_HOST or host.endswith("." + STRIPE_HOST))


def cache_folder(ident: str) -> str:
    """special://temp/kodisimplestream/preview/<ident> – the ident comes from URL parameters."""
    if not is_valid_ident(ident):
        raise ValueError(f"invalid ident {ident!r}")
    import xbmcvfs

    return os.path.join(xbmcvfs.translatePath(CACHE_ROOT), ident)


def _frame_paths(folder: str, count: int) -> List[str]:
    return [os.path.join(folder, f"{index}.jpg") for index in range(count)]


def prune_cache(root: str, keep_name: str, keep: int = MAX_CACHED) -> None:
    """Deletes all but the newest `keep` ident folders in root (by mtime), never the folder keep_name."""
    try:
        names = [name for name in os.listdir(root)
                 if name != keep_name and is_valid_ident(name) and os.path.isdir(os.path.join(root, name))]
        names.sort(key=lambda name: os.path.getmtime(os.path.join(root, name)), reverse=True)
    except OSError:
        return
    for name in names[max(0, keep - 1):]:  # room for keep_name
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def cached_frames(folder: str) -> List[str]:
    """Frames of an earlier preview; the count file is written last, so a half-written set is not used."""
    try:
        with open(os.path.join(folder, _COUNT_FILE), encoding="utf-8") as handle:
            count = int(handle.read().strip())
    except (OSError, ValueError):
        return []
    paths = _frame_paths(folder, count) if 0 < count <= MAX_FRAMES else []
    return paths if paths and all(os.path.isfile(path) for path in paths) else []


def _fits(width: int, height: int, count: int) -> bool:
    """True when count cuts the image into whole frames within 10 % of 16:9."""
    return width % count == 0 and abs(width / count / height - 16 / 9) <= 16 / 9 * 0.1


def split_stripe(data: bytes, count: int, folder: str) -> List[str]:
    """Cuts the stripe (frames side by side in one JPEG) into separate files, returns their paths."""
    # Pillow is part of the Kodi build (tools/depends pythonmodule-pil: Windows, Android, Apple, webOS);
    # there is no script.module.pil for Omega. Imported only when a preview is requested.
    from PIL import Image

    # Image.open only reads the header; the format is checked before anything is decoded.
    # (Image.open(formats=...) needs Pillow 7.1, Kodi 21 for Windows bundles Pillow 6.2.)
    strip = Image.open(io.BytesIO(data))
    if strip.format not in STRIPE_FORMATS:
        raise ValueError(f"unexpected stripe format {strip.format!r}")
    if strip.width * strip.height > MAX_STRIPE_PIXELS:
        raise ValueError(f"stripe too large: {strip.width}x{strip.height}")
    strip = strip.convert("RGB")
    # Webshare frames are 16:9 (320x180 or 649x365) and fill the width exactly, also for 4:3 videos
    # (pillarboxed into 320x180, checked on real stripes); a count that does not cut the image into
    # such frames would mix neighbouring frames and is replaced by the count inferred from the width
    if not 0 < count <= MAX_FRAMES or not _fits(strip.width, strip.height, count):
        count = min(MAX_FRAMES, max(1, round(strip.width / (strip.height * 16 / 9))))
    width = strip.width // count
    # Even frame sizes keep the 1:1 drawing pixel-exact also on a 4K GUI (2 pixels per window unit);
    # an odd 649x365 frame would be drawn at 648x364 and resampled, so its last column/row is dropped
    frame_w, frame_h = max(1, width - width % 2), max(1, strip.height - strip.height % 2)
    os.makedirs(folder, exist_ok=True)
    count_file = os.path.join(folder, _COUNT_FILE)
    if os.path.exists(count_file):
        os.remove(count_file)  # the old set is invalid until all new frames are written
    # Frames of an earlier set (another count, an interrupted cut) would stay behind for good
    for name in os.listdir(folder):
        if name.endswith(".jpg"):
            os.remove(os.path.join(folder, name))
    paths = _frame_paths(folder, count)
    for index, path in enumerate(paths):
        strip.crop((index * width, 0, index * width + frame_w, frame_h)).save(path, quality=90)
    with open(count_file, "w", encoding="utf-8") as handle:
        handle.write(str(count))
    return paths


def load_frames(stripe_url: str, count: int, folder: str) -> List[str]:
    """Frames from the cache folder, or downloaded and cut on the first request."""
    if not is_stripe_url(stripe_url):
        raise ValueError(f"not a http(s) stripe URL: {stripe_url!r}")
    cached = cached_frames(folder)
    if cached:
        try:
            os.utime(folder)  # recently used, kept by prune_cache
        except OSError:
            pass
        return cached
    # Without Pillow (e.g. a distro Kodi on the system Python) fail before downloading anything
    import PIL.Image  # noqa: F401

    prune_cache(os.path.dirname(folder), os.path.basename(folder), MAX_CACHED)
    return split_stripe(_download(stripe_url), count, folder)


def _http():
    """The Webshare session shared with the searches: one SSL context per process (see webshare.py)."""
    from resources.lib.webshare import shared_session

    return shared_session()


def _download(url: str) -> bytes:
    """The stripe bytes; redirects are followed by hand so that every hop is checked by is_stripe_url."""
    for _ in range(MAX_REDIRECTS + 1):
        with _http().get(url, timeout=DOWNLOAD_TIMEOUT, stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                if not is_stripe_url(url):
                    raise ValueError(f"stripe redirected to a foreign URL: {url!r}")
                continue
            response.raise_for_status()
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > MAX_STRIPE_BYTES:
                    raise ValueError("stripe download too large")
            return data
    raise ValueError("too many stripe redirects")


# --- Webshare file_info ---

def _clip(text: Optional[str], limit: int = 64) -> str:
    return " ".join((text or "").split())[:limit]


def parse_file_info(data: bytes) -> Optional[Dict[str, Any]]:
    """The fields used by the preview from a file_info XML response, None unless its status is OK.

    All values are strings as Webshare sends them, missing ones are left out; video and audio
    are lists of streams (one <stream> or many, also none for files Webshare has not analysed).
    """
    root = ElementTree.fromstring(data)
    if root.tag != "response" or _clip(root.findtext("status")) != "OK":
        return None
    info: Dict[str, Any] = {}
    for field in _INFO_FIELDS:
        value = _clip(root.findtext(field), 512 if field == "name" else 64)
        if value:
            info[field] = value
    for kind, fields in _STREAM_FIELDS.items():
        streams = []
        for stream in root.findall(f"{kind}/stream")[:MAX_STREAMS]:
            values = {field: _clip(stream.findtext(field)) for field in fields}
            streams.append({field: value for field, value in values.items() if value})
        info[kind] = streams
    return info


def fetch_file_info(ident: str) -> Optional[Dict[str, Any]]:
    """Anonymous file_info request (no token): POST with the ident only, size and time capped."""
    deadline = time.monotonic() + FILE_INFO_WAIT
    with _http().post(FILE_INFO_URL, data={"ident": ident}, timeout=FILE_INFO_TIMEOUT,
                       stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"file_info HTTP {response.status_code}")
        data = b""
        for chunk in response.iter_content(16 * 1024):
            data += chunk
            if len(data) > MAX_FILE_INFO_BYTES:
                raise ValueError("file_info response too large")
            if time.monotonic() > deadline:
                raise ValueError("file_info response too slow")
    return parse_file_info(data)


def cached_file_info(folder: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(folder, _INFO_FILE), encoding="utf-8") as handle:
            cached = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(cached, dict) and cached.get("version") == _INFO_VERSION and isinstance(cached.get("info"), dict):
        return cached["info"]
    return None


def load_file_info(ident: str, folder: str) -> Optional[Dict[str, Any]]:
    """file_info from the cache folder of the frames, or requested and stored there (small JSON)."""
    if not is_valid_ident(ident):
        raise ValueError(f"invalid ident {ident!r}")
    info = cached_file_info(folder)
    if info is not None:
        return info
    info = fetch_file_info(ident)
    # Not cached until Webshare has analysed the file: the next preview asks again and gets the details
    if info is not None and is_analysed(info):
        try:
            os.makedirs(folder, exist_ok=True)
            temp = os.path.join(folder, _INFO_FILE + ".tmp")
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump({"version": _INFO_VERSION, "info": info}, handle, ensure_ascii=False)
            os.replace(temp, os.path.join(folder, _INFO_FILE))
        except OSError:
            pass  # shown anyway, only requested again next time
    return info


class FileInfoRequest:
    """load_file_info in a background thread (HTTP only); the main thread reads result() and builds the GUI."""

    def __init__(self, ident: str, folder: str):
        self.info: Optional[Dict[str, Any]] = None
        self.error: Optional[BaseException] = None
        self.started = time.monotonic()
        self._thread = threading.Thread(target=self._run, args=(ident, folder), daemon=True)
        self._thread.start()

    def _run(self, ident: str, folder: str) -> None:
        try:
            self.info = load_file_info(ident, folder)
        except Exception as exc:  # network, HTTP status, broken XML: the preview opens without the details
            self.error = exc

    def result(self, wait: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """The info, waiting until `wait` (FILE_INFO_WAIT) seconds after the start at most; None when late or failed."""
        wait = FILE_INFO_WAIT if wait is None else wait
        self._thread.join(max(0.0, wait - (time.monotonic() - self.started)))
        return None if self._thread.is_alive() else self.info


# --- details panel ---

# ISO 639-2 codes (both B and T forms) used by Webshare, shown as the two-letter codes of the source labels
_LANGUAGE_CODES = {
    "CZE": "CZ", "CES": "CZ", "CS": "CZ", "CZ": "CZ",
    "SLO": "SK", "SLK": "SK", "SVK": "SK", "SK": "SK",
    "ENG": "EN", "EN": "EN",
    "JPN": "JA", "JAP": "JA", "JA": "JA",
    "GER": "DE", "DEU": "DE", "FRE": "FR", "FRA": "FR", "SPA": "ES", "ITA": "IT", "POL": "PL",
    "HUN": "HU", "RUS": "RU", "UKR": "UK", "KOR": "KO", "CHI": "ZH", "ZHO": "ZH", "POR": "PT",
}
_UNKNOWN_LANGUAGES = {"", "UND", "UNK", "MUL", "ZXX", "QAA", "NONE"}
_CHANNEL_LAYOUTS = {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}
_FORMAT_NAMES = {"EAC3": "E-AC3", "TRUEHD": "TrueHD", "OPUS": "Opus", "VORBIS": "Vorbis", "MPEG4": "MPEG-4",
                 "MPEG2VIDEO": "MPEG-2", "MPEG1VIDEO": "MPEG-1", "MSMPEG4V3": "MS MPEG-4"}
_CONTAINER_RE = re.compile(r"[A-Za-z0-9]{2,4}")


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def format_duration(seconds: Any) -> str:
    number = _number(seconds)
    if number is None:
        return ""
    minutes, secs = divmod(int(round(number)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_bitrate(bits_per_second: Any) -> str:
    number = _number(bits_per_second)
    if number is None:
        return ""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f} Mbit/s"
    return f"{max(1, round(number / 1000))} kbit/s"


def format_fps(fps: Any) -> str:
    number = _number(fps)
    return f"{round(number, 3):g} fps" if number else ""


def format_channels(channels: Any) -> str:
    number = _number(channels)
    if number is None:
        return ""
    return _CHANNEL_LAYOUTS.get(int(number), f"{int(number)} ch")


def format_codec(codec: Any) -> str:
    name = _clip(str(codec or "")).upper()
    if name.startswith("PCM_"):
        return "PCM"
    return _FORMAT_NAMES.get(name, name)


def language_code(language: Any) -> str:
    """CZE -> CZ, ENG -> EN, SLO -> SK …; UND or missing -> "?", other codes as they are."""
    code = _clip(str(language or "")).upper()
    if code in _UNKNOWN_LANGUAGES:
        return "?"
    return _LANGUAGE_CODES.get(code, code)


def _main_video(info: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level fields describe the main video stream; the stream list is the fallback (cover art skipped)."""
    streams = [stream for stream in info.get("video") or [] if isinstance(stream, dict)]
    stream = next((s for s in streams if format_codec(s.get("format")) not in _IMAGE_FORMATS), {})
    return {field: info.get(field) or stream.get(field) for field in ("format", "width", "height", "fps")}


def is_analysed(info: Dict[str, Any]) -> bool:
    """Whether file_info describes the media (video, length or audio); about 12 % of files are not analysed yet."""
    video = _main_video(info)
    return bool((_number(video["width"]) and _number(video["height"])) or format_codec(video["format"])
                or format_fps(video["fps"]) or _number(info.get("length"))
                or any(isinstance(stream, dict) for stream in info.get("audio") or []))


def details_rows(info: Optional[Dict[str, Any]], size: Any, labels: Dict[str, str]) -> List[Tuple[str, str]]:
    """(label, value) rows of the details panel. info: parse_file_info output or None;
    size: bytes from the list item, used when file_info is missing; labels: localized row names
    (video, bitrate, length, audio, size, container, unavailable, unanalysed)."""
    info = info if isinstance(info, dict) else {}
    rows: List[Tuple[str, str]] = []
    video = _main_video(info)
    width, height = _number(video["width"]), _number(video["height"])
    parts = [f"{int(width)}×{int(height)}" if width and height else "",
             format_codec(video["format"]), format_fps(video["fps"])]
    if any(parts):
        rows.append((labels["video"], " · ".join(part for part in parts if part)))
    bitrate = info.get("bitrate")
    length = _number(info.get("length"))
    if not _number(bitrate) and length and _number(info.get("size")):
        bitrate = _number(info["size"]) * 8 / length  # the average of the whole file
    if format_bitrate(bitrate):
        rows.append((labels["bitrate"], format_bitrate(bitrate)))
    if format_duration(length):
        rows.append((labels["length"], format_duration(length)))
    audio = [stream for stream in info.get("audio") or [] if isinstance(stream, dict)]
    for index, stream in enumerate(audio[:MAX_AUDIO_ROWS]):
        parts = [language_code(stream.get("language")), format_codec(stream.get("format")),
                 format_channels(stream.get("channels"))]
        rows.append((labels["audio"] if index == 0 else "", " · ".join(part for part in parts if part)))
    if len(audio) > MAX_AUDIO_ROWS:
        rows.append(("", f"+{len(audio) - MAX_AUDIO_ROWS}"))
    size_text = format_size(info.get("size")) or format_size(size)
    if size_text:
        rows.append((labels["size"], size_text))
    container = _clip(info.get("type"))
    if _CONTAINER_RE.fullmatch(container):
        rows.append((labels["container"], container.upper()))
    if not info:
        rows.append(("", labels["unavailable"]))
    elif not is_analysed(info):
        # An OK response without video, audio and length: Webshare has not analysed the file (about 12 % of files)
        rows.append(("", labels["unanalysed"]))
    return rows


# --- window ---

def _size(width: Any, height: Any) -> Optional[Tuple[int, int]]:
    try:
        size = int(str(width).strip()), int(str(height).strip())
    except (TypeError, ValueError):
        return None
    return size if all(100 <= value <= 16384 for value in size) else None


def screen_size(width: Any, height: Any) -> Tuple[int, int]:
    """Screen resolution from System.ScreenWidth/Height, DEFAULT_SCREEN when they are empty or odd."""
    return _size(width, height) or DEFAULT_SCREEN


def gui_size() -> Tuple[int, int]:
    """Pixel size of the GUI render buffer that the window coordinates are stretched over.

    xbmcgui.getScreenWidth/Height return it (CGraphicContext::GetWidth/GetHeight). When Kodi limits
    the GUI size (default 1080p on Android 4K devices, a setting elsewhere) it is smaller than the
    display mode in System.ScreenWidth/Height and the whole buffer is upscaled afterwards, so the
    1:1 math has to use the buffer. The labels and then DEFAULT_SCREEN are fallbacks only.
    """
    import xbmc
    import xbmcgui

    try:
        size = _size(xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight())
    except Exception:  # missing in an odd Kodi build or failing: use the display mode
        size = None
    return size or screen_size(xbmc.getInfoLabel("System.ScreenWidth"), xbmc.getInfoLabel("System.ScreenHeight"))


def frame_size(path: str) -> Tuple[int, int]:
    """Pixel size of a cut frame (Pillow reads the header only), DEFAULT_FRAME when it cannot be read."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        if width > 0 and height > 0:
            return width, height
    except Exception:
        pass
    return DEFAULT_FRAME


def skin_size(screen: Tuple[int, int]) -> Tuple[int, int]:
    """Window coordinates of a WindowDialog: 1280x720 on every screen."""
    return SKIN_WIDTH, SKIN_HEIGHT


def scaled(value: int, skin: Tuple[int, int]) -> int:
    """A layout size given in 1280x720 units, in the window coordinates skin."""
    return int(round(value * skin[1] / SKIN_HEIGHT))


def native_box(frame: Tuple[int, int], screen: Tuple[int, int], skin: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
    """Window-coordinate size in which the frame is drawn 1 image pixel = 1 screen pixel.

    Kodi stretches the skin_w x skin_h window coordinates over the screen (gui_size), one unit is
    screen_w/skin_w pixels wide and screen_h/skin_h pixels high; a frame of w x h pixels therefore
    takes w*skin_w/screen_w x h*skin_h/screen_h units. With skin_size() that is exact on 720p and
    1080p screens and on 4K for even frame sizes (split_stripe cuts only even frames); otherwise
    coordinates are whole units and the drawn frame is off by at most one pixel.
    """
    skin = skin or skin_size(screen)
    width = frame[0] * skin[0] / screen[0]
    height = frame[1] * skin[1] / screen[1]
    # Only a frame that does not fit the layout (large frames on a small screen) is scaled, keeping its shape
    scale = min(1.0, scaled(FRAME_MAX[0], skin) / width, scaled(FRAME_MAX[1], skin) / height)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _pixel_aligned(position: int, screen: int, skin: int) -> int:
    """A nearby coordinate that falls on a whole screen pixel, so the frame is not shifted by a fraction of a pixel."""
    for distance in range(5):
        for candidate in (position - distance, position + distance):
            if candidate >= 0 and candidate * screen % skin == 0:
                return candidate
    return position


def layout(frame_box: Tuple[int, int], rows: int, screen: Tuple[int, int],
           skin: Optional[Tuple[int, int]] = None) -> Dict[str, Tuple[int, int, int, int]]:
    """(x, y, width, height) in skin coordinates of the frame, the counter under it, the details
    panel to its right and the name at the bottom; "row" is (0, 0, label column width, row height)."""
    skin = skin or skin_size(screen)
    frame_w, frame_h = frame_box
    gap, row_h, counter_h = scaled(PANEL_GAP, skin), scaled(ROW_HEIGHT, skin), scaled(COUNTER_HEIGHT, skin)
    panel_w = scaled(PANEL_LABEL_WIDTH + PANEL_VALUE_WIDTH, skin)
    group_w = frame_w + gap + panel_w
    group_h = max(frame_h + counter_h, rows * row_h)
    name_top = scaled(NAME_TOP, skin)
    x = _pixel_aligned(max(0, (skin[0] - group_w) // 2), screen[0], skin[0])
    y = _pixel_aligned(max(scaled(20, skin), (name_top - group_h) // 2), screen[1], skin[1])
    name_w = min(skin[0] - scaled(80, skin), max(group_w, scaled(800, skin)))
    counter_w = max(frame_w, scaled(120, skin))  # "10/10" also under the small 1:1 frame of a 4K screen
    return {
        "frame": (x, y, frame_w, frame_h),
        "counter": (x + (frame_w - counter_w) // 2, y + frame_h + scaled(6, skin), counter_w,
                    scaled(COUNTER_HEIGHT - 10, skin)),
        "panel": (x + frame_w + gap, y, panel_w, max(1, rows) * row_h),
        "row": (0, 0, scaled(PANEL_LABEL_WIDTH, skin), row_h),
        "name": ((skin[0] - name_w) // 2, name_top, name_w, scaled(NAME_HEIGHT, skin)),
    }


def show(frames: List[str], title: str, background: str, details: Sequence[Tuple[str, str]] = ()) -> None:
    """Shows the frames in a modal window, one per FRAME_SECONDS, until the user closes it or Kodi exits.

    The frame is drawn at its native pixel size (see native_box), the details rows (details_rows)
    to its right, the frame counter under it and the full file name at the bottom.
    """
    import xbmc
    import xbmcgui

    screen = gui_size()  # the GUI buffer, not the display mode (see gui_size)
    skin = skin_size(screen)
    boxes = layout(native_box(frame_size(frames[0]), screen, skin), len(details), screen, skin)

    class PreviewWindow(xbmcgui.WindowDialog):
        def __init__(self):
            super().__init__()
            self.stopped = threading.Event()
            self.addControl(xbmcgui.ControlImage(0, 0, skin[0], skin[1], background, colorDiffuse="E6000000"))
            # Stretch to the exact box: its shape is the frame's own, "keep" would fit the rounded box
            # by the smaller side and shift the image by a fraction of a pixel
            self.image = xbmcgui.ControlImage(*boxes["frame"], frames[0], aspectRatio=0)
            self.addControl(self.image)
            self.counter = xbmcgui.ControlLabel(*boxes["counter"], "", alignment=0x00000002)  # centered
            self.addControl(self.counter)
            x, y, width, _ = boxes["panel"]
            _, _, label_w, row_h = boxes["row"]
            for row, (label, value) in enumerate(details):
                top = y + row * row_h
                self.addControl(xbmcgui.ControlLabel(x, top, label_w, row_h, label, textColor=LABEL_COLOR))
                self.addControl(xbmcgui.ControlLabel(x + label_w, top, width - label_w, row_h, value))
            # The full name, wrapped to more lines when it is long
            self.name = xbmcgui.ControlTextBox(*boxes["name"])
            self.addControl(self.name)
            self.name.setText(title)
            # Invisible full-window button: without a focused control Kodi drops mouse actions
            # before onAction, so a click or a tap (touch screen) would not close the window
            self.button = xbmcgui.ControlButton(0, 0, skin[0], skin[1], "", focusTexture="", noFocusTexture="")
            self.addControl(self.button)
            self.setFocus(self.button)

        def onAction(self, action):
            if action.getId() in CLOSE_ACTIONS:
                self.stopped.set()
                self.close()

        def onClick(self, control_id):
            self.stopped.set()
            self.close()

        def cycle(self):
            monitor = xbmc.Monitor()
            index = 0
            while not self.stopped.is_set():
                self.image.setImage(frames[index], False)
                self.counter.setLabel(f"{index + 1}/{len(frames)}")
                index = (index + 1) % len(frames)
                if monitor.waitForAbort(FRAME_SECONDS):
                    self.stopped.set()
                    self.close()

    window = PreviewWindow()
    thread = threading.Thread(target=window.cycle, daemon=True)
    thread.start()
    try:
        window.doModal()
    finally:
        # Also when doModal raises: Kodi waits for the script's threads before it ends the invoker
        window.stopped.set()
        thread.join(FRAME_SECONDS * 2)
        del window
