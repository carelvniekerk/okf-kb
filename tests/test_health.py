"""Tests for the automated wiki health checks.

These cover the checks that read frontmatter, which now goes through the shared
parser. The interesting cases are the ones the old regexes could not express:
malformed YAML, an absent ``type``, and the OKF ``sources`` list-of-mappings
shape that would previously have been compared against as if it were a count.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from pathlib import Path

from okf_kb import health

VALID_ARTICLE = """\
---
tags: [alpha, beta]
type: concept
date_added: 2026-08-16
sources: 1
source_files:
  - raw/alpha.md
---

# Alpha

Body.

## Sources

- [Alpha](../raw/alpha.md)
"""


def _write(wiki: Path, name: str, text: str) -> Path:
    path = wiki / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# -- is_article --------------------------------------------------------------


def test_is_article_accepts_ordinary_article():
    assert health.is_article(Path("wiki/flash-attention.md"))


def test_is_article_rejects_reserved_and_partials():
    assert not health.is_article(Path("wiki/INDEX.md"))
    assert not health.is_article(Path("wiki/log.md"))
    assert not health.is_article(Path("wiki/_partial.md"))
    assert not health.is_article(Path("wiki/notes.txt"))


# -- check_okf_conformance ---------------------------------------------------


def test_okf_conformance_passes_on_valid_article(tmp_path):
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    assert health.check_okf_conformance(tmp_path) == []


def test_okf_conformance_catches_missing_type(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntags: [alpha]\ndate_added: 2026-08-16\n---\n\n# Alpha\n",
    )
    issues = health.check_okf_conformance(tmp_path)
    assert len(issues) == 1
    assert "Missing or empty `type`" in issues[0]
    assert "alpha.md" in issues[0]


def test_okf_conformance_catches_empty_type(tmp_path):
    _write(tmp_path, "alpha.md", '---\ntype: ""\n---\n\n# Alpha\n')
    issues = health.check_okf_conformance(tmp_path)
    assert len(issues) == 1
    assert "Missing or empty `type`" in issues[0]


def test_okf_conformance_catches_malformed_frontmatter(tmp_path):
    # Unterminated block: an opening delimiter with no closing one.
    _write(tmp_path, "alpha.md", "---\ntype: concept\n\n# Alpha\n")
    issues = health.check_okf_conformance(tmp_path)
    assert len(issues) == 1
    assert "Malformed frontmatter" in issues[0]


def test_okf_conformance_catches_invalid_yaml(tmp_path):
    _write(tmp_path, "alpha.md", "---\ntype: [unclosed\n---\n\n# Alpha\n")
    issues = health.check_okf_conformance(tmp_path)
    assert len(issues) == 1
    assert "Malformed frontmatter" in issues[0]


def test_okf_conformance_catches_absent_frontmatter(tmp_path):
    _write(tmp_path, "alpha.md", "# Alpha\n\nNo frontmatter at all.\n")
    issues = health.check_okf_conformance(tmp_path)
    assert len(issues) == 1
    assert "Missing frontmatter" in issues[0]


def test_okf_conformance_exempts_reserved_files(tmp_path):
    _write(tmp_path, "INDEX.md", "# Index\n")
    _write(tmp_path, "log.md", "# Log\n")
    _write(tmp_path, "_partial.md", "Fragment.\n")
    assert health.check_okf_conformance(tmp_path) == []


def test_okf_conformance_reports_every_offender(tmp_path):
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    _write(tmp_path, "beta.md", "---\ntags: [beta]\n---\n\n# Beta\n")
    _write(tmp_path, "nested/gamma.md", "# Gamma\n")
    assert len(health.check_okf_conformance(tmp_path)) == 2


# -- check_staleness ---------------------------------------------------------


def test_passed_stale_after_is_reported(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nstale_after: 2020-01-01\n---\n\n# Alpha\n",
    )
    issues = health.check_staleness(tmp_path)
    assert len(issues) == 1
    assert "alpha.md" in issues[0]
    assert "2020-01-01" in issues[0]


def test_future_stale_after_is_silent(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nstale_after: 2999-01-01\n---\n\n# Alpha\n",
    )
    assert health.check_staleness(tmp_path) == []


def test_absent_stale_after_is_not_stale(tmp_path):
    """No expiry means none was ever set, not that the content is fresh."""
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    assert health.check_staleness(tmp_path) == []


def test_stale_articles_are_reported_oldest_first(tmp_path):
    _write(
        tmp_path,
        "a.md",
        "---\ntype: concept\nstale_after: 2021-06-01\n---\n\n# A\n",
    )
    _write(
        tmp_path,
        "b.md",
        "---\ntype: concept\nstale_after: 2019-06-01\n---\n\n# B\n",
    )
    issues = health.check_staleness(tmp_path)
    assert "b.md" in issues[0]
    assert "a.md" in issues[1]


# -- trust_tiers -------------------------------------------------------------


def test_absent_verified_is_unverified(tmp_path):
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    assert health.trust_tiers(tmp_path)["unverified"] == 1


def test_human_actor_is_human_reviewed(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nverified:\n"
        "  - {by: 'human:carel', at: '2026-08-16T10:00:00Z'}\n---\n\n# Alpha\n",
    )
    assert health.trust_tiers(tmp_path)["human-reviewed"] == 1


def test_process_actor_only_is_machine_confirmed(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nverified:\n"
        "  - {by: 'process:kb-health', at: '2026-08-16T10:00:00Z'}\n---\n\n# Alpha\n",
    )
    tiers = health.trust_tiers(tmp_path)
    assert tiers["machine-confirmed"] == 1
    assert tiers["human-reviewed"] == 0


def test_bare_verified_mapping_is_treated_as_one_entry(tmp_path):
    """OKF §11 requires consumers to accept a bare mapping, not just a list."""
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\n"
        "verified: {by: 'human:carel', at: '2026-08-16T10:00:00Z'}\n"
        "---\n\n# Alpha\n",
    )
    assert health.trust_tiers(tmp_path)["human-reviewed"] == 1


def test_a_human_entry_wins_over_process_entries(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nverified:\n"
        "  - {by: 'process:kb-health', at: '2026-08-16T10:00:00Z'}\n"
        "  - {by: 'human:carel', at: '2026-08-16T11:00:00Z'}\n---\n\n# Alpha\n",
    )
    assert health.trust_tiers(tmp_path)["human-reviewed"] == 1


# -- check_stale_source_files ------------------------------------------------


def test_stale_source_files_reads_okf_sources(tmp_path):
    wiki = tmp_path / "wiki"
    _write(
        wiki,
        "alpha.md",
        "---\ntype: concept\nsources:\n  - resource: raw/missing.md\n---\n\n# Alpha\n",
    )
    issues = health.check_stale_source_files(wiki, tmp_path)
    assert len(issues) == 1
    assert "raw/missing.md" in issues[0]


def test_stale_source_files_silent_when_source_exists(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "alpha.md").write_text("source", encoding="utf-8")
    wiki = tmp_path / "wiki"
    _write(wiki, "alpha.md", VALID_ARTICLE)
    assert health.check_stale_source_files(wiki, tmp_path) == []


def test_stale_source_files_does_not_depend_on_the_working_directory(
    tmp_path,
    monkeypatch,
):
    """Declared resources are root-relative, not relative to where you stand.

    Resolving them against the working directory made every source read as
    missing whenever the command ran from anywhere but the bundle root.
    """
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "alpha.md").write_text("source", encoding="utf-8")
    wiki = tmp_path / "wiki"
    _write(wiki, "nested/alpha.md", VALID_ARTICLE)

    monkeypatch.chdir(wiki / "nested")

    assert health.check_stale_source_files(wiki, tmp_path) == []


# -- check_source_files_frontmatter ------------------------------------------


def test_missing_source_declaration_is_reported(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\n---\n\n# Alpha\n\n## Sources\n\n- something\n",
    )
    issues = health.check_source_files_frontmatter(tmp_path)
    assert len(issues) == 1
    assert "alpha.md" in issues[0]


def test_okf_sources_satisfy_the_declaration_check(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nsources:\n  - resource: raw/alpha.md\n---\n\n"
        "# Alpha\n\n## Sources\n\n- [Alpha](../raw/alpha.md)\n",
    )
    assert health.check_source_files_frontmatter(tmp_path) == []


# -- check_sources_sections --------------------------------------------------


def test_sources_section_check_skips_reserved_files(tmp_path):
    _write(tmp_path, "INDEX.md", "# Index\n")
    _write(tmp_path, "log.md", "# Log\n")
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    assert health.check_sources_sections(tmp_path) == []


def test_sources_section_check_reports_article_without_sources(tmp_path):
    _write(tmp_path, "alpha.md", "---\ntype: concept\n---\n\n# Alpha\n")
    issues = health.check_sources_sections(tmp_path)
    assert len(issues) == 1
    assert "alpha.md" in issues[0]


# -- check_orphans -----------------------------------------------------------


def test_orphan_article_is_reported(tmp_path):
    _write(tmp_path, "INDEX.md", "# Index\n\n- [Alpha](./alpha.md)\n")
    _write(tmp_path, "alpha.md", VALID_ARTICLE)
    _write(tmp_path, "beta.md", "---\ntype: concept\n---\n\n# Beta\n")
    issues = health.check_orphans(tmp_path)
    assert len(issues) == 1
    assert "beta.md" in issues[0]


# -- check_sources_listed ----------------------------------------------------


def test_declared_source_missing_from_body_is_reported(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nsources:\n  - resource: raw/notes/alpha.md\n---\n\n"
        "# Alpha\n\n## Sources\n\n- [Something else](../raw/notes/other.md)\n",
    )
    issues = health.check_sources_listed(tmp_path)
    assert len(issues) == 1
    assert "raw/notes/alpha.md" in issues[0]


def test_declared_source_present_in_body_is_silent(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nsources:\n  - resource: raw/notes/alpha.md\n---\n\n"
        "# Alpha\n\n## Sources\n\n- [Alpha](../raw/notes/alpha.md)\n",
    )
    assert health.check_sources_listed(tmp_path) == []


def test_percent_encoded_link_still_matches(tmp_path):
    """Paths with spaces are encoded in links but not in frontmatter."""
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nsources:\n  - resource: raw/notes/My Note.md\n---\n\n"
        "# Alpha\n\n## Sources\n\n- [My Note](../raw/notes/My%20Note.md)\n",
    )
    assert health.check_sources_listed(tmp_path) == []


def test_article_without_a_sources_section_is_left_to_the_other_check(tmp_path):
    _write(
        tmp_path,
        "alpha.md",
        "---\ntype: concept\nsources:\n"
        "  - resource: raw/notes/alpha.md\n---\n\n# Alpha\n",
    )
    assert health.check_sources_listed(tmp_path) == []
