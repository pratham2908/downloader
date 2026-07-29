"""Unit tests for URL handling and download-option building (no network)."""
from pathlib import Path

from app import config
from app import ytdlp_service as yt
from app.models import Settings


def test_apply_cookies_file(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_FILE", "/data/cookies.txt")
    monkeypatch.setattr(config, "COOKIES_FROM_BROWSER", None)
    assert yt.apply_cookies({})["cookiefile"] == "/data/cookies.txt"


def test_apply_cookies_from_browser(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_FILE", None)
    monkeypatch.setattr(config, "COOKIES_FROM_BROWSER", "chrome")
    assert yt.apply_cookies({})["cookiesfrombrowser"] == ("chrome",)


def test_apply_cookies_none(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_FILE", None)
    monkeypatch.setattr(config, "COOKIES_FROM_BROWSER", None)
    assert yt.apply_cookies({}) == {}


def test_resolve_cookie_file_prefers_explicit_file(tmp_path):
    assert config.resolve_cookie_file("some content", "/x/cookies.txt", str(tmp_path)) == "/x/cookies.txt"


def test_resolve_cookie_file_materializes_content(tmp_path):
    content = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tX\tY\n"
    path = config.resolve_cookie_file(content, None, str(tmp_path))
    assert path is not None
    assert Path(path).read_text() == content


def test_resolve_cookie_file_none_when_empty(tmp_path):
    assert config.resolve_cookie_file(None, None, str(tmp_path)) is None
    assert config.resolve_cookie_file("   ", None, str(tmp_path)) is None


def test_download_opts_includes_cookies(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COOKIES_FILE", "/data/cookies.txt")
    monkeypatch.setattr(config, "COOKIES_FROM_BROWSER", None)
    opts = yt.build_download_opts(Settings(download_dir=str(tmp_path)),
                                  "video", "best", "Chan", lambda d: None)
    assert opts["cookiefile"] == "/data/cookies.txt"


SAMPLE_RSS = """<?xml version="1.0"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <title>Channel</title>
  <published>2010-07-21T07:18:02+00:00</published>
  <entry>
    <yt:videoId>AAA111</yt:videoId>
    <published>2026-07-17T13:28:38+00:00</published>
  </entry>
  <entry>
    <yt:videoId>BBB222</yt:videoId>
    <published>2026-06-05T09:00:00+00:00</published>
  </entry>
</feed>"""


def test_parse_rss_dates_pairs_id_to_date():
    dates = yt.parse_rss_dates(SAMPLE_RSS)
    assert dates == {"AAA111": "20260717", "BBB222": "20260605"}


def test_parse_rss_dates_ignores_channel_published():
    # The feed-level 2010 <published> must not leak in as a video date.
    assert "20100721" not in yt.parse_rss_dates(SAMPLE_RSS).values()


def test_parse_rss_dates_empty_on_garbage():
    assert yt.parse_rss_dates("not xml at all") == {}


def test_is_channel_url():
    assert yt.is_channel_url("https://youtube.com/@veritasium")
    assert yt.is_channel_url("https://www.youtube.com/channel/UCabc")
    assert yt.is_channel_url("https://www.youtube.com/c/mkbhd")
    assert not yt.is_channel_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not yt.is_channel_url("https://youtu.be/dQw4w9WgXcQ")


def test_normalize_channel_url_appends_videos():
    assert yt.normalize_channel_url("https://youtube.com/@veritasium") == \
        "https://youtube.com/@veritasium/videos"
    # already a tab -> untouched
    assert yt.normalize_channel_url("https://youtube.com/@veritasium/videos") == \
        "https://youtube.com/@veritasium/videos"
    # a video link -> untouched
    v = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert yt.normalize_channel_url(v) == v


def test_normalize_channel_url_shorts_tab():
    assert yt.normalize_channel_url("https://youtube.com/@veritasium", "shorts") == \
        "https://youtube.com/@veritasium/shorts"
    # explicit videos tab is the default
    assert yt.normalize_channel_url("https://youtube.com/@veritasium", "videos") == \
        "https://youtube.com/@veritasium/videos"
    # a URL that already targets a tab is honoured, whatever tab was asked for
    assert yt.normalize_channel_url("https://youtube.com/@veritasium/shorts", "videos") == \
        "https://youtube.com/@veritasium/shorts"
    # a plain video link is never touched
    v = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert yt.normalize_channel_url(v, "shorts") == v


def test_strip_channel_tab():
    assert yt.strip_channel_tab("https://youtube.com/@x/videos") == "https://youtube.com/@x"
    assert yt.strip_channel_tab("https://youtube.com/@x/shorts") == "https://youtube.com/@x"
    assert yt.strip_channel_tab("https://youtube.com/@x/shorts/") == "https://youtube.com/@x"
    # no tab -> unchanged (trailing slash trimmed)
    assert yt.strip_channel_tab("https://youtube.com/channel/UCabc") == \
        "https://youtube.com/channel/UCabc"


def test_sanitize_folder():
    assert yt.sanitize_folder("Veritasium") == "Veritasium"
    assert yt.sanitize_folder("Bad/Name:With*Chars?") == "Bad Name With Chars"
    assert yt.sanitize_folder("   ") == "Unknown Channel"


def test_thumbnail_for():
    assert yt.thumbnail_for("abc123") == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


def _settings(tmp):
    return Settings(download_dir=str(tmp))


def test_highest_index_empty_and_missing(tmp_path):
    assert yt.highest_index(tmp_path) == 0                    # no numbered files
    assert yt.highest_index(tmp_path / "nope") == 0           # folder doesn't exist


def test_highest_index_is_numeric_not_lexical(tmp_path):
    for name in ("1. a.mp4", "9. b.mp4", "10. c.mp4", "not numbered.mp4"):
        (tmp_path / name).write_bytes(b"")
    # Lexically "9." > "10."; we must compare as numbers.
    assert yt.highest_index(tmp_path) == 10


def test_reserve_index_continues_and_is_unique(tmp_path):
    (tmp_path / "3. existing.mp4").write_bytes(b"")
    assert yt.reserve_index(tmp_path) == 4
    assert yt.reserve_index(tmp_path) == 5   # in-flight reservation remembered


def test_reserve_index_is_threadsafe(tmp_path):
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(lambda _: yt.reserve_index(tmp_path), range(20)))
    assert sorted(got) == list(range(1, 21))   # every number handed out exactly once


def test_outtmpl_has_index_prefix_for_channel(tmp_path):
    s = Settings(download_dir=str(tmp_path))
    opts = yt.build_download_opts(s, "video", "best", "Chan", lambda d: None)
    assert Path(opts["outtmpl"]).name.startswith("1. ")


def test_outtmpl_has_no_prefix_without_channel_folders(tmp_path):
    s = Settings(download_dir=str(tmp_path), per_channel_folders=False)
    opts = yt.build_download_opts(s, "video", "best", "Chan", lambda d: None)
    assert not yt.INDEX_RE.match(Path(opts["outtmpl"]).name)


def test_build_download_opts_video_quality(tmp_path):
    opts = yt.build_download_opts(_settings(tmp_path), "video", "1080", "Chan", lambda d: None)
    assert opts["merge_output_format"] == "mp4"
    assert "height<=?1080" in opts["format"]
    assert opts["outtmpl"].endswith("[%(id)s].%(ext)s")
    assert "Chan" in opts["outtmpl"]  # per-channel folder


def test_build_download_opts_video_best(tmp_path):
    opts = yt.build_download_opts(_settings(tmp_path), "video", "best", None, lambda d: None)
    assert opts["format"] == "bv*+ba/b"
    assert "height" not in opts["format"]


def test_build_download_opts_audio(tmp_path):
    s = Settings(download_dir=str(tmp_path), audio_codec="mp3")
    opts = yt.build_download_opts(s, "audio", "best", "Chan", lambda d: None)
    assert opts["format"] == "ba/b"
    pp = opts["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert "merge_output_format" not in opts


def _history(tmp_path, monkeypatch):
    """Point the library at a temp file and return the store module."""
    from app import store
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    return store


def _hist_entry(store_mod, video_id, filepath):
    from app.models import HistoryEntry
    store_mod.add_history(HistoryEntry(
        id=video_id, video_id=video_id, title="t", format="video",
        quality="best", url="u", filepath=filepath, downloaded_at=1.0))


def test_downloaded_ids_survives_download_dir_change(tmp_path, monkeypatch):
    """Moving the download folder loses the archive, but the library remembers."""
    store_mod = _history(tmp_path, monkeypatch)
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"x")
    _hist_entry(store_mod, "KEEP1", str(kept))

    empty_dir = tmp_path / "new-downloads"
    empty_dir.mkdir()
    s = Settings(download_dir=str(empty_dir))

    assert yt.load_archive_ids(s) == set()          # archive is gone...
    assert "KEEP1" in yt.downloaded_ids(s)          # ...library still knows


def test_downloaded_ids_drops_deleted_files(tmp_path, monkeypatch):
    store_mod = _history(tmp_path, monkeypatch)
    _hist_entry(store_mod, "GONE1", str(tmp_path / "never-existed.mp4"))
    s = Settings(download_dir=str(tmp_path / "dl"))
    assert "GONE1" not in yt.downloaded_ids(s)


def test_library_overrides_stale_archive_entry(tmp_path, monkeypatch):
    """Archive says downloaded, but the library knows the file was deleted."""
    store_mod = _history(tmp_path, monkeypatch)
    _hist_entry(store_mod, "GONE1", str(tmp_path / "deleted.mp4"))

    dl = tmp_path / "dl"
    dl.mkdir()
    s = Settings(download_dir=str(dl))
    (dl / ".download-archive-video.txt").write_text("youtube GONE1\nyoutube OLD99\n")

    ids = yt.downloaded_ids(s)
    assert "GONE1" not in ids   # library's "file is gone" wins
    assert "OLD99" in ids       # archive-only (pre-library) entries still trusted


def test_archive_is_format_aware(tmp_path):
    s = _settings(tmp_path)
    yt.archive_path(s, "video").write_text("youtube vid123\n", encoding="utf-8")
    yt.archive_path(s, "audio").write_text("youtube aud456\n", encoding="utf-8")

    # Per-format lookups are isolated...
    assert yt.load_archive_ids(s, "video") == {"vid123"}
    assert yt.load_archive_ids(s, "audio") == {"aud456"}
    # ...so a video already grabbed as MP4 is NOT considered done as audio.
    assert "vid123" not in yt.load_archive_ids(s, "audio")
    # The badge (no fmt) sees the union across all formats.
    assert yt.load_archive_ids(s) == {"vid123", "aud456"}


def test_resolve_routes_to_shorts_tab(tmp_path, monkeypatch):
    """resolve(..., tab='shorts') must extract from the channel's /shorts tab
    and hand back a tab-free channel_url."""
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            captured["url"] = url
            return {
                "_type": "playlist",
                "title": "Chan – Shorts",
                "uploader": "Chan",
                "channel_url": "https://youtube.com/@chan/shorts",
                "entries": [{"id": "s1", "title": "Short 1", "ie_key": "Youtube"}],
            }

    monkeypatch.setattr(yt, "YoutubeDL", FakeYDL)
    res = yt.resolve("https://youtube.com/@chan", Settings(download_dir=str(tmp_path)), tab="shorts")

    assert captured["url"] == "https://youtube.com/@chan/shorts"
    assert res.kind == "channel"
    assert res.channel_url == "https://youtube.com/@chan"  # tab stripped
    assert [i.id for i in res.items] == ["s1"]


def test_per_channel_folders_disabled(tmp_path):
    s = Settings(download_dir=str(tmp_path), per_channel_folders=False)
    opts = yt.build_download_opts(s, "video", "best", "Chan", lambda d: None)
    assert "Chan" not in opts["outtmpl"]
