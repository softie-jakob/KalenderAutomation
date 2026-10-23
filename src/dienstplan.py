from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import time
from threading import Event
from difflib import unified_diff
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


def _filename_plan_key(path: Path) -> Optional[tuple[int, int, int]]:
    match = re.fullmatch(r"(\d{2})(\d{2})\s+V(\d+)", path.stem, re.IGNORECASE)
    if not match:
        return None
    year, month, version = (int(value) for value in match.groups())
    if not 1 <= month <= 12:
        return None
    return 2000 + year, month, version


def _person_slug(person: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", person.lower()).strip("-")


def _parse_time(value: str) -> Optional[dt_time]:
    match = re.search(r"(\d{1,2}):(\d{2})", value)
    return dt_time(int(match.group(1)), int(match.group(2))) if match else None


def _parse_definition(code: str, description: str) -> ShiftDefinition:
    times = re.findall(r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})", description)
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
        for match in re.finditer(
            r"\b([A-Za-zÜü0-9/]+)\s+(.+?"
            r"\d{1,2}\s*:\s*\d{2}\s*-\s*\d{1,2}\s*:\s*\d{2}[h]?)"
            r"(?=\s+[A-Za-zÜü0-9/]+\s+|$)",
            line.strip(),
        ):
            code, description = match.groups()
            definitions[code] = _parse_definition(code, description)
        for match in re.finditer(
            r"\b(A|SEF)\s+([^0-9\n]*?(?:8h|4h))(?=\s+[A-Za-zÜü0-9/]+\s+|$)",
            line.strip(),
        ):
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
    pdf_rows = False
    if target_codes is None:
        target_codes = _pdf_row_values(text, target_person, expected_days)
        if target_codes is not None:
            rows[target_person] = target_codes
            pdf_rows = True
    if pdf_rows:
        for line in lines:
            candidate = line.strip()
            if (
                " " in candidate
                and re.fullmatch(r"[A-Za-zÄÖÜäöüß ./'-]+", candidate)
                and not candidate.startswith(("Dienst", "Gedruckt", "von Benutzer"))
            ):
                person = re.sub(r"(?:\s+\.)+$", "", candidate)
                values = _pdf_row_values(text, person, expected_days)
                if values is not None:
                    rows[person] = values
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


def build_ics(
    plan: Plan,
    generated_at: Optional[datetime] = None,
    target_person: str = TARGET_PERSON,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Dienstplan {target_person}",
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
        uid = f"{_person_slug(target_person)}-{shift.day:%Y%m%d}@kalender-automation.local"
        summary = f"{definition.code} - {definition.description}"
        details = (
            f"Person: {target_person}; Dienstkürzel: {definition.code}; "
            f"Dienst: {definition.description}; Quelle: {shift.source_name}; "
            f"Planversion: {shift.plan_version}"
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


def select_latest_plan(
    input_dir: Path,
    target_person: str = TARGET_PERSON,
) -> tuple[Path, str, Plan, str]:
    candidates = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".pdf"}
    )
    if not candidates:
        raise FileNotFoundError(f"Keine TXT- oder PDF-Datei in {input_dir} gefunden.")
    parsed: list[tuple[Path, Plan, str, tuple[int, int, int]]] = []
    for path in candidates:
        text = _read_source_text(path)
        plan = parse_plan(path, target_person=target_person, text=text)
        filename_key = _filename_plan_key(path)
        if filename_key is None:
            filename_key = (plan.start.year, plan.start.month, plan.version)
        parsed.append((path, plan, text, filename_key))

    latest_by_month: dict[tuple[int, int], tuple[Path, Plan, str, tuple[int, int, int]]] = {}
    for item in parsed:
        month_key = item[3][:2]
        current = latest_by_month.get(month_key)
        if current is None or item[3][2:] > current[3][2:] or (
            item[3][2:] == current[3][2:] and item[0].stat().st_mtime > current[0].stat().st_mtime
        ):
            latest_by_month[month_key] = item

    shifts_by_day: dict[date, Shift] = {}
    warnings: list[str] = []
    for path, plan, _text, _key in sorted(parsed, key=lambda item: item[3]):
        shifts_by_day.update({shift.day: shift for shift in plan.shifts})
    for _path, plan, _text, _key in sorted(latest_by_month.values(), key=lambda item: item[1].start):
        warnings.extend(plan.warnings)
    selected_path, selected_plan, selected_text, _ = max(
        latest_by_month.values(), key=lambda item: item[3]
    )
    merged_plan = Plan(
        source_name="Mehrere Dienstpläne",
        plan_id=selected_plan.plan_id,
        start=min(plan.start for _path, plan, _text, _key in latest_by_month.values()),
        end=max(plan.end for _path, plan, _text, _key in latest_by_month.values()),
        version=selected_plan.version,
        shifts=tuple(shifts_by_day[day] for day in sorted(shifts_by_day)),
        warnings=tuple(warnings),
    )
    digest = hashlib.sha256(
        b"".join(path.read_bytes() for path, _plan, _text, _key in sorted(latest_by_month.values()))
    ).hexdigest()
    return selected_path, digest, merged_plan, selected_text


def _event_map(ics: str) -> dict[str, str]:
    unfolded = re.sub(r"\r?\n[ \t]", "", ics).replace("\r\n", "\n")
    events = {}
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", unfolded, re.DOTALL):
        uid = re.search(r"(?:^|\n)UID:(.+)", block)
        if uid:
            events[uid.group(1)] = re.sub(r"^DTSTAMP:.*\n", "", block, flags=re.MULTILINE)
    return events


def render_change_report(old_ics: str, new_ics: str) -> str:
    old_events = _event_map(old_ics)
    new_events = _event_map(new_ics)
    added = sorted(set(new_events) - set(old_events))
    removed = sorted(set(old_events) - set(new_events))
    changed = sorted(uid for uid in set(old_events) & set(new_events)
                     if old_events[uid] != new_events[uid])
    lines = [
        f"Neue Termine: {len(added)}",
        f"Geänderte Termine: {len(changed)}",
        f"Entfernte Termine: {len(removed)}",
        f"Unveränderte Termine: {len(set(old_events) & set(new_events)) - len(changed)}",
    ]
    for label, uids in (("NEU", added), ("GEÄNDERT", changed), ("ENTFERNT", removed)):
        for uid in uids:
            lines.append(f"\n{label}: {uid}")
            if label == "GEÄNDERT":
                lines.extend(unified_diff(
                    old_events[uid].splitlines(), new_events[uid].splitlines(),
                    fromfile="alt", tofile="neu", lineterm="",
                ))
    return "\n".join(lines) + "\n"


def _archive_superseded_inputs(input_dir: Path, archive_dir: Path) -> None:
    candidates = [
        path for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".txt", ".pdf"}
        and _filename_plan_key(path) is not None
    ]
    latest: dict[tuple[int, int], Path] = {}
    for path in candidates:
        key = _filename_plan_key(path)
        assert key is not None
        month = key[:2]
        current = latest.get(month)
        if current is None:
            latest[month] = path
            continue
        current_key = _filename_plan_key(current)
        assert current_key is not None
        if key[2] > current_key[2] or (
            key[2] == current_key[2] and path.stat().st_mtime > current.stat().st_mtime
        ):
            latest[month] = path

    superseded = [path for path in candidates if latest[_plan_month(path)] != path]
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in sorted(superseded):
        target = archive_dir / f"{stamp}-{path.name}"
        shutil.copy2(path, target)
        path.unlink()


def _plan_month(path: Path) -> tuple[int, int]:
    key = _filename_plan_key(path)
    assert key is not None
    return key[:2]


def publish_output(root: Path, pages_dir: Path, target_person: str) -> None:
    source = root / "output" / f"dienstplan-{_person_slug(target_person)}.ics"
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


def process_once(
    root: Path,
    pages_dir: Optional[Path] = None,
    target_person: str = TARGET_PERSON,
    dry_run: bool = False,
) -> Plan:
    input_dir = root / "input"
    working_dir = root / "working"
    output_dir = root / "output"
    source, digest, plan, source_text = select_latest_plan(input_dir, target_person)
    output_path = output_dir / f"dienstplan-{_person_slug(target_person)}.ics"
    new_ics = build_ics(plan, target_person=target_person)
    old_ics = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    change_report = render_change_report(old_ics, new_ics)
    if dry_run:
        print(change_report, end="")
        return plan
    working_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    (working_dir / "last-input.sha256").write_text(f"{digest}  {source.name}\n", encoding="utf-8")
    (working_dir / "plan.txt").write_text(source_text, encoding="utf-8")
    (working_dir / "preview.txt").write_text(
        render_preview(plan, target_person), encoding="utf-8"
    )
    (working_dir / "changes.txt").write_text(change_report, encoding="utf-8")
    if old_ics != new_ics and output_path.exists():
        history_dir = working_dir / "history"
        history_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (history_dir / f"{output_path.stem}-{stamp}.ics").write_text(old_ics, encoding="utf-8")
    if old_ics != new_ics:
        output_path.write_text(new_ics, encoding="utf-8")
    _archive_superseded_inputs(input_dir, working_dir / "archive")
    if pages_dir is not None:
        publish_output(root, pages_dir, target_person)
    return plan


def render_preview(plan: Plan, target_person: str = TARGET_PERSON) -> str:
    lines = [
        f"Person: {target_person}",
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


def _shift_label(shift: Optional[Shift]) -> str:
    if shift is None:
        return "kein Dienst"
    definition = shift.definition
    time_info = (
        f"{definition.start:%H:%M}–{definition.end:%H:%M}"
        if definition.is_timed else "ganztägig"
    )
    return f"{definition.code} ({time_info})"


def render_comparison(first: Plan, first_person: str, second: Plan, second_person: str) -> str:
    first_by_day = {shift.day: shift for shift in first.shifts}
    second_by_day = {shift.day: shift for shift in second.shifts}
    days = sorted(set(first_by_day) | set(second_by_day))
    same: list[date] = []
    different: list[date] = []
    only_first: list[date] = []
    only_second: list[date] = []
    for day in days:
        first_shift = first_by_day.get(day)
        second_shift = second_by_day.get(day)
        if first_shift is None:
            only_second.append(day)
        elif second_shift is None:
            only_first.append(day)
        elif _shift_label(first_shift) == _shift_label(second_shift):
            same.append(day)
        else:
            different.append(day)

    lines = [
        f"# Dienstplanvergleich: {first_person} und {second_person}",
        "",
        f"- Zeitraum: {min(first.start, second.start):%d.%m.%Y}–{max(first.end, second.end):%d.%m.%Y}",
        f"- Vergleichte Person 1: {first_person}",
        f"- Vergleichte Person 2: {second_person}",
        "",
        "## Zusammenfassung",
        "",
        f"- Gleicher Dienst: {len(same)}",
        f"- Unterschiedlicher Dienst: {len(different)}",
        f"- Nur bei {first_person}: {len(only_first)}",
        f"- Nur bei {second_person}: {len(only_second)}",
        "",
        "## Tagesübersicht",
        "",
        f"| Datum | {first_person} | {second_person} | Ergebnis |",
        "|---|---|---|---|",
    ]
    for day in days:
        first_label = _shift_label(first_by_day.get(day))
        second_label = _shift_label(second_by_day.get(day))
        if day in same:
            result = "Gleich"
        elif day in only_first:
            result = f"Nur {first_person}"
        elif day in only_second:
            result = f"Nur {second_person}"
        else:
            result = "Unterschiedlich"
        lines.append(f"| {day:%d.%m.%Y} | {first_label} | {second_label} | {result} |")
    return "\n".join(lines) + "\n"


def compare_people(
    root: Path,
    first_person: str,
    second_person: str,
    output_path: Optional[Path] = None,
) -> Path:
    input_dir = root / "input"
    _, _, first_plan, _ = select_latest_plan(input_dir, first_person)
    _, _, second_plan, _ = select_latest_plan(input_dir, second_person)
    target = (root / output_path) if output_path is not None and not output_path.is_absolute() else output_path
    target = target or (
        root / "working" /
        f"vergleich-{_person_slug(first_person)}-{_person_slug(second_person)}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_comparison(first_plan, first_person, second_plan, second_person),
        encoding="utf-8",
    )
    return target


def watch(
    root: Path,
    interval: float,
    pages_dir: Optional[Path] = None,
    target_person: str = TARGET_PERSON,
    stop_event: Optional[Event] = None,
) -> None:
    last_signature: Optional[tuple[tuple[str, int, int], ...]] = None
    while stop_event is None or not stop_event.is_set():
        input_dir = root / "input"
        signature = tuple(
            sorted((path.name, path.stat().st_size, path.stat().st_mtime_ns)
                   for path in input_dir.iterdir()
                   if path.is_file() and path.suffix.lower() in {".txt", ".pdf"})
        ) if input_dir.exists() else ()
        if signature != last_signature:
            try:
                process_once(root, pages_dir, target_person)
                print("Dienstplan verarbeitet.")
                last_signature = signature
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                print(f"Verarbeitung fehlgeschlagen: {error}")
                last_signature = signature
        if stop_event is not None and stop_event.wait(interval):
            break
        if stop_event is None:
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dienstplan für Gruber J. als ICS erzeugen.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--watch", action="store_true", help="input/ dauerhaft überwachen.")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--person", default=TARGET_PERSON, help="Name der Zielperson im Dienstplan.")
    parser.add_argument("--dry-run", action="store_true", help="Nur Änderungen anzeigen, nichts schreiben.")
    parser.add_argument(
        "--compare-person",
        help="Vergleicht --person mit dieser Person und erzeugt eine Markdown-Datei.",
    )
    parser.add_argument(
        "--compare-output",
        type=Path,
        help="Optionaler Pfad für die Vergleichsdatei.",
    )
    parser.add_argument(
        "--publish-dir",
        type=Path,
        help="Lokaler Checkout des GitHub-Pages-Repositories; Änderungen werden gepusht.",
    )
    args = parser.parse_args()
    if args.compare_person:
        if args.watch or args.dry_run or args.publish_dir:
            parser.error("--compare-person kann nicht mit --watch, --dry-run oder --publish-dir verwendet werden.")
        output = compare_people(args.root, args.person, args.compare_person, args.compare_output)
        print(f"Vergleich gespeichert: {output}")
        return
    if args.watch:
        if args.dry_run:
            parser.error("--dry-run kann nicht zusammen mit --watch verwendet werden.")
        watch(args.root, args.interval, args.publish_dir, args.person)
    else:
        plan = process_once(args.root, args.publish_dir, args.person, args.dry_run)
        print(render_preview(plan, args.person))


if __name__ == "__main__":
    main()
