#!/usr/bin/env bash
set -euo pipefail

echo "tools/setup_codespace_wsl.sh is deprecated. Use: agp code start" >&2

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$repo_root/scripts/agp" code start "$@"
