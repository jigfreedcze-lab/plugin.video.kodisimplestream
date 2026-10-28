import sys, types
import os
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []
sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")
xbmc = types.ModuleType("xbmc"); sys.modules["xbmc"] = xbmc
class Addon:
    settings = {"tmdb_api_key": "0123456789abcdef0123456789abcdef"}
    def getSetting(self, k): return self.settings.get(k, "")
    def getLocalizedString(self, i): return {30007: "Chyba vyhledávání: {}", 30051: "ZADEJ KLÍČ", 30053: "KLÍČ ODMÍTNUT"}.get(i, f"#{i}")
    def getAddonInfo(self, k): return "kss"
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info", ListItem=lambda **k: types.SimpleNamespace(setInfo=lambda *a: None, setArt=lambda *a: None, setProperty=lambda *a: None))
sys.modules["xbmcplugin"] = types.SimpleNamespace(endOfDirectory=lambda h, succeeded=True: log.append(("end", succeeded)), addDirectoryItem=lambda *a, **k: log.append(("item", a[1])), addSortMethod=lambda *a: None, setContent=lambda *a: None, SORT_METHOD_NONE=0)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k
from resources.lib.tmdb import TMDBAuthError

searched, matches = [], []
k.list_search_results = lambda q, match=None: (searched.append(q), matches.append(match))
class FakeTMDB:
    def __init__(self, detail=None, exc=None): self.detail, self.exc = detail, exc
    def get_detail(self, i):
        if self.exc: raise self.exc
        return self.detail
    def get_seasons(self, i): raise ConnectionError("síť")
    def get_episodes(self, i, s): raise TMDBAuthError("x")

k.get_tmdb = lambda: FakeTMDB({"title": "Neznámý film", "year": None, "original_title": None})
k.handle_tmdb_selection("movie:1", "movie"); assert searched[-1] == ["Neznámý film"], searched
assert matches[-1] == {"mediatype": "movie", "title": "Neznámý film", "originaltitle": "", "year": ""}, matches
k.get_tmdb = lambda: FakeTMDB({"title": "Pelíšky", "year": "1999", "original_title": None})
k.handle_tmdb_selection("movie:2", "movie"); assert searched[-1] == ["Pelíšky 1999"], searched
# TMDb názvy pro skóre shody: výsledky anglického dotazu nesmí zůstat za šumem českého
k.get_tmdb = lambda: FakeTMDB({"title": "Fantastická zvířata: Brumbálova tajemství", "year": "2022",
                               "original_title": "Fantastic Beasts: The Secrets of Dumbledore"})
k.handle_tmdb_selection("movie:338953", "movie")
# dotazy z matching.build_search_queries: oba názvy s rokem
assert searched[-1] == ["Fantastická zvířata: Brumbálova tajemství 2022", "Fantastic Beasts: The Secrets of Dumbledore 2022"], searched
assert matches[-1] == {"mediatype": "movie", "title": "Fantastická zvířata: Brumbálova tajemství",
                       "originaltitle": "Fantastic Beasts: The Secrets of Dumbledore", "year": "2022"}, matches
log.clear(); k.get_tmdb = lambda: FakeTMDB(exc=TMDBAuthError("x"))
k.handle_tmdb_selection("movie:3", "movie"); assert log == [("notif", "KLÍČ ODMÍTNUT"), ("end", False)], log
log.clear(); k.get_tmdb = lambda: FakeTMDB({"title": "Seriál", "year": "2008", "original_title": None})
k.handle_tmdb_selection("tv:4", "series"); assert log == [("notif", "Chyba vyhledávání: síť"), ("end", False)], log
log.clear(); k.list_episodes("tv:4", "1", "Seriál", ""); assert log == [("notif", "KLÍČ ODMÍTNUT"), ("end", False)], log

import importlib; importlib.reload(k)  # skutečné get_tmdb
log.clear(); Addon.settings["tmdb_api_key"] = "  Bearer  "; assert k.get_tmdb() is None and log == [("notif", "ZADEJ KLÍČ")], log
Addon.settings["tmdb_api_key"] = " 0123456789abcdef0123456789abcdef "; assert k.get_tmdb() is not None
log.clear(); Addon.settings.update(username="", password=""); assert k.get_api() is None and log == [("notif", "#30009")], log
print("plugin: 11 kontrol prošlo")

# --- volitelné TMDb: menu a průvodce klíčem ---
answers = []
Dialog.textviewer = lambda self, heading, text: log.append(("text", text))
Dialog.yesno = lambda self, heading, text: (log.append(("yesno", text)), answers.pop(0))[1]
Addon.openSettings = lambda self: log.append(("settings",))
xbmc.executebuiltin = lambda cmd: log.append(("builtin", cmd))

sys.modules["xbmcplugin"].addDirectoryItem = lambda h, url, item, isFolder=False: log.append(("item", url, isFolder))
def menu_actions():
    return [(i[1].split("action=")[1], i[2]) for i in log if i[0] == "item"]

Addon.settings["tmdb_api_key"] = "0123456789abcdef0123456789abcdef"
log.clear(); k.list_categories(); assert menu_actions() == [("search_webshare", True), ("search_tmdb_movie", True), ("search_tmdb_series", True)] and log[-1] == ("end", True), log
for empty in ("", "   "):
    Addon.settings["tmdb_api_key"] = empty
    log.clear(); k.list_categories(); assert menu_actions() == [("search_webshare", True), ("tmdb_setup", False)] and log[-1] == ("end", True), log
# akční položka: Kodi ji spustí jako skript s handle -1, bez listingu a bez endOfDirectory
k._handle = -1
log.clear(); answers[:] = [True]; k.router("action=tmdb_setup")
assert log == [("text", "#30055"), ("yesno", "#30056"), ("settings",), ("builtin", "Container.Refresh")], log
log.clear(); answers[:] = [False]; k.tmdb_setup()
assert log == [("text", "#30055"), ("yesno", "#30056")], log
# otevřené jako složka (stará nabídka v cache) – listing se musí ukončit jako neúspěšný
k._handle = 1
log.clear(); answers[:] = [False]; k.tmdb_setup()
assert log == [("text", "#30055"), ("yesno", "#30056"), ("end", False)], log
print("menu a průvodce: 6 kontrol prošlo")
