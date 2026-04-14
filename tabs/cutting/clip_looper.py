"""
tab_cliplooper.py  ─  Clip Looper

Loop a video section N times for comedic emphasis, beat drops,
or "wait for it" moments.  Options for:
  • Simple repeat (exact loop)
  • Stutter loop (rapid short repeats for emphasis/comedy)
  • Speed ramp loop (each iteration faster than the last)
  • Echo loop (each repeat fades in volume/opacity)
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile

from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    return f"{int(m):02d}:{s:05.2f}"


class ClipLooperTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.clip_looper"),
                         t("clip_looper.subtitle"),
                         icon="🔁")

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

        # ── Timeline ──────────────────────────────────────────────────────
        tl_lf = tk.LabelFrame(self, text=f"  {t('clip_looper.timeline_section')}  ",
                               padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        tl_lf.pack(fill="x", padx=20, pady=8)
        self._timeline = VideoTimeline(tl_lf, on_change=self._on_timeline_change,
                                       height=90, show_handles=True)
        self._timeline.pack(fill="x")

        # ── Loop range ────────────────────────────────────────────────────
        range_lf = tk.LabelFrame(self, text=f"  {t('clip_looper.loop_range_section')}  ", padx=15, pady=10,
                                 font=(UI_FONT, 9, "bold"))
        range_lf.pack(fill="x", padx=20, pady=8)

        rr1 = tk.Frame(range_lf)
        rr1.pack(fill="x", pady=3)
        tk.Label(rr1, text=t("clip_looper.loop_from_label"), font=(UI_FONT, 10, "bold"),
                 width=12, anchor="e").pack(side="left")
        self._loop_start = tk.StringVar(value="0.0")
        tk.Entry(rr1, textvariable=self._loop_start, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(rr1, text=t("clip_looper.to_label"), font=(UI_FONT, 10, "bold")).pack(side="left", padx=(12, 0))
        self._loop_end = tk.StringVar(value="2.0")
        tk.Entry(rr1, textvariable=self._loop_end, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(rr1, text="seconds", fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        rr2 = tk.Frame(range_lf)
        rr2.pack(fill="x", pady=3)
        self._loop_whole = tk.BooleanVar(value=False)
        tk.Checkbutton(rr2, text=t("clip_looper.loop_entire_checkbox"),
                       variable=self._loop_whole, font=(UI_FONT, 10),
                       command=self._on_whole_toggle).pack(side="left")

        # ── Loop mode ─────────────────────────────────────────────────────
        mode_lf = tk.LabelFrame(self, text=f"  {t('clip_looper.loop_mode_section')}  ", padx=15, pady=10,
                                font=(UI_FONT, 9, "bold"))
        mode_lf.pack(fill="x", padx=20, pady=6)

        self._mode_var = tk.StringVar(value="simple")
        modes = [
            ("simple",   t("clip_looper.simple_repeat_label"),
             t("clip_looper.simple_repeat_desc")),
            ("stutter",  t("clip_looper.stutter_label"),
             t("clip_looper.stutter_desc")),
            ("accel",    t("clip_looper.accelerating_label"),
             t("clip_looper.accelerating_desc")),
            ("echo",     t("clip_looper.echo_fade_label"),
             t("clip_looper.echo_fade_desc")),
        ]
        for val, label, desc in modes:
            row = tk.Frame(mode_lf, bg=CLR["bg"])
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, text=label, variable=self._mode_var, value=val,
                           font=(UI_FONT, 10), bg=CLR["bg"],
                           command=self._on_mode).pack(side="left")
            tk.Label(row, text=desc, fg=CLR["fgdim"], font=(UI_FONT, 9),
                     bg=CLR["bg"]).pack(side="left", padx=(8, 0))

        # ── Settings frame ────────────────────────────────────────────────
        self._settings_f = tk.LabelFrame(self, text=f"  {t('clip_looper.loop_settings_section')}  ",
                                         padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        self._settings_f.pack(fill="x", padx=20, pady=6)

        sr1 = tk.Frame(self._settings_f)
        sr1.pack(fill="x", pady=3)
        tk.Label(sr1, text=t("clip_looper.number_of_loops_label"), font=(UI_FONT, 10, "bold"),
                 width=16, anchor="e").pack(side="left")
        self._loop_count = tk.IntVar(value=3)
        self._loop_spin = tk.Spinbox(sr1, from_=2, to=50,
                                     textvariable=self._loop_count, width=5,
                                     font=(UI_FONT, 11))
        self._loop_spin.pack(side="left", padx=8)

        # Quick loop presets
        qlf = tk.Frame(sr1)
        qlf.pack(side="left", padx=12)
        for val, lbl in [(2, "×2"), (3, "×3"), (5, "×5"),
                          (8, "×8"), (10, "×10"), (20, "×20")]:
            tk.Button(qlf, text=lbl, width=4, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9), cursor="hand2",
                      command=lambda v=val: self._loop_count.set(v)
                      ).pack(side="left", padx=2)

        # Stutter-specific: segment duration
        self._stutter_f = tk.Frame(self._settings_f)
        sr2 = tk.Frame(self._stutter_f)
        sr2.pack(fill="x", pady=3)
        tk.Label(sr2, text=t("clip_looper.stutter_slice_label"), font=(UI_FONT, 10),
                 width=16, anchor="e").pack(side="left")
        self._stutter_dur = tk.StringVar(value="0.15")
        tk.Entry(sr2, textvariable=self._stutter_dur, width=8, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(sr2, text=t("clip_looper.stutter_duration_info"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # Accel-specific: speed multiplier per iteration
        self._accel_f = tk.Frame(self._settings_f)
        ar1 = tk.Frame(self._accel_f)
        ar1.pack(fill="x", pady=3)
        tk.Label(ar1, text=t("clip_looper.speed_up_label"), font=(UI_FONT, 10),
                 width=16, anchor="e").pack(side="left")
        self._accel_factor = tk.DoubleVar(value=1.3)
        tk.Scale(ar1, variable=self._accel_factor, from_=1.05, to=3.0,
                 resolution=0.05, orient="horizontal", length=200,
                 bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
                 highlightthickness=0).pack(side="left", padx=8)
        tk.Label(ar1, text=t("clip_looper.speed_factor_info"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # ── Context: keep surrounding video ───────────────────────────────
        ctx_lf = tk.LabelFrame(self, text=f"  {t('clip_looper.context_section')}  ", padx=15, pady=8,
                               font=(UI_FONT, 9, "bold"))
        ctx_lf.pack(fill="x", padx=20, pady=6)

        self._keep_context = tk.BooleanVar(value=True)
        tk.Checkbutton(ctx_lf, text=t("clip_looper.keep_context_checkbox"),
                       variable=self._keep_context,
                       font=(UI_FONT, 10)).pack(side="left")

        # ── Options ───────────────────────────────────────────────────────
        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=4)
        tk.Label(opt_f, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        self._btn_run = tk.Button(
            bf, text="🔁  " + t("tab.clip_looper"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
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
        self._stutter_f.pack_forget()
        self._accel_f.pack_forget()
        mode = self._mode_var.get()
        if mode == "stutter":
            self._stutter_f.pack(fill="x", pady=2)
        elif mode == "accel":
            self._accel_f.pack(fill="x", pady=2)

    def _on_timeline_change(self, start, end, playhead):
        """Called when the user drags the timeline handles."""
        self._loop_start.set(str(round(start, 2)))
        self._loop_end.set(str(round(end, 2)))

    def _on_whole_toggle(self):
        pass  # UI only; logic in render

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self._src_var.set(p)
            self.duration = get_video_duration(p)
            self._dur_lbl.config(text=_fmt(self.duration))
            self._timeline.set_duration(self.duration)
            loop_end = round(min(2.0, self.duration), 2)
            self._loop_end.set(str(loop_end))
            self._timeline.set_range(0.0, loop_end)

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

        mode = self._mode_var.get()
        loops = self._loop_count.get()
        crf = self._crf_var.get()
        ffmpeg = get_binary_path("ffmpeg")

        if self._loop_whole.get():
            ss, ee = 0.0, self.duration
        else:
            try:
                ss = float(self._loop_start.get())
                ee = float(self._loop_end.get())
            except ValueError:
                messagebox.showerror(t("clip_looper.bad_range_title"), t("clip_looper.bad_range_message"))
                return
        if ee <= ss:
            messagebox.showerror(t("clip_looper.bad_range_title"), t("clip_looper.bad_range_order"))
            return

        self._btn_run.config(state="disabled", text=t("app.status.queued_btn"))
        self.log(self.console, f"Looping {_fmt(ss)}→{_fmt(ee)} × {loops} ({mode})…")

        def _worker(progress_cb, cancel_fn):
            tmp_dir = tempfile.mkdtemp(prefix="xfpro_loop_")
            segment_dur = ee - ss
            parts = []

            # Part 1: before the loop (if keeping context)
            if self._keep_context.get() and ss > 0.1 and not self._loop_whole.get():
                if cancel_fn():
                    return -1
                pre = os.path.join(tmp_dir, "pre.mp4")
                cmd = [ffmpeg, "-i", self.file_path, "-t", str(ss),
                       t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                       t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", pre, "-y"]
                subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
                if os.path.exists(pre):
                    parts.append(pre)

            # Part 2: the loop segment(s)
            for i in range(loops):
                seg_out = os.path.join(tmp_dir, f"loop_{i:03d}.mp4")

                if mode == "simple":
                    cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                           "-t", str(segment_dur),
                           t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", seg_out, "-y"]

                elif mode == "stutter":
                    try:
                        stut_dur = float(self._stutter_dur.get())
                    except ValueError:
                        stut_dur = 0.15
                    # Each stutter is a tiny slice from the start of the range
                    cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                           "-t", str(stut_dur),
                           t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", seg_out, "-y"]

                elif mode == "accel":
                    factor = self._accel_factor.get()
                    speed = factor ** i
                    pts_mult = 1.0 / speed
                    # Build atempo chain
                    remaining = speed
                    atempo_chain = []
                    while remaining > 2.0:
                        atempo_chain.append("atempo=2.0")
                        remaining /= 2.0
                    while remaining < 0.5:
                        atempo_chain.append("atempo=0.5")
                        remaining *= 2.0
                    atempo_chain.append(f"atempo={remaining:.4f}")
                    af = ",".join(atempo_chain)

                    cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                           "-t", str(segment_dur),
                           "-vf", f"setpts={pts_mult:.4f}*PTS",
                           "-af", af,
                           t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", seg_out, "-y"]

                elif mode == "echo":
                    # Reduce volume progressively
                    vol_db = -3 * i  # -3dB per iteration
                    cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                           "-t", str(segment_dur),
                           "-af", f"volume={vol_db}dB",
                           t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", seg_out, "-y"]
                else:
                    cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                           "-t", str(segment_dur),
                           t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", seg_out, "-y"]

                if cancel_fn():
                    return -1
                self.log(self.console, f"  Loop {i + 1}/{loops}")
                subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
                if os.path.exists(seg_out):
                    parts.append(seg_out)

            # Part 3: after the loop (if keeping context)
            if (self._keep_context.get() and ee < self.duration - 0.1
                    and not self._loop_whole.get()):
                if cancel_fn():
                    return -1
                post = os.path.join(tmp_dir, "post.mp4")
                cmd = [ffmpeg, "-ss", str(ee), "-i", self.file_path,
                       t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                       t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", post, "-y"]
                subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
                if os.path.exists(post):
                    parts.append(post)

            # Concat
            list_file = os.path.join(tmp_dir, "concat.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for p in parts:
                    f.write(f"file '{p}'\n")

            cmd = [ffmpeg, "-f", "concat", "-safe", "0",
                   "-i", list_file,
                   t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                   t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                   "-movflags", t("dynamics.faststart"), out, "-y"]
            progress_cb("Concatenating all parts…")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    creationflags=CREATE_NO_WINDOW)
            for line in iter(proc.stdout.readline, ""):
                if cancel_fn():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                progress_cb(line.rstrip())
            proc.stdout.close()
            proc.wait()
            final_rc = proc.returncode

            # Cleanup
            for p in parts:
                try:
                    os.remove(p)
                except Exception:
                    pass
            try:
                os.remove(list_file)
                os.rmdir(tmp_dir)
            except Exception:
                pass

            return final_rc

        def _on_start(tid):
            self._btn_run.config(text=t("app.status.processing_btn"))

        def _on_progress(tid, line):
            self.log(self.console, line)

        def _on_complete(tid, rc):
            self._btn_run.config(state="normal", text=t("clip_looper.create_button"))
            self.show_result(rc, out)

        self.enqueue_render(
            "Clip Looper",
            output_path=out,
            worker_fn=_worker,
            on_start=_on_start,
            on_progress=_on_progress,
            on_complete=_on_complete,
        )
