# Fresh MCPE roadmap

## First milestone in this repository

- [x] Dark desktop home and sidebar navigation
- [x] Detect installed versions in native and Flatpak data roots
- [x] Launch a selected installed version through MCPelauncher
- [x] Import resource and behavior packs from .mcpack/.mcaddon archives
- [x] Path-traversal checks for archive extraction
- [x] Browse, import, enable, and disable custom launcher-mod folders
- [x] Automatic changed-world backups before game launch
- [x] Manual backups, retention, and a guarded restore flow
- [x] Use the upstream sign-in/version-management UI
- [x] CI for core tests and Python syntax

## Next milestones

1. Exercise the first app on Pop!_OS with an installed native MCPelauncher client.
2. Add real integration tests around runtime paths and command-line behavior from several upstream versions.
3. Add a curated downloadable add-on catalog only after source URLs, licensing, version metadata, and checksums can be verified.
4. Add FPS/performance presets only where the selected runtime exposes a reliable supported setting.
5. Improve account status only if MCPelauncher offers a safe supported way to query it; never read or store raw login secrets.
6. Consider packaging as a .deb or AppImage after the app's runtime integration is stable.

## Non-goals

- Shipping Minecraft APKs, game libraries, paid content, or account credentials.
- Claiming all Bedrock versions work on Linux.
- Replacing the upstream compatibility layer or bypassing purchase/authentication checks.
- Silently overwriting worlds or packs.
