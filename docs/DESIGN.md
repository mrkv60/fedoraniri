# Fedoraniri Setup — Design Notes

![Status](https://img.shields.io/badge/Status-experimental-orange?style=for-the-badge)
![Language](https://img.shields.io/badge/Language-YAML%20%2B%20Python-2ea44f?style=for-the-badge)
![Deps](https://img.shields.io/badge/Deps-Ansible%20optional%20%7C%20Fedora%2045-2b6cb0?style=for-the-badge)
![Safety](https://img.shields.io/badge/Safety-no%20stored%20secrets-2ea44f?style=for-the-badge)
![Docs](https://img.shields.io/badge/Docs-architecture-2ea44f?style=for-the-badge)

Developer-facing notes for the experimental Fedora/Niri/DMS setup. Two entry points share one configuration file. User-facing instructions are in the [README](../README.md).

## 🏗️ Architecture

The project has two implementations of the same flow plus a single source of truth for configuration.

| File | Responsibility |
| --- | --- |
| `config.json` | Shared defaults: repos, COPRs, flags, DNF apps, Flatpak IDs. JSON is valid YAML, so Ansible loads it with `vars_files`. |
| `Fedoraniri setup.yml` | Declarative localhost play using Ansible modules and handlers. |
| `fedoraniri.py` | Standalone stdlib-only implementation with its own check mode and idempotency helpers. |
| `run.sh` | Thin wrapper that installs `python3` if missing and executes `fedoraniri.py`. |
| `templates/fedoraniri-environment.conf.j2` | Ansible template for `/etc/environment.d/99-fedoraniri.conf`. |
| `bootstrap.sh` | Installs Ansible, `community.general`, and the DNF COPR plugin on a fresh Fedora system. |
| `tests/test_fedoraniri.py` | Pytest coverage for the Python helpers. |
| `README.md` | User-facing requirements, configuration, usage, and limitations. |
| `.gitignore` | Keeps secrets, SSH material, caches, and scratch output out of git. |
| `LICENSE` | MIT. |

There is no inventory file or role layout. `-i localhost,` is used on the command line to avoid Ansible's implicit-localhost warning.

```text
                    config.json
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
   bootstrap.sh                     run.sh
   (Ansible path)                   (Python path)
          │                             │
          ▼                             ▼
   Fedoraniri setup.yml           fedoraniri.py
          │                             │
          └──────────────┬──────────────┘
                         ▼
              Phase 0: COPR repos
              Phase 1: dnf.conf → gated upgrade → RPM Fusion → RPM apps
              Phase 2: Flathub remote → verified Flatpak IDs
              Phase 3: private staging → clone → backup/copy → cleanup
              Phase 4: /etc/environment.d → shell prefs → legacy cleanup
              Phase 5: autoremove → cache clean
              Finish: greeter enable → greeter sync → keybindings → Bluetooth → optional reboot
```

## 🔄 Execution flow

1. **Repositories first.** A read-only `dnf5 copr list` is registered, then native `dnf5 copr enable -y` commands enable `duxlabs/dms-git`, `duxlabs/dux-repo`, and `avengemedia/danklinux` when missing, so later DNF installs can resolve `dms` and `ghostty`.
2. **DNF phase.** Two applicable `dnf.conf` lines are added with `lineinfile` (`fastestmirror` was removed because DNF5 ignores it). The full upgrade and its user notice are gated by `run_upgrade | bool`, then RPM Fusion release RPMs are installed, followed by the `dnf_apps` list.
3. **Flatpak phase.** Flathub is registered with `method: user`, and each ID in `flatpak_apps` is installed through `community.general.flatpak`. All remaining IDs were checked with `flatpak remote-info --user flathub`.
4. **Dotfile phase.** A `0700` directory under `~/.local/share/fedoraniri` is cleared and recreated. A `block` clones a pinned branch/tag (`dotfiles_version`), backs up an existing `~/.config/niri` to a timestamped sibling path, copies directory contents (with trailing slashes), then removes the staging directory in `always`.
5. **Environment phase.** The Jinja2 template renders `/etc/environment.d/99-fedoraniri.conf`. `LIBVA_DRIVER_NAME` is emitted only when `libva_driver` is non-empty. Shell-only editor/terminal variables go to `~/.bashrc`; the old managed block in `~/.bash_profile` is removed.
6. **Cleanup phase.** `dnf5 autoremove` and `dnf5 clean all` run with `become: true`.
7. **Handlers.** Package changes notify greeter enable (root), greeter sync (normal user), and Bluetooth. Niri config changes notify the marked `blockinfile` keybindings block. Reboot is last and only when `reboot_after_setup` is true.

The Python implementation follows the same seven phases imperatively. Its helpers replace Ansible modules: `ensure_line()` for `lineinfile`, `write_text()` with a unified diff for `template`/`copy`, `managed_block()` for `blockinfile`, and `try/finally` for the staging cleanup. Handlers become ordinary functions called at the end.

## 🛡️ Safety decisions

| Decision | Reason |
| --- | --- |
| Separate experimental repo | Keeps changes away from the maintained `ymlfiles/` playbook. |
| Native `dnf5 copr` instead of `community.general.copr` | The Ansible module needs DNF4 Python bindings, which Fedora 45 does not provide; the dry run caught this. |
| Shared `config.json` | Both implementations consume the same defaults, preventing drift between the playbook and script. |
| No credentials in files | Public-safe. Ansible uses `ansible-vault` or runtime `-e`; the clone task uses `no_log: true`. The Python script reads `GITHUB_TOKEN` from the environment and marks the clone command sensitive. |
| No `ignore_errors` | A failed Flatpak, copy, or greeter step must fail the run rather than print a false success. |
| Private staging + `always` cleanup | Avoids a predictable `/tmp` path and prevents a credential-bearing `.git/config` from surviving a failure. |
| Timestamped Niri backup | Repeated runs no longer overwrite or nest into `niri.bak`. |
| Trailing slashes on directory copies | `copy` with `remote_src: true` nests a source directory into an existing destination; trailing slashes copy contents instead. |
| Unique marker for keybindings | `blockinfile` updates one marked block on reruns instead of appending duplicate `binds { }` blocks. |
| `--yes` on greeter commands | Prevents an interactive prompt from hanging Ansible. |
| `sync` without `become` | Per `dms-greeter sync --help`, it syncs the current user's DMS settings; running it as root would read the wrong config. |
| `/etc/environment.d` instead of `.bash_profile` | Greetd launches Niri directly, not via `niri-session`; Niri's own `environment { }` block does not reach systemd-started DMS apps. |
| `run_upgrade` gate | Repeat runs can skip the expensive full upgrade. |
| Opt-in reboot | A reboot ends the play, so it is never the default. |

## 📦 State and side effects

- **System files:** `/etc/dnf/dnf.conf`, `/etc/environment.d/99-fedoraniri.conf`, RPM Fusion repos, COPR repos, installed packages, greetd configuration, Bluetooth service state.
- **User files:** `~/.config/niri` (timestamped backup + deployed contents), `~/.config/{nvim,waybar,alacritty}`, `~/.bashrc`, `~/.bash_profile` (legacy block removed), and anything in the dotfiles repo's `_extra_backup/` overlaid into `$HOME`.
- **User installs:** Flathub remote and Flatpak apps under the invoking user's Flatpak installation.
- **Transient:** the `0700` staging directory is always deleted, including on failure.
- **Reversible?** Partially. Package installs and config deploys are not automatically rolled back. Niri's old config is preserved under `niri.bak.<timestamp>`. Greetd changes can be undone with `dms-greeter uninstall`.

## 🚨 Failure handling

- Any failed task stops the play; there are no `ignore_errors` tasks.
- The inner config-deployment `block` has a `rescue` that calls `ansible.builtin.fail` with a clear message instead of pretending a fallback exists.
- The outer dotfile `block` has an `always` cleanup even when clone or copy fails.
- Handlers run in declaration order: DMS greeter enable, DMS greeter sync, keybindings, Bluetooth, optional reboot. A failure in an earlier handler stops later handlers, including the reboot.
- Optional inputs (`waybar`, `alacritty`, `_extra_backup`) are guarded by `stat` checks rather than by ignoring errors.

## 🧪 Tests and verification

Static checks performed before publication:

| Layer | Command | Result |
| --- | --- | --- |
| Ansible lint | `ansible-lint 'Fedoraniri setup.yml'` | pass, 0 failures / 0 warnings |
| Ansible syntax | `ansible-playbook --syntax-check 'Fedoraniri setup.yml'` | pass |
| Task listing | `ansible-playbook -i localhost, --list-tasks 'Fedoraniri setup.yml'` | pass |
| Bash syntax | `bash -n bootstrap.sh` | pass |
| Shell lint | `shellcheck bootstrap.sh` | pass |
| Bash format | `shfmt -d bootstrap.sh` | pass |
| Template rendering | rendered with empty and `iHD` values of `libva_driver` | pass |
| Flatpak IDs | `flatpak remote-info --user flathub <id>` for every configured ID | pass (11 IDs) |
| `blockinfile` idempotency | two local runs against a sample `config.kdl` | pass (one marker pair) |
| `copy` nesting | local test with and without trailing slashes | pass (trailing slashes copy contents) |
| Disposable Fedora 45 container dry run | `ansible-playbook -i localhost, --check --diff -e run_upgrade=false` in Podman | completed through every task and handler; only failure was the systemd-dependent Bluetooth handler |
| Deprecation warnings | same container dry run | pass — 0 warnings after switching to `ansible_facts` |
| Python compile | `python3 -m py_compile fedoraniri.py` | pass |
| Python lint | `uvx ruff check fedoraniri.py tests/test_fedoraniri.py` | pass |
| Python format | `uvx ruff format --check fedoraniri.py tests/test_fedoraniri.py` | pass |
| Python types | `uvx mypy fedoraniri.py` | pass |
| Python tests | `uvx pytest -q` | pass (6 tests) |
| Python check mode | `python3 fedoraniri.py --check --dotfiles-repo /root/fake-dotfiles` in Podman | pass (exit 0), diffs shown for all file changes |
| Shared config | Ansible dry run after moving vars to `config.json` | pass — playbook loads config and reaches package installation |

The dry run found and fixed three real issues: `community.general.copr` needs DNF4 Python bindings unavailable on Fedora 45; `starship` and `lxqt-policykit-agent` are not shipped in the configured repos/COPRs. It also confirmed idempotent COPR gating, all 11 verified Flatpak IDs, the staging cleanup on failure, and the single marked keybindings block.

The playbook was **not** executed against the live system during verification. Check mode skips `command` tasks, so COPR repos were pre-enabled and the staging directory pre-populated with a local fake dotfiles repo to let later tasks resolve. A container has no systemd, so the Bluetooth `systemd_service` handler and the optional reboot handler cannot be exercised there.

## 🧭 Known limitations

- No disposable Fedora Everything VM run has been performed yet; that remains the recommended real-world smoke test. A disposable Fedora 45 container was used for check-mode testing instead.
- The Python script's `--check` mode was exercised in the disposable container, but its full real run has not; only the Ansible path has been dry-run end to end.
- `starship` and `lxqt-policykit-agent` are unavailable on Fedora 45 and were removed; `polkit-kde` replaces the latter.
- `fastestmirror=True` was removed because DNF5 ignores it.
- Timestamped Niri backups accumulate and must be pruned manually.
- Hardware video decoding requires an explicit `libva_driver` override.
- Some upstream package names are Fedora 45 / COPR specific and may need adjustment on other releases.
- The dotfiles repo default (`mrkv60/dotfiles`) is not part of this project and must be overridden if unavailable.

See the [README](../README.md) for setup instructions and configuration options.
