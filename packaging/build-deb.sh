#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VERSION="$(sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p' fresh_mcpe.py | head -n1)"
if [[ -z "$VERSION" ]]; then VERSION="0.2.0"; fi
ARCH="$(dpkg --print-architecture)"
PKG="fresh-mcpe"
STAGE="$ROOT/.package-stage"
OUT="$ROOT/dist"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/fresh-mcpe" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$OUT"
cp fresh_mcpe.py fresh_mcpe_core.py "$STAGE/opt/fresh-mcpe/"
cp -a runtime "$STAGE/opt/fresh-mcpe/"
cp -a tests "$STAGE/opt/fresh-mcpe/"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: games
Priority: optional
Architecture: $ARCH
Depends: python3, python3-pyside6.qtwidgets
Maintainer: Fresh MCPE contributors
Description: Standalone Minecraft Bedrock launcher for Linux
 A desktop launcher for managing a private MCPelauncher-derived runtime,
 Bedrock versions, add-ons, skins, mods and world backups.
EOF
cat > "$STAGE/usr/bin/fresh-mcpe" <<'EOF'
#!/usr/bin/env bash
set -e
cd /opt/fresh-mcpe
exec /usr/bin/python3 /opt/fresh-mcpe/fresh_mcpe.py "$@"
EOF
chmod 755 "$STAGE/usr/bin/fresh-mcpe"
cat > "$STAGE/usr/share/applications/fresh-mcpe.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Fresh MCPE
Comment=Launcher and manager for Minecraft Bedrock on Linux
Exec=fresh-mcpe
Icon=applications-games
Terminal=false
Categories=Game;
StartupNotify=true
EOF
dpkg-deb --root-owner-group --build "$STAGE" "$OUT/fresh-mcpe_${VERSION}_${ARCH}.deb"
echo "Package created:"
ls -lh "$OUT"/*.deb
