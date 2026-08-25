"""Command-line entry point for ``kb-video``.

The tool exposes four primitives that Claude orchestrates via the ``/video``
slash command:

    kb-video fetch <url>                    # stage metadata, captions, audio, video
    kb-video whisper <video_id>             # re-transcribe audio with MLX Whisper
    kb-video frames <video_id> <ts...>      # extract frames into scratch
    kb-video cleanup <video_id>             # remove the scratch directory
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from okf_kb.video.pipeline import (
    IngestionError,
    cmd_cleanup,
    cmd_fetch,
    cmd_frames,
    cmd_whisper,
)


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the right subcommand based on argv."""
    parser = argparse.ArgumentParser(
        prog="kb-video",
        description="Stage and process YouTube videos for /video → raw/videos/.",
    )
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        default=Path("video_scratch"),
        help="Root scratch directory (default: video_scratch).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch",
        help="Download metadata, captions, audio, and low-res video to scratch.",
    )
    fetch.add_argument("url", help="YouTube URL or video ID.")

    whisper = sub.add_parser(
        "whisper",
        help="Transcribe the staged audio file with MLX Whisper.",
    )
    whisper.add_argument("video_id")
    whisper.add_argument(
        "--model",
        default="mlx-community/whisper-large-v3-mlx",
        help="MLX Whisper model id (default: mlx-community/whisper-large-v3-mlx).",
    )

    frames = sub.add_parser(
        "frames",
        help="Extract frames at given timestamps into the scratch frames/ dir.",
    )
    frames.add_argument("video_id")
    frames.add_argument(
        "timestamps",
        nargs="+",
        help="Timestamps as SS, MM:SS, or HH:MM:SS.",
    )

    cleanup = sub.add_parser(
        "cleanup",
        help="Remove the scratch directory for a video.",
    )
    cleanup.add_argument("video_id")

    args = parser.parse_args(argv)

    try:
        if args.command == "fetch":
            cmd_fetch(args.url, args.scratch_dir)
        elif args.command == "whisper":
            cmd_whisper(args.video_id, args.scratch_dir, args.model)
        elif args.command == "frames":
            cmd_frames(args.video_id, args.scratch_dir, args.timestamps)
        elif args.command == "cleanup":
            cmd_cleanup(args.video_id, args.scratch_dir)
    except IngestionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
