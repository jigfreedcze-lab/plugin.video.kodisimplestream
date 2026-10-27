from resources.lib.source_ui import (
    detect_languages,
    language_tag,
    matches_language_preference,
    normalize_source,
)


def test_czech_dub_words():
    assert detect_languages("Harry.Potter.2.a.Tajemna.komnata.2002.1080p.Bluray.x264.AC3.5.1.CZ.Dabing.mkv") == (["CZ"], [])
    assert detect_languages("Film.2020.cz-dab.1080p.mkv") == (["CZ"], [])
    assert detect_languages("Film.2020.SK.dabing.mkv") == (["SK"], [])
    # "dabing" bez kódu jazyka na Webshare znamená český dabing
    assert detect_languages("Film.2020.Dabing.1080p.mkv") == (["CZ"], [])


def test_czech_subtitles_words():
    # "titulky" bez kódu jazyka = české titulky, zvuk neznámý
    assert detect_languages("Film.2020.1080p.titulky.mkv") == ([], ["CZ"])
    assert detect_languages("Film.2020.EN.CZ.titulky.mkv") == (["EN"], ["CZ"])
    assert detect_languages("Film.2160p.CZ.vlozene.titulky.mkv") == ([], ["CZ"])


def test_no_false_positives():
    assert detect_languages("Dabble.and.Tito.2019.1080p.mkv") == ([], [])
    assert detect_languages("GoPro - Tomorrowland in 4K.mp4") == ([], [])
    # samotné „dab“ bývá slovo názvu
    assert detect_languages("Dab.2019.1080p.mkv") == ([], [])
    assert detect_languages("The.Dab.Experiment.2019.mkv") == ([], [])
    assert detect_languages("Film.2020.bez.titulku.mkv") == ([], [])


def test_dub_and_subtitles_in_different_languages():
    # slovenský dabing s českými titulky – běžný tvar názvu na Webshare
    assert detect_languages("Film.2020.SK.Dabing.CZ.titulky.mkv") == (["SK"], ["CZ"])
    assert detect_languages("Film.2020.CZ.dabing.EN.titulky.mkv") == (["CZ"], ["EN"])
    assert detect_languages("Film.2020.dabing.CZ.titulky.mkv") == (["CZ"], ["CZ"])
    assert detect_languages("Film.2020.CZ.dab.mkv") == (["CZ"], [])
    # anglické značky mají jazyk za slovem: dabing CZ, titulky EN
    assert detect_languages("Film.dub.CZ.sub.EN.mkv") == (["CZ"], ["CZ", "EN"])
    assert "CZ" in detect_languages("Film.audio.CZ.subs.EN.mkv")[0]
    assert "CZ" in detect_languages("Film.2020.lang.CZ.subtitles.EN.mkv")[0]


def test_language_tag_and_preference():
    dub = normalize_source({"name": "Film.2020.CZ.Dabing.mkv"})
    subs = normalize_source({"name": "Film.2020.EN.CZ.titulky.mkv"})
    both = normalize_source({"name": "Film.2020.CZ.dabing.CZ.titulky.mkv"})
    plain = normalize_source({"name": "Film.2020.1080p.mkv"})
    assert language_tag(dub) == ("CZ", "audio")
    assert language_tag(subs) == ("CZ", "subs")
    assert language_tag(plain) == ("", "")
    assert matches_language_preference(dub, "cz_audio") and not matches_language_preference(dub, "cz_subs")
    assert matches_language_preference(subs, "cz_subs") and not matches_language_preference(subs, "cz_audio")
    assert matches_language_preference(both, "cz_audio")
    assert not any(matches_language_preference(s, "") for s in (dub, subs, plain))


if __name__ == "__main__":
    import inspect
    import sys
    count = 0
    for name, fn in inspect.getmembers(sys.modules[__name__], inspect.isfunction):
        if name.startswith("test_"):
            fn()
            count += 1
    print(f"jazyk: {count} testů prošlo")
