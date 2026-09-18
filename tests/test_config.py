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


def test_a_zone_that_is_a_symlink_out_of_the_bundle_is_allowed(tmp_path):
    """A zone may be a symlink to storage elsewhere.

    Containment is a property of the configured *value*, not of what the
    filesystem does with it. Resolving the link instead read a synced output/
    directory as an escape and broke every command in the bundle.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root = _bundle(tmp_path / "bundle")
    (root / "output").rmdir()
    (root / "output").symlink_to(elsewhere, target_is_directory=True)

    assert config.load_from(root).output == root / "output"


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


# -- scope resolution: fixtures ----------------------------------------------


@pytest.fixture
def scope(tmp_path, monkeypatch):
    """Isolate resolution from the real machine.

    Points the user config and home at the temporary directory, clears the
    environment variable, and stands in a directory that is neither a bundle
    nor a project.

    Returns:
        A namespace with the user config path and the working directory.

    """
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    class Scope:
        user = xdg / config.USER_CONFIG_DIRNAME / config.USER_CONFIG_FILENAME
        here = cwd

        @staticmethod
        def write_user(text: str) -> Path:
            Scope.user.parent.mkdir(parents=True, exist_ok=True)
            Scope.user.write_text(text, encoding="utf-8")
            return Scope.user

    return Scope


def _project(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / config.PROJECT_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def _names(bundles) -> list[str]:
    return [b.name for b in bundles]


# -- user config -------------------------------------------------------------


def test_user_config_path_honours_xdg(scope):
    assert config.user_config_path() == scope.user


@pytest.mark.usefixtures("scope")
def test_absent_user_config_is_empty():
    bundles, default = config.load_user_config()
    assert dict(bundles) == {}
    assert default is None


def test_user_config_expands_home_and_resolves_relative_paths(scope, tmp_path):
    scope.write_user('[bundles]\nwork = "~/kb"\nnear = "../near"\n')
    bundles, _ = config.load_user_config()
    assert bundles["work"] == (tmp_path / "home" / "kb").resolve()
    assert bundles["near"] == (scope.user.parent.parent / "near").resolve()


def test_user_default_must_name_a_mapped_bundle(scope):
    scope.write_user('default = "nope"\n[bundles]\nwork = "/tmp/x"\n')
    with pytest.raises(config.ConfigError, match="default 'nope'"):
        config.load_user_config()


# -- project file ------------------------------------------------------------


def test_project_file_bundles_default_to_the_paths_keys(tmp_path):
    path = _project(tmp_path / "proj", '[paths]\na = "../a"\nb = "/abs/b"\n')
    bundles, default, paths = config.load_project_file(path)
    assert bundles == ("a", "b")
    assert default is None
    assert paths["a"] == (tmp_path / "a").resolve()


def test_project_file_with_nothing_named_is_rejected(tmp_path):
    path = _project(tmp_path / "proj", "")
    with pytest.raises(config.ConfigError, match="names no bundles"):
        config.load_project_file(path)


def test_project_default_must_be_listed(tmp_path):
    path = _project(tmp_path / "proj", 'bundles = ["a"]\ndefault = "b"\n')
    with pytest.raises(config.ConfigError, match="not listed in bundles"):
        config.load_project_file(path)


def test_find_project_file_stops_at_a_closer_bundle(tmp_path):
    _project(tmp_path, 'bundles = ["a"]\n')
    inner = _bundle(tmp_path / "kb")
    assert config.find_project_file(inner / "wiki") is None
    assert (
        config.find_project_file(tmp_path / "kb" / "..")
        == (tmp_path / config.PROJECT_FILENAME).resolve()
    )


# -- resolution order --------------------------------------------------------


def test_nothing_in_scope_names_all_four_places(scope):
    with pytest.raises(config.ScopeError) as info:
        config.resolve_roots()
    message = str(info.value)
    assert "--kb" in message
    assert config.ENV_ROOT in message
    assert config.PROJECT_FILENAME in message
    assert str(scope.user) in message
    assert len(info.value.searched) == 4


def test_user_default_is_the_last_resort(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    scope.write_user(f'default = "work"\n[bundles]\nwork = "{work}"\n')
    (found,) = config.resolve_roots()
    assert found.name == "work"
    assert found.source == "user-config"
    assert found.config.root == work.resolve()


def test_project_file_beats_the_user_default(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    client = _bundle(tmp_path / "client")
    scope.write_user(
        f'default = "work"\n[bundles]\nwork = "{work}"\nclient = "{client}"\n',
    )
    _project(scope.here, 'bundles = ["work", "client"]\n')
    found = config.resolve_roots()
    assert _names(found) == ["work", "client"]
    assert {b.source for b in found} == {"project"}


def test_project_default_narrows_the_scope(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    client = _bundle(tmp_path / "client")
    scope.write_user(f'[bundles]\nwork = "{work}"\nclient = "{client}"\n')
    _project(scope.here, 'bundles = ["work", "client"]\ndefault = "client"\n')
    assert _names(config.resolve_roots()) == ["client"]


def test_enclosing_bundle_beats_the_project_file_and_user_default(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    scope.write_user(f'default = "work"\n[bundles]\nwork = "{work}"\n')
    inside = _bundle(tmp_path / "inside")
    (found,) = config.resolve_roots(start=inside / "wiki")
    assert found.source == "walk-up"
    assert found.config.root == inside.resolve()


def test_env_beats_the_project_file(scope, tmp_path, monkeypatch):
    work = _bundle(tmp_path / "work")
    other = _bundle(tmp_path / "other")
    scope.write_user(f'[bundles]\nwork = "{work}"\n')
    _project(scope.here, 'bundles = ["work"]\n')
    monkeypatch.setenv(config.ENV_ROOT, str(other))
    (found,) = config.resolve_roots()
    assert found.source == "env"
    assert found.config.root == other.resolve()


@pytest.mark.usefixtures("scope")
def test_an_enclosing_bundle_beats_env(tmp_path, monkeypatch):
    """A globally exported OKF_KB_ROOT must not redirect a compile's search."""
    inside = _bundle(tmp_path / "inside")
    other = _bundle(tmp_path / "other")
    monkeypatch.setenv(config.ENV_ROOT, str(other))
    (found,) = config.resolve_roots(start=inside / "wiki")
    assert found.source == "walk-up"
    assert found.config.root == inside.resolve()


@pytest.mark.usefixtures("scope")
def test_env_pointing_at_a_non_bundle_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_ROOT, str(tmp_path))
    with pytest.raises(config.ConfigError, match=config.ENV_ROOT):
        config.resolve_roots()


def test_flag_beats_everything(scope, tmp_path, monkeypatch):
    work = _bundle(tmp_path / "work")
    other = _bundle(tmp_path / "other")
    scope.write_user(f'default = "work"\n[bundles]\nwork = "{work}"\n')
    monkeypatch.setenv(config.ENV_ROOT, str(other))
    (found,) = config.resolve_roots(["work"])
    assert found.name == "work"
    assert found.source == "flag"


@pytest.mark.usefixtures("scope")
def test_flag_accepts_a_path(tmp_path):
    somewhere = _bundle(tmp_path / "somewhere")
    (found,) = config.resolve_roots([str(somewhere)])
    assert found.name == "somewhere"
    assert found.config.root == somewhere.resolve()


def test_flag_all_takes_every_declared_bundle(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    client = _bundle(tmp_path / "client")
    scope.write_user(f'[bundles]\nwork = "{work}"\n')
    _project(scope.here, f'bundles = ["client"]\n[paths]\nclient = "{client}"\n')
    assert sorted(_names(config.resolve_roots([config.ALL_BUNDLES]))) == [
        "client",
        "work",
    ]


def test_an_unknown_flag_value_lists_the_known_names(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    scope.write_user(f'[bundles]\nwork = "{work}"\n')
    with pytest.raises(
        config.ConfigError,
        match=r"neither a declared bundle name \(work\)",
    ):
        config.resolve_roots(["nope"])


def test_the_same_root_twice_is_deduplicated(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    scope.write_user(f'[bundles]\nwork = "{work}"\n')
    assert _names(config.resolve_roots(["work", str(work)])) == ["work"]


@pytest.mark.usefixtures("scope")
def test_two_roots_with_one_name_are_rejected(tmp_path):
    a = _bundle(tmp_path / "a" / "kb")
    b = _bundle(tmp_path / "b" / "kb")
    with pytest.raises(config.ConfigError, match="both called 'kb'"):
        config.resolve_roots([str(a), str(b)])


# -- declarations ------------------------------------------------------------


def test_project_paths_shadow_the_user_config(scope, tmp_path):
    user_copy = _bundle(tmp_path / "user-copy")
    checkout = _bundle(scope.here / "vendor" / "kb")
    scope.write_user(f'[bundles]\nclient = "{user_copy}"\n')
    _project(scope.here, '[paths]\nclient = "./vendor/kb"\n')
    (found,) = config.resolve_roots()
    assert found.config.root == checkout.resolve()


def test_a_declared_name_without_okf_toml_names_the_declaring_file(scope, tmp_path):
    empty = tmp_path / "not-a-bundle"
    empty.mkdir()
    project = _project(scope.here, f'[paths]\nclient = "{empty}"\n')
    with pytest.raises(config.ConfigError) as info:
        config.resolve_roots()
    assert str(project) in str(info.value)
    assert "holds no okf.toml" in str(info.value)


def test_a_user_mapping_without_okf_toml_names_the_user_config(scope, tmp_path):
    empty = tmp_path / "not-a-bundle"
    empty.mkdir()
    scope.write_user(f'default = "work"\n[bundles]\nwork = "{empty}"\n')
    with pytest.raises(config.ConfigError, match=str(scope.user)):
        config.resolve_roots()


def test_a_project_name_mapped_nowhere_names_the_project_file(scope):
    project = _project(scope.here, 'bundles = ["ghost"]\n')
    with pytest.raises(config.ConfigError) as info:
        config.resolve_roots()
    assert str(project) in str(info.value)
    assert "'ghost'" in str(info.value)


def test_resolve_one_rejects_two_bundles(scope, tmp_path):
    work = _bundle(tmp_path / "work")
    client = _bundle(tmp_path / "client")
    _project(scope.here, f'[paths]\nwork = "{work}"\nclient = "{client}"\n')
    with pytest.raises(config.ConfigError, match="more than one"):
        config.resolve_one()


def test_writing_discovery_ignores_the_project_file(scope, tmp_path):
    """Only resolve_roots reads the pointer files; load() must not."""
    work = _bundle(tmp_path / "work")
    _project(scope.here, f'[paths]\nwork = "{work}"\n')
    with pytest.raises(config.ConfigError, match=r"no okf\.toml found"):
        config.load()


# -- bundle_for_wiki ---------------------------------------------------------


def test_bundle_for_wiki_uses_the_enclosing_bundle(tmp_path):
    root = _bundle(tmp_path / "kb", '[paths]\nwiki = "notes"\n')
    (root / "notes").mkdir()
    found = config.bundle_for_wiki(root / "notes")
    assert found.config.root == root.resolve()
    assert found.name == "kb"


def test_bundle_for_wiki_synthesises_a_bundle_for_a_bare_wiki(tmp_path):
    wiki = tmp_path / "fixture" / "wiki"
    wiki.mkdir(parents=True)
    found = config.bundle_for_wiki(wiki)
    assert found.config.wiki == wiki.resolve()
    assert found.config.root == wiki.parent.resolve()
    assert found.name == "fixture"
