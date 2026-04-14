"""
tab_manualcrop.py  ─  Manual Crop & Reframe

Manually crop any region of the video frame - essential for:
  • Cropping out UI elements, watermarks, or black bars
  • Reframing a wide shot to focus on one person
  • Converting between aspect ratios with precise control
  • Extracting a sub-region for vertical/short-form content

Provides a visual crop preview on a canvas where users can
drag corners to define the crop rectangle, plus numeric
fields for pixel-perfect control.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    return f"{int(m):02d}:{s:05.2f}"


def _probe_wh(path):
    try:
        r = subprocess.run(
            [get_binary_path("ffprobe"), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=10)
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


ASPECT_PRESETS = {
    t("crop.free_custom"):   None,
    t("crop.16_9_youtube"):  (16, 9),
    t("crop.9_16_shorts"):   (9, 16),
    t("crop.4_3_classic"):   (4, 3),
    t("crop.1_1_square"):    (1, 1),
    t("crop.21_9_cinema"):   (21, 9),
    t("crop.4_5_instagram"): (4, 5),
}


class ManualCropTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.vid_w, self.vid_h = 1920, 1080
        self.preview_proc = None

        # Crop rect in video pixels
        self._crop_x = tk.IntVar(value=0)
        self._crop_y = tk.IntVar(value=0)
        self._crop_w = tk.IntVar(value=1920)
        self._crop_h = tk.IntVar(value=1080)

        # Canvas dragging state
        self._drag_type = None  # "move", "tl", "tr", "bl", "br"
        self._drag_start = (0, 0)
        self._drag_crop_start = (0, 0, 0, 0)

        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.manual_crop"),
                         t("crop.subtitle"),
                         icon="🔲")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=52, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._info_lbl = tk.Label(sf, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._info_lbl.pack(side="left", padx=10)

        # ── Main area: canvas + controls side by side ─────────────────────
        main_f = tk.Frame(self)
        main_f.pack(fill="both", expand=True, padx=20, pady=6)

        # Left: crop preview canvas
        canvas_lf = tk.LabelFrame(main_f, text=f"  {t('crop.preview_section')}  ",
                                  padx=6, pady=6, font=(UI_FONT, 9, "bold"))
        canvas_lf.pack(side="left", fill="both", expand=True)

        self._canvas = tk.Canvas(canvas_lf, bg=CLR["console_bg"], width=520, height=300,
                                 highlightthickness=0, cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", lambda _: self._draw_crop())
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        # Right: controls panel
        ctrl_f = tk.Frame(main_f, width=300)
        ctrl_f.pack(side="right", fill="y", padx=(10, 0))
        ctrl_f.pack_propagate(False)

        # Aspect ratio presets
        ar_lf = tk.LabelFrame(ctrl_f, text=f"  {t('crop.aspect_ratio_section')}  ", padx=10, pady=6,
                              font=(UI_FONT, 9, "bold"))
        ar_lf.pack(fill="x", pady=(0, 6))

        self._aspect_var = tk.StringVar(value="Free (custom)")
        for name in ASPECT_PRESETS:
            tk.Radiobutton(ar_lf, text=name, variable=self._aspect_var,
                           value=name, font=(UI_FONT, 9),
                           command=self._on_aspect_change).pack(anchor="w")

        # Numeric crop fields
        num_lf = tk.LabelFrame(ctrl_f, text=f"  {t('crop.crop_region_section')}  ", padx=10, pady=6,
                               font=(UI_FONT, 9, "bold"))
        num_lf.pack(fill="x", pady=6)

        for lbl, var in [("X offset:", self._crop_x), ("Y offset:", self._crop_y),
                         ("Width:", self._crop_w), ("Height:", self._crop_h)]:
            row = tk.Frame(num_lf)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=(UI_FONT, 9), width=10,
                     anchor="e").pack(side="left")
            ent = tk.Entry(row, textvariable=var, width=7, relief="flat",
                           font=(MONO_FONT, 10))
            ent.pack(side="left", padx=4)
            ent.bind("<Return>", lambda e: self._draw_crop())
            ent.bind("<FocusOut>", lambda e: self._draw_crop())

        tk.Button(num_lf, text=t("crop.reset_button"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2", width=20,
                  command=self._reset_crop).pack(pady=6)

        # Crop info
        self._crop_info = tk.Label(ctrl_f, text="", fg=CLR["accent"],
                                   font=(MONO_FONT, 9))
        self._crop_info.pack(pady=4)

        # Scale output after crop
        scale_lf = tk.LabelFrame(ctrl_f, text=f"  {t('crop.scale_output_section')}  ", padx=10, pady=6,
                                 font=(UI_FONT, 9, "bold"))
        scale_lf.pack(fill="x", pady=6)

        self._scale_mode = tk.StringVar(value="keep")
        tk.Radiobutton(scale_lf, text=t("crop.keep_cropped_size"), variable=self._scale_mode,
                       value="keep", font=(UI_FONT, 9)).pack(anchor="w")
        sr = tk.Frame(scale_lf)
        sr.pack(fill="x")
        tk.Radiobutton(sr, text=t("crop.scale_to_label"), variable=self._scale_mode,
                       value="scale", font=(UI_FONT, 9)).pack(side="left")
        self._scale_w = tk.StringVar(value="1920")
        tk.Entry(sr, textvariable=self._scale_w, width=6, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(sr, text="×", font=(UI_FONT, 10)).pack(side="left")
        self._scale_h = tk.StringVar(value="1080")
        tk.Entry(sr, textvariable=self._scale_h, width=6, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=2)
        tk.Label(opt_f, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        tk.Button(bf, text=t("crop.preview"), bg=CLR["accent"], fg="white",
                  width=14, font=(UI_FONT, 10), cursor="hand2",
                  command=self._preview).pack(side="left", padx=8)
        self._btn_run = tk.Button(
            bf, text=t("crop.export_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=24,
            cursor="hand2", command=self._render)
        self._btn_run.pack(side="left", padx=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=4)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Canvas coordinate helpers ─────────────────────────────────────
    def _vid_to_canvas(self, vx, vy):
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if self.vid_w == 0 or self.vid_h == 0:
            return 0, 0
        scale = min(cw / self.vid_w, ch / self.vid_h)
        ox = (cw - self.vid_w * scale) / 2
        oy = (ch - self.vid_h * scale) / 2
        return ox + vx * scale, oy + vy * scale

    def _canvas_to_vid(self, cx, cy):
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if self.vid_w == 0 or self.vid_h == 0:
            return 0, 0
        scale = min(cw / self.vid_w, ch / self.vid_h)
        ox = (cw - self.vid_w * scale) / 2
        oy = (ch - self.vid_h * scale) / 2
        vx = (cx - ox) / scale
        vy = (cy - oy) / scale
        return max(0, min(int(vx), self.vid_w)), max(0, min(int(vy), self.vid_h))

    # ── Drawing ───────────────────────────────────────────────────────
    def _draw_crop(self):
        c = self._canvas
        c.delete("all")
        cw = c.winfo_width()
        ch = c.winfo_height()

        # Draw video frame outline
        x1c, y1c = self._vid_to_canvas(0, 0)
        x2c, y2c = self._vid_to_canvas(self.vid_w, self.vid_h)
        c.create_rectangle(x1c, y1c, x2c, y2c, fill="#222222", outline="#555555")
        c.create_text((x1c + x2c) / 2, (y1c + y2c) / 2,
                      text=f"{self.vid_w}×{self.vid_h}",
                      fill="#444444", font=(UI_FONT, 14))

        # Draw crop rectangle
        cx = self._crop_x.get()
        cy = self._crop_y.get()
        cw_val = self._crop_w.get()
        ch_val = self._crop_h.get()

        rx1, ry1 = self._vid_to_canvas(cx, cy)
        rx2, ry2 = self._vid_to_canvas(cx + cw_val, cy + ch_val)

        # Dimmed areas outside crop
        # top
        c.create_rectangle(x1c, y1c, x2c, ry1, fill="#000000", stipple="gray50", outline="")
        # bottom
        c.create_rectangle(x1c, ry2, x2c, y2c, fill="#000000", stipple="gray50", outline="")
        # left
        c.create_rectangle(x1c, ry1, rx1, ry2, fill="#000000", stipple="gray50", outline="")
        # right
        c.create_rectangle(rx2, ry1, x2c, ry2, fill="#000000", stipple="gray50", outline="")

        # Crop border
        c.create_rectangle(rx1, ry1, rx2, ry2, outline=CLR["accent"], width=2)

        # Corner handles
        hs = 6
        for x, y in [(rx1, ry1), (rx2, ry1), (rx1, ry2), (rx2, ry2)]:
            c.create_rectangle(x - hs, y - hs, x + hs, y + hs,
                               fill=CLR["accent"], outline="white", width=1)

        # Rule of thirds - stipple simulates transparency (Tk has no RGBA hex support)
        for i in (1, 2):
            tx = rx1 + (rx2 - rx1) * i / 3
            ty = ry1 + (ry2 - ry1) * i / 3
            c.create_line(tx, ry1, tx, ry2, fill="#FFFFFF", stipple="gray25", dash=(2, 4))
            c.create_line(rx1, ty, rx2, ty, fill="#FFFFFF", stipple="gray25", dash=(2, 4))

        # Info label
        c.create_text((rx1 + rx2) / 2, ry1 - 12,
                      text=f"{cw_val}×{ch_val}",
                      fill=CLR["accent"], font=(MONO_FONT, 9, "bold"))

        # Update info label
        self._crop_info.config(
            text=f"Crop: {cw_val}×{ch_val} at ({cx},{cy})")

    # ── Mouse interaction ─────────────────────────────────────────────
    def _on_press(self, ev):
        cx = self._crop_x.get()
        cy = self._crop_y.get()
        cw = self._crop_w.get()
        ch = self._crop_h.get()

        rx1, ry1 = self._vid_to_canvas(cx, cy)
        rx2, ry2 = self._vid_to_canvas(cx + cw, cy + ch)

        hs = 10

        if abs(ev.x - rx1) < hs and abs(ev.y - ry1) < hs:
            self._drag_type = "tl"
        elif abs(ev.x - rx2) < hs and abs(ev.y - ry1) < hs:
            self._drag_type = "tr"
        elif abs(ev.x - rx1) < hs and abs(ev.y - ry2) < hs:
            self._drag_type = "bl"
        elif abs(ev.x - rx2) < hs and abs(ev.y - ry2) < hs:
            self._drag_type = "br"
        elif rx1 < ev.x < rx2 and ry1 < ev.y < ry2:
            self._drag_type = "move"
        else:
            self._drag_type = None
            return

        self._drag_start = (ev.x, ev.y)
        self._drag_crop_start = (cx, cy, cw, ch)

    def _on_drag(self, ev):
        if not self._drag_type:
            return

        vx, vy = self._canvas_to_vid(ev.x, ev.y)
        ocx, ocy, ocw, och = self._drag_crop_start

        if self._drag_type == "move":
            dx_vid, dy_vid = self._canvas_to_vid(ev.x, ev.y)
            sx_vid, sy_vid = self._canvas_to_vid(*self._drag_start)
            new_x = max(0, min(ocx + dx_vid - sx_vid, self.vid_w - ocw))
            new_y = max(0, min(ocy + dy_vid - sy_vid, self.vid_h - och))
            self._crop_x.set(new_x)
            self._crop_y.set(new_y)

        elif self._drag_type == "tl":
            new_x = max(0, min(vx, ocx + ocw - 16))
            new_y = max(0, min(vy, ocy + och - 16))
            self._crop_x.set(new_x)
            self._crop_y.set(new_y)
            self._crop_w.set(ocx + ocw - new_x)
            self._crop_h.set(ocy + och - new_y)

        elif self._drag_type == "tr":
            new_w = max(16, min(vx - ocx, self.vid_w - ocx))
            new_y = max(0, min(vy, ocy + och - 16))
            self._crop_y.set(new_y)
            self._crop_w.set(new_w)
            self._crop_h.set(ocy + och - new_y)

        elif self._drag_type == "bl":
            new_x = max(0, min(vx, ocx + ocw - 16))
            new_h = max(16, min(vy - ocy, self.vid_h - ocy))
            self._crop_x.set(new_x)
            self._crop_w.set(ocx + ocw - new_x)
            self._crop_h.set(new_h)

        elif self._drag_type == "br":
            new_w = max(16, min(vx - ocx, self.vid_w - ocx))
            new_h = max(16, min(vy - ocy, self.vid_h - ocy))
            self._crop_w.set(new_w)
            self._crop_h.set(new_h)

        self._draw_crop()

    def _on_release(self, ev):
        self._drag_type = None

    # ── Aspect ratio ──────────────────────────────────────────────────
    def _on_aspect_change(self):
        name = self._aspect_var.get()
        ratio = ASPECT_PRESETS.get(name)
        if ratio is None:
            return

        rw, rh = ratio
        # Fit the crop rect to the selected aspect within the video
        if (self.vid_w / self.vid_h) > (rw / rh):
            # Video is wider - constrain by height
            new_h = self.vid_h
            new_w = int(new_h * rw / rh)
        else:
            # Video is taller - constrain by width
            new_w = self.vid_w
            new_h = int(new_w * rh / rw)

        new_w = min(new_w, self.vid_w)
        new_h = min(new_h, self.vid_h)

        self._crop_x.set((self.vid_w - new_w) // 2)
        self._crop_y.set((self.vid_h - new_h) // 2)
        self._crop_w.set(new_w)
        self._crop_h.set(new_h)
        self._draw_crop()

    def _reset_crop(self):
        self._crop_x.set(0)
        self._crop_y.set(0)
        self._crop_w.set(self.vid_w)
        self._crop_h.set(self.vid_h)
        self._aspect_var.set("Free (custom)")
        self._draw_crop()

    # ── File browsing ─────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self._src_var.set(p)
            self.duration = get_video_duration(p)
            self.vid_w, self.vid_h = _probe_wh(p)
            self._info_lbl.config(
                text=f"{_fmt(self.duration)}  ·  {self.vid_w}×{self.vid_h}")
            self._reset_crop()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    # ── Preview & Render ──────────────────────────────────────────────
    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
        self.preview_proc = launch_preview(self.file_path)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg")
        cx = self._crop_x.get()
        cy = self._crop_y.get()
        cw = self._crop_w.get()
        ch = self._crop_h.get()
        crf = self._crf_var.get()

        # Make even (FFmpeg requires even dimensions for h264)
        cw = cw - (cw % 2)
        ch = ch - (ch % 2)

        vf = f"crop={cw}:{ch}:{cx}:{cy}"

        if self._scale_mode.get() == "scale":
            try:
                sw = int(self._scale_w.get())
                sh = int(self._scale_h.get())
                sw = sw - (sw % 2)
                sh = sh - (sh % 2)
                vf += f",scale={sw}:{sh}"
            except ValueError:
                pass

        cmd = [ffmpeg, "-i", self.file_path,
               "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
               t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
               "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Cropping: {cw}×{ch} at ({cx},{cy})")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label="🔲  CROP & EXPORT")
