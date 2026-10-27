# -*- coding: utf-8 -*-
"""Kodi-friendly Webshare source metadata and label helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

_LANGUAGE_ALIASES = (
    ("CZ", ("cz", "czech", "cesky", "česky", "cestina", "čeština")),
    ("SK", ("sk", "slovak", "slovensky", "slovenský", "slovencina", "slovenčina")),
    ("EN", ("en", "eng", "english")),
    ("JA", ("ja", "jpn", "japanese", "japan")),
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

    normalized = re.sub(r"[._\-+\[\]()]", " ", _clean_text(text).lower())
    all_langs = _languages_from_text(normalized)

    audio_patterns = (
        # not followed by the Czech "titulky": "SK dabing CZ titulky" is a Slovak dub with Czech subtitles.
        # English tags put the language after the word ("dub CZ sub EN"), there the language belongs to the dub.
        r"(?:audio|dub(?:bing)?|dab(?:ing)?|lang(?:uage)?)\s+(?P<lang>cz|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|japanese)"
        r"(?!\s+titulk)",
        r"(?P<lang>cz|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|japanese)\s+(?:audio|dub(?:bing)?|dab(?:ing)?|lang(?:uage)?)",
    )
    for pattern in audio_patterns:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            for lang in _languages_from_text(match.group("lang")):
                _append_unique(audio_langs, lang)

    subtitle_patterns = (
        r"(?P<lang>cz|czech|cesky|česky|sk|slovak|slovensky|en|eng|english)\s+(?:titulk\w*|subs?|subtitles?)",
        r"(?:titulk\w*|subs?|subtitles?)\s+(?P<lang>cz|czech|cesky|česky|sk|slovak|slovensky|en|eng|english|ja|japanese)",
    )
    for pattern in subtitle_patterns:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            for lang in _languages_from_text(match.group("lang")):
                _append_unique(subtitle_langs, lang)

    embedded_subs = re.search(r"(?:vlo[zž]en[éeýy]?|embedded\s+subs?)", normalized, re.IGNORECASE)
    if embedded_subs:
        for lang in all_langs:
            _append_unique(subtitle_langs, lang)

    # A bare language token in a release name usually describes audio/dubbing, not subtitles.
    for lang in all_langs:
        if lang not in subtitle_langs:
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
    """Title-only label for rows where artwork already shows the quality badge."""
    return ellipsize(source.get("title") or source.get("original_name") or "Unknown source", max_title)


def source_icon_name(source: Dict[str, Any]) -> str:
    """Return the bundled icon filename for a normalized source quality."""
    quality = (source.get("quality_label") or "SD").upper()
    return {
        "4K": "4K.png",
        "FHD": "FHD.png",
        "HD": "hd.png",
    }.get(quality, "sd.png")
