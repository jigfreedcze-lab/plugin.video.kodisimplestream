"""Klient Webshare: timeouty, jedna session, chyby bez tracebacku, paralelní hledání v pořadí dotazů (podvržené requests).

Spuštění z kořene repozitáře: python tests/test_webshare_api.py
"""
import http.cookiejar
import os
import sys
import threading
import time
import types
import urllib.request

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)

# --- podvržené requests a xmltodict ---
class RequestException(Exception): pass
class Timeout(RequestException): pass
ConnectionError_ = type("ConnectionError", (RequestException,), {})

class Resp:
    def __init__(self, content, status_code=200): self.content, self.status_code = content, status_code

posts, sessions, answers = [], [], {}
lock = threading.Lock()
class Session:
    def __init__(self): sessions.append(self); self.mounted = []; self.cookies = http.cookiejar.CookieJar()
    def mount(self, prefix, adapter): self.mounted.append((prefix, adapter))
    def post(self, url, data=None, headers=None, timeout=None):
        endpoint = url.rsplit("/api/", 1)[1]
        with lock:
            posts.append((endpoint, dict(data), timeout, threading.current_thread() is threading.main_thread()))
        answer = answers[endpoint](data)
        if isinstance(answer, Exception):
            raise answer
        return answer

requests = types.ModuleType("requests")
requests.Session, requests.RequestException, requests.Timeout, requests.ConnectionError = Session, RequestException, Timeout, ConnectionError_
requests.adapters = types.SimpleNamespace(_preloaded_ssl_context=object())  # requests >= 2.32 sdílí kontext sám
sys.modules["requests"] = requests
xmltodict = types.ModuleType("xmltodict")
xmltodict.parse = lambda content: {"response": {"what": content.decode()}}
sys.modules["xmltodict"] = xmltodict

from resources.lib import webshare as ws

def xml(status="OK", **fields):
    return Resp(("<response><status>%s</status>%s</response>" % (
        status, "".join(f"<{k}>{v}</{k}>" for k, v in fields.items()))).encode())

def raises(fn, cls):
    try:
        fn()
    except cls as exc:
        return exc
    raise AssertionError(f"{cls.__name__} expected")

# 1. přihlášení: salt a login s timeoutem, jedna session pro všechny klienty procesu
answers["salt/"] = lambda d: xml(salt="abcdefgh")
answers["login/"] = lambda d: xml(token="T0K")
api = ws.WebshareAPI(); api.login("user", "heslo")
assert api.token == "T0K" and [p[0] for p in posts] == ["salt/", "login/"], posts
assert all(p[2] == ws.TIMEOUT == (3.05, 10) for p in posts), posts
assert ws.WebshareAPI()._session is api._session and len(sessions) == 1 and sessions[0].mounted == []
api.set_token("ULOZENY"); assert api.token == "ULOZENY"
# sdílená session cookie neukládá (souběžná vlákna by měnila jar, který requests prochází bez zámku)
def cookie_stored(jar):
    cookie = http.cookiejar.Cookie(0, "sid", "1", None, False, "webshare.cz", False, False, "/", False,
                                   True, None, False, None, None, {})
    jar.set_cookie_if_ok(cookie, urllib.request.Request("https://webshare.cz/api/search/"))
    return len(jar) > 0
assert not cookie_stored(sessions[0].cookies) and cookie_stored(http.cookiejar.CookieJar())

# 2. chyby přihlášení: zpráva Webshare pro uživatele, bez hashe hesla
answers["login/"] = lambda d: xml("FATAL", code="LOGIN_FATAL_1", message="Bad password")
exc = raises(lambda: api.login("user", "heslo"), ws.WebshareStatusError)
hashed = posts[-1][1]["password"]
assert "Bad password" in str(exc) and "LOGIN_FATAL_1" in str(exc) and hashed not in str(exc), exc
answers["login/"] = lambda d: xml()
assert not isinstance(raises(lambda: api.login("user", "heslo"), ws.WebshareError), ws.WebshareStatusError)
answers["salt/"] = lambda d: xml("FATAL", code="SALT_FATAL_1", message="User not found")
raises(lambda: api.login("nikdo", "x"), ws.WebshareStatusError)

# 3. síť: timeout, spojení, HTTP chyba a nečitelná odpověď → WebshareError s krátkou zprávou
for answer, text in ((Timeout("HTTPSConnectionPool(...): Read timed out."), "Webshare did not respond in time"),
                     (ConnectionError_("Max retries exceeded"), "Cannot connect to Webshare (ConnectionError)"),
                     (Resp(b"", 503), "Webshare request file_link/ failed with status code: 503"),
                     (Resp(b"<html"), "Invalid response from Webshare file_link/")):
    answers["file_link/"] = lambda d, answer=answer: answer
    exc = raises(lambda: api.get_download_link("ID"), ws.WebshareError)
    assert str(exc) == text and not isinstance(exc, ws.WebshareStatusError), exc

# 4. file_link: odkaz, OK bez odkazu → "", chybový stav (prošlý token, chybějící soubor) → WebshareStatusError bez tokenu
api.set_token("TAJNY")
answers["file_link/"] = lambda d: xml(link="https://dl/1")
assert api.get_download_link("ID") == "https://dl/1" and posts[-1][1] == {"ident": "ID", "wst": "TAJNY"} and posts[-1][2] == ws.TIMEOUT
answers["file_link/"] = lambda d: xml()
assert api.get_download_link("ID") == ""
answers["file_link/"] = lambda d: xml("FATAL", code="FILE_LINK_FATAL_1", message="File not found")
exc = raises(lambda: api.get_download_link("ID"), ws.WebshareStatusError); assert "TAJNY" not in str(exc), exc

# 5. hledání: bez tokenu, s timeoutem; chyba sítě → WebshareError
answers["search/"] = lambda d: Resp(d["what"])
posts.clear(); assert api.search("Dune", sort="")["response"]["what"] == "Dune"
endpoint, data, timeout, _ = posts[-1]
assert endpoint == "search/" and "wst" not in data and data["sort"] == "" and timeout == ws.TIMEOUT, posts
answers["search/"] = lambda d: Timeout("x")
raises(lambda: api.search("Dune"), ws.WebshareError)

# 6. paralelní hledání: nejvýš 4 najednou, jen ve vláknech, výsledky v pořadí dotazů i když první odpoví poslední;
#    chyba jednoho dotazu je výjimka na jeho místě
active, peak = [0], [0]
def slow(d):
    query = d["what"].decode()
    with lock:
        active[0] += 1; peak[0] = max(peak[0], active[0])
    time.sleep(0.15 if query == "q0" else 0.03)
    with lock:
        active[0] -= 1
    return Timeout("x") if query == "q3" else Resp(d["what"])
answers["search/"] = slow
queries = [f"q{i}" for i in range(7)]
posts.clear(); results = api.search_all(queries, sort="", limit=30)
assert [r if isinstance(r, Exception) else r["response"]["what"] for r in results][:3] == ["q0", "q1", "q2"], results
assert isinstance(results[3], ws.WebshareError) and [r["response"]["what"] for r in results[4:]] == ["q4", "q5", "q6"], results
assert 1 < peak[0] <= ws.MAX_PARALLEL_SEARCHES == 4, peak
assert len(posts) == 7 and not any(p[3] for p in posts) and all(p[2] == ws.TIMEOUT and p[1]["sort"] == "" for p in posts), posts
# jediný dotaz bez vláken, prázdný seznam bez požadavku
posts.clear(); assert api.search_all(["q1"])[0]["response"]["what"] == "q1" and posts[0][3] is True
assert api.search_all([]) == [] and len(posts) == 1

# 7. requests < 2.32 (bez předem načteného kontextu): session dostane adaptér se sdíleným SSL kontextem
ws._session = None; requests.adapters._preloaded_ssl_context = None
built = []; ws._shared_context_adapter = lambda: built.append(1) or "adapter"
session = ws.WebshareAPI()._session; ws.WebshareAPI()
assert session.mounted == [("https://", "adapter")] and built == [1], session.mounted

print("webshare klient: 7 skupin kontrol prošlo")
