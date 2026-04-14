"""
tab_deinterlace.py  ─  Deinterlace
Fix interlaced content from broadcast TV, VHS captures, camcorders.
Supports Yadif (fast), BWDIF (best quality), and frame-doubling for
buttery-smooth output from 50i/60i sources.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


ALGORITHMS = {
    t("deinterlace.bwdif_best_quality_recommended"): {
        "filter":  "bwdif",
        "desc":    ("Bob Weaver Deinterlacing Filter. Motion-adaptive, edge-aware. "
                    "The gold standard. Slightly slower than yadif."),
    },
    "Yadif  (fast, good quality)": {
        "filter":  "yadif",
        "desc":    ("Yet Another DeInterlacing Filter. Excellent balance of speed "
                    "and quality. The FFmpeg default."),
    },
    "Yadif 2× (frame-doubling)": {
        "filter":  "yadif=mode=1",
        "desc":    ("Outputs EVERY field as a full frame. 50i → 100fps, 60i → 120fps. "
                    "Buttery smooth motion. Large output files."),
    },
    "BWDIF 2× (frame-doubling, best)": {
        "filter":  "bwdif=mode=1",
        "desc":    "Same as BWDIF but doubles frame rate. Best quality + smooth motion.",
    },
    "Decomb  (smart, only deinterlaces when needed)": {
        "filter":  "yadif=mode=0:parity=-1:deint=1",
        "desc":    ("Analyses each frame and only deinterlaces combed frames. "
                    "Good for hybrid progressive/interlaced content."),
    },
}

SOURCE_TYPES = {
    "Auto-detect":           "parity=-1",
    t("deinterlace.top_field_first_tff"): "parity=0",
    t("deinterlace.bottom_field_first_bff"): "parity=1",
}


class DeinterlaceTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path    = ""
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📺  " + t("tab.deinterlace"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("deinterlace.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=12)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Algorithm picker ─────────────────────────────────────────────
        algo_lf = tk.LabelFrame(self, text=f"  {t('deinterlace.algorithm_section')}  ",
                                padx=16, pady=12)
        algo_lf.pack(fill="x", padx=20, pady=6)

        self.algo_var = tk.StringVar(value=list(ALGORITHMS.keys())[0])
        for name in ALGORITHMS:
            rb = tk.Radiobutton(algo_lf, text=name, variable=self.algo_var,
                                value=name, font=(UI_FONT, 10),
                                command=self._on_algo_change)
            rb.pack(anchor="w", pady=1)

        self.algo_desc_lbl = tk.Label(algo_lf, text="", fg=CLR["accent"],
                                       font=(UI_FONT, 9), wraplength=700,
                                       justify="left")
        self.algo_desc_lbl.pack(anchor="w", pady=(8, 0))

        # ── Source field order ────────────────────────────────────────────
        field_lf = tk.LabelFrame(self, text=f"  {t('deinterlace.field_order_section')}  ",
                                  padx=16, pady=8)
        field_lf.pack(fill="x", padx=20, pady=4)

        field_row = tk.Frame(field_lf); field_row.pack(fill="x")
        self.field_var = tk.StringVar(value="Auto-detect")
        for label in SOURCE_TYPES:
            tk.Radiobutton(field_row, text=label, variable=self.field_var,
                           value=label).pack(side="left", padx=16)
        tk.Label(field_lf,
                 text=t("deinterlace.field_order_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w", pady=2)

        # ── Output FPS option ─────────────────────────────────────────────
        fps_lf = tk.LabelFrame(self, text=t("section.output_options"), padx=16, pady=8)
        fps_lf.pack(fill="x", padx=20, pady=4)

        fps_row = tk.Frame(fps_lf); fps_row.pack(fill="x")
        tk.Label(fps_row, text=t("deinterlace.output_fps_label")).pack(side="left")
        self.fps_var = tk.StringVar(value="Source")
        ttk.Combobox(fps_row, textvariable=self.fps_var,
                     values=["Source", "23.976", "24", "25", "29.97", "30", "50", "60"],
                     state="normal", width=10).pack(side="left", padx=6)
        tk.Label(fps_row, text=t("deinterlace.output_fps_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Encode settings ───────────────────────────────────────────────
        enc_f = tk.Frame(self); enc_f.pack(padx=22, pady=4, fill="x")
        tk.Label(enc_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="16")  # slightly lower - deinterlacing loses some quality
        tk.Entry(enc_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(enc_f, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="medium")
        ttk.Combobox(enc_f, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)
        tk.Label(enc_f, text=t("webm_maker.pixel_format")).pack(side="left", padx=(12, 0))
        self.pixfmt_var = tk.StringVar(value="yuv420p")
        ttk.Combobox(enc_f, textvariable=self.pixfmt_var,
                     values=["yuv420p", "yuv422p"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # Filter display
        self.filter_lbl = tk.Label(self, text="", fg=CLR["fgdim"],
                                    font=(MONO_FONT, 9))
        self.filter_lbl.pack(anchor="w", padx=22)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=14, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("deinterlace.apply_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_algo_change()

    def _on_algo_change(self):
        info = ALGORITHMS.get(self.algo_var.get(), {})
        self.algo_desc_lbl.config(text=info.get("desc", ""))
        self._update_filter_lbl()

    def _build_filter(self):
        info   = ALGORITHMS[self.algo_var.get()]
        base   = info["filter"]
        parity = SOURCE_TYPES[self.field_var.get()]

        # Inject parity unless already parameterised
        if "=" in base:
            # e.g. yadif=mode=0:parity=-1:deint=1 - replace parity
            base = re.sub(r"parity=[^:)]+", parity, base)
        else:
            base = f"{base}={parity}"

        fps = self.fps_var.get()
        if fps not in ("Source", "0", ""):
            return f"{base},fps={fps}"
        return base

    def _update_filter_lbl(self):
        self.filter_lbl.config(text=f"Filter:  {self._build_filter()}")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.ts *.mpg *.vob"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_deinterlaced.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p: self.out_var.set(p)

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("deinterlace.no_file_title"), t("deinterlace.no_file_message"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay = get_binary_path("ffplay.exe")
        vf = self._build_filter()
        cmd = [ffplay, "-i", self.file_path, "-vf", vf,
               "-window_title", t("deinterlace.deinterlace_preview"), "-x", "800", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        vf = self._build_filter()
        cmd = [ffmpeg, "-i", self.file_path,
               "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_var.get(),
               "-pix_fmt", self.pixfmt_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, f"Algorithm: {self.algo_var.get()}")
        self.log(self.console, f"Filter:    {vf}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label="📺  DEINTERLACE")
