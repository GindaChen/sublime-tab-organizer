#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

PLUGIN_DIR="${STO_PLUGIN_DIR:-$HOME/Library/Application Support/Sublime Text/Packages/User}"
CLI_DIR="${STO_CLI_DIR:-$HOME/.local/bin}"

mkdir -p "$PLUGIN_DIR"
mkdir -p "$CLI_DIR"

cp "$SCRIPT_DIR/plugin/SublimeTabOrganizer.py" "$PLUGIN_DIR/SublimeTabOrganizer.py"
echo "plugin -> $PLUGIN_DIR/SublimeTabOrganizer.py"

cp "$SCRIPT_DIR/cli/sto" "$CLI_DIR/sto"
chmod +x "$CLI_DIR/sto"
echo "cli    -> $CLI_DIR/sto"

cat <<EOF

Next:
  1. Restart Sublime Text (or disable/re-enable the plugin) to load the TCP server.
  2. Ensure $CLI_DIR is on your PATH.
  3. Try: sto ping && sto list
EOF
