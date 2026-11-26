"""Tests for the pure helpers in fedoraniri.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fedoraniri


@pytest.fixture
def runner() -> fedoraniri.Runner:
    return fedoraniri.Runner(check=False, verbose=False)


def test_render_environment_omits_driver_when_empty() -> None:
    content = fedoraniri.render_environment({"libva_driver": ""})
    assert "LIBVA_DRIVER_NAME" not in content
    assert "MOZ_ENABLE_WAYLAND=1" in content


def test_render_environment_includes_driver() -> None:
    content = fedoraniri.render_environment({"libva_driver": "iHD"})
    assert 'LIBVA_DRIVER_NAME="iHD"' in content


def test_ensure_line_is_idempotent(runner: fedoraniri.Runner, tmp_path: Path) -> None:
    target = tmp_path / "bashrc"
    target.write_text("existing\n", encoding="utf-8")
    fedoraniri.ensure_line(runner, target, 'export EDITOR="nvim"')
    fedoraniri.ensure_line(runner, target, 'export EDITOR="nvim"')
    assert target.read_text(encoding="utf-8").count('export EDITOR="nvim"') == 1


def test_managed_block_replaces_existing_block(
    runner: fedoraniri.Runner, tmp_path: Path
) -> None:
    target = tmp_path / "config.kdl"
    target.write_text(
        "before\n"
        "// BEGIN ANSIBLE MANAGED DMS KEYBINDINGS\n"
        "old binds {}\n"
        "// END ANSIBLE MANAGED DMS KEYBINDINGS\n"
        "after\n",
        encoding="utf-8",
    )
    fedoraniri.managed_block(
        runner, target, fedoraniri.KEYBINDINGS_MARKER, "binds { new = true; }"
    )
    fedoraniri.managed_block(
        runner, target, fedoraniri.KEYBINDINGS_MARKER, "binds { new = true; }"
    )
    content = target.read_text(encoding="utf-8")
    assert content.count("// BEGIN ANSIBLE MANAGED DMS KEYBINDINGS") == 1
    assert "old binds {}" not in content
    assert "binds { new = true; }" in content


def test_resolve_repo_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "TEST_TOKEN")
    config = {
        "github_user": "example",
        "dotfiles_repo": "https://github.com/{{ github_user }}/dotfiles.git",
    }
    resolved = fedoraniri.resolve_repo(config)
    assert resolved.startswith("https://TEST_TOKEN@github.com/example/")


def test_unique_backup_path(tmp_path: Path) -> None:
    base = tmp_path / "niri.bak.20260101T000000"
    base.mkdir()
    assert (
        fedoraniri.unique_backup_path(base) == tmp_path / "niri.bak.20260101T000000_1"
    )
