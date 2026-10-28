#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="${1:-full}"
if [[ "$MODE" != "full" && "$MODE" != "--ui-only" ]]; then
  echo "Usage: bash install.sh [--ui-only]" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from your distribution first." >&2
  exit 1
fi

echo "Installing Fresh MCPE build dependencies on Pop!_OS / Ubuntu..."
sudo apt update
sudo apt install -y \
  build-essential clang cmake ninja-build git curl pkg-config \
  python3-venv python3-pip \
  zlib1g-dev libpng-dev libjpeg-dev \
  libx11-dev libxext-dev libxrender-dev libxi-dev libxinerama-dev \
  libxcursor-dev libxrandr-dev libxfixes-dev libxss-dev libxkbcommon-dev \
  libxkbcommon-x11-0 libegl1-mesa-dev libgles2-mesa-dev libgl1-mesa-dev \
  libevdev-dev libudev-dev libasound2-dev libpulse-dev libwayland-dev \
  libssl-dev libcurl4-openssl-dev libzip-dev protobuf-compiler libprotobuf-dev \
  libuv1-dev qt6-base-dev qt6-declarative-dev qt6-webengine-dev \
  qt6-webchannel-dev qt6-svg-dev qt6-tools-dev libegl1 libgl1 libxcb-cursor0

# Ubuntu 24.04's Clang can need GCC 14's libstdc++ linker files even though
# the default g++ toolchain is GCC 13. Install this extra package only when
# the configured APT repositories offer it, so older Pop!_OS releases work too.
if apt-cache policy libstdc++-14-dev | grep -Eq 'Candidate: [^ (]'; then
  sudo apt install -y libstdc++-14-dev
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ "$MODE" != "--ui-only" ]]; then
  bash runtime/build.sh
else
  echo "UI-only install requested; Bedrock will not launch until runtime/build.sh succeeds."
fi

APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/fresh-mcpe.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fresh MCPE
Comment=Standalone Minecraft Bedrock launcher
Exec="$ROOT/.venv/bin/python" "$ROOT/fresh_mcpe.py"
Path=$ROOT
Terminal=false
Categories=Game;
StartupNotify=true
EOF
chmod 644 "$APP_DIR/fresh-mcpe.desktop"

echo
echo "Fresh MCPE's interface is installed."
echo "Run it with: bash $ROOT/run.sh"
echo "It should appear in your application menu."
if [[ "$MODE" == "--ui-only" ]]; then
  echo "Reminder: run bash runtime/build.sh to build the private Bedrock runtime."
fi
echo "Fresh MCPE never launches a system MCPelauncher .deb or Flatpak binary."
