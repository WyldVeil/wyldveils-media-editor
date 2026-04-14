"""
tab_resolutionscaler.py  ─  Resolution Scaler
Upscale or downscale video to any resolution with
Lanczos, bicubic, or Lanczos4 (best quality upscaling).
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


RES_PRESETS = [
    t("scaler.7680x4320_8k"), t("scaler.3840x2160_4k_uhd"), t("scaler.2560x1440_qhd_2k"),
    t("scaler.1920x1080_full_hd"), t("scaler.1280x720_hd"), t("scaler.854x480_sd"),
    t("scaler.640x360_360p"), t("smart_reframe.custom"),
]

ALGO = {
    t("scaler.lanczos_best_for_downscale"):   "lanczos",
    t("scaler.lanczos4_best_for_upscale"):    "lanczos4",  # Bug fix: was "lanczos"
    "Bicubic":                         "bicubic",
    t("scaler.bilinear_fastest"):              "bilinear",
    t("scaler.nearest_no_blur"):               "neighbor",
}


class ResolutionScalerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📐  " + t("tab.resolution_scaler"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("scaler.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Options
        opts = tk.LabelFrame(self, text=f"  {t('scaler.scale_options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("scaler.target_resolution_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.res_var = tk.StringVar(value=RES_PRESETS[3])
        res_cb = ttk.Combobox(r0, textvariable=self.res_var, values=RES_PRESETS,
                              state="readonly", width=26)
        res_cb.pack(side="left", padx=8)
        res_cb.bind("<<ComboboxSelected>>", self._on_res)

        tk.Label(r0, text="W:").pack(side="left", padx=(12, 0))
        self.w_var = tk.StringVar(value="1920")
        self.w_entry = tk.Entry(r0, textvariable=self.w_var, width=6, relief="flat")
        self.w_entry.pack(side="left", padx=2)
        tk.Label(r0, text="H:").pack(side="left")
        self.h_var = tk.StringVar(value="1080")
        self.h_entry = tk.Entry(r0, textvariable=self.h_var, width=6, relief="flat")
        self.h_entry.pack(side="left", padx=2)
        tk.Label(r0, text=t("scaler.auto_aspect_hint"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left", padx=6)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("scaler.scaling_algorithm_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.algo_var = tk.StringVar(value=list(ALGO.keys())[0])
        ttk.Combobox(r1, textvariable=self.algo_var, values=list(ALGO.keys()),
                     state="readonly", width=32).pack(side="left", padx=8)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        self.pad_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r2, text=t("scaler.pad_checkbox"),
                       variable=self.pad_var).pack(side="left")
        tk.Label(r2, text=t("rotate_flip.crf")).pack(side="left", padx=(15, 0))
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(r2, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(r2, text=t("rotate_flip.preset")).pack(side="left", padx=(10, 0))
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(r2, textvariable=self.preset_var,
                     values=["ultrafast", "fast", "medium", "slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("scaler.scale_video"), font=(UI_FONT, 12, "bold"),
            bg=CLR["accent"], fg="black", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_res(self, *_):
        v = self.res_var.get()
        if "Custom" not in v:
            m = re.match(r"(\d+)x(\d+)", v)
            if m:
                self.w_var.set(m.group(1))
                self.h_var.set(m.group(2))

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

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

        w = self.w_var.get(); h = self.h_var.get()
        try:
            int(w); int(h)
        except ValueError:
            messagebox.showwarning(t("scaler.invalid_title"),
                                   t("scaler.invalid_message"))
            return
        algo = ALGO[self.algo_var.get()]
        scale_f = f"scale={w}:{h}:flags={algo}"
        if self.pad_var.get():
            scale_f += f",pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path, "-vf", scale_f,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Scaling to {w}×{h} with {self.algo_var.get()}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label="📐  SCALE VIDEO")


# ─────────────────────────────────────────────────────────────────────────────

"""
tab_fpsinterpolator.py  ─  Framerate Interpolator
Change frame rate with motion-compensated interpolation (minterpolate)
or simple fps filter. Smooth 24→60fps conversions, slo-mo.
"""

FPS_PRESETS = {
    t("scaler.23_976_fps_film"):     23.976,
    t("scaler.24_fps_cinema"):       24,
    t("scaler.25_fps_pal_broadcast"):25,
    t("scaler.29_97_fps_ntsc"):      29.97,
    t("scaler.30_fps"):                30,
    t("scaler.50_fps_pal_hfr"):      50,
    t("scaler.59_94_fps"):             59.94,
    t("scaler.60_fps_gaming"):       60,
    t("scaler.120_fps_slow_mo"):     120,
    t("scaler.240_fps_extreme_slomo"):240,
    t("smart_reframe.custom"):               None,
}

MI_MODE = {
    t("scaler.blend_fast_smooth"):     "blend",
    t("scaler.dup_duplicate_frames"):   "dup",
    t("scaler.mci_motion_compensated"): "mci",
}


class FPSInterpolatorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text=t("scaler.framerate_interpolator"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("fps.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Options
        opts = tk.LabelFrame(self, text=f"  {t('scaler.fps_options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("fps.target_fps_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.fps_preset_var = tk.StringVar(value=list(FPS_PRESETS.keys())[5])
        fps_cb = ttk.Combobox(r0, textvariable=self.fps_preset_var,
                              values=list(FPS_PRESETS.keys()), state="readonly", width=28)
        fps_cb.pack(side="left", padx=8)
        fps_cb.bind("<<ComboboxSelected>>", self._on_fps_preset)
        self.fps_var = tk.StringVar(value="50")
        self.fps_entry = tk.Entry(r0, textvariable=self.fps_var, width=8, relief="flat")
        self.fps_entry.pack(side="left", padx=4)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("fps.method_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.method_var = tk.StringVar(value=t("fps.method_simple"))
        ttk.Combobox(r1, textvariable=self.method_var,
                     values=[t("scaler.scaler_fps_method_simple"),
                              t("scaler.scaler_fps_method_blend"),
                              t("scaler.scaler_fps_method_dup"),
                              t("scaler.scaler_fps_method_mci")],
                     state="readonly", width=40).pack(side="left", padx=8)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(r2, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(r2, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(r2, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)
        tk.Label(r2,
                 text=t("fps.mci_warning"),
                 fg=CLR["orange"], font=(UI_FONT, 9)).pack(side="left", padx=10)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("scaler.interpolate_fps"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_fps_preset(self, *_):
        v = FPS_PRESETS.get(self.fps_preset_var.get())
        if v:
            self.fps_var.set(str(v))

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

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

        fps = self.fps_var.get()
        method = self.method_var.get()
        ffmpeg = get_binary_path("ffmpeg.exe")

        if "Simple" in method:
            vf = f"fps={fps}"
        else:
            mi = "blend" if "blend" in method else ("dup" if "dup" in method else "mci")
            vf = f"minterpolate=fps={fps}:mi_mode={mi}"

        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(), "-preset", self.preset_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Interpolating to {fps} fps using {method}…")
        self.log(self.console, t("log.scaler.minterpolate_modes_can_be_slow_be_patient"))
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label="⚡  INTERPOLATE FPS")
