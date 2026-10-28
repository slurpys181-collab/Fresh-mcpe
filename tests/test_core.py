import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fresh_mcpe_core import (
    DataRoot, backup_changed_worlds, import_addon, list_installed_packs,
    safe_extract_zip, safe_remove_pack, set_mod_enabled,
)


def make_manifest(name, module_type, pack_uuid):
    return {
        "format_version": 2,
        "header": {"name": name, "description": "test pack", "uuid": pack_uuid, "version": [1, 0, 0], "min_engine_version": [1, 20, 0]},
        "modules": [{"type": module_type, "uuid": pack_uuid + "-module", "version": [1, 0, 0]}],
    }


class CoreTests(unittest.TestCase):
    def test_import_mcpack_routes_resource_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            archive = base / "test.mcpack"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("manifest.json", json.dumps(make_manifest("Test Resources", "resources", "resource-id")))
                bundle.writestr("textures/placeholder.txt", "sample")
            installed = import_addon(archive, base / "games/com.mojang")
            self.assertEqual(len(installed), 1)
            self.assertEqual(installed[0].kind, "Resource pack")
            self.assertTrue((installed[0].path / "manifest.json").is_file())
            self.assertEqual(len(list_installed_packs(base / "games/com.mojang")), 1)

    def test_import_mcaddon_routes_both_pack_types(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            archive = base / "bundle.mcaddon"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("behavior/manifest.json", json.dumps(make_manifest("Behavior", "data", "behavior-id")))
                bundle.writestr("resource/manifest.json", json.dumps(make_manifest("Resources", "resources", "resources-id")))
            installed = import_addon(archive, base / "games/com.mojang")
            self.assertEqual({item.kind for item in installed}, {"Resource pack", "Behavior pack"})
            self.assertTrue((base / "games/com.mojang/behavior_packs/Behavior/manifest.json").is_file())
            self.assertTrue((base / "games/com.mojang/resource_packs/Resources/manifest.json").is_file())

    def test_zip_slip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            archive = base / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escaped.txt", "no")
            with self.assertRaises(ValueError):
                safe_extract_zip(archive, base / "stage")
            self.assertFalse((base / "escaped.txt").exists())

    def test_mod_toggle_protects_update_mod(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = Path(folder) / "mods"
            mods.mkdir()
            custom = mods / "custom"
            custom.mkdir()
            disabled = set_mod_enabled(custom, False, mods)
            self.assertTrue(disabled.name.endswith(".disabled"))
            enabled = set_mod_enabled(disabled, True, mods)
            self.assertEqual(enabled.name, "custom")
            update = mods / "mcpelauncher-updates"
            update.mkdir()
            with self.assertRaises(ValueError):
                set_mod_enabled(update, False, mods)

    def test_world_backups_skip_unchanged_worlds_and_keep_changed_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = DataRoot("native", "Linux install", base / "data", "native")
            worlds = root.game_dir / "minecraftWorlds" / "world-id"
            worlds.mkdir(parents=True)
            (worlds / "levelname.txt").write_text("My World", encoding="utf-8")
            backups, fingerprints = backup_changed_worlds([root], base / "backups", {}, keep=5)
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "minecraftWorlds/world-id/levelname.txt").is_file())
            unchanged, same_fingerprints = backup_changed_worlds([root], base / "backups", fingerprints, keep=5)
            self.assertEqual(unchanged, [])
            self.assertEqual(same_fingerprints, fingerprints)
            (worlds / "levelname.txt").write_text("Changed name", encoding="utf-8")
            updated, _ = backup_changed_worlds([root], base / "backups", fingerprints, keep=5)
            self.assertEqual(len(updated), 1)

    def test_pack_remove_only_allows_managed_pack_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            game = base / "games/com.mojang"
            pack_dir = game / "resource_packs" / "Pack"
            pack_dir.mkdir(parents=True)
            (pack_dir / "manifest.json").write_text(json.dumps(make_manifest("Pack", "resources", "uuid")), encoding="utf-8")
            pack = list_installed_packs(game)[0]
            safe_remove_pack(pack, game)
            self.assertFalse(pack_dir.exists())


if __name__ == "__main__":
    unittest.main()
