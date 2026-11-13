# Dienstplan-Kalender

Dieses Projekt liest Dienstplan-PDFs oder -Textdateien aus `input/` und erzeugt
eine abonnierbare iCalendar-Datei für eine Person. Die zu verarbeitenden Personen werden standardmäßig in `input/personen.json`
festgelegt.

## 1. Terminal öffnen

In VS Code:

1. Öffne das Menü **Terminal → Neues Terminal**.
2. Im Terminal siehst du eine Eingabezeile, zum Beispiel:

   ```text
   user@computer:~$
   ```

3. Befehle werden hinter dem `$` eingegeben und mit **Enter** ausgeführt.
4. Die Zeichen ``` ``` gehören nicht zum Befehl und dürfen nicht mitkopiert
   werden.

Wechsle zuerst in den Projektordner:

```sh
cd /workspaces/KalenderAutomation
```

Prüfe optional, ob du im richtigen Ordner bist:

```sh
pwd
ls
```

In der Liste sollte unter anderem `README.md`, `input`, `src` und `output`
stehen. Mit `Ctrl+C` kann ein laufender Befehl, insbesondere der Watch-Modus,
beendet werden.

## 2. Einmalige Einrichtung

Lege die Ordner an und installiere die benötigte PDF-Bibliothek:

```sh
mkdir -p input working output
python3 -m pip install -r requirements.txt
```

Kopiere danach deine Dienstplan-PDFs in den Ordner `input/`. Das geht im
VS-Code-Explorer per Drag-and-drop oder im Terminal, zum Beispiel:

```sh
cp "/pfad/zu/2610 V2.pdf" input/
```

Die Anführungszeichen sind bei Dateinamen mit Leerzeichen erforderlich.

## 3. Dateinamen und mehrere Monate

Empfohlen wird das Format:

```text
JJMM Vn.pdf
```

Beispiel:

```text
2610 V2.pdf
```

Bedeutung:

- `26`: Jahr 2026
- `10`: Oktober
- `V2`: Version 2

Mehrere Monatspläne dürfen gleichzeitig in `input/` liegen:

```text
input/
├── 2610 V2.pdf
├── 2611 V1.pdf
└── 2612 V1.pdf
```

Pro Monat wird die höchste Version verwendet. Bei gleicher Version gewinnt die
zuletzt geänderte Datei. Nach einer erfolgreichen normalen Verarbeitung werden
ältere Versionen nach `working/archive/` kopiert und aus `input/` entfernt.
Die aktuellste Version jedes Monats bleibt in `input/`.

Dateien, die nicht dem Format `JJMM Vn.pdf` oder `JJMM Vn.txt` entsprechen,
werden nicht automatisch entfernt.

## 4. Dienstplan einmalig verarbeiten

Führe im Projektordner aus:

```sh
python3 -m src.dienstplan
```

Danach findest du die Kalenderdatei hier:

```text
output/dienstplan-gruber-j.ics
```

Zusätzliche Dateien und Ordner:

```text
working/preview.txt       erkannte Termine und Warnungen
working/changes.txt       neue, geänderte und entfernte Termine
working/last-input.sha256 Hash der verwendeten Monatsdateien
working/archive/          ältere Eingabeversionen
working/history/          Backups früherer ICS-Dateien
working/plan.txt          extrahierter Text der zuletzt ausgewählten Quelle
```

Die PDF-Dateien in `input/` werden nicht verändert, außer dass ältere Versionen
nach erfolgreicher Verarbeitung archiviert und dort entfernt werden.

### Zielpersonen festlegen

Lege im Ordner `input/` die Datei `personen.json` an. Die Namen müssen exakt
so geschrieben sein wie im Dienstplan:

```json
{
  "personen": [
    "Gruber J.",
    "Muster M."
  ]
}
```

Für jede Person wird eine eigene Datei erzeugt, zum Beispiel
`output/dienstplan-gruber-j.ics`. Großschreibung, Leerzeichen und Punkte werden
für den Dateinamen automatisch normalisiert. Umlaute werden ersetzt, zum
Beispiel `Müller Ä.` durch `mueller-a`. Wird keine `personen.json` gefunden,
wird weiterhin nur `Gruber J.` verarbeitet. Mit `--person "Name"` kann die
JSON-Datei für einen einzelnen Lauf überschrieben werden.

## 4a. Grafische Oberfläche

Alle Befehle können auch über eine grafische Oberfläche ausgeführt werden:

```sh
python3 -m src.interface
```

Über die Oberfläche kannst du Dienstplan-Dateien auswählen und nach `input/`
kopieren, einen Dienstplan normal oder als Dry-Run verarbeiten, zwei Personen
vergleichen, den Watch-Modus starten oder stoppen und optional in ein lokales
GitHub-Pages-Repository veröffentlichen. Das Fenster bleibt während des
Watch-Modus bedienbar.

## 5. Änderungen zuerst nur anzeigen (`--dry-run`)

Mit `--dry-run` kannst du prüfen, was passieren würde:

```sh
python3 -m src.dienstplan --dry-run
```

Der Befehl zeigt eine Statistik an, schreibt aber keine ICS-Datei, keine
Backups und kein Archiv. Er verändert also nichts.

## 6. Andere Zielperson verarbeiten

Standardmäßig wird `Gruber J.` gesucht. Für eine andere Person:

```sh
python3 -m src.dienstplan --person "Muster M."
```

Die Datei wird dann beispielsweise hier erzeugt:

```text
output/dienstplan-muster-m.ics
```

Der Name muss genau so geschrieben werden, wie er im Dienstplan vorkommt.

## 7. Zwei Dienstpläne vergleichen

Mit diesem Befehl vergleichst du `Gruber J.` mit `Muster M.`:

```sh
python3 -m src.dienstplan \
  --person "Gruber J." \
  --compare-person "Muster M." \
  --compare-output "working/vergleich-gruber-muster.md"
```

Wichtig bei mehreren Zeilen: Der Backslash `\` muss jeweils das letzte Zeichen
der Zeile sein. Danach darf kein Leerzeichen mehr folgen. Du kannst den Befehl
auch sicher in einer einzigen Zeile ausführen:

```sh
python3 -m src.dienstplan --person "Gruber J." --compare-person "Muster M." --compare-output "working/vergleich-gruber-muster.md"
```

Das Ergebnis wird als Markdown-Datei gespeichert:

```text
working/vergleich-gruber-muster.md
```

Die Datei enthält:

- eine Zusammenfassung
- gleiche Dienste
- unterschiedliche Dienste
- Dienste, die nur bei einer Person vorkommen
- eine Tagesübersicht mit Datum, Dienst und Uhrzeit

Wenn du die erste Person nicht angeben möchtest, wird automatisch `Gruber J.`
verwendet:

```sh
python3 -m src.dienstplan --compare-person "Muster M."
```

## 8. Automatische Verarbeitung mit Watch-Modus

Der Watch-Modus prüft den `input/`-Ordner regelmäßig auf neue oder geänderte
Dateien:

```sh
python3 -m src.dienstplan --watch --interval 10
```

`10` bedeutet, dass alle zehn Sekunden geprüft wird. Wenn eine neue PDF in
`input/` kopiert wird, wird der Kalender automatisch aktualisiert.

Beenden kannst du den Watch-Modus mit:

```text
Ctrl+C
```

Für eine andere Person:

```sh
python3 -m src.dienstplan --watch --interval 10 --person "Muster M."
```

`--dry-run` und `--compare-person` werden nicht zusammen mit `--watch`
verwendet.

## 9. GitHub Pages veröffentlichen

Wenn ein lokales GitHub-Pages-Repository eingerichtet ist, kann die aktualisierte
ICS-Datei dorthin kopiert und per Git veröffentlicht werden:

```sh
python3 -m src.dienstplan \
  --watch \
  --interval 10 \
  --publish-dir "/pfad/zum/lokal-geklonten-pages-repository"
```

Der Push verwendet deine lokale Git-Authentifizierung. Zugangsdaten werden
nicht im Projekt gespeichert. Die Quelldateien aus `input/` dürfen nicht in
das öffentliche Pages-Repository kopiert werden.

## 10. Kalender abonnieren

Veröffentliche die ICS-Dateien zuerst über GitHub Pages oder einen anderen
Webserver. Kopiere danach den **HTTPS-Link** der jeweiligen Datei, zum Beispiel
`https://example.github.io/dienstplan-gruber-j.ics`. Verwende die URL des
Kalenders, nicht den Link zum Bearbeiten oder Herunterladen einer lokalen Datei.

### Google Kalender

1. Öffne [Google Kalender](https://calendar.google.com) im Browser.
2. Klicke neben **Weitere Kalender** auf **+** und wähle **Per URL**.
3. Füge den HTTPS-Link ein und klicke auf **Kalender hinzufügen**.

### Outlook / Microsoft 365

1. Öffne Outlook im Browser und gehe zu **Kalender**.
2. Wähle **Kalender hinzufügen** → **Aus dem Internet abonnieren**.
3. Füge den HTTPS-Link ein, vergebe einen Namen und bestätige.

### Apple Kalender

1. Öffne Kalender auf dem Mac.
2. Wähle **Ablage** → **Neues Kalenderabonnement**.
3. Füge den HTTPS-Link ein und bestätige. Auf iPhone oder iPad kann der Link
   über Safari geöffnet und als Kalenderabonnement hinzugefügt werden.

### Thunderbird

1. Öffne die Kalenderansicht und wähle **Datei** → **Neu** → **Kalender**.
2. Wähle **Im Netzwerk** und als Format **iCalendar (ICS)**.
3. Füge den HTTPS-Link ein und speichere den Kalender.

Ein Kalenderabonnement wird regelmäßig vom jeweiligen Kalenderdienst
aktualisiert. Der genaue Aktualisierungszeitpunkt kann nicht vom Projekt
erzwungen werden. Änderungen erscheinen daher möglicherweise erst nach einiger
Zeit.

## 11. Typische Fehler

### `unrecognized arguments`

Bei einem mehrzeiligen Befehl steht wahrscheinlich ein Leerzeichen nach `\`.
Verwende entweder eine einzelne Zeile oder achte darauf, dass `\` direkt vor
dem Zeilenumbruch steht.

### `Person '...' wurde nicht gefunden`

Prüfe die Schreibweise des Namens. Sie muss mit dem Namen im PDF
übereinstimmen. Außerdem muss die Person im Dienstplan enthalten sein.

### Keine PDF-Verarbeitung möglich

Installiere die Abhängigkeiten erneut:

```sh
python3 -m pip install -r requirements.txt
```

Eine eingescannte PDF enthält möglicherweise keinen auslesbaren Text und
benötigt zuerst OCR.

### Keine TXT- oder PDF-Datei gefunden

Prüfe, ob du im Projektordner bist und ob eine Datei in `input/` liegt:

```sh
pwd
ls input
```

## 12. Tests ausführen

```sh
python3 -m unittest discover -s tests -v
```

## Sonderkürzel

`.`, `U`, `X`, `XR` und `K` werden nicht exportiert. `A` und `SEF` werden als
ganztägige Hinweise mit dem Zusatz „Dauer: 8 Stunden; Beginn laut Plan
unbekannt“ ausgegeben. Für andere Dienste werden Beginn und Ende aus der
Legende der Quelldatei gelesen.
