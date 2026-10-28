"""Safe file and runtime operations for Fresh MCPE.

This module deliberately does not download or redistribute Minecraft binaries.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


# Fresh MCPE keeps its data and its separately built runtime isolated from any
# legacy MCPelauncher .deb/Flatpak installation.
FRESH_HOME = Path.home() / ".local/share/fresh-mcpe"
NATIVE_ROOT = FRESH_HOME / "mcpelauncher"
FLATPAK_ROOT = Path.home() / ".var/app/io.mrarm.mcpelauncher/data/mcpelauncher"  # migration source only
RUNTIME_ROOT = Path.home() / ".local/opt/fresh-mcpe/runtime"
MOJANG_RELATIVE = Path("games/com.mojang")
MAX_ARCHIVE_FILES = 25000
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class DataRoot:
    key: str
    label: str
    path: Path
    kind: str

    @property
    def game_dir(self) -> Path:
        return self.path / MOJANG_RELATIVE

    @property
    def versions_dir(self) -> Path:
        return self.path / "versions"

    @property
    def mods_dir(self) -> Path:
        return self.path / "mods"


@dataclass(frozen=True)
class InstalledVersion:
    name: str
    root_key: str
    root_label: str
    root_path: Path
    path: Path


@dataclass(frozen=True)
class InstalledPack:
    name: str
    kind: str
    version: str
    path: Path
    pack_uuid: str = ""


def discover_data_roots() -> list[DataRoot]:
    """Only discover Fresh MCPE's isolated data root; never launch a system install."""
    return [DataRoot("native", "Fresh MCPE runtime", NATIVE_ROOT, "bundled")]


def find_root(roots: Iterable[DataRoot], key: str) -> DataRoot:
    # Old settings may contain "flatpak"; never use it as the active runtime.
    for root in roots:
        if root.key == "native":
            return root
    return DataRoot("native", "Fresh MCPE runtime", NATIVE_ROOT, "bundled")


def discover_versions(roots: Iterable[DataRoot]) -> list[InstalledVersion]:
    result: list[InstalledVersion] = []
    for root in roots:
        if not root.versions_dir.is_dir():
            continue
        try:
            dirs = [p for p in root.versions_dir.iterdir() if p.is_dir()]
        except OSError:
            continue
        for folder in sorted(dirs, key=lambda p: (tuple(int(part) for part in re.findall("[0-9]+", p.name)), p.name.casefold()), reverse=True):
            result.append(InstalledVersion(folder.name, root.key, root.label, root.path, folder))
    return result


def safe_slug(value: str, fallback: str = "pack") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_")
    value = re.sub(r"-{2,}", "-", value)
    return value[:72] or fallback


def _safe_member_path(destination: Path, member_name: str) -> Path:
    # ZIP/TAR paths are POSIX paths even when created on another OS.
    member = PurePosixPath(member_name)
    if member.is_absolute() or any(part in ("..", "") for part in member.parts):
        raise ValueError(f"Unsafe archive path: {member_name}")
    target = (destination / Path(*member.parts)).resolve()
    base = destination.resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"Archive path escapes target: {member_name}")
    return target


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("Archive contains too many files.")
        expanded_size = sum(item.file_size for item in entries)
        if expanded_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive expands beyond the 1 GiB safety limit.")
        for item in entries:
            target = _safe_member_path(destination, item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic links are not allowed in imports: {item.filename}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as archive:
        entries = archive.getmembers()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("Archive contains too many files.")
        expanded_size = sum(item.size for item in entries if item.isfile())
        if expanded_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Archive expands beyond the 1 GiB safety limit.")
        for item in entries:
            target = _safe_member_path(destination, item.name)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            # Do not accept symlinks, hard links, devices, or special files.
            if not item.isfile():
                raise ValueError(f"Unsupported archive entry: {item.name}")
            source = archive.extractfile(item)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def read_manifest(folder: Path) -> dict | None:
    manifest_path = folder / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _manifest_kind(payload: dict) -> str | None:
    modules = payload.get("modules", [])
    types = {
        str(item.get("type", "")).lower()
        for item in modules if isinstance(item, dict)
    } if isinstance(modules, list) else set()
    if "resources" in types:
        return "resource_packs"
    if types.intersection({"data", "script", "client_data", "world_template"}):
        return "behavior_packs"
    return None


def _manifest_name(payload: dict, fallback: str) -> str:
    header = payload.get("header", {})
    if isinstance(header, dict):
        value = header.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def list_installed_packs(game_dir: Path) -> list[InstalledPack]:
    found: list[InstalledPack] = []
    for folder_name, kind in (("resource_packs", "Resource pack"), ("behavior_packs", "Behavior pack")):
        pack_root = game_dir / folder_name
        if not pack_root.is_dir():
            continue
        try:
            folders = [p for p in pack_root.iterdir() if p.is_dir()]
        except OSError:
            continue
        for folder in sorted(folders, key=lambda p: p.name.casefold()):
            payload = read_manifest(folder)
            if not payload:
                continue
            header = payload.get("header", {})
            header = header if isinstance(header, dict) else {}
            version_value = header.get("version", "?")
            version = ".".join(map(str, version_value)) if isinstance(version_value, list) else str(version_value)
            pack_uuid = str(header.get("uuid", ""))
            found.append(InstalledPack(
                _manifest_name(payload, folder.name),
                kind,
                version,
                folder,
                pack_uuid,
            ))
    return found


def _expand_embedded_mcpack_files(staging: Path) -> None:
    # Some .mcaddon files contain nested .mcpack archives instead of folders.
    embedded = [p for p in staging.rglob("*.mcpack") if p.is_file()]
    for index, pack_file in enumerate(embedded[:100]):
        target = staging / ".fresh-nested" / f"pack-{index}-{safe_slug(pack_file.stem)}"
        safe_extract_zip(pack_file, target)


def import_addon(archive_path: Path, game_dir: Path) -> list[InstalledPack]:
    archive_path = archive_path.expanduser().resolve()
    extension = archive_path.suffix.lower()
    if extension not in {".mcpack", ".mcaddon", ".zip"}:
        raise ValueError("Choose a .mcpack, .mcaddon, or ZIP add-on archive.")
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)

    installed: list[InstalledPack] = []
    with tempfile.TemporaryDirectory(prefix="fresh-mcpe-import-") as temp_name:
        staging = Path(temp_name) / "contents"
        safe_extract_zip(archive_path, staging)
        if extension == ".mcaddon":
            _expand_embedded_mcpack_files(staging)

        manifests = []
        for manifest_path in staging.rglob("manifest.json"):
            # Only manifests within safely extracted directories are considered.
            payload = read_manifest(manifest_path.parent)
            if payload and _manifest_kind(payload):
                manifests.append((manifest_path.parent, payload, _manifest_kind(payload)))

        # Deduplicate manifests if an archive repeats the same folder through nesting.
        seen: set[tuple[str, str]] = set()
        candidates = []
        for folder, payload, kind in manifests:
            header = payload.get("header", {})
            pack_uuid = str(header.get("uuid", "")) if isinstance(header, dict) else ""
            identity = (pack_uuid, str(folder.resolve())) if not pack_uuid else (pack_uuid, kind or "")
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append((folder, payload, kind))

        if not candidates:
            raise ValueError(
                "No valid Bedrock behavior/resource pack manifest was found. "
                "The archive may be for Java Edition or have an unsupported layout."
            )

        kinds = {"resource_packs": game_dir / "resource_packs", "behavior_packs": game_dir / "behavior_packs"}
        for index, (folder, payload, kind) in enumerate(candidates):
            target_root = kinds[kind]
            target_root.mkdir(parents=True, exist_ok=True)
            header = payload.get("header", {})
            header = header if isinstance(header, dict) else {}
            label = _manifest_name(payload, archive_path.stem)
            pack_uuid = str(header.get("uuid", ""))
            base_name = safe_slug(label, f"pack-{index + 1}")
            destination = target_root / base_name
            if destination.exists():
                suffix = re.sub(r"[^A-Fa-f0-9]", "", pack_uuid)[:8] or datetime.now().strftime("%H%M%S")
                destination = target_root / f"{base_name}-{suffix}"
                counter = 2
                while destination.exists():
                    destination = target_root / f"{base_name}-{suffix}-{counter}"
                    counter += 1
            shutil.copytree(folder, destination)
            header_version = header.get("version", "?")
            version = ".".join(map(str, header_version)) if isinstance(header_version, list) else str(header_version)
            installed.append(InstalledPack(label, "Resource pack" if kind == "resource_packs" else "Behavior pack", version, destination, pack_uuid))

    return installed


DOWNLOAD_LIMIT_BYTES = 250 * 1024 * 1024


def _validate_https_url(url: str) -> None:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Use a direct HTTPS download URL from a trusted source.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local network addresses are not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise ValueError("Local or private network addresses are not allowed.")
        return
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve download host: {hostname}") from exc
    for item in addresses:
        try:
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise ValueError("Download host resolves to a local or private network address.")
        except ValueError as exc:
            if "not allowed" in str(exc) or "resolves" in str(exc):
                raise


class _HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _validate_https_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download_archive(url: str, output_dir: Path, allowed_extensions: tuple[str, ...]) -> Path:
    _validate_https_url(url)
    opener = build_opener(_HTTPSRedirectHandler())
    request = Request(url.strip(), headers={"User-Agent": "Fresh-MCPE/0.1 (+https://github.com/slurpys181-collab/Fresh-mcpe)"})
    with opener.open(request, timeout=30) as response:
        _validate_https_url(response.geturl())
        headers = response.headers
        content_length = headers.get("Content-Length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError as exc:
                raise ValueError("The server sent an invalid content length.") from exc
            if length > DOWNLOAD_LIMIT_BYTES:
                raise ValueError("Download exceeds the 250 MiB safety limit.")
        disposition = headers.get("Content-Disposition", "")
        match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
        if match:
            filename = unquote(match.group(1).strip().strip('"'))
        else:
            match = re.search(r'filename\s*=\s*"?([^";]+)', disposition, flags=re.IGNORECASE)
            filename = match.group(1).strip() if match else Path(unquote(urlsplit(response.geturl()).path)).name
        filename_lower = filename.lower()
        extension = next((ext for ext in sorted(allowed_extensions, key=len, reverse=True) if filename_lower.endswith(ext)), None)
        if extension is None:
            allowed = ", ".join(allowed_extensions)
            raise ValueError(f"The direct link must serve one of these archive types: {allowed}.")
        archive_path = output_dir / f"download{extension}"
        received = 0
        with archive_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > DOWNLOAD_LIMIT_BYTES:
                    raise ValueError("Download exceeds the 250 MiB safety limit.")
                output.write(chunk)
    if not zipfile.is_zipfile(archive_path) and extension in {".mcpack", ".mcaddon", ".zip"}:
        raise ValueError("The download was not a valid ZIP-based Bedrock pack archive.")
    return archive_path


def download_and_import_addon(url: str, game_dir: Path) -> list[InstalledPack]:
    """Download an HTTPS Bedrock add-on archive and install it via the safe importer."""
    with tempfile.TemporaryDirectory(prefix="fresh-mcpe-download-") as temporary:
        archive = _download_archive(url, Path(temporary), (".mcpack", ".mcaddon", ".zip"))
        return import_addon(archive, game_dir)


def download_and_import_mod(url: str, mods_dir: Path) -> Path:
    """Download an HTTPS native-mod archive; user confirmation is handled in the UI."""
    with tempfile.TemporaryDirectory(prefix="fresh-mcpe-mod-download-") as temporary:
        archive = _download_archive(url, Path(temporary), (".tar.gz", ".tar.xz", ".tgz", ".tar", ".zip"))
        return import_mod_archive(archive, mods_dir)


def safe_remove_pack(pack: InstalledPack, game_dir: Path) -> None:
    allowed_roots = [(game_dir / "resource_packs").resolve(), (game_dir / "behavior_packs").resolve()]
    target = pack.path.resolve()
    if not any(root == target.parent for root in allowed_roots):
        raise ValueError("Refusing to remove a folder outside the managed pack directories.")
    if target.exists():
        shutil.rmtree(target)


def find_compatibility_mod(data_root: Path) -> Path | None:
    """Find the newest installed updates-mod directory for this machine architecture."""
    updates_root = data_root / "mods" / "mcpelauncher-updates"
    machine = os.uname().machine.lower() if hasattr(os, "uname") else "x86_64"
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    elif machine.startswith("armv7"):
        arch = "armeabi-v7a"
    else:
        arch = machine
    candidates = []
    try:
        version_folders = [p for p in updates_root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for version_folder in version_folders:
        candidate = version_folder / arch
        if candidate.is_dir() and any(candidate.iterdir()):
            parts = tuple(int(part) for part in re.findall("[0-9]+", version_folder.name))
            candidates.append((parts, version_folder.name, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def list_mod_folders(mods_dir: Path) -> list[Path]:
    if not mods_dir.is_dir():
        return []
    try:
        return sorted((p for p in mods_dir.iterdir() if p.is_dir()), key=lambda p: p.name.casefold())
    except OSError:
        return []


def import_mod_archive(archive_path: Path, mods_dir: Path) -> Path:
    archive_path = archive_path.expanduser().resolve()
    if archive_path.suffix.lower() not in {".zip", ".tgz", ".gz", ".tar"} and not archive_path.name.lower().endswith((".tar.gz", ".tar.xz")):
        raise ValueError("Choose a ZIP, TAR, TAR.GZ, TGZ, or TAR.XZ mod archive.")
    mods_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fresh-mcpe-mod-") as temp_name:
        staging = Path(temp_name) / "contents"
        if zipfile.is_zipfile(archive_path):
            safe_extract_zip(archive_path, staging)
        else:
            safe_extract_tar(archive_path, staging)
        children = list(staging.iterdir())
        source = children[0] if len(children) == 1 and children[0].is_dir() else staging
        destination_name = safe_slug(source.name if source != staging else archive_path.name.rsplit(".", 1)[0], "custom-mod")
        destination = mods_dir / destination_name
        counter = 2
        while destination.exists():
            destination = mods_dir / f"{destination_name}-{counter}"
            counter += 1
        shutil.copytree(source, destination)
        return destination


def set_mod_enabled(folder: Path, enabled: bool, mods_dir: Path) -> Path:
    mods_root = mods_dir.resolve()
    source = folder.resolve()
    if source.parent != mods_root:
        raise ValueError("Only top-level mod folders can be toggled.")
    if source.name == "mcpelauncher-updates":
        raise ValueError("Fresh MCPE protects the MCPelauncher compatibility/update mod.")
    if enabled and source.name.endswith(".disabled"):
        target = source.with_name(source.name[:-len(".disabled")])
    elif not enabled and not source.name.endswith(".disabled"):
        target = source.with_name(source.name + ".disabled")
    else:
        return source
    if target.exists():
        raise FileExistsError(f"Cannot rename mod: {target.name} already exists.")
    source.rename(target)
    return target


def worlds_fingerprint(worlds_dir: Path) -> tuple[str, int, int]:
    """Fingerprint file metadata without reading world database contents into RAM."""
    digest = hashlib.blake2b(digest_size=16)
    total_bytes = 0
    file_count = 0
    if not worlds_dir.is_dir():
        return digest.hexdigest(), 0, 0
    for directory, dirs, files in os.walk(worlds_dir, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not (Path(directory) / name).is_symlink())
        for filename in sorted(files):
            path = Path(directory) / filename
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
                rel = path.relative_to(worlds_dir).as_posix()
                digest.update(f"{rel}\0{info.st_size}\0{info.st_mtime_ns}\n".encode("utf-8", "surrogateescape"))
                total_bytes += info.st_size
                file_count += 1
            except OSError:
                continue
    return digest.hexdigest(), total_bytes, file_count


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def backup_changed_worlds(
    roots: Iterable[DataRoot],
    backup_base: Path,
    previous_fingerprints: dict[str, str],
    keep: int = 5,
    force: bool = False,
) -> tuple[list[Path], dict[str, str]]:
    """Back up world sets whose contents changed, then prune old snapshots."""
    created: list[Path] = []
    fingerprints = dict(previous_fingerprints)
    backup_base.mkdir(parents=True, exist_ok=True)
    for root in roots:
        worlds = root.game_dir / "minecraftWorlds"
        if not worlds.is_dir() or not any(worlds.iterdir()):
            continue
        signature, total_bytes, file_count = worlds_fingerprint(worlds)
        if not force and fingerprints.get(root.key) == signature:
            continue
        source_backup_dir = backup_base / root.key
        source_backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        snapshot = source_backup_dir / f"{timestamp}-{root.key}"
        suffix = 2
        while snapshot.exists():
            snapshot = source_backup_dir / f"{timestamp}-{root.key}-{suffix}"
            suffix += 1
        snapshot.mkdir(parents=True)
        try:
            shutil.copytree(worlds, snapshot / "minecraftWorlds", symlinks=True)
            meta = {
                "created": datetime.now().astimezone().isoformat(timespec="seconds"),
                "root_key": root.key,
                "root_label": root.label,
                "source_data_root": str(root.path),
                "worlds_fingerprint": signature,
                "file_count": file_count,
                "total_bytes": total_bytes,
            }
            _write_json(snapshot / "meta.json", meta)
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        fingerprints[root.key] = signature
        created.append(snapshot)
        snapshots = sorted(
            (p for p in source_backup_dir.iterdir() if p.is_dir() and p.name[:8].isdigit() and (p / "meta.json").is_file()),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in snapshots[max(1, keep):]:
            shutil.rmtree(old, ignore_errors=True)
    return created, fingerprints


def list_backups(backup_base: Path) -> list[tuple[Path, dict]]:
    result: list[tuple[Path, dict]] = []
    if not backup_base.is_dir():
        return result
    for meta_path in backup_base.glob("*/*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (meta_path.parent / "minecraftWorlds").is_dir() and isinstance(meta, dict):
                result.append((meta_path.parent, meta))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(result, key=lambda pair: str(pair[0]), reverse=True)


def restore_backup(snapshot: Path, backup_base: Path) -> Path:
    """Restore a chosen snapshot after first preserving the live world folder."""
    snapshot = snapshot.resolve()
    base = backup_base.resolve()
    if base not in snapshot.parents or not (snapshot / "meta.json").is_file():
        raise ValueError("Selected folder is not a Fresh MCPE backup.")
    payload = json.loads((snapshot / "meta.json").read_text(encoding="utf-8"))
    source_root = Path(payload["source_data_root"]).expanduser()
    game_dir = source_root / MOJANG_RELATIVE
    worlds = snapshot / "minecraftWorlds"
    if not worlds.is_dir():
        raise ValueError("This backup does not contain a world directory.")

    current = game_dir / "minecraftWorlds"
    game_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if current.is_dir() and any(current.iterdir()):
        current_signature, current_bytes, current_count = worlds_fingerprint(current)
        safety_dir = base / str(payload.get("root_key", "native")) / f"pre-restore-{timestamp}"
        safety_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(current, safety_dir / "minecraftWorlds", symlinks=True)
        _write_json(safety_dir / "meta.json", {
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "root_key": payload.get("root_key", "native"),
            "root_label": "Safety copy before restore",
            "source_data_root": str(source_root),
            "worlds_fingerprint": current_signature,
            "file_count": current_count,
            "total_bytes": current_bytes,
        })

    staged = game_dir / f".fresh-mcpe-restore-{timestamp}"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(worlds, staged, symlinks=True)
    old = game_dir / f".fresh-mcpe-old-{timestamp}"
    try:
        if current.exists():
            current.rename(old)
        staged.rename(current)
    except Exception:
        if not current.exists() and old.exists():
            old.rename(current)
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    return current
