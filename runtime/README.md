# Fresh MCPE private runtime

Fresh MCPE does **not** depend on the MCPelauncher system .deb or Flatpak package. Its installer builds a private runtime prefix at:

- Runtime binaries: ~/.local/opt/fresh-mcpe/runtime/bin
- Game data and versions: ~/.local/share/fresh-mcpe/mcpelauncher
- Source checkout: ~/.cache/fresh-mcpe/runtime-source
- Build tree: ~/.cache/fresh-mcpe/runtime-build

## Build on Pop!_OS 24.04 / Ubuntu 24.04

From the repository root:

~~~bash
bash runtime/build.sh
~~~

The build script pins the runtime source to commit 9d8f19741dd894db25f4f8edb1d26c4b7b0ca5aa in the public GPL-3.0 fork at https://github.com/komixkat/mcpe. That fork adds recent Android Bedrock compatibility patches to the upstream MCPelauncher runtime. Fresh MCPE's own interface is a separate application.

### Dependencies

The one-time runtime build needs a C/C++ toolchain, CMake, Ninja, Git, Qt 6 and the multimedia / graphics development libraries used by the upstream source. The root install script installs these via APT on Pop!_OS or Ubuntu. If setting them up manually, install:

~~~bash
sudo apt update
sudo apt install -y \
  build-essential clang cmake ninja-build git curl pkg-config \
  python3-venv python3-pip \
  zlib1g-dev libpng-dev libjpeg-dev \
  libx11-dev libxext-dev libxrender-dev libxi-dev libxinerama-dev \
  libxcursor-dev libxrandr-dev libxfixes-dev libxss-dev libxkbcommon-dev \
  libxkbcommon-x11-0 libegl1-mesa-dev libgles2-mesa-dev libgl1-mesa-dev \
  libevdev-dev libudev-dev libasound2-dev libpulse-dev \
  libwayland-dev libssl-dev libcurl4-openssl-dev libzip-dev \
  protobuf-compiler libprotobuf-dev libuv1-dev \
  qt6-base-dev qt6-declarative-dev qt6-webengine-dev \
  qt6-webchannel-dev qt6-svg-dev qt6-tools-dev
~~~

A first source build can take a while and use several GB of disk space. The default is **one compile job** to reduce memory pressure. You can choose a higher value only if your system has enough free RAM:

~~~bash
FRESH_MCPE_BUILD_JOBS=2 bash runtime/build.sh
~~~

## Sign-in and version installation

After the source build finishes, the launcher offers the bundled version/authentication component built in the same private prefix. Its data home is isolated from installed .deb and Flatpak copies. Minecraft files still need to be downloaded through the supported account flow; this repository does not redistribute them.

## Important compatibility limitation

The previous reported crash was libpairipcore.so failing to find __gnu_strerror_r while launching Bedrock 1.26.60.4. At the time this repository was rebuilt, the public MCPelauncher updates-mod catalogue listed compatibility versions only through 1.26.45.1. This private source build removes the dependency on a system launcher package, but it **cannot guarantee that 1.26.60.4 will run** until a matching patch exists and is tested on Pop!_OS. Use a version with an available matching patch rather than repeatedly launching the crashing version.

## Data isolation

Fresh MCPE points XDG_DATA_HOME at ~/.local/share/fresh-mcpe, so the runtime's standard mcpelauncher folder is created beneath that Fresh MCPE home. It does not automatically copy worlds, sign-in state, or versions from another launcher. Copy world folders only after making a separate backup.
