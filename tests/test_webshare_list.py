"""Výpis výsledků z Webshare: řazení, duplicity, stránkování a přehrání (podvržené moduly Kodi).

Spuštění z kořene repozitáře: python tests/test_webshare_list.py
"""
import os
import sys
import time
import types
import urllib.parse

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []

# --- podvržené moduly Kodi a knihoven ---
sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")
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

selects, inputs = [], []
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
    def select(self, heading, labels, preselect=-1, *a): log.append(("select", tuple(labels), preselect)); return selects.pop(0)
    def input(self, heading, default=""): log.append(("input", default)); return inputs.pop(0)

class Window:
    props = {}  # okno 10000 přežije volání pluginu (samostatné procesy)
    def __init__(self, window_id): assert window_id == 10000, window_id
    def getProperty(self, k): return self.props.get(k, "")
    def setProperty(self, k, v): self.props[k] = v
    def clearProperty(self, k): self.props.pop(k, None)
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, Window=Window, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")

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
from resources.lib.webshare import WebshareAPI, WebshareError, WebshareStatusError
real_get_api = k.get_api

class FakeAPI:
    def __init__(self, pages=None, link="https://dl/x", link_exc=None, delays=None, search_exc=None):
        self.pages, self.link, self.link_exc, self.calls, self.links = pages or {}, link, link_exc, [], []
        self.delays, self.search_exc, self.batches, self.logins, self.link_tokens, self.token = delays or {}, search_exc or {}, [], [], [], ""
    def search(self, term, limit=30, offset=0, sort="rating", category="video"):
        self.calls.append((term, limit, offset, sort))
        time.sleep(self.delays.get(term, 0))
        if term in self.search_exc:
            raise self.search_exc[term]
        total, files = self.pages.get((term, offset), (0, None))
        return {"response": {"total": str(total), **({"file": files} if files is not None else {})}}
    def search_all(self, queries, **kwargs):
        # skutečné paralelní hledání z webshare.py, jen si zapamatuje dávku dotazů v pořadí
        self.batches.append(list(queries))
        return WebshareAPI.search_all(self, queries, **kwargs)
    def login(self, user, password):
        self.logins.append(user); self.token = f"tok{len(self.logins)}"
    def set_token(self, token): self.token = token
    def get_download_link(self, ident):
        self.links.append(ident); self.link_tokens.append(self.token)
        exc = self.link_exc(self.token) if callable(self.link_exc) else self.link_exc
        if exc:
            raise exc
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
    # bez uloženého tokenu (opakování s novým přihlášením zkouší bod 17)
    Window.props.clear(); log.clear(); k.get_api = lambda api=api: api; k.router("action=play_ident&ident=ID1")
    assert api.links == ["ID1"] and [e for e in log if e[0] != "log"] == expect, log
Addon.settings["username"] = ""
log.clear(); k.play_ident("ID1"); assert log == [("notif", "#30009"), ("resolved", False, "")], log
Addon.settings["username"] = "u"
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
k.list_search_results = lambda q, s=None, o=0, r=False, match=None: seen.append((q, s, o, r, match))
k.router("action=list_search_results&query=%5B%27a%27%5D&sort=4&offset=60&replace=1")
k.router("action=list_search_results&query=jen+text&offset=abc")
assert seen == [(["a"], 4, 60, True, None), (["jen text"], None, 0, False, None)], seen
# match: objekt JSON, hodnoty jako text (matching.py), neplatný JSON / jiný typ → bez skóre
seen.clear()
for raw in ('{"mediatype":"movie","title":"Dune","year":2021,"originaltitle":null}', "{vadný", "[1, 2]", "null", '"text"', ""):
    k.router("action=list_search_results&query=%5B%27a%27%5D&" + urllib.parse.urlencode({"match": raw}))
assert [m for *_, m in seen] == [{"mediatype": "movie", "title": "Dune", "year": "2021", "originaltitle": ""}] + [None] * 5, seen
k.list_search_results = orig
seen.clear(); orig_sort = k.choose_sort
k.choose_sort = lambda q, current, match=None: seen.append((q, current, match))
k.router("action=choose_sort&query=%5B%27a%27%5D&sort=2&match=%7B%22title%22%3A%22Dune%22%7D")
k.router("action=choose_sort&query=%5B%27a%27%5D&sort=2&match=%7B")
assert seen == [(["a"], 2, {"title": "Dune"}), (["a"], 2, None)], seen
k.choose_sort = orig_sort
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

# 11. TMDb hledání filmu: s TMDb názvy (match) a řazením podle shody řadit podle skóre z matching.py jako
#     u TMDb Helperu. Webshare hledá slova přes OR – za šumem českého dotazu by zůstaly správné soubory
#     nalezené anglickým názvem (ve skutečnosti až od 31. místa).
import json
from resources.lib.matching import score_episode_result, score_movie_result
cz_q, en_q = "Fantastická zvířata: Brumbálova tajemství 2022", "Fantastic Beasts: The Secrets of Dumbledore"
fb = {"mediatype": "movie", "title": "Fantastická zvířata: Brumbálova tajemství",
      "originaltitle": "Fantastic Beasts: The Secrets of Dumbledore", "year": "2022"}
fb_files = [n("cz4k", "Fantasticka zvirata   Brumbalova tajemstvi 2022 CZ Dabing 2160p -vorek"),
            n("cz1080", "Fantastická zvířata Brumbálova tajemství CZ Dabing 1080p 2022.mkv"),
            n("zoo", "ZOO 52 Odhalene tajemstvi (2022) 720p.mkv"),
            n("hlubin", "Zvířata z hlubin 2022 S01E01 Tini Heke (H264-CZ).mp4"),
            n("grind_cz", "Fantastická zvířata-Grindelwaldovy zločiny-fantasy film USA_VB 2018 cz.avi"),
            n("en", "Fantastic Beasts The Secrets of Dumbledore 2022 1080p MAX WEB-DL DDP5.1.mkv"),
            n("grind_en", "Fantastic.Beasts.The.Crimes.Of.Grindelwald.2018.1080p.BluRay.x264.mkv"),
            n("blanche", "The Secret of Madame Blanche (Charles Brabin, 1933).avi")]
webshare_order = [x["ident"] for x in fb_files]
right, noise, other_parts = {"cz4k", "cz1080", "en"}, {"zoo", "hlubin"}, {"grind_cz", "grind_en"}
api = FakeAPI({(cz_q, 0): (5, fb_files[:5]), (en_q, 0): (3, fb_files[5:])})
def idents(): return [params(u)["ident"] for u, _, _ in items if params(u)["action"] == "play_ident"]
def shown_scores():
    rows = [(params(u)["ident"], i.label2) for u, i, _ in items if params(u)["action"] == "play_ident"]
    return {ident: int(line.rsplit("score ", 1)[1]) if "score " in line else None for ident, line in rows}
expected = {x["ident"]: score_movie_result(x, fb) for x in fb_files}
run(api, [cz_q, en_q], match=fb); order = idents()
# jiné díly série (shoda názvu před dvojtečkou, jiný rok) před šumem s jedním společným slovem
assert set(order[:3]) == right and set(order[3:5]) == other_parts and noise <= set(order[5:]), order
assert order == ["cz4k", "cz1080", "en", "grind_en", "grind_cz", "zoo", "hlubin", "blanche"], order  # 97 95 95 20 14 6 -17 -18
assert shown_scores() == expected, shown_scores()  # skóre ve druhém řádku
assert [c[3] for c in api.calls] == ["", ""] and log[-1] == ("end", True, False)
# bez match nebo s jiným řazením pořadí Webshare a žádné skóre
for kwargs in ({}, {"sort": 1, "match": fb}, {"sort": 4, "match": fb}):
    run(api, [cz_q, en_q], **kwargs)
    assert idents() == webshare_order and set(shown_scores().values()) == {None}, (kwargs, idents())
Addon.settings["ws_sort"] = "1"; run(api, [cz_q, en_q], match=fb); assert idents() == webshare_order, idents()
Addon.settings["ws_sort"] = "0"; run(api, [cz_q, en_q], match=fb); assert idents() == order, idents()
Addon.settings["ws_sort"] = ""
# CZ dabing: +15 jen k řazení – český Grindelwald … cz (14) předběhne anglický (20), zobrazené skóre se nemění
Addon.settings["lang_pref"] = "1"; run(api, [cz_q, en_q], match=fb); pref_order = idents()
assert pref_order == ["cz4k", "cz1080", "en", "grind_cz", "grind_en", "zoo", "hlubin", "blanche"], pref_order
assert shown_scores() == expected, shown_scores()
Addon.settings["lang_pref"] = "0"
groups += 1

# 12. match zůstává v URL „Další“ i „Řazení“, volba řazení ho předá dál přes Container.Update
api = FakeAPI({("a", 0): (54, page("p", 30)), ("a", 30): (54, [n("m", "Fantastic.Beasts.The.Secrets.of.Dumbledore.2022.mkv")])})
run(api, ["a"], match=fb); sort_url, next_url = items[0][0], items[-1][0]
assert params(sort_url)["action"] == "choose_sort" and json.loads(params(sort_url)["match"]) == fb, sort_url
assert params(next_url)["action"] == "list_search_results" and json.loads(params(next_url)["match"]) == fb, next_url
items.clear(); log.clear(); k.router(next_url.split("?", 1)[1])
assert api.calls[-1][2] == 30 and shown_scores() == {"m": score_movie_result({"name": "Fantastic.Beasts.The.Secrets.of.Dumbledore.2022.mkv"}, fb)}
k._handle = -1
for current, chosen in ((0, 1), (1, 0)):
    log.clear(); selects[:] = [chosen]
    k.router(f"action=choose_sort&query=%5B%27a%27%5D&sort={current}&" + urllib.parse.urlencode(k._match_params(fb)))
    cmd = log[-1][1]; inner = cmd[len("Container.Update("):-1]
    assert cmd.startswith("Container.Update(plugin://") and "," not in inner, cmd
    assert params(inner)["sort"] == str(chosen) and json.loads(params(inner)["match"]) == fb, params(inner)
k._handle = 1
# bez match se parametr do URL nepřidává
run(api, ["a"]); assert "match" not in params(items[0][0]) and "match" not in params(items[-1][0])
# neplatný match v URL: výpis bez skóre v pořadí Webshare, nespadne
api = FakeAPI({("a", 0): (2, [f("X"), f("Y")])}); k.get_api = lambda: api
for raw in ("{vadný", "[1]", '{"title": 5, "year": null, "season": [1]}'):
    items.clear(); log.clear(); k.router("action=list_search_results&query=%5B%27a%27%5D&sort=0&" + urllib.parse.urlencode({"match": raw}))
    assert idents() == ["X", "Y"] and log[-1] == ("end", True, False), (raw, log)
groups += 1

# 13. epizoda: list_episodes vloží match do URL, router ho předá a skóruje se přes score_episode_result
class FakeTMDB:
    def get_episodes(self, tmdb_id, season_id):
        return [{"id": "62086", "title": "Cat's in the Bag...", "season": 1, "number": 2}]
k.get_tmdb = lambda: FakeTMDB()
items.clear(); log.clear(); k.list_episodes("tv:1396", "1", "Perníkový táta", "Breaking Bad")
ep_url = items[0][0]; ep = json.loads(params(ep_url)["match"])
assert ep == {"mediatype": "episode", "showname": "Perníkový táta", "show_originaltitle": "Breaking Bad",
              "season": 1, "episode": 2, "episode_title": "Cat's in the Bag..."}, ep
assert "," not in ep_url and items[0][2] is True and log[-1] == ("end", True, False)
ep_files = [n("e3", "Pernikovy.tata.S01E03.mkv"), n("bb22", "Breaking.Bad.S02E02.mkv"), n("e2", "Pernikovy.tata.S01E02.CZ.mkv")]
api = FakeAPI({("Perníkový táta S01E02", 0): (3, ep_files)}); k.get_api = lambda: api
items.clear(); log.clear(); k.router(ep_url.split("?", 1)[1])
# dotazy z matching.build_search_queries: SxxEyy s oběma názvy, název seriálu s názvem epizody, 1x02
assert api.batches == [["Perníkový táta S01E02", "Breaking Bad S01E02", "Perníkový táta Cat's in the Bag...",
                         "Perníkový táta 1x02"]], api.batches
assert sorted(c[0] for c in api.calls) == sorted(api.batches[0]), api.calls
assert idents() == ["e2", "e3", "bb22"], idents()
assert shown_scores() == {x["ident"]: score_episode_result(x, ep) for x in ep_files}, shown_scores()
groups += 1

print(f"webshare výpis: {groups} skupin kontrol prošlo")

# 14. TMDb Helper bez jména a hesla: přehrání se hned zeptá na přihlášení (30009), nehledá a nehlásí „nenalezeno“;
#     výpis zdrojů hledá anonymně, přihlášení chce až přehrání položky (play_ident)
Addon.settings.update(username="", password="")
api = FakeAPI({("Film 2020", 0): (1, [f("F")])}); k.get_api = lambda: api
log.clear(); k.tmdbh_play({"mediatype": "movie", "title": "Film", "year": "2020"})
assert api.calls == [] and log == [("notif", "#30009"), ("resolved", False, "")], log
items.clear(); log.clear(); k.list_tmdbh_sources({"mediatype": "movie", "title": "Film", "year": "2020"})
assert [params(u)["ident"] for u, _, _ in items] == ["F"] and log[-1] == ("end", True, False) and api.logins == [], log
assert not [e for e in log if e[0] == "notif"], log
log.clear(); k.router(items[0][0].split("?", 1)[1]); assert log == [("notif", "#30009"), ("resolved", False, "")], log
Addon.settings.update(username="u", password="p")
print("tmdbh bez přihlášení: OK")

# 15. Náhled videa místo odznaku kvality (výchozí), kvalita v popisku; vypnutí v nastavení; soubor bez náhledu
k.get_api = lambda: FakeAPI({("a", 0): (2, [{"ident": "P", "name": "Film.2020.1080p.CZ.Dabing.mkv", "size": "100", "img": "https://img/P-S.jpg"},
                                              {"ident": "N", "name": "Film.2020.mkv", "size": "100", "img": ""}])})
items.clear(); log.clear(); k.list_search_results(["a"])
p, n = items[1][1], items[2][1]
assert p.art["thumb"] == p.art["icon"] == "https://img/P-S.jpg" and p.label.startswith("[FHD] [CZ dabing] "), (p.art, p.label)
assert n.art["thumb"].endswith("sd.png") and not n.label.startswith("["), (n.art, n.label)
Addon.settings["preview_thumbs"] = "false"
items.clear(); log.clear(); k.list_search_results(["a"])
p = items[1][1]; assert p.art["thumb"].endswith("FHD.png") and p.art["fanart"] == "https://img/P-S.jpg" and p.label.startswith("[CZ dabing] "), (p.art, p.label)
Addon.settings.pop("preview_thumbs")
print("náhledy: OK")

# 16. Výběr zdroje TMDb Helperu má stejný náhled a popisek
li = k._tmdbh_source_listitem({"ident": "P", "name": "Film.2020.1080p.CZ.Dabing.mkv", "img": "https://img/P-S.jpg", "size": 100, "score": 90})
assert li.art["thumb"] == li.art["landscape"] == "https://img/P-S.jpg" and li.label.startswith("[FHD] [CZ dabing] "), (li.art, li.label)
li = k._tmdbh_source_listitem({"ident": "N", "name": "Film.2020.mkv", "img": None, "size": 100, "score": 50})
assert li.art["thumb"].endswith("sd.png") and not li.label.startswith("["), (li.art, li.label)
print("náhledy TMDb Helper: OK")

# 17. Token z přihlášení v okně 10000 pro celé sezení Kodi: další přehrání jen file_link; jiný účet a odmítnutý
#     uložený token → nové přihlášení (jen jednou); síťová chyba ani čerstvý token se znovu nepřihlašují
def play(api, ident="ID1"):
    k.get_api = lambda: api; log.clear(); k.play_ident(ident)
    return [e for e in log if e[0] != "log"]
Window.props.clear()
api = FakeAPI(link="https://dl/1")
assert play(api) == [("resolved", True, "https://dl/1")] and api.logins == ["u"] and api.link_tokens == ["tok1"]
stored = Window.props[k.TOKEN_PROPERTY]; assert stored.endswith(":tok1") and "u" != stored.split(":")[0], stored
api = FakeAPI(link="https://dl/2")  # další volání pluginu = nový proces
assert play(api) == [("resolved", True, "https://dl/2")] and api.logins == [] and api.link_tokens == ["tok1"], api.logins
Addon.settings["username"] = "jiny"; api = FakeAPI()
assert play(api)[-1][1] is True and api.logins == ["jiny"] and Window.props[k.TOKEN_PROPERTY] != stored
Addon.settings["username"] = "u"; Window.props[k.TOKEN_PROPERTY] = stored.replace("tok1", "old")
expired = lambda token: WebshareStatusError("Webshare file_link/ returned FATAL") if token == "old" else None
api = FakeAPI(link="https://dl/3", link_exc=expired)
assert play(api) == [("resolved", True, "https://dl/3")] and api.logins == ["u"] and api.link_tokens == ["old", "tok1"], api.link_tokens
assert Window.props[k.TOKEN_PROPERTY].endswith(":tok1")
api = FakeAPI(link_exc=lambda token: WebshareStatusError("missing"))  # čerstvý token: soubor opravdu chybí
assert play(api) == [("notif", "BEZ ODKAZU"), ("resolved", False, "")] and api.link_tokens == ["tok1", "tok1"] and api.logins == ["u"]
# hláška Webshare se ukáže tak, jak ji poslal (soubor dočasně nedostupný)
unavailable = WebshareStatusError("Webshare file_link/ returned FATAL: File temporarily unavailable. (FILE_LINK_FATAL_4)",
                                  "File temporarily unavailable.", "FILE_LINK_FATAL_4")
api = FakeAPI(link_exc=lambda token: unavailable)
assert play(api) == [("notif", "Webshare: File temporarily unavailable."), ("resolved", False, "")], log
Window.props[k.TOKEN_PROPERTY] = stored
api = FakeAPI(link_exc=WebshareError("Webshare did not respond in time"))
assert play(api) == [("notif", "Webshare did not respond in time"), ("resolved", False, "")] and api.logins == [] and len(api.links) == 1
# Odvolaný uložený token může dostat status OK bez odkazu → také nové přihlášení, jen jednou
class EmptyLink(FakeAPI):
    def get_download_link(self, ident): return FakeAPI.get_download_link(self, ident) if self.token != "old" else (self.link_tokens.append(self.token) or "")
Window.props[k.TOKEN_PROPERTY] = stored.replace("tok1", "old"); api = EmptyLink(link="https://dl/5")
assert play(api) == [("resolved", True, "https://dl/5")] and api.logins == ["u"] and api.link_tokens == ["old", "tok1"], api.link_tokens
api = FakeAPI(link="")  # ani po novém přihlášení bez odkazu: konec, žádné další přihlášení
Window.props[k.TOKEN_PROPERTY] = stored.replace("tok1", "old")
assert play(api) == [("notif", "BEZ ODKAZU"), ("resolved", False, "")] and api.logins == ["u"] and api.link_tokens == ["old", "tok1"], api.link_tokens
Window.props[k.TOKEN_PROPERTY] = stored
# Uložený token se používá jen omezenou dobu (file_link možná odvolaný token neodmítne); starý formát bez času
account, saved, _ = stored.split(":", 2)
for value in (f"{account}:{int(saved) - k.TOKEN_MAX_AGE - 1}:tok0", f"{account}:{int(saved) + 3600}:tok0", f"{account}:tok0"):
    Window.props[k.TOKEN_PROPERTY] = value; api = FakeAPI(link="https://dl/4")
    assert play(api) == [("resolved", True, "https://dl/4")] and api.logins == ["u"] and api.link_tokens == ["tok1"], (value, api.link_tokens)
Window.props[k.TOKEN_PROPERTY] = f"{account}:{int(saved) - k.TOKEN_MAX_AGE + 60}:tok0"; api = FakeAPI()
assert play(api)[-1][1] is True and api.logins == [] and api.link_tokens == ["tok0"], api.link_tokens
class BadLogin(FakeAPI):
    def login(self, user, password): raise WebshareStatusError("Webshare login/ returned FATAL: Bad password (LOGIN_FATAL_1)")
Window.props[k.TOKEN_PROPERTY] = stored.replace("tok1", "old")
api = BadLogin(link_exc=expired)
assert play(api) == [("notif", "#30006"), ("resolved", False, "")] and k.TOKEN_PROPERTY not in Window.props, log
assert not any("tok" in str(e) or "old" in str(e) for e in log), "token se nesmí logovat"
print("token v okně: OK")

# 18. Výpis Webshare bez jména a hesla funguje (hledání nepotřebuje přihlášení)
Addon.settings.update(username="", password="")
api = FakeAPI({("a", 0): (1, [f("X")])}); run(api, ["a"])
assert actions() == ["choose_sort", "play_ident"] and api.logins == [] and log[-1] == ("end", True, False), log
Addon.settings.update(username="u", password="p")
print("výpis bez přihlášení: OK")

# 19. Paralelní dotazy: pomalejší první dotaz nemění pořadí stránek pro rank_files ani výsledek;
#     chyba dotazu (timeout) → upozornění a neúspěšný listing, ne traceback
api = FakeAPI({(cz_q, 0): (5, fb_files[:5]), (en_q, 0): (3, fb_files[5:])}, delays={cz_q: 0.2})
run(api, [cz_q, en_q], match=fb); assert idents() == order, idents()
run(api, [cz_q, en_q]); assert idents() == webshare_order, idents()
api = FakeAPI({("a", 0): (1, [f("X")])}, search_exc={"b": WebshareError("Webshare did not respond in time")})
run(api, ["a", "b"])
assert ("notif", "Chyba vyhledávání: Webshare did not respond in time") in log and log[-1] == ("end", False, False), log
assert not [i for i in items if params(i[0])["action"] == "play_ident"], items
print("paralelní hledání: OK")

# 20. TMDb Helper: pod prahem automatického přehrání ukáže výběr ze stejných výsledků, bez druhého hledání;
#     zrušená změna dotazu ukáže stejný seznam znovu, nový dotaz hledá jen ten
src = lambda ident, name: {"ident": ident, "name": name, "size": "100", "img": ""}  # n je od 15. přepsané
tm = {"mediatype": "movie", "title": "Film", "originaltitle": "Film", "year": "2020"}
api = FakeAPI({("Film 2020", 0): (2, [src("A", "Film.2020.1080p.mkv"), src("B", "Jiny.2019.mkv")]),
               ("Jiný film", 0): (1, [src("C", "Jiny.film.mkv")])})
k.get_api = lambda: api; Addon.settings.update(tmdbh_auto_play_best="true", tmdbh_auto_play_min_score="1000")
log.clear(); selects[:] = [2]; k.tmdbh_play(tm)
assert len(api.batches) == 1 and [e[0] for e in log if e[0] != "log"] == ["select", "resolved"], (api.batches, log)
assert log[-1] == ("resolved", True, "https://dl/x") and api.links == ["B"], api.links
log.clear(); api.batches.clear(); selects[:] = [0, 0, 1]; inputs[:] = ["", "Jiný film"]
k.tmdbh_play(tm)
picks = [e for e in log if e[0] == "select"]
assert api.batches == [k.build_tmdbh_queries(tm), ["Jiný film"]] and len(picks) == 3, api.batches
labels = [[i.label for i in pick[1]] for pick in picks]
assert labels[0] == labels[1] and len(labels[0]) == 3 and len(labels[2]) == 2, labels
assert log[-1] == ("resolved", True, "https://dl/x") and api.links[-1] == "C", api.links
Addon.settings.update(tmdbh_auto_play_best="", tmdbh_auto_play_min_score="")
print("tmdbh bez druhého hledání: OK")

# 21. TMDb Helper: Webshare neodpovídá na žádný dotaz → chyba hledání, ne „nenalezeno“ ani nabídka nového dotazu;
#     odpověď aspoň na jeden dotaz stačí
down = {q: WebshareError("Webshare did not respond in time") for q in k.build_tmdbh_queries(tm)}
api = FakeAPI(search_exc=down); k.get_api = lambda: api
for auto in ("true", ""):
    Addon.settings["tmdbh_auto_play_best"] = auto
    log.clear(); k.tmdbh_play(tm)
    assert [e for e in log if e[0] != "log"] == [("notif", "Chyba vyhledávání: Webshare did not respond in time"), ("resolved", False, "")], log
items.clear(); log.clear(); k.list_tmdbh_sources(tm)
assert [e for e in log if e[0] != "log"] == [("notif", "Chyba vyhledávání: Webshare did not respond in time"), ("end", False, False)], log
ep = {"mediatype": "episode", "showname": "Seriál", "show_originaltitle": "Show", "season": "1", "episode": "2"}
queries = k.build_tmdbh_queries(ep); assert len(queries) > 1, queries
api = FakeAPI({(queries[-1], 0): (1, [src("E", "Show.S01E02.mkv")])}, search_exc={queries[0]: WebshareError("x")})
k.get_api = lambda: api; log.clear(); res = k.search_and_score_tmdbh(ep)
assert [r["ident"] for r in res] == ["E"] and not [e for e in log if e[0] == "notif"], log
Addon.settings["tmdbh_auto_play_best"] = ""
print("tmdbh bez odpovědi: OK")

# 22. Verze OpenSSL jednou do logu (debug), klient sdílený celým voláním pluginu
k.get_api = real_get_api; k._api = None; orig_api = k.WebshareAPI; k.WebshareAPI = FakeAPI
log.clear(); first = k.get_api(); assert k.get_api() is first
import ssl
assert [e for e in log if e[0] == "log"] == [("log", f"[KodiSimpleStream] {ssl.OPENSSL_VERSION}")], log
k.WebshareAPI = orig_api
print("OpenSSL v logu: OK")
