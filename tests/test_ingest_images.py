"""Tests for the image naming that keeps same-stem originals apart.

``_remove_images`` deletes files from a directory that clippings and PDF figures
share, so the cases that matter are the ones it must leave alone: another
original's images, files with a name that only resembles its own, and anything
that is not a file.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import re

from okf_kb import ingest

NAMESPACE = "0123abcd"


def test_namespace_is_eight_hex_digits_and_follows_the_path():
    first = ingest._image_namespace("raw/a/report.docx")

    assert re.fullmatch(r"[0-9a-f]{8}", first)
    assert first == ingest._image_namespace("raw/a/report.docx")
    assert first != ingest._image_namespace("raw/b/report.docx")


def test_remove_images_deletes_only_files_of_its_own_namespace(tmp_path):
    own = [
        f"image-{NAMESPACE}-001.png",
        f"image-{NAMESPACE}-002.jpg",
        f"image-{NAMESPACE}-1000.svg",
    ]
    others = [
        "clipping.png",
        "image-001.png",
        "image-ffffffff-001.png",
        f"image-{NAMESPACE}x-001.png",
        f"image-{NAMESPACE}-abc.png",
        f"image-{NAMESPACE}-001.png.bak",
        "page-001-1.png",
    ]
    for name in (*own, *others):
        (tmp_path / name).write_bytes(b"x")
    lookalike = tmp_path / f"image-{NAMESPACE}-003.png"
    lookalike.mkdir()

    ingest._remove_images(tmp_path, NAMESPACE)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [*others, lookalike.name],
    )


def test_remove_images_accepts_a_missing_directory(tmp_path):
    ingest._remove_images(tmp_path / "absent", NAMESPACE)

    assert not (tmp_path / "absent").exists()
