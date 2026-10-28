#!/usr/bin/env python3
"""Fresh MCPE - a lightweight modern desktop shell for MCPelauncher."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from fresh_mcpe_core import (
    FLATPAK_ROOT, NATIVE_ROOT, DataRoot, InstalledPack, InstalledVersion,
    backup_changed_worlds, discover_data_roots, discover_versions, find_root,
    import_addon, import_mod_archive, list_backups, list_installed_packs,
    list_mod_folders, restore_backup, safe_remove_pack, set_mod_enabled,
)


APP_NAME = "Fresh MCPE"
CONFIG_DIR = Path.home() / ".config/fresh-mcpe"
CONFIG_PATH = CONFIG_DIR / "settings.json"
BACKUP_DIR = Path.home() / "Documents" / "Fresh MCPE Backups"
LOG_DIR = Path.home() / ".local/state/fresh-mcpe/logs"
GITHUB_URL = "https://github.com/slurpys181-collab/Fresh-mcpe"
OFFICIAL_GUIDE = "https://minecraft-linux.github.io/"
DEFAULT_SETTINGS = {
    "active_root": "native",
    "auto_backup": True,
    "backup_retention": 5,
    "world_fingerprints": {},
    "selected_root": "native",
    "selected_version": "",
}


def read_settings() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            merged = dict(DEFAULT_SETTINGS)
            merged.update(payload)
            return merged
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def format_bytes(value: int) -> str:
    number = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TB"


def panel(title: str | None = None, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    if title:
        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        layout.addWidget(title_label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return frame, layout


def button(text: str, primary: bool = False, compact: bool = False) -> QPushButton:
    result = QPushButton(text)
    result.setObjectName("primary" if primary else "secondary")
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if compact:
        result.setMinimumHeight(34)
    else:
        result.setMinimumHeight(42)
    return result


class Worker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object]):
        super().__init__()
        self.task = task

    def run(self) -> None:
        try:
            self.succeeded.emit(self.task())
        except Exception as exc:
            self.failed.emit(str(exc))


class FreshMCPE(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = read_settings()
        self.roots = discover_data_roots()
        self.active_root = find_root(self.roots, str(self.settings.get("active_root", "native")))
        self._refreshing = False
        self._worker: Worker | None = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self.setWindowTitle("Fresh MCPE")
        self.setMinimumSize(1060, 680)
        self.resize(1380, 860)
        self.setAcceptDrops(True)
        self._build_ui()
        self.refresh_all()
        self.navigate("Home")

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(222)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 22, 16, 18)
        side.setSpacing(8)

        brand_row = QHBoxLayout()
        mark = QLabel("F")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(43, 43)
        brand = QVBoxLayout()
        brand_name = QLabel("FRESH MCPE")
        brand_name.setObjectName("brandName")
        tagline = QLabel("BEDROCK • LINUX")
        tagline.setObjectName("brandTag")
        brand.addWidget(brand_name)
        brand.addWidget(tagline)
        brand_row.addWidget(mark)
        brand_row.addLayout(brand)
        brand_row.addStretch(1)
        side.addLayout(brand_row)
        side.addSpacing(22)

        nav_items = [
            ("Home", "⌂"),
            ("Add-ons", "⬡"),
            ("Versions", "◷"),
            ("Mods", "✳"),
            ("Worlds & backups", "▣"),
            ("Account & settings", "⚙"),
        ]
        for name, glyph in nav_items:
            nav = QPushButton(f"  {glyph}    {name}")
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setMinimumHeight(43)
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda _checked=False, page=name: self.navigate(page))
            self._nav_buttons[name] = nav
            side.addWidget(nav)
        side.addStretch(1)

        runtime_box, runtime_layout = panel("RUNTIME STATUS")
        self.runtime_status = QLabel("Checking MCPelauncher…")
        self.runtime_status.setObjectName("muted")
        self.runtime_status.setWordWrap(True)
        runtime_layout.addWidget(self.runtime_status)
        self.runtime_button = button("Open launcher", compact=True)
        self.runtime_button.clicked.connect(self.open_native_launcher)
        runtime_layout.addWidget(self.runtime_button)
        side.addWidget(runtime_box)

        foot = QLabel("FRESH MCPE  •  EARLY ACCESS")
        foot.setObjectName("brandTag")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(foot)

        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 21, 28, 22)
        content_layout.setSpacing(16)
        header = QHBoxLayout()
        self.page_title = QLabel("Home")
        self.page_title.setObjectName("pageTitle")
        header.addWidget(self.page_title)
        header.addStretch(1)
        self.header_status = QLabel("●  READY")
        self.header_status.setObjectName("statusPill")
        header.addWidget(self.header_status)
        help_button = button("Help ↗", compact=True)
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OFFICIAL_GUIDE)))
        header.addWidget(help_button)
        content_layout.addLayout(header)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(sidebar)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)

        self._pages = {
            "Home": self._make_home_page(),
            "Add-ons": self._make_addons_page(),
            "Versions": self._make_versions_page(),
            "Mods": self._make_mods_page(),
            "Worlds & backups": self._make_worlds_page(),
            "Account & settings": self._make_settings_page(),
        }
        for page in self._pages.values():
            self.stack.addWidget(page)

    def _scroll_page(self, body: QWidget) -> QScrollArea:
        scroller = QScrollArea()
        scroller.setObjectName("pageScroll")
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidget(body)
        return scroller

    def _make_home_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(28, 25, 28, 24)
        hero_layout.setSpacing(24)
        left = QVBoxLayout()
        overline = QLabel("YOUR BEDROCK. YOUR WAY.")
        overline.setObjectName("greenLabel")
        title = QLabel("Ready to play?")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        description = QLabel("A cleaner home for Minecraft Bedrock on Linux.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        left.addWidget(overline)
        left.addWidget(title)
        left.addWidget(description)
        left.addSpacing(12)
        actions = QHBoxLayout()
        self.home_launch = button("▶   Launch Bedrock", primary=True)
        self.home_launch.clicked.connect(self.launch_selected_version)
        actions.addWidget(self.home_launch)
        manage_btn = button("Manage versions")
        manage_btn.clicked.connect(lambda: self.navigate("Versions"))
        actions.addWidget(manage_btn)
        left.addLayout(actions)
        hero_layout.addLayout(left, 3)

        right_card = QFrame()
        right_card.setObjectName("heroRight")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(18, 18, 18, 18)
        cube = QLabel("▦")
        cube.setObjectName("heroCube")
        cube.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(cube)
        launch_label = QLabel("SELECTED VERSION")
        launch_label.setObjectName("brandTag")
        right.addWidget(launch_label)
        self.home_version_combo = QComboBox()
        self.home_version_combo.setMinimumHeight(40)
        self.home_version_combo.currentIndexChanged.connect(
            lambda _index: self._sync_selected_version(self.home_version_combo, self.versions_combo)
            if hasattr(self, "versions_combo") else None
        )
        right.addWidget(self.home_version_combo)
        self.version_hint = QLabel("Select an installed game version.")
        self.version_hint.setObjectName("muted")
        self.version_hint.setWordWrap(True)
        right.addWidget(self.version_hint)
        hero_layout.addWidget(right_card, 2)
        layout.addWidget(hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        self.metric_values: dict[str, QLabel] = {}
        for index, (key, title_text, symbol) in enumerate([
            ("versions", "INSTALLED VERSIONS", "◷"),
            ("packs", "ADD-ONS INSTALLED", "⬡"),
            ("mods", "MOD FOLDERS", "✳"),
            ("worlds", "WORLDS", "▣"),
        ]):
            frame, frame_layout = panel()
            row = QHBoxLayout()
            icon = QLabel(symbol)
            icon.setObjectName("metricIcon")
            value = QLabel("—")
            value.setObjectName("metricValue")
            self.metric_values[key] = value
            text = QVBoxLayout()
            label = QLabel(title_text)
            label.setObjectName("brandTag")
            text.addWidget(label)
            text.addWidget(value)
            row.addWidget(icon)
            row.addLayout(text)
            row.addStretch(1)
            frame_layout.addLayout(row)
            metrics.addWidget(frame, index // 2, index % 2)
        layout.addLayout(metrics)

        lower = QHBoxLayout()
        versions_panel, versions_layout = panel("YOUR LIBRARY", "Versions already installed on this computer.")
        self.home_versions_list = QListWidget()
        self.home_versions_list.setMinimumHeight(205)
        versions_layout.addWidget(self.home_versions_list)
        versions_buttons = QHBoxLayout()
        versions_refresh = button("Refresh versions", compact=True)
        versions_refresh.clicked.connect(self.refresh_all)
        versions_buttons.addWidget(versions_refresh)
        versions_open = button("Download / sign in ↗", compact=True)
        versions_open.clicked.connect(self.open_native_launcher)
        versions_buttons.addWidget(versions_open)
        versions_layout.addLayout(versions_buttons)
        lower.addWidget(versions_panel, 3)

        quick_panel, quick_layout = panel("QUICK ACTIONS")
        for label_text, destination, detail in [
            ("Import an add-on", "Add-ons", "Install .mcpack / .mcaddon"),
            ("Protect my worlds", "Worlds & backups", "Back up before changing things"),
            ("Manage native mods", "Mods", "Review enabled mod folders"),
        ]:
            item = QPushButton(f"{label_text}\n{detail}    →")
            item.setObjectName("quickAction")
            item.setMinimumHeight(66)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            item.clicked.connect(lambda _checked=False, page=destination: self.navigate(page))
            quick_layout.addWidget(item)
        lower.addWidget(quick_panel, 2)
        layout.addLayout(lower)
        note = QLabel("Fresh MCPE uses your installed MCPelauncher runtime. It does not ship Minecraft game files.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return self._scroll_page(body)

    def _make_addons_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        title, title_layout = panel("Add-on library", "Drag a .mcpack or .mcaddon onto this window, or import it from a file. Fresh MCPE reads the manifest and places each pack in the correct Bedrock folder.")
        action_row = QHBoxLayout()
        import_btn = button("＋  Import add-on", primary=True)
        import_btn.clicked.connect(self.choose_addons)
        action_row.addWidget(import_btn)
        folder_btn = button("Open pack folder")
        folder_btn.clicked.connect(lambda: self.open_path(self.active_root.game_dir / "resource_packs"))
        action_row.addWidget(folder_btn)
        action_row.addStretch(1)
        title_layout.addLayout(action_row)
        layout.addWidget(title)
        self.addons_list = QListWidget()
        self.addons_list.setMinimumHeight(310)
        layout.addWidget(self.addons_list, 1)
        manage = QHBoxLayout()
        refresh_btn = button("Refresh list", compact=True)
        refresh_btn.clicked.connect(self.refresh_all)
        manage.addWidget(refresh_btn)
        remove_btn = button("Remove selected pack", compact=True)
        remove_btn.clicked.connect(self.remove_selected_addon)
        manage.addWidget(remove_btn)
        manage.addStretch(1)
        layout.addLayout(manage)
        hint_frame, hint_layout = panel("HOW PACKS WORK")
        hint = QLabel("Resource packs and behavior packs are installed separately. Importing a pack makes it available to Minecraft; to use it, activate it in the target world's Resource Packs or Behavior Packs settings. Java Edition mods are not Bedrock add-ons.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint_layout.addWidget(hint)
        layout.addWidget(hint_frame)
        return self._scroll_page(body)

    def _make_versions_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        intro, intro_layout = panel("Game versions", "Fresh MCPE detects versions that MCPelauncher has already installed. Use the original launcher to sign in and download versions it supports.")
        self.versions_combo = QComboBox()
        self.versions_combo.setMinimumHeight(42)
        self.versions_combo.currentIndexChanged.connect(
            lambda _index: self._sync_selected_version(self.versions_combo, self.home_version_combo)
            if hasattr(self, "home_version_combo") else None
        )
        intro_layout.addWidget(self.versions_combo)
        row = QHBoxLayout()
        launch_btn = button("▶  Launch selected", primary=True)
        launch_btn.clicked.connect(self.launch_selected_version)
        row.addWidget(launch_btn)
        native_btn = button("Open MCPelauncher / download versions")
        native_btn.clicked.connect(self.open_native_launcher)
        row.addWidget(native_btn)
        refresh_btn = button("Refresh", compact=True)
        refresh_btn.clicked.connect(self.refresh_all)
        row.addWidget(refresh_btn)
        row.addStretch(1)
        intro_layout.addLayout(row)
        layout.addWidget(intro)
        list_panel, list_layout = panel("DETECTED INSTALLATIONS", "Different data roots are kept separate. Changing or removing a version is intentionally not done automatically.")
        self.versions_list = QListWidget()
        self.versions_list.setMinimumHeight(280)
        list_layout.addWidget(self.versions_list)
        layout.addWidget(list_panel, 1)
        perf_panel, perf_layout = panel("PERFORMANCE NOTE")
        perf_note = QLabel("The launcher runs the selected version directly to avoid an extra UI process during gameplay. Actual FPS depends on the game build, drivers, graphics settings, and hardware; set the in-game frame-rate option for a preferred cap.")
        perf_note.setWordWrap(True)
        perf_note.setObjectName("muted")
        perf_layout.addWidget(perf_note)
        layout.addWidget(perf_panel)
        return self._scroll_page(body)

    def _make_mods_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        intro, intro_layout = panel("MCPelauncher mods", "These are launcher-side native mods, not Minecraft Bedrock .mcpack add-ons. Install only archives from sources you trust because native libraries can execute code on your computer.")
        controls = QHBoxLayout()
        import_btn = button("＋  Import mod archive", primary=True)
        import_btn.clicked.connect(self.choose_mod)
        controls.addWidget(import_btn)
        folder_btn = button("Open mods folder")
        folder_btn.clicked.connect(lambda: self.open_path(self.active_root.mods_dir))
        controls.addWidget(folder_btn)
        refresh_btn = button("Refresh", compact=True)
        refresh_btn.clicked.connect(self.refresh_all)
        controls.addWidget(refresh_btn)
        controls.addStretch(1)
        intro_layout.addLayout(controls)
        layout.addWidget(intro)
        mods_panel, mods_layout = panel("INSTALLED MOD FOLDERS")
        self.mods_list = QListWidget()
        self.mods_list.setMinimumHeight(300)
        mods_layout.addWidget(self.mods_list)
        mod_buttons = QHBoxLayout()
        toggle_btn = button("Enable / disable selected", compact=True)
        toggle_btn.clicked.connect(self.toggle_selected_mod)
        mod_buttons.addWidget(toggle_btn)
        mod_buttons.addStretch(1)
        mods_layout.addLayout(mod_buttons)
        layout.addWidget(mods_panel, 1)
        note = QLabel("The MCPelauncher compatibility/update component is protected from being disabled here. Mod support depends on the exact game and launcher versions.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return self._scroll_page(body)

    def _make_worlds_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        intro, intro_layout = panel("World safety", "Fresh MCPE can automatically snapshot changed world folders before you launch a game. Backups are separate copies stored under Documents/Fresh MCPE Backups.")
        buttons = QHBoxLayout()
        backup_btn = button("Create backup now", primary=True)
        backup_btn.clicked.connect(lambda: self.start_backup(manual=True))
        buttons.addWidget(backup_btn)
        open_btn = button("Open world folder")
        open_btn.clicked.connect(lambda: self.open_path(self.active_root.game_dir / "minecraftWorlds"))
        buttons.addWidget(open_btn)
        refresh_btn = button("Refresh", compact=True)
        refresh_btn.clicked.connect(self.refresh_all)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        intro_layout.addLayout(buttons)
        layout.addWidget(intro)
        worlds_panel, worlds_layout = panel("DETECTED WORLDS")
        self.worlds_list = QListWidget()
        self.worlds_list.setMinimumHeight(170)
        worlds_layout.addWidget(self.worlds_list)
        layout.addWidget(worlds_panel)
        backup_panel, backup_layout = panel("SAVED BACKUPS")
        self.backups_list = QListWidget()
        self.backups_list.setMinimumHeight(180)
        backup_layout.addWidget(self.backups_list)
        restore_row = QHBoxLayout()
        restore_btn = button("Restore selected backup")
        restore_btn.clicked.connect(self.restore_selected_backup)
        restore_row.addWidget(restore_btn)
        restore_row.addStretch(1)
        backup_layout.addLayout(restore_row)
        layout.addWidget(backup_panel)
        warn = QLabel("Restoring replaces the selected install's current world folder. Fresh MCPE makes an extra safety copy first. Keep another copy of worlds you cannot afford to lose.")
        warn.setObjectName("warningText")
        warn.setWordWrap(True)
        layout.addWidget(warn)
        return self._scroll_page(body)

    def _make_settings_page(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        runtime_panel, runtime_layout = panel("Runtime & sign-in", "Use MCPelauncher's own account sign-in and version download interface. Fresh MCPE never asks you to type your Microsoft or Google password into this app.")
        login_btn = button("Open official MCPelauncher sign-in", primary=True)
        login_btn.clicked.connect(self.open_native_launcher)
        runtime_layout.addWidget(login_btn)
        docs_btn = button("Official MCPelauncher documentation ↗")
        docs_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OFFICIAL_GUIDE)))
        runtime_layout.addWidget(docs_btn)
        layout.addWidget(runtime_panel)

        setup_panel, setup_layout = panel("Storage & backups")
        root_row = QHBoxLayout()
        root_label = QLabel("Active MCPelauncher data folder")
        root_label.setMinimumWidth(220)
        root_row.addWidget(root_label)
        self.root_combo = QComboBox()
        self.root_combo.setMinimumHeight(38)
        self.root_combo.currentIndexChanged.connect(self.change_active_root)
        root_row.addWidget(self.root_combo, 1)
        setup_layout.addLayout(root_row)
        self.auto_backup_check = QCheckBox("Automatically back up changed worlds before launching")
        self.auto_backup_check.toggled.connect(self.change_auto_backup)
        setup_layout.addWidget(self.auto_backup_check)
        retention_row = QHBoxLayout()
        retention_row.addWidget(QLabel("Keep recent automatic backups"))
        self.retention_combo = QComboBox()
        for count in (3, 5, 10, 20):
            self.retention_combo.addItem(f"{count} snapshots", count)
        self.retention_combo.currentIndexChanged.connect(self.change_retention)
        retention_row.addWidget(self.retention_combo)
        retention_row.addStretch(1)
        setup_layout.addLayout(retention_row)
        path_buttons = QHBoxLayout()
        open_data_btn = button("Open data folder", compact=True)
        open_data_btn.clicked.connect(lambda: self.open_path(self.active_root.path))
        path_buttons.addWidget(open_data_btn)
        open_backups_btn = button("Open backups", compact=True)
        open_backups_btn.clicked.connect(lambda: self.open_path(BACKUP_DIR))
        path_buttons.addWidget(open_backups_btn)
        path_buttons.addStretch(1)
        setup_layout.addLayout(path_buttons)
        layout.addWidget(setup_panel)

        about, about_layout = panel("About Fresh MCPE")
        about_text = QLabel("Fresh MCPE is an independent interface for the existing MCPelauncher runtime. It does not include Minecraft, bypass ownership checks, modify authentication tokens, or promise compatibility with every Bedrock release. A launcher UI can manage files, but it cannot repair an incompatible native game library by itself.")
        about_text.setObjectName("muted")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        repo_btn = button("Fresh MCPE on GitHub ↗")
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        about_layout.addWidget(repo_btn)
        layout.addWidget(about)
        return self._scroll_page(body)

    def navigate(self, name: str) -> None:
        if name not in self._pages:
            return
        self.page_title.setText(name)
        self.stack.setCurrentWidget(self._pages[name])
        for nav_name, nav in self._nav_buttons.items():
            nav.setChecked(nav_name == name)
        self.refresh_runtime_status()

    def _sync_selected_version(self, source: QComboBox, target: QComboBox | None) -> None:
        if self._refreshing:
            return
        selected = source.currentData()
        if selected is not None:
            self.settings["selected_root"] = selected.root_key
            self.settings["selected_version"] = selected.name
            save_settings(self.settings)
            if target is not None:
                for index in range(target.count()):
                    candidate = target.itemData(index)
                    if candidate and candidate.name == selected.name and candidate.root_key == selected.root_key:
                        self._refreshing = True
                        target.setCurrentIndex(index)
                        self._refreshing = False
                        break
            self.version_hint.setText(f"{selected.name} · {selected.root_label}")
        self._update_launch_controls()

    def _update_launch_controls(self) -> None:
        available = self.home_version_combo.currentData() is not None
        self.home_launch.setEnabled(available)
        self.version_hint.setText("No installed versions detected. Open MCPelauncher to sign in or install a supported version." if not available else self.version_hint.text())

    def refresh_runtime_status(self) -> None:
        native_client = shutil.which("mcpelauncher-client")
        native_ui = shutil.which("mcpelauncher-ui-qt")
        flatpak = shutil.which("flatpak")
        installed = bool(native_client or native_ui)
        if flatpak:
            try:
                check = subprocess.run(
                    [flatpak, "info", "io.mrarm.mcpelauncher"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False,
                )
                installed = installed or check.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if native_client:
            self.runtime_status.setText("●  Native MCPelauncher found")
            self.header_status.setText("●  RUNTIME FOUND")
        elif installed:
            self.runtime_status.setText("●  MCPelauncher UI found; direct client not detected")
            self.header_status.setText("●  PARTIAL")
        else:
            self.runtime_status.setText("○  MCPelauncher not detected")
            self.header_status.setText("○  SETUP NEEDED")

    def refresh_all(self) -> None:
        self.roots = discover_data_roots()
        self.active_root = find_root(self.roots, str(self.settings.get("active_root", "native")))
        versions = discover_versions(self.roots)
        self._refreshing = True
        for combo in (self.home_version_combo, self.versions_combo):
            combo.blockSignals(True)
            combo.clear()
            for version in versions:
                combo.addItem(f"{version.name}   ·   {version.root_label}", version)
            selected_index = -1
            for index, version in enumerate(versions):
                if version.root_key == self.settings.get("selected_root") and version.name == self.settings.get("selected_version"):
                    selected_index = index
                    break
            if selected_index < 0:
                for index, version in enumerate(versions):
                    if version.root_key == self.active_root.key:
                        selected_index = index
                        break
            if selected_index < 0 and versions:
                selected_index = 0
            combo.setCurrentIndex(selected_index)
            combo.blockSignals(False)
        # Keep persisted active root options visible even when a data folder is empty.
        root_options = [
            DataRoot("native", "Linux install", NATIVE_ROOT, "native"),
            DataRoot("flatpak", "Flatpak install", FLATPAK_ROOT, "flatpak"),
        ]
        self.root_combo.blockSignals(True)
        self.root_combo.clear()
        for root in root_options:
            self.root_combo.addItem(f"{root.label} — {root.path}", root.key)
        root_idx = self.root_combo.findData(self.active_root.key)
        self.root_combo.setCurrentIndex(max(0, root_idx))
        self.root_combo.blockSignals(False)
        self.auto_backup_check.blockSignals(True)
        self.auto_backup_check.setChecked(bool(self.settings.get("auto_backup", True)))
        self.auto_backup_check.blockSignals(False)
        self.retention_combo.blockSignals(True)
        retention_idx = self.retention_combo.findData(int(self.settings.get("backup_retention", 5)))
        self.retention_combo.setCurrentIndex(max(0, retention_idx))
        self.retention_combo.blockSignals(False)
        self._refreshing = False

        self.home_versions_list.clear()
        self.versions_list.clear()
        for version in versions:
            text = f"{version.name}    ·    {version.root_label}\n{version.path}"
            self.home_versions_list.addItem(text)
            self.versions_list.addItem(text)
        if not versions:
            self.home_versions_list.addItem("No versions found. Use MCPelauncher to sign in and install a supported Bedrock version.")
            self.versions_list.addItem("No installed versions found.")
        self._refresh_addons()
        self._refresh_mods()
        self._refresh_worlds()
        self._refresh_backups()
        packs = list_installed_packs(self.active_root.game_dir)
        self.metric_values["versions"].setText(str(len(versions)))
        self.metric_values["packs"].setText(str(len(packs)))
        self.metric_values["mods"].setText(str(len(list_mod_folders(self.active_root.mods_dir))))
        self.metric_values["worlds"].setText(str(len(self._get_world_rows())))
        selected = self.home_version_combo.currentData()
        self.version_hint.setText("No installed versions detected. Open MCPelauncher to sign in or install a supported version." if selected is None else f"{selected.name} · {selected.root_label}")
        self._update_launch_controls()
        self.refresh_runtime_status()

    def _refresh_addons(self) -> None:
        self.addons_list.clear()
        packs = list_installed_packs(self.active_root.game_dir)
        for pack in packs:
            item = QListWidgetItem(f"{'◇' if pack.kind == 'Resource pack' else '⬡'}  {pack.name}   ·   v{pack.version}\n{pack.kind}  •  {pack.path}")
            item.setData(Qt.ItemDataRole.UserRole, pack)
            self.addons_list.addItem(item)
        if not packs:
            self.addons_list.addItem("No add-ons found for this data folder yet. Import a .mcpack or .mcaddon above.")

    def _refresh_mods(self) -> None:
        self.mods_list.clear()
        folders = list_mod_folders(self.active_root.mods_dir)
        for folder in folders:
            disabled = folder.name.endswith(".disabled")
            protected = folder.name == "mcpelauncher-updates"
            status = "PROTECTED" if protected else ("DISABLED" if disabled else "ENABLED")
            item = QListWidgetItem(f"{'●' if not disabled else '○'}  {folder.name}\n{status}  •  {folder}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.mods_list.addItem(item)
        if not folders:
            self.mods_list.addItem("No mod folders found.")

    def _get_world_rows(self) -> list[tuple[str, Path, str]]:
        worlds: list[tuple[str, Path, str]] = []
        for root in self.roots:
            folder = root.game_dir / "minecraftWorlds"
            if not folder.is_dir():
                continue
            try:
                children = [p for p in folder.iterdir() if p.is_dir()]
            except OSError:
                continue
            for child in children:
                label = child.name
                level_name = child / "levelname.txt"
                try:
                    if level_name.is_file():
                        label = level_name.read_text(encoding="utf-8", errors="replace").strip() or label
                except OSError:
                    pass
                worlds.append((label, child, root.label))
        return worlds

    def _refresh_worlds(self) -> None:
        self.worlds_list.clear()
        worlds = self._get_world_rows()
        for name, path, root_label in worlds:
            item = QListWidgetItem(f"▣  {name}\n{root_label}  •  {path}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.worlds_list.addItem(item)
        if not worlds:
            self.worlds_list.addItem("No world folders detected yet.")

    def _refresh_backups(self) -> None:
        self.backups_list.clear()
        for snapshot, meta in list_backups(BACKUP_DIR):
            created = meta.get("created", snapshot.name)
            count = meta.get("file_count", "?")
            size = format_bytes(int(meta.get("total_bytes", 0) or 0))
            row = QListWidgetItem(f"◷  {meta.get('root_label', meta.get('root_key', 'Install'))}  ·  {created}\n{count} files  •  {size}  •  {snapshot}")
            row.setData(Qt.ItemDataRole.UserRole, snapshot)
            self.backups_list.addItem(row)
        if self.backups_list.count() == 0:
            self.backups_list.addItem("No backups yet. Create one now or enable automatic backups in Settings.")

    def _start_task(self, task: Callable[[], object], success: Callable[[object], None], failure: Callable[[str], None] | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, APP_NAME, "Another file operation is already running. Please let it finish first.")
            return
        worker = Worker(task)
        self._worker = worker
        worker.succeeded.connect(success)
        worker.failed.connect(failure or self._show_error)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
        self.header_status.setText("◌  WORKING")
        worker.start()

    def _show_error(self, message: str) -> None:
        self.header_status.setText("●  READY")
        QMessageBox.critical(self, f"{APP_NAME} — operation failed", message)
        self.refresh_all()

    def _finish_task(self) -> None:
        self.header_status.setText("●  READY")
        self.refresh_all()

    def start_backup(self, manual: bool = False, next_step: Callable[[], None] | None = None) -> None:
        self.header_status.setText("◌  BACKING UP")
        roots = list(self.roots)
        previous = dict(self.settings.get("world_fingerprints", {}))
        retention = int(self.settings.get("backup_retention", 5))

        def success(result: object) -> None:
            created, updated = result
            self.settings["world_fingerprints"] = updated
            save_settings(self.settings)
            self._finish_task()
            if manual:
                if created:
                    QMessageBox.information(self, APP_NAME, f"Created {len(created)} backup snapshot(s).\n\nSaved in:\n{BACKUP_DIR}")
                else:
                    QMessageBox.information(self, APP_NAME, "No changed world data needed backing up. Existing world folders are unchanged since the last automatic snapshot.")
            if next_step:
                next_step()

        def failure(message: str) -> None:
            self.header_status.setText("●  READY")
            if next_step:
                answer = QMessageBox.question(
                    self, "World backup failed",
                    f"Fresh MCPE could not create a world backup:\n\n{message}\n\nLaunch the game anyway? It is safer to cancel if these worlds are important.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    next_step()
            else:
                QMessageBox.critical(self, "Backup failed", message)

        self._start_task(lambda: backup_changed_worlds(roots, BACKUP_DIR, previous, retention), success, failure)

    def launch_selected_version(self) -> None:
        version = self.home_version_combo.currentData()
        if version is None:
            QMessageBox.information(self, APP_NAME, "No installed version was found. Open MCPelauncher to sign in and install a version first.")
            return
        if version.name == "1.26.60.4":
            answer = QMessageBox.warning(
                self, "Known compatibility risk",
                "Your earlier log for Bedrock 1.26.60.4 showed libpairipcore failing with __gnu_strerror_r. Fresh MCPE cannot repair that native binary mismatch.\n\nLaunch it anyway, or open MCPelauncher to look for a compatible version?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Open,
            )
            if answer == QMessageBox.StandardButton.Open:
                self.open_native_launcher()
                return
            if answer != QMessageBox.StandardButton.Yes:
                return
        if bool(self.settings.get("auto_backup", True)):
            self.start_backup(manual=False, next_step=lambda: self._launch_version(version))
        else:
            self._launch_version(version)

    def _launch_version(self, version: InstalledVersion) -> None:
        client = shutil.which("mcpelauncher-client")
        flatpak = shutil.which("flatpak")
        if version.root_key == "flatpak":
            if not flatpak:
                QMessageBox.warning(self, APP_NAME, "Flatpak command was not found. This installation cannot be launched.")
                return
            command = [flatpak, "run", "--command=mcpelauncher-client", "io.mrarm.mcpelauncher", "-dg", str(version.path)]
        elif client:
            command = [client, "-dg", str(version.path)]
        else:
            QMessageBox.warning(
                self, APP_NAME,
                "The direct MCPelauncher client was not found on PATH. Try installing the native launcher packages, or open the original launcher UI.",
            )
            return
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIR / f"launch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
            log_handle = log_path.open("w", encoding="utf-8")
            subprocess.Popen(
                command,
                cwd=str(version.path),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
            # Popen duplicates the file descriptor in the child.
            log_handle.close()
            self.header_status.setText("●  GAME STARTED")
            QMessageBox.information(
                self, APP_NAME,
                f"Launch command started for Bedrock {version.name}.\n\nFresh MCPE will save the launcher output here:\n{log_path}\n\nIf the game crashes, attach that log when reporting the problem.",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Could not launch Minecraft", str(exc))
        self.refresh_runtime_status()

    def open_native_launcher(self) -> None:
        ui = shutil.which("mcpelauncher-ui-qt")
        flatpak = shutil.which("flatpak")
        try:
            if ui:
                subprocess.Popen([ui], start_new_session=True)
                return
            if flatpak:
                check = subprocess.run(
                    [flatpak, "info", "io.mrarm.mcpelauncher"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False,
                )
                if check.returncode == 0:
                    subprocess.Popen([flatpak, "run", "io.mrarm.mcpelauncher"], start_new_session=True)
                    return
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not open MCPelauncher:\n{exc}")
            return
        QMessageBox.warning(
            self, APP_NAME,
            "MCPelauncher UI was not found.\n\nUse the official installation guide to install the runtime and UI:\nhttps://minecraft-linux.github.io/",
        )

    def choose_addons(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Bedrock add-ons", str(Path.home() / "Downloads"),
            "Bedrock add-ons (*.mcpack *.mcaddon *.zip);;All files (*)",
        )
        if not paths:
            return
        self._import_addon_paths([Path(path) for path in paths])

    def _import_addon_paths(self, paths: list[Path]) -> None:
        self.header_status.setText("◌  IMPORTING")
        game_dir = self.active_root.game_dir

        def task() -> list[InstalledPack]:
            result: list[InstalledPack] = []
            for path in paths:
                result.extend(import_addon(path, game_dir))
            return result

        def success(result: object) -> None:
            packs = result
            self._finish_task()
            names = "\n".join(f"• {pack.name} — {pack.kind}" for pack in packs)
            QMessageBox.information(self, "Add-on import complete", f"Installed {len(packs)} pack(s):\n\n{names}\n\nOpen Minecraft and activate the packs in the world's settings.")
        self._start_task(task, success)

    def remove_selected_addon(self) -> None:
        item = self.addons_list.currentItem()
        pack = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(pack, InstalledPack):
            QMessageBox.information(self, APP_NAME, "Select an installed pack first.")
            return
        answer = QMessageBox.question(
            self, "Remove add-on",
            f"Remove {pack.name} from this install?\n\nThis deletes its installed pack files but does not edit worlds that already reference it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def success(_result: object) -> None:
            self._finish_task()
            QMessageBox.information(self, APP_NAME, f"Removed {pack.name}.")
        self._start_task(lambda: safe_remove_pack(pack, self.active_root.game_dir), success)

    def choose_mod(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import launcher mod archive", str(Path.home() / "Downloads"),
            "Mod archives (*.zip *.tar *.tar.gz *.tgz *.tar.xz);;All files (*)",
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self, "Trust the mod source",
            "Launcher mods may contain native code that runs on your computer. Only install an archive from a source you trust.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_task(
            lambda: import_mod_archive(Path(path), self.active_root.mods_dir),
            lambda target: (self._finish_task(), QMessageBox.information(self, APP_NAME, f"Imported mod archive to:\n{target}")),
        )

    def toggle_selected_mod(self) -> None:
        item = self.mods_list.currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(path, Path):
            QMessageBox.information(self, APP_NAME, "Select a custom mod folder first.")
            return
        enabled = path.name.endswith(".disabled")
        if path.name == "mcpelauncher-updates":
            QMessageBox.information(self, APP_NAME, "The MCPelauncher compatibility/update mod is protected.")
            return
        answer = QMessageBox.question(
            self, "Change mod state",
            f"{'Enable' if enabled else 'Disable'} {path.name}?\n\nThis renames the mod folder. It will not make an incompatible mod compatible with your game version.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_task(
            lambda: set_mod_enabled(path, enabled, self.active_root.mods_dir),
            lambda _result: self._finish_task(),
        )

    def change_active_root(self, index: int) -> None:
        if self._refreshing or index < 0:
            return
        key = str(self.root_combo.itemData(index))
        self.settings["active_root"] = key
        self.active_root = find_root(self.roots, key)
        save_settings(self.settings)
        self.refresh_all()

    def change_auto_backup(self, checked: bool) -> None:
        self.settings["auto_backup"] = bool(checked)
        save_settings(self.settings)

    def change_retention(self, index: int) -> None:
        if self._refreshing or index < 0:
            return
        self.settings["backup_retention"] = int(self.retention_combo.itemData(index))
        save_settings(self.settings)

    def restore_selected_backup(self) -> None:
        item = self.backups_list.currentItem()
        snapshot = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(snapshot, Path):
            QMessageBox.information(self, APP_NAME, "Select a saved backup first.")
            return
        answer = QMessageBox.warning(
            self, "Restore world backup",
            f"Restore this backup?\n\n{snapshot}\n\nThe target install's current worlds will be copied to a safety snapshot before the restore. Close Minecraft before continuing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_task(
            lambda: restore_backup(snapshot, BACKUP_DIR),
            lambda path: (self._finish_task(), QMessageBox.information(self, APP_NAME, f"Restored worlds to:\n{path}")),
        )

    def open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not open folder:\n{exc}")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            suffixes = {Path(url.toLocalFile()).suffix.lower() for url in event.mimeData().urls() if url.isLocalFile()}
            if suffixes.intersection({".mcpack", ".mcaddon", ".zip"}):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        paths = [
            Path(url.toLocalFile()) for url in event.mimeData().urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".mcpack", ".mcaddon", ".zip"}
        ]
        if paths:
            self.navigate("Add-ons")
            self._import_addon_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


def app_stylesheet() -> str:
    return """
    * { font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif; font-size: 13px; }
    QWidget { background: #101318; color: #ecf0f6; }
    QWidget#content { background: #101318; }
    QFrame#sidebar { background: #0b0d11; border-right: 1px solid #262b34; }
    QFrame#panel { background: #171b22; border: 1px solid #272d38; border-radius: 15px; }
    QFrame#hero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #222b2c,stop:0.55 #1a2328,stop:1 #17202b); border: 1px solid #344342; border-radius: 20px; }
    QFrame#heroRight { background: rgba(8,12,16,0.45); border: 1px solid #384348; border-radius: 15px; }
    QLabel { background: transparent; }
    QLabel#brandMark { background: #8fe36a; color: #10170d; border-radius: 12px; font-size: 27px; font-weight: 900; }
    QLabel#brandName { color: #f0f4f8; font-weight: 900; font-size: 14px; letter-spacing: 1px; }
    QLabel#brandTag { color: #828c9a; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
    QLabel#pageTitle { color: #f1f4f9; font-size: 22px; font-weight: 800; }
    QLabel#muted { color: #9aa4b2; }
    QLabel#greenLabel { color: #9be87c; font-size: 11px; font-weight: 900; letter-spacing: 2px; }
    QLabel#heroTitle { color: #f7fafc; font-size: 32px; font-weight: 900; }
    QLabel#heroCube { color: #99ef7b; font-size: 55px; font-weight: 900; padding: 0px; }
    QLabel#panelTitle { font-size: 15px; font-weight: 800; color: #edf1f6; }
    QLabel#metricIcon { color: #9ae978; font-size: 26px; font-weight: bold; min-width: 38px; }
    QLabel#metricValue { color: #f7f9fc; font-size: 25px; font-weight: 900; }
    QLabel#statusPill { color: #a0e985; background: #1a2a20; border: 1px solid #2c4b36; border-radius: 11px; padding: 7px 11px; font-size: 10px; font-weight: 900; }
    QLabel#warningText { color: #eacb8c; background: #282318; border: 1px solid #4b3b24; border-radius: 10px; padding: 12px; }
    QPushButton { border-radius: 10px; padding: 0px 14px; font-weight: 700; }
    QPushButton#primary { background: #9be879; color: #14200f; border: 1px solid #b2f49a; }
    QPushButton#primary:hover { background: #b0f393; }
    QPushButton#primary:disabled { background: #333b37; color: #899188; border: 1px solid #3b4540; }
    QPushButton#secondary { background: #242a33; color: #e6ebf2; border: 1px solid #353d49; }
    QPushButton#secondary:hover { background: #303946; border-color: #525e6d; }
    QPushButton#navButton { text-align: left; color: #9ba5b3; background: transparent; border: 1px solid transparent; padding-left: 10px; }
    QPushButton#navButton:hover { background: #171c23; color: #eef2f7; }
    QPushButton#navButton:checked { background: #202c24; color: #a1ed81; border: 1px solid #304b35; }
    QPushButton#quickAction { text-align: left; color: #e5eaf1; background: #1d222b; border: 1px solid #303743; padding: 10px 13px; }
    QPushButton#quickAction:hover { border-color: #658754; background: #232b27; }
    QComboBox { color: #edf1f6; background: #20252e; border: 1px solid #343c48; border-radius: 9px; padding: 7px 10px; }
    QComboBox QAbstractItemView { background: #20252e; color: #edf1f6; selection-background-color: #344d37; border: 1px solid #343c48; }
    QListWidget { background: #12161c; border: 1px solid #2c323d; border-radius: 11px; padding: 7px; outline: none; }
    QListWidget::item { background: #1a1f27; border: 1px solid #29303a; border-radius: 8px; padding: 12px; margin: 4px 2px; color: #e1e7ef; }
    QListWidget::item:selected { background: #25332a; border: 1px solid #628451; color: #f7fff4; }
    QListWidget::item:hover { background: #232a33; }
    QCheckBox { color: #e0e6ef; spacing: 10px; }
    QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #525c68; background: #1d222a; }
    QCheckBox::indicator:checked { background: #9be879; border-color: #9be879; }
    QScrollArea { background: #101318; border: 0; }
    QScrollBar:vertical { width: 9px; background: #101318; margin: 0; }
    QScrollBar::handle:vertical { background: #353e4a; border-radius: 4px; min-height: 30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Fresh MCPE")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    window = FreshMCPE()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
