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
def fake_get(url, params=None, headers=None, timeout=None):
    path = url.split("/3/", 1)[1]
    calls.append((path, dict(params or {}), dict(headers or {})))
    return Resp(FAKE[path]) if path in FAKE else Resp({"status_message": "nope"}, 404)
requests.get = fake_get
from resources.lib.tmdb import TMDB

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
real_get = requests.get
requests.get = lambda *a, **k: Resp({"status_code": 7}, 401)
try: t.search("x"); raise SystemExit("401 nevyhodilo TMDBAuthError")
except TMDBAuthError: pass
requests.get = real_get
print("2. kolo: dalších 8 kontrol prošlo")
