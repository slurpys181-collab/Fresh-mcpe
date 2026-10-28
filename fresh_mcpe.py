#!/usr/bin/env python3
"""Fresh MCPE: standalone launcher shell with a source-built private runtime."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QDialog, QDialogButtonBox,
    QFormLayout, QStackedWidget, QVBoxLayout, QWidget,
)

from fresh_mcpe_core import (
    FRESH_HOME, NATIVE_ROOT, LEGACY_NATIVE_ROOT, FLATPAK_ROOT, RUNTIME_ROOT, DataRoot, InstalledPack, InstalledVersion,
    backup_changed_worlds, discover_data_roots, discover_versions, download_and_import_addon,
    download_and_import_mod, find_compatibility_mod, find_root, import_addon,
    import_mod_archive, list_backups, list_installed_packs, list_mod_folders,
    migrate_legacy_game_data, restore_backup, safe_remove_pack, set_mod_enabled,
)

APP_NAME = "Fresh MCPE"
CONFIG_DIR = Path.home() / ".config/fresh-mcpe"
CONFIG_PATH = CONFIG_DIR / "settings.json"
BACKUP_DIR = Path.home() / "Documents" / "Fresh MCPE Backups"
LOG_DIR = Path.home() / ".local/state/fresh-mcpe/logs"
GITHUB_URL = "https://github.com/slurpys181-collab/Fresh-mcpe"
RUNTIME_SOURCE_URL = "https://github.com/komixkat/mcpe"
DEFAULT_SETTINGS = {
    "auto_backup": True,
    "backup_retention": 5,
    "world_fingerprints": {},
    "selected_version": "",
    "selected_profile": "metacopy",
    "performance_mode": True,
}


def read_settings() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    # Isolate the runtime's standard "mcpelauncher" data directory under Fresh MCPE.
    env["XDG_DATA_HOME"] = str(FRESH_HOME)
    env["XDG_CONFIG_HOME"] = str(Path.home() / ".config" / "fresh-mcpe" / "runtime")
    env["PATH"] = str(RUNTIME_ROOT / "bin") + os.pathsep + env.get("PATH", "")
    env.setdefault("SDL_VIDEODRIVER", "x11")
    env.setdefault("EGL_PLATFORM", "x11")
    return env


def runtime_executable(name: str) -> Path | None:
    # Never fall back to a system executable installed by a .deb or Flatpak.
    for candidate in (RUNTIME_ROOT / "bin" / name, RUNTIME_ROOT / "usr" / "bin" / name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def fmt_bytes(number: int) -> str:
    value = float(max(0, number))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def make_button(text: str, kind: str = "secondary", height: int = 38) -> QPushButton:
    item = QPushButton(text)
    item.setObjectName(kind)
    item.setMinimumHeight(height)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    return item


def make_panel(title: str | None = None, subtitle: str | None = None, object_name: str = "panel") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(15, 13, 15, 13)
    layout.setSpacing(9)
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("panelTitle")
        layout.addWidget(lbl)
    if subtitle:
        lbl = QLabel(subtitle)
        lbl.setObjectName("muted")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
    return frame, layout


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
        self.root = find_root(self.roots, "native")
        self.versions: list[InstalledVersion] = []
        self.worker: Worker | None = None
        self.pages: dict[str, QWidget] = {}
        self.nav: dict[str, QPushButton] = {}
        self.refreshing = False
        self.setWindowTitle("Fresh MCPE")
        self.resize(1430, 890)
        self.setMinimumSize(1120, 700)
        self.setAcceptDrops(True)
        self.build_shell()
        self.build_pages()
        self.refresh_all()
        self.navigate("Home")

    def build_shell(self) -> None:
        central = QWidget()
        central.setObjectName("shell")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.rail = QFrame()
        self.rail.setObjectName("rail")
        self.rail.setFixedWidth(70)
        side = QVBoxLayout(self.rail)
        side.setContentsMargins(8, 16, 8, 14)
        side.setSpacing(7)
        logo = QLabel("F")
        logo.setObjectName("logo")
        logo.setFixedSize(48, 48)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)
        side.addSpacing(14)
        for page, glyph, tooltip in [
            ("Home", "⌂", "Home and Play"),
            ("Instances", "▦", "Installed versions"),
            ("Add-ons", "⬡", "Bedrock add-ons"),
            ("Skins", "♧", "Skin packs and dressing room"),
            ("Mods", "✳", "Launcher mods"),
            ("Discover", "◎", "Discover content"),
            ("Worlds & backups", "▣", "Worlds and backups"),
        ]:
            button = QPushButton(glyph)
            button.setObjectName("railButton")
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setFixedSize(50, 45)
            button.clicked.connect(lambda _checked=False, key=page: self.navigate(key))
            self.nav[page] = button
            side.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        add = QPushButton("+")
        add.setObjectName("addButton")
        add.setToolTip("Add version / sign in")
        add.setFixedSize(50, 45)
        add.clicked.connect(self.open_runtime_ui)
        side.addWidget(add, alignment=Qt.AlignmentFlag.AlignHCenter)
        side.addStretch(1)
        avatar = QLabel("MC")
        avatar.setObjectName("avatar")
        avatar.setFixedSize(43, 43)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignHCenter)
        for glyph, tip, callback in [
            ("♢", "Notifications", lambda: self.notice("Notifications", "Launcher notifications will appear here as they are implemented.")),
            ("◉", "Community", lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL))),
            ("ϟ", "Performance options", lambda: self.navigate("Settings")),
            ("⚙", "Settings", lambda: self.navigate("Settings")),
        ]:
            button = QPushButton(glyph)
            button.setObjectName("railButton")
            button.setToolTip(tip)
            button.setFixedSize(50, 40)
            button.clicked.connect(callback)
            side.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(22, 12, 18, 12)
        top.setSpacing(12)
        brand = QLabel("FRESH MCPE")
        brand.setObjectName("topBrand")
        version = QLabel("BEDROCK • LINUX")
        version.setObjectName("topTag")
        top.addWidget(brand)
        top.addWidget(version)
        top.addStretch(1)
        self.runtime_badge = QLabel("CHECKING RUNTIME")
        self.runtime_badge.setObjectName("runtimeBadge")
        top.addWidget(self.runtime_badge)
        patreon = make_button("♡  Support the project", "support", 34)
        patreon.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        top.addWidget(patreon)
        workspace_layout.addWidget(topbar)

        lower = QHBoxLayout()
        lower.setContentsMargins(20, 17, 16, 17)
        lower.setSpacing(16)
        self.stack = QStackedWidget()
        self.stack.setObjectName("centerStack")
        lower.addWidget(self.stack, 1)

        self.news_rail = QFrame()
        self.news_rail.setObjectName("newsRail")
        self.news_rail.setFixedWidth(252)
        news = QVBoxLayout(self.news_rail)
        news.setContentsMargins(12, 7, 1, 4)
        news.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("What's new")
        title.setObjectName("newsTitle")
        head.addWidget(title)
        head.addStretch(1)
        refresh = QPushButton("↻")
        refresh.setObjectName("smallIcon")
        refresh.setToolTip("Refresh starter news")
        refresh.clicked.connect(self.refresh_news)
        head.addWidget(refresh)
        news.addLayout(head)
        intro = QLabel("Tools, add-ons and community updates.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        news.addWidget(intro)
        self.news_cards = QVBoxLayout()
        self.news_cards.setSpacing(9)
        news.addLayout(self.news_cards)
        news.addStretch(1)
        social_label = QLabel("FRESH MCPE • COMMUNITY")
        social_label.setObjectName("socialLabel")
        social_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        news.addWidget(social_label)
        socials = QHBoxLayout()
        for glyph, url in [
            ("F", GITHUB_URL), ("◉", GITHUB_URL), ("𝕏", "https://x.com/"),
            ("▶", "https://youtube.com/"), ("◎", "https://reddit.com/"),
        ]:
            b = QPushButton(glyph)
            b.setObjectName("socialButton")
            b.setFixedSize(33, 33)
            b.clicked.connect(lambda _checked=False, dest=url: QDesktopServices.openUrl(QUrl(dest)))
            socials.addWidget(b)
        news.addLayout(socials)
        lower.addWidget(self.news_rail)
        workspace_layout.addLayout(lower, 1)
        outer.addWidget(self.rail)
        outer.addWidget(workspace, 1)
        self.setCentralWidget(central)
        self.build_news()

    def build_pages(self) -> None:
        self.pages = {
            "Home": self.build_home(),
            "Instances": self.build_instances(),
            "Add-ons": self.build_addons(),
            "Skins": self.build_skins(),
            "Mods": self.build_mods(),
            "Discover": self.build_discover(),
            "Worlds & backups": self.build_worlds(),
            "Settings": self.build_settings(),
        }
        for widget in self.pages.values():
            self.stack.addWidget(widget)

    def scroll_page(self, body: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        return scroll

    def build_home(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        root.setSpacing(16)
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 21, 18, 19)
        hero_layout.setSpacing(16)
        left = QVBoxLayout()
        label = QLabel("YOUR WORLD IS WAITING")
        label.setObjectName("eyebrow")
        left.addWidget(label)
        nickname = str(self.settings.get("selected_profile", "metacopy")).strip() or "player"
        title = QLabel(f"Time to torch up the base, {nickname}")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        left.addWidget(title)
        subtitle = QLabel("The mobs won't fight themselves")
        subtitle.setObjectName("muted")
        left.addWidget(subtitle)
        left.addStretch(1)
        playrow = QHBoxLayout()
        self.play_button = make_button("▶   Play Bedrock", "primary", 44)
        self.play_button.clicked.connect(self.launch_selected_version)
        playrow.addWidget(self.play_button)
        self.version_combo = QComboBox()
        self.version_combo.setMinimumHeight(43)
        self.version_combo.setMinimumWidth(165)
        self.version_combo.currentIndexChanged.connect(self.on_version_changed)
        playrow.addWidget(self.version_combo)
        addver = make_button("＋", "soft", 43)
        addver.setToolTip("Sign in or install a version")
        addver.clicked.connect(self.open_runtime_ui)
        playrow.addWidget(addver)
        left.addLayout(playrow)
        hero_layout.addLayout(left, 3)
        art = QFrame()
        art.setObjectName("heroGlass")
        art_layout = QVBoxLayout(art)
        art_layout.setContentsMargins(12, 10, 12, 10)
        art_layout.addWidget(QLabel("FRESH MCPE"))
        big = QLabel("▦")
        big.setObjectName("heroArt")
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art_layout.addWidget(big, 1)
        self.hero_status = QLabel("Build the private runtime to get started.")
        self.hero_status.setObjectName("mutedSmall")
        self.hero_status.setWordWrap(True)
        art_layout.addWidget(self.hero_status)
        hero_layout.addWidget(art, 1)
        root.addWidget(hero)

        quick_head = QHBoxLayout()
        quick_title = QLabel("Quick Play")
        quick_title.setObjectName("sectionTitle")
        quick_head.addWidget(quick_title)
        quick_head.addStretch(1)
        qhelp = QLabel("Recently installed versions")
        qhelp.setObjectName("mutedSmall")
        quick_head.addWidget(qhelp)
        root.addLayout(quick_head)
        self.quick_row = QHBoxLayout()
        self.quick_row.setSpacing(9)
        root.addLayout(self.quick_row)

        featured_head = QHBoxLayout()
        feature_title = QLabel("Explore Bedrock")
        feature_title.setObjectName("sectionTitle")
        featured_head.addWidget(feature_title)
        featured_head.addStretch(1)
        browse = QPushButton("Browse add-ons  →")
        browse.setObjectName("textButton")
        browse.clicked.connect(lambda: self.navigate("Discover"))
        featured_head.addWidget(browse)
        root.addLayout(featured_head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(11)
        grid.setVerticalSpacing(11)
        for column, (tag, name, summary, glyph, base) in enumerate([
            ("SURVIVAL", "Survival toolkit", "Make your next world feel like yours.", "◈", "#302344"),
            ("VISUALS", "Better visuals", "Textures, resource packs and clean UI.", "▧", "#292543"),
            ("GAMEPLAY", "Gameplay add-ons", "Behavior packs for new ways to play.", "✳", "#342644"),
        ]):
            card = QFrame()
            card.setObjectName("featureCard")
            card.setStyleSheet(f"QFrame#featureCard {{ background: {base}; border: 1px solid #514071; border-radius: 13px; }}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(13, 12, 13, 12)
            cv.setSpacing(6)
            picture = QLabel(glyph)
            picture.setObjectName("featureArt")
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setMinimumHeight(62)
            cv.addWidget(picture)
            flag = QLabel(tag)
            flag.setObjectName("eyebrow")
            cv.addWidget(flag)
            headline = QLabel(name)
            headline.setObjectName("cardTitle")
            cv.addWidget(headline)
            detail = QLabel(summary)
            detail.setObjectName("mutedSmall")
            detail.setWordWrap(True)
            cv.addWidget(detail)
            button = make_button("Import a pack  ↗", "soft", 31)
            button.clicked.connect(self.choose_addons)
            cv.addWidget(button)
            grid.addWidget(card, 0, column)
        root.addLayout(grid)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        servers, server_layout = make_panel("Servers", "Your saved Bedrock server list")
        server_head = QHBoxLayout()
        server_head.addStretch(1)
        add_server = make_button("＋ Add", "soft", 29)
        add_server.clicked.connect(self.add_server)
        server_head.addWidget(add_server)
        server_layout.addLayout(server_head)
        self.server_list = QListWidget()
        self.server_list.setObjectName("compactList")
        self.server_list.setMinimumHeight(115)
        server_layout.addWidget(self.server_list)
        lower.addWidget(servers, 3)
        playtime, time_layout = make_panel("Your playtime", "Recorded by Fresh MCPE")
        self.playtime_value = QLabel("0h 00m")
        self.playtime_value.setObjectName("playtimeValue")
        time_layout.addWidget(self.playtime_value)
        bars = QHBoxLayout()
        bars.setSpacing(6)
        for height in (18, 33, 23, 43, 29, 21, 47):
            wrap = QVBoxLayout()
            wrap.addStretch(1)
            bar = QFrame()
            bar.setObjectName("chartBar")
            bar.setFixedHeight(height)
            bar.setMinimumWidth(12)
            wrap.addWidget(bar)
            bars.addLayout(wrap, 1)
        time_layout.addLayout(bars)
        local_note = QLabel("Session-time tracking is being added; past playtime is not imported.")
        local_note.setObjectName("mutedSmall")
        local_note.setWordWrap(True)
        time_layout.addWidget(local_note)
        lower.addWidget(playtime, 2)
        root.addLayout(lower)
        root.addStretch(1)
        return self.scroll_page(body)

    def build_instances(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        panel, layout = make_panel("Instances & versions", "Fresh MCPE lists game builds in its private data folder, separate from other launcher installs.")
        row = QHBoxLayout()
        self.instances_combo = QComboBox()
        self.instances_combo.setMinimumHeight(42)
        self.instances_combo.currentIndexChanged.connect(self.on_instance_changed)
        row.addWidget(self.instances_combo, 1)
        launch = make_button("▶ Play", "primary", 42)
        launch.clicked.connect(self.launch_selected_version)
        row.addWidget(launch)
        install = make_button("＋ Sign in / install version", "secondary", 42)
        install.clicked.connect(self.open_runtime_ui)
        row.addWidget(install)
        layout.addLayout(row)
        root.addWidget(panel)
        self.instances_list = QListWidget()
        self.instances_list.setMinimumHeight(300)
        root.addWidget(self.instances_list, 1)
        note, note_layout = make_panel("Private runtime", "The client and version manager are built from source into Fresh MCPE's own runtime directory. The system .deb and Flatpak are not used.")
        root.addWidget(note)
        return self.scroll_page(body)

    def build_addons(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        panel, layout = make_panel("Add-on manager", "Choose or drag .mcpack / .mcaddon files, or use a direct HTTPS archive URL.")
        row = QHBoxLayout()
        choose = make_button("＋ Import .mcpack / .mcaddon", "primary", 40)
        choose.clicked.connect(self.choose_addons)
        row.addWidget(choose)
        openres = make_button("Open resource packs", "secondary", 40)
        openres.clicked.connect(lambda: self.open_path(self.root.game_dir / "resource_packs"))
        row.addWidget(openres)
        openbeh = make_button("Open behavior packs", "secondary", 40)
        openbeh.clicked.connect(lambda: self.open_path(self.root.game_dir / "behavior_packs"))
        row.addWidget(openbeh)
        layout.addLayout(row)
        urlrow = QHBoxLayout()
        self.addon_url_input = QLineEdit()
        self.addon_url_input.setPlaceholderText("Direct HTTPS link to .mcpack, .mcaddon or ZIP")
        urlrow.addWidget(self.addon_url_input, 1)
        get = make_button("Download & install", "soft", 40)
        get.clicked.connect(self.download_addon_url)
        urlrow.addWidget(get)
        layout.addLayout(urlrow)
        root.addWidget(panel)
        packs, packs_layout = make_panel("Installed Bedrock packs")
        self.addons_list = QListWidget()
        self.addons_list.setMinimumHeight(300)
        packs_layout.addWidget(self.addons_list)
        remove = make_button("Remove selected pack", "secondary")
        remove.clicked.connect(self.remove_selected_addon)
        packs_layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(packs, 1)
        note = QLabel("Imported packs still need activating in the chosen world's settings. Java Edition modpacks are not Bedrock add-ons.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        return self.scroll_page(body)

    def build_skins(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        panel, layout = make_panel("Skins & dressing room", "Import Bedrock skin packs. After importing, choose a skin in Minecraft's Dressing Room / Classic Skins interface. Marketplace account features remain controlled by the game.")
        row = QHBoxLayout()
        choose = make_button("＋ Import skin pack", "primary", 40)
        choose.clicked.connect(self.choose_addons)
        row.addWidget(choose)
        folder = make_button("Open skin packs folder", "secondary", 40)
        folder.clicked.connect(lambda: self.open_path(self.root.game_dir / "skin_packs"))
        row.addWidget(folder)
        layout.addLayout(row)
        root.addWidget(panel)
        packs_panel, packs_layout = make_panel("Installed skin packs")
        self.skins_list = QListWidget()
        self.skins_list.setMinimumHeight(300)
        packs_layout.addWidget(self.skins_list)
        remove = make_button("Remove selected skin pack", "secondary")
        remove.clicked.connect(self.remove_selected_skin)
        packs_layout.addWidget(remove, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(packs_panel, 1)
        return self.scroll_page(body)

    def remove_selected_skin(self) -> None:
        item = self.skins_list.currentItem()
        pack = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(pack, InstalledPack) or pack.kind != "Skin pack":
            self.notice("Select a skin pack", "Choose an installed skin pack first.")
            return
        if QMessageBox.question(self, "Remove skin pack", f"Remove {pack.name} from Fresh MCPE?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self.start_task(lambda: safe_remove_pack(pack, self.root.game_dir), lambda _result: (self.finish_task(), self.notice("Skin pack removed", pack.name)))

    def build_mods(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        panel, layout = make_panel("Launcher mods", "Native mods run code inside the launcher/game process. Use only builds you trust and that match your selected game version.")
        row = QHBoxLayout()
        choose = make_button("＋ Import archive", "primary")
        choose.clicked.connect(self.choose_mod)
        row.addWidget(choose)
        openfolder = make_button("Open mods folder", "secondary")
        openfolder.clicked.connect(lambda: self.open_path(self.root.mods_dir))
        row.addWidget(openfolder)
        layout.addLayout(row)
        urlrow = QHBoxLayout()
        self.mod_url_input = QLineEdit()
        self.mod_url_input.setPlaceholderText("Direct HTTPS ZIP/TAR mod archive URL")
        urlrow.addWidget(self.mod_url_input, 1)
        download = make_button("Download & install", "soft")
        download.clicked.connect(self.download_mod_url)
        urlrow.addWidget(download)
        layout.addLayout(urlrow)
        root.addWidget(panel)
        modpanel, modlayout = make_panel("Installed mod folders")
        self.mods_list = QListWidget()
        self.mods_list.setMinimumHeight(300)
        modlayout.addWidget(self.mods_list)
        toggle = make_button("Enable / disable selected", "secondary")
        toggle.clicked.connect(self.toggle_selected_mod)
        modlayout.addWidget(toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(modpanel, 1)
        return self.scroll_page(body)

    def build_discover(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        panel, layout = make_panel("Discover Bedrock add-ons", "Use a direct download link from a trusted Bedrock add-on source. Regular web-page URLs are not direct downloads.")
        row = QHBoxLayout()
        self.discover_url = QLineEdit()
        self.discover_url.setPlaceholderText("Paste direct HTTPS add-on URL")
        row.addWidget(self.discover_url, 1)
        install = make_button("Download & install", "primary", 40)
        install.clicked.connect(self.install_discover_url)
        row.addWidget(install)
        layout.addLayout(row)
        root.addWidget(panel)
        grid = QGridLayout()
        for i, (tag, name, desc, url) in enumerate([
            ("COMMUNITY", "MCPEDL", "Community maps, resource packs and behavior packs.", "https://mcpedl.com/"),
            ("OFFICIAL", "Minecraft Marketplace", "Official Bedrock content and Marketplace updates.", "https://www.minecraft.net/en-us/marketplace"),
            ("PROJECT", "Fresh MCPE", "Report bugs and follow the launcher development.", GITHUB_URL),
        ]):
            card, cv = make_panel(name, desc, "featureCard")
            flag = QLabel(tag)
            flag.setObjectName("eyebrow")
            cv.addWidget(flag)
            openbutton = make_button("Open site ↗", "soft")
            openbutton.clicked.connect(lambda _checked=False, dest=url: QDesktopServices.openUrl(QUrl(dest)))
            cv.addWidget(openbutton)
            grid.addWidget(card, 0, i)
        root.addLayout(grid)
        recent, recent_layout = make_panel("Installed add-ons")
        self.discover_list = QListWidget()
        self.discover_list.setMinimumHeight(260)
        recent_layout.addWidget(self.discover_list)
        root.addWidget(recent, 1)
        return self.scroll_page(body)

    def build_worlds(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        intro, layout = make_panel("Worlds & backups", "Worlds are kept in Fresh MCPE's isolated data directory. Backups are saved under Documents/Fresh MCPE Backups.")
        row = QHBoxLayout()
        backup = make_button("Create backup now", "primary", 40)
        backup.clicked.connect(lambda: self.backup(manual=True))
        row.addWidget(backup)
        folder = make_button("Open worlds folder", "secondary", 40)
        folder.clicked.connect(lambda: self.open_path(self.root.game_dir / "minecraftWorlds"))
        row.addWidget(folder)
        layout.addLayout(row)
        root.addWidget(intro)
        worldspanel, wlayout = make_panel("Worlds in Fresh MCPE")
        self.worlds_list = QListWidget()
        self.worlds_list.setMinimumHeight(155)
        wlayout.addWidget(self.worlds_list)
        root.addWidget(worldspanel)
        bpanel, blayout = make_panel("Saved snapshots")
        self.backups_list = QListWidget()
        self.backups_list.setMinimumHeight(190)
        blayout.addWidget(self.backups_list)
        restore = make_button("Restore selected backup", "secondary")
        restore.clicked.connect(self.restore_selected_backup)
        blayout.addWidget(restore, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(bpanel)
        note = QLabel("Close Minecraft before manual backup or restore. Restore creates a separate safety copy of current worlds first.")
        note.setObjectName("warningText")
        note.setWordWrap(True)
        root.addWidget(note)
        return self.scroll_page(body)

    def build_settings(self) -> QWidget:
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 6)
        runtime, runtime_layout = make_panel("Fresh MCPE runtime", "The runtime is built into Fresh MCPE's private directory; the system MCPelauncher .deb and Flatpak are not dependencies.")
        path = QLabel(str(RUNTIME_ROOT))
        path.setObjectName("pathLabel")
        path.setWordWrap(True)
        runtime_layout.addWidget(path)
        self.runtime_detail = QLabel("Checking private runtime...")
        self.runtime_detail.setObjectName("muted")
        self.runtime_detail.setWordWrap(True)
        runtime_layout.addWidget(self.runtime_detail)
        row = QHBoxLayout()
        build = make_button("Build / repair runtime", "primary", 40)
        build.clicked.connect(self.build_runtime_help)
        row.addWidget(build)
        login = make_button("Sign in / install game versions", "secondary", 40)
        login.clicked.connect(self.open_runtime_ui)
        row.addWidget(login)
        runtime_layout.addLayout(row)
        root.addWidget(runtime)

        options, opt_layout = make_panel("Storage and performance")
        self.auto_backup = QCheckBox("Automatically back up changed worlds before launching")
        self.auto_backup.toggled.connect(self.change_auto_backup)
        opt_layout.addWidget(self.auto_backup)
        self.gamemode = QCheckBox("Use Linux GameMode when installed")
        self.gamemode.toggled.connect(self.change_gamemode)
        opt_layout.addWidget(self.gamemode)
        retain = QHBoxLayout()
        retain.addWidget(QLabel("Keep recent automatic snapshots"))
        self.retention = QComboBox()
        for count in (3, 5, 10, 20):
            self.retention.addItem(f"{count} backups", count)
        self.retention.currentIndexChanged.connect(self.change_retention)
        retain.addWidget(self.retention)
        retain.addStretch(1)
        opt_layout.addLayout(retain)
        paths = QHBoxLayout()
        data = make_button("Open Fresh MCPE data", "secondary")
        data.clicked.connect(lambda: self.open_path(NATIVE_ROOT))
        paths.addWidget(data)
        backups = make_button("Open backups", "secondary")
        backups.clicked.connect(lambda: self.open_path(BACKUP_DIR))
        paths.addWidget(backups)
        paths.addStretch(1)
        opt_layout.addLayout(paths)
        migration, migration_layout = make_panel("Bring over your old worlds", "Copy versions and Bedrock user content from another launcher into Fresh MCPE. The source install is left untouched. Account tokens and native mods are never copied.")
        migration_row = QHBoxLayout()
        import_deb = make_button("Import old .deb data", "secondary")
        import_deb.clicked.connect(lambda: self.migrate_from(LEGACY_NATIVE_ROOT, "old native install"))
        migration_row.addWidget(import_deb)
        import_flatpak = make_button("Import Flatpak data", "secondary")
        import_flatpak.clicked.connect(lambda: self.migrate_from(FLATPAK_ROOT, "old Flatpak install"))
        migration_row.addWidget(import_flatpak)
        migration_layout.addLayout(migration_row)
        root.addWidget(migration)

        root.addWidget(options)

        account, acc_layout = make_panel("Account and privacy")
        message = QLabel("Sign-in uses the version manager that is built from source into Fresh MCPE. Fresh MCPE does not ask you to paste Microsoft or Google passwords into its own fields.")
        message.setObjectName("muted")
        message.setWordWrap(True)
        acc_layout.addWidget(message)
        repo = make_button("Fresh MCPE on GitHub ↗", "soft")
        repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        acc_layout.addWidget(repo)
        root.addWidget(account)
        root.addStretch(1)
        return self.scroll_page(body)

    def build_news(self) -> None:
        entries = [
            ("SEP 28, 2026", "Grinding & Galaxy", "New on Java Realms", "✧", "#30244b"),
            ("AUG 28, 2026", "Mischiefs & Secrets", "New on Java Realms", "♜", "#3c2c4a"),
            ("JUL 29, 2026", "9 fun Realms maps", "Are you ready?", "▧", "#2d493a"),
            ("JUN 26, 2026", "Dash and Unwind", "New on Java Realms", "ϟ", "#493051"),
        ]
        while self.news_cards.count():
            item = self.news_cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for date, title, subtitle, glyph, color in entries:
            card = QFrame()
            card.setObjectName("newsCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 8, 8, 9)
            layout.setSpacing(4)
            art = QLabel(glyph)
            art.setObjectName("newsArt")
            art.setAlignment(Qt.AlignmentFlag.AlignCenter)
            art.setMinimumHeight(62)
            art.setStyleSheet(f"QLabel#newsArt {{ background: {color}; color: #f0dcff; border-radius: 7px; font-size: 28px; font-weight: 900; }}")
            layout.addWidget(art)
            date_label = QLabel(date)
            date_label.setObjectName("newsDate")
            layout.addWidget(date_label)
            title_label = QLabel(title)
            title_label.setObjectName("newsItemTitle")
            title_label.setWordWrap(True)
            layout.addWidget(title_label)
            sub = QLabel(subtitle)
            sub.setObjectName("mutedSmall")
            layout.addWidget(sub)
            card.mousePressEvent = lambda _event: QDesktopServices.openUrl(QUrl("https://www.minecraft.net/en-us/realms/realms-stories"))
            self.news_cards.addWidget(card)

    def refresh_news(self) -> None:
        self.notice("News", "The starter rail uses the headlines in your design brief. Live news integration is a future task; these cards are not a live news feed yet.")

    def navigate(self, page: str) -> None:
        if page not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[page])
        for key, button in self.nav.items():
            button.setChecked(key == page)
        self.refresh_runtime_status()

    def selected_version(self) -> InstalledVersion | None:
        return self.version_combo.currentData() if hasattr(self, "version_combo") else None

    def on_version_changed(self, _index: int = -1) -> None:
        if self.refreshing:
            return
        selected = self.selected_version()
        if selected:
            self.settings["selected_version"] = selected.name
            save_settings(self.settings)
        self.sync_version_combos()

    def on_instance_changed(self, _index: int = -1) -> None:
        if self.refreshing:
            return
        selected = self.instances_combo.currentData()
        if selected:
            self.version_combo.blockSignals(True)
            idx = self.version_combo.findData(selected)
            self.version_combo.setCurrentIndex(idx)
            self.version_combo.blockSignals(False)
            self.settings["selected_version"] = selected.name
            save_settings(self.settings)

    def sync_version_combos(self) -> None:
        if not hasattr(self, "instances_combo"):
            return
        selected = self.selected_version()
        self.instances_combo.blockSignals(True)
        self.instances_combo.setCurrentIndex(self.instances_combo.findData(selected))
        self.instances_combo.blockSignals(False)

    def refresh_all(self) -> None:
        self.roots = discover_data_roots()
        self.root = find_root(self.roots, "native")
        self.versions = discover_versions(self.roots)
        self.refreshing = True
        for combo in (self.version_combo, self.instances_combo):
            combo.blockSignals(True)
            combo.clear()
            for version in self.versions:
                combo.addItem(f"{version.name}  ·  Bedrock", version)
            index = next((i for i, version in enumerate(self.versions) if version.name == self.settings.get("selected_version")), 0 if self.versions else -1)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.refreshing = False
        while self.quick_row.count():
            item = self.quick_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i in range(4):
            if i < len(self.versions):
                version = self.versions[i]
                label = version.name if len(version.name) < 7 else version.name[-5:]
                button = QPushButton(label)
                button.setObjectName("quickChip")
                button.setFixedSize(51, 51)
                button.setToolTip(f"Launch Bedrock {version.name}")
                button.clicked.connect(lambda _checked=False, item=version: self.launch_version(item))
            else:
                button = QPushButton("·")
                button.setObjectName("quickChipEmpty")
                button.setFixedSize(51, 51)
                button.setEnabled(False)
            self.quick_row.addWidget(button)
        plus = QPushButton("+")
        plus.setObjectName("quickChipAdd")
        plus.setFixedSize(51, 51)
        plus.setToolTip("Add a Bedrock version")
        plus.clicked.connect(self.open_runtime_ui)
        self.quick_row.addWidget(plus)
        self.quick_row.addStretch(1)
        self.instances_list.clear()
        for version in self.versions:
            row = QListWidgetItem(f"▦  {version.name}\n{version.path}")
            row.setData(Qt.ItemDataRole.UserRole, version)
            self.instances_list.addItem(row)
        if not self.versions:
            self.instances_list.addItem("No versions installed in Fresh MCPE yet. Click + to sign in and install one.")
        self.refresh_addons()
        self.refresh_skins()
        self.refresh_mods()
        self.refresh_worlds()
        self.refresh_backups()
        self.refresh_servers()
        self.refresh_playtime()
        self.refresh_runtime_status()
        self.auto_backup.blockSignals(True)
        self.auto_backup.setChecked(bool(self.settings.get("auto_backup", True)))
        self.auto_backup.blockSignals(False)
        self.gamemode.blockSignals(True)
        self.gamemode.setChecked(bool(self.settings.get("performance_mode", True)))
        self.gamemode.blockSignals(False)
        self.retention.blockSignals(True)
        self.retention.setCurrentIndex(max(0, self.retention.findData(int(self.settings.get("backup_retention", 5)))))
        self.retention.blockSignals(False)

    def refresh_addons(self) -> None:
        packs = list_installed_packs(self.root.game_dir)
        for key in ("addons_list", "discover_list"):
            view = getattr(self, key, None)
            if view is None:
                continue
            view.clear()
            for pack in packs:
                item = QListWidgetItem(f"{'◇' if pack.kind == 'Resource pack' else '⬡'}  {pack.name}  ·  v{pack.version}\n{pack.kind}  •  {pack.path}")
                item.setData(Qt.ItemDataRole.UserRole, pack)
                view.addItem(item)
            if not packs:
                view.addItem("No Bedrock packs installed in this Fresh MCPE instance yet.")

    def refresh_skins(self) -> None:
        view = getattr(self, "skins_list", None)
        if view is None:
            return
        view.clear()
        packs = [pack for pack in list_installed_packs(self.root.game_dir) if pack.kind == "Skin pack"]
        for pack in packs:
            item = QListWidgetItem(f"♧  {pack.name}  ·  v{pack.version}\n{pack.path}")
            item.setData(Qt.ItemDataRole.UserRole, pack)
            view.addItem(item)
        if not packs:
            view.addItem("No skin packs installed. Import a Bedrock skin-pack .mcpack to start.")

    def refresh_mods(self) -> None:
        view = getattr(self, "mods_list", None)
        if view is None:
            return
        view.clear()
        for folder in list_mod_folders(self.root.mods_dir):
            disabled = folder.name.endswith(".disabled")
            protected = folder.name == "mcpelauncher-updates"
            status = "PROTECTED RUNTIME" if protected else ("DISABLED" if disabled else "ENABLED")
            item = QListWidgetItem(f"{'●' if not disabled else '○'}  {folder.name}\n{status}  •  {folder}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            view.addItem(item)
        if not view.count():
            view.addItem("No custom native mod folders.")

    def refresh_worlds(self) -> None:
        view = getattr(self, "worlds_list", None)
        if view is None:
            return
        view.clear()
        worlds = self.root.game_dir / "minecraftWorlds"
        if worlds.is_dir():
            for folder in sorted((p for p in worlds.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
                name = folder.name
                try:
                    file = folder / "levelname.txt"
                    if file.is_file():
                        name = file.read_text(encoding="utf-8", errors="replace").strip() or name
                except OSError:
                    pass
                item = QListWidgetItem(f"▣  {name}\n{folder}")
                item.setData(Qt.ItemDataRole.UserRole, folder)
                view.addItem(item)
        if not view.count():
            view.addItem("No worlds in Fresh MCPE yet. Existing worlds can be copied into this folder.")

    def refresh_backups(self) -> None:
        view = getattr(self, "backups_list", None)
        if view is None:
            return
        view.clear()
        for folder, meta in list_backups(BACKUP_DIR):
            item = QListWidgetItem(f"◷  {meta.get('root_label', 'Fresh MCPE')}  ·  {meta.get('created', folder.name)}\n{meta.get('file_count', '?')} files  •  {fmt_bytes(int(meta.get('total_bytes', 0) or 0))}\n{folder}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            view.addItem(item)
        if not view.count():
            view.addItem("No snapshots yet.")

    def refresh_servers(self) -> None:
        if not hasattr(self, "server_list"):
            return
        self.server_list.clear()
        path = CONFIG_DIR / "servers.json"
        try:
            servers = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(servers, list):
                servers = []
        except (OSError, json.JSONDecodeError):
            servers = []
        for server in servers:
            if not isinstance(server, dict):
                continue
            self.server_list.addItem(f"●  {server.get('name', 'Server')}   ·   {server.get('address', '')}:{server.get('port', 19132)}")
        if not servers:
            self.server_list.addItem("No servers saved. Click + Add to create a favourite.")

    def refresh_playtime(self) -> None:
        try:
            data = json.loads((CONFIG_DIR / "playtime.json").read_text(encoding="utf-8"))
            seconds = max(0, int(data.get("total_seconds", 0)))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            seconds = 0
        hours, remainder = divmod(seconds, 3600)
        self.playtime_value.setText(f"{hours}h {remainder // 60:02d}m")

    def start_task(self, task: Callable[[], object], success: Callable[[object], None], failure: Callable[[str], None] | None = None) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.notice("Working", "Another file operation is still running.")
            return
        worker = Worker(task)
        self.worker = worker
        worker.succeeded.connect(success)
        worker.failed.connect(failure or self.show_error)
        worker.finished.connect(lambda: setattr(self, "worker", None))
        self.runtime_badge.setText("WORKING…")
        worker.start()

    def show_error(self, message: str) -> None:
        self.runtime_badge.setText("RUNTIME READY")
        self.notice("Operation failed", message)
        self.refresh_all()

    def finish_task(self) -> None:
        self.runtime_badge.setText("RUNTIME READY")
        self.refresh_all()

    def backup(self, manual: bool = False, next_step: Callable[[], None] | None = None) -> None:
        previous = dict(self.settings.get("world_fingerprints", {}))
        retention = int(self.settings.get("backup_retention", 5))
        roots = list(self.roots)
        def success(result: object) -> None:
            created, updated = result
            self.settings["world_fingerprints"] = updated
            save_settings(self.settings)
            self.finish_task()
            if manual:
                self.notice("Backup complete", f"Created {len(created)} snapshot(s).\n\n{BACKUP_DIR}" if created else "No Fresh MCPE worlds were found to back up.")
            if next_step:
                next_step()
        def failure(message: str) -> None:
            self.runtime_badge.setText("RUNTIME READY")
            if next_step and QMessageBox.question(self, "Backup failed", f"Backup failed:\n\n{message}\n\nLaunch anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                next_step()
            elif not next_step:
                self.notice("Backup failed", message)
        self.start_task(lambda: backup_changed_worlds(roots, BACKUP_DIR, previous, retention, force=manual), success, failure)

    def launch_selected_version(self) -> None:
        version = self.selected_version()
        if not version:
            self.notice("No version installed", "Click + Add to sign in and install a Bedrock version into Fresh MCPE.")
            return
        self.launch_version(version)

    def launch_version(self, version: InstalledVersion) -> None:
        if version.name == "1.26.60.4":
            choice = QMessageBox.warning(
                self, "Unconfirmed Bedrock compatibility",
                "This is the version that previously crashed with the missing __gnu_strerror_r symbol. The public compatibility-mod catalogue I checked lists supported patches only through 1.26.45.1, so this version is not confirmed to work yet.\n\nOpen the bundled version manager to choose a version with a matching patch, or try launching anyway?",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Open,
            )
            if choice == QMessageBox.StandardButton.Open:
                self.open_runtime_ui()
                return
            if choice != QMessageBox.StandardButton.Yes:
                return
        client = runtime_executable("mcpelauncher-client")
        if not client:
            self.build_runtime_help()
            return
        env = runtime_env()
        env["FRESH_MCPE_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
        env["FRESH_MCPE_DATA_ROOT"] = str(self.root.path)
        command = [str(client), "-dg", str(version.path)]
        # The runtime auto-loads its standard private mods directory. Pass -m only
        # when selecting the versioned compatibility bundle required by this build.
        compat = find_compatibility_mod(version.root_path)
        if compat:
            command.extend(["-m", str(compat)])
        gamemode = shutil.which("gamemoderun")
        if self.settings.get("performance_mode", True) and gamemode:
            command.insert(0, gamemode)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"bedrock-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        def launch() -> None:
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    subprocess.Popen(command, cwd=str(version.path), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.record_launch()
                self.runtime_badge.setText(f"LAUNCHING {version.name}")
                self.notice("Launching Bedrock", f"Started version {version.name} with Fresh MCPE's private runtime.\n\nCrash log:\n{log_path}")
            except OSError as exc:
                self.notice("Launch failed", str(exc))
        if self.settings.get("auto_backup", True):
            self.backup(manual=False, next_step=launch)
        else:
            launch()

    def record_launch(self) -> None:
        path = CONFIG_DIR / "playtime.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data["launch_count"] = int(data.get("launch_count", 0)) + 1
        data.setdefault("total_seconds", 0)
        data["last_launch"] = datetime.now().astimezone().isoformat(timespec="seconds")
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def open_runtime_ui(self) -> None:
        ui = runtime_executable("mcpelauncher-ui-qt")
        if not ui:
            self.build_runtime_help()
            return
        try:
            subprocess.Popen([str(ui)], env=runtime_env(), start_new_session=True)
            self.notice("Fresh MCPE version manager", "This sign-in and download component was built into Fresh MCPE's own runtime. Game data is stored separately from other installs.")
        except OSError as exc:
            self.notice("Couldn't open version manager", str(exc))

    def build_runtime_help(self) -> None:
        self.notice("Build the private runtime", "Open Terminal in your Fresh-mcpe repository and run:\n\nbash runtime/build.sh\n\nThis builds the client and sign-in/version component from source into ~/.local/opt/fresh-mcpe/runtime. It does not install or launch the system MCPelauncher .deb or Flatpak. Build dependencies require disk space and use two jobs by default for lower-memory PCs.")

    def choose_addons(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import Bedrock add-ons", str(Path.home() / "Downloads"), "Bedrock add-ons (*.mcpack *.mcaddon *.zip);;All files (*)")
        if paths:
            self.import_addon_paths([Path(p) for p in paths])

    def import_addon_paths(self, paths: list[Path]) -> None:
        def action() -> list[InstalledPack]:
            installed: list[InstalledPack] = []
            for path in paths:
                installed.extend(import_addon(path, self.root.game_dir))
            return installed
        def success(result: object) -> None:
            self.finish_task()
            self.notice("Add-on import complete", "\n".join(f"{p.name} — {p.kind}" for p in result) + "\n\nActivate packs in world settings.")
        self.start_task(action, success)

    def download_addon_url(self) -> None:
        url = self.addon_url_input.text().strip()
        if not url:
            self.notice("Add-on URL needed", "Paste a direct HTTPS link to a .mcpack, .mcaddon or compatible ZIP.")
            return
        def success(result: object) -> None:
            self.finish_task()
            self.addon_url_input.clear()
            self.notice("Download complete", "\n".join(f"{p.name} — {p.kind}" for p in result))
        self.start_task(lambda: download_and_import_addon(url, self.root.game_dir), success)

    def install_discover_url(self) -> None:
        self.addon_url_input.setText(self.discover_url.text())
        self.navigate("Add-ons")
        self.download_addon_url()

    def remove_selected_addon(self) -> None:
        item = self.addons_list.currentItem()
        pack = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(pack, InstalledPack):
            self.notice("Select a pack", "Select an installed Bedrock pack first.")
            return
        if QMessageBox.question(self, "Remove pack", f"Remove {pack.name} from Fresh MCPE?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self.start_task(lambda: safe_remove_pack(pack, self.root.game_dir), lambda _result: (self.finish_task(), self.notice("Pack removed", pack.name)))

    def choose_mod(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import native launcher mod", str(Path.home() / "Downloads"), "Mod archives (*.zip *.tar *.tar.gz *.tgz *.tar.xz);;All files (*)")
        if not path:
            return
        if QMessageBox.warning(self, "Trust this mod", "Native launcher mods can execute code on your computer. Continue only if you trust this source.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self.start_task(lambda: import_mod_archive(Path(path), self.root.mods_dir), lambda target: (self.finish_task(), self.notice("Mod imported", str(target))))

    def download_mod_url(self) -> None:
        url = self.mod_url_input.text().strip()
        if not url:
            self.notice("Mod URL needed", "Paste a direct HTTPS archive URL from a trusted source.")
            return
        if QMessageBox.warning(self, "Trust this mod", "Native launcher mods can execute code on this computer. Download only if you trust the archive.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        def success(target: object) -> None:
            self.finish_task()
            self.mod_url_input.clear()
            self.notice("Mod installed", str(target))
        self.start_task(lambda: download_and_import_mod(url, self.root.mods_dir), success)

    def toggle_selected_mod(self) -> None:
        item = self.mods_list.currentItem()
        folder = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(folder, Path):
            self.notice("Select a mod", "Choose a custom mod folder first.")
            return
        disabled = folder.name.endswith(".disabled")
        if QMessageBox.question(self, "Change mod state", f"{'Enable' if disabled else 'Disable'} {folder.name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self.start_task(lambda: set_mod_enabled(folder, disabled, self.root.mods_dir), lambda _result: self.finish_task())

    def add_server(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Bedrock server")
        form = QFormLayout(dialog)
        name = QLineEdit()
        address = QLineEdit()
        address.setPlaceholderText("play.example.net")
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(19132)
        form.addRow("Name", name)
        form.addRow("Address", address)
        form.addRow("Port", port)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not name.text().strip() or not address.text().strip():
            return
        path = CONFIG_DIR / "servers.json"
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except (OSError, json.JSONDecodeError):
            rows = []
        rows.append({"name": name.text().strip(), "address": address.text().strip(), "port": port.value()})
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        self.refresh_servers()

    def migrate_from(self, source: Path, source_label: str) -> None:
        if not source.is_dir():
            self.notice("No old launcher data", f"Couldn't find {source_label} at:\n{source}")
            return
        if QMessageBox.question(
            self, "Copy old launcher data",
            f"Copy installed versions and Bedrock user content from {source_label}?\n\nSource:\n{source}\n\nDestination:\n{NATIVE_ROOT}\n\nThis copies files without overwriting existing Fresh MCPE files. It does not copy login tokens, launcher binaries, or native mods. The old install stays untouched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        def success(result: object) -> None:
            self.finish_task()
            self.notice("Migration complete", f"Copied {result['copied_files']} files ({fmt_bytes(result['copied_bytes'])}).\nSkipped existing or unsupported files: {result['skipped_files']}.\n\nYour old launcher data was not deleted.")
        self.start_task(lambda: migrate_legacy_game_data(source, NATIVE_ROOT), success)

    def restore_selected_backup(self) -> None:
        item = self.backups_list.currentItem()
        snapshot = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(snapshot, Path):
            self.notice("Select a backup", "Choose a saved snapshot first.")
            return
        if QMessageBox.warning(self, "Restore backup", f"Restore this snapshot?\n\n{snapshot}\n\nClose Minecraft first. Fresh MCPE makes a safety copy of current worlds before restoring.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self.start_task(lambda: restore_backup(snapshot, BACKUP_DIR), lambda path: (self.finish_task(), self.notice("Worlds restored", str(path))))

    def change_auto_backup(self, checked: bool) -> None:
        self.settings["auto_backup"] = bool(checked)
        save_settings(self.settings)

    def change_gamemode(self, checked: bool) -> None:
        self.settings["performance_mode"] = bool(checked)
        save_settings(self.settings)

    def change_retention(self, index: int) -> None:
        if self.refreshing or index < 0:
            return
        self.settings["backup_retention"] = int(self.retention.itemData(index))
        save_settings(self.settings)

    def refresh_runtime_status(self) -> None:
        client = runtime_executable("mcpelauncher-client")
        ui = runtime_executable("mcpelauncher-ui-qt")
        if client and ui:
            self.runtime_badge.setText("PRIVATE RUNTIME READY")
            self.hero_status.setText("Bundled client and version manager are ready.")
            self.runtime_detail.setText(f"Client: {client}\nVersion manager: {ui}")
        elif client:
            self.runtime_badge.setText("RUNTIME PARTIAL")
            self.hero_status.setText("Game client found; version manager missing.")
            self.runtime_detail.setText("Run bash runtime/build.sh to finish the private runtime.")
        else:
            self.runtime_badge.setText("RUNTIME NOT BUILT")
            self.hero_status.setText("Build Fresh MCPE's private runtime to get started.")
            self.runtime_detail.setText("No system .deb or Flatpak is used. Runtime source is built into Fresh MCPE's own directory.")
        if hasattr(self, "play_button"):
            self.play_button.setEnabled(bool(self.versions) and client is not None)

    def open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except OSError as exc:
            self.notice("Couldn't open folder", str(exc))

    def notice(self, title: str, body: str) -> None:
        QMessageBox.information(self, title, body)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in {".mcpack", ".mcaddon", ".zip"} for url in event.mimeData().urls() if url.isLocalFile()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".mcpack", ".mcaddon", ".zip"}]
        if files:
            self.navigate("Add-ons")
            self.import_addon_paths(files)
            event.acceptProposedAction()
        else:
            event.ignore()


def style() -> str:
    """A calmer, polished desktop theme with readable typography and clear hierarchy."""
    return """
    * { font-family: "Inter", "Noto Sans", "Ubuntu", sans-serif; font-size: 13px; }
    QWidget { color: #e8edf5; background: #10151f; }
    QWidget#shell, QWidget#centerStack { background: #10151f; }
    QFrame#rail { background: #0b1018; border-right: 1px solid #222c3a; }
    QFrame#topbar { background: #111824; border-bottom: 1px solid #263142; }
    QFrame#newsRail { background: #111824; border-left: 1px solid #263142; }
    QLabel#logo { color: #ffffff; font-size: 25px; font-weight: 800; border-radius: 14px; background: #3978f6; }
    QLabel#avatar { color: #eaf1ff; background: #1c2a40; border: 1px solid #354966; border-radius: 21px; font-weight: 700; }
    QLabel#topBrand { color: #f7f9fc; font-size: 15px; font-weight: 800; letter-spacing: 1px; }
    QLabel#topTag { color: #8796ab; font-size: 9px; font-weight: 700; letter-spacing: 1.1px; }
    QLabel#runtimeBadge { background: #182a28; border: 1px solid #285b50; border-radius: 8px; padding: 7px 10px; color: #81dfc0; font-size: 10px; font-weight: 700; }
    QLabel#muted { color: #9ba9bc; }
    QLabel#mutedSmall { color: #9ba9bc; font-size: 11px; }
    QLabel#eyebrow { color: #85b4ff; font-size: 10px; font-weight: 800; letter-spacing: 1.2px; }
    QLabel#sectionTitle { color: #f2f5fa; font-size: 19px; font-weight: 750; }
    QLabel#panelTitle { color: #f0f4fa; font-size: 15px; font-weight: 700; }
    QLabel#heroTitle { color: #ffffff; font-size: 29px; font-weight: 800; }
    QLabel#heroArt { color: #b7d0ff; font-size: 58px; font-weight: 800; }
    QLabel#cardTitle { color: #f5f7fb; font-size: 14px; font-weight: 700; }
    QLabel#newsTitle { color: #f5f7fb; font-size: 17px; font-weight: 750; }
    QLabel#newsDate { color: #8fb8ff; font-size: 9px; font-weight: 700; letter-spacing: 0.8px; }
    QLabel#newsItemTitle { color: #e8edf5; font-size: 13px; font-weight: 650; }
    QLabel#socialLabel { color: #75859a; font-size: 9px; font-weight: 700; letter-spacing: 0.8px; }
    QLabel#playtimeValue { color: #ffffff; font-size: 30px; font-weight: 800; }
    QLabel#pathLabel { color: #c8d9f4; background: #151e2c; border: 1px solid #2b3a4e; padding: 10px; border-radius: 9px; }
    QLabel#warningText { color: #f0d6a4; background: #2b251a; border: 1px solid #5b4a2d; border-radius: 9px; padding: 10px; }
    QPushButton { color: #dfe7f2; border-radius: 8px; padding: 0 13px; font-weight: 650; min-height: 30px; }
    QPushButton#primary { color: #ffffff; border: 1px solid #6396ff; background: #3978f6; }
    QPushButton#primary:hover { background: #4b87ff; border-color: #83adff; }
    QPushButton#primary:disabled { color: #758196; background: #252f3d; border-color: #303c4d; }
    QPushButton#secondary { color: #e0e8f4; border: 1px solid #354357; background: #202b3a; }
    QPushButton#secondary:hover { background: #29384b; border-color: #506783; }
    QPushButton#soft { color: #b8d1ff; background: #192a42; border: 1px solid #2c4d78; }
    QPushButton#soft:hover { background: #203959; border-color: #4d79b7; }
    QPushButton#support { color: #c5d8f6; background: #172235; border: 1px solid #2c3e57; }
    QPushButton#support:hover { background: #21324a; }
    QPushButton#railButton { color: #7e8da2; background: transparent; border: 1px solid transparent; font-size: 22px; padding: 0; min-height: 0; }
    QPushButton#railButton:hover { color: #f4f7fb; background: #182333; }
    QPushButton#railButton:checked { color: #ffffff; background: #203c66; border-color: #376bb0; }
    QPushButton#addButton { color: #a9caff; background: #17263b; border: 1px dashed #456da5; font-size: 23px; padding: 0; min-height: 0; }
    QPushButton#addButton:hover { background: #213958; }
    QPushButton#quickChip { color: #e9f1ff; background: #1b2636; border: 1px solid #35465c; border-radius: 25px; font-weight: 700; }
    QPushButton#quickChip:hover { border: 2px solid #6096f8; background: #223550; }
    QPushButton#quickChipEmpty { color: #7d8ca1; background: #151e2b; border: 1px solid #283647; border-radius: 25px; }
    QPushButton#quickChipAdd { color: #b8d1ff; background: #17263b; border: 1px dashed #456da5; border-radius: 25px; font-size: 23px; }
    QPushButton#quickChipAdd:hover { color: #ffffff; background: #213958; }
    QPushButton#textButton { color: #8eb7ff; background: transparent; border: none; }
    QPushButton#textButton:hover { color: #c4d9ff; }
    QPushButton#smallIcon, QPushButton#socialButton { color: #a7b6ca; background: #1a2534; border: 1px solid #2c3a4d; padding: 0; min-height: 0; }
    QPushButton#smallIcon:hover, QPushButton#socialButton:hover { color: #ffffff; border-color: #5682c3; }
    QFrame#panel { background: #151e2b; border: 1px solid #273548; border-radius: 12px; }
    QFrame#hero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1c3455,stop:0.55 #17283f,stop:1 #172131); border: 1px solid #35557f; border-radius: 15px; }
    QFrame#heroGlass { background: rgba(10,17,28,0.45); border: 1px solid #344d6d; border-radius: 11px; }
    QFrame#featureCard { background: #182333; border: 1px solid #2b3b50; border-radius: 12px; }
    QFrame#newsCard { background: #172130; border: 1px solid #29374a; border-radius: 10px; }
    QFrame#newsCard:hover { border-color: #4d75ad; }
    QFrame#chartBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #83b1ff,stop:1 #3978f6); border-radius: 4px; }
    QComboBox, QLineEdit, QSpinBox { color: #e8edf5; background: #111a27; border: 1px solid #334257; border-radius: 8px; padding: 8px 10px; selection-background-color: #315f9e; }
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #5b94f4; }
    QComboBox QAbstractItemView { background: #151e2b; color: #e8edf5; selection-background-color: #29466c; }
    QListWidget { color: #e8edf5; background: #111a27; border: 1px solid #2b394c; border-radius: 9px; padding: 5px; outline: none; }
    QListWidget#compactList { max-height: 116px; }
    QListWidget::item { background: #182333; border: 1px solid #27374b; border-radius: 6px; padding: 9px; margin: 3px 1px; }
    QListWidget::item:selected { background: #223b5b; border-color: #5284c8; }
    QCheckBox { color: #dfe7f2; spacing: 9px; }
    QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px; border: 1px solid #53647b; background: #111a27; }
    QCheckBox::indicator:checked { background: #3978f6; border-color: #82adff; }
    QScrollArea { background: transparent; border: none; }
    QScrollBar:vertical { background: #10151f; width: 8px; margin: 0; }
    QScrollBar::handle:vertical { background: #34455d; border-radius: 4px; min-height: 24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Noto Sans", 10))
    app.setStyleSheet(style())
    window = FreshMCPE()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
