"""Tests for the generated wiki indexes.

The generator exists because the hand-maintained index drifted: its badge
counts matched neither the frontmatter nor the filesystem. So the assertions
that matter most here are the computed ones — the unique-source count that is
deliberately *not* the sum of the per-article counts, and the health badge that
must stay honest unless a real check says otherwise.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import datetime as dt
from pathlib import Path

from typer.testing import CliRunner

from okf_kb import frontmatter as fm
from okf_kb import health, index_gen

runner = CliRunner()


def _article(  # noqa: PLR0913
    title: str,
    description: str,
    sources: list[str],
    *,
    date_added: str = "2026-01-01",
    tags: list[str] | None = None,
    status: str = "stable",
    verified: str | None = None,
) -> str:
    lines = [
        "---",
        "type: concept",
        f"title: {title}",
        f"description: {description}",
        f"tags: [{', '.join(tags or ['alpha'])}]",
    ]
    if verified is not None:
        lines.append(f"verified:\n  - by: {verified}\n    at: '2026-01-02T00:00:00Z'")
    lines.append(f"status: {status}")
    lines.append("sources:")
    for source in sources:
        lines.append(f"  - id: {Path(source).stem}")
        lines.append(f"    resource: {source}")
    lines.append(f"date_added: {date_added}")
    lines.append("---")
    lines.extend(["", f"# {title}", "", "Body.", "", "## Sources", ""])
    lines.extend(f"- [{s}](../{s})" for s in sources)
    return "\n".join(lines) + "\n"


def _write(wiki: Path, rel: str, text: str) -> Path:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fixture_wiki(tmp_path: Path) -> Path:
    """Build a wiki with 5 articles over 3 unique sources.

    ``raw/shared.md`` feeds three of them, so the per-article counts sum to 7
    while only 3 distinct sources exist. Directory shapes covered: a flat
    section, a container directory holding only sub-sections, and a nested
    section.
    """
    wiki = tmp_path / "wiki"
    _write(
        wiki,
        "tools/alpha.md",
        _article("Alpha", "First tool.", ["raw/shared.md"], date_added="2026-01-01"),
    )
    _write(
        wiki,
        "tools/beta.md",
        _article(
            "Beta",
            "Second tool.",
            ["raw/shared.md", "raw/beta.md"],
            date_added="2026-01-02",
        ),
    )
    _write(
        wiki,
        "personal/gamma.md",
        _article("Gamma", "A personal note.", ["raw/gamma.md"]),
    )
    _write(
        wiki,
        "projects/car-bench/overview.md",
        _article("🏁 Overview", "Project hub.", ["raw/shared.md"]),
    )
    _write(
        wiki,
        "projects/car-bench/reference.md",
        _article(
            "📐 Reference",
            "Design reference.",
            ["raw/shared.md", "raw/beta.md"],
            date_added="2026-01-03",
        ),
    )
    return wiki


# -- tree construction -------------------------------------------------------


def test_tree_prunes_directories_without_articles(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    (wiki / "empty").mkdir()
    root = index_gen.build_tree(wiki)
    assert {node.rel for node in root.walk() if node.rel} == {
        "tools",
        "personal",
        "projects",
        "projects/car-bench",
    }


def test_container_directory_counts_nested_articles(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    root = index_gen.build_tree(wiki)
    projects = next(node for node in root.walk() if node.rel == "projects")
    assert projects.articles == []
    assert projects.article_count == 2


# -- one index per article-bearing directory ---------------------------------


def test_index_generated_for_every_article_bearing_directory(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    rendered = index_gen.build_indexes(wiki)
    assert set(rendered) == {
        wiki / "INDEX.md",
        wiki / "tools" / "INDEX.md",
        wiki / "personal" / "INDEX.md",
        wiki / "projects" / "INDEX.md",
        wiki / "projects" / "car-bench" / "INDEX.md",
    }


def test_container_directory_index_lists_its_subdirectories(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    rendered = index_gen.build_indexes(wiki)
    text = rendered[wiki / "projects" / "INDEX.md"]
    assert "## 📁 Subdirectories" in text
    assert "](./car-bench/) — 2 articles" in text


def test_leaf_directory_index_has_no_subdirectories_section(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    rendered = index_gen.build_indexes(wiki)
    assert "## 📁 Subdirectories" not in rendered[wiki / "tools" / "INDEX.md"]


def test_subdirectory_index_lists_its_own_articles(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "tools" / "INDEX.md"]
    assert "[Alpha](./alpha.md) — First tool." in text
    assert "[Beta](./beta.md) — Second tool." in text
    assert "1 source ·" in text
    assert "2 sources ·" in text


# -- frontmatter placement (OKF §8) ------------------------------------------


def test_subdirectory_indexes_carry_no_frontmatter(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    rendered = index_gen.build_indexes(wiki)
    for path, text in rendered.items():
        if path.parent == wiki:
            continue
        data, _ = fm.parse(text)
        assert data == {}, path
        assert text.startswith("# ")


def test_root_index_carries_the_okf_frontmatter(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    data, body = fm.parse(text)
    assert data == {"okf_version": "0.2", "kb_format": "1.0"}
    assert body.lstrip().startswith("# 🧠 Knowledge Base")


def test_root_index_frontmatter_versions_stay_strings(tmp_path):
    """Unquoted, YAML would read ``0.2`` as a float and lose the version."""
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert 'okf_version: "0.2"' in text
    assert 'kb_format: "1.0"' in text


# -- computed badges ---------------------------------------------------------


def test_source_badge_counts_unique_resources_not_the_sum(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    root = index_gen.build_tree(wiki)
    articles = root.all_articles()

    assert sum(len(a.source_resources) for a in articles) == 7
    assert index_gen.unique_sources(articles) == [
        "raw/beta.md",
        "raw/gamma.md",
        "raw/shared.md",
    ]

    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert "badge/sources-3-green" in text
    assert "badge/sources-7-green" not in text


def test_article_badge_counts_articles(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert "badge/articles-5-blue" in text


def test_compiled_badge_uses_the_given_date(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki, dt.date(2026, 8, 16))[wiki / "INDEX.md"]
    assert "badge/compiled-2026--08--16-lightgrey" in text


def test_compiled_badge_falls_back_to_today_without_an_existing_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    today = index_gen.shield_escape(dt.date.today().isoformat())  # noqa: DTZ011
    assert f"badge/compiled-{today}-lightgrey" in text


# -- the compiled badge records compiles, not kb-index runs -------------------
#
# kb-index runs on every commit via pre-commit. If the badge defaulted to today
# it would claim a compile on every unrelated chore commit, which is exactly the
# drift these tests exist to prevent.


def test_read_compiled_recovers_the_date_from_an_existing_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    index_gen.write_indexes(index_gen.build_indexes(wiki, dt.date(2026, 8, 16)))
    assert index_gen.read_compiled(wiki) == dt.date(2026, 8, 16)


def test_read_compiled_returns_none_without_an_index(tmp_path):
    assert index_gen.read_compiled(_fixture_wiki(tmp_path)) is None


def test_read_compiled_returns_none_when_the_badge_is_absent(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    (wiki / "INDEX.md").write_text("# no badge here\n", encoding="utf-8")
    assert index_gen.read_compiled(wiki) is None


def test_regeneration_preserves_the_committed_compile_date(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    index_gen.write_indexes(index_gen.build_indexes(wiki, dt.date(2026, 8, 16)))
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert "badge/compiled-2026--08--16-lightgrey" in text


def test_cli_leaves_the_compile_date_alone_by_default(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    index_gen.write_indexes(index_gen.build_indexes(wiki, dt.date(2026, 8, 16)))
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    assert result.exit_code == 0
    assert "badge/compiled-2026--08--16-lightgrey" in (wiki / "INDEX.md").read_text()


def test_cli_stamp_compiled_moves_the_date_to_today(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    index_gen.write_indexes(index_gen.build_indexes(wiki, dt.date(2026, 8, 16)))
    result = runner.invoke(
        index_gen.app,
        ["--wiki-dir", str(wiki), "--stamp-compiled"],
    )
    assert result.exit_code == 0
    today = index_gen.shield_escape(dt.date.today().isoformat())  # noqa: DTZ011
    assert f"badge/compiled-{today}-lightgrey" in (wiki / "INDEX.md").read_text()


def test_cli_rejects_stamp_compiled_together_with_compiled(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    result = runner.invoke(
        index_gen.app,
        ["--wiki-dir", str(wiki), "--stamp-compiled", "--compiled", "2026-01-01"],
    )
    assert result.exit_code != 0


def test_check_does_not_go_stale_as_the_calendar_advances(tmp_path):
    """A committed index stays current on a later day than its compile date."""
    wiki = _fixture_wiki(tmp_path)
    index_gen.write_indexes(index_gen.build_indexes(wiki, dt.date(2026, 8, 16)))
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki), "--check"])
    assert result.exit_code == 0


# -- the health badge must stay honest ---------------------------------------


def test_health_badge_defaults_to_unknown(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert "badge/health-unknown-lightgrey" in text
    assert "brightgreen" not in text


def test_health_badge_flips_only_with_the_explicit_flag(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki, health_passing=True)[wiki / "INDEX.md"]
    assert "badge/health-%E2%9C%93%20passing-brightgreen" in text
    assert "health-unknown" not in text


def test_cli_health_badge_defaults_to_unknown(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    assert result.exit_code == 0
    assert "badge/health-unknown-lightgrey" in (wiki / "INDEX.md").read_text()


def test_cli_health_passing_flag_sets_the_passing_badge(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    result = runner.invoke(
        index_gen.app,
        ["--wiki-dir", str(wiki), "--health-passing"],
    )
    assert result.exit_code == 0
    assert "brightgreen" in (wiki / "INDEX.md").read_text()


# -- trust tiers (OKF §5.2) --------------------------------------------------


def test_trust_tier_absent_verified_is_unverified():
    assert index_gen.trust_tier({"type": "concept"}) == index_gen.TIER_UNVERIFIED


def test_trust_tier_empty_verified_is_unverified():
    assert index_gen.trust_tier({"verified": []}) == index_gen.TIER_UNVERIFIED
    assert index_gen.trust_tier({"verified": None}) == index_gen.TIER_UNVERIFIED


def test_trust_tier_non_human_actor_is_machine_confirmed():
    data = {"verified": [{"by": "claude-opus-5", "at": "2026-01-02T00:00:00Z"}]}
    assert index_gen.trust_tier(data) == index_gen.TIER_MACHINE


def test_trust_tier_human_actor_is_human_reviewed():
    data = {
        "verified": [
            {"by": "claude-opus-5", "at": "2026-01-02T00:00:00Z"},
            {"by": "human:carel", "at": "2026-01-03T00:00:00Z"},
        ],
    }
    assert index_gen.trust_tier(data) == index_gen.TIER_HUMAN


def test_trust_tier_accepts_a_bare_actor_string():
    assert index_gen.trust_tier({"verified": "human:carel"}) == index_gen.TIER_HUMAN


def test_every_tier_renders_a_distinct_badge(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "sec/a.md", _article("A", "Unverified.", ["raw/a.md"]))
    _write(
        wiki,
        "sec/b.md",
        _article("B", "Machine.", ["raw/b.md"], verified="claude-opus-5"),
    )
    _write(
        wiki,
        "sec/c.md",
        _article("C", "Human.", ["raw/c.md"], verified="human:carel"),
    )
    text = index_gen.build_indexes(wiki)[wiki / "sec" / "INDEX.md"]
    assert index_gen.TIER_BADGES[index_gen.TIER_UNVERIFIED] in text
    assert index_gen.TIER_BADGES[index_gen.TIER_MACHINE] in text
    assert index_gen.TIER_BADGES[index_gen.TIER_HUMAN] in text


def test_stable_status_gets_no_badge_but_draft_does(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "sec/a.md", _article("A", "Stable.", ["raw/a.md"]))
    text = index_gen.build_indexes(wiki)[wiki / "sec" / "INDEX.md"]
    assert "badge/status-" not in text

    _write(wiki, "sec/b.md", _article("B", "Draft.", ["raw/b.md"], status="draft"))
    text = index_gen.build_indexes(wiki)[wiki / "sec" / "INDEX.md"]
    assert "![status](https://img.shields.io/badge/status-draft-yellow)" in text


# -- entry rendering ---------------------------------------------------------


def test_leading_emoji_moves_from_the_title_into_the_bullet(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "projects" / "car-bench" / "INDEX.md"]
    assert "- 🏁 [Overview](./overview.md)" in text
    assert "- 📐 [Reference](./reference.md)" in text


def test_titleless_emoji_defaults_to_the_page_icon(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "tools" / "INDEX.md"]
    assert "- 📄 [Alpha](./alpha.md)" in text


def test_split_emoji_leaves_ordinary_titles_alone():
    assert index_gen.split_emoji("Tülu 3: Open Post-Training") == (
        "📄",
        "Tülu 3: Open Post-Training",
    )


def test_shield_escape_doubles_separators():
    assert index_gen.shield_escape("flash-attention") == "flash--attention"
    assert index_gen.shield_escape("2026-08-16") == "2026--08--16"
    assert index_gen.shield_escape("a b_c") == "a_b__c"


def test_tag_badges_are_capped(tmp_path):
    wiki = tmp_path / "wiki"
    _write(
        wiki,
        "sec/a.md",
        _article("A", "Many tags.", ["raw/a.md"], tags=["t1", "t2", "t3", "t4", "t5"]),
    )
    text = index_gen.build_indexes(wiki)[wiki / "sec" / "INDEX.md"]
    assert "badge/-t4-" in text
    assert "badge/-t5-" not in text


# -- root index structure ----------------------------------------------------


def test_root_index_groups_sections_under_curated_headings(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert "## 🛠️ Development & Tools" in text
    assert "## 📬 Other" in text
    assert "## 🏁 Projects" in text
    assert "### 🚗 CAR-bench Challenge" in text
    assert text.rstrip().endswith(
        "- [Operations Log](./log.md) — Chronological history of all "
        "compilations, ingestions, Q&A, and lint passes",
    )


def test_root_index_links_every_article_by_its_full_path(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    for link in (
        "./tools/alpha.md",
        "./tools/beta.md",
        "./personal/gamma.md",
        "./projects/car-bench/overview.md",
        "./projects/car-bench/reference.md",
    ):
        assert f"]({link})" in text


def test_unmapped_directory_is_not_dropped_from_the_root_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    _write(wiki, "brand-new/delta.md", _article("Delta", "New section.", ["raw/d.md"]))
    text = index_gen.build_indexes(wiki)[wiki / "INDEX.md"]
    assert index_gen.FALLBACK_GROUP_TITLE in text
    assert "](./brand-new/delta.md)" in text


# -- --check -----------------------------------------------------------------


def test_check_passes_immediately_after_a_write(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    assert runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)]).exit_code == 0
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki), "--check"])
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_check_reports_a_missing_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    (wiki / "tools" / "INDEX.md").unlink()
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki), "--check"])
    assert result.exit_code == 1
    assert "tools/INDEX.md" in result.output.replace("\\", "/")
    assert "missing" in result.output


def test_check_reports_a_stale_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    _write(wiki, "tools/delta.md", _article("Delta", "New tool.", ["raw/d.md"]))
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki), "--check"])
    assert result.exit_code == 1
    assert "out of date" in result.output


def test_check_does_not_write(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    result = runner.invoke(index_gen.app, ["--wiki-dir", str(wiki), "--check"])
    assert result.exit_code == 1
    assert not (wiki / "INDEX.md").exists()


def test_rewriting_unchanged_indexes_is_a_no_op(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    rendered = index_gen.build_indexes(wiki, dt.date(2026, 8, 16))
    assert len(index_gen.write_indexes(rendered)) == 5
    assert index_gen.write_indexes(rendered) == []


def test_invalid_compiled_date_is_rejected(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    result = runner.invoke(
        index_gen.app,
        ["--wiki-dir", str(wiki), "--compiled", "16-08-2026"],
    )
    assert result.exit_code != 0


# -- health integration ------------------------------------------------------


def test_health_flags_a_directory_missing_its_index(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    (wiki / "personal" / "INDEX.md").unlink()
    issues = health.check_subdir_indexes(wiki)
    assert len(issues) == 1
    assert "personal/" in issues[0]


def test_health_is_silent_when_every_index_exists(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    runner.invoke(index_gen.app, ["--wiki-dir", str(wiki)])
    assert health.check_subdir_indexes(wiki) == []


def test_health_flags_container_directories_too(tmp_path):
    wiki = _fixture_wiki(tmp_path)
    issues = health.check_subdir_indexes(wiki)
    assert len(issues) == 4
    assert any("projects/" in issue for issue in issues)


def test_health_ignores_the_root_index(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "alpha.md", _article("Alpha", "Flat.", ["raw/a.md"]))
    assert health.check_subdir_indexes(wiki) == []


def test_check_ignores_the_health_badge(tmp_path):
    """`--check` asks whether the index reflects the wiki, not whether health passed.

    Comparing the badge made every index read as stale whenever the committed
    file recorded a passing run and the check ran without --health-passing.
    """
    wiki = tmp_path / "wiki"
    (wiki / "tools").mkdir(parents=True)
    (wiki / "tools" / "a.md").write_text(
        "---\ntype: tool-guide\ntitle: A\ndescription: d\n---\n\n# A\n",
        encoding="utf-8",
    )

    passing = index_gen.build_indexes(wiki, health_passing=True)
    index_gen.write_indexes(passing)

    # Same content, opposite health state: content is current, so not stale.
    unknown = index_gen.build_indexes(wiki, health_passing=False)
    assert index_gen.stale_indexes(unknown) == []


def test_check_still_detects_real_content_drift(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "tools").mkdir(parents=True)
    article = wiki / "tools" / "a.md"
    article.write_text(
        "---\ntype: tool-guide\ntitle: A\ndescription: d\n---\n\n# A\n",
        encoding="utf-8",
    )
    index_gen.write_indexes(index_gen.build_indexes(wiki, health_passing=True))

    article.write_text(
        "---\ntype: tool-guide\ntitle: Renamed\ndescription: d\n---\n\n# Renamed\n",
        encoding="utf-8",
    )
    assert (
        index_gen.stale_indexes(index_gen.build_indexes(wiki, health_passing=True))
        != []
    )
