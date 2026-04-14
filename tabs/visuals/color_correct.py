"""
tab_colorcorrector.py  ─  Basic Color Corrector
Interactive sliders for brightness, contrast, saturation, gamma,
highlights, shadows, and colour temperature using FFmpeg eq + curves.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


class ColorCorrectorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.preview_proc = None
        self._preview_job = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🌈  " + t("tab.basic_color_corrector"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("color_correct.desc"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=8)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=55, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Sliders ──────────────────────────────────────────────────────────
        sliders_lf = tk.LabelFrame(self, text=t("color_correct.sect_colour_controls"), padx=15, pady=8)
        sliders_lf.pack(fill="x", padx=20, pady=6)

        # Define: (label, attr, min, max, default, resolution)
        slider_defs = [
            ("Brightness",   "brightness",  -1.0,  1.0,   0.0,  0.01),
            ("Contrast",     "contrast",     0.0,  3.0,   1.0,  0.01),
            ("Saturation",   "saturation",   0.0,  3.0,   1.0,  0.01),
            ("Gamma",        "gamma",        0.1,  5.0,   1.0,  0.01),
            (t("color_correct.gamma_r"),      "gamma_r",      0.1,  5.0,   1.0,  0.01),
            (t("color_correct.gamma_g"),      "gamma_g",      0.1,  5.0,   1.0,  0.01),
            (t("color_correct.gamma_b"),      "gamma_b",      0.1,  5.0,   1.0,  0.01),
            (t("color_correct.hue_deg"),    "hue",        -180, 180.0,   0.0,  1.0),
        ]

        self.slider_vars = {}
        self.slider_lbls = {}

        grid = tk.Frame(sliders_lf)
        grid.pack(fill="x")

        for idx, (label, attr, lo, hi, default, res) in enumerate(slider_defs):
            col = (idx % 2) * 4
            row = idx // 2
            var = tk.DoubleVar(value=default)
            self.slider_vars[attr] = var

            tk.Label(grid, text=label, width=11, anchor="e").grid(
                row=row, column=col, padx=(12, 4), pady=4)
            sl = tk.Scale(grid, variable=var, from_=lo, to=hi, resolution=res,
                          orient="horizontal", length=200,
                          command=lambda v, a=attr: self._update_lbl(a))
            sl.grid(row=row, column=col+1, padx=2)
            lbl = tk.Label(grid, text=str(default), width=6, fg=CLR["accent"])
            lbl.grid(row=row, column=col+2, padx=4)
            self.slider_lbls[attr] = lbl

            tk.Button(grid, text="↺", width=2,
                      command=lambda a=attr, d=default, v=var: (v.set(d), self._update_lbl(a))
                      ).grid(row=row, column=col+3, padx=2)

        # Reset All button
        reset_row = tk.Frame(sliders_lf)
        reset_row.pack(anchor="e", pady=4)
        tk.Button(reset_row, text=t("color_correct.btn_reset_all"), command=self._reset_all,
                  bg=CLR["panel"], fg=CLR["fg"]).pack(side="right", padx=6)

        # ── Curves (quick lift/gamma/gain) ───────────────────────────────────
        curves_lf = tk.LabelFrame(self, text=f"  {t('color_correct.curves_section')}  ", padx=15, pady=8)
        curves_lf.pack(fill="x", padx=20, pady=4)
        for lbl, attr, default in [("Lift (blacks):", "lift", 0.0),
                                     ("Gain (whites):", "gain", 1.0)]:
            rf = tk.Frame(curves_lf); rf.pack(fill="x", pady=2)
            tk.Label(rf, text=lbl, width=16, anchor="e").pack(side="left")
            var = tk.DoubleVar(value=default)
            setattr(self, attr + "_var", var)
            tk.Scale(rf, variable=var, from_=0.0, to=2.0, resolution=0.01,
                     orient="horizontal", length=250,
                     command=lambda _: self._schedule_preview()).pack(side="left", padx=6)
            tk.Button(rf, text="↺", width=2,
                      command=lambda a=attr, d=default, v=var: (
                          v.set(d), self._schedule_preview())
                      ).pack(side="left", padx=2)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Buttons
        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("color_correct.live_preview"), bg=CLR["accent"], fg="white",
                  width=16, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(btn_row, text=t("color_correct.render_grade"),
                                     font=(UI_FONT, 12, "bold"),
                                     bg=CLR["pink"], fg="white", width=20,
                                     command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _update_lbl(self, attr):
        val = self.slider_vars[attr].get()
        self.slider_lbls[attr].config(text=f"{val:.2f}")
        self._schedule_preview()

    def _schedule_preview(self):
        """Debounce preview renders: wait 250 ms after the last slider move."""
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._debounced_preview)

    def _debounced_preview(self):
        self._preview_job = None
        if self.file_path and self.preview_proc and self.preview_proc.poll() is None:
            # A live preview window is already open - relaunch it with new settings
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
            self._preview()

    def _reset_all(self):
        defaults = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0,
                    "gamma": 1.0, "gamma_r": 1.0, "gamma_g": 1.0,
                    "gamma_b": 1.0, "hue": 0.0}
        for attr, val in defaults.items():
            self.slider_vars[attr].set(val)
            self._update_lbl(attr)
        self.lift_var.set(0.0)
        self.gain_var.set(1.0)

    def _build_vf(self):
        sv = self.slider_vars
        eq = (f"eq=brightness={sv['brightness'].get():.3f}"
              f":contrast={sv['contrast'].get():.3f}"
              f":saturation={sv['saturation'].get():.3f}"
              f":gamma={sv['gamma'].get():.3f}"
              f":gamma_r={sv['gamma_r'].get():.3f}"
              f":gamma_g={sv['gamma_g'].get():.3f}"
              f":gamma_b={sv['gamma_b'].get():.3f}")
        hue = sv['hue'].get()
        hue_f = f",hue=h={hue:.1f}" if abs(hue) > 0.01 else ""
        lift = self.lift_var.get()
        gain = self.gain_var.get()
        lift_f = ""
        if abs(lift) > 0.01 or abs(gain - 1.0) > 0.01:
            lift_f = f",curves=all='{lift:.2f}/0 {gain:.2f}/1'"
        return f"{eq}{hue_f}{lift_f}"

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(f"{base}_corrected.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay = get_binary_path("ffplay.exe")
        vf = self._build_vf()
        cmd = [ffplay, "-i", self.file_path, "-vf", vf,
               "-window_title", t("color_correct.colour_preview"), "-x", "800", "-autoexit"]
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
        vf = self._build_vf()
        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, t("log.color_correct.rendering_colour_grade"))
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label="🌈  RENDER GRADE")
