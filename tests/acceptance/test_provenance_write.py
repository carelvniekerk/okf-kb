"""Acceptance tests AC-7 to AC-14: `kb-provenance migrate --write`.

The migration stamps provenance from git history, so the cases that matter most
are the ones where it must write nothing: no history, a human-curated source, an
existing sign-off, a second run, and a directory outside any bundle. A guessed
`author` or `generated` poisons the trust signal, so those absences are asserted
as strictly as the values.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100, S603, S607

from __future__ import annotations

import inspect
import re
from pathlib import Path

from conftest import OPUS, GitBundle, legacy_article, needs_git, source_file
from typer.testing import CliRunner

from okf_kb import config, frontmatter, gitmeta, okf, provenance

runner = CliRunner()

pytestmark = needs_git


def _migrate(*args: str):
    return runner.invoke(provenance.app, ["migrate", *args])


def _entry(document: frontmatter.Document, resource: str) -> dict:
    return next(s for s in document.frontmatter["sources"] if s["resource"] == resource)


def test_ac_7_migrate_without_write_changes_nothing_and_documents_the_flag(bundle):
    bundle.write("raw/papers/x.md", source_file("Paper X"))
    article = bundle.write(
        "wiki/a.md",
        "---\ntype: concept\ntitle: A\n---\n\n# A\n\n## Sources\n\n"
        "- [Paper X](../raw/papers/x.md)\n",
    )
    bundle.commit("add")
    before = article.read_bytes()

    result = _migrate()

    assert result.exit_code == 0, result.output
    assert "x.md" in result.output
    assert article.read_bytes() == before
    assert "--write" in runner.invoke(provenance.app, ["migrate", "--help"]).output


def test_ac_8_write_stamps_sources_and_generated_and_keeps_the_body(bundle):
    bundle.write("raw/papers/x.md", source_file("Paper X"))
    bundle.commit("add source")
    article = bundle.write("wiki/a.md", legacy_article(["raw/papers/x.md"]))
    sha = bundle.commit("add article", OPUS)
    body_before = frontmatter.load(article).body

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    assert "a.md" in result.output
    document = frontmatter.load(article)
    data = document.frontmatter
    assert "source_files" not in data
    entry = _entry(document, "raw/papers/x.md")
    assert {"id", "title", "last_modified"} <= set(entry)
    assert data["generated"]["by"] == "claude-opus-4-6"
    assert data["generated"]["at"].endswith("Z")
    assert sha.startswith(data["generated"]["commit"])
    assert data["status"] == "stable"
    assert list(data) == list(okf.reorder(dict(data)))
    assert document.body == body_before


def test_ac_9_author_is_written_only_when_the_commit_names_a_model(bundle):
    bundle.write("raw/notes/plain.md", source_file("Plain"))
    bundle.write("raw/papers/p.md", source_file("Paper"))
    bundle.commit("add human and fetched sources")
    bundle.write("raw/research/r.md", source_file("Brief"))
    bundle.commit("add agent source", OPUS)
    article = bundle.write(
        "wiki/a.md",
        legacy_article(
            ["raw/notes/plain.md", "raw/papers/p.md", "raw/research/r.md"],
        ),
    )
    bundle.commit("add article", OPUS)

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    document = frontmatter.load(article)
    assert "author" not in _entry(document, "raw/notes/plain.md")
    assert "author" not in _entry(document, "raw/papers/p.md")
    assert _entry(document, "raw/research/r.md")["author"] == "claude-opus-4-6"
    assert "human:carel" not in article.read_text(encoding="utf-8")


def test_ac_10_an_article_without_history_gets_no_generated_block(bundle):
    bundle.write("raw/papers/x.md", source_file("Paper X"))
    bundle.commit("add source")
    article = bundle.write("wiki/a.md", legacy_article(["raw/papers/x.md"]))

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    assert "generated" not in frontmatter.load(article).frontmatter
    assert "a.md" in result.output
    assert "generated" in result.output.lower()


def test_ac_11_migration_never_writes_or_alters_verified(bundle):
    bundle.write("raw/papers/x.md", source_file("Paper X"))
    plain = bundle.write("wiki/plain.md", legacy_article(["raw/papers/x.md"], "Plain"))
    signed_text = legacy_article(["raw/papers/x.md"], "Signed").replace(
        "---\n\n#",
        "verified:\n  - { by: process:kb-health, at: 2026-10-05T10:00:00Z }\n---\n\n#",
        1,
    )
    signed = bundle.write("wiki/signed.md", signed_text)
    bundle.commit("add articles", OPUS)
    verified_before = frontmatter.load(signed).frontmatter["verified"]

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    assert "verified" not in frontmatter.load(plain).frontmatter
    assert frontmatter.load(signed).frontmatter["verified"] == verified_before


def test_ac_12_a_second_write_changes_nothing(bundle):
    bundle.write("raw/papers/x.md", source_file("Paper X"))
    article = bundle.write("wiki/a.md", legacy_article(["raw/papers/x.md"]))
    bundle.commit("add", OPUS)
    assert _migrate("--write").exit_code == 0
    after_first = article.read_bytes()

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    assert article.read_bytes() == after_first
    assert re.search(r"(?i)\b0\b[^\n]*changed|changed[^\n]*\b0\b", result.output)


def test_ac_13_renamed_zones_drive_rename_tracking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bundle = GitBundle(tmp_path, wiki="articles", raw="notes")
    bundle.write("notes/papers/x.md", source_file("Paper X"))
    bundle.write("articles/a.md", legacy_article(["notes/papers/x.md"]))
    created = bundle.commit("add article", OPUS)
    bundle.git("mv", "articles/a.md", "articles/b.md")
    bundle.commit("rename article")

    result = _migrate("--write")

    assert result.exit_code == 0, result.output
    document = frontmatter.load(tmp_path / "articles" / "b.md")
    assert created.startswith(document.frontmatter["generated"]["commit"])
    assert _entry(document, "notes/papers/x.md")["id"]


def test_ac_13_no_zone_literal_is_a_default_argument():
    functions = (
        okf.source_zone,
        gitmeta.rename_map,
        gitmeta.creation_commit,
        gitmeta.provenance,
    )
    for function in functions:
        for name in ("zone", "raw_name"):
            parameter = inspect.signature(function).parameters.get(name)
            if parameter is not None:
                assert parameter.default not in {"wiki", "raw"}, (function, name)


def test_ac_14_write_outside_a_bundle_raises_the_config_error_and_writes_nothing(
    tmp_path,
    monkeypatch,
):
    stray = tmp_path / "wiki" / "a.md"
    stray.parent.mkdir()
    stray.write_text(legacy_article(["raw/papers/x.md"]), encoding="utf-8")
    before = stray.read_bytes()
    monkeypatch.chdir(Path(tmp_path))

    result = _migrate("--write")

    assert result.exit_code != 0
    assert isinstance(result.exception, config.ConfigError)
    assert stray.read_bytes() == before
