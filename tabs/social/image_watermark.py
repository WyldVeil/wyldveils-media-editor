"""
tab_imagewatermark.py  ─  Image / Logo Watermark
Overlay a PNG, JPG, or GIF image (channel logo, sponsor badge, bug, etc.)
onto a video with full control over position, size, opacity, and timing.

This is different from the text Watermarker tab - this burns a real image file
onto the video, which is what most users expect when they say "add a watermark."
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# Position label → (x_expr, y_expr) using FFmpeg overlay variables
# W/H = video dimensions, w/h = overlay dimensions
POSITIONS = {
    "Top-Left":      ("MARGIN",          "MARGIN"),
    "Top-Centre":    ("(W-w)/2",         "MARGIN"),
    "Top-Right":     ("W-w-MARGIN",      "MARGIN"),
    "Middle-Left":   ("MARGIN",          "(H-h)/2"),
    "Centre":        ("(W-w)/2",         "(H-h)/2"),
    "Middle-Right":  ("W-w-MARGIN",      "(H-h)/2"),
    "Bottom-Left":   ("MARGIN",          "H-h-MARGIN"),
    "Bottom-Centre": ("(W-w)/2",         "H-h-MARGIN"),
    "Bottom-Right":  ("W-w-MARGIN",      "H-h-MARGIN"),
    "Custom":        ("CUSTOM_X",        "CUSTOM_Y"),
}


class ImageWatermarkTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    # ─── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🖼  " + t("tab.image_watermark"),
                 font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner,
                 text=t("watermark.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Source video ──────────────────────────────────────────────────────
        r1 = tk.Frame(self)
        r1.pack(fill="x", padx=16, pady=8)
        tk.Label(r1, text=t("common.source_video"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(r1, textvariable=self._src_var, width=58,
                 relief="flat").pack(side="left", padx=8)
        tk.Button(r1, text=t("btn.browse"), command=self._browse_src,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Image / logo ──────────────────────────────────────────────────────
        r2 = tk.Frame(self)
        r2.pack(fill="x", padx=16, pady=4)
        tk.Label(r2, text=t("watermark.logo_label"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._img_var = tk.StringVar()
        tk.Entry(r2, textvariable=self._img_var, width=58,
                 relief="flat").pack(side="left", padx=8)
        tk.Button(r2, text=t("btn.browse"), command=self._browse_img,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Settings ──────────────────────────────────────────────────────────
        sf = tk.LabelFrame(self, text=f"  {t('watermark.settings_section')}  ", padx=16, pady=10)
        sf.pack(fill="x", padx=20, pady=10)

        # Row A: position + margin
        ra = tk.Frame(sf)
        ra.pack(fill="x", pady=4)
        tk.Label(ra, text=t("watermark.position_label"), width=16, anchor="e").pack(side="left")
        self._pos_var = tk.StringVar(value="Bottom-Right")
        pos_cb = ttk.Combobox(ra, textvariable=self._pos_var,
                               values=list(POSITIONS.keys()),
                               state="readonly", width=18)
        pos_cb.pack(side="left", padx=8)
        pos_cb.bind("<<ComboboxSelected>>", self._on_pos_change)

        tk.Label(ra, text=f"   {t('watermark.margin_label')}").pack(side="left")
        self._margin = tk.StringVar(value="20")
        tk.Entry(ra, textvariable=self._margin, width=5,
                 relief="flat").pack(side="left", padx=6)

        # Custom X/Y (shown only when Position = Custom)
        self._custom_frame = tk.Frame(ra)
        self._custom_frame.pack(side="left", padx=8)
        tk.Label(self._custom_frame, text="X:").pack(side="left")
        self._custom_x = tk.StringVar(value="50")
        tk.Entry(self._custom_frame, textvariable=self._custom_x,
                 width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(self._custom_frame, text="Y:").pack(side="left")
        self._custom_y = tk.StringVar(value="50")
        tk.Entry(self._custom_frame, textvariable=self._custom_y,
                 width=5, relief="flat").pack(side="left", padx=4)
        self._custom_frame.pack_forget()   # hidden by default

        # Row B: size + opacity
        rb = tk.Frame(sf)
        rb.pack(fill="x", pady=4)
        tk.Label(rb, text=t("watermark.size_label"), width=16, anchor="e").pack(side="left")
        self._size_pct = tk.IntVar(value=15)
        size_scale = tk.Scale(rb, variable=self._size_pct, from_=2, to=80,
                               orient="horizontal", length=180)
        size_scale.pack(side="left", padx=8)
        self._size_lbl = tk.Label(rb, text="15%", width=5, fg=CLR["accent"])
        self._size_lbl.pack(side="left")
        self._size_pct.trace_add("write", lambda *_: self._size_lbl.config(
            text=t("ducker.item").format(self._size_pct.get())))

        tk.Label(rb, text=f"   {t('watermark.opacity_label')}", padx=8).pack(side="left")
        self._opacity = tk.DoubleVar(value=1.0)
        tk.Scale(rb, variable=self._opacity, from_=0.05, to=1.0,
                 resolution=0.05, orient="horizontal",
                 length=160).pack(side="left", padx=4)
        self._opacity_lbl = tk.Label(rb, text="100%", width=5, fg=CLR["accent"])
        self._opacity_lbl.pack(side="left")
        self._opacity.trace_add("write", lambda *_: self._opacity_lbl.config(
            text=t("ducker.item").format(int(self._opacity.get() * 100))))

        # Row C: time range (optional)
        rc = tk.Frame(sf)
        rc.pack(fill="x", pady=4)
        self._use_timerange = tk.BooleanVar(value=False)
        tk.Checkbutton(rc, text=t("watermark.time_range_checkbox"),
                       variable=self._use_timerange,
                       command=self._on_timerange_toggle).pack(side="left")
        self._time_start = tk.StringVar(value="0")
        self._t_start_entry = tk.Entry(rc, textvariable=self._time_start,
                                        width=6, relief="flat", state="disabled")
        self._t_start_entry.pack(side="left", padx=4)
        tk.Label(rc, text=t("image_watermark.s_and")).pack(side="left")
        self._time_end = tk.StringVar(value="10")
        self._t_end_entry = tk.Entry(rc, textvariable=self._time_end,
                                      width=6, relief="flat", state="disabled")
        self._t_end_entry.pack(side="left", padx=4)
        tk.Label(rc, text="s").pack(side="left")
        tk.Label(rc, text=f"  {t('watermark.time_range_hint')}",
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=8)

        # ── Output ────────────────────────────────────────────────────────────
        ro = tk.Frame(self)
        ro.pack(fill="x", padx=16, pady=6)
        tk.Label(ro, text=t("common.output_file"),
                 font=(UI_FONT, 10, "bold"), width=18, anchor="e").pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(ro, textvariable=self._out_var, width=58,
                 relief="flat").pack(side="left", padx=8)
        tk.Button(ro, text=t("common.save_as"), command=self._browse_out,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Render button ──────────────────────────────────────────────────────
        self._btn_render = tk.Button(
            self, text=t("watermark.burn_button"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["orange"], fg="white",
            height=2, width=28,
            command=self._render)
        self._btn_render.pack(pady=10)

        # ── Console ───────────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─── Callbacks ────────────────────────────────────────────────────────────
    def _on_pos_change(self, _event=None):
        if self._pos_var.get() == "Custom":
            self._custom_frame.pack(side="left", padx=8)
        else:
            self._custom_frame.pack_forget()

    def _on_timerange_toggle(self):
        state = "normal" if self._use_timerange.get() else "disabled"
        self._t_start_entry.config(state=state)
        self._t_end_entry.config(state=state)

    def _browse_src(self):
        p = filedialog.askopenfilename(
            title="Select source video",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self._src_var.set(p)
            if not self._out_var.get():
                self._out_var.set(os.path.splitext(p)[0] + "_watermarked.mp4")

    def _browse_img(self):
        p = filedialog.askopenfilename(
            title="Select logo / watermark image",
            filetypes=[("Image", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                        ("All", t("ducker.item_2"))])
        if p:
            self._img_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p:
            self._out_var.set(p)

    # ─── Render ───────────────────────────────────────────────────────────────
    def _render(self):
        src = self._src_var.get().strip()
        img = self._img_var.get().strip()
        out = self._out_var.get().strip()

        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("watermark.no_source_message"))
            return
        if not img or not os.path.exists(img):
            messagebox.showwarning(t("common.warning"), t("watermark.no_image_message"))
            return
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        try:
            margin  = int(self._margin.get())
            size_pct = int(self._size_pct.get())
            opacity  = float(self._opacity.get())
        except ValueError:
            messagebox.showwarning(t("common.warning"), "Margin must be a whole number.")
            return

        # Resolve position expression - substitute MARGIN and CUSTOM values
        pos_key = self._pos_var.get()
        x_tmpl, y_tmpl = POSITIONS[pos_key]
        x_expr = x_tmpl.replace("MARGIN", str(margin)) \
                        .replace("CUSTOM_X", self._custom_x.get())
        y_expr = y_tmpl.replace("MARGIN", str(margin)) \
                        .replace("CUSTOM_Y", self._custom_y.get())

        # Logo width = size_pct% of the video width (iw refers to INPUT video)
        # scale=W*PCT:-1 scales width proportionally, height is auto
        logo_w = "iw*{}/100".format(size_pct)

        # Build filter chain for the logo stream
        # 1. Scale to desired width
        # 2. Convert to RGBA so opacity works even on opaque JPGs
        # 3. Apply opacity via colorchannelmixer (multiplies alpha channel)
        logo_filter = (
            "[1:v]scale={w}:-1,"
            "format=rgba,"
            "colorchannelmixer=aa={op:.2f}"
            "[logo]"
        ).format(w=logo_w, op=opacity)

        # Build overlay expression with optional time range
        if self._use_timerange.get():
            try:
                t0 = float(self._time_start.get())
                t1 = float(self._time_end.get())
            except ValueError:
                messagebox.showwarning(t("common.warning"),
                                       "Start/End times must be numbers.")
                return
            enable = ":enable='between(t,{},{})'"  .format(t0, t1)
        else:
            enable = ""

        overlay_filter = "[0:v][logo]overlay={}:{}{}".format(
            x_expr, y_expr, enable)

        fc = "{};{}".format(logo_filter, overlay_filter)

        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [
            ffmpeg, "-y",
            "-i", src,
            "-i", img,
            "-filter_complex", fc,
            t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]

        self.log(self.console,
                 "▶ Burning {} onto video at {} ({}%, opacity {:.0%})".format(
                     os.path.basename(img), pos_key, size_pct, opacity))
        self.run_ffmpeg(
            cmd, self.console,
            on_done=lambda rc: self.show_result(rc, out),
            btn=self._btn_render,
            btn_label=t("watermark.burn_button"),
        )
