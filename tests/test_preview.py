"""Video preview from the context menu: cutting the stripe, cache, file_info details, menu item, routing,
the window and its 1:1 layout (stubbed Kodi modules). Names and idents are synthetic.

Run from the repository root: python tests/test_preview.py
"""
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import urllib.parse

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []
TMP = tempfile.mkdtemp(prefix="kss-preview-")

# --- stubbed Kodi modules and libraries ---
requests_stub = types.ModuleType("requests")
sys.modules["requests"] = requests_stub
sys.modules["xmltodict"] = types.ModuleType("xmltodict")


class Monitor:
    abort = False
    def waitForAbort(self, timeout=0):
        time.sleep(timeout)
        return Monitor.abort

builtins = []
info_labels = {"System.ScreenWidth": "1920", "System.ScreenHeight": "1080"}
sys.modules["xbmc"] = types.SimpleNamespace(
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, Monitor=Monitor,
    log=lambda msg, level=0: log.append(("log", msg)),
    executebuiltin=builtins.append,
    getInfoLabel=lambda name: info_labels.get(name, ""),
)
sys.modules["xbmcvfs"] = types.SimpleNamespace(translatePath=lambda path: os.path.join(TMP, path.replace("special://temp/", "")))

STRINGS = {30059: "Náhled videa", 30060: "Náhled není k dispozici", 30061: "Video", 30062: "Datový tok", 30063: "Délka",
           30064: "Zvuk", 30065: "Velikost", 30066: "Kontejner", 30067: "Podrobnosti nejsou k dispozici", 30068: "Titulky", 30070: "Webshare soubor zatím neanalyzoval",
           30069: "Kontextová nabídka: Náhled videa"}

class Addon:
    settings = {"username": "u", "password": "p"}
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return "/addon" if k == "path" else "kss"
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)

class ListItem:
    def __init__(self, label="", label2="", path=""): self.label, self.label2, self.path, self.props, self.menu = label, label2, path, {}, []
    def setInfo(self, kind, info): self.info = info
    def setArt(self, art): self.art = art
    def setProperty(self, k, v): self.props[k] = v
    def addContextMenuItems(self, entries): self.menu.extend(entries)

class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))

# Window stubs: doModal sends the scripted actions and returns once the window is closed
class Action:
    def __init__(self, action_id): self.action_id = action_id
    def getId(self): return self.action_id

# Like Kodi (Window::OnAction): mouse actions (100-109) reach onAction only while a control has focus;
# "click" stands for a click/tap on the focused button (onClick)
class WindowDialog:
    script, states = [], []
    def __init__(self): self.closed, self.focused, self.added = threading.Event(), None, False
    def addControl(self, control): self.added = True
    def setFocus(self, control): self.focused = control
    def close(self): self.closed.set()
    def doModal(self):
        for action_id in WindowDialog.script:
            time.sleep(0.05)
            WindowDialog.states.append((action_id, self.closed.is_set()))
            if action_id == "raise":
                raise RuntimeError("doModal failed")
            if action_id == "click":
                assert self.focused is not None, "click with no focused control"
                self.onClick(1)
            elif not 100 <= action_id <= 109 or self.focused is not None:
                self.onAction(Action(action_id))
        deadline = time.time() + 2
        while not self.closed.is_set() and not Monitor.abort and time.time() < deadline:
            time.sleep(0.01)
        assert self.closed.is_set() or Monitor.abort, "window not closed"

shown, labels, controls = [], [], []
class ControlImage:
    def __init__(self, x, y, w, h, filename, aspectRatio=0, colorDiffuse=None):
        controls.append(("image", (x, y, w, h), filename, aspectRatio))
    def setImage(self, filename, useCache=True): shown.append(filename)
class ControlLabel:
    def __init__(self, x, y, w, h, label, font=None, textColor=None, disabledColor=None, alignment=0):
        controls.append(("label", (x, y, w, h), label, textColor))
    def setLabel(self, label): labels.append(label)
class ControlTextBox:
    def __init__(self, x, y, w, h, font=None, textColor=None): self.box = (x, y, w, h)
    def setText(self, text): controls.append(("text", self.box, text, None))
class ControlButton:
    def __init__(self, x, y, w, h, label, focusTexture=None, noFocusTexture=None):
        assert (x, y, w, h) == (0, 0, 1280, 720) and focusTexture == noFocusTexture == "", "visible or partial button"
        controls.append(("button", (x, y, w, h), label, None))

home_props = {}
class Window:
    def __init__(self, window_id): assert window_id == 10000, window_id
    def getProperty(self, k): return home_props.get(k, "")
    def setProperty(self, k, v): home_props[k] = v
    def clearProperty(self, k): home_props.pop(k, None)

# xbmcgui.getScreenWidth/Height: the GUI render buffer, smaller than the display mode when the GUI size is limited
gui = {"size": (1920, 1080)}
def gui_dimension(index):
    if gui["size"] is None:
        raise RuntimeError("getScreenWidth failed")
    return gui["size"][index]

sys.modules["xbmcgui"] = types.SimpleNamespace(
    getScreenWidth=lambda: gui_dimension(0), getScreenHeight=lambda: gui_dimension(1),
    Dialog=Dialog, ListItem=ListItem, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info", Window=Window,
    WindowDialog=WindowDialog, ControlImage=ControlImage, ControlLabel=ControlLabel, ControlButton=ControlButton,
    ControlTextBox=ControlTextBox,
)
items = []
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    SORT_METHOD_NONE="none", SORT_METHOD_UNSORTED="unsorted", SORT_METHOD_LABEL="label", SORT_METHOD_SIZE="size",
    addDirectoryItem=lambda h, url, item, isFolder=False: items.append((url, item, isFolder)),
    addSortMethod=lambda h, m, labelMask="", label2Mask="": None,
    setContent=lambda h, c: None,
    endOfDirectory=lambda h, succeeded=True, updateListing=False, cacheToDisc=True: log.append(("end", succeeded)),
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "-1", ""]
import kodisimplestream as k
from resources.lib import preview
preview._http = lambda: requests_stub  # the shared Webshare session in Kodi
# Pillow is imported only when a preview is cut: without it (some Linux builds) the plugin must still load
assert not any(name == "PIL" or name.startswith("PIL.") for name in sys.modules), "PIL imported with the plugin"

try:
    from PIL import Image
except ImportError:
    Image = None

def stripe_jpeg(count, width=320, height=180, fmt="JPEG"):
    """Test stripe: frames side by side, each in its own colour."""
    strip = Image.new("RGB", (count * width, height))
    for index in range(count):
        strip.paste((index * 25 % 256, 200, 255 - index * 25 % 256), (index * width, 0, (index + 1) * width, height))
    out = io.BytesIO(); strip.save(out, fmt, **({"quality": 95} if fmt == "JPEG" else {}))
    return out.getvalue()

class FakeResponse:
    def __init__(self, data, location=None):
        self.data, self.is_redirect, self.headers = data, location is not None, {"Location": location} if location else {}
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def raise_for_status(self): pass
    def iter_content(self, size): return (self.data[i:i + size] for i in range(0, len(self.data), size))

def no_file_info(*a, **kw): raise ConnectionError("file_info offline in this test")
requests_stub.post = no_file_info

downloads = []
def serve(data, redirects=None):
    """Fake requests.get: the URLs in redirects answer with a redirect to their value, the rest with data."""
    def get(url, timeout=None, stream=False, allow_redirects=True):
        assert allow_redirects is False, "redirects must be checked by hand"
        downloads.append(url)
        return FakeResponse(data, (redirects or {}).get(url))
    requests_stub.get = get

posts = []
class FakePost(FakeResponse):
    def __init__(self, data, status=200, location=None):
        super().__init__(data, location); self.status_code = status
def serve_info(body, status=200, location=None, delay=0.0):
    """Fake requests.post for file_info: checks that only the ident is sent (no token, no cookies)."""
    def post(url, data=None, timeout=None, stream=False, allow_redirects=True, **kwargs):
        assert not kwargs and allow_redirects is False and stream and timeout, (kwargs, allow_redirects, stream, timeout)
        posts.append((url, dict(data)))
        time.sleep(delay)
        return FakePost(body, status, location)
    requests_stub.post = post

def info_xml(fields, video=None, audio=None, status="OK"):
    """Synthetic file_info response; video/audio: lists of stream dicts (None leaves the element out)."""
    def streams(tag, items):
        if items is None:
            return ""
        return f"<{tag}>" + "".join("<stream>" + "".join(f"<{k}>{v}</{k}>" if v != "" else f"<{k}/>" for k, v in item.items())
                                    + "</stream>" for item in items) + f"</{tag}>"
    body = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?><response><status>{status}</status>{body}'
            f"{streams('video', video)}{streams('audio', audio)}<app_version>30</app_version></response>").encode("utf-8")

# A: fully analysed MKV, one video and one audio stream (xmltodict would give dicts, not lists)
SHAPE_A = info_xml({"name": "Synthetic.Film.2001.1080p.mkv", "size": "3113851289", "type": "mkv", "length": "11318",
                    "bitrate": "2200956", "format": "H264", "width": "1920", "height": "1072", "fps": "23.976023976024"},
                   [{"format": "H264", "width": "1920", "height": "1072", "bitrate": "1800000", "fps": "23.976023976024"}],
                   [{"format": "AC3", "channels": "2", "bitrate": "192000", "language": "CZE"}])
ROWS_A = [("Video", "1920×1072 · H264 · 23.976 fps"), ("Datový tok", "2.2 Mbit/s"), ("Délka", "3:08:38"),
          ("Zvuk", "CZ · AC3 · 2.0"), ("Velikost", "2.9 GB"), ("Kontejner", "MKV")]

groups = 0

# 1. ident and URL checks (path traversal from URL parameters, only http(s))
assert preview.is_valid_ident("5Fh3t7Oo2a") and preview.is_valid_ident("a_b-C9")
for bad in ("", "..", "../x", "a/b", "a\\b", "C:x", "a b", "x" * 65, None, 5):
    assert not preview.is_valid_ident(bad), bad
    try:
        preview.cache_folder(bad); raise AssertionError(f"cache_folder accepted {bad!r}")
    except ValueError:
        pass
assert os.path.normpath(preview.cache_folder("ID1")) == os.path.join(TMP, "kodisimplestream", "preview", "ID1")
for good in ("https://img.webshare.cz/static/p/000123/AbCdEf1234-M.jpg", "http://img.webshare.cz/s.jpg",
             "https://IMG.Webshare.CZ/s.jpg", "https://webshare.cz/s.jpg", "https://img.webshare.cz:443/s.jpg"):
    assert preview.is_stripe_url(good), good
for bad in ("", "file:///etc/passwd", "special://temp/x.jpg", "ftp://img.webshare.cz/s.jpg", "//img.webshare.cz/s.jpg",
            "https://", None, "https://img/s.jpg", "http://192.168.1.1/s.jpg", "http://localhost/s.jpg",
            "https://webshare.cz.evil.com/s.jpg", "https://evilwebshare.cz/s.jpg", "https://evil.com/img.webshare.cz/s.jpg",
            "https://img.webshare.cz@evil.com/s.jpg", "http://[::1/s.jpg",
            # urlparse and urllib3 disagree on these: urllib3 would connect to the host before the backslash
            "http://192.168.1.1\\@img.webshare.cz/s.jpg", "http://192.168.1.1\\@webshare.cz/s.jpg",
            "https://img.webshare.cz/s.jpg\\x", " https://img.webshare.cz/s.jpg", "https://img.webshare.cz/s .jpg",
            "https://img.webshare.cz/\x00s.jpg", "https://img.webshare.cz/\ts.jpg"):
    assert not preview.is_stripe_url(bad), bad
try:
    preview.load_frames("file:///etc/passwd", 10, os.path.join(TMP, "x")); raise AssertionError("file URL loaded")
except ValueError:
    pass
groups += 1

# 2. cutting the stripe: count given, count 0 inferred from the 16:9 frames, count not fitting the width
if Image:
    folder = os.path.join(TMP, "cut")
    paths = preview.split_stripe(stripe_jpeg(10), 10, folder)
    assert paths == [os.path.join(folder, f"{i}.jpg") for i in range(10)], paths
    def read(path):
        with Image.open(path) as image:
            return image.copy()
    frames = [read(p) for p in paths]
    assert all(f.size == (320, 180) for f in frames), [f.size for f in frames]
    assert abs(frames[3].getpixel((160, 90))[0] - 75) < 12, frames[3].getpixel((160, 90))  # the 4th frame, not the 1st
    for count, expected in ((0, 10), (-3, 10), (25, 10), (3, 10), (999, 10)):
        shutil.rmtree(folder)
        assert len(preview.split_stripe(stripe_jpeg(10), count, folder)) == expected, count
    shutil.rmtree(folder)
    assert len(preview.split_stripe(stripe_jpeg(5), 10, folder)) == 5, "5 frames in the image, stripe_count 10"
    assert preview.cached_frames(folder) == [os.path.join(folder, f"{i}.jpg") for i in range(5)]
    # a count off by a few frames (2560 / 10 = 256 px, 1.42:1) would mix neighbouring frames
    shutil.rmtree(folder)
    paths = preview.split_stripe(stripe_jpeg(8), 10, folder)
    assert len(paths) == 8 and read(paths[3]).size == (320, 180), len(paths)
    pixels = [read(paths[3]).getpixel((x, 90))[0] for x in (2, 318)]
    assert all(abs(p - 75) < 12 for p in pixels), pixels  # both edges in the 4th frame
    # the larger Webshare stripe: 10 frames of 649x365, cut to even 648x364 (pixel-exact 1:1 on a 4K GUI)
    shutil.rmtree(folder)
    paths = preview.split_stripe(stripe_jpeg(10, 649, 365), 10, folder)
    assert len(paths) == 10 and all(read(p).size == (648, 364) for p in paths), [read(p).size for p in paths]
    pixels = [read(paths[3]).getpixel((x, 182))[0] for x in (2, 645)]
    assert all(abs(p - 75) < 12 for p in pixels), pixels  # still starts at 3 * 649, both edges in the 4th frame
    assert len(preview.split_stripe(stripe_jpeg(10, 649, 365), 0, folder)) == 10
    # a stripe_count that leaves a remainder of the width is not used
    assert not preview._fits(3200, 180, 9) and not preview._fits(3205, 180, 10) and preview._fits(6490, 365, 10)
    # only JPEG/PNG/WebP are decoded (Pillow's EPS plugin would run Ghostscript); PNG still works
    try:
        preview.split_stripe(stripe_jpeg(2, fmt="GIF"), 2, os.path.join(TMP, "gif")); raise AssertionError("GIF cut")
    except ValueError as exc:
        assert "format" in str(exc), exc
    assert not os.path.exists(os.path.join(TMP, "gif")), "folder created for a refused format"
    shutil.rmtree(folder)
    assert len(preview.split_stripe(stripe_jpeg(3, fmt="PNG"), 3, folder)) == 3
    # a re-cut with fewer frames leaves no frames of the old set behind
    preview.split_stripe(stripe_jpeg(10), 10, folder)
    preview.split_stripe(stripe_jpeg(4), 4, folder)
    assert sorted(os.listdir(folder)) == ["0.jpg", "1.jpg", "2.jpg", "3.jpg", "count"], os.listdir(folder)
    try:
        preview.split_stripe(b"not a jpeg", 10, os.path.join(TMP, "broken")); raise AssertionError("broken image cut")
    except Exception as exc:
        assert not isinstance(exc, AssertionError), exc
    groups += 1
else:
    print("Pillow missing in this Python: cutting checks skipped")

# 3. cache: a miss downloads and cuts, a hit downloads nothing; half-written sets are not used
folder = preview.cache_folder("CACHE1")
if Image:
    serve(stripe_jpeg(10)); downloads.clear()
    first = preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder)
    assert downloads == ["https://img.webshare.cz/s.jpg"] and len(first) == 10, downloads
    assert preview.load_frames("https://img.webshare.cz/s.jpg", 0, folder) == first and downloads == ["https://img.webshare.cz/s.jpg"], downloads
    os.remove(first[4])
    assert preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder) == first and len(downloads) == 2, "missing frame = miss"
    # redirects: followed while they stay on webshare.cz, a foreign target is never requested
    shutil.rmtree(folder); downloads.clear()
    serve(stripe_jpeg(10), {"https://img.webshare.cz/s.jpg": "//img2.webshare.cz/s.jpg"})
    assert len(preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder)) == 10
    assert downloads == ["https://img.webshare.cz/s.jpg", "https://img2.webshare.cz/s.jpg"], downloads
    for target in ("http://192.168.1.1/s.jpg", "file:///etc/passwd", "https://evil.com/s.jpg"):
        shutil.rmtree(folder, ignore_errors=True); downloads.clear()
        serve(stripe_jpeg(10), {"https://img.webshare.cz/s.jpg": target})
        try:
            preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder); raise AssertionError(f"redirect to {target}")
        except ValueError:
            pass
        assert downloads == ["https://img.webshare.cz/s.jpg"] and not preview.cached_frames(folder), downloads
    loop = {f"https://img.webshare.cz/{i}.jpg": f"/{i + 1}.jpg" for i in range(10)}
    serve(stripe_jpeg(10), loop); downloads.clear()
    try:
        preview.load_frames("https://img.webshare.cz/0.jpg", 10, folder); raise AssertionError("redirect loop")
    except ValueError:
        pass
    assert len(downloads) == preview.MAX_REDIRECTS + 1, downloads
    serve(stripe_jpeg(10)); preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder)
    serve(b"x" * (preview.MAX_STRIPE_BYTES + 1))
    try:
        preview.load_frames("https://img.webshare.cz/big.jpg", 10, os.path.join(TMP, "big")); raise AssertionError("oversized download")
    except ValueError:
        pass
# hit without Pillow and without the network: frames and the count file already there
folder = preview.cache_folder("CACHE2"); os.makedirs(folder)
for i in range(3):
    open(os.path.join(folder, f"{i}.jpg"), "wb").close()
requests_stub.get = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("downloaded despite the cache"))
open(os.path.join(folder, "count"), "w").write("3")
assert preview.load_frames("https://img.webshare.cz/s.jpg", 10, folder) == [os.path.join(folder, f"{i}.jpg") for i in range(3)]
for bad in ("", "abc", "0", "999", "4"):
    open(os.path.join(folder, "count"), "w").write(bad)
    assert preview.cached_frames(folder) == [], bad
# pruning: a miss keeps the newest MAX_CACHED ident folders (by mtime) and never touches other entries
root = os.path.join(TMP, "prune")
for index in range(6):
    os.makedirs(os.path.join(root, f"P{index}"))
    os.utime(os.path.join(root, f"P{index}"), (1000 + index, 1000 + index))
os.makedirs(os.path.join(root, "not an ident")); open(os.path.join(root, "file.txt"), "w").close()
os.utime(os.path.join(root, "not an ident"), (1, 1))
preview.prune_cache(root, "P0", keep=3)
assert sorted(os.listdir(root)) == ["P0", "P4", "P5", "file.txt", "not an ident"], os.listdir(root)
preview.prune_cache(os.path.join(TMP, "missing"), "X")  # no cache folder yet: nothing to do
if Image:
    # load_frames prunes before a download; a cache hit marks its folder as recently used
    root = os.path.dirname(preview.cache_folder("X"))
    for name in os.listdir(root):
        os.utime(os.path.join(root, name), (1000, 1000))
    preview.load_frames("https://img.webshare.cz/s.jpg", 10, preview.cache_folder("CACHE1"))
    orig_max, preview.MAX_CACHED = preview.MAX_CACHED, 2
    serve(stripe_jpeg(10))
    preview.load_frames("https://img.webshare.cz/s.jpg", 10, preview.cache_folder("NEW1"))
    assert sorted(os.listdir(root)) == ["CACHE1", "NEW1"], os.listdir(root)
    preview.MAX_CACHED = orig_max
groups += 1

# 4. context menu only on rows with a valid stripe URL and ident (Webshare list and TMDb Helper source list)
class FakeAPI:
    def __init__(self, files): self.files = files
    def search(self, term, limit=30, offset=0, sort="rating", category="video"):
        return {"response": {"total": str(len(self.files)), "file": self.files}} if offset == 0 else {"response": {"total": "0"}}
    def search_all(self, queries, **kwargs):
        return [self.search(query, **kwargs) for query in queries]
def row(ident, stripe=None, count=None):
    info = {"ident": ident, "name": f"Film.2020.{ident}.1080p.mkv", "size": "100", "img": ""}
    if stripe is not None:
        info["stripe"] = stripe
    if count is not None:
        info["stripe_count"] = count
    return info
files = [row("S", "https://img.webshare.cz/S.jpg", "10"), row("N"), row("E", ""), row("F", "file:///etc/x.jpg"), row("..", "https://img.webshare.cz/x.jpg"),
         row("Z", "https://img.webshare.cz/Z.jpg")]
def params(url): return dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
def menus():
    return {params(u)["ident"]: i.menu for u, i, _ in items if params(u).get("action") == "play_ident"}
k.get_api = lambda: FakeAPI(files)
items.clear(); k.list_search_results(["a"])
found = menus()
assert {ident for ident, menu in found.items() if menu} == {"S", "Z"}, found
(label, command), = found["S"]
assert label == "Náhled videa" and command.startswith("RunPlugin(plugin://") and command.endswith(")"), command
inner = command[len("RunPlugin("):-1]
assert "," not in inner, "a comma in the URL would break the builtin"
assert params(inner) == {"action": "preview", "ident": "S", "stripe": "https://img.webshare.cz/S.jpg", "count": "10",
                         "title": "Film.2020.S.1080p.mkv", "size": "100"}, params(inner)
assert params(found["Z"][0][1][len("RunPlugin("):-1]).get("count", "") == ""
# Information dialog: plot from what the list knows, the preview hint only on rows with the menu
plots = {params(u)["ident"]: i.info["plot"] for u, i, _ in items if params(u).get("action") == "play_ident"}
assert plots["S"].split("[CR]") == ["Film.2020.S.1080p.mkv", "FHD 1080p · 0.0 MB", "Kontextová nabídka: Náhled videa"], plots["S"]
assert "Náhled videa" not in plots["N"] and plots["N"].startswith("Film.2020.N.1080p.mkv[CR]"), plots["N"]
# the sort row also has a plot (Icon wall shows "No information available" without one)
assert [i.info.get("plot") for u, i, _ in items if params(u).get("action") == "choose_sort"] == ["#30071"], items
results = k.search_and_score_tmdbh({"mediatype": "movie", "title": "Film", "year": "2020"})
assert {r["ident"]: (r["stripe"], r["stripe_count"]) for r in results}["S"] == ("https://img.webshare.cz/S.jpg", "10"), results
items.clear(); k.list_tmdbh_sources({"mediatype": "movie", "title": "Film", "year": "2020"})
assert {ident for ident, menu in menus().items() if menu} == {"S", "Z"}, menus()
assert all(i.info["plot"].startswith("Film.2020.") for u, i, _ in items if "play_ident" in u), "TMDb Helper rows without plot"
plot = k._tmdbh_source_listitem(next(r for r in results if r["ident"] == "S")).info["plot"]
assert plot.startswith("Film.2020.S.1080p.mkv[CR]FHD 1080p") and "Náhled" not in plot, plot  # select dialog: no context menu
groups += 1

# 5. routing of the preview URL: parameters as given, a missing or invalid count is 0
seen = []
orig_show = k.show_preview
k.show_preview = lambda *a: seen.append(a)
k.router(inner.split("?", 1)[1])
k.router("action=preview&ident=X&stripe=https%3A%2F%2Fimg.webshare.cz%2Fx.jpg&title=T&size=2048")
k.router("action=preview&ident=X&stripe=https%3A%2F%2Fimg.webshare.cz%2Fx.jpg&count=abc&title=T")
k.router("action=preview")
assert seen == [("S", "https://img.webshare.cz/S.jpg", 10, "Film.2020.S.1080p.mkv", "100"), ("X", "https://img.webshare.cz/x.jpg", 0, "T", "2048"),
                ("X", "https://img.webshare.cz/x.jpg", 0, "T", ""), ("", "", 0, "", "")], seen
k.show_preview = orig_show
groups += 1

# 6. failures: notification 30060, nothing shown, no exception (missing Pillow, network, edited URL)
windows = []
orig_window = preview.show
preview.show = lambda frames, title, background, details=(): windows.append((frames, title, background))
orig_load = preview.load_frames
def no_pil(*a): raise ImportError("No module named 'PIL'")
def no_net(*a): raise ConnectionError("network down")
for loader, args in ((no_pil, ("ID1", "https://img.webshare.cz/s.jpg", 10, "T")), (no_net, ("ID1", "https://img.webshare.cz/s.jpg", 10, "T")),
                     (orig_load, ("../../x", "https://img.webshare.cz/s.jpg", 10, "T")), (orig_load, ("ID2", "file:///etc/passwd", 10, "T")),
                     (orig_load, ("ID2", "http://192.168.1.1/s.jpg", 10, "T")),
                     (lambda *a: [], ("ID1", "https://img.webshare.cz/s.jpg", 10, "T"))):
    preview.load_frames = loader; log.clear(); builtins.clear()
    k.show_preview(*args)
    assert [e for e in log if e[0] != "log"] == [("notif", "Náhled není k dispozici")] and windows == [], (loader, log)
    assert any(e[0] == "log" and "preview failed" in e[1] for e in log) or loader not in (no_pil, no_net), log
    # busy dialog while loading, closed also when loading fails; the guard is released
    assert builtins == ["ActivateWindow(busydialognocancel)", "Dialog.Close(busydialognocancel)"], builtins
    assert home_props == {}, home_props
# Pillow really missing: load_frames fails before downloading anything, same notification
saved_pil = {name: module for name, module in sys.modules.items() if name == "PIL" or name.startswith("PIL.")}
sys.modules["PIL"] = sys.modules["PIL.Image"] = None  # import of a None entry raises ImportError
try:
    preview.load_frames = orig_load; serve(b"not decoded"); downloads.clear(); log.clear(); builtins.clear()
    k.show_preview("NOPIL", "https://img.webshare.cz/s.jpg", 10, "T")
    assert downloads == [], downloads
    assert [e for e in log if e[0] != "log"] == [("notif", "Náhled není k dispozici")] and windows == [], log
    assert any(e[0] == "log" and "preview failed" in e[1] and "ModuleNotFoundError" in e[1] for e in log), log
    assert builtins == ["ActivateWindow(busydialognocancel)", "Dialog.Close(busydialognocancel)"] and home_props == {}, builtins
    assert not preview.cached_frames(preview.cache_folder("NOPIL")), "frames cached without Pillow"
finally:
    del sys.modules["PIL"], sys.modules["PIL.Image"]
    sys.modules.update(saved_pil)
# the window fails (frame removed from special://temp, WindowException): notification and log, no traceback
def broken_show(*a): raise RuntimeError("window failed")
preview.load_frames, preview.show = (lambda *a: ["/tmp/0.jpg"]), broken_show; log.clear()
k.show_preview("ID1", "https://img.webshare.cz/s.jpg", 10, "T")
assert [e for e in log if e[0] != "log"] == [("notif", "Náhled není k dispozici")], log
assert any(e[0] == "log" and "window failed" in e[1] for e in log) and home_props == {}, (log, home_props)
# a second request while one is running (RunPlugin starts a new script) is ignored; a stale guard is not
loads = []
preview.load_frames = lambda *a: loads.append(a) or ["/tmp/0.jpg"]
preview.show = lambda frames, title, background, details=(): windows.append(dict(home_props))
home_props[k._PREVIEW_PROPERTY] = str(time.time() - 5); log.clear(); builtins.clear()
k.show_preview("ID1", "https://img.webshare.cz/s.jpg", 10, "T")
assert loads == [] and windows == [] and builtins == [] and [e for e in log if e[0] != "log"] == [], (loads, log)
assert home_props[k._PREVIEW_PROPERTY], "guard of the running preview cleared"
for stale in (str(time.time() - k._PREVIEW_GUARD_SECONDS - 1), "garbage"):
    home_props[k._PREVIEW_PROPERTY] = stale; loads.clear(); windows.clear()
    k.show_preview("ID1", "https://img.webshare.cz/s.jpg", 10, "T")
    # the guard is set while the window is open and released afterwards
    assert len(loads) == 1 and list(windows[0]) == [k._PREVIEW_PROPERTY] and home_props == {}, (stale, windows, home_props)
preview.show = lambda frames, title, background, details=(): windows.append((frames, title, background, list(details))); windows.clear()
assert not os.path.exists(os.path.join(TMP, "kodisimplestream", "x")), "path traversal created a folder"
BACKGROUND = os.path.join("/addon", "resources", "media", "white.png")
# success with file_info offline: the window opens anyway, with the size of the list and a note; the failure is logged
preview.load_frames = lambda *a: ["/tmp/0.jpg"]; log.clear()
k.show_preview("ID1", "https://img.webshare.cz/s.jpg", 10, "Film", "3221225472")
assert windows == [(["/tmp/0.jpg"], "Film", BACKGROUND, [("Velikost", "3.0 GB"), ("", "Podrobnosti nejsou k dispozici")])], windows
assert [e for e in log if e[0] != "log"] == [] and any("file_info unavailable" in e[1] and "ConnectionError" in e[1] for e in log), log
# success with file_info: the rows of the response; the stripe and file_info load under one busy dialog
serve_info(SHAPE_A); posts.clear(); windows.clear(); log.clear(); builtins.clear()
k.show_preview("INFO1", "https://img.webshare.cz/s.jpg", 10, "Film.mkv", "100")
assert posts == [(preview.FILE_INFO_URL, {"ident": "INFO1"})], posts
assert windows == [(["/tmp/0.jpg"], "Film.mkv", BACKGROUND, ROWS_A)] and log == [], (windows, log)
assert builtins == ["ActivateWindow(busydialognocancel)", "Dialog.Close(busydialognocancel)"], builtins
# no title in the URL: the name from file_info
windows.clear(); k.show_preview("INFO1", "https://img.webshare.cz/s.jpg", 10, "", "")
assert windows[0][1] == "Synthetic.Film.2001.1080p.mkv" and len(posts) == 1, (windows, posts)  # cached: no second request
requests_stub.post = no_file_info
# opened as a folder (handle >= 0) the listing is ended so Kodi does not wait
k._handle = 1; log.clear(); k.show_preview("ID1", "https://img.webshare.cz/s.jpg", 10, "Film")
assert [e for e in log if e[0] != "log"] == [("end", False)], log
k._handle = -1
preview.load_frames, preview.show = orig_load, orig_window
groups += 1

# 7. window: mouse moves do not close it, Back does; the frame thread stops on close and on Kodi abort
preview.FRAME_SECONDS = 0.01
frames = ["a.jpg", "b.jpg", "c.jpg"]
def frame_threads(): return [t for t in threading.enumerate() if getattr(t, "_target", None) and t._target.__name__ == "cycle"]
WindowDialog.script, WindowDialog.states = [107, 106, 107, 92], []
shown.clear(); labels.clear()
preview.show(frames, "Film", "white.png")
assert [state for _, state in WindowDialog.states] == [False, False, False, False], WindowDialog.states
deadline = time.time() + 2
while frame_threads() and time.time() < deadline:
    time.sleep(0.01)
assert not frame_threads(), "frame thread still running after close"
count = len(shown); time.sleep(0.1); assert len(shown) == count, "frames change after close"
assert shown[:4] == ["a.jpg", "b.jpg", "c.jpg", "a.jpg"] and labels[:2] == ["1/3", "2/3"], (shown[:4], labels[:2])
for action_id in (7, 10, 13, 100, 101, "click"):  # mouse click/tap work thanks to the focused button
    WindowDialog.script = [action_id]; preview.show(frames, "Film", "white.png")
Monitor.abort = True; WindowDialog.script = []; shown.clear()
preview.show(frames, "Film", "white.png")
assert shown == ["a.jpg"], shown
Monitor.abort = False
# doModal raising: the frame thread is stopped too and the error reaches show_preview
WindowDialog.script = ["raise"]
try:
    preview.show(frames, "Film", "white.png"); raise AssertionError("doModal error swallowed")
except RuntimeError:
    pass
deadline = time.time() + 2
while frame_threads() and time.time() < deadline:
    time.sleep(0.01)
assert not frame_threads(), "frame thread still running after a doModal error"
groups += 1

# 8. file_info: parsing the real variations (synthetic values), panel rows, anonymous request, cache, background thread
LABELS = {"video": "Video", "bitrate": "Bitrate", "length": "Length", "audio": "Audio", "size": "Size",
          "container": "Container", "unavailable": "Details unavailable", "unanalysed": "Not analysed"}
info_a = preview.parse_file_info(SHAPE_A)
assert info_a["width"] == "1920" and info_a["audio"] == [{"format": "AC3", "channels": "2", "language": "CZE"}], info_a
assert info_a["video"] == [{"format": "H264", "width": "1920", "height": "1072", "fps": "23.976023976024"}], info_a
# B: cover art listed first among video streams, top-level video fields and bitrate missing,
#    several audio tracks with CES/SLO/ENG, UND, an empty and a missing language, 1/6/7/8 channels, odd codecs
SHAPE_B = info_xml({"name": "Synthetic.Show.S01E01.mp4", "size": "734003200", "type": "mp4", "length": "2700"},
                   [{"format": "PNG", "width": "350", "height": "197", "bitrate": "", "fps": "0"},
                    {"format": "HEVC", "width": "3840", "height": "1608", "bitrate": "", "fps": "25"}],
                   [{"format": "EAC3", "channels": "6", "bitrate": "640000", "language": "CES"},
                    {"format": "DTS", "channels": "8", "bitrate": "", "language": "ENG"},
                    {"format": "AAC", "channels": "2", "bitrate": "", "language": "UND"},
                    {"format": "PCM_S16LE", "channels": "1", "bitrate": "", "language": ""},
                    {"format": "TRUEHD", "channels": "7", "bitrate": ""},
                    {"format": "MP3", "channels": "2", "bitrate": "", "language": "SLO"},
                    {"format": "OPUS", "channels": "2", "bitrate": "", "language": "HIN"},
                    {"format": "AAC", "channels": "2", "bitrate": "", "language": "KOR"}])
rows_b = preview.details_rows(preview.parse_file_info(SHAPE_B), "1", LABELS)
assert rows_b == [("Video", "3840×1608 · HEVC · 25 fps"), ("Bitrate", "2.2 Mbit/s"), ("Length", "45:00"),
                  ("Audio", "CZ · E-AC3 · 5.1"), ("", "EN · DTS · 7.1"), ("", "? · AAC · 2.0"), ("", "? · PCM · 1.0"),
                  ("", "? · TrueHD · 6.1"), ("", "SK · MP3 · 2.0"), ("", "+2"), ("Size", "700 MB"), ("Container", "MP4")], rows_b
# C: not analysed by Webshare (no video/audio/length), an odd type; D: an error status; None: request failed
SHAPE_C = info_xml({"name": "Synthetic.Clip.avi", "size": "52428800", "type": "1 CZE  mkv"})
assert preview.details_rows(preview.parse_file_info(SHAPE_C), "1", LABELS) == [("Size", "50.0 MB"), ("", "Not analysed")]
assert preview.parse_file_info(info_xml({"message": "File not found."}, status="FATAL")) is None
assert preview.details_rows(None, "1073741824", LABELS) == [("Size", "1.0 GB"), ("", "Details unavailable")]
assert preview.details_rows(None, "", LABELS) == [("", "Details unavailable")]
assert preview.details_rows({"type": "avi", "length": "0", "bitrate": "abc", "width": "640"}, "", LABELS) == \
    [("Container", "AVI"), ("", "Not analysed")]
# any of video, length or audio counts as analysed: no note
assert preview.details_rows({"length": "60"}, "", LABELS) == [("Length", "1:00")]
assert preview.details_rows({"audio": [{"format": "AAC", "channels": "2"}]}, "", LABELS) == [("Audio", "? · AAC · 2.0")]
for broken in (b"", b"<html>maintenance</html>", b"<response><status>OK</status>"):
    try:
        assert preview.parse_file_info(broken) is None, broken
    except AssertionError:
        raise
    except Exception:
        pass
# units
assert [preview.format_duration(v) for v in ("59", "3600", "11318", "", None, "x", "-5")] == ["0:59", "1:00:00", "3:08:38", "", "", "", ""]
assert [preview.format_bitrate(v) for v in ("2200956", "850000", "999", "")] == ["2.2 Mbit/s", "850 kbit/s", "1 kbit/s", ""]
assert [preview.format_fps(v) for v in ("23.976023976024", "25", "29.97002997003", "0", "")] == ["23.976 fps", "25 fps", "29.97 fps", "", ""]
assert [preview.format_channels(v) for v in ("1", "2", "6", "8", "4", "")] == ["1.0", "2.0", "5.1", "7.1", "4 ch", ""]
assert [preview.language_code(v) for v in ("CZE", "ces", "SLK", "SVK", "eng", "JAP", "UND", "", None, "HIN")] == \
    ["CZ", "CZ", "SK", "SK", "EN", "JA", "?", "?", "?", "HIN"]
# the request: anonymous POST with the ident only, no redirects, status, size cap; nothing cached on failure
folder = preview.cache_folder("FI1")
serve_info(SHAPE_B); posts.clear()
assert preview.load_file_info("FI1", folder)["name"] == "Synthetic.Show.S01E01.mp4" and posts == [(preview.FILE_INFO_URL, {"ident": "FI1"})]
assert preview.load_file_info("FI1", folder)["length"] == "2700" and len(posts) == 1, "second preview must use the cache"
assert preview.cached_frames(folder) == [], "info.json must not look like frames"
for body, status, location in ((SHAPE_A, 500, None), (SHAPE_A, 302, "https://evil.example/"),
                               (b"x" * (preview.MAX_FILE_INFO_BYTES + 1), 200, None), (b"<broken", 200, None)):
    serve_info(body, status, location); posts.clear()
    try:
        preview.load_file_info("FI2", preview.cache_folder("FI2")); raise AssertionError(f"accepted {status} {body[:10]!r}")
    except AssertionError:
        raise
    except Exception:
        pass
    assert len(posts) == 1 and preview.cached_file_info(preview.cache_folder("FI2")) is None, posts
serve_info(info_xml({}, status="FATAL")); posts.clear()
assert preview.load_file_info("FI2", preview.cache_folder("FI2")) is None and preview.cached_file_info(preview.cache_folder("FI2")) is None
# an OK response of a file Webshare has not analysed yet is shown but not cached: asked again next time
folder_c = preview.cache_folder("FI6")
serve_info(SHAPE_C); posts.clear()
assert preview.load_file_info("FI6", folder_c)["size"] == "52428800" and preview.cached_file_info(folder_c) is None
assert preview.load_file_info("FI6", folder_c)["size"] == "52428800" and len(posts) == 2, posts
serve_info(SHAPE_A); posts.clear()  # analysed meanwhile: now cached
assert preview.load_file_info("FI6", folder_c)["width"] == "1920" and preview.load_file_info("FI6", folder_c)["width"] == "1920"
assert len(posts) == 1 and preview.cached_file_info(folder_c)["width"] == "1920", posts
assert not preview.is_analysed(preview.parse_file_info(SHAPE_C)) and not preview.is_analysed({"width": "640", "length": "0"})
assert preview.is_analysed({"length": "60"}) and preview.is_analysed({"audio": [{"format": "AAC"}]})
assert preview.is_analysed(preview.parse_file_info(SHAPE_A)) and preview.is_analysed(preview.parse_file_info(SHAPE_B))
# a corrupt or old cache file is requested again
with open(os.path.join(folder, "info.json"), "w") as handle:
    handle.write('{"version": 0, "info": {}}')
serve_info(SHAPE_A); posts.clear()
assert preview.load_file_info("FI1", folder)["name"] == "Synthetic.Film.2001.1080p.mkv" and len(posts) == 1
try:
    preview.load_file_info("../x", folder); raise AssertionError("invalid ident requested")
except ValueError:
    pass
# background thread: result() waits until FILE_INFO_WAIT after the start at most, errors are kept for the log
orig_wait, preview.FILE_INFO_WAIT = preview.FILE_INFO_WAIT, 0.2
serve_info(SHAPE_A, delay=1.0)
started = time.time()
request = preview.FileInfoRequest("FI3", preview.cache_folder("FI3"))
assert request.result() is None and time.time() - started < 0.8, time.time() - started
requests_stub.post = no_file_info
request = preview.FileInfoRequest("FI4", preview.cache_folder("FI4"))
assert request.result() is None and isinstance(request.error, ConnectionError), request.error
serve_info(SHAPE_C)
assert preview.FileInfoRequest("FI5", preview.cache_folder("FI5")).result()["size"] == "52428800"
preview.FILE_INFO_WAIT = orig_wait
requests_stub.post = no_file_info
groups += 1

# 9. 1:1 frame: window units from the frame pixels and the screen, layout on 720p, 1080p, 4K and odd screens
assert preview.screen_size("1920", "1080") == (1920, 1080) and preview.screen_size("3840", "2160") == (3840, 2160)
for bad in (("", ""), ("abc", "1080"), ("0", "0"), (None, None), ("1920", "")):
    assert preview.screen_size(*bad) == preview.DEFAULT_SCREEN, bad
assert preview.frame_size(os.path.join(TMP, "missing.jpg")) == preview.DEFAULT_FRAME
if Image:
    path = os.path.join(TMP, "frame.jpg"); Image.new("RGB", (648, 364)).save(path)  # a cut 649x365 frame
    assert preview.frame_size(path) == (648, 364)
def drawn(position, size, screen, skin):
    """Screen pixels Kodi draws for a box (it rounds the scaled edges to whole pixels)."""
    scale = screen / skin
    return int((position + size) * scale + 0.5) - int(position * scale + 0.5)
assert preview.skin_size((1280, 720)) == preview.skin_size((1920, 1080)) == preview.skin_size((3840, 2160)) == (1280, 720)
HD = (1280, 720)
for screen, frame, box in (((1280, 720), (320, 180), (320, 180)), ((1920, 1080), (320, 180), (213, 120)),
                           ((3840, 2160), (320, 180), (107, 60)), ((1920, 1080), (648, 364), (432, 243)),
                           ((3840, 2160), (648, 364), (216, 121)), ((2560, 1440), (320, 180), (160, 90)),
                           ((1280, 720), (648, 364), (648, 364)), ((1920, 1200), (320, 180), (213, 108)),
                           ((1366, 768), (320, 180), (300, 169)), ((640, 360), (649, 365), (670, 377))):
    assert preview.native_box(frame, screen) == box, (screen, frame, preview.native_box(frame, screen))
    boxes = preview.layout(box, 12, screen)
    x, y, w, h = boxes["frame"]
    assert (w, h) == box
    if screen[0] >= 1280:  # not scaled down: 1 image pixel = 1 screen pixel within 1 px (whole window units)
        assert abs(drawn(x, w, screen[0], HD[0]) - frame[0]) <= 1 and abs(drawn(y, h, screen[1], HD[1]) - frame[1]) <= 1, (screen, frame)
    if screen == (1280, 720):
        assert (drawn(x, w, 1280, 1280), drawn(y, h, 720, 720)) == frame, boxes["frame"]
    for name, (bx, by, bw, bh) in boxes.items():
        assert bx >= 0 and by >= 0 and bx + bw <= HD[0] and by + bh <= HD[1], (screen, name, boxes[name])
    px, py, pw, ph = boxes["panel"]
    cx, cy, cw, ch = boxes["counter"]
    nx, ny, nw, nh = boxes["name"]
    assert px >= x + w and py == y, "panel right of the frame"
    assert ph == 12 * boxes["row"][3] and boxes["row"][2] < pw, boxes
    assert cy >= y + h and abs((cx + cw / 2) - (x + w / 2)) <= 1, "counter centered under the frame"
    assert ny >= max(cy + ch, py + ph), "name below the frame, counter and panel"
# the GUI buffer (xbmcgui.getScreenWidth/Height) wins over the display mode in the labels, which are only a fallback
info_labels["System.ScreenWidth"], info_labels["System.ScreenHeight"] = "3840", "2160"
gui["size"] = (1920, 1080)  # 4K display with the GUI limited to 1080p (default on Android 4K devices)
assert preview.gui_size() == (1920, 1080)
for broken in (None, (0, 0), ("", "")):
    gui["size"] = broken
    assert preview.gui_size() == (3840, 2160), broken
info_labels["System.ScreenWidth"], info_labels["System.ScreenHeight"] = "", ""
assert preview.gui_size() == preview.DEFAULT_SCREEN
# show(): the frame box from the GUI size and the real frame pixels, details in two columns, the full name in the text box
WindowDialog.script = [92]
real = [os.path.join(TMP, "frame.jpg")] if Image else []  # 648x364, saved above
cases = [((1920, 1080), ("1920", "1080"), frames, (213, 120)), ((3840, 2160), ("3840", "2160"), frames, (107, 60)),
         ((1920, 1080), ("3840", "2160"), frames, (213, 120)),  # GUI limited to 1080p on a 4K display
         (None, ("", ""), frames, (213, 120)), (None, ("3840", "2160"), frames, (107, 60)),
         ((1280, 720), ("1280", "720"), frames, (320, 180))]
if real:  # the box follows the real pixel size of the cut frame, not a fixed one
    cases += [((1920, 1080), ("1920", "1080"), real, (432, 243)), ((3840, 2160), ("3840", "2160"), real, (216, 121)),
              ((1920, 1080), ("3840", "2160"), real, (432, 243))]
for gui_screen, screen, shown_frames, box in cases:
    gui["size"] = gui_screen
    info_labels["System.ScreenWidth"], info_labels["System.ScreenHeight"] = screen
    controls.clear()
    preview.show(shown_frames, "Synthetic.Film.2001.1080p.mkv", "white.png", ROWS_A)
    window = (0, 0, 1280, 720)
    images = [c for c in controls if c[0] == "image"]
    assert images[0][1] == window and images[1][1][2:] == box and images[1][3] == 0, (gui_screen, screen, images)
    assert images[1][2] == shown_frames[0], images
    assert [c[1] for c in controls if c[0] == "button"] == [window], screen
    cells = [c[2] for c in controls if c[0] == "label" and c[2]]
    assert cells == [cell for row in ROWS_A for cell in row if cell], cells
    assert [c for c in controls if c[0] == "label" and c[2] == "Video"][0][3] == preview.LABEL_COLOR
    assert [c[2] for c in controls if c[0] == "text"] == ["Synthetic.Film.2001.1080p.mkv"]
info_labels["System.ScreenWidth"], info_labels["System.ScreenHeight"] = "1920", "1080"
gui["size"] = (1920, 1080)
groups += 1

shutil.rmtree(TMP, ignore_errors=True)
print(f"video preview: {groups} groups of checks passed")
