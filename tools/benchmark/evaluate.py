# -*- coding: utf-8 -*-
"""Offline evaluation of the Webshare search ranking of plugin.video.kodisimplestream.

python -X utf8 tools/benchmark/evaluate.py [--data <snapshot>] [--repo <repo>] [--split train|holdout|all]
       [--flow a|b|both] [--labels labels_audited.json] [--json out.json] [--per-case]
       [--public-json results/<name>.json] [--compare results/<name>.json]

Flow a: TMDb search inside the add-on (handle_tmdb_selection / list_episodes -> list_search_results).
        Uses matching.build_search_queries(match) and matching.rank_files(results_per_query, match, preference)
        from --repo when both exist, otherwise a copy of the current add-on logic.
Flow b: TMDb Helper (tmdbh_play -> search_and_score_tmdbh) with matching.build_tmdbh_queries.
Webshare answers come from <data>/cache/<id>.json only, a query missing there counts as an empty result.
The snapshot with file names is private (--data or KSS_BENCH_DATA, default ../KodiSimpleStream-benchmark next
to the repository). --public-json writes results without file names and idents, those go to results/.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
# The Webshare snapshot (cache, pools, labels) lives in a private repository, see README.md
DATA = os.environ.get("KSS_BENCH_DATA") or os.path.join(os.path.dirname(REPO_ROOT), "KodiSimpleStream-benchmark")
PAGE_SIZE = 30
METRICS = ("SCORE", "Top1", "P@5", "MRR", "R@10", "Hit@10", "queries")
QUALITY_PREF_SETTINGS = ("none", "1080p_or_best", "720p_or_best", "highest")


def jload(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


class Repo:
    """Modules of the add-on working copy given by --repo."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not os.path.isfile(os.path.join(self.path, "resources", "lib", "matching.py")):
            raise SystemExit(f"{self.path} is not a KodiSimpleStream working copy (resources/lib/matching.py missing)")
        for name in list(sys.modules):
            if name == "resources" or name.startswith("resources."):
                del sys.modules[name]
        sys.path.insert(0, self.path)
        self.matching = importlib.import_module("resources.lib.matching")
        self.source_ui = importlib.import_module("resources.lib.source_ui")
        for module in (self.matching, self.source_ui):
            if not os.path.abspath(module.__file__).startswith(self.path):
                raise SystemExit(f"{module.__name__} was imported from {module.__file__}, not from {self.path}")
        self.custom_flow_a = all(callable(getattr(self.matching, name, None))
                                 for name in ("build_search_queries", "rank_files"))
        self.lang_pref_bonus = self._addon_constant("LANG_PREF_BONUS", 15)

    def _addon_constant(self, name: str, default: int) -> int:
        if isinstance(getattr(self.matching, name, None), int):
            return getattr(self.matching, name)
        main = os.path.join(self.path, "kodisimplestream.py")
        if os.path.isfile(main):
            with open(main, encoding="utf-8") as fh:
                found = re.search(rf"^{name}\s*=\s*(\d+)", fh.read(), re.MULTILINE)
            if found:
                return int(found.group(1))
        return default


class Cache:
    """Webshare answers of one case, looked up by the exact query (whitespace collapsed)."""

    def __init__(self, case_id: str):
        path = os.path.join(DATA, "cache", f"{case_id}.json")
        self.case_id = case_id
        self.queries: Dict[str, Dict[str, Any]] = jload(path)["queries"] if os.path.exists(path) else {}
        self.folded = {key.casefold(): key for key in self.queries}
        self.misses: List[str] = []

    def page(self, query: str, offset: int = 0) -> List[Dict[str, str]]:
        key = " ".join(str(query).split())
        if key not in self.queries:
            key = self.folded.get(key.casefold(), key)
        page = self.queries.get(key, {}).get(str(offset))
        if page is None:
            self.misses.append(query)
            warn(f"cache miss: {self.case_id} {query!r} offset {offset}")
            return []
        # xmltodict gives the add-on text values only
        return [{field: str(value) for field, value in f.items()} for f in page["files"]]


def parse_match(match: Dict[str, Any]) -> Dict[str, str]:
    """kodisimplestream._parse_match: the match goes through the plugin URL, all values become text."""
    return {str(key): "" if value is None else str(value) for key, value in match.items()}


def addon_flow_a_queries(match: Dict[str, Any]) -> List[str]:
    """Queries of handle_tmdb_selection (movie) and list_episodes (episode)."""
    if (match.get("mediatype") or "").lower() == "episode":
        tag = f"S{int(match['season'] or 0):02d}E{int(match['episode'] or 0):02d}"
        queries = [f"{match['showname']} {tag}"]
        original = match.get("show_originaltitle")
        if original and original != match["showname"]:
            queries.append(f"{original} {tag}")
        return queries
    year = match.get("year")
    queries = [f"{match['title']} {year}" if year else match["title"]]
    original = match.get("originaltitle")
    if original and original != match["title"]:
        queries.append(original)
    return queries


def addon_flow_a_rank(repo: Repo, pages: List[List[Dict[str, str]]], match: Dict[str, str],
                      preference: str) -> List[Dict[str, Any]]:
    """list_search_results with match and sort 0: dedup by ident in query order, stable sort by score."""
    seen = set()
    rows = []
    for files in pages:
        for file_info in files:
            ident = file_info.get("ident")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            rows.append(file_info)
    episode = (match.get("mediatype") or "").lower() == "episode"
    scored = []
    for file_info in rows:
        source = repo.source_ui.normalize_source(file_info)
        score = (repo.matching.score_episode_result(file_info, match) if episode
                 else repo.matching.score_movie_result(file_info, match))
        bonus = repo.lang_pref_bonus if repo.source_ui.matches_language_preference(source, preference) else 0
        scored.append((score + bonus, score, file_info))
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return [dict(file_info, score=score) for _, score, file_info in scored]


def run_flow_a(repo: Repo, case: Dict[str, Any], cache: Cache, preference: str) -> Tuple[List[str], List[Dict]]:
    match_raw = dict(case["match"])
    match = parse_match(match_raw)
    if repo.custom_flow_a:
        queries = [str(q) for q in repo.matching.build_search_queries(dict(match_raw))]
        pages = [cache.page(q) for q in queries]
        ranked = list(repo.matching.rank_files(pages, match, preference=preference))
    else:
        queries = addon_flow_a_queries(match_raw)
        pages = [cache.page(q) for q in queries]
        ranked = addon_flow_a_rank(repo, pages, match, preference)
    return queries, ranked


def quality_pref_value(setting: str, quality: str) -> int:
    """kodisimplestream._prefer_quality_value, "none" stands for quality_pref 0."""
    if setting == "none":
        return 0
    base = {"2160p": 4, "1080p": 3, "720p": 2, "sd": 1}.get(quality, 0)
    if setting == "highest":
        return base
    if setting == "720p_or_best":
        return base if base >= 2 else 0
    return base if base >= 3 else 0


def run_flow_b(repo: Repo, case: Dict[str, Any], cache: Cache, preference: str,
               quality_setting: str, max_results: int) -> Tuple[List[str], List[Dict]]:
    """search_and_score_tmdbh without the Kodi parts."""
    params = {str(k): str(v) for k, v in case["tmdbh_params"].items()}
    matching, source_ui = repo.matching, repo.source_ui
    queries = [str(q) for q in matching.build_tmdbh_queries(params)]
    mediatype = (params.get("mediatype") or "movie").lower()
    merged: Dict[str, Dict[str, Any]] = {}
    for term in queries:
        for file_info in cache.page(term):
            ident = file_info.get("ident")
            name = file_info.get("name", "")
            if not ident or not name:
                continue
            score = (matching.score_episode_result(file_info, params) if mediatype == "episode"
                     else matching.score_movie_result(file_info, params))
            quality = matching.parse_quality(name)
            item = {
                "ident": ident,
                "name": name,
                "img": file_info.get("img", ""),
                "size": matching.parse_size(file_info.get("size")),
                "quality": quality.get("quality", "sd"),
                "score": score,
                "quality_pref": quality_pref_value(quality_setting, quality.get("quality", "sd")),
            }
            source = source_ui.normalize_source(item)
            source["score"] = score
            item["source"] = source
            prev = merged.get(ident)
            if prev is None or item["score"] > prev["score"]:
                merged[ident] = item
    bonus = repo.lang_pref_bonus
    ranked = sorted(
        merged.values(),
        key=lambda x: (x["score"] + (bonus if source_ui.matches_language_preference(x["source"], preference) else 0),
                       x["quality_pref"], x["size"]),
        reverse=True,
    )
    return queries, [{k: v for k, v in item.items() if k != "source"} for item in ranked[:max_results]]


def case_metrics(ranked_idents: List[str], relevant: set, uncertain: set) -> Dict[str, float]:
    """Uncertain files are removed from the ranking, they count neither as a hit nor as a miss."""
    ranking = [ident for ident in ranked_idents if ident not in uncertain]
    hits = [ident in relevant for ident in ranking]
    first = next((pos for pos, hit in enumerate(hits, 1) if hit), 0)
    top1 = 1.0 if hits[:1] == [True] else 0.0
    p5 = sum(hits[:5]) / 5.0
    r10 = sum(hits[:10]) / min(10, len(relevant))
    mrr = 1.0 / first if first else 0.0
    return {
        "SCORE": (top1 + p5 + mrr + r10) / 4.0,
        "Top1": top1,
        "P@5": p5,
        "MRR": mrr,
        "R@10": r10,
        "Hit@10": 1.0 if any(hits[:10]) else 0.0,
        "first_relevant_rank": first,
    }


def evaluate_flow(flow: str, repo: Repo, cases: List[Dict], labels: Dict[str, Dict], pools: Dict[str, set],
                  args: argparse.Namespace) -> Dict[str, Any]:
    results, unlabeled, no_relevant = [], [], []
    for case in cases:
        cache = Cache(case["id"])
        if flow == "a":
            queries, ranked = run_flow_a(repo, case, cache, args.preference)
        else:
            queries, ranked = run_flow_b(repo, case, cache, args.preference, args.tmdbh_quality, args.tmdbh_max)
        idents = []
        for item in ranked:
            if not isinstance(item, dict) or not item.get("ident"):
                raise SystemExit(f"flow {flow}, {case['id']}: ranking contains an item without ident: {item!r}")
            idents.append(str(item["ident"]))
        entry: Dict[str, Any] = {
            "id": case["id"], "category": case["category"], "split": case["split"],
            "queries": queries, "n_queries": len(queries), "cache_misses": list(cache.misses),
            "n_results": len(idents),
            "top10": [{"ident": item["ident"], "name": item.get("name", ""), "score": item.get("score")}
                      for item in ranked[:10]],
        }
        label = labels.get(case["id"])
        if label is None:
            unlabeled.append(case["id"])
            entry["status"] = "unlabeled"
        else:
            pool = pools[case["id"]]
            relevant = set(label.get("relevant") or [])
            uncertain = set(label.get("uncertain") or []) - relevant
            outside = (relevant | uncertain) - pool
            if outside:
                warn(f"{case['id']}: {len(outside)} labeled idents are not in pool/{case['id']}.json")
            relevant &= pool
            entry["n_relevant_pool"] = len(relevant)
            entry["n_relevant_found"] = len(relevant & set(idents))
            if not relevant:
                no_relevant.append(case["id"])
                entry["status"] = "no_relevant"
            else:
                entry["status"] = "scored"
                entry.update(case_metrics(idents, relevant, uncertain))
                entry["queries_metric"] = len(queries)
                for item in entry["top10"]:
                    item["label"] = ("relevant" if item["ident"] in relevant
                                     else "uncertain" if item["ident"] in uncertain else "")
        results.append(entry)
    return {"flow": flow, "cases": results, "unlabeled": unlabeled, "no_relevant": no_relevant}


def aggregate(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [e for e in entries if e["status"] == "scored"]
    summary: Dict[str, Any] = {"n": len(scored)}
    for metric in METRICS:
        key = "queries_metric" if metric == "queries" else metric
        summary[metric] = round(sum(e[key] for e in scored) / len(scored), 4) if scored else None
    return summary


def summarize(flow_result: Dict[str, Any]) -> Dict[str, Any]:
    cases = flow_result["cases"]
    by_split = {"all": aggregate(cases)}
    for split in ("train", "holdout"):
        members = [e for e in cases if e["split"] == split]
        if members:
            by_split[split] = aggregate(members)
    categories = sorted({e["category"] for e in cases})
    by_category = {c: aggregate([e for e in cases if e["category"] == c]) for c in categories}
    return {"by_split": by_split, "by_category": by_category,
            "unlabeled": flow_result["unlabeled"], "no_relevant": flow_result["no_relevant"],
            "cache_misses": sum(len(e["cache_misses"]) for e in cases)}


def fmt(value: Optional[float], width: int = 7) -> str:
    return f"{'-':>{width}}" if value is None else f"{value:>{width}.3f}"


def print_table(title: str, rows: Dict[str, Dict[str, Any]]) -> None:
    print(f"  {title:<22}{'n':>4}" + "".join(f"{m:>8}" for m in METRICS))
    for name, row in rows.items():
        print(f"  {name:<22}{row['n']:>4}" + "".join(" " + fmt(row[m]) for m in METRICS))


def print_flow(flow_result: Dict[str, Any], summary: Dict[str, Any], per_case: bool) -> None:
    label = {"a": "a - TMDb search in the add-on", "b": "b - TMDb Helper"}[flow_result["flow"]]
    print(f"\nFlow {label}")
    print_table("split", summary["by_split"])
    print_table("category", summary["by_category"])
    notes = []
    if summary["unlabeled"]:
        notes.append(f"unlabeled {len(summary['unlabeled'])}")
    if summary["no_relevant"]:
        notes.append(f"no relevant file in pool {len(summary['no_relevant'])}: {', '.join(summary['no_relevant'])}")
    if summary["cache_misses"]:
        notes.append(f"cache misses {summary['cache_misses']}")
    if notes:
        print("  " + "; ".join(notes))
    if per_case:
        print(f"\n  {'case':<28}{'split':<8}{'Top1':>5}{'P@5':>6}{'MRR':>6}{'R@10':>6}{'1st':>5}{'rel':>7}{'q':>4}  top 1")
        for e in flow_result["cases"]:
            top = e["top10"][0]["name"] if e["top10"] else "(no results)"
            if e["status"] != "scored":
                print(f"  {e['id']:<28}{e['split']:<8}{e['status']:>35}{e['n_queries']:>4}  {top[:60]}")
                continue
            rel = f"{e['n_relevant_found']}/{e['n_relevant_pool']}"
            print(f"  {e['id']:<28}{e['split']:<8}{e['Top1']:>5.0f}{e['P@5']:>6.2f}{e['MRR']:>6.2f}{e['R@10']:>6.2f}"
                  f"{e['first_relevant_rank'] or '-':>5}{rel:>7}{e['n_queries']:>4}  {top[:60]}")


def write_public(report: Dict[str, Any], path: str) -> None:
    """Results for the public repository: metrics only, no Webshare file names or idents."""
    public = {key: value for key, value in report.items() if key not in ("repo", "labels", "flows")}
    public["labels"] = os.path.basename(report["labels"])
    public["flows"] = {
        flow: {"summary": data["summary"],
               "cases": [{key: value for key, value in case.items() if key != "top10"} for case in data["cases"]]}
        for flow, data in report["flows"].items()
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(public, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"written {path} (without file names)")


def compare(old: Dict[str, Any], new: Dict[str, Any]) -> None:
    """Prints old -> new metrics per flow and split and the cases whose SCORE changed."""
    for flow, data in new["flows"].items():
        before = old.get("flows", {}).get(flow)
        if not before:
            print(f"\ncompare: flow {flow} missing in the old results")
            continue
        print(f"\n=== compare flow {flow}: old -> new")
        for split, metrics in data["summary"]["by_split"].items():
            prev = before["summary"]["by_split"].get(split)
            if not prev:
                continue
            cells = []
            for name in METRICS:
                delta = metrics[name] - prev[name]
                mark = "" if abs(delta) < 0.00005 else f" ({delta:+.3f})"
                cells.append(f"{name} {prev[name]:.3f}->{metrics[name]:.3f}{mark}")
            print(f"  {split:<8} n={metrics['n']:<3} " + " | ".join(cells))
        old_cases = {case["id"]: case for case in before["cases"]}
        changed = [(case["id"], old_cases[case["id"]].get("SCORE"), case.get("SCORE")) for case in data["cases"]
                   if case["id"] in old_cases and old_cases[case["id"]].get("SCORE") != case.get("SCORE")]
        for case_id, prev, now in sorted(changed, key=lambda item: (item[2] or 0) - (item[1] or 0)):
            print(f"  {case_id:<28} SCORE {prev if prev is None else round(prev, 3)} -> {now if now is None else round(now, 3)}")
        if not changed:
            print("  no case changed")


def main() -> None:
    global DATA
    parser = argparse.ArgumentParser(description="Offline evaluation of the Webshare search ranking.")
    parser.add_argument("--repo", default=REPO_ROOT, help="KodiSimpleStream working copy to evaluate (default: this one)")
    parser.add_argument("--data", default=DATA, help="private Webshare snapshot with cache/, pool/ and labels")
    parser.add_argument("--cases", default=os.path.join(HERE, "cases.json"))
    parser.add_argument("--split", choices=["train", "holdout", "all"], default="all")
    parser.add_argument("--flow", choices=["a", "b", "both"], default="both")
    parser.add_argument("--labels", help="default: <data>/labels_audited.json")
    parser.add_argument("--json", dest="json_out", help="write per-case results incl. top 10 file names (keep private)")
    parser.add_argument("--public-json", help="write results without file names and idents (for results/)")
    parser.add_argument("--compare", help="results JSON to compare with, e.g. tools/benchmark/results/current.json")
    parser.add_argument("--per-case", action="store_true")
    parser.add_argument("--case", action="append", default=[], help="evaluate only these ids (repeat or comma list)")
    parser.add_argument("--preference", choices=["", "cz_audio", "cz_subs"], default="",
                        help="lang_pref setting of the add-on (language bonus in sorting)")
    parser.add_argument("--tmdbh-quality", choices=QUALITY_PREF_SETTINGS, default="none",
                        help="tmdbh_prefer_quality for flow b, none = quality_pref 0")
    parser.add_argument("--tmdbh-max", type=int, default=20, help="tmdbh_max_results for flow b")
    args = parser.parse_args()
    DATA = os.path.abspath(args.data)
    if not os.path.isdir(os.path.join(DATA, "cache")):
        raise SystemExit(f"Webshare snapshot not found in {DATA} (clone the private data repository, see README.md)")
    args.labels = args.labels or os.path.join(DATA, "labels_audited.json")

    repo = Repo(args.repo)
    cases = jload(args.cases)
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]
    wanted = {cid for value in args.case for cid in value.split(",") if cid}
    if wanted:
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"unknown case ids for split {args.split}: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in wanted]
    if not os.path.isfile(args.labels):
        raise SystemExit(f"labels file not found: {args.labels}")
    labels = jload(args.labels)
    pools = {c["id"]: {f["ident"] for f in jload(os.path.join(DATA, "pool", f"{c['id']}.json"))["files"]}
             for c in cases}

    print(f"repo {repo.path}")
    print(f"flow a: {'matching.build_search_queries + rank_files' if repo.custom_flow_a else 'copy of the add-on logic'}"
          f" | split {args.split} | {len(cases)} cases | labels {os.path.basename(args.labels)}"
          f" | preference {args.preference or 'none'} (bonus {repo.lang_pref_bonus})")

    report: Dict[str, Any] = {
        "repo": repo.path, "split": args.split, "labels": os.path.abspath(args.labels),
        "custom_flow_a": repo.custom_flow_a, "preference": args.preference,
        "lang_pref_bonus": repo.lang_pref_bonus, "tmdbh_quality": args.tmdbh_quality,
        "tmdbh_max": args.tmdbh_max, "flows": {},
    }
    for flow in (["a", "b"] if args.flow == "both" else [args.flow]):
        flow_result = evaluate_flow(flow, repo, cases, labels, pools, args)
        summary = summarize(flow_result)
        print_flow(flow_result, summary, args.per_case)
        report["flows"][flow] = {"summary": summary, "cases": flow_result["cases"]}

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(f"\nwritten {args.json_out}")
    if args.public_json:
        write_public(report, args.public_json)
    if args.compare:
        compare(jload(args.compare), report)


if __name__ == "__main__":
    main()
