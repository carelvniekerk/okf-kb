"""Optional dependencies, and how to tell the user what to install.

The heavy, platform-sensitive dependencies live behind extras — ``[ingest]``
for PDF and HTML conversion, ``[video]`` for yt-dlp and MLX Whisper — so that a
core install stays light. Every module that needs one imports it inside the
function that uses it, which keeps a core-only install importable and pushes
the failure to the moment the feature is actually used.

That failure is what this module exists to shape. A bare ``ModuleNotFoundError:
No module named 'yt_dlp'`` names neither the extra that provides it nor the
environment it is missing from, so the fix the user reaches for — ``pip install
yt-dlp`` — lands in the wrong place. Wrapping the import instead::

    with extras.required("video"):
        from yt_dlp import YoutubeDL

turns it into a message naming the extra and the exact command that puts it
into the environment this process is running from.

The command it suggests always names every extra the user already has as well
as the missing one. ``uv tool install --force`` *replaces* a tool environment,
so telling someone with ``[ingest]`` to reinstall with ``[video]`` would
silently take their PDF tooling away — the fix has to be additive to be a fix.
"""

from __future__ import annotations

import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

#: Where a released install comes from. The package is not on PyPI.
GIT_SOURCE = "git+ssh://git@github.com/carelvniekerk/okf-kb"

#: Extras, and the import names each one makes available. Keys match
#: ``[project.optional-dependencies]`` in ``pyproject.toml``; values are import
#: names, not distribution names, because that is what a failed import reports.
EXTRA_MODULES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "ingest": ("bs4", "fitz", "markdownify", "requests"),
        "video": ("mlx_whisper", "slugify", "yt_dlp"),
    },
)

#: External binaries an extra needs beyond its Python packages, with the
#: command that installs each on macOS.
EXTRA_BINARIES: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        "ingest": MappingProxyType({}),
        "video": MappingProxyType({"ffmpeg": "brew install ffmpeg"}),
    },
)


class MissingExtraError(RuntimeError):
    """Raised when a feature's optional dependencies are not installed."""

    def __init__(self, extra: str, module: str | None = None) -> None:
        """Build the error.

        Args:
            extra: The extra that provides the missing dependency.
            module: The import name that failed, when it is known.

        """
        self.extra = extra
        self.module = module
        super().__init__(_missing_extra_message(extra, module))


class MissingBinaryError(RuntimeError):
    """Raised when an external command an extra depends on is not on PATH."""

    def __init__(self, binary: str, hint: str) -> None:
        """Build the error.

        Args:
            binary: The command that could not be found.
            hint: The shell command that installs it.

        """
        self.binary = binary
        self.hint = hint
        super().__init__(f"{binary} not found — install it with `{hint}`")


def install_command(*wanted: str) -> str:
    """Return the command that installs ``wanted`` into the running environment.

    The extras already present are folded in, because reinstalling a uv tool
    replaces its environment: a command naming only the missing extra would
    remove the ones the user already had.

    Args:
        *wanted: Extras that must end up installed. Pass none to install the
            package with no extras at all.

    Returns:
        A single shell command, ready to paste.

    """
    names = set(wanted) | set(installed_extras())
    if names == set(EXTRA_MODULES):
        marker = "[all]"
    elif names:
        marker = f"[{','.join(sorted(names))}]"
    else:
        marker = ""
    spec = f'"okf-kb{marker} @ {GIT_SOURCE}"'
    if _is_uv_tool_install():
        # --force because the tool environment already exists; without it uv
        # reports "already installed" and the new extra never lands.
        return f"uv tool install --force {spec}"
    if _is_source_checkout():
        return "uv sync --group all"
    return f"uv pip install {spec}"


def installed_extras() -> list[str]:
    """Return the extras whose Python packages are all importable.

    Binaries are deliberately not considered: ``ffmpeg`` is installed by a
    different package manager, so its absence says nothing about which extras
    a reinstall needs to preserve.

    Returns:
        The names of the fully installed extras, in declaration order.

    """
    return [extra for extra in EXTRA_MODULES if not missing_modules(extra)]


@contextmanager
def required(extra: str) -> Iterator[None]:
    """Translate a failed optional import into an actionable error.

    Wraps an ``import`` of a dependency provided by ``extra``, so that a missing
    install reports which extra is absent and how to add it rather than only
    which module could not be found.

    Args:
        extra: The extra that provides the imports made inside the block.

    Yields:
        Nothing; the block runs unchanged when the import succeeds.

    Raises:
        MissingExtraError: If an import inside the block fails.

    """
    try:
        yield
    except ImportError as exc:
        raise MissingExtraError(extra, exc.name) from exc


def require_binary(binary: str, extra: str) -> str:
    """Locate an external command an extra depends on.

    Args:
        binary: The command to look for on PATH.
        extra: The extra that declares it, used to find the install hint.

    Returns:
        The absolute path to the command.

    Raises:
        MissingBinaryError: If the command is not on PATH.
        KeyError: If ``extra`` does not declare ``binary``.

    """
    found = shutil.which(binary)
    if found is None:
        raise MissingBinaryError(binary, EXTRA_BINARIES[extra][binary])
    return found


def missing_modules(extra: str) -> list[str]:
    """Return the import names of ``extra`` that are not installed.

    Args:
        extra: The extra to probe.

    Returns:
        The missing import names, in declaration order. Empty when the extra is
        fully installed.

    Raises:
        KeyError: If ``extra`` is not a known extra.

    """
    import importlib.util  # noqa: PLC0415

    missing = []
    for module in EXTRA_MODULES[extra]:
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(module)
    return missing


def missing_binaries(extra: str) -> list[str]:
    """Return the external commands ``extra`` needs that are not on PATH.

    Args:
        extra: The extra to probe.

    Returns:
        The missing command names, in declaration order.

    Raises:
        KeyError: If ``extra`` is not a known extra.

    """
    return [name for name in EXTRA_BINARIES[extra] if shutil.which(name) is None]


def _missing_extra_message(extra: str, module: str | None) -> str:
    """Compose the user-facing text for a missing extra.

    Args:
        extra: The extra that is absent.
        module: The import name that failed, when known.

    Returns:
        A multi-line message naming the caller, the extra, and the fix.

    """
    because = f" (no module named {module!r})" if module else ""
    lines = [
        (
            f"{_program_name()} needs the okf-kb [{extra}] extra, "
            f"which is not installed{because}."
        ),
        "",
        "Install it with:",
        "",
        f"    {install_command(extra)}",
    ]
    missing = [
        f"`{hint}`"
        for name, hint in EXTRA_BINARIES[extra].items()
        if shutil.which(name) is None
    ]
    if missing:
        lines += ["", f"[{extra}] also needs: {', '.join(missing)}"]
    return "\n".join(lines)


def _program_name() -> str:
    """Return the running command's name for use in error messages.

    Returns:
        The basename of ``sys.argv[0]``, or ``"okf-kb"`` when there is none.

    """
    argv0 = sys.argv[0] if sys.argv else ""
    return Path(argv0).name or "okf-kb"


def _is_uv_tool_install() -> bool:
    """Report whether this process runs from a ``uv tool install`` environment.

    Returns:
        True when the interpreter's prefix sits under uv's tool directory.

    """
    parts = Path(sys.prefix).parts
    return "uv" in parts and "tools" in parts


def _is_source_checkout() -> bool:
    """Report whether this process runs from the package's own working tree.

    Returns:
        True when the package is imported from a ``src/`` layout whose project
        root holds the ``pyproject.toml`` that declares these extras.

    """
    src_root = Path(__file__).resolve().parent.parent
    return src_root.name == "src" and (src_root.parent / "pyproject.toml").is_file()
