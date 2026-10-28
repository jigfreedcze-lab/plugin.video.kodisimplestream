import requests
import hashlib
import http.cookiejar
import xmltodict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Union
from xml.etree import ElementTree
import json

from resources.lib.md5crypt import md5crypt

# (connect, read) seconds – a stuck connection must not block the plugin and the TMDb Helper player
TIMEOUT = (3.05, 10)
# Webshare answered HTTP 403 at ~16 requests/s, keep the parallel searches few
MAX_PARALLEL_SEARCHES = 4


class WebshareError(Exception):
    """Webshare request failed: no connection, timeout, HTTP error or an invalid response."""


class WebshareStatusError(WebshareError):
    """Webshare answered, but with an error status (wrong login, expired token, missing file…).
    message and code are Webshare's own, e.g. "File temporarily unavailable." and FILE_LINK_FATAL_4."""

    def __init__(self, text: str, message: str = "", code: str = ""):
        super().__init__(text)
        self.message = message
        self.code = code


_session = None

def _shared_context_adapter():
    """
    HTTPAdapter whose connections share one SSL context with the CA bundle loaded once.
    requests < 2.32 loads the bundle again for every new connection (~0.3 s with OpenSSL 3).
    Defined lazily, the tests replace requests with a bare module.
    """
    from requests.adapters import HTTPAdapter
    from requests.certs import where
    from urllib3.util.ssl_ import create_urllib3_context

    # The same context as requests >= 2.32 preloads
    context = create_urllib3_context()
    context.load_verify_locations(where())

    class SharedContextAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = context
            super().init_poolmanager(*args, **kwargs)

        def cert_verify(self, conn, url, verify, cert):
            super().cert_verify(conn, url, verify, cert)
            # The bundle is in the shared context already – urllib3 would load it again per connection.
            # Pools of a proxy manager do not use the context, those keep the bundle path.
            if verify is True and getattr(conn, "conn_kw", {}).get("ssl_context") is context:
                conn.ca_certs = None
                conn.ca_cert_dir = None

    return SharedContextAdapter()

def shared_session():
    """
    One session per process. Webshare answers "Connection: close", so keep-alive does not help,
    but the connections share the SSL context instead of loading the CA bundle each time.
    """
    global _session
    if _session is None:
        session = requests.Session()
        # The API needs no cookies (the token goes in the POST body). Never storing one keeps the jar
        # unchanged, so the parallel searches can share the session (requests iterates it unlocked).
        session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        # Some requests 2.32.x releases share a preloaded context themselves
        if getattr(requests.adapters, "_preloaded_ssl_context", None) is None:
            session.mount("https://", _shared_context_adapter())
        _session = session
    return _session


class WebshareAPI:
    """
    Webshare API class
    https://webshare.cz/apidoc/
    """

    def __init__(self):
        self._base_url = "https://webshare.cz/api/"
        self._headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
        self._token = ""
        self._session = shared_session()

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str) -> None:
        """Uses a token from an earlier login (e.g. cached by the caller) instead of logging in."""
        self._token = token

    def _post(self, endpoint: str, data: Dict[str, Any]) -> bytes:
        """POSTs to the API with a timeout, network and HTTP errors raise WebshareError."""
        try:
            response = self._session.post(self._base_url + endpoint, data=data, headers=self._headers, timeout=TIMEOUT)
        except requests.Timeout as exc:
            raise WebshareError("Webshare did not respond in time") from exc
        except requests.RequestException as exc:
            raise WebshareError(f"Cannot connect to Webshare ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise WebshareError(f"Webshare request {endpoint} failed with status code: {response.status_code}")
        return response.content

    def _post_xml(self, endpoint: str, data: Dict[str, Any]) -> ElementTree.Element:
        """POSTs to the API and returns the XML answer, an error status raises WebshareStatusError."""
        try:
            root = ElementTree.fromstring(self._post(endpoint, data))
        except ElementTree.ParseError as exc:
            raise WebshareError(f"Invalid response from Webshare {endpoint}") from exc
        if root.findtext('status') != 'OK':
            message, code = (root.findtext('message') or '').strip(), (root.findtext('code') or '').strip()
            raise WebshareStatusError('Webshare {} returned {}: {} ({})'.format(
                endpoint, root.findtext('status'), message, code), message, code)
        return root

    def login(self, user_name, password):
        """Logs {user_name} in Webshare API"""
        salt = self.get_salt(user_name)
        password = self.hash_password(password, salt)
        data = {
                'username_or_email' : user_name,
                'password' : password,
                'keep_logged_in' : 1
                }
        token = self._post_xml('login/', data).findtext('token')
        if not token:
            raise WebshareError("Webshare returned an empty token – check credentials.")
        self._token = token

    def hash_password(self, password, salt):
        """Creates password hash used by Webshare API"""
        return hashlib.sha1(md5crypt(password, salt).encode('utf-8')).hexdigest()

    def get_salt(self, user_name):
        """Retrieves salt for password hash from webshare.cz"""
        return self._post_xml('salt/', {'username_or_email' : user_name}).findtext('salt')

    def get_download_link(self, file_id) -> str:
        """Query actual download link from {file_id}, returning empty string if no link is found.
        An error status (missing file, expired token…) raises WebshareStatusError."""
        root = self._post_xml('file_link/', {'ident' : file_id, 'wst' : self._token})
        return root.findtext('link') or ''

    def search(self, query: str, limit: int = 30, offset: int = 0, sort: str = 'rating', category: str = 'video'):
        """Search for videos on webshare.cz, no login needed
        query: str - search query
        limit: int - number of results to return
        offset: int - number of results to skip
        sort: str - sort order (recent, rating, largest, smallest)
        category: str - category (video, images, audio, docs, archives)
        """
        data = {'what' : query.encode('utf-8') ,'sort' : sort, 'limit' : limit, 'offset' : offset, 'category' : category}
        content = self._post('search/', data)

        try:
            json_response = xmltodict.parse(content)
            if not json_response or 'response' not in json_response:
                raise Exception("Invalid response format from server")
            return json_response
        except Exception as e:
            raise WebshareError(f"Failed to parse search response: {str(e)}")

    def search_all(self, queries: List[str], **kwargs) -> List[Union[Dict[str, Any], Exception]]:
        """Runs search() for every query, at most MAX_PARALLEL_SEARCHES at once (HTTP only, no GUI calls).
        Returns the responses in the order of {queries}, a failed query gives its exception instead."""
        def run(query):
            try:
                return self.search(query, **kwargs)
            except Exception as exc:
                return exc

        if len(queries) <= 1:
            return [run(query) for query in queries]
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_SEARCHES, len(queries))) as pool:
            # map() keeps the order of the queries, not the order of the answers
            return list(pool.map(run, queries))


if __name__ == "__main__":
    # For testing purposes
    webshare = WebshareAPI()
    webshare.login("test", "test")
    json_search = webshare.search("iron", 5)
    print(json.dumps(json_search, indent=4))
    print(webshare.get_download_link(json_search['response']['file'][0]['ident']))
