#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from your distribution first." >&2
  exit 1
fi

echo "Installing system prerequisites for Fresh MCPE..."
sudo apt update
sudo apt install -y python3-venv python3-pip libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/fresh-mcpe.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fresh MCPE
Comment=Modern Minecraft Bedrock launcher interface for MCPelauncher
Exec=$ROOT/.venv/bin/python $ROOT/fresh_mcpe.py
Path=$ROOT
Terminal=false
Categories=Game;
StartupNotify=true
EOF
chmod 644 "$APP_DIR/fresh-mcpe.desktop"

echo
echo "Fresh MCPE is installed."
echo "Run it with: $ROOT/run.sh"
echo "It should also appear in your application menu."
echo "This installs the Fresh MCPE interface only; it does not install Minecraft or MCPelauncher."
