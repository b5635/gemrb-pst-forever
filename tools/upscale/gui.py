"""Desktop window for leftover / stale upscale counts and for running the pipeline."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

import status as up_status

HERE = Path(__file__).resolve().parent


class App:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("PST art upscaler")
        self.root.minsize(860, 700)
        self.root.geometry("980x820")
        self.queue: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.busy = False
        self.report: up_status.Report | None = None
        self.scale = IntVar(value=2)
        self.fp16 = BooleanVar(value=True)
        self.limit = IntVar(value=0)
        self.only = StringVar(value="")
        self.game = StringVar(value=str(up_status.DEFAULT_GAME))
        self.out = StringVar(value=str(up_status.DEFAULT_OUT))
        self.want = {name: BooleanVar(value=True) for name in up_status.CATEGORIES}
        self.list_cat = StringVar(value="sprites")
        self.hint = StringVar(value="Counting files on disk...")
        self.gpu_label = "checking GPU..."
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(80, self._poll)
        self.root.after(200, lambda: self._scan(hash_sources=False, reclassify=False, query_gpu=False))
        self.root.after(800, self._check_gpu)

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        title_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=10)
        small_font = tkfont.Font(family="Segoe UI", size=9)
        banner_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(5, weight=1)

        head = ttk.Frame(root)
        head.grid(row=0, column=0, sticky="ew", **pad)
        ttk.Label(head, text="PST art upscaler", font=title_font).pack(anchor="w")
        ttk.Label(
            head,
            text=(
                "Sharper menus, maps, and creatures for the GemRB build. "
                "The game still uses the original sizes for clicks and scripts."
            ),
            font=body_font,
            wraplength=920,
        ).pack(anchor="w", pady=(2, 6))
        steps = ttk.LabelFrame(head, text="What to click")
        steps.pack(fill="x")
        ttk.Label(
            steps,
            text=(
                "1. Read the green box. That is the one thing to do next.\n"
                "2. Click the big button in that box. Finished files are skipped, so this is safe to stop and start again.\n"
                "3. Watch the log at the bottom. Use Stop if you need the GPU for something else.\n"
                "4. When it finishes, the numbers refresh. Repeat until Left is 0.\n\n"
                "Left = never upscaled.  Incomplete = the last run died halfway.  "
                "Stale = the original file or the model changed, so the PNG should be redone."
            ),
            font=small_font,
            justify="left",
        ).pack(anchor="w", padx=8, pady=6)

        self.banner = ttk.Frame(root, style="Banner.TFrame")
        self.banner.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.banner.columnconfigure(0, weight=1)
        self.banner_title = ttk.Label(self.banner, text="Counting...", font=banner_font)
        self.banner_title.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        self.banner_body = ttk.Label(self.banner, text="", font=body_font, wraplength=760, justify="left")
        self.banner_body.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        self.banner_btn = ttk.Button(self.banner, text="Please wait", command=self._do_recommended)
        self.banner_btn.grid(row=0, column=1, rowspan=2, padx=8, pady=8, sticky="e")

        table_fr = ttk.LabelFrame(root, text="How many")
        table_fr.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        cols = ("what", "total", "done", "left", "stale", "incomplete")
        self.table = ttk.Treeview(table_fr, columns=cols, show="headings", height=4, selectmode="browse")
        headings = {
            "what": "What it is",
            "total": "Total",
            "done": "Done",
            "left": "Left",
            "stale": "Stale",
            "incomplete": "Incomplete",
        }
        widths = {"what": 280, "total": 80, "done": 80, "left": 80, "stale": 80, "incomplete": 100}
        for key, label in headings.items():
            self.table.heading(key, text=label)
            self.table.column(key, width=widths[key], anchor="center" if key != "what" else "w")
        self.table.pack(fill="x", padx=6, pady=6)

        mid = ttk.Frame(root)
        mid.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        check_fr = ttk.LabelFrame(mid, text="What's left to do")
        check_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.check_box = ttk.Frame(check_fr)
        self.check_box.pack(fill="both", expand=True, padx=8, pady=6)

        right = ttk.LabelFrame(mid, text="Names still waiting (select a row, then Open list)")
        right.grid(row=0, column=1, sticky="nsew")
        pick = ttk.Frame(right)
        pick.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(pick, text="Show:").pack(side="left")
        combo = ttk.Combobox(
            pick,
            textvariable=self.list_cat,
            values=("sprites", "gui", "areas"),
            width=10,
            state="readonly",
        )
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._fill_names())
        ttk.Button(pick, text="Open leftover list", command=self._open_leftover).pack(side="left", padx=4)
        ttk.Button(pick, text="Open stale list", command=self._open_stale).pack(side="left")
        list_fr = ttk.Frame(right)
        list_fr.pack(fill="both", expand=True, padx=6, pady=6)
        self.names = ttk.Treeview(list_fr, columns=("name", "why"), show="headings", height=8)
        self.names.heading("name", text="Resource")
        self.names.heading("why", text="Why")
        self.names.column("name", width=140)
        self.names.column("why", width=140)
        scroll = ttk.Scrollbar(list_fr, orient="vertical", command=self.names.yview)
        self.names.configure(yscrollcommand=scroll.set)
        self.names.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        run = ttk.LabelFrame(root, text="If you want to do something else")
        run.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        cats = ttk.Frame(run)
        cats.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(cats, text="Categories:").pack(side="left")
        ttk.Checkbutton(cats, text="GUI", variable=self.want["gui"]).pack(side="left", padx=8)
        ttk.Checkbutton(cats, text="Maps", variable=self.want["areas"]).pack(side="left", padx=8)
        ttk.Checkbutton(cats, text="Sprites", variable=self.want["sprites"]).pack(side="left", padx=8)
        ttk.Checkbutton(cats, text="Use fp16 (faster on this GPU)", variable=self.fp16).pack(side="left", padx=16)
        ttk.Label(cats, text="Stop after N files (0 = all):").pack(side="left")
        ttk.Spinbox(cats, from_=0, to=5000, textvariable=self.limit, width=6).pack(side="left", padx=4)

        names_row = ttk.Frame(run)
        names_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(names_row, text="Only these names (optional, comma-separated):").pack(side="left")
        ttk.Entry(names_row, textvariable=self.only).pack(side="left", fill="x", expand=True, padx=6)

        paths = ttk.Frame(run)
        paths.pack(fill="x", padx=8, pady=2)
        ttk.Label(paths, text="Game:").pack(side="left")
        ttk.Entry(paths, textvariable=self.game, width=48).pack(side="left", padx=4)
        ttk.Button(paths, text="Browse", command=self._pick_game).pack(side="left")
        ttk.Label(paths, text="Output:").pack(side="left", padx=(12, 0))
        ttk.Entry(paths, textvariable=self.out, width=32).pack(side="left", padx=4)
        ttk.Button(paths, text="Browse", command=self._pick_out).pack(side="left")

        btns = ttk.Frame(run)
        btns.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Label(btns, text="Count:").pack(side="left")
        ttk.Button(btns, text="Refresh counts", command=lambda: self._scan(False, False, False)).pack(side="left", padx=4)
        ttk.Button(btns, text="Scan the game files", command=lambda: self._scan(False, True, False)).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Check for stale art", command=lambda: self._scan(True, False, False)).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Set up GPU environment", command=self._setup).pack(side="left", padx=4)
        run_row = ttk.Frame(run)
        run_row.pack(fill="x", padx=8, pady=2)
        ttk.Label(run_row, text="Run:").pack(side="left")
        ttk.Button(run_row, text="Continue checked", command=lambda: self._run("continue")).pack(side="left", padx=4)
        ttk.Button(run_row, text="Redo stale in checked", command=lambda: self._run("stale")).pack(side="left", padx=4)
        ttk.Button(run_row, text="Regenerate checked", command=lambda: self._run("force")).pack(side="left", padx=4)
        ttk.Button(run_row, text="Stop", command=self._stop).pack(side="left", padx=4)
        open_row = ttk.Frame(run)
        open_row.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(open_row, text="Open:").pack(side="left")
        ttk.Button(open_row, text="Open upscaled folder", command=self._open_out).pack(side="left", padx=4)
        ttk.Button(open_row, text="Open error log", command=self._open_errors).pack(side="left", padx=4)

        log_fr = ttk.LabelFrame(root, text="Log")
        log_fr.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 4))
        self.log = ScrolledText(log_fr, height=10, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        foot = ttk.Frame(root)
        foot.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 8))
        ttk.Label(foot, textvariable=self.hint, font=small_font).pack(side="left")
        ttk.Sizegrip(foot).pack(side="right")

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        if not text.endswith("\n"):
            self.log.insert("end", "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.banner_btn.state(["disabled"])
        elif self.report and self.report.next.button:
            self.banner_btn.state(["!disabled"])

    def _scan(self, hash_sources: bool, reclassify: bool, query_gpu: bool) -> None:
        if self.busy:
            messagebox.showinfo("Busy", "Wait for the current job to finish, or click Stop.")
            return
        self._set_busy(True)
        self.hint.set("Working...")
        if hash_sources:
            self._append("Comparing each finished file to the original in the game. This can take a few minutes.")
        elif reclassify:
            self._append("Scanning CHITIN.KEY and classifying every TIS, MOS, and BAM.")
        else:
            self._append("Counting leftover / done files on disk.")

        def work() -> None:
            try:
                report = up_status.scan(
                    out=Path(self.out.get()),
                    game=Path(self.game.get()),
                    scale=int(self.scale.get() or 2),
                    fp16=bool(self.fp16.get()),
                    hash_sources=hash_sources,
                    reclassify=reclassify,
                    query_gpu=query_gpu,
                    progress=lambda msg: self.queue.put(("hint", msg)),
                )
                up_status.write_name_lists(report)
                self.queue.put(("report", report))
            except Exception as exc:
                self.queue.put(("fail", f"{exc}\n{traceback.format_exc()}"))

        threading.Thread(target=work, daemon=True).start()

    def _check_gpu(self) -> None:
        def work() -> None:
            label = up_status._gpu_label(up_status.venv_python())
            self.queue.put(("gpu", label))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, report: up_status.Report) -> None:
        if self.gpu_label and not self.gpu_label.startswith("checking"):
            report.gpu = self.gpu_label
        self.report = report
        nxt = report.next
        self.banner_title.configure(text=nxt.title)
        self.banner_body.configure(text=nxt.body)
        if nxt.button and not self.busy:
            self.banner_btn.configure(text=nxt.button, state="normal")
        else:
            self.banner_btn.configure(text="Nothing to click", state="disabled")
        for row in self.table.get_children():
            self.table.delete(row)
        pretty = {"gui": "GUI", "areas": "Maps", "sprites": "Sprites"}
        for name in up_status.CATEGORIES:
            bucket = report.categories[name]
            stale = f"{bucket.stale:,}" if report.hashed or bucket.stale else "not checked"
            self.table.insert(
                "",
                "end",
                iid=name,
                values=(
                    f"{pretty[name]} - {up_status.CATEGORY_BLURB[name]}",
                    f"{bucket.total:,}",
                    f"{bucket.done:,}",
                    f"{bucket.leftover:,}",
                    stale,
                    f"{bucket.incomplete:,}",
                ),
            )
        for child in self.check_box.winfo_children():
            child.destroy()
        marks = {"done": "✓", "todo": "○", "later": "·"}
        for state, title, detail in report.checklist:
            ttk.Label(
                self.check_box,
                text=f"{marks[state]}  {title}\n      {detail}",
                justify="left",
            ).pack(anchor="w", pady=2)
        leftover_cat = next((name for name in ("sprites", "gui", "areas") if report.categories[name].leftover), "sprites")
        self.list_cat.set(leftover_cat)
        self._fill_names()
        bits = [
            report.gpu,
            f"output {up_status.format_bytes(report.bytes)}",
        ]
        if report.error_count:
            bits.append(f"{report.error_count} errors in work\\errors.log")
        if report.tmp_count:
            bits.append(f"{report.tmp_count} leftover .tmp files")
        self.hint.set("  ·  ".join(bits))
        self._append(up_status.format_report(report))
        if nxt.categories:
            for name, var in self.want.items():
                var.set(name in nxt.categories)

    def _fill_names(self) -> None:
        for row in self.names.get_children():
            self.names.delete(row)
        if not self.report:
            return
        bucket = self.report.categories.get(self.list_cat.get())
        if not bucket:
            return
        rows = [(name, "left") for name in bucket.leftover_names]
        rows += [(name, "stale") for name in bucket.stale_names]
        rows += [(name, "incomplete") for name in bucket.incomplete_names]
        for name, why in rows[:4000]:
            self.names.insert("", "end", values=(name, why))

    def _do_recommended(self) -> None:
        if not self.report:
            return
        action = self.report.next.action
        if action == "setup":
            self._setup()
        elif action == "scan":
            self._scan(False, True, False)
        elif action == "hash":
            self._scan(True, False, False)
        elif action in ("continue", "stale"):
            self._run(action, categories=self.report.next.categories)
        elif action == "none":
            messagebox.showinfo("Caught up", self.report.next.body)

    def _selected_categories(self, override: list[str] | None) -> list[str]:
        if override:
            return override
        names = [name for name, var in self.want.items() if var.get()]
        if not names:
            messagebox.showinfo("Pick a category", "Check GUI, Maps, and/or Sprites first.")
        return names

    def _run(self, mode: str, categories: list[str] | None = None) -> None:
        if self.busy:
            messagebox.showinfo("Busy", "Wait for the current job to finish, or click Stop.")
            return
        cats = self._selected_categories(categories)
        if not cats:
            return
        if mode == "force":
            label = up_status._join_cats(cats)
            if not messagebox.askyesno(
                "Regenerate from scratch?",
                f"This redoes every file in {label}, even the ones that are already done.\n\n"
                "GUI and maps took hours last time. Sprites will too.\n\n"
                "Use Continue if you only want the leftover files.",
            ):
                return
        py = up_status.venv_python()
        if py is None:
            messagebox.showerror(
                "No GPU environment",
                'Click "Set up the GPU environment" first (once).',
            )
            return
        argv = [
            str(py),
            "-u",
            str(HERE / "upscale.py"),
            "--categories",
            ",".join(cats),
            "--mode",
            mode,
            "--scale",
            str(int(self.scale.get() or 2)),
            "--game",
            self.game.get(),
            "--out",
            self.out.get(),
        ]
        if self.fp16.get():
            argv.append("--fp16")
        limit = int(self.limit.get() or 0)
        if limit:
            argv += ["--limit", str(limit)]
        only = self.only.get().strip()
        if only:
            argv += ["--only", only]
        self._start_proc(argv, f"Running {mode} on {', '.join(cats)}...")

    def _setup(self) -> None:
        if self.busy:
            return
        bat = HERE / "setup_env.bat"
        if not bat.is_file():
            messagebox.showerror("Missing", str(bat))
            return
        argv = ["cmd", "/c", str(bat)]
        self._start_proc(argv, "Installing the GPU environment. This takes a few minutes the first time.")

    def _start_proc(self, argv: list[str], headline: str) -> None:
        self._set_busy(True)
        self.hint.set(headline)
        self._append(headline)
        self._append("> " + subprocess.list2cmdline(argv))
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self.proc = subprocess.Popen(
                argv,
                cwd=str(HERE),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as exc:
            self._set_busy(False)
            messagebox.showerror("Could not start", str(exc))
            return

        def reader() -> None:
            assert self.proc is not None
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.queue.put(("log", line.rstrip("\n")))
            code = self.proc.wait()
            self.queue.put(("done", code))

        threading.Thread(target=reader, daemon=True).start()

    def _stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self._append("Stopping... finished files are kept; leftover stay leftover.")
            self.proc.terminate()
        else:
            messagebox.showinfo("Nothing running", "There is no upscale job to stop.")

    def _poll(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "hint":
                self.hint.set(str(payload))
            elif kind == "log":
                self._append(str(payload))
            elif kind == "report":
                self._set_busy(False)
                self._apply(payload)
            elif kind == "gpu":
                self.gpu_label = str(payload)
                if self.report:
                    self.report.gpu = self.gpu_label
                    current = self.hint.get()
                    if "  ·  " in current:
                        parts = current.split("  ·  ")
                        parts[0] = self.gpu_label
                        self.hint.set("  ·  ".join(parts))
            elif kind == "fail":
                self._set_busy(False)
                self.hint.set("Failed")
                self._append(str(payload))
                messagebox.showerror("Scan failed", str(payload)[:800])
            elif kind == "done":
                self.proc = None
                code = int(payload)
                self._append(f"Finished with exit code {code}.")
                self._set_busy(False)
                if code == 0:
                    self._scan(False, False, False)
                else:
                    self.hint.set(f"Job ended with exit code {code}. See the log.")
        self.root.after(120, self._poll)

    def _pick_game(self) -> None:
        path = filedialog.askdirectory(title="Planescape: Torment folder (has CHITIN.KEY)")
        if path:
            self.game.set(path)

    def _pick_out(self) -> None:
        path = filedialog.askdirectory(title="Upscaled output folder")
        if path:
            self.out.set(path)

    def _open_out(self) -> None:
        path = Path(self.out.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def _open_errors(self) -> None:
        path = up_status.ERRORS_PATH
        if not path.is_file():
            messagebox.showinfo("No error log", "work\\errors.log is only created when a file fails.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def _open_leftover(self) -> None:
        self._open_work_list(f"leftover-{self.list_cat.get()}.txt")

    def _open_stale(self) -> None:
        self._open_work_list(f"stale-{self.list_cat.get()}.txt")

    def _open_work_list(self, name: str) -> None:
        path = up_status.WORK / name
        if not path.is_file() or path.stat().st_size == 0:
            messagebox.showinfo("Empty", f"{name} has no names right now.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def _close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Stop and close?", "An upscale job is still running. Stop it and close?"):
                return
            self.proc.terminate()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        App().run()
    except Exception:
        messagebox.showerror("PST art upscaler", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
