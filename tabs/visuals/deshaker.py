"""
tab_deshaker.py  ─  Deshaker
FFmpeg vidstabdetect + vidstabtransform two-pass stabilisation.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import tempfile
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


class DeshakerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎥  " + t("tab.deshaker"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("deshaker.subtitle"),
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
        opts = tk.LabelFrame(self, text=f"  {t('deshaker.options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("deshaker.smoothing_label")).pack(side="left")
        self.smooth_var = tk.StringVar(value="10")
        tk.Scale(r0, variable=self.smooth_var, from_=1, to=30,
                 orient="horizontal", length=200).pack(side="left", padx=6)
        tk.Label(r0, text=t("deshaker.smoothing_hint"), fg=CLR["fgdim"]).pack(side="left", padx=6)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("deshaker.zoom_label")).pack(side="left")
        self.zoom_var = tk.StringVar(value="5")
        tk.Entry(r1, textvariable=self.zoom_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=f"  {t('deshaker.crop_fill_label')}").pack(side="left", padx=(12, 0))
        self.crop_var = tk.StringVar(value="keep border")
        ttk.Combobox(r1, textvariable=self.crop_var,
                     values=[t("deshaker.deshaker_keep_border"), t("deshaker.deshaker_black_fill"), t("deshaker.deshaker_clone_border")],
                     state="readonly", width=14).pack(side="left", padx=4)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("deshaker.shake_detect_label")).pack(side="left")
        self.shakiness_var = tk.StringVar(value="5")
        tk.Scale(r2, variable=self.shakiness_var, from_=1, to=10,
                 orient="horizontal", length=150).pack(side="left", padx=4)
        tk.Label(r2, text=f"  {t('deshaker.accuracy_label')}").pack(side="left", padx=(12, 0))
        self.accuracy_var = tk.StringVar(value="9")
        tk.Scale(r2, variable=self.accuracy_var, from_=1, to=15,
                 orient="horizontal", length=150).pack(side="left", padx=4)

        r3 = tk.Frame(opts); r3.pack(fill="x", pady=4)
        tk.Label(r3, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(r3, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("deshaker.stabilise_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        self.status_lbl = tk.Label(self, text="", fg=CLR["fgdim"])
        self.status_lbl.pack()

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
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

        ffmpeg     = get_binary_path("ffmpeg.exe")
        smooth     = self.smooth_var.get() if isinstance(self.smooth_var.get(), str) else str(int(self.smooth_var.get()))
        zoom       = self.zoom_var.get()
        shakiness  = self.shakiness_var.get() if isinstance(self.shakiness_var.get(), str) else str(int(self.shakiness_var.get()))
        accuracy   = self.accuracy_var.get() if isinstance(self.accuracy_var.get(), str) else str(int(self.accuracy_var.get()))
        crop_mode  = {"keep border": "0", "black fill": "1", "clone border": "2"}.get(self.crop_var.get(), "0")
        tmp_trf    = tempfile.mktemp(suffix=".trf")

        def _work():
            self.after(0, lambda: self.status_lbl.config(text=t("deshaker.pass_1_detecting_motion")))
            self.log(self.console, t("log.deshaker.pass_1_vidstabdetect"))
            cmd1 = [ffmpeg, "-i", self.file_path,
                    "-vf", f"vidstabdetect=shakiness={shakiness}:accuracy={accuracy}:result={tmp_trf}",
                    "-f", "null", "-"]
            r1 = subprocess.run(cmd1, capture_output=True, creationflags=CREATE_NO_WINDOW)
            if r1.returncode != 0:
                self.log(self.console, t("log.deshaker.pass_1_failed_is_vidstab_compiled_into_your_ffmpeg"))
                self.after(0, lambda: self.status_lbl.config(text=t("deshaker.failed")))
                return

            self.after(0, lambda: self.status_lbl.config(text=t("deshaker.pass_2_transforming")))
            self.log(self.console, t("log.deshaker.pass_2_vidstabtransform"))
            cmd2 = [ffmpeg, "-i", self.file_path,
                    "-vf", (f"vidstabtransform=smoothing={smooth}:zoom={zoom}"
                            f":crop={crop_mode}:input={tmp_trf}"),
                    t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(), "-preset", "fast",
                    t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
            r2 = subprocess.run(cmd2, capture_output=True, text=True,
                                creationflags=CREATE_NO_WINDOW)
            try: os.remove(tmp_trf)
            except Exception: pass

            self.after(0, lambda: self.status_lbl.config(
                text=t("deshaker.done") if r2.returncode == 0 else "❌ Failed."))
            self.after(0, lambda: self.show_result(r2.returncode, out))

        self.run_in_thread(_work)
