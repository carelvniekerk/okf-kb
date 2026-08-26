"""yt-dlp wrappers — metadata, audio, video, subtitles, and timestamp utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from okf_kb import extras

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Chapter:
    """Represents a chapter in the video."""

    start_seconds: float
    title: str

    @property
    def timestamp(self) -> str:
        """Render the chapter start time as hh:mm:ss for display."""
        return _seconds_to_hms(self.start_seconds)


@dataclass
class VideoMetadata:
    """Metadata about a YouTube video, extracted via yt-dlp."""

    video_id: str
    title: str
    channel: str
    description: str
    duration_seconds: int
    upload_date: str  # YYYY-MM-DD
    url: str
    chapters: list[Chapter] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def duration_human(self) -> str:
        """Render the duration as hh:mm:ss for display."""
        return _seconds_to_hms(self.duration_seconds)

    @property
    def duration_badge(self) -> str:
        """Short badge version of the duration, e.g. '1h23m'."""
        h, rem = divmod(self.duration_seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h{m:02d}m"
        if m:
            return f"{m}m"
        return f"0m{s:02d}s"


_YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
}


def fetch_metadata(url: str) -> VideoMetadata:
    """Resolve a YouTube URL or ID into a structured metadata record."""
    with extras.required("video"):
        from yt_dlp import YoutubeDL  # noqa: PLC0415  # ty: ignore[unresolved-import]

    with YoutubeDL(_YDL_BASE_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise RuntimeError("yt-dlp returned no metadata")  # noqa: EM101, TRY003

    upload_raw = info.get("upload_date")  # 'YYYYMMDD'
    if upload_raw and len(upload_raw) == 8:  # noqa: PLR2004
        upload_date = datetime.strptime(upload_raw, "%Y%m%d").strftime("%Y-%m-%d")
    else:
        upload_date = "unknown"

    chapters_raw = info.get("chapters") or []
    chapters = [
        Chapter(start_seconds=float(c.get("start_time", 0.0)), title=c.get("title", ""))
        for c in chapters_raw
        if c.get("title")
    ]

    return VideoMetadata(
        video_id=info["id"],
        title=info.get("title", "(untitled)"),
        channel=info.get("uploader") or info.get("channel") or "(unknown channel)",
        description=info.get("description") or "",
        duration_seconds=int(info.get("duration") or 0),
        upload_date=upload_date,
        url=info.get("webpage_url") or url,
        chapters=chapters,
        tags=[t for t in (info.get("tags") or []) if isinstance(t, str)],
    )


def download_audio(url: str, workdir: Path) -> Path:
    """Download audio-only stream and re-encode to 16 kHz mono WAV for Whisper."""
    output_template = str(workdir / "audio.%(ext)s")
    opts = {
        **_YDL_BASE_OPTS,
        "skip_download": False,
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "overwrites": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            },
        ],
        # Force 16k mono via ffmpeg postprocessor args — Whisper's expected input.
        "postprocessor_args": ["-ar", "16000", "-ac", "1"],
    }
    with extras.required("video"):
        from yt_dlp import YoutubeDL  # noqa: PLC0415  # ty: ignore[unresolved-import]

    with YoutubeDL(opts) as ydl:
        ydl.download([url])

    wav_path = workdir / "audio.wav"
    if not wav_path.exists():
        raise RuntimeError("audio extraction did not produce audio.wav")  # noqa: EM101, TRY003
    return wav_path


def download_video(url: str, workdir: Path, max_height: int = 720) -> Path:
    """Download a video stream for frame extraction.

    Pulls a video-only stream at the chosen resolution cap. Frames are
    extracted via ffmpeg later — we don't need audio in this file because
    download_audio already produced a clean WAV.
    """
    output_template = str(workdir / "video.%(ext)s")
    opts = {
        **_YDL_BASE_OPTS,
        "skip_download": False,
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]"
            f"/best[height<={max_height}][ext=mp4]"
            f"/worst[ext=mp4]/worst"
        ),
        "outtmpl": output_template,
        "overwrites": True,
        "merge_output_format": "mp4",
    }
    with extras.required("video"):
        from yt_dlp import YoutubeDL  # noqa: PLC0415  # ty: ignore[unresolved-import]

    with YoutubeDL(opts) as ydl:
        ydl.download([url])

    # yt-dlp may save as .mp4, .webm, or .mkv depending on what was available.
    candidates = sorted(workdir.glob("video.*"))
    if not candidates:
        raise RuntimeError("video download produced no file")  # noqa: EM101, TRY003
    mp4 = workdir / "video.mp4"
    if mp4.exists():
        return mp4
    # ffmpeg detects format from content — rename whatever landed to .mp4.
    candidates[0].rename(mp4)
    return mp4


def download_subtitles(url: str, workdir: Path) -> Path | None:
    """Try to fetch subtitles (manual preferred, auto as fallback).

    Returns the VTT file path if anything usable was retrieved, else None.
    """
    output_template = str(workdir / "subs.%(ext)s")
    opts = {
        **_YDL_BASE_OPTS,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-GB", "en-US"],
        "subtitlesformat": "vtt",
        "outtmpl": output_template,
        "overwrites": True,
    }
    with extras.required("video"):
        from yt_dlp import YoutubeDL  # noqa: PLC0415  # ty: ignore[unresolved-import]

    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception:  # noqa: BLE001
        return None

    # yt-dlp names the file something like 'subs.en.vtt' — find whichever variant landed
    candidates = sorted(workdir.glob("subs.*.vtt"))
    if not candidates:
        return None
    # Prefer manual ('en') over automatic ('en-orig' or similar) when both exist.
    for preferred in ("subs.en.vtt", "subs.en-GB.vtt", "subs.en-US.vtt"):
        match = workdir / preferred
        if match.exists():
            return match
    return candidates[0]


def slugify_title(title: str) -> str:
    """Filesystem-safe slug for filenames, capped at a sensible length."""
    with extras.required("video"):
        from slugify import slugify  # noqa: PLC0415  # ty: ignore[unresolved-import]

    slug = slugify(title, max_length=60, word_boundary=True, save_order=True)
    # python-slugify returns empty string for purely non-ASCII titles; fall back.
    return slug or "video"


def parse_timestamp(ts: str) -> float:
    """Parse a timestamp string into seconds.

    Accepts: ``SS``, ``SS.fff``, ``MM:SS``, ``HH:MM:SS``.
    """
    s = ts.strip()
    if not s:
        raise ValueError("empty timestamp")  # noqa: EM101, TRY003
    if ":" not in s:
        return float(s)
    parts = s.split(":")
    if len(parts) == 2:  # noqa: PLR2004
        m, sec = parts
        return int(m) * 60 + float(sec)
    if len(parts) == 3:  # noqa: PLR2004
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    raise ValueError(f"unrecognized timestamp format: {ts!r}")  # noqa: EM102, TRY003


def seconds_to_filename(seconds: float) -> str:
    """Filename-safe ``HHhMMmSSs`` form, e.g. ``00h02m34s``."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}h{m:02d}m{s:02d}s"


def _seconds_to_hms(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# Used by transcribe.py to render inline timestamp markers.
def seconds_to_hms(seconds: float) -> str:
    """Convert a raw seconds value into hh:mm:ss for display."""
    return _seconds_to_hms(seconds)
