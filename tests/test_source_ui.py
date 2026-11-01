from resources.lib.source_ui import (
    WARNING_COLOR,
    bitrate_part,
    bitrate_text,
    compact_label,
    detect_audio_format,
    detect_codec,
    detect_languages,
    detect_quality,
    detect_source_type,
    format_size,
    metadata_line,
    normalize_source,
    source_heading,
    source_icon_name,
    source_title_label,
)


def test_format_size_mb_and_gb():
    assert format_size(700 * 1024 * 1024) == "700 MB"
    assert format_size(int(1.6 * 1024 * 1024 * 1024)) == "1.6 GB"


def test_detect_release_metadata():
    text = "Obsession 2026 S02E02 1080p NF WEB-DL DDP5.1 Atmos H.264 EN CZ titulky.mkv"
    assert detect_quality(text) == ("FHD", "1080p")
    assert detect_source_type(text) == "WEB-DL"
    assert detect_codec(text) == "H.264"
    assert detect_audio_format(text) == "DDP5.1"
    audio, subs = detect_languages(text)
    assert audio == ["EN"]
    assert subs == ["CZ"]


def test_detect_4k_h265_and_embedded_subtitles():
    text = "Film.2160p.UHD.BluRay.x265.CZ.vlozene.titulky.mkv"
    assert detect_quality(text) == ("4K", "2160p")
    assert detect_source_type(text) == "BluRay"
    assert detect_codec(text) == "H.265"
    audio, subs = detect_languages(text)
    assert audio == []
    assert subs == ["CZ"]


def test_normalize_source_handles_missing_metadata():
    source = normalize_source({"name": "Episode.720p.WEBRip.audio.Japanese.subs.en.mkv", "size": "734003200", "score": "72"})
    assert source["title"] == "Episode.720p.WEBRip.audio.Japanese.subs.en"
    assert source["quality_label"] == "HD"
    assert source["resolution_label"] == "720p"
    assert source["size_text"] == "700 MB"
    assert source["audio_langs"] == ["JA"]
    assert source["subtitle_langs"] == ["EN"]
    assert source["score"] == 72


def test_source_heading_keeps_modal_rows_short():
    source = normalize_source({
        "name": "Deadpool.2016.UHD.BluRay.2160p.TrueHD.Atmos.x265.CZ.SK.EN.mkv",
        "size": str(14 * 1024 * 1024 * 1024),
        "score": 92,
    })
    label = source_heading(source, max_title=28)
    assert label.startswith("[4K 2160p] Deadpool.2016.UHD.BluRay.21…")
    assert label.endswith("[92]")
    assert "Size" not in label
    assert "Audio" not in label


def test_source_icon_name_uses_existing_icon_filenames():
    assert source_icon_name({"quality_label": "4K"}) == "4K.png"
    assert source_icon_name({"quality_label": "FHD"}) == "FHD.png"
    assert source_icon_name({"quality_label": "HD"}) == "hd.png"
    assert source_icon_name({"quality_label": "SD"}) == "sd.png"


def test_title_label_omits_quality_when_badge_art_is_used():
    source = normalize_source({"name": "The.Matrix.1999.2160p.BluRay.x265.mkv", "size": str(5 * 1024 * 1024 * 1024)})
    assert source_title_label(source) == "The.Matrix.1999.2160p.BluRay.x265"
    assert not source_title_label(source).startswith("[4K 2160p]")
    assert metadata_line(source, include_quality=True).startswith("4K 2160p | Size 5.0 GB")


def test_bitrate_marker_only_over_the_limit():
    assert bitrate_text(45_200_000) == "45 Mbit/s" and bitrate_text(71_600_000, estimated=True) == "≈72 Mbit/s"
    assert bitrate_text(8_440_000) == "8.4 Mbit/s" and bitrate_text(0) == bitrate_text(None) == bitrate_text("x") == ""
    source = normalize_source({"name": "Film.2010.2160p.REMUX.mkv", "size": str(60 * 1024 ** 3)})
    assert bitrate_part(source) == "" and "Mbit" not in metadata_line(source, include_quality=True)
    source.update(bitrate=71_600_000, bitrate_estimated=True, bitrate_over=True)
    marker = f"[COLOR {WARNING_COLOR}]≈72 Mbit/s ![/COLOR]"
    assert bitrate_part(source) == marker
    # the second line: right after the quality (and the length), before the size that a long line cuts off
    assert metadata_line(source, include_quality=True) == f"4K 2160p | {marker} | Size 60.0 GB", metadata_line(source, include_quality=True)
    source.update(length_text="1:58:00")
    assert metadata_line(source, include_quality=True).startswith(f"4K 2160p | 1:58:00 | {marker} | Size")
    assert f"  •  1:58:00 • {marker} • Size" in compact_label(source)
    source.update(bitrate=45_000_000, bitrate_estimated=False)
    assert bitrate_part(source) == f"[COLOR {WARNING_COLOR}]45 Mbit/s ![/COLOR]"
    source.update(bitrate=None)
    assert bitrate_part(source) == ""
