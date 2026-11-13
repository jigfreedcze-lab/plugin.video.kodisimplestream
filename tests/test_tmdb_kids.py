import sys, types
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
calls = []


class Resp:
    def __init__(self, data, code=200): self._d, self.status_code, self.text = data, code, str(data)
    def json(self): return self._d


FAKE = {
    "search/movie": {"results": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]},
    "search/tv": {"results": []},
    "movie/1": {"id": 1, "release_dates": {"results": []}},
    "tv/2": {"id": 2, "content_ratings": {"results": []}},
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
    calls.append((path, dict(params or {})))
    return Resp(FAKE[path]) if path in FAKE else Resp({"status_message": "nope"}, 404)


handler = fake_get
from resources.lib.tmdb import TMDB, PLAYBACK_TIMEOUT

t = TMDB("0123456789abcdef0123456789abcdef")
res = t.search_raw("kocour", "movie", page=3)
assert [r["id"] for r in res] == [1, 2], res
assert calls[-1][0] == "search/movie" and calls[-1][1]["page"] == 3 and calls[-1][1]["query"] == "kocour"
assert calls[-1][1]["include_adult"] == "false"
assert t.search_raw("x", "tv") == [] and calls[-1][1]["page"] == 1
try: t.search_raw("x", "person"); raise SystemExit("missing kind check")
except ValueError: pass

assert t.details_with_ratings("movie", 1)["id"] == 1
assert calls[-1][0] == "movie/1" and calls[-1][1]["append_to_response"] == "release_dates"
assert t.details_with_ratings("tv", "2")["id"] == 2
assert calls[-1][0] == "tv/2" and calls[-1][1]["append_to_response"] == "content_ratings"
try: t.details_with_ratings("x", 1); raise SystemExit("missing kind check")
except ValueError: pass

try: t.details_with_ratings("movie", 99); raise SystemExit("missing HTTP error")
except Exception as ex: assert "404" in str(ex)

# details_extras: posters and translations in one request, with the language preference for posters
FAKE["movie/3"] = {"id": 3, "images": {"posters": []}, "translations": {"translations": []}}
FAKE["tv/4"] = {"id": 4}
extras = t.details_extras("movie", 3)
assert extras["id"] == 3
assert calls[-1][0] == "movie/3"
assert calls[-1][1]["append_to_response"] == "images,translations"
assert calls[-1][1]["include_image_language"] == "cs,sk,en,null"
assert t.details_extras("tv", "4")["id"] == 4 and calls[-1][0] == "tv/4"
try: t.details_extras("person", 1); raise SystemExit("missing kind check")
except ValueError: pass

# HTTP errors: 401 is an auth error, other 4xx a plain failure, a non-JSON answer raises as well
FAKE_CODES = {"movie/401": 401, "movie/500": 500}
_ok_get = handler


def coded_get(url, params=None, headers=None, timeout=None):
    path = url.split("/3/", 1)[1]
    if path in FAKE_CODES:
        return Resp({"status_message": "x"}, FAKE_CODES[path])
    if path == "movie/empty":
        return Resp(None)
    if path == "movie/notjson":
        class Bad(Resp):
            def json(self): raise ValueError("not json")
        return Bad("<html>")
    return _ok_get(url, params, headers, timeout)


handler = coded_get
from resources.lib.tmdb import TMDBAuthError
try: t.details_extras("movie", 401); raise SystemExit("missing auth error")
except TMDBAuthError: pass
try: t.details_extras("movie", 500); raise SystemExit("missing HTTP error")
except TMDBAuthError: raise SystemExit("500 must not be an auth error")
except Exception as ex: assert "500" in str(ex)
try: t.details_with_ratings("movie", 401); raise SystemExit("missing auth error")
except TMDBAuthError: pass
try: t.details_extras("movie", "notjson"); raise SystemExit("non-JSON answer must raise")
except ValueError: pass
assert t.details_extras("movie", "empty") is None  # an empty body is passed on; kids.build tolerates it
handler = _ok_get

# the per-call timeout of the playback check reaches the session, the default one stays (connect, read)
seen = []
def spy(url, params=None, headers=None, timeout=None):
    seen.append(timeout); return _ok_get(url, params, headers, timeout)
handler = spy
FAKE["find/tt7"] = {"movie_results": [{"id": 1}], "tv_results": [], "tv_episode_results": []}
t.details_with_ratings("movie", 1); assert seen[-1] == (3.05, 8), seen
t.details_with_ratings("movie", 1, timeout=PLAYBACK_TIMEOUT); assert seen[-1] == (3.05, 6), seen
assert t.find_by_imdb("tt7", "movie", timeout=PLAYBACK_TIMEOUT) == 1 and seen[-1] == (3.05, 6), seen
assert len(FakeSession.created) == 1, "one shared session"
handler = _ok_get
print("all kids TMDb checks passed")
