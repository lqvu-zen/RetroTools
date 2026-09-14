"""Tests for the pure (non-Qt) device-config persistence module."""

import tempfile
import unittest
from pathlib import Path

from retro_tools.gui_configs import DeviceConfig, load_configs, save_configs


class ConfigPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "configs.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_configs(self.path), {})

    def test_round_trip(self):
        configs = {
            "Miyoo Mini": DeviceConfig(
                roms_path="D:/Roms",
                m3u_layout="nextui",
                m3u_single_disc_folders=True,
                cheats_root="D:/Cheats",
                cheats_chtdb="D:/libretro-database/cht",
            ),
            "RetroArch PC": DeviceConfig(roms_path="E:/Roms", m3u_layout="flat"),
        }
        save_configs(configs, self.path)
        self.assertEqual(load_configs(self.path), configs)

    def test_corrupt_file_returns_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("not json{{{", encoding="utf-8")
        self.assertEqual(load_configs(self.path), {})

    def test_non_dict_json_returns_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(load_configs(self.path), {})

    def test_unknown_and_missing_fields_tolerated(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            '{"Old Device": {"roms_path": "D:/Roms", "future_field": 123}}',
            encoding="utf-8",
        )
        loaded = load_configs(self.path)
        self.assertEqual(loaded["Old Device"], DeviceConfig(roms_path="D:/Roms"))

    def test_non_dict_entry_skipped(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"Bad": "not-an-object"}', encoding="utf-8")
        self.assertEqual(load_configs(self.path), {})

    def test_save_creates_parent_directory(self):
        nested = Path(self.tmpdir.name) / "nested" / "dir" / "configs.json"
        save_configs({"x": DeviceConfig(roms_path="D:/Roms")}, nested)
        self.assertTrue(nested.is_file())


if __name__ == "__main__":
    unittest.main()
