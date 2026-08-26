"""Tests for ``kb-doctor``.

The skills lean on this command's exit code to decide whether to warn, so the
exit contract matters more than the wording: a missing extra is reported but
not an error unless the caller said it needed one.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from okf_kb import doctor, extras

runner = CliRunner()


@pytest.fixture
def _installed(monkeypatch) -> None:
    """Report every extra and every core command as present."""
    monkeypatch.setattr(extras, "missing_modules", lambda _extra: [])
    monkeypatch.setattr(extras, "missing_binaries", lambda _extra: [])
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.fixture
def _video_missing(monkeypatch) -> None:
    """Report [video] as absent and everything else as present."""
    monkeypatch.setattr(
        extras,
        "missing_modules",
        lambda extra: ["yt_dlp"] if extra == "video" else [],
    )
    monkeypatch.setattr(extras, "missing_binaries", lambda _extra: [])
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.mark.usefixtures("_installed")
def test_a_complete_install_exits_zero():
    result = runner.invoke(doctor.app, [])

    assert result.exit_code == 0
    assert "✗" not in result.output


@pytest.mark.usefixtures("_video_missing")
def test_a_missing_extra_is_reported_but_not_an_error():
    result = runner.invoke(doctor.app, [])

    assert result.exit_code == 0
    assert "yt_dlp" in result.output
    assert "kb-video will fail" in result.output


@pytest.mark.usefixtures("_video_missing")
def test_requiring_a_missing_extra_exits_non_zero():
    assert runner.invoke(doctor.app, ["--require", "video"]).exit_code == 1


@pytest.mark.usefixtures("_video_missing")
def test_require_accepts_a_plugin_name():
    """The skills know plugin names, not extra names."""
    assert runner.invoke(doctor.app, ["--require", "kb-video"]).exit_code == 1
    assert runner.invoke(doctor.app, ["--require", "kb-ingest"]).exit_code == 0


@pytest.mark.usefixtures("_installed")
def test_require_rejects_an_unknown_name():
    result = runner.invoke(doctor.app, ["--require", "nonsense"])

    assert result.exit_code != 0
    assert "unknown extra or plugin" in result.output


@pytest.mark.usefixtures("_video_missing")
def test_json_output_is_machine_readable():
    result = runner.invoke(doctor.app, ["--json-output"])
    payload = json.loads(result.output)

    assert payload["core"]["ok"] is True
    assert payload["ingest"]["ok"] is True
    assert payload["video"]["ok"] is False
    assert payload["video"]["missing_modules"] == ["yt_dlp"]
    assert payload["video"]["plugins"] == ["kb-video"]
    assert payload["video"]["install"]


def test_a_broken_core_install_exits_non_zero(monkeypatch):
    monkeypatch.setattr(extras, "missing_modules", lambda _extra: [])
    monkeypatch.setattr(extras, "missing_binaries", lambda _extra: [])
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)

    result = runner.invoke(doctor.app, [])

    assert result.exit_code == 1
    assert "not on PATH" in result.output


def test_every_plugin_maps_to_a_real_extra():
    assert set(doctor.PLUGIN_EXTRAS.values()) <= set(extras.EXTRA_MODULES)
