"""
tab_animatedzoom.py  ─  Animated Zoom & Pan

Keyframed crop/zoom/pan over time. THE essential content editor move:
punch-in zooms on facecams, Ken Burns on stills, slow pans across
wide shots, dramatic zoom-ins on reactions.

Modes
─────
  1. Punch-In Zoom    - Zoom into a region at a specific time (snappy or smooth)
  2. Ken Burns         - Slow zoom + pan across the full clip (documentary style)
  3. Keyframe Pan      - Define start/end crop regions, animate between them
  4. Zoom Pulse        - Quick zoom in-and-out for comedic emphasis
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import math

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


class AnimatedZoomTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.vid_w, self.vid_h = 1920, 1080
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.animated_zoom"),
                         t("zoom.subtitle"),
                         icon="🔎")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._info_lbl = tk.Label(sf, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._info_lbl.pack(side="left", padx=10)

        # ── Mode ──────────────────────────────────────────────────────────
        mode_lf = tk.LabelFrame(self, text=f"  {t('zoom.mode_section')}  ", padx=15, pady=10,
                                font=(UI_FONT, 9, "bold"))
        mode_lf.pack(fill="x", padx=20, pady=8)

        self._mode_var = tk.StringVar(value="punch")
        modes = [
            ("punch",    t("zoom.zoom_punch_in_label"),
             t("zoom.zoom_punch_in_hint")),
            ("kenburns", t("zoom.zoom_ken_burns_label"),
             t("zoom.zoom_ken_burns_hint")),
            ("keyframe", t("zoom.zoom_keyframe_label"),
             t("zoom.zoom_keyframe_hint")),
            ("pulse",    t("zoom.zoom_pulse_label"),
             t("zoom.zoom_pulse_hint")),
        ]
        for val, label, desc in modes:
            row = tk.Frame(mode_lf, bg=CLR["bg"])
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, text=label, variable=self._mode_var, value=val,
                           font=(UI_FONT, 10), bg=CLR["bg"],
                           command=self._on_mode).pack(side="left")
            tk.Label(row, text=desc, fg=CLR["fgdim"], font=(UI_FONT, 9),
                     bg=CLR["bg"]).pack(side="left", padx=(8, 0))

        # ── Punch-In frame ────────────────────────────────────────────────
        self._punch_f = tk.LabelFrame(self, text=f"  {t('zoom.punch_settings_section')}  ", padx=15, pady=8,
                                      font=(UI_FONT, 9, "bold"))

        pr1 = tk.Frame(self._punch_f)
        pr1.pack(fill="x", pady=3)
        tk.Label(pr1, text=t("zoom.zoom_start_time"), font=(UI_FONT, 10), width=16,
                 anchor="e").pack(side="left")
        self._punch_start = tk.StringVar(value="0.0")
        tk.Entry(pr1, textvariable=self._punch_start, width=8, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(pr1, text=t("zoom.zoom_end_time"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._punch_end = tk.StringVar(value="3.0")
        tk.Entry(pr1, textvariable=self._punch_end, width=8, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(pr1, text="seconds", fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        pr2 = tk.Frame(self._punch_f)
        pr2.pack(fill="x", pady=3)
        tk.Label(pr2, text=t("zoom.zoom_factor"), font=(UI_FONT, 10), width=16,
                 anchor="e").pack(side="left")
        self._punch_zoom = tk.DoubleVar(value=1.5)
        tk.Scale(pr2, variable=self._punch_zoom, from_=1.1, to=4.0,
                 resolution=0.1, orient="horizontal", length=200,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=6)
        self._pz_lbl = tk.Label(pr2, text="1.5×", fg=CLR["accent"],
                                font=(MONO_FONT, 11, "bold"), width=5)
        self._pz_lbl.pack(side="left")
        self._punch_zoom.trace_add("write",
            lambda *_: self._pz_lbl.config(text=f"{self._punch_zoom.get():.1f}×"))

        # Quick zoom presets
        qz = tk.Frame(pr2)
        qz.pack(side="left", padx=14)
        for val, lbl in [(1.2, "1.2×"), (1.5, "1.5×"), (2.0, "2×"),
                          (2.5, "2.5×"), (3.0, "3×")]:
            tk.Button(qz, text=lbl, width=4, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9),
                      command=lambda v=val: self._punch_zoom.set(v)
                      ).pack(side="left", padx=2)

        pr3 = tk.Frame(self._punch_f)
        pr3.pack(fill="x", pady=3)
        tk.Label(pr3, text=t("zoom.zoom_target_x"), font=(UI_FONT, 10), width=16,
                 anchor="e").pack(side="left")
        self._punch_x = tk.DoubleVar(value=50.0)
        tk.Scale(pr3, variable=self._punch_x, from_=0, to=100,
                 resolution=1, orient="horizontal", length=160,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=6)
        tk.Label(pr3, text="%", fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        tk.Label(pr3, text="  Y:", font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._punch_y = tk.DoubleVar(value=50.0)
        tk.Scale(pr3, variable=self._punch_y, from_=0, to=100,
                 resolution=1, orient="horizontal", length=160,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=6)
        tk.Label(pr3, text="%", fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        pr4 = tk.Frame(self._punch_f)
        pr4.pack(fill="x", pady=3)
        tk.Label(pr4, text=t("zoom.ease"), font=(UI_FONT, 10), width=16,
                 anchor="e").pack(side="left")
        self._ease_var = tk.StringVar(value="smooth")
        for val, lbl in [("smooth", "Smooth (ease in/out)"),
                          ("snap", "Snappy (instant)"),
                          ("linear", "Linear")]:
            tk.Radiobutton(pr4, text=lbl, variable=self._ease_var, value=val,
                           font=(UI_FONT, 10)).pack(side="left", padx=8)

        # ── Ken Burns frame ───────────────────────────────────────────────
        self._kb_f = tk.LabelFrame(self, text=f"  {t('zoom.ken_burns_settings_section')}  ", padx=15, pady=8,
                                   font=(UI_FONT, 9, "bold"))

        kbr1 = tk.Frame(self._kb_f)
        kbr1.pack(fill="x", pady=3)
        tk.Label(kbr1, text=t("zoom.direction"), font=(UI_FONT, 10)).pack(side="left")
        self._kb_dir = tk.StringVar(value="zoom_in")
        for val, lbl in [("zoom_in", "Zoom In"), ("zoom_out", "Zoom Out"),
                          ("pan_left", "Pan Left"), ("pan_right", "Pan Right")]:
            tk.Radiobutton(kbr1, text=lbl, variable=self._kb_dir, value=val,
                           font=(UI_FONT, 10)).pack(side="left", padx=8)

        kbr2 = tk.Frame(self._kb_f)
        kbr2.pack(fill="x", pady=3)
        tk.Label(kbr2, text=t("lut.intensity_label"), font=(UI_FONT, 10)).pack(side="left")
        self._kb_intensity = tk.DoubleVar(value=1.3)
        tk.Scale(kbr2, variable=self._kb_intensity, from_=1.05, to=2.0,
                 resolution=0.05, orient="horizontal", length=200,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=8)
        self._kbi_lbl = tk.Label(kbr2, text="1.30×", fg=CLR["accent"],
                                 font=(MONO_FONT, 10), width=6)
        self._kbi_lbl.pack(side="left")
        self._kb_intensity.trace_add("write",
            lambda *_: self._kbi_lbl.config(text=f"{self._kb_intensity.get():.2f}×"))

        # ── Keyframe Pan frame ────────────────────────────────────────────
        self._kf_f = tk.LabelFrame(self, text=f"  {t('zoom.keyframe_section')}  ",
                                   padx=15, pady=8, font=(UI_FONT, 9, "bold"))

        kfr = tk.Frame(self._kf_f)
        kfr.pack(fill="x", pady=3)
        tk.Label(kfr, text=t("zoom.start_crop_x"), font=(UI_FONT, 10)).pack(side="left")
        self._kf_sx = tk.StringVar(value="0")
        tk.Entry(kfr, textvariable=self._kf_sx, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(kfr, text=t("zoom.y"), font=(UI_FONT, 10)).pack(side="left")
        self._kf_sy = tk.StringVar(value="0")
        tk.Entry(kfr, textvariable=self._kf_sy, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(kfr, text=t("zoom.zoom"), font=(UI_FONT, 10)).pack(side="left")
        self._kf_sz = tk.StringVar(value="1.0")
        tk.Entry(kfr, textvariable=self._kf_sz, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)

        tk.Label(kfr, text=t("zoom.end_x"), font=(UI_FONT, 10, "bold"),
                 fg=CLR["accent"]).pack(side="left", padx=(12, 0))
        self._kf_ex = tk.StringVar(value="30")
        tk.Entry(kfr, textvariable=self._kf_ex, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(kfr, text=t("zoom.y"), font=(UI_FONT, 10)).pack(side="left")
        self._kf_ey = tk.StringVar(value="20")
        tk.Entry(kfr, textvariable=self._kf_ey, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(kfr, text=t("zoom.zoom"), font=(UI_FONT, 10)).pack(side="left")
        self._kf_ez = tk.StringVar(value="1.5")
        tk.Entry(kfr, textvariable=self._kf_ez, width=5, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)

        # ── Pulse frame ───────────────────────────────────────────────────
        self._pulse_f = tk.LabelFrame(self, text=f"  {t('zoom.pulse_settings_section')}  ", padx=15, pady=8,
                                      font=(UI_FONT, 9, "bold"))

        plr1 = tk.Frame(self._pulse_f)
        plr1.pack(fill="x", pady=3)
        tk.Label(plr1, text=t("zoom.pulse_at_time"), font=(UI_FONT, 10)).pack(side="left")
        self._pulse_time = tk.StringVar(value="1.0")
        tk.Entry(plr1, textvariable=self._pulse_time, width=8, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(plr1, text=t("zoom.pulse_duration"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._pulse_dur = tk.StringVar(value="0.3")
        tk.Entry(plr1, textvariable=self._pulse_dur, width=6, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(plr1, text="s", fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        plr2 = tk.Frame(self._pulse_f)
        plr2.pack(fill="x", pady=3)
        tk.Label(plr2, text=t("zoom.pulse_zoom"), font=(UI_FONT, 10)).pack(side="left")
        self._pulse_zoom = tk.DoubleVar(value=1.4)
        tk.Scale(plr2, variable=self._pulse_zoom, from_=1.1, to=3.0,
                 resolution=0.1, orient="horizontal", length=200,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=6)

        # ── Shared options ────────────────────────────────────────────────
        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=4)
        tk.Label(opt_f, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        self._keep_audio = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("zoom.keep_audio_checkbox"), variable=self._keep_audio,
                       font=(UI_FONT, 10)).pack(side="left", padx=20)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        self._btn_run = tk.Button(
            bf, text=t("zoom.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28,
            cursor="hand2", command=self._render)
        self._btn_run.pack()

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_mode()

    def _on_mode(self):
        for f in (self._punch_f, self._kb_f, self._kf_f, self._pulse_f):
            f.pack_forget()
        mode = self._mode_var.get()
        if mode == "punch":
            self._punch_f.pack(fill="x", padx=20, pady=6)
        elif mode == "kenburns":
            self._kb_f.pack(fill="x", padx=20, pady=6)
        elif mode == "keyframe":
            self._kf_f.pack(fill="x", padx=20, pady=6)
        elif mode == "pulse":
            self._pulse_f.pack(fill="x", padx=20, pady=6)

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

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

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
        mode = self._mode_var.get()
        crf = self._crf_var.get()
        W, H = self.vid_w, self.vid_h

        vf = ""

        if mode == "punch":
            try:
                t_start = float(self._punch_start.get())
                t_end = float(self._punch_end.get())
                zoom = self._punch_zoom.get()
                cx_pct = self._punch_x.get() / 100.0
                cy_pct = self._punch_y.get() / 100.0
            except (ValueError, tk.TclError):
                messagebox.showerror(t("zoom.bad_input_title"), t("zoom.bad_input_message"))
                return

            ease = self._ease_var.get()
            # Use zoompan filter with expressions
            # zoompan: z = zoom level, x/y = top-left of crop
            dur_s = t_end - t_start
            fps = 30  # assume 30fps for expression
            total_frames = int(self.duration * fps)
            start_frame = int(t_start * fps)
            end_frame = int(t_end * fps)

            if ease == "snap":
                z_expr = (f"if(between(on,{start_frame},{end_frame}),"
                          f"{zoom},1)")
            elif ease == "linear":
                z_expr = (f"if(lt(on,{start_frame}),1,"
                          f"if(lt(on,{(start_frame+end_frame)//2}),"
                          f"1+({zoom}-1)*(on-{start_frame})/{max(1,(end_frame-start_frame)//2)},"
                          f"if(lt(on,{end_frame}),"
                          f"{zoom}-({zoom}-1)*(on-{(start_frame+end_frame)//2})/{max(1,(end_frame-start_frame)//2)},"
                          f"1)))")
            else:  # smooth
                z_expr = (f"if(between(on,{start_frame},{end_frame}),"
                          f"1+({zoom}-1)*0.5*(1-cos(2*PI*(on-{start_frame})/{max(1,end_frame-start_frame)})),"
                          f"1)")

            cx = int(cx_pct * W)
            cy = int(cy_pct * H)
            x_expr = f"max(0,min({cx}-iw/zoom/2,iw-iw/zoom))"
            y_expr = f"max(0,min({cy}-ih/zoom/2,ih-ih/zoom))"

            vf = (f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
                  f":d={total_frames}:s={W}x{H}:fps={fps}")
            self.log(self.console, f"Punch-in: {zoom}× at ({cx_pct*100:.0f}%,{cy_pct*100:.0f}%) "
                                   f"from {_fmt(t_start)} to {_fmt(t_end)}")

        elif mode == "kenburns":
            direction = self._kb_dir.get()
            intensity = self._kb_intensity.get()
            fps = 30
            total_frames = int(self.duration * fps)

            if direction == "zoom_in":
                z_expr = f"1+({intensity}-1)*on/{total_frames}"
                x_expr = f"iw/2-(iw/zoom/2)"
                y_expr = f"ih/2-(ih/zoom/2)"
            elif direction == "zoom_out":
                z_expr = f"{intensity}-({intensity}-1)*on/{total_frames}"
                x_expr = f"iw/2-(iw/zoom/2)"
                y_expr = f"ih/2-(ih/zoom/2)"
            elif direction == "pan_left":
                z_expr = f"{intensity}"
                x_expr = f"(iw-iw/zoom)*(1-on/{total_frames})"
                y_expr = f"ih/2-(ih/zoom/2)"
            else:  # pan_right
                z_expr = f"{intensity}"
                x_expr = f"(iw-iw/zoom)*on/{total_frames}"
                y_expr = f"ih/2-(ih/zoom/2)"

            vf = (f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
                  f":d={total_frames}:s={W}x{H}:fps={fps}")
            self.log(self.console, f"Ken Burns: {direction} at {intensity:.2f}×")

        elif mode == "keyframe":
            try:
                sx = float(self._kf_sx.get()) / 100
                sy = float(self._kf_sy.get()) / 100
                sz = float(self._kf_sz.get())
                ex = float(self._kf_ex.get()) / 100
                ey = float(self._kf_ey.get()) / 100
                ez = float(self._kf_ez.get())
            except ValueError:
                messagebox.showerror(t("zoom.bad_input_title"), t("zoom.bad_input_message"))
                return

            fps = 30
            total_frames = int(self.duration * fps)
            z_expr = f"{sz}+({ez}-{sz})*on/{total_frames}"
            sx_px, sy_px = int(sx * W), int(sy * H)
            ex_px, ey_px = int(ex * W), int(ey * H)
            x_expr = f"{sx_px}+({ex_px}-{sx_px})*on/{total_frames}"
            y_expr = f"{sy_px}+({ey_px}-{sy_px})*on/{total_frames}"

            vf = (f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
                  f":d={total_frames}:s={W}x{H}:fps={fps}")
            self.log(self.console, f"Keyframe pan: ({sx*100:.0f}%,{sy*100:.0f}%,{sz}×) → "
                                   f"({ex*100:.0f}%,{ey*100:.0f}%,{ez}×)")

        elif mode == "pulse":
            try:
                pt = float(self._pulse_time.get())
                pd = float(self._pulse_dur.get())
                pz = self._pulse_zoom.get()
            except (ValueError, tk.TclError):
                messagebox.showerror(t("zoom.bad_input_title"), t("zoom.bad_input_message"))
                return

            fps = 30
            total_frames = int(self.duration * fps)
            sf = int(pt * fps)
            ef = int((pt + pd) * fps)

            z_expr = (f"if(between(on,{sf},{ef}),"
                      f"1+({pz}-1)*sin(PI*(on-{sf})/{max(1,ef-sf)}),1)")
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

            vf = (f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
                  f":d={total_frames}:s={W}x{H}:fps={fps}")
            self.log(self.console, f"Zoom pulse: {pz}× at {_fmt(pt)} for {pd}s")

        if not vf:
            return

        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast"]

        if self._keep_audio.get():
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]

        cmd += ["-movflags", "+faststart", out, "-y"]

        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label=t("zoom.apply_button"))
