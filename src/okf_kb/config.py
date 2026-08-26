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
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Filename that marks a directory as a knowledge-base root.
CONFIG_FILENAME = "okf.toml"

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

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: invalid TOML: {exc}"
        raise ConfigError(msg) from exc
    except OSError as exc:
        msg = f"{path}: cannot be read: {exc}"
        raise ConfigError(msg) from exc

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

    resolved = (root / candidate).resolve()
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
