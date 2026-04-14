"""
tab_regionblur.py  ─  Privacy / Region Blur
Blur one or more rectangular regions permanently into a video.
Use cases: blur faces, license plates, screens, sensitive documents.

Multiple regions supported. Each region has its own:
  • Position (x, y) and size (w, h)
  • Blur strength
  • Time range (always or start–end seconds)
  • Blur type: Gaussian, Mosaic/Pixelate, or Black box
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import json

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


BLUR_TYPES = {
    t("region_blur.gaussian_smooth_blur"):   "gaussian",
    t("region_blur.mosaic_pixelate"):         "mosaic",
    t("region_blur.black_box_solid_fill"):    "black",
    t("region_blur.white_box"):                 "white",
}


class RegionBlurTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.preview_proc = None
        self.regions = []   # list of region dicts
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔲  " + t("tab.privacy_blur"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("region_blur.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dim_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dim_lbl.pack(side="left", padx=8)

        # ── Regions list ──────────────────────────────────────────────────
        list_lf = tk.LabelFrame(self, text=f"  {t('region_blur.blur_regions_section')}  ", padx=10, pady=8)
        list_lf.pack(fill="both", expand=True, padx=16, pady=6)

        # Column headers
        h_row = tk.Frame(list_lf); h_row.pack(fill="x", pady=(0, 4))
        for txt, w in [("#", 3), (t("region_blur.type_col"), 14), (t("region_blur.x_col"), 7), (t("region_blur.y_col"), 7),
                        (t("region_blur.width_col"), 7), (t("region_blur.height_col"), 7), (t("region_blur.strength_col"), 9),
                        (t("region_blur.from_col"), 8), (t("region_blur.to_col"), 8), (t("region_blur.always_col"), 7)]:
            tk.Label(h_row, text=txt, width=w, font=(UI_FONT, 8, "bold"),
                     anchor="w", fg=CLR["fgdim"]).pack(side="left", padx=2)

        # Scrollable region rows
        canvas = tk.Canvas(list_lf, height=200, highlightthickness=0)
        sb = ttk.Scrollbar(list_lf, orient="vertical", command=canvas.yview)
        self.rows_frame = tk.Frame(canvas)
        canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>",
                             lambda e: canvas.configure(
                                 scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Buttons
        btn_f = tk.Frame(self); btn_f.pack(pady=4)
        tk.Button(btn_f, text=t("region_blur.add_region_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._add_region).pack(side="left", padx=6)
        tk.Button(btn_f, text=t("region_blur.remove_last_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._remove_last).pack(side="left", padx=6)
        tk.Button(btn_f, text=t("region_blur.fullwidth_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._add_fullwidth).pack(side="left", padx=6)
        tk.Button(btn_f, text=t("region_blur.auto_detect_faces_hint"), bg=CLR["panel"],
                  fg=CLR["fgdim"], font=(UI_FONT, 8),
                  command=self._face_hint).pack(side="left", padx=6)

        # Quick presets
        preset_row = tk.Frame(self); preset_row.pack(pady=2)
        tk.Label(preset_row, text=t("region_blur.quick_region_presets"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")
        for label, x, y, w, h in [
            (t("region_blur.preset_top_left"), 0, 0, 200, 200),
            (t("region_blur.preset_license_plate"), 0, -100, 300, 80),
            (t("region_blur.preset_screen"), 100, 100, 600, 400),
            (t("region_blur.preset_bottom_strip"), 0, -100, 1920, 100),
        ]:
            tk.Button(preset_row, text=label, bg=CLR["panel"], fg=CLR["fgdim"],
                      font=(UI_FONT, 8),
                      command=lambda x=x, y=y, w=w, h=h: self._add_preset_region(x,y,w,h)
                      ).pack(side="left", padx=3)

        # Options
        opt_f = tk.Frame(self); opt_f.pack(pady=4)
        tk.Label(opt_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(opt_f, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(opt_f, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row2 = tk.Frame(self); btn_row2.pack(pady=6)
        tk.Button(btn_row2, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=12, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row2, text=t("region_blur.apply_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["red"], fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # Seed one region
        self._add_region()

    # ─────────────────────────────────────────────────────────────────────
    def _add_region(self, x=100, y=100, w=200, h=200,
                    blur_type="Gaussian (smooth blur)", strength=20,
                    t_start="0", t_end="0", always=True):
        idx = len(self.regions)
        row = tk.Frame(self.rows_frame, relief="groove", bd=1)
        row.pack(fill="x", pady=2)

        type_var    = tk.StringVar(value=blur_type)
        x_var       = tk.StringVar(value=str(x))
        y_var       = tk.StringVar(value=str(y))
        w_var       = tk.StringVar(value=str(w))
        h_var       = tk.StringVar(value=str(h))
        str_var     = tk.StringVar(value=str(strength))
        ts_var      = tk.StringVar(value=t_start)
        te_var      = tk.StringVar(value=t_end)
        always_var  = tk.BooleanVar(value=always)

        tk.Label(row, text=str(idx+1), width=3).pack(side="left", padx=2)
        ttk.Combobox(row, textvariable=type_var,
                     values=list(BLUR_TYPES.keys()),
                     state="readonly", width=22).pack(side="left", padx=2)
        for var, w_ in [(x_var,6),(y_var,6),(w_var,6),(h_var,6),(str_var,7)]:
            tk.Entry(row, textvariable=var, width=w_, relief="flat").pack(side="left", padx=2)
        tk.Entry(row, textvariable=ts_var, width=7, relief="flat").pack(side="left", padx=2)
        tk.Entry(row, textvariable=te_var, width=7, relief="flat").pack(side="left", padx=2)
        tk.Checkbutton(row, variable=always_var).pack(side="left", padx=4)

        self.regions.append({
            "type": type_var, "x": x_var, "y": y_var,
            "w": w_var, "h": h_var, "strength": str_var,
            "t_start": ts_var, "t_end": te_var,
            "always": always_var, "row": row,
        })

    def _add_preset_region(self, x, y, w, h):
        self._add_region(x=x, y=y, w=w, h=h)

    def _add_fullwidth(self):
        self._add_region(x=0, y=50, w=1920, h=100,
                         blur_type="Black box (solid fill)")

    def _remove_last(self):
        if self.regions:
            r = self.regions.pop()
            r["row"].destroy()

    def _face_hint(self):
        messagebox.showinfo(t("msg.face_detection_tip_title"), t("msg.face_detection_tip"))

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_censored.mp4")
            # Try to read dimensions
            self._probe_dims(p)

    def _probe_dims(self, path):
        ffprobe = get_binary_path("ffprobe.exe")
        if not os.path.exists(ffprobe): return
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                    "stream=width,height", "-of", "json", path],
                   capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        try:
            d = json.loads(r.stdout)
            s = next(s for s in d["streams"] if s.get("width"))
            self.dim_lbl.config(
                text=f"{s['width']}×{s['height']}", fg=CLR["accent"])
        except Exception:
            pass

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _build_filter(self):
        """Build the FFmpeg filter_complex string for all regions."""
        if not self.regions:
            return None

        parts = []

        for i, r in enumerate(self.regions):
            try:
                x       = int(r["x"].get())
                y       = int(r["y"].get())
                w       = int(r["w"].get())
                h       = int(r["h"].get())
                strength= int(r["strength"].get())
                blur_t  = BLUR_TYPES[r["type"].get()]
                always  = r["always"].get()
                ts      = r["t_start"].get()
                te      = r["t_end"].get()
            except (ValueError, KeyError):
                continue

            enable = "" if always else f":enable='between(t,{ts},{te})'"

            if blur_t == "gaussian":
                # crop region, boxblur it, overlay back
                filt = (f"[v{i}]crop={w}:{h}:{x}:{y},"
                        f"boxblur={strength}:{strength}[blurred{i}];"
                        f"[v{i}][blurred{i}]overlay={x}:{y}{enable}[v{i+1}]")
            elif blur_t == "mosaic":
                scale_down = max(1, strength // 3)
                filt = (f"[v{i}]crop={w}:{h}:{x}:{y},"
                        f"scale=iw/{scale_down}:ih/{scale_down}:flags=neighbor,"
                        f"scale={w}:{h}:flags=neighbor[blurred{i}];"
                        f"[v{i}][blurred{i}]overlay={x}:{y}{enable}[v{i+1}]")
            elif blur_t == "black":
                filt = (f"[v{i}]drawbox={x}:{y}:{w}:{h}:black:fill{enable}[v{i+1}]")
            else:  # white
                filt = (f"[v{i}]drawbox={x}:{y}:{w}:{h}:white:fill{enable}[v{i+1}]")

            parts.append(filt)

        if not parts:
            return None

        # Chain: [0:v] → [v0], then each filter advances [vi] → [v{i+1}]
        n = len([r for r in self.regions])
        header = f"[0:v]copy[v0]"
        chain  = ";".join(parts)
        # The final output is [v{n}]
        return header + ";" + chain, f"[v{n}]"

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("region_blur.no_file_title"), t("region_blur.no_file_message"))
            return
        result = self._build_filter()
        if not result:
            messagebox.showwarning(t("region_blur.no_regions_title"), t("region_blur.no_regions_message"))
            return
        fc, out_stream = result

        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass

        ffplay = get_binary_path("ffplay.exe")
        cmd = [ffplay, "-i", self.file_path,
               "-filter_complex", fc,
               "-map", out_stream,
               "-window_title", t("region_blur.region_blur_preview"),
               "-x", "800", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        result = self._build_filter()
        if not result:
            messagebox.showwarning(t("region_blur.no_regions_title"), t("region_blur.no_regions_message"))
            return
        fc, out_stream = result

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-i", self.file_path,
               "-filter_complex", fc,
               "-map", out_stream, "-map", t("region_blur.0_a"),
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Applying {len(self.regions)} blur region(s)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("region_blur.apply_button"))
