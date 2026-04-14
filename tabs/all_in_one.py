"""
tab_allinone.py  ─  All-in-One Pipeline Builder

Select a video, enable any combination of processing steps, and the
tab assembles a single optimised FFmpeg command that does everything
in one pass - no intermediate files, no quality loss from multiple
re-encodes.

The generated command is shown in a live-updating editable box at the
bottom. You can tweak it by hand before rendering.

Sections (all optional, all combinable):
  ✂  Trim            - start/end timestamps
  📐  Scale           - resolution + algorithm
  🎬  Frame Rate      - target FPS
  🔄  Rotate & Flip   - transpose / hflip / vflip
  ⚡  Speed           - constant speed multiplier with audio pitch
  🎨  Color & Image   - eq, hue, lift/gain
  🌫  Denoise         - hqdn3d or nlmeans
  🔪  Sharpen         - unsharp mask
  🔊  Audio           - volume, normalise, fade in/out
  💬  Text Overlay    - burned-in watermark / caption
  🌅  Fade            - video and audio fade in/out
  ⚙   Encode          - codec, CRF, preset, audio bitrate
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shlex
import subprocess
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, CREATE_NO_WINDOW,
    get_video_duration,
)
from core.i18n import t

# ── Constants reused from other tabs ─────────────────────────────────────────

_RES_PRESETS = [
    "7680x4320 (8K)", "3840x2160 (4K UHD)", "2560x1440 (QHD/2K)",
    "1920x1080 (Full HD)", "1280x720 (HD)",
    "854x480 (SD)", "640x360 (360p)", "Custom…",
]
_SCALE_ALGO = {
    "Lanczos (best downscale)":  "lanczos",
    "Lanczos4 (best upscale)":   "lanczos", # Changed from lanczos4 for compatibility
    "Bicubic":                   "bicubic",
    "Bilinear (fastest)":        "bilinear",
    "Nearest (pixel art)":       "neighbor",
}

# Updated to a dictionary to translate friendly UI names to FFmpeg identifiers
_VCODECS = {
    "H.264 (CPU)": "libx264",
    "H.265 / HEVC (CPU)": "libx265",
    "H.264 (Nvidia HW)": "h264_nvenc",
    "H.265 / HEVC (Nvidia HW)": "hevc_nvenc",
    "H.264 (AMD HW)": "h264_amf",
    "H.265 / HEVC (AMD HW)": "hevc_amf",
    "H.264 (Intel HW)": "h264_qsv",
    "H.265 / HEVC (Intel HW)": "hevc_qsv",
    "VP9 (CPU)": "libvpx-vp9",
    "ProRes (CPU)": "prores_ks",
    "Copy (No re-encode)": "copy"
}

_ACODECS   = ["aac", "libmp3lame", "libopus", "libvorbis", "copy", "none"]
_PRESETS   = ["ultrafast","superfast","veryfast","faster",
              "fast","medium","slow","slower","veryslow"]
_ABITRATES = ["96k","128k","192k","256k","320k"]
_FPS_VALS  = ["23.976","24","25","29.97","30","48","50","59.94","60","120"]

_TEXT_POSITIONS = {
    "Bottom Centre": "x=(w-text_w)/2:y=h-text_h-30",
    "Top Centre":    "x=(w-text_w)/2:y=30",
    "Bottom Left":   "x=30:y=h-text_h-30",
    "Bottom Right":  "x=w-text_w-30:y=h-text_h-30",
    "Centre":        "x=(w-text_w)/2:y=(h-text_h)/2",
    "Top Left":      "x=30:y=30",
    "Top Right":     "x=w-text_w-30:y=30",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Small UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def _lbl(parent, text, bold=False, dim=False):
    fg   = CLR["fgdim"] if dim else CLR["fg"]
    font = (UI_FONT, 9, "bold") if bold else (UI_FONT, 9)
    return tk.Label(parent, text=text, bg=CLR["bg"],
                    fg=fg, font=font)


def _entry(parent, var, width=10):
    return tk.Entry(parent, textvariable=var, width=width,
                    bg=CLR["panel"], fg=CLR["fg"],
                    insertbackground=CLR["fg"],
                    relief="flat", bd=4)


def _combo(parent, var, values, width=18, state="readonly"):
    cb = ttk.Combobox(parent, textvariable=var, values=values,
                      state=state, width=width)
    return cb


def _spin(parent, var, from_, to, inc=0.5, width=7):
    return tk.Spinbox(parent, from_=from_, to=to, increment=inc,
                      textvariable=var, width=width,
                      bg=CLR["panel"], fg=CLR["fg"],
                      buttonbackground=CLR["panel"],
                      insertbackground=CLR["fg"],
                      relief="flat")


def _row(parent, pady=3):
    f = tk.Frame(parent, bg=CLR["bg"])
    f.pack(fill="x", pady=pady)
    return f


def _pack_lr(*widgets, padx=6):
    """Pack a sequence of widgets left-to-right."""
    for w in widgets:
        w.pack(side="left", padx=padx)


# ─────────────────────────────────────────────────────────────────────────────
#  Section container
# ─────────────────────────────────────────────────────────────────────────────

class _Section(tk.Frame):
    """
    A collapsible section with a checkbox header.
    When the checkbox is off all interior widgets are disabled (greyed out).
    Calls *on_toggle* whenever the enabled state changes.
    """
    def __init__(self, parent, title, on_toggle, **kw):
        super().__init__(parent, bg=CLR["bg"], **kw)
        self._en  = tk.BooleanVar(value=False)
        self._cb  = on_toggle

        # ── Header row ────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Checkbutton(
            hdr, text=title,
            variable=self._en,
            font=(UI_FONT, 10, "bold"),
            bg=CLR["panel"], fg=CLR["fg"],
            selectcolor=CLR["sb_active"] if "sb_active" in CLR else "#333333",
            activebackground=CLR["panel"],
            command=self._toggled,
        ).pack(side="left", padx=10, pady=6)

        # ── Body ──────────────────────────────────────────────────────────
        self.body = tk.Frame(self, bg=CLR["bg"], padx=16, pady=6)
        self.body.pack(fill="x")
        self._set_body_state("disabled")

    def get(self):
        return self._en.get()

    def _toggled(self):
        self._set_body_state("normal" if self._en.get() else "disabled")
        self._cb()

    def _set_body_state(self, state):
        fg = CLR["fg"] if state == "normal" else CLR["fgdim"]
        self._walk(self.body, state, fg)

    def _walk(self, widget, state, fg):
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "Spinbox", "Button", "Checkbutton",
                       "Radiobutton"):
                widget.config(state=state)
            if cls in ("Label",):
                widget.config(fg=fg)
            if cls == "TCombobox":
                widget.config(state="readonly" if state == "normal" else "disabled")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._walk(child, state, fg)


# ─────────────────────────────────────────────────────────────────────────────
#  Main tab
# ─────────────────────────────────────────────────────────────────────────────

class AllInOneTab(BaseTab):
    """Pipeline builder - combine any processing steps into one FFmpeg pass."""

    def __init__(self, parent):
        super().__init__(parent)
        self._duration   = 0.0    # loaded video duration - needed for fade-out math
        self._last_cmd   = []     # most recently built command list
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────
    #  Top-level layout
    # ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Fixed header ──────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎛  " + t("tab.all_in_one"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(
            side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("all_in_one.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Source / output (always visible, above scroll) ─────────────────
        io_frame = tk.Frame(self, bg=CLR["bg"], padx=12, pady=8)
        io_frame.pack(fill="x")
        self._build_io(io_frame)

        # ── Scrollable section area ────────────────────────────────────────
        self._canvas = tk.Canvas(self, highlightthickness=0, bg=CLR["bg"])
        _sb = ttk.Scrollbar(self, orient="vertical",
                            command=self._canvas.yview)
        self._scroll_inner = tk.Frame(self._canvas, bg=CLR["bg"])
        self._canvas.create_window((0, 0), window=self._scroll_inner,
                                   anchor="nw")
        self._scroll_inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        self._canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas.bind("<MouseWheel>", _on_mousewheel)
        self._scroll_inner.bind("<MouseWheel>", _on_mousewheel)

        self._build_sections(self._scroll_inner)

        # ── Fixed bottom: command display + render ─────────────────────────
        self._build_bottom()

    # ─────────────────────────────────────────────────────────────────────
    #  Source / Output
    # ─────────────────────────────────────────────────────────────────────

    def _build_io(self, parent):
        self._src_var = tk.StringVar()
        self._out_var = tk.StringVar()

        r1 = _row(parent, pady=2)
        _lbl(r1, t("common.source_video"), bold=True).pack(side="left")
        _entry(r1, self._src_var, width=62).pack(side="left", padx=8)
        tk.Button(r1, text=t("btn.browse"), command=self._browse_src,
                  bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")
        self._dur_lbl = tk.Label(r1, text="", bg=CLR["bg"],
                                 fg=CLR["accent"], font=(MONO_FONT, 9))
        self._dur_lbl.pack(side="left", padx=10)

        r2 = _row(parent, pady=2)
        _lbl(r2, t("common.output_file"), bold=True).pack(side="left")
        _entry(r2, self._out_var, width=62).pack(side="left", padx=8)
        tk.Button(r2, text=t("common.save_as"), command=self._browse_out,
                  bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")

    def _browse_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", "*.*")])
        if not p:
            return
        self._src_var.set(p)
        base = os.path.splitext(p)[0]
        if not self._out_var.get():
            self._out_var.set(base + "_pipeline.mp4")
        # Load duration in background
        threading.Thread(target=self._load_duration,
                         args=(p,), daemon=True).start()
        self._rebuild_cmd()

    def _load_duration(self, path):
        dur = get_video_duration(path)
        self._duration = dur
        self.after(0, lambda: self._dur_lbl.config(
            text="{:.2f}s".format(dur) if dur else ""))
        self.after(0, self._rebuild_cmd)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"),
                       ("MOV", "*.mov"), ("All", "*.*")])
        if p:
            self._out_var.set(p)
            self._rebuild_cmd()

    # ─────────────────────────────────────────────────────────────────────
    #  Sections
    # ─────────────────────────────────────────────────────────────────────

    def _build_sections(self, parent):
        """Build all optional processing sections inside the scrollable area."""

        def sep():
            tk.Frame(parent, bg=CLR["panel"], height=2).pack(
                fill="x", pady=2)

        self._build_trim(parent);       sep()
        self._build_scale(parent);      sep()
        self._build_fps(parent);        sep()
        self._build_rotate(parent);     sep()
        self._build_speed(parent);      sep()
        self._build_color(parent);      sep()
        self._build_denoise(parent);    sep()
        self._build_sharpen(parent);    sep()
        self._build_audio(parent);      sep()
        self._build_text(parent);       sep()
        self._build_fade(parent);       sep()
        self._build_encode(parent)

    # ── ✂ Trim ────────────────────────────────────────────────────────────

    def _build_trim(self, parent):
        self._sec_trim = _Section(parent, "✂  Trim",
                                  self._rebuild_cmd)
        self._sec_trim.pack(fill="x", pady=1)
        b = self._sec_trim.body

        self._trim_start = tk.StringVar(value="0.0")
        self._trim_end   = tk.StringVar(value="")
        self._trim_start.trace_add("write", lambda *_: self._rebuild_cmd())
        self._trim_end.trace_add("write",   lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Start (s):").pack(side="left")
        _entry(r, self._trim_start, 8).pack(side="left", padx=6)
        _lbl(r, "  End (s):").pack(side="left")
        _entry(r, self._trim_end, 8).pack(side="left", padx=6)
        _lbl(r, "(leave End blank to go to end of video)", dim=True).pack(
            side="left", padx=6)

    # ── 📐 Scale ──────────────────────────────────────────────────────────

    def _build_scale(self, parent):
        self._sec_scale = _Section(parent, "📐  Scale / Resolution",
                                   self._rebuild_cmd)
        self._sec_scale.pack(fill="x", pady=1)
        b = self._sec_scale.body

        self._scale_preset = tk.StringVar(value=_RES_PRESETS[3])
        self._scale_w      = tk.StringVar(value="1920")
        self._scale_h      = tk.StringVar(value="1080")
        self._scale_algo   = tk.StringVar(value=list(_SCALE_ALGO.keys())[0])
        self._scale_pad    = tk.BooleanVar(value=False)

        for v in (self._scale_preset, self._scale_w, self._scale_h,
                  self._scale_algo):
            v.trace_add("write", lambda *_: self._rebuild_cmd())
        self._scale_pad.trace_add("write", lambda *_: self._rebuild_cmd())

        r1 = _row(b)
        _lbl(r1, "Preset:").pack(side="left")
        cb = _combo(r1, self._scale_preset, _RES_PRESETS, width=24)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", self._on_res_preset)
        _lbl(r1, "  W:").pack(side="left")
        self._scale_w_entry = _entry(r1, self._scale_w, 6)
        self._scale_w_entry.pack(side="left", padx=3)
        _lbl(r1, "H:").pack(side="left")
        self._scale_h_entry = _entry(r1, self._scale_h, 6)
        self._scale_h_entry.pack(side="left", padx=3)
        _lbl(r1, "(-1 = auto-aspect)", dim=True).pack(side="left", padx=6)

        r2 = _row(b)
        _lbl(r2, "Algorithm:").pack(side="left")
        _combo(r2, self._scale_algo,
               list(_SCALE_ALGO.keys()), width=26).pack(side="left", padx=6)
        tk.Checkbutton(r2, text="Pad to exact size (adds black bars)",
                       variable=self._scale_pad,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left", padx=10)

    def _on_res_preset(self, *_):
        val = self._scale_preset.get()
        if "Custom" not in val:
            wh = val.split(" ")[0].split("x")
            if len(wh) == 2:
                self._scale_w.set(wh[0])
                self._scale_h.set(wh[1])
        self._rebuild_cmd()

    # ── 🎬 Frame Rate ─────────────────────────────────────────────────────

    def _build_fps(self, parent):
        self._sec_fps = _Section(parent, "🎬  Frame Rate",
                                 self._rebuild_cmd)
        self._sec_fps.pack(fill="x", pady=1)
        b = self._sec_fps.body

        self._fps_val = tk.StringVar(value="30")
        self._fps_val.trace_add("write", lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Target FPS:").pack(side="left")
        cb = _combo(r, self._fps_val, _FPS_VALS, width=8, state="normal")
        cb.pack(side="left", padx=6)
        _lbl(r, "(or type any value)", dim=True).pack(side="left", padx=4)

    # ── 🔄 Rotate & Flip ─────────────────────────────────────────────────

    def _build_rotate(self, parent):
        self._sec_rotate = _Section(parent, "🔄  Rotate & Flip",
                                    self._rebuild_cmd)
        self._sec_rotate.pack(fill="x", pady=1)
        b = self._sec_rotate.body

        self._rotate_val = tk.StringVar(value="0")
        self._flip_h     = tk.BooleanVar(value=False)
        self._flip_v     = tk.BooleanVar(value=False)

        for v in (self._rotate_val, self._flip_h, self._flip_v):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Rotation:").pack(side="left")
        for val, label in [("0","None"),("90","90° CW"),
                            ("180","180°"),("270","90° CCW")]:
            tk.Radiobutton(
                r, text=label, variable=self._rotate_val, value=val,
                bg=CLR["bg"], fg=CLR["fg"],
                selectcolor=CLR["panel"],
                activebackground=CLR["bg"],
                command=self._rebuild_cmd,
            ).pack(side="left", padx=8)

        r2 = _row(b)
        tk.Checkbutton(r2, text="Flip Horizontal (Mirror)",
                       variable=self._flip_h,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left", padx=4)
        tk.Checkbutton(r2, text="Flip Vertical",
                       variable=self._flip_v,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left", padx=20)

    # ── ⚡ Speed ──────────────────────────────────────────────────────────

    def _build_speed(self, parent):
        self._sec_speed = _Section(parent, "⚡  Speed",
                                   self._rebuild_cmd)
        self._sec_speed.pack(fill="x", pady=1)
        b = self._sec_speed.body

        self._speed_val   = tk.StringVar(value="2.0")
        self._speed_pitch = tk.BooleanVar(value=True)
        for v in (self._speed_val, self._speed_pitch):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Speed multiplier:").pack(side="left")
        _spin(r, self._speed_val, 0.05, 16, 0.25, width=6).pack(
            side="left", padx=6)
        _lbl(r, "(0.5 = half speed · 2.0 = double)", dim=True).pack(
            side="left", padx=6)

        r2 = _row(b)
        tk.Checkbutton(r2, text="Preserve audio pitch (atempo)",
                       variable=self._speed_pitch,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left", padx=4)
        _lbl(r2, "(when off, audio speeds up / slows down raw)",
             dim=True).pack(side="left", padx=6)

    # ── 🎨 Color & Image ──────────────────────────────────────────────────

    def _build_color(self, parent):
        self._sec_color = _Section(parent, "🎨  Color & Image",
                                   self._rebuild_cmd)
        self._sec_color.pack(fill="x", pady=1)
        b = self._sec_color.body

        def _sv(default):
            v = tk.StringVar(value=str(default))
            v.trace_add("write", lambda *_: self._rebuild_cmd())
            return v

        self._bri = _sv("0.00")
        self._con = _sv("1.00")
        self._sat = _sv("1.00")
        self._gam = _sv("1.00")
        self._hue = _sv("0")

        sliders = [
            ("Brightness:", self._bri, -1.0, 1.0, 0.05),
            ("Contrast:",   self._con,  0.1, 3.0, 0.05),
            ("Saturation:", self._sat,  0.0, 3.0, 0.05),
            ("Gamma:",      self._gam,  0.1, 5.0, 0.05),
            ("Hue shift°:", self._hue, -180,180,  5.0),
        ]
        for label, var, lo, hi, inc in sliders:
            r = _row(b, pady=2)
            _lbl(r, label, bold=True).pack(side="left")
            sc = tk.Scale(
                r, variable=var, from_=lo, to=hi, resolution=inc,
                orient="horizontal", length=280,
                bg=CLR["bg"], fg=CLR["fg"],
                troughcolor=CLR["panel"],
                highlightthickness=0,
                command=lambda v, var=var: (var.set(
                    "{:.2f}".format(float(v))), self._rebuild_cmd()),
            )
            sc.pack(side="left", padx=6)
            _lbl(r, "", dim=True).pack(side="left")  # spacer

        r5 = _row(b, pady=2)
        tk.Button(r5, text="Reset all to defaults",
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=self._reset_color).pack(side="left")

    def _reset_color(self):
        self._bri.set("0.00"); self._con.set("1.00")
        self._sat.set("1.00"); self._gam.set("1.00"); self._hue.set("0")
        self._rebuild_cmd()

    # ── 🌫 Denoise ────────────────────────────────────────────────────────

    def _build_denoise(self, parent):
        self._sec_denoise = _Section(parent, "🌫  Denoise",
                                     self._rebuild_cmd)
        self._sec_denoise.pack(fill="x", pady=1)
        b = self._sec_denoise.body

        self._denoise_algo = tk.StringVar(value="hqdn3d")
        self._denoise_str  = tk.StringVar(value="Medium")
        for v in (self._denoise_algo, self._denoise_str):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Algorithm:").pack(side="left")
        for val, lbl in [("hqdn3d","HQDN3D (fast)"),
                          ("nlmeans","NLMeans (quality)")]:
            tk.Radiobutton(
                r, text=lbl, variable=self._denoise_algo, value=val,
                bg=CLR["bg"], fg=CLR["fg"],
                selectcolor=CLR["panel"],
                activebackground=CLR["bg"],
                command=self._rebuild_cmd,
            ).pack(side="left", padx=10)

        r2 = _row(b)
        _lbl(r2, "Strength:").pack(side="left")
        _combo(r2, self._denoise_str,
               ["Light","Medium","Strong","Aggressive"], width=12).pack(
            side="left", padx=6)

    # ── 🔪 Sharpen ────────────────────────────────────────────────────────

    def _build_sharpen(self, parent):
        self._sec_sharpen = _Section(parent, "🔪  Sharpen",
                                     self._rebuild_cmd)
        self._sec_sharpen.pack(fill="x", pady=1)
        b = self._sec_sharpen.body

        self._sharp_lx = tk.StringVar(value="5")
        self._sharp_la = tk.StringVar(value="1.0")
        for v in (self._sharp_lx, self._sharp_la):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r = _row(b)
        _lbl(r, "Kernel size (odd):").pack(side="left")
        _combo(r, self._sharp_lx,
               ["3","5","7"], width=4).pack(side="left", padx=6)
        _lbl(r, "  Amount (luma):").pack(side="left")
        _spin(r, self._sharp_la, 0.1, 5.0, 0.1, width=5).pack(
            side="left", padx=6)
        _lbl(r, "(0.5 subtle · 1.0 standard · 2.5 aggressive)",
             dim=True).pack(side="left", padx=6)

    # ── 🔊 Audio ──────────────────────────────────────────────────────────

    def _build_audio(self, parent):
        self._sec_audio = _Section(parent, "🔊  Audio Processing",
                                   self._rebuild_cmd)
        self._sec_audio.pack(fill="x", pady=1)
        b = self._sec_audio.body

        self._vol_en   = tk.BooleanVar(value=False)
        self._vol_val  = tk.StringVar(value="1.5")
        self._norm_en  = tk.BooleanVar(value=False)
        self._norm_lufs= tk.StringVar(value="-23")

        for v in (self._vol_en, self._vol_val,
                  self._norm_en, self._norm_lufs):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r1 = _row(b)
        tk.Checkbutton(r1, text="Adjust volume ×",
                       variable=self._vol_en,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left")
        _spin(r1, self._vol_val, 0.05, 10, 0.05, width=5).pack(
            side="left", padx=6)
        _lbl(r1, "(1.0 = no change · 2.0 = double)", dim=True).pack(
            side="left", padx=4)

        r2 = _row(b)
        tk.Checkbutton(r2, text="Loudness normalise to",
                       variable=self._norm_en,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left")
        _combo(r2, self._norm_lufs,
               ["-14","-16","-18","-23","-24"],
               width=5, state="normal").pack(side="left", padx=4)
        _lbl(r2, "LUFS  (YouTube = -14 · broadcast = -23)",
             dim=True).pack(side="left", padx=4)

    # ── 💬 Text Overlay ───────────────────────────────────────────────────

    def _build_text(self, parent):
        self._sec_text = _Section(parent, "💬  Text / Watermark Overlay",
                                  self._rebuild_cmd)
        self._sec_text.pack(fill="x", pady=1)
        b = self._sec_text.body

        self._text_val   = tk.StringVar(value="@YourChannel")
        self._text_size  = tk.StringVar(value="42")
        self._text_color = tk.StringVar(value="white")
        self._text_pos   = tk.StringVar(value="Bottom Right")
        self._text_start = tk.StringVar(value="0")
        self._text_end   = tk.StringVar(value="")

        for v in (self._text_val, self._text_size, self._text_color,
                  self._text_pos, self._text_start, self._text_end):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r1 = _row(b)
        _lbl(r1, "Text:").pack(side="left")
        _entry(r1, self._text_val, 34).pack(side="left", padx=6)
        _lbl(r1, "  Size:").pack(side="left")
        _spin(r1, self._text_size, 8, 200, 2, width=5).pack(
            side="left", padx=4)
        _lbl(r1, "  Colour:").pack(side="left")
        _combo(r1, self._text_color,
               ["white","yellow","red","cyan","black","orange"],
               width=8).pack(side="left", padx=4)

        r2 = _row(b)
        _lbl(r2, "Position:").pack(side="left")
        _combo(r2, self._text_pos,
               list(_TEXT_POSITIONS.keys()), width=14).pack(
            side="left", padx=6)
        _lbl(r2, "  Show from (s):").pack(side="left")
        _entry(r2, self._text_start, 6).pack(side="left", padx=4)
        _lbl(r2, "  to (s, blank = end):").pack(side="left")
        _entry(r2, self._text_end, 6).pack(side="left", padx=4)

    # ── 🌅 Fade In / Out ─────────────────────────────────────────────────

    def _build_fade(self, parent):
        self._sec_fade = _Section(parent, "🌅  Fade In / Fade Out",
                                  self._rebuild_cmd)
        self._sec_fade.pack(fill="x", pady=1)
        b = self._sec_fade.body

        self._fi_en  = tk.BooleanVar(value=False)
        self._fi_dur = tk.StringVar(value="1.5")
        self._fo_en  = tk.BooleanVar(value=False)
        self._fo_dur = tk.StringVar(value="2.0")
        self._fade_audio = tk.BooleanVar(value=True)

        for v in (self._fi_en, self._fi_dur,
                  self._fo_en, self._fo_dur, self._fade_audio):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r1 = _row(b)
        tk.Checkbutton(r1, text="Fade IN duration (s):",
                       variable=self._fi_en,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left")
        _spin(r1, self._fi_dur, 0.2, 10, 0.5, width=5).pack(
            side="left", padx=6)

        r2 = _row(b)
        tk.Checkbutton(r2, text="Fade OUT duration (s):",
                       variable=self._fo_en,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left")
        _spin(r2, self._fo_dur, 0.2, 10, 0.5, width=5).pack(
            side="left", padx=6)
        _lbl(r2, "(requires source duration to be loaded)", dim=True).pack(
            side="left", padx=6)

        r3 = _row(b)
        tk.Checkbutton(r3, text="Also fade audio in/out",
                       variable=self._fade_audio,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"],
                       command=self._rebuild_cmd).pack(side="left")

    # ── ⚙ Encode Settings ─────────────────────────────────────────────────

    def _build_encode(self, parent):
        self._sec_encode = _Section(parent, "⚙  Encode Settings",
                                    self._rebuild_cmd)
        self._sec_encode.pack(fill="x", pady=1)
        # Default ON - you almost always want to set these
        self._sec_encode._en.set(True)
        self._sec_encode._set_body_state("normal")
        b = self._sec_encode.body

        self._vcodec  = tk.StringVar(value="H.264 (CPU)")
        self._crf     = tk.StringVar(value="18")
        self._preset  = tk.StringVar(value="fast")
        self._acodec  = tk.StringVar(value="aac")
        self._abitrate= tk.StringVar(value="192k")

        for v in (self._vcodec, self._crf, self._preset,
                  self._acodec, self._abitrate):
            v.trace_add("write", lambda *_: self._rebuild_cmd())

        r1 = _row(b)
        _lbl(r1, "Video codec:").pack(side="left")
        _combo(r1, self._vcodec, list(_VCODECS.keys()), width=24).pack(
            side="left", padx=6)
        _lbl(r1, "  Quality (CRF/CQ):").pack(side="left")
        _combo(r1, self._crf,
               [str(x) for x in range(12, 32)],
               width=4).pack(side="left", padx=4)
        _lbl(r1, "  Preset:").pack(side="left")
        _combo(r1, self._preset, _PRESETS, width=10).pack(
            side="left", padx=4)

        r2 = _row(b)
        _lbl(r2, "Audio codec:").pack(side="left")
        _combo(r2, self._acodec, _ACODECS, width=12).pack(
            side="left", padx=6)
        _lbl(r2, "  Bitrate:").pack(side="left")
        _combo(r2, self._abitrate, _ABITRATES, width=7).pack(
            side="left", padx=4)
        _lbl(r2, "(ignored when codec = copy / none)", dim=True).pack(
            side="left", padx=6)

    # ─────────────────────────────────────────────────────────────────────
    #  Fixed bottom bar: command display + render
    # ─────────────────────────────────────────────────────────────────────

    def _build_bottom(self):
        bottom = tk.Frame(self, bg=CLR["panel"])
        bottom.pack(side="bottom", fill="x")

        # ── Command label + copy button ────────────────────────────────────
        cmd_hdr = tk.Frame(bottom, bg=CLR["panel"])
        cmd_hdr.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(cmd_hdr,
                 text="📋  Generated FFmpeg Command  (editable; your changes are preserved on render)",
                 font=(UI_FONT, 9, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Button(cmd_hdr, text="Copy to clipboard",
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=self._copy_cmd).pack(side="right", padx=4)
        tk.Button(cmd_hdr, text="Reset command",
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=self._rebuild_cmd).pack(side="right", padx=4)

        # ── Command text widget (editable) ────────────────────────────────
        cmd_frame = tk.Frame(bottom, bg=CLR["panel"])
        cmd_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._cmd_text = tk.Text(
            cmd_frame,
            height=5,
            bg="#0A0A0A", fg="#00FF88",
            font=(MONO_FONT, 9),
            wrap="none",
            insertbackground="#00FF88",
            relief="flat",
            bd=4,
        )
        cmd_sb_x = ttk.Scrollbar(cmd_frame, orient="horizontal",
                                  command=self._cmd_text.xview)
        cmd_sb_y = ttk.Scrollbar(cmd_frame, orient="vertical",
                                  command=self._cmd_text.yview)
        self._cmd_text.configure(xscrollcommand=cmd_sb_x.set,
                                  yscrollcommand=cmd_sb_y.set)
        cmd_sb_y.pack(side="right", fill="y")
        self._cmd_text.pack(side="left", fill="x", expand=True)
        cmd_sb_x.pack(side="bottom", fill="x")

        # ── Action buttons ────────────────────────────────────────────────
        btn_row = tk.Frame(bottom, bg=CLR["panel"])
        btn_row.pack(fill="x", padx=12, pady=(4, 10))

        self._btn_render = tk.Button(
            btn_row,
            text="▶  RENDER",
            font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="black",
            height=2, width=20,
            cursor="hand2",
            command=self._render,
        )
        self._btn_render.pack(side="left", padx=8)

        self._btn_stop = tk.Button(
            btn_row,
            text="⏹  STOP",
            font=(UI_FONT, 12, "bold"),
            bg="#D32F2F", fg="white",
            height=2, width=10,
            cursor="hand2",
            state="disabled",
            command=self._stop_render,
        )
        self._btn_stop.pack(side="left", padx=4)

        tk.Button(
            btn_row, text="💾  Save Command as .bat",
            bg=CLR["panel"], fg=CLR["fg"],
            height=2,
            command=self._save_bat,
        ).pack(side="left", padx=4)

        tk.Button(
            btn_row, text="💾  Save Command as .sh",
            bg=CLR["panel"], fg=CLR["fg"],
            height=2,
            command=self._save_sh,
        ).pack(side="left", padx=4)

        # Console
        con_frame = tk.Frame(bottom, bg=CLR["panel"])
        con_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.console, csb = self.make_console(con_frame, height=5)
        self.console.pack(side="left", fill="x", expand=True)
        csb.pack(side="right", fill="y")

        # Initial command render
        self._rebuild_cmd()

    # ─────────────────────────────────────────────────────────────────────
    #  Command builder  ← the heart of the tab
    # ─────────────────────────────────────────────────────────────────────

    def _rebuild_cmd(self, *_):
        """
        Assemble an FFmpeg command from all enabled sections and update
        the editable command display.  Called whenever any variable changes.
        """
        # Guards against variables attempting to update text box before UI creation
        if not hasattr(self, "_cmd_text"):
            return

        src = self._src_var.get().strip()
        out = self._out_var.get().strip()

        if not src or not out:
            self._set_cmd_text(
                "# Select a source video and output file above\n"
                "# to generate the FFmpeg command.")
            return

        ff      = get_binary_path("ffmpeg")
        parts   = [ff, "-y"]
        vf      = []     # video filter chain parts
        af      = []     # audio filter chain parts

        # ── Trim: -ss before -i for fast keyframe seek ────────────────────
        trim_en    = self._sec_trim.get()
        trim_start = 0.0
        trim_dur   = None

        if trim_en:
            try:
                trim_start = float(self._trim_start.get())
            except ValueError:
                trim_start = 0.0
            try:
                trim_end_val = float(self._trim_end.get())
                trim_dur = max(0.01, trim_end_val - trim_start)
            except ValueError:
                trim_dur = None

            if trim_start > 0:
                parts += ["-ss", "{:.3f}".format(trim_start)]

        parts += ["-i", src]

        if trim_en and trim_dur is not None:
            parts += ["-t", "{:.3f}".format(trim_dur)]

        # ── Scale ─────────────────────────────────────────────────────────
        if self._sec_scale.get():
            w   = self._scale_w.get() or "1920"
            h   = self._scale_h.get() or "1080"
            alg = _SCALE_ALGO.get(self._scale_algo.get(), "lanczos")
            if self._scale_pad.get():
                vf.append(
                    "scale={w}:{h}:force_original_aspect_ratio=decrease"
                    ":flags={a},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
                    ":color=black".format(w=w, h=h, a=alg))
            else:
                vf.append("scale={w}:{h}:flags={a}".format(w=w, h=h, a=alg))

        # ── FPS ───────────────────────────────────────────────────────────
        if self._sec_fps.get():
            fps = self._fps_val.get().strip() or "30"
            vf.append("fps={f}".format(f=fps))

        # ── Speed (video part) ────────────────────────────────────────────
        speed     = 1.0
        speed_en  = self._sec_speed.get()
        if speed_en:
            try:
                speed = float(self._speed_val.get())
            except ValueError:
                speed = 1.0
            speed = max(0.05, min(speed, 64.0))
            if abs(speed - 1.0) > 0.001:
                vf.append("setpts={:.4f}*PTS".format(1.0 / speed))

        # ── Rotate & Flip ─────────────────────────────────────────────────
        if self._sec_rotate.get():
            rot = self._rotate_val.get()
            if rot == "90":
                vf.append("transpose=1")
            elif rot == "180":
                vf.append("hflip")
                vf.append("vflip")
            elif rot == "270":
                vf.append("transpose=2")
            if self._flip_h.get():
                vf.append("hflip")
            if self._flip_v.get():
                vf.append("vflip")

        # ── Color & Image ─────────────────────────────────────────────────
        if self._sec_color.get():
            try:
                bri = float(self._bri.get())
                con = float(self._con.get())
                sat = float(self._sat.get())
                gam = float(self._gam.get())
                hue = float(self._hue.get())
            except ValueError:
                bri, con, sat, gam, hue = 0, 1, 1, 1, 0

            eq_parts = []
            if abs(bri)       > 0.001: eq_parts.append("brightness={:.3f}".format(bri))
            if abs(con - 1.0) > 0.001: eq_parts.append("contrast={:.3f}".format(con))
            if abs(sat - 1.0) > 0.001: eq_parts.append("saturation={:.3f}".format(sat))
            if abs(gam - 1.0) > 0.001: eq_parts.append("gamma={:.3f}".format(gam))
            if eq_parts:
                vf.append("eq=" + ":".join(eq_parts))
            if abs(hue) > 0.1:
                vf.append("hue=h={:.1f}".format(hue))

        # ── Denoise ───────────────────────────────────────────────────────
        if self._sec_denoise.get():
            algo = self._denoise_algo.get()
            str_map = {
                "Light":      (2,  2,  3,  3),
                "Medium":     (4,  4,  6,  6),
                "Strong":     (8,  8, 12, 12),
                "Aggressive": (14,14, 20, 20),
            }
            p = str_map.get(self._denoise_str.get(), (4, 4, 6, 6))
            if algo == "hqdn3d":
                vf.append("hqdn3d={}:{}:{}:{}".format(*p))
            else:
                vf.append("nlmeans={}".format(p[0]))

        # ── Sharpen ───────────────────────────────────────────────────────
        if self._sec_sharpen.get():
            try:
                lx = int(self._sharp_lx.get())
                la = float(self._sharp_la.get())
            except ValueError:
                lx, la = 5, 1.0
            vf.append("unsharp={lx}:{lx}:{la}:{lx}:{lx}:0".format(
                lx=lx, la=la))

        # ── Fade In / Out (video) ─────────────────────────────────────────
        if self._sec_fade.get():
            if self._fi_en.get():
                try:
                    fd = float(self._fi_dur.get())
                except ValueError:
                    fd = 1.5
                vf.append("fade=type=in:st=0:d={:.2f}".format(fd))

            if self._fo_en.get():
                try:
                    fd = float(self._fo_dur.get())
                except ValueError:
                    fd = 2.0
                # Calculate total duration for fade-out start
                total = self._duration
                if trim_en and trim_dur is not None:
                    total = trim_dur
                elif trim_en:
                    total = max(0, self._duration - trim_start)
                if total > 0:
                    st = max(0, total - fd)
                    vf.append("fade=type=out:st={:.2f}:d={:.2f}".format(st, fd))

        # ── Text Overlay ──────────────────────────────────────────────────
        if self._sec_text.get():
            txt   = (self._text_val.get()
                     .replace("'", r"\'")
                     .replace(":", r"\:"))
            sz    = self._text_size.get() or "42"
            col   = self._text_color.get() or "white"
            pos   = _TEXT_POSITIONS.get(
                self._text_pos.get(), _TEXT_POSITIONS["Bottom Right"])
            t_st  = self._text_start.get().strip() or "0"
            t_en  = self._text_end.get().strip()

            enable = ""
            try:
                st_f = float(t_st)
                if t_en:
                    en_f = float(t_en)
                    enable = ":enable='between(t,{st},{en})'".format(
                        st=st_f, en=en_f)
                elif st_f > 0:
                    enable = ":enable='gte(t,{st})'".format(st=st_f)
            except ValueError:
                pass

            vf.append(
                "drawtext=text='{txt}':fontsize={sz}:fontcolor={col}"
                ":bordercolor=black:borderw=3:{pos}{en}".format(
                    txt=txt, sz=sz, col=col, pos=pos, en=enable))

        # ── Audio filters ─────────────────────────────────────────────────

        # Speed (audio part - atempo chains for extreme values)
        if speed_en and abs(speed - 1.0) > 0.001:
            if self._speed_pitch.get():
                remaining = speed
                chain = []
                while remaining > 2.0:
                    chain.append("atempo=2.0")
                    remaining /= 2.0
                while remaining < 0.5:
                    chain.append("atempo=0.5")
                    remaining *= 2.0
                chain.append("atempo={:.4f}".format(remaining))
                af.extend(chain)

        # Volume
        if self._sec_audio.get():
            if self._vol_en.get():
                try:
                    vol = float(self._vol_val.get())
                    af.append("volume={:.2f}".format(vol))
                except ValueError:
                    pass
            if self._norm_en.get():
                lufs = self._norm_lufs.get() or "-23"
                af.append(
                    "loudnorm=I={l}:TP=-1:LRA=11".format(l=lufs))

        # Audio fade in/out
        if self._sec_fade.get() and self._fade_audio.get():
            if self._fi_en.get():
                try:
                    fd = float(self._fi_dur.get())
                    af.append("afade=type=in:st=0:d={:.2f}".format(fd))
                except ValueError:
                    pass
            if self._fo_en.get():
                try:
                    fd   = float(self._fo_dur.get())
                    total = self._duration
                    if trim_en and trim_dur is not None:
                        total = trim_dur
                    elif trim_en:
                        total = max(0, self._duration - trim_start)
                    if total > 0:
                        st = max(0, total - fd)
                        af.append("afade=type=out:st={:.2f}:d={:.2f}".format(
                            st, fd))
                except ValueError:
                    pass

        # ── Attach filters to command ──────────────────────────────────────
        if vf:
            parts += ["-vf", ",".join(vf)]
        if af:
            parts += ["-af", ",".join(af)]

        # ── Codec & output ────────────────────────────────────────────────
        if self._sec_encode.get():
            # Translate friendly UI name to real ffmpeg codec
            vcodec_friendly = self._vcodec.get()
            vcodec = _VCODECS.get(vcodec_friendly, "libx264")
            acodec = self._acodec.get()

            if vf or vcodec != "copy":
                parts += ["-c:v", vcodec]
                
                # Apply appropriate quality parameters depending on hardware/software
                if vcodec in ("libx264", "libx265"):
                    parts += ["-crf", self._crf.get(), "-preset", self._preset.get()]
                elif "nvenc" in vcodec:
                    parts += ["-preset", self._preset.get(), "-cq", self._crf.get()]
                elif "amf" in vcodec or "qsv" in vcodec:
                    parts += ["-preset", self._preset.get(), "-q:v", self._crf.get()]
                elif vcodec in ("libvpx-vp9", "libvpx"):
                    parts += ["-b:v", "0", "-crf", self._crf.get()]
            else:
                parts += ["-c:v", "copy"]

            if acodec == "none":
                parts += ["-an"]
            elif af or acodec != "copy":
                parts += ["-c:a", acodec]
                if acodec in ("aac", "libmp3lame", "libopus", "libvorbis"):
                    parts += ["-b:a", self._abitrate.get()]
            else:
                parts += ["-c:a", "copy"]
        else:
            # No encode section - sensible defaults
            if vf:
                parts += ["-c:v", "libx264", "-crf", "18",
                          "-preset", "fast"]
            else:
                parts += ["-c:v", "copy"]
            if af:
                parts += ["-c:a", "aac", "-b:a", "192k"]
            else:
                parts += ["-c:a", "copy"]

        parts += ["-movflags", "+faststart", out]

        self._last_cmd = parts
        self._set_cmd_text(self._format_cmd(parts))

    # ─────────────────────────────────────────────────────────────────────
    #  Command display helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_cmd(parts):
        """
        Format the command list as a readable multi-line string using
        backslash line continuations.  Groups args into logical pairs.
        """
        if not parts:
            return ""

        lines  = [shlex.quote(parts[0])]
        i      = 1
        # Flags that take a following value
        takes_val = {"-ss","-t","-to","-i","-vf","-af","-c:v","-c:a",
                     "-crf","-preset","-b:v","-b:a","-movflags",
                     "-r","-s","-map","-f"}

        while i < len(parts):
            p = parts[i]
            if p.startswith("-") and i + 1 < len(parts) and parts[i + 1] not in takes_val:
                # flag + value on same continuation line
                lines.append("  {} {}".format(
                    shlex.quote(p), shlex.quote(parts[i + 1])))
                i += 2
            else:
                lines.append("  {}".format(shlex.quote(p)))
                i += 1

        return " \\\n".join(lines)

    def _set_cmd_text(self, text):
        self._cmd_text.config(state="normal")
        self._cmd_text.delete("1.0", "end")
        self._cmd_text.insert("1.0", text)

    def _get_cmd_from_text(self):
        """Parse the (possibly user-edited) text widget back into a list."""
        raw = self._cmd_text.get("1.0", "end").strip()
        # Remove backslash line continuations
        raw = raw.replace("\\\n", " ").replace("\\n", " ")
        try:
            return shlex.split(raw)
        except ValueError as exc:
            messagebox.showerror(
                t("msg.command_parse_error_title"),
                t("msg.command_parse_error", cmd=str(exc)))
            return []

    # ─────────────────────────────────────────────────────────────────────
    #  Actions
    # ─────────────────────────────────────────────────────────────────────

    def _render(self):
        cmd = self._get_cmd_from_text()
        if not cmd:
            return

        # Basic sanity checks
        src = self._src_var.get().strip()
        out = self._out_var.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"),
                                   "Source file not found.")
            return
        if not out:
            messagebox.showwarning(t("common.warning"),
                                   "Set an output file path.")
            return

        self.log(self.console, t("log.all_in_one.running_pipeline"))
        self.log(self.console, "  " + " ".join(
            shlex.quote(c) for c in cmd[:6]) + " …")

        # Turn on the STOP button
        self._btn_stop.config(state="normal")
        
        # A little wrapper to re-disable the STOP button when FFmpeg finishes
        def _on_done_wrapper(rc):
            self._btn_stop.config(state="disabled")
            self.show_result(rc, out)

        self.run_ffmpeg(
            cmd,
            self.console,
            on_done=_on_done_wrapper,
            btn=self._btn_render,
            btn_label="▶  RENDER",
        )

    def _stop_render(self):
        """Safely stops the active FFmpeg thread running in the BaseTab worker."""
        # Attempt to kill process properly if base_tab bound it to typical identifiers
        proc = getattr(self, "proc", getattr(self, "_proc", getattr(self, "current_process", None)))
        
        if proc and hasattr(proc, "terminate"):
            try:
                proc.terminate()
            except Exception:
                pass
        else:
            # Absolute fallback if we can't find the thread: execute a system kill order
            if os.name == 'nt':
                os.system("taskkill /F /IM ffmpeg.exe /T >nul 2>&1")

        self.log(self.console, t("log.all_in_one.render_forcibly_stopped_by_user"))
        self._btn_stop.config(state="disabled")
        self._btn_render.config(state="normal", text="▶  RENDER")

    def _copy_cmd(self):
        raw = self._cmd_text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(raw)
        self.log(self.console, t("log.all_in_one.command_copied_to_clipboard"))

    def _save_bat(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".bat",
            filetypes=[("Batch file", "*.bat"), ("All", "*.*")])
        if not p:
            return
        raw = self._cmd_text.get("1.0", "end").strip()
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write("@echo off\n")
                f.write(raw.replace("\\\n", "^\n") + "\n")
                f.write("pause\n")
            self.log(self.console, "✅  Saved: {}".format(p))
        except OSError as exc:
            messagebox.showerror(t("common.error"), str(exc))

    def _save_sh(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".sh",
            filetypes=[("Shell script", "*.sh"), ("All", "*.*")])
        if not p:
            return
        raw = self._cmd_text.get("1.0", "end").strip()
        try:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write("#!/usr/bin/env bash\n")
                f.write(raw + "\n")
            self.log(self.console, "✅  Saved: {}".format(p))
        except OSError as exc:
            messagebox.showerror(t("common.error"), str(exc))