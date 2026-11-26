# Fedoraniri Setup

![Status](https://img.shields.io/badge/Status-experimental-orange?style=for-the-badge)
![Language](https://img.shields.io/badge/Language-YAML%20%2B%20Python-2ea44f?style=for-the-badge)
![Deps](https://img.shields.io/badge/Deps-Ansible%20optional%20%7C%20Fedora%2045-2b6cb0?style=for-the-badge)
![Safety](https://img.shields.io/badge/Safety-no%20stored%20secrets-2ea44f?style=for-the-badge)
![Docs](https://img.shields.io/badge/Docs-MIT-2ea44f?style=for-the-badge)

Experimental setup for a Fedora desktop around the **Niri** Wayland compositor and **DankMaterialShell (DMS)**. It offers two entry points: the original Ansible playbook and a standalone Python script that needs no Ansible installation.

> **Status: experimental.** This is a learning project. Read the whole playbook and run it in check mode before using it on a real machine. It performs a full system upgrade, installs packages, replaces dotfiles, and can optionally reboot the machine.

Developer-facing architecture notes are in [docs/DESIGN.md](docs/DESIGN.md).

## 📋 What it does

1. Enables the COPR repositories needed for DMS and Ghostty.
2. Tunes `/etc/dnf/dnf.conf` and upgrades all installed packages when `run_upgrade` is true.
3. Installs RPM Fusion free/nonfree release packages.
4. Installs native DNF packages (compositor, shell, terminal, utilities, Flatpak CLI).
5. Adds Flathub and installs a set of Flatpak applications.
6. Clones a dotfiles repository into a private `0700` staging directory and removes it afterward.
7. Backs up an existing Niri config to a timestamped path, deploys `niri`, `nvim`, `waybar` (if present), `alacritty`, and `_extra_backup` into `$HOME/.config` and `$HOME`, and injects marked DMS keybindings into `config.kdl`.
8. Writes Wayland environment variables to `/etc/environment.d/99-fedoraniri.conf`, removes the old `~/.bash_profile` block, and keeps shell-only preferences in `~/.bashrc`.
9. Removes orphaned packages and clears the DNF cache.

Failures in any of these steps stop the play — there are no `ignore_errors` tasks left.

Greeter setup runs `dms-greeter enable --yes` with root privileges and `dms-greeter sync --yes` as your normal user, using non-interactive flags so Ansible cannot hang on a prompt.

DMS greeter launches Niri directly rather than through `niri-session`, so a login-shell file is not a reliable place for desktop environment variables. `/etc/environment.d/` is used instead; Niri's own `environment { }` config would not reach systemd-started DMS applications.

## ✅ Prerequisites

- Fedora 45 (the RPM Fusion URLs are templated on `ansible_facts['distribution_major_version']`).
- A normal (non-root) user with `sudo` access — the playbook prompts for a password with `-K`.
- Network access.
- For the Ansible path, run `./bootstrap.sh` first on a fresh install: it installs `ansible`, the `community.general` collection, and the DNF COPR plugin support.
- For the Python path, `python3` is enough; `./run.sh` installs it with `sudo dnf5 install -y python3` if it is missing.
- Both implementations enable the COPR repositories that provide `dms` and `ghostty` using the native `dnf5 copr` command: `duxlabs/dms-git`, `duxlabs/dux-repo`, and `avengemedia/danklinux`.
- A dotfiles repository you can clone. The default is `https://github.com/mrkv60/dotfiles.git`; see [Private dotfiles repository](#-private-dotfiles-repository) if yours is private.

## 🚀 Quick start

### Ansible playbook

On a fresh install, bootstrap the prerequisites first:

```bash
./bootstrap.sh
```

Then always start with a syntax check and a dry run:

```bash
ansible-playbook --syntax-check 'Fedoraniri setup.yml'
ansible-playbook -i localhost, --check --diff -K 'Fedoraniri setup.yml'
```

Then, if you accept the changes shown:

```bash
ansible-playbook -i localhost, -K 'Fedoraniri setup.yml'
```

`-i localhost,` supplies a minimal inline inventory and removes Ansible's "hosts list is empty" warning. `-K` prompts for the sudo password.

### No-Ansible script

The standalone script uses only the Python standard library:

```bash
./run.sh --check          # describe changes without applying them
./run.sh -v               # apply with verbose command output
```

`run.sh` prompts for your sudo password once, then uses `sudo` only for root-owned operations. It reads the same `config.json` as the playbook.

Useful overrides:

| Flag | Purpose |
| --- | --- |
| `--dotfiles-repo URL` | Use a fork or private repo. |
| `--dotfiles-version TAG` | Pin a branch or tag. |
| `--no-run-upgrade` | Skip the full DNF upgrade on repeat runs. |
| `--reboot` / `--no-reboot` | Override `reboot_after_setup`. |
| `--libva-driver iHD` | Set `LIBVA_DRIVER_NAME`. |
| `--config PATH` | Use a different shared config file. |

## ⚙️ Configuration

Defaults live in the shared `config.json` used by both implementations. Ansible overrides use `-e`; the Python script uses the flags in [Quick start](#-quick-start). `user_home` and `temp_dir` are derived from `$HOME` rather than stored in the config.

| Variable | Default | Purpose |
| --- | --- | --- |
| `github_user` | `mrkv60` | GitHub account used to build the default dotfiles URL. |
| `dotfiles_repo` | `https://github.com/{{ github_user }}/dotfiles.git` | Full clone URL. Change this for a fork or private repo. |
| `dotfiles_version` | `main` | Git branch or tag to check out; pin a tag for fully repeatable runs. |
| `copr_repos` | `duxlabs/dms-git`, `duxlabs/dux-repo`, `avengemedia/danklinux` | COPR projects enabled before package installation. |
| `run_upgrade` | `true` | Set to `false` on repeat runs to skip the full DNF upgrade. |
| `reboot_after_setup` | `false` | Allow the upgrade task to reboot at the end of the run. |
| `libva_driver` | `""` | Optional `LIBVA_DRIVER_NAME`; e.g. `-e libva_driver=iHD` for Intel or `nvidia`. |
| `user_home` | `{{ ansible_facts['env']['HOME'] }}` | Target home directory. |
| `temp_dir` | `{{ user_home }}/.local/share/fedoraniri/dotfiles_deployment` | Private `0700` staging directory; removed after deployment. |
| `dnf_apps` | see `config.json` | RPM packages to install. |
| `flatpak_apps` | see `config.json` | Flatpak application IDs to install. |

Example, using your own fork:

```bash
ansible-playbook -i localhost, -K -e 'github_user=yourname' 'Fedoraniri setup.yml'
```

## 🔐 Private dotfiles repository

No token or credential is stored in this repository. To use a private dotfiles repo, override `dotfiles_repo` at runtime.

Recommended: keep the credential in a vault-encrypted vars file. `.gitignore` already excludes `secrets.yml` and `*vault*.yml`.

```bash
ansible-vault create secrets.yml
# put this inside the encrypted file:
# dotfiles_repo: "https://mrkv60:YOUR_TOKEN@github.com/mrkv60/dotfiles.git"

ansible-playbook -i localhost, -K -e @secrets.yml --ask-vault-pass 'Fedoraniri setup.yml'
```

Alternative without writing the token to disk:

```bash
read -rs GITHUB_TOKEN
ansible-playbook -i localhost, -K \
  -e "dotfiles_repo=https://mrkv60:${GITHUB_TOKEN}@github.com/mrkv60/dotfiles.git" \
  'Fedoraniri setup.yml'
```

The second form leaves the token briefly visible in the process list; prefer the vault method. In both cases the clone task uses `no_log: true`, so Ansible will not print the URL.

For the Python script, export `GITHUB_TOKEN` in your shell and run `./run.sh`. The script injects the token only into the in-memory clone URL and marks that command as sensitive, so it never appears in logs.

## 🧪 Verification

Static checks used before publishing (all passed):

| Check | Command |
| --- | --- |
| Ansible lint | `ansible-lint 'Fedoraniri setup.yml'` |
| Ansible syntax | `ansible-playbook --syntax-check 'Fedoraniri setup.yml'` |
| Bash syntax | `bash -n bootstrap.sh` |
| Shell lint | `shellcheck bootstrap.sh` |
| Bash formatting | `shfmt -d bootstrap.sh` |
| Python compile | `python3 -m py_compile fedoraniri.py` |
| Python lint | `uvx ruff check fedoraniri.py tests/test_fedoraniri.py` |
| Python format | `uvx ruff format --check fedoraniri.py tests/test_fedoraniri.py` |
| Python types | `uvx mypy fedoraniri.py` |
| Python check mode | `./run.sh --check` (also exercised in a disposable container) |
| Python tests | `uvx pytest -q` |

Before changing a real machine, run the playbook's `--check --diff` dry run or `./run.sh --check` and review the proposed changes. A disposable Fedora container was used during development; a full Fedora VM run is still recommended.

## 🚦 Exit codes

| Exit code | Meaning |
| --- | --- |
| `0` | Setup completed successfully. |
| `1` | A step failed (for example, clone, package, Flatpak, or config deployment error). |
| `2` | Ansible could not parse or start the playbook (for example, syntax error or inventory problem). |

The Python script only uses `0` and `1`. Ansible's `2` applies to the playbook path.

## ⚠️ Known limitations

These are intentional learning exercises still to be worked through:

- A real Fedora Everything VM dry run has not been performed; verification is static plus a disposable container dry run.
- Rebooting is opt-in via `reboot_after_setup`. Handlers were reordered so DMS setup, keybindings, and Bluetooth run first, but if you enable the reboot the playbook will not continue afterwards.
- `peazip`, the nonexistent `@multimedia` group, `starship`, and `lxqt-policykit-agent` were removed because they are unavailable in the Fedora 45 repos and COPRs used here. `polkit-kde` replaces the LXQt polkit agent.
- `io.github.marmgros.waypaper` was removed because it is not published on Flathub; the Helix ID was corrected to `com.helix_editor.Helix`. The other eleven Flatpak IDs were verified against Flathub.
- Hardware video decoding is opt-in: no `LIBVA_DRIVER_NAME` is set unless you pass `libva_driver`.
- Timestamped Niri backups accumulate on repeated runs; prune old `niri.bak.*` directories manually if desired.
- The Python script is a reference implementation, not a byte-for-byte clone of Ansible behavior; its `--check` mode describes commands and file changes but cannot predict every tool's internal decision.
- The Python script's `--check` mode was exercised in the disposable container, but a full real run has not; only its helpers are unit-tested.
- No token or credential is stored in this repository. For a private dotfiles repo, use the workflow documented above.

## 📄 License

MIT — see [LICENSE](LICENSE).
