"""Transcription paths: YouTube captions (fast) and MLX Whisper (fallback).

The output of either path is a structured ``Transcript`` plus a markdown file
under ``video_scratch/<id>/transcript.md`` for Claude to read and judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator

from okf_kb.video.youtube import (
    download_subtitles,
    seconds_to_hms,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class TranscriptSegment:
    """Transcript text with its start time in seconds."""

    start_seconds: float
    text: str

    @property
    def timestamp(self) -> str:
        """Render the segment start time as hh:mm:ss for display."""
        return seconds_to_hms(self.start_seconds)


@dataclass
class Transcript:
    """Transcript consisting of multiple segments, each with text and a start time."""

    segments: list[TranscriptSegment]

    def render_with_timestamps(self, every_n_seconds: int = 30) -> str:
        """Render with periodic ``[hh:mm:ss]`` markers, ~one paragraph per marker."""
        if not self.segments:
            return "_(empty transcript)_"

        lines: list[str] = []
        last_marker = -1e9
        buffer: list[str] = []

        def flush_buffer() -> None:
            if buffer:
                lines.append(" ".join(buffer).strip())
                buffer.clear()

        for seg in self.segments:
            if seg.start_seconds - last_marker >= every_n_seconds:
                flush_buffer()
                if lines:
                    lines.append("")
                lines.append(f"**[{seg.timestamp}]** {seg.text.strip()}")
                last_marker = seg.start_seconds
            else:
                buffer.append(seg.text.strip())
        flush_buffer()
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# YouTube captions fast-path
# ---------------------------------------------------------------------------

_VTT_TIMESTAMP = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})",
)
_VTT_TAG = re.compile(r"<[^>]+>")  # strip <c>, <00:00:01.000>, etc.


def transcribe_with_captions(url: str, workdir: Path) -> Transcript | None:
    """Pull YouTube subtitles, parse to Transcript with karaoke dedup.

    Returns None if no captions are available or the result looks unusable.
    """
    vtt_path = download_subtitles(url, workdir)
    if vtt_path is None:
        return None

    raw_segments = list(_parse_vtt(vtt_path))
    if not raw_segments:
        return None
    segments = _dedup_karaoke(raw_segments)
    if not segments:
        return None
    if _looks_unusable(segments):
        return None
    return Transcript(segments=segments)


def _parse_vtt(path: Path) -> Generator[TranscriptSegment]:
    """Yield TranscriptSegments (cue text + start time) from a WebVTT file."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw)
    last_text = ""

    for block in blocks:
        match = _VTT_TIMESTAMP.search(block)
        if not match:
            continue
        h, m, s = match.group(1), match.group(2), match.group(3)
        start = int(h) * 3600 + int(m) * 60 + int(s)

        lines: list[str] = []
        seen_timestamp = False
        for line in block.splitlines():
            if not seen_timestamp:
                if _VTT_TIMESTAMP.search(line):
                    seen_timestamp = True
                continue
            cleaned = _VTT_TAG.sub("", line).strip()
            if cleaned:
                lines.append(cleaned)
        text = " ".join(lines).strip()
        if not text or text == last_text:
            continue
        last_text = text
        yield TranscriptSegment(start_seconds=float(start), text=text)


def _dedup_karaoke(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Strip the rolling-window duplication that YouTube auto-captions emit.

    Adjacent cues in auto-VTT typically read like::

        cue 1: "ABCD"
        cue 2: "BCDE"
        cue 3: "CDEF"

    Naively concatenating yields ``ABCD BCDE CDEF`` (the triple-repetition
    artifact). For each cue we keep only the words that didn't already appear
    at the tail of the previous cue.
    """
    if not segments:
        return []
    result = [segments[0]]
    last_full = segments[0].text
    for seg in segments[1:]:
        new_text = _strip_prefix_overlap(seg.text, last_full)
        if new_text:
            result.append(TranscriptSegment(seg.start_seconds, new_text))
        last_full = seg.text
    return result


def _strip_prefix_overlap(text: str, prev: str) -> str:
    """Drop the longest prefix of ``text`` that appears as a suffix of ``prev``."""
    text_words = text.split()
    prev_words = prev.split()
    if not text_words or not prev_words:
        return text.strip()

    max_overlap = min(len(text_words), len(prev_words))
    for n in range(max_overlap, 0, -1):
        if [w.lower() for w in prev_words[-n:]] == [w.lower() for w in text_words[:n]]:
            return " ".join(text_words[n:]).strip()
    return text.strip()


def _looks_unusable(segments: list[TranscriptSegment]) -> bool:
    """Reject pathologically empty caption sets."""
    total_chars = sum(len(s.text) for s in segments)
    return total_chars < 200  # noqa: PLR2004


# ---------------------------------------------------------------------------
# MLX Whisper fallback
# ---------------------------------------------------------------------------


def transcribe_with_whisper_audio(audio_path: Path, model: str) -> Transcript:
    """Run MLX Whisper against a pre-staged audio file."""
    try:
        import mlx_whisper  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(  # noqa: TRY003
            "mlx-whisper is not installed. Install with `uv add mlx-whisper`.",  # noqa: EM101
        ) from exc

    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        word_timestamps=False,
    )
    raw_segments = result.get("segments") or []
    segments = [
        TranscriptSegment(
            start_seconds=float(seg.get("start", 0.0)),
            text=str(seg.get("text", "")).strip(),
        )
        for seg in raw_segments
        if seg.get("text")
    ]
    if not segments:
        raise RuntimeError("Whisper produced no segments")  # noqa: EM101, TRY003
    return Transcript(segments=segments)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_transcript(transcript: Transcript, path: Path, method: str) -> None:
    """Write the transcript to ``path`` with a method header for Claude to read."""
    body = transcript.render_with_timestamps(every_n_seconds=30)
    header = f"<!-- transcription_method: {method} -->\n\n"
    path.write_text(header + body + "\n", encoding="utf-8")
