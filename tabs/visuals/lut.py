"""
tab_lutapplicator.py  ─  LUT Applicator
Apply .cube or .3dl LUT files for colour grading.
Supports intensity blending and preview.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


class LUTApplicatorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.video_path = ""
        self.lut_path   = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎨  " + t("tab.lut_applicator"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("lut.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File pickers
        pick = tk.LabelFrame(self, text=t("section.input_files"), padx=15, pady=8)
        pick.pack(fill="x", padx=20, pady=8)

        for row, label, attr, ftypes in [
            (0, t("lut.video_label"), "video_path",
             [("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", "*.*")]),
            (1, t("lut.lut_label"), "lut_path",
             [("LUT Files", "*.cube *.3dl"), ("All", "*.*")]),
        ]:
            tk.Label(pick, text=label, font=(UI_FONT, 9, "bold")).grid(
                row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(pick, textvariable=var, width=60, relief="flat").grid(row=row, column=1, padx=8)

            def _b(a=attr, v=var, ft=ftypes):
                p = filedialog.askopenfilename(filetypes=ft)
                if p:
                    setattr(self, a, p)
                    v.set(p)
                    if a == "video_path":
                        base = os.path.splitext(p)[0]
                        self.out_var.set(f"{base}_graded.mp4")
            tk.Button(pick, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").grid(row=row, column=2)

        # Options
        opts = tk.LabelFrame(self, text=f"  {t('lut.application_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("lut.intensity_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.intensity_var = tk.DoubleVar(value=1.0)
        tk.Scale(r0, variable=self.intensity_var, from_=0.0, to=1.0,
                 resolution=0.01, orient="horizontal", length=300).pack(side="left", padx=8)
        self.intens_lbl = tk.Label(r0, text="100%", width=5)
        self.intens_lbl.pack(side="left")
        self.intensity_var.trace_add("write", lambda *_: self.intens_lbl.config(
            text=f"{int(self.intensity_var.get()*100)}%"))

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("lut.interpolation_label")).pack(side="left")
        self.interp_var = tk.StringVar(value="trilinear")
        ttk.Combobox(r1, textvariable=self.interp_var,
                     values=["nearest", "trilinear", "tetrahedral"],
                     state="readonly", width=14).pack(side="left", padx=6)
        tk.Label(r1, text=t("lut.interpolation_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(r2, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        self.preview_btn = tk.Button(r2, text=t("crop.preview"), bg=CLR["accent"], fg="white",
                                     command=self._preview)
        self.preview_btn.pack(side="left", padx=20)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("lut.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["pink"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _build_vf(self):
        intensity = self.intensity_var.get()
        interp    = self.interp_var.get()
        lut_safe  = self.lut_path.replace("\\", "/").replace(":", "\\:")
        if intensity >= 1.0:
            return f"lut3d='{lut_safe}':interp={interp}"
        else:
            # Blend with original using overlay + mix
            return (f"split=2[orig][toapply];"
                    f"[toapply]lut3d='{lut_safe}':interp={interp}[luted];"
                    f"[orig][luted]blend=all_expr='A*{1-intensity:.2f}+B*{intensity:.2f}'")

    def _preview(self):
        if not self.video_path or not self.lut_path:
            messagebox.showwarning(t("lut.missing_title"), t("lut.missing_message"))
            return
        ffplay = get_binary_path("ffplay.exe")
        vf = self._build_vf()
        # For complex filter in preview, use simpler blend approach
        if "[orig]" in vf:
            vf = f"lut3d='{self.lut_path.replace(chr(92), '/').replace(':', chr(92)+':')}'"
        cmd = [ffplay, "-i", self.video_path, "-vf", vf,
               "-window_title", t("lut.lut_preview"), "-x", "800", "-autoexit"]
        subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.video_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not self.lut_path:
            messagebox.showwarning(t("lut.no_lut_title"), t("lut.no_lut_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        vf = self._build_vf()
        intensity = self.intensity_var.get()

        if "[orig]" in vf:
            # Complex filter
            cmd = [ffmpeg, "-i", self.video_path,
                   "-filter_complex", vf,
                   t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                   "-preset", "fast", t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        else:
            cmd = [ffmpeg, "-i", self.video_path, "-vf", vf,
                   t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                   "-preset", "fast", t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Applying LUT at {int(intensity*100)}% intensity…")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("lut.apply_button"))
