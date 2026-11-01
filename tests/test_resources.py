"""Jazykové soubory a nastavení: každý použitý text existuje v obou jazycích a Kodi ho přečte."""
import os
import re
import xml.etree.ElementTree as ET

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LANGS = ("cs_cz", "en_gb")


def _po_ids(lang):
    path = os.path.join(REPO, "resources", "language", f"resource.language.{lang}", "strings.po")
    text = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    ids = []
    # Kodi (CPODocument) dělí záznamy prázdným řádkem a z každého bere jen první msgctxt
    for entry in text.split("\n\n"):
        found = re.findall(r'^msgctxt "#(\d+)"', entry, re.M)
        assert len(found) <= 1, f"{lang}: záznamy bez prázdného řádku mezi sebou: {found}"
        if found:
            assert re.search(r'^msgid ".*"$', entry, re.M) and re.search(r'^msgstr\s+".*"$', entry, re.M), f"{lang} #{found[0]}"
            ids.append(int(found[0]))
    assert len(ids) == len(set(ids)), f"{lang}: duplicitní ID"
    return set(ids)


def _used_ids():
    used = set()
    code = open(os.path.join(REPO, "kodisimplestream.py"), encoding="utf-8").read()
    # Každé pětimístné číslo 3xxxx v hlavním modulu je ID textu (getLocalizedString, menu, _keyboard_search, …)
    used |= {int(x) for x in re.findall(r"\b3\d{4}\b", code)}
    for setting in ET.parse(os.path.join(REPO, "resources", "settings.xml")).iter():
        for attr in ("label", "lvalues"):
            used |= {int(x) for x in re.findall(r"\d{5}", setting.get(attr) or "")}
    return used


def test_po_files_parse_like_kodi_and_match():
    cs, en = _po_ids("cs_cz"), _po_ids("en_gb")
    assert cs == en, f"jen cs: {sorted(cs - en)}, jen en: {sorted(en - cs)}"


def test_every_used_string_exists():
    known = _po_ids("cs_cz")
    missing = sorted(_used_ids() - known - {30016})  # 30016: nepoužívaný list_videos, chybí odjakživa
    assert not missing, f"chybí v .po: {missing}"


def test_settings_ids_unique():
    ids = [s.get("id") for s in ET.parse(os.path.join(REPO, "resources", "settings.xml")).iter("setting") if s.get("id")]
    assert len(ids) == len(set(ids)), ids



def test_tmdbhelper_player_uses_known_keys():
    """TMDb Helper fills unknown keys with "_" ({tmdb_id}, {show_originaltitle} do not exist, see
    tmdbhelper/lib/player/details.py set_detailed_item): only keys it sets."""
    import json, re
    folder = os.path.join(REPO, "docs", "tmdbhelper")
    players = {name: json.load(open(os.path.join(folder, name), encoding="utf-8"))
               for name in sorted(os.listdir(folder)) if name.endswith(".json")}
    assert set(players) == {"kodisimplestream.json", "kodisimplestream_select.json"}, sorted(players)
    known = {"title", "originaltitle", "year", "imdb", "tmdb", "showname", "tvshowtitle", "season", "episode", "premiered"}
    for name, player in players.items():
        for key in ("play_movie", "play_episode"):
            used = set(re.findall(r"{(\w+)}", player[key]))
            assert used <= known, (name, key, sorted(used - known))
        assert "show_originaltitle={originaltitle}" in player["play_episode"] and "tmdb_id={tmdb}" in player["play_episode"], name
    # The picker player: the main one plus &select=1, its own name and the next priority (TMDb Helper sorts
    # by priority; the user's default player is bound to the file name kodisimplestream.json)
    main, select = players["kodisimplestream.json"], players["kodisimplestream_select.json"]
    assert set(main) == set(select), sorted(set(main) ^ set(select))
    for key in main:
        if key in ("play_movie", "play_episode"):
            assert select[key] == main[key] + "&select=1", key
        elif key == "name":
            assert select[key] != main[key] and select[key].startswith(main[key]), select[key]
        elif key == "priority":
            assert select[key] == main[key] + 1, (main[key], select[key])
        else:
            assert select[key] == main[key], key

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("zdroje: OK")
