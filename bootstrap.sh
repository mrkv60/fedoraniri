#!/usr/bin/env bash
# Bootstrap a fresh Fedora install (for example, Fedora Everything)
# so that 'Fedoraniri setup.yml' can be run.

set -euo pipefail

if [[ $EUID -eq 0 ]]; then
	echo "ERROR: run this script as your normal user, not as root." >&2
	exit 1
fi

echo "==> Installing Ansible and COPR prerequisites"
sudo dnf5 install -y ansible dnf5-plugins dnf-plugins-core

if ansible-galaxy collection list community.general >/dev/null 2>&1; then
	echo "==> community.general collection already present"
else
	echo "==> Installing community.general collection"
	ansible-galaxy collection install community.general
fi

echo
echo "Bootstrap complete. Next steps:"
echo "  ansible-playbook --syntax-check 'Fedoraniri setup.yml'"
echo "  ansible-playbook -i localhost, --check --diff -K 'Fedoraniri setup.yml'"
echo "  ansible-playbook -i localhost, -K 'Fedoraniri setup.yml'"
