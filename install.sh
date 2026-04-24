#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

PLUGIN_DIR="${STO_PLUGIN_DIR:-$HOME/Library/Application Support/Sublime Text/Packages/User}"
CLI_DIR="${STO_CLI_DIR:-$HOME/.local/bin}"

mkdir -p "$PLUGIN_DIR"
mkdir -p "$CLI_DIR"

# plugin + command palette file
cp "$SCRIPT_DIR/plugin/SublimeTabOrganizer.py" "$PLUGIN_DIR/SublimeTabOrganizer.py"
echo "plugin   -> $PLUGIN_DIR/SublimeTabOrganizer.py"
cp "$SCRIPT_DIR/plugin/Default.sublime-commands" "$PLUGIN_DIR/Default.sublime-commands"
echo "palette  -> $PLUGIN_DIR/Default.sublime-commands"

# cli
cp "$SCRIPT_DIR/cli/sto" "$CLI_DIR/sto"
chmod +x "$CLI_DIR/sto"
echo "cli      -> $CLI_DIR/sto"

# shell completions (best-effort — install to well-known per-shell locations when present)
install_completion() {
    local src="$1" dest_dir="$2" dest_name="$3"
    if [ -d "$dest_dir" ]; then
        cp "$src" "$dest_dir/$dest_name"
        echo "compl.   -> $dest_dir/$dest_name"
    fi
}

# zsh — prefer ~/.zsh/completions, fallback to /usr/local/share/zsh/site-functions or skip
ZSH_DIR="${STO_ZSH_COMPL_DIR:-$HOME/.zsh/completions}"
mkdir -p "$ZSH_DIR"
install_completion "$SCRIPT_DIR/completions/_sto" "$ZSH_DIR" "_sto"

# bash — source line appended to ~/.bash_completion if present, else just drop file
BASH_DIR="${STO_BASH_COMPL_DIR:-$HOME/.bash_completion.d}"
mkdir -p "$BASH_DIR"
install_completion "$SCRIPT_DIR/completions/sto.bash" "$BASH_DIR" "sto.bash"

# fish
FISH_DIR="${STO_FISH_COMPL_DIR:-$HOME/.config/fish/completions}"
if [ -d "$HOME/.config/fish" ]; then
    mkdir -p "$FISH_DIR"
    install_completion "$SCRIPT_DIR/completions/sto.fish" "$FISH_DIR" "sto.fish"
fi

cat <<EOF

Next:
  1. Restart Sublime Text (or disable/re-enable the plugin) to load the TCP server.
  2. Ensure $CLI_DIR is on your PATH.
  3. Try: sto ping && sto list

Shell completion:
  - zsh:   ensure $ZSH_DIR is on \$fpath, then \`autoload -Uz compinit && compinit\`.
  - bash:  \`source $BASH_DIR/sto.bash\` from your ~/.bashrc.
  - fish:  installed automatically if ~/.config/fish exists.
EOF
