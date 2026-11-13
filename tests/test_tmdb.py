import sys, types
import os
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
calls = []
class Resp:
    def __init__(self, data, code=200): self._d, self.status_code, self.text = data, code, str(data)
    def json(self): return self._d
FAKE = {
 "search/movie": {"results": [{"id": 129, "title": "Cesta do fantazie", "original_title": "千と千尋の神隠し", "release_date": "2001-07-20", "vote_average": 8.535, "overview": "Desetiletá Čihiro…", "poster_path": "/abc.jpg"},
                              {"id": 672, "title": "Harry Potter a Tajemná komnata", "original_title": "Harry Potter and the Chamber of Secrets", "release_date": "2002-11-13", "vote_average": 7.7, "overview": "", "poster_path": None}]},
 "movie/129": {"id": 129, "title": "Cesta do fantazie", "original_title": "千と千尋の神隠し", "release_date": "2001-07-20", "genres": [{"name": "Animovaný"}], "poster_path": "/abc.jpg",
               "translations": {"translations": [{"iso_639_1": "ja", "data": {"title": ""}}, {"iso_639_1": "en", "data": {"title": "Spirited Away"}}]}},
 "movie/672": {"id": 672, "title": "Harry Potter a Tajemná komnata", "original_title": "Harry Potter and the Chamber of Secrets", "release_date": "2002-11-13", "translations": {"translations": []}},
 "movie/999": {"id": 999, "title": "Pelíšky", "original_title": "Pelíšky", "release_date": "1999-04-01", "translations": {"translations": []}},
 "search/tv": {"results": [{"id": 1396, "name": "Perníkový táta", "original_name": "Breaking Bad", "first_air_date": "2008-01-20"}]},
 "tv/1396": {"id": 1396, "name": "Perníkový táta", "original_name": "Breaking Bad", "first_air_date": "2008-01-20",
             "seasons": [{"season_number": 0, "name": "Speciály", "air_date": None, "episode_count": 9}, {"season_number": 2, "name": "Série 2", "air_date": "2009-03-08", "episode_count": 13}, {"season_number": 1, "name": "Série 1", "air_date": "2008-01-20", "episode_count": 7}]},
 "tv/1396/season/1": {"episodes": [{"id": 62086, "name": "Kočka v pytli", "season_number": 1, "episode_number": 2}, {"id": 62085, "name": "Pilot", "season_number": 1, "episode_number": 1}]},
}
requests = types.ModuleType("requests"); sys.modules["requests"] = requests
handler = None  # what the shared session answers with; the checks below swap it
class FakeCookies:
    def set_policy(self, policy): self.policy = policy
class FakeSession:
    created = []
    def __init__(self): self.cookies = FakeCookies(); self.gets = 0; FakeSession.created.append(self)
    def get(self, url, params=None, headers=None, timeout=None):
        self.gets += 1
        return handler(url, params, headers, timeout)
requests.Session = FakeSession
requests.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("every TMDb call must go through the shared session"))
def fake_get(url, params=None, headers=None, timeout=None):
    path = url.split("/3/", 1)[1]
    calls.append((path, dict(params or {}), dict(headers or {})))
    return Resp(FAKE[path]) if path in FAKE else Resp({"status_message": "nope"}, 404)
handler = fake_get
from resources.lib.tmdb import TMDB, TIMEOUT, PLAYBACK_TIMEOUT

t = TMDB("0123456789abcdef0123456789abcdef")
res = t.search("cesta", type="movie")
assert [r["id"] for r in res] == ["movie:129", "movie:672"], res
assert res[0]["year"] == "2001" and res[0]["rating"] == 8.5 and res[0]["poster"] == "https://image.tmdb.org/t/p/w500/abc.jpg"
assert res[1]["poster"] is None and res[1]["plot"] is None
assert calls[-1][1]["api_key"] and calls[-1][1]["language"] == "cs-CZ" and "Authorization" not in calls[-1][2]
d = t.get_detail("movie:129"); assert d["original_title"] == "Spirited Away" and d["genres"] == ["Animovaný"], d
d = t.get_detail("movie:672"); assert d["original_title"] == "Harry Potter and the Chamber of Secrets", d
d = t.get_detail("movie:999"); assert d["original_title"] is None, d
s = t.get_seasons("tv:1396"); assert [x["number"] for x in s] == [1, 2] and s[0]["id"] == "1" and s[0]["year"] == "2008", s
e = t.get_episodes("tv:1396", "1"); assert [(x["season"], x["number"], x["title"]) for x in e] == [(1, 1, "Pilot"), (1, 2, "Kočka v pytli")], e
t4 = TMDB("eyJ" + "x" * 200); sr = t4.search("x", type="series"); assert sr[0]["id"] == "tv:1396" and sr[0]["type"] == "series" and sr[0]["original_title"] == "Breaking Bad", sr
assert calls[-1][0] == "search/tv" and calls[-1][2]["Authorization"].startswith("Bearer ") and "api_key" not in calls[-1][1]
try: t.get_detail("123"); raise SystemExit("chybí kontrola id")
except ValueError: pass
try: t.get_detail("movie:404"); raise SystemExit("chybí chyba HTTP")
except Exception as ex: assert "404" in str(ex)
try: TMDB(""); raise SystemExit("chybí kontrola klíče")
except ValueError: pass
print("všech", 14, "kontrol prošlo")

# --- 2. kolo: nálezy z review ---
from resources.lib.tmdb import TMDBAuthError
FAKE["movie/500"] = {"id": 500, "title": "千と千尋の神隠し", "original_title": "千と千尋の神隠し", "release_date": "2001-07-20",
    "translations": {"translations": [{"iso_639_1": "en", "iso_3166_1": "GB", "data": {"title": ""}}, {"iso_639_1": "en", "iso_3166_1": "CA", "data": {"title": "Spirited Away CA"}}, {"iso_639_1": "en", "iso_3166_1": "US", "data": {"title": "Spirited Away"}}]}}
FAKE["movie/501"] = {"id": 501, "title": "Cesta do fantazie", "original_title": "千と千尋の神隠し", "release_date": "",
    "translations": {"translations": [{"iso_639_1": "en", "iso_3166_1": "GB", "data": {"title": ""}}, {"iso_639_1": "en", "iso_3166_1": "CA", "data": {"title": "Spirited Away CA"}}]}}
FAKE["movie/502"] = {"id": 502, "title": "Брат", "original_title": "Брат", "release_date": "1997-05-17", "translations": {"translations": []}}
d = t.get_detail("movie:500"); assert (d["title"], d["original_title"]) == ("Spirited Away", None), d
d = t.get_detail("movie:501"); assert (d["title"], d["original_title"], d["year"]) == ("Cesta do fantazie", "Spirited Away CA", None), d
d = t.get_detail("movie:502"); assert (d["title"], d["original_title"]) == ("Брат", None), d
FAKE["tv/1396"]["translations"] = {"translations": []}
n = len(calls); t.get_detail("tv:1396"); s = t.get_seasons("tv:1396"); assert len(calls) == n + 1 and [x["number"] for x in s] == [1, 2], (calls[n:], s)
tb = TMDB("  Bearer eyJ" + "y" * 200 + "  "); tb.search("x", type="series"); assert calls[-1][2]["Authorization"] == "Bearer eyJ" + "y" * 200
try: TMDB("Bearer   "); raise SystemExit("chybí kontrola prázdného tokenu")
except ValueError: pass
real_get = handler
handler = lambda *a, **k: Resp({"status_code": 7}, 401)
try: t.search("x"); raise SystemExit("401 nevyhodilo TMDBAuthError")
except TMDBAuthError: pass
handler = real_get
print("2. kolo: dalších 8 kontrol prošlo")

# --- 3. kolo: stopáž (minuty) pro kontrolu délky nalezených souborů, bez dalšího dotazu ---
FAKE["movie/129"]["runtime"] = 125
FAKE["tv/1396/season/1"]["episodes"][0]["runtime"] = 47
n = len(calls)
assert t.get_detail("movie:129")["runtime"] == 125 and t.get_detail("movie:672")["runtime"] is None
assert t.get_detail("tv:1396")["runtime"] is None, "seriál: stopáž mají až epizody"
e = t.get_episodes("tv:1396", "1"); assert {x["number"]: x["runtime"] for x in e} == {1: None, 2: 47}, e
assert len(calls) == n + 4
print("3. kolo: stopáž OK")

# --- 4. kolo: anglický název pro TMDb Helper (jen překlady, krátký timeout) ---
FAKE["movie/129/translations"] = {"id": 129, "translations": [{"iso_639_1": "en", "iso_3166_1": "GB", "data": {"title": "Spirited Away (GB)"}},
                                                             {"iso_639_1": "en", "iso_3166_1": "US", "data": {"title": "Spirited Away"}}]}
FAKE["tv/1396/translations"] = {"id": 1396, "translations": [{"iso_639_1": "de", "data": {"name": "Breaking Bad"}}]}
timeouts = []
def timed_get(url, params=None, headers=None, timeout=None):
    timeouts.append(timeout); return fake_get(url, params, headers, timeout)
handler = timed_get
quick = TMDB("0123456789abcdef0123456789abcdef", timeout=3)
assert quick.english_title("movie:129") == "Spirited Away" and quick.english_title("tv:1396") == ""
assert timeouts == [3, 3] and calls[-1][0] == "tv/1396/translations", (timeouts, calls[-1])
assert t.get_detail("movie:999") and timeouts[-1] == TIMEOUT == (3.05, 8), "výchozí timeout: spojení 3.05 s, čtení 8 s"
handler = fake_get
print("4. kolo: anglický název OK")

# --- 5. kolo: sdílená session, timeouty, 429 s jedním opakováním, klíč nikdy ve výjimce ---
import resources.lib.tmdb as tmdb_mod
KEY = "0123456789abcdef0123456789abcdef"
TOKEN = "eyJ" + "z" * 200

# a single keep-alive session for every client and every call, without cookies
assert len(FakeSession.created) == 1, FakeSession.created
session = FakeSession.created[0]
assert session.gets >= len(calls) > 10, "všechny dosavadní dotazy šly přes session"
before, n = session.gets, len(calls)
TMDB(KEY).search("x"); TMDB(TOKEN, timeout=3).search("x")
assert len(FakeSession.created) == 1 and session.gets - before == len(calls) - n == 2, "další klienti sdílejí tutéž session"
assert tmdb_mod.shared_session() is session
assert session.cookies.policy.allowed_domains() == (), "cookies zakázané"

# timeouts: (connect, read) by default, the age check at playback is shorter, an explicit one wins
timeouts = []
def timed(url, params=None, headers=None, timeout=None):
    timeouts.append(timeout); return fake_get(url, params, headers, timeout)
handler = timed
FAKE["find/tt1"] = {"movie_results": [{"id": 129}]}
t.search("x"); assert timeouts[-1] == (3.05, 8)
t.details_with_ratings("movie", 129); assert timeouts[-1] == (3.05, 8)
t.details_with_ratings("movie", 129, timeout=PLAYBACK_TIMEOUT); assert timeouts[-1] == (3.05, 6) == PLAYBACK_TIMEOUT
assert t.find_by_imdb("tt1", "movie", timeout=PLAYBACK_TIMEOUT) == 129 and timeouts[-1] == (3.05, 6)
assert t.find_by_imdb("tt1", "movie") == 129 and timeouts[-1] == (3.05, 8)
assert TMDB(KEY, timeout=3).search("x") is not None and timeouts[-1] == 3

# HTTP 429: one retry after Retry-After (capped at 2 s, 1 s by default), a second 429 raises, never a third attempt
class Resp429(Resp):
    def __init__(self, retry_after=None, text="slow down"):
        super().__init__({}, 429); self.text = text
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}
sleeps, attempts, logged = [], [], []
real_time, real_log = tmdb_mod.time, tmdb_mod._log
tmdb_mod.time = types.SimpleNamespace(sleep=sleeps.append)
tmdb_mod._log = logged.append
def answers(*responses):
    queue = list(responses)
    def answer(url, params=None, headers=None, timeout=None):
        attempts.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception): raise item
        return item
    return answer
def run429(*responses):
    global handler
    attempts.clear(); sleeps.clear(); logged.clear()
    handler = answers(*responses)
    return t.search("x")
for retry_after, expected in (("1.5", 1.5), ("30", 2.0), (None, 1.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0), ("-5", 0.0), ("nan", 1.0)):
    assert run429(Resp429(retry_after), Resp(FAKE["search/movie"])) and len(attempts) == 2 and sleeps == [expected], (retry_after, sleeps)
assert logged and all(KEY not in m and "api_key" not in m for m in logged), logged
try: run429(Resp429("0"), Resp429("0"), Resp(FAKE["search/movie"])); raise SystemExit("druhé 429 nevyhodilo výjimku")
except tmdb_mod.TMDBError as ex: assert "429" in str(ex) and KEY not in str(ex)
assert len(attempts) == 2 and len(sleeps) == 1, "žádný třetí pokus"
try: run429(Resp(FAKE["search/movie"], 500), Resp(FAKE["search/movie"])); raise SystemExit("500 se nemá opakovat")
except tmdb_mod.TMDBError: assert len(attempts) == 1 and sleeps == []

# a timeout or connection error raises at once (no retry); the key is neither in the message nor in the chained error
for client, secret in ((t, KEY), (TMDB(TOKEN), TOKEN)):
    for error in (TimeoutError(f"read timed out: https://api.themoviedb.org/3/search/movie?api_key={KEY}&query=x"),
                  ConnectionError(f"Max retries exceeded with url: /3/search/movie?api_key={KEY} Bearer {TOKEN} ({secret})")):
        attempts.clear(); sleeps.clear()
        handler = answers(error, Resp(FAKE["search/movie"]))
        try: client.search("x"); raise SystemExit("chyba spojení nevyhodila výjimku")
        except tmdb_mod.TMDBError as ex:
            assert KEY not in str(ex) and secret not in str(ex) and type(error).__name__ in str(ex), str(ex)
            assert ex.__cause__ is None and ex.__suppress_context__, "řetězená výjimka by prozradila URL s klíčem"
        assert len(attempts) == 1 and sleeps == [], "timeout se neopakuje"
# an error body echoing the key is redacted too
def echo(url, params=None, headers=None, timeout=None):
    r = Resp({}, 404); r.text = f"bad api_key={KEY} / {KEY}"; return r
handler = echo
try: t.search("x"); raise SystemExit("404 nevyhodilo výjimku")
except tmdb_mod.TMDBError as ex: assert KEY not in str(ex) and "404" in str(ex), str(ex)
tmdb_mod.time, tmdb_mod._log = real_time, real_log
handler = fake_get
print("5. kolo: session, timeouty, 429 a ochrana klíče OK")
