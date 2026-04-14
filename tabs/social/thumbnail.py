"""
tab_thumbnailmaker.py  ─  Thumbnail Maker

Extract the best frame from a video and export it as a high-res
image suitable for YouTube/TikTok thumbnails.  Options for:
  • Frame scrubbing to pick the perfect moment
  • Multiple output sizes (YouTube 1280×720, TikTok 1080×1920, etc.)
  • Text overlay with customisable font, colour, position, and stroke
  • Brightness / contrast / saturation boost for punchy thumbnails
  • Border / vignette effects
  • Batch: export a frame every N seconds for selection
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


PRESETS = {
    t("thumbnail.youtube_1280_720"):   (1280, 720),
    t("thumbnail.youtube_hd_1920_1080"): (1920, 1080),
    t("thumbnail.tiktok_shorts_1080_1920"): (1080, 1920),
    t("thumbnail.instagram_1080_1080"): (1080, 1080),
    t("thumbnail.twitter_x_1200_675"): (1200, 675),
    t("thumbnail.original_resolution"):  (0, 0),
}


class ThumbnailMakerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.thumbnail_maker"),
                         t("thumbnail.subtitle"),
                         icon="🖼")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._dur_lbl.pack(side="left", padx=10)

        # ── Frame selection ───────────────────────────────────────────────
        frame_lf = tk.LabelFrame(self, text=f"  {t('thumbnail.frame_section')}  ", padx=15, pady=10,
                                 font=(UI_FONT, 9, "bold"))
        frame_lf.pack(fill="x", padx=20, pady=8)

        fr1 = tk.Frame(frame_lf)
        fr1.pack(fill="x", pady=3)
        tk.Label(fr1, text=t("thumbnail.scrub_label"), font=(UI_FONT, 10, "bold"),
                 width=14, anchor="e").pack(side="left")
        self._scrub_var = tk.DoubleVar(value=0.0)
        self._scrub = tk.Scale(fr1, variable=self._scrub_var, from_=0, to=100,
                               resolution=0.01, orient="horizontal", length=420,
                               bg=CLR["panel"], fg=CLR["fg"],
                               troughcolor=CLR["bg"], highlightthickness=0,
                               command=self._on_scrub)
        self._scrub.pack(side="left", padx=8)
        self._time_lbl = tk.Label(fr1, text="00:00.00", fg=CLR["accent"],
                                  font=(MONO_FONT, 10, "bold"), width=10)
        self._time_lbl.pack(side="left")

        fr2 = tk.Frame(frame_lf)
        fr2.pack(fill="x", pady=3)
        tk.Label(fr2, text="", width=14).pack(side="left")
        tk.Button(fr2, text=f"👁 {t('thumbnail.preview_button')}", bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._preview_frame).pack(side="left", padx=4)
        tk.Button(fr2, text=t("thumbnail.1s"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), width=5, cursor="hand2",
                  command=lambda: self._nudge(-1.0)).pack(side="left", padx=2)
        tk.Button(fr2, text=t("thumbnail.0_1s"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), width=6, cursor="hand2",
                  command=lambda: self._nudge(-0.1)).pack(side="left", padx=2)
        tk.Button(fr2, text=t("thumbnail.0_1s_2"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), width=6, cursor="hand2",
                  command=lambda: self._nudge(0.1)).pack(side="left", padx=2)
        tk.Button(fr2, text=t("thumbnail.1s_2"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), width=5, cursor="hand2",
                  command=lambda: self._nudge(1.0)).pack(side="left", padx=2)

        # ── Size preset ───────────────────────────────────────────────────
        size_lf = tk.LabelFrame(self, text=f"  {t('thumbnail.output_size_section')}  ", padx=15, pady=8,
                                font=(UI_FONT, 9, "bold"))
        size_lf.pack(fill="x", padx=20, pady=6)

        self._size_var = tk.StringVar(value="YouTube HD (1920×1080)")
        sz_row = tk.Frame(size_lf)
        sz_row.pack(fill="x")
        for preset_name in PRESETS:
            tk.Radiobutton(sz_row, text=preset_name, variable=self._size_var,
                           value=preset_name, font=(UI_FONT, 9)).pack(anchor="w")

        # ── Image adjustments ─────────────────────────────────────────────
        adj_lf = tk.LabelFrame(self, text=f"  {t('thumbnail.adjustments_section')}  ",
                               padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        adj_lf.pack(fill="x", padx=20, pady=6)

        ar1 = tk.Frame(adj_lf)
        ar1.pack(fill="x", pady=2)

        tk.Label(ar1, text=t("thumbnail.brightness_label"), font=(UI_FONT, 10), width=12,
                 anchor="e").pack(side="left")
        self._brightness = tk.DoubleVar(value=0.0)
        tk.Scale(ar1, variable=self._brightness, from_=-0.5, to=0.5,
                 resolution=0.02, orient="horizontal", length=150,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=4)

        tk.Label(ar1, text=t("thumbnail.contrast_label"), font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._contrast = tk.DoubleVar(value=1.0)
        tk.Scale(ar1, variable=self._contrast, from_=0.5, to=2.0,
                 resolution=0.05, orient="horizontal", length=150,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=4)

        tk.Label(ar1, text=t("thumbnail.saturation_label"), font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._saturation = tk.DoubleVar(value=1.0)
        tk.Scale(ar1, variable=self._saturation, from_=0.0, to=3.0,
                 resolution=0.05, orient="horizontal", length=150,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=4)

        # ── Text overlay ──────────────────────────────────────────────────
        txt_lf = tk.LabelFrame(self, text=f"  {t('thumbnail.text_overlay_section')}  ",
                               padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        txt_lf.pack(fill="x", padx=20, pady=6)

        self._use_text = tk.BooleanVar(value=False)
        tk.Checkbutton(txt_lf, text=t("thumbnail.add_text_checkbox"), variable=self._use_text,
                       font=(UI_FONT, 10)).pack(anchor="w")

        tr1 = tk.Frame(txt_lf)
        tr1.pack(fill="x", pady=3)
        tk.Label(tr1, text=t("thumbnail.text_label"), font=(UI_FONT, 10), width=10,
                 anchor="e").pack(side="left")
        self._text_var = tk.StringVar(value="")
        tk.Entry(tr1, textvariable=self._text_var, width=40, relief="flat",
                 font=(UI_FONT, 11)).pack(side="left", padx=6)

        tr2 = tk.Frame(txt_lf)
        tr2.pack(fill="x", pady=3)
        tk.Label(tr2, text=t("thumbnail.text_size_label"), font=(UI_FONT, 10), width=10,
                 anchor="e").pack(side="left")
        self._text_size = tk.StringVar(value="64")
        tk.Entry(tr2, textvariable=self._text_size, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        tk.Label(tr2, text=t("thumbnail.text_color_label"), font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._text_color = tk.StringVar(value="white")
        ttk.Combobox(tr2, textvariable=self._text_color, width=10,
                     values=["white", "yellow", "red", "black", "cyan", "lime"],
                     state="readonly").pack(side="left", padx=6)
        tk.Label(tr2, text=t("thumbnail.text_position_label"), font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._text_pos = tk.StringVar(value="center")
        ttk.Combobox(tr2, textvariable=self._text_pos, width=12,
                     values=["center", "top", "bottom", "top-left", "top-right"],
                     state="readonly").pack(side="left", padx=6)

        self._text_stroke = tk.BooleanVar(value=True)
        tk.Checkbutton(tr2, text=t("thumbnail.stroke_checkbox"), variable=self._text_stroke,
                       font=(UI_FONT, 10)).pack(side="left", padx=12)

        # ── Batch mode ────────────────────────────────────────────────────
        batch_lf = tk.LabelFrame(self, text=f"  {t('thumbnail.batch_section')}  ", padx=15, pady=8,
                                 font=(UI_FONT, 9, "bold"))
        batch_lf.pack(fill="x", padx=20, pady=6)

        br = tk.Frame(batch_lf)
        br.pack(fill="x")
        self._batch_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(br, text=t("thumbnail.extract_every_label"), variable=self._batch_mode,
                       font=(UI_FONT, 10)).pack(side="left")
        self._batch_interval = tk.StringVar(value="10")
        tk.Entry(br, textvariable=self._batch_interval, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(br, text=t("thumbnail.seconds_to_folder_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("encode_queue.output_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        fmt_f = tk.Frame(self)
        fmt_f.pack(fill="x", padx=20, pady=2)
        tk.Label(fmt_f, text=t("common.format"), font=(UI_FONT, 10)).pack(side="left")
        self._fmt_var = tk.StringVar(value="PNG")
        for v in ["PNG", "JPEG (q95)", "JPEG (q85)", "WebP"]:
            tk.Radiobutton(fmt_f, text=v, variable=self._fmt_var, value=v,
                           font=(UI_FONT, 10)).pack(side="left", padx=8)

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        self._btn_run = tk.Button(
            bf, text="🖼  " + t("tab.thumbnail_maker"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack()

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=4)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Callbacks ──────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self._src_var.set(p)
            self.duration = get_video_duration(p)
            self._dur_lbl.config(text=_fmt(self.duration))
            self._scrub.config(to=max(0.1, self.duration))

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WebP", "*.webp")])
        if p:
            self._out_var.set(p)

    def _on_scrub(self, val):
        try:
            self._time_lbl.config(text=_fmt(float(val)))
        except (ValueError, tk.TclError):
            pass

    def _nudge(self, delta):
        t = self._scrub_var.get() + delta
        t = max(0.0, min(t, self.duration))
        self._scrub_var.set(t)
        self._time_lbl.config(text=_fmt(t))

    def _preview_frame(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        t = self._scrub_var.get()
        if self.preview_proc:
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
        self.preview_proc = launch_preview(self.file_path, start_time=t)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        ffmpeg = get_binary_path("ffmpeg")
        batch = self._batch_mode.get()

        if batch:
            # Batch: export frames to a folder
            out_dir = filedialog.askdirectory(title="Choose folder for thumbnails")
            if not out_dir:
                return

            try:
                interval = float(self._batch_interval.get())
            except ValueError:
                interval = 10.0

            vf_parts = self._build_vf()
            vf = ",".join(vf_parts) if vf_parts else None

            ext = self._get_ext()
            out_pattern = os.path.join(out_dir, f"thumb_%04d{ext}")

            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", f"fps=1/{interval}" + ("," + vf if vf else "")]
            cmd += self._get_format_args()
            cmd += [out_pattern, "-y"]

            self.log(self.console, f"Batch export: every {interval}s → {out_dir}")
            self.run_ffmpeg(cmd, self.console,
                            on_done=lambda rc: self.show_result(rc, out_dir),
                            btn=self._btn_run, btn_label="🖼  EXPORT THUMBNAIL")
            return

        # Single frame
        out = self._out_var.get().strip()
        if not out:
            ext = self._get_ext()
            out = filedialog.asksaveasfilename(
                defaultextension=ext,
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WebP", "*.webp")])
        if not out:
            return
        self._out_var.set(out)

        t = self._scrub_var.get()
        vf_parts = self._build_vf()
        vf = ",".join(vf_parts) if vf_parts else None

        cmd = [ffmpeg, "-ss", str(t), "-i", self.file_path, "-vframes", "1"]
        if vf:
            cmd += ["-vf", vf]
        cmd += self._get_format_args()
        cmd += [out, "-y"]

        self.log(self.console, f"Extracting frame at {_fmt(t)}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label="🖼  EXPORT THUMBNAIL")

    def _build_vf(self):
        parts = []

        # Size
        preset = self._size_var.get()
        w, h = PRESETS.get(preset, (0, 0))
        if w > 0 and h > 0:
            parts.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")

        # Adjustments
        br = self._brightness.get()
        ct = self._contrast.get()
        sat = self._saturation.get()
        if br != 0.0 or ct != 1.0 or sat != 1.0:
            parts.append(f"eq=brightness={br}:contrast={ct}:saturation={sat}")

        # Text overlay
        if self._use_text.get():
            text = self._text_var.get().replace("'", "\\'").replace(":", "\\:")
            if text:
                size = self._text_size.get()
                color = self._text_color.get()
                pos = self._text_pos.get()

                if pos == "center":
                    x_expr, y_expr = "(w-text_w)/2", "(h-text_h)/2"
                elif pos == "top":
                    x_expr, y_expr = "(w-text_w)/2", "40"
                elif pos == "bottom":
                    x_expr, y_expr = "(w-text_w)/2", "h-text_h-40"
                elif pos == "top-left":
                    x_expr, y_expr = "40", "40"
                elif pos == "top-right":
                    x_expr, y_expr = "w-text_w-40", "40"
                else:
                    x_expr, y_expr = "(w-text_w)/2", "(h-text_h)/2"

                stroke = ""
                if self._text_stroke.get():
                    stroke = ":borderw=4:bordercolor=black"

                parts.append(
                    f"drawtext=text='{text}':fontsize={size}:"
                    f"fontcolor={color}:x={x_expr}:y={y_expr}{stroke}")

        return parts

    def _get_ext(self):
        fmt = self._fmt_var.get()
        if "PNG" in fmt:
            return ".png"
        elif "WebP" in fmt:
            return ".webp"
        else:
            return ".jpg"

    def _get_format_args(self):
        fmt = self._fmt_var.get()
        if "PNG" in fmt:
            return []
        elif "q95" in fmt:
            return ["-q:v", "2"]
        elif "q85" in fmt:
            return ["-q:v", "5"]
        elif "WebP" in fmt:
            return ["-quality", "90"]
        return []
