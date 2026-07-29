"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Format = Literal["video", "audio"]
Quality = Literal["best", "2160", "1440", "1080", "720", "480"]


class VideoItem(BaseModel):
    """A single video, as listed from a channel or resolved from a link."""

    id: str
    url: str
    title: str
    duration: Optional[float] = None  # seconds
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    upload_date: Optional[str] = None  # YYYYMMDD
    view_count: Optional[int] = None
    downloaded: bool = False  # present in the download archive


ChannelTab = Literal["videos", "shorts"]


class ResolveRequest(BaseModel):
    url: str
    # Which channel content tab to list. Ignored for direct video/playlist links.
    tab: ChannelTab = "videos"


class ResolveResponse(BaseModel):
    kind: Literal["video", "channel", "playlist"]
    title: Optional[str] = None
    uploader: Optional[str] = None
    channel_url: Optional[str] = None
    items: list[VideoItem]
    total: int = 0            # number of videos returned (the true catalog size, up to the cap)
    truncated: bool = False   # True if the channel has more videos than we fetched


class DownloadRequest(BaseModel):
    items: list[VideoItem]
    format: Format = "video"
    quality: Quality = "best"
    # Optional per-request override of the channel folder name.
    channel: Optional[str] = None


class Job(BaseModel):
    id: str
    video_id: str
    title: str
    channel: Optional[str] = None
    format: Format
    quality: Quality
    status: Literal["queued", "downloading", "processing", "completed", "error", "skipped", "cancelled"]
    progress: float = 0.0  # 0-100
    speed: Optional[str] = None
    eta: Optional[str] = None
    size: Optional[str] = None
    filepath: Optional[str] = None
    error: Optional[str] = None
    url: str


class HistoryEntry(BaseModel):
    """A completed download, persisted to the library."""

    id: str
    video_id: str
    title: str
    channel: Optional[str] = None
    format: Format
    quality: Quality
    size: Optional[str] = None
    filepath: Optional[str] = None
    thumbnail: Optional[str] = None
    url: str
    downloaded_at: float  # epoch seconds


class SavedChannel(BaseModel):
    id: str
    name: str
    url: str
    handle: Optional[str] = None
    thumbnail: Optional[str] = None


class Settings(BaseModel):
    download_dir: str
    default_format: Format = "video"
    default_quality: Quality = "best"
    concurrency: int = 3
    per_channel_folders: bool = True
    audio_codec: Literal["mp3", "m4a"] = "mp3"
    # Max videos to pull from a channel in one fetch. The whole catalog (up to
    # this cap) is loaded so the UI can sort/paginate across it client-side.
    list_limit: int = 200
