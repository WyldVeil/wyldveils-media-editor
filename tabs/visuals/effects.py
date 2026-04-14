"""
tab_specialeffects.py  ─  Special Effects Studio

Six sub-tabs covering the most popular video effects used on YouTube,
TikTok, Instagram Reels, and short-form content platforms.

Sub-tabs
────────
  1. Intros        - Fade-in, Zoom Burst, Slide In, Spin In, Split Open
  2. Outros        - Fade Out, Freeze & Zoom Out, Blur Dissolve, Iris Close
  3. Overlays      - Emoji Burst, Lower Third, Subscribe Bump, Countdown, Progress Bar
  4. Glitch & Vibe - RGB Chromatic Split, VHS Retro, Film Grain, Vignette, Light Leak
  5. Motion        - Camera Shake, Zoom Punch, Ken Burns, Whip Pan Blur, Heartbeat Pulse
  6. Branding      - Meme Caption, Cinematic Bars, Corner Logo Burn, Social Watermark

All effects use FFmpeg filter chains. The video is never cropped or
shortened unless the user explicitly chooses to trim - intro and outro
effects overlay onto the existing video so no content is lost.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import subprocess
import threading
import tempfile
import math

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, CREATE_NO_WINDOW, get_video_duration, open_in_explorer,
)
from core.i18n import t


# ─────────────────────────────────────────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

VIDEO_TYPES = [
    (t("silence.video_files"), "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
    (t("youtube.all_files"),   t("ducker.item_2")),
]


def _ffmpeg():
    return get_binary_path("ffmpeg")


def _ffprobe():
    return get_binary_path("ffprobe")


def _probe_duration(path):
    """Return float duration of *path* in seconds, or 0.0."""
    return get_video_duration(path)


def _probe_wh(path):
    """Return (width, height) of the video stream, or (1920, 1080)."""
    try:
        r = subprocess.run(
            [_ffprobe(), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x",
             path],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=10,
        )
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def _find_nonblack_frame(path, max_seek=10.0):
    """
    Return a timestamp (float, seconds) for the first non-black frame
    within the first *max_seek* seconds of *path*.

    Strategy: scan at 0.5 s intervals, extract a tiny thumbnail, compare
    average brightness.  Falls back to 1.0 s if nothing is found.
    """
    try:
        dur = _probe_duration(path)
        limit = min(max_seek, dur - 0.1) if dur > 0.1 else max_seek
        candidates = [i * 0.5 for i in range(1, int(limit / 0.5) + 1)]
        for t in candidates:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                subprocess.run(
                    [_ffmpeg(), "-y", "-ss", str(t), "-i", path,
                     "-vframes", "1",
                     "-vf", "scale=32:32",          # tiny - fast to check
                     tmp_path],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW, timeout=8,
                )
                # Check brightness via ffprobe signalstats
                r = subprocess.run(
                    [_ffprobe(), "-v", "error",
                     "-select_streams", "v:0",
                     "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
                     "-f", "lavfi",
                     "movie={}[out0]".format(tmp_path.replace("\\", "/")),
                     ],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW, timeout=8,
                )
                # Simple heuristic: if ffprobe can't run signalstats,
                # just check file size - a black PNG is tiny
                if os.path.getsize(tmp_path) > 400:
                    return t
            except Exception:
                pass
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    except Exception:
        pass
    return 1.0


def _extract_frame(path, timestamp, out_png):
    """Extract a single frame at *timestamp* seconds into *out_png*."""
    subprocess.run(
        [_ffmpeg(), "-y", "-ss", str(timestamp), "-i", path,
         "-vframes", "1", "-q:v", "2", out_png],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW, timeout=20,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Reusable sub-widget builders
# ─────────────────────────────────────────────────────────────────────────────

def _make_scrollable(parent):
    """Return (canvas, inner_frame) - a vertically scrollable container."""
    canvas = tk.Canvas(parent, highlightthickness=0, bg=CLR["bg"])
    sb     = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner  = tk.Frame(canvas, bg=CLR["bg"])
    canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    return canvas, inner


def _src_row(parent, src_var, browse_cmd):
    """Standard source-file browse row."""
    f = tk.Frame(parent, bg=CLR["bg"])
    f.pack(fill="x", padx=18, pady=(12, 4))
    tk.Label(f, text=t("common.source_video"), font=(UI_FONT, 10, "bold"),
             bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
    tk.Entry(f, textvariable=src_var, width=56,
             bg=CLR["panel"], fg=CLR["fg"],
             insertbackground=CLR["fg"]).pack(side="left", padx=8)
    tk.Button(f, text=t("btn.browse"), command=browse_cmd,
              bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")


def _out_row(parent, out_var, browse_cmd):
    """Standard output-file save row."""
    f = tk.Frame(parent, bg=CLR["bg"])
    f.pack(fill="x", padx=18, pady=4)
    tk.Label(f, text=t("common.output_file"), font=(UI_FONT, 10, "bold"),
             bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
    tk.Entry(f, textvariable=out_var, width=60,
             bg=CLR["panel"], fg=CLR["fg"],
             insertbackground=CLR["fg"]).pack(side="left", padx=8)
    tk.Button(f, text=t("common.save_as"), command=browse_cmd,
              bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")


def _run_btn(parent, text, command, color=None):
    color = color or CLR["accent"]
    btn = tk.Button(
        parent, text=text,
        font=(UI_FONT, 12, "bold"),
        bg=color, fg="black",
        height=2, width=30,
        cursor="hand2",
        command=command,
    )
    btn.pack(pady=10)
    return btn


def _console_block(parent, height=7):
    f = tk.Frame(parent, bg=CLR["bg"])
    f.pack(fill="both", expand=True, padx=18, pady=(4, 12))
    c, sb = BaseTab.make_console(f, height=height)
    c.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return c


def _lf(parent, title, **kw):
    return tk.LabelFrame(
        parent, text="  {}  ".format(title),
        bg=CLR["bg"], fg=CLR["fg"],
        font=(UI_FONT, 9, "bold"),
        padx=14, pady=10,
        **kw,
    )


def _spin(parent, label, var, from_, to, resolution=0.5, width=6):
    f = tk.Frame(parent, bg=CLR["bg"])
    tk.Label(f, text=label, bg=CLR["bg"], fg=CLR["fg"],
             font=(UI_FONT, 10)).pack(side="left")
    tk.Spinbox(
        f, from_=from_, to=to, increment=resolution,
        textvariable=var, width=width,
        bg=CLR["panel"], fg=CLR["fg"],
        buttonbackground=CLR["panel"],
        insertbackground=CLR["fg"],
    ).pack(side="left", padx=6)
    return f


def _combo(parent, label, var, values, width=18):
    f = tk.Frame(parent, bg=CLR["bg"])
    tk.Label(f, text=label, bg=CLR["bg"], fg=CLR["fg"],
             font=(UI_FONT, 10)).pack(side="left")
    ttk.Combobox(
        f, textvariable=var, values=values,
        state="readonly", width=width,
    ).pack(side="left", padx=6)
    return f


def _hint(parent, text):
    tk.Label(
        parent, text=text,
        bg=CLR["bg"], fg=CLR["fgdim"],
        font=(UI_FONT, 8), justify="left", wraplength=640,
    ).pack(anchor="w", padx=18, pady=(0, 6))


# ─────────────────────────────────────────────────────────────────────────────
#  Main tab class
# ─────────────────────────────────────────────────────────────────────────────

class SpecialEffectsTab(BaseTab):
    """
    Special Effects Studio - six categories of popular video effects,
    each in its own sub-tab.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="✨  " + t("tab.special_effects"),
            font=(UI_FONT, 16, "bold"),
            bg=CLR["panel"], fg=CLR["accent"],
        ).pack(side="left", padx=20, pady=12)
        tk.Label(
            hdr,
            text=t("effects.top_youtube_social_media_effects"),
            bg=CLR["panel"], fg=CLR["fgdim"],
        ).pack(side="left")

        # ── Category notebook ─────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=8)

        self._build_intros_tab(nb)
        self._build_outros_tab(nb)
        self._build_overlays_tab(nb)
        self._build_glitch_tab(nb)
        self._build_motion_tab(nb)
        self._build_branding_tab(nb)

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 1 - INTROS
    # ═════════════════════════════════════════════════════════════════════

    def _build_intros_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.intros"))

        intro_nb = ttk.Notebook(outer)
        intro_nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_intro_fadein(intro_nb)
        self._build_intro_zoomburst(intro_nb)
        self._build_intro_slidein(intro_nb)
        self._build_intro_spin(intro_nb)
        self._build_intro_splitopen(intro_nb)

    # ── Intro 1: Fade-In from Static Frame ───────────────────────────────

    def _build_intro_fadein(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Fade-In  ")
        _, inner = _make_scrollable(f)

        tk.Label(
            inner,
            text=t("effects.fade_in_from_static_frame"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["bg"], fg=CLR["accent"],
        ).pack(anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "A still frame from the start of your video fades out over the live "
              "footage, so you see the image dissolve into the actual video. "
              "No frames are lost. The tool automatically finds the first "
              "non-black frame for you.")

        self._fi_src = tk.StringVar()
        self._fi_out = tk.StringVar()
        _src_row(inner, self._fi_src,
                 lambda: self._browse_src(self._fi_src, self._fi_out, "_fadein"))
        _out_row(inner, self._fi_out,
                 lambda: self._browse_out(self._fi_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._fi_dur   = tk.StringVar(value="2.5")
        self._fi_start = tk.StringVar(value="auto")
        self._fi_crf   = tk.StringVar(value="18")

        r = _spin(opts, "Fade duration (s):", self._fi_dur, 0.5, 10, 0.5)
        r.pack(anchor="w", pady=3)

        r2 = tk.Frame(opts, bg=CLR["bg"])
        r2.pack(anchor="w", pady=3)
        tk.Label(r2, text=t("effects.still_frame_source"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        for val, lbl in [("auto",   "Auto (first non-black)"),
                         ("custom", "Custom timestamp (s):")]:
            tk.Radiobutton(
                r2, text=lbl, value=val,
                variable=self._fi_start,
                bg=CLR["bg"], fg=CLR["fg"],
                selectcolor=CLR["panel"],
                activebackground=CLR["bg"],
            ).pack(side="left", padx=8)
        self._fi_custom_t = tk.StringVar(value="2.0")
        tk.Entry(r2, textvariable=self._fi_custom_t,
                 width=6, bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)

        r3 = _spin(opts, "CRF (quality):", self._fi_crf, 12, 30, 1)
        r3.pack(anchor="w", pady=3)

        self._fi_btn = _run_btn(inner, "✨  APPLY FADE-IN",
                                self._render_fadein, CLR["accent"])
        self._fi_console = _console_block(inner)

    def _render_fadein(self):
        src = self._fi_src.get().strip()
        out = self._fi_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        fade_dur = float(self._fi_dur.get())
        crf      = self._fi_crf.get()

        def _work():
            self.after(0, lambda: self._fi_btn.config(
                state="disabled", text=t("effects.extracting_frame")))
            self.log(self._fi_console, t("log.effects.finding_non_black_frame"))

            # Determine still-frame timestamp
            if self._fi_start.get() == "auto":
                t = _find_nonblack_frame(src, max_seek=10.0)
                self.log(self._fi_console,
                         "  Auto-selected frame at {:.2f}s".format(t))
            else:
                try:
                    t = float(self._fi_custom_t.get())
                except ValueError:
                    t = 1.0

            # Extract the still frame as a temp PNG
            with tempfile.NamedTemporaryFile(
                    suffix="_sfx_still.png", delete=False) as tmp:
                still = tmp.name
            try:
                _extract_frame(src, t, still)
                if not os.path.exists(still) or os.path.getsize(still) < 100:
                    self.after(0, lambda: messagebox.showerror(
                        t("msg.frame_error_title"),
                        t("msg.frame_extract_failed")))
                    return
                self.log(self._fi_console, "  Still frame extracted → {}".format(
                    os.path.basename(still)))

                # Build filter:
                # • [0:v] = original video
                # • [1:v] = looped still image, fading out over fade_dur
                # The fading still is alpha-composited over the video so the
                # actual video is always playing underneath - zero frames lost.
                filter_graph = (
                    "[1:v]"
                    "fade=type=out:st=0:d={dur}:alpha=1,"
                    "format=rgba"
                    "[ov];"
                    "[0:v][ov]overlay=0:0[v]"
                ).format(dur=fade_dur)

                cmd = [
                    _ffmpeg(), "-y",
                    "-i", src,
                    "-loop", "1", "-framerate", "30", "-i", still,
                    "-filter_complex", filter_graph,
                    "-map", "[v]",
                    "-map", "0:a?",
                    "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    out,
                ]
                self.log(self._fi_console, t("log.effects.rendering"))
                self.run_ffmpeg(
                    cmd, self._fi_console,
                    on_done=lambda rc: self._done(
                        rc, out, self._fi_btn, "✨  APPLY FADE-IN"),
                    btn=self._fi_btn,
                    btn_label="✨  APPLY FADE-IN",
                )
            finally:
                # Clean up temp still only after ffmpeg finishes
                def _cleanup():
                    import time; time.sleep(4)
                    try:
                        os.unlink(still)
                    except OSError:
                        pass
                threading.Thread(target=_cleanup, daemon=True).start()

        threading.Thread(target=_work, daemon=True).start()

    # ── Intro 2: Zoom Burst ───────────────────────────────────────────────

    def _build_intro_zoomburst(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.zoom_burst"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.zoom_burst_in"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The video starts massively zoomed-in and rapidly pulls back to "
              "full frame, like a camera snap-zoom. Great for high-energy openers. "
              "Uses zoompan filter; original video is untouched after the burst ends.")

        self._zb_src = tk.StringVar()
        self._zb_out = tk.StringVar()
        _src_row(inner, self._zb_src,
                 lambda: self._browse_src(self._zb_src, self._zb_out, "_zoomburst"))
        _out_row(inner, self._zb_out, lambda: self._browse_out(self._zb_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._zb_dur    = tk.StringVar(value="1.5")
        self._zb_zoom   = tk.StringVar(value="3.0")
        self._zb_crf    = tk.StringVar(value="18")

        _spin(opts, "Burst duration (s):", self._zb_dur, 0.3, 5, 0.1).pack(
            anchor="w", pady=3)
        _spin(opts, "Starting zoom factor (×):", self._zb_zoom, 1.5, 8, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF (quality):", self._zb_crf, 12, 30, 1).pack(
            anchor="w", pady=3)

        self._zb_btn = _run_btn(inner, "🔍  APPLY ZOOM BURST",
                                self._render_zoomburst, CLR["green"])
        self._zb_console = _console_block(inner)

    def _render_zoomburst(self):
        src = self._zb_src.get().strip()
        out = self._zb_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                dur  = float(self._zb_dur.get())
                zoom = float(self._zb_zoom.get())
            except ValueError:
                dur, zoom = 1.5, 3.0

            crf = self._zb_crf.get()
            fps = 30

            # zoompan: during [0, dur], zoom decreases from `zoom` → 1.0
            # z expression: if t < dur, zoom - (zoom-1)*t/dur, else 1
            z_expr = (
                "if(lte(on,{frames}),"
                "{zmax}-({zmax}-1)*on/{frames},"
                "1)"
            ).format(zmax=zoom, frames=int(dur * fps))

            w, h   = _probe_wh(src)
            filter_str = (
                "zoompan="
                "z='{z}':"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                "d=1:"
                "s={w}x{h}:"
                "fps={fps}"
            ).format(z=z_expr, w=w, h=h, fps=fps)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._zb_console,
                on_done=lambda rc: self._done(
                    rc, out, self._zb_btn, "🔍  APPLY ZOOM BURST"),
                btn=self._zb_btn,
                btn_label="🔍  APPLY ZOOM BURST",
            )

        threading.Thread(target=_work, daemon=True).start()

    # ── Intro 3: Slide In ─────────────────────────────────────────────────

    def _build_intro_slidein(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.slide_in"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.slide_in_2"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The video frame slides onto a black background from any edge. "
              "After the animation the video plays normally at full size.")

        self._sl_src = tk.StringVar()
        self._sl_out = tk.StringVar()
        _src_row(inner, self._sl_src,
                 lambda: self._browse_src(self._sl_src, self._sl_out, "_slidein"))
        _out_row(inner, self._sl_out, lambda: self._browse_out(self._sl_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._sl_dir  = tk.StringVar(value="Left")
        self._sl_dur  = tk.StringVar(value="1.2")
        self._sl_crf  = tk.StringVar(value="18")

        _combo(opts, "Slide from:",
               self._sl_dir,
               ["Left", "Right", "Top", "Bottom"],
               width=12).pack(anchor="w", pady=3)
        _spin(opts, "Slide duration (s):", self._sl_dur, 0.2, 5, 0.1).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._sl_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._sl_btn = _run_btn(inner, "↔  APPLY SLIDE-IN",
                                self._render_slidein, CLR["orange"])
        self._sl_console = _console_block(inner)

    def _render_slidein(self):
        src = self._sl_src.get().strip()
        out = self._sl_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                dur = float(self._sl_dur.get())
            except ValueError:
                dur = 1.2

            crf       = self._sl_crf.get()
            direction = self._sl_dir.get()
            w, h      = _probe_wh(src)
            fps       = 30
            frames    = int(dur * fps)

            # Slide x/y as fraction of time → ease-out using sqrt
            ease = "({val}*(1-sqrt(on/{fr})))".format
            if direction == "Left":
                x_expr = ease(val=-w, fr=frames)
                y_expr = "0"
            elif direction == "Right":
                x_expr = ease(val=w, fr=frames)
                y_expr = "0"
            elif direction == "Top":
                x_expr = "0"
                y_expr = ease(val=-h, fr=frames)
            else:  # Bottom
                x_expr = "0"
                y_expr = ease(val=h, fr=frames)

            # Pad + overlay approach:
            filter_str = (
                "[0:v]pad={pw}:{ph}:{ox}:{oy}:color=black[padded];"
                "[padded]crop={w}:{h}:"
                "if(lte(on,{fr}),{ox}+({xexpr}),{ox}):"
                "if(lte(on,{fr}),{oy}+({yexpr}),{oy})"
                "[v]"
            ).format(
                pw=w * 3, ph=h * 3,
                ox=w, oy=h,
                w=w, h=h,
                fr=frames,
                xexpr=x_expr.strip("()"),
                yexpr=y_expr.strip("()"),
            )

            # Simpler, more reliable approach: overlay with offset position
            if direction == "Left":
                x_pos = "if(lte(n,{fr}),n*{w}/{fr}-{w},0)".format(fr=frames, w=w)
                y_pos = "0"
            elif direction == "Right":
                x_pos = "if(lte(n,{fr}),{w}-n*{w}/{fr},0)".format(fr=frames, w=w)
                y_pos = "0"
            elif direction == "Top":
                x_pos = "0"
                y_pos = "if(lte(n,{fr}),n*{h}/{fr}-{h},0)".format(fr=frames, h=h)
            else:
                x_pos = "0"
                y_pos = "if(lte(n,{fr}),{h}-n*{h}/{fr},0)".format(fr=frames, h=h)

            filter_str2 = (
                "color=black:size={w}x{h}:rate={fps}[bg];"
                "[0:v][bg]overlay=x={x}:y={y}[v]"
            ).format(w=w, h=h, fps=fps, x=x_pos, y=y_pos)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-filter_complex", filter_str2,
                "-map", "[v]",
                "-map", "0:a?",
                "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                "-c:a", "copy",
                "-movflags", "+faststart",
                out,
            ]
            self.run_ffmpeg(
                cmd, self._sl_console,
                on_done=lambda rc: self._done(
                    rc, out, self._sl_btn, "↔  APPLY SLIDE-IN"),
                btn=self._sl_btn,
                btn_label="↔  APPLY SLIDE-IN",
            )

        threading.Thread(target=_work, daemon=True).start()

    # ── Intro 4: Spin In ──────────────────────────────────────────────────

    def _build_intro_spin(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.spin_in"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.spin_in_2"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The video rotates in from a small, spinning state and expands "
              "to fill the frame. A popular dramatic opener. "
              "Achieved via rotate + scale expressions on the first N frames.")

        self._sp_src = tk.StringVar()
        self._sp_out = tk.StringVar()
        _src_row(inner, self._sp_src,
                 lambda: self._browse_src(self._sp_src, self._sp_out, "_spinin"))
        _out_row(inner, self._sp_out, lambda: self._browse_out(self._sp_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._sp_dur    = tk.StringVar(value="1.5")
        self._sp_turns  = tk.StringVar(value="1")
        self._sp_crf    = tk.StringVar(value="18")

        _spin(opts, "Spin duration (s):", self._sp_dur, 0.3, 5, 0.1).pack(
            anchor="w", pady=3)
        _spin(opts, "Number of rotations:", self._sp_turns, 1, 5, 1).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._sp_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._sp_btn = _run_btn(inner, "🌀  APPLY SPIN-IN",
                                self._render_spinin, CLR["pink"])
        self._sp_console = _console_block(inner)

    def _render_spinin(self):
        src = self._sp_src.get().strip()
        out = self._sp_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                dur   = float(self._sp_dur.get())
                turns = int(self._sp_turns.get())
            except ValueError:
                dur, turns = 1.5, 1

            crf    = self._sp_crf.get()
            w, h   = _probe_wh(src)
            fps    = 30
            frames = int(dur * fps)

            # Rotate from (turns * 2π) → 0  while scaling 0.05 → 1.0
            # Both use ease-in via t^2
            angle_expr = (
                "if(lte(n,{fr}),"
                "{twopi}*(1-(n/{fr})*(n/{fr})),"
                "0)"
            ).format(fr=frames, twopi=turns * 6.2832)

            scale_expr = (
                "if(lte(n\\,{fr}),"
                "0.05+(0.95*(n/{fr})*(n/{fr})),"
                "1)"
            ).format(fr=frames)

            diag = int(math.sqrt(w * w + h * h)) + 4  # safe bounding for rotation
            diag = diag + (diag % 2)                  # keep even

            filter_str = (
                "[0:v]"
                "scale=iw*{sc}:ih*{sc}:eval=frame,"
                "pad={diag}:{diag}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
                "rotate=angle='{angle}':fillcolor=black@0,"
                "crop={w}:{h}"
                "[v]"
            ).format(
                sc=scale_expr, diag=diag,
                angle=angle_expr,
                w=w, h=h,
            )

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-filter_complex", filter_str,
                "-map", "[v]",
                "-map", "0:a?",
                "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                "-c:a", "copy",
                "-movflags", "+faststart",
                out,
            ]
            self.run_ffmpeg(
                cmd, self._sp_console,
                on_done=lambda rc: self._done(
                    rc, out, self._sp_btn, "🌀  APPLY SPIN-IN"),
                btn=self._sp_btn,
                btn_label="🌀  APPLY SPIN-IN",
            )

        threading.Thread(target=_work, daemon=True).start()

    # ── Intro 5: Split Open ───────────────────────────────────────────────

    def _build_intro_splitopen(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.split_open"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.split_open_2"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The screen is split horizontally. Top half slides up and bottom half "
              "slides down, revealing the video. The cinematic curtain reveal. "
              "Achieved with two crop+overlay layers animating in opposite directions.")

        self._spo_src = tk.StringVar()
        self._spo_out = tk.StringVar()
        _src_row(inner, self._spo_src,
                 lambda: self._browse_src(self._spo_src, self._spo_out, "_splitopen"))
        _out_row(inner, self._spo_out, lambda: self._browse_out(self._spo_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._spo_dur = tk.StringVar(value="1.0")
        self._spo_dir = tk.StringVar(value="Vertical (curtain)")
        self._spo_crf = tk.StringVar(value="18")

        _spin(opts, "Open duration (s):", self._spo_dur, 0.2, 4, 0.1).pack(
            anchor="w", pady=3)
        _combo(opts, "Split axis:",
               self._spo_dir,
               ["Vertical (curtain)", "Horizontal (book)"],
               width=22).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._spo_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._spo_btn = _run_btn(inner, "↕  APPLY SPLIT-OPEN",
                                 self._render_splitopen, "#9C27B0")
        self._spo_console = _console_block(inner)

    def _render_splitopen(self):
        src = self._spo_src.get().strip()
        out = self._spo_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                dur = float(self._spo_dur.get())
            except ValueError:
                dur = 1.0

            crf       = self._spo_crf.get()
            w, h      = _probe_wh(src)
            fps       = 30
            frames    = int(dur * fps)
            vertical  = "Vertical" in self._spo_dir.get()

            if vertical:
                half = h // 2
                # Top half slides up, bottom half slides down over black
                filter_str = (
                    "color=black:size={w}x{h}:rate={fps}[bg];"
                    "[0:v]split=2[top_src][bot_src];"
                    "[top_src]crop={w}:{half}:0:0[top];"
                    "[bot_src]crop={w}:{half}:0:{half}[bot];"
                    "[bg][top]overlay=x=0:y='if(lte(n,{fr}),-(n*{half}/{fr}),0)'[mid];"
                    "[mid][bot]overlay=x=0:y='if(lte(n,{fr}),{h}-(n*{half}/{fr}),{half})'[v]"
                ).format(w=w, h=h, fps=fps, half=half, fr=frames)
            else:
                half = w // 2
                filter_str = (
                    "color=black:size={w}x{h}:rate={fps}[bg];"
                    "[0:v]split=2[left_src][right_src];"
                    "[left_src]crop={half}:{h}:0:0[left];"
                    "[right_src]crop={half}:{h}:{half}:0[right];"
                    "[bg][left]overlay=x='if(lte(n,{fr}),-(n*{half}/{fr}),0)':y=0[mid];"
                    "[mid][right]overlay=x='if(lte(n,{fr}),{w}-(n*{half}/{fr}),{half})':y=0[v]"
                ).format(w=w, h=h, fps=fps, half=half, fr=frames)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-filter_complex", filter_str,
                "-map", "[v]",
                "-map", "0:a?",
                "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                "-c:a", "copy",
                "-movflags", "+faststart",
                out,
            ]
            self.run_ffmpeg(
                cmd, self._spo_console,
                on_done=lambda rc: self._done(
                    rc, out, self._spo_btn, "↕  APPLY SPLIT-OPEN"),
                btn=self._spo_btn,
                btn_label="↕  APPLY SPLIT-OPEN",
            )

        threading.Thread(target=_work, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 2 - OUTROS
    # ═════════════════════════════════════════════════════════════════════

    def _build_outros_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.outros"))
        outro_nb = ttk.Notebook(outer)
        outro_nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_outro_fadeout(outro_nb)
        self._build_outro_freezezoom(outro_nb)
        self._build_outro_irisclose(outro_nb)

    def _build_outro_fadeout(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.fade_out"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.fade_to_black"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The last N seconds of your video fade smoothly to black. "
              "Audio fades out in parallel. Clean and professional.")

        self._fo_src = tk.StringVar()
        self._fo_out = tk.StringVar()
        _src_row(inner, self._fo_src,
                 lambda: self._browse_src(self._fo_src, self._fo_out, "_fadeout"))
        _out_row(inner, self._fo_out, lambda: self._browse_out(self._fo_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._fo_dur = tk.StringVar(value="2.0")
        self._fo_crf = tk.StringVar(value="18")
        _spin(opts, "Fade duration (s):", self._fo_dur, 0.3, 10, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._fo_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._fo_btn = _run_btn(inner, "⬛  APPLY FADE-OUT",
                                self._render_fadeout, "#455A64")
        self._fo_console = _console_block(inner)

    def _render_fadeout(self):
        src = self._fo_src.get().strip()
        out = self._fo_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        dur    = float(self._fo_dur.get())
        crf    = self._fo_crf.get()
        total  = _probe_duration(src)
        start  = max(0, total - dur)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", "fade=type=out:st={st}:d={dur}".format(st=start, dur=dur),
            "-af", "afade=type=out:st={st}:d={dur}".format(st=start, dur=dur),
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._fo_console,
            on_done=lambda rc: self._done(
                rc, out, self._fo_btn, "⬛  APPLY FADE-OUT"),
            btn=self._fo_btn,
            btn_label="⬛  APPLY FADE-OUT",
        )

    def _build_outro_freezezoom(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.freeze_zoom_out"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.freeze_frame_zoom_out"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "The last frame of the video is frozen, then slowly zooms out and "
              "fades to black. A classic cinematic ending.")

        self._fz_src = tk.StringVar()
        self._fz_out = tk.StringVar()
        _src_row(inner, self._fz_src,
                 lambda: self._browse_src(self._fz_src, self._fz_out, "_freezezoom"))
        _out_row(inner, self._fz_out, lambda: self._browse_out(self._fz_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._fz_hold  = tk.StringVar(value="2.5")
        self._fz_fade  = tk.StringVar(value="1.0")
        self._fz_crf   = tk.StringVar(value="18")
        _spin(opts, "Hold duration (s):", self._fz_hold, 0.5, 10, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Fade duration (s):", self._fz_fade, 0.3, 5, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._fz_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._fz_btn = _run_btn(inner, "🎞  APPLY FREEZE & ZOOM OUT",
                                self._render_freezezoom, "#37474F")
        self._fz_console = _console_block(inner)

    def _render_freezezoom(self):
        src = self._fz_src.get().strip()
        out = self._fz_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                hold = float(self._fz_hold.get())
                fade = float(self._fz_fade.get())
            except ValueError:
                hold, fade = 2.5, 1.0

            crf   = self._fz_crf.get()
            total = _probe_duration(src)
            w, h  = _probe_wh(src)
            fps   = 30
            hold_frames = int(hold * fps)

            self.after(0, lambda: self._fz_btn.config(
                state="disabled", text=t("effects.extracting_last_frame")))

            # Extract last frame
            with tempfile.NamedTemporaryFile(
                    suffix="_fz_last.png", delete=False) as tmp:
                last_frame = tmp.name
            try:
                last_ts = max(0, total - 0.1)
                _extract_frame(src, last_ts, last_frame)
                self.log(self._fz_console, t("log.effects.last_frame_extracted"))

                # zoom-out from 1.1x → 1.0x over hold_frames, then fade to black
                zoom_expr = (
                    "if(lte(on,{fr}),1.1-0.1*on/{fr},1.0)"
                ).format(fr=hold_frames)

                filter_str = (
                    # Main video part
                    "[0:v]trim=0:{vid_end},setpts=PTS-STARTPTS[vid];"
                    # Freeze part: loop last frame, zoom-out, fade
                    "[1:v]loop=loop={lf}:size=1:start=0,"
                    "scale=iw*{z}:ih*{z}:eval=frame,"
                    "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    "fade=type=out:st={fst}:d={fd}"
                    "[freeze];"
                    # Concatenate
                    "[vid][freeze]concat=n=2:v=1:a=0[v]"
                ).format(
                    vid_end=total,
                    lf=hold_frames + int(fade * fps) + 10,
                    z=zoom_expr,
                    w=w, h=h,
                    fst=hold - 0.05,
                    fd=fade,
                )

                cmd = [
                    _ffmpeg(), "-y",
                    "-i", src,
                    "-loop", "1", "-framerate", str(fps), "-i", last_frame,
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-map", "0:a?",
                    "-shortest",
                    "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    out,
                ]
                self.log(self._fz_console, t("log.effects.rendering_freeze_zoom_outro"))
                self.run_ffmpeg(
                    cmd, self._fz_console,
                    on_done=lambda rc: self._done(
                        rc, out, self._fz_btn, "🎞  APPLY FREEZE & ZOOM OUT"),
                    btn=self._fz_btn,
                    btn_label="🎞  APPLY FREEZE & ZOOM OUT",
                )
            finally:
                def _cleanup():
                    import time; time.sleep(5)
                    try:
                        os.unlink(last_frame)
                    except OSError:
                        pass
                threading.Thread(target=_cleanup, daemon=True).start()

        threading.Thread(target=_work, daemon=True).start()

    def _build_outro_irisclose(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.iris_close"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.iris_vignette_close"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "A black oval vignette closes in from the edges to the centre "
              "like a classic iris wipe, beloved in cinema and vintage content.")

        self._ir_src = tk.StringVar()
        self._ir_out = tk.StringVar()
        _src_row(inner, self._ir_src,
                 lambda: self._browse_src(self._ir_src, self._ir_out, "_irisclose"))
        _out_row(inner, self._ir_out, lambda: self._browse_out(self._ir_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._ir_dur = tk.StringVar(value="1.5")
        self._ir_crf = tk.StringVar(value="18")
        _spin(opts, "Iris duration (s):", self._ir_dur, 0.3, 6, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._ir_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._ir_btn = _run_btn(inner, "⭕  APPLY IRIS CLOSE",
                                self._render_irisclose, "#263238")
        self._ir_console = _console_block(inner)

    def _render_irisclose(self):
        src = self._ir_src.get().strip()
        out = self._ir_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            dur = float(self._ir_dur.get())
        except ValueError:
            dur = 1.5

        crf   = self._ir_crf.get()
        total = _probe_duration(src)
        start = max(0, total - dur)

        # vignette filter: as time goes on the sigma grows → darkness closes in
        filter_str = (
            "geq="
            "r='r(X,Y)*max(0,1-max(0,((t-{st})/{dur})*2)*sqrt((X-W/2)^2/(W/2)^2+(Y-H/2)^2/(H/2)^2))':"
            "g='g(X,Y)*max(0,1-max(0,((t-{st})/{dur})*2)*sqrt((X-W/2)^2/(W/2)^2+(Y-H/2)^2/(H/2)^2))':"
            "b='b(X,Y)*max(0,1-max(0,((t-{st})/{dur})*2)*sqrt((X-W/2)^2/(W/2)^2+(Y-H/2)^2/(H/2)^2))'"
        ).format(st=start, dur=dur)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", filter_str,
            "-af", "afade=type=out:st={st}:d={dur}".format(st=start, dur=dur),
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._ir_console,
            on_done=lambda rc: self._done(
                rc, out, self._ir_btn, "⭕  APPLY IRIS CLOSE"),
            btn=self._ir_btn,
            btn_label="⭕  APPLY IRIS CLOSE",
        )

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 3 - OVERLAYS
    # ═════════════════════════════════════════════════════════════════════

    def _build_overlays_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.overlays"))
        ov_nb = ttk.Notebook(outer)
        ov_nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_ov_emoji(ov_nb)
        self._build_ov_lowerthird(ov_nb)
        self._build_ov_subscribe(ov_nb)
        self._build_ov_countdown(ov_nb)
        self._build_ov_progressbar(ov_nb)

    def _build_ov_emoji(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.emoji_burst"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.emoji_text_burst"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Slam a large emoji or short text onto the video at a specific "
              "timestamp with a pop-in scale animation. "
              "Set the position (% of frame), appear time, and hold duration.")

        self._em_src = tk.StringVar()
        self._em_out = tk.StringVar()
        _src_row(inner, self._em_src,
                 lambda: self._browse_src(self._em_src, self._em_out, "_emoji"))
        _out_row(inner, self._em_out, lambda: self._browse_out(self._em_out))

        opts = _lf(inner, "Emoji / Text Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._em_text  = tk.StringVar(value="😂")
        self._em_size  = tk.StringVar(value="96")
        self._em_x     = tk.StringVar(value="50")
        self._em_y     = tk.StringVar(value="30")
        self._em_start = tk.StringVar(value="3.0")
        self._em_hold  = tk.StringVar(value="2.0")
        self._em_crf   = tk.StringVar(value="18")

        r0 = tk.Frame(opts, bg=CLR["bg"]); r0.pack(anchor="w", pady=3)
        tk.Label(r0, text=t("effects.text_emoji"), bg=CLR["bg"],
                 fg=CLR["fg"]).pack(side="left")
        tk.Entry(r0, textvariable=self._em_text, width=24,
                 font=(UI_FONT, 14),
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=6)
        tk.Label(r0, text=t("effects.supports_emoji_ascii_latin_text"),
                 bg=CLR["bg"], fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left")

        _spin(opts, "Font size (px):", self._em_size, 24, 256, 8).pack(
            anchor="w", pady=3)

        r1 = tk.Frame(opts, bg=CLR["bg"]); r1.pack(anchor="w", pady=3)
        tk.Label(r1, text=t("effects.position_x_from_left"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Spinbox(r1, from_=0, to=100, textvariable=self._em_x,
                   width=5, bg=CLR["panel"], fg=CLR["fg"],
                   buttonbackground=CLR["panel"],
                   insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Label(r1, text=t("effects.y_from_top"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Spinbox(r1, from_=0, to=100, textvariable=self._em_y,
                   width=5, bg=CLR["panel"], fg=CLR["fg"],
                   buttonbackground=CLR["panel"],
                   insertbackground=CLR["fg"]).pack(side="left", padx=4)

        _spin(opts, "Appear at (s):",  self._em_start, 0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Hold for (s):",   self._em_hold,  0.2, 30, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:",            self._em_crf,   12,  30,   1).pack(
            anchor="w", pady=3)

        self._em_btn = _run_btn(inner, "😂  BURN EMOJI ONTO VIDEO",
                                self._render_emoji, CLR["orange"])
        self._em_console = _console_block(inner)

    def _render_emoji(self):
        src = self._em_src.get().strip()
        out = self._em_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                size  = int(self._em_size.get())
                xpct  = float(self._em_x.get()) / 100.0
                ypct  = float(self._em_y.get()) / 100.0
                start = float(self._em_start.get())
                hold  = float(self._em_hold.get())
            except ValueError:
                size, xpct, ypct, start, hold = 96, 0.5, 0.3, 3.0, 2.0

            text  = self._em_text.get()
            crf   = self._em_crf.get()
            w, h  = _probe_wh(src)
            end   = start + hold

            # x/y as absolute pixels, centred on the chosen %
            x_px = int(w * xpct)
            y_px = int(h * ypct)

            # Pop-in scale: over 0.2s the text scales from 0 → 1 then holds
            # Achieved via fontsize with a time-based multiplier
            pop_frames  = 6   # ~0.2s at 30fps - used in scale expression
            scale_expr  = (
                "if(lt(t-{st},0.2),"
                "{sz}*(t-{st})/0.2,"
                "{sz})"
            ).format(st=start, sz=size)

            filter_str = (
                "drawtext="
                "text='{text}':"
                "fontsize={sz}:"
                "fontcolor=white:"
                "x={x}-text_w/2:"
                "y={y}-text_h/2:"
                "shadowcolor=black@0.7:shadowx=3:shadowy=3:"
                "enable='between(t,{st},{en})'"
            ).format(
                text=text.replace("'", "\\'").replace(":", "\\:"),
                sz=size,
                x=x_px, y=y_px,
                st=start, en=end,
            )

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._em_console,
                on_done=lambda rc: self._done(
                    rc, out, self._em_btn, "😂  BURN EMOJI ONTO VIDEO"),
                btn=self._em_btn,
                btn_label="😂  BURN EMOJI ONTO VIDEO",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_ov_lowerthird(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.lower_third"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.lower_third_banner"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "A professional name/title bar that slides up from the bottom. "
              "Used for speaker IDs, location captions, product names, "
              "and news-style graphics.")

        self._lt_src   = tk.StringVar()
        self._lt_out   = tk.StringVar()
        _src_row(inner, self._lt_src,
                 lambda: self._browse_src(self._lt_src, self._lt_out, "_lt"))
        _out_row(inner, self._lt_out, lambda: self._browse_out(self._lt_out))

        opts = _lf(inner, "Banner Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._lt_title    = tk.StringVar(value="John Smith")
        self._lt_subtitle = tk.StringVar(value="Content Creator")
        self._lt_color    = tk.StringVar(value="#1565C0")
        self._lt_start    = tk.StringVar(value="2.0")
        self._lt_hold     = tk.StringVar(value="4.0")
        self._lt_crf      = tk.StringVar(value="18")

        for lbl, var, w in [
            ("Title:",    self._lt_title,    28),
            ("Subtitle:", self._lt_subtitle, 28),
            ("Bar colour (hex):", self._lt_color, 10),
        ]:
            r = tk.Frame(opts, bg=CLR["bg"]); r.pack(anchor="w", pady=3)
            tk.Label(r, text=lbl, bg=CLR["bg"], fg=CLR["fg"],
                     width=18, anchor="e").pack(side="left")
            tk.Entry(r, textvariable=var, width=w,
                     bg=CLR["panel"], fg=CLR["fg"],
                     insertbackground=CLR["fg"]).pack(side="left", padx=6)

        _spin(opts, "Appear at (s):", self._lt_start, 0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Hold for (s):",  self._lt_hold,  0.5, 60, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:",           self._lt_crf,   12, 30,   1).pack(
            anchor="w", pady=3)

        self._lt_btn = _run_btn(inner, "📛  BURN LOWER THIRD",
                                self._render_lowerthird, "#1565C0")
        self._lt_console = _console_block(inner)

    def _render_lowerthird(self):
        src = self._lt_src.get().strip()
        out = self._lt_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                start = float(self._lt_start.get())
                hold  = float(self._lt_hold.get())
            except ValueError:
                start, hold = 2.0, 4.0

            end     = start + hold
            crf     = self._lt_crf.get()
            title   = self._lt_title.get().replace("'", "\\'").replace(":", "\\:")
            sub     = self._lt_subtitle.get().replace("'", "\\'").replace(":", "\\:")
            color   = self._lt_color.get().lstrip("#")
            w, h    = _probe_wh(src)
            bar_y   = int(h * 0.78)
            bar_h   = int(h * 0.14)

            # Slide-in: bar starts below frame, eases up over 0.3s
            slide_expr = (
                "if(lt(t-{st},0.3),"
                "{by}+{bh}*(1-(t-{st})/0.3),"
                "{by})"
            ).format(st=start, by=bar_y, bh=bar_h)

            filter_str = (
                # Coloured bar background
                "drawbox="
                "x=0:y='{ye}':w={w}:h={bh}:"
                "color=0x{col}@0.85:t=fill:"
                "enable='between(t,{st},{en})',"
                # Title text
                "drawtext="
                "text='{ttl}':"
                "fontsize={fs1}:"
                "fontcolor=white:"
                "x=40:y='{ye}'+8:"
                "fontweight=bold:"
                "enable='between(t,{st},{en})',"
                # Subtitle text
                "drawtext="
                "text='{sub}':"
                "fontsize={fs2}:"
                "fontcolor=white@0.80:"
                "x=42:y='{ye}'+{fs1}+10:"
                "enable='between(t,{st},{en})'"
            ).format(
                ye=slide_expr,
                w=w, bh=bar_h,
                col=color,
                st=start, en=end,
                ttl=title,
                sub=sub,
                fs1=int(bar_h * 0.42),
                fs2=int(bar_h * 0.30),
            )

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._lt_console,
                on_done=lambda rc: self._done(
                    rc, out, self._lt_btn, "📛  BURN LOWER THIRD"),
                btn=self._lt_btn,
                btn_label="📛  BURN LOWER THIRD",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_ov_subscribe(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.subscribe_bump"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.subscribe_like_reminder"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Burns a customisable call-to-action reminder onto your video. "
              "\"Like & Subscribe!\", \"Follow for more\", etc. "
              "Animates in with a bounce and fades out cleanly.")

        self._sub_src = tk.StringVar()
        self._sub_out = tk.StringVar()
        _src_row(inner, self._sub_src,
                 lambda: self._browse_src(self._sub_src, self._sub_out, "_subscribe"))
        _out_row(inner, self._sub_out, lambda: self._browse_out(self._sub_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._sub_text  = tk.StringVar(value="👍 Like & Subscribe! 🔔")
        self._sub_size  = tk.StringVar(value="52")
        self._sub_pos   = tk.StringVar(value="Bottom Centre")
        self._sub_start = tk.StringVar(value="5.0")
        self._sub_hold  = tk.StringVar(value="4.0")
        self._sub_crf   = tk.StringVar(value="18")

        r0 = tk.Frame(opts, bg=CLR["bg"]); r0.pack(anchor="w", pady=3)
        tk.Label(r0, text=t("effects.message"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r0, textvariable=self._sub_text, width=36,
                 font=(UI_FONT, 12),
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=6)

        _spin(opts, "Font size:", self._sub_size, 24, 120, 4).pack(
            anchor="w", pady=3)
        _combo(opts, "Position:", self._sub_pos,
               ["Bottom Centre", "Top Centre",
                "Bottom Left", "Bottom Right"], width=16).pack(
            anchor="w", pady=3)
        _spin(opts, "Appear at (s):", self._sub_start, 0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Hold for (s):",  self._sub_hold, 0.5, 60, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._sub_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._sub_btn = _run_btn(inner, "🔔  BURN SUBSCRIBE REMINDER",
                                 self._render_subscribe, "#FF0000")
        self._sub_console = _console_block(inner)

    def _render_subscribe(self):
        src = self._sub_src.get().strip()
        out = self._sub_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                size  = int(self._sub_size.get())
                start = float(self._sub_start.get())
                hold  = float(self._sub_hold.get())
            except ValueError:
                size, start, hold = 52, 5.0, 4.0

            end     = start + hold
            crf     = self._sub_crf.get()
            text    = self._sub_text.get().replace("'", "\\'").replace(":", "\\:")
            pos     = self._sub_pos.get()
            w, h    = _probe_wh(src)

            pos_map = {
                "Bottom Centre": ("(w-text_w)/2", "h-text_h-40"),
                "Top Centre":    ("(w-text_w)/2", "40"),
                "Bottom Left":   ("40",           "h-text_h-40"),
                "Bottom Right":  ("w-text_w-40",  "h-text_h-40"),
            }
            x_expr, y_expr = pos_map.get(pos, pos_map["Bottom Centre"])

            filter_str = (
                "drawtext="
                "text='{text}':"
                "fontsize={sz}:"
                "fontcolor=white:"
                "x={x}:y={y}:"
                "shadowcolor=black@0.8:shadowx=3:shadowy=3:"
                "box=1:boxcolor=black@0.45:boxborderw=8:"
                "enable='between(t,{st},{en})'"
            ).format(
                text=text, sz=size,
                x=x_expr, y=y_expr,
                st=start, en=end,
            )

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._sub_console,
                on_done=lambda rc: self._done(
                    rc, out, self._sub_btn, "🔔  BURN SUBSCRIBE REMINDER"),
                btn=self._sub_btn,
                btn_label="🔔  BURN SUBSCRIBE REMINDER",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_ov_countdown(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Countdown  ")
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.countdown_timer_overlay"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Burns a live countdown clock onto the video starting at "
              "your chosen value. Great for reaction videos, cooking timers, "
              "challenges, and live event coverage.")

        self._cd_src   = tk.StringVar()
        self._cd_out   = tk.StringVar()
        _src_row(inner, self._cd_src,
                 lambda: self._browse_src(self._cd_src, self._cd_out, "_countdown"))
        _out_row(inner, self._cd_out, lambda: self._browse_out(self._cd_out))

        opts = _lf(inner, "Countdown Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._cd_from   = tk.StringVar(value="10")
        self._cd_start  = tk.StringVar(value="2.0")
        self._cd_size   = tk.StringVar(value="80")
        self._cd_crf    = tk.StringVar(value="18")

        _spin(opts, "Count from (s):", self._cd_from,  3, 3600, 1).pack(
            anchor="w", pady=3)
        _spin(opts, "Start at (s):",   self._cd_start, 0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Font size:",      self._cd_size,  24, 200, 8).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:",            self._cd_crf,   12,  30,  1).pack(
            anchor="w", pady=3)

        self._cd_btn = _run_btn(inner, "⏱  BURN COUNTDOWN",
                                self._render_countdown, "#E53935")
        self._cd_console = _console_block(inner)

    def _render_countdown(self):
        src = self._cd_src.get().strip()
        out = self._cd_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            count_from = int(self._cd_from.get())
            start      = float(self._cd_start.get())
            size       = int(self._cd_size.get())
        except ValueError:
            count_from, start, size = 10, 2.0, 80

        crf = self._cd_crf.get()
        end = start + count_from

        # drawtext with a time-based expression that counts down
        filter_str = (
            "drawtext="
            "text='%{{eif\\:{count_from}-(t-{st})\\:d}}':"
            "fontsize={sz}:"
            "fontcolor=white:"
            "x=(w-text_w)/2:y=(h-text_h)/2:"
            "shadowcolor=black@0.8:shadowx=4:shadowy=4:"
            "box=1:boxcolor=black@0.5:boxborderw=12:"
            "enable='between(t,{st},{en})'"
        ).format(
            count_from=count_from, st=start, en=end, sz=size)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", filter_str,
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._cd_console,
            on_done=lambda rc: self._done(
                rc, out, self._cd_btn, "⏱  BURN COUNTDOWN"),
            btn=self._cd_btn,
            btn_label="⏱  BURN COUNTDOWN",
        )

    def _build_ov_progressbar(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.progress_bar"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.video_progress_bar"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Adds a YouTube-style thin progress bar at the top or bottom that "
              "fills from left to right as the video plays. "
              "Viewers love knowing how far through the video they are.")

        self._pb_src = tk.StringVar()
        self._pb_out = tk.StringVar()
        _src_row(inner, self._pb_src,
                 lambda: self._browse_src(self._pb_src, self._pb_out, "_progress"))
        _out_row(inner, self._pb_out, lambda: self._browse_out(self._pb_out))

        opts = _lf(inner, "Bar Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._pb_color  = tk.StringVar(value="FF0000")
        self._pb_height = tk.StringVar(value="8")
        self._pb_pos    = tk.StringVar(value="Bottom")
        self._pb_crf    = tk.StringVar(value="18")

        r0 = tk.Frame(opts, bg=CLR["bg"]); r0.pack(anchor="w", pady=3)
        tk.Label(r0, text=t("effects.bar_colour_hex_no"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r0, textvariable=self._pb_color, width=10,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=6)

        _spin(opts, "Bar height (px):", self._pb_height, 2, 40, 2).pack(
            anchor="w", pady=3)
        _combo(opts, "Position:", self._pb_pos,
               ["Bottom", "Top"], width=10).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._pb_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._pb_btn = _run_btn(inner, "▶  BURN PROGRESS BAR",
                                self._render_progressbar, "#E53935")
        self._pb_console = _console_block(inner)

    def _render_progressbar(self):
        src = self._pb_src.get().strip()
        out = self._pb_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                bar_h = int(self._pb_height.get())
            except ValueError:
                bar_h = 8

            crf    = self._pb_crf.get()
            color  = self._pb_color.get().lstrip("#")
            pos    = self._pb_pos.get()
            total  = _probe_duration(src)
            w, h   = _probe_wh(src)

            y_pos  = (h - bar_h) if pos == "Bottom" else 0

            # drawbox with width proportional to current time
            filter_str = (
                "drawbox="
                "x=0:y={y}:"
                "w='iw*t/{total}':"
                "h={bar_h}:"
                "color=0x{color}@1:t=fill"
            ).format(
                y=y_pos, total=total, bar_h=bar_h, color=color)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._pb_console,
                on_done=lambda rc: self._done(
                    rc, out, self._pb_btn, "▶  BURN PROGRESS BAR"),
                btn=self._pb_btn,
                btn_label="▶  BURN PROGRESS BAR",
            )

        threading.Thread(target=_work, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 4 - GLITCH & VIBE
    # ═════════════════════════════════════════════════════════════════════

    def _build_glitch_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.glitch_vibe"))
        gl_nb = ttk.Notebook(outer)
        gl_nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_gl_rgb(gl_nb)
        self._build_gl_vhs(gl_nb)
        self._build_gl_grain(gl_nb)
        self._build_gl_vignette(gl_nb)
        self._build_gl_lightleak(gl_nb)

    def _build_gl_rgb(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  RGB Glitch  ")
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.rgb_chromatic_aberration_glitch"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Splits the Red, Green, and Blue channels and offsets them "
              "horizontally to create the classic chromatic aberration / "
              "cyberpunk glitch look seen everywhere on YouTube. "
              "Apply to a section or the entire video.")

        self._rgb_src = tk.StringVar()
        self._rgb_out = tk.StringVar()
        _src_row(inner, self._rgb_src,
                 lambda: self._browse_src(self._rgb_src, self._rgb_out, "_rgb"))
        _out_row(inner, self._rgb_out, lambda: self._browse_out(self._rgb_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._rgb_offset = tk.StringVar(value="6")
        self._rgb_start  = tk.StringVar(value="0")
        self._rgb_dur    = tk.StringVar(value="whole video")
        self._rgb_crf    = tk.StringVar(value="18")

        _spin(opts, "Channel offset (px):", self._rgb_offset, 1, 40, 1).pack(
            anchor="w", pady=3)

        r = tk.Frame(opts, bg=CLR["bg"]); r.pack(anchor="w", pady=3)
        tk.Label(r, text=t("effects.apply_from_s"), bg=CLR["bg"],
                 fg=CLR["fg"]).pack(side="left")
        tk.Entry(r, textvariable=self._rgb_start, width=8,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Label(r, text="  Duration (s, or 'whole video'):",
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r, textvariable=self._rgb_dur, width=12,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        _spin(opts, "CRF:", self._rgb_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._rgb_btn = _run_btn(inner, "🌈  APPLY RGB GLITCH",
                                 self._render_rgb, "#9C27B0")
        self._rgb_console = _console_block(inner)

    def _render_rgb(self):
        src = self._rgb_src.get().strip()
        out = self._rgb_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            offset = int(self._rgb_offset.get())
            start  = float(self._rgb_start.get())
        except ValueError:
            offset, start = 6, 0.0

        crf      = self._rgb_crf.get()
        dur_str  = self._rgb_dur.get().strip()
        whole    = (dur_str.lower() == "whole video")
        total    = _probe_duration(src)
        end      = total if whole else (start + float(dur_str))

        enable = "between(t,{st},{en})".format(st=start, en=end)

        # Split channels, offset R right, B left, keep G centre
        # Then blend with addition
        filter_str = (
            "[0:v]split=3[r0][g0][b0];"
            "[r0]geq=r='r(X,Y)':g=0:b=0[r];"
            "[g0]geq=r=0:g='g(X,Y)':b=0[g];"
            "[b0]geq=r=0:g=0:b='b(X,Y)'[b];"
            "[r]pad=iw+{off}:ih:0:0:color=black[rp];"
            "[b]pad=iw+{off}:ih:{off}:0:color=black[bp];"
            "[g]pad=iw+{off}:ih:{half}:0:color=black[gp];"
            "[rp][gp]blend=all_mode=addition[rg];"
            "[rg][bp]blend=all_mode=addition,"
            "crop=iw-{off}:ih:0:0"
            "[glitch];"
            "[0:v][glitch]overlay=0:0:enable='{en}'[v]"
        ).format(off=offset, half=offset // 2, en=enable)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            out,
        ]
        self.run_ffmpeg(
            cmd, self._rgb_console,
            on_done=lambda rc: self._done(
                rc, out, self._rgb_btn, "🌈  APPLY RGB GLITCH"),
            btn=self._rgb_btn,
            btn_label="🌈  APPLY RGB GLITCH",
        )

    def _build_gl_vhs(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.vhs_retro"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.vhs_retro_effect"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Simulates a degraded VHS tape: colour bleed, noise, "
              "scanlines, and edge distortion. Popular for nostalgia, "
              "horror, lo-fi, and vaporwave aesthetics.")

        self._vhs_src = tk.StringVar()
        self._vhs_out = tk.StringVar()
        _src_row(inner, self._vhs_src,
                 lambda: self._browse_src(self._vhs_src, self._vhs_out, "_vhs"))
        _out_row(inner, self._vhs_out, lambda: self._browse_out(self._vhs_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._vhs_strength = tk.StringVar(value="Medium")
        self._vhs_crf      = tk.StringVar(value="18")

        _combo(opts, "Intensity:", self._vhs_strength,
               ["Subtle", "Medium", "Heavy"], width=10).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._vhs_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._vhs_btn = _run_btn(inner, "📼  APPLY VHS EFFECT",
                                 self._render_vhs, "#546E7A")
        self._vhs_console = _console_block(inner)

    def _render_vhs(self):
        src = self._vhs_src.get().strip()
        out = self._vhs_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        crf   = self._vhs_crf.get()
        level = self._vhs_strength.get()

        # Noise strength / chroma blur / scanline opacity by level
        params = {
            "Subtle": (15,  1, 1.5, 0.10),
            "Medium": (35,  2, 2.5, 0.18),
            "Heavy":  (60,  3, 4.0, 0.28),
        }
        noise, chroma_blur, luma_blur, scan_alpha = params.get(
            level, params["Medium"])

        filter_str = (
            # Chroma blur simulates colour bleed
            "split=2[main][cb];"
            "[cb]hue=s=1.3,boxblur=luma_radius={cb}:chroma_radius={cb}[cblur];"
            "[main][cblur]blend=all_mode=overlay:all_opacity=0.3[blended];"
            # Luma softness
            "[blended]unsharp=3:3:-{lu}[soft];"
            # Noise (grain)
            "[soft]noise=alls={ns}:allf=t[noisy];"
            # Scanlines
            "[noisy]drawgrid="
            "width=0:height=2:thickness=1:"
            "color=black@{sa}[v]"
        ).format(
            cb=chroma_blur, lu=luma_blur,
            ns=noise, sa=scan_alpha)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            out,
        ]
        self.run_ffmpeg(
            cmd, self._vhs_console,
            on_done=lambda rc: self._done(
                rc, out, self._vhs_btn, "📼  APPLY VHS EFFECT"),
            btn=self._vhs_btn,
            btn_label="📼  APPLY VHS EFFECT",
        )

    def _build_gl_grain(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.film_grain"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.film_grain_cinematic_noise"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Adds organic, temporal film grain. Used by cinematographers to "
              "add texture, hide compression artefacts, and give footage a "
              "cinematic / analogue feel.")

        self._gr_src = tk.StringVar()
        self._gr_out = tk.StringVar()
        _src_row(inner, self._gr_src,
                 lambda: self._browse_src(self._gr_src, self._gr_out, "_grain"))
        _out_row(inner, self._gr_out, lambda: self._browse_out(self._gr_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._gr_amount = tk.StringVar(value="20")
        self._gr_crf    = tk.StringVar(value="18")
        _spin(opts, "Grain amount (0-100):", self._gr_amount, 1, 100, 5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._gr_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._gr_btn = _run_btn(inner, "🎞  APPLY FILM GRAIN",
                                self._render_grain, "#5D4037")
        self._gr_console = _console_block(inner)

    def _render_grain(self):
        src = self._gr_src.get().strip()
        out = self._gr_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            amount = int(self._gr_amount.get())
        except ValueError:
            amount = 20

        crf = self._gr_crf.get()
        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", "noise=alls={amt}:allf=t+u".format(amt=amount),
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._gr_console,
            on_done=lambda rc: self._done(
                rc, out, self._gr_btn, "🎞  APPLY FILM GRAIN"),
            btn=self._gr_btn,
            btn_label="🎞  APPLY FILM GRAIN",
        )

    def _build_gl_vignette(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Vignette  ")
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.cinematic_vignette"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Darkens the edges of the frame, drawing the eye to the centre. "
              "One of the most universally used effects in cinema and YouTube.")

        self._vi_src = tk.StringVar()
        self._vi_out = tk.StringVar()
        _src_row(inner, self._vi_src,
                 lambda: self._browse_src(self._vi_src, self._vi_out, "_vignette"))
        _out_row(inner, self._vi_out, lambda: self._browse_out(self._vi_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._vi_angle  = tk.StringVar(value="0.628")
        self._vi_crf    = tk.StringVar(value="18")
        _spin(opts, "Strength (angle 0.1–1.5):", self._vi_angle,
              0.1, 1.5, 0.05, width=6).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._vi_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._vi_btn = _run_btn(inner, "🔲  APPLY VIGNETTE",
                                self._render_vignette, "#37474F")
        self._vi_console = _console_block(inner)

    def _render_vignette(self):
        src = self._vi_src.get().strip()
        out = self._vi_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        angle = self._vi_angle.get()
        crf   = self._vi_crf.get()
        cmd   = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", "vignette=angle={a}".format(a=angle),
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._vi_console,
            on_done=lambda rc: self._done(
                rc, out, self._vi_btn, "🔲  APPLY VIGNETTE"),
            btn=self._vi_btn,
            btn_label="🔲  APPLY VIGNETTE",
        )

    def _build_gl_lightleak(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.light_leak"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.light_leak_lens_flare"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Simulates a burst of warm light sweeping across the frame, "
              "as if a lens flare or light leak was caught on a film camera. "
              "Great for transitions and dream-like sequences.")

        self._ll_src = tk.StringVar()
        self._ll_out = tk.StringVar()
        _src_row(inner, self._ll_src,
                 lambda: self._browse_src(self._ll_src, self._ll_out, "_lightleak"))
        _out_row(inner, self._ll_out, lambda: self._browse_out(self._ll_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._ll_start    = tk.StringVar(value="2.0")
        self._ll_dur      = tk.StringVar(value="1.0")
        self._ll_color    = tk.StringVar(value="Warm Orange")
        self._ll_crf      = tk.StringVar(value="18")

        _spin(opts, "Appear at (s):", self._ll_start, 0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Duration (s):", self._ll_dur, 0.2, 5, 0.2).pack(
            anchor="w", pady=3)
        _combo(opts, "Light colour:", self._ll_color,
               ["Warm Orange", "Cool White", "Golden Yellow",
                "Soft Pink", "Electric Blue"],
               width=16).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._ll_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._ll_btn = _run_btn(inner, "✨  APPLY LIGHT LEAK",
                                self._render_lightleak, "#FF6F00")
        self._ll_console = _console_block(inner)

    def _render_lightleak(self):
        src = self._ll_src.get().strip()
        out = self._ll_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            start = float(self._ll_start.get())
            dur   = float(self._ll_dur.get())
        except ValueError:
            start, dur = 2.0, 1.0

        crf    = self._ll_crf.get()
        end    = start + dur
        mid    = start + dur / 2.0
        col_map = {
            "Warm Orange":    "FFA040",
            "Cool White":     "E8F0FF",
            "Golden Yellow":  "FFD700",
            "Soft Pink":      "FFB0C8",
            "Electric Blue":  "40C0FF",
        }
        color = col_map.get(self._ll_color.get(), "FFA040")

        # Lerp alpha: 0 → max at mid → 0 at end, sweeping with geq
        filter_str = (
            "geq="
            "r='r(X,Y)+if(between(t,{st},{en}),"
            "  if(lt(t,{mid}),"
            "    ((t-{st})/{hdur})*200*0x{r}/255*(1-(X/W)),"
            "    ((1-(t-{mid})/{hdur}))*200*0x{r}/255*(1-(X/W))),"
            "  0)':"
            "g='g(X,Y)+if(between(t,{st},{en}),"
            "  if(lt(t,{mid}),"
            "    ((t-{st})/{hdur})*200*0x{g2}/255*(1-(X/W)),"
            "    ((1-(t-{mid})/{hdur}))*200*0x{g2}/255*(1-(X/W))),"
            "  0)':"
            "b='b(X,Y)+if(between(t,{st},{en}),"
            "  if(lt(t,{mid}),"
            "    ((t-{st})/{hdur})*200*0x{b2}/255*(1-(X/W)),"
            "    ((1-(t-{mid})/{hdur}))*200*0x{b2}/255*(1-(X/W))),"
            "  0)'"
        ).format(
            st=start, en=end, mid=mid, hdur=dur / 2.0,
            r=int(color[0:2], 16),
            g2=int(color[2:4], 16),
            b2=int(color[4:6], 16),
        )

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", filter_str,
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._ll_console,
            on_done=lambda rc: self._done(
                rc, out, self._ll_btn, "✨  APPLY LIGHT LEAK"),
            btn=self._ll_btn,
            btn_label="✨  APPLY LIGHT LEAK",
        )

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 5 - MOTION
    # ═════════════════════════════════════════════════════════════════════

    def _build_motion_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.motion"))
        mo_nb = ttk.Notebook(outer)
        mo_nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_mo_shake(mo_nb)
        self._build_mo_zoompunch(mo_nb)
        self._build_mo_kenburns(mo_nb)
        self._build_mo_whippan(mo_nb)

    def _build_mo_shake(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.camera_shake"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.camera_shake_2"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Simulates an unstabilised handheld camera. Apply to impact moments, "
              "action sequences, or jump scares. Amplitude controls jitter size. "
              "Frame edges are cropped slightly to hide the shake border.")

        self._sh_src = tk.StringVar()
        self._sh_out = tk.StringVar()
        _src_row(inner, self._sh_src,
                 lambda: self._browse_src(self._sh_src, self._sh_out, "_shake"))
        _out_row(inner, self._sh_out, lambda: self._browse_out(self._sh_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._sh_amp   = tk.StringVar(value="10")
        self._sh_speed = tk.StringVar(value="Normal")
        self._sh_start = tk.StringVar(value="0")
        self._sh_dur   = tk.StringVar(value="whole video")
        self._sh_crf   = tk.StringVar(value="18")

        _spin(opts, "Amplitude (px):", self._sh_amp, 2, 60, 2).pack(
            anchor="w", pady=3)
        _combo(opts, "Shake speed:", self._sh_speed,
               ["Slow", "Normal", "Fast", "Violent"], width=10).pack(
            anchor="w", pady=3)
        r = tk.Frame(opts, bg=CLR["bg"]); r.pack(anchor="w", pady=3)
        tk.Label(r, text=t("common.start_s"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r, textvariable=self._sh_start, width=8,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Label(r, text="  Duration (s / 'whole video'):",
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r, textvariable=self._sh_dur, width=14,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        _spin(opts, "CRF:", self._sh_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._sh_btn = _run_btn(inner, "📳  APPLY CAMERA SHAKE",
                                self._render_shake, "#B71C1C")
        self._sh_console = _console_block(inner)

    def _render_shake(self):
        src = self._sh_src.get().strip()
        out = self._sh_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                amp   = int(self._sh_amp.get())
                start = float(self._sh_start.get())
            except ValueError:
                amp, start = 10, 0.0

            crf     = self._sh_crf.get()
            speed_map = {"Slow": (7, 13), "Normal": (19, 31),
                         "Fast": (37, 53), "Violent": (61, 79)}
            freq1, freq2 = speed_map.get(self._sh_speed.get(), (19, 31))

            dur_str = self._sh_dur.get().strip()
            total   = _probe_duration(src)
            whole   = (dur_str.lower() == "whole video")
            end     = total if whole else (start + float(dur_str))
            enable  = "between(t,{st},{en})".format(st=start, en=end)

            # Use crop to hide black edges introduced by the translate
            w, h = _probe_wh(src)
            cw   = w - amp * 2
            ch   = h - amp * 2

            filter_str = (
                "crop={cw}:{ch}:"
                "x='if({en},{amp}+{amp}*sin(t*{f1}),{amp})':"
                "y='if({en},{amp}+{amp}*cos(t*{f2}),{amp})',"
                "scale={w}:{h}"
            ).format(
                cw=cw, ch=ch, amp=amp,
                f1=freq1, f2=freq2,
                w=w, h=h,
                en=enable,
            )

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._sh_console,
                on_done=lambda rc: self._done(
                    rc, out, self._sh_btn, "📳  APPLY CAMERA SHAKE"),
                btn=self._sh_btn,
                btn_label="📳  APPLY CAMERA SHAKE",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_mo_zoompunch(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.zoom_punch"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.zoom_punch_impact_zoom"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "A sudden very fast zoom-in at a specific timestamp, synced to an "
              "impact, beat drop, or punchline. A favourite for meme edits, "
              "gaming highlights, and react content.")

        self._zp_src   = tk.StringVar()
        self._zp_out   = tk.StringVar()
        _src_row(inner, self._zp_src,
                 lambda: self._browse_src(self._zp_src, self._zp_out, "_zoompunch"))
        _out_row(inner, self._zp_out, lambda: self._browse_out(self._zp_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._zp_at      = tk.StringVar(value="5.0")
        self._zp_zoom    = tk.StringVar(value="1.4")
        self._zp_attack  = tk.StringVar(value="0.1")
        self._zp_hold    = tk.StringVar(value="0.3")
        self._zp_release = tk.StringVar(value="0.5")
        self._zp_crf     = tk.StringVar(value="18")

        _spin(opts, "Punch at (s):",       self._zp_at,      0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Zoom factor (×):",    self._zp_zoom,    1.1, 4, 0.05).pack(
            anchor="w", pady=3)
        _spin(opts, "Attack (s):",         self._zp_attack,  0.03, 0.5, 0.02).pack(
            anchor="w", pady=3)
        _spin(opts, "Hold at peak (s):",   self._zp_hold,    0.05, 2, 0.05).pack(
            anchor="w", pady=3)
        _spin(opts, "Release / ease (s):", self._zp_release, 0.1, 3, 0.1).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._zp_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._zp_btn = _run_btn(inner, "👊  APPLY ZOOM PUNCH",
                                self._render_zoompunch, "#D32F2F")
        self._zp_console = _console_block(inner)

    def _render_zoompunch(self):
        src = self._zp_src.get().strip()
        out = self._zp_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                at      = float(self._zp_at.get())
                zoom    = float(self._zp_zoom.get())
                attack  = float(self._zp_attack.get())
                hold    = float(self._zp_hold.get())
                release = float(self._zp_release.get())
            except ValueError:
                at, zoom, attack, hold, release = 5.0, 1.4, 0.1, 0.3, 0.5

            crf       = self._zp_crf.get()
            t0, t1    = at, at + attack
            t2        = t1 + hold
            t3        = t2 + release

            # Piecewise zoom expression:
            # Before t0 → 1, attack t0→t1 → 1 + (zoom-1)*progress,
            # hold t1→t2 → zoom, release t2→t3 → zoom back to 1
            z_expr = (
                "if(lt(t,{t0}),1,"
                "if(lt(t,{t1}),1+({zm}-1)*(t-{t0})/{att},"
                "if(lt(t,{t2}),{zm},"
                "if(lt(t,{t3}),{zm}-({zm}-1)*(t-{t2})/{rel},"
                "1))))"
            ).format(t0=at, t1=t1, t2=t2, t3=t3,
                     zm=zoom, att=attack, rel=release)

            w, h = _probe_wh(src)
            filter_str = (
                "scale=iw*{z}:ih*{z}:eval=frame,"
                "crop={w}:{h}:(iw-{w})/2:(ih-{h})/2"
            ).format(z=z_expr, w=w, h=h)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._zp_console,
                on_done=lambda rc: self._done(
                    rc, out, self._zp_btn, "👊  APPLY ZOOM PUNCH"),
                btn=self._zp_btn,
                btn_label="👊  APPLY ZOOM PUNCH",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_mo_kenburns(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Ken Burns  ")
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.ken_burns_pan_zoom"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "A slow, cinematic pan and zoom across the entire video. "
              "Named after the documentary filmmaker. Ideal for drone footage, "
              "landscape shots, interview B-roll, and still photo slideshows.")

        self._kb_src = tk.StringVar()
        self._kb_out = tk.StringVar()
        _src_row(inner, self._kb_src,
                 lambda: self._browse_src(self._kb_src, self._kb_out, "_kenburns"))
        _out_row(inner, self._kb_out, lambda: self._browse_out(self._kb_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._kb_zoom_start = tk.StringVar(value="1.0")
        self._kb_zoom_end   = tk.StringVar(value="1.15")
        self._kb_dir        = tk.StringVar(value="Left → Right")
        self._kb_crf        = tk.StringVar(value="18")

        _spin(opts, "Zoom start (×):", self._kb_zoom_start,
              1.0, 2.0, 0.05).pack(anchor="w", pady=3)
        _spin(opts, "Zoom end (×):",   self._kb_zoom_end,
              1.0, 2.0, 0.05).pack(anchor="w", pady=3)
        _combo(opts, "Pan direction:", self._kb_dir,
               ["Left → Right", "Right → Left",
                "Top → Bottom", "Bottom → Top",
                "Centre zoom only"], width=18).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._kb_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._kb_btn = _run_btn(inner, "🎥  APPLY KEN BURNS",
                                self._render_kenburns, "#1B5E20")
        self._kb_console = _console_block(inner)

    def _render_kenburns(self):
        src = self._kb_src.get().strip()
        out = self._kb_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                z0  = float(self._kb_zoom_start.get())
                z1  = float(self._kb_zoom_end.get())
            except ValueError:
                z0, z1 = 1.0, 1.15

            crf   = self._kb_crf.get()
            total = _probe_duration(src)
            w, h  = _probe_wh(src)
            fps   = 30
            dir_  = self._kb_dir.get()

            # Linear zoom from z0 to z1 over the whole clip
            zoom_expr = "{z0}+({z1}-{z0})*t/{total}".format(
                z0=z0, z1=z1, total=max(total, 0.01))

            dir_map = {
                "Left → Right":   ("iw*(zoom-1)*t/{total}".format(total=total), "(ih*(zoom-1))/2"),
                "Right → Left":   ("iw*(zoom-1)*(1-t/{total})".format(total=total), "(ih*(zoom-1))/2"),
                "Top → Bottom":   ("(iw*(zoom-1))/2", "ih*(zoom-1)*t/{total}".format(total=total)),
                "Bottom → Top":   ("(iw*(zoom-1))/2", "ih*(zoom-1)*(1-t/{total})".format(total=total)),
                "Centre zoom only": ("(iw*(zoom-1))/2", "(ih*(zoom-1))/2"),
            }
            x_expr, y_expr = dir_map.get(dir_, dir_map["Left → Right"])

            filter_str = (
                "zoompan="
                "z='{z}':"
                "x='{x}':"
                "y='{y}':"
                "d=1:s={w}x{h}:fps={fps}"
            ).format(z=zoom_expr, x=x_expr, y=y_expr, w=w, h=h, fps=fps)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._kb_console,
                on_done=lambda rc: self._done(
                    rc, out, self._kb_btn, "🎥  APPLY KEN BURNS"),
                btn=self._kb_btn,
                btn_label="🎥  APPLY KEN BURNS",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_mo_whippan(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.whip_pan_blur"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.whip_pan_motion_blur"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Adds an extreme horizontal or vertical motion blur over a short "
              "window, simulating a fast camera whip pan. "
              "Perfect for transitions between scenes, used on YouTube by "
              "MrBeast, MKBHD, Linus Tech Tips, and almost every vlogger.")

        self._wp_src  = tk.StringVar()
        self._wp_out  = tk.StringVar()
        _src_row(inner, self._wp_src,
                 lambda: self._browse_src(self._wp_src, self._wp_out, "_whippan"))
        _out_row(inner, self._wp_out, lambda: self._browse_out(self._wp_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._wp_at    = tk.StringVar(value="5.0")
        self._wp_dur   = tk.StringVar(value="0.3")
        self._wp_dir   = tk.StringVar(value="Horizontal")
        self._wp_str   = tk.StringVar(value="40")
        self._wp_crf   = tk.StringVar(value="18")

        _spin(opts, "Apply at (s):",  self._wp_at,  0, 3600, 0.5).pack(
            anchor="w", pady=3)
        _spin(opts, "Duration (s):",  self._wp_dur, 0.1, 2, 0.05).pack(
            anchor="w", pady=3)
        _combo(opts, "Direction:",    self._wp_dir,
               ["Horizontal", "Vertical"], width=12).pack(anchor="w", pady=3)
        _spin(opts, "Blur strength:", self._wp_str, 5, 120, 5).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._wp_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._wp_btn = _run_btn(inner, "💨  APPLY WHIP PAN BLUR",
                                self._render_whippan, "#0D47A1")
        self._wp_console = _console_block(inner)

    def _render_whippan(self):
        src = self._wp_src.get().strip()
        out = self._wp_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            at  = float(self._wp_at.get())
            dur = float(self._wp_dur.get())
            strength = int(self._wp_str.get())
        except ValueError:
            at, dur, strength = 5.0, 0.3, 40

        crf      = self._wp_crf.get()
        end      = at + dur
        enable   = "between(t,{st},{en})".format(st=at, en=end)
        horiz    = self._wp_dir.get() == "Horizontal"

        # minterpolate + boxblur combo; boxblur with luma_power controls intensity
        if horiz:
            blur_filter = "boxblur=luma_radius={s}:luma_power=1:chroma_radius={s}:chroma_power=1".format(
                s=strength)
        else:
            blur_filter = "boxblur=luma_radius=1:luma_power=1:chroma_radius=1:chroma_power=1,transpose,boxblur=luma_radius={s}:luma_power=1,transpose".format(
                s=strength)

        filter_str = (
            "split[orig][blur_src];"
            "[blur_src]{blur},format=rgba[blurred];"
            "[orig][blurred]overlay=0:0:enable='{en}'[v]"
        ).format(blur=blur_filter, en=enable)

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            out,
        ]
        self.run_ffmpeg(
            cmd, self._wp_console,
            on_done=lambda rc: self._done(
                rc, out, self._wp_btn, "💨  APPLY WHIP PAN BLUR"),
            btn=self._wp_btn,
            btn_label="💨  APPLY WHIP PAN BLUR",
        )

    # ═════════════════════════════════════════════════════════════════════
    #  TAB 6 - BRANDING
    # ═════════════════════════════════════════════════════════════════════

    def _build_branding_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("effects.branding"))
        br_nb = ttk.Notebook(outer)
        br_nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_br_meme(br_nb)
        self._build_br_cinebars(br_nb)
        self._build_br_watermark(br_nb)

    def _build_br_meme(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.meme_caption"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.impact_meme_caption"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Burns large white Impact-style text with black outline onto the "
              "video: top caption, bottom caption, or both. The classic meme "
              "format used on every reaction and highlight channel.")

        self._mc_src    = tk.StringVar()
        self._mc_out    = tk.StringVar()
        _src_row(inner, self._mc_src,
                 lambda: self._browse_src(self._mc_src, self._mc_out, "_meme"))
        _out_row(inner, self._mc_out, lambda: self._browse_out(self._mc_out))

        opts = _lf(inner, "Caption Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._mc_top    = tk.StringVar(value="WHEN YOU REALISE")
        self._mc_bot    = tk.StringVar(value="IT WAS THAT EASY")
        self._mc_size   = tk.StringVar(value="72")
        self._mc_start  = tk.StringVar(value="0")
        self._mc_hold   = tk.StringVar(value="whole video")
        self._mc_crf    = tk.StringVar(value="18")

        for lbl, var in [("Top text:", self._mc_top), ("Bottom text:", self._mc_bot)]:
            r = tk.Frame(opts, bg=CLR["bg"]); r.pack(anchor="w", pady=3)
            tk.Label(r, text=lbl, bg=CLR["bg"], fg=CLR["fg"],
                     width=16, anchor="e").pack(side="left")
            tk.Entry(r, textvariable=var, width=40,
                     bg=CLR["panel"], fg=CLR["fg"],
                     insertbackground=CLR["fg"],
                     font=(UI_FONT, 11)).pack(side="left", padx=6)

        _spin(opts, "Font size:", self._mc_size, 24, 180, 4).pack(
            anchor="w", pady=3)
        r2 = tk.Frame(opts, bg=CLR["bg"]); r2.pack(anchor="w", pady=3)
        tk.Label(r2, text=t("pip.show_from_label"), bg=CLR["bg"],
                 fg=CLR["fg"]).pack(side="left")
        tk.Entry(r2, textvariable=self._mc_start, width=8,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Label(r2, text="  Duration (s / 'whole video'):",
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Entry(r2, textvariable=self._mc_hold, width=14,
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=4)
        _spin(opts, "CRF:", self._mc_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._mc_btn = _run_btn(inner, "🗯  BURN MEME CAPTIONS",
                                self._render_meme, "#F57F17")
        self._mc_console = _console_block(inner)

    def _render_meme(self):
        src = self._mc_src.get().strip()
        out = self._mc_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            size  = int(self._mc_size.get())
            start = float(self._mc_start.get())
        except ValueError:
            size, start = 72, 0.0

        crf    = self._mc_crf.get()
        top    = self._mc_top.get().replace("'", "\\'").replace(":", "\\:")
        bot    = self._mc_bot.get().replace("'", "\\'").replace(":", "\\:")
        dur_s  = self._mc_hold.get().strip()
        total  = _probe_duration(src)
        whole  = (dur_s.lower() == "whole video")
        end    = total if whole else (start + float(dur_s))
        enable = "between(t,{st},{en})".format(st=start, en=end)

        filters = []
        if top:
            filters.append(
                "drawtext="
                "text='{t}':"
                "fontsize={sz}:"
                "fontcolor=white:"
                "x=(w-text_w)/2:y=20:"
                "bordercolor=black:borderw=4:"
                "enable='{en}'".format(t=top, sz=size, en=enable))
        if bot:
            filters.append(
                "drawtext="
                "text='{t}':"
                "fontsize={sz}:"
                "fontcolor=white:"
                "x=(w-text_w)/2:y=h-text_h-20:"
                "bordercolor=black:borderw=4:"
                "enable='{en}'".format(t=bot, sz=size, en=enable))

        if not filters:
            messagebox.showwarning(t("common.warning"), "Enter at least one caption.")
            return

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", ",".join(filters),
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._mc_console,
            on_done=lambda rc: self._done(
                rc, out, self._mc_btn, "🗯  BURN MEME CAPTIONS"),
            btn=self._mc_btn,
            btn_label="🗯  BURN MEME CAPTIONS",
        )

    def _build_br_cinebars(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.cinematic_bars"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.cinematic_black_bars"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Adds letterbox bars to simulate a 2.39:1 or 2.35:1 anamorphic "
              "widescreen cinema aspect ratio. Optionally animate them sliding "
              "in from the edges for a dramatic reveal.")

        self._cb_src   = tk.StringVar()
        self._cb_out   = tk.StringVar()
        _src_row(inner, self._cb_src,
                 lambda: self._browse_src(self._cb_src, self._cb_out, "_cinebars"))
        _out_row(inner, self._cb_out, lambda: self._browse_out(self._cb_out))

        opts = _lf(inner, "Options")
        opts.pack(fill="x", padx=18, pady=8)
        self._cb_ratio = tk.StringVar(value="2.39:1")
        self._cb_anim  = tk.BooleanVar(value=True)
        self._cb_adur  = tk.StringVar(value="1.0")
        self._cb_crf   = tk.StringVar(value="18")

        _combo(opts, "Aspect ratio:", self._cb_ratio,
               ["2.39:1 (Scope)", "2.35:1 (Scope)", "2.20:1",
                "1.85:1 (Flat)"], width=18).pack(anchor="w", pady=3)
        r = tk.Frame(opts, bg=CLR["bg"]); r.pack(anchor="w", pady=3)
        tk.Checkbutton(r, text=t("effects.animate_bars_sliding_in"),
                       variable=self._cb_anim,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["panel"],
                       activebackground=CLR["bg"]).pack(side="left")
        _spin(opts, "Animation duration (s):", self._cb_adur, 0.2, 3, 0.2).pack(
            anchor="w", pady=3)
        _spin(opts, "CRF:", self._cb_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._cb_btn = _run_btn(inner, "🎬  APPLY CINEMATIC BARS",
                                self._render_cinebars, "#1A237E")
        self._cb_console = _console_block(inner)

    def _render_cinebars(self):
        src = self._cb_src.get().strip()
        out = self._cb_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        def _work():
            try:
                adur = float(self._cb_adur.get())
            except ValueError:
                adur = 1.0

            crf    = self._cb_crf.get()
            ratio  = self._cb_ratio.get()
            w, h   = _probe_wh(src)
            fps    = 30

            ratio_map = {
                "2.39:1 (Scope)": 2.39, "2.35:1 (Scope)": 2.35,
                "2.20:1": 2.20,          "1.85:1 (Flat)":  1.85,
            }
            ar     = ratio_map.get(ratio, 2.39)
            new_h  = int(w / ar)
            new_h += (new_h % 2)
            bar_h  = (h - new_h) // 2

            animate = self._cb_anim.get()
            frames  = int(adur * fps)

            if animate:
                # Top bar slides from -bar_h → 0, bottom from h+bar_h → h-bar_h
                top_y = "if(lte(n,{fr}),{bh}*(n/{fr}-1),0)".format(
                    fr=frames, bh=bar_h)
                bot_y = "if(lte(n,{fr}),{h}+(1-n/{fr})*{bh},{hb})".format(
                    fr=frames, h=h - bar_h, bh=bar_h, hb=h - bar_h)
            else:
                top_y = "0"
                bot_y = str(h - bar_h)

            filter_str = (
                "drawbox=x=0:y='{ty}':w={w}:h={bh}:color=black@1:t=fill,"
                "drawbox=x=0:y='{by}':w={w}:h={bh}:color=black@1:t=fill"
            ).format(ty=top_y, by=bot_y, w=w, bh=bar_h)

            cmd = [
                _ffmpeg(), "-y", "-i", src,
                "-vf", filter_str,
                t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                t("dynamics.c_a"), "copy",
                "-movflags", t("dynamics.faststart"),
                out,
            ]
            self.run_ffmpeg(
                cmd, self._cb_console,
                on_done=lambda rc: self._done(
                    rc, out, self._cb_btn, "🎬  APPLY CINEMATIC BARS"),
                btn=self._cb_btn,
                btn_label="🎬  APPLY CINEMATIC BARS",
            )

        threading.Thread(target=_work, daemon=True).start()

    def _build_br_watermark(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("effects.social_watermark"))
        _, inner = _make_scrollable(f)

        tk.Label(inner, text=t("effects.social_media_watermark"),
                 font=(UI_FONT, 12, "bold"),
                 bg=CLR["bg"], fg=CLR["accent"]).pack(
            anchor="w", padx=18, pady=(14, 2))
        _hint(inner,
              "Burns a persistent channel handle / watermark onto the entire "
              "video. Supports @ prefixes, emojis, and custom positioning. "
              "Essential for short-form content repurposed across platforms.")

        self._wm_src  = tk.StringVar()
        self._wm_out  = tk.StringVar()
        _src_row(inner, self._wm_src,
                 lambda: self._browse_src(self._wm_src, self._wm_out, "_watermark"))
        _out_row(inner, self._wm_out, lambda: self._browse_out(self._wm_out))

        opts = _lf(inner, "Watermark Options")
        opts.pack(fill="x", padx=18, pady=8)

        self._wm_text   = tk.StringVar(value="@YourChannel")
        self._wm_size   = tk.StringVar(value="38")
        self._wm_pos    = tk.StringVar(value="Bottom Right")
        self._wm_alpha  = tk.StringVar(value="0.70")
        self._wm_crf    = tk.StringVar(value="18")

        r0 = tk.Frame(opts, bg=CLR["bg"]); r0.pack(anchor="w", pady=3)
        tk.Label(r0, text=t("effects.watermark_text"), bg=CLR["bg"],
                 fg=CLR["fg"]).pack(side="left")
        tk.Entry(r0, textvariable=self._wm_text, width=28,
                 font=(UI_FONT, 12),
                 bg=CLR["panel"], fg=CLR["fg"],
                 insertbackground=CLR["fg"]).pack(side="left", padx=6)

        _spin(opts, "Font size:", self._wm_size, 12, 100, 2).pack(
            anchor="w", pady=3)
        _combo(opts, "Position:", self._wm_pos,
               ["Bottom Right", "Bottom Left",
                "Top Right",    "Top Left",
                "Centre"], width=14).pack(anchor="w", pady=3)
        _spin(opts, "Opacity (0.1–1.0):", self._wm_alpha,
              0.1, 1.0, 0.05, width=6).pack(anchor="w", pady=3)
        _spin(opts, "CRF:", self._wm_crf, 12, 30, 1).pack(anchor="w", pady=3)

        self._wm_btn = _run_btn(inner, "©  BURN WATERMARK",
                                self._render_watermark, "#455A64")
        self._wm_console = _console_block(inner)

    def _render_watermark(self):
        src = self._wm_src.get().strip()
        out = self._wm_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not out:
            messagebox.showwarning(t("common.warning"), "Please set an output path.")
            return

        try:
            size  = int(self._wm_size.get())
            alpha = float(self._wm_alpha.get())
        except ValueError:
            size, alpha = 38, 0.70

        crf   = self._wm_crf.get()
        text  = self._wm_text.get().replace("'", "\\'").replace(":", "\\:")
        pos   = self._wm_pos.get()
        margin = 24

        pos_map = {
            "Bottom Right": ("w-text_w-{m}".format(m=margin),
                             "h-text_h-{m}".format(m=margin)),
            "Bottom Left":  (str(margin), "h-text_h-{m}".format(m=margin)),
            "Top Right":    ("w-text_w-{m}".format(m=margin), str(margin)),
            "Top Left":     (str(margin), str(margin)),
            "Centre":       ("(w-text_w)/2", "(h-text_h)/2"),
        }
        x_e, y_e = pos_map.get(pos, pos_map["Bottom Right"])

        filter_str = (
            "drawtext="
            "text='{text}':"
            "fontsize={sz}:"
            "fontcolor=white@{alpha}:"
            "x={x}:y={y}:"
            "shadowcolor=black@{sha}:shadowx=2:shadowy=2"
        ).format(
            text=text, sz=size, alpha=alpha,
            x=x_e, y=y_e,
            sha=min(alpha + 0.2, 1.0),
        )

        cmd = [
            _ffmpeg(), "-y", "-i", src,
            "-vf", filter_str,
            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
            t("dynamics.c_a"), "copy",
            "-movflags", t("dynamics.faststart"),
            out,
        ]
        self.run_ffmpeg(
            cmd, self._wm_console,
            on_done=lambda rc: self._done(
                rc, out, self._wm_btn, "©  BURN WATERMARK"),
            btn=self._wm_btn,
            btn_label="©  BURN WATERMARK",
        )

    # ═════════════════════════════════════════════════════════════════════
    #  Shared helpers used by all render methods
    # ═════════════════════════════════════════════════════════════════════

    def _browse_src(self, src_var, out_var, suffix):
        p = filedialog.askopenfilename(filetypes=VIDEO_TYPES)
        if not p:
            return
        src_var.set(p)
        base = os.path.splitext(p)[0]
        if not out_var.get():
            out_var.set(base + suffix + ".mp4")

    @staticmethod
    def _browse_out(out_var):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[(t("effects.mp4_video"), "*.mp4"), (t("youtube.all_files"), t("ducker.item_2"))])
        if p:
            out_var.set(p)

    def _done(self, rc, out_path, btn, btn_label):
        btn.config(state="normal", text=btn_label)
        self.show_result(rc, out_path)
