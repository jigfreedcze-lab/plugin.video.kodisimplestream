"""Kids mode: the age check of a title at playback (tmdbh_play), stubbed Kodi and TMDb.

Run from the repo root: python tests/test_kids_play.py
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
STRINGS = {30007: "Chyba: {}", 30143: "Nevhodné pro věk {}", 30144: "Nehodnoceno, věk {}", 30051: "KLÍČ"}
KEY = "0123456789abcdef0123456789abcdef"

class Addon:
    settings = {"tmdb_api_key": KEY, "kids_only": "true", "kids_age": "8", "kids_min_votes": "50"}
    def getSetting(self, k): return self.settings.get(k, "")
    def getSettingBool(self, k): return self.settings.get(k) == "true"
    def getLocalizedString(self, i): return STRINGS.get(i, f"#{i}")
    def getAddonInfo(self, k): return "kss"
sys.modules["xbmcaddon"] = types.SimpleNamespace(Addon=Addon)

class ListItem:
    def __init__(self, *a, **kw): pass
class Dialog:
    def notification(self, heading, msg, icon=None, ms=None): log.append(("notif", msg))
sys.modules["xbmcgui"] = types.SimpleNamespace(Dialog=Dialog, ListItem=ListItem, NOTIFICATION_ERROR="err", NOTIFICATION_INFO="info")
sys.modules["xbmcplugin"] = types.SimpleNamespace(
    setResolvedUrl=lambda h, ok, item: log.append(("resolved", ok)),
    endOfDirectory=lambda *a, **kw: log.append(("end",)),
)
sys.argv = ["plugin://plugin.video.kodisimplestream/", "1", ""]
import kodisimplestream as k

requests_made = []  # every TMDb call: (what, kind, id)
timeouts = []  # the timeout each of them was given

def movie(cert="PG", genres=(16,), votes=5):
    return {"genres": [{"id": g} for g in genres], "vote_count": votes,
            "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": cert}]}] if cert else []}}

def show(cert="TV-Y7", genres=(16,), votes=5):
    return {"genres": [{"id": g} for g in genres], "vote_count": votes,
            "content_ratings": {"results": [{"iso_3166_1": "US", "rating": cert}] if cert else []}}

class FakeTmdb:
    data = {}  # (kind, id) -> details or Exception
    found = {}  # (imdb, kind) -> id
    def details_with_ratings(self, kind, tmdb_id, timeout=None):
        requests_made.append(("details", kind, tmdb_id)); timeouts.append(timeout)
        value = self.data.get((kind, tmdb_id), RuntimeError("TMDb request failed"))
        if isinstance(value, Exception):
            raise value
        return value
    def find_by_imdb(self, imdb, kind, timeout=None):
        requests_made.append(("find", kind, imdb)); timeouts.append(timeout)
        return self.found.get((imdb, kind))

fake = FakeTmdb()
tmdb_client = [fake]
k.get_tmdb = lambda: tmdb_client[0]
events = []
k._credentials = lambda: ("u", "p")
k._add_english_title = lambda params: events.append("english")
k.select_tmdbh_source = lambda params, *a: events.append("picker")
k.play_best_tmdbh_source = lambda params: events.append("best")
k.play_ident = lambda ident: events.append("play_ident")

def run(params, **settings):
    Addon.settings.update(settings)
    events.clear(); log.clear(); requests_made.clear()
    k.tmdbh_play(dict(params))
    return list(events), list(log), list(requests_made)

MOVIE = {"mediatype": "movie", "title": "Film", "tmdb_id": "10"}
EPISODE = {"mediatype": "episode", "showname": "Show", "season": "1", "episode": "2", "tmdb_id": "20"}
PLAYS = ["english", "best"]

def is_refused(ev, lg):
    assert ev == [] and ("resolved", False) in lg and ("resolved", True) not in lg, (ev, lg)

# allowed: plays as before, one TMDb request; the minimum of votes (50, the title has 5) does not decide
fake.data = {("movie", 10): movie("PG"), ("tv", 20): show("TV-Y7")}
ev, lg, rq = run(MOVIE)
assert ev == PLAYS and rq == [("details", "movie", 10)] and ("resolved", False) not in lg, (ev, lg, rq)

# refused by age: the notification, a failed resolve, nothing downstream (no source search, no Up Next)
fake.data[("movie", 10)] = movie("R")
ev, lg, rq = run(MOVIE); is_refused(ev, lg)
assert ("notif", "Nevhodné pro věk 8") in lg, lg
# a different age setting changes the verdict
ev, lg, rq = run(MOVIE, kids_age="17")
assert ev == PLAYS, (ev, lg)
Addon.settings["kids_age"] = "8"

# refused by genre (Horror) even with a fine rating
fake.data[("movie", 10)] = movie("G", genres=(27,))
ev, lg, rq = run(MOVIE); is_refused(ev, lg)
assert ("notif", "Nevhodné pro věk 8") in lg, lg

# unrated: refused by default (with the unrated text), allowed with kids_unrated=1
fake.data[("movie", 10)] = movie(None)
ev, lg, rq = run(MOVIE, kids_unrated="0"); is_refused(ev, lg)
assert ("notif", "Nehodnoceno, věk 8") in lg, lg
ev, lg, rq = run(MOVIE, kids_unrated="1"); assert ev == PLAYS and ("resolved", False) not in lg, (ev, lg)
Addon.settings["kids_unrated"] = "0"

# series: the episode is judged by the series (tv/content_ratings), never the episode
fake.data[("tv", 20)] = show("TV-MA")
ev, lg, rq = run(EPISODE); is_refused(ev, lg)
assert rq == [("details", "tv", 20)], rq
fake.data[("tv", 20)] = show("TV-Y7")
ev, lg, rq = run(EPISODE); assert ev == PLAYS and rq == [("details", "tv", 20)], (ev, rq)
# a movie id is not mixed up with a series id: tv/20 is unknown here, so refused
fake.data = {("movie", 20): movie("G")}
ev, lg, rq = run(EPISODE); is_refused(ev, lg)

# only an IMDb id: TMDb /find, then the details (two requests); a series by an episode IMDb id too
fake.data = {("movie", 10): movie("PG"), ("tv", 20): show("TV-Y7")}
fake.found = {("tt1", "movie"): 10, ("tt2", "tv"): 20}
ev, lg, rq = run({"mediatype": "movie", "title": "F", "imdb_id": "tt1"})
assert ev == PLAYS and rq == [("find", "movie", "tt1"), ("details", "movie", 10)], (ev, rq)
ev, lg, rq = run(dict(EPISODE, tmdb_id="_", imdb_id="tt2"))
assert ev == PLAYS and rq == [("find", "tv", "tt2"), ("details", "tv", 20)], (ev, rq)
# the age check at playback uses the shorter playback timeout for both requests
from resources.lib.tmdb import PLAYBACK_TIMEOUT
timeouts.clear()
ev, lg, rq = run({"mediatype": "movie", "title": "F", "imdb_id": "tt1"})
assert len(rq) == 2 and timeouts == [PLAYBACK_TIMEOUT, PLAYBACK_TIMEOUT], timeouts
# the TMDb id wins when both are there (one request)
ev, lg, rq = run(dict(MOVIE, imdb_id="tt1")); assert rq == [("details", "movie", 10)], rq
# unknown IMDb id, no id at all, a garbage id: refused (fail closed)
ev, lg, rq = run({"mediatype": "movie", "title": "F", "imdb_id": "tt999"}); is_refused(ev, lg)
ev, lg, rq = run({"mediatype": "movie", "title": "F"}); is_refused(ev, lg); assert rq == [], rq
ev, lg, rq = run({"mediatype": "movie", "title": "F", "tmdb_id": "abc", "imdb_id": "xx"}); is_refused(ev, lg); assert rq == [], rq
# a missing or unknown mediatype is refused before any lookup (movie and tv id spaces overlap)
fake.data = {("movie", 10): movie("G"), ("tv", 10): show("TV-Y")}
for params in ({"title": "F", "tmdb_id": "10"}, {"mediatype": "video", "title": "F", "tmdb_id": "10"},
               {"mediatype": "", "title": "F", "tmdb_id": "10", "imdb_id": "tt1"}):
    ev, lg, rq = run(params); is_refused(ev, lg); assert rq == [], rq
# unknown TMDb id (TMDb answers an error)
ev, lg, rq = run(dict(MOVIE, tmdb_id="999")); is_refused(ev, lg)

# network error: refused, the notification never carries the API key
fake.data[("movie", 10)] = RuntimeError(f"Connection failed: https://api.themoviedb.org/3/movie/10?api_key={KEY}&x=1")
ev, lg, rq = run(MOVIE); is_refused(ev, lg)
assert not any(KEY in str(entry) for entry in lg), lg
assert any(entry[0] == "notif" and entry[1].startswith("Chyba") for entry in lg), lg
# an invalid answer (no genres): refused
fake.data[("movie", 10)] = {"vote_count": 100}
ev, lg, rq = run(MOVIE); is_refused(ev, lg)
# a rejected key
fake.data[("movie", 10)] = k.TMDBAuthError("rejected")
ev, lg, rq = run(MOVIE); is_refused(ev, lg)
# no TMDb key: get_tmdb is None (it notifies itself), refused
tmdb_client[0] = None
ev, lg, rq = run(MOVIE); is_refused(ev, lg); assert rq == [], rq
tmdb_client[0] = fake

# a script call (handle -1): refused without setResolvedUrl
fake.data[("movie", 10)] = movie("R")
k._handle = -1
ev, lg, rq = run(MOVIE)
assert ev == [] and ("resolved", False) not in lg and ("notif", "Nevhodné pro věk 8") in lg, (ev, lg)
k._handle = 1

# kids mode off: no check, no TMDb request, the usual way (even for a title that would be refused)
ev, lg, rq = run(MOVIE, kids_only="false")
assert ev == ["english", "picker"] and rq == [] and ("resolved", False) not in lg, (ev, lg, rq)
Addon.settings.pop("kids_only")
ev, lg, rq = run(MOVIE)
assert ev == ["english", "picker"] and rq == [], (ev, rq)

# the real client: find_by_imdb (no network)
from resources.lib import tmdb as tmdb_module
real = tmdb_module.TMDB(KEY)
paths = []
def fake_get(path, _timeout=None, **params):
    paths.append((path, params))
    return {"movie_results": [{"id": 7}], "tv_results": [], "tv_episode_results": [{"show_id": 9}]}
real._get = fake_get
assert real.find_by_imdb("tt1", "movie") == 7 and real.find_by_imdb("tt1", "tv") == 9
assert paths[0] == ("find/tt1", {"external_source": "imdb_id"}), paths
real._get = lambda path, **p: {}
assert real.find_by_imdb("tt1", "movie") is None and real.find_by_imdb("tt1", "tv") is None

print("kids playback: checks passed")
