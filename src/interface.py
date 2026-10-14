"""Grafische Oberfläche für die Dienstplan-Verarbeitung."""

from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .dienstplan import (
    TARGET_PERSON,
    compare_people,
    process_once,
    render_preview,
    watch,
)


class DienstplanApp:
    def __init__(self, root: tk.Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root
        self.publish_dir = tk.StringVar()
        self.person = tk.StringVar(value=TARGET_PERSON)
        self.compare_person = tk.StringVar()
        self.compare_output = tk.StringVar()
        self.interval = tk.StringVar(value="10")
        self.status = tk.StringVar(value="Bereit")
        self._messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None

        self.root.title("Dienstplan-Kalender")
        self.root.minsize(760, 560)
        self._build()
        self.root.after(100, self._drain_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(6, weight=1)

        ttk.Label(main, text="Dienstplan-Kalender", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(main, text="Zielperson").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(main, textvariable=self.person).grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)

        action_frame = ttk.LabelFrame(main, text="Verarbeitung", padding=10)
        action_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)
        for column in range(3):
            action_frame.columnconfigure(column, weight=1)
        ttk.Button(action_frame, text="Dienstplan verarbeiten", command=self._process).grid(
            row=0, column=0, sticky="ew", padx=4, pady=4
        )
        ttk.Button(action_frame, text="Nur Vorschau (Dry-Run)", command=self._dry_run).grid(
            row=0, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Button(action_frame, text="Dateien in input/ öffnen", command=self._choose_input_files).grid(
            row=0, column=2, sticky="ew", padx=4, pady=4
        )

        compare_frame = ttk.LabelFrame(main, text="Zwei Personen vergleichen", padding=10)
        compare_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        compare_frame.columnconfigure(1, weight=1)
        ttk.Label(compare_frame, text="Vergleichsperson").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(compare_frame, textvariable=self.compare_person).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(compare_frame, text="Ausgabedatei (optional)").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(compare_frame, textvariable=self.compare_output).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(compare_frame, text="Pfad wählen", command=self._choose_compare_output).grid(row=1, column=2, padx=4)
        ttk.Button(compare_frame, text="Vergleich erstellen", command=self._compare).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

        publish_frame = ttk.LabelFrame(main, text="Veröffentlichen und überwachen", padding=10)
        publish_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        publish_frame.columnconfigure(1, weight=1)
        ttk.Label(publish_frame, text="GitHub-Pages-Ordner").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(publish_frame, textvariable=self.publish_dir).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(publish_frame, text="Ordner wählen", command=self._choose_publish_dir).grid(row=0, column=2, padx=4)
        ttk.Label(publish_frame, text="Intervall (Sekunden)").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(publish_frame, textvariable=self.interval, width=10).grid(row=1, column=1, sticky="w", pady=4)
        self.watch_button = ttk.Button(publish_frame, text="Watch starten", command=self._toggle_watch)
        self.watch_button.grid(row=1, column=2, padx=4, pady=4)

        ttk.Label(main, textvariable=self.status, foreground="#555").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4, 6)
        )
        self.output = tk.Text(main, height=12, wrap="word", state="disabled")
        self.output.grid(row=6, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(main, orient="vertical", command=self.output.yview)
        scrollbar.grid(row=6, column=3, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)

    def _write(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def _selected_publish_dir(self) -> Path | None:
        value = self.publish_dir.get().strip()
        return Path(value) if value else None

    def _process(self, dry_run: bool = False) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            messagebox.showinfo("Watch-Modus", "Beende zuerst den Watch-Modus.")
            return
        self.status.set("Verarbeitung läuft ...")
        try:
            plan = process_once(
                self.project_root,
                pages_dir=self._selected_publish_dir(),
                target_person=self.person.get().strip() or TARGET_PERSON,
                dry_run=dry_run,
            )
            self._write(render_preview(plan, self.person.get().strip() or TARGET_PERSON))
            self.status.set("Dry-Run abgeschlossen." if dry_run else "Verarbeitung abgeschlossen.")
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
            self.status.set("Verarbeitung fehlgeschlagen.")
            messagebox.showerror("Fehler", str(error))

    def _dry_run(self) -> None:
        self._process(dry_run=True)

    def _compare(self) -> None:
        second = self.compare_person.get().strip()
        if not second:
            messagebox.showwarning("Angabe fehlt", "Bitte eine Vergleichsperson eingeben.")
            return
        try:
            output = compare_people(
                self.project_root,
                self.person.get().strip() or TARGET_PERSON,
                second,
                Path(self.compare_output.get().strip()) if self.compare_output.get().strip() else None,
            )
            self._write(output.read_text(encoding="utf-8"))
            self.status.set(f"Vergleich gespeichert: {output}")
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
            self.status.set("Vergleich fehlgeschlagen.")
            messagebox.showerror("Fehler", str(error))

    def _choose_input_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Dienstplan-Dateien auswählen",
            filetypes=[("Dienstpläne", "*.pdf *.txt"), ("PDF", "*.pdf"), ("Text", "*.txt")],
        )
        if not paths:
            return
        input_dir = self.project_root / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        for selected in paths:
            shutil.copy2(selected, input_dir / Path(selected).name)
        self.status.set(f"{len(paths)} Datei(en) nach input/ kopiert.")

    def _choose_compare_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Vergleich speichern",
            initialdir=self.project_root / "working",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
        )
        if path:
            self.compare_output.set(path)

    def _choose_publish_dir(self) -> None:
        path = filedialog.askdirectory(title="Lokales GitHub-Pages-Repository auswählen")
        if path:
            self.publish_dir.set(path)

    def _toggle_watch(self) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_stop.set()
            self.watch_button.configure(text="Watch wird beendet ...", state="disabled")
            return
        try:
            interval = float(self.interval.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ungültiges Intervall", "Das Intervall muss eine positive Zahl sein.")
            return
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(
            target=self._run_watch,
            args=(interval, self._selected_publish_dir(), self.person.get().strip() or TARGET_PERSON),
            daemon=True,
        )
        self._watch_thread.start()
        self.watch_button.configure(text="Watch stoppen")
        self.status.set("Watch-Modus läuft.")

    def _run_watch(self, interval: float, publish_dir: Path | None, person: str) -> None:
        try:
            watch(self.project_root, interval, publish_dir, person, stop_event=self._watch_stop)
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
            self._messages.put(("error", str(error)))
        finally:
            self._messages.put(("watch-stopped", "Watch-Modus beendet."))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, text = self._messages.get_nowait()
                if kind == "error":
                    messagebox.showerror("Watch-Fehler", text)
                self.status.set(text)
                self.watch_button.configure(text="Watch starten", state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def _close(self) -> None:
        self._watch_stop.set()
        self.root.destroy()


def launch(project_root: Path | None = None) -> None:
    root = tk.Tk()
    DienstplanApp(root, project_root or Path(__file__).resolve().parents[1])
    root.mainloop()


if __name__ == "__main__":
    launch()
