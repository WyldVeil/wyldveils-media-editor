"""
tab_webmmaker.py  ─  WebM Maker
Produces the highest quality WebM possible within a user-defined file-size
budget, using proper two-pass bitrate targeting.

Quality presets map to cpu-used + deadline settings for VP8/VP9.
Resolution sliders lock to original aspect ratio if desired.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import threading
import os
import re
import math
import json
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ─── Quality preset definitions ──────────────────────────────────────────────
# Each entry: (label, vp9_cpu_used, vp9_deadline, vp8_cpu_used, crf_hint)
QUALITY_PRESETS = [
    (t("webm_maker.best_quality_very_very_slow"),  0, "best",     0,  10),
    (t("webm_maker.brilliant_quality_very_slow"),        1, "best",     1,  18),
    (t("webm_maker.great_quality_slow"),             2, "good",     2,  24),
    (t("webm_maker.good_quality_balanced"),         3, "good",     3,  31),
    (t("webm_maker.low_quality_fast"),             4, "good",     4,  40),
    (t("webm_maker.bad_quality_very_fast"),        5, "realtime", 5,  50),
    (t("webm_maker.terrible_quality_very_very_fast"),   8, "realtime", 8,  63),
]
QUALITY_LABELS = [p[0] for p in QUALITY_PRESETS]

# Audio codec options
AUDIO_OPTIONS = {
    t("webm_maker.no_audio_option"):     None,
    "Opus  (recommended)": "libopus",
    "Vorbis":              "libvorbis",
}

AUDIO_BITRATES = ["48k", "64k", "96k", "128k", "160k", "192k", "256k", "320k"]


class WebMTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)

        # Source metadata (populated on file load)
        self._src_w      = 0
        self._src_h      = 0
        self._src_dur    = 0.0
        self._src_fps    = 0.0
        self._aspect     = 1.0       # w/h ratio
        self._lock_updating = False  # prevents slider feedback loops

        self._cancel_flag = threading.Event()
        self._queue_cancel_fn = None   # set during active queue task
        self._build_ui()

    # ═════════════════════════════════════════════════════════════════════════
    #  UI
    # ═════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🌐  " + t("tab.webm_maker"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("webm_maker.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Outer scroll canvas (so the whole tab scrolls on small screens) ─
        outer = tk.Frame(self)
        outer.pack(fill="both", expand=True)

        # ── Source file ───────────────────────────────────────────────────
        src_lf = tk.LabelFrame(outer, text=t("section.source_file"), padx=14, pady=8)
        src_lf.pack(fill="x", padx=18, pady=(10, 4))

        src_row = tk.Frame(src_lf); src_row.pack(fill="x")
        tk.Label(src_row, text=t("webm_maker.input"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(src_row, textvariable=self.src_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(src_row, text=t("btn.browse"), command=self._browse_src, cursor="hand2", relief="flat").pack(side="left")

        self.src_info_lbl = tk.Label(src_lf, text=t("common.no_file_loaded"),
                                      fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self.src_info_lbl.pack(anchor="w", pady=(4, 0))

        # ── Two-column layout for the main controls ───────────────────────
        cols = tk.Frame(outer)
        cols.pack(fill="x", padx=18, pady=4)
        left  = tk.Frame(cols); left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(cols); right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        # ════ LEFT COLUMN ═════════════════════════════════════════════════

        # ── Size limit ────────────────────────────────────────────────────
        size_lf = tk.LabelFrame(left, text=f"  {t('webm_maker.target_size_section')}  ", padx=14, pady=10)
        size_lf.pack(fill="x", pady=(0, 6))

        size_row = tk.Frame(size_lf); size_row.pack(fill="x")
        self.size_limit_var = tk.StringVar(value="8")
        size_entry = tk.Entry(size_row, textvariable=self.size_limit_var,
                              width=7, font=(UI_FONT, 14, "bold"), justify="center")
        size_entry.pack(side="left")
        tk.Label(size_row, text="MB", font=(UI_FONT, 13)).pack(side="left", padx=4)

        # Quick-pick buttons
        quick = tk.Frame(size_lf); quick.pack(anchor="w", pady=(6, 0))
        for mb in [4, 8, 10, 25, 50, 100, 200]:
            tk.Button(quick, text=f"{mb} MB", width=6, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 8),
                      command=lambda v=mb: self.size_limit_var.set(str(v))
                      ).pack(side="left", padx=2)

        self.budget_lbl = tk.Label(size_lf, text="", fg=CLR["fgdim"], font=(UI_FONT, 9))
        self.budget_lbl.pack(anchor="w", pady=(4, 0))
        # Update budget estimate whenever size or duration changes
        self.size_limit_var.trace_add("write", lambda *_: self._update_budget_label())

        # ── Quality preset ────────────────────────────────────────────────
        qual_lf = tk.LabelFrame(left, text=f"  {t('webm_maker.speed_section')}  ",
                                padx=14, pady=10)
        qual_lf.pack(fill="x", pady=(0, 6))

        self.quality_var = tk.StringVar(value=QUALITY_LABELS[3])
        qual_cb = ttk.Combobox(qual_lf, textvariable=self.quality_var,
                               values=QUALITY_LABELS, state="readonly", width=44)
        qual_cb.pack(anchor="w")
        tk.Label(qual_lf,
                 text=t("webm_maker.lower_quality_faster_encode_higher_quality_very"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w", pady=(4, 0))

        # ── Codec ─────────────────────────────────────────────────────────
        codec_lf = tk.LabelFrame(left, text=f"  {t('webm_maker.video_codec_section')}  ", padx=14, pady=10)
        codec_lf.pack(fill="x", pady=(0, 6))

        self.codec_var = tk.StringVar(value="VP9")
        for label, val in [("VP9  (better compression, recommended)", "VP9"),
                            ("VP8  (wider legacy compatibility)",      "VP8")]:
            tk.Radiobutton(codec_lf, text=label, variable=self.codec_var, value=val,
                           command=self._on_codec_change).pack(anchor="w", pady=1)

        self.twopass_var = tk.BooleanVar(value=True)
        tk.Checkbutton(codec_lf,
                       text=t("webm_maker.two_pass_checkbox"),
                       variable=self.twopass_var).pack(anchor="w", pady=(6, 0))

        # ── Audio ─────────────────────────────────────────────────────────
        audio_lf = tk.LabelFrame(left, text=f"  {t('webm_maker.audio_section')}  ", padx=14, pady=10)
        audio_lf.pack(fill="x", pady=(0, 6))

        self.audio_codec_var = tk.StringVar(value="Opus  (recommended)")
        audio_cb = ttk.Combobox(audio_lf, textvariable=self.audio_codec_var,
                                values=list(AUDIO_OPTIONS.keys()),
                                state="readonly", width=28)
        audio_cb.pack(side="left")
        audio_cb.bind("<<ComboboxSelected>>", self._on_audio_change)

        tk.Label(audio_lf, text=t("webm_maker.bitrate")).pack(side="left", padx=(12, 0))
        self.audio_br_var = tk.StringVar(value="128k")
        self.audio_br_cb = ttk.Combobox(audio_lf, textvariable=self.audio_br_var,
                                         values=AUDIO_BITRATES, state="readonly", width=7)
        self.audio_br_cb.pack(side="left", padx=4)

        # ════ RIGHT COLUMN ════════════════════════════════════════════════

        # ── Resolution ────────────────────────────────────────────────────
        res_lf = tk.LabelFrame(right, text=f"  {t('webm_maker.output_resolution_section')}  ", padx=14, pady=10)
        res_lf.pack(fill="x", pady=(0, 6))

        # Lock aspect ratio
        self.lock_ar_var = tk.BooleanVar(value=True)
        tk.Checkbutton(res_lf, text=t("webm_maker.lock_aspect_ratio"),
                       variable=self.lock_ar_var).pack(anchor="w")

        # Width slider + entry
        w_row = tk.Frame(res_lf); w_row.pack(fill="x", pady=(8, 2))
        tk.Label(w_row, text=t("crop.width_label"), width=7, anchor="e").pack(side="left")
        self.res_w_var = tk.IntVar(value=1920)
        self.w_slider = tk.Scale(w_row, variable=self.res_w_var,
                                  from_=128, to=7680, resolution=2,
                                  orient="horizontal", length=200,
                                  command=self._on_w_changed)
        self.w_slider.pack(side="left", padx=6)
        self.w_entry = tk.Entry(w_row, textvariable=self.res_w_var, width=6,
                                 justify="center")
        self.w_entry.pack(side="left")
        self.w_entry.bind("<Return>",   lambda e: self._on_w_changed(self.res_w_var.get()))
        self.w_entry.bind("<FocusOut>", lambda e: self._on_w_changed(self.res_w_var.get()))

        # Height slider + entry
        h_row = tk.Frame(res_lf); h_row.pack(fill="x", pady=(2, 4))
        tk.Label(h_row, text=t("crop.height_label"), width=7, anchor="e").pack(side="left")
        self.res_h_var = tk.IntVar(value=1080)
        self.h_slider = tk.Scale(h_row, variable=self.res_h_var,
                                  from_=128, to=4320, resolution=2,
                                  orient="horizontal", length=200,
                                  command=self._on_h_changed)
        self.h_slider.pack(side="left", padx=6)
        self.h_entry = tk.Entry(h_row, textvariable=self.res_h_var, width=6,
                                 justify="center")
        self.h_entry.pack(side="left")
        self.h_entry.bind("<Return>",   lambda e: self._on_h_changed(self.res_h_var.get()))
        self.h_entry.bind("<FocusOut>", lambda e: self._on_h_changed(self.res_h_var.get()))

        # Resolution presets
        preset_row = tk.Frame(res_lf); preset_row.pack(anchor="w", pady=(4, 0))
        tk.Label(preset_row, text=t("scene_detect.presets_label"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left", padx=(0, 4))
        for label, w, h in [("8K", 7680, 4320), ("4K", 3840, 2160),
                              ("1440p", 2560, 1440), ("1080p", 1920, 1080),
                              ("720p", 1280, 720), ("480p", 854, 480),
                              ("360p", 640, 360), ("Original", 0, 0)]:
            tk.Button(preset_row, text=label, width=5, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 7),
                      command=lambda ww=w, hh=h: self._apply_res_preset(ww, hh)
                      ).pack(side="left", padx=1)

        # ── Trim ──────────────────────────────────────────────────────────
        trim_lf = tk.LabelFrame(right, text=f"  {t('webm_maker.trim_section')}  ", padx=14, pady=8)
        trim_lf.pack(fill="x", pady=(0, 6))

        trim_row = tk.Frame(trim_lf); trim_row.pack(fill="x")
        tk.Label(trim_row, text=t("common.start_s")).pack(side="left")
        self.trim_start_var = tk.StringVar(value="0")
        tk.Entry(trim_row, textvariable=self.trim_start_var, width=8, relief="flat").pack(side="left", padx=4)
        tk.Label(trim_row, text=t("webm_maker.end_s_0_full")).pack(side="left", padx=(12, 0))
        self.trim_end_var = tk.StringVar(value="0")
        tk.Entry(trim_row, textvariable=self.trim_end_var, width=8, relief="flat").pack(side="left", padx=4)

        # ── Extra options ─────────────────────────────────────────────────
        extra_lf = tk.LabelFrame(right, text=f"  {t('webm_maker.extra_options_section')}  ", padx=14, pady=8)
        extra_lf.pack(fill="x", pady=(0, 6))

        # Row 1
        ex1 = tk.Frame(extra_lf); ex1.pack(fill="x", pady=2)
        tk.Label(ex1, text=t("webm_maker.fps_label")).pack(side="left")
        self.fps_var = tk.StringVar(value="0")
        ttk.Combobox(ex1, textvariable=self.fps_var,
                     values=["0", "24", "25", "30", "50", "60"],
                     width=6, state="normal").pack(side="left", padx=4)

        tk.Label(ex1, text=t("webm_maker.pixel_format")).pack(side="left", padx=(12, 0))
        self.pixfmt_var = tk.StringVar(value="yuv420p")
        ttk.Combobox(ex1, textvariable=self.pixfmt_var,
                     values=["yuv420p", "yuva420p (transparency)",
                              "yuv444p", "gbrp"],
                     state="readonly", width=22).pack(side="left", padx=4)

        # Row 2
        ex2 = tk.Frame(extra_lf); ex2.pack(fill="x", pady=2)
        self.strip_meta_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ex2, text=t("webm_maker.strip_metadata_checkbox"),
                       variable=self.strip_meta_var).pack(side="left")
        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ex2, text=t("webm_maker.loop_flag_checkbox"),
                       variable=self.loop_var).pack(side="left", padx=20)

        # Row 3 - VP9-specific
        ex3 = tk.Frame(extra_lf); ex3.pack(fill="x", pady=2)
        tk.Label(ex3, text=t("webm_maker.tile_columns_vp9")).pack(side="left")
        self.tile_col_var = tk.StringVar(value="2")
        ttk.Combobox(ex3, textvariable=self.tile_col_var,
                     values=["0", "1", "2", "3", "4", "6"],
                     state="readonly", width=4).pack(side="left", padx=4)
        tk.Label(ex3, text=t("webm_maker.row_mt_vp9_multi_thread"),
                 fg=CLR["fgdim"]).pack(side="left", padx=(10, 0))
        self.rowmt_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ex3, variable=self.rowmt_var).pack(side="left")

        self.vp9_extra_widgets = [ex3]   # hide for VP8

        # ── Output ────────────────────────────────────────────────────────
        out_lf = tk.LabelFrame(outer, text=t("section.output"), padx=14, pady=8)
        out_lf.pack(fill="x", padx=18, pady=(2, 6))
        out_row = tk.Frame(out_lf); out_row.pack(fill="x")
        tk.Label(out_row, text=t("webm_maker.save_as"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(out_row, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # ── Render controls ───────────────────────────────────────────────
        render_row = tk.Frame(outer)
        render_row.pack(pady=8)

        self.btn_render = tk.Button(
            render_row, text=t("webm_maker.encode_webm"),
            font=(UI_FONT, 12, "bold"),
            bg="#5C6BC0", fg="white",
            height=2, width=26,
            command=self._start_render)
        self.btn_render.pack(side="left", padx=8)

        self.btn_cancel = tk.Button(
            render_row, text=t("webm_maker.cancel"),
            font=(UI_FONT, 10), bg=CLR["red"], fg="white",
            height=2, width=10,
            state="disabled",
            command=self._cancel)
        self.btn_cancel.pack(side="left", padx=4)

        # Progress / status
        self.status_var = tk.StringVar(value="Ready.")
        self.status_lbl = tk.Label(outer, textvariable=self.status_var,
                                    fg=CLR["accent"], font=(UI_FONT, 10, "bold"))
        self.status_lbl.pack()

        self.progress = ttk.Progressbar(outer, mode="indeterminate", length=600)
        self.progress.pack(pady=(2, 6))

        # ── Console ───────────────────────────────────────────────────────
        con_f = tk.Frame(outer)
        con_f.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.console, csb = self.make_console(con_f, height=9)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ═════════════════════════════════════════════════════════════════════════
    #  File loading
    # ═════════════════════════════════════════════════════════════════════════
    def _browse_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.src_var.set(p)
            self.run_in_thread(self._load_metadata, p)

    def _load_metadata(self, path):
        """Read width, height, duration, fps via ffprobe."""
        ffprobe = get_binary_path("ffprobe.exe")
        if not os.path.exists(ffprobe):
            return
        cmd = [ffprobe, "-v", "error",
               "-show_entries", t("webm_maker.format_duration_stream_width_height_r_frame_rate"),
               "-of", "json", path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
            data = json.loads(r.stdout)
            streams = data.get("streams", [])
            vid = next((s for s in streams if s.get("codec_type") == "video"), {})
            fmt  = data.get("format", {})

            w    = int(vid.get("width",  1920))
            h    = int(vid.get("height", 1080))
            dur  = float(fmt.get("duration", 0))
            fps_str = vid.get("r_frame_rate", "30/1")
            num, den = map(int, fps_str.split("/"))
            fps  = round(num / den, 3) if den else 30.0

            self._src_w   = w
            self._src_h   = h
            self._src_dur = dur
            self._src_fps = fps
            self._aspect  = w / h if h else 1.0

            mins, secs = divmod(int(dur), 60)
            info = (f"{w}×{h}  |  {fps} fps  |  {mins}m {secs}s  "
                    f"|  {os.path.getsize(path)/1024/1024:.1f} MB")

            self.after(0, lambda: self.src_info_lbl.config(text=info, fg=CLR["accent"]))
            self.after(0, lambda: self._seed_resolution(w, h))
            self.after(0, self._update_budget_label)

            # Auto-name output
            base = os.path.splitext(path)[0]
            self.after(0, lambda: self.out_var.set(base + "_studio.webm"))
        except Exception as e:
            self.after(0, lambda: self.src_info_lbl.config(
                text=f"Could not read metadata: {e}", fg=CLR["red"]))

    # ═════════════════════════════════════════════════════════════════════════
    #  Resolution logic
    # ═════════════════════════════════════════════════════════════════════════
    def _seed_resolution(self, w, h):
        self._lock_updating = True
        self.res_w_var.set(w)
        self.res_h_var.set(h)
        self.w_slider.config(to=max(7680, w))
        self.h_slider.config(to=max(4320, h))
        self._lock_updating = False

    def _apply_res_preset(self, w, h):
        if w == 0:
            self._seed_resolution(self._src_w or 1920, self._src_h or 1080)
            return
        self._lock_updating = True
        self.res_w_var.set(w)
        self.res_h_var.set(h)
        self._lock_updating = False

    def _on_w_changed(self, val):
        if self._lock_updating:
            return
        try:
            w = int(float(val))
            if w < 2: return
            # Snap to even number
            w = w if w % 2 == 0 else w + 1
            self._lock_updating = True
            self.res_w_var.set(w)
            if self.lock_ar_var.get() and self._aspect:
                h = int(round(w / self._aspect))
                h = h if h % 2 == 0 else h + 1
                self.res_h_var.set(h)
            self._lock_updating = False
        except (ValueError, TypeError):
            pass

    def _on_h_changed(self, val):
        if self._lock_updating:
            return
        try:
            h = int(float(val))
            if h < 2: return
            h = h if h % 2 == 0 else h + 1
            self._lock_updating = True
            self.res_h_var.set(h)
            if self.lock_ar_var.get() and self._aspect:
                w = int(round(h * self._aspect))
                w = w if w % 2 == 0 else w + 1
                self.res_w_var.set(w)
            self._lock_updating = False
        except (ValueError, TypeError):
            pass

    # ═════════════════════════════════════════════════════════════════════════
    #  Budget label
    # ═════════════════════════════════════════════════════════════════════════
    def _update_budget_label(self):
        try:
            size_mb  = float(self.size_limit_var.get())
            dur      = self._src_dur

            # Subtract audio from budget
            audio_key = self.audio_codec_var.get() if hasattr(self, "audio_codec_var") else "No audio track"
            audio_kbps = 0
            if AUDIO_OPTIONS.get(audio_key):
                try:
                    audio_kbps = int(
                        self.audio_br_var.get().replace("k", ""))
                except Exception:
                    audio_kbps = 128

            if dur > 0:
                total_bits  = size_mb * 1024 * 1024 * 8
                audio_bits  = audio_kbps * 1000 * dur
                video_bits  = max(0, total_bits - audio_bits)
                video_kbps  = video_bits / dur / 1000
                self.budget_lbl.config(
                    text=(f"≈ {video_kbps:.0f} kbps video bitrate  "
                          f"({size_mb:.0f} MB ÷ {dur:.1f}s)"),
                    fg=CLR["accent"] if video_kbps > 100 else CLR["red"])
            else:
                self.budget_lbl.config(
                    text=t("webm_maker.load_a_source_file_to_see_bitrate_estimate"),
                    fg=CLR["fgdim"])
        except (ValueError, AttributeError):
            pass

    # ═════════════════════════════════════════════════════════════════════════
    #  Codec / audio change handlers
    # ═════════════════════════════════════════════════════════════════════════
    def _on_codec_change(self):
        is_vp9 = self.codec_var.get() == "VP9"
        for w in self.vp9_extra_widgets:
            if is_vp9:
                w.pack(fill="x", pady=2)
            else:
                w.pack_forget()

    def _on_audio_change(self, *_):
        has_audio = AUDIO_OPTIONS.get(self.audio_codec_var.get()) is not None
        self.audio_br_cb.config(state="readonly" if has_audio else "disabled")
        self._update_budget_label()

    # ═════════════════════════════════════════════════════════════════════════
    #  Browse output
    # ═════════════════════════════════════════════════════════════════════════
    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".webm",
            filetypes=[("WebM", "*.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.out_var.set(p)

    # ═════════════════════════════════════════════════════════════════════════
    #  Cancel
    # ═════════════════════════════════════════════════════════════════════════
    def _cancel(self):
        self._cancel_flag.set()
        self.status_var.set("Cancelling…")

    # ═════════════════════════════════════════════════════════════════════════
    #  Main render entry
    # ═════════════════════════════════════════════════════════════════════════
    def _start_render(self):
        src = self.src_var.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".webm",
                                               filetypes=[("WebM", "*.webm")])
        if not out:
            return
        self.out_var.set(out)

        try:
            size_mb = float(self.size_limit_var.get())
            assert size_mb > 0
        except Exception:
            messagebox.showerror(t("common.error"), "Enter a valid positive file-size target.")
            return

        self._cancel_flag.clear()
        self._queue_cancel_fn = None       # set by worker_fn below
        self.btn_render.config(state="disabled", text=t("app.status.queued_btn"))
        self.btn_cancel.config(state="normal")
        self.progress.start(12)
        self.console.delete("1.0", tk.END)
        self.status_var.set("Queued…")

        _src, _out, _size_mb = src, out, size_mb

        def _worker_fn(progress_cb, cancel_fn):
            # Bridge the queue's cancel signal to the existing _cancel_flag
            self._queue_cancel_fn = cancel_fn
            self.after(0, lambda: self.status_var.set("Encoding…"))
            self.after(0, lambda: self.btn_render.config(text=t("webm_maker.encoding")))
            self._encode_worker(_src, _out, _size_mb)
            self._queue_cancel_fn = None
            return 1 if self._cancel_flag.is_set() else 0

        self.enqueue_render("WebM Encode", output_path=_out, worker_fn=_worker_fn)

    # ═════════════════════════════════════════════════════════════════════════
    #  Encoding worker (runs in background thread)
    # ═════════════════════════════════════════════════════════════════════════
    def _encode_worker(self, src, out, size_mb):
        ffmpeg = get_binary_path("ffmpeg.exe")
        codec  = self.codec_var.get()       # "VP9" or "VP8"
        two_pass = self.twopass_var.get()

        # ── Quality preset ─────────────────────────────────────────────
        quality_label = self.quality_var.get()
        preset = next(p for p in QUALITY_PRESETS if p[0] == quality_label)
        _, vp9_cpu, vp9_deadline, vp8_cpu, crf_hint = preset

        # ── Determine effective duration ────────────────────────────────
        t_start = float(self.trim_start_var.get() or 0)
        t_end   = float(self.trim_end_var.get()   or 0)
        duration = self._src_dur

        if t_end > t_start:
            effective_dur = t_end - t_start
        elif t_end == 0 and t_start > 0:
            effective_dur = max(1.0, duration - t_start)
        else:
            effective_dur = max(1.0, duration)

        # ── Bitrate calculation ─────────────────────────────────────────
        audio_codec_key = self.audio_codec_var.get()
        audio_lib       = AUDIO_OPTIONS.get(audio_codec_key)
        audio_kbps = 0
        if audio_lib:
            try:
                audio_kbps = int(self.audio_br_var.get().replace("k", ""))
            except Exception:
                audio_kbps = 128

        total_bits  = size_mb * 1024 * 1024 * 8
        audio_bits  = audio_kbps * 1000 * effective_dur
        video_bits  = max(10_000, total_bits - audio_bits)
        video_kbps  = int(video_bits / effective_dur / 1000)
        # min/max guard
        video_kbps  = max(50, min(video_kbps, 100_000))
        video_br    = f"{video_kbps}k"

        self._log(f"━━━ WebM Maker ━━━")
        self._log(f"Codec:          {codec}")
        self._log(f"Target size:    {size_mb} MB")
        self._log(f"Duration:       {effective_dur:.2f}s")
        self._log(f"Video bitrate:  {video_kbps} kbps")
        self._log(f"Audio:          {audio_codec_key}  {audio_kbps if audio_lib else 0} kbps")
        self._log(f"Quality preset: {quality_label.strip()}")
        self._log("")

        # ── Build filter string ─────────────────────────────────────────
        out_w = self.res_w_var.get()
        out_h = self.res_h_var.get()
        # Only scale if different from source
        vf_parts = []
        if out_w != self._src_w or out_h != self._src_h:
            vf_parts.append(f"scale={out_w}:{out_h}:flags=lanczos")

        fps_setting = self.fps_var.get().strip()
        if fps_setting and fps_setting != "0":
            vf_parts.append(f"fps={fps_setting}")

        vf = ",".join(vf_parts) if vf_parts else None

        # ── Pixel format ───────────────────────────────────────────────
        pixfmt = self.pixfmt_var.get().split(" ")[0]   # strip "(transparency)" etc.

        # ── Common input args ───────────────────────────────────────────
        input_args = [ffmpeg]
        if t_start > 0:
            input_args += ["-ss", str(t_start)]
        input_args += ["-i", src]
        if t_end > t_start:
            input_args += ["-t", str(effective_dur)]

        # ── Codec-specific args ─────────────────────────────────────────
        if codec == "VP9":
            vcodec_args = [
                t("dynamics.c_v"), "libvpx-vp9",
                t("webm_maker.b_v"), video_br,
                "-minrate", f"{int(video_kbps*0.5)}k",
                "-maxrate", f"{int(video_kbps*1.45)}k",
                "-crf", str(crf_hint),
                "-cpu-used", str(vp9_cpu),
                "-deadline", vp9_deadline,
                "-tile-columns", self.tile_col_var.get(),
                "-row-mt", "1" if self.rowmt_var.get() else "0",
                "-pix_fmt", pixfmt,
            ]
        else:  # VP8
            vcodec_args = [
                t("dynamics.c_v"), "libvpx",
                t("webm_maker.b_v"), video_br,
                "-minrate", f"{int(video_kbps*0.5)}k",
                "-maxrate", f"{int(video_kbps*1.45)}k",
                "-cpu-used", str(vp8_cpu),
                "-pix_fmt", pixfmt,
            ]

        if vf:
            vcodec_args += ["-vf", vf]

        # ── Audio args ──────────────────────────────────────────────────
        if audio_lib:
            acodec_args = [t("dynamics.c_a"), audio_lib, t("dynamics.b_a"), self.audio_br_var.get()]
        else:
            acodec_args = ["-an"]

        # ── Metadata / loop ─────────────────────────────────────────────
        extra_args = []
        if self.strip_meta_var.get():
            extra_args += ["-map_metadata", "-1"]
        if self.loop_var.get():
            extra_args += ["-loop", "0"]

        # ── Two-pass or single-pass ─────────────────────────────────────
        if two_pass:
            pass_log = tempfile.mktemp()   # ffmpeg appends -0.log etc.

            # Pass 1
            self._status("Pass 1 of 2: Analysing…")
            self._log(t("log.webm_maker.pass_1"))
            pass1_cmd = (input_args
                         + vcodec_args
                         + ["-pass", "1", "-passlogfile", pass_log]
                         + ["-an", "-f", "webm", os.devnull, "-y"])
            ok = self._run_cmd(pass1_cmd)
            if not ok or self._cancel_flag.is_set():
                self._finish(False, out, pass_log)
                return

            # Pass 2
            self._status("Pass 2 of 2: Encoding…")
            self._log(t("log.webm_maker.pass_2"))
            pass2_cmd = (input_args
                         + vcodec_args
                         + ["-pass", "2", "-passlogfile", pass_log]
                         + acodec_args + extra_args
                         + ["-movflags", "+faststart", out, "-y"])
            ok = self._run_cmd(pass2_cmd)
            self._finish(ok, out, pass_log)
        else:
            # Single pass
            self._status("Encoding (single-pass)…")
            cmd = input_args + vcodec_args + acodec_args + extra_args + ["-movflags", "+faststart", out, "-y"]
            ok  = self._run_cmd(cmd)
            self._finish(ok, out)

    # ─── Helpers ─────────────────────────────────────────────────────────────
    def _run_cmd(self, cmd) -> bool:
        """Run a command, stream to console. Returns True on success."""
        self.log_debug(f"CMD: {' '.join(str(c) for c in cmd)}")
        self._log(f"$ {' '.join(str(c) for c in cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        # Parse FFmpeg progress lines for live status
        time_re = re.compile(r"time=(\d+):(\d+):([\d.]+)")
        for line in iter(proc.stdout.readline, ""):
            if self._cancel_flag.is_set() or (
                    self._queue_cancel_fn and self._queue_cancel_fn()):
                self._cancel_flag.set()
                proc.terminate()
                return False
            line = line.rstrip()
            self._log(line)
            m = time_re.search(line)
            if m:
                h, mi, s = m.groups()
                elapsed = int(h)*3600 + int(mi)*60 + float(s)
                total   = self._src_dur or 1
                pct     = min(100, int(elapsed / total * 100))
                self._status(f"Encoding… {pct}%  ({elapsed:.1f}s / {total:.1f}s)")
        proc.stdout.close()
        proc.wait()
        return proc.returncode == 0

    def _finish(self, ok: bool, out: str, pass_log: str = None):
        """Clean up temp files, update UI, report result."""
        # Remove pass-log files
        if pass_log:
            for suffix in ["-0.log", "-0.log.mbtree", ""]:
                p = pass_log + suffix
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

        def _ui():
            self.btn_render.config(state="normal", text=t("webm_maker.encode_webm"))
            self.btn_cancel.config(state="disabled")
            self.progress.stop()
            self.progress.config(value=0)

            if self._cancel_flag.is_set():
                self.status_var.set("Cancelled.")
                return

            if ok and os.path.exists(out):
                actual_mb = os.path.getsize(out) / 1024 / 1024
                self.status_var.set(
                    f"✅  Done!  →  {actual_mb:.2f} MB  ({out})")
                messagebox.showinfo("WebM Complete",
                                    f"Encode finished!\n\n"
                                    f"Output:  {os.path.basename(out)}\n"
                                    f"Size:    {actual_mb:.2f} MB")
            else:
                self.status_var.set("❌  Encode failed. Check console for details.")
                messagebox.showerror(t("common.error"),
                                     "FFmpeg returned an error.\n"
                                     "Check the console for details.")
        self.after(0, _ui)

    def _log(self, msg: str):
        self.after(0, lambda m=msg: [
            self.console.insert(tk.END, m + "\n"),
            self.console.see(tk.END)])

    def _status(self, msg: str):
        self.after(0, lambda m=msg: self.status_var.set(m))
