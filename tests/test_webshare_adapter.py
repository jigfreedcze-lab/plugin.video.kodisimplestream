"""Sdílený SSL kontext pro requests < 2.32 se skutečnými requests/urllib3 (bez sítě); bez nich se přeskočí.

Spuštění z kořene repozitáře: python tests/test_webshare_adapter.py
"""
import http.cookiejar
import os
import ssl
import sys
import types
import urllib.request

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.certs import where
except ImportError:
    print("webshare adaptér: přeskočeno, requests/urllib3 nejsou nainstalované")
    sys.exit(0)
try:
    import xmltodict  # noqa: F401
except ImportError:  # adaptér ho nepotřebuje, webshare.py ho jen importuje
    sys.modules["xmltodict"] = types.ModuleType("xmltodict")

from resources.lib import webshare as ws

URL = "https://webshare.cz/api/search/"

# 1. pool manager adaptéru dostane sdílený kontext s ověřováním certifikátu a načteným CA bundlem
adapter = ws._shared_context_adapter()
context = adapter.poolmanager.connection_pool_kw["ssl_context"]
assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED, context
# (jméno serveru kontroluje kontext v urllib3 2, v urllib3 1.26 urllib3 sám po handshaku)
assert context.cert_store_stats()["x509_ca"] > 0, context.cert_store_stats()

# 2. pool se sdíleným kontextem bundle znovu nenačítá, ale ověřování zůstává zapnuté
pool = adapter.poolmanager.connection_from_url(URL)
assert pool.conn_kw.get("ssl_context") is context, pool.conn_kw
adapter.cert_verify(pool, URL, True, None)
assert pool.ca_certs is None and pool.ca_cert_dir is None and pool.cert_reqs == "CERT_REQUIRED", vars(pool)

# 3. vlastní bundle (verify=cesta) i pool proxy (bez kontextu) se chovají jako u běžného HTTPAdapter
def verified(adapter_, pool_, verify):
    adapter_.cert_verify(pool_, URL, verify, None)
    return pool_.ca_certs, pool_.ca_cert_dir, pool_.cert_reqs
base = HTTPAdapter()
assert verified(adapter, adapter.poolmanager.connection_from_url(URL), where()) == \
       verified(base, base.poolmanager.connection_from_url(URL), where())
proxy_pool = adapter.proxy_manager_for("http://proxy.invalid:3128").connection_from_url(URL)
assert proxy_pool.conn_kw.get("ssl_context") is not context, proxy_pool.conn_kw
base_proxy_pool = base.proxy_manager_for("http://proxy.invalid:3128").connection_from_url(URL)
assert verified(adapter, proxy_pool, True) == verified(base, base_proxy_pool, True)

# 4. sdílená session: adaptér jen bez předem načteného kontextu (requests < 2.32), cookie neukládá
ws._session = None
session = ws.shared_session()
preloaded = getattr(requests.adapters, "_preloaded_ssl_context", None) is not None
assert isinstance(session.get_adapter(URL), HTTPAdapter)
assert (type(session.get_adapter(URL)).__name__ == "SharedContextAdapter") is not preloaded
cookie = http.cookiejar.Cookie(0, "sid", "1", None, False, "webshare.cz", False, False, "/", False,
                               True, None, False, None, None, {})
session.cookies.set_cookie_if_ok(cookie, urllib.request.Request(URL))
assert len(session.cookies) == 0, list(session.cookies)

print(f"webshare adaptér: 4 skupiny kontrol prošlo (requests {requests.__version__})")
