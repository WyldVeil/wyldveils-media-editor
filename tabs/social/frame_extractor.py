"""
tab_frameextractor.py  ─  Thumbnail & Frame Extractor
Extract still frames from video for YouTube thumbnails, storyboards,
contact sheets, or editorial review.

Modes:
  1. Single frame  - extract one specific frame at a timestamp
  2. Range of frames - extract every Nth frame in a time range
  3. Scene changes - extract first frame of each scene (via scdet filter)
  4. Contact sheet - montage of N evenly-spaced frames as one image (tile filter)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import math
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


IMAGE_FORMATS = {
    t("frame_extractor.png_lossless_best_quality"):   "png",
    t("frame_extractor.jpeg_smaller_files"):             "jpg",
    t("frame_extractor.webp_modern_great_compression"): "webp",
    t("frame_extractor.bmp_uncompressed"):              "bmp",
}


class FrameExtractorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._duration = 0.0
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🖼  " + t("tab.frame_extractor"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("frame_extractor.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # ── Mode notebook ─────────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=6)

        self._build_single_tab(nb)
        self._build_range_tab(nb)
        self._build_scene_tab(nb)
        self._build_contact_sheet_tab(nb)

        # ── Common: image format, output folder ──────────────────────────
        bottom = tk.LabelFrame(self, text=t("section.output_settings"), padx=14, pady=8)
        bottom.pack(fill="x", padx=16, pady=4)

        b_row = tk.Frame(bottom); b_row.pack(fill="x")
        tk.Label(b_row, text=t("common.format"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.fmt_var = tk.StringVar(value=list(IMAGE_FORMATS.keys())[0])
        ttk.Combobox(b_row, textvariable=self.fmt_var,
                     values=list(IMAGE_FORMATS.keys()),
                     state="readonly", width=34).pack(side="left", padx=8)

        tk.Label(b_row, text=t("frame_extractor.quality_jpeg_webp_1_100"),
                 fg=CLR["fgdim"]).pack(side="left")
        self.quality_var = tk.StringVar(value="95")
        tk.Entry(b_row, textvariable=self.quality_var, width=4, relief="flat").pack(side="left", padx=4)

        b_row2 = tk.Frame(bottom); b_row2.pack(fill="x", pady=4)
        tk.Label(b_row2, text=t("common.output_folder")).pack(side="left")
        self.out_dir_var = tk.StringVar()
        tk.Entry(b_row2, textvariable=self.out_dir_var, width=55, relief="flat").pack(side="left", padx=6)
        tk.Button(b_row2, text=t("btn.browse"), command=self._browse_dir, cursor="hand2", relief="flat").pack(side="left")
        tk.Label(b_row2, text=t("frame_extractor.blank_next_to_source_video"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left", padx=6)

        # Run button
        self.btn_render = tk.Button(
            self, text=t("frame_extractor.extract_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["accent"], fg="black",
            height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        self.status_lbl = tk.Label(self, text="", fg=CLR["fgdim"])
        self.status_lbl.pack()

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Mode tabs ─────────────────────────────────────────────────────────
    def _build_single_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("frame_extractor.single_frame"))

        tk.Label(f, text=t("frame_extractor.extract_one_frame_at_a_specific_timestamp"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=14, pady=8)

        row = tk.Frame(f); row.pack(padx=14, pady=6)
        tk.Label(row, text=t("frame_extractor.timestamp_label"),
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        self.single_ts_var = tk.StringVar(value="0")
        tk.Entry(row, textvariable=self.single_ts_var, width=14,
                 font=(UI_FONT, 13)).pack(side="left", padx=8)

        # Quick timestamp buttons
        quick_row = tk.Frame(f); quick_row.pack(padx=14, anchor="w")
        tk.Label(quick_row, text=t("frame_extractor.quick")).pack(side="left")
        for pct, label in [(0, "0%"), (10, "10%"), (25, "25%"),
                            (50, "50%"), (75, "75%"), (90, "90%"), (100, "100%")]:
            tk.Button(quick_row, text=label, width=5, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 8),
                      command=lambda p=pct: self._set_pct(p)
                      ).pack(side="left", padx=2, pady=6)

        tk.Label(f,
                 text=t("frame_extractor.output_one_image_file_use_timestamp_in_filename"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(anchor="w", padx=14)
        self._mode_tab = f   # track current
        self._nb = nb

    def _build_range_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("frame_extractor.frame_range"))

        tk.Label(f, text=t("frame_extractor.extract_every_nth_frame_across_a_time_range"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=14, pady=8)

        r0 = tk.Frame(f); r0.pack(padx=14, pady=4)
        tk.Label(r0, text=t("common.start_s")).pack(side="left")
        self.range_start_var = tk.StringVar(value="0")
        tk.Entry(r0, textvariable=self.range_start_var, width=8, relief="flat").pack(side="left", padx=4)
        tk.Label(r0, text=t("frame_extractor.end_s_0_full")).pack(side="left")
        self.range_end_var = tk.StringVar(value="0")
        tk.Entry(r0, textvariable=self.range_end_var, width=8, relief="flat").pack(side="left", padx=4)

        r1 = tk.Frame(f); r1.pack(padx=14, pady=4)
        tk.Label(r1, text=t("frame_extractor.extract_fps_label")).pack(side="left")
        self.range_fps_var = tk.StringVar(value="1")
        ttk.Combobox(r1, textvariable=self.range_fps_var,
                     values=["0.1", "0.25", "0.5", "1", "2", "5", "10",
                              "24", "25", "30"],
                     width=6).pack(side="left", padx=6)
        tk.Label(r1, text=t("frame_extractor.fps_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        r2 = tk.Frame(f); r2.pack(padx=14, pady=4)
        tk.Label(r2, text=t("frame_extractor.max_frames_label")).pack(side="left")
        self.range_max_var = tk.StringVar(value="0")
        tk.Entry(r2, textvariable=self.range_max_var, width=6, relief="flat").pack(side="left", padx=4)

        tk.Label(f,
                 text="Output: numbered image sequence  (frame_000001.png etc.)",
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(anchor="w", padx=14, pady=4)

    def _build_scene_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("frame_extractor.scene_detect"))

        tk.Label(f,
                 text=t("frame_extractor.extract_the_first_frame_of_each_new_scene_auto_s"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=14, pady=8)

        r0 = tk.Frame(f); r0.pack(padx=14, pady=6)
        tk.Label(r0, text=t("frame_extractor.scene_threshold_label"),
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        self.scene_thresh_var = tk.DoubleVar(value=0.3)
        tk.Scale(r0, variable=self.scene_thresh_var, from_=0.05, to=1.0,
                 resolution=0.05, orient="horizontal", length=240).pack(side="left", padx=8)
        self.scene_thresh_lbl = tk.Label(r0, text="0.30", width=5, fg=CLR["accent"])
        self.scene_thresh_lbl.pack(side="left")
        self.scene_thresh_var.trace_add("write", lambda *_:
            self.scene_thresh_lbl.config(text=f"{self.scene_thresh_var.get():.2f}"))

        tk.Label(f,
                 text=("Lower = more sensitive (more frames extracted).\n"
                       "0.3 is a good starting point for most footage."),
                 fg=CLR["fgdim"], font=(UI_FONT, 9), justify="left").pack(
            anchor="w", padx=14, pady=4)

        r1 = tk.Frame(f); r1.pack(padx=14, pady=4)
        tk.Label(r1, text=t("frame_extractor.min_scene_label")).pack(side="left")
        self.scene_min_var = tk.StringVar(value="2")
        tk.Entry(r1, textvariable=self.scene_min_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=t("frame_extractor.ignore_scene_changes_shorter_than_this"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

    def _build_contact_sheet_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("frame_extractor.contact_sheet"))

        tk.Label(f,
                 text=t("frame_extractor.create_a_single_image_grid_of_evenly_spaced_fram"),
                 fg=CLR["fgdim"], wraplength=640).pack(anchor="w", padx=14, pady=8)

        r0 = tk.Frame(f); r0.pack(padx=14, pady=4)
        tk.Label(r0, text=t("frame_extractor.columns_label")).pack(side="left")
        self.cs_cols_var = tk.StringVar(value="5")
        tk.Entry(r0, textvariable=self.cs_cols_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(r0, text=f"  {t('frame_extractor.rows_label')}").pack(side="left")
        self.cs_rows_var = tk.StringVar(value="4")
        tk.Entry(r0, textvariable=self.cs_rows_var, width=4, relief="flat").pack(side="left", padx=4)

        r1 = tk.Frame(f); r1.pack(padx=14, pady=4)
        tk.Label(r1, text=t("frame_extractor.frame_width_label")).pack(side="left")
        self.cs_fw_var = tk.StringVar(value="320")
        ttk.Combobox(r1, textvariable=self.cs_fw_var,
                     values=["160","240","320","480","640"],
                     state="normal", width=6).pack(side="left", padx=4)
        tk.Label(r1, text=f"  {t('frame_extractor.padding_label')}").pack(side="left")
        self.cs_pad_var = tk.StringVar(value="4")
        tk.Entry(r1, textvariable=self.cs_pad_var, width=4, relief="flat").pack(side="left", padx=4)

        r2 = tk.Frame(f); r2.pack(padx=14, pady=4)
        self.cs_ts_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text=t("frame_extractor.timestamp_checkbox"),
                       variable=self.cs_ts_var).pack(side="left")

        tk.Label(f,
                 text="Output: one large image file  (contact_sheet.jpg etc.)",
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(anchor="w", padx=14, pady=4)

    # ─────────────────────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self._duration = get_video_duration(p)
            m, s = divmod(int(self._duration), 60)
            self.dur_lbl.config(text=f"{m}m {s}s")

    def _browse_dir(self):
        p = filedialog.askdirectory()
        if p: self.out_dir_var.set(p)

    def _set_pct(self, pct):
        ts = self._duration * pct / 100
        self.single_ts_var.set(f"{ts:.3f}")

    def _get_out_dir(self):
        d = self.out_dir_var.get().strip()
        if not d and self.file_path:
            d = os.path.dirname(self.file_path)
        return d or "."

    def _get_ext(self):
        fmt_label = self.fmt_var.get()
        return IMAGE_FORMATS.get(fmt_label, "png")

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("frame_extractor.no_file_message"))
            return

        mode = self._nb.index(self._nb.select())
        # 0=single, 1=range, 2=scene, 3=contact sheet
        if mode == 0:
            self._extract_single()
        elif mode == 1:
            self._extract_range()
        elif mode == 2:
            self._extract_scenes()
        else:
            self._extract_contact_sheet()

    def _extract_single(self):
        ts  = self.single_ts_var.get()
        ext = self._get_ext()
        out_dir = self._get_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        safe_ts = ts.replace(":", "-").replace(".", "_")
        out = os.path.join(out_dir, f"frame_{safe_ts}.{ext}")

        ffmpeg = get_binary_path("ffmpeg.exe")
        q_args = [t("frame_extractor.q_v"), self.quality_var.get()] if ext in ("jpg","webp") else []
        cmd = [ffmpeg, "-ss", ts, "-i", self.file_path,
               t("smart_reframe.frames_v"), "1"] + q_args + [out, "-y"]

        self.log(self.console, f"Extracting frame at {ts}s…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: (self.show_result(rc, out)
                                            if rc == 0
                                            else self.show_result(rc)),
                        btn=self.btn_render, btn_label=t("frame_extractor.extract_button"))

    def _extract_range(self):
        fps    = self.range_fps_var.get()
        start  = self.range_start_var.get()
        end    = self.range_end_var.get()
        maxf   = self.range_max_var.get()
        ext    = self._get_ext()
        out_dir= self._get_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        out_pat = os.path.join(out_dir, f"frame_%06d.{ext}")

        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg]
        if start and start != "0":
            cmd += ["-ss", start]
        if end and end != "0":
            cmd += ["-t", str(float(end) - float(start or 0))]
        cmd += ["-i", self.file_path, "-vf", f"fps={fps}"]
        if maxf and maxf != "0":
            cmd += ["-frames:v", maxf]
        q_args = [t("frame_extractor.q_v"), self.quality_var.get()] if ext in ("jpg","webp") else []
        cmd += q_args + [out_pat, "-y"]

        self.log(self.console, f"Extracting {fps} fps frames…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out_dir),
                        btn=self.btn_render, btn_label=t("frame_extractor.extract_button"))

    def _extract_scenes(self):
        thresh  = self.scene_thresh_var.get()
        min_len = self.scene_min_var.get()
        ext     = self._get_ext()
        out_dir = self._get_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        out_pat = os.path.join(out_dir, f"scene_%04d.{ext}")

        ffmpeg = get_binary_path("ffmpeg.exe")
        vf = (f"select='gt(scene,{thresh:.2f})',setpts=N/FRAME_RATE/TB")
        cmd = [ffmpeg, "-i", self.file_path,
               "-vf", vf, "-vsync", "vfr",
               t("smart_reframe.frames_v"), "999", out_pat, "-y"]

        self.log(self.console, f"Detecting scenes (threshold={thresh:.2f})…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out_dir),
                        btn=self.btn_render, btn_label=t("frame_extractor.extract_button"))

    def _extract_contact_sheet(self):
        try:
            cols = int(self.cs_cols_var.get())
            rows = int(self.cs_rows_var.get())
            fw   = int(self.cs_fw_var.get())
            pad  = int(self.cs_pad_var.get())
        except ValueError:
            messagebox.showerror(t("common.error"), "Enter valid numbers for grid settings.")
            return

        total   = cols * rows
        ext     = self._get_ext()
        out_dir = self._get_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"contact_sheet.{ext}")

        ffmpeg = get_binary_path("ffmpeg.exe")
        # Select evenly spaced frames
        dur     = self._duration or 60
        fps_val = total / dur   # take exactly `total` frames from whole video
        ts_var  = "on" if self.cs_ts_var.get() else ""

        ts_filter = (
            f",drawtext=text='%{{pts\\:hms}}':fontsize=14:"
            f"fontcolor=white:box=1:boxcolor=black@0.5:"
            f"x=(w-text_w)/2:y=h-20"
        ) if self.cs_ts_var.get() else ""

        vf = (f"fps={fps_val:.4f},"
              f"scale={fw}:-1{ts_filter},"
              f"tile={cols}x{rows}:padding={pad}:margin={pad}")

        q_args = [t("frame_extractor.q_v"), self.quality_var.get()] if ext in ("jpg","webp") else []
        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("smart_reframe.frames_v"), "1"] + q_args + [out, "-y"]

        self.log(self.console, f"Building {cols}×{rows} contact sheet ({total} frames)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("frame_extractor.extract_button"))
