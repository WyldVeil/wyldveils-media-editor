"""
tab_scenedetect.py  ─  Scene Detector & Splitter

Automatically detect scene changes in long footage (livestream VODs,
multi-camera recordings, raw captured footage) and split into
individual clips.  Essential for processing hours-long streams into
highlight compilations.

Uses FFmpeg's scene-detection filter (select='gt(scene,T)') to find
cut points, then splits the video at those timestamps.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import threading
import re

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, CREATE_NO_WINDOW, open_in_explorer,
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


class SceneDetectTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self._scenes = []  # list of float timestamps
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.scene_detector"),
                         t("scene_detect.subtitle"),
                         icon="🎬")

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

        # ── Detection settings ────────────────────────────────────────────
        det_lf = tk.LabelFrame(self, text=f"  {t('scene_detect.detection_settings_section')}  ", padx=15, pady=10,
                               font=(UI_FONT, 9, "bold"))
        det_lf.pack(fill="x", padx=20, pady=8)

        r1 = tk.Frame(det_lf)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text=t("scene_detect.sensitivity_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._thresh_var = tk.DoubleVar(value=0.3)
        self._thresh_scale = tk.Scale(
            r1, variable=self._thresh_var, from_=0.05, to=0.8,
            resolution=0.01, orient="horizontal", length=300,
            bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
            highlightthickness=0)
        self._thresh_scale.pack(side="left", padx=8)
        self._thresh_lbl = tk.Label(r1, text="0.30", fg=CLR["accent"],
                                    font=(MONO_FONT, 11, "bold"), width=5)
        self._thresh_lbl.pack(side="left")
        self._thresh_var.trace_add("write",
            lambda *_: self._thresh_lbl.config(
                text=f"{self._thresh_var.get():.2f}"))

        r1b = tk.Frame(det_lf)
        r1b.pack(fill="x", pady=2)
        tk.Label(r1b, text="", width=10).pack(side="left")
        tk.Label(r1b, text=t("scene_detect.sensitivity_info"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # Presets
        r1c = tk.Frame(det_lf)
        r1c.pack(fill="x", pady=4)
        tk.Label(r1c, text=t("scene_detect.presets_label"), font=(UI_FONT, 10)).pack(side="left")
        for val, lbl in [(0.10, t("scene_detect.preset_very_sensitive")), (0.25, t("scene_detect.preset_sensitive")),
                          (0.35, t("scene_detect.preset_balanced")), (0.50, t("scene_detect.preset_conservative")),
                          (0.70, t("scene_detect.preset_hard_cuts"))]:
            tk.Button(r1c, text=lbl, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9), cursor="hand2",
                      command=lambda v=val: self._thresh_var.set(v)
                      ).pack(side="left", padx=3)

        r2 = tk.Frame(det_lf)
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("scene_detect.min_scene_label"), font=(UI_FONT, 10)).pack(side="left")
        self._min_dur = tk.StringVar(value="2.0")
        tk.Entry(r2, textvariable=self._min_dur, width=6, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        tk.Label(r2, text=t("scene_detect.min_scene_info"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # ── Detect button ─────────────────────────────────────────────────
        self._btn_detect = tk.Button(
            self, text=t("scene_detect.detect_button"), font=(UI_FONT, 11, "bold"),
            bg=CLR["accent"], fg="white", height=2, width=24,
            cursor="hand2", command=self._detect)
        self._btn_detect.pack(pady=8)

        # ── Results ───────────────────────────────────────────────────────
        res_lf = tk.LabelFrame(self, text=f"  {t('scene_detect.detected_section')}  ", padx=15, pady=8,
                               font=(UI_FONT, 9, "bold"))
        res_lf.pack(fill="both", expand=True, padx=20, pady=4)

        self._scene_count_lbl = tk.Label(res_lf, text=t("scene_detect.no_scenes_yet"),
                                         fg=CLR["fgdim"], font=(UI_FONT, 10))
        self._scene_count_lbl.pack(anchor="w")

        # Canvas for scene visualization
        self._scene_canvas = tk.Canvas(res_lf, bg=CLR["console_bg"], height=60,
                                       highlightthickness=0)
        self._scene_canvas.pack(fill="x", pady=6)

        # Listbox of timestamps
        list_f = tk.Frame(res_lf)
        list_f.pack(fill="both", expand=True)
        self._scene_list = tk.Listbox(
            list_f, bg=CLR["console_bg"], fg=CLR["console_fg"],
            font=(MONO_FONT, 9), selectmode="extended", height=6,
            relief="flat", bd=0)
        lsb = ttk.Scrollbar(list_f, command=self._scene_list.yview)
        self._scene_list.config(yscrollcommand=lsb.set)
        self._scene_list.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

        # ── Split options ─────────────────────────────────────────────────
        split_f = tk.Frame(self)
        split_f.pack(fill="x", padx=20, pady=6)

        tk.Label(split_f, text=t("common.output_folder"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_dir_var = tk.StringVar()
        tk.Entry(split_f, textvariable=self._out_dir_var, width=50, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(split_f, text=t("scene_detect.choose"), command=self._browse_out_dir,
                  cursor="hand2", relief="flat", font=(UI_FONT, 9)).pack(side="left")

        split_opt = tk.Frame(self)
        split_opt.pack(fill="x", padx=20, pady=2)
        self._copy_mode = tk.BooleanVar(value=True)
        tk.Checkbutton(split_opt, text=t("scene_detect.stream_copy_checkbox"),
                       variable=self._copy_mode, font=(UI_FONT, 10)).pack(side="left")
        self._prefix_var = tk.StringVar(value="scene_")
        tk.Label(split_opt, text=f"    {t('scene_detect.filename_prefix_label')}", font=(UI_FONT, 10)).pack(side="left")
        tk.Entry(split_opt, textvariable=self._prefix_var, width=12, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)

        self._btn_split = tk.Button(
            self, text=t("scene_detect.split_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28,
            cursor="hand2", command=self._split, state="disabled")
        self._btn_split.pack(pady=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
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

    def _browse_out_dir(self):
        d = filedialog.askdirectory(title="Output folder for split clips")
        if d:
            self._out_dir_var.set(d)

    def _draw_scenes(self):
        c = self._scene_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or self.duration <= 0:
            return

        # Draw timeline bar
        c.create_rectangle(20, 15, w - 20, h - 15, fill=CLR["panel"], outline=CLR["border"])

        # Draw scene boundaries
        bar_l, bar_r = 20, w - 20
        bar_w = bar_r - bar_l

        all_pts = [0.0] + self._scenes + [self.duration]
        colors = [CLR["accent"], CLR["green"], CLR["orange"], CLR["pink"],
                  "#9C27B0", "#00BCD4", "#FF5722", "#8BC34A", "#FFEB3B"]

        for i in range(len(all_pts) - 1):
            x1 = bar_l + (all_pts[i] / self.duration) * bar_w
            x2 = bar_l + (all_pts[i + 1] / self.duration) * bar_w
            color = colors[i % len(colors)]
            c.create_rectangle(x1, 16, x2, h - 16, fill=color, outline="")
            # Label
            mid = (x1 + x2) / 2
            dur_s = all_pts[i + 1] - all_pts[i]
            if x2 - x1 > 30:
                c.create_text(mid, h // 2, text=f"{dur_s:.1f}s",
                              fill="white", font=(UI_FONT, 7, "bold"))

        # Scene cut lines
        for t in self._scenes:
            x = bar_l + (t / self.duration) * bar_w
            c.create_line(x, 10, x, h - 10, fill="white", width=2)

    def _detect(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        thresh = self._thresh_var.get()
        try:
            min_dur = float(self._min_dur.get())
        except ValueError:
            min_dur = 2.0

        self.log(self.console, f"Detecting scenes (threshold={thresh:.2f}, min={min_dur}s)…")
        self._btn_detect.config(state="disabled", text=t("scene_detect.analyzing"))

        def _worker(progress_cb, cancel_fn):
            ffmpeg = get_binary_path("ffmpeg")
            cmd = [
                ffmpeg, "-i", self.file_path,
                "-vf", f"select='gt(scene,{thresh})',showinfo",
                "-vsync", "vfr", "-f", "null", "-"
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)

            timestamps = []
            pattern = re.compile(r"pts_time:([\d.]+)")

            for line in iter(proc.stdout.readline, ""):
                if cancel_fn():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                match = pattern.search(line)
                if match:
                    t = float(match.group(1))
                    timestamps.append(t)
                    progress_cb(f"  Scene change at {_fmt(t)}")

            proc.stdout.close()
            proc.wait()

            # Filter by minimum duration
            filtered = []
            last_t = 0.0
            for t in sorted(timestamps):
                if t - last_t >= min_dur:
                    filtered.append(t)
                    last_t = t

            self._scenes = filtered
            self.after(0, self._update_scene_ui)
            return 0

        self.enqueue_render(
            "Scene Detect",
            worker_fn=_worker,
            on_progress=lambda tid, line: self.log(self.console, line),
        )

    def _update_scene_ui(self):
        self._btn_detect.config(state="normal", text=t("scene_detect.detect_button"))
        count = len(self._scenes)
        self._scene_count_lbl.config(
            text=f"{count} scene{'s' if count != 1 else ''} detected  →  "
                 f"{count + 1} clips",
            fg=CLR["green"] if count > 0 else CLR["orange"])

        self._scene_list.delete(0, "end")
        all_pts = [0.0] + self._scenes + [self.duration]
        for i in range(len(all_pts) - 1):
            dur = all_pts[i + 1] - all_pts[i]
            self._scene_list.insert(
                "end",
                f"  Clip {i + 1:03d}:   {_fmt(all_pts[i])}  →  "
                f"{_fmt(all_pts[i + 1])}   ({_fmt(dur)})")

        if count > 0:
            self._btn_split.config(state="normal")
        self.log(self.console, f"Done: {count} scene changes, {count + 1} clips.")
        self._scene_canvas.after(100, self._draw_scenes)

    def _split(self):
        if not self._scenes:
            messagebox.showwarning(t("scene_detect.no_scenes_title"), t("scene_detect.run_detection_first"))
            return

        out_dir = self._out_dir_var.get().strip()
        if not out_dir:
            out_dir = filedialog.askdirectory(title="Output folder")
        if not out_dir:
            return
        self._out_dir_var.set(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        prefix = self._prefix_var.get().strip() or "scene_"
        copy = self._copy_mode.get()

        all_pts = [0.0] + self._scenes + [self.duration]
        total = len(all_pts) - 1
        self.log(self.console, f"Splitting into {total} clips…")
        self._btn_split.config(state="disabled", text=t("scene_detect.splitting"))

        def _worker(progress_cb, cancel_fn):
            ffmpeg = get_binary_path("ffmpeg")
            ext = os.path.splitext(self.file_path)[1] if copy else ".mp4"
            for i in range(total):
                if cancel_fn():
                    return -1
                ss = all_pts[i]
                to = all_pts[i + 1]
                out = os.path.join(out_dir, f"{prefix}{i + 1:03d}{ext}")

                if copy:
                    cmd = [ffmpeg, "-ss", str(ss), "-to", str(to),
                           "-i", self.file_path,
                           "-c", "copy", "-avoid_negative_ts", "make_zero",
                           out, "-y"]
                else:
                    cmd = [ffmpeg, "-ss", str(ss), "-to", str(to),
                           "-i", self.file_path,
                           t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
                           t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                           "-movflags", t("dynamics.faststart"), out, "-y"]

                progress_cb(f"  [{i + 1}/{total}] {_fmt(ss)} → {_fmt(to)}")
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, creationflags=CREATE_NO_WINDOW)
                proc.communicate()

            progress_cb(f"✅  All {total} clips saved to: {out_dir}")
            self.after(0, lambda: open_in_explorer(out_dir))
            return 0

        def _on_complete(tid, rc):
            self._btn_split.config(state="normal", text=t("scene_detect.split_button"))
            if rc == 0:
                self.log(self.console, f"✅  Done. {total} clips saved to: {out_dir}")

        self.enqueue_render(
            "Scene Split",
            output_path=out_dir,
            worker_fn=_worker,
            on_progress=lambda tid, line: self.log(self.console, line),
            on_complete=_on_complete,
        )
