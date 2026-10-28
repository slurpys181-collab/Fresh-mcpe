# Fresh MCPE

A modern dark desktop launcher interface for **Minecraft Bedrock Edition on Linux**, built to use the MCPelauncher runtime already installed on your computer.

> **Development status: early MVP.** The first build includes a Qt desktop UI, installed-version discovery, direct runtime launch, .mcpack / .mcaddon import, custom launcher-mod folder management, and automatic changed-world backups. This is not yet a fully independent fork of the native launcher.

## Screens and features

- **Home:** installed versions, pack/mod/world counts, and a direct Play action.
- **Add-ons:** import .mcpack, .mcaddon, or ZIP archives by button or drag-and-drop, or paste a direct HTTPS download URL. The importer reads manifest.json, routes resource packs to resource_packs and behavior packs to behavior_packs, rejects unsafe archive paths, and avoids silently overwriting installed packs.
- **Versions:** discover versions already present in native MCPelauncher or its Flatpak data folder. Launch an installed version directly through mcpelauncher-client.
- **Mods:** view custom launcher-mod directories, import ZIP/TAR archives, and enable/disable folders. The compatibility/update folder is protected. Native mods can execute code, so only import files from trusted sources.
- **World safety:** automatic backups before launching when world data has changed, manual snapshots on demand, retention limits, and restore with an extra safety copy first.
- **Performance:** launch directly and optionally wrap the game with Linux GameMode when it is installed. The FPS cap itself remains controlled by Minecraft's video settings.
- **Sign-in / downloads:** opens MCPelauncher's own UI. Fresh MCPE does not collect or store Google/Microsoft passwords and does not redistribute Minecraft binaries.

## Install on Pop!_OS / Ubuntu

1. Install the native MCPelauncher UI and client from the project's official instructions: https://minecraft-linux.github.io/
2. Download or clone this repository to a folder in your home directory.
3. Open Terminal in that folder and run:

   ~~~bash
   bash install.sh
   ~~~

   This installs Python/Qt dependencies in a local .venv and creates a Fresh MCPE app-menu shortcut. It does not remove or overwrite your existing launcher, worlds, or Flatpak install.

4. Launch **Fresh MCPE** from the app menu, or run:

   ~~~bash
   bash run.sh
   ~~~

## Develop / test

Requires Python 3.10+ and a working GUI session.

~~~bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q fresh_mcpe.py fresh_mcpe_core.py tests
.venv/bin/python fresh_mcpe.py
~~~

GitHub Actions runs the core tests and Python syntax checks on pushes and pull requests.

## Important details and limitations

- **MCPelauncher is still required.** Fresh MCPE is an interface and management layer; it does not contain the Android Bedrock runtime or game files, bypass purchase requirements, or replace Microsoft's/Google's supported authentication flow.
- **Version availability depends on MCPelauncher.** Only versions already installed are listed. Open MCPelauncher to sign in and download versions supported by that upstream project. A new interface cannot make an unsupported game binary compatible.
- **FPS is not artificially promised.** Fresh MCPE launches the selected game version directly to avoid keeping a second UI process open while playing. Actual frame rate depends on the game build and driver; set the preferred limit inside Minecraft's video settings.
- **Imported add-ons are installed, not automatically activated for every world.** Activate them in the intended world's Resource Packs / Behavior Packs settings.
- **Automatic backups use disk space.** Changed world folders are copied to ~/Documents/Fresh MCPE Backups. The retention setting prunes old automatic snapshots; keep separate copies of valuable worlds as well.
- **Native mods are trusted code.** Fresh MCPE rejects path-traversal archive entries and protects the standard MCPelauncher update-mod folder from the toggle control, but it cannot verify that third-party native code is safe.
- **Compatibility is not guaranteed for every release.** The app can report and preserve crash logs, but fixing an error such as a missing symbol in libpairipcore.so requires a compatible upstream runtime or patch.

## Runtime documentation

- MCPelauncher project: https://github.com/minecraft-linux/mcpelauncher-manifest
- Official installation guide: https://minecraft-linux.github.io/
- MCPelauncher FAQ / data paths: https://minecraft-linux.github.io/faq/
- Fresh MCPE issues: https://github.com/slurpys181-collab/Fresh-mcpe/issues

## License

Fresh MCPE's own code is MIT-licensed. Minecraft and MCPelauncher remain the property of their respective owners and are subject to their own licenses and terms.
