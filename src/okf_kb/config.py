"""Bundle discovery and configuration.

Every tool in this package needs two things before it can do anything: where
the knowledge base *is*, and how this particular bundle is laid out. Both come
from a single ``okf.toml`` at the bundle root.

Discovery walks up from the working directory looking for that file, the way
``git`` finds ``.git`` and ``uv`` finds ``pyproject.toml``. That is what lets a
command run from anywhere inside a bundle instead of only from its root, and it
is what turns "standing in the wrong directory" from a silently empty result
into a real error.

Configuration then answers the questions that used to be hardcoded: which
directories hold the wiki and its sources, what the bundle is called, and how
the root index groups its sections. A conventional bundle needs almost none of
it — every key has a default matching the canonical layout — so a minimal
``okf.toml`` is a valid one::

    # okf.toml
    [bundle]
    title = "🧠 Knowledge Base"

Paths returned by :func:`load` are always absolute, resolved against the
discovered root. Nothing downstream should ever do relative-path arithmetic.

Walk-up discovery is right for the tools that write to a bundle, and useless
for reading one from somewhere else. Read-only commands therefore resolve their
scope through :func:`resolve_roots`, which also consults two further files:

* the user config, ``$XDG_CONFIG_HOME/okf-kb/config.toml``, which maps bundle
  names to paths on this machine and may name a ``default``;
* a project file, ``.okf-kb.toml`` at the root of a project that consumes one
  or more bundles, which names them, optionally picks a ``default``, and may
  carry its own ``[paths]`` for a checkout with no user config.

The project file is deliberately not called ``okf.toml``: that name means
"this directory is a knowledge base" to every writing tool, and reusing it as a
pointer would let them operate on a code repository. :func:`resolve_roots` is
the only reader of either file, so writing tools cannot be pointed at a bundle
the user is not standing in.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Filename that marks a directory as a knowledge-base root.
CONFIG_FILENAME = "okf.toml"

#: Directory under ``$XDG_CONFIG_HOME`` holding the user config.
USER_CONFIG_DIRNAME = "okf-kb"

#: The user config's filename inside :data:`USER_CONFIG_DIRNAME`.
USER_CONFIG_FILENAME = "config.toml"

#: Filename that names the bundles a project consumes. Distinct from
#: :data:`CONFIG_FILENAME` on purpose; see the module docstring.
PROJECT_FILENAME = ".okf-kb.toml"

#: Environment variable pointing at a single bundle root.
ENV_ROOT = "OKF_KB_ROOT"

#: ``--kb`` value that puts every known bundle in scope.
ALL_BUNDLES = "all"

#: How a bundle came to be in scope, in resolution order.
type BundleSource = Literal["flag", "env", "walk-up", "project", "user-config"]

#: Default directory names, matching the canonical bundle layout.
DEFAULT_WIKI_DIR = "wiki"
DEFAULT_RAW_DIR = "raw"
DEFAULT_OUTPUT_DIR = "output"

#: Default bundle title, used as the root index's H1.
DEFAULT_TITLE = "🧠 Knowledge Base"

#: Default one-line description, rendered under the root index badges. Kept
#: subject-neutral: a bundle's own subject belongs in its config, not here.
DEFAULT_DESCRIPTION = "A knowledge base compiled from curated sources."

#: Spec versions a bundle is assumed to target when it declares none.
DEFAULT_OKF_VERSION = "0.2"
DEFAULT_KB_FORMAT = "1.0"


class ConfigError(RuntimeError):
    """Raised when a bundle cannot be found or its configuration is invalid."""


class ScopeError(ConfigError):
    """Raised when nothing puts any bundle in scope.

    Distinct from a malformed config, which is always an error: a project with
    no knowledge base configured is a state a read-only caller may want to
    report and carry on from.

    Attributes:
        searched: One line per place that was consulted, in resolution order.

    """

    def __init__(self, searched: Sequence[str]) -> None:
        """Build the message from the places searched.

        Args:
            searched: One line per place that was consulted.

        """
        self.searched = tuple(searched)
        super().__init__(
            "no knowledge base in scope; searched:\n"
            + "\n".join(f"  - {line}" for line in self.searched),
        )


@dataclass(frozen=True)
class Group:
    """A heading in the root index and the directories filed beneath it.

    Directories absent from every group are still rendered, in a trailing
    fallback group, so a new section is never silently dropped from the index.
    """

    title: str
    directories: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    """A resolved bundle: where it lives and how it is laid out.

    All four path attributes are absolute. ``root`` is the directory holding
    ``okf.toml``; the rest are resolved against it.
    """

    root: Path
    wiki: Path
    raw: Path
    output: Path
    title: str = DEFAULT_TITLE
    description: str = DEFAULT_DESCRIPTION
    okf_version: str = DEFAULT_OKF_VERSION
    kb_format: str = DEFAULT_KB_FORMAT
    groups: tuple[Group, ...] = ()
    #: Display title per wiki subdirectory name, e.g. ``{"tools": "🔧 Tools"}``.
    directory_titles: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )

    def relative(self, path: Path) -> Path:
        """Express an absolute path inside the bundle relative to its root.

        Provenance records and index links are written root-relative so they do
        not depend on where the bundle happens to be checked out.

        Args:
            path: A path inside the bundle.

        Returns:
            The path relative to :attr:`root`, or the input unchanged if it
            lies outside the bundle.

        """
        try:
            return path.resolve().relative_to(self.root)
        except ValueError:
            return path


@dataclass(frozen=True)
class Bundle:
    """A bundle in scope for a read-only command.

    Attributes:
        name: The name it was declared under, or its root directory's name
            when it was reached by path.
        config: Its resolved configuration.
        source: Which step of the resolution order put it in scope.

    """

    name: str
    config: Config
    source: BundleSource


@dataclass(frozen=True)
class _Declared:
    """A bundle name mapped to a path, and the file that mapped it."""

    path: Path
    origin: str


def find_root(start: Path | None = None) -> Path | None:
    """Search upwards for the directory holding ``okf.toml``.

    Args:
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The bundle root, or ``None`` if no ancestor holds a config file.

    """
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate
    return None


def load(start: Path | None = None) -> Config:
    """Find the enclosing bundle and read its configuration.

    Args:
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The resolved configuration.

    Raises:
        ConfigError: If no bundle encloses ``start``, or its config is invalid.

    """
    root = find_root(start)
    if root is None:
        where = (start or Path.cwd()).resolve()
        msg = (
            f"no {CONFIG_FILENAME} found in {where} or any parent directory — "
            f"run this from inside a knowledge base, or create one with "
            f"the init skill"
        )
        raise ConfigError(msg)
    return load_from(root)


def load_from(root: Path) -> Config:
    """Read the configuration of a bundle whose root is already known.

    Args:
        root: Directory holding ``okf.toml``.

    Returns:
        The resolved configuration.

    Raises:
        ConfigError: If the config file is missing, unparseable, or malformed.

    """
    root = root.resolve()
    path = root / CONFIG_FILENAME
    if not path.is_file():
        msg = f"{path} does not exist"
        raise ConfigError(msg)

    raw = _read_toml(path)
    bundle = _table(raw, "bundle", path)
    paths = _table(raw, "paths", path)

    return Config(
        root=root,
        wiki=_resolve(root, paths, "wiki", DEFAULT_WIKI_DIR, path),
        raw=_resolve(root, paths, "raw", DEFAULT_RAW_DIR, path),
        output=_resolve(root, paths, "output", DEFAULT_OUTPUT_DIR, path),
        title=_string(bundle, "title", DEFAULT_TITLE, path),
        description=_string(bundle, "description", DEFAULT_DESCRIPTION, path),
        okf_version=_string(bundle, "okf_version", DEFAULT_OKF_VERSION, path),
        kb_format=_string(bundle, "kb_format", DEFAULT_KB_FORMAT, path),
        groups=_groups(raw, path),
        directory_titles=_directory_titles(raw, path),
    )


def resolve_dir(
    explicit: Path | None,
    which: str,
    start: Path | None = None,
) -> Path:
    """Resolve a command's directory option against the enclosing bundle.

    Commands keep their explicit ``--wiki-dir``-style flags, so a caller — a
    test fixture, a one-off run against another checkout — can still point them
    anywhere. Config only supplies the default, which is what lets a command be
    run from anywhere inside a bundle instead of only from its root.

    Args:
        explicit: The value passed on the command line, if any.
        which: Attribute of :class:`Config` to fall back to: ``wiki``, ``raw``
            or ``output``.
        start: Directory to discover from. Defaults to the working directory.

    Returns:
        ``explicit`` when given, otherwise the configured directory.

    Raises:
        ConfigError: If no value was given and no bundle encloses ``start``.

    """
    if explicit is not None:
        return explicit
    return getattr(load(start), which)


def user_config_path() -> Path:
    """Locate the user config, honouring ``XDG_CONFIG_HOME``.

    Returns:
        The path the user config lives at, whether or not it exists.

    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / USER_CONFIG_DIRNAME / USER_CONFIG_FILENAME


def load_user_config() -> tuple[Mapping[str, Path], str | None]:
    """Read the machine-specific bundle names and default.

    Returns:
        The ``[bundles]`` table as absolute paths, and the ``default`` name.
        Both are empty when the file does not exist.

    Raises:
        ConfigError: If the file is unparseable, a path is not a string, or
            ``default`` names a bundle the file does not map.

    """
    path = user_config_path()
    if not path.is_file():
        return MappingProxyType({}), None
    raw = _read_toml(path)
    bundles = _path_table(raw, "bundles", path)
    default = _optional_string(raw, "default", path)
    if default is not None and default not in bundles:
        msg = f"{path}: default {default!r} is not a key of [bundles]"
        raise ConfigError(msg)
    return bundles, default


def find_project_file(start: Path | None = None) -> Path | None:
    """Search upwards for a project's ``.okf-kb.toml``.

    The walk stops at the first ancestor holding either file, so a project
    file above a bundle is never reached from inside that bundle.

    Args:
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The project file, or ``None`` if a bundle root is closer or neither
        file exists in any ancestor.

    """
    return _scope_files(start)[1]


def load_project_file(
    path: Path,
) -> tuple[tuple[str, ...], str | None, Mapping[str, Path]]:
    """Read which bundles a project consumes.

    Args:
        path: The project file.

    Returns:
        The listed bundle names, the ``default`` name if any, and the
        ``[paths]`` table as absolute paths. When ``bundles`` is absent it
        defaults to the keys of ``[paths]``.

    Raises:
        ConfigError: If the file is unparseable or malformed, lists no bundles,
            or its ``default`` is not one of them.

    """
    raw = _read_toml(path)
    paths = _path_table(raw, "paths", path)
    declared = raw.get("bundles")
    if declared is None:
        bundles = tuple(paths)
    elif isinstance(declared, list) and all(isinstance(n, str) for n in declared):
        bundles = tuple(declared)
    else:
        msg = f"{path}: bundles must be an array of strings"
        raise ConfigError(msg)
    if not bundles:
        msg = f"{path}: names no bundles; set bundles = [...] or add [paths]"
        raise ConfigError(msg)
    default = _optional_string(raw, "default", path)
    if default is not None and default not in bundles:
        msg = f"{path}: default {default!r} is not listed in bundles"
        raise ConfigError(msg)
    return bundles, default, paths


def bundle_for_wiki(wiki_dir: Path) -> Bundle:
    """Wrap an explicitly passed wiki directory as a bundle.

    Commands keep their ``--wiki-dir`` flags, and tests pass bare fixture
    wikis. A wiki whose enclosing bundle configures it as its wiki gets that
    bundle; anything else is treated as a wiki whose root is its parent, which
    is what ``kb-health`` already assumes when it has nothing to discover.

    Args:
        wiki_dir: The wiki directory.

    Returns:
        A bundle whose ``config.wiki`` is ``wiki_dir``, resolved.

    """
    wiki = wiki_dir.resolve()
    root = find_root(wiki)
    if root is not None:
        cfg = load_from(root)
        if cfg.wiki.resolve() == wiki:
            return Bundle(name=root.name, config=cfg, source="flag")
    parent = wiki.parent
    cfg = Config(
        root=parent,
        wiki=wiki,
        raw=parent / DEFAULT_RAW_DIR,
        output=parent / DEFAULT_OUTPUT_DIR,
    )
    return Bundle(name=parent.name, config=cfg, source="flag")


def resolve_roots(
    requested: Sequence[str] | None = None,
    start: Path | None = None,
) -> tuple[Bundle, ...]:
    """Decide which bundles a read-only command operates on.

    Resolution order: an explicit ``requested`` list (bundle names, paths, or
    :data:`ALL_BUNDLES`), then :data:`ENV_ROOT`, then an enclosing
    ``okf.toml``, then an enclosing ``.okf-kb.toml`` (its ``default``, or every
    bundle it lists), then the user config's ``default``. The first step that
    yields anything wins.

    Args:
        requested: Values of a repeatable ``--kb`` option.
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The bundles in scope, deduplicated by root, first occurrence first.

    Raises:
        ConfigError: If a declared bundle's directory holds no ``okf.toml``, a
            requested name is unknown, or two different roots would share one
            name.
        ScopeError: If no step puts any bundle in scope.

    """
    here = (start or Path.cwd()).resolve()
    bundle_root, project_file = _scope_files(here)

    if requested:
        found = _from_flags(requested, bundle_root, project_file)
    elif env := os.environ.get(ENV_ROOT):
        root = Path(env).expanduser().resolve()
        found = [_bundle_at(root.name, root, f"${ENV_ROOT}", "env")]
    elif bundle_root is not None:
        found = [Bundle(bundle_root.name, load_from(bundle_root), "walk-up")]
    elif project_file is not None:
        found = _from_project(project_file)
    else:
        found = _from_user_default(here)
    return _dedupe(found)


def resolve_one(requested: str | None = None, start: Path | None = None) -> Bundle:
    """Resolve exactly one bundle.

    Args:
        requested: A single ``--kb`` value, if given.
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The one bundle in scope.

    Raises:
        ConfigError: If resolution fails, or puts more than one bundle in
            scope.

    """
    bundles = resolve_roots([requested] if requested else None, start)
    if len(bundles) > 1:
        names = ", ".join(b.name for b in bundles)
        msg = f"more than one knowledge base in scope ({names}); pick one with --kb"
        raise ConfigError(msg)
    return bundles[0]


def _scope_files(start: Path | None) -> tuple[Path | None, Path | None]:
    """Walk up once for the nearer of a bundle root and a project file.

    Args:
        start: Directory to search from. Defaults to the working directory.

    Returns:
        ``(bundle_root, None)``, ``(None, project_file)``, or ``(None, None)``.
        A directory holding both files is a bundle.

    """
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate, None
        if (candidate / PROJECT_FILENAME).is_file():
            return None, candidate / PROJECT_FILENAME
    return None, None


def _name_table(project_file: Path | None) -> dict[str, _Declared]:
    """Merge the user config's names with a project file's ``[paths]``.

    Args:
        project_file: The project file in scope, if any.

    Returns:
        Every known name, with project ``[paths]`` shadowing the user config.

    """
    user_path = user_config_path()
    user_bundles, _ = load_user_config()
    table = {
        name: _Declared(path, f"{user_path} [bundles]")
        for name, path in user_bundles.items()
    }
    if project_file is not None:
        _, _, paths = load_project_file(project_file)
        table.update(
            {
                name: _Declared(path, f"{project_file} [paths]")
                for name, path in paths.items()
            },
        )
    return table


def _from_flags(
    requested: Sequence[str],
    bundle_root: Path | None,
    project_file: Path | None,
) -> list[Bundle]:
    """Resolve explicit ``--kb`` values.

    Args:
        requested: Names, paths, or :data:`ALL_BUNDLES`.
        bundle_root: The enclosing bundle root, if any.
        project_file: The enclosing project file, if any.

    Returns:
        The requested bundles, in the order given.

    Raises:
        ConfigError: If a value is neither a known name nor a bundle directory,
            or ``all`` finds nothing.

    """
    table = _name_table(project_file)
    found: list[Bundle] = []
    for item in requested:
        if item == ALL_BUNDLES:
            found.extend(
                _bundle_at(name, d.path, d.origin, "flag") for name, d in table.items()
            )
            if bundle_root is not None:
                found.append(Bundle(bundle_root.name, load_from(bundle_root), "flag"))
            if not found:
                msg = (
                    f"--kb {ALL_BUNDLES}: no bundles are declared in "
                    f"{user_config_path()} or a {PROJECT_FILENAME}, and no "
                    f"{CONFIG_FILENAME} encloses the working directory"
                )
                raise ConfigError(msg)
        elif item in table:
            found.append(_bundle_at(item, table[item].path, table[item].origin, "flag"))
        else:
            root = Path(item).expanduser().resolve()
            if not (root / CONFIG_FILENAME).is_file():
                known = ", ".join(sorted(table)) or "none declared"
                msg = (
                    f"--kb {item!r} is neither a declared bundle name ({known}) "
                    f"nor a directory holding {CONFIG_FILENAME}"
                )
                raise ConfigError(msg)
            found.append(Bundle(root.name, load_from(root), "flag"))
    return found


def _from_project(project_file: Path) -> list[Bundle]:
    """Resolve the bundles an enclosing project file puts in scope.

    Args:
        project_file: The project file.

    Returns:
        Its ``default`` when set, otherwise every bundle it lists.

    Raises:
        ConfigError: If a listed name is mapped nowhere.

    """
    bundles, default, _ = load_project_file(project_file)
    table = _name_table(project_file)
    found: list[Bundle] = []
    for name in (default,) if default else bundles:
        if name not in table:
            msg = (
                f"{project_file} names bundle {name!r}, but neither its [paths] "
                f"nor {user_config_path()} maps it to a directory"
            )
            raise ConfigError(msg)
        found.append(_bundle_at(name, table[name].path, table[name].origin, "project"))
    return found


def _from_user_default(here: Path) -> list[Bundle]:
    """Resolve the user config's default, the last step of the order.

    Args:
        here: The directory the walk started from, for the error message.

    Returns:
        The default bundle.

    Raises:
        ScopeError: If there is no default to fall back to.

    """
    user_path = user_config_path()
    bundles, default = load_user_config()
    if default is None:
        state = "declares no default" if user_path.is_file() else "does not exist"
        raise ScopeError(
            [
                "--kb: not given",
                f"{ENV_ROOT}: not set",
                (
                    f"{CONFIG_FILENAME} or {PROJECT_FILENAME}: none in {here} "
                    f"or any parent directory"
                ),
                f"{user_path}: {state}",
            ],
        )
    origin = f"{user_path} [bundles]"
    return [_bundle_at(default, bundles[default], origin, "user-config")]


def _bundle_at(name: str, root: Path, origin: str, source: BundleSource) -> Bundle:
    """Load a declared bundle, naming the declaration when it is not one.

    Args:
        name: The declared name.
        root: The declared directory.
        origin: The file (or variable) that declared it, for the error.
        source: The resolution step being taken.

    Returns:
        The loaded bundle.

    Raises:
        ConfigError: If ``root`` holds no ``okf.toml``.

    """
    if not (root / CONFIG_FILENAME).is_file():
        msg = f"{origin} maps {name!r} to {root}, which holds no {CONFIG_FILENAME}"
        raise ConfigError(msg)
    return Bundle(name=name, config=load_from(root), source=source)


def _dedupe(found: Sequence[Bundle]) -> tuple[Bundle, ...]:
    """Drop repeated roots and reject one name bound to two roots.

    Args:
        found: Bundles in resolution order.

    Returns:
        The first bundle for each root.

    Raises:
        ConfigError: If two different roots carry the same name.

    """
    by_root: dict[Path, Bundle] = {}
    by_name: dict[str, Path] = {}
    for bundle in found:
        root = bundle.config.root
        if root in by_root:
            continue
        if bundle.name in by_name:
            msg = (
                f"two knowledge bases in scope are both called {bundle.name!r}: "
                f"{by_name[bundle.name]} and {root}"
            )
            raise ConfigError(msg)
        by_root[root] = bundle
        by_name[bundle.name] = root
    return tuple(by_root.values())


def _read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, turning failures into :class:`ConfigError`.

    Args:
        path: The file to read.

    Returns:
        The parsed document.

    Raises:
        ConfigError: If the file cannot be read or parsed.

    """
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: invalid TOML: {exc}"
        raise ConfigError(msg) from exc
    except OSError as exc:
        msg = f"{path}: cannot be read: {exc}"
        raise ConfigError(msg) from exc


def _path_table(raw: dict[str, Any], key: str, path: Path) -> Mapping[str, Path]:
    """Read a table of name-to-directory strings as absolute paths.

    Args:
        raw: The parsed document.
        key: Table name.
        path: The file, whose directory relative values resolve against.

    Returns:
        A read-only mapping of names to absolute paths, ``~`` expanded.

    Raises:
        ConfigError: If the table or any value is malformed.

    """
    table = _table(raw, key, path)
    resolved: dict[str, Path] = {}
    for name, value in table.items():
        if not isinstance(value, str):
            msg = f"{path}: {key}.{name} must be a string path"
            raise ConfigError(msg)
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        resolved[name] = candidate.resolve()
    return MappingProxyType(resolved)


def _optional_string(raw: dict[str, Any], key: str, path: Path) -> str | None:
    """Read an optional top-level string.

    Args:
        raw: The parsed document.
        key: Field name.
        path: Config file path, for error messages.

    Returns:
        The value, or ``None`` when absent.

    Raises:
        ConfigError: If the field is present but is not a string.

    """
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        msg = f"{path}: {key} must be a string, got {type(value).__name__}"
        raise ConfigError(msg)
    return value


def _table(raw: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    """Return a top-level table, defaulting to empty.

    Args:
        raw: The parsed document.
        key: Table name.
        path: Config file path, for error messages.

    Returns:
        The table, or an empty mapping when absent.

    Raises:
        ConfigError: If the key is present but is not a table.

    """
    value = raw.get(key, {})
    if not isinstance(value, dict):
        msg = f"{path}: [{key}] must be a table, got {type(value).__name__}"
        raise ConfigError(msg)
    return value


def _string(table: dict[str, Any], key: str, default: str, path: Path) -> str:
    """Read a string field, defaulting when absent.

    Args:
        table: The table to read from.
        key: Field name.
        default: Value to use when the field is absent.
        path: Config file path, for error messages.

    Returns:
        The field's value, or ``default``.

    Raises:
        ConfigError: If the field is present but is not a string.

    """
    value = table.get(key, default)
    if not isinstance(value, str):
        msg = f"{path}: {key} must be a string, got {type(value).__name__}"
        raise ConfigError(msg)
    return value


def _resolve(
    root: Path,
    paths: dict[str, Any],
    key: str,
    default: str,
    path: Path,
) -> Path:
    """Resolve one configured directory against the bundle root.

    Args:
        root: The bundle root.
        paths: The ``[paths]`` table.
        key: Which directory to resolve.
        default: Directory name to use when unconfigured.
        path: Config file path, for error messages.

    Returns:
        An absolute path.

    Raises:
        ConfigError: If the value is not a string, or is absolute, or escapes
            the bundle root.

    """
    value = _string(paths, key, default, path)
    candidate = Path(value)
    if candidate.is_absolute():
        msg = f"{path}: paths.{key} must be relative to the bundle root"
        raise ConfigError(msg)

    # Normalised lexically rather than with Path.resolve, because a zone may
    # legitimately be a symlink to storage outside the bundle (an output/
    # directory synced to cloud storage, a raw/ mirror on another volume), and
    # following the link would read that layout as an escape. What has to be
    # rejected is a *configured value* that traverses upward, which normpath
    # collapses without touching the filesystem.
    resolved = Path(os.path.normpath(root / candidate))
    if resolved != root and root not in resolved.parents:
        msg = f"{path}: paths.{key} escapes the bundle root"
        raise ConfigError(msg)
    return resolved


def _groups(raw: dict[str, Any], path: Path) -> tuple[Group, ...]:
    """Parse the ``[[groups]]`` array into root-index headings.

    Args:
        raw: The parsed document.
        path: Config file path, for error messages.

    Returns:
        The declared groups, in document order.

    Raises:
        ConfigError: If the array or any entry is malformed.

    """
    declared = raw.get("groups", [])
    if not isinstance(declared, list):
        msg = f"{path}: groups must be an array of tables"
        raise ConfigError(msg)

    groups: list[Group] = []
    for index, entry in enumerate(declared):
        where = f"{path}: groups[{index}]"
        if not isinstance(entry, dict):
            msg = f"{where} must be a table"
            raise ConfigError(msg)
        title = entry.get("title")
        if not isinstance(title, str) or not title:
            msg = f"{where} needs a non-empty string title"
            raise ConfigError(msg)
        directories = entry.get("directories", [])
        if not isinstance(directories, list) or not all(
            isinstance(item, str) for item in directories
        ):
            msg = f"{where}.directories must be an array of strings"
            raise ConfigError(msg)
        groups.append(Group(title=title, directories=tuple(directories)))
    return tuple(groups)


def _directory_titles(raw: dict[str, Any], path: Path) -> Mapping[str, str]:
    """Parse the ``[directories]`` table of per-directory display titles.

    Args:
        raw: The parsed document.
        path: Config file path, for error messages.

    Returns:
        A read-only mapping from directory name to display title.

    Raises:
        ConfigError: If any title is not a string.

    """
    table = _table(raw, "directories", path)
    for key, value in table.items():
        if not isinstance(value, str):
            msg = f"{path}: directories.{key} must be a string"
            raise ConfigError(msg)
    return MappingProxyType(dict(table))
