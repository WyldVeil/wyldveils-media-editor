"""
tab_audioducker.py  ─  Background Music Auto-Ducker
Automatically lowers background music whenever speech / audio is detected
in the main video track, using FFmpeg's sidechaincompress filter.

Classic YouTube workflow: voice commentary ducks the background music.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


PRESETS = {
    t("ducker.gentle_podcast"):     dict(threshold=0.025, ratio=4,  attack=20, release=600),
    t("ducker.standard_youtube"):   dict(threshold=0.015, ratio=8,  attack=10, release=300),
    t("ducker.aggressive_speech"):  dict(threshold=0.010, ratio=15, attack=5,  release=200),
    t("ducker.full_mute_on_voice"):   dict(threshold=0.010, ratio=20, attack=5,  release=150),
}


class AudioDuckerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    # ─── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎚  " + t("tab.music_ducker"),
                 font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner,
                 text=t("ducker.desc_header"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Source video ──────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=16, pady=8)
        tk.Label(sf, text=t("common.source_video"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse_src,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Music file ────────────────────────────────────────────────────────
        mf = tk.Frame(self)
        mf.pack(fill="x", padx=16, pady=4)
        tk.Label(mf, text=t("ducker.lbl_bg_music"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._music_var = tk.StringVar()
        tk.Entry(mf, textvariable=self._music_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(mf, text=t("btn.browse"), command=self._browse_music,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Preset selector ───────────────────────────────────────────────────
        pf = tk.Frame(self)
        pf.pack(fill="x", padx=16, pady=6)
        tk.Label(pf, text=t("common.preset"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._preset_var = tk.StringVar(value="Standard (YouTube)")
        preset_cb = ttk.Combobox(pf, textvariable=self._preset_var,
                                  values=list(PRESETS.keys()),
                                  state="readonly", width=26)
        preset_cb.pack(side="left", padx=8)
        preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)
        tk.Button(pf, text=t("ducker.btn_apply_preset"), command=self._apply_preset,
                  bg=CLR["panel"], fg=CLR["fg"], relief="flat").pack(side="left", padx=4)

        # ── Duck settings ─────────────────────────────────────────────────────
        settings_f = tk.LabelFrame(self, text=t("ducker.sect_duck_settings"), padx=16, pady=10)
        settings_f.pack(fill="x", padx=20, pady=8)

        # Music volume
        r1 = tk.Frame(settings_f)
        r1.pack(fill="x", pady=3)
        tk.Label(r1, text=t("ducker.lbl_music_volume"),
                 width=18, anchor="e").pack(side="left")
        self._music_vol = tk.DoubleVar(value=0.8)
        tk.Scale(r1, variable=self._music_vol, from_=0.0, to=1.5,
                 resolution=0.05, orient="horizontal",
                 length=200).pack(side="left", padx=8)
        self._music_vol_lbl = tk.Label(r1, text="80%", width=5, fg=CLR["accent"])
        self._music_vol_lbl.pack(side="left")
        self._music_vol.trace_add("write", lambda *_: self._music_vol_lbl.config(
            text=t("ducker.item").format(int(self._music_vol.get() * 100))))
        tk.Label(r1, text=t("ducker.desc_music_volume"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=12)

        # Sensitivity / threshold
        r2 = tk.Frame(settings_f)
        r2.pack(fill="x", pady=3)
        tk.Label(r2, text=t("ducker.lbl_sensitivity"),
                 width=18, anchor="e").pack(side="left")
        self._threshold = tk.DoubleVar(value=0.015)
        tk.Scale(r2, variable=self._threshold, from_=0.001, to=0.10,
                 resolution=0.001, orient="horizontal",
                 length=200).pack(side="left", padx=8)
        self._thresh_lbl = tk.Label(r2, text="0.015", width=6, fg=CLR["accent"])
        self._thresh_lbl.pack(side="left")
        self._threshold.trace_add("write", lambda *_: self._thresh_lbl.config(
            text="{:.3f}".format(self._threshold.get())))
        tk.Label(r2, text=t("ducker.desc_sensitivity"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=12)

        # Duck intensity / ratio
        r3 = tk.Frame(settings_f)
        r3.pack(fill="x", pady=3)
        tk.Label(r3, text=t("ducker.lbl_duck_intensity"),
                 width=18, anchor="e").pack(side="left")
        self._ratio = tk.DoubleVar(value=8.0)
        tk.Scale(r3, variable=self._ratio, from_=2.0, to=20.0,
                 resolution=1.0, orient="horizontal",
                 length=200).pack(side="left", padx=8)
        self._ratio_lbl = tk.Label(r3, text="8:1", width=5, fg=CLR["accent"])
        self._ratio_lbl.pack(side="left")
        self._ratio.trace_add("write", lambda *_: self._ratio_lbl.config(
            text=t("ducker.1").format(int(self._ratio.get()))))
        tk.Label(r3, text=t("ducker.desc_duck_intensity"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=12)

        # Attack / release
        r4 = tk.Frame(settings_f)
        r4.pack(fill="x", pady=3)
        tk.Label(r4, text=t("ducker.lbl_attack_ms"),
                 width=18, anchor="e").pack(side="left")
        self._attack = tk.StringVar(value="10")
        tk.Entry(r4, textvariable=self._attack, width=6,
                 relief="flat").pack(side="left", padx=8)
        tk.Label(r4, text=t("ducker.lbl_release_ms")).pack(side="left", padx=(16, 0))
        self._release = tk.StringVar(value="300")
        tk.Entry(r4, textvariable=self._release, width=6,
                 relief="flat").pack(side="left", padx=8)
        tk.Label(r4, text=t("ducker.desc_attack_release"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=12)

        # ── Options ───────────────────────────────────────────────────────────
        opt_f = tk.Frame(self)
        opt_f.pack(anchor="w", padx=16, pady=4)
        self._loop_music = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("ducker.opt_loop_music"),
                       variable=self._loop_music).pack(side="left")
        self._normalize = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f,
                       text=t("ducker.opt_normalize"),
                       variable=self._normalize).pack(side="left")

        # ── Output ────────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=16, pady=6)
        tk.Label(of, text=t("common.output_file"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Render button ──────────────────────────────────────────────────────
        self._btn_render = tk.Button(
            self, text=t("ducker.btn_duck_render"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="black",
            height=2, width=30,
            command=self._render)
        self._btn_render.pack(pady=10)

        # ── Console ───────────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─── Callbacks ────────────────────────────────────────────────────────────
    def _apply_preset(self, _event=None):
        p = PRESETS.get(self._preset_var.get())
        if p:
            self._threshold.set(p["threshold"])
            self._ratio.set(p["ratio"])
            self._attack.set(str(p["attack"]))
            self._release.set(str(p["release"]))

    def _browse_src(self):
        p = filedialog.askopenfilename(
            title="Select source video (with voice/speech)",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self._src_var.set(p)
            if not self._out_var.get():
                self._out_var.set(os.path.splitext(p)[0] + "_ducked.mp4")

    def _browse_music(self):
        p = filedialog.askopenfilename(
            title="Select background music",
            filetypes=[("Audio", "*.mp3 *.wav *.aac *.flac *.ogg *.m4a"),
                        (t("ducker.video_audio"), "*.mp4 *.mov *.mkv"),
                        ("All", t("ducker.item_2"))])
        if p:
            self._music_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p:
            self._out_var.set(p)

    # ─── Render ───────────────────────────────────────────────────────────────
    def _render(self):
        src   = self._src_var.get().strip()
        music = self._music_var.get().strip()
        out   = self._out_var.get().strip()

        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("ducker.msg_no_source"))
            return
        if not music or not os.path.exists(music):
            messagebox.showwarning(t("common.warning"), t("ducker.msg_no_music"))
            return
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        try:
            threshold = float(self._threshold.get())
            ratio     = float(self._ratio.get())
            attack    = float(self._attack.get())
            release   = float(self._release.get())
            music_vol = float(self._music_vol.get())
        except ValueError:
            messagebox.showwarning(t("common.warning"), t("ducker.msg_invalid_values"))
            return

        # Clamp to sidechaincompress valid ranges
        threshold = max(0.000976, min(1.0, threshold))
        ratio     = max(1.0, min(20.0, ratio))
        attack    = max(0.01, min(2000.0, attack))
        release   = max(0.01, min(9000.0, release))

        ffmpeg = get_binary_path("ffmpeg.exe")

        # ── Build FFmpeg command ───────────────────────────────────────────────
        # Input 0: source video (voice/speech audio on [0:a])
        # Input 1: background music
        cmd = [ffmpeg, "-y", "-i", src]
        if self._loop_music.get():
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", music]

        # Filter graph:
        #   [1:a]volume=X[music]
        #   → apply pre-gain to music
        #
        #   [music][0:a]sidechaincompress=....[ducked]
        #   → compress music using voice as the sidechain trigger
        #
        #   [0:a][ducked]amix=inputs=2:duration=first[mixed]
        #   → blend original voice + ducked music
        #
        #   (optional) [mixed]loudnorm=...[aout]

        fc_parts = [
            "[1:a]volume={:.3f}[music]".format(music_vol),
            (
                "[music][0:a]sidechaincompress="
                "threshold={th}:"
                "ratio={rt}:"
                "attack={at}:"
                "release={rl}[ducked]"
            ).format(th=threshold, rt=ratio, at=attack, rl=release),
            "[0:a][ducked]amix=inputs=2:duration=first[mixed]",
        ]

        if self._normalize.get():
            fc_parts.append("[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
            final_a = "[aout]"
        else:
            final_a = "[mixed]"

        fc = ";".join(fc_parts)

        cmd += [
            "-filter_complex", fc,
            "-map", "0:v",
            "-map", final_a,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart",
            out,
        ]

        self.log(self.console, "▶ Ducking music into: {}".format(
            os.path.basename(src)))
        self.log(self.console,
                 "  Threshold={th}  Ratio={rt}:1  "
                 "Attack={at}ms  Release={rl}ms  Music vol={mv:.0%}".format(
                     th=threshold, rt=int(ratio),
                     at=int(attack), rl=int(release), mv=music_vol))

        self.run_ffmpeg(
            cmd, self.console,
            on_done=lambda rc: self.show_result(rc, out),
            btn=self._btn_render,
            btn_label=t("ducker.btn_duck_render"),
        )
