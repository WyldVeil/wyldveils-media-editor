"""
tab_autocropper.py  ─  Auto-Cropper
Manual crop with live coordinate preview, aspect-ratio presets,
and optional black bar (letterbox/pillarbox) auto-detection.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


ASPECT_PRESETS = {
    t("crop.free_custom"):  None,
    t("auto_cropper.16_9_widescreen"): (16, 9),
    t("auto_cropper.9_16_vertical"):   (9, 16),
    "4:3":                (4, 3),
    t("auto_cropper.1_1_square"):     (1, 1),
    t("auto_cropper.2_35_1_cinematic"): (2.35, 1),
    t("auto_cropper.21_9_ultra_wide"): (21, 9),
}


class AutoCropperTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🖼  " + t("tab.auto_cropper"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("auto_cropper.desc"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=8)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Crop options
        cf = tk.LabelFrame(self, text=t("auto_cropper.sect_crop_settings"), padx=15, pady=10)
        cf.pack(fill="x", padx=20, pady=6)

        tk.Label(cf, text=t("auto_cropper.lbl_aspect_ratio"), font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        self.aspect_var = tk.StringVar(value=list(ASPECT_PRESETS.keys())[0])
        ttk.Combobox(cf, textvariable=self.aspect_var, values=list(ASPECT_PRESETS.keys()),
                     state="readonly", width=26).grid(row=0, column=1, sticky="w", pady=5)

        for lbl, var_name, default, col in [
            ("X (crop start px):", "x_var", "0",    0),
            ("Y (crop start px):", "y_var", "0",    2),
            ("Width (px):",        "w_var", "1920", 4),
            ("Height (px):",       "h_var", "1080", 6),
        ]:
            tk.Label(cf, text=lbl).grid(row=1, column=col, sticky="e", padx=(10, 0))
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            tk.Entry(cf, textvariable=var, width=7, relief="flat").grid(row=1, column=col+1, padx=4, pady=5)

        self.autodetect_btn = tk.Button(cf, text=t("auto_cropper.btn_autodetect"),
                                        command=self._autodetect, bg="#333",
                                        fg=CLR["accent"], font=(UI_FONT, 9, "bold"))
        self.autodetect_btn.grid(row=2, column=0, columnspan=3, sticky="w", pady=5)
        self.detect_result = tk.Label(cf, text="", fg=CLR["fgdim"])
        self.detect_result.grid(row=2, column=3, columnspan=4, sticky="w")

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("auto_cropper.btn_crop_export"), font=(UI_FONT, 12, "bold"),
            bg=CLR["orange"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf2 = tk.Frame(self); cf2.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf2, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _autodetect(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path, "-vf",
               t("auto_cropper.cropdetect_24_16_0"), t("smart_reframe.frames_v"), "300",
               "-f", "null", "-"]
        self.detect_result.config(text=t("auto_cropper.lbl_scanning"))

        def do_detect():
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    creationflags=CREATE_NO_WINDOW)
            matches = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", result.stderr)
            if matches:
                w, h, x, y = matches[-1]
                self.after(0, lambda: (
                    self.w_var.set(w), self.h_var.set(h),
                    self.x_var.set(x), self.y_var.set(y),
                    self.detect_result.config(
                        text=f"Detected: crop={w}:{h}:{x}:{y}", fg=CLR["green"])))
            else:
                self.after(0, lambda: self.detect_result.config(
                    text=t("auto_cropper.lbl_no_bars"), fg=CLR["fgdim"]))

        self.run_in_thread(do_detect)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)
        w = self.w_var.get(); h = self.h_var.get()
        x = self.x_var.get(); y = self.y_var.get()
        filt = f"crop={w}:{h}:{x}:{y}"
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path, "-vf", filt,
               t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, f"Cropping → {filt}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("auto_cropper.btn_crop_export"))
