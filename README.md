# Dienstplan-Kalender für Gruber J.

Dieses Projekt liest Dienstplan-Textdateien, übernimmt ausschließlich die Zeile
`Gruber J.` und erzeugt daraus einen abonnierbaren iCalendar-Feed.

## Einrichtung

```sh
cd "/Users/jakobg./Desktop/Kalender Automation/KalenderAutomation"
mkdir -p input working output
cp "/Users/jakobg./Desktop/Kalender Skill/01_ForReview/2610 V2.txt" input/
```

Die Quelldatei wird nicht verändert. Die Ausgabe ist ausschließlich:

```text
output/dienstplan-gruber-j.ics
```

## Einmalige Verarbeitung

```sh
python3 -m src.dienstplan
```

Dabei werden außerdem `working/preview.txt` und `working/last-input.sha256`
erzeugt. Vor dem Veröffentlichen bitte die Vorschau und Warnungen prüfen.

## Automatische Verarbeitung

```sh
python3 -m src.dienstplan --watch --interval 10
```

Bei mehreren Dateien wird die höchste erkannte Planversion verwendet. Bei
gleicher Version gewinnt die zuletzt geänderte Datei. Exakte Duplikate werden
über ihren SHA-256-Hash erkannt; sie ändern das Ergebnis nicht.

## GitHub Pages automatisch aktualisieren

Das Pages-Repository muss einmalig separat geklont und lokal eingerichtet
werden. Es darf keine Quelldateien aus `input/` enthalten. Danach kann der
Watcher bei jeder Änderung die ICS-Datei kopieren, committen und pushen:

```sh
python3 -m src.dienstplan --watch --interval 10 \
  --publish-dir "/Pfad/zum/lokal-geklonten-pages-repository"
```

Der Push verwendet die normale lokale Git-Authentifizierung (SSH-Key,
Credential Helper oder GitHub CLI). Zugangsdaten stehen nicht im Projekt.
Die veröffentlichte URL ist anschließend beispielsweise:
`https://BENUTZER.github.io/REPOSITORY/dienstplan-gruber-j.ics`

## Sonderkürzel

`.`, `U`, `X`, `XR` und `K` werden nicht exportiert. `A` und `SEF` werden als
ganztägige Hinweise mit dem Zusatz „Dauer: 8 Stunden; Beginn laut Plan
unbekannt“ ausgegeben. Für alle anderen Dienste werden Beginn und Ende nur aus
der Legende der Quelldatei gelesen.

Bei Tour-/Fahrzeugkürzeln werden zusätzlich die Personen ermittelt, die am
selben Datum denselben Tourstamm verwenden. Beispielsweise gehören `B1B`,
`B1T` und `B1F` zur gemeinsamen Besatzung der Tour B1. Die Namen und
Kürzel dieser Besatzungsmitglieder werden in die jeweilige
Terminbeschreibung geschrieben. Für nicht zuordenbare Sonderkürzel wird
`keine weiteren erkannt` angegeben.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## Veröffentlichung

Der lokale Prozess veröffentlicht absichtlich nichts automatisch. Die Datei
`output/dienstplan-gruber-j.ics` kann nach Prüfung in ein separates GitHub-Pages-
Repository kopiert oder per GitHub Actions/Upload veröffentlicht werden. Die
Quelldateien aus `input/` dürfen nicht in dieses öffentliche Repository gelangen.
