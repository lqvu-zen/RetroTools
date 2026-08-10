import unittest
from pathlib import Path

from retro_tools.discs import DiscName, group_by_stem, group_discs, parse_disc


class ParseDiscTests(unittest.TestCase):
    def test_redump_style(self):
        self.assertEqual(
            parse_disc("Final Fantasy VII (USA) (Disc 1)"),
            DiscName("Final Fantasy VII (USA)", 1),
        )

    def test_variants(self):
        cases = {
            "Chrono Cross (USA) (Disk 2)": ("Chrono Cross (USA)", 2),
            "Metal Gear Solid [Disc 1 of 2]": ("Metal Gear Solid", 1),
            "Grandia - CD3": ("Grandia", 3),
            "Riven.disc4": ("Riven", 4),
            "Some Game (USA) (Disc 01)": ("Some Game (USA)", 1),
        }
        for stem, (base, number) in cases.items():
            with self.subTest(stem=stem):
                self.assertEqual(parse_disc(stem), DiscName(base, number))

    def test_rightmost_token_wins(self):
        self.assertEqual(
            parse_disc("Example Sega CD Game (USA) (Disc 2)"),
            DiscName("Example Sega CD Game (USA)", 2),
        )

    def test_trailing_tags_are_preserved(self):
        self.assertEqual(
            parse_disc("Policenauts (Disc 1) (Rev 1)"),
            DiscName("Policenauts (Rev 1)", 1),
        )

    def test_no_disc_token(self):
        self.assertIsNone(parse_disc("Super Metroid (USA)"))
        self.assertIsNone(parse_disc("Sonic CD"))
        self.assertIsNone(parse_disc("Disc 1"))


class GroupTests(unittest.TestCase):
    def test_groups_by_base_title(self):
        paths = [
            Path("/roms/FF7 (USA) (Disc 1).cue"),
            Path("/roms/FF7 (USA) (Disc 1).bin"),
            Path("/roms/FF7 (USA) (Disc 2).cue"),
            Path("/roms/FF7 (USA) (Disc 2).bin"),
            Path("/roms/Other Game.chd"),
        ]
        groups = group_discs(paths)
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group.base, "FF7 (USA)")
        self.assertEqual(group.numbers, [1, 2])
        self.assertEqual(len(group.files), 4)

    def test_playlist_prefers_cue_over_bin(self):
        paths = [
            Path("/roms/G (Disc 1).bin"),
            Path("/roms/G (Disc 1).cue"),
            Path("/roms/G (Disc 2).bin"),
            Path("/roms/G (Disc 2).cue"),
        ]
        group = group_discs(paths)[0]
        self.assertEqual(
            group.playlist_lines(), ["G (Disc 1).cue", "G (Disc 2).cue"]
        )
        self.assertEqual(group.m3u_name, "G.m3u")

    def test_playlist_sorted_by_disc_number(self):
        paths = [
            Path("/roms/G (Disc 10).chd"),
            Path("/roms/G (Disc 2).chd"),
            Path("/roms/G (Disc 1).chd"),
        ]
        group = group_discs(paths)[0]
        self.assertEqual(
            group.playlist_lines(),
            ["G (Disc 1).chd", "G (Disc 2).chd", "G (Disc 10).chd"],
        )

    def test_case_insensitive_grouping(self):
        paths = [
            Path("/roms/Game (disc 1).cue"),
            Path("/roms/GAME (Disc 2).cue"),
        ]
        self.assertEqual(len(group_discs(paths)), 1)

    def test_group_by_stem_skips_disc_files(self):
        paths = [
            Path("/roms/Single.cue"),
            Path("/roms/Single.bin"),
            Path("/roms/Multi (Disc 1).cue"),
        ]
        stems = group_by_stem(paths)
        self.assertEqual(sorted(stems), ["Single"])
        self.assertEqual(len(stems["Single"]), 2)


if __name__ == "__main__":
    unittest.main()
