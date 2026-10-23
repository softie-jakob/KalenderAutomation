import unittest
from datetime import date, datetime, timezone

from src.dienstplan import (
    build_ics,
    compare_people,
    parse_legend,
    parse_plan,
    process_once,
)


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

    def test_pdf_rows_keep_first_code_after_name_marker(self) -> None:
        from pathlib import Path
        import tempfile

        text = """Dienstplan: 020RKT Von: 01.10.2026 Bis: 03.10.2026 Version: 02
01 02 03
Gruber J. .
07B
.
100:00
Kollege T. .
07T
.
.
Kollege T. 100:00
06B   Tour 6 - BF - 06:00-18:00   07B   Tour 7 - BF - 06:30-18:00
07T   Tour 7 - TF - 06:30-18:00
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.txt"
            path.write_text(text, encoding="utf-8")
            plan = parse_plan(path)

        self.assertEqual(plan.shifts[0].crew_members, ("Kollege T. (07T Rolle T)",))

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

    def test_multiple_months_use_filename_versions_and_are_merged(self) -> None:
        from pathlib import Path
        import tempfile
        from src.dienstplan import process_once

        october = TEXT.replace("01.10.2026 Bis: 03.10.2026", "01.10.2026 Bis: 03.10.2026")
        november = TEXT.replace("01.10.2026 Bis: 03.10.2026", "01.11.2026 Bis: 03.11.2026")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("input", "working", "output"):
                (root / name).mkdir()
            (root / "input" / "2610 V1.txt").write_text(october, encoding="utf-8")
            (root / "input" / "2611 V1.txt").write_text(november, encoding="utf-8")
            process_once(root)
            ics = (root / "output" / "dienstplan-gruber-j.ics").read_text(encoding="utf-8")

        self.assertIn("DTSTART;TZID=Europe/Vienna:20261002T063000", ics)
        self.assertIn("DTSTART;TZID=Europe/Vienna:20261102T063000", ics)

    def test_change_report_backup_archive_dry_run_and_person(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("input", "working", "output"):
                (root / name).mkdir()
            old_source = root / "input" / "2610 V1.txt"
            source = root / "input" / "2610 V2.txt"
            old_source.write_text(TEXT, encoding="utf-8")
            source.write_text(TEXT, encoding="utf-8")

            process_once(root, target_person="Gruber J.")
            source.write_text(TEXT.replace("07B SEF", "07T SEF"), encoding="utf-8")
            process_once(root, target_person="Gruber J.")

            self.assertTrue(list((root / "working" / "history").glob("*.ics")))
            self.assertTrue(list((root / "working" / "archive").glob("*-2610 V1.txt")))
            self.assertFalse(old_source.exists())
            self.assertIn("GEÄNDERT", (root / "working" / "changes.txt").read_text(encoding="utf-8"))
            before = (root / "output" / "dienstplan-gruber-j.ics").read_bytes()
            process_once(root, target_person="Gruber J.", dry_run=True)
            self.assertEqual(before, (root / "output" / "dienstplan-gruber-j.ics").read_bytes())
            self.assertIn("X-WR-CALNAME:Dienstplan Andere P.", build_ics(parse_plan(source), target_person="Andere P."))

    def test_compare_people_writes_markdown(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input").mkdir()
            text = TEXT.replace("Gruber J. . 07B SEF", "Gruber J. . 07B SEF")
            (root / "input" / "2610 V1.txt").write_text(text, encoding="utf-8")
            target = compare_people(root, "Gruber J.", "Kollege T.")
            markdown = target.read_text(encoding="utf-8")

        self.assertIn("# Dienstplanvergleich: Gruber J. und Kollege T.", markdown)
        self.assertIn("| 02.10.2026 | 07B (06:30–18:00) | 07T (ganztägig) | Unterschiedlich |", markdown)


if __name__ == "__main__":
    unittest.main()
