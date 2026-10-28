# Fresh MCPE

**Fresh MCPE is a standalone launcher application for Minecraft Bedrock on Linux.** It has its own modern Qt interface, its own isolated game-data folder, and a private MCPelauncher-derived runtime built from source. It does **not** use an installed MCPelauncher .deb or Flatpak executable.

The visual direction is inspired by SKlauncher 4's dark navy / violet / lavender theme and modern layout, but Fresh MCPE has its own name, UI, code, and Bedrock-specific workflows.

## Current status

The launcher interface and core file-management tests are implemented. The private runtime build is scripted and pinned to a public source commit, but the full native runtime compile has not yet been run on this repository's CI. First use on Pop!_OS is still needed to confirm compilation, sign-in, a real version download, and launching a game.

## Features in this build

- **Three-column launcher layout:** slim icon rail, main launch workspace, and right-side starter news/social rail.
- **Quick Play:** installed Bedrock versions plus an add-version shortcut.
- **Private runtime:** build the MCPelauncher-derived client and version/authentication UI into ~/.local/opt/fresh-mcpe/runtime. Fresh MCPE launches only those private binaries; it never falls back to a system .deb or Flatpak binary.
- **Private game data:** versions, mods, and worlds are stored beneath ~/.local/share/fresh-mcpe/mcpelauncher, isolated from other launcher installs.
- **Bedrock add-ons:** import .mcpack, .mcaddon and compatible ZIP archives by file chooser or drag-and-drop; direct HTTPS archive URLs are also supported. Resource and behavior packs are routed by manifest type.
- **Mod manager:** import, download, enable and disable custom native launcher-mod folders. Native mods can execute code and should only come from sources you trust.
- **World safety:** automatic snapshots before launches when a world folder changes, manual snapshots, retention, and restore with a separate safety copy.
- **Performance:** launches the private game client directly and can optionally use Linux GameMode if installed.
- **Sign-in and version download:** opens the version/authentication component built in the same private source runtime; passwords are not collected by Fresh MCPE's own UI.

## Download Fresh MCPE

- [Download the latest source bundle as a ZIP](https://github.com/slurpys181-collab/Fresh-mcpe/archive/refs/heads/main.zip)
- [Browse the source code](https://github.com/slurpys181-collab/Fresh-mcpe)
- [Check automated tests](https://github.com/slurpys181-collab/Fresh-mcpe/actions/workflows/ci.yml)

The ZIP is the runnable project source, not a precompiled installer. The install script builds the private Bedrock launcher runtime on your Pop!_OS system. A full runtime build and live Bedrock launch have not yet been validated in CI.

## Install on Pop!_OS / Ubuntu

The full install builds the native game runtime from source and can install quite a few development dependencies. It needs internet access, free disk space for source/build outputs, and a working C/C++ toolchain.

1. Clone the repository:

   ~~~bash
   git clone https://github.com/slurpys181-collab/Fresh-mcpe.git
   cd Fresh-mcpe
   ~~~

2. Run the installer:

   ~~~bash
   bash install.sh
   ~~~

   This installs dependencies through APT, the PySide6 interface into a local .venv, and builds the private runtime. It does not install, uninstall, or launch the MCPelauncher .deb or Flatpak package. The source build defaults to one compile job for computers with limited RAM.

3. Open **Fresh MCPE** from your applications menu or run:

   ~~~bash
   bash run.sh
   ~~~

To install only the interface for UI development, run bash install.sh --ui-only. Bedrock launching remains unavailable until bash runtime/build.sh completes successfully.

## Runtime build details

- Runtime source repository: https://github.com/komixkat/mcpe
- Pinned runtime commit: 9d8f19741dd894db25f4f8edb1d26c4b7b0ca5aa
- Runtime build instructions and packages: runtime/README.md
- Runtime source build output: ~/.local/opt/fresh-mcpe/runtime
- Fresh MCPE private data: ~/.local/share/fresh-mcpe/mcpelauncher
- Runtime source cache: ~/.cache/fresh-mcpe/runtime-source

The runtime is derived from GPL-3.0-licensed MCPelauncher sources. Fresh MCPE's own interface and core management code are independent project files. Minecraft game files are not included; they're downloaded through the runtime's account/version flow.

## Important limitation: Bedrock 1.26.60.4

The earlier crash reported libpairipcore.so failing to resolve __gnu_strerror_r. The public MCPelauncher updates-mod catalogue currently lists version-specific compatibility through Bedrock 1.26.45.1, not 1.26.60.4. Building a separate runtime removes the need for the installed system package, but does not magically create the missing compatibility patch. The 1.26.60.4 fix is **not confirmed** until a matching patch is available and the game actually launches on Pop!_OS. Do not delete your old world backups while testing.

## Tests

~~~bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q fresh_mcpe.py fresh_mcpe_core.py tests
bash -n install.sh runtime/build.sh run.sh
~~~

GitHub Actions runs the core tests, compiles Python, and constructs the Qt UI offscreen. The full C++ runtime build is not yet part of CI.

## Links

- Fresh MCPE source/issues: https://github.com/slurpys181-collab/Fresh-mcpe
- Pinned runtime source: https://github.com/komixkat/mcpe
- Official SKlauncher 4 visual reference: https://next.skmedix.pl/

## License

Fresh MCPE's own code is MIT-licensed. The separately built runtime source remains under the upstream fork's GPL-3.0 licence. Minecraft and its game files remain the property of their respective owners.
