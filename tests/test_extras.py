"""Tests for optional-dependency handling.

The point of this layer is that a missing extra produces a message the user can
act on, so most of these assert on message content rather than on types. The
additive install command carries the sharpest edge: a suggestion that names
only the missing extra would, under ``uv tool install --force``, uninstall the
extras the user already had.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

from okf_kb import extras

# -- required() --------------------------------------------------------------


def test_required_passes_a_successful_import_through():
    with extras.required("ingest"):
        module = importlib.import_module("json")

    assert module is not None


def test_required_translates_a_missing_module():
    with (
        pytest.raises(extras.MissingExtraError) as excinfo,
        extras.required("video"),
    ):
        importlib.import_module("definitely_not_a_real_module")

    assert excinfo.value.extra == "video"
    assert excinfo.value.module == "definitely_not_a_real_module"


def test_missing_extra_message_names_the_extra_and_the_fix(monkeypatch):
    monkeypatch.setattr(extras, "installed_extras", list)
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: True)
    monkeypatch.setattr(extras, "_is_source_checkout", lambda: False)
    monkeypatch.setattr(extras.sys, "argv", ["kb-video"])

    message = extras._missing_extra_message("video", "yt_dlp")

    assert "kb-video" in message
    assert "[video]" in message
    assert "yt_dlp" in message
    assert "uv tool install --force" in message


def test_missing_extra_message_mentions_a_missing_binary(monkeypatch):
    monkeypatch.setattr(extras.shutil, "which", lambda _name: None)

    message = extras._missing_extra_message("video", "yt_dlp")

    assert "brew install ffmpeg" in message


def test_missing_extra_message_omits_a_binary_already_on_path(monkeypatch):
    monkeypatch.setattr(extras.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    message = extras._missing_extra_message("video", "yt_dlp")

    assert "ffmpeg" not in message


# -- install_command() -------------------------------------------------------


def test_install_command_keeps_the_extras_already_installed(monkeypatch):
    """The whole point: --force replaces the environment, so the fix must add."""
    monkeypatch.setattr(extras, "installed_extras", lambda: ["ingest"])
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: True)

    command = extras.install_command("video")

    assert "okf-kb[all]" in command


def test_install_command_names_only_what_is_wanted_on_a_bare_install(monkeypatch):
    monkeypatch.setattr(extras, "installed_extras", list)
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: True)

    assert "okf-kb[ingest]" in extras.install_command("ingest")


def test_install_command_with_no_extras_installs_the_bare_package(monkeypatch):
    monkeypatch.setattr(extras, "installed_extras", list)
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: True)

    command = extras.install_command()

    assert "okf-kb @" in command
    assert "[" not in command.split("@")[0]


def test_install_command_prefers_uv_sync_in_a_source_checkout(monkeypatch):
    monkeypatch.setattr(extras, "installed_extras", list)
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: False)
    monkeypatch.setattr(extras, "_is_source_checkout", lambda: True)

    assert extras.install_command("video") == "uv sync --group all"


def test_install_command_falls_back_to_uv_pip(monkeypatch):
    monkeypatch.setattr(extras, "installed_extras", list)
    monkeypatch.setattr(extras, "_is_uv_tool_install", lambda: False)
    monkeypatch.setattr(extras, "_is_source_checkout", lambda: False)

    assert extras.install_command("video").startswith("uv pip install")


# -- probes ------------------------------------------------------------------


def test_missing_modules_reports_absent_imports(monkeypatch):
    monkeypatch.setattr(
        extras,
        "EXTRA_MODULES",
        {"ingest": ("json", "definitely_not_a_real_module")},
    )

    assert extras.missing_modules("ingest") == ["definitely_not_a_real_module"]


def test_missing_binaries_reports_absent_commands(monkeypatch):
    monkeypatch.setattr(extras.shutil, "which", lambda _name: None)

    assert extras.missing_binaries("video") == ["ffmpeg"]
    assert extras.missing_binaries("ingest") == []


def test_require_binary_raises_with_the_install_hint(monkeypatch):
    monkeypatch.setattr(extras.shutil, "which", lambda _name: None)

    with pytest.raises(extras.MissingBinaryError) as excinfo:
        extras.require_binary("ffmpeg", "video")

    assert "brew install ffmpeg" in str(excinfo.value)


def test_every_extra_in_pyproject_is_declared_here():
    """A new extra that this module does not know about would fail silently."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    optional = declared["project"]["optional-dependencies"]

    # "all" is a meta-extra pulling in the others, not one with its own modules.
    assert set(optional) - {"all"} == set(extras.EXTRA_MODULES)
    assert set(extras.EXTRA_MODULES) == set(extras.EXTRA_BINARIES)
