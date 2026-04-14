"""
tab_colormatch.py  ─  Colour Match
Automatically match the colour grade of a source clip to a reference clip.

Method:
  1. Use ffprobe signalstats to extract per-channel mean and standard
     deviation from both source and reference (at a representative frame)
  2. Compute the linear transform needed for each channel:
       out = (in - src_mean) * (ref_std / src_std) + ref_mean
  3. Express that transform as a curves filter and apply it

This is the same statistical colour matching algorithm used in
DaVinci Resolve's "Colour Match" and Lightroom's "Match Exposure".

Optional: adjust match strength (blend with original via overlay).
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import json
import os
import re

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


def _get_frame_stats(ffmpeg_path, video_path, timestamp="0"):
    """
    Run signalstats on a single frame and return per-channel
    mean (YAVG, RAVG, GAVG, BAVG) and standard deviation.
    Returns dict with keys: Y, R, G, B each having 'mean' and 'std'.
    """
    cmd = [
        ffmpeg_path,
        "-ss", str(timestamp),
        "-i", video_path,
        "-vf", t("color_match.signalstats_stat_tout_brng_vrep"),
        t("smart_reframe.frames_v"), "30",   # analyse 30 frames for better average
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=CREATE_NO_WINDOW)
    output = result.stderr

    stats = {"Y": [], "R": [], "G": [], "B": []}
    for line in output.split("\n"):
        for ch, key in [("Y", "YAVG"), ("R", "RAVG"), ("G", "GAVG"), ("B", "BAVG")]:
            m = re.search(rf"{key}:(\d+\.?\d*)", line)
            if m:
                stats[ch].append(float(m.group(1)))

    result_stats = {}
    for ch in ["Y", "R", "G", "B"]:
        vals = stats[ch]
        if vals:
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = max(variance ** 0.5, 0.001)
        else:
            mean, std = 128.0, 32.0
        result_stats[ch] = {"mean": mean, "std": std}

    return result_stats


def _build_curves_filter(src_stats, ref_stats, channels, strength=1.0):
    """
    Build a curves filter that maps src colour stats to ref colour stats.
    Returns a string like: curves=red='0/0 0.5/0.6 1/1':green=...
    """
    parts = []
    channel_map = {"R": "red", "G": "green", "B": "blue"}

    for ch in channels:
        key = channel_map.get(ch)
        if not key:
            continue
        src_m = src_stats[ch]["mean"] / 255.0
        src_s = src_stats[ch]["std"]  / 255.0
        ref_m = ref_stats[ch]["mean"] / 255.0
        ref_s = ref_stats[ch]["std"]  / 255.0

        # Linear transform: out = (in - src_mean) * (ref_std/src_std) + ref_mean
        scale = ref_s / max(src_s, 0.001)
        scale = min(max(scale, 0.1), 5.0)   # clamp

        # Build 5-point curve: 0, 0.25, 0.5, 0.75, 1.0
        curve_points = []
        for x in [0.0, 0.25, 0.5, 0.75, 1.0]:
            y = (x - src_m) * scale + ref_m
            # Blend with identity based on strength
            y_blended = x + (y - x) * strength
            y_blended = min(max(y_blended, 0.0), 1.0)
            curve_points.append(f"{x:.3f}/{y_blended:.3f}")

        parts.append(f"{key}='{' '.join(curve_points)}'")

    if not parts:
        return None
    return "curves=" + ":".join(parts)


class ColorMatchTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.src_path = ""
        self.ref_path = ""
        self._src_stats = None
        self._ref_stats = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎨  " + t("tab.colour_match"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("color_match.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Input files ───────────────────────────────────────────────────
        inp = tk.LabelFrame(self, text=t("section.input_clips"), padx=14, pady=10)
        inp.pack(fill="x", padx=16, pady=8)

        for label, attr, hint in [
            (t("color_match.source_label"), "src",
             t("color_match.source_hint")),
            (t("color_match.reference_label"), "ref",
             t("color_match.reference_hint")),
        ]:
            row = tk.Frame(inp); row.pack(fill="x", pady=4)
            tk.Label(row, text=label, font=(UI_FONT, 9, "bold"),
                     width=32, anchor="w").pack(side="left")
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(row, textvariable=var, width=50, relief="flat").pack(side="left", padx=6)

            def _b(a=attr, v=var):
                p = filedialog.askopenfilename(
                    filetypes=[(t("color_match.video_image"),
                                "*.mp4 *.mov *.mkv *.avi *.webm *.jpg *.jpeg *.png"),
                               ("All", t("ducker.item_2"))])
                if p:
                    setattr(self, a + "_path", p)
                    v.set(p)
            tk.Button(row, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").pack(side="left")
            tk.Label(inp, text=f"  ℹ  {hint}", fg=CLR["fgdim"],
                     font=(UI_FONT, 8)).pack(anchor="w")

        # ── Analysis timestamps ───────────────────────────────────────────
        ts_lf = tk.LabelFrame(self, text=f"  {t('color_match.analysis_section')}  ", padx=14, pady=8)
        ts_lf.pack(fill="x", padx=16, pady=4)

        ts_row = tk.Frame(ts_lf); ts_row.pack(fill="x")
        tk.Label(ts_row, text=t("color_match.analyse_source_label")).pack(side="left")
        self.src_ts_var = tk.StringVar(value="0")
        tk.Entry(ts_row, textvariable=self.src_ts_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(ts_row, text=f"  {t('color_match.analyse_reference_label')}").pack(side="left", padx=(16, 0))
        self.ref_ts_var = tk.StringVar(value="0")
        tk.Entry(ts_row, textvariable=self.ref_ts_var, width=7, relief="flat").pack(side="left", padx=4)

        tk.Label(ts_lf,
                 text=("Choose a representative frame. Avoid fades, cuts, or unusually "
                        "dark or bright frames. A well-lit middle section works best."),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w", pady=(4, 0))

        # ── Match options ─────────────────────────────────────────────────
        opts = tk.LabelFrame(self, text=f"  {t('color_match.match_options_section')}  ", padx=14, pady=10)
        opts.pack(fill="x", padx=16, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("color_match.strength_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.strength_var = tk.DoubleVar(value=1.0)
        tk.Scale(r0, variable=self.strength_var, from_=0.1, to=1.0,
                 resolution=0.05, orient="horizontal", length=260).pack(side="left", padx=8)
        self.str_lbl = tk.Label(r0, text="100%", width=5, fg=CLR["accent"])
        self.str_lbl.pack(side="left")
        self.strength_var.trace_add("write", lambda *_: self.str_lbl.config(
            text=f"{int(self.strength_var.get()*100)}%"))
        tk.Label(r0, text=t("color_match.strength_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("color_match.channels_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.ch_vars = {}
        for ch, default in [("R", True), ("G", True), ("B", True)]:
            v = tk.BooleanVar(value=default)
            self.ch_vars[ch] = v
            tk.Checkbutton(r1, text=ch, variable=v,
                           font=(UI_FONT, 11, "bold")).pack(side="left", padx=8)
        tk.Label(r1, text=t("color_match.uncheck_to_preserve_a_channel"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        self.match_luma_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text=t("color_match.luma_checkbox"),
                       variable=self.match_luma_var).pack(side="left")

        # ── Stats display ─────────────────────────────────────────────────
        self.stats_lf = tk.LabelFrame(self, text=f"  {t('color_match.statistics_section')}  ",
                                       padx=14, pady=8)
        self.stats_lf.pack(fill="x", padx=16, pady=4)

        self.stats_text = tk.Text(self.stats_lf, height=4,
                                   bg=CLR["console_bg"], fg="#00FF88",
                                   font=(MONO_FONT, 9))
        self.stats_text.pack(fill="x")
        self.stats_text.insert(tk.END,
                                "Run 'Analyse' to see colour statistics…")
        self.stats_text.config(state="disabled")

        # ── Filter preview ────────────────────────────────────────────────
        self.filter_lbl = tk.Label(self, text="", fg=CLR["fgdim"],
                                    font=(MONO_FONT, 8), wraplength=900,
                                    justify="left")
        self.filter_lbl.pack(anchor="w", padx=18)

        # ── Output & buttons ──────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        self.btn_analyse = tk.Button(
            btn_row, text=t("color_match.analyse_button"),
            font=(UI_FONT, 10, "bold"),
            bg="#37474F", fg="white", width=20, height=2,
            command=self._analyse)
        self.btn_analyse.pack(side="left", padx=8)

        self.btn_render = tk.Button(
            btn_row, text=t("color_match.apply_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#AD1457", fg="white", height=2, width=24,
            command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _analyse(self):
        if not self.src_path or not self.ref_path:
            messagebox.showwarning(t("color_match.missing_files_title"),
                                   t("color_match.missing_files_message"))
            return
        self.btn_analyse.config(state="disabled", text=t("loudness.analysing_2"))
        self.log(self.console, t("log.color_match.extracting_colour_statistics"))

        def _work():
            ffmpeg = get_binary_path("ffmpeg.exe")
            try:
                src_stats = _get_frame_stats(ffmpeg, self.src_path,
                                              self.src_ts_var.get())
                ref_stats = _get_frame_stats(ffmpeg, self.ref_path,
                                              self.ref_ts_var.get())
                self._src_stats = src_stats
                self._ref_stats = ref_stats

                lines = [t("color_match.channel_source_mean_std_reference_mean_std")]
                lines.append("─" * 56)
                for ch in ["R", "G", "B", "Y"]:
                    sm = src_stats[ch]["mean"]
                    ss = src_stats[ch]["std"]
                    rm = ref_stats[ch]["mean"]
                    rs = ref_stats[ch]["std"]
                    lines.append(f"  {ch}      │  {sm:6.1f} / {ss:5.1f}        "
                                 f"│  {rm:6.1f} / {rs:5.1f}")

                self.after(0, lambda: self._show_stats("\n".join(lines)))

                # Build and preview filter
                channels = [ch for ch, v in self.ch_vars.items() if v.get()]
                filt = _build_curves_filter(src_stats, ref_stats,
                                            channels, self.strength_var.get())
                if filt:
                    self.after(0, lambda f=filt: self.filter_lbl.config(
                        text=f"Filter:  {f[:160]}…" if len(f) > 160 else f"Filter:  {f}"))

            except Exception as e:
                self.log(self.console, f"❌  Analysis error: {e}")
            finally:
                self.after(0, lambda: self.btn_analyse.config(
                    state="normal", text=t("color_match.analyse_button")))

        self.run_in_thread(_work)

    def _show_stats(self, text):
        self.stats_text.config(state="normal")
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, text)
        self.stats_text.config(state="disabled")
        self.log(self.console, t("log.color_match.analysis_complete"))

    def _render(self):
        if not self.src_path:
            messagebox.showwarning(t("color_match.missing_files_title"), t("color_match.missing_files_message"))
            return
        if self._src_stats is None or self._ref_stats is None:
            if messagebox.askyesno(t("color_match.not_analysed_title"),
                                   t("color_match.not_analysed_message")):
                self._analyse()
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        channels = [ch for ch, v in self.ch_vars.items() if v.get()]
        strength = self.strength_var.get()
        filt     = _build_curves_filter(self._src_stats, self._ref_stats,
                                        channels, strength)
        if not filt:
            messagebox.showwarning(t("color_match.no_filter_title"), t("color_match.no_filter_message"))
            return

        # Also match luma via eq brightness if requested
        if self.match_luma_var.get():
            src_y = self._src_stats["Y"]["mean"] / 255.0
            ref_y = self._ref_stats["Y"]["mean"] / 255.0
            brightness_delta = (ref_y - src_y) * strength
            filt += f",eq=brightness={brightness_delta:.3f}"

        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.src_path, "-vf", filt,
               t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Applying colour match (strength {int(strength*100)}%)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label=t("color_match.apply_button"))
