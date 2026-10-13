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
        self.assertIn("lege T. (07T)", ics)
        self.assertIn("DTSTART;VALUE=DATE:20261003", ics)
        self.assertNotIn("UID:gruber-j-20261001", ics)


if __name__ == "__main__":
    unittest.main()
