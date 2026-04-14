"""
tab_mediagenerator.py  ─  Media Generator
Generate synthetic B-roll media: SMPTE Color Bars, Countdown Leaders, and Test Tones.
"""
import tkinter as tk
from tkinter import filedialog, ttk
import os
import subprocess

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t

PATTERNS_FFMPEG = {
    "smpte": "smptebars",
    "static": "nullsrc",
    "black": "color=c=black",
    "white": "color=c=white",
}

class MediaGeneratorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("mgen.title"), t("mgen.subtitle"), icon="🎨")

        f = tk.Frame(self, bg=CLR["bg"])
        f.pack(pady=10)

        tk.Label(f, text=t("mgen.visual_pattern"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=0, column=0, sticky="w", pady=5)
        self.pattern_var = tk.StringVar(value=t("mgen.pattern_smpte"))
        ttk.Combobox(f, textvariable=self.pattern_var, values=[t("media_gen.media_gen_mgen_pattern_smpte"), t("media_gen.media_gen_mgen_pattern_static"), t("media_gen.media_gen_mgen_pattern_black"), t("media_gen.media_gen_mgen_pattern_white")], state="readonly").grid(row=0, column=1)

        tk.Label(f, text=t("mgen.duration_seconds"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=1, column=0, sticky="w", pady=5)
        self.dur_var = tk.StringVar(value="10")
        tk.Entry(f, textvariable=self.dur_var, width=10).grid(row=1, column=1, sticky="w")

        tk.Label(f, text=t("mgen.add_tone"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=2, column=0, sticky="w", pady=5)
        self.tone_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f, variable=self.tone_var, bg=CLR["bg"], selectcolor=CLR["panel"]).grid(row=2, column=1, sticky="w")

        self.btn_render = tk.Button(self, text=t("mgen.btn_generate"), font=(UI_FONT, 11, "bold"), bg=CLR["green"], fg="white", command=self._render)
        self.btn_render.pack(pady=15)
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _render(self):
        out = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if not out: return

        ffmpeg = get_binary_path("ffmpeg.exe")
        dur = self.dur_var.get()
        pattern_name = self.pattern_var.get()

        # Map translated label back to internal slug
        _label_to_slug = {
            t("mgen.pattern_smpte"):   "smpte",
            t("mgen.pattern_static"):  "static",
            t("mgen.pattern_black"):   "black",
            t("mgen.pattern_white"):   "white",
        }
        slug = _label_to_slug.get(pattern_name, "smpte")

        # Build the lavfi source string - TV Static needs special handling since
        # it's a filtergraph (nullsrc → geq) and can't use the ":d=:s=" suffix form.
        if slug == "static":
            vf_input = f"nullsrc=s=1920x1080:d={dur},geq=random(1)*255:128:128"
        else:
            vf = PATTERNS_FFMPEG[slug]
            vf_input = f"{vf}:d={dur}:s=1920x1080"

        cmd = [ffmpeg, "-f", "lavfi", "-i", vf_input]
        if self.tone_var.get():
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={dur}"]
            cmd += ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", out, "-y"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", out, "-y"]

        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out), btn=self.btn_render)