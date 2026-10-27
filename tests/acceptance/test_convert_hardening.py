"""Acceptance tests AC-30 to AC-39 of docs/design/convert-hardening.md.

They pin down three things a user can observe. Every markitdown format that the
README advertises converts, makes no network connection and reports a missing
module instead of raising. ``convert --force`` replaces a markdown file whose
frontmatter cannot be read, which is the file ``list-unconverted`` files under
``legacy`` and tells the user to force. Two originals with one stem never share
an image, and a reconversion removes only the images that original wrote.

AC-30 to AC-34 describe behaviour that already exists and only lacked a test, so
they pass before the change. AC-35 to AC-39 fail until it is made.

The ``.xls`` and ``.msg`` files in ``tests/fixtures/documents/`` are synthetic.
``xlwt`` wrote the ``.xls`` and a throwaway compound-file writer wrote the
``.msg``. Neither holds real names, addresses or text.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100, S603, S607, PLC0415, PLR0913, FBT003

from __future__ import annotations

import re
import shutil
import socket
import sys
import zipfile
from pathlib import Path

import pytest
from test_convert import _bundle, _docx, _invoke, _listing, _png, _read, _run_main, _sha

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


# -- fixtures built in code or copied -------------------------------------------


def _epub(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    package = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Test book</dc:title>"
        '<dc:identifier id="id">urn:test</dc:identifier>'
        "<dc:language>en</dc:language></metadata>"
        '<manifest><item id="c1" href="chapter1.xhtml" '
        'media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c1"/></spine></package>'
    )
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head>'
        "<body><h1>Chapter heading</h1><p>The chapter paragraph.</p></body></html>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        archive.writestr("OEBPS/chapter1.xhtml", chapter)
    return path


def _copy_fixture(name: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, path)
    return path


def _xls(path: Path) -> Path:
    return _copy_fixture("budget.xls", path)


def _msg(path: Path) -> Path:
    return _copy_fixture("message.msg", path)


def _linked(md_path: Path) -> list[Path]:
    """Resolve the image links of a converted file, in document order."""
    _, body = _read(md_path)
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)
    return [(md_path.parent / link).resolve() for link in links]


# -- AC-30 to AC-32: the three formats that had no conversion test --------------


def test_ac_30_epub_converts_heading_and_paragraph(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch)
    source = _epub(root / "raw" / "documents" / "book.epub")

    result = _invoke("convert", source)

    assert result.exit_code == 0, result.output
    meta, body = _read(source.with_suffix(".md"))
    assert "Chapter heading" in body
    assert "The chapter paragraph." in body
    assert meta["converter"] == "markitdown"


def test_ac_31_xls_converts_sheet_name_and_cells(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch)
    source = _xls(root / "raw" / "documents" / "budget.xls")

    result = _invoke("convert", source)

    assert result.exit_code == 0, result.output
    _, body = _read(source.with_suffix(".md"))
    assert "Budget" in body
    assert "Licences" in body
    assert "1234" in body


def test_ac_32_msg_converts_subject_sender_and_body(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch)
    source = _msg(root / "raw" / "documents" / "message.msg")

    result = _invoke("convert", source)

    assert result.exit_code == 0, result.output
    _, body = _read(source.with_suffix(".md"))
    assert "Quarterly figures" in body
    assert "sender@example.invalid" in body
    assert "The synthetic message body." in body


# -- AC-33, AC-34: no network, and a missing module is reported -----------------


@pytest.mark.parametrize(
    ("build", "name"),
    [(_epub, "book.epub"), (_xls, "budget.xls"), (_msg, "message.msg")],
    ids=["epub", "xls", "msg"],
)
def test_ac_33_conversion_makes_no_network_connection(
    build,
    name,
    tmp_path,
    monkeypatch,
):
    root = _bundle(tmp_path, monkeypatch)
    source = build(root / "raw" / "documents" / name)
    attempts: list[object] = []

    def refuse(*args: object, **_kwargs: object):
        attempts.append(args)
        msg = "network access is blocked in this test"
        raise OSError(msg)

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    result = _invoke("convert", source)

    assert result.exit_code == 0, result.output
    assert attempts == []


@pytest.mark.parametrize(
    "case",
    [(_xls, "budget.xls", "xlrd"), (_msg, "message.msg", "olefile")],
    ids=["xls-xlrd", "msg-olefile"],
)
def test_ac_34_missing_backing_module_is_reported_not_raised(
    case,
    tmp_path,
    monkeypatch,
    capsys,
):
    build, name, module = case
    root = _bundle(tmp_path, monkeypatch)
    source = build(root / "raw" / "documents" / name)
    monkeypatch.setitem(sys.modules, module, None)

    code, err = _run_main(monkeypatch, capsys, "convert", source)

    assert code == 1
    assert "[ingest]" in err
    assert "uv" in err
    assert "Traceback" not in err


# -- AC-35, AC-36: --force on a malformed frontmatter block ---------------------

#: Each malformed form `frontmatter.parse` rejects, with the fragment of its
#: error that the warning must carry.
MALFORMED_CASES = [
    ("---\ntitle: [unclosed\n---\n# Hand written\n", "invalid yaml"),
    ("---\ntitle: x\n# Hand written, no closing fence\n", "unterminated"),
    ("---\n- just\n- a list\n---\n# Hand written\n", "mapping"),
]
MALFORMED_IDS = ["invalid-yaml", "unterminated", "not-a-mapping"]


@pytest.mark.parametrize(
    "text",
    [text for text, _ in MALFORMED_CASES],
    ids=MALFORMED_IDS,
)
def test_ac_35_malformed_frontmatter_refuses_and_names_force(
    text,
    tmp_path,
    monkeypatch,
):
    root = _bundle(tmp_path, monkeypatch)
    source = _docx(root / "raw" / "documents" / "report.docx")
    md_path = source.with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")
    before = md_path.read_bytes()

    refused = _invoke("convert", source)

    assert refused.exit_code == 1
    assert md_path.read_bytes() == before
    assert "--force" in refused.output


@pytest.mark.parametrize(
    ("text", "fragment"),
    MALFORMED_CASES,
    ids=MALFORMED_IDS,
)
def test_ac_36_force_replaces_malformed_frontmatter_with_a_warning(
    text,
    fragment,
    tmp_path,
    monkeypatch,
):
    root = _bundle(tmp_path, monkeypatch)
    source = _docx(root / "raw" / "documents" / "report.docx")
    md_path = source.with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")
    original = "raw/documents/report.docx"
    assert original in _listing()["legacy"]

    forced = _invoke("convert", source, "--force")

    assert forced.exit_code == 0, forced.output
    meta, body = _read(md_path)
    assert "The body paragraph." in body
    assert "Hand written" not in body
    assert meta["converted_from"] == "report.docx"
    assert meta["converted_sha256"] == _sha(source)
    assert meta["converter"] == "markitdown"
    for key in ("converted", "type", "title", "source_type", "date_added"):
        assert key in meta, key
    warning = forced.stderr.lower()
    assert "[warn]" in warning
    assert "discard" in warning
    assert "report.md" in warning
    assert fragment in warning
    assert all(original not in group for group in _listing().values())


# -- AC-37 to AC-39: images of originals that share a stem ----------------------


def test_ac_37_same_stem_originals_keep_their_own_images(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch)
    first = _docx(root / "raw" / "a" / "report.docx", image_sizes=(128,))
    second = _docx(root / "raw" / "b" / "report.docx", image_sizes=(96,))

    assert _invoke("convert", first).exit_code == 0
    assert _invoke("convert", second).exit_code == 0

    first_links = _linked(first.with_suffix(".md"))
    second_links = _linked(second.with_suffix(".md"))
    assert len(first_links) == 1
    assert len(second_links) == 1
    assert first_links[0].name != second_links[0].name
    assert first_links[0].read_bytes() == _png(128)
    assert second_links[0].read_bytes() == _png(96)


def test_ac_38_reconversion_removes_only_its_own_images(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch)
    first = _docx(root / "raw" / "a" / "report.docx", image_sizes=(128, 96))
    second = _docx(root / "raw" / "b" / "report.docx", image_sizes=(80,))
    directory = root / "raw" / "images" / "report"
    planted = directory / "clipping.png"
    directory.mkdir(parents=True)
    planted.write_bytes(_png(70))
    assert _invoke("convert", first).exit_code == 0
    assert _invoke("convert", second).exit_code == 0
    second_link = _linked(second.with_suffix(".md"))[0]
    _docx(first, paragraph="A rewritten paragraph.", image_sizes=(128,))

    result = _invoke("convert", first)

    assert result.exit_code == 0, result.output
    first_links = _linked(first.with_suffix(".md"))
    assert len(first_links) == 1
    assert sorted(path.name for path in directory.iterdir()) == sorted(
        {planted.name, first_links[0].name, second_link.name},
    )
    assert planted.read_bytes() == _png(70)
    assert second_link.read_bytes() == _png(80)
    assert first_links[0].read_bytes() == _png(128)


def test_ac_39_image_names_do_not_depend_on_the_working_directory(
    tmp_path,
    monkeypatch,
):
    root = _bundle(tmp_path, monkeypatch)
    first = _docx(root / "raw" / "a" / "report.docx", image_sizes=(128,))
    second = _docx(root / "raw" / "b" / "report.docx", image_sizes=(96,))
    directory = root / "raw" / "images" / "report"
    assert _invoke("convert", first).exit_code == 0
    assert _invoke("convert", second).exit_code == 0
    names = sorted(path.name for path in directory.iterdir())

    monkeypatch.chdir(first.parent)
    assert _invoke("convert", first, "--force").exit_code == 0
    monkeypatch.chdir(second.parent)
    assert _invoke("convert", second, "--force").exit_code == 0

    assert len(names) == 2
    assert sorted(path.name for path in directory.iterdir()) == names
    first_link = _linked(first.with_suffix(".md"))[0]
    second_link = _linked(second.with_suffix(".md"))[0]
    assert first_link.name != second_link.name
    assert first_link.read_bytes() == _png(128)
    assert second_link.read_bytes() == _png(96)
