import shutil
import tempfile
import unittest
from pathlib import Path

from retro_tools.m3u import find_system_folders, looks_like_roms_root, plan_path
from retro_tools.plan import PlanError, execute, validate


def touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TempTreeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="retro-tools-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)


class PlanMultiDiscTests(TempTreeTestCase):
    def setUp(self):
        super().setUp()
        self.system = self.root / "Roms" / "PlayStation (PS)"
        self.system.mkdir(parents=True)
        for disc in (1, 2, 3):
            touch(self.system / "Final Fantasy VII (USA) (Disc {}).bin".format(disc))
            touch(self.system / "Final Fantasy VII (USA) (Disc {}).cue".format(disc))
        touch(self.system / "Castlevania SOTN (USA).chd")

    def test_dry_run_changes_nothing(self):
        before = sorted(p.name for p in self.system.iterdir())
        plan = plan_path(self.system)
        self.assertFalse(plan.is_empty)
        self.assertEqual(before, sorted(p.name for p in self.system.iterdir()))

    def test_apply_creates_folder_and_playlist(self):
        plan = plan_path(self.system)
        execute(plan)

        game = self.system / "Final Fantasy VII (USA)"
        self.assertTrue(game.is_dir())
        m3u = game / "Final Fantasy VII (USA).m3u"
        self.assertTrue(m3u.is_file())
        self.assertEqual(
            m3u.read_text(encoding="utf-8").splitlines(),
            [
                "Final Fantasy VII (USA) (Disc 1).cue",
                "Final Fantasy VII (USA) (Disc 2).cue",
                "Final Fantasy VII (USA) (Disc 3).cue",
            ],
        )
        # all six disc files moved, nothing left loose
        self.assertEqual(len(list(game.glob("*.bin"))), 3)
        self.assertEqual(len(list(game.glob("*.cue"))), 3)
        self.assertEqual(list(self.system.glob("*.cue")), [])

    def test_single_disc_game_left_alone(self):
        execute(plan_path(self.system))
        self.assertTrue((self.system / "Castlevania SOTN (USA).chd").is_file())

    def test_rerun_is_a_no_op(self):
        execute(plan_path(self.system))
        second = plan_path(self.system)
        self.assertTrue(second.is_empty, second.actions)

    def test_m3u_uses_lf_endings(self):
        execute(plan_path(self.system))
        raw = (
            self.system / "Final Fantasy VII (USA)" / "Final Fantasy VII (USA).m3u"
        ).read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))


class PlanExistingFolderTests(TempTreeTestCase):
    def test_writes_playlist_named_after_folder(self):
        game = self.root / "Sega CD (SEGACD)" / "Snatcher (USA)"
        game.mkdir(parents=True)
        for disc in (1, 2):
            touch(game / "Snatcher (USA) (Disc {}).cue".format(disc))
            touch(game / "Snatcher (USA) (Disc {}).bin".format(disc))

        execute(plan_path(self.root / "Sega CD (SEGACD)"))
        m3u = game / "Snatcher (USA).m3u"
        self.assertTrue(m3u.is_file())
        self.assertEqual(len(m3u.read_text(encoding="utf-8").splitlines()), 2)

    def test_existing_playlist_is_not_touched(self):
        game = self.root / "PS" / "Game"
        game.mkdir(parents=True)
        for disc in (1, 2):
            touch(game / "Game (Disc {}).cue".format(disc))
        touch(game / "Game.m3u", "original\n")

        plan = plan_path(self.root / "PS")
        self.assertTrue(plan.is_empty)
        self.assertEqual((game / "Game.m3u").read_text(encoding="utf-8"), "original\n")

    def test_mismatched_playlist_name_warns(self):
        game = self.root / "PS" / "Weird Folder Name"
        game.mkdir(parents=True)
        for disc in (1, 2):
            touch(game / "Game (Disc {}).cue".format(disc))
        touch(game / "Game.m3u", "a\nb\n")

        plan = plan_path(self.root / "PS")
        self.assertTrue(plan.warnings)
        self.assertIn("Weird Folder Name.m3u", plan.warnings[0])


class SingleDiscFolderTests(TempTreeTestCase):
    def test_bin_cue_pair_moved_into_folder(self):
        system = self.root / "PlayStation (PS)"
        system.mkdir(parents=True)
        touch(system / "Tony Hawk's Pro Skater 2 (USA).cue")
        touch(system / "Tony Hawk's Pro Skater 2 (USA).bin")
        touch(system / "Standalone.chd")

        execute(plan_path(system, single_disc_folders=True))
        folder = system / "Tony Hawk's Pro Skater 2 (USA)"
        self.assertTrue((folder / "Tony Hawk's Pro Skater 2 (USA).cue").is_file())
        self.assertTrue((folder / "Tony Hawk's Pro Skater 2 (USA).bin").is_file())
        # a lone .chd needs no folder
        self.assertTrue((system / "Standalone.chd").is_file())

    def test_not_done_without_the_flag(self):
        system = self.root / "PlayStation (PS)"
        system.mkdir(parents=True)
        touch(system / "Game.cue")
        touch(system / "Game.bin")
        self.assertTrue(plan_path(system).is_empty)


class RomsRootTests(TempTreeTestCase):
    def test_detects_root_and_walks_systems(self):
        roms = self.root / "Roms"
        for name in ("PlayStation (PS)", "Sega CD (SEGACD)", "Screenshots"):
            (roms / name).mkdir(parents=True)
        for disc in (1, 2):
            touch(roms / "PlayStation (PS)" / "A (Disc {}).cue".format(disc))
            touch(roms / "Sega CD (SEGACD)" / "B (Disc {}).cue".format(disc))
        touch(roms / "Screenshots" / "C (Disc 1).cue")
        touch(roms / "Screenshots" / "C (Disc 2).cue")

        self.assertTrue(looks_like_roms_root(roms))
        self.assertEqual(len(find_system_folders(roms)), 2)

        execute(plan_path(roms))
        self.assertTrue((roms / "PlayStation (PS)" / "A" / "A.m3u").is_file())
        self.assertTrue((roms / "Sega CD (SEGACD)" / "B" / "B.m3u").is_file())
        # untagged folder is ignored entirely
        self.assertFalse((roms / "Screenshots" / "C").exists())


class SafetyTests(TempTreeTestCase):
    def test_refuses_to_overwrite_existing_playlist(self):
        system = self.root / "PS"
        system.mkdir(parents=True)
        for disc in (1, 2):
            touch(system / "Game (Disc {}).cue".format(disc))
        # a stale file occupying the playlist path inside the target folder
        (system / "Game").mkdir()
        touch(system / "Game" / "Game.m3u", "stale\n")

        plan = plan_path(system)
        self.assertTrue(validate(plan))
        with self.assertRaises(PlanError):
            execute(plan)
        # nothing moved
        self.assertTrue((system / "Game (Disc 1).cue").is_file())
        self.assertEqual((system / "Game" / "Game.m3u").read_text(), "stale\n")

    def test_force_allows_overwrite(self):
        system = self.root / "PS"
        system.mkdir(parents=True)
        for disc in (1, 2):
            touch(system / "Game (Disc {}).cue".format(disc))
        (system / "Game").mkdir()
        touch(system / "Game" / "Game.m3u", "stale\n")

        execute(plan_path(system), force=True)
        self.assertNotEqual(
            (system / "Game" / "Game.m3u").read_text(encoding="utf-8"), "stale\n"
        )

    def test_target_collision_is_blocked(self):
        system = self.root / "PS"
        system.mkdir(parents=True)
        for disc in (1, 2):
            touch(system / "Game (Disc {}).cue".format(disc))
        (system / "Game").mkdir()
        touch(system / "Game" / "Game (Disc 1).cue", "already here")

        plan = plan_path(system)
        problems = validate(plan)
        self.assertTrue(any("already exists" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
