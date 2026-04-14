"""
tab_batch.py  ─  Batch Processor
Apply the same FFmpeg operation to an entire folder of videos at once.
Supports: re-encode, resize, extract audio, convert format.
Progress is shown per-file in the console.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


OPERATIONS = {
    t("batch.re_encode_h_264"):     "reencode",
    t("batch.convert_to_mp4"):        "to_mp4",
    t("batch.extract_audio_mp3"):   "audio_mp3",
    t("batch.extract_audio_aac"):   "audio_aac",
    t("batch.resize_video"):          "resize",
    t("batch.normalise_loudness"):    "loudness",
    t("webm_maker.strip_metadata_checkbox"):        "strip_meta",
}

RESOLUTIONS = ["3840x2160", "2560x1440", "1920x1080", "1280x720",
               "854x480", "640x360"]


class BatchTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.input_files: list[str] = []
        self._cancel_flag = threading.Event()
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🗂  " + t("tab.batch_processor"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("batch.desc_subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Input files ───────────────────────────────────────────────────
        inp_lf = tk.LabelFrame(self, text=t("section.input_files"), padx=12, pady=8)
        inp_lf.pack(fill="both", expand=True, padx=20, pady=8)

        self.listbox = tk.Listbox(
            inp_lf, selectmode="extended", font=(MONO_FONT, 9),
            height=10, bg=CLR["bg"], fg=CLR["fg"],
            selectbackground=CLR["accent"], selectforeground="black",
            activestyle="dotbox")
        sb = ttk.Scrollbar(inp_lf, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_f = tk.Frame(self); btn_f.pack(pady=4)
        for txt, cmd, bg in [
            ("➕ Add Files",     self._add_files,  "#3A3A3A"),
            ("📁 Add Folder",    self._add_folder, "#3A3A3A"),
            ("🗑 Remove Sel.",   self._remove_sel, "#3A3A3A"),
            ("🧹 Clear All",     self._clear,      "#3A3A3A"),
        ]:
            tk.Button(btn_f, text=txt, bg=bg, fg=CLR["fg"], width=14,
                      command=cmd).pack(side="left", padx=4)

        self._count_lbl = tk.Label(self, text=t("batch.0_files_queued"),
                                    fg=CLR["fgdim"], font=(UI_FONT, 9))
        self._count_lbl.pack()

        # ── Operation ─────────────────────────────────────────────────────
        op_lf = tk.LabelFrame(self, text=f"  {t('batch.operation_section')}  ", padx=14, pady=10)
        op_lf.pack(fill="x", padx=20, pady=4)

        op_row = tk.Frame(op_lf); op_row.pack(fill="x", pady=4)
        tk.Label(op_row, text=t("batch.operation"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._op_var = tk.StringVar(value=list(OPERATIONS.keys())[0])
        op_cb = ttk.Combobox(op_row, textvariable=self._op_var,
                              values=list(OPERATIONS.keys()),
                              state="readonly", width=28)
        op_cb.pack(side="left", padx=8)
        op_cb.bind("<<ComboboxSelected>>", self._on_op_change)

        # Dynamic options frame
        self._op_opts = tk.Frame(op_lf)
        self._op_opts.pack(fill="x", pady=4)

        # CRF / preset (for re-encode)
        self._enc_row = tk.Frame(self._op_opts)
        tk.Label(self._enc_row, text=t("common.crf")).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(self._enc_row, textvariable=self._crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(self._enc_row, text=t("rotate_flip.preset")).pack(side="left")
        self._preset_var = tk.StringVar(value="fast")
        ttk.Combobox(self._enc_row, textvariable=self._preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)
        self._enc_row.pack(fill="x", pady=2)

        # Resolution (for resize)
        self._res_row = tk.Frame(self._op_opts)
        tk.Label(self._res_row, text=t("batch.target_resolution")).pack(side="left")
        self._res_var = tk.StringVar(value="1920x1080")
        ttk.Combobox(self._res_row, textvariable=self._res_var,
                     values=RESOLUTIONS, state="readonly", width=12).pack(side="left", padx=4)
        tk.Label(self._res_row, text=t("batch.scale_down_keeps_aspect_ratio"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Output folder ─────────────────────────────────────────────────
        out_lf = tk.LabelFrame(self, text=t("section.output"), padx=14, pady=8)
        out_lf.pack(fill="x", padx=20, pady=4)

        of = tk.Frame(out_lf); of.pack(fill="x", pady=4)
        tk.Label(of, text=t("common.output_folder"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=52, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("btn.browse"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")
        tk.Label(out_lf, text=t("batch.output_files_are_saved_as_originalname_batch_ext"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

        # ── Controls ─────────────────────────────────────────────────────
        ctrl_f = tk.Frame(self); ctrl_f.pack(pady=8)
        self._btn_run = tk.Button(
            ctrl_f, text=t("batch.process_all_files"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=24, command=self._run)
        self._btn_run.pack(side="left", padx=8)
        tk.Button(ctrl_f, text=t("batch.cancel"),
                  bg=CLR["red"], fg="white", width=10,
                  command=self._cancel).pack(side="left", padx=4)
        self._prog_lbl = tk.Label(ctrl_f, text="", fg=CLR["accent"],
                                   font=(UI_FONT, 10))
        self._prog_lbl.pack(side="left", padx=12)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_op_change()

    # ─── File management ──────────────────────────────────────────────────
    def _add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        for p in paths:
            if p not in self.input_files:
                self.input_files.append(p)
                self.listbox.insert(tk.END, f"  {os.path.basename(p)}")
        self._update_count()

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if not folder: return
        exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
        for fn in sorted(os.listdir(folder)):
            if os.path.splitext(fn)[1].lower() in exts:
                full = os.path.join(folder, fn)
                if full not in self.input_files:
                    self.input_files.append(full)
                    self.listbox.insert(tk.END, f"  {fn}")
        self._update_count()

    def _remove_sel(self):
        for i in reversed(self.listbox.curselection()):
            self.input_files.pop(i)
            self.listbox.delete(i)
        self._update_count()

    def _clear(self):
        self.input_files.clear()
        self.listbox.delete(0, tk.END)
        self._update_count()

    def _update_count(self):
        n = len(self.input_files)
        self._count_lbl.config(text=f"{n} file{'s' if n != 1 else ''} queued")

    def _browse_out(self):
        p = filedialog.askdirectory()
        if p: self._out_var.set(p)

    def _cancel(self):
        self._cancel_flag.set()
        self.log(self.console, t("log.batch.cancel_requested_will_stop_after_current_file"))

    # ─── Operation UI ─────────────────────────────────────────────────────
    def _on_op_change(self, *_):
        op = OPERATIONS.get(self._op_var.get(), "reencode")
        self._enc_row.pack_forget()
        self._res_row.pack_forget()
        if op in ("reencode", "to_mp4"):
            self._enc_row.pack(fill="x", pady=2)
        elif op == "resize":
            self._res_row.pack(fill="x", pady=2)
            self._enc_row.pack(fill="x", pady=2)

    # ─── Render ──────────────────────────────────────────────────────────
    def _run(self):
        if not self.input_files:
            messagebox.showwarning(t("common.warning"), "Add at least one file to process.")
            return
        out_dir = self._out_var.get().strip()
        if not out_dir:
            out_dir = filedialog.askdirectory(title="Select output folder")
        if not out_dir:
            return
        self._out_var.set(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        self._cancel_flag.clear()
        self._btn_run.config(state="disabled")
        self.log(self.console, f"── Batch start: {len(self.input_files)} files ──")

        ffmpeg = get_binary_path("ffmpeg.exe")
        op     = OPERATIONS.get(self._op_var.get(), "reencode")
        files  = self.input_files[:]

        def _work():
            """Runs in a background thread; enqueues each file and waits."""
            import threading as _threading
            done = 0
            failed = 0

            for i, src_path in enumerate(files):
                if self._cancel_flag.is_set():
                    self.log(self.console, t("log.batch.cancelled_by_user"))
                    break

                base_name = os.path.basename(src_path)
                self.after(0, lambda i=i: self._prog_lbl.config(
                    text=f"[{i+1}/{len(files)}]  {os.path.basename(files[i])}"))
                self.log(self.console, f"[{i+1}/{len(files)}] {base_name}")

                cmd = self._build_cmd(ffmpeg, op, src_path, out_dir)
                if not cmd:
                    self.log(self.console, t("log.batch.skipped_unsupported_op"))
                    continue

                # Determine output path (last positional arg before -y)
                out_path = cmd[-2] if len(cmd) >= 2 else ""

                # Event to block until this task finishes
                done_event = _threading.Event()
                file_rc    = [0]

                def _on_prog(tid, line, idx=i):
                    self.log(self.console, f"  {line}")

                def _on_done(tid, rc, _name=base_name, _ev=done_event, _rc=file_rc):
                    _rc[0] = rc
                    self.log(self.console,
                             f"  {'✅ Done' if rc == 0 else '❌ Failed'}: {_name}")
                    _ev.set()

                self.enqueue_render(
                    f"Batch: {base_name}",
                    output_path=out_path,
                    cmd=cmd,
                    on_progress=_on_prog,
                    on_complete=_on_done,
                )

                # Wait for this file to complete before submitting the next
                done_event.wait()

                if file_rc[0] == 0:
                    done += 1
                else:
                    failed += 1

            self.after(0, lambda: [
                self._btn_run.config(state="normal"),
                self._prog_lbl.config(text=""),
                messagebox.showinfo(
                    "Batch complete",
                    f"✅ {done} succeeded   ❌ {failed} failed\nOutput: {out_dir}")])

        threading.Thread(target=_work, daemon=True).start()

    def _build_cmd(self, ffmpeg, op, src, out_dir):
        base = os.path.splitext(os.path.basename(src))[0]
        crf    = self._crf_var.get()
        preset = self._preset_var.get()

        if op == "reencode":
            out = os.path.join(out_dir, base + "_batch.mp4")
            return [ffmpeg, "-i", src,
                    "-c:v", "libx264", "-crf", crf, "-preset", preset,
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out, "-y"]
        elif op == "to_mp4":
            out = os.path.join(out_dir, base + "_batch.mp4")
            return [ffmpeg, "-i", src,
                    "-c:v", "libx264", "-crf", crf, "-preset", preset,
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out, "-y"]
        elif op == "audio_mp3":
            out = os.path.join(out_dir, base + "_batch.mp3")
            return [ffmpeg, "-i", src, "-vn",
                    "-c:a", "libmp3lame", "-q:a", "2", out, "-y"]
        elif op == "audio_aac":
            out = os.path.join(out_dir, base + "_batch.aac")
            return [ffmpeg, "-i", src, "-vn",
                    "-c:a", "aac", "-b:a", "192k", out, "-y"]
        elif op == "resize":
            res = self._res_var.get()
            rw, rh = res.split("x")
            out = os.path.join(out_dir, base + f"_batch_{res}.mp4")
            vf  = (f"scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
                   f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2")
            return [ffmpeg, "-i", src, "-vf", vf,
                    "-c:v", "libx264", "-crf", crf, "-preset", preset,
                    "-c:a", "copy",
                    "-movflags", "+faststart", out, "-y"]
        elif op == "loudness":
            out = os.path.join(out_dir, base + "_batch_loud.mp4")
            return [ffmpeg, "-i", src,
                    "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out, "-y"]
        elif op == "strip_meta":
            out = os.path.join(out_dir, base + "_batch_clean.mp4")
            return [ffmpeg, "-i", src, "-c", "copy",
                    "-map_metadata", "-1",
                    "-map_chapters", "-1", out, "-y"]
        return None
