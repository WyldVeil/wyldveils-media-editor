"""
tab_denoise.py  ─  Denoise
Two industry-standard denoising algorithms:
  • HQDN3D  - fast, good for moderate noise (compression artefacts, mild grain)
  • NLMeans - slow, excellent quality (film grain, low-light sensor noise)

Per-channel luma/chroma control, live preview, strength presets.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


PRESETS = {
    t("denoise.light_touch_compression_artefacts"):  ("hqdn3d", 2, 2, 3, 3),
    t("denoise.moderate_webcam_phone_noise"):   ("hqdn3d", 4, 4, 6, 6),
    t("denoise.strong_low_light_footage"):      ("hqdn3d", 8, 8, 12, 12),
    t("denoise.aggressive_very_noisy_old_vhs"):   ("hqdn3d", 14, 14, 20, 20),
    t("denoise.nlmeans_light_film_grain_subtle"):   ("nlmeans", 4, 4, None, None),
    t("denoise.nlmeans_strong_heavy_sensor_noise"):   ("nlmeans", 8, 8, None, None),
    "Custom":                                  None,
}


class DenoiseTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path   = ""
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🌫  " + t("tab.denoise"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("denoise.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Algorithm choice ─────────────────────────────────────────────
        algo_lf = tk.LabelFrame(self, text=t("section.algorithm"), padx=16, pady=10)
        algo_lf.pack(fill="x", padx=20, pady=6)

        self.algo_var = tk.StringVar(value="hqdn3d")
        algo_row = tk.Frame(algo_lf); algo_row.pack(fill="x")
        for val, label, desc in [
            ("hqdn3d",  t("denoise.hqdn3d_option"),
             t("denoise.hqdn3d_hint")),
            ("nlmeans", t("denoise.nlmeans_option"),
             t("denoise.nlmeans_hint")),
        ]:
            col = tk.Frame(algo_row)
            col.pack(side="left", padx=20)
            tk.Radiobutton(col, text=label, variable=self.algo_var, value=val,
                           font=(UI_FONT, 11, "bold"),
                           command=self._on_algo_change).pack(anchor="w")
            tk.Label(col, text=desc, fg=CLR["fgdim"],
                     font=(UI_FONT, 8), wraplength=260, justify="left").pack(anchor="w")

        # ── Strength presets ─────────────────────────────────────────────
        preset_lf = tk.LabelFrame(self, text=f"  {t('denoise.strength_presets_section')}  ", padx=16, pady=8)
        preset_lf.pack(fill="x", padx=20, pady=4)

        self.preset_var = tk.StringVar(value=list(PRESETS.keys())[1])
        preset_cb = ttk.Combobox(preset_lf, textvariable=self.preset_var,
                                  values=list(PRESETS.keys()),
                                  state="readonly", width=44)
        preset_cb.pack(side="left")
        preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)

        # ── HQDN3D manual controls ────────────────────────────────────────
        self.hqdn3d_lf = tk.LabelFrame(self, text=f"  {t('denoise.hqdn3d_controls_section')}  ",
                                        padx=16, pady=10)
        self.hqdn3d_lf.pack(fill="x", padx=20, pady=4)

        slider_info = [
            (t("denoise.denoise_luma_spatial_label"),   "hs_luma_s",   0, 20, 4.0,
             t("denoise.removes_static_luma_brightness_noise_within_each")),
            (t("denoise.denoise_luma_temporal_label"),  "hs_luma_t",   0, 20, 6.0,
             t("denoise.blends_luma_across_frames_great_for_flickering_f")),
            (t("denoise.denoise_chroma_spatial_label"), "hs_chroma_s", 0, 20, 4.0,
             t("denoise.removes_colour_noise_within_each_frame")),
            (t("denoise.denoise_chroma_temporal_label"),"hs_chroma_t", 0, 20, 6.0,
             t("denoise.blends_colour_noise_across_frames")),
        ]

        self._hqdn3d_vars = {}
        self._hqdn3d_lbls = {}

        for label, attr, lo, hi, default, tip in slider_info:
            row = tk.Frame(self.hqdn3d_lf); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=16, anchor="e").pack(side="left")
            var = tk.DoubleVar(value=default)
            self._hqdn3d_vars[attr] = var
            sl = tk.Scale(row, variable=var, from_=lo, to=hi,
                          resolution=0.5, orient="horizontal", length=260,
                          command=lambda v, a=attr: self._on_slider(a))
            sl.pack(side="left", padx=6)
            lbl = tk.Label(row, text=str(default), width=5, fg=CLR["accent"])
            lbl.pack(side="left")
            self._hqdn3d_lbls[attr] = lbl
            tk.Label(row, text=tip, fg=CLR["fgdim"],
                     font=(UI_FONT, 8)).pack(side="left", padx=6)

        # ── NLMeans controls ──────────────────────────────────────────────
        self.nlmeans_lf = tk.LabelFrame(self, text=f"  {t('denoise.nlmeans_controls_section')}  ",
                                         padx=16, pady=10)
        # (shown only when NLMeans selected)

        nm_slider_info = [
            (t("denoise.denoise_nlmeans_luma_label"),   "nm_luma",   1, 20, 4,
             t("denoise.denoising_strength_for_brightness_channel_h_para")),
            (t("denoise.denoise_nlmeans_chroma_label"), "nm_chroma", 1, 20, 4,
             t("denoise.denoising_strength_for_colour_channels")),
        ]
        self._nlmeans_vars = {}
        self._nlmeans_lbls = {}

        for label, attr, lo, hi, default, tip in nm_slider_info:
            row = tk.Frame(self.nlmeans_lf); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=16, anchor="e").pack(side="left")
            var = tk.IntVar(value=default)
            self._nlmeans_vars[attr] = var
            sl = tk.Scale(row, variable=var, from_=lo, to=hi,
                          resolution=1, orient="horizontal", length=260,
                          command=lambda v, a=attr: self._on_nm_slider(a))
            sl.pack(side="left", padx=6)
            lbl = tk.Label(row, text=str(default), width=5, fg=CLR["accent"])
            lbl.pack(side="left")
            self._nlmeans_lbls[attr] = lbl
            tk.Label(row, text=tip, fg=CLR["fgdim"],
                     font=(UI_FONT, 8)).pack(side="left", padx=6)

        tk.Label(self.nlmeans_lf,
                 text=t("denoise.nlmeans_warning"),
                 fg=CLR["orange"], font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=4)

        # ── Live filter string display ────────────────────────────────────
        self.filter_lbl = tk.Label(self,
                                    text="", fg=CLR["fgdim"],
                                    font=(MONO_FONT, 9))
        self.filter_lbl.pack(anchor="w", padx=22, pady=(0, 4))

        # ── Encode options ────────────────────────────────────────────────
        enc_f = tk.Frame(self); enc_f.pack(padx=20, fill="x")
        tk.Label(enc_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(enc_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(enc_f, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_enc_var = tk.StringVar(value="medium")
        ttk.Combobox(enc_f, textvariable=self.preset_enc_var,
                     values=["ultrafast","fast","medium","slow","slower"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("denoise.preview_button"), bg=CLR["accent"], fg="white",
                  width=14, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("denoise.apply_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_algo_change()
        self._update_filter_lbl()

    # ─────────────────────────────────────────────────────────────────────
    def _on_algo_change(self):
        if self.algo_var.get() == "hqdn3d":
            self.nlmeans_lf.pack_forget()
            self.hqdn3d_lf.pack(fill="x", padx=20, pady=4)
        else:
            self.hqdn3d_lf.pack_forget()
            self.nlmeans_lf.pack(fill="x", padx=20, pady=4)
        self._update_filter_lbl()

    def _on_slider(self, attr):
        val = self._hqdn3d_vars[attr].get()
        self._hqdn3d_lbls[attr].config(text=f"{val:.1f}")
        self._update_filter_lbl()

    def _on_nm_slider(self, attr):
        val = self._nlmeans_vars[attr].get()
        self._nlmeans_lbls[attr].config(text=str(val))
        self._update_filter_lbl()

    def _apply_preset(self, *_):
        p = PRESETS.get(self.preset_var.get())
        if not p: return
        algo, ls, lt, cs, ct = p[0], p[1], p[2], p[3], p[4]
        self.algo_var.set(algo)
        self._on_algo_change()
        if algo == "hqdn3d":
            self._hqdn3d_vars["hs_luma_s"].set(ls)
            self._hqdn3d_vars["hs_luma_t"].set(lt)
            self._hqdn3d_vars["hs_chroma_s"].set(cs or ls)
            self._hqdn3d_vars["hs_chroma_t"].set(ct or lt)
            for a in self._hqdn3d_lbls:
                self._hqdn3d_lbls[a].config(text=f"{self._hqdn3d_vars[a].get():.1f}")
        elif algo == "nlmeans":
            self._nlmeans_vars["nm_luma"].set(ls)
            self._nlmeans_vars["nm_chroma"].set(lt)
            for a in self._nlmeans_lbls:
                self._nlmeans_lbls[a].config(text=str(self._nlmeans_vars[a].get()))
        self._update_filter_lbl()

    def _build_filter(self):
        if self.algo_var.get() == "hqdn3d":
            ls = self._hqdn3d_vars["hs_luma_s"].get()
            lt = self._hqdn3d_vars["hs_luma_t"].get()
            cs = self._hqdn3d_vars["hs_chroma_s"].get()
            ct = self._hqdn3d_vars["hs_chroma_t"].get()
            return f"hqdn3d={ls:.1f}:{cs:.1f}:{lt:.1f}:{ct:.1f}"
        else:
            h  = self._nlmeans_vars["nm_luma"].get()
            hc = self._nlmeans_vars["nm_chroma"].get()
            return f"nlmeans=s={h}:sp=7:r=15:sc={hc}"

    def _update_filter_lbl(self):
        self.filter_lbl.config(text=f"Filter:  {self._build_filter()}")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_denoised.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("denoise.no_file_title"), t("denoise.no_file_message"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay = get_binary_path("ffplay.exe")
        vf = self._build_filter()
        cmd = [ffplay, "-i", self.file_path, "-vf", vf,
               "-window_title", t("denoise.denoise_preview"), "-x", "800", "-autoexit"]
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
        if self.algo_var.get() == "nlmeans":
            self.log(self.console, t("log.denoise.nlmeans_is_slow_this_will_take_a_while"))

        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_enc_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, f"Filter: {vf}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("denoise.apply_button"))
