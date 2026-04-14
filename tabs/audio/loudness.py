"""
tab_loudnessnorm.py  ─  Loudness Normalizer
Two-pass EBU R128 / ITU-R BS.1770 loudness normalization.
Also offers simple peak normalization mode.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import re
import os
import json
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# Standard broadcast targets
PRESETS = {
    t("loudness.streaming_spotify_apple_music_14_lufs"): (-14.0, -1.0, 11.0),
    t("loudness.youtube_podcast_16_lufs"):                 (-16.0, -1.5, 11.0),
    t("loudness.broadcast_tv_ebu_r128_23_lufs"):            (-23.0, -1.0,  7.0),
    t("loudness.broadcast_tv_atsc_a_85_us_24_lufs"):        (-24.0, -2.0,  7.0),
    t("loudness.film_27_lufs"):                               (-27.0, -2.0, 15.0),
    "Custom":                                        None,
}


class LoudnessNormTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔊  " + t("tab.loudness_normalizer"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("loudness.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Presets + targets
        opts = tk.LabelFrame(self, text=t("loudness.loudness_target_section"), padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("common.preset"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.preset_var = tk.StringVar(value=list(PRESETS.keys())[1])
        preset_cb = ttk.Combobox(r0, textvariable=self.preset_var,
                                  values=list(PRESETS.keys()), state="readonly", width=48)
        preset_cb.pack(side="left", padx=8)
        preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("loudness.target_lufs_label")).pack(side="left")
        self.lufs_var = tk.StringVar(value="-16.0")
        tk.Entry(r1, textvariable=self.lufs_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=t("loudness.true_peak_label")).pack(side="left")
        self.tp_var = tk.StringVar(value="-1.5")
        tk.Entry(r1, textvariable=self.tp_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=t("loudness.lra_label")).pack(side="left")
        self.lra_var = tk.StringVar(value="11.0")
        tk.Entry(r1, textvariable=self.lra_var, width=7, relief="flat").pack(side="left", padx=4)

        # Mode
        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        self.mode_var = tk.StringVar(value=t("loudness.ebu_r128_option"))
        tk.Label(r2, text=t("loudness.algorithm_label")).pack(side="left")
        for m in [t("loudness.ebu_r128_option"), t("loudness.simple_peak_option")]:
            tk.Radiobutton(r2, text=m, variable=self.mode_var, value=m).pack(side="left", padx=8)

        # Scan button
        self.btn_scan = tk.Button(opts, text=t("loudness.analyse_button"),
                                   bg="#333", fg=CLR["accent"],
                                   font=(UI_FONT, 9, "bold"), command=self._scan)
        self.btn_scan.pack(anchor="w", pady=5)

        # Scan results panel
        self.scan_frame = tk.LabelFrame(self, text=t("loudness.measured_section"), padx=12, pady=6)
        self.scan_frame.pack(fill="x", padx=20, pady=4)
        self.scan_lbl = tk.Label(self.scan_frame,
                                  text=t("loudness.run_analysis_hint"),
                                  fg=CLR["fgdim"], font=(MONO_FONT, 10))
        self.scan_lbl.pack(anchor="w")

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("loudness.normalize_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _apply_preset(self, *_):
        p = PRESETS.get(self.preset_var.get())
        if p:
            self.lufs_var.set(str(p[0]))
            self.tp_var.set(str(p[1]))
            self.lra_var.set(str(p[2]))

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.mp3 *.aac *.wav *.flac"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("MP3", "*.mp3"), ("WAV", "*.wav")])
        if p:
            self.out_var.set(p)

    def _scan(self):
        if not self.file_path:
            messagebox.showwarning(t("loudness.no_file_title"), t("loudness.no_file_message"))
            return
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path, "-af",
               t("loudness.loudnorm_i_23_tp_1_lra_11_print_format_summary"),
               "-f", "null", "-"]
        self.log(self.console, t("log.loudness.analysing_loudness"))
        self.btn_scan.config(state="disabled", text=t("loudness.analysing"))

        def do_scan():
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    creationflags=CREATE_NO_WINDOW)
            out = result.stderr
            patterns = {
                "Input Integrated": r"Input Integrated:\s+([-\d.]+)",
                "Input True Peak":  r"Input True Peak:\s+([-\d.]+)",
                "Input LRA":        r"Input LRA:\s+([-\d.]+)",
                "Input Threshold":  r"Input Threshold:\s+([-\d.]+)",
            }
            lines = []
            for label, pat in patterns.items():
                m = re.search(pat, out)
                val = m.group(1) if m else "N/A"
                lines.append(f"{label}: {val} LUFS" if "LRA" not in label or m else f"{label}: {val}")
            self.after(0, lambda: self.scan_lbl.config(text="  |  ".join(lines), fg=CLR["accent"]))
            self.after(0, lambda: self.log(self.console, t("log.loudness.analysis_complete")))
            self.after(0, lambda: self.btn_scan.config(state="normal", text=t("loudness.analyse_button")))

        self.run_in_thread(do_scan)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("loudness.no_file_title"), t("loudness.no_file_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)
        ffmpeg = get_binary_path("ffmpeg.exe")

        lufs = self.lufs_var.get()
        tp   = self.tp_var.get()
        lra  = self.lra_var.get()

        if self.mode_var.get() == t("loudness.simple_peak_option"):
            af = f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"
            cmd = [ffmpeg, "-i", self.file_path, "-af", af,
                   t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k", "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, f"Normalizing (simple) → {lufs} LUFS")
            self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                            btn=self.btn_render, btn_label=t("loudness.normalize_button"))
        else:
            # True two-pass: Pass 1 measures current levels, Pass 2 applies correction
            self.log(self.console, f"Two-pass normalizing → {lufs} LUFS")
            self.btn_render.config(state="disabled", text=t("loudness.analysing_2"))
            af_measure = (f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"
                          f":dual_mono=true:linear=true:print_format=json")
            cmd_p1 = [ffmpeg, "-i", self.file_path, "-af", af_measure,
                      "-f", "null", "-"]

            def _do_twopass():
                self.log(self.console, t("log.loudness.pass_1_measuring_input_loudness"))
                r1 = subprocess.run(cmd_p1, capture_output=True, text=True,
                                    creationflags=CREATE_NO_WINDOW)
                # Extract measured values from stderr JSON block
                measured = {}
                try:
                    # loudnorm prints JSON between { } in stderr
                    m = re.search(r'\{[^}]+\}', r1.stderr, re.DOTALL)
                    if m:
                        measured = json.loads(m.group(0))
                except Exception:
                    pass

                if measured:
                    il  = measured.get("input_i",  lufs)
                    tp2 = measured.get("input_tp", tp)
                    lra2= measured.get("input_lra", lra)
                    thr = measured.get("input_thresh", "-70.0")
                    off = measured.get("target_offset", "0.0")
                    self.after(0, lambda: self.log(self.console,
                        f"  Measured: I={il} LUFS  TP={tp2} dBTP  LRA={lra2}"))
                    af_p2 = (f"loudnorm=I={lufs}:TP={tp}:LRA={lra}"
                             f":dual_mono=true:linear=true"
                             f":measured_I={il}:measured_TP={tp2}"
                             f":measured_LRA={lra2}:measured_thresh={thr}"
                             f":offset={off}:print_format=summary")
                else:
                    # Fallback: single-pass if measurement failed
                    self.after(0, lambda: self.log(self.console,
                        t("log.loudness.measurement_parse_failed_applying_single_pass_norm")))
                    af_p2 = f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:dual_mono=true:linear=true"

                self.after(0, lambda: self.log(self.console, t("log.loudness.pass_2_applying_normalization")))
                cmd_p2 = [ffmpeg, "-i", self.file_path, "-af", af_p2,
                          t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k",
                          "-movflags", t("dynamics.faststart"), out, "-y"]
                self.after(0, lambda: self.btn_render.config(
                    state="normal", text=t("loudness.normalize_button")))
                self.after(0, lambda: self.run_ffmpeg(
                    cmd_p2, self.console,
                    on_done=lambda rc: self.show_result(rc, out),
                    btn=self.btn_render, btn_label=t("loudness.normalize_button")))

            self.run_in_thread(_do_twopass)
