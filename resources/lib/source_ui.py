# -*- coding: utf-8 -*-
"""Kodi-friendly Webshare source metadata and label helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

_LANGUAGE_ALIASES = (
    ("CZ", ("cz", "cze", "czech", "cesky", "česky", "cestina", "čeština")),
    ("SK", ("sk", "slovak", "slovensky", "slovenský", "slovencina", "slovenčina")),
    ("EN", ("en", "eng", "english")),
    ("JA", ("ja", "jap", "jpn", "japanese", "japan")),
)

_LANGUAGE_FIELD_HINTS = ("lang", "language", "audio", "subtitle", "subtitles", "subs")
_SUBTITLE_FIELD_HINTS = ("subtitle", "subtitles", "subs", "caption", "captions")
_AUDIO_FIELD_HINTS = ("audio", "dub", "dubbing", "lang", "language")

_VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".ts")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _field_values(result: Any, hints: Iterable[str]) -> List[str]:
    if not isinstance(result, dict):
        return []
    values: List[str] = []
    lowered_hints = tuple(h.lower() for h in hints)
    for key, value in result.items():
        key_text = str(key).lower()
        if not any(hint in key_text for hint in lowered_hints):
            continue
        if isinstance(value, (list, tuple, set)):
            values.extend(_clean_text(v) for v in value if _clean_text(v))
        elif isinstance(value, dict):
            values.extend(_clean_text(v) for v in value.values() if _clean_text(v))
        elif _clean_text(value):
            values.append(_clean_text(value))
    return values


def _append_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _languages_from_text(text: str) -> List[str]:
    if not text:
        return []
    normalized = re.sub(r"[._\-+\[\]()]", " ", text.lower())
    langs: List[str] = []
    for code, aliases in _LANGUAGE_ALIASES:
        for alias in aliases:
            if re.search(r"(^|\W)" + re.escape(alias) + r"($|\W)", normalized, re.IGNORECASE):
                _append_unique(langs, code)
                break
    return langs


def ellipsize(text: Any, max_length: int) -> str:
    value = _clean_text(text)
    if max_length <= 0 or len(value) <= max_length:
        return value
    if max_length <= 1:
        return "…"
    return value[: max_length - 1].rstrip() + "…"


def format_size(size_value: Any) -> str:
    """Format a byte count as a compact Kodi label (for example 700 MB, 1.6 GB)."""
    try:
        size_bytes = int(float(size_value or 0))
    except (TypeError, ValueError):
        return ""
    if size_bytes <= 0:
        return ""

    mb = size_bytes / (1024.0 * 1024.0)
    if mb < 1024:
        if mb >= 100:
            return f"{int(round(mb))} MB"
        return f"{mb:.1f} MB"

    gb = mb / 1024.0
    return f"{gb:.1f} GB"


def detect_quality(text: str) -> Tuple[str, str]:
    normalized = _clean_text(text).lower()
    if re.search(r"(?:2160p|\b4k\b|\buhd\b)", normalized):
        return "4K", "2160p"
    if "1080p" in normalized:
        return "FHD", "1080p"
    if "720p" in normalized:
        return "HD", "720p"
    return "SD", "SD"


def detect_codec(text: str) -> Optional[str]:
    normalized = _clean_text(text).lower()
    if re.search(r"(?:h\.?265|hevc|x265)", normalized):
        return "H.265"
    if re.search(r"(?:h\.?264|avc|x264)", normalized):
        return "H.264"
    return None


def detect_source_type(text: str) -> Optional[str]:
    normalized = _clean_text(text).lower()
    if re.search(r"web[ ._-]?dl", normalized):
        return "WEB-DL"
    if re.search(r"web[ ._-]?rip", normalized):
        return "WEBRip"
    if "hdtv" in normalized:
        return "HDTV"
    if re.search(r"(?:blu[ ._-]?ray|bdrip|br[ ._-]?rip)", normalized):
        return "BluRay"
    if re.search(r"dvd[ ._-]?rip", normalized):
        return "DVDRip"
    return None


def detect_audio_format(text: str) -> Optional[str]:
    normalized = _clean_text(text).lower()
    if re.search(r"(?:ddp|dd\+|eac3|e-ac-3)[ ._-]?(?:5[ ._-]?1)?", normalized):
        return "DDP5.1"
    if "atmos" in normalized:
        return "Atmos"
    if re.search(r"\bac[ ._-]?3\b", normalized):
        return "AC3"
    if re.search(r"\baac\b", normalized):
        return "AAC"
    if re.search(r"\bdts\b", normalized):
        return "DTS"
    return None


def detect_languages(text: str, result: Any = None) -> Tuple[List[str], List[str]]:
    """Return audio and subtitle language codes without guessing beyond available hints."""
    audio_langs: List[str] = []
    subtitle_langs: List[str] = []

    for field_text in _field_values(result, _AUDIO_FIELD_HINTS):
        for lang in _languages_from_text(field_text):
            _append_unique(audio_langs, lang)
    for field_text in _field_values(result, _SUBTITLE_FIELD_HINTS):
        for lang in _languages_from_text(field_text):
            _append_unique(subtitle_langs, lang)

    lowered = _clean_text(text).lower()
    # A track count glued to the code ("2xCZ", "4xEN-4xCZ", "CZE3x") still names the audio language.
    lowered = re.sub(r"(?<![a-z0-9])\d+x(?=(?:cz|cze|sk|en|eng)(?![a-z]))", " ", lowered)
    lowered = re.sub(r"(?<![a-z0-9])(cz|cze|sk|en|eng)\d+x(?![a-z0-9])", r"\1", lowered)
    # "spaced" keeps "+" and "," for language lists, "normalized" is the same text without "+" (same length).
    spaced = re.sub(r"[._\-\[\]()]", " ", lowered)
    normalized = spaced.replace("+", " ")
    all_langs = _languages_from_text(normalized)

    # A code (or tag) assigned by a pattern is blanked out with "#", so the patterns after it and the bare
    # tokens below do not read it again, and a blank never joins the words around it.
    bare = list(spaced)

    def unread() -> str:
        return "".join(bare).replace("+", " ")

    def consume(start: int, end: int) -> None:
        bare[start:end] = "#" * (end - start)

    # A list of languages joined by "+" or "," next to the dub word ("CZ+EN Dabing", "audio.EN,CZ") is all dubs,
    # even if one of them also has subtitles ("[CZ+EN Dabing] [CZ Titulky]").
    # Like a single language, a list between the dub word and "titulky" is the subtitles ("SK dabing CZ+EN titulky"),
    # unless "titulky" has its own language ("audio CZ+EN tit CZ").
    lang_list = r"(?P<langs>(?:cz|cze|sk|en|eng|ja|jap)(?:\s*[+,]\s*(?:cz|cze|sk|en|eng|ja|jap))+)(?!\w)"
    list_patterns = (
        r"(?<!\w)" + lang_list + r"\s+(?:audio|dub(?:bing)?|dab(?:ing)?)(?!\w)",
        r"(?<!\w)(?:audio|dub(?:bing)?|dab(?:ing)?)\s+" + lang_list
        + r"(?P<subs>\s+(?:titulk\w*|tit)(?!\w)(?!\s+(?:cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|jap|japanese)(?!\w)))?",
    )
    for pattern in list_patterns:
        for match in re.finditer(pattern, "".join(bare), re.IGNORECASE):
            subs = match.groupdict().get("subs")
            for lang in _languages_from_text(match.group("langs")):
                _append_unique(subtitle_langs if subs else audio_langs, lang)
            consume(*match.span("langs"))
            if subs:
                consume(*match.span("subs"))

    audio_patterns = (
        # not followed by the Czech "titulky" or "tit": "SK dabing CZ titulky" is a Slovak dub with Czech subtitles.
        # English tags put the language after the word ("dub CZ sub EN"), there the language belongs to the dub.
        # A dub word with its language in front ("CZ_EN.dub_CZ.sub", "CZ+EN dub CZ sub") does not take the one
        # after it, that one is left for the subtitle word.
        r"(?:(?<!\w)(?P<pre>cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|jap|japanese|#+)\s+)?"
        r"(?:audio|dub(?:bing)?|dab(?:ing)?|lang(?:uage)?)\s+(?P<lang>cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|jap|japanese)"
        r"(?!\w)(?!\s+(?:titulk|tit(?!\w)))",
        r"(?<!\w)(?P<lang>cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|jap|japanese)\s+(?:audio|dub(?:bing)?|dab(?:ing)?|lang(?:uage)?)",
    )
    for pattern in audio_patterns:
        for match in re.finditer(pattern, unread(), re.IGNORECASE):
            if match.groupdict().get("pre"):
                continue
            for lang in _languages_from_text(match.group("lang")):
                _append_unique(audio_langs, lang)
            consume(*match.span("lang"))

    # Each subtitle word takes one language. The Czech words take the one before them ("CZ titulky",
    # "CZ tit EN" = EN audio), the English ones the one after them ("dub CZ sub EN", "ENG CZE sub CZE" = EN+CZ
    # audio), the other side only when the preferred one has none ("TIT CZ", "CZ subs"). A code already read as
    # the dub stays the dub. "tit" and "subt" are common short forms ("CZ.tit", "cz-tit", "subt.CZ"), only as
    # whole words, so "Petit CZ" or "subtle CZ" keep CZ as audio.
    sub_lang_before = r"(?<!\w)(?P<lang>cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english)\s+$"
    sub_lang_after = r"\s+(?P<lang>cz|cze|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|jap|japanese)(?!\w)"
    for word in re.finditer(r"(?<!\w)(?:(?P<cs>titulk\w*|tit)|(?:hard|soft)?sub(?:s|bed)?|subt(?:i\w*)?)(?!\w)", unread(), re.IGNORECASE):
        current = unread()
        before = re.search(sub_lang_before, current[:word.start()], re.IGNORECASE)
        after = re.match(sub_lang_after, current[word.end():], re.IGNORECASE)
        sides = ((0, before), (word.end(), after)) if word.group("cs") else ((word.end(), after), (0, before))
        offset, match = next(((start, found) for start, found in sides if found), (0, None))
        if match:
            for lang in _languages_from_text(match.group("lang")):
                _append_unique(subtitle_langs, lang)
            consume(offset + match.start("lang"), offset + match.end("lang"))

    embedded_subs = re.search(r"(?:vlo[zž]en[éeýy]?|embedded\s+subs?)", normalized, re.IGNORECASE)
    if embedded_subs:
        for lang in all_langs:
            _append_unique(subtitle_langs, lang)

    # A bare language token in a release name usually describes audio/dubbing, not subtitles.
    for lang in _languages_from_text(unread()):
        if not (embedded_subs and lang in subtitle_langs):
            _append_unique(audio_langs, lang)

    # Czech words without a language code: "dabing" means a Czech dub, "titulky" Czech subtitles.
    # The short "dab" only next to a language code (patterns above), on its own it is often a title word.
    if not audio_langs and re.search(r"(^|\W)dabing($|\W)", normalized):
        audio_langs.append("CZ")
    if (not subtitle_langs and re.search(r"(^|\W)titulk\w*", normalized)
            and not re.search(r"(^|\W)bez\s+titulk", normalized)):
        subtitle_langs.append("CZ")

    return audio_langs, subtitle_langs


def language_tag(source: Dict[str, Any]) -> Tuple[str, str]:
    """Czech/Slovak dub or subtitles worth a label tag: ("CZ", "audio"), ("SK", "subs") or ("", "")."""
    for kind, key in (("audio", "audio_langs"), ("subs", "subtitle_langs")):
        for lang in ("CZ", "SK"):
            if lang in (source.get(key) or []):
                return lang, kind
    return "", ""


def matches_language_preference(source: Dict[str, Any], preference: str) -> bool:
    """preference: "" (no preference), "cz_audio" (Czech dub) or "cz_subs" (Czech subtitles)."""
    if preference == "cz_audio":
        return "CZ" in (source.get("audio_langs") or [])
    if preference == "cz_subs":
        return "CZ" in (source.get("subtitle_langs") or [])
    return False


def source_score(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("score", "rating", "rank", "relevance"):
        value = result.get(key)
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _display_title(name: str) -> str:
    title = _clean_text(name) or "Unknown source"
    lower = title.lower()
    for ext in _VIDEO_EXTENSIONS:
        if lower.endswith(ext):
            return title[: -len(ext)]
    return title


def normalize_source(result: Dict[str, Any]) -> Dict[str, Any]:
    original_name = _clean_text(result.get("name") or result.get("title"))
    title = _display_title(original_name)
    text = " ".join(_clean_text(part) for part in (original_name, result.get("description"), result.get("type")) if _clean_text(part))
    quality_label, resolution_label = detect_quality(text)
    audio_langs, subtitle_langs = detect_languages(text, result)
    size_bytes = 0
    try:
        size_bytes = int(float(result.get("size") or result.get("size_bytes") or 0))
    except (TypeError, ValueError):
        size_bytes = 0

    return {
        "title": title,
        "original_name": original_name or title,
        "score": source_score(result),
        "quality_label": quality_label,
        "resolution_label": resolution_label,
        "size_bytes": size_bytes,
        "size_text": format_size(size_bytes),
        "audio_langs": audio_langs,
        "subtitle_langs": subtitle_langs,
        "source_type": detect_source_type(text),
        "codec": detect_codec(text),
        "audio_format": detect_audio_format(text),
        "raw": result,
    }


def metadata_parts(source: Dict[str, Any], include_score: bool = False) -> List[str]:
    parts: List[str] = []
    if source.get("size_text"):
        parts.append(f"Size {source['size_text']}")
    if source.get("audio_langs"):
        parts.append("Audio " + "/".join(source["audio_langs"]))
    if source.get("subtitle_langs"):
        parts.append("Subs " + "/".join(source["subtitle_langs"]))
    for key in ("source_type", "audio_format", "codec"):
        if source.get(key):
            parts.append(source[key])
    if include_score and source.get("score") is not None:
        parts.append(f"score {source['score']}")
    return parts


def metadata_line(source: Dict[str, Any], include_score: bool = False, include_quality: bool = False) -> str:
    parts: List[str] = []
    if include_quality:
        quality = source.get("quality_label") or "SD"
        resolution = source.get("resolution_label") or "SD"
        parts.append(f"{quality} {resolution}")
    parts.extend(metadata_parts(source, include_score))
    return " | ".join(parts)


def source_heading(source: Dict[str, Any], max_title: int = 42, include_score: bool = True) -> str:
    """Short single-line source label for Kodi select rows that should not marquee."""
    quality = source.get("quality_label") or "SD"
    resolution = source.get("resolution_label") or "SD"
    title = ellipsize(source.get("title") or source.get("original_name") or "Unknown source", max_title)
    label = f"[{quality} {resolution}] {title}"
    if include_score and source.get("score") is not None:
        label += f"  [{source['score']}]"
    return label


def compact_label(source: Dict[str, Any], include_score: bool = True, max_title: int = 42) -> str:
    """One-line fallback label for skins/Kodi builds without detailed select rows."""
    label = source_heading(source, max_title=max_title, include_score=False)
    parts = metadata_parts(source, include_score=False)[:4]
    if parts:
        label += "  •  " + " • ".join(parts)
    if include_score and source.get("score") is not None:
        label += f"  [{source['score']}]"
    return label


def source_title_label(source: Dict[str, Any], max_title: int = 54) -> str:
    """Title-only label; the quality is shown by the badge artwork or a tag added by the caller."""
    return ellipsize(source.get("title") or source.get("original_name") or "Unknown source", max_title)


def source_icon_name(source: Dict[str, Any]) -> str:
    """Return the bundled icon filename for a normalized source quality."""
    quality = (source.get("quality_label") or "SD").upper()
    return {
        "4K": "4K.png",
        "FHD": "FHD.png",
        "HD": "hd.png",
    }.get(quality, "sd.png")
