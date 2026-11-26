#!/usr/bin/env python3
"""Standalone Fedora/Niri/DMS setup using only the Python standard library.

This is an alternative to ``Fedoraniri setup.yml`` for systems where installing
Ansible is undesirable. Both implementations read ``config.json``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DNF_CONF = Path("/etc/dnf/dnf.conf")
ENVIRONMENT_FILE = Path("/etc/environment.d/99-fedoraniri.conf")
KEYBINDINGS_MARKER = "// {mark} ANSIBLE MANAGED DMS KEYBINDINGS"
WAYLAND_BLOCK_MARKER = "# {mark} ANSIBLE MANAGED WAYLAND ENGINE OPTIMIZATIONS"
SHELL_EXPORTS = (
    'export TERMINAL="ghostty"',
    'export EDITOR="nvim"',
    'export VISUAL="nvim"',
)
KEYBINDINGS = """binds {
    Mod+Space       { spawn "dms-launcher"; }
    Mod+D           { spawn "dms-launcher"; }
    Mod+Return      { spawn "ghostty"; }
    Mod+L           { spawn "dms-greeter" "--lock"; }
    XF86AudioRaiseVolume  allow-inhibited=true { spawn "wpctl" "set-volume" "@DEFAULT_AUDIO_SINK@" "5%+"; }
    XF86AudioLowerVolume  allow-inhibited=true { spawn "wpctl" "set-volume" "@DEFAULT_AUDIO_SINK@" "5%-"; }
    XF86AudioMute         allow-inhibited=true { spawn "wpctl" "set-mute"   "@DEFAULT_AUDIO_SINK@" "toggle"; }
    XF86MonBrightnessUp   allow-inhibited=true { spawn "brightnessctl" "set" "5%+"; }
    XF86MonBrightnessDown allow-inhibited=true { spawn "brightnessctl" "set" "5%-"; }
}"""

Config = dict[str, Any]


class SetupError(Exception):
    """A fatal, user-facing setup error."""


def log(message: str) -> None:
    """Print a progress message."""
    print(message, flush=True)


class Runner:
    """Run commands with optional check mode, sudo, and secret redaction."""

    def __init__(self, check: bool, verbose: bool) -> None:
        self.check = check
        self.verbose = verbose

    def run(
        self,
        cmd: Sequence[str],
        *,
        become: bool = False,
        mutating: bool = True,
        sensitive: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a command, or only describe it in check mode."""
        argv = ["sudo", *cmd] if become and os.geteuid() != 0 else list(cmd)
        shown = "<redacted>" if sensitive else " ".join(argv)

        if self.check and mutating:
            log(f"[check] would run: {shown}")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        if self.verbose:
            log(f"[run] {shown}")

        result = subprocess.run(argv, check=True, text=True, capture_output=True)
        if self.verbose and result.stdout.strip():
            print(result.stdout, end="")
        if self.verbose and result.stderr.strip():
            print(result.stderr, end="", file=sys.stderr)
        return result


def as_bool(value: Any) -> bool:
    """Interpret a JSON or CLI boolean consistently."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def as_string_list(value: Any, name: str) -> list[str]:
    """Validate a config value that must be a list of strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SetupError(f"{name} must be a list of strings")
    return value


def load_config(path: Path) -> Config:
    """Load and validate the shared JSON configuration."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot load config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SetupError(f"config {path} must contain a JSON object")
    return data


def read_text(runner: Runner, path: Path, *, become: bool = False) -> str:
    """Read a UTF-8 text file, returning an empty string when it is absent."""
    if become and os.geteuid() != 0:
        result = runner.run(["cat", str(path)], become=True, mutating=False)
        return result.stdout
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise SetupError(f"cannot read {path}: {exc}") from exc


def write_text(
    runner: Runner,
    path: Path,
    content: str,
    mode: str,
    *,
    become: bool = False,
) -> bool:
    """Write a file only when its content changes; show a diff in check mode."""
    current = read_text(runner, path, become=become)
    if current == content:
        log(f"unchanged: {path}")
        return False

    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a{path}",
            tofile=f"b{path}",
        )
    )
    if runner.check:
        log(f"[check] would write: {path}")
        if diff:
            print(diff, end="")
        return True

    runner.run(["install", "-d", "-m", "0755", str(path.parent)], become=become)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.chmod(0o644)
        runner.run(["install", "-m", mode, str(temporary), str(path)], become=become)
    finally:
        temporary.unlink(missing_ok=True)
    log(f"wrote: {path}")
    return True


def ensure_line(runner: Runner, path: Path, line: str, *, become: bool = False) -> None:
    """Append a line to a file if it is not already present."""
    content = read_text(runner, path, become=become)
    if line in content.splitlines():
        log(f"already present in {path}: {line}")
        return
    prefix = content if content.endswith("\n") or not content else f"{content}\n"
    write_text(runner, path, f"{prefix}{line}\n", "0644", become=become)


def managed_block(runner: Runner, path: Path, marker: str, block: str) -> None:
    """Insert or replace a marked block, mirroring Ansible's blockinfile."""
    begin = marker.replace("{mark}", "BEGIN")
    end = marker.replace("{mark}", "END")
    lines = read_text(runner, path).splitlines()

    if begin in lines and end in lines:
        start = lines.index(begin)
        finish = lines.index(end)
        updated = [
            *lines[:start],
            begin,
            *block.splitlines(),
            end,
            *lines[finish + 1 :],
        ]
    else:
        updated = [*lines, begin, *block.splitlines(), end]
    write_text(runner, path, f"{'\n'.join(updated)}\n", "0644")


def resolve_repo(config: Config) -> str:
    """Build the dotfiles URL without ever exposing a token in logs."""
    repo = str(config["dotfiles_repo"]).replace(
        "{{ github_user }}", str(config["github_user"])
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token and repo.startswith("https://github.com/"):
        repo = repo.replace("https://github.com/", f"https://{token}@github.com/", 1)
    return repo


def distribution_major_version() -> str:
    """Return the Fedora major version from /etc/os-release."""
    release = platform.freedesktop_os_release()
    version = str(release.get("VERSION_ID", "")).split(".")[0]
    if not version:
        raise SetupError("could not determine the distribution major version")
    return version


def render_environment(config: Config) -> str:
    """Render the systemd/PAM environment file."""
    lines = [
        "# Managed by Fedoraniri setup - do not edit by hand.",
        "# Read by PAM logins and the systemd user manager.",
        "",
        "MOZ_ENABLE_WAYLAND=1",
        'QT_QPA_PLATFORM="wayland;xcb"',
        'GDK_BACKEND="wayland,x11,*"',
        'CLUTTER_BACKEND="wayland"',
        "NIXOS_OZONE_WL=1",
        'ELECTRON_OZONE_PLATFORM_HINT="auto"',
        'XDG_CURRENT_DESKTOP="niri"',
        'XDG_SESSION_DESKTOP="niri"',
        'XDG_SESSION_TYPE="wayland"',
        "_JAVA_AWT_WM_NONREPARENTING=1",
    ]
    driver = str(config["libva_driver"])
    if driver:
        lines.extend(["", f'LIBVA_DRIVER_NAME="{driver}"'])
    return f"{'\n'.join(lines)}\n"


def unique_backup_path(base: Path) -> Path:
    """Return a backup path that does not yet exist."""
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{suffix}")
        suffix += 1
    return candidate


def copy_path(
    runner: Runner, source: Path, destination: Path, *, directory: bool
) -> None:
    """Copy a file or directory tree, preserving metadata."""
    if runner.check:
        log(f"[check] would copy: {source} -> {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if directory:
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
    else:
        shutil.copy2(source, destination)
    log(f"copied: {source} -> {destination}")


def ensure_copr_repos(runner: Runner, repos: list[str]) -> None:
    """Enable only COPR repositories that are not already enabled."""
    enabled = runner.run(["dnf5", "copr", "list"], become=True, mutating=False).stdout
    for repo in repos:
        if repo in enabled:
            log(f"COPR already enabled: {repo}")
            continue
        runner.run(["dnf5", "copr", "enable", "-y", repo], become=True)


def ensure_dnf_conf(runner: Runner) -> None:
    """Add the DNF5 tuning lines that still apply."""
    content = read_text(runner, DNF_CONF, become=True)
    lines = content.splitlines()
    missing = [
        item
        for item in ("max_parallel_downloads=10", "defaultyes=True")
        if item not in lines
    ]
    if not missing:
        log(f"unchanged: {DNF_CONF}")
        return
    prefix = content if content.endswith("\n") or not content else f"{content}\n"
    write_text(runner, DNF_CONF, f"{prefix}{'\n'.join(missing)}\n", "0644", become=True)


def deploy_dotfiles(runner: Runner, config: Config, home: Path) -> None:
    """Clone dotfiles into a private staging directory and deploy them."""
    staging = home / ".local/share/fedoraniri/dotfiles_deployment"
    if staging.exists():
        if runner.check:
            log(f"[check] would remove: {staging}")
        else:
            shutil.rmtree(staging)
            log(f"removed stale staging: {staging}")

    try:
        if runner.check:
            log(f"[check] would create private staging directory: {staging}")
        else:
            staging.mkdir(parents=True, mode=0o700)
            os.chmod(staging, 0o700)

        runner.run(
            [
                "git",
                "clone",
                "--branch",
                str(config["dotfiles_version"]),
                resolve_repo(config),
                str(staging),
            ],
            sensitive=True,
        )

        niri = home / ".config" / "niri"
        if niri.is_dir():
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            backup = unique_backup_path(home / ".config" / f"niri.bak.{stamp}")
            runner.run(["mv", str(niri), str(backup)])

        if runner.check:
            log(
                "[check] would copy config directories: niri, nvim, waybar (if present)"
            )
            log("[check] would copy alacritty and _extra_backup (if present)")
            return

        for name in ("niri", "nvim"):
            source = staging / name
            if not source.is_dir():
                raise SetupError(f"dotfiles repo is missing required directory: {name}")
            copy_path(runner, source, home / ".config" / name, directory=True)

        waybar = staging / "waybar"
        if waybar.is_dir():
            copy_path(runner, waybar, home / ".config" / "waybar", directory=True)

        alacritty = staging / "alacritty"
        if alacritty.is_dir():
            copy_path(runner, alacritty, home / ".config" / "alacritty", directory=True)

        extra = staging / "_extra_backup"
        if extra.is_dir():
            copy_path(runner, extra, home, directory=True)
    finally:
        if staging.exists() and not runner.check:
            shutil.rmtree(staging, ignore_errors=True)
            log(f"removed staging: {staging}")


def remove_obsolete_wayland_block(runner: Runner, home: Path) -> None:
    """Remove the block written by older versions of the setup."""
    path = home / ".bash_profile"
    begin = WAYLAND_BLOCK_MARKER.replace("{mark}", "BEGIN")
    end = WAYLAND_BLOCK_MARKER.replace("{mark}", "END")
    lines = read_text(runner, path).splitlines()
    if begin not in lines and end not in lines:
        log(f"no obsolete Wayland block in {path}")
        return
    updated: list[str] = []
    skipping = False
    for line in lines:
        if line == begin:
            skipping = True
            continue
        if line == end:
            skipping = False
            continue
        if not skipping:
            updated.append(line)
    write_text(runner, path, f"{'\n'.join(updated)}\n", "0644")


def run_handlers(runner: Runner, config: Config, home: Path) -> None:
    """Run the same handlers Ansible would run at the end of the play."""
    runner.run(["dms-greeter", "enable", "--yes"], become=True)
    runner.run(["dms-greeter", "sync", "--yes"])
    managed_block(
        runner,
        home / ".config" / "niri" / "config.kdl",
        KEYBINDINGS_MARKER,
        KEYBINDINGS,
    )
    runner.run(
        ["systemctl", "enable", "--now", "bluetooth.service"],
        become=True,
    )
    if as_bool(config["reboot_after_setup"]):
        runner.run(["reboot"], become=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line overrides."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "-C",
        "--check",
        action="store_true",
        help="describe changes without applying them",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print command output"
    )
    parser.add_argument("--dotfiles-repo", help="override the dotfiles clone URL")
    parser.add_argument("--dotfiles-version", help="override the git branch or tag")
    parser.add_argument(
        "--run-upgrade",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="run the full DNF upgrade (default: from config.json)",
    )
    parser.add_argument(
        "--reboot",
        dest="reboot_after_setup",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="reboot after setup (default: from config.json)",
    )
    parser.add_argument("--libva-driver", help="set LIBVA_DRIVER_NAME")
    return parser.parse_args(argv)


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Overlay CLI options onto the shared configuration."""
    updated = dict(config)
    if args.dotfiles_repo is not None:
        updated["dotfiles_repo"] = args.dotfiles_repo
    if args.dotfiles_version is not None:
        updated["dotfiles_version"] = args.dotfiles_version
    if args.run_upgrade is not None:
        updated["run_upgrade"] = args.run_upgrade
    if args.reboot_after_setup is not None:
        updated["reboot_after_setup"] = args.reboot_after_setup
    if args.libva_driver is not None:
        updated["libva_driver"] = args.libva_driver
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    """Run the full setup."""
    args = parse_args(argv)
    try:
        config = apply_overrides(load_config(args.config), args)
        repos = as_string_list(config["copr_repos"], "copr_repos")
        packages = as_string_list(config["dnf_apps"], "dnf_apps")
        flatpaks = as_string_list(config["flatpak_apps"], "flatpak_apps")
        major = distribution_major_version()
        home = Path(os.environ["HOME"])

        if os.geteuid() != 0:
            subprocess.run(["sudo", "-v"], check=True)

        runner = Runner(check=args.check, verbose=args.verbose)
        log("Starting Fedoraniri setup" + (" (check mode)" if args.check else ""))

        ensure_copr_repos(runner, repos)
        ensure_dnf_conf(runner)

        if as_bool(config["run_upgrade"]):
            runner.run(["dnf5", "upgrade", "-y"], become=True)

        runner.run(
            [
                "dnf5",
                "install",
                "-y",
                f"https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-{major}.noarch.rpm",
                f"https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{major}.noarch.rpm",
            ],
            become=True,
        )
        runner.run(["dnf5", "install", "-y", *packages], become=True)

        runner.run(
            [
                "flatpak",
                "remote-add",
                "--user",
                "--if-not-exists",
                "flathub",
                "https://dl.flathub.org/repo/flathub.flatpakrepo",
            ]
        )
        for app in flatpaks:
            runner.run(["flatpak", "install", "--user", "-y", "flathub", app])

        (home / ".config").mkdir(parents=True, exist_ok=True)
        deploy_dotfiles(runner, config, home)

        write_text(
            runner, ENVIRONMENT_FILE, render_environment(config), "0644", become=True
        )
        for line in SHELL_EXPORTS:
            ensure_line(runner, home / ".bashrc", line)
        remove_obsolete_wayland_block(runner, home)

        runner.run(["dnf5", "autoremove", "-y"], become=True)
        runner.run(["dnf5", "clean", "all"], become=True)

        run_handlers(runner, config, home)
        log("Setup complete. Reboot when convenient, then log in via DMS.")
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"error: command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}",
            file=sys.stderr,
        )
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"error: missing config key {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
