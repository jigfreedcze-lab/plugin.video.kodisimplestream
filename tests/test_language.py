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
    assert detect_languages("Film.dub.CZ.sub.EN.mkv") == (["CZ"], ["EN"])
    assert "CZ" in detect_languages("Film.audio.CZ.subs.EN.mkv")[0]
    assert "CZ" in detect_languages("Film.2020.lang.CZ.subtitles.EN.mkv")[0]
    # jazyk před slovem dub patří dabingu, jazyk za ním zůstane titulkům
    assert detect_languages("Film.CZ_EN.dub_CZ.sub.mkv") == (["EN", "CZ"], ["CZ"])
    assert detect_languages("Film.CZ+EN.dub.CZ.sub.mkv") == (["CZ", "EN"], ["CZ"])
    assert detect_languages("Film.CZ.dub.EN.sub.mkv") == (["CZ"], ["EN"])
    assert detect_languages("Film.JAP.dub_ENG.sub.mp4") == (["JA"], ["EN"])


def test_japanese_release_tag():
    # „JAP“ je běžná značka japonského zvuku
    assert detect_languages("Show.DUAL-AUDIO.JAP-ENG.mkv") == (["JA", "EN"], [])
    assert detect_languages("Show.S01E01.DUAL-AUDIO.JAP-ENG.(CZ titulky).mkv") == (["JA", "EN"], ["CZ"])
    # „ja“ jen jako celé slovo, ne začátek jména
    assert detect_languages("Film.CZ-Dabing(janko).mkv") == (["CZ"], [])


def test_short_subtitle_tags():
    # „tit“ a „subt“ jsou zkratky titulků, ne dabing
    assert detect_languages("Film.2020.1080p.CZ.tit.mkv") == ([], ["CZ"])
    assert detect_languages("Film 2020 1080p cz-tit.mkv") == ([], ["CZ"])
    assert detect_languages("Film (2020)_subt.CZ.mkv") == ([], ["CZ"])
    assert detect_languages("Film.2020.1080p.TIT.CZ.mkv") == ([], ["CZ"])
    assert detect_languages("Film.2020.KOREAN.CZ.tit.mkv") == ([], ["CZ"])
    assert detect_languages("Film.2020.SK.Dabing.CZ.tit.mkv") == (["SK"], ["CZ"])
    # vypálené a vložené titulky
    assert detect_languages("Film.2020.EN.hardsub.CZ.mkv") == (["EN"], ["CZ"])
    assert detect_languages("Film.2020.softsubs.CZ.1080p.mkv") == ([], ["CZ"])
    # „tit“ jen jako samostatné slovo
    assert detect_languages("Titanic.1997.CZ.mkv") == (["CZ"], [])
    assert detect_languages("Tit.for.Tat.2020.mkv") == ([], [])
    assert detect_languages("Le.Petit.CZ.mkv") == (["CZ"], [])
    assert detect_languages("Jak.zaplatit.CZ.mkv") == (["CZ"], [])
    assert detect_languages("Film.Petit.CZ.dabing.mkv") == (["CZ"], [])
    assert detect_languages("Subtle.CZ.mkv") == (["CZ"], [])
    assert detect_languages("Film.2020.subtitulky.CZ.mkv") == ([], ["CZ"])


def test_language_used_by_subtitle_tag_and_bare():
    # první CZ je zvuk, druhé patří k titulkům
    assert detect_languages("Film 2020 720p 5.1 CZ + cz tit.mkv") == (["CZ"], ["CZ"])
    assert detect_languages("Film 2020 6ch CZ, FR, tit.CZ.mkv") == (["CZ"], ["CZ"])


def test_joined_dub_languages():
    assert detect_languages("Film (2020) [2160p] [CZ+EN Dabing] [CZ Titulky].mkv") == (["CZ", "EN"], ["CZ"])
    assert detect_languages("Film.2020.CZ+EN.dabing.mkv") == (["CZ", "EN"], [])
    assert detect_languages("Film.2020.1080p.audio.EN,CZ.mkv") == (["CZ", "EN"], [])
    assert detect_languages("Film.2020_Audio.Cz,Eng_Tit.Cz.mkv") == (["CZ", "EN"], ["CZ"])
    assert detect_languages("Film.2020.audio.CZ,EN.titulky.CZ.mkv") == (["CZ", "EN"], ["CZ"])
    assert detect_languages("Film.audio.CZ+ENG.tit.CZ.mkv") == (["CZ", "EN"], ["CZ"])
    # seznam mezi slovem dabing a „titulky“ jsou titulky, stejně jako „SK dabing CZ titulky“
    assert detect_languages("Film.2020.SK.dabing.CZ+EN.titulky.mkv") == (["SK"], ["CZ", "EN"])
    assert detect_languages("Film.2020.dabing.CZ+EN.titulky.mkv") == (["CZ"], ["CZ", "EN"])


def test_subtitle_word_takes_one_language():
    # české slovo bere jazyk před sebou, anglické za sebou; druhý jazyk zůstane zvuku
    assert detect_languages("Film.CZ.tit.EN.mkv") == (["EN"], ["CZ"])
    assert detect_languages("Film.CZ.tit.(EN.audio).mkv") == (["EN"], ["CZ"])
    assert detect_languages("Film.2020.ENG.CZE.sub.CZE.mkv") == (["CZ", "EN"], ["CZ"])
    assert detect_languages("Film.2020.CZ.sub.EN.mkv") == (["CZ"], ["EN"])
    assert detect_languages("Film.2020.CZ.subs.mkv") == ([], ["CZ"])


def test_language_code_boundaries():
    # kód jazyka jen jako celé slovo: „cze“ není „cz“ + zbytek, „czar“ není jazyk
    assert detect_languages("Film.subti.CZE.mkv") == ([], ["CZ"])
    assert detect_languages("Film.subti.Czar.mkv") == ([], [])
    assert detect_languages("Film.2020.CZE.subti.CZE.mkv") == (["CZ"], ["CZ"])
    assert detect_languages("Film.2020.ENG.CZE3x.subti.ENG.mkv") == (["CZ", "EN"], ["EN"])
    assert detect_languages("Ztracen.Dabing.mkv") == (["CZ"], [])


def test_track_count_prefix():
    # „2xCZ“ = dvě české zvukové stopy
    assert detect_languages("Film.2020.1080p.2xCZ.mkv") == (["CZ"], [])
    assert detect_languages("Film 2020 EN 2Xcz 1080p.mkv") == (["CZ", "EN"], [])
    assert detect_languages("Film (2020)(1080p)(4xEN-4xCZ).mkv") == (["CZ", "EN"], [])
    assert detect_languages("Film.2020.CZE3x.mkv") == (["CZ"], [])
    # číslo epizody „1x05“ se jazykem nestane
    assert detect_languages("Film.1x05.1080p.mkv") == ([], [])


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
