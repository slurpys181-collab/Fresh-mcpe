#!/usr/bin/env bash
set -euo pipefail

# Build a private MCPelauncher-derived runtime from source. This does not install
# or invoke a system mcpelauncher .deb, Flatpak, or system client executable.
RUNTIME_REPO="https://github.com/komixkat/mcpe.git"
RUNTIME_REF="9d8f19741dd894db25f4f8edb1d26c4b7b0ca5aa"
CACHE_HOME="$HOME/.cache"
if [[ -n "${XDG_CACHE_HOME:-}" ]]; then CACHE_HOME="$XDG_CACHE_HOME"; fi
SOURCE_DIR="$CACHE_HOME/fresh-mcpe/runtime-source"
BUILD_DIR="$CACHE_HOME/fresh-mcpe/runtime-build"
PREFIX="$HOME/.local/opt/fresh-mcpe/runtime"
DATA_HOME="$HOME/.local/share/fresh-mcpe"
DATA_DIR="$DATA_HOME/mcpelauncher"
JOBS=1
if [[ -n "${FRESH_MCPE_BUILD_JOBS:-}" ]]; then JOBS="$FRESH_MCPE_BUILD_JOBS"; fi

case "$(uname -m)" in
  x86_64|amd64) ABI="x86_64" ;;
  aarch64|arm64) ABI="arm64-v8a" ;;
  *)
    echo "Unsupported CPU architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

for tool in git cmake clang clang++ ninja curl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing build tool: $tool" >&2
    echo "Install the Pop!_OS build dependencies listed in runtime/README.md." >&2
    exit 1
  fi
done

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  mkdir -p "$(dirname "$SOURCE_DIR")"
  git clone --filter=blob:none "$RUNTIME_REPO" "$SOURCE_DIR"
fi

git -C "$SOURCE_DIR" fetch --tags origin
git -C "$SOURCE_DIR" checkout --detach "$RUNTIME_REF"
git -C "$SOURCE_DIR" submodule sync --recursive
git -C "$SOURCE_DIR" submodule update --init --recursive

mkdir -p "$BUILD_DIR" "$PREFIX" "$DATA_DIR/mods"
echo
echo "Building Fresh MCPE private runtime from source commit $RUNTIME_REF"
echo "Install prefix: $PREFIX"
echo "Private game data: $DATA_DIR"
echo "Build parallelism: $JOBS (override with FRESH_MCPE_BUILD_JOBS)"
echo

cmake -S "$SOURCE_DIR" -B "$BUILD_DIR/core" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_DEV_PATHS=OFF \
  -DBUILD_CLIENT=ON \
  -DBUILD_UI=OFF \
  -DBUILD_WEBVIEW=OFF \
  -Wno-dev

cmake --build "$BUILD_DIR/core" --parallel "$JOBS"
cmake --install "$BUILD_DIR/core"

if [[ ! -x "$PREFIX/bin/mcpelauncher-client" ]]; then
  echo "The runtime build did not produce $PREFIX/bin/mcpelauncher-client." >&2
  exit 1
fi

cmake -S "$SOURCE_DIR/ui" -B "$BUILD_DIR/ui" -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLAUNCHER_VERSION_NAME="Fresh-MCPE-runtime" \
  -DLAUNCHER_VERSION_CODE="$RUNTIME_REF" \
  -DLAUNCHER_DISABLE_DEV_MODE=OFF \
  -Wno-dev

cmake --build "$BUILD_DIR/ui" --parallel "$JOBS"
cmake --install "$BUILD_DIR/ui"

if [[ ! -x "$PREFIX/bin/mcpelauncher-ui-qt" ]]; then
  echo "The private runtime version manager was not built." >&2
  exit 1
fi

# Deploy the runtime compatibility bundle into the layout MCPelauncher discovers.
# This fork's checked-in patch bundle is versioned for its 1.26.45.1 updates mod.
UPDATE_VERSION="1.26.45.1"
UPDATE_MOD_DIR="$DATA_DIR/mods/mcpelauncher-updates/$UPDATE_VERSION/$ABI"
if [[ -f "$SOURCE_DIR/mods/libmcpelauncher-updates.so" ]]; then
  install -Dm755 "$SOURCE_DIR/mods/libmcpelauncher-updates.so" "$UPDATE_MOD_DIR/libmcpelauncher-updates.so"
fi
if [[ -d "$SOURCE_DIR/mods/patches" ]]; then
  mkdir -p "$UPDATE_MOD_DIR/patches"
  cp -a "$SOURCE_DIR/mods/patches/." "$UPDATE_MOD_DIR/patches/"
fi
if [[ ! -f "$UPDATE_MOD_DIR/libmcpelauncher-updates.so" ]]; then
  echo "WARNING: the source checkout did not include the prebuilt updates mod." >&2
  echo "Recent Bedrock versions may still require a compatible runtime patch." >&2
fi

cat > "$DATA_DIR/fresh-mcpe-runtime.json" <<EOF
{
  "source_repository": "$RUNTIME_REPO",
  "source_commit": "$RUNTIME_REF",
  "architecture": "$ABI",
  "prefix": "$PREFIX",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo
echo "Fresh MCPE's private runtime has been built."
echo "Game client: $PREFIX/bin/mcpelauncher-client"
echo "Version manager: $PREFIX/bin/mcpelauncher-ui-qt"
echo "Data: $DATA_DIR"
echo "The system MCPelauncher .deb / Flatpak was not used."
