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
    used |= {int(x) for x in re.findall(r"getLocalizedString\((\d{5})", code)}
    for block in re.findall(r"(?:SORT_LABELS|_LABELS)\s*=\s*\[([^\]]*)\]", code):
        used |= {int(x) for x in re.findall(r"\d{5}", block)}
    used |= {int(x) for x in re.findall(r'\("[a-z_]+", (\d{5}),', code)}  # položky menu
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("zdroje: OK")
