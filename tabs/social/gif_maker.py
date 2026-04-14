"""
tab_gifmaker.py  ─  Pro GIF Maker
Two-pass FFmpeg GIF generation with palette optimisation.
Produces the smallest, highest-quality GIF possible.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


class GIFMakerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎞  " + t("tab.pro_gif_maker"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("gif_maker.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=55, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # Options
        opts = tk.LabelFrame(self, text=f"  {t('gif_maker.gif_options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=3)
        tk.Label(r0, text=t("common.start_s")).pack(side="left")
        self.start_var = tk.StringVar(value="0")
        tk.Entry(r0, textvariable=self.start_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(r0, text=t("gif_maker.duration_label")).pack(side="left", padx=(15, 0))
        self.dur_var = tk.StringVar(value="5")
        tk.Entry(r0, textvariable=self.dur_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(r0, text=t("gif_maker.fps_label")).pack(side="left", padx=(15, 0))
        self.fps_var = tk.StringVar(value="15")
        ttk.Combobox(r0, textvariable=self.fps_var, values=["8", "10", "12", "15", "20", "24"],
                     state="readonly", width=5).pack(side="left", padx=4)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=3)
        tk.Label(r1, text=t("gif_maker.width_label")).pack(side="left")
        self.width_var = tk.StringVar(value="640")
        tk.Entry(r1, textvariable=self.width_var, width=6, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=t("gif_maker.palette_size_label")).pack(side="left", padx=(15, 0))
        self.palsize_var = tk.StringVar(value="256")
        ttk.Combobox(r1, textvariable=self.palsize_var, values=["64", "128", "256"],
                     state="readonly", width=5).pack(side="left", padx=4)
        tk.Label(r1, text=t("gif_maker.dither_label")).pack(side="left", padx=(15, 0))
        self.dither_var = tk.StringVar(value="sierra2_4a")
        ttk.Combobox(r1, textvariable=self.dither_var,
                     values=["none", t("gif_maker.gif_maker_bayer_bayer_scale_1"), t("gif_maker.gif_maker_bayer_bayer_scale_2"),
                             "floyd_steinberg", "sierra2", "sierra2_4a"],
                     state="readonly", width=18).pack(side="left", padx=4)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=3)
        self.loop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text=t("gif_maker.loop_checkbox"), variable=self.loop_var).pack(side="left")
        tk.Label(r2, text=f"  {t('gif_maker.crop_label')}").pack(side="left", padx=10)
        self.crop_var = tk.StringVar(value="")
        tk.Entry(r2, textvariable=self.crop_var, width=18, relief="flat").pack(side="left", padx=4)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")
        self.size_lbl = tk.Label(of, text="", fg=CLR["fgdim"])
        self.size_lbl.pack(side="left", padx=8)

        # Render
        self.btn_render = tk.Button(
            self, text=t("gif_maker.create_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["pink"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

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
            dur = get_video_duration(p)
            m, s = divmod(int(dur), 60)
            self.dur_lbl.config(text=f"{m}m {s}s")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".gif",
                                         filetypes=[("GIF", "*.gif")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".gif",
                                               filetypes=[("GIF", "*.gif")])
        if not out:
            return
        self.out_var.set(out)

        ffmpeg  = get_binary_path("ffmpeg.exe")
        ss      = self.start_var.get()
        dur     = self.dur_var.get()
        fps     = self.fps_var.get()
        width   = self.width_var.get()
        palsize = self.palsize_var.get()
        dither  = self.dither_var.get()
        loop    = 0 if self.loop_var.get() else -1
        crop    = self.crop_var.get().strip()

        # Build scale/crop filter chain
        vf_parts = []
        if crop:
            vf_parts.append(f"crop={crop}")
        vf_parts.append(f"fps={fps},scale={width}:-1:flags=lanczos")
        vf = ",".join(vf_parts)

        tmp_pal = tempfile.mktemp(suffix=".png")

        def _work():
            # Pass 1: generate palette
            cmd1 = [ffmpeg, "-ss", ss, "-t", dur, "-i", self.file_path,
                    "-vf", f"{vf},palettegen=max_colors={palsize}:stats_mode=diff",
                    "-y", tmp_pal]
            self.log(self.console, t("log.gif_maker.pass_1_generating_palette"))
            r1 = subprocess.run(cmd1, capture_output=True, creationflags=CREATE_NO_WINDOW)
            if r1.returncode != 0:
                self.log(self.console, t("log.gif_maker.palette_generation_failed"))
                return

            # Pass 2: render GIF using palette
            cmd2 = [ffmpeg, "-ss", ss, "-t", dur, "-i", self.file_path,
                    "-i", tmp_pal,
                    "-filter_complex", f"{vf}[x];[x][1:v]paletteuse=dither={dither}",
                    "-loop", str(loop), "-y", out]
            self.log(self.console, t("log.gif_maker.pass_2_rendering_gif"))
            r2 = subprocess.run(cmd2, capture_output=True, creationflags=CREATE_NO_WINDOW)

            try: os.remove(tmp_pal)
            except Exception: pass

            if r2.returncode == 0 and os.path.exists(out):
                size_kb = os.path.getsize(out) / 1024
                self.after(0, lambda: self.size_lbl.config(
                    text=f"✅ {size_kb:.0f} KB", fg=CLR["green"]))
            self.after(0, lambda: self.show_result(r2.returncode, out))

        self.run_in_thread(_work)
