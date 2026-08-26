"""Tests for bundle discovery and configuration.

Discovery is what lets a command run from anywhere inside a bundle, so the
walking cases carry most of the weight here. The rest pin down the promise that
makes adoption cheap: an empty okf.toml must describe the canonical layout, so
marking an existing folder as a knowledge base takes a file, not a filled-in
one.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from pathlib import Path

import pytest

from okf_kb import config


def _bundle(tmp_path: Path, toml: str = "") -> Path:
    """Create a bundle root holding an okf.toml.

    Args:
        tmp_path: Directory to build the bundle in.
        toml: Contents of the config file.

    Returns:
        The bundle root.

    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / config.CONFIG_FILENAME).write_text(toml, encoding="utf-8")
    for name in ("wiki", "raw", "output"):
        (tmp_path / name).mkdir(exist_ok=True)
    return tmp_path


# -- discovery ---------------------------------------------------------------


def test_find_root_locates_the_bundle_from_its_own_directory(tmp_path):
    root = _bundle(tmp_path)
    assert config.find_root(root) == root


def test_find_root_walks_up_from_a_nested_directory(tmp_path):
    root = _bundle(tmp_path)
    nested = root / "wiki" / "efficiency" / "deep"
    nested.mkdir(parents=True)
    assert config.find_root(nested) == root


def test_find_root_accepts_a_file_and_searches_from_its_parent(tmp_path):
    root = _bundle(tmp_path)
    article = root / "wiki" / "article.md"
    article.write_text("# hi\n", encoding="utf-8")
    assert config.find_root(article) == root


def test_find_root_returns_none_outside_a_bundle(tmp_path):
    (tmp_path / "somewhere").mkdir()
    assert config.find_root(tmp_path / "somewhere") is None


def test_find_root_stops_at_the_nearest_bundle(tmp_path):
    outer = _bundle(tmp_path)
    inner = _bundle(outer / "wiki" / "nested")
    assert config.find_root(inner) == inner


# -- loading -----------------------------------------------------------------


def test_load_walks_up_and_reads_the_config(tmp_path):
    root = _bundle(tmp_path, '[bundle]\ntitle = "📚 Notes"\n')
    cfg = config.load(root / "raw")
    assert cfg.root == root
    assert cfg.title == "📚 Notes"


def test_load_raises_outside_a_bundle(tmp_path):
    with pytest.raises(config.ConfigError, match=r"no okf\.toml found"):
        config.load(tmp_path)


def test_load_from_raises_when_the_config_is_absent(tmp_path):
    with pytest.raises(config.ConfigError, match="does not exist"):
        config.load_from(tmp_path)


def test_invalid_toml_is_reported_with_the_path(tmp_path):
    root = _bundle(tmp_path, "[bundle\n")
    with pytest.raises(config.ConfigError, match="invalid TOML"):
        config.load_from(root)


# -- defaults ----------------------------------------------------------------
#
# An empty okf.toml must describe the canonical layout, so adopting a
# conventional bundle needs a marker file rather than a filled-in one.


def test_an_empty_config_yields_the_canonical_layout(tmp_path):
    root = _bundle(tmp_path)
    cfg = config.load_from(root)
    assert cfg.wiki == root / "wiki"
    assert cfg.raw == root / "raw"
    assert cfg.output == root / "output"
    assert cfg.title == config.DEFAULT_TITLE
    assert cfg.okf_version == config.DEFAULT_OKF_VERSION
    assert cfg.kb_format == config.DEFAULT_KB_FORMAT
    assert cfg.groups == ()
    assert dict(cfg.directory_titles) == {}


def test_paths_are_absolute_regardless_of_the_working_directory(tmp_path):
    root = _bundle(tmp_path)
    cfg = config.load_from(root)
    assert all(p.is_absolute() for p in (cfg.root, cfg.wiki, cfg.raw, cfg.output))


def test_paths_can_be_renamed(tmp_path):
    root = _bundle(
        tmp_path,
        '[paths]\nwiki = "articles"\nraw = "sources"\noutput = "tmp"\n',
    )
    cfg = config.load_from(root)
    assert cfg.wiki == root / "articles"
    assert cfg.raw == root / "sources"
    assert cfg.output == root / "tmp"


def test_a_nested_path_is_allowed(tmp_path):
    root = _bundle(tmp_path, '[paths]\nwiki = "kb/wiki"\n')
    assert config.load_from(root).wiki == root / "kb" / "wiki"


# -- rejecting paths that leave the bundle -----------------------------------


def test_an_absolute_path_is_rejected(tmp_path):
    root = _bundle(tmp_path, '[paths]\nwiki = "/etc"\n')
    with pytest.raises(config.ConfigError, match="must be relative"):
        config.load_from(root)


def test_a_path_escaping_the_root_is_rejected(tmp_path):
    root = _bundle(tmp_path / "bundle")
    (tmp_path / "bundle" / "okf.toml").write_text(
        '[paths]\nraw = "../elsewhere"\n',
        encoding="utf-8",
    )
    with pytest.raises(config.ConfigError, match="escapes the bundle root"):
        config.load_from(root)


# -- taxonomy ----------------------------------------------------------------
#
# The index's section headings were module constants naming one KB's subjects.
# Any other bundle got everything dumped into the fallback group.


def test_groups_are_read_in_document_order(tmp_path):
    root = _bundle(
        tmp_path,
        """
        [[groups]]
        title = "🤖 Machine Learning"
        directories = ["foundations", "efficiency"]

        [[groups]]
        title = "🔧 Tools"
        directories = ["tools"]
        """,
    )
    cfg = config.load_from(root)
    assert [g.title for g in cfg.groups] == ["🤖 Machine Learning", "🔧 Tools"]
    assert cfg.groups[0].directories == ("foundations", "efficiency")


def test_a_group_may_declare_no_directories(tmp_path):
    root = _bundle(tmp_path, '[[groups]]\ntitle = "📁 Empty"\n')
    assert config.load_from(root).groups[0].directories == ()


def test_a_group_without_a_title_is_rejected(tmp_path):
    root = _bundle(tmp_path, '[[groups]]\ndirectories = ["tools"]\n')
    with pytest.raises(config.ConfigError, match="non-empty string title"):
        config.load_from(root)


def test_group_directories_must_be_strings(tmp_path):
    root = _bundle(tmp_path, '[[groups]]\ntitle = "x"\ndirectories = [1, 2]\n')
    with pytest.raises(config.ConfigError, match="array of strings"):
        config.load_from(root)


def test_directory_titles_are_read(tmp_path):
    root = _bundle(
        tmp_path,
        '[directories]\nfoundations = "🏗️ Foundations"\ntools = "🔧 Tools"\n',
    )
    cfg = config.load_from(root)
    assert cfg.directory_titles["foundations"] == "🏗️ Foundations"
    assert cfg.directory_titles["tools"] == "🔧 Tools"


def test_a_non_string_directory_title_is_rejected(tmp_path):
    root = _bundle(tmp_path, "[directories]\ntools = 3\n")
    with pytest.raises(config.ConfigError, match="must be a string"):
        config.load_from(root)


def test_directory_titles_are_read_only(tmp_path):
    cfg = config.load_from(_bundle(tmp_path))
    with pytest.raises(TypeError):
        cfg.directory_titles["tools"] = "nope"  # ty: ignore[invalid-assignment]


# -- malformed tables --------------------------------------------------------


def test_a_non_table_bundle_section_is_rejected(tmp_path):
    root = _bundle(tmp_path, 'bundle = "not a table"\n')
    with pytest.raises(config.ConfigError, match=r"\[bundle\] must be a table"):
        config.load_from(root)


def test_a_non_string_title_is_rejected(tmp_path):
    root = _bundle(tmp_path, "[bundle]\ntitle = 42\n")
    with pytest.raises(config.ConfigError, match="title must be a string"):
        config.load_from(root)


# -- root-relative addressing ------------------------------------------------


def test_relative_expresses_a_bundle_path_against_the_root(tmp_path):
    cfg = config.load_from(_bundle(tmp_path))
    assert cfg.relative(cfg.wiki / "tools" / "a.md") == Path("wiki/tools/a.md")


def test_relative_passes_through_a_path_outside_the_bundle(tmp_path):
    cfg = config.load_from(_bundle(tmp_path / "bundle"))
    outside = (tmp_path / "elsewhere" / "a.md").resolve()
    assert cfg.relative(outside) == outside


def test_description_defaults_to_something_subject_neutral(tmp_path):
    """The index intro named one bundle's subjects. It belongs in config."""
    assert config.load_from(_bundle(tmp_path)).description == config.DEFAULT_DESCRIPTION


def test_description_is_read_from_the_bundle(tmp_path):
    root = _bundle(tmp_path, '[bundle]\ndescription = "Notes on Postgres."\n')
    assert config.load_from(root).description == "Notes on Postgres."
