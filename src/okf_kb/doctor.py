"""Report which parts of the okf-kb install are present, and how to fix the rest.

The extras are lazily imported, which is what keeps a core-only install usable —
but it also means ``kb-ingest --help`` succeeds whether or not ``[ingest]`` is
there. Nothing short of running a real conversion tells you, and by then the
user is already mid-task.

``kb-doctor`` is the probe that answers it up front: what is installed, what a
given plugin needs, and the one command that closes the gap. ``kb-doctor
bundles`` answers the other question a skill needs settled before it starts:
which knowledge bases are in scope from where it is standing.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from typing import Annotated, Any

import typer

from okf_kb import config, extras
from okf_kb.frontmatter import is_article

app = typer.Typer(help="Check the okf-kb install and report what is missing.")

#: The commands a core install puts on PATH.
CORE_COMMANDS = (
    "kb-index",
    "kb-health",
    "kb-search",
    "kb-stats",
    "kb-provenance",
    "kb-export",
    "kb-graph",
    "kb-read",
)

#: Which extra each plugin's skills depend on. The plugin names are the ones
#: users pass to ``claude plugin install``. ``None`` means the plugin needs only
#: the core install; it is listed so ``--require`` accepts its name.
PLUGIN_EXTRAS: dict[str, str | None] = {
    "kb-ingest": "ingest",
    "kb-video": "video",
    "kb-query": None,
}


@dataclass
class ExtraState:
    """What is present and absent for one extra."""

    ok: bool
    plugins: list[str]
    missing_modules: list[str] = field(default_factory=list)
    missing_binaries: list[str] = field(default_factory=list)
    install: str = ""


@dataclass
class BundleState:
    """One bundle in scope, as ``kb-doctor bundles`` reports it."""

    name: str
    path: str
    source: str
    ok: bool
    articles: int


@dataclass
class CoreState:
    """What is present and absent for the core install."""

    ok: bool
    missing_commands: list[str] = field(default_factory=list)
    install: str = ""


def _core_state() -> CoreState:
    """Probe the core install.

    Returns:
        The state of the ``kb-*`` commands a core install provides.

    """
    missing = [cmd for cmd in CORE_COMMANDS if shutil.which(cmd) is None]
    return CoreState(
        ok=not missing,
        missing_commands=missing,
        install="" if not missing else extras.install_command(),
    )


def _extra_state(extra: str) -> ExtraState:
    """Probe one extra.

    Args:
        extra: The extra to probe.

    Returns:
        Its missing modules and binaries, and the command that installs them.

    """
    modules = extras.missing_modules(extra)
    binaries = extras.missing_binaries(extra)
    return ExtraState(
        ok=not modules and not binaries,
        plugins=[name for name, dep in PLUGIN_EXTRAS.items() if dep == extra],
        missing_modules=modules,
        missing_binaries=binaries,
        install="" if not modules else extras.install_command(extra),
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    require: Annotated[
        list[str] | None,
        typer.Option(
            "--require",
            help="Exit non-zero unless this extra or plugin is fully installed. "
            "Repeatable. Accepts an extra (ingest, video) or a plugin name "
            "(kb-ingest, kb-video, kb-query).",
        ),
    ] = None,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json-output", help="Emit the report as JSON."),
    ] = False,
) -> None:
    """Check the install and report what is missing.

    Exits 0 when everything asked for is present and 1 otherwise. With no
    ``--require``, only a broken core install fails: extras are opt-in, so
    their absence is reported without being treated as an error.

    Args:
        ctx: The typer context, used to step aside when a subcommand runs.
        require: Extras or plugins that must be fully installed.
        json_output: Emit the report as JSON.

    Raises:
        typer.BadParameter: If ``--require`` names an unknown extra or plugin.
        typer.Exit: With code 1 when a required component is missing.

    """
    if ctx.invoked_subcommand is not None:
        return
    wanted: list[str] = []
    for name in require or []:
        extra = PLUGIN_EXTRAS.get(name, name)
        if extra is None:
            # A core-only plugin is satisfied by the core check below.
            continue
        if extra not in extras.EXTRA_MODULES:
            known = ", ".join([*extras.EXTRA_MODULES, *PLUGIN_EXTRAS])
            msg = f"unknown extra or plugin {extra!r}; expected one of: {known}"
            raise typer.BadParameter(msg)
        wanted.append(extra)

    core = _core_state()
    states = {extra: _extra_state(extra) for extra in extras.EXTRA_MODULES}

    if json_output:
        payload = {"core": asdict(core)} | {
            name: asdict(state) for name, state in states.items()
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        _print_report(core, states)

    if not core.ok or any(not states[extra].ok for extra in wanted):
        raise typer.Exit(1)


def _print_report(core: CoreState, states: dict[str, ExtraState]) -> None:
    """Write the report to stdout in human-readable form.

    Args:
        core: The core install's state.
        states: One entry per extra, keyed by extra name.

    """
    label_width = max(len(name) for name in states) + 2

    if core.ok:
        typer.echo(f"✓ {'core':<{label_width}}  the kb-* commands are on PATH")
    else:
        typer.echo(
            f"✗ {'core':<{label_width}}  not on PATH: "
            f"{', '.join(core.missing_commands)}",
        )
        typer.echo(f"    {core.install}")

    for name, state in states.items():
        label = f"[{name}]"
        needed_by = ", ".join(state.plugins) or "no plugin"
        if state.ok:
            typer.echo(f"✓ {label:<{label_width}}  available for {needed_by}")
            continue
        gaps = ", ".join([*state.missing_modules, *state.missing_binaries])
        typer.echo(
            f"✗ {label:<{label_width}}  missing {gaps} — {needed_by} will fail",
        )
        if state.install:
            typer.echo(f"    {state.install}")
        for binary in state.missing_binaries:
            typer.echo(f"    {extras.EXTRA_BINARIES[name][binary]}")


def _bundle_state(bundle: config.Bundle) -> BundleState:
    """Describe one resolved bundle.

    Args:
        bundle: The bundle to describe.

    Returns:
        Its name, root, source, whether ``okf.toml`` is present, and how many
        articles its wiki holds.

    """
    root = bundle.config.root
    wiki = bundle.config.wiki
    articles = (
        sum(1 for p in wiki.rglob("*.md") if is_article(p)) if wiki.is_dir() else 0
    )
    return BundleState(
        name=bundle.name,
        path=str(root),
        source=bundle.source,
        ok=(root / config.CONFIG_FILENAME).is_file(),
        articles=articles,
    )


def scope_report(kb: list[str] | None = None) -> dict[str, Any]:
    """Describe the bundles in scope, treating an empty scope as a state.

    Args:
        kb: Explicit bundles to resolve instead of the default scope.

    Returns:
        ``bundles``, one :class:`BundleState` mapping per bundle, and, when
        none is in scope, ``searched``: one line per place consulted.

    Raises:
        ConfigError: If the configuration is malformed or names a directory
            that is not a bundle.

    """
    try:
        states = [_bundle_state(b) for b in config.resolve_roots(kb)]
    except config.ScopeError as exc:
        return {"bundles": [], "searched": list(exc.searched)}
    return {"bundles": [asdict(s) for s in states]}


@app.command()
def bundles(
    kb: Annotated[
        list[str] | None,
        typer.Option(
            "--kb",
            help="Knowledge base to resolve: a name, a path, or 'all'. Repeatable.",
        ),
    ] = None,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json-output", help="Emit the listing as JSON."),
    ] = False,
) -> None:
    """List the knowledge bases in scope from the working directory.

    Having none in scope is a state, not a failure: this exits 0 with an empty
    list and says where it looked, so a skill can carry on without a wiki.

    Args:
        kb: Explicit bundles to resolve instead of the default scope.
        json_output: Emit the listing as JSON.

    Raises:
        typer.Exit: With code 1 when the configuration is malformed or names a
            directory that is not a bundle.

    """
    try:
        payload = scope_report(kb)
    except config.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    states = payload["bundles"]
    if not states:
        typer.echo("No knowledge base in scope. Searched:")
        for line in payload["searched"]:
            typer.echo(f"  - {line}")
        return

    width = max(len(s["name"]) for s in states)
    for state in states:
        mark = "✓" if state["ok"] else "✗"
        typer.echo(
            f"{mark} {state['name']:<{width}}  {state['path']}  "
            f"({state['source']}, {state['articles']} articles)",
        )
