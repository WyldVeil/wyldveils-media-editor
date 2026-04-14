"""
tab_speedramper.py  ─  Speed Ramper
Apply speed ramps to video: constant speed change, gradual ramp,
or multi-point custom curve. Uses pts filter + setpts.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import tempfile
import subprocess
from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


class SpeedRamperTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration  = 0.0
        self.ramp_points = []   # list of {time_var, speed_var, row}
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="⚡  " + t("tab.speed_ramper"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("speed_ramp.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=55, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # Timeline
        tl_lf = tk.LabelFrame(self, text=f"  {t('speed_ramp.timeline_section')}  ", padx=15, pady=8)
        tl_lf.pack(fill="x", padx=20, pady=6)
        self._timeline = VideoTimeline(tl_lf, on_change=lambda pos: None,
                                       height=80, show_handles=False)
        self._timeline.pack(fill="x")

        # Mode
        mode_lf = tk.LabelFrame(self, text=f"  {t('speed_ramp.speed_mode_section')}  ", padx=15, pady=8)
        mode_lf.pack(fill="x", padx=20, pady=6)

        self.mode_var = tk.StringVar(value=t("speed_ramp.constant_option"))
        for m in [t("speed_ramp.constant_option"), t("speed_ramp.multipoint_option")]:
            tk.Radiobutton(mode_lf, text=m, variable=self.mode_var,
                           value=m, command=self._on_mode).pack(side="left", padx=20)

        # ── Constant speed frame ──────────────────────────────────────────────
        self.const_f = tk.Frame(self)
        self.const_f.pack(fill="x", padx=20, pady=4)
        tk.Label(self.const_f, text=t("speed_ramp.speed_multiplier_label"), font=(UI_FONT, 11, "bold")).pack(side="left")
        self.speed_var = tk.DoubleVar(value=1.0)
        tk.Scale(self.const_f, variable=self.speed_var, from_=0.1, to=10.0,
                 resolution=0.05, orient="horizontal", length=300).pack(side="left", padx=8)
        self.speed_lbl = tk.Label(self.const_f, text="1.0×", width=6,
                                   fg=CLR["accent"], font=(UI_FONT, 12))
        self.speed_lbl.pack(side="left")
        self.speed_var.trace_add("write",
            lambda *_: self.speed_lbl.config(text=f"{self.speed_var.get():.2f}×"))

        quick_f = tk.Frame(self.const_f)
        quick_f.pack(side="left", padx=20)
        for val, lbl in [(0.25, "¼×"), (0.5, "½×"), (1.0, "1×"),
                          (1.5, "1.5×"), (2.0, "2×"), (4.0, "4×"), (8.0, "8×")]:
            tk.Button(quick_f, text=lbl, width=5, bg=CLR["panel"], fg=CLR["fg"],
                      command=lambda v=val: self.speed_var.set(v)).pack(side="left", padx=2)

        # ── Ramp points frame ─────────────────────────────────────────────────
        self.ramp_f = tk.LabelFrame(self, text=f"  {t('speed_ramp.ramp_points_section')}  ", padx=10, pady=8)
        # Cols header
        hdr_r = tk.Frame(self.ramp_f); hdr_r.pack(fill="x")
        
        # FIX: Changed loop variable from 't' to 'col_text' to prevent overwriting the i18n 't' function!
        for col_text, w in [("#", 3), (t("speed_ramp.time_col"), 12), (t("speed_ramp.speed_col"), 12), ("", 8)]:
            tk.Label(hdr_r, text=col_text, width=w, anchor="w").pack(side="left", padx=2)

        self.ramp_rows_f = tk.Frame(self.ramp_f)
        self.ramp_rows_f.pack(fill="x")

        btn_row2 = tk.Frame(self.ramp_f)
        btn_row2.pack(anchor="w", pady=4)
        tk.Button(btn_row2, text=t("speed_ramp.add_point_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._add_ramp).pack(side="left", padx=4)
        tk.Button(btn_row2, text=t("speed_ramp.remove_last_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._remove_ramp).pack(side="left", padx=4)

        # Options
        opt_f = tk.Frame(self); opt_f.pack(pady=4)
        self.pitch_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("speed_ramp.pitch_correction_checkbox"),
                       variable=self.pitch_var).pack(side="left", padx=8)
        tk.Label(opt_f, text=t("rotate_flip.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("speed_ramp.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # Seed two ramp points
        self._add_ramp()
        self._add_ramp()
        self._on_mode()

    def _on_mode(self):
        if self.mode_var.get() == t("speed_ramp.constant_option"):
            self.const_f.pack(fill="x", padx=20, pady=4)
            self.ramp_f.pack_forget()
        else:
            self.const_f.pack_forget()
            self.ramp_f.pack(fill="x", padx=20, pady=6)

    def _add_ramp(self):
        idx = len(self.ramp_points)
        row = tk.Frame(self.ramp_rows_f, relief="groove", bd=1)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=str(idx+1), width=3).pack(side="left")
        tv = tk.StringVar(value=str(idx * 5))
        sv = tk.StringVar(value="1.0")
        tk.Entry(row, textvariable=tv, width=10, relief="flat").pack(side="left", padx=4)
        tk.Entry(row, textvariable=sv, width=10, relief="flat").pack(side="left", padx=4)
        self.ramp_points.append({"time": tv, "speed": sv, "row": row})

    def _remove_ramp(self):
        if self.ramp_points:
            p = self.ramp_points.pop()
            p["row"].destroy()

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self.duration = get_video_duration(p)
            self._timeline.set_duration(self.duration)
            m, s = divmod(int(self.duration), 60)
            self.dur_lbl.config(text=f"{m}m {s}s")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)
        ffmpeg = get_binary_path("ffmpeg.exe")
        mode = self.mode_var.get()

        if mode == t("speed_ramp.constant_option"):
            speed = self.speed_var.get()
            pts_mult = 1.0 / speed
            vf = f"setpts={pts_mult:.4f}*PTS"
            if self.pitch_var.get():
                # atempo supports 0.5–2.0 range; chain for extreme values
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
                cmd = [ffmpeg, "-i", self.file_path,
                       "-vf", vf, "-af", af,
                       t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                       "-preset", "fast", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                       "-movflags", t("dynamics.faststart"), out, "-y"]
            else:
                cmd = [ffmpeg, "-i", self.file_path,
                       "-vf", vf, "-an",
                       t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                       "-preset", "fast", "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, f"Speed: {speed:.2f}× ({pts_mult:.4f}×PTS)")
            
            self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                            btn=self.btn_render, btn_label=t("speed_ramp.apply_button"))
        else:
            # Multi-point: build trim+setpts segments and concat
            try:
                pts = [(float(p["time"].get()), float(p["speed"].get()))
                       for p in self.ramp_points]
                pts.sort(key=lambda x: x[0])
            except ValueError:
                messagebox.showerror(t("speed_ramp.bad_input_title"), t("speed_ramp.bad_input_message"))
                return

            if len(pts) < 2:
                messagebox.showerror(t("speed_ramp.too_few_title"),
                                     t("speed_ramp.too_few_message"))
                return

            # Validate times are within video duration
            dur = self.duration
            for t_val, s in pts:
                if dur > 0 and (t_val < 0 or t_val > dur):
                    messagebox.showerror(t("common.error"),
                                         f"Time {t_val}s is outside video duration {dur:.1f}s")
                    return
                if s <= 0:
                    messagebox.showerror(t("common.error"),
                                         f"Speed {s}× must be greater than 0")
                    return

            # Build a filter_complex that trims each segment and applies per-segment speed,
            # then concatenates all segments.
            tmp_dir = tempfile.mkdtemp()

            def _work():
                segs = []
                for i in range(len(pts) - 1):
                    t0, v0 = pts[i]
                    t1, v1 = pts[i + 1]
                    seg_speed = (v0 + v1) / 2.0
                    pts_mult  = 1.0 / seg_speed
                    seg_dur   = t1 - t0
                    tmp = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
                    segs.append(tmp)

                    # atempo for audio
                    remaining = seg_speed
                    atempo_chain = []
                    if self.pitch_var.get():
                        while remaining > 2.0:
                            atempo_chain.append("atempo=2.0")
                            remaining /= 2.0
                        while remaining < 0.5:
                            atempo_chain.append("atempo=0.5")
                            remaining *= 2.0
                        atempo_chain.append(f"atempo={remaining:.4f}")
                        af = ",".join(atempo_chain)
                        cmd_seg = [ffmpeg,
                                   "-ss", str(t0), "-i", self.file_path,
                                   "-t", str(seg_dur),
                                   "-vf", f"setpts={pts_mult:.4f}*PTS",
                                   "-af", af,
                                   t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                                   "-preset", "fast", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                                   "-avoid_negative_ts", "make_zero",
                                   "-reset_timestamps", "1", tmp, "-y"]
                    else:
                        cmd_seg = [ffmpeg,
                                   "-ss", str(t0), "-i", self.file_path,
                                   "-t", str(seg_dur),
                                   "-vf", f"setpts={pts_mult:.4f}*PTS",
                                   t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                                   "-preset", "fast", "-an",
                                   "-avoid_negative_ts", "make_zero",
                                   "-reset_timestamps", "1", tmp, "-y"]

                    self.after(0, lambda i=i, n=len(pts)-1:
                               self.log(self.console,
                                        f"[{i+1}/{n}] Encoding segment {i+1}…"))
                    r = subprocess.run(cmd_seg, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
                    if r.returncode != 0:
                        self.after(0, lambda e=r.stderr[-200:]:
                                   self.log(self.console, f"  ⚠ {e}"))

                # Concat list
                list_path = os.path.join(tmp_dir, "list.txt")
                with open(list_path, "w") as f:
                    for p in segs:
                        f.write(f"file '{p}'\n")

                cmd_cat = [ffmpeg, "-f", "concat", "-safe", "0",
                           "-i", list_path, "-c", "copy",
                           "-movflags", t("dynamics.faststart"), out, "-y"]
                self.after(0, lambda: self.log(self.console, t("log.speed_ramp.concatenating_segments")))
                rc_proc = subprocess.run(cmd_cat, capture_output=True, text=True,
                                 creationflags=CREATE_NO_WINDOW)
                for p in segs:
                    try: os.remove(p)
                    except Exception: pass
                try: os.rmdir(tmp_dir)
                except Exception: pass
                self.after(0, lambda: self.show_result(rc_proc.returncode, out))
                self.after(0, lambda: self.btn_render.config(
                    state="normal", text=t("speed_ramp.apply_button")))

            self.btn_render.config(state="disabled", text=t("crossfader.rendering"))
            self.log(self.console,
                     f"Multi-point ramp: {len(pts)-1} segment(s) over {pts[-1][0]-pts[0][0]:.1f}s")
            self.run_in_thread(_work)
            return