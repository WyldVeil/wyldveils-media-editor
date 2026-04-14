"""
tab_voicechanger.py  ─  Voice Changer & Modulator
Apply creative vocal effects like Pitch Shift, Robot, Chipmunk, or Echo.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t

PRESETS = {
    t("voice_changer.chipmunk_high_pitch"): "asetrate=48000*1.3,atempo=1/1.3",
    t("voice_changer.deep_anonymous_low_pitch"): "asetrate=48000*0.7,atempo=1/0.7",
    t("voice_changer.robot_metallic"): "tremolo=f=10:d=0.8,flanger=delay=5:depth=2:regen=50",
    t("voice_changer.stadium_echo"): "aecho=0.8:0.9:1000:0.3",
    t("voice_changer.demon_voice"): "asetrate=48000*0.6,atempo=1/0.6,aecho=0.8:0.9:500:0.4",
}

class VoiceChangerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.voice_changer"), t("voice_changer.subtitle"), icon="🎙️")
        
        self.src_var = tk.StringVar()
        file_row = self.make_file_row(self, "Input Video/Audio:", self.src_var, self._browse)
        file_row.pack(fill="x", padx=20, pady=8)

        opt_f = tk.Frame(self, bg=CLR["bg"])
        opt_f.pack(pady=10)
        tk.Label(opt_f, text=t("voice_changer.preset_label"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=10)
        self.preset_var = tk.StringVar(value="Chipmunk (High Pitch)")
        ttk.Combobox(opt_f, textvariable=self.preset_var, values=list(PRESETS.keys()), state="readonly", width=30).pack(side="left")

        self.btn_render = tk.Button(self, text=t("voice_changer.apply_button"), font=(UI_FONT, 11, "bold"), bg=CLR["green"], fg="white", command=self._render)
        self.btn_render.pack(pady=15)
        cf = tk.Frame(self, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse(self):
        p = filedialog.askopenfilename(filetypes=[("Media", "*.mp4 *.mov *.wav *.mp3")])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _render(self):
        if not self.file_path: return
        out = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4"), ("MP3", "*.mp3")])
        if not out: return

        ffmpeg = get_binary_path("ffmpeg.exe")
        af = PRESETS[self.preset_var.get()]
        
        cmd = [ffmpeg, "-i", self.file_path, "-af", af]
        if out.lower().endswith(".mp3"):
            cmd += ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
        else:
            cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        cmd += [out, "-y"]

        self.log(self.console, f"Applying filter: {af}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out), btn=self.btn_render)