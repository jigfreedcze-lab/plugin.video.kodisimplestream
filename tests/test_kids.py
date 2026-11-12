import json
import os
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_had_requests = "requests" in sys.modules
if not _had_requests:
    sys.modules["requests"] = types.ModuleType("requests")  # tmdb.py imports it; no HTTP here
try:
    from resources.lib import kids
    from resources.lib import tmdb as _tmdb  # noqa: F401  (imported while the fake exists)
finally:
    if not _had_requests:
        del sys.modules["requests"]  # do not leak an empty fake into other test modules
from resources.lib.kids import (AGE_TABLE, KidsConfig, blocked_genres_for_age, config_from_settings, evaluate,
                                is_no_rating, normalise, prefilter, ratings_of, search_safe)


def movie(certs_by_country=None, genres=(16,), **extra):
    results = [{"iso_3166_1": c, "release_dates": [{"certification": x} for x in certs]}
               for c, certs in (certs_by_country or {}).items()]
    data = {"id": 1, "genres": [{"id": g, "name": str(g)} for g in genres], "release_dates": {"results": results},
            "vote_count": 100}
    data.update(extra)
    return data


def tv(certs_by_country=None, genres=(16,), **extra):
    results = [{"iso_3166_1": c, "rating": r} for c, r in (certs_by_country or {}).items()]
    data = {"id": 1, "genres": [{"id": g, "name": str(g)} for g in genres], "content_ratings": {"results": results},
            "vote_count": 100}
    data.update(extra)
    return data


class ConfigTests(unittest.TestCase):
    def cfg(self, **settings):
        return config_from_settings(lambda key: settings.get(key, ""))

    def test_defaults(self):
        self.assertEqual(self.cfg(), KidsConfig())
        self.assertEqual((KidsConfig().age, KidsConfig().unrated, KidsConfig().min_votes), (8, "deny", 20))

    def test_values_and_clamping(self):
        self.assertEqual(self.cfg(kids_age="10", kids_unrated="1"), KidsConfig(age=10, unrated="allow"))
        self.assertEqual(self.cfg(kids_age="10.0").age, 10)
        self.assertEqual(self.cfg(kids_age="0").age, 3)
        self.assertEqual(self.cfg(kids_age="99").age, 18)
        self.assertEqual(self.cfg(kids_age="-5").age, 3)

    def test_sort_and_limit_config(self):
        self.assertEqual((self.cfg().sort, self.cfg().limit), ("relevance", 20))
        self.assertEqual(self.cfg(kids_sort="1").sort, "popularity")
        self.assertEqual(self.cfg(kids_sort="2").sort, "rating")
        self.assertEqual(self.cfg(kids_sort="3").sort, "year")
        self.assertEqual(self.cfg(kids_sort="9").sort, "relevance")
        self.assertEqual(self.cfg(kids_limit="40").limit, 40)
        self.assertEqual(self.cfg(kids_limit="1").limit, 5)
        self.assertEqual(self.cfg(kids_limit="999").limit, 60)
        self.assertEqual(self.cfg(kids_limit="x").limit, 20)

    def test_sort_keys(self):
        from resources.lib.kids import _sort_key
        items = [{"id": 1, "popularity": 5, "vote_average": 9, "release_date": "1999-01-01"},
                 {"id": 2, "popularity": 50, "vote_average": 6, "release_date": "2020-05-05"},
                 {"id": 3, "popularity": 20, "vote_average": 7.5, "first_air_date": "2010-01-01"},
                 {"id": 4, "popularity": 99, "vote_average": 1}]  # no date
        order = lambda sort: [i["id"] for i in sorted(items, key=lambda it: _sort_key(KidsConfig(sort=sort), it))]
        ranks = {1: (1, 0), 2: (1, 1), 3: (1, 2), 4: (2, 0)}  # relevance: page, position
        self.assertEqual([i["id"] for i in sorted(items, key=lambda it: _sort_key(KidsConfig(sort="relevance"), it, ranks[it["id"]]))], [1, 2, 3, 4])
        self.assertEqual(order("popularity"), [4, 2, 3, 1])
        self.assertEqual(order("rating"), [1, 3, 2, 4])
        self.assertEqual(order("year"), [2, 3, 1, 4])

    def test_percentile_config(self):
        self.assertEqual(self.cfg().percentile, 75)
        self.assertEqual(self.cfg(kids_percentile="90").percentile, 90)
        self.assertEqual(self.cfg(kids_percentile="10").percentile, 50)
        self.assertEqual(self.cfg(kids_percentile="500").percentile, 100)
        self.assertEqual(self.cfg(kids_percentile="x").percentile, 75)

    def test_min_votes(self):
        self.assertEqual(self.cfg(kids_min_votes="5").min_votes, 5)
        self.assertEqual(self.cfg(kids_min_votes="0").min_votes, 0)
        self.assertEqual(self.cfg(kids_min_votes="-3").min_votes, 0)
        self.assertEqual(self.cfg(kids_min_votes="x").min_votes, 20)
        self.assertEqual(self.cfg(kids_min_votes="inf").min_votes, 20)

    def test_garbage(self):
        self.assertEqual(self.cfg(kids_age="abc", kids_unrated="x"), KidsConfig())
        self.assertEqual(self.cfg(kids_age="nan").age, 8)
        self.assertEqual(self.cfg(kids_age="inf").age, 8)

    def test_never_raises(self):
        def boom(key):
            raise RuntimeError("x")
        self.assertEqual(config_from_settings(boom), KidsConfig())
        self.assertEqual(config_from_settings(lambda key: None), KidsConfig())

    def test_age_clamped_in_genres(self):
        self.assertEqual(blocked_genres_for_age("junk"), blocked_genres_for_age(8))


class GenreTests(unittest.TestCase):
    def test_by_age(self):
        strong = {27, 53, 80, 10752, 9648, 10768}
        self.assertEqual(blocked_genres_for_age(3), strong)
        self.assertEqual(blocked_genres_for_age(11), strong)
        self.assertEqual(blocked_genres_for_age(12), {27, 10752})
        self.assertEqual(blocked_genres_for_age(15), {27, 10752})
        self.assertEqual(blocked_genres_for_age(16), frozenset())
        self.assertEqual(blocked_genres_for_age(18), frozenset())


class NormaliseTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(normalise(" pg–13 "), "PG-13")
        self.assertEqual(normalise("12 +"), "12+")
        self.assertEqual(normalise("12＋"), "12+")
        self.assertEqual(normalise("ma  15+"), "MA 15+")
        self.assertEqual(normalise(None), "")

    def test_no_rating(self):
        for value in ("NR", "nr", "UR", "Unrated", "", "  ", "Not Rated"):
            self.assertTrue(is_no_rating("US", value), value)
        self.assertTrue(is_no_rating("CA", "Exempt"))
        self.assertTrue(is_no_rating("DK", "F"))
        self.assertFalse(is_no_rating("US", "F"))
        self.assertFalse(is_no_rating("US", "PG"))


class TableTests(unittest.TestCase):
    def age(self, kind, country, cert):
        details = movie({country: [cert]}) if kind == "movie" else tv({country: cert})
        return evaluate(kind, details, KidsConfig(age=18)).age

    def test_required_countries(self):
        for country in "CZ SK DE AT CH US GB FR ES IT NL SE NO DK FI CA BR".split():
            self.assertIn(country, AGE_TABLE)

    def test_examples(self):
        cases = [
            ("movie", "CZ", "U", 0), ("movie", "CZ", "12+", 12), ("movie", "CZ", "15+", 15), ("movie", "CZ", "18+", 18),
            ("tv", "CZ", "0+", 0), ("tv", "CZ", "5+", 5), ("tv", "CZ", "7+", 7), ("tv", "CZ", "9+", 9),
            ("tv", "CZ", "12+", 12), ("tv", "CZ", "15+", 15), ("tv", "CZ", "18+", 18),
            ("movie", "SK", "U", 0), ("movie", "SK", "7", 7), ("tv", "SK", "15", 15),
            ("movie", "DE", "0", 0), ("movie", "DE", "6", 6), ("movie", "DE", "12", 12),
            ("movie", "DE", "16", 16), ("movie", "DE", "18", 18),
            ("movie", "AT", "AA", 0), ("movie", "AT", "8", 8), ("tv", "AT", "14", 14),
            ("movie", "CH", "0", 0), ("movie", "CH", "10", 10), ("movie", "CH", "18", 18),
            ("movie", "US", "G", 0), ("movie", "US", "PG", 8), ("movie", "US", "PG-13", 13),
            ("movie", "US", "R", 17), ("movie", "US", "NC-17", 18),
            ("tv", "US", "TV-Y", 0), ("tv", "US", "TV-Y7", 7), ("tv", "US", "TV-G", 0), ("tv", "US", "TV-PG", 8),
            ("tv", "US", "TV-14", 14), ("tv", "US", "TV-MA", 17),
            ("movie", "GB", "U", 0), ("movie", "GB", "PG", 8), ("movie", "GB", "12A", 12), ("movie", "GB", "12", 12),
            ("movie", "GB", "15", 15), ("movie", "GB", "18", 18), ("movie", "GB", "R18", 18),
            ("movie", "FR", "TP", 0), ("tv", "FR", "10", 10), ("movie", "FR", "16", 16),
            ("movie", "ES", "A", 0), ("movie", "ES", "7i", 7), ("movie", "ES", "X", 18), ("tv", "ES", "ERI", 0),
            ("movie", "IT", "T", 0), ("movie", "IT", "6+", 6), ("tv", "IT", "VM14", 14),
            ("movie", "NL", "AL", 0), ("movie", "NL", "9", 9), ("movie", "NL", "16", 16),
            ("movie", "SE", "Btl", 0), ("movie", "SE", "11", 11), ("tv", "SE", "Från 7 år", 7),
            ("movie", "NO", "A", 0), ("movie", "NO", "9", 9), ("movie", "DK", "A", 0), ("movie", "DK", "11", 11),
            ("movie", "FI", "S", 0), ("movie", "FI", "K-12", 12), ("tv", "FI", "K16", 16), ("movie", "FI", "KK", 18),
            ("movie", "CA", "G", 0), ("movie", "CA", "PG", 8), ("movie", "CA", "14A", 14), ("movie", "CA", "18A", 18),
            ("movie", "CA", "R", 18), ("tv", "CA", "C8", 8), ("tv", "CA", "14+", 14),
            ("movie", "BR", "L", 0), ("movie", "BR", "14", 14),
            ("movie", "AU", "M", 15), ("movie", "AU", "MA 15+", 15), ("movie", "NZ", "R13", 13),
            ("movie", "IE", "15A", 15), ("movie", "PL", "AL", 0), ("movie", "HU", "6", 6),
            # strings seen in real TMDb data but missing from its certification lists
            ("movie", "ES", "APTA", 0), ("movie", "FR", "U", 0), ("movie", "CH", "U", 0), ("movie", "AT", "0", 0),
            ("movie", "PL", "15", 15), ("tv", "AU", "MA15+", 15), ("movie", "FI", "7", 7), ("movie", "FI", "K-8", 8),
            ("movie", "FI", "K-10", 10), ("movie", "FI", "16", 16), ("movie", "FI", "18", 18),
            ("movie", "NO", "7", 7), ("movie", "NO", "16", 16), ("movie", "CZ", "12", 12), ("movie", "CZ", "0", 0),
            ("movie", "NZ", "13", 13), ("movie", "CA-QC", "G", 0), ("movie", "CA-QC", "13+", 13),
            ("movie", "CA-QC", "18+", 18),
        ]
        for kind, country, cert, expected in cases:
            self.assertEqual(self.age(kind, country, cert), expected, (kind, country, cert))

    def test_label(self):
        verdict = evaluate("movie", movie({"DE": ["6"]}), KidsConfig(age=8))
        self.assertEqual((verdict.allowed, verdict.age, verdict.label), (True, 6, "DE 6"))

    def test_table_keys_are_normalised(self):
        for country, table in AGE_TABLE.items():
            for key in table:
                self.assertEqual(normalise(key), key, (country, key))
            self.assertFalse([k for k in table if is_no_rating(country, k)], country)

    def test_snapshot_of_tmdb_lists(self):
        """A {kind: {country: [certifications]}} snapshot of TMDb's lists must be fully covered (and must exist)."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmdb_certifications.json")
        with open(path, encoding="utf-8") as f:  # a missing file fails the test on purpose
            snapshot = json.load(f)
        self.assertIn("CA-QC", snapshot["movie"])
        uncovered = set()
        for kind, countries in snapshot.items():
            for country, certs in countries.items():
                if country in AGE_TABLE:
                    for cert in certs:
                        self.assertTrue(normalise(cert) in AGE_TABLE[country] or is_no_rating(country, cert),
                                        (kind, country, cert))
                else:
                    uncovered.add(country)
        # Countries of the snapshot that the table does not know are a conscious decision: a new country in
        # TMDb's lists fails here until it is added to AGE_TABLE or to this list (their adult ratings are
        # still caught by foreign_min_age).
        deliberately_outside = {"AR", "BE", "BG", "CL", "GR", "HK", "ID", "IL", "IN", "JP", "KR", "LT", "LU", "LV",
                                "MA", "MO", "MX", "MY", "PH", "PR", "PT", "RO", "RU", "SG", "TH", "TR", "TW", "UA",
                                "VI", "ZA"}
        self.assertEqual(uncovered - deliberately_outside, set(), "countries of the snapshot missing in AGE_TABLE")


class RatingsOfTests(unittest.TestCase):
    def test_movie_all_countries(self):
        details = movie({"CZ": ["12+", ""], "XX": ["Z"], "US": ["PG"]})
        self.assertEqual(ratings_of("movie", details), [("CZ", "12+"), ("XX", "Z"), ("US", "PG")])

    def test_tv(self):
        self.assertEqual(ratings_of("tv", tv({"DE": "6", "US": "", "CZ": " 7+ "})), [("DE", "6"), ("CZ", "7+")])

    def test_empty_and_broken(self):
        self.assertEqual(ratings_of("movie", {}), [])
        self.assertEqual(ratings_of("tv", None), [])
        self.assertEqual(ratings_of("movie", {"release_dates": {"results": [{"iso_3166_1": "CZ"}]}}), [])


class PrefilterTests(unittest.TestCase):
    CFG = KidsConfig(age=8)

    def item(self, **kw):
        data = {"id": 1, "genre_ids": [16], "vote_count": 100}
        data.update(kw)
        return data

    def test_ok(self):
        self.assertIsNone(prefilter(self.item(), self.CFG))
        self.assertIsNone(prefilter(self.item(genre_ids=[], original_language="ja"), self.CFG))  # no genre/language rules

    def test_rejections(self):
        self.assertEqual(prefilter(self.item(adult=True), self.CFG), "adult")
        self.assertEqual(prefilter(self.item(genre_ids=[16, 27]), self.CFG), "blocked genre")
        self.assertEqual(prefilter(self.item(vote_count=5), self.CFG), "few votes")
        self.assertEqual(prefilter(self.item(vote_count=None), self.CFG), "few votes")

    def test_genres_depend_on_age(self):
        self.assertEqual(prefilter(self.item(genre_ids=[53]), self.CFG), "blocked genre")
        self.assertIsNone(prefilter(self.item(genre_ids=[53]), KidsConfig(age=12)))
        self.assertEqual(prefilter(self.item(genre_ids=["27"]), self.CFG), "blocked genre")  # ids are coerced

    def test_genres_fail_closed(self):
        for bad in (None, "27", 5, ["abc"], [None]):
            self.assertEqual(prefilter(self.item(genre_ids=bad), self.CFG), "no genres", bad)
        item = self.item()
        del item["genre_ids"]
        self.assertEqual(prefilter(item, self.CFG), "no genres")
        self.assertEqual(prefilter(self.item(genre_ids=[27]), KidsConfig(age=15)), "blocked genre")
        self.assertIsNone(prefilter(self.item(genre_ids=[27]), KidsConfig(age=16)))


class EvaluateTests(unittest.TestCase):
    def ev(self, details, kind="movie", **cfg):
        return evaluate(kind, details, KidsConfig(**cfg))

    def test_allowed_and_too_high(self):
        self.assertTrue(self.ev(movie({"DE": ["6"]}), age=6).allowed)
        verdict = self.ev(movie({"DE": ["12"]}), age=8)
        self.assertEqual((verdict.allowed, verdict.reason, verdict.age, verdict.label), (False, "age too high", 12, "DE 12"))

    def test_strictest_of_many_countries(self):
        details = movie({"CZ": ["U"], "DE": ["6"], "US": ["PG-13"]})
        verdict = self.ev(details, age=8)
        self.assertFalse(verdict.allowed)
        self.assertEqual((verdict.age, verdict.label), (13, "US PG-13"))
        verdict = self.ev(details, age=13)
        self.assertTrue(verdict.allowed)
        self.assertEqual(verdict.age, 13)

    FAMILY = {"CZ": ["U"], "DE": ["0"], "SE": ["Btl"], "US": ["G"], "GB": ["U"], "FR": ["U"], "ES": ["TP"],
              "NL": ["AL"], "AT": ["0"], "IT": ["T"], "CH": ["12"], "HU": ["12"]}

    def test_outlier_countries_ignored_with_many_countries(self):
        verdict = self.ev(movie(self.FAMILY), age=8)  # default percentile 75: CH 12 and HU 12 do not decide
        self.assertTrue(verdict.allowed, verdict)
        self.assertEqual(verdict.age, 0)
        # ...but a 16+ rating is never an outlier: it decides whatever the other countries say
        self.assertFalse(self.ev(movie(dict(self.FAMILY, HU=["16"])), age=8).allowed)
        five = {"US": ["R"], "CZ": ["U"], "FR": ["TP"], "ES": ["A"], "IT": ["T"]}
        verdict = self.ev(movie(five), age=8)
        self.assertEqual((verdict.allowed, verdict.age, verdict.label), (False, 17, "US R"))
        self.assertFalse(self.ev(movie(dict(five, US=["NC-17"])), age=16).allowed)
        # an adult title stays high: most countries agree
        adult = {"CZ": ["18"], "DE": ["16"], "US": ["R"], "GB": ["18"], "SE": ["15"], "FR": ["16"]}
        self.assertFalse(self.ev(movie(adult), age=8).allowed)
        self.assertFalse(self.ev(movie(adult), age=12).allowed)

    def test_percentile_setting(self):
        self.assertFalse(self.ev(movie(self.FAMILY), age=8, percentile=100).allowed)  # the strictest decides
        self.assertEqual(self.ev(movie(self.FAMILY), age=18, percentile=100).age, 12)
        self.assertEqual(self.ev(movie(self.FAMILY), age=18, percentile=50).age, 0)

    def test_one_vote_per_country(self):
        # many duplicate rows of one country must not use up the "outliers": US counted once (its strictest)
        ratings = {"CZ": ["U"], "DE": ["0"], "SE": ["Btl"], "GB": ["U"], "FR": ["U"], "ES": ["TP"],
                   "US": ["PG-13", "PG-13", "PG-13", "PG-13", "G"]}
        self.assertEqual(self.ev(movie(ratings), age=18, percentile=100).age, 13)
        self.assertEqual(self.ev(movie(ratings), age=18).age, 0)

    def test_few_countries_strictest_wins(self):
        # fewer than 5 countries: no percentile, the strictest decides
        self.assertFalse(self.ev(movie({"CZ": ["U"], "DE": ["0"], "SE": ["Btl"], "CH": ["12"]}), age=8).allowed)

    def test_several_ratings_of_one_country(self):
        self.assertFalse(self.ev(movie({"US": ["PG", "R"]}), age=8).allowed)
        self.assertTrue(self.ev(movie({"US": ["PG", "G"]}), age=8).allowed)

    def test_tv(self):
        self.assertTrue(self.ev(tv({"US": "TV-Y7"}), "tv", age=7).allowed)
        self.assertFalse(self.ev(tv({"US": "TV-14"}), "tv", age=8).allowed)

    def test_unplaced_rating_rejects(self):
        verdict = self.ev(movie({"CZ": ["U"], "DE": ["99"]}), age=18, unrated="allow")
        self.assertEqual((verdict.allowed, verdict.reason), (False, "unplaced rating"))
        self.assertFalse(self.ev(movie({"US": ["TV-MA?"]}), age=18).allowed)

    def test_no_rating_markers_ignored(self):
        self.assertTrue(self.ev(movie({"US": ["NR"], "CZ": ["U"]}), age=3).allowed)
        verdict = self.ev(movie({"US": ["NR"], "CZ": ["UR"]}), age=8)
        self.assertEqual((verdict.allowed, verdict.reason), (False, "unrated"))
        self.assertTrue(self.ev(movie({"US": ["NR"]}), age=8, unrated="allow").allowed)

    def test_countries_outside_table(self):
        # an unreadable or young rating outside the table is ignored next to a placed one
        self.assertTrue(self.ev(movie({"JP": ["G"], "CZ": ["U"]}), age=3).allowed)
        self.assertTrue(self.ev(movie({"JP": ["PG12"], "CZ": ["U"]}), age=3).allowed)
        verdict = self.ev(movie({"JP": ["G"]}), age=8)
        self.assertEqual(verdict.reason, "unplaced rating")

    def test_adult_rating_outside_table_rejects(self):
        for country, cert in (("JP", "R18+"), ("JP", "R-18"), ("KR", "19"), ("RU", "18+"), ("TH", "X"),
                              ("KR", "18"), ("MX", "+16"), ("XX", "NC-17")):
            verdict = self.ev(movie({country: [cert], "CZ": ["U"]}), age=8)
            self.assertEqual((verdict.allowed, verdict.reason), (False, "age too high"), (country, cert))
            self.assertEqual(verdict.label, f"{country} {cert}")
        self.assertFalse(self.ev(tv({"KR": "19", "CZ": "U"}), "tv", age=8).allowed)
        # an older child may still see it
        self.assertTrue(self.ev(movie({"KR": ["16"], "CZ": ["U"]}), age=16).allowed)
        self.assertFalse(self.ev(movie({"KR": ["19"], "CZ": ["U"]}), age=18).allowed)
        # JP R18+ + KR 19 + RU 18+ + CZ U (the reviewed bypass)
        self.assertFalse(self.ev(movie({"JP": ["R18+"], "KR": ["19"], "RU": ["18+"], "CZ": ["U"]}), age=8).allowed)

    def test_foreign_min_age(self):
        from resources.lib.kids import foreign_min_age
        for text, expected in (("R18+", 18), ("19", 19), ("18+", 18), ("X", 18), ("16", 16), ("+18", 18),
                               ("12", None), ("PG12", None), ("G", None), ("", None), ("2018", None), ("R", None)):
            self.assertEqual(foreign_min_age(text), expected, text)

    def test_only_foreign_rating_never_counts_as_unrated(self):
        for unrated in ("deny", "allow"):
            verdict = self.ev(movie({"KR": ["ABC"]}), age=18, unrated=unrated)
            self.assertEqual((verdict.allowed, verdict.reason), (False, "unplaced rating"), unrated)
        self.assertFalse(self.ev(movie({"CA-QC": ["18+"]}), age=8, unrated="allow").allowed)
        self.assertTrue(self.ev(movie({"JP": ["NR"]}), unrated="allow").allowed)  # a no-rating marker is still none

    def test_unrated_policy(self):
        self.assertEqual(self.ev(movie({})).reason, "unrated")
        self.assertEqual(self.ev(movie({})).age, None)
        verdict = self.ev(movie({}), unrated="allow")
        self.assertEqual((verdict.allowed, verdict.age), (True, None))
        self.assertTrue(self.ev(tv({}), "tv", unrated="allow").allowed)

    def test_normalised_strings(self):
        self.assertTrue(self.ev(movie({"US": ["pg–13"]}), age=13).allowed)
        self.assertFalse(self.ev(movie({"US": ["pg–13"]}), age=12).allowed)
        self.assertTrue(self.ev(movie({"CZ": ["12 +"]}), age=12).allowed)

    def test_adult_genres_votes(self):
        self.assertEqual(self.ev(movie({"CZ": ["U"]}, adult=True)).reason, "adult")
        self.assertEqual(self.ev(movie({"CZ": ["U"]}, genres=(16, 27))).reason, "blocked genre")
        self.assertEqual(self.ev(movie({"CZ": ["U"]}, genres=(16, 9648)), age=11).reason, "blocked genre")
        self.assertTrue(self.ev(movie({"CZ": ["U"]}, genres=(16, 9648)), age=12).allowed)
        self.assertFalse(self.ev(movie({"CZ": ["U"]}, genres=(27,)), age=15).allowed)
        self.assertTrue(self.ev(movie({"CZ": ["U"]}, genres=(27,)), age=16).allowed)
        self.assertEqual(self.ev(movie({"CZ": ["U"]}, vote_count=3)).reason, "few votes")
        details = movie({"CZ": ["U"]})
        del details["vote_count"]
        self.assertEqual(self.ev(details).reason, "few votes")  # a missing count is 0

    def test_genres_fail_closed(self):
        ok = movie({"DE": ["6"]})
        self.assertTrue(self.ev(ok, age=8).allowed)
        for bad in (None, "x", 5, [None], ["27"], [{"name": "no id"}], [{"id": None}], [{"id": "abc"}]):
            details = dict(ok, genres=bad)
            self.assertFalse(self.ev(details, age=8).allowed, bad)
        details = dict(ok)
        del details["genres"]
        self.assertEqual(self.ev(details, age=8).reason, "no genres")
        horror = dict(ok, genres=[{"id": "27"}])  # a string id is coerced, so the genre is still blocked
        self.assertEqual(self.ev(horror, age=8).reason, "blocked genre")
        self.assertEqual(self.ev(dict(ok, genres=[]), age=8).reason, "age ok")

    def test_broken_details(self):
        self.assertFalse(self.ev({}).allowed)
        self.assertFalse(self.ev({"genres": None, "release_dates": None}).allowed)


class FakeTmdb:
    def __init__(self, searches, details, failing=()):
        self.searches, self.details, self.failing = searches, details, set(failing)
        self.search_calls, self.detail_threads, self.lock = [], set(), threading.Lock()

    def search_raw(self, query, kind, page=1):
        with self.lock:
            self.search_calls.append((query, kind, page, threading.get_ident()))
        return self.searches.get((kind, page), [])

    def details_with_ratings(self, kind, tmdb_id):
        with self.lock:
            self.detail_threads.add(threading.get_ident())
        if (kind, tmdb_id) in self.failing:
            raise RuntimeError("boom")
        return self.details[(kind, tmdb_id)]


def sr(id_, popularity, title="T", **kw):
    data = {"id": id_, "title": title, "name": title, "popularity": popularity, "genre_ids": [16],
            "vote_count": 100, "release_date": "2020-05-01", "poster_path": "/p.jpg", "overview": "plot",
            "vote_average": 7.26}
    data.update(kw)
    return data


class SearchSafeTests(unittest.TestCase):
    CFG = KidsConfig(age=12, sort="popularity")

    def setUp(self):
        self.searches = {("movie", 1): [sr(1, 10), sr(2, 50), sr(3, 5, adult=True), sr(4, 1, vote_count=1)],
                         ("movie", 2): [sr(5, 30), sr(1, 10)],
                         ("tv", 1): [sr(10, 40, name="Serial", first_air_date="2019-01-01", release_date=None)]}
        self.details = {("movie", 1): movie({"CZ": ["U"]}), ("movie", 2): movie({"CZ": ["12+"], "DE": ["6"]}),
                        ("movie", 5): movie({"CZ": ["18+"]}), ("tv", 10): tv({"CZ": "0+"})}

    def run_search(self, **kw):
        tmdb = FakeTmdb(self.searches, self.details, kw.pop("failing", ()))
        kinds = kw.pop("kinds", ("movie", "tv"))
        return tmdb, search_safe(tmdb, "q", kinds, kw.pop("cfg", self.CFG), **kw)

    def test_merge_order_and_dedupe(self):
        tmdb, result = self.run_search()
        self.assertEqual([r["id"] for r in result], ["movie:2", "tv:10", "movie:1"])
        first = result[0]
        self.assertEqual((first["kind"], first["year"], first["certification"], first["country"], first["rating"]),
                         ("movie", "2020", "12+", "", 7.3))
        self.assertEqual(first["title"], "T")
        self.assertEqual(first["poster"], "https://image.tmdb.org/t/p/w500/p.jpg")
        self.assertEqual(result[1]["year"], "2019")
        self.assertEqual(result[2]["certification"], "0+")
        self.assertEqual({c[1:3] for c in tmdb.search_calls}, {("movie", 1), ("movie", 2), ("tv", 1), ("tv", 2)})

    def test_pages_fetched_in_parallel(self):
        barrier = threading.Barrier(4, timeout=5)  # 2 kinds x 2 pages: passes only when all four run at once

        class BarrierTmdb(FakeTmdb):
            def search_raw(self, query, kind, page=1):
                barrier.wait()
                return super().search_raw(query, kind, page)

        tmdb = BarrierTmdb(self.searches, self.details)
        search_safe(tmdb, "q", ("movie", "tv"), self.CFG)
        self.assertEqual(len(tmdb.search_calls), 4)
        self.assertNotIn(threading.get_ident(), {c[3] for c in tmdb.search_calls})

    def test_malformed_search_item_drops_only_itself(self):
        self.searches[("movie", 1)] += [sr(6, 20, vote_count="abc"), sr(7, 20, genre_ids=5), "junk", None,
                                        sr(8, 20, genre_ids=None)]
        _, result = self.run_search()
        self.assertEqual([r["id"] for r in result], ["movie:2", "tv:10", "movie:1"])

    def test_fail_closed(self):
        _, result = self.run_search(failing=[("movie", 2)])
        self.assertEqual([r["id"] for r in result], ["tv:10", "movie:1"])

    def test_missing_details_is_dropped(self):
        del self.details[("tv", 10)]
        _, result = self.run_search()
        self.assertNotIn("tv:10", [r["id"] for r in result])

    def test_relevance_interleaves_kinds_and_pages(self):
        _, result = self.run_search(cfg=KidsConfig(age=12))  # default sort: TMDb order, page by page
        # first of each kind (tie broken by popularity), then the second movie; movie:5 is too old for age 12
        self.assertEqual([r["id"] for r in result], ["tv:10", "movie:1", "movie:2"])

    def test_heavy_details_only_for_listed_titles(self):
        class Counting(FakeTmdb):
            extras = []

            def details_extras(self, kind, tmdb_id):
                self.extras.append((kind, tmdb_id))
                return {"images": {"posters": [{"iso_639_1": "cs", "file_path": "/cs.jpg", "vote_average": 1}]}}

        tmdb = Counting(self.searches, self.details)
        result = search_safe(tmdb, "q", ("movie", "tv"), KidsConfig(age=12, sort="popularity"), limit=1)
        self.assertEqual([r["id"] for r in result], ["movie:2"])
        self.assertEqual(Counting.extras, [("movie", 2)])  # not for the 4 other candidates
        self.assertTrue(result[0]["poster"].endswith("/cs.jpg"))

    def test_limit_and_pages(self):
        _, result = self.run_search(limit=2)
        self.assertEqual([r["id"] for r in result], ["movie:2", "tv:10"])
        tmdb, _ = self.run_search(pages=1)
        self.assertTrue(all(c[2] == 1 for c in tmdb.search_calls))

    def test_kinds(self):
        tmdb, result = self.run_search(kinds=("tv",))
        self.assertEqual([r["id"] for r in result], ["tv:10"])
        self.assertTrue(all(c[1] == "tv" for c in tmdb.search_calls))
        self.assertEqual(search_safe(FakeTmdb({}, {}), "q", (), self.CFG), [])

    def test_threading_and_nothing_found(self):
        self.searches = {("movie", 1): [sr(i, i) for i in range(1, 9)]}
        self.details = {("movie", i): movie({"CZ": ["U"]}) for i in range(1, 9)}
        tmdb, result = self.run_search(kinds=("movie",), workers=4)
        self.assertEqual(len(result), 8)
        self.assertNotIn(threading.get_ident(), tmdb.detail_threads)
        tmdb, result = self.run_search(kinds=("movie",), cfg=KidsConfig(min_votes=10000))
        self.assertEqual(result, [])
        self.assertEqual(tmdb.detail_threads, set())

    def test_age_applies(self):
        _, result = self.run_search(cfg=KidsConfig(age=5, sort="popularity"))
        self.assertEqual([r["id"] for r in result], ["tv:10", "movie:1"])
        _, result = self.run_search(cfg=KidsConfig(age=18))
        self.assertIn("movie:5", [r["id"] for r in result])

    def test_unrated_entry_has_no_certification(self):
        self.details[("movie", 1)] = movie({})
        _, result = self.run_search(cfg=KidsConfig(age=12, unrated="allow", sort="popularity"))
        entry = [r for r in result if r["id"] == "movie:1"][0]
        self.assertEqual(entry["certification"], "")
        _, result = self.run_search()
        self.assertNotIn("movie:1", [r["id"] for r in result])


class SearchRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.searches = {("movie", 1): [sr(1, 10), sr(2, "high", vote_average="9x"), sr(3, None, vote_average="n/a"),
                                        sr(4, float("nan"), release_date=20200101, overview=5)]}
        self.details = {("movie", i): movie({"CZ": ["U"]}) for i in range(1, 5)}

    def test_non_numeric_fields_do_not_break_search(self):
        for sort in ("relevance", "popularity", "rating", "year"):
            tmdb = FakeTmdb(self.searches, self.details)
            result = search_safe(tmdb, "q", ("movie",), KidsConfig(age=12, sort=sort))
            self.assertEqual(sorted(r["id"] for r in result), ["movie:1", "movie:2", "movie:3", "movie:4"], sort)
        self.assertEqual([r["id"] for r in search_safe(tmdb, "q", ("movie",), KidsConfig(age=12, sort="popularity"))][0],
                         "movie:1")

    def test_details_failure_is_logged_without_details_of_the_error(self):
        logged = []
        original = kids._log
        kids._log = logged.append
        try:
            class Secret(FakeTmdb):
                def details_with_ratings(self, kind, tmdb_id):
                    if tmdb_id == 2:
                        raise RuntimeError("https://x/3/movie/2?api_key=SECRETKEY")
                    return super().details_with_ratings(kind, tmdb_id)
            result = search_safe(Secret(self.searches, self.details), "q", ("movie",), KidsConfig(age=12))
        finally:
            kids._log = original
        self.assertNotIn("movie:2", [r["id"] for r in result])
        self.assertEqual(len(logged), 1)
        self.assertIn("movie:2", logged[0])
        self.assertNotIn("SECRETKEY", logged[0])

    def test_all_details_failing_raises_instead_of_empty(self):
        tmdb = FakeTmdb(self.searches, self.details, failing=[("movie", i) for i in range(1, 5)])
        original = kids._log
        kids._log = lambda message: None
        try:
            with self.assertRaises(RuntimeError):
                search_safe(tmdb, "q", ("movie",), KidsConfig(age=12))
        finally:
            kids._log = original
        # nothing suitable (as opposed to a failure) is still an empty list
        self.assertEqual(search_safe(FakeTmdb(self.searches, self.details), "q", ("movie",), KidsConfig(age=12, min_votes=10 ** 6)), [])


class SearchAllTests(unittest.TestCase):
    def setUp(self):
        self.searches = {("movie", 1): [sr(1, 10, vote_average=5), sr(2, 50, vote_average=9, adult=True),
                                        sr(3, 30, vote_average=8, genre_ids=[27], vote_count=0, release_date="2023-01-01"),
                                        sr(4, 20, vote_average=6, release_date="2010-01-01")],
                         ("tv", 1): [sr(10, 40, name="Serial", first_air_date="2021-01-01", release_date=None)]}

    def run_all(self, cfg, **kw):
        tmdb = FakeTmdb(self.searches, {})  # details_with_ratings would raise KeyError: it must not be called
        return tmdb, kids.search_all(tmdb, "q", ("movie", "tv"), cfg, **kw)

    def ids(self, cfg, **kw):
        return [r["id"] for r in self.run_all(cfg, **kw)[1]]

    def test_no_age_filter_but_no_adult(self):
        tmdb, result = self.run_all(KidsConfig(age=3, sort="popularity"))
        self.assertEqual([r["id"] for r in result], ["tv:10", "movie:3", "movie:4", "movie:1"])  # horror, 0 votes kept; adult gone
        self.assertEqual(tmdb.detail_threads, set())
        self.assertTrue(all(r["certification"] == "" for r in result))

    def test_sorting(self):
        self.assertEqual(self.ids(KidsConfig(sort="rating")), ["movie:3", "tv:10", "movie:4", "movie:1"])
        self.assertEqual(self.ids(KidsConfig(sort="year")), ["movie:3", "tv:10", "movie:1", "movie:4"])
        self.assertEqual(self.ids(KidsConfig(sort="relevance")), ["tv:10", "movie:1", "movie:3", "movie:4"])

    def test_limit(self):
        self.assertEqual(self.ids(KidsConfig(sort="popularity"), limit=2), ["tv:10", "movie:3"])
        self.assertEqual(self.ids(KidsConfig(sort="popularity", limit=1)), ["tv:10"])


class RealDataAliasesTest(unittest.TestCase):
    def test_strings_seen_in_real_tmdb_data_are_placed(self):
        """Ratings of table countries that real TMDb answers contain (found by scanning ~550 family titles)."""
        for country, text, age in (("CH", "7", 7), ("CZ", "6+", 6), ("CZ", "G", 0), ("FI", "11", 11), ("FI", "12", 12), ("FI", "K-11", 11),
                                   ("FI", "K-13", 13), ("FI", "K-14", 14), ("FI", "K-6-4", 6), ("NO", "7 år", 7), ("NO", "11 år", 11),
                                   ("HU", "6 éven aluliak számára nem ajánlott", 6)):
            self.assertEqual(kids.AGE_TABLE[country][kids.normalise(text)], age, (country, text))


class PosterTests(unittest.TestCase):
    def test_czech_poster_preferred(self):
        from resources.lib.kids import _best_poster
        item = {"poster_path": "/jp.jpg"}
        details = {"images": {"posters": [
            {"iso_639_1": "ja", "file_path": "/jp.jpg", "vote_average": 9},
            {"iso_639_1": "en", "file_path": "/en.jpg", "vote_average": 8},
            {"iso_639_1": "cs", "file_path": "/cs1.jpg", "vote_average": 1},
            {"iso_639_1": "cs", "file_path": "/cs2.jpg", "vote_average": 5}]}}
        self.assertEqual(_best_poster(item, details), "/cs2.jpg")
        del details["images"]["posters"][2:]
        self.assertEqual(_best_poster(item, details), "/en.jpg")
        self.assertEqual(_best_poster(item, {}), "/jp.jpg")
        # Slovak before English, language-less last
        sk = {"images": {"posters": [{"iso_639_1": None, "file_path": "/none.jpg", "vote_average": 9},
                                     {"iso_639_1": "sk", "file_path": "/sk.jpg", "vote_average": 1},
                                     {"iso_639_1": "en", "file_path": "/en.jpg", "vote_average": 8}]}}
        self.assertEqual(_best_poster(item, sk), "/sk.jpg")
        del sk["images"]["posters"][1:]
        self.assertEqual(_best_poster(item, sk), "/none.jpg")
        self.assertEqual(_best_poster(item, {"images": {"posters": [{"iso_639_1": "ja", "file_path": "/ja.jpg"}]}}), "/jp.jpg")
        self.assertEqual(_best_poster(item, {"images": {"posters": [{"iso_639_1": "cs", "file_path": "/a.jpg", "vote_average": "x"}]}}), "/a.jpg")
        self.assertEqual(_best_poster(item, {"images": None}), "/jp.jpg")

class DisplayTitleTests(unittest.TestCase):
    def test_non_latin_title_uses_english(self):
        from resources.lib.kids import _display_title
        details = {"translations": {"translations": [
            {"iso_639_1": "en", "iso_3166_1": "US", "data": {"name": "Pokemon: The Origin"}}]}}
        self.assertEqual(_display_title({"title": "ポケットモンスター THE ORIGIN"}, details), "Pokemon: The Origin")
        self.assertEqual(_display_title({"name": "Покемон"}, details), "Pokemon: The Origin")
        self.assertEqual(_display_title({"title": "ポケ"}, {}), "ポケ")  # no English: keep the original
        self.assertEqual(_display_title({"title": "Příliš žluťoučký"}, details), "Příliš žluťoučký")
        self.assertEqual(_display_title({"title": "Léon"}, None), "Léon")
        self.assertEqual(_display_title({}, None), "")


if __name__ == "__main__":
    unittest.main()
