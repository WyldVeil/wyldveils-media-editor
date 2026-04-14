"""
tab_splicer.py  ─  The Splicer
Lets the user pick in/out points from multiple source videos and
stitches the chosen segments together into a single output file.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


class SplicerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.segments = []   # list of dicts: {path, start, end, dur}
        self._sel_idx = None
        self._build_ui()

    # ─── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x", padx=0, pady=0)
        tk.Label(hdr, text="✂  " + t("tab.the_splicer"), font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr, text=t("splicer.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left", padx=5)

        # Segments list area
        list_outer = tk.LabelFrame(self, text=t("splicer.segment_queue_section"), padx=10, pady=8)
        list_outer.pack(fill="both", expand=True, padx=20, pady=10)

        # Column headers
        hf = tk.Frame(list_outer)
        hf.pack(fill="x", pady=(0, 4))
        for txt, w in [("#", 3), (t("splicer.column_source"), 38), (t("splicer.column_start"), 8),
                       (t("splicer.column_end"), 8), (t("splicer.column_duration"), 9), ("", 12)]:
            tk.Label(hf, text=txt, font=(UI_FONT, 9, "bold"), width=w, anchor="w").pack(side="left", padx=2)

        # Scrollable segment rows
        self.seg_canvas = tk.Canvas(list_outer, height=280, highlightthickness=0)
        seg_sb = ttk.Scrollbar(list_outer, orient="vertical", command=self.seg_canvas.yview)
        self.seg_frame = tk.Frame(self.seg_canvas)
        self.seg_canvas.create_window((0, 0), window=self.seg_frame, anchor="nw")
        self.seg_canvas.configure(yscrollcommand=seg_sb.set)
        self.seg_frame.bind("<Configure>", lambda e: self.seg_canvas.configure(
            scrollregion=self.seg_canvas.bbox("all")))
        self.seg_canvas.pack(side="left", fill="both", expand=True)
        seg_sb.pack(side="right", fill="y")

        # Timeline
        tl_frame = tk.LabelFrame(self, text=t("splicer.segment_queue_section") + " - Timeline",
                                 padx=10, pady=8)
        tl_frame.pack(fill="x", padx=20, pady=(0, 6))
        self._timeline = VideoTimeline(tl_frame, on_change=self._on_timeline_change,
                                       height=90, show_handles=True)
        self._timeline.pack(fill="x")
        self._tl_pos_var = tk.StringVar(value="Playhead: -")
        tk.Label(tl_frame, textvariable=self._tl_pos_var,
                 font=(MONO_FONT, 9), fg=CLR["fgdim"]).pack(anchor="w", pady=(4, 0))

        # Buttons
        btn_row = tk.Frame(self)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("splicer.add_segment_button"), bg=CLR["panel"], fg=CLR["fg"],
                  width=18, command=self._add_segment).pack(side="left", padx=6)
        tk.Button(btn_row, text=t("splicer.remove_last_button"), bg=CLR["panel"], fg=CLR["fg"],
                  width=18, command=self._remove_last).pack(side="left", padx=6)
        tk.Button(btn_row, text=t("splicer.move_up_button"), bg=CLR["panel"], fg=CLR["fg"],
                  width=14, command=lambda: self._move(-1)).pack(side="left", padx=6)
        tk.Button(btn_row, text=t("splicer.move_down_button"), bg=CLR["panel"], fg=CLR["fg"],
                  width=14, command=lambda: self._move(1)).pack(side="left", padx=6)

        # Output row
        out_f = tk.Frame(self)
        out_f.pack(pady=5)
        tk.Label(out_f, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(out_f, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(out_f, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Options
        opt_f = tk.Frame(self)
        opt_f.pack(pady=4)
        self.reencode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_f, text=t("splicer.reencode_checkbox"),
                       variable=self.reencode_var).pack(side="left", padx=10)
        tk.Label(opt_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)

        # Render button
        self.btn_render = tk.Button(
            self, text=t("splicer.splice_export_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=30, command=self._render)
        self.btn_render.pack(pady=10)

        # Console
        console_f = tk.Frame(self)
        console_f.pack(fill="both", expand=True, padx=20, pady=5)
        self.console, sb = self.make_console(console_f, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ─── Segment management ───────────────────────────────────────────────────
    def _add_segment(self):
        path = filedialog.askopenfilename(
            title="Select source clip",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if not path:
            return
        dur = get_video_duration(path)
        idx = len(self.segments)
        seg = {"path": path, "start": tk.StringVar(value="0"),
               "end": tk.StringVar(value=f"{dur:.3f}"), "dur": dur}
        self.segments.append(seg)
        self._draw_row(idx, seg)
        self._select_row(idx)

    def _draw_row(self, idx, seg):
        row = tk.Frame(self.seg_frame, relief="groove", bd=1)
        row.pack(fill="x", pady=2)
        seg["row"] = row

        tk.Label(row, text=str(idx + 1), width=3, anchor="w").pack(side="left", padx=2)
        fname = os.path.basename(seg["path"])
        tk.Label(row, text=fname, width=38, anchor="w",
                 fg=CLR["accent"]).pack(side="left", padx=2)

        for var, tip in [(seg["start"], "Start"), (seg["end"], "End")]:
            tk.Label(row, text=tip + ":").pack(side="left")
            tk.Entry(row, textvariable=var, width=8, relief="flat").pack(side="left", padx=2)
            var.trace_add("write", lambda *_: self._refresh_dur(seg))

        seg["dur_lbl"] = tk.Label(row, text=self._calc_dur(seg),
                                  width=9, fg=CLR["fgdim"])
        seg["dur_lbl"].pack(side="left", padx=4)

        if "include" not in seg:
            seg["include"] = tk.BooleanVar(value=True)
        sel_btn = tk.Checkbutton(row, text=t("splicer.include"), variable=seg["include"])
        sel_btn.pack(side="left", padx=4)
        row.bind("<Button-1>", lambda e, i=idx: self._select_row(i))

    def _calc_dur(self, seg):
        try:
            d = float(seg["end"].get()) - float(seg["start"].get())
            return f"{d:.2f}s" if d > 0 else "⚠ invalid"
        except Exception:
            return "-"

    def _refresh_dur(self, seg):
        if "dur_lbl" in seg:
            seg["dur_lbl"].config(text=self._calc_dur(seg))

    def _remove_last(self):
        if self.segments:
            seg = self.segments.pop()
            seg["row"].destroy()

    def _select_row(self, idx):
        if self._sel_idx is not None and self._sel_idx < len(self.segments):
            old = self.segments[self._sel_idx].get("row")
            if old and old.winfo_exists():
                old.config(relief="groove", bd=1)
        self._sel_idx = idx
        new = self.segments[idx].get("row")
        if new and new.winfo_exists():
            new.config(relief="solid", bd=2)
        self._update_timeline_for_segment(idx)

    def _on_timeline_change(self, start, end, playhead):
        """Called when the user interacts with the timeline widget."""
        self._tl_pos_var.set(f"Playhead: {playhead:.2f}s  |  Range: {start:.2f}s – {end:.2f}s")
        # Sync the timeline range back into the selected segment's in/out fields
        if self._sel_idx is not None and self._sel_idx < len(self.segments):
            seg = self.segments[self._sel_idx]
            seg["start"].set(f"{start:.3f}")
            seg["end"].set(f"{end:.3f}")

    def _update_timeline_for_segment(self, idx):
        """Push the selected segment's duration and range into the timeline."""
        if idx is not None and idx < len(self.segments):
            seg = self.segments[idx]
            self._timeline.set_duration(seg["dur"])
            try:
                s = float(seg["start"].get())
                e = float(seg["end"].get())
            except ValueError:
                s, e = 0, seg["dur"]
            self._timeline.set_range(s, e)
            self._timeline.set_playhead(s)

    def _rebuild_rows(self):
        for seg in self.segments:
            if seg.get("row") and seg["row"].winfo_exists():
                seg["row"].destroy()
            seg.pop("row", None)
            seg.pop("dur_lbl", None)
        for i, seg in enumerate(self.segments):
            self._draw_row(i, seg)

    def _move(self, direction):
        if self._sel_idx is None:
            messagebox.showinfo(t("splicer.select_row_title"), t("splicer.select_row_message"))
            return
        idx = self._sel_idx
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.segments):
            return
        self.segments[idx], self.segments[new_idx] = self.segments[new_idx], self.segments[idx]
        self._rebuild_rows()
        self._select_row(new_idx)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p:
            self.out_var.set(p)

    # ─── Render ───────────────────────────────────────────────────────────────
    def _render(self):
        active = [s for s in self.segments if s["include"].get()]
        if len(active) < 1:
            messagebox.showwarning(t("splicer.no_segments_title"), t("splicer.no_segments_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)
        self.log(self.console, t("log.splicer.starting_splice_render"))

        ffmpeg = get_binary_path("ffmpeg.exe")

        if self.reencode_var.get():
            self._render_reencode(active, out, ffmpeg)
        else:
            self._render_concat(active, out, ffmpeg)

    def _render_concat(self, segs, out, ffmpeg):
        """Fast stream-copy via concat demuxer (requires matching codec/resolution)."""
        # Trim each segment to a temp file first, then concat
        tmp_dir = tempfile.mkdtemp()
        tmp_files = []
        self.log(self.console, f"Temp dir: {tmp_dir}")

        def _work():
            for i, seg in enumerate(segs):
                tmp = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
                tmp_files.append(tmp)
                ss = seg["start"].get()
                to = seg["end"].get()
                try:
                    dur = float(to) - float(ss)
                except ValueError:
                    dur = 0
                # Use -t (duration) instead of -to to avoid pts drift issues
                # -reset_timestamps 1 ensures each segment starts at pts=0
                cmd = [ffmpeg, "-ss", str(ss), "-i", seg["path"],
                       "-t", str(max(0.01, dur)),
                       "-c", "copy",
                       "-avoid_negative_ts", "make_zero",
                       "-reset_timestamps", "1",
                       tmp, "-y"]
                self.log(self.console, f"[{i+1}/{len(segs)}] Trimming → {os.path.basename(tmp)}")
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=CREATE_NO_WINDOW)
                if r.returncode != 0:
                    self.log(self.console, f"  ⚠ Trim failed for segment {i+1}: {r.stderr[-200:]}")

            # Write concat list
            list_path = os.path.join(tmp_dir, "list.txt")
            with open(list_path, "w") as f:
                for p in tmp_files:
                    f.write(f"file '{p}'\n")

            cmd_cat = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_path, "-c", "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, t("log.splicer.concatenating"))
            proc = subprocess.run(cmd_cat, capture_output=True, text=True,
                                  creationflags=CREATE_NO_WINDOW)
            rc = proc.returncode
            # Cleanup
            for p in tmp_files:
                try: os.remove(p)
                except Exception: pass
            try: os.rmdir(tmp_dir)
            except Exception: pass
            self.after(0, lambda: self.show_result(rc, out))

        self.run_in_thread(_work)

    def _render_reencode(self, segs, out, ffmpeg):
        """Full re-encode with select filter - handles mixed sources."""
        crf = self.crf_var.get()
        tmp_dir = tempfile.mkdtemp()
        tmp_files = []

        def _work():
            for i, seg in enumerate(segs):
                tmp = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
                tmp_files.append(tmp)
                ss = seg["start"].get()
                to = seg["end"].get()
                try:
                    dur = float(to) - float(ss)
                except ValueError:
                    dur = 0
                # Normalise to 1920×1080 so all segments share same resolution
                vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
                      "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                      "setpts=PTS-STARTPTS")
                cmd = [ffmpeg, "-ss", str(ss), "-i", seg["path"],
                       "-t", str(max(0.01, dur)),
                       "-vf", vf,
                       "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                       "-c:a", "aac", "-b:a", "192k",
                       "-avoid_negative_ts", "make_zero",
                       "-reset_timestamps", "1",
                       tmp, "-y"]
                self.log(self.console, f"[{i+1}/{len(segs)}] Encoding → {os.path.basename(tmp)}")
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=CREATE_NO_WINDOW)
                if r.returncode != 0:
                    self.log(self.console, f"  ⚠ Encode error: {r.stderr[-300:]}")

            list_path = os.path.join(tmp_dir, "list.txt")
            with open(list_path, "w") as f:
                for p in tmp_files:
                    f.write(f"file '{p}'\n")

            cmd_cat = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_path, "-c", "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, t("log.splicer.final_concat"))
            proc = subprocess.run(cmd_cat, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            for p in tmp_files:
                try: os.remove(p)
                except Exception: pass
            try: os.rmdir(tmp_dir)
            except Exception: pass
            self.after(0, lambda: self.show_result(proc.returncode, out))

        self.run_in_thread(_work)
