"""Kids search in the plugin: listing, kids_only mode, tmdbh_no_picker, the age settings and the strings (stubbed Kodi).

Run from the repo root: python tests/test_kids_plugin.py
"""
import os
import re
import sys
import types
import xml.etree.ElementTree as ET

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []
updates = []

sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")
sys.modules["xbmc"] = types.SimpleNamespace(
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2,
    log=lambda msg, level=0: None,
    executebuiltin=lambda cmd: log.append(("builtin", cmd)),
)

STRINGS = {30007: "Chyba vyhledávání: {}", 30051: "ZADEJ KLÍČ", 30053: "KLÍČ ODMÍTNUT"}

class Addon:
    settings = {"tmdb_api_key": "0123456789abcdef0123456789abcdef"}
    stored = []
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def setSetting(self, k, v): Addon.stored.append((k, v)); Addon.settings[k] = v
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return "kss"
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)

class ListItem:
    def __init__(self, label="", label2="", path=""): self.label, self.props, self.info, self.art = label, {}, {}, {}
    def setInfo(self, kind, info): self.info = info
    def setArt(self, art): self.art = art
    def setProperty(self, k, v): self.props[k] = v
    def addContextMenuItems(self, items): self.context = list(items)

answers = []  # answers of the wizard dialogs, in the order they are asked
asked = []
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
    def select(self, heading, labels, preselect=-1): asked.append(("select", heading, list(labels), preselect)); return answers.pop(0)
    def multiselect(self, heading, labels, preselect=None): asked.append(("multi", heading, list(labels), list(preselect or []))); return answers.pop(0)
    def input(self, heading, default=""): asked.append(("input", heading, default)); return answers.pop(0)
    def numeric(self, kind, heading, default=""): asked.append(("numeric", heading, default)); return answers.pop(0)
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")

items = []
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    addDirectoryItem=lambda h, url, item, isFolder=False: items.append((url, item, isFolder)),
    endOfDirectory=lambda h, succeeded=True, updateListing=False: (log.append(("end", succeeded)), updates.append(updateListing)),
    setResolvedUrl=lambda h, ok, item: log.append(("resolved", ok)),
    setContent=lambda *a: None, addSortMethod=lambda *a: None, SORT_METHOD_NONE=0,
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k
from resources.lib import kids
from resources.lib.tmdb import TMDBAuthError

TMDBH = "plugin://plugin.video.themoviedb.helper/"

# --- kids_search: listing ---
FOUND = [
    {"id": "movie:123", "kind": "movie", "title": "Malý princ", "year": "2015", "plot": "Příběh.", "poster": "http://img/p1.jpg",
     "rating": 7.4, "certification": "8+", "country": ""},
    {"id": "tv:77", "kind": "tv", "title": "Méďové", "year": "2010", "plot": "", "poster": "http://img/p2.jpg",
     "rating": 8.0, "certification": "", "country": ""},
]
calls = []
used = []  # which search ran: "safe" (kids mode on) or "all" (off)
def fake_search(tmdb, query, kinds, cfg, **kw):
    calls.append((query, list(kinds), cfg))
    used.append(fake_search.name)
    if isinstance(fake_search.result, Exception):
        raise fake_search.result
    return fake_search.result
fake_search.result = FOUND
fake_search.name = "safe"
k.kids.search_safe = fake_search
def fake_all(tmdb, query, kinds, cfg, **kw):
    fake_search.name = "all"
    try:
        return fake_search(tmdb, query, kinds, cfg, **kw)
    finally:
        fake_search.name = "safe"
k.kids.search_all = fake_all
tmdb_client = object()
k.get_tmdb = lambda: tmdb_client
keyboard = []
k._keyboard_search = lambda label_id: (log.append(("keyboard", label_id)), keyboard.pop(0))[1]

log.clear(); items.clear(); keyboard[:] = ["princ"]
k.router("action=kids_search")
assert log == [("keyboard", 30108), ("end", True)], log
assert calls[-1][:2] == ("princ", ["movie", "tv"]), calls[-1]
(urln, itemn, foldern), (url1, item1, folder1), (url2, item2, folder2) = items
assert urln == "plugin://plugin.video.kodisimplestream/?action=kids_search&replace=1" and foldern is True and itemn.label == "#30126", items
assert updates[-1] is False, updates
assert url1 == TMDBH + "?info=play&tmdb_type=movie&tmdb_id=123" and folder1 is False and item1.props.get("IsPlayable") == "true", items
assert item1.label == "Malý princ (2015)  [8+]", item1.label
assert item1.art["poster"] == "http://img/p1.jpg" and item1.art["fanart"] == "http://img/p1.jpg", item1.art
assert item1.info["plot"] == "Příběh." and item1.info["rating"] == 7.4, item1.info
assert item1.context == [("#30142", "RunScript(plugin.video.themoviedb.helper,sync_trakt,tmdb_type=movie,tmdb_id=123)")], item1.context
assert item2.context == [("#30142", "RunScript(plugin.video.themoviedb.helper,sync_trakt,tmdb_type=tv,tmdb_id=77)")], item2.context
assert url2 == TMDBH + "?info=seasons&tmdb_type=tv&tmdb_id=77" and folder2 is True and "IsPlayable" not in item2.props, items
assert item2.label == "Méďové (2010)", item2.label  # no certification known: no brackets

# the type and the query from the URL, no keyboard
log.clear(); items.clear(); k.router("action=kids_search&type=tv&query=m%C3%A9%C4%8Fov%C3%A9")
assert calls[-1][:2] == ("méďové", ["tv"]) and ("keyboard", 30108) not in log, calls[-1]
k.router("action=kids_search&type=movie&query=x"); assert calls[-1][1] == ["movie"]
k.router("action=kids_search&type=bogus&query=x"); assert calls[-1][1] == ["movie", "tv"]

# keyboard cancelled: nothing is searched
n = len(calls); log.clear(); items.clear(); keyboard[:] = [None]
k.router("action=kids_search"); assert len(calls) == n and not items and log[-1] == ("end", False), log
keyboard[:] = ["   "]; log.clear(); k.router("action=kids_search"); assert len(calls) == n and log[-1] == ("end", False), log

# no results: a notification and an empty directory
fake_search.result = []; log.clear(); items.clear(); k.router("action=kids_search&query=nic")
assert log == [("notif", "#30109"), ("end", True)] and [i[0] for i in items] == ["plugin://plugin.video.kodisimplestream/?action=kids_search&replace=1"], (log, items)

# TMDb errors
fake_search.result = TMDBAuthError("x"); log.clear(); k.router("action=kids_search&query=a")
assert log == [("notif", "KLÍČ ODMÍTNUT"), ("end", False)], log
fake_search.result = ConnectionError("síť"); log.clear(); k.router("action=kids_search&query=a")
assert log == [("notif", "Chyba vyhledávání: síť"), ("end", False)], log
_old_key = Addon.settings.get("tmdb_api_key")
Addon.settings["tmdb_api_key"] = "SECRETKEY0123456789abcdef"
fake_search.result = ConnectionError("HTTPSConnectionPool: /3/search/movie?api_key=SECRETKEY0123456789abcdef&query=x failed")
log.clear(); k.router("action=kids_search&query=a")
assert log[0][0] == "notif" and "SECRETKEY" not in log[0][1] and "api_key=***" in log[0][1], log
Addon.settings["tmdb_api_key"] = _old_key
fake_search.result = FOUND
# a missing key: the notification of get_tmdb, nothing searched
n = len(calls); k.get_tmdb = lambda: None; log.clear(); k.router("action=kids_search&query=a"); assert len(calls) == n and log == [("end", False)], log
k.get_tmdb = lambda: tmdb_client
# New search from the results: the type is kept, the listing replaces the old one in the history
log.clear(); items.clear(); updates.clear(); keyboard[:] = ["bluey"]
k.router("action=kids_search&type=tv&replace=1")
assert updates == [True] and calls[-1][:2] == ("bluey", ["tv"]), (updates, calls[-1])
assert items[0][0] == "plugin://plugin.video.kodisimplestream/?action=kids_search&type=tv&replace=1", items[0]
# a cancelled keyboard from the results leaves the shown list as it is
log.clear(); items.clear(); updates.clear(); keyboard[:] = [None]
k.router("action=kids_search&replace=1"); assert not items and log[-1] == ("end", False) and updates == [False], (items, log, updates)
# kids mode off: everything (search_all); on: the age filter (search_safe)
Addon.settings.pop("kids_only", None); used.clear(); k.router("action=kids_search&query=a")
assert used == ["all"], used
Addon.settings["kids_only"] = "true"; used.clear(); k.router("action=kids_search&query=a")
assert used == ["safe"], used
Addon.settings["kids_only"] = "false"; used.clear(); k.router("action=kids_search&type=tv&query=a")
assert used == ["all"], used
Addon.settings.pop("kids_only", None)
print("kids_search: listing checks passed")

# --- config wiring ---
Addon.settings.update(kids_age="6", kids_unrated="1")
cfg = k._kids_config()
assert cfg == kids.KidsConfig(age=6, unrated="allow"), cfg
fake_search.result = FOUND; k.router("action=kids_search&query=a"); assert calls[-1][2] == cfg
Addon.settings.update(kids_age="abc", kids_unrated="x")
assert k._kids_config() == kids.KidsConfig(), "garbage gives the defaults"
for key in [key for key in Addon.settings if key.startswith("kids_")]:
    del Addon.settings[key]
assert k._kids_config() == kids.KidsConfig(), "empty settings give the defaults"
assert kids.KidsConfig().age == 8 and kids.KidsConfig().unrated == "deny"
print("config wiring: checks passed")

# --- kids_only: root menu and router ---
Addon.settings["kids_only"] = "true"
log.clear(); items.clear(); k.router("")
base = "plugin://plugin.video.kodisimplestream/?action=kids_search"
assert [(i[0], i[1].label, i[2]) for i in items] == [(base, "#30137", True), (base + "&type=movie", "#30138", True),
                                                   (base + "&type=tv", "#30139", True)] and log == [("end", True)], (items, log)

called = []
BLOCKED = {  # action -> (paramstring, name of the function that must not run)
    "listing": ("action=listing&category=x", "list_videos"),
    "play": ("action=play&video=x", "play_video"),
    "search_webshare": ("action=search_webshare", "search_webshare"),
    "play_ident": ("action=play_ident&ident=abc", "play_ident"),
    "preview": ("action=preview&ident=abc", "show_preview"),
    "search_tmdb_movie": ("action=search_tmdb_movie", "search_tmdb"),
    "search_tmdb_series": ("action=search_tmdb_series", "search_tmdb"),
    "tmdb_setup": ("action=tmdb_setup", "tmdb_setup"),
    "select_tmdb": ("action=select_tmdb&tmdb_id=movie:1&search_type=movie", "handle_tmdb_selection"),
    "list_episodes": ("action=list_episodes&tmdb_id=tv:1&season_id=1&series_title=S", "list_episodes"),
    "list_search_results": ("action=list_search_results&query=x", "list_search_results"),
    "file_details": ("action=file_details&token=t", "fetch_details"),
    "choose_sort": ("action=choose_sort&query=x", "choose_sort"),
    "kids_configure": ("action=kids_configure", "list_videos"),  # the wizard is gone: refused like any unknown action
    "unknown": ("action=whatever", "list_videos"),
}
originals = {name: getattr(k, name) for _, name in BLOCKED.values()}
for _, name in BLOCKED.values():
    setattr(k, name, lambda *a, _n=name, **kw: called.append(_n))
for action, (params, _) in BLOCKED.items():
    log.clear()
    k.router(params)
    expected = ("resolved", False) if action in ("play", "play_ident") else ("end", False)
    assert log == [("notif", "#30110"), expected], (action, log)
assert not called, called
for name, fn in originals.items():
    setattr(k, name, fn)

# the allowed ones
allowed = []
k.tmdbh_play = lambda params: allowed.append(("tmdbh_play", params.get("title")))
log.clear(); items.clear(); keyboard[:] = ["x"]
k.router("action=tmdbh_play&title=Film"); k.router("action=kids_search&query=a")
assert allowed == [("tmdbh_play", "Film")] and calls[-1][0] == "a" and ("notif", "#30110") not in log, (allowed, log)

# off: the Webshare search works and the root menu is the normal one with the kids entry
Addon.settings["kids_only"] = "false"
k.search_webshare = lambda: allowed.append(("search_webshare",))
log.clear(); k.router("action=search_webshare"); assert allowed[-1] == ("search_webshare",) and not log
items.clear(); k.router("")
assert [i[0].split("action=")[1] for i in items] == ["search_webshare", "search_tmdb_movie", "search_tmdb_series", "kids_menu"], items
# the submenu: everything / movies / series
items.clear(); k.router("action=kids_menu")
assert [i[0].split("action=")[1] for i in items] == ["kids_search", "kids_search&type=movie", "kids_search&type=tv"], items
print("kids_only: checks passed")

# --- tmdbh_no_picker ---
import importlib
importlib.reload(k)  # the real functions again (the stubs above replaced some)
real_best = k.play_best_tmdbh_source

events = []
k._credentials = lambda: ("u", "p")
k._add_english_title = lambda params: None
k.select_tmdbh_source = lambda params, *a: events.append(("picker",))
k.play_best_tmdbh_source = lambda params: events.append(("best",))
k.play_ident = lambda ident: events.append(("play", ident))
PARAMS = {"mediatype": "movie", "title": "Film", "year": "2020"}

for no_picker, auto, select, expected in [
    ("false", "false", None, "picker"),   # default: unchanged
    ("false", "false", "1", "picker"),
    ("false", "true", None, "best"),
    ("false", "true", "1", "picker"),     # select=1 forces the picker
    ("true", "false", None, "best"),      # auto-play even with the option off
    ("true", "false", "1", "best"),       # select=1 ignored
    ("true", "true", "1", "best"),
]:
    Addon.settings.update(tmdbh_no_picker=no_picker, tmdbh_auto_play_best=auto)
    events.clear()
    k.tmdbh_play(dict(PARAMS, **({"select": select} if select else {})))
    assert events == [(expected,)], (no_picker, auto, select, events)

# play_best_tmdbh_source: both places of the picker
k._details_cache = lambda: None
k._apply_tmdbh_details = lambda *a: None
k._fetch_autoplay_details = lambda *a: None
RESULTS = [{"score": 95, "name": "x", "ident": "i1"}]
def run_best(results, no_picker, reject=""):
    Addon.settings.update(tmdbh_no_picker=no_picker, tmdbh_auto_play_min_score="80")
    k.search_and_score_tmdbh = lambda params, query=None, capped=True: results
    k._autoplay_rejection = lambda candidate, params: reject
    events.clear(); log.clear()
    real_best(PARAMS)
    return list(events), list(log)

low = [{"score": 10, "name": "x", "ident": "i1"}]
# below the threshold: the picker by default, a notification and a failed resolve with no_picker
ev, lg = run_best(low, "false"); assert ev == [("picker",)] and ("notif", "#30111") not in lg, (ev, lg)
ev, lg = run_best(low, "true"); assert ev == [] and lg == [("notif", "#30111"), ("resolved", False)], (ev, lg)
# a candidate above the threshold that is rejected: the same two branches
ev, lg = run_best(RESULTS, "false", reject="bitrate"); assert ev == [("picker",)] and ("notif", "#30074") in lg, (ev, lg)
ev, lg = run_best(RESULTS, "true", reject="bitrate"); assert ev == [] and lg == [("notif", "#30111"), ("resolved", False)], (ev, lg)
# an acceptable candidate plays either way
for flag in ("false", "true"):
    ev, lg = run_best(RESULTS, flag); assert ev == [("play", "i1")], (flag, ev)
# kids_only implies no picker (the picker lists raw file names, and its items are play_ident, which kids mode refuses)
Addon.settings.update(tmdbh_no_picker="false", kids_only="true", tmdbh_auto_play_best="false")
for select in (None, "1"):
    events.clear()
    k.tmdbh_play(dict(PARAMS, **({"select": select} if select else {})))
    assert events == [("best",)], (select, events)
ev, lg = run_best(low, "false"); assert ev == [] and lg == [("notif", "#30111"), ("resolved", False)], (ev, lg)
ev, lg = run_best(RESULTS, "false", reject="bitrate"); assert ev == [] and lg == [("notif", "#30111"), ("resolved", False)], (ev, lg)
Addon.settings["kids_only"] = "false"
print("tmdbh_no_picker: checks passed")

# --- strings: unique ids, every used id in both languages ---
def po_ids(lang):
    path = os.path.join(REPO, "resources", "language", f"resource.language.{lang}", "strings.po")
    ids = [int(x) for x in re.findall(r'^msgctxt "#(\d+)"', open(path, encoding="utf-8").read(), re.M)]
    assert len(ids) == len(set(ids)), f"{lang}: duplicate msgctxt ids"
    return set(ids)
cs, en = po_ids("cs_cz"), po_ids("en_gb")
spec_source = open(os.path.join(REPO, "kodisimplestream.py"), encoding="utf-8").read()
used = {int(x) for x in re.findall(r"\b3\d{4}\b", spec_source)}
for setting in ET.parse(os.path.join(REPO, "resources", "settings.xml")).iter():
    for attr in ("label", "lvalues"):
        used |= {int(x) for x in re.findall(r"\d{5}", setting.get(attr) or "")}
missing = sorted(used - {30016} - (cs & en))
assert not missing, f"missing in a .po file: {missing}"
assert (cs & en) == cs | en, "both .po files have the same ids"
ids = [s.get("id") for s in ET.parse(os.path.join(REPO, "resources", "settings.xml")).iter("setting") if s.get("id")]
assert len(ids) == len(set(ids)), ids
kids_ids = sorted(i for i in ids if i.startswith("kids_"))
assert kids_ids == ["kids_age", "kids_limit", "kids_min_votes", "kids_only", "kids_percentile", "kids_sort", "kids_unrated"], kids_ids
assert "tmdbh_no_picker" in ids
settings_root = ET.parse(os.path.join(REPO, "resources", "settings.xml")).getroot()
age = settings_root.find(".//setting[@id='kids_age']")
assert age.get("type") == "number" and age.get("default") == "8", age.attrib
unrated = settings_root.find(".//setting[@id='kids_unrated']")
assert unrated.get("type") == "enum" and unrated.get("default") == "0" and unrated.get("lvalues") == "30104|30105", unrated.attrib
actions = [s for s in settings_root.iter("setting") if s.get("type") == "action"]
assert not actions, "the wizard button is gone"
# every string a kids setting uses exists in both files; removed wizard strings left nothing behind
for gone in (30093, 30094, 30095, 30096, 30097, 30100, 30103, 30106, 30112, 30113, 30114, 30115, 30116, 30117, 30118,
             30120, 30121, 30122, 30123, 30124, 30125, 30127, 30128, 30129):
    assert gone not in cs and gone not in en, gone
assert {30090, 30091, 30092, 30099, 30104, 30105, 30107, 30108, 30109, 30110, 30111, 30126, 30130, 30131, 30132, 30133, 30134, 30135, 30136, 30137, 30138, 30139, 30140, 30142} <= cs & en
assert "kids_configure" not in spec_source and "kids_cache" not in spec_source
print("kids plugin: all checks passed")
