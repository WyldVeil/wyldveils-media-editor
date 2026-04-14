"""
tab_voiceisolation.py  ─  Voice Isolation / Background Noise Removal
Uses FFmpeg's arnndn (AI Recurrent Neural Network Denoiser for audio)
filter to remove background noise while preserving voice quality.

This is entirely different from the AudioDynamics gate/EQ:
  • arnndn uses a pre-trained neural network (RNNoise model)
  • Works on random, non-tonal noise (fans, traffic, HVAC, crowd)
  • Doesn't need threshold tuning - the model does the work
  • Industry equivalent of iZotope RX, Adobe Enhance, FCP Voice Isolation

Also includes:
  • Conventional spectral noise reduction (anlmdn) as an alternative
  • Noise print mode (learn silence, subtract from speech)
  • Output as cleaned audio-only OR full video with cleaned track
  • Blend control (mix cleaned + original for naturalness)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW, open_in_explorer
from core.i18n import t


# ── Built-in arnndn model paths ───────────────────────────────────────────
# FFmpeg ships with these models if compiled with --enable-librnnoise
# We also bundle the path to a common community model.
ARNNDN_MODELS = {
    "Default  (built-in RNNoise)":         None,          # uses built-in
    t("voice_isolation.bd_babble_crowd_noise"):           "bd.rnnn",
    t("voice_isolation.cb_cb_band_radio_noise"):          "cb.rnnn",
    t("voice_isolation.cd_conference_room_hvac"):       "cd.rnnn",
    t("voice_isolation.dn_dense_noise"):                  "dn.rnnn",
    t("voice_isolation.lapse_wind_lapse_noise"):             "lapse.rnnn",
    t("voice_isolation.mp_music_people_noise"):         "mp.rnnn",
    t("voice_isolation.sp_street_traffic_noise"):         "sp.rnnn",
    "Custom model (.rnnn file)":            "custom",
}

METHODS = {
    t("voice_isolation.arnndn_option"): "arnndn",
    t("voice_isolation.anlmdn_option"): "anlmdn",
    t("voice_isolation.afftdn_option"): "afftdn",
}


class VoiceIsolationTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path      = ""
        self.custom_model   = ""
        self.preview_proc   = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎙  " + t("tab.voice_isolation"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("voice_isolation.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Method ───────────────────────────────────────────────────────
        meth_lf = tk.LabelFrame(self, text=f"  {t('voice_isolation.method_section')}  ",
                                 padx=14, pady=10)
        meth_lf.pack(fill="x", padx=16, pady=6)

        self.method_var = tk.StringVar(value=list(METHODS.keys())[0])
        for key in METHODS:
            rb = tk.Radiobutton(meth_lf, text=key, variable=self.method_var,
                                value=key, font=(UI_FONT, 10),
                                command=self._on_method_change)
            rb.pack(anchor="w", pady=1)

        # Method descriptions
        descs = {
            "arnndn": ("Best overall quality. Uses a pre-trained recurrent neural "
                       "network (RNNoise). Excellent for fans, HVAC, traffic, crowd. "
                       "Requires FFmpeg built with --enable-librnnoise."),
            "anlmdn": ("Non-Local Means spectral denoiser. No external library needed. "
                       "Good for steady broadband hiss (tape hiss, mic self-noise). "
                       "More configurable than arnndn."),
            "afftdn": ("FFT-based spectral subtraction. Analyses a noise floor snapshot "
                       "and subtracts it. Excellent for tonal noise (AC hum, computer fan). "
                       "Set noise floor via the 'Learn noise' button."),
        }
        self.method_desc_lbl = tk.Label(meth_lf, text=descs["arnndn"],
                                         fg=CLR["fgdim"], font=(UI_FONT, 8),
                                         wraplength=700, justify="left")
        self.method_desc_lbl.pack(anchor="w", pady=(4, 0))
        self._method_descs = descs

        # ── arnndn options ────────────────────────────────────────────────
        self.arnndn_lf = tk.LabelFrame(self, text=f"  {t('voice_isolation.arnndn_section')}  ",
                                        padx=14, pady=8)
        self.arnndn_lf.pack(fill="x", padx=16, pady=4)

        m0 = tk.Frame(self.arnndn_lf); m0.pack(fill="x", pady=3)
        tk.Label(m0, text=t("voice_isolation.noise_model_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.model_var = tk.StringVar(value=list(ARNNDN_MODELS.keys())[0])
        model_cb = ttk.Combobox(m0, textvariable=self.model_var,
                                 values=list(ARNNDN_MODELS.keys()),
                                 state="readonly", width=36)
        model_cb.pack(side="left", padx=8)
        model_cb.bind("<<ComboboxSelected>>", self._on_model_change)

        self.custom_model_f = tk.Frame(self.arnndn_lf)
        tk.Label(self.custom_model_f, text=t("voice_isolation.model_file_label")).pack(side="left")
        self.custom_model_var = tk.StringVar()
        tk.Entry(self.custom_model_f, textvariable=self.custom_model_var,
                 width=40).pack(side="left", padx=6)
        tk.Button(self.custom_model_f, text=t("btn.browse"),
                  command=self._browse_model).pack(side="left")

        m1 = tk.Frame(self.arnndn_lf); m1.pack(fill="x", pady=3)
        tk.Label(m1, text=t("voice_isolation.blend_label"),
                 font=(UI_FONT, 9, "bold")).pack(side="left")
        self.blend_var = tk.DoubleVar(value=0.0)
        tk.Scale(m1, variable=self.blend_var, from_=0.0, to=1.0,
                 resolution=0.05, orient="horizontal", length=200).pack(side="left", padx=8)
        self.blend_lbl = tk.Label(m1, text=t("voice_isolation.0_original"), width=12, fg=CLR["accent"])
        self.blend_lbl.pack(side="left")
        self.blend_var.trace_add("write", lambda *_: self.blend_lbl.config(
            text=f"{int(self.blend_var.get()*100)}% original"))

        # ── anlmdn options ────────────────────────────────────────────────
        self.anlmdn_lf = tk.LabelFrame(self, text=f"  {t('voice_isolation.anlmdn_section')}  ",
                                        padx=14, pady=8)
        for lbl, attr, lo, hi, default, res in [
            (t("voice_isolation.strength_label"),       "anlmdn_s",   0.00001, 0.001, 0.00015, 0.00001),
            (t("voice_isolation.patch_size_label"),     "anlmdn_p",   0.001,   0.1,   0.002,   0.001),
            (t("voice_isolation.research_size_label"),  "anlmdn_r",   0.001,   0.5,   0.006,   0.001),
        ]:
            row = tk.Frame(self.anlmdn_lf); row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, width=20, anchor="e").pack(side="left")
            var = tk.DoubleVar(value=default)
            setattr(self, attr, var)
            tk.Scale(row, variable=var, from_=lo, to=hi,
                     resolution=res, orient="horizontal", length=220).pack(side="left", padx=6)

        # ── afftdn options ────────────────────────────────────────────────
        self.afftdn_lf = tk.LabelFrame(self, text=f"  {t('voice_isolation.afftdn_section')}  ",
                                        padx=14, pady=8)
        af_row = tk.Frame(self.afftdn_lf); af_row.pack(fill="x", pady=3)
        tk.Label(af_row, text=t("voice_isolation.noise_floor_label"), font=(UI_FONT, 10)).pack(side="left")
        self.afftdn_noise_var = tk.StringVar(value="-30")
        tk.Entry(af_row, textvariable=self.afftdn_noise_var, width=6, relief="flat").pack(side="left", padx=4)
        tk.Label(af_row, text=f"  {t('voice_isolation.reduction_label')}").pack(side="left", padx=(10, 0))
        self.afftdn_reduction_var = tk.StringVar(value="12")
        tk.Entry(af_row, textvariable=self.afftdn_reduction_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(self.afftdn_lf,
                 text=t("voice_isolation.tip_record_1_2_seconds_of_room_noise_alone"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

        # ── Output options ────────────────────────────────────────────────
        out_opts = tk.LabelFrame(self, text=f"  {t('voice_isolation.output_mode_section')}  ", padx=14, pady=8)
        out_opts.pack(fill="x", padx=16, pady=4)

        oo0 = tk.Frame(out_opts); oo0.pack(fill="x", pady=3)
        self.out_mode_var = tk.StringVar(value=t("voice_isolation.full_video_option"))
        for m in [t("voice_isolation.full_video_option"),
                  t("voice_isolation.audio_mp3_option"), t("voice_isolation.audio_wav_option")]:
            tk.Radiobutton(oo0, text=m, variable=self.out_mode_var,
                           value=m).pack(side="left", padx=12)

        of = tk.Frame(self); of.pack(fill="x", padx=16, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("voice_isolation.preview_button"),
                  bg=CLR["accent"], fg="white", width=14,
                  command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("voice_isolation.clean_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#1B5E20", fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_method_change()

    # ─────────────────────────────────────────────────────────────────────
    def _on_method_change(self, *_):
        mkey = self.method_var.get()
        mval = METHODS[mkey]
        self.method_desc_lbl.config(text=self._method_descs.get(mval, ""))

        self.arnndn_lf.pack_forget()
        self.anlmdn_lf.pack_forget()
        self.afftdn_lf.pack_forget()

        if mval == "arnndn":
            self.arnndn_lf.pack(fill="x", padx=16, pady=4)
        elif mval == "anlmdn":
            self.anlmdn_lf.pack(fill="x", padx=16, pady=4)
        else:
            self.afftdn_lf.pack(fill="x", padx=16, pady=4)

    def _on_model_change(self, *_):
        if self.model_var.get() == "Custom model (.rnnn file)":
            self.custom_model_f.pack(fill="x", pady=4)
        else:
            self.custom_model_f.pack_forget()

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.aac *.flac"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_cleaned.mp4")

    def _browse_model(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("voice_isolation.rnnoise_model"), "*.rnnn"), ("All", t("ducker.item_2"))])
        if p:
            self.custom_model = p
            self.custom_model_var.set(p)

    def _browse_out(self):
        mode = self.out_mode_var.get()
        ext  = ".mp3" if mode == t("voice_isolation.audio_mp3_option") else (".wav" if mode == t("voice_isolation.audio_wav_option") else ".mp4")
        p = filedialog.asksaveasfilename(defaultextension=ext,
                                          filetypes=[("Media", f"*{ext}")])
        if p: self.out_var.set(p)

    def _build_af(self):
        """Build the audio filter string based on current settings."""
        mkey = self.method_var.get()
        mval = METHODS[mkey]

        if mval == "arnndn":
            model_key = self.model_var.get()
            model_file = ARNNDN_MODELS.get(model_key)
            if model_file == "custom":
                model_file = self.custom_model
            if model_file and os.path.exists(str(model_file)):
                base_filter = f"arnndn=model={model_file}"
            else:
                base_filter = "arnndn"   # use built-in default model

            blend = self.blend_var.get()
            if blend > 0.01:
                # Mix cleaned + original
                return (f"asplit=2[clean_in][orig];"
                        f"[clean_in]{base_filter}[clean_out];"
                        f"[clean_out][orig]amix=inputs=2:"
                        f"weights={1-blend:.3f}+{blend:.3f}[aout]"), True
            else:
                return base_filter, False

        elif mval == "anlmdn":
            s   = self.anlmdn_s.get()
            p   = self.anlmdn_p.get()
            r   = self.anlmdn_r.get()
            return f"anlmdn=s={s:.6f}:p={p:.4f}:r={r:.4f}", False

        else:  # afftdn
            nf  = self.afftdn_noise_var.get()
            red = self.afftdn_reduction_var.get()
            return f"afftdn=nf={nf}:nr={red}", False

    def _build_cmd(self, out, limit_duration=None):
        af_result = self._build_af()
        if isinstance(af_result, tuple):
            af, is_complex = af_result
        else:
            af, is_complex = af_result, False

        ffmpeg   = get_binary_path("ffmpeg.exe")
        mode     = self.out_mode_var.get()
        audio_only = mode in (t("voice_isolation.audio_mp3_option"), t("voice_isolation.audio_wav_option"))
        ext      = os.path.splitext(out)[1].lower()

        cmd = [ffmpeg, "-i", self.file_path]
        if limit_duration:
            cmd += ["-t", str(limit_duration)]

        if is_complex:
            cmd += ["-filter_complex", af, "-map", "[aout]"]
            if not audio_only:
                cmd += ["-map", "0:v"]
        else:
            cmd += ["-af", af]

        if audio_only:
            if mode == t("voice_isolation.audio_mp3_option"):
                cmd += ["-vn", "-c:a", "libmp3lame", "-b:a", "320k"]
            else:
                cmd += ["-vn", "-c:a", "pcm_s16le"]
        else:
            if is_complex:
                cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "256k"]
            else:
                cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "256k"]

        cmd += [out, "-y"]
        return cmd

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("waveform.no_file_message"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        tmp  = tempfile.mktemp(suffix="_preview.mp3")
        cmd  = self._build_cmd(tmp, limit_duration=15)
        self.log(self.console, t("log.voice_isolation.rendering_15s_preview"))

        def done(rc):
            if rc == 0 and os.path.exists(tmp):
                open_in_explorer(tmp)
        self.run_ffmpeg(cmd, self.console, on_done=done)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        cmd = self._build_cmd(out)
        mkey = self.method_var.get()
        self.log(self.console, f"Method: {mkey}")

        if "arnndn" in METHODS.get(mkey, ""):
            self.log(self.console,
                     "⚠  If this fails, your FFmpeg may not have RNNoise support. "
                     "Try the anlmdn method instead.")

        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label=t("voice_isolation.clean_button"))
