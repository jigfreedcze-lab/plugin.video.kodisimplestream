"""Výpis výsledků z Webshare: řazení, duplicity, stránkování a přehrání (podvržené moduly Kodi).

Spuštění z kořene repozitáře: python tests/test_webshare_list.py
"""
import os
import sys
import types
import urllib.parse

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []

# --- podvržené moduly Kodi a knihoven ---
sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")
sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=None)  # csfd.py, dokud je v doplňku
sys.modules["xbmc"] = types.SimpleNamespace(
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2,
    log=lambda msg, level=0: log.append(("log", msg)),
    executebuiltin=lambda cmd: log.append(("builtin", cmd)),
)

STRINGS = {30007: "Chyba vyhledávání: {}", 30008: "Nenalezeno", 30037: "Řazení: {}", 30038: "Další (strana {})",
           30039: "Seřadit", 30040: "BEZ ODKAZU", 30041: "ŽÁDNÉ DALŠÍ", 30042: "dabing", 30043: "titulky",
           30030: "Shoda", 30031: "Hodnocení", 30032: "Nejnovější", 30033: "Největší", 30034: "Nejmenší"}

class Addon:
    settings = {"username": "u", "password": "p", "ws_sort": ""}
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return "/addon" if k == "path" else "kss"
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)

class ListItem:
    def __init__(self, label="", label2="", path=""): self.label, self.label2, self.path, self.props = label, label2, path, {}
    def setInfo(self, kind, info): self.info = info
    def setArt(self, art): self.art = art
    def setProperty(self, k, v): self.props[k] = v

selects = []
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
    def select(self, heading, labels, preselect=-1, *a): log.append(("select", tuple(labels), preselect)); return selects.pop(0)
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")

items = []
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    SORT_METHOD_NONE="none", SORT_METHOD_UNSORTED="unsorted", SORT_METHOD_LABEL="label", SORT_METHOD_SIZE="size",
    addDirectoryItem=lambda h, url, item, isFolder=False: items.append((url, item, isFolder)),
    addSortMethod=lambda h, m, labelMask="", label2Mask="": log.append(("sort", m)),
    setContent=lambda h, c: None,
    endOfDirectory=lambda h, succeeded=True, updateListing=False, cacheToDisc=True: log.append(("end", succeeded, updateListing)),
    setResolvedUrl=lambda h, ok, item: log.append(("resolved", ok, item.path)),
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k

class FakeAPI:
    def __init__(self, pages=None, link="https://dl/x", link_exc=None):
        self.pages, self.link, self.link_exc, self.calls, self.links = pages or {}, link, link_exc, [], []
    def search(self, term, limit=30, offset=0, sort="rating", category="video"):
        self.calls.append((term, limit, offset, sort))
        total, files = self.pages.get((term, offset), (0, None))
        return {"response": {"total": str(total), **({"file": files} if files is not None else {})}}
    def get_download_link(self, ident):
        self.links.append(ident)
        if self.link_exc:
            raise self.link_exc
        return self.link

def f(ident): return {"ident": ident, "name": f"{ident}.1080p.mkv", "size": "100", "img": ""}
def page(prefix, n): return [f(f"{prefix}{i}") for i in range(n)]
def params(url): return dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
def run(api, *a, **kw):
    items.clear(); log.clear(); k.get_api = lambda: api; k.list_search_results(*a, **kw)
def actions(): return [params(u)["action"] for u, _, _ in items]
groups = 0

# 1. dva dotazy, duplicita mezi nimi; odkazy se při výpisu nežádají; řazení Kodi
api = FakeAPI({("a", 0): (2, [f("X"), f("Y")]), ("b", 0): (2, [f("Y"), f("Z")])})
run(api, ["a", "b"])
assert actions() == ["choose_sort", "play_ident", "play_ident", "play_ident"], actions()
assert [params(u)["ident"] for u, _, _ in items[1:]] == ["X", "Y", "Z"]
assert api.links == [], "odkaz se nesmí žádat při výpisu"
sw = items[0]; assert sw[2] is False and sw[1].props["SpecialSort"] == "top" and sw[1].label == "Řazení: Shoda"
assert all(i[1].props.get("IsPlayable") == "true" and i[2] is False for i in items[1:])
assert items[1][1].label2.startswith("FHD 1080p"), "metadata badmin15 zůstávají ve druhém řádku"
assert [c[3] for c in api.calls] == ["", ""] and log[-1] == ("end", True, False)
assert [e[1] for e in log if e[0] == "sort"] == ["unsorted", "label", "size"]
groups += 1

# 2. stránkování: jen po plné stránce a při total > další offset (total u malých sad lže)
api = FakeAPI({("a", 0): (54, page("p", 30)), ("a", 30): (54, page("q", 24))})
run(api, ["a"]); nxt = items[-1]
assert nxt[2] is True and nxt[1].props["SpecialSort"] == "bottom" and nxt[1].label == "Další (strana 2)", nxt[1].label
assert params(nxt[0]) == {"action": "list_search_results", "query": "['a']", "sort": "0", "offset": "30"}
run(api, ["a"], offset=30); assert actions()[-1] == "play_ident" and len(items) == 1 + 24 and api.calls[-1][2] == 30
api = FakeAPI({("a", 0): (60, page("p", 29))}); run(api, ["a"]); assert actions()[-1] == "play_ident", "neplná stránka = konec"
api = FakeAPI({("a", 0): (30, page("p", 30))}); run(api, ["a"]); assert actions()[-1] == "play_ident", "total nepřesahuje další offset"
api = FakeAPI({("a", 0): (30, page("p", 30)), ("b", 0): (500, page("r", 30))}); run(api, ["a", "b"])
assert actions()[-1] == "list_search_results", "stačí, když má další stránku jeden z dotazů"
groups += 1

# 3. prázdná další stránka: upozornění a neúspěšný listing (Kodi se vrátí na předchozí stránku)
api = FakeAPI(); run(api, ["a"], offset=30)
assert log == [("notif", "ŽÁDNÉ DALŠÍ"), ("end", False, False)] and items == [], log
run(api, ["a"]); assert ("notif", "Chyba vyhledávání: Nenalezeno") in log and actions() == ["choose_sort"] and log[-1] == ("end", True, False)
groups += 1

# 4. jediný výsledek jako dict (xmltodict) a žádný <file> při total>0
api = FakeAPI({("a", 0): (1, f("ONLY")), ("b", 0): (5, None)})
run(api, ["a", "b"]); assert [params(u).get("ident") for u, _, _ in items] == [None, "ONLY"]
groups += 1

# 5. řazení: z nastavení, z URL, neplatné hodnoty; replace → updateListing
Addon.settings["ws_sort"] = "2"; api = FakeAPI(); run(api, ["a"]); assert api.calls[-1][3] == "recent" and items[0][1].label == "Řazení: Nejnovější"
run(api, ["a"], sort=3); assert api.calls[-1][3] == "largest"
Addon.settings["ws_sort"] = "9"; run(api, ["a"]); assert api.calls[-1][3] == ""
Addon.settings["ws_sort"] = "x"; run(api, ["a"], sort=-1); assert api.calls[-1][3] == ""
run(api, ["a"], offset=-30); assert api.calls[-1][2] == 0
Addon.settings["ws_sort"] = ""
api = FakeAPI({("a", 0): (1, [f("X")])}); run(api, ["a"], 1, 0, True); assert log[-1] == ("end", True, True)
groups += 1

# 6. přehrání: odkaz až teď; prázdný odkaz i výjimka → upozornění a neúspěšné přehrání
for api, expect in ((FakeAPI(link="https://dl/1"), [("resolved", True, "https://dl/1")]),
                    (FakeAPI(link=""), [("notif", "BEZ ODKAZU"), ("resolved", False, "")]),
                    (FakeAPI(link_exc=RuntimeError("síť")), [("notif", "BEZ ODKAZU"), ("resolved", False, "")])):
    log.clear(); k.get_api = lambda api=api: api; k.router("action=play_ident&ident=ID1")
    assert api.links == ["ID1"] and [e for e in log if e[0] != "log"] == expect, log
log.clear(); k.get_api = lambda: None; k.play_ident("ID1"); assert log == [("resolved", False, "")], log
log.clear(); k.router("action=play&video=https%3A%2F%2Fold%2Flink"); assert log == [("resolved", True, "https://old/link")], log
groups += 1

# 7. volba řazení v seznamu: Container.Update bez ",replace", nové řazení nahradí listing přes updateListing
k._handle = -1
log.clear(); selects[:] = [3]; k.router("action=choose_sort&query=%5B%27a%27%2C+%27b%27%5D&sort=0")
sel, upd = log
assert sel == ("select", ("Shoda", "Hodnocení", "Nejnovější", "Největší", "Nejmenší"), 0), sel
cmd = upd[1]; assert cmd.startswith("Container.Update(plugin://") and cmd.endswith(")") and ",replace" not in cmd, cmd
inner = cmd[len("Container.Update("):-1]; assert "," not in inner, "čárka v URL by rozbila builtin"
assert params(inner) == {"action": "list_search_results", "query": "['a', 'b']", "sort": "3", "replace": "1"}, params(inner)
for answer in (-1, 0):
    log.clear(); selects[:] = [answer]; k.choose_sort(["a"], 0); assert [e[0] for e in log] == ["select"], log
k._handle = 1; log.clear(); selects[:] = [-1]; k.choose_sort(["a"], 0); assert log[-1] == ("end", False, False)
groups += 1

# 8. routování výsledků s parametry
seen = []
orig = k.list_search_results
k.list_search_results = lambda q, s=None, o=0, r=False: seen.append((q, s, o, r))
k.router("action=list_search_results&query=%5B%27a%27%5D&sort=4&offset=60&replace=1")
k.router("action=list_search_results&query=jen+text&offset=abc")
assert seen == [(["a"], 4, 60, True), (["jen text"], None, 0, False)], seen
k.list_search_results = orig
groups += 1

# 9. TMDb Helper hledá vždy podle shody s názvem (OR hledání u jiného řazení přináší šum)
api = FakeAPI({("Dune 2021", 0): (1, [f("D")])}); k.get_api = lambda: api
k.search_and_score_tmdbh({"mediatype": "movie", "title": "Dune", "year": "2021"})
assert api.calls and all(c[3] == "" for c in api.calls), api.calls
groups += 1

# 10. jazyková preference: štítky v názvu, preferované soubory nahoru, jinak pořadí Webshare
def n(ident, name): return {"ident": ident, "name": name, "size": "100", "img": ""}
files = [n("P", "Film.2020.1080p.mkv"), n("S", "Film.2020.EN.CZ.titulky.mkv"), n("D", "Film.2020.CZ.Dabing.mkv"), n("Q", "Film.2020.720p.mkv")]
api = FakeAPI({("a", 0): (4, files)})
for pref, order in (("0", ["P", "S", "D", "Q"]), ("1", ["D", "P", "S", "Q"]), ("2", ["S", "P", "D", "Q"])):
    Addon.settings["lang_pref"] = pref; run(api, ["a"])
    assert [params(u)["ident"] for u, _, _ in items[1:]] == order, (pref, [params(u)["ident"] for u, _, _ in items[1:]])
labels = {params(u)["ident"]: i.label for u, i, _ in items[1:]}
assert labels["D"] == "[CZ dabing] Film.2020.CZ.Dabing" and labels["S"] == "[CZ titulky] Film.2020.EN.CZ.titulky" and labels["P"] == "Film.2020.1080p", labels
# TMDb Helper: bonus k řazení, zobrazené skóre se nemění
tm = {"mediatype": "movie", "title": "Film", "year": "2020"}
api = FakeAPI({("Film 2020", 0): (2, [n("P", "Film.2020.1080p.mkv"), n("D", "Film.2020.CZ.Dabing.mkv")])}); k.get_api = lambda: api
Addon.settings["lang_pref"] = "0"; base = {r["ident"]: r["score"] for r in k.search_and_score_tmdbh(tm)}
Addon.settings["lang_pref"] = "1"; res = k.search_and_score_tmdbh(tm)
assert [r["ident"] for r in res][0] == "D" and {r["ident"]: r["score"] for r in res} == base, (res, base)
Addon.settings["lang_pref"] = "7"; assert k.language_preference() == ""
Addon.settings["lang_pref"] = "0"
groups += 1

print(f"webshare výpis: {groups} skupin kontrol prošlo")
