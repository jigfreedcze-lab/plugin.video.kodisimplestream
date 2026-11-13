"""Kids mode: signed in-memory caches of age verdicts and search results (kids_memo), stubbed Kodi and TMDb.

Run from the repo root: python tests/test_kids_memo.py
"""
import os
import sys
import types

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
log = []

sys.modules["requests"] = types.ModuleType("requests")
sys.modules["xmltodict"] = types.ModuleType("xmltodict")
sys.modules["xbmc"] = types.SimpleNamespace(
    LOGDEBUG=0, LOGINFO=1, LOGWARNING=2,
    log=lambda msg, level=0: log.append(("log", msg)),
    executebuiltin=lambda cmd: log.append(("builtin", cmd)),
    sleep=lambda ms: None,
)
STRINGS = {30007: "Chyba: {}", 30143: "Nevhodné pro věk {}", 30144: "Nehodnoceno, věk {}", 30051: "KLÍČ", 30109: "NIC"}
KEY = "0123456789abcdef0123456789abcdef"


class Addon:
    settings = {"tmdb_api_key": KEY, "kids_only": "true", "kids_age": "8", "kids_min_votes": "20",
                "tmdbh_auto_play_best": "true"}
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return "kss"


sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)


class ListItem:
    def __init__(self, *a, **kw): pass


class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))


class Window:
    props = {}  # the home window, shared by all instances
    def __init__(self, window_id): pass
    def getProperty(self, name): return Window.props.get(name, "")
    def setProperty(self, name, value): Window.props[name] = value


sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, Window=Window,
                                               NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    setResolvedUrl=lambda h, ok, item: log.append(("resolved", ok)),
    endOfDirectory=lambda *a, **kw: log.append(("end",)),
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k
from resources.lib import kids, kids_memo
from resources.lib.kids import KidsConfig, Verdict
from resources.lib.kids_memo import KidsMemo

CFG = KidsConfig(age=8, unrated="deny", min_votes=20, percentile=50, sort="relevance", limit=20)
ALLOW = Verdict(True, "age ok", 6, "US PG")
DENY = Verdict(False, "age too high", 17, "US R")


# ---------------------------------------------------------------- KidsMemo on its own
class Clock:
    now = 1_000_000.0
    def __call__(self): return self.now


clock = Clock()
store = {}
memo = KidsMemo(KEY, lambda n: store.get(n, ""), store.__setitem__, clock)

# miss, then hit with every field of the verdict
assert memo.get_verdict("movie", 10, CFG) is None
assert memo.put_verdict("movie", 10, CFG, ALLOW) and memo.put_verdict("tv", "10", CFG, DENY)
assert memo.get_verdict("movie", "10", CFG) == ALLOW and memo.get_verdict("tv", 10, CFG) == DENY
assert memo.get_verdict("movie", 11, CFG) is None  # another title
assert memo.get_verdict("movie", "abc", CFG) is None and memo.get_verdict("episode", 10, CFG) is None

# TTL: valid just before 6 hours, a miss at 6 hours
clock.now += kids_memo.VERDICT_TTL - 1
assert memo.get_verdict("movie", 10, CFG) == ALLOW
clock.now += 1
assert memo.get_verdict("movie", 10, CFG) is None
clock.now -= kids_memo.VERDICT_TTL
# a clock that went back a little keeps the record, one that went back far does not
clock.now -= 30
assert memo.get_verdict("movie", 10, CFG) == ALLOW
clock.now -= 3600
assert memo.get_verdict("movie", 10, CFG) is None
clock.now += 3630

# any setting of the decision invalidates at once; settings that do not count at playback (min votes) do not
for changed in (dict(age=9), dict(age=7), dict(unrated="allow"), dict(percentile=100), dict(percentile=60)):
    assert memo.get_verdict("movie", 10, KidsConfig(**{**CFG.__dict__, **changed})) is None, changed
assert memo.get_verdict("movie", 10, KidsConfig(**{**CFG.__dict__, "min_votes": 0, "sort": "year", "limit": 5})) == ALLOW

# another version of the algorithm, signed by ourselves: a miss
real_version = kids_memo.CACHE_VERSION
kids_memo.CACHE_VERSION = real_version + 1
memo.put_verdict("movie", 12, CFG, ALLOW)
assert memo.get_verdict("movie", 12, CFG) == ALLOW
kids_memo.CACHE_VERSION = real_version
assert memo.get_verdict("movie", 12, CFG) is None
# a record from before an edit of the age table (same version number): the digest in the fingerprint differs
memo.put_verdict("movie", 13, CFG, ALLOW)
real_digest = kids.algorithm_digest
kids.algorithm_digest = lambda: "edited"
assert memo.get_verdict("movie", 13, CFG) is None
kids.algorithm_digest = real_digest
assert memo.get_verdict("movie", 13, CFG) == ALLOW
real_table = dict(kids.AGE_TABLE["US"])
kids.AGE_TABLE["US"]["PG"] = 5
assert kids.algorithm_digest() != real_digest and memo.get_verdict("movie", 13, CFG) is None
kids.AGE_TABLE["US"].clear(); kids.AGE_TABLE["US"].update(real_table)
assert memo.get_verdict("movie", 13, CFG) == ALLOW

# a record signed by something that does not know the key (another add-on, a skin), or a different TMDb key
forger_store = {}
forger = KidsMemo("not the key", lambda n: forger_store.get(n, ""), forger_store.__setitem__, clock)
forger.put_verdict("movie", 20, CFG, ALLOW)
store[kids_memo.VERDICT_PROPERTY + "movie:20"] = forger_store[kids_memo.VERDICT_PROPERTY + "movie:20"]
assert memo.get_verdict("movie", 20, CFG) is None
assert KidsMemo("another key", store.get, store.__setitem__, clock).get_verdict("movie", 10, CFG) is None
# the same body without a signature, with a made-up one, with the signature of another body
good = store[kids_memo.VERDICT_PROPERTY + "movie:10"]
signature, _, body = good.partition(":")
for bad in (body, ":" + body, "0" * 64 + ":" + body, signature + ":" + body.replace('"a":true', '"a":false'),
            signature + ":" + body + " ", "é" * 64 + ":" + body, signature, "", "garbage", "a:b:c", "{}", None, 7):
    store[kids_memo.VERDICT_PROPERTY + "movie:10"] = bad
    assert memo.get_verdict("movie", 10, CFG) is None, bad
store[kids_memo.VERDICT_PROPERTY + "movie:10"] = good
assert memo.get_verdict("movie", 10, CFG) == ALLOW
# a valid record of another title (copied under this name) or of the search cache does not pass
store[kids_memo.VERDICT_PROPERTY + "movie:10"] = store[kids_memo.VERDICT_PROPERTY + "tv:10"]
assert memo.get_verdict("movie", 10, CFG) is None
store[kids_memo.VERDICT_PROPERTY + "movie:10"] = good
# a signed but malformed payload (wrong types) is a miss: sign by hand with the right key
for fields in ({"a": "yes"}, {"a": True, "r": 5}, {"a": True, "g": "6"}, {"a": True, "g": True}, {"a": True, "l": None}):
    payload = {"k": "movie:10", "f": kids_memo.settings_fingerprint(CFG, True), "a": True, "r": "age ok", "g": 6, "l": "x"}
    payload.update(fields)
    store[kids_memo.VERDICT_PROPERTY + "movie:10"] = memo._seal("verdict", payload)
    assert memo.get_verdict("movie", 10, CFG) is None, fields
store[kids_memo.VERDICT_PROPERTY + "movie:10"] = memo._seal("verdict", {"k": "movie:10", "f": "x", "a": True, "r": "", "g": None, "l": ""})
assert memo.get_verdict("movie", 10, CFG) is None  # another fingerprint
store[kids_memo.VERDICT_PROPERTY + "movie:10"] = good

# a store that raises is a miss, never an error; no key, no cache
def boom(*a): raise RuntimeError("window gone")
broken = KidsMemo(KEY, boom, boom, clock)
assert broken.get_verdict("movie", 10, CFG) is None and broken.put_verdict("movie", 10, CFG, ALLOW) in (True, False)
assert broken.get_search("x", ["movie"], CFG) is None
for empty_key in ("", "  ", None):
    off = KidsMemo(empty_key, store.get, store.__setitem__, clock)
    assert not off.enabled and off.get_verdict("movie", 10, CFG) is None and not off.put_verdict("movie", 10, CFG, ALLOW)
    assert off.get_search("x", ["movie"], CFG) is None and not off.put_search("x", ["movie"], CFG, [])

# degraded answers are no verdict: never stored; a real refusal is
assert not memo.put_verdict("movie", 30, CFG, Verdict(False, "no genres"))
assert not memo.put_verdict("movie", 30, CFG, Verdict(False, "bad genres"))
assert not memo.put_verdict("movie", 30, CFG, "refused") and not memo.put_verdict("movie", 0.5 and "x", CFG, ALLOW)
assert memo.get_verdict("movie", 30, CFG) is None
assert memo.put_verdict("movie", 30, CFG, Verdict(False, "unrated")) and memo.get_verdict("movie", 30, CFG).reason == "unrated"

# the key is not in what is stored
assert all(KEY not in str(value) for value in store.values())

# --- search results
RESULTS = [{"id": "movie:1", "kind": "movie", "title": "Malý princ", "year": "2015", "plot": None, "poster": None,
            "rating": 7.4, "certification": "6+", "country": ""}]
assert memo.get_search("princ", ["movie", "tv"], CFG) is None
assert memo.put_search("princ", ["movie", "tv"], CFG, RESULTS)
assert memo.get_search("princ", ["movie", "tv"], CFG) == RESULTS
assert memo.get_search("  PRINC ", ["tv", "movie"], CFG) == RESULTS  # case, spaces, order of the kinds
assert memo.get_search("princ", ["movie"], CFG) is None  # other kinds
assert memo.get_search("princ 2", ["movie", "tv"], CFG) is None
for changed in (dict(age=9), dict(unrated="allow"), dict(percentile=100), dict(min_votes=21), dict(sort="year"), dict(limit=21)):
    assert memo.get_search("princ", ["movie", "tv"], KidsConfig(**{**CFG.__dict__, **changed})) is None, changed
assert memo.put_search("nothing", ["movie"], CFG, [])  # a genuine empty result is a result
assert memo.get_search("nothing", ["movie"], CFG) == []
# the summary of the hidden titles is stored with the results (counts only) and comes back with them
HIDDEN = {"high": 2, "unrated": 1, "min_age": 12}
hstore = {}
hmemo = KidsMemo(KEY, lambda n: hstore.get(n, ""), hstore.__setitem__, clock)
hmemo.put_search("princ", ["movie", "tv"], CFG, RESULTS)
assert hmemo.get_search_report("princ", ["movie", "tv"], CFG) == (RESULTS, None)  # stored without a summary
assert hmemo.put_search("hid", ["movie"], CFG, RESULTS, HIDDEN)
assert hmemo.get_search_report("hid", ["movie"], CFG) == (RESULTS, HIDDEN)
assert hmemo.get_search("hid", ["movie"], CFG) == RESULTS  # the old accessor keeps its type
assert hmemo.put_search("hid", ["movie"], CFG, [], kids.empty_hidden()) and hmemo.get_search_report("hid", ["movie"], CFG) == ([], kids.empty_hidden())
assert hmemo.get_search_report("hid", ["tv"], CFG) is None and hmemo.get_search_report("hid", ["movie"], KidsConfig(age=9)) is None
for bad_hidden in ({"high": 1}, {"high": -1, "unrated": 0, "min_age": 0}, {"high": "1", "unrated": 0, "min_age": 0},
                   {"high": True, "unrated": 0, "min_age": 0}, {"high": 1, "unrated": 0, "min_age": 0, "title": "x"}, [1, 2, 3], "x"):
    assert not hmemo.put_search("bad", ["movie"], CFG, RESULTS, bad_hidden), bad_hidden
    assert hmemo.get_search_report("bad", ["movie"], CFG) is None
    # the same summary in a validly signed record is a miss as well (a record never half-trusted)
    hstore[kids_memo.SEARCH_PROPERTY + "0"] = hmemo._seal("search", {"f": kids_memo.search_fingerprint("bad", ["movie"], CFG), "n": RESULTS, "h": bad_hidden})
    assert hmemo.get_search_report("bad", ["movie"], CFG) is None, bad_hidden
    hstore.pop(kids_memo.SEARCH_PROPERTY + "0", None)
clock.now += kids_memo.SEARCH_TTL - 1
assert memo.get_search("princ", ["movie", "tv"], CFG) == RESULTS
clock.now += 1
assert memo.get_search("princ", ["movie", "tv"], CFG) is None
# an overwritten, forged or malformed record
memo.put_search("princ", ["movie", "tv"], CFG, RESULTS)
slot = [n for n in store if n.startswith(kids_memo.SEARCH_PROPERTY)]
forger.put_search("princ", ["movie", "tv"], CFG, [dict(RESULTS[0], title="Hacked")])
fake_slot = [n for n in forger_store if n.startswith(kids_memo.SEARCH_PROPERTY)][0]
saved = dict((n, store[n]) for n in slot)
for n in slot:
    store[n] = forger_store[fake_slot]
assert memo.get_search("princ", ["movie", "tv"], CFG) is None
store.update(saved)
assert memo.get_search("princ", ["movie", "tv"], CFG) == RESULTS
# a search record under a verdict name and the other way round do not verify
store[kids_memo.VERDICT_PROPERTY + "movie:1"] = saved[slot[0]]
assert memo.get_verdict("movie", 1, CFG) is None
for bad_results in ([{"id": 5, "kind": "movie"}], [{"id": "movie:1", "kind": "x"}], ["x"], {"id": "movie:1"}):
    store[slot[0]] = memo._seal("search", {"f": kids_memo.search_fingerprint("princ", ["movie", "tv"], CFG), "n": bad_results})
    assert memo.get_search("princ", ["movie", "tv"], CFG) is None, bad_results
store.update(saved)
# not JSON-able: not stored
assert not memo.put_search("x", ["movie"], CFG, [{"id": "movie:1", "kind": "movie", "bad": object()}])
# bounded memory: more searches than slots keep SEARCH_SLOTS properties, the newest stay
for i in range(kids_memo.SEARCH_SLOTS + 3):
    clock.now += 1
    memo.put_search(f"query {i}", ["movie"], CFG, RESULTS)
assert len([n for n in store if n.startswith(kids_memo.SEARCH_PROPERTY)]) == kids_memo.SEARCH_SLOTS
assert memo.get_search(f"query {kids_memo.SEARCH_SLOTS + 2}", ["movie"], CFG) == RESULTS and memo.get_search("query 0", ["movie"], CFG) is None
print("kids memo: unit checks passed")


# ---------------------------------------------------------------- the plugin: playback and search
requests_made = []
timeouts = []


def movie(cert="G", genres=(16,), votes=100):
    return {"genres": [{"id": g} for g in genres], "vote_count": votes,
            "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": cert}]}] if cert else []}}


class FakeTmdb:
    data = {}  # (kind, id) -> details or Exception
    found = {}
    search_results = {}  # kind -> raw items of page 1
    def details_with_ratings(self, kind, tmdb_id, timeout=None):
        requests_made.append(("details", kind, tmdb_id)); timeouts.append(timeout)
        value = self.data.get((kind, tmdb_id), RuntimeError("TMDb request failed"))
        if isinstance(value, Exception):
            raise value
        return value
    def find_by_imdb(self, imdb, kind, timeout=None):
        requests_made.append(("find", kind, imdb))
        return self.found.get((imdb, kind))
    def search_raw(self, query, kind, page=1):
        requests_made.append(("search", kind, page))
        return list(self.search_results.get(kind, [])) if page == 1 else []
    def details_extras(self, kind, tmdb_id):
        requests_made.append(("extras", kind, tmdb_id))
        return {}


fake = FakeTmdb()
k.get_tmdb = lambda: fake
events = []
k._credentials = lambda: ("u", "p")
k._add_english_title = lambda params: events.append("english")
k.select_tmdbh_source = lambda params, *a: events.append("picker")
k.play_best_tmdbh_source = lambda params: events.append("best")
listed = []
hidden_listed = []  # the summary of hidden titles handed to the listing, one per search
k.list_kids_results = lambda results, kind="both", replace=False, hidden=None: (listed.append(list(results)), hidden_listed.append(hidden))


def settings(**kw):
    Addon.settings.update({"kids_only": "true", "kids_age": "8", "kids_unrated": "0", "kids_min_votes": "20",
                           "kids_percentile": "50", "kids_sort": "0", "kids_limit": "20"})
    Addon.settings.update(kw)


def play(tmdb_id, **kw):
    settings(**kw)
    events.clear(); log.clear(); requests_made.clear()
    k.tmdbh_play({"mediatype": "movie", "title": "Film", "tmdb_id": str(tmdb_id)})
    return list(events), list(log), list(requests_made)


def search(query="princ", kind="both", **kw):
    settings(**kw)
    log.clear(); requests_made.clear(); listed.clear(); hidden_listed.clear()
    k.kids_search(kind, query)
    return (listed[0] if listed else None), list(log), list(requests_made)


def timing_lines():
    return [m for t, m in log if t == "log" and "timing" in m]


def item(i, votes=100):
    return {"id": i, "title": f"T{i}", "genre_ids": [16], "vote_count": votes, "popularity": 10 - i, "vote_average": 7.0}


fake.data = {("movie", 1): movie("G"), ("movie", 2): movie("R"), ("movie", 3): movie("G")}
fake.search_results = {"movie": [item(1), item(2), item(3, votes=5)], "tv": []}

# playback: miss -> TMDb asked and the verdict remembered; hit -> no TMDb at all, same outcome
ev, lg, rq = play(1)
assert ev == ["english", "best"] and rq == [("details", "movie", 1)], (ev, rq)
assert any("age=" in m and "cache miss" in m for m in timing_lines()), timing_lines()
ev, lg, rq = play(1)
assert ev == ["english", "best"] and rq == [], (ev, rq)
assert len(timing_lines()) == 1 and "cache hit" in timing_lines()[0] and "english=" in timing_lines()[0], timing_lines()
# a refusal is remembered too, and is still refused with the same notification
ev, lg, rq = play(2)
assert ev == [] and ("resolved", False) in lg and ("notif", "Nevhodné pro věk 8") in lg and rq == [("details", "movie", 2)]
ev, lg, rq = play(2)
assert ev == [] and ("resolved", False) in lg and ("notif", "Nevhodné pro věk 8") in lg and rq == [], (ev, lg, rq)
# a change of the age settings acts at once, in both directions
ev, lg, rq = play(2, kids_age="17")
assert ev == ["english", "best"] and rq == [("details", "movie", 2)], (ev, rq)
ev, lg, rq = play(1, kids_age="3")
assert rq == [("details", "movie", 1)], rq
ev, lg, rq = play(2, kids_age="8")  # back to the old settings: the old record was replaced by the age-17 one
assert ev == [] and rq == [("details", "movie", 2)], (ev, rq)
ev, lg, rq = play(2, kids_unrated="1")
assert rq == [("details", "movie", 2)], rq  # unrated policy changed
ev, lg, rq = play(2, kids_percentile="100")
assert rq == [("details", "movie", 2)], rq

# errors are never remembered: the next call asks TMDb again and plays when TMDb is back
Window.props.clear()
fake.data[("movie", 4)] = RuntimeError("TMDb request failed")
ev, lg, rq = play(4)
assert ev == [] and ("resolved", False) in lg and rq == [("details", "movie", 4)]
assert not any(n.startswith(kids_memo.VERDICT_PROPERTY) for n in Window.props), Window.props
fake.data[("movie", 4)] = movie("G")
ev, lg, rq = play(4)
assert ev == ["english", "best"] and rq == [("details", "movie", 4)], (ev, rq)
# a degraded answer (no genres) is a refusal, but not a remembered verdict
fake.data[("movie", 5)] = {"vote_count": 5, "release_dates": {"results": []}}
ev, lg, rq = play(5)
assert ev == [] and rq == [("details", "movie", 5)] and (kids_memo.VERDICT_PROPERTY + "movie:5") not in Window.props
fake.data[("movie", 5)] = movie("G")
ev, lg, rq = play(5)
assert ev == ["english", "best"], ev

# a forged "allowed" record of a title that TMDb refuses, written without the key: ignored
Window.props.clear()
fake.data[("movie", 6)] = movie("NC-17")
forger_store.clear()
forger.put_verdict("movie", 6, k._kids_config(), ALLOW)
Window.props.update(forger_store)
ev, lg, rq = play(6)
assert ev == [] and rq == [("details", "movie", 6)], (ev, rq)
# the right key but a record of another age setting, or an expired one, is ignored as well
Window.props.clear()
good_memo = KidsMemo(KEY, Window(10000).getProperty, Window(10000).setProperty)
settings()
good_memo.put_verdict("movie", 6, KidsConfig(age=18), ALLOW)
ev, lg, rq = play(6)
assert ev == [] and rq == [("details", "movie", 6)], (ev, rq)
Window.props.clear()
old = Clock(); old.now = k.time.time() - kids_memo.VERDICT_TTL - 5
KidsMemo(KEY, Window(10000).getProperty, Window(10000).setProperty, old).put_verdict("movie", 6, k._kids_config(), ALLOW)
ev, lg, rq = play(6)
assert ev == [] and rq == [("details", "movie", 6)], (ev, rq)

# kids mode off: nothing is read or written, and no age check at all
Window.props.clear()
ev, lg, rq = play(1, kids_only="false")
assert ev == ["english", "best"] and rq == [] and Window.props == {}, (ev, rq, Window.props)
assert "age=0.00s (cache off)" in timing_lines()[0], timing_lines()
# a verdict written before the mode was switched off is not read (kids mode on again: read as usual)
good_memo.put_verdict("movie", 6, k._kids_config(), ALLOW)
before = dict(Window.props)
play(6, kids_only="false")
assert Window.props == before

# search: miss, then hit (a Container.Refresh, the same query again) without any TMDb request
Window.props.clear()
fake.data = {("movie", 1): movie("G"), ("movie", 2): movie("R"), ("movie", 3): movie("G")}
results, lg, rq = search()
assert [r["id"] for r in results] == ["movie:1"], results
assert ("details", "movie", 1) in rq and ("details", "movie", 2) in rq and ("details", "movie", 3) not in rq, rq  # 3: few votes
assert any("kids_search timing" in m and "cache miss" in m for m in timing_lines()), timing_lines()
refreshed, lg, rq = search()
assert refreshed == results and rq == [], (refreshed, rq)
assert "cache hit" in timing_lines()[0], timing_lines()
refreshed, lg, rq = search("  PRINC  ")
assert refreshed == results and rq == []
# the summary of what the age hid (movie 2 is R = 17+; 3 was refused by the votes before its age mattered) is cached with the results
results, lg, rq = search("hid")
assert hidden_listed == [{"high": 1, "unrated": 0, "min_age": 17}] and rq, (hidden_listed, rq)
results, lg, rq = search("hid")
assert hidden_listed == [{"high": 1, "unrated": 0, "min_age": 17}] and rq == [], (hidden_listed, rq)  # a hit: same summary, no TMDb
# the search filled the playback cache with what it allowed, and only with that
ev, lg, rq = play(1)
assert ev == ["english", "best"] and rq == [], (ev, rq)
ev, lg, rq = play(2)
assert ev == [] and rq == [("details", "movie", 2)], (ev, rq)  # refused in the search: not remembered from there
# ... which also holds when the settings changed in between
results, lg, rq = search(kids_age="3")
assert rq and [r["id"] for r in results] == ["movie:1"], (results, rq)
ev, lg, rq = play(1, kids_age="8")
assert rq == [("details", "movie", 1)], rq  # the age-3 search stored its verdicts for age 3 only
# other settings of the search are part of its key
results, lg, rq = search(kids_limit="30"); assert rq, rq
results, lg, rq = search(kids_sort="1"); assert rq, rq
results, lg, rq = search(kids_min_votes="21"); assert rq, rq
results, lg, rq = search(kids_unrated="1"); assert rq, rq
results, lg, rq = search(kind="movie"); assert rq, rq

# a search with an error is not remembered: a complete failure ...
Window.props.clear()
fake.data = {}
results, lg, rq = search()
assert results == [] and any(t == "notif" for t, *_ in lg)
assert not any(n.startswith(kids_memo.SEARCH_PROPERTY) for n in Window.props), Window.props
fake.data = {("movie", 1): movie("G"), ("movie", 2): movie("R"), ("movie", 3): movie("G")}
results, lg, rq = search()
assert [r["id"] for r in results] == ["movie:1"] and rq, (results, rq)
# ... and a partial one, where an error dropped a title: shown, but not kept
Window.props.clear()
fake.search_results = {"movie": [item(1), item(2), item(7)], "tv": []}
fake.data = {("movie", 1): movie("G"), ("movie", 2): movie("R"), ("movie", 7): RuntimeError("timeout")}
results, lg, rq = search()
assert [r["id"] for r in results] == ["movie:1"], results
assert not any(n.startswith(kids_memo.SEARCH_PROPERTY) for n in Window.props), Window.props
assert (kids_memo.VERDICT_PROPERTY + "movie:1") in Window.props and (kids_memo.VERDICT_PROPERTY + "movie:7") not in Window.props
fake.data[("movie", 7)] = movie("G")
results, lg, rq = search()
assert [r["id"] for r in results] == ["movie:1", "movie:7"] and rq, results
# a genuine empty result is kept
Window.props.clear()
fake.search_results = {"movie": [], "tv": []}
results, lg, rq = search("nic")
assert results == []
results, lg, rq = search("nic")
assert results == [] and rq == []

# kids mode off: the unfiltered search leaves no cache behind and uses none
Window.props.clear()
fake.search_results = {"movie": [item(1), item(2)], "tv": []}
fake.data = {}
results, lg, rq = search(kids_only="false")
assert {r["id"] for r in results} == {"movie:1", "movie:2"} and Window.props == {}, (results, Window.props)
assert "cache off" in timing_lines()[0], timing_lines()
results, lg, rq = search(kids_only="false")
assert rq and Window.props == {}
# a forged search record (no key) is ignored: the search goes to TMDb
Window.props.clear()
fake.data = {("movie", 1): movie("G"), ("movie", 2): movie("R")}
forger_store.clear()
forger.put_search("princ", ["movie", "tv"], k._kids_config(), [dict(RESULTS[0], id="movie:666", title="Forged")])
Window.props.update(forger_store)
results, lg, rq = search()
assert [r["id"] for r in results] == ["movie:1"] and rq, results

# the API key is in no property and in no log line
assert Window.props and all(KEY not in value for value in Window.props.values())
assert all(KEY not in str(entry) for entry in log)
# without a TMDb key there is no cache (it could not be signed)
Window.props.clear()
Addon.settings["tmdb_api_key"] = ""
assert k._kids_memo() is None
Addon.settings["tmdb_api_key"] = KEY
print("kids memo: plugin checks passed")
