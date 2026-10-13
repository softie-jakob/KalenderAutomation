import unittest
from datetime import date, datetime, timezone

from src.dienstplan import build_ics, parse_legend, parse_plan


TEXT = """Dienstplan: 020RKT Von: 01.10.2026 Bis: 03.10.2026 Version: 02
01 02 03
Gruber J. . 07B SEF 185:15
Kollege T. . 07T . 185:15
06B   Tour 6 - BF - 06:00-18:00   07B   Tour 7 - BF - 06:30-18:00   SEF   SEF Ausbildung - 8h
"""


class DienstplanTests(unittest.TestCase):
    def test_legend_extracts_times(self) -> None:
        legend = parse_legend(["07B   Tour 7 - BF - 06:30-18:00   SEF   SEF Ausbildung - 8h"])
        self.assertEqual(legend["07B"].start.hour, 6)
        self.assertEqual(legend["07B"].end.hour, 18)
        self.assertFalse(legend["SEF"].is_timed)

    def test_parse_and_stable_uid(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.txt"
            path.write_text(TEXT, encoding="utf-8")
            plan = parse_plan(path)
            ics = build_ics(plan, datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(len(plan.shifts), 2)
        self.assertIn("UID:gruber-j-20261002@kalender-automation.local", ics)
        self.assertIn("Besatzungsmitglieder: Kol", ics)
        self.assertIn("lege T. (07T Rolle T)", ics)
        self.assertIn("DTSTART;VALUE=DATE:20261003", ics)
        self.assertNotIn("UID:gruber-j-20261001", ics)

    def test_crew_matches_first_two_characters_and_reports_role(self) -> None:
        from pathlib import Path
        import tempfile

        text = TEXT.replace("07B SEF", "B1B SEF").replace("07T .", "B1T .")
        text = text.replace("07B   Tour 7", "B1B   Tour B1").replace(
            "SEF   SEF", "B1T   Tour B1 - TF - 06:30-18:00   SEF   SEF"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.txt"
            path.write_text(text, encoding="utf-8")
            plan = parse_plan(path)
            ics = build_ics(plan)

        self.assertIn("Kollege T. (B1T Rolle T)", ics.replace("\r\n ", ""))

    def test_process_saves_extracted_text_and_ics(self) -> None:
        from pathlib import Path
        import tempfile

        from src.dienstplan import process_once

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("input", "working", "output"):
                (root / name).mkdir()
            (root / "input" / "plan.txt").write_text(TEXT, encoding="utf-8")

            process_once(root)

            self.assertEqual(
                (root / "working" / "plan.txt").read_text(encoding="utf-8"),
                TEXT,
            )
            self.assertTrue((root / "output" / "dienstplan-gruber-j.ics").exists())


if __name__ == "__main__":
    unittest.main()
