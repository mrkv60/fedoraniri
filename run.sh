#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
	echo "python3 is missing; installing it with sudo..." >&2
	sudo dnf5 install -y python3
fi

exec python3 "${script_dir}/fedoraniri.py" "$@"
