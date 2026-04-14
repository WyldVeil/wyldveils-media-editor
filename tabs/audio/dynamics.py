"""
tab_audiodynamics.py  ─  Audio Dynamics
Professional-grade audio processing chain using FFmpeg filters.
Equivalent to DaVinci Resolve Fairlight's dynamics and EQ tools.

Chain (applied in order):
  1. Noise Gate    - cuts audio below a threshold (kills room noise)
  2. EQ            - 5-band parametric equaliser
  3. Compressor    - controls dynamic range
  4. De-esser      - reduces harsh sibilance (S/SH sounds)
  5. Limiter       - hard ceiling to prevent clipping

Each stage can be bypassed independently.
Preview by exporting a short clip with the chain applied.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, open_in_explorer
from core.i18n import t


# ── EQ Band definitions ───────────────────────────────────────────────────
EQ_BANDS = [
    ("Low-shelf",  "lowshelf",  80,    t("dynamics.low_end_boost_for_warmth_cut_for_thinness")),
    ("Low-mid",    "peaking",   300,   t("dynamics.mud_zone_cut_to_clean_up_muddy_speech")),
    ("Presence",   "peaking",   2500,  t("dynamics.voice_presence_boost_for_clarity")),
    ("High-mid",   "peaking",   5000,  t("dynamics.air_brightness_boost_for_sparkle")),
    ("High-shelf", "highshelf", 10000, t("dynamics.top_end_air")),
]

VOICE_PRESETS = {
    t("dynamics.flat_bypass_all"): None,
    t("dynamics.podcast_voice_warm_clear"): {
        "gate_thresh": -40, "gate_ratio": 4,
        "comp_thresh": -18, "comp_ratio": 3, "comp_attack": 5, "comp_release": 80,
        "eq": [(80, -2), (300, -3), (2500, 3), (5000, 1), (10000, 0)],
        "limit_thresh": -1,
    },
    "YouTube voiceover: punchy": {
        "gate_thresh": -45, "gate_ratio": 6,
        "comp_thresh": -15, "comp_ratio": 4, "comp_attack": 3, "comp_release": 60,
        "eq": [(80, 2), (300, -4), (2500, 4), (5000, 2), (10000, 1)],
        "limit_thresh": -0.5,
    },
    "Music mastering: balanced": {
        "gate_thresh": -60, "gate_ratio": 2,
        "comp_thresh": -12, "comp_ratio": 2, "comp_attack": 20, "comp_release": 200,
        "eq": [(80, 0), (300, -1), (2500, 0), (5000, 1), (10000, 2)],
        "limit_thresh": -0.1,
    },
    "De-harsh: reduce harshness": {
        "gate_thresh": -50, "gate_ratio": 2,
        "comp_thresh": -20, "comp_ratio": 3, "comp_attack": 10, "comp_release": 100,
        "eq": [(80, 0), (300, -2), (2500, -3), (5000, -2), (10000, 0)],
        "limit_thresh": -1,
    },
}


class AudioDynamicsTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎛  " + t("tab.audio_dynamics"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("dynamics.desc_header"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=8)
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Preset
        pre_f = tk.Frame(self); pre_f.pack(fill="x", padx=16, pady=4)
        tk.Label(pre_f, text=t("dynamics.lbl_quick_preset"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.preset_var = tk.StringVar(value=list(VOICE_PRESETS.keys())[0])
        preset_cb = ttk.Combobox(pre_f, textvariable=self.preset_var,
                                  values=list(VOICE_PRESETS.keys()),
                                  state="readonly", width=34)
        preset_cb.pack(side="left", padx=8)
        preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)

        # ── Scrollable chain ─────────────────────────────────────────────
        canvas = tk.Canvas(self, highlightthickness=0)
        sb     = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=sb.set)

        # No mousewheel binding here - main.py's _global_mousewheel handles it.
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        sb.pack(side="right", fill="y")

        # ── 1. Noise Gate ─────────────────────────────────────────────────
        self._build_gate(inner)

        # ── 2. EQ ─────────────────────────────────────────────────────────
        self._build_eq(inner)

        # ── 3. Compressor ─────────────────────────────────────────────────
        self._build_compressor(inner)

        # ── 4. De-esser ───────────────────────────────────────────────────
        self._build_deesser(inner)

        # ── 5. Limiter ────────────────────────────────────────────────────
        self._build_limiter(inner)

        # ── Filter preview ────────────────────────────────────────────────
        self.filter_preview = tk.Label(inner, text="", fg=CLR["fgdim"],
                                        font=(MONO_FONT, 8),
                                        wraplength=860, justify="left")
        self.filter_preview.pack(anchor="w", padx=16, pady=4)

        # ── Output & render ───────────────────────────────────────────────
        of = tk.Frame(inner); of.pack(pady=6, padx=16, fill="x")
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(inner); btn_row.pack(pady=8, padx=16)
        tk.Button(btn_row, text=t("dynamics.btn_preview_10s"),
                  bg=CLR["accent"], fg="white", width=16, font=(UI_FONT, 10),
                  command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("dynamics.btn_apply_dynamics"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white",
            height=2, width=24,
            command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(inner); cf.pack(fill="both", padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Stage builders ────────────────────────────────────────────────────
    def _stage_frame(self, parent, title, bypass_attr):
        lf = tk.LabelFrame(parent, text=f"  {title}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)
        var = tk.BooleanVar(value=True)
        setattr(self, bypass_attr, var)
        tk.Checkbutton(lf, text=t("common.enable"),
                       variable=var,
                       command=self._update_filter_preview).pack(anchor="e")
        return lf

    def _slider_row(self, parent, label, attr, lo, hi, default, res, unit=""):
        row = tk.Frame(parent); row.pack(fill="x", pady=2)
        tk.Label(row, text=label, width=22, anchor="e").pack(side="left")
        var = tk.DoubleVar(value=default)
        setattr(self, attr, var)
        sl = tk.Scale(row, variable=var, from_=lo, to=hi,
                      resolution=res, orient="horizontal", length=240,
                      command=lambda v: self._update_filter_preview())
        sl.pack(side="left", padx=6)
        lbl = tk.Label(row, text=f"{default}{unit}", width=8, fg=CLR["accent"])
        lbl.pack(side="left")
        var.trace_add("write", lambda *_, l=lbl, v=var, u=unit:
                      l.config(text=f"{v.get():.2f}{u}"))

    def _build_gate(self, parent):
        lf = self._stage_frame(parent, "🚪  1. Noise Gate", "gate_on")
        self._slider_row(lf, "Threshold (dB):", "gate_thresh", -80, 0, -40, 0.5, " dB")
        self._slider_row(lf, "Ratio:",           "gate_ratio",   1, 10,   4, 0.5, ":1")
        self._slider_row(lf, "Attack (ms):",     "gate_attack",  1, 200,  5, 1, " ms")
        self._slider_row(lf, "Release (ms):",    "gate_release",10,2000, 80,10, " ms")
        tk.Label(lf,
                 text=t("dynamics.cuts_everything_below_the_threshold_silences_roo"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

    def _build_eq(self, parent):
        lf = self._stage_frame(parent, "🎚  2. Parametric EQ  (5 bands)", "eq_on")
        self._eq_vars = {}
        for i, (name, ftype, freq, tip) in enumerate(EQ_BANDS):
            row = tk.Frame(lf); row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{name} ({freq} Hz):", width=22, anchor="e").pack(side="left")
            var = tk.DoubleVar(value=0.0)
            self._eq_vars[i] = (var, ftype, freq)
            sl = tk.Scale(row, variable=var, from_=-12, to=12,
                          resolution=0.5, orient="horizontal", length=240,
                          command=lambda v: self._update_filter_preview())
            sl.pack(side="left", padx=6)
            lbl = tk.Label(row, text=t("dynamics.0_0_db"), width=8, fg=CLR["accent"])
            lbl.pack(side="left")
            var.trace_add("write", lambda *_, l=lbl, v=var:
                          l.config(text=f"{v.get():.1f} dB"))
            tk.Label(row, text=tip, fg=CLR["fgdim"],
                     font=(UI_FONT, 7)).pack(side="left", padx=6)

    def _build_compressor(self, parent):
        lf = self._stage_frame(parent, "🗜  3. Compressor", "comp_on")
        self._slider_row(lf, "Threshold (dB):", "comp_thresh",  -60, 0, -18, 0.5, " dB")
        self._slider_row(lf, "Ratio:",           "comp_ratio",  1, 20,   3, 0.5, ":1")
        self._slider_row(lf, "Attack (ms):",     "comp_attack",  0.1, 200,  5, 0.1, " ms")
        self._slider_row(lf, "Release (ms):",    "comp_release",10, 2000, 80,10, " ms")
        self._slider_row(lf, "Makeup gain (dB):","comp_makeup",   0, 24,   0, 0.5, " dB")
        tk.Label(lf,
                 text=t("dynamics.raises_quiet_parts_and_lowers_loud_peaks_makes_s"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

    def _build_deesser(self, parent):
        lf = self._stage_frame(parent, "🐍  4. De-esser", "deess_on")
        self._slider_row(lf, "Frequency (Hz):", "deess_freq", 2000, 16000, 6000, 100, " Hz")
        self._slider_row(lf, "Threshold:",      "deess_thresh",  0, 1, 0.1, 0.01, "")
        tk.Label(lf,
                 text=t("dynamics.targets_harsh_s_sh_sibilance_at_the_chosen_frequ"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

    def _build_limiter(self, parent):
        lf = self._stage_frame(parent, "🔔  5. Limiter", "limit_on")
        self._slider_row(lf, "Ceiling (dBFS):", "limit_thresh", -12, 0, -1, 0.1, " dBFS")
        tk.Label(lf,
                 text=t("dynamics.hard_ceiling_prevents_any_peak_from_exceeding_th"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

    # ── Preset ────────────────────────────────────────────────────────────
    def _apply_preset(self, *_):
        p = VOICE_PRESETS.get(self.preset_var.get())
        if not p: return
        self.gate_thresh.set(p["gate_thresh"])
        self.gate_ratio.set(p["gate_ratio"])
        self.comp_thresh.set(p["comp_thresh"])
        self.comp_ratio.set(p["comp_ratio"])
        self.comp_attack.set(p["comp_attack"])
        self.comp_release.set(p["comp_release"])
        self.limit_thresh.set(p["limit_thresh"])
        for i, gain in enumerate(p["eq"]):
            if i < len(EQ_BANDS):
                self._eq_vars[i][0].set(gain[1])
        self._update_filter_preview()

    # ── Filter string ─────────────────────────────────────────────────────
    def _build_filter(self):
        parts = []

        # Gate
        if self.gate_on.get():
            gt = self.gate_thresh.get()
            gr = self.gate_ratio.get()
            ga = self.gate_attack.get()
            grel = self.gate_release.get()
            parts.append(f"agate=threshold={10**(gt/20):.6f}:ratio={gr:.1f}"
                         f":attack={ga:.1f}:release={grel:.1f}")

        # EQ
        if self.eq_on.get():
            eq_parts = []
            for i, (var, ftype, freq) in self._eq_vars.items():
                gain = var.get()
                if abs(gain) > 0.1:
                    if ftype == "lowshelf":
                        eq_parts.append(f"equalizer=f={freq}:t=s:w=200:g={gain:.1f}")
                    elif ftype == "highshelf":
                        eq_parts.append(f"equalizer=f={freq}:t=s:w=2000:g={gain:.1f}")
                    else:
                        eq_parts.append(f"equalizer=f={freq}:t=o:w=200:g={gain:.1f}")
            if eq_parts:
                parts.extend(eq_parts)

        # Compressor
        if self.comp_on.get():
            ct = self.comp_thresh.get()
            cr = self.comp_ratio.get()
            ca = self.comp_attack.get()
            crel = self.comp_release.get()
            mk = self.comp_makeup.get()
            parts.append(f"acompressor=threshold={10**(ct/20):.6f}:ratio={cr:.1f}"
                         f":attack={ca:.1f}:release={crel:.1f}:makeup={10**(mk/20):.4f}")

        # De-esser (high-pass shelving compressor on the sibilant range)
        if self.deess_on.get():
            df = self.deess_freq.get()
            dt = self.deess_thresh.get()
            parts.append(f"deesser=i={dt:.2f}:m=s:f={df:.0f}")

        # Limiter
        if self.limit_on.get():
            lt = self.limit_thresh.get()
            parts.append(f"alimiter=level_in=1:level_out={10**(lt/20):.6f}:limit=1:attack=5:release=50")

        return ",".join(parts) if parts else "anull"

    def _update_filter_preview(self):
        filt = self._build_filter()
        short = filt[:180] + "…" if len(filt) > 180 else filt
        self.filter_preview.config(text=f"Filter chain:  {short}")

    # ─────────────────────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.aac *.flac"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_dynamics.mp4")
        self._update_filter_preview()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4","*.mp4"),
                                                     ("MP3","*.mp3"),
                                                     ("WAV","*.wav")])
        if p: self.out_var.set(p)

    def _preview(self):
        """Export first 10 seconds with the chain applied for a quick listen."""
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("common.no_input"))
            return
        tmp = tempfile.mktemp(suffix="_preview.mp3")
        filt = self._build_filter()
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path, "-t", "10",
               "-af", filt, t("dynamics.c_a"), "libmp3lame", t("dynamics.b_a"), "192k",
               "-vn", tmp, "-y"]
        self.log(self.console, t("log.dynamics.rendering_10s_preview"))

        def done(rc):
            if rc == 0 and os.path.exists(tmp):
                open_in_explorer(tmp)
            else:
                self.show_result(rc)
        self.run_ffmpeg(cmd, self.console, on_done=done)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4","*.mp4")])
        if not out: return
        self.out_var.set(out)

        filt   = self._build_filter()
        ffmpeg = get_binary_path("ffmpeg.exe")
        ext    = os.path.splitext(out)[1].lower()

        if ext in (".mp3",):
            cmd = [ffmpeg, "-i", self.file_path, "-af", filt,
                   "-vn", t("dynamics.c_a"), "libmp3lame", t("dynamics.b_a"), "320k", "-movflags", t("dynamics.faststart"), out, "-y"]
        elif ext in (".wav",):
            cmd = [ffmpeg, "-i", self.file_path, "-af", filt,
                   "-vn", t("dynamics.c_a"), "pcm_s16le", "-movflags", t("dynamics.faststart"), out, "-y"]
        else:
            cmd = [ffmpeg, "-i", self.file_path, "-af", filt,
                   t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, t("log.dynamics.applying_audio_dynamics_chain"))
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label=t("dynamics.btn_apply_dynamics"))
