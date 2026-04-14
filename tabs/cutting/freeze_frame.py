"""
tab_freezeframe.py  ─  Freeze Frame Maker

Extract a single frame from a video and hold it for a configurable
duration, then optionally stitch it back into the clip.  Essential for
comedy/reaction content ("record scratch" moments) and dramatic pauses.

Modes
─────
  1. Freeze Insert    - original plays → freeze → original continues
  2. Freeze Extend    - freeze is appended at the end
  3. Freeze Only      - export just the frozen frame as a still video
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT, VideoTimeline
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t


def _fmt(seconds):
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class FreezeFrameTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.freeze_frame"),
                         t("freeze_frame.subtitle"),
                         icon="⏸")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=58, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._dur_lbl.pack(side="left", padx=10)

        # ── Timeline ──────────────────────────────────────────────────────
        tl_lf = tk.LabelFrame(self, text=f"  {t('freeze_frame.timeline_section')}  ", padx=15, pady=10,
                              font=(UI_FONT, 9, "bold"))
        tl_lf.pack(fill="x", padx=20, pady=8)
        self._timeline = VideoTimeline(tl_lf, on_change=self._on_timeline_change,
                                       height=90, show_handles=False)
        self._timeline.pack(fill="x")

        # ── Freeze point ──────────────────────────────────────────────────
        fp_lf = tk.LabelFrame(self, text=f"  {t('freeze_frame.freeze_point_section')}  ", padx=15, pady=10,
                              font=(UI_FONT, 9, "bold"))
        fp_lf.pack(fill="x", padx=20, pady=8)

        r1 = tk.Frame(fp_lf)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text=t("freeze_frame.freeze_at_label"), font=(UI_FONT, 10, "bold"),
                 width=12, anchor="e").pack(side="left")
        self._freeze_time = tk.StringVar(value="0.0")
        tk.Entry(r1, textvariable=self._freeze_time, width=10, relief="flat",
                 font=(MONO_FONT, 11)).pack(side="left", padx=8)
        tk.Label(r1, text="seconds", font=(UI_FONT, 9),
                 fg=CLR["fgdim"]).pack(side="left")

        # Scrubber for picking the freeze point
        r1b = tk.Frame(fp_lf)
        r1b.pack(fill="x", pady=4)
        tk.Label(r1b, text=t("freeze_frame.scrub_label"), font=(UI_FONT, 10), width=12,
                 anchor="e").pack(side="left")
        self._scrub_var = tk.DoubleVar(value=0.0)
        self._scrub = tk.Scale(r1b, variable=self._scrub_var, from_=0, to=100,
                               resolution=0.01, orient="horizontal", length=420,
                               bg=CLR["panel"], fg=CLR["fg"],
                               troughcolor=CLR["bg"], highlightthickness=0,
                               command=self._on_scrub)
        self._scrub.pack(side="left", padx=8)
        tk.Button(r1b, text=t("freeze_frame.set_freeze_button"), bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._set_freeze_from_scrub).pack(side="left", padx=6)
        tk.Button(r1b, text=t("freeze_frame.preview_frame_button"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._preview_frame).pack(side="left", padx=4)

        r2 = tk.Frame(fp_lf)
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("freeze_frame.freeze_duration_label"), font=(UI_FONT, 10, "bold"),
                 width=12, anchor="e").pack(side="left")
        self._freeze_dur = tk.StringVar(value="3.0")
        tk.Entry(r2, textvariable=self._freeze_dur, width=8, relief="flat",
                 font=(MONO_FONT, 11)).pack(side="left", padx=8)
        tk.Label(r2, text="seconds", font=(UI_FONT, 9),
                 fg=CLR["fgdim"]).pack(side="left")

        # Quick duration buttons
        qf = tk.Frame(r2)
        qf.pack(side="left", padx=20)
        for val, lbl in [(0.5, "0.5s"), (1.0, "1s"), (2.0, "2s"),
                          (3.0, "3s"), (5.0, "5s"), (10.0, "10s")]:
            tk.Button(qf, text=lbl, width=4, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9),
                      command=lambda v=val: self._freeze_dur.set(str(v))
                      ).pack(side="left", padx=2)

        # ── Mode ──────────────────────────────────────────────────────────
        mode_lf = tk.LabelFrame(self, text=f"  {t('freeze_frame.freeze_mode_section')}  ", padx=15, pady=8,
                                font=(UI_FONT, 9, "bold"))
        mode_lf.pack(fill="x", padx=20, pady=6)

        self._mode_var = tk.StringVar(value="insert")
        modes = [
            ("insert",  t("freeze_frame.freeze_frame_insert_label"),
             t("freeze_frame.freeze_frame_insert_desc")),
            ("extend",  t("freeze_frame.freeze_frame_at_end_label"),
             t("freeze_frame.freeze_frame_at_end_desc")),
            ("only",    t("freeze_frame.freeze_frame_only_label"),
             t("freeze_frame.freeze_frame_only_desc")),
        ]
        for val, label, desc in modes:
            row = tk.Frame(mode_lf, bg=CLR["bg"])
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, text=label, variable=self._mode_var, value=val,
                           font=(UI_FONT, 10), bg=CLR["bg"]).pack(side="left")
            tk.Label(row, text=desc, fg=CLR["fgdim"], font=(UI_FONT, 9),
                     bg=CLR["bg"]).pack(side="left", padx=(8, 0))

        # ── Options ───────────────────────────────────────────────────────
        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=4)
        tk.Label(opt_f, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        self._silent_freeze = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("freeze_frame.silent_checkbox"),
                       variable=self._silent_freeze,
                       font=(UI_FONT, 10)).pack(side="left", padx=20)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=8)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=58, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        self._btn_run = tk.Button(
            bf, text=t("freeze_frame.create_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28,
            cursor="hand2", command=self._render)
        self._btn_run.pack()

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=6)
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
            self._timeline.set_duration(self.duration)

    def _on_timeline_change(self, start, end, playhead):
        self._freeze_time.set(str(round(playhead, 2)))
        self._scrub_var.set(playhead)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    def _on_scrub(self, val):
        pass

    def _set_freeze_from_scrub(self):
        self._freeze_time.set(str(round(self._scrub_var.get(), 2)))

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

        try:
            ft = float(self._freeze_time.get())
            fd = float(self._freeze_dur.get())
        except ValueError:
            messagebox.showerror(t("freeze_frame.bad_input_title"), t("freeze_frame.bad_input_message"))
            return

        if fd <= 0:
            messagebox.showerror(t("freeze_frame.bad_input_title"), t("freeze_frame.bad_input_message"))
            return

        if mode == "insert":
            # tpad filter: freeze at the specified frame
            # Use trim to split, then tpad to insert freeze
            fps_cmd = [get_binary_path("ffprobe"), "-v", "error",
                       "-select_streams", t("freeze_frame.v_0"),
                       "-show_entries", t("freeze_frame.stream_r_frame_rate"),
                       "-of", t("freeze_frame.csv_p_0"), self.file_path]
            try:
                r = subprocess.run(fps_cmd, capture_output=True, text=True,
                                   creationflags=CREATE_NO_WINDOW, timeout=10)
                num, den = r.stdout.strip().split("/")
                fps = float(num) / float(den)
            except Exception:
                fps = 30.0

            freeze_frames = int(fd * fps)

            # Complex filter: split input, trim before/after freeze point,
            # generate freeze frame, concatenate
            fc = (
                f"[0:v]split=3[pre][freeze_src][post];"
                f"[pre]trim=0:{ft},setpts=PTS-STARTPTS[v_pre];"
                f"[freeze_src]trim={ft}:{ft + 0.05},setpts=PTS-STARTPTS,"
                f"loop=loop={freeze_frames}:size=1:start=0,setpts=PTS-STARTPTS[v_freeze];"
                f"[post]trim={ft}:{self.duration},setpts=PTS-STARTPTS[v_post];"
                f"[v_pre][v_freeze][v_post]concat=n=3:v=1:a=0[vout]"
            )

            cmd = [ffmpeg, "-i", self.file_path,
                   "-filter_complex", fc, "-map", "[vout]", "-an",
                   "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                   "-movflags", "+faststart", out, "-y"]
            self.log(self.console, f"Freeze insert at {_fmt(ft)} for {fd}s ({freeze_frames} frames)")

        elif mode == "extend":
            # tpad to repeat the last frame
            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", f"tpad=stop_mode=clone:stop_duration={fd}",
                   t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                   t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                   "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, f"Freeze extend: hold last frame for {fd}s")

        elif mode == "only":
            # Extract single frame, loop it for fd seconds
            cmd = [ffmpeg, "-ss", str(ft), "-i", self.file_path,
                   "-vframes", "1", "-vf",
                   f"loop=loop={int(fd * 30)}:size=1:start=0,fps=30",
                   t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                   "-t", str(fd), "-an",
                   "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, f"Freeze only: frame at {_fmt(ft)} for {fd}s")

        else:
            return

        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label=t("freeze_frame.create_button"))
