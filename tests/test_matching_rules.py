"""Pravidla skóre shody a dotazů v matching.py na vymyšlených názvech souborů."""
import unittest

from resources.lib.matching import (
    MAX_QUERIES,
    build_search_queries,
    build_tmdbh_queries,
    czech_to_hepburn,
    parse_episode_numbers,
    parse_episode_tags,
    rank_files,
    score_episode_result,
    score_movie_result,
    tokenize,
)

MOVIE = {"mediatype": "movie", "title": "Zelený ostrov", "originaltitle": "The Green Island", "year": "2015"}
SHOW = {"mediatype": "episode", "showname": "Tichá řeka", "show_originaltitle": "Silent River", "season": "2",
        "episode": "5", "episode_title": "Most přes vodu"}


def movie(name, params=MOVIE):
    return score_movie_result({"name": name}, params)


def episode(name, params=SHOW):
    return score_episode_result({"name": name}, params)


class TokenizeTests(unittest.TestCase):
    def test_diacritics_apostrophes_and_scripts(self):
        self.assertEqual(tokenize("Skok přes plot: Jack's Fence"), ["skok", "pres", "plot", "jacks", "fence"])
        self.assertEqual(tokenize("Мост через реку"), ["most", "cherez", "reku"])
        self.assertEqual(tokenize("Zelená rieka.Łódź_2019"), ["zelena", "rieka", "lodz", "2019"])
        self.assertEqual(tokenize("緑の島 (2015)"), ["緑の島", "2015"])

    def test_czech_transcription_of_japanese(self):
        self.assertEqual(czech_to_hepburn("Kódži no čidžin"), "Kóji no chijin")
        self.assertEqual(czech_to_hepburn("Cukimi šódžo"), "Tsukimi shójo")


class MovieTitleTests(unittest.TestCase):
    def test_any_title_is_a_full_match(self):
        czech = movie("Zeleny.Ostrov.2015.1080p.mkv")
        self.assertEqual(movie("The.Green.Island.2015.1080p.mkv"), czech)
        self.assertEqual(movie("Green Island, The (2015) 1080p.mkv"), czech)
        english = dict(MOVIE, originaltitle="緑の島", englishtitle="The Green Island")
        self.assertEqual(movie("The.Green.Island.2015.1080p.mkv", english), czech)

    def test_words_in_any_order_and_typos(self):
        self.assertGreater(movie("Ostrov zelený 2015.avi"), 80)
        self.assertGreater(movie("Zeleny ostrow 2015.avi"), movie("Zeleny 2015.avi"))
        self.assertGreater(movie("Zeleny ostrow 2015.avi"), movie("Zelený ostrov 1998.avi"))

    def test_single_word_title_without_typos(self):
        params = {"title": "Kometa", "originaltitle": "", "year": "2010"}
        self.assertGreater(movie("Kometa 2010.mkv", params), 80)
        self.assertLess(movie("Komety 2010.mkv", params), 10)

    def test_non_latin_title_inside_the_name(self):
        params = {"title": "Zelený ostrov", "originaltitle": "緑の島", "year": "2015"}
        self.assertGreater(movie("緑の島 (2015) 1080p.mkv", params), 80)
        self.assertGreater(movie("[字幕组][緑の島][1080P].mkv", params), 65)
        params = {"title": "Tichý ostrov", "originaltitle": "Тихий остров", "year": "2015"}
        self.assertGreater(movie("Тихий острів (2015).avi", params), 75)

    def test_year_only_with_the_title(self):
        self.assertLess(movie("Uplne jiny film 2015 1080p.mkv"), 10)
        self.assertGreater(movie("Zelený ostrov 2015.avi"), movie("Zelený ostrov.avi"))
        self.assertGreater(movie("Zelený ostrov.avi"), movie("Zelený ostrov 1971.avi"))
        self.assertEqual(movie("Zelený ostrov 2016.avi"), movie("Zelený ostrov.avi"))

    def test_year_with_a_partly_matching_title(self):
        # název v jiném jazyce, který má se známým názvem společné jen některé slovo: rok podle shodné části
        params = {"title": "Zelený ostrov", "originaltitle": "緑の島", "year": "2015"}
        partly = movie("Zeleny Island 2015.avi", params)
        self.assertGreater(partly, movie("Zeleny Island.avi", params) + 5)
        self.assertGreater(partly, movie("Zeleny Island 1998.avi", params) + 25)
        self.assertLess(partly, movie("Zelený ostrov.avi", params))

    def test_other_part_of_a_series(self):
        plain = movie("Zelený ostrov.avi")
        for name in ("Zelený ostrov 2.avi", "Zeleny-ostrov---3 CZ.avi", "Zelený ostrov II. CZ.avi"):
            self.assertLess(movie(name), plain - 20, name)
        self.assertLess(movie("Zelený ostrov Part Two.avi"), plain)
        # číslo před slovem část/part je část filmu jako Part 2, ne další díl série
        self.assertEqual(movie("Zelený ostrov 2. část.avi"), movie("Zelený ostrov Part 2.avi"))
        self.assertGreater(movie("Zelený ostrov 2. část.avi"), movie("Zelený ostrov 2.avi") + 10)
        self.assertEqual(movie("Zelený ostrov 1.avi"), plain)
        self.assertEqual(movie("Zelený ostrov 5.1 CZ.avi"), movie("Zelený ostrov CZ.avi"))
        numbered = {"title": "Ostrov 2: Návrat", "originaltitle": "Island 2: Return", "year": "2018"}
        self.assertGreater(movie("Island 2 Return 2018.mkv", numbered), movie("Island 3 2021.mkv", numbered))
        self.assertGreater(movie("Ostrov II Navrat 2018.mkv", numbered), 80)

    def test_title_before_the_subtitle(self):
        params = {"title": "Ostrov 2: Návrat", "originaltitle": "", "year": "2018"}
        self.assertGreater(movie("Ostrov 2 (2018) 1080p.mkv", params), 70)
        self.assertGreater(movie("Ostrov 2 Navrat (2018) 1080p.mkv", params), movie("Ostrov 2 (2018) 1080p.mkv", params))
        sequel = {"title": "Ostrov: Návrat", "originaltitle": "", "year": "2018"}
        # první film bez podtitulu je jen částečná shoda, rok se počítá jen podle shodné části
        self.assertLess(movie("Ostrov (2018) 1080p.mkv", sequel), 40)
        self.assertLess(movie("Ostrov (2018) 1080p.mkv", sequel), movie("Ostrov Navrat (2018) 1080p.mkv", sequel) - 50)

    def test_other_words_around_the_title(self):
        right = movie("Zelený ostrov 2015.avi")
        self.assertLess(movie("Zelený ostrov Pomsta 2015.avi"), right - 15)
        self.assertLess(movie("Navrat na Zeleny ostrov 2015.avi"), right - 15)
        self.assertEqual(movie("Zelený ostrov - Green Island 2015 CZ dabing.avi"), right)
        self.assertEqual(movie("[Skupina] Zelený ostrov 2015.avi"), right)
        short = {"title": "Kometa", "originaltitle": "", "year": "2010"}
        self.assertLess(movie("Kometa Halley 2010.mkv", short), movie("Kometa 2010.mkv", short) - 25)

    def test_episode_or_extra_in_a_movie_search(self):
        plain = movie("Zelený ostrov 2015.avi")
        self.assertLess(movie("Zelený ostrov S01E02 2015.avi"), plain - 30)
        self.assertLess(movie("Zelený ostrov 2015 trailer.avi"), plain - 50)
        self.assertLess(movie("Zelený ostrov soundtrack 2015.mp4"), plain - 50)
        self.assertLess(movie("Zelený ostrov - Film o filmu 2015.avi"), plain - 50)
        # film s bonusem v jednom souboru
        self.assertEqual(movie("Zelený ostrov 2015 + Film o filmu.avi"), plain)
        self.assertEqual(movie("Zelený ostrov film 2015.avi"), plain)
        trailer = {"title": "Trailer na kraji lesa", "originaltitle": "", "year": "2015"}
        self.assertGreater(movie("Trailer na kraji lesa 2015.avi", trailer), 80)
        making_of = {"title": "Film o filmu", "originaltitle": "", "year": "2015"}
        self.assertGreater(movie("Film o filmu 2015.avi", making_of), 80)


class EpisodeTests(unittest.TestCase):
    def test_episode_tag_formats(self):
        for name in ("Ticha.reka.S02E05.mkv", "Ticha reka s02.e05.mkv", "Tichá řeka S02 E05.mkv", "Ticha reka 2x05.avi",
                     "Ticha reka 02x05.avi", "Ticha reka S2E5.avi", "Ticha reka S02E04-E06.mkv", "Ticha reka S02E04E05.mkv",
                     "Silent.River.S02E05.1080p.mkv"):
            self.assertIn((2, 5), parse_episode_tags(name)[0], name)
            self.assertGreater(episode(name), 120, name)
        self.assertEqual(parse_episode_tags("Ticha reka 1920x1080 S02.mkv"), (set(), {2}))
        self.assertEqual(parse_episode_tags("Ticha reka 2. rada.mkv"), (set(), {2}))
        self.assertEqual(parse_episode_tags("Ticha reka Season 2 Episode 5.mkv"), ({(2, 5)}, set()))
        self.assertEqual(parse_episode_tags("Ticha reka 2. serie 5. dil.avi"), ({(2, 5)}, set()))

    def test_other_episode_or_season(self):
        right = episode("Ticha reka S02E05.mkv")
        self.assertLess(episode("Ticha reka S02E06.mkv"), right - 100)
        self.assertLess(episode("Ticha reka S01E05.mkv"), right - 100)
        self.assertLess(episode("Ticha reka S03.mkv"), episode("Ticha reka.mkv"))

    def test_show_title_is_needed(self):
        self.assertLess(episode("Jiny serial S02E05.mkv"), episode("Ticha reka S02E05.mkv") - 80)
        self.assertLess(episode("Ticha reka Navrat S02E05.mkv"), episode("Ticha reka S02E05.mkv") - 10)

    def test_episode_numbers_without_season(self):
        self.assertEqual(parse_episode_numbers("Ticha reka E05 - Most.mkv"), {5})
        self.assertEqual(parse_episode_numbers("Ticha reka - 5. dil.mkv"), {5})
        self.assertEqual(parse_episode_numbers("Ticha-reka-5dil.avi"), {5})
        first = dict(SHOW, season="1")
        self.assertGreater(episode("[Grupa] Ticha reka - 05 [ABC123].mkv", first), episode("Ticha reka.mkv", first) + 40)
        self.assertGreater(episode("Ticha reka 05.avi", first), episode("Ticha reka 07.avi", first) + 60)
        self.assertGreater(episode("Ticha reka E05.avi", first), episode("Ticha reka E06.avi", first) + 60)
        self.assertEqual(episode("Ticha reka 5 Pribeh dal.avi", first), episode("Ticha reka 7 Pribeh dal.avi", first))

    def test_episode_title(self):
        self.assertGreater(episode("Tichá řeka - Most přes vodu.avi"), episode("Tichá řeka.avi") + 30)
        self.assertGreater(episode("05 - Most pres vodu.avi"), episode("Jiny serial S02E05.avi"))
        generic = dict(SHOW, episode_title="5. epizoda")
        self.assertEqual(episode("Ticha reka 5 epizoda.avi", generic), episode("Ticha reka.avi", generic) + 25)

    def test_episode_title_stands_in_for_the_show_title(self):
        # soubor ve složce seriálu bez jeho názvu: tag SxxEyy s názvem epizody je silnější než holé číslo
        tagged = episode("S02E05 - Most pres vodu.mkv")
        self.assertGreater(tagged, episode("Jiny serial S02E05.mkv") + 80)
        self.assertGreater(tagged, episode("05 - Most pres vodu.avi"))
        self.assertLess(tagged, episode("Ticha reka S02E05.mkv"))
        one_word = dict(SHOW, season="1", episode_title="Od mostu")
        self.assertGreater(episode("S01E05 - Od mostu.mkv", one_word), episode("05 Znovu od mostu.mkv", one_word))

    def test_making_of_a_show(self):
        first = dict(SHOW, season="1", episode_title="Od mostu")
        making_of = episode("Ticha reka E05 Film o serialu.mkv", first)
        self.assertLess(making_of, episode("Ticha reka E05.mkv", first) - 50)
        self.assertLess(making_of, episode("S01E05 - Od mostu.mkv", first))

    def test_czech_transcription_of_a_japanese_show(self):
        params = {"mediatype": "episode", "showname": "Kódži no čidžin", "show_originaltitle": "", "season": "1",
                  "episode": "3"}
        self.assertGreater(episode("Koji.no.Chijin.S01E03.1080p.mkv", params), 120)

    def test_sxe_preferred_over_x_but_both_match(self):
        self.assertGreater(episode("Ticha reka S02E05.mkv"), episode("Ticha reka 2x05.mkv"))
        self.assertGreater(episode("Ticha reka 2x05.mkv"), 120)


class QueryTests(unittest.TestCase):
    def test_movie_queries(self):
        self.assertEqual(build_search_queries(MOVIE), ["Zelený ostrov 2015", "The Green Island 2015"])
        self.assertEqual(build_search_queries({"mediatype": "movie", "title": "Ostrov", "originaltitle": "ostrov",
                                               "year": ""}), ["Ostrov"])
        self.assertEqual(build_tmdbh_queries(MOVIE), ["Zelený ostrov 2015", "Zelený ostrov", "The Green Island 2015",
                                                      "The Green Island"])

    def test_unsearchable_original_is_skipped(self):
        params = {"mediatype": "movie", "title": "Zelený ostrov", "originaltitle": "緑の島", "year": "2015"}
        self.assertEqual(build_tmdbh_queries(params), ["Zelený ostrov 2015", "Zelený ostrov"])
        params = dict(params, originaltitle="Зелёный остров")
        self.assertIn("Зелёный остров 2015", build_tmdbh_queries(params))
        self.assertIn("300 2006", build_tmdbh_queries({"title": "300: Bitva", "originaltitle": "300", "year": "2006"}))
        show = dict(SHOW, show_originaltitle="녹색 강")
        self.assertNotIn("녹색 강 S02E05", build_tmdbh_queries(show))

    def test_episode_queries(self):
        self.assertEqual(build_search_queries(dict(SHOW, season=2, episode=5)),
                         ["Tichá řeka S02E05", "Silent River S02E05", "Tichá řeka Most přes vodu", "Tichá řeka 2x05"])
        colon = {"mediatype": "episode", "showname": "Řeka: Návrat", "show_originaltitle": "", "season": 1, "episode": 2,
                 "episode_title": "2. epizoda"}
        self.assertEqual(build_search_queries(colon), ["Řeka: Návrat S01E02", "Řeka S01E02", "Řeka: Návrat 1x02"])
        self.assertEqual(build_search_queries(dict(colon, season=0)), ["Řeka: Návrat S00E02", "Řeka S00E02"])
        for params in (SHOW, dict(SHOW, showname="A: B", show_originaltitle="C: D")):
            self.assertLessEqual(len(build_tmdbh_queries(params)), MAX_QUERIES)
            self.assertLessEqual(len(build_search_queries(params)), MAX_QUERIES)
        self.assertEqual(build_tmdbh_queries(dict(SHOW, season="")), [])


class RankTests(unittest.TestCase):
    def test_rank_files(self):
        pages = [[{"ident": "a", "name": "Jiny film 2015.avi"}, {"ident": "b", "name": "Zelený ostrov 2015 CZ dabing.avi"}],
                 [{"ident": "b", "name": "duplicate"}, {"ident": "c", "name": "The Green Island 2015.avi"},
                  {"ident": "d", "name": "Zelený ostrov 2015 EN.avi"}]]
        ranked = rank_files(pages, MOVIE)
        self.assertEqual([r["ident"] for r in ranked], ["b", "c", "d", "a"])
        self.assertEqual(ranked[0]["name"], "Zelený ostrov 2015 CZ dabing.avi")
        self.assertEqual(ranked[0]["score"], movie("Zelený ostrov 2015 CZ dabing.avi"))
        preferred = rank_files(pages, MOVIE, preference="cz_audio")
        self.assertEqual([r["ident"] for r in preferred], ["b", "c", "d", "a"])
        self.assertEqual([r["score"] for r in preferred], [r["score"] for r in ranked])
        self.assertEqual([r["ident"] for r in rank_files([pages[1][1:]], MOVIE, preference="cz_audio")], ["c", "d"])


if __name__ == "__main__":
    unittest.main()
