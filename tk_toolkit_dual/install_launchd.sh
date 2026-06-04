#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/install_launchd_instances.sh" "${1:-${TK_INSTANCE:-colleague}}"
