"""
tab_transitionstudio.py  ─  Transition Studio

Apply cinematic transitions between two clips: wipes, slides, zooms,
spins, blur dissolves, glitch cuts, and more.  Preview any transition
before rendering.

Unlike the Crossfader (which joins N clips with one global transition),
the Transition Studio is designed for precise, per-cut transition work
with a visual preview of each effect.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import threading
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t


# ── Transition catalogue ─────────────────────────────────────────────────
TRANSITIONS = {
    "Dissolves": [
        ("fade",       "Fade",          "Classic opacity crossfade"),
        ("fadeblack",  "Fade to Black", "Fade through solid black"),
        ("fadewhite",  "Fade to White", "Fade through solid white"),
        ("fadegrays",  "Fade Grays",    "Fade through desaturated gray"),
        ("dissolve",   "Dissolve",      "Random pixel dissolve"),
    ],
    "Wipes": [
        ("wipeleft",   "Wipe Left",     "Wipe revealing from right to left"),
        ("wiperight",  "Wipe Right",    "Wipe revealing from left to right"),
        ("wipeup",     "Wipe Up",       "Wipe revealing from bottom to top"),
        ("wipedown",   "Wipe Down",     "Wipe revealing from top to bottom"),
    ],
    "Slides": [
        ("slideleft",  "Slide Left",    "Clip B slides in from the right"),
        ("slideright", "Slide Right",   "Clip B slides in from the left"),
        ("slideup",    "Slide Up",      "Clip B slides in from below"),
        ("slidedown",  "Slide Down",    "Clip B slides in from above"),
    ],
    "Shape": [
        ("circlecrop",  "Circle Crop",   "Circular reveal from center"),
        ("circleopen",  "Circle Open",   "Circle expanding outward"),
        ("circleclose", "Circle Close",  "Circle shrinking inward"),
        ("radial",      "Radial",        "Clock-wipe radial sweep"),
    ],
    "Stylized": [
        ("pixelize",    "Pixelize",      "Pixelation transition"),
        ("smoothleft",  "Smooth Left",   "Smooth directional blur left"),
        ("smoothright", "Smooth Right",  "Smooth directional blur right"),
        ("hblur",       "H-Blur",        "Horizontal blur transition"),
    ],
}


class TransitionStudioTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_a = ""
        self.file_b = ""
        self.dur_a = 0.0
        self.dur_b = 0.0
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.transition_studio"),
                         t("transitions.subtitle"),
                         icon="🎞")

        # ── Clip A & B ────────────────────────────────────────────────────
        clips_lf = tk.LabelFrame(self, text=f"  {t('transitions.source_clips_section')}  ", padx=15, pady=8,
                                 font=(UI_FONT, 9, "bold"))
        clips_lf.pack(fill="x", padx=20, pady=(10, 4))

        # Clip A
        ra = tk.Frame(clips_lf)
        ra.pack(fill="x", pady=3)
        tk.Label(ra, text=t("transitions.clip_a_label"), font=(UI_FONT, 10, "bold"),
                 width=16, anchor="e").pack(side="left")
        self._src_a_var = tk.StringVar()
        tk.Entry(ra, textvariable=self._src_a_var, width=50, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(ra, text=t("btn.browse"), command=lambda: self._browse("a"),
                  cursor="hand2", relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._dur_a_lbl = tk.Label(ra, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._dur_a_lbl.pack(side="left", padx=8)

        # Clip B
        rb = tk.Frame(clips_lf)
        rb.pack(fill="x", pady=3)
        tk.Label(rb, text=t("transitions.clip_b_label"), font=(UI_FONT, 10, "bold"),
                 width=16, anchor="e").pack(side="left")
        self._src_b_var = tk.StringVar()
        tk.Entry(rb, textvariable=self._src_b_var, width=50, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(rb, text=t("btn.browse"), command=lambda: self._browse("b"),
                  cursor="hand2", relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._dur_b_lbl = tk.Label(rb, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._dur_b_lbl.pack(side="left", padx=8)

        # ── Transition picker ─────────────────────────────────────────────
        pick_lf = tk.LabelFrame(self, text=f"  {t('transitions.type_section')}  ", padx=15, pady=8,
                                font=(UI_FONT, 9, "bold"))
        pick_lf.pack(fill="x", padx=20, pady=6)

        # Category tabs
        self._trans_nb = ttk.Notebook(pick_lf)
        self._trans_nb.pack(fill="x")

        self._trans_var = tk.StringVar(value="fade")
        for cat_name, effects in TRANSITIONS.items():
            tab_f = tk.Frame(self._trans_nb, bg=CLR["bg"])
            self._trans_nb.add(tab_f, text=f"  {cat_name}  ")

            for i, (val, label, desc) in enumerate(effects):
                row = tk.Frame(tab_f, bg=CLR["bg"])
                row.pack(fill="x", pady=1, padx=4)
                tk.Radiobutton(row, text=label, variable=self._trans_var, value=val,
                               font=(UI_FONT, 10), bg=CLR["bg"],
                               activebackground=CLR["bg"]).pack(side="left")
                tk.Label(row, text=f"  {desc}", fg=CLR["fgdim"],
                         font=(UI_FONT, 9), bg=CLR["bg"]).pack(side="left")

        # ── Duration ──────────────────────────────────────────────────────
        dur_f = tk.Frame(self)
        dur_f.pack(fill="x", padx=20, pady=6)

        tk.Label(dur_f, text=t("transitions.duration_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._trans_dur = tk.DoubleVar(value=1.0)
        tk.Scale(dur_f, variable=self._trans_dur, from_=0.1, to=5.0,
                 resolution=0.1, orient="horizontal", length=250,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=8)
        self._dur_val_lbl = tk.Label(dur_f, text=t("transitions.1_0s"), fg=CLR["accent"],
                                     font=(MONO_FONT, 11, "bold"), width=5)
        self._dur_val_lbl.pack(side="left")
        self._trans_dur.trace_add("write",
            lambda *_: self._dur_val_lbl.config(
                text=f"{self._trans_dur.get():.1f}s"))

        # Quick buttons
        for val in [0.3, 0.5, 1.0, 1.5, 2.0, 3.0]:
            tk.Button(dur_f, text=f"{val}s", width=4, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9), cursor="hand2",
                      command=lambda v=val: self._trans_dur.set(v)
                      ).pack(side="left", padx=2)

        # ── Options ───────────────────────────────────────────────────────
        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=4)
        tk.Label(opt_f, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        self._audio_xfade = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("transitions.audio_xfade_checkbox"),
                       variable=self._audio_xfade,
                       font=(UI_FONT, 10)).pack(side="left", padx=20)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        tk.Button(bf, text=t("transitions.preview_button"), bg=CLR["accent"], fg="white",
                  width=22, font=(UI_FONT, 10), cursor="hand2",
                  command=self._preview).pack(side="left", padx=8)
        self._btn_run = tk.Button(
            bf, text=t("transitions.render_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack(side="left", padx=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Helpers ────────────────────────────────────────────────────────
    def _has_audio(self, path):
        """Return True if the file has at least one audio stream."""
        if not path:
            return False
        try:
            ffprobe = get_binary_path("ffprobe.exe")
            r = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=codec_type",
                 "-of", "csv=p=0", path],
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW)
            return bool(r.stdout.strip())
        except Exception:
            return False

    # ── Callbacks ──────────────────────────────────────────────────────
    def _browse(self, which):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        if not p:
            return
        if which == "a":
            self.file_a = p
            self._src_a_var.set(p)
            self.dur_a = get_video_duration(p)
            self._dur_a_lbl.config(text=f"{self.dur_a:.1f}s")
        else:
            self.file_b = p
            self._src_b_var.set(p)
            self.dur_b = get_video_duration(p)
            self._dur_b_lbl.config(text=f"{self.dur_b:.1f}s")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    def _build_cmd(self, out):
        ffmpeg = get_binary_path("ffmpeg")
        trans = self._trans_var.get()
        dur = self._trans_dur.get()
        crf = self._crf_var.get()

        # xfade offset = duration of clip A minus transition duration
        offset = max(0.0, self.dur_a - dur)

        fc_parts = [
            f"[0:v][1:v]xfade=transition={trans}:duration={dur}:offset={offset}[vout]"
        ]

        maps = ["-map", "[vout]"]

        if self._audio_xfade.get():
            # Only add audio crossfade if both clips have audio streams
            has_audio_a = self._has_audio(self.file_a)
            has_audio_b = self._has_audio(self.file_b)
            if has_audio_a and has_audio_b:
                fc_parts.append(
                    f"[0:a][1:a]acrossfade=d={dur}[aout]"
                )
                maps += ["-map", "[aout]"]

        cmd = [ffmpeg, "-i", self.file_a, "-i", self.file_b,
               "-filter_complex", ";".join(fc_parts)]
        cmd += maps
        cmd += ["-c:v", "libx264", "-crf", crf, "-preset", "fast"]
        if self._audio_xfade.get():
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", out, "-y"]
        return cmd

    def _validate(self):
        if not self.file_a:
            messagebox.showwarning(t("transitions.missing_title"), t("transitions.missing_clip_a"))
            return False
        if not self.file_b:
            messagebox.showwarning(t("transitions.missing_title"), t("transitions.missing_clip_b"))
            return False
        dur = self._trans_dur.get()
        if dur >= self.dur_a or dur >= self.dur_b:
            messagebox.showerror(t("transitions.too_long_title"), t("transitions.too_long_message"))
            return False
        return True

    def _preview(self):
        if not self._validate():
            return
        tmp = os.path.join(tempfile.gettempdir(), "_xfpro_trans_preview.mp4")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        cmd = self._build_cmd(tmp)
        self.log(self.console, f"Building preview: {self._trans_var.get()} ({self._trans_dur.get():.1f}s)…")

        def _done(rc):
            if rc == 0:
                if self.preview_proc:
                    try:
                        self.preview_proc.terminate()
                    except Exception:
                        pass
                self.preview_proc = launch_preview(tmp)
            else:
                self.log(self.console, t("log.transitions.preview_build_failed"))

        self.run_ffmpeg(cmd, self.console, on_done=_done)

    def _render(self):
        if not self._validate():
            return
        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        cmd = self._build_cmd(out)
        trans = self._trans_var.get()
        dur = self._trans_dur.get()
        self.log(self.console, f"Rendering: {trans} ({dur:.1f}s)")

        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label=t("transitions.render_button"))
