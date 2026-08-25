"""Per-command handlers for ``kb-video``.

The Python tool stages raw materials in ``video_scratch/<video_id>/`` and
extracts frames on demand; Claude (via the ``/video`` slash command) does the
quality judgement, picks important timestamps, writes the final article in
``raw/videos/``, moves keeper frames into ``raw/images/``, and runs cleanup.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from typing import TYPE_CHECKING

from okf_kb.video.transcribe import (
    transcribe_with_captions,
    transcribe_with_whisper_audio,
    write_transcript,
)
from okf_kb.video.youtube import (
    VideoMetadata,
    download_audio,
    download_video,
    fetch_metadata,
    parse_timestamp,
    seconds_to_filename,
    slugify_title,
)

if TYPE_CHECKING:
    from pathlib import Path


class IngestionError(RuntimeError):
    """Raised when a kb-video command cannot complete."""


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def cmd_fetch(url: str, scratch_dir: Path) -> None:
    """Stage metadata, captions, audio, and low-res video into ``scratch_dir/<id>/``."""
    try:
        metadata = fetch_metadata(url)
    except Exception as exc:
        raise IngestionError(f"could not fetch metadata: {exc}") from exc  # noqa: EM102, TRY003

    workdir = scratch_dir / metadata.video_id
    workdir.mkdir(parents=True, exist_ok=True)

    slug = slugify_title(metadata.title)

    metadata_path = workdir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            _metadata_to_dict(metadata, slug=slug),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Identifying lines first — Claude parses these to drive subsequent commands.
    print(f"id: {metadata.video_id}")
    print(f"slug: {slug}")
    print(f"title: {metadata.title}")
    print(f"channel: {metadata.channel}")
    print(f"duration: {metadata.duration_human}")
    print(f"scratch: {workdir}")
    print()

    print("→ fetching captions...")
    transcript = transcribe_with_captions(url, workdir)
    if transcript is not None:
        write_transcript(
            transcript,
            workdir / "transcript.md",
            method="youtube_captions",
        )
        print(f"  ✓ transcript.md ({len(transcript.segments)} segments)")
    else:
        (workdir / "transcript.md").write_text(
            "<!-- transcription_method: none -->\n\n"
            "_(no usable captions; run `kb-video whisper` to transcribe locally)_\n",
            encoding="utf-8",
        )
        print("  ⚠ no usable captions — run `kb-video whisper` next")

    print("→ downloading audio for whisper fallback...")
    try:
        audio = download_audio(url, workdir)
    except Exception as exc:
        raise IngestionError(f"audio download failed: {exc}") from exc  # noqa: EM102, TRY003
    print(f"  ✓ {_human_bytes(audio.stat().st_size)} audio.wav")

    print("→ downloading low-res video for frame extraction...")
    try:
        video = download_video(url, workdir)
    except Exception as exc:
        raise IngestionError(f"video download failed: {exc}") from exc  # noqa: EM102, TRY003
    print(f"  ✓ {_human_bytes(video.stat().st_size)} video.mp4")

    print()
    print(f"✓ ready. Inspect {workdir}/transcript.md, then:")
    print(
        f"    kb-video whisper {metadata.video_id}              # if captions are bad",
    )
    print(f"    kb-video frames {metadata.video_id} <ts1> [<ts2> ...]")
    print(f"    kb-video cleanup {metadata.video_id}              # when done")


# ---------------------------------------------------------------------------
# whisper
# ---------------------------------------------------------------------------


def cmd_whisper(video_id: str, scratch_dir: Path, model: str) -> None:
    """Re-transcribe a staged video with MLX Whisper, overwriting transcript.md."""
    workdir = scratch_dir / video_id
    audio = workdir / "audio.wav"
    if not audio.exists():
        raise IngestionError(  # noqa: TRY003
            f"no audio at {audio}; run `kb-video fetch <url>` first",  # noqa: EM102
        )

    print(f"→ transcribing {audio.name} with {model} (this can take a few minutes)...")
    try:
        transcript = transcribe_with_whisper_audio(audio, model)
    except Exception as exc:
        raise IngestionError(f"whisper transcription failed: {exc}") from exc  # noqa: EM102, TRY003

    method = f"whisper:{model.rsplit('/', 1)[-1]}"
    write_transcript(transcript, workdir / "transcript.md", method=method)
    print(f"  ✓ transcript.md ({len(transcript.segments)} segments, method={method})")


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------


def cmd_frames(
    video_id: str,
    scratch_dir: Path,
    timestamps: list[str],
) -> None:
    """Extract frames at given timestamps into ``scratch_dir/<id>/frames/``.

    Frames stay in scratch — the ``/video`` slash command reviews them and only
    moves keepers into ``raw/images/<slug>-<id>/``. Anything left in scratch is
    discarded by ``cmd_cleanup``.
    """
    workdir = scratch_dir / video_id
    video = workdir / "video.mp4"
    if not video.exists():
        raise IngestionError(  # noqa: TRY003
            f"no video at {video}; run `kb-video fetch <url>` first",  # noqa: EM102
        )
    if shutil.which("ffmpeg") is None:
        raise IngestionError(  # noqa: TRY003
            "ffmpeg not found — install with `brew install ffmpeg`",  # noqa: EM101
        )

    output_dir = workdir / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    for ts in timestamps:
        try:
            seconds = parse_timestamp(ts)
        except ValueError as exc:
            raise IngestionError(f"bad timestamp {ts!r}: {exc}") from exc  # noqa: EM102, TRY003

        out = output_dir / f"frame-{seconds_to_filename(seconds)}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{seconds:.2f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True)  # noqa: S603
        except subprocess.CalledProcessError as exc:
            raise IngestionError(f"ffmpeg failed for ts={ts}: {exc}") from exc  # noqa: EM102, TRY003
        print(f"  ✓ {out}")


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def cmd_cleanup(video_id: str, scratch_dir: Path) -> None:
    """Remove ``scratch_dir/<id>/`` — call once the article is written."""
    workdir = scratch_dir / video_id
    if not workdir.exists():
        print(f"(nothing to clean: {workdir} doesn't exist)")
        return
    shutil.rmtree(workdir)
    print(f"✓ removed {workdir}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _metadata_to_dict(metadata: VideoMetadata, slug: str) -> dict:
    d = asdict(metadata)
    d["slug"] = slug
    d["duration_human"] = metadata.duration_human
    d["duration_badge"] = metadata.duration_badge
    return d


def _human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(n)
    for unit in units:
        if size < 1024:  # noqa: PLR2004
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
