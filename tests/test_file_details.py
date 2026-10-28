"""File details from Webshare file_info in the lists: checks, cache, bounded fetching, the background
script with its one refresh, the TMDb Helper picker and auto-play (stubbed Kodi modules).
Names and idents are synthetic.

Run from the repository root: python tests/test_file_details.py
"""
import json
import re
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
TMP = tempfile.mkdtemp(prefix="kss-details-")
log = []

# --- stubbed Kodi modules and libraries ---
sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")


class Monitor:
    def waitForAbort(self, timeout=0):
        time.sleep(min(timeout, 0.01))
        return False
    def abortRequested(self): return False


# Kodi 21 signatures (xbmc/interfaces/legacy/InfoTagVideo.h): a wrong keyword raises TypeError here too
class VideoStreamDetail:
    def __init__(self, width=0, height=0, aspect=0.0, duration=0, codec="", stereomode="", language="", hdrtype=""):
        self.args = {"width": width, "height": height, "duration": duration, "codec": codec}
class AudioStreamDetail:
    def __init__(self, channels=-1, codec="", language=""):
        self.args = (channels, codec, language)


info_labels = {}
conditions = {"System.HasActiveModalDialog": False}
sys.modules["xbmc"] = types.SimpleNamespace(
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, Monitor=Monitor,
    VideoStreamDetail=VideoStreamDetail, AudioStreamDetail=AudioStreamDetail,
    log=lambda msg, level=0: log.append(("log", msg)),
    executebuiltin=lambda cmd: log.append(("builtin", cmd)),
    getInfoLabel=lambda name: info_labels.get(name, ""),
    getCondVisibility=lambda name: conditions.get(name, False),
)
sys.modules["xbmcvfs"] = types.SimpleNamespace(translatePath=lambda path: os.path.join(TMP, path.replace("special://", "").replace("/", os.sep)))

STRINGS = {30042: "dabing", 30043: "titulky", 30061: "Video", 30062: "Bitrate", 30063: "Length", 30064: "Audio",
           30065: "Size", 30066: "Container", 30067: "Unavailable", 30068: "Subtitles", 30070: "Not analysed",
           30073: "Length does not match ({} min)", 30074: "CHOOSE"}


class Addon:
    settings = {"username": "u", "password": "p"}
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return {"path": "/addon", "profile": "special://profile/addon_data/kss/"}.get(k, "kss")
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)


class InfoTag:
    def __init__(self): self.duration, self.video, self.audio = None, [], []
    def setDuration(self, seconds): assert isinstance(seconds, int), seconds; self.duration = seconds
    def addVideoStream(self, stream): self.video.append(stream.args)
    def addAudioStream(self, stream): self.audio.append(stream.args)


class ListItem:
    def __init__(self, label="", label2="", path=""):
        self.label, self.label2, self.path, self.props, self.menu, self.tag = label, label2, path, {}, [], None
    def setInfo(self, kind, info): self.info = info
    def setArt(self, art): self.art = art
    def setProperty(self, k, v): self.props[k] = v
    def addContextMenuItems(self, entries): self.menu.extend(entries)
    def addStreamInfo(self, kind, values):  # Kodi 19 only (deprecated since 20)
        assert all(isinstance(v, str) for v in values.values()), values
        self.streams = getattr(self, "streams", []) + [(kind, values)]
    def getVideoInfoTag(self):
        self.tag = self.tag or InfoTag()
        return self.tag


selects = []
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
    def select(self, heading, items, preselect=-1, *a):
        log.append(("select", [getattr(i, "label", i) + (" || " + i.label2 if getattr(i, "label2", "") else "") for i in items], [getattr(i, "info", {}).get("plot", "") for i in items]))
        return selects.pop(0)
    def input(self, heading, default=""): raise AssertionError("no query change expected")


class Window:
    props = {}
    def __init__(self, window_id): assert window_id == 10000, window_id
    def getProperty(self, k): return self.props.get(k, "")
    def setProperty(self, k, v): assert isinstance(v, str); self.props[k] = v
    def clearProperty(self, k): self.props.pop(k, None)
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, Window=Window,
                                               NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")

items = []
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    SORT_METHOD_UNSORTED="unsorted", SORT_METHOD_LABEL="label", SORT_METHOD_SIZE="size",
    addDirectoryItem=lambda h, url, item, isFolder=False: items.append((url, item, isFolder)),
    addSortMethod=lambda h, m, labelMask="", label2Mask="": None,
    setContent=lambda h, c: None,
    endOfDirectory=lambda h, succeeded=True, updateListing=False, cacheToDisc=True: log.append(("end", succeeded, updateListing)),
    setResolvedUrl=lambda h, ok, item: log.append(("resolved", ok, item.path)),
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k
from resources.lib import file_details as fd, preview
from resources.lib.matching import autoplay_concern

preview._http = lambda: None  # the shared Webshare session in Kodi


def info_xml(fields, video=(), audio=()):
    def streams(tag, rows):
        return f"<{tag}>" + "".join("<stream>" + "".join(f"<{a}>{b}</{a}>" for a, b in row.items()) + "</stream>"
                                    for row in rows) + f"</{tag}>"
    body = "".join(f"<{a}>{b}</{a}>" for a, b in fields.items())
    return (f"<response><status>OK</status>{body}{streams('video', video)}{streams('audio', audio)}</response>").encode()


def film(length="7080", width="1920", height="800", audio=(("CZE", "6", "AC3"), ("ENG", "2", "AAC"))):
    return preview.parse_file_info(info_xml(
        {"name": "Synthetic.mkv", "size": "2147483648", "type": "mkv", "length": length, "format": "H264",
         "width": width, "height": height, "fps": "25"},
        [{"format": "H264", "width": width, "height": height, "fps": "25"}],
        [{"format": codec, "channels": ch, "language": lang} for lang, ch, codec in audio]))


groups = 0

# 1. checks of one file: length against the runtime, real resolution, audio, stream flags, unknown values
info = film()
assert fd.length_seconds(info) == 7080 and fd.runtime_minutes("118") == 118 and fd.runtime_minutes("0") is None
for runtime, mediatype, expected in (("118", "movie", False), ("150", "movie", True), ("78", "movie", True),
                                     ("79", "movie", False), ("", "movie", None), (None, "movie", None),
                                     ("abc", "movie", None), ("118", "episode", False), ("45", "episode", True),
                                     ("263", "episode", True), ("260", "episode", False)):
    assert fd.length_mismatch(info, runtime, mediatype) is expected, (runtime, mediatype)
assert fd.length_mismatch({"length": "0"}, "100") is None and fd.length_mismatch(None, "100") is None
assert fd.length_mismatch(film(length="2400"), "100") is True  # 0.4x: a part, an episode or a trailer
for width, height, expected in (("3840", "1600", "4K"), ("1920", "800", "FHD"), ("1440", "1080", "FHD"),
                                ("1280", "536", "HD"), ("960", "720", "HD"), ("720", "400", "SD")):
    assert fd.resolution(film(width=width, height=height)) == (expected, f"{width}×{height}"), (width, height)
assert fd.resolution({"length": "60"}) is None and fd.resolution(None) is None
assert fd.audio_languages(info) == ["CZ", "EN"] and fd.audio_text(info) == "CZ 5.1, EN"
many = film(audio=[("UND", "2", "AAC"), ("SLO", "8", "DTS"), ("GER", "2", "AC3"), ("FRE", "2", "AC3"), ("ITA", "1", "MP3")])
assert fd.audio_languages(many) == ["SK", "DE", "FR", "IT"] and fd.audio_text(many) == "?, SK 7.1, DE, FR, +1", fd.audio_text(many)
assert fd.video_stream(info) == {"width": 1920, "height": 800, "codec": "h264", "duration": 7080}
assert fd.audio_streams(info) == [{"channels": 6, "codec": "ac3", "language": "cze"}, {"channels": 2, "codec": "aac", "language": "eng"}]
assert fd.audio_streams({"audio": [{"format": "AAC", "language": "UND"}, {"language": "c2e"}]}) == \
    [{"channels": -1, "codec": "aac", "language": ""}, {"channels": -1, "codec": "", "language": ""}]
assert fd.video_stream({"length": "60"}) is None and fd.audio_streams(None) == [] and fd.audio_text({}) == ""
small = fd.compact(info)
assert "name" not in small and small["length"] == "7080" and len(small["audio"]) == 2, small
assert len(fd.compact({"audio": [{"language": "CZE"}] * 50})["audio"]) == fd._KEEP_STREAMS and fd.compact("x") is None
groups += 1

# 2. names the auto-play must not take without asking (scores unchanged, see the benchmark)
movie = {"mediatype": "movie", "title": "Synthetic Film", "year": "2010"}
for name, expected in (("Synthetic.Film.2010.1080p.mkv", ""), ("Synthetic.Film.2010.Trailer.mkv", "extra"),
                       ("Synthetic Film (2010) CD1.avi", "part"), ("Synthetic.Film.2010.cd2.avi", "part"),
                       ("Synthetic Film 2010 1of2.avi", "part"), ("Synthetic.Film.1987.mkv", "year"),
                       ("Synthetic.Film.2011.mkv", ""), ("Synthetic.Film.mkv", ""), ("Synthetic Film 2010 DVD5.iso", ""),
                       ("Synthetic.Film.2010.5.1.CZ.mkv", "")):
    assert autoplay_concern({"name": name}, movie) == expected, (name, autoplay_concern({"name": name}, movie))
assert autoplay_concern({"name": "Trailer.Park.2010.mkv"}, {"mediatype": "movie", "title": "Trailer Park", "year": "2010"}) == ""
show = {"mediatype": "episode", "showname": "Synthetic Show", "season": "1", "episode": "2"}
assert autoplay_concern({"name": "Synthetic.Show.S01E02.Part.1.1999.mkv"}, show) == ""
assert autoplay_concern({"name": "Synthetic.Show.S01E02.sample.mkv"}, show) == "extra"
groups += 1

# 3. cache: session property first, addon_data file merged and pruned, TTL, "no details" only for the session
props = {}
class Home:
    def getProperty(self, key): return props.get(key, "")
    def setProperty(self, key, value): props[key] = value
folder, previews = os.path.join(TMP, "data"), os.path.join(TMP, "previews")
cache = fd.DetailsCache(Home(), folder, previews, now=1_000_000)
assert cache.lookup("A1") == (False, None)
cache.put("A1", film()); cache.put("A2", None); cache.put("A3", preview.parse_file_info(info_xml({"size": "1"}))); cache.put("../x", film())
assert cache.known("A2") and cache.get("A2") is None and cache.get("A1")["length"] == "7080"
cache.save()
on_disk = json.load(open(os.path.join(folder, fd.CACHE_FILE), encoding="utf-8"))
assert on_disk["version"] == fd.CACHE_VERSION and list(on_disk["entries"]) == ["A1"], on_disk  # only details go to disk
assert set(json.loads(props[fd.SESSION_PROPERTY])) == {"A1", "A2", "A3"}
props.clear()  # a new Kodi session: the file is still there, the misses are forgotten
fresh = fd.DetailsCache(Home(), folder, previews, now=1_000_000 + 3600)
assert fresh.get("A1")["width"] == "1920" and not fresh.known("A2")
assert not fd.DetailsCache(Home(), folder, previews, now=1_000_000 + fd.CACHE_TTL + 1).known("A1"), "TTL"
props[fd.SESSION_PROPERTY] = json.dumps({"A2": {"t": 1_000_000}})
assert fd.DetailsCache(Home(), "", "", now=1_000_000 + fd.MISS_TTL - 1).known("A2")
assert not fd.DetailsCache(Home(), "", "", now=1_000_000 + fd.MISS_TTL + 1).known("A2")
# another plugin call wrote meanwhile: merged, not overwritten; the oldest go beyond CACHE_MAX
other = fd.DetailsCache(None, folder, "", now=1_000_010); other.put("B1", film()); other.save()
orig_max, fd.CACHE_MAX = fd.CACHE_MAX, 2
late = fd.DetailsCache(None, folder, "", now=1_000_020); late.put("C1", film()); late.save()
assert set(json.load(open(os.path.join(folder, fd.CACHE_FILE), encoding="utf-8"))["entries"]) == {"B1", "C1"}
fd.CACHE_MAX = orig_max
orig_session, fd.SESSION_MAX = fd.SESSION_MAX, 2
capped = fd.DetailsCache(Home(), "", "", now=1_000_030)
for index in range(4):
    capped.now += 1; capped.put(f"S{index}", None)
capped.save(); assert set(json.loads(props[fd.SESSION_PROPERTY])) == {"S2", "S3"}
fd.SESSION_MAX = orig_session
# two plugin calls overlap (the list's background script, a preview): the later save keeps the other's entries
props.clear()
slow = fd.DetailsCache(Home(), "", "", now=1_000_040); quick = fd.DetailsCache(Home(), "", "", now=1_000_040)
quick.put("Q1", None); quick.save()
slow.put("L1", None); slow.save()
assert set(json.loads(props[fd.SESSION_PROPERTY])) == {"Q1", "L1"}, props
# broken file, broken property, the preview's info.json as a fallback (an analysed one only)
for broken in ("{", '{"version": 0, "entries": {}}', '{"version": 1, "entries": []}'):
    open(os.path.join(folder, fd.CACHE_FILE), "w").write(broken)
    props[fd.SESSION_PROPERTY] = "[not json"
    assert fd.DetailsCache(Home(), folder, previews).lookup("B1") == (False, None)
os.makedirs(os.path.join(previews, "P1"))
json.dump({"version": 1, "info": film()}, open(os.path.join(previews, "P1", "info.json"), "w"))
got = fd.DetailsCache(None, "", previews).get("P1")
assert got["length"] == "7080" and "name" not in got
groups += 1

# 4. fetching: at most 4 at once, starts spaced, a broken answer skips one file, 403 or a timeout stops
#    (no retry), nothing starts after the start window, wait() returns what arrived by the deadline
running, peak, starts, failed = [0], [0], [], []
lock = threading.Lock()
def fake_fetch(answers, delay=0.05):
    def fetch(ident):
        with lock:
            running[0] += 1; peak[0] = max(peak[0], running[0]); starts.append((ident, time.perf_counter()))
        try:
            time.sleep(delay)
            answer = answers.get(ident, film())
            if isinstance(answer, BaseException):
                failed.append(time.perf_counter())
                raise answer
            return answer
        finally:
            with lock:
                running[0] -= 1
    return fetch
idents = [f"F{i}" for i in range(10)]
fetcher = fd.Fetcher(idents + ["F0", "../x"], 5, fake_fetch({"F3": None, "F4": fd.ElementTree.ParseError("x")}), interval=0.01)
got = fetcher.wait(5)
assert fetcher.done() and set(got) == set(idents) and got["F3"] is None and got["F4"] is None and got["F0"]["length"], got
# taken in order (threads may enter a moment later), deduplicated, valid idents only, starts spread by the interval
assert peak[0] <= fd.WORKERS and sorted(i for i, _ in starts) == idents, (peak, starts)
assert starts[-1][1] - starts[0][1] >= 9 * 0.01 * 0.9, starts
starts.clear()
fetcher = fd.Fetcher(idents, 5, fake_fetch({"F2": preview.FileInfoStatusError(403)}), interval=0.01)
got = fetcher.wait(5)
def started_after_failure(): return [ident for ident, at in starts if at > failed[-1] + 0.005]
assert fetcher.blocked and "F2" in fetcher.errors and not started_after_failure() and len(got) < 10, (starts, failed)
starts.clear(); failed.clear()
fetcher = fd.Fetcher(idents, 5, fake_fetch({"F1": TimeoutError("read timed out")}), interval=0.01)
# the requests already started end, nothing starts after the failure
fetcher.wait(5); assert not fetcher.blocked and not started_after_failure() and len(starts) < 10, (starts, failed)
assert isinstance(fetcher.errors["F1"], TimeoutError)
starts.clear()
# one file answering 500: that one has no details (a miss), the others go on, nothing is blocked
fetcher = fd.Fetcher(idents, 5, fake_fetch({"F1": preview.FileInfoStatusError(500)}), interval=0.01)
got = fetcher.wait(5)
assert not fetcher.blocked and got["F1"] is None and got["F0"]["length"] and set(got) == set(idents), got
starts.clear(); failed.clear()
fetcher = fd.Fetcher(idents, 0.12, fake_fetch({}), interval=0.05)  # starts at 0, .05, .10 only
fetcher.wait(5); assert len(starts) == 3, starts
starts.clear(); began = time.monotonic()
fetcher = fd.Fetcher(idents, 5, fake_fetch({}, delay=0.5), interval=0)
partial = fetcher.wait(0.2); fetcher.stop()
assert time.monotonic() - began < 0.45 and partial == {}, partial  # late: nothing yet, no waiting for them
fetcher.wait(3); assert len(starts) == 4, starts  # stop(): only the requests in flight ended
assert fd.Fetcher([], 1).wait(1) == {}
# no session (TLS setup failed): no threads, no details, no exception
preview._http = lambda: (_ for _ in ()).throw(RuntimeError("no TLS"))
fetcher = fd.Fetcher(["X1"], 1); assert fetcher.wait(1) == {} and "" in fetcher.errors
preview._http = lambda: None
# one Fetcher for a whole plugin call: idents added later, none requested twice, at most WORKERS in
# flight in total; the ones not started yet can be dropped and asked for later; nothing after a failure
starts.clear(); running[0] = peak[0] = 0
fetcher = fd.Fetcher(idents[:6], 5, fake_fetch({}, delay=0.3), interval=0)
fetcher.wait(0.1, idents=idents[:2]); fetcher.cancel_pending()  # F0-F3 in flight, F4 and F5 dropped
fetcher.request(idents[:8], 5)  # only F4-F7 are new; the 4 busy workers take them
got = fetcher.wait(5, idents=idents[:8])
assert peak[0] <= fd.WORKERS and sorted(i for i, _ in starts) == idents[:8] and set(got) == set(idents[:8]), (peak, starts)
fetcher.wait(5)
fetcher.request(idents[:8] + ["F8"], 5); fetcher.wait(5)  # all workers left: a new one for F8 only
assert sorted(i for i, _ in starts) == idents[:9], starts
starts.clear()
fetcher = fd.Fetcher(["F0"], 5, fake_fetch({"F0": TimeoutError("read timed out")}), interval=0)
fetcher.wait(5); fetcher.request(["F0", "F1"], 5); fetcher.wait(1, idents=["F0", "F1"])
assert [i for i, _ in starts] == ["F0"], starts  # no retry, no new request after the failure
groups += 1

# --- the add-on: the list, the background script and its one refresh ---
fetched = []
def serve(answers=None, delay=0.0):
    """preview.fetch_file_info as the Fetcher calls it: anonymous, the ident only."""
    def fetch(ident, timeout=None, wait=None):
        assert timeout == fd.REQUEST_TIMEOUT and wait == fd.REQUEST_WAIT, (timeout, wait)
        fetched.append(ident); time.sleep(delay)
        answer = (answers or {}).get(ident, film())
        if isinstance(answer, BaseException):
            raise answer
        return answer
    preview.fetch_file_info = fetch


class FakeAPI:
    def __init__(self, files): self.files, self.calls = files, []
    def search_all(self, queries, **kwargs):
        self.calls.append(list(queries))
        return [{"response": {"total": str(len(self.files)), "file": self.files}} for _ in queries]
    token = "tok"
    def get_download_link(self, ident): return f"https://dl/{ident}"
    def set_token(self, token): pass
    def login(self, user, password): pass


def ws(ident, name): return {"ident": ident, "name": name, "size": "2147483648", "img": "https://img.webshare.cz/x.jpg"}
FILES = [ws(f"R{i}", f"Synthetic.Film.2010.R{i}.mkv") for i in range(20)]
DETAILS = {"R0": film(), "R1": film(length="1500", width="1280", height="720", audio=[("ENG", "2", "AAC")]),
           "R2": film(audio=[("UND", "2", "AAC")]), "R3": None}
api = FakeAPI(FILES)
k.get_api = lambda: api
SEARCH_URL = "action=list_search_results&query=%5B%27a%27%5D&match=" + urllib.parse.quote(json.dumps(
    {"mediatype": "movie", "title": "Synthetic Film", "year": "2010", "runtime": "118"}))


def call(query, handle=1):
    """One plugin call like Kodi makes it (a new process: _api and the per-call state start empty)."""
    sys.argv = ["plugin://plugin.video.kodisimplestream/", str(handle), "?" + query]
    k._handle, k._refresh_pass = handle, False
    items.clear(); log.clear()
    k.router(query)


def rows(): return {dict(urllib.parse.parse_qsl(u.split("?", 1)[1]))["ident"]: i for u, i, _ in items if "play_ident" in u}
def builtins(): return [e[1] for e in log if e[0] == "builtin"]


# 5. the list is shown at once, a separate script fetches the top rows and refreshes the list once;
#    the refresh uses the cached search answers and details and starts nothing (no loop)
Window.props.clear(); fetched.clear(); serve(DETAILS)
call(SEARCH_URL)
# shown at once without details: name guesses, no length, no stream flags; the background script started
assert len(rows()) == 20 and all(i.tag is None and "  " not in i.label for i in rows().values()), [i.label for i in rows().values()]
assert fetched == [] and log[-1] == ("end", True, False), (fetched, log[-1])
(run_plugin,) = builtins()
assert run_plugin.startswith("RunPlugin(plugin://") and "," not in run_plugin, run_plugin
job = json.loads(Window.props[k.ENRICH_PROPERTY])
assert job["idents"] == [f"R{i}" for i in range(fd.LIST_COUNT)] and job["key"] == k._listing_key("plugin://plugin.video.kodisimplestream/?" + SEARCH_URL)
token = dict(urllib.parse.parse_qsl(run_plugin[len("RunPlugin("):-1].split("?", 1)[1]))
assert token == {"action": "file_details", "token": job["token"]}, token
# the same listing again within a minute (Back): no second job
call(SEARCH_URL); assert builtins() == [] and json.loads(Window.props[k.ENRICH_PROPERTY])["token"] == job["token"]
assert len(api.calls) == 2

# the background script (handle -1): fetches, caches, waits for the listing to be shown, refreshes it once
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?" + SEARCH_URL.replace("%5B", "%5b")
conditions["System.HasActiveModalDialog"] = False
call(f"action=file_details&token={job['token']}", handle=-1)
assert sorted(fetched) == sorted(job["idents"]) and builtins() == ["Container.Refresh"], (fetched, log)
marker = json.loads(Window.props[k.REFRESH_PROPERTY]); assert marker["key"] == job["key"]
assert any("15/15 answers, 14 with details" in e[1] for e in log if e[0] == "log"), [e for e in log if e[0] == "log"]
assert set(json.loads(Window.props[fd.SESSION_PROPERTY])) == set(job["idents"])
assert os.path.isfile(os.path.join(TMP, "profile", "addon_data", "kss", fd.CACHE_FILE))
# the refresh: the cached search answers (no search), the details, no new job – it cannot loop
fetched.clear()
call(SEARCH_URL)
assert len(api.calls) == 2 and builtins() == [] and fetched == [] and k.REFRESH_PROPERTY not in Window.props, (api.calls, log)
shown = rows(); r0, r1, r2, r3 = shown["R0"], shown["R1"], shown["R2"], shown["R3"]
# R0: real FHD of a 1920x800 file, a hidden Czech dub (CZE track), its length; R1: 25 min of a 118 min film
assert r0.label == "[FHD] [CZ dabing] Synthetic.Film.2010.R0", r0.label
# the length in the second line after the resolution: at the end of a long title it would be cut off
assert r0.label2.startswith("FHD 1920×800 | 1:58:00 | "), r0.label2
assert r1.label2.startswith(f"HD 1280×720 | [COLOR {k.WARNING_COLOR}]25:00 ![/COLOR] | "), r1.label2
assert "[CZ" not in r2.label and "| 1:58:00 |" in r2.label2, (r2.label, r2.label2)  # UND is no evidence of anything
assert r3.tag is None and r3.label == "Synthetic.Film.2010.R3", r3.label  # no details: the name guesses stay
assert r0.label2.startswith("FHD 1920×800 | ") and "Audio CZ/EN" in r0.label2, r0.label2
assert r0.tag.duration == 7080 and r0.tag.video == [{"width": 1920, "height": 800, "duration": 7080, "codec": "h264"}]
assert r0.tag.audio == [(6, "ac3", "cze"), (2, "aac", "eng")], r0.tag.audio
plot = r0.info["plot"].split("[CR]")
assert plot[:2] == ["Synthetic.Film.2010.R0.mkv", "FHD 1920×800 · 2.0 GB"], plot
assert "Video: 1920×800 · H264 · 25 fps" in plot and "Length: 1:58:00" in plot and "Audio: CZ · AC3 · 5.1, EN · AAC · 2.0" in plot, plot
assert not any(line.startswith("Audio: CZ/") for line in plot), plot  # the tracks replace the name guess
# a CZ known only from the name stays when the tracks are UND-tagged (UND is no evidence against it)
und_source = {"original_name": "Film.2010.CZ.dabing.mkv", "audio_langs": ["CZ"],
              "details": {"audio": [{"format": "AAC", "channels": "2", "language": "UND"}]}}
assert "Audio: CZ" in k._source_plot(und_source).split("[CR]"), k._source_plot(und_source)
assert f"[COLOR {k.WARNING_COLOR}]Length does not match (118 min)[/COLOR]" in r1.info["plot"].split("[CR]"), r1.info["plot"]
assert "Length does not match" not in r0.info["plot"]
# the order stays (only the language preference moves rows, see below)
assert list(shown)[:4] == ["R0", "R1", "R2", "R3"], list(shown)
# a later visit (no marker): all top rows known, so no job; the next page gets its own
Window.props.pop(k.ENRICH_PROPERTY)
call(SEARCH_URL); assert builtins() == [] and len(api.calls) == 3
groups += 1

# 6. the background script does not refresh: another listing open, a dialog over it, a newer job, nothing new
def start_job(query):
    Window.props.pop(k.ENRICH_PROPERTY, None)
    call(query)
    return json.loads(Window.props[k.ENRICH_PROPERTY])
api.files = [ws(f"N{i}", f"Synthetic.Film.2010.N{i}.mkv") for i in range(3)]
orig_window = k.REFRESH_WINDOW
k.REFRESH_WINDOW = 0.3
for folder_path, dialog in (("plugin://plugin.video.kodisimplestream/?action=other", False), (None, True)):
    Window.props.pop(fd.SESSION_PROPERTY, None)
    shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
    job = start_job(SEARCH_URL)
    info_labels["Container.FolderPath"] = folder_path or "plugin://plugin.video.kodisimplestream/?" + SEARCH_URL
    conditions["System.HasActiveModalDialog"] = dialog
    started = time.time(); call(f"action=file_details&token={job['token']}", handle=-1)
    assert builtins() == [] and k.REFRESH_PROPERTY not in Window.props and time.time() - started < 2, log
conditions["System.HasActiveModalDialog"] = False
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?" + SEARCH_URL
k.REFRESH_WINDOW = orig_window
Window.props.pop(fd.SESSION_PROPERTY, None); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
job = start_job(SEARCH_URL)
Window.props[k.ENRICH_PROPERTY] = json.dumps(dict(job, token="newer"))  # the user opened another listing
fetched.clear(); call(f"action=file_details&token={job['token']}", handle=-1); assert builtins() == [] and fetched == [], (fetched, log)
Window.props.pop(fd.SESSION_PROPERTY, None); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
serve({"N0": None, "N1": None, "N2": None})  # only "no details" answers: nothing to show, no refresh
job = start_job(SEARCH_URL)
call(f"action=file_details&token={job['token']}", handle=-1); assert builtins() == [], log
Window.props.pop(k.ENRICH_PROPERTY)
call(SEARCH_URL); assert builtins() == [], "misses are known for the session: no new job"
# a wrong token or an old URL opened as a folder does nothing
call("action=file_details&token=bad", handle=-1); assert log == []
call("action=file_details&token=bad", handle=3); assert log == [("end", False, False)], log
# Webshare refuses (403): no further requests and no jobs for a while, the listing still works
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
serve({"N0": preview.FileInfoStatusError(403)}); fetched.clear()
job = start_job(SEARCH_URL)
call(f"action=file_details&token={job['token']}", handle=-1)
assert fetched == ["N0"] or len(fetched) <= fd.WORKERS, fetched
assert fd.blocked(Window(10000)) and builtins() == [] and any("rate limited" in e[1] for e in log if e[0] == "log"), log
Window.props.pop(k.ENRICH_PROPERTY)
call(SEARCH_URL); assert builtins() == [] and len(rows()) == 3 and log[-1] == ("end", True, False)
Window.props.clear(); serve(DETAILS)
groups += 1

# 7. the refresh of a search typed on the keyboard does not ask again; the TMDb search keeps its runtime
api.files = FILES
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
class Keyboard:
    typed = []
    def __init__(self, text, heading): pass
    def doModal(self): Keyboard.typed.append(1)
    def isConfirmed(self): return True
    text = "synthetic film"
    def getText(self): return Keyboard.text
k.xbmc.Keyboard = Keyboard
call("action=search_webshare")
assert Keyboard.typed == [1] and len(rows()) == 20 and api.calls[-1] == ["synthetic film"]
job = json.loads(Window.props[k.ENRICH_PROPERTY]); assert job["key"].endswith("?action=search_webshare"), job
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?action=search_webshare"
calls_before = len(api.calls)
call(f"action=file_details&token={job['token']}", handle=-1); assert builtins() == ["Container.Refresh"]
call("action=search_webshare")
assert Keyboard.typed == [1] and len(api.calls) == calls_before and rows()["R0"].label2.startswith("FHD 1920×800 | 1:58:00 | "), rows()["R0"].label
assert "COLOR" not in rows()["R1"].label, "no runtime in a plain search: no warning"
# a stale marker is dropped, a marker of another listing is kept for it
Window.props[k.REFRESH_PROPERTY] = json.dumps({"key": "plugin://x?a=1", "time": time.time()})
call("action=search_webshare"); assert Keyboard.typed == [1, 1] and k.REFRESH_PROPERTY in Window.props
Window.props[k.REFRESH_PROPERTY] = json.dumps({"key": "x", "time": time.time() - 999})
call("action=search_webshare"); assert Keyboard.typed == [1, 1, 1] and k.REFRESH_PROPERTY not in Window.props
# another search on the keyboard has the same URL but other rows: its own job at once
Keyboard.text, api.files = "another film", [ws("K0", "Another.Film.mkv")]
call("action=search_webshare"); assert [b[:10] for b in builtins()] == ["RunPlugin("], log
assert json.loads(Window.props[k.ENRICH_PROPERTY])["idents"] == ["K0"]
# the user leaves before its details arrive and searches again with all top rows known (no new job): the
# old job is dropped, so its script neither fetches nor refreshes the new list with the old search answers
old = json.loads(Window.props[k.ENRICH_PROPERTY])
Keyboard.text, api.files = "synthetic film", FILES
call("action=search_webshare"); assert builtins() == [] and len(rows()) == 20, log
assert k.ENRICH_PROPERTY not in Window.props and k.LISTING_PROPERTY not in Window.props
fetched.clear(); call(f"action=file_details&token={old['token']}", handle=-1)
assert builtins() == [] and fetched == [] and k.REFRESH_PROPERTY not in Window.props, (fetched, log)
# the same search again (the same top rows, all known): its unfinished job stays, its refresh shows the same rows
same = dict(old, token="same", top=[f"R{i}" for i in range(fd.LIST_COUNT)])
Window.props[k.ENRICH_PROPERTY] = json.dumps(same)
call("action=search_webshare"); assert builtins() == [] and json.loads(Window.props[k.ENRICH_PROPERTY]) == same, log
Window.props.pop(k.ENRICH_PROPERTY)
# TMDb: the runtime of the film and of an episode goes into the match (URL) of the search
class FakeTMDB:
    def get_detail(self, tmdb_id): return {"title": "Synthetic Film", "original_title": None, "year": "2010", "runtime": 118}
    def get_episodes(self, tmdb_id, season):
        return [{"title": "Pilot", "season": 1, "number": 1, "runtime": 44}, {"title": "Two", "season": 1, "number": 2, "runtime": None}]
k.get_tmdb = lambda: FakeTMDB()
seen = []
orig_list = k.list_search_results
k.list_search_results = lambda terms, match=None: seen.append(match)
k.handle_tmdb_selection("movie:1", "movie")
assert seen[-1]["runtime"] == "118", seen
k.list_search_results = orig_list
call("action=list_episodes&tmdb_id=tv%3A1&season_id=1&series_title=Synthetic+Show")
matches = [json.loads(dict(urllib.parse.parse_qsl(u.split("?", 1)[1]))["match"]) for u, _, _ in items]
assert matches[0]["runtime"] == 44 and "runtime" not in matches[1], matches
groups += 1

# 8. the key of a listing: the same URL with other encodings or parameter order is the same listing
same = ("plugin://plugin.video.kodisimplestream/?action=list_search_results&query=%5B%27a+b%27%5D&sort=0",
        "plugin://plugin.video.kodisimplestream?sort=0&query=%5b%27a%20b%27%5d&action=list_search_results")
assert k._listing_key(same[0]) == k._listing_key(same[1])
assert k._listing_key(same[0]) != k._listing_key(same[0] + "&offset=30") and k._listing_key("") == "?"
groups += 1

# 9. TMDb Helper picker: details fetched before the dialog with a deadline, late ones without details;
#    a CZE track counts for the Czech dub preference
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
picker_files = [ws("T0", "Synthetic.Film.2010.1080p.mkv"), ws("T1", "Synthetic.Film.2010.720p.mkv"), ws("T2", "Synthetic.Film.2010.mkv")]
api.files = picker_files
tm = {"mediatype": "movie", "title": "Synthetic Film", "year": "2010"}
orig_deadline = fd.PICKER_DEADLINE
fd.PICKER_DEADLINE = 0.3
serve({"T0": film(audio=[("ENG", "2", "AAC")]), "T1": film(width="1280", height="720", audio=[("CZE", "2", "AC3")])}, delay=0.05)
slow = preview.fetch_file_info
preview.fetch_file_info = lambda ident, timeout=None, wait=None: (time.sleep(1.0) if ident == "T2" else None) or slow(ident, timeout, wait)
Addon.settings["lang_pref"] = "1"  # Czech dub first
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]; k._handle = 1
log.clear(); selects[:] = [1]; began = time.monotonic(); k.select_tmdbh_source(tm)
waited = time.monotonic() - began
(_, labels, plots), = [e for e in log if e[0] == "select"]
assert waited < 0.9, waited  # the deadline (0.3 s), not the 1 s of the slow answer
# the picker: no quality tag in the title (label2 starts with it), the language tag stays
assert labels[1].startswith("[CZ dabing] ") and "|| HD " in labels[1] and "1:58:00" in labels[1], labels  # T1 moved up by its CZE track
assert labels[2].startswith("Synthetic.") and "|| FHD " in labels[2] and "[CZ" not in labels[2], labels
assert "1:58:00" not in labels[3] and labels[3].startswith("Synthetic.Film.2010"), labels  # T2 too late
assert log[-1] == ("resolved", True, "https://dl/T1"), log[-1]
Addon.settings["lang_pref"] = "0"
fd.PICKER_DEADLINE = orig_deadline
time.sleep(1.0)  # the late request ends
groups += 1

# 10. auto-play: the length check with a runtime, the name check always, none fits -> the picker
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
Addon.settings.update(tmdbh_auto_play_best="true", tmdbh_auto_play_min_score="50")
api.files = [ws("A0", "Synthetic.Film.2010.1080p.mkv"), ws("A1", "Synthetic.Film.2010.720p.mkv"),
             ws("A2", "Synthetic.Film.2010.Trailer.1080p.mkv")]
serve({"A0": film(length="1500"), "A1": film(length="7000")}); fetched.clear()
log.clear(); k.tmdbh_play(dict(tm, runtime="118"))
assert log[-1] == ("resolved", True, "https://dl/A1") and not [e for e in log if e[0] == "select"], log
assert any("skips (length)" in e[1] for e in log if e[0] == "log") and set(fetched) <= {"A0", "A1", "A2"}, log
# without a runtime (TMDb Helper passes none) and without the Czech preference: no file_info wait at all
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True); fetched.clear()
log.clear(); k.tmdbh_play(tm)
assert fetched == [] and log[-1] == ("resolved", True, "https://dl/A0"), (fetched, log)
# every candidate rejected (trailer, wrong length) -> notification and the picker, not a doubtful file
api.files = [ws("B0", "Synthetic.Film.2010.1080p.mkv"), ws("B1", "Synthetic.Film.2010.Trailer.mkv")]
serve({"B0": film(length="600")}); Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
log.clear(); selects[:] = [-1]; k.tmdbh_play(dict(tm, runtime="118"))
events = [e[0] for e in log if e[0] != "log"]
assert events == ["notif", "select", "resolved"] and ("notif", "CHOOSE") in log and log[-1] == ("resolved", False, ""), log
(_, labels, _), = [e for e in log if e[0] == "select"]
assert f"|| FHD 1920×800 | [COLOR {k.WARNING_COLOR}]10:00 ![/COLOR] | " in labels[1], labels
# file_info down: the auto-play falls back to the old behaviour (unknown length is no reason)
serve({"B0": ConnectionError("down")}); Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
api.files = [ws("B0", "Synthetic.Film.2010.1080p.mkv")]
log.clear(); k.tmdbh_play(dict(tm, runtime="118"))
assert log[-1] == ("resolved", True, "https://dl/B0"), log
Addon.settings.update(tmdbh_auto_play_best="", tmdbh_auto_play_min_score="")
groups += 1

# 11. the refresh is final even when top rows stay unknown (a timeout stops the fetching): no new job
#     from the refreshed listing, so it cannot loop; a later visit without the marker may start one
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
api.files = FILES; serve({"R5": TimeoutError("read timed out")}); fetched.clear()
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?" + SEARCH_URL
conditions["System.HasActiveModalDialog"] = False
job = start_job(SEARCH_URL)
call(f"action=file_details&token={job['token']}", handle=-1)
assert "R5" in fetched and builtins() == ["Container.Refresh"], (fetched, log)
unknown = [ident for ident in job["idents"] if not k._details_cache().known(ident)]
assert "R5" in unknown, unknown  # a timeout is not cached as "no details"
call(SEARCH_URL)  # the refresh: the unknown rows start nothing
assert builtins() == [] and k.REFRESH_PROPERTY not in Window.props, log
assert json.loads(Window.props[k.ENRICH_PROPERTY])["token"] == job["token"]
assert not re.search(r"\d+:\d\d", rows()["R5"].label2) and rows()["R0"].label2.startswith("FHD 1920×800 | 1:58:00 | ")
call(SEARCH_URL)  # the same listing again by the user (no marker): the unknown rows get their own job
assert [b[:10] for b in builtins()] == ["RunPlugin("], log
assert json.loads(Window.props[k.ENRICH_PROPERTY])["idents"] == unknown
# a new sort replaces the listing in history once; its refresh must not pop the parent path again
# (Kodi does RemoveParentPath on every fetch with updateListing, GUIMediaWindow::GetDirectory)
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True); serve(DETAILS)
SORTED_URL = SEARCH_URL + "&sort=3&replace=1"
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?" + SORTED_URL
job = start_job(SORTED_URL); assert log[-1] == ("end", True, True), log
assert "replace" not in json.loads(Window.props[k.LISTING_PROPERTY]), "the refresh never replaces"
call(f"action=file_details&token={job['token']}", handle=-1); assert builtins() == ["Container.Refresh"], log
call(SORTED_URL)
assert builtins() == [] and k.REFRESH_PROPERTY not in Window.props and log[-1] == ("end", True, False), log
assert rows()["R0"].label2.startswith("FHD 1920×800 | 1:58:00 | ")
groups += 1

# 12. Kodi 19 (xbmc.python 3.0.0): no stream classes and no InfoTagVideo setters, addStreamInfo instead
class MatrixTag:  # getters only
    pass
matrix_item = ListItem("x")
matrix_item.getVideoInfoTag = lambda: MatrixTag()
classes = (k.xbmc.VideoStreamDetail, k.xbmc.AudioStreamDetail)
del k.xbmc.VideoStreamDetail, k.xbmc.AudioStreamDetail
try:
    k._set_stream_details(matrix_item, {"details": film(audio=[("CZE", "6", "AC3"), ("UND", "", "")])})
    k._set_stream_details(ListItem("y"), {})
finally:
    k.xbmc.VideoStreamDetail, k.xbmc.AudioStreamDetail = classes
assert matrix_item.streams == [("video", {"width": "1920", "height": "800", "codec": "h264", "duration": "7080"}),
                               ("audio", {"channels": "6", "codec": "ac3", "language": "cze"})], matrix_item.streams
groups += 1

# 13. one fetcher per plugin call: the picker after the auto-play check (deadline passed with requests in
#     flight) and again after a cancelled new search requests no ident twice, at most WORKERS run at once,
#     an ident that timed out is not asked again; a newer listing job stops the fetching of the old one
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
Addon.settings.update(tmdbh_auto_play_best="true", tmdbh_auto_play_min_score="50")
api.files = [ws(f"C{i}", f"Synthetic.Film.2010.Trailer.C{i}.mkv") for i in range(8)]
serve({"C1": TimeoutError("read timed out")}, delay=0.4); fetched.clear()
busy, top_busy = [0], [0]
served = preview.fetch_file_info
def counted(ident, timeout=None, wait=None):
    with lock:
        busy[0] += 1; top_busy[0] = max(top_busy[0], busy[0])
    try:
        return served(ident, timeout, wait)
    finally:
        with lock:
            busy[0] -= 1
preview.fetch_file_info = counted
orig = fd.AUTOPLAY_DEADLINE, fd.PICKER_DEADLINE
fd.AUTOPLAY_DEADLINE, fd.PICKER_DEADLINE = 0.2, 0.6
Dialog.input = lambda self, heading, default="": ""  # "Change search" cancelled
log.clear(); selects[:] = [0, -1]; k.tmdbh_play(dict(tm, runtime="118"))
time.sleep(0.6)  # the requests in flight end
assert [e[0] for e in log if e[0] not in ("log", "notif")] == ["select", "select", "resolved"], log
assert top_busy[0] <= fd.WORKERS and len(fetched) == len(set(fetched)), (top_busy, fetched)
assert fetched.count("C1") == 1 and len(fetched) <= fd.WORKERS + 2, fetched  # C1 timed out: not asked again, nothing new
fd.AUTOPLAY_DEADLINE, fd.PICKER_DEADLINE = orig
del Dialog.input
Addon.settings.update(tmdbh_auto_play_best="", tmdbh_auto_play_min_score="")
# without a failure: the picker asks only for the rows the check did not request
serve({}, delay=0.3); fetched.clear(); Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
fetcher = fd.Fetcher([], 0)
cache = k._details_cache()
results = k.search_and_score_tmdbh(tm)
k._fetch_tmdbh_details(results, fd.AUTOPLAY_COUNT, 0.1, cache, fetcher)  # the deadline passes, requests in flight
k._fetch_tmdbh_details(results, fd.PICKER_COUNT, 2, cache, fetcher)  # those are not requested again
assert sorted(fetched) == sorted(r["ident"] for r in results[:fd.PICKER_COUNT]) and len(fetched) == len(set(fetched)), fetched
assert all(cache.known(r["ident"]) for r in results[:fd.PICKER_COUNT])
# the list script: a newer job during the fetching stops further requests and the refresh
Window.props.clear(); shutil.rmtree(os.path.join(TMP, "profile"), ignore_errors=True)
api.files = FILES; serve(DETAILS, delay=0.2); fetched.clear()
info_labels["Container.FolderPath"] = "plugin://plugin.video.kodisimplestream/?" + SEARCH_URL
job = start_job(SEARCH_URL)
inner = preview.fetch_file_info
def takeover(ident, timeout=None, wait=None):
    Window.props[k.ENRICH_PROPERTY] = json.dumps(dict(job, token="newer"))  # another listing started its job
    return inner(ident, timeout, wait)
preview.fetch_file_info = takeover
began = time.monotonic(); call(f"action=file_details&token={job['token']}", handle=-1)
assert time.monotonic() - began < 1 and builtins() == [] and len(fetched) <= fd.WORKERS, (fetched, log)
time.sleep(0.3)
serve(DETAILS)
groups += 1

# the setting off: no background job for a new listing, nothing fetched for the picker or auto-play
Addon.settings["file_details"] = "false"
Window.props.pop(k.ENRICH_PROPERTY, None); Window.props.pop(k.REFRESH_PROPERTY, None)
call(SEARCH_URL.replace("%27a%27", "%27off%27"))
assert not any(b.startswith("RunPlugin(") for b in builtins()) and k.ENRICH_PROPERTY not in Window.props, log
fetched.clear(); k._fetch_tmdbh_details([{"ident": "OFF1"}], 5, 0.2, k._details_cache(), fd.Fetcher([], 0))
assert fetched == [], fetched
Addon.settings.pop("file_details")
groups += 1

shutil.rmtree(TMP, ignore_errors=True)
print(f"file details: {groups} groups of checks passed")
