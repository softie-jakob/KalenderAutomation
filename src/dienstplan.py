from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

TARGET_PERSON = "Gruber J."
TIMEZONE = "Europe/Vienna"
PRODID = "-//Kalender Automation//Dienstplan//DE"
IGNORED_CODES = {".", "U", "X", "XR", "K"}
SPECIAL_ALL_DAY_CODES = {"A", "SEF"}
MONTHS = {
    "Jänner": 1, "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8, "September": 9,
    "Oktober": 10, "November": 11, "Dezember": 12,
}


@dataclass(frozen=True)
class ShiftDefinition:
    code: str
    description: str
    start: Optional[dt_time] = None
    end: Optional[dt_time] = None

    @property
    def is_timed(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass(frozen=True)
class Shift:
    day: date
    definition: ShiftDefinition
    source_name: str
    plan_version: int
    crew_members: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    source_name: str
    plan_id: str
    start: date
    end: date
    version: int
    shifts: tuple[Shift, ...]
    warnings: tuple[str, ...]


def _parse_time(value: str) -> Optional[dt_time]:
    match = re.search(r"(\d{1,2}):(\d{2})", value)
    return dt_time(int(match.group(1)), int(match.group(2))) if match else None


def _parse_definition(code: str, description: str) -> ShiftDefinition:
    times = re.findall(r"(?<!\d)(\d{1,2}):(\d{2})", description)
    start = dt_time(int(times[0][0]), int(times[0][1])) if len(times) >= 1 else None
    end = dt_time(int(times[1][0]), int(times[1][1])) if len(times) >= 2 else None
    return ShiftDefinition(code, description.strip(), start, end)


def parse_legend(lines: Iterable[str]) -> dict[str, ShiftDefinition]:
    definitions: dict[str, ShiftDefinition] = {}
    for line in lines:
        pattern = r"([A-Za-zÜü0-9/]+)\s+(.+?)(?=\s{2,}[A-Za-zÜü0-9/]+\s+|$)"
        for match in re.finditer(pattern, line.strip()):
            code, description = match.groups()
            definitions[code] = _parse_definition(code, description)
    return definitions


def _metadata(text: str) -> tuple[date, date, int, str]:
    period = re.search(r"Von:\s*(\d{2}\.\d{2}\.\d{4})\s+Bis:\s*(\d{2}\.\d{2}\.\d{4})", text)
    if not period:
        period = re.search(
            r"(\d{2}\.\d{2}\.\d{4})\s*Von:\s*Bis:\s*(\d{2}\.\d{2}\.\d{4})",
            text,
        )
    if not period:
        raise ValueError("Zeitraum 'Von ... Bis ...' wurde nicht gefunden.")
    start = datetime.strptime(period.group(1), "%d.%m.%Y").date()
    end = datetime.strptime(period.group(2), "%d.%m.%Y").date()
    version_match = re.search(r"Version:\s*(\d+)", text)
    if not version_match:
        version_match = re.search(r"(\d+)\s*Version:", text)
    version = int(version_match.group(1)) if version_match else 0
    plan_match = re.search(r"Dienstplan:\s+(\S+)", text)
    plan_id = plan_match.group(1) if plan_match else "unbekannt"
    return start, end, version, plan_id


def _row_values(line: str, expected_days: int) -> Optional[tuple[str, list[str]]]:
    tokens = line.strip().split()
    if len(tokens) < expected_days + 2 or not re.fullmatch(r"\d+:\d+", tokens[-1]):
        return None
    codes = tokens[-(expected_days + 1):-1]
    name_tokens = tokens[:-(expected_days + 1)]
    if not name_tokens or not all(re.fullmatch(r"[A-Za-zÜüÄäÖöß0-9/.-]+", code) for code in codes):
        return None
    return " ".join(name_tokens), codes


def _tour_and_role(code: str) -> Optional[tuple[str, str]]:
    if len(code) != 3 or not all(character.isalnum() for character in code):
        return None
    role = code[2].upper()
    if role not in {"B", "F", "T"}:
        return None
    return code[:2].upper(), role


def _pdf_row_values(text: str, person: str, expected_days: int) -> Optional[list[str]]:
    lines = text.splitlines()
    try:
        start = next(
            index for index, line in enumerate(lines)
            if line.strip() == person or line.strip().startswith(f"{person} ")
        )
    except StopIteration:
        return None
    codes: list[str] = []
    for index, line in enumerate(lines[start:], start):
        tokens = line.split()
        if index == start:
            tokens = tokens[len(person.split()):]
        for token in tokens:
            if re.fullmatch(r"\d+:\d+", token):
                return codes[:expected_days] if len(codes) >= expected_days else None
            if re.fullmatch(r"[A-Za-zÜüÄäÖöß0-9/.-]+", token):
                codes.append(token)
    return codes[:expected_days] if len(codes) >= expected_days else None


def _read_source_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Nicht unterstütztes Eingabeformat: {path.suffix or 'unbekannt'}")
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "PDF-Verarbeitung benötigt pypdf. Installiere die Abhängigkeiten mit "
            "'python3 -m pip install -r requirements.txt'."
        ) from error
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(
            f"Aus {path.name} konnte kein Text extrahiert werden. "
            "Die PDF benötigt möglicherweise OCR."
        )
    return text


def parse_plan(
    path: Path,
    target_person: str = TARGET_PERSON,
    text: Optional[str] = None,
) -> Plan:
    text = _read_source_text(path) if text is None else text
    start, end, version, plan_id = _metadata(text)
    lines = text.splitlines()
    legend_start = next(
        (
            index for index, line in enumerate(lines)
            if re.search(r"\b06B\s+Tour\s+6\b", line)
        ),
        len(lines),
    )
    definitions = parse_legend(lines[legend_start:])
    expected_days = (end - start).days + 1
    rows: dict[str, list[str]] = {}
    for line in lines[:legend_start]:
        row = _row_values(line, expected_days)
        if row is not None:
            rows[row[0]] = row[1]
    target_codes = rows.get(target_person)
    if target_codes is None:
        target_codes = _pdf_row_values(text, target_person, expected_days)
        if target_codes is not None:
            rows[target_person] = target_codes
    if target_codes is None:
        raise ValueError(f"Person {target_person!r} wurde nicht gefunden.")

    codes = target_codes
    warnings: list[str] = []
    if len(codes) != expected_days:
        warnings.append(
            f"{target_person}: {len(codes)} Dienstspalten erkannt, erwartet wurden {expected_days}."
        )

    shifts: list[Shift] = []
    for offset, code in enumerate(codes[:expected_days]):
        day = start + timedelta(days=offset)
        if code in IGNORED_CODES:
            continue
        definition = definitions.get(code)
        if definition is None:
            warnings.append(f"{day.isoformat()}: Kürzel {code!r} fehlt in der Legende.")
            definition = ShiftDefinition(code, "Unbekanntes Dienstkürzel")
        elif code not in SPECIAL_ALL_DAY_CODES and not definition.is_timed:
            warnings.append(f"{day.isoformat()}: {code} hat keine auswertbare Uhrzeit.")
        crew_members: list[str] = []
        tour_and_role = _tour_and_role(code)
        if tour_and_role is not None:
            tour, _ = tour_and_role
            for name, person_codes in rows.items():
                if name == target_person:
                    continue
                other_code = person_codes[offset]
                other_tour_and_role = _tour_and_role(other_code)
                if other_tour_and_role is not None and other_tour_and_role[0] == tour:
                    crew_members.append(
                        f"{name} ({other_code} Rolle {other_tour_and_role[1]})"
                    )
        shifts.append(Shift(day, definition, path.name, version, tuple(sorted(crew_members))))
    return Plan(path.name, plan_id, start, end, version, tuple(shifts), tuple(warnings))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    encoded = line.encode("utf-8")
    chunks: list[bytes] = []
    while len(encoded) > 75:
        cut = 75
        while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(encoded[:cut])
        encoded = encoded[cut:]
    chunks.append(encoded)
    return "\r\n".join(chunk.decode("utf-8") if index == 0 else " " + chunk.decode("utf-8")
                        for index, chunk in enumerate(chunks))


def _format_local(day: date, value: dt_time) -> str:
    return f"{day:%Y%m%d}T{value:%H%M%S}"


def build_ics(plan: Plan, generated_at: Optional[datetime] = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Dienstplan Gruber J.",
        "X-WR-TIMEZONE:Europe/Vienna",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Vienna",
        "BEGIN:STANDARD",
        "DTSTART:19701025T030000",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "END:STANDARD",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]
    for shift in plan.shifts:
        definition = shift.definition
        uid = f"gruber-j-{shift.day:%Y%m%d}@kalender-automation.local"
        summary = f"{definition.code} - {definition.description}"
        details = (
            f"Person: {TARGET_PERSON}; Dienstkürzel: {definition.code}; "
            f"Dienst: {definition.description}; Quelle: {plan.source_name}; "
            f"Planversion: {plan.version}"
        )
        if shift.crew_members:
            details += f"; Besatzungsmitglieder: {', '.join(shift.crew_members)}"
        else:
            details += "; Besatzungsmitglieder: keine weiteren erkannt"
        if definition.code in SPECIAL_ALL_DAY_CODES or not definition.is_timed:
            details += "; Dauer: 8 Stunden; Beginn laut Plan unbekannt"
            lines += [
                "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{shift.day:%Y%m%d}",
                f"DTEND;VALUE=DATE:{(shift.day + timedelta(days=1)):%Y%m%d}",
                f"SUMMARY:{_escape(summary)}", f"DESCRIPTION:{_escape(details)}",
                "END:VEVENT",
            ]
        else:
            lines += [
                "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
                f"DTSTART;TZID={TIMEZONE}:{_format_local(shift.day, definition.start)}",
                f"DTEND;TZID={TIMEZONE}:{_format_local(shift.day, definition.end)}",
                f"SUMMARY:{_escape(summary)}", f"DESCRIPTION:{_escape(details)}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def select_latest_plan(input_dir: Path) -> tuple[Path, str, Plan, str]:
    candidates = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".pdf"}
    )
    if not candidates:
        raise FileNotFoundError(f"Keine TXT- oder PDF-Datei in {input_dir} gefunden.")
    parsed: list[tuple[Path, Plan, str]] = []
    for path in candidates:
        text = _read_source_text(path)
        parsed.append((path, parse_plan(path, text=text), text))
    selected_path, selected_plan, selected_text = max(
        parsed, key=lambda item: (item[1].version, item[0].stat().st_mtime)
    )
    digest = hashlib.sha256(selected_path.read_bytes()).hexdigest()
    return selected_path, digest, selected_plan, selected_text


def publish_output(root: Path, pages_dir: Path) -> None:
    source = root / "output" / "dienstplan-gruber-j.ics"
    target = pages_dir / source.name
    pages_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() == source.read_bytes():
        return
    shutil.copyfile(source, target)
    subprocess.run(["git", "-C", str(pages_dir), "add", target.name], check=True)
    result = subprocess.run(
        ["git", "-C", str(pages_dir), "diff", "--cached", "--quiet"],
        check=False,
    )
    if result.returncode == 1:
        subprocess.run(
            ["git", "-C", str(pages_dir), "commit", "-m", "Aktualisiere Dienstplan-Kalender"],
            check=True,
        )
        subprocess.run(["git", "-C", str(pages_dir), "push"], check=True)


def process_once(root: Path, pages_dir: Optional[Path] = None) -> Plan:
    input_dir = root / "input"
    working_dir = root / "working"
    output_dir = root / "output"
    working_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    source, digest, plan, source_text = select_latest_plan(input_dir)
    (working_dir / "last-input.sha256").write_text(f"{digest}  {source.name}\n", encoding="utf-8")
    (working_dir / "plan.txt").write_text(source_text, encoding="utf-8")
    (working_dir / "preview.txt").write_text(render_preview(plan), encoding="utf-8")
    (output_dir / "dienstplan-gruber-j.ics").write_text(build_ics(plan), encoding="utf-8")
    if pages_dir is not None:
        publish_output(root, pages_dir)
    return plan


def render_preview(plan: Plan) -> str:
    lines = [
        f"Quelle: {plan.source_name}",
        f"Plan: {plan.plan_id}, Version: {plan.version}",
        f"Zeitraum: {plan.start:%d.%m.%Y}–{plan.end:%d.%m.%Y}",
        "",
        "Termine:",
    ]
    for shift in plan.shifts:
        definition = shift.definition
        time_info = (
            f"{definition.start:%H:%M}–{definition.end:%H:%M}"
            if definition.is_timed else "ganztägig; Beginn unbekannt"
        )
        lines.append(f"{shift.day:%d.%m.%Y}  {definition.code:<4} {time_info}  {definition.description}")
    lines += ["", "Warnungen:"]
    lines.extend(f"- {warning}" for warning in plan.warnings) if plan.warnings else lines.append("- keine")
    return "\n".join(lines) + "\n"


def watch(root: Path, interval: float, pages_dir: Optional[Path] = None) -> None:
    last_signature: Optional[tuple[tuple[str, int, int], ...]] = None
    while True:
        input_dir = root / "input"
        signature = tuple(
            sorted((path.name, path.stat().st_size, path.stat().st_mtime_ns)
                   for path in input_dir.iterdir()
                   if path.is_file() and path.suffix.lower() in {".txt", ".pdf"})
        ) if input_dir.exists() else ()
        if signature != last_signature:
            try:
                process_once(root, pages_dir)
                print("Dienstplan verarbeitet.")
                last_signature = signature
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                print(f"Verarbeitung fehlgeschlagen: {error}")
                last_signature = signature
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dienstplan für Gruber J. als ICS erzeugen.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--watch", action="store_true", help="input/ dauerhaft überwachen.")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument(
        "--publish-dir",
        type=Path,
        help="Lokaler Checkout des GitHub-Pages-Repositories; Änderungen werden gepusht.",
    )
    args = parser.parse_args()
    if args.watch:
        watch(args.root, args.interval, args.publish_dir)
    else:
        plan = process_once(args.root, args.publish_dir)
        print(render_preview(plan))


if __name__ == "__main__":
    main()
