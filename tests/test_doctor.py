"""Tests for ``kb-doctor``.

The skills lean on this command's exit code to decide whether to warn, so the
exit contract matters more than the wording: a missing extra is reported but
not an error unless the caller said it needed one. The same holds for
``kb-doctor bundles``: no knowledge base in scope is a state the query skill
carries on from, while a config naming a directory that is not a bundle is an
error it must surface.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from okf_kb import config, doctor, extras

if TYPE_CHECKING:
    from pathlib import Path

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
    # None marks a core-only plugin, which needs no extra at all.
    needed = {extra for extra in doctor.PLUGIN_EXTRAS.values() if extra is not None}
    assert needed <= set(extras.EXTRA_MODULES)


@pytest.mark.usefixtures("_installed")
def test_require_accepts_a_core_only_plugin():
    assert runner.invoke(doctor.app, ["--require", "kb-query"]).exit_code == 0


# -- kb-doctor bundles -------------------------------------------------------


@pytest.fixture
def scope(tmp_path, monkeypatch) -> Path:
    """Isolate bundle resolution and stand in an empty project directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    here = tmp_path / "project"
    here.mkdir()
    monkeypatch.chdir(here)
    return here


def _kb(root: Path, articles: int) -> Path:
    (root / "wiki").mkdir(parents=True)
    (root / config.CONFIG_FILENAME).write_text("", encoding="utf-8")
    (root / "wiki" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
    for n in range(articles):
        (root / "wiki" / f"a{n}.md").write_text("---\ntype: concept\n---\n")
    return root


def test_bundles_lists_every_bundle_in_scope(scope, tmp_path):
    work = _kb(tmp_path / "work", 2)
    client = _kb(tmp_path / "client", 1)
    (scope / config.PROJECT_FILENAME).write_text(
        f'[paths]\nwork = "{work}"\nclient = "{client}"\n',
        encoding="utf-8",
    )

    result = runner.invoke(doctor.app, ["bundles", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "searched" not in payload
    assert payload["bundles"] == [
        {
            "name": "work",
            "path": str(work.resolve()),
            "source": "project",
            "ok": True,
            "articles": 2,
        },
        {
            "name": "client",
            "path": str(client.resolve()),
            "source": "project",
            "ok": True,
            "articles": 1,
        },
    ]


@pytest.mark.usefixtures("scope")
def test_bundles_human_output_names_each_bundle(tmp_path):
    work = _kb(tmp_path / "work", 3)
    result = runner.invoke(doctor.app, ["bundles", "--kb", str(work)])
    assert result.exit_code == 0
    assert "work" in result.output
    assert "3 articles" in result.output
    assert "flag" in result.output


@pytest.mark.usefixtures("scope")
def test_bundles_with_nothing_in_scope_is_not_an_error():
    result = runner.invoke(doctor.app, ["bundles", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["bundles"] == []
    assert len(payload["searched"]) == 4


def test_bundles_with_a_broken_declaration_is_an_error(scope, tmp_path):
    (tmp_path / "empty").mkdir()
    (scope / config.PROJECT_FILENAME).write_text(
        f'[paths]\nwork = "{tmp_path / "empty"}"\n',
        encoding="utf-8",
    )

    result = runner.invoke(doctor.app, ["bundles"])

    assert result.exit_code == 1
    assert "holds no okf.toml" in result.output
