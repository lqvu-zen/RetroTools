import shutil
import tempfile
import unittest
from pathlib import Path

from retro_tools.cheats import (
    LaunchTarget,
    iter_launch_targets,
    plan_cheats,
    plan_cheats_for_system,
)
from retro_tools.plan import execute


def touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TempTreeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="retro-tools-cheats-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)


class IterLaunchTargetsTests(TempTreeTestCase):
    def test_loose_file_is_a_target(self):
        touch(self.root / "Ace Combat 2 (USA).chd")
        targets = iter_launch_targets(self.root)
        self.assertEqual(
            targets,
            [LaunchTarget(title="Ace Combat 2 (USA)", cheat_name="Ace Combat 2 (USA).chd")],
        )

    def test_folder_with_matching_m3u_is_a_target_named_after_the_playlist(self):
        game = self.root / "Xenogears (USA)"
        touch(game / "Xenogears (USA) (Disc 1).chd")
        touch(game / "Xenogears (USA) (Disc 2).chd")
        touch(game / "Xenogears (USA).m3u")

        targets = iter_launch_targets(self.root)
        self.assertEqual(
            targets,
            [LaunchTarget(title="Xenogears (USA)", cheat_name="Xenogears (USA).m3u")],
        )

    def test_folder_without_matching_m3u_is_not_a_target(self):
        game = self.root / "Weird Folder"
        touch(game / "Something.chd")
        self.assertEqual(iter_launch_targets(self.root), [])

    def test_m3u_and_ignored_extensions_are_not_their_own_target(self):
        touch(self.root / "Game.zip")
        touch(self.root / "Game.txt")
        touch(self.root / "map.txt")
        targets = iter_launch_targets(self.root)
        self.assertEqual(
            targets, [LaunchTarget(title="Game", cheat_name="Game.zip")]
        )


class PlanCheatsForSystemTests(TempTreeTestCase):
    def setUp(self):
        super().setUp()
        self.rom_dir = self.root / "Game Boy (GB)"
        self.rom_dir.mkdir(parents=True)
        self.cht_dir = self.root / "cht" / "Nintendo - Game Boy"
        self.cht_dir.mkdir(parents=True)
        self.cheats_root = self.root / "Cheats"

    def test_exact_match_writes_cheat_file(self):
        touch(self.rom_dir / "Tetris (World).zip")
        touch(self.cht_dir / "Tetris (World).cht", "cheats = 1\n")

        plan = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        execute(plan)

        written = self.cheats_root / "GB" / "Tetris (World).zip.cht"
        self.assertTrue(written.is_file())
        self.assertEqual(written.read_text(encoding="utf-8"), "cheats = 1\n")

    def test_no_match_writes_nothing(self):
        touch(self.rom_dir / "Some Homebrew Game.zip")
        plan = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        self.assertTrue(plan.is_empty)
        self.assertFalse((self.cheats_root / "GB").exists())

    def test_prefers_plain_variant_without_warning(self):
        touch(self.rom_dir / "Tetris (World).zip")
        touch(self.cht_dir / "Tetris (World).cht", "plain\n")
        touch(self.cht_dir / "Tetris (World) (Game Genie).cht", "genie\n")

        plan = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        execute(plan)

        written = self.cheats_root / "GB" / "Tetris (World).zip.cht"
        self.assertEqual(written.read_text(encoding="utf-8"), "plain\n")
        self.assertFalse(plan.warnings)

    def test_picks_best_device_variant_and_warns_when_no_plain_exists(self):
        touch(self.rom_dir / "Tetris (World).zip")
        touch(self.cht_dir / "Tetris (World) (Xploder).cht", "xploder\n")
        touch(self.cht_dir / "Tetris (World) (Game Buster).cht", "buster\n")

        plan = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        execute(plan)

        written = self.cheats_root / "GB" / "Tetris (World).zip.cht"
        self.assertEqual(written.read_text(encoding="utf-8"), "buster\n")
        self.assertTrue(plan.warnings)

    def test_single_device_variant_with_no_alternative_does_not_warn(self):
        touch(self.rom_dir / "Tetris (World).zip")
        touch(self.cht_dir / "Tetris (World) (Game Genie).cht", "genie\n")

        plan = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        execute(plan)
        self.assertFalse(plan.warnings)

    def test_rerun_is_a_no_op(self):
        touch(self.rom_dir / "Tetris (World).zip")
        touch(self.cht_dir / "Tetris (World).cht", "cheats = 1\n")
        execute(plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB"))

        second = plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        self.assertTrue(second.is_empty, second.actions)

    def test_multi_disc_folder_cheat_named_after_playlist(self):
        game = self.rom_dir / "Pokemon Trading Card Game (USA)"
        touch(game / "Pokemon Trading Card Game (USA) (Disc 1).chd")
        touch(game / "Pokemon Trading Card Game (USA).m3u")
        touch(self.cht_dir / "Pokemon Trading Card Game (USA).cht", "cheats = 1\n")

        execute(
            plan_cheats_for_system(self.rom_dir, self.cheats_root, self.cht_dir, "GB")
        )
        self.assertTrue(
            (
                self.cheats_root
                / "GB"
                / "Pokemon Trading Card Game (USA).m3u.cht"
            ).is_file()
        )

    def test_missing_cht_dir_is_noted_not_an_error(self):
        touch(self.rom_dir / "Tetris (World).zip")
        plan = plan_cheats_for_system(
            self.rom_dir, self.cheats_root, self.root / "no-such-console", "GB"
        )
        self.assertTrue(plan.is_empty)
        self.assertTrue(plan.notes)


class PlanCheatsTests(TempTreeTestCase):
    def setUp(self):
        super().setUp()
        self.roms_root = self.root / "Roms"
        self.cht_root = self.root / "cht"
        self.cheats_root = self.root / "Cheats"

    def test_walks_roms_root_and_maps_known_tags(self):
        gb = self.roms_root / "Game Boy (GB)"
        touch(gb / "Tetris (World).zip")
        touch(self.cht_root / "Nintendo - Game Boy" / "Tetris (World).cht", "x\n")

        plan = plan_cheats(self.roms_root, self.cheats_root, self.cht_root)
        execute(plan)
        self.assertTrue((self.cheats_root / "GB" / "Tetris (World).zip.cht").is_file())

    def test_unmapped_tag_is_noted_not_guessed(self):
        touch(self.roms_root / "Amiga (PUAE)" / "Some Game.adf")
        self.cht_root.mkdir(parents=True)
        plan = plan_cheats(self.roms_root, self.cheats_root, self.cht_root)
        self.assertTrue(any("PUAE" in n for n in plan.notes))
        self.assertFalse((self.cheats_root / "PUAE").exists())

    def test_single_system_folder_path_works_too(self):
        gb = self.roms_root / "Game Boy (GB)"
        touch(gb / "Tetris (World).zip")
        touch(self.cht_root / "Nintendo - Game Boy" / "Tetris (World).cht", "x\n")

        plan = plan_cheats(gb, self.cheats_root, self.cht_root)
        execute(plan)
        self.assertTrue((self.cheats_root / "GB" / "Tetris (World).zip.cht").is_file())


if __name__ == "__main__":
    unittest.main()
