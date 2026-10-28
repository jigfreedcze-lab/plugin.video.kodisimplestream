# -*- coding: utf-8 -*-
"""Builds the benchmark data: python -X utf8 tools/benchmark/build_benchmark.py [--repo <repo>] {tmdb|fetch|finalize|all}

tmdb      - case metadata from TMDb (resources/lib/tmdb.py of the repo) -> cases_meta.json
fetch     - Webshare results for all query variants -> cache/<id>.json (resumable)
finalize  - excluded.json, pool/<id>.json, split, cases.json

The TMDb API key is read from the Kodi add-on settings at runtime and never printed or stored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import types
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
# Webshare snapshot (private repository, see README.md); cases.json is public and stays next to this script
BENCH = os.environ.get("KSS_BENCH_DATA") or os.path.join(os.path.dirname(REPO_ROOT), "KodiSimpleStream-benchmark")
SETTINGS = os.path.join(os.environ.get("APPDATA", ""), "Kodi", "userdata", "addon_data",
                        "plugin.video.kodisimplestream", "settings.xml")
WS_URL = "https://webshare.cz/api/search/"
PAGE = 30
PAUSE = 0.3
HOLDOUT_SHARE = 0.3

# (id, category, TMDb search query, year)
MOVIES = [
    ("vratne_lahve", "cz_movie", "Vratné lahve", 2007),
    ("kolja", "cz_movie", "Kolja", 1996),
    ("samotari", "cz_movie", "Samotáři", 2000),
    ("kulovy_blesk", "cz_movie", "Kulový blesk", 1978),
    ("baba_z_ledu", "cz_movie", "Bába z ledu", 2017),
    ("shawshank", "foreign_cs_title", "The Shawshank Redemption", 1994),
    ("kukacci_hnizdo", "foreign_cs_title", "One Flew Over the Cuckoo's Nest", 1975),
    ("zelena_mile", "foreign_cs_title", "The Green Mile", 1999),
    ("mlceni_jehnatek", "foreign_cs_title", "The Silence of the Lambs", 1991),
    ("nedotknutelni", "foreign_cs_title", "Intouchables", 2011),
    ("tenkrat_na_zapade", "foreign_cs_title", "Once Upon a Time in the West", 1968),
    ("cesta_do_fantazie", "non_latin_movie", "Spirited Away", 2001),
    ("parazit", "non_latin_movie", "Parasite", 2019),
    ("your_name", "non_latin_movie", "Your Name.", 2016),
    ("vlak_do_pusanu", "non_latin_movie", "Train to Busan", 2016),
    ("sedm_samuraju", "non_latin_movie", "Seven Samurai", 1954),
    ("moskva_slzam", "non_latin_movie", "Moscow Does Not Believe in Tears", 1980),
    ("duna_1984", "sequel_remake", "Dune", 1984),
    ("duna_2021", "sequel_remake", "Dune", 2021),
    ("lvi_kral_1994", "sequel_remake", "The Lion King", 1994),
    ("lvi_kral_2019", "sequel_remake", "The Lion King", 2019),
    ("matrix_1999", "sequel_remake", "The Matrix", 1999),
    ("andel_pane_2", "sequel_remake", "Anděl Páně 2", 2016),
    ("slunce_seno_jahody", "sequel_remake", "Slunce, seno, jahody", 1984),
    ("sam_doma", "sequel_remake", "Home Alone", 1990),
    ("up", "short_title", "Up", 2009),
    ("her", "short_title", "Her", 2013),
    ("joker_2019", "short_title", "Joker", 2019),
    ("it_2017", "short_title", "It", 2017),
    ("se7en", "short_title", "Se7en", 1995),
    ("us_2019", "short_title", "Us", 2019),
    ("lotr_fellowship", "long_subtitle", "The Lord of the Rings: The Fellowship of the Ring", 2001),
    ("pirates_black_pearl", "long_subtitle", "Pirates of the Caribbean: The Curse of the Black Pearl", 2003),
    ("mad_max_fury_road", "long_subtitle", "Mad Max: Fury Road", 2015),
    ("spiderman_nwh", "long_subtitle", "Spider-Man: No Way Home", 2021),
    ("terminator2", "long_subtitle", "Terminator 2: Judgment Day", 1991),
]

# TMDb search does not find these reliably (specials, making-of, other titles come first)
FIXED_IDS = {
    "cesta_do_fantazie": "movie:129",
    "parazit": "movie:496243",
    "your_name": "movie:372058",
    "attack_on_titan_s01e01": "tv:1429",
}

# (id, category, TMDb search query, first air year, season, episode)
EPISODES = [
    ("got_s03e09", "episode_foreign_cs", "Game of Thrones", 2011, 3, 9),
    ("breaking_bad_s05e14", "episode_foreign_cs", "Breaking Bad", 2008, 5, 14),
    ("friends_s02e14", "episode_foreign_cs", "Friends", 1994, 2, 14),
    ("tbbt_s03e05", "episode_foreign_cs", "The Big Bang Theory", 2007, 3, 5),
    ("black_mirror_s03e04", "episode_foreign_cs", "Black Mirror", 2011, 3, 4),
    ("rings_of_power_s01e01", "episode_foreign_cs", "The Lord of the Rings: The Rings of Power", 2022, 1, 1),
    ("house_s04e16", "episode_foreign_cs", "House", 2004, 4, 16),
    ("stranger_things_s04e04", "episode_same_name", "Stranger Things", 2016, 4, 4),
    ("last_of_us_s01e03", "episode_same_name", "The Last of Us", 2023, 1, 3),
    ("mandalorian_s01e03", "episode_same_name", "The Mandalorian", 2019, 1, 3),
    ("dark_s01e01", "episode_other_lang", "Dark", 2017, 1, 1),
    ("money_heist_s01e01", "episode_other_lang", "La casa de papel", 2017, 1, 1),
    ("lupin_s01e01", "episode_other_lang", "Lupin", 2021, 1, 1),
    ("most_s01e01", "episode_czech", "Most!", 2019, 1, 1),
    ("vypravej_s01e01", "episode_czech", "Vyprávěj", 2009, 1, 1),
    ("okresni_prebor_s01e03", "episode_czech", "Okresní přebor", 2010, 1, 3),
    ("arabela_s01e01", "episode_czech", "Arabela", 1979, 1, 1),
    ("navstevnici_s01e02", "episode_czech", "Návštěvníci", 1983, 1, 2),
    ("pripady_1_oddeleni_s01e05", "episode_czech", "Případy 1. oddělení", 2014, 1, 5),
    ("kancelar_blanik_s01e01", "episode_czech", "Kancelář Blaník", 2014, 1, 1),
    ("squid_game_s01e01", "episode_non_latin", "Squid Game", 2021, 1, 1),
    ("squid_game_s02e03", "episode_non_latin", "Squid Game", 2021, 2, 3),
    ("attack_on_titan_s01e01", "episode_non_latin", "Attack on Titan", 2013, 1, 1),
    ("alice_borderland_s01e01", "episode_non_latin", "Alice in Borderland", 2020, 1, 1),
]


def jload(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def jdump(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def strip_diacritics(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    return unicodedata.normalize("NFC", "".join(ch for ch in text if unicodedata.category(ch) != "Mn"))


def is_latin(text: str) -> bool:
    return all(unicodedata.name(ch, "").startswith("LATIN") for ch in text if ch.isalpha())


def colon_prefix(text: str) -> str:
    return text.split(":", 1)[0].strip() if text and ":" in text else ""


def read_api_key() -> str:
    root = ET.parse(SETTINGS).getroot()
    for node in root.iter("setting"):
        if node.get("id") == "tmdb_api_key":
            return (node.text or node.get("value") or "").strip()
    return ""


class _Response:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


def _requests_get(url, params=None, headers=None, timeout=None):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(full, headers=dict(headers or {}))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout or 15) as resp:
                return _Response(resp.status, resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                time.sleep(2 + attempt * 2)
                continue
            return _Response(exc.code, exc.read().decode("utf-8", "replace"))
        except Exception as exc:
            # The message may contain the URL with the API key - never pass it on
            if attempt == 3:
                raise RuntimeError(f"TMDb request failed ({type(exc).__name__})") from None
            time.sleep(1 + attempt)
    raise RuntimeError("TMDb request failed")


def install_requests_stub() -> None:
    module = types.ModuleType("requests")
    module.get = _requests_get
    sys.modules["requests"] = module


def import_repo(repo: str):
    sys.path.insert(0, os.path.abspath(repo))
    install_requests_stub()
    from resources.lib import matching  # noqa: E402
    from resources.lib import tmdb  # noqa: E402
    return matching, tmdb


def pick(results: List[Dict], year: int, kind_label: str, query: str) -> Dict:
    for tolerance in (0, 1):
        for item in results:
            if item.get("year") and abs(int(item["year"]) - year) <= tolerance:
                return item
    raise RuntimeError(f"No TMDb {kind_label} result for {query!r} ({year})")


def stage_tmdb(repo: str) -> None:
    _, tmdb_module = import_repo(repo)
    key = read_api_key()
    if not key:
        raise SystemExit("TMDb API key not found in Kodi settings")
    client = tmdb_module.TMDB(key)
    del key
    cases = []

    for cid, category, query, year in MOVIES:
        full_id = FIXED_IDS.get(cid) or pick(client.search(query, type="movie"), year, "movie", query)["id"]
        details = client.get_detail(full_id)
        raw = client._details[full_id]
        # English translations of English originals have an empty title
        english = client._english_title(raw) or (raw.get("original_title") if raw.get("original_language") == "en" else "")
        movie_year = details.get("year") or ""
        meta = {
            "tmdb_id": full_id,
            "cs": raw.get("title") or "",
            "original": raw.get("original_title") or "",
            "original_language": raw.get("original_language") or "",
            "english": english,
            "year": movie_year,
            "imdb_id": raw.get("imdb_id") or "",
            "addon_title": details["title"],
            "addon_original_title": details.get("original_title") or "",
        }
        match = {
            "mediatype": "movie",
            "title": details["title"],
            "originaltitle": details.get("original_title") or "",
            "year": movie_year or "",
        }
        tmdbh = {
            "mediatype": "movie",
            "title": meta["cs"],
            "originaltitle": meta["original"],
            "year": movie_year,
            "imdb_id": meta["imdb_id"],
            "tmdb_id": full_id.split(":", 1)[1],
        }
        cases.append({"id": cid, "type": "movie", "category": category, "metadata": meta,
                      "match": match, "tmdbh_params": tmdbh})
        print(f"{cid:28} {full_id:14} {meta['cs']} | {meta['original']} | {english} | {movie_year}"
              f"  -> addon: {details['title']} | {details.get('original_title')}")

    for cid, category, query, year, season, episode in EPISODES:
        full_id = FIXED_IDS.get(cid) or pick(client.search(query, type="series"), year, "series", query)["id"]
        details = client.get_detail(full_id)
        raw = client._details[full_id]
        english = client._english_title(raw) or (raw.get("original_name") if raw.get("original_language") == "en" else "")
        tv_id = full_id.split(":", 1)[1]
        cs_eps = {e["number"]: e for e in client.get_episodes(full_id, str(season))}
        en_season = client._get(f"tv/{tv_id}/season/{season}", language="en-US")
        en_eps = {e.get("episode_number"): e for e in en_season.get("episodes", [])}
        if episode not in cs_eps:
            raise RuntimeError(f"{cid}: episode {season}x{episode} not on TMDb")
        ep_cs = cs_eps[episode]
        ep_en = en_eps.get(episode, {})
        air_date = ep_en.get("air_date") or ""
        meta = {
            "tmdb_id": full_id,
            "show_cs": raw.get("name") or "",
            "show_original": raw.get("original_name") or "",
            "original_language": raw.get("original_language") or "",
            "show_english": english,
            "show_year": (raw.get("first_air_date") or "")[:4],
            "season": season,
            "episode": episode,
            "episode_title": ep_cs["title"],
            "episode_title_en": ep_en.get("name") or "",
            "air_date": air_date,
            "addon_title": details["title"],
            "addon_original_title": details.get("original_title") or "",
        }
        match = {
            "mediatype": "episode",
            "showname": details["title"],
            "show_originaltitle": details.get("original_title") or "",
            "season": ep_cs.get("season") or 0,
            "episode": ep_cs.get("number") or 0,
            "episode_title": ep_cs.get("title") or "",
        }
        tmdbh = {
            "mediatype": "episode",
            "showname": meta["show_cs"],
            "tvshowtitle": meta["show_cs"],
            "show_originaltitle": meta["show_original"],
            "season": str(season),
            "episode": str(episode),
            "episode_title": ep_cs["title"],
            "aired": air_date,
            "year": air_date[:4],
            "imdb_id": "",
            "tmdb_id": tv_id,
        }
        cases.append({"id": cid, "type": "episode", "category": category, "metadata": meta,
                      "match": match, "tmdbh_params": tmdbh})
        print(f"{cid:28} {full_id:12} {meta['show_cs']} | {meta['show_original']} | {english} | "
              f"S{season:02d}E{episode:02d} {ep_cs['title']} / {meta['episode_title_en']}"
              f"  -> addon: {details['title']} | {details.get('original_title')}")

    jdump(os.path.join(BENCH, "cases_meta.json"), cases)
    print(f"{len(cases)} cases written")


def flow_a_queries(match: Dict[str, Any]) -> List[str]:
    if match["mediatype"] == "episode":
        tag = f"S{int(match['season']):02d}E{int(match['episode']):02d}"
        queries = [f"{match['showname']} {tag}"]
        if match["show_originaltitle"] and match["show_originaltitle"] != match["showname"]:
            queries.append(f"{match['show_originaltitle']} {tag}")
        return queries
    year = match.get("year")
    queries = [f"{match['title']} {year}" if year else match["title"]]
    if match["originaltitle"] and match["originaltitle"] != match["title"]:
        queries.append(match["originaltitle"])
    return queries


def variant_queries(case: Dict[str, Any], matching) -> List[str]:
    meta = case["metadata"]
    queries: List[str] = list(flow_a_queries(case["match"]))
    queries += matching.build_tmdbh_queries(case["tmdbh_params"])

    if case["type"] == "movie":
        year = meta["year"]
        names = [meta["cs"], meta["original"], meta["english"], meta["addon_title"], meta["addon_original_title"]]
        extra = [colon_prefix(meta["cs"]), colon_prefix(meta["english"]), colon_prefix(meta["original"]),
                 strip_diacritics(meta["cs"]), strip_diacritics(meta["original"])]
        for name in names + extra:
            if name:
                if year:
                    queries.append(f"{name} {year}")
                queries.append(name)
    else:
        season, episode = meta["season"], meta["episode"]
        tags = [f"S{season:02d}E{episode:02d}", f"{season}x{episode:02d}", f"S{season:02d} E{episode:02d}"]
        names = [meta["show_cs"], meta["show_original"], meta["show_english"]]
        for name in names:
            if name:
                for tag in tags:
                    queries.append(f"{name} {tag}")
                if meta["episode_title"]:
                    queries.append(f"{name} {meta['episode_title']}")
        for name in (meta["show_english"], meta["show_original"]):
            if name and meta["episode_title_en"]:
                queries.append(f"{name} {meta['episode_title_en']}")
        for name in (strip_diacritics(meta["show_cs"]), colon_prefix(meta["show_cs"]), colon_prefix(meta["show_english"])):
            if name:
                queries.append(f"{name} {tags[0]}")

    result: List[str] = []
    for query in queries:
        query = " ".join(query.split())
        if query and query not in result:
            result.append(query)
    return result


def ws_search(query: str, offset: int) -> Dict[str, Any]:
    data = urllib.parse.urlencode({"what": query, "category": "video", "limit": PAGE,
                                   "offset": offset, "sort": ""}).encode("utf-8")
    request = urllib.request.Request(WS_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    last_error = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = resp.read()
            root = ET.fromstring(body)
            files = []
            for node in root.findall("file"):
                files.append({
                    "ident": node.findtext("ident") or "",
                    "name": node.findtext("name") or "",
                    "size": int(node.findtext("size") or 0),
                    "type": node.findtext("type") or "",
                    "positive_votes": int(node.findtext("positive_votes") or 0),
                    "negative_votes": int(node.findtext("negative_votes") or 0),
                })
            return {"status": root.findtext("status") or "", "total": int(root.findtext("total") or 0),
                    "files": files}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2 + attempt * 3)
    return {"status": "ERROR", "error": last_error, "total": 0, "files": []}


def stage_fetch(repo: str) -> None:
    matching, _ = import_repo(repo)
    cases = jload(os.path.join(BENCH, "cases_meta.json"))
    for index, case in enumerate(cases, 1):
        path = os.path.join(BENCH, "cache", f"{case['id']}.json")
        cache = jload(path) if os.path.exists(path) else {"id": case["id"], "sort": "", "limit": PAGE, "queries": {}}
        jobs = [(q, 0) for q in variant_queries(case, matching)]
        jobs += [(q, PAGE) for q in flow_a_queries(case["match"])]
        new = 0
        for query, offset in jobs:
            pages = cache["queries"].setdefault(query, {})
            if str(offset) in pages and pages[str(offset)].get("status") != "ERROR":
                continue
            pages[str(offset)] = ws_search(query, offset)
            new += 1
            time.sleep(PAUSE)
        jdump(path, cache)
        counts = ", ".join(f"{len(p['0']['files'])}" for p in cache["queries"].values() if "0" in p)
        print(f"[{index}/{len(cases)}] {case['id']}: {len(jobs)} requests ({new} new) -> {counts}", flush=True)


def stage_finalize() -> None:
    cases = jload(os.path.join(BENCH, "cases_meta.json"))
    kept, excluded = [], []
    for case in cases:
        meta = case["metadata"]
        cache = jload(os.path.join(BENCH, "cache", f"{case['id']}.json"))["queries"]
        errors = [q for q, p in cache.items() for page in p.values() if page.get("status") == "ERROR"]
        if errors:
            raise SystemExit(f"{case['id']}: failed requests, run fetch again: {errors[:3]}")
        if case["type"] == "movie":
            cs_names = [meta["cs"]]
            orig_names = [meta["original"], meta["addon_original_title"]]
        else:
            cs_names = [meta["show_cs"]]
            orig_names = [meta["show_original"], meta["addon_original_title"]]

        def hits(names: List[str]) -> int:
            total = 0
            for query, pages in cache.items():
                if any(name and (query == name or query.startswith(name + " ")) for name in names):
                    total += len(pages.get("0", {}).get("files", []))
            return total

        if hits(cs_names) == 0 and hits(orig_names) == 0:
            excluded.append({"id": case["id"], "category": case["category"],
                             "reason": "Webshare returns 0 results for the Czech and the original title (blocked?)"})
            continue

        pool: Dict[str, Dict[str, Any]] = {}
        for pages in cache.values():
            for page in pages.values():
                for f in page["files"]:
                    if f["ident"] and f["ident"] not in pool:
                        pool[f["ident"]] = {"ident": f["ident"], "name": f["name"], "size": f["size"]}
        files = sorted(pool.values(), key=lambda f: (f["name"].casefold(), f["ident"]))
        jdump(os.path.join(BENCH, "pool", f"{case['id']}.json"), {"id": case["id"], "count": len(files), "files": files})
        case["pool_size"] = len(files)
        kept.append(case)

    by_category: Dict[str, List[Dict]] = {}
    for case in kept:
        by_category.setdefault(case["category"], []).append(case)
    for members in by_category.values():
        members.sort(key=lambda c: hashlib.sha1(c["id"].encode("utf-8")).hexdigest())
        holdout = int(len(members) * HOLDOUT_SHARE + 0.5)
        for position, case in enumerate(members):
            case["split"] = "holdout" if position < holdout else "train"

    ordered = [{key: case[key] for key in ("id", "type", "category", "split", "metadata", "match", "tmdbh_params", "pool_size")}
               for case in kept]
    jdump(os.path.join(HERE, "cases.json"), ordered)
    jdump(os.path.join(BENCH, "excluded.json"), excluded)
    train = sum(1 for c in ordered if c["split"] == "train")
    print(f"kept {len(ordered)} (train {train}, holdout {len(ordered) - train}), excluded {len(excluded)}")
    for item in excluded:
        print("excluded:", item["id"], "-", item["reason"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=REPO_ROOT)
    parser.add_argument("stage", choices=["tmdb", "fetch", "finalize", "all"])
    args = parser.parse_args()
    if args.stage in ("tmdb", "all"):
        stage_tmdb(args.repo)
    if args.stage in ("fetch", "all"):
        stage_fetch(args.repo)
    if args.stage in ("finalize", "all"):
        stage_finalize()


if __name__ == "__main__":
    main()
