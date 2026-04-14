"""
tab_sequencer.py  ─  Multi-Clip Sequencer

A visual storyboard for arranging multiple clips in order before
rendering them into a single output.  Editors can reorder clips,
set per-clip in/out points, and preview the sequence.

This is the "timeline lite" that every content editor needs when
they have 10-20 clips from a stream and need to stitch a highlights
reel together quickly.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class SequencerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.clips = []  # list of dicts: {path, duration, trim_in, trim_out, name}
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.multi_clip_sequencer"),
                         t("sequencer.subtitle"),
                         icon="🎬")

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=CLR["panel"])
        tb.pack(fill="x", padx=0, pady=0)
        tb_inner = tk.Frame(tb, bg=CLR["panel"])
        tb_inner.pack(fill="x", padx=16, pady=8)

        tk.Button(tb_inner, text=t("sequencer.add_clips_button"), bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 10, "bold"), cursor="hand2", relief="flat",
                  command=self._add_clips).pack(side="left", padx=4)
        tk.Button(tb_inner, text=t("sequencer.remove_selected_button"), bg=CLR["red"], fg="white",
                  font=(UI_FONT, 10), cursor="hand2", relief="flat",
                  command=self._remove_selected).pack(side="left", padx=4)
        tk.Button(tb_inner, text="⬆", bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 11, "bold"), cursor="hand2", relief="flat", width=3,
                  command=self._move_up).pack(side="left", padx=2)
        tk.Button(tb_inner, text="⬇", bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 11, "bold"), cursor="hand2", relief="flat", width=3,
                  command=self._move_down).pack(side="left", padx=2)
        tk.Button(tb_inner, text=t("sequencer.clear_all_button"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2", relief="flat",
                  command=self._clear_all).pack(side="left", padx=(12, 4))

        self._total_lbl = tk.Label(tb_inner, text=t("sequencer.0_clips_0_00_total"),
                                   bg=CLR["panel"], fg=CLR["fgdim"],
                                   font=(UI_FONT, 10))
        self._total_lbl.pack(side="right")

        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Timeline canvas (visual storyboard) ──────────────────────────
        tl_lf = tk.LabelFrame(self, text=f"  {t('sequencer.storyboard_section')}  ",
                              padx=8, pady=6, font=(UI_FONT, 9, "bold"))
        tl_lf.pack(fill="x", padx=20, pady=8)

        self._timeline = tk.Canvas(tl_lf, bg=CLR["console_bg"], height=70,
                                   highlightthickness=0)
        self._timeline.pack(fill="x")
        self._timeline.bind("<Configure>", lambda _: self._draw_timeline())

        # ── Clip list ─────────────────────────────────────────────────────
        list_lf = tk.LabelFrame(self, text=f"  {t('sequencer.clip_list_section')}  ",
                                padx=8, pady=6, font=(UI_FONT, 9, "bold"))
        list_lf.pack(fill="both", expand=True, padx=20, pady=4)

        # Column headers
        hdr = tk.Frame(list_lf, bg=CLR["panel"])
        hdr.pack(fill="x")
        for txt, w in [(t("sequencer.column_number"), 4), (t("sequencer.column_filename"), 35), (t("sequencer.column_duration"), 10),
                       (t("sequencer.column_trim_in"), 10), (t("sequencer.column_trim_out"), 10), (t("sequencer.column_use"), 10)]:
            tk.Label(hdr, text=txt, width=w, anchor="w", bg=CLR["panel"],
                     fg=CLR["fgdim"], font=(UI_FONT, 8, "bold")).pack(side="left", padx=2)

        list_f = tk.Frame(list_lf)
        list_f.pack(fill="both", expand=True)

        self._clip_list = tk.Listbox(
            list_f, bg=CLR["console_bg"], fg=CLR["console_fg"],
            font=(MONO_FONT, 9), selectmode="browse", height=8,
            relief="flat", bd=0, activestyle="none")
        lsb = ttk.Scrollbar(list_f, command=self._clip_list.yview)
        self._clip_list.config(yscrollcommand=lsb.set)
        self._clip_list.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self._clip_list.bind("<Double-1>", self._edit_trim)

        # ── Per-clip trim editor ──────────────────────────────────────────
        trim_lf = tk.LabelFrame(self, text=f"  {t('sequencer.selected_trim_section')}  ",
                                padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        trim_lf.pack(fill="x", padx=20, pady=4)

        tr = tk.Frame(trim_lf)
        tr.pack(fill="x")
        tk.Label(tr, text=t("sequencer.trim_in_label"), font=(UI_FONT, 10)).pack(side="left")
        self._trim_in_var = tk.StringVar(value="0.0")
        tk.Entry(tr, textvariable=self._trim_in_var, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(tr, text=t("sequencer.trim_out_label"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._trim_out_var = tk.StringVar(value="0.0")
        tk.Entry(tr, textvariable=self._trim_out_var, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Button(tr, text=t("sequencer.apply_trim_button"), bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._apply_trim).pack(side="left", padx=10)
        tk.Button(tr, text=t("sequencer.preview_clip_button"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._preview_clip).pack(side="left", padx=4)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        opt_f = tk.Frame(self)
        opt_f.pack(fill="x", padx=20, pady=2)
        self._copy_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_f, text=t("sequencer.stream_copy_checkbox"),
                       variable=self._copy_mode, font=(UI_FONT, 10)).pack(side="left")
        tk.Label(opt_f, text=t("rotate_flip.crf"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(opt_f, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        tk.Button(bf, text=t("sequencer.preview_sequence_button"), bg=CLR["accent"], fg="white",
                  width=24, font=(UI_FONT, 10), cursor="hand2",
                  command=self._preview_all).pack(side="left", padx=8)
        self._btn_run = tk.Button(
            bf, text=t("sequencer.render_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack(side="left", padx=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Clip management ───────────────────────────────────────────────
    def _add_clips(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        for p in paths:
            dur = get_video_duration(p)
            self.clips.append({
                "path": p,
                "name": os.path.basename(p),
                "duration": dur,
                "trim_in": 0.0,
                "trim_out": dur,
            })
        self._refresh_list()

    def _remove_selected(self):
        sel = self._clip_list.curselection()
        if sel:
            idx = sel[0]
            self.clips.pop(idx)
            self._refresh_list()

    def _move_up(self):
        sel = self._clip_list.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            self.clips[idx - 1], self.clips[idx] = self.clips[idx], self.clips[idx - 1]
            self._refresh_list()
            self._clip_list.selection_set(idx - 1)

    def _move_down(self):
        sel = self._clip_list.curselection()
        if sel and sel[0] < len(self.clips) - 1:
            idx = sel[0]
            self.clips[idx + 1], self.clips[idx] = self.clips[idx], self.clips[idx + 1]
            self._refresh_list()
            self._clip_list.selection_set(idx + 1)

    def _clear_all(self):
        self.clips.clear()
        self._refresh_list()

    def _refresh_list(self):
        self._clip_list.delete(0, "end")
        total_dur = 0.0
        for i, c in enumerate(self.clips):
            use_dur = c["trim_out"] - c["trim_in"]
            total_dur += use_dur
            line = (f" {i + 1:3d}   {c['name'][:32]:<34s} "
                    f"{_fmt(c['duration']):>9s}  "
                    f"{_fmt(c['trim_in']):>9s}  "
                    f"{_fmt(c['trim_out']):>9s}  "
                    f"{_fmt(use_dur):>9s}")
            self._clip_list.insert("end", line)

        self._total_lbl.config(
            text=f"{len(self.clips)} clips  ·  {_fmt(total_dur)} total")
        self._draw_timeline()

    def _edit_trim(self, event=None):
        sel = self._clip_list.curselection()
        if not sel:
            return
        idx = sel[0]
        c = self.clips[idx]
        self._trim_in_var.set(str(round(c["trim_in"], 2)))
        self._trim_out_var.set(str(round(c["trim_out"], 2)))

    def _apply_trim(self):
        sel = self._clip_list.curselection()
        if not sel:
            messagebox.showwarning(t("sequencer.no_selection_title"), t("sequencer.no_selection_message"))
            return
        idx = sel[0]
        try:
            ti = float(self._trim_in_var.get())
            to = float(self._trim_out_var.get())
        except ValueError:
            messagebox.showerror(t("common.error"), t("common.no_input"))
            return
        if to <= ti:
            messagebox.showerror(t("trimmer.invalid_range_error"), t("trimmer.invalid_range_message"))
            return
        self.clips[idx]["trim_in"] = ti
        self.clips[idx]["trim_out"] = min(to, self.clips[idx]["duration"])
        self._refresh_list()
        self._clip_list.selection_set(idx)

    def _preview_clip(self):
        sel = self._clip_list.curselection()
        if not sel:
            return
        c = self.clips[sel[0]]
        if self.preview_proc:
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
        self.preview_proc = launch_preview(
            c["path"], start_time=c["trim_in"])

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    # ── Timeline drawing ──────────────────────────────────────────────
    def _draw_timeline(self):
        c = self._timeline
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or not self.clips:
            c.create_text(w // 2, h // 2, text=t("sequencer.add_clips_to_see_the_storyboard"),
                          fill=CLR["fgdim"], font=(UI_FONT, 10))
            return

        total = sum(cl["trim_out"] - cl["trim_in"] for cl in self.clips)
        if total <= 0:
            return

        colors = [CLR["accent"], CLR["green"], CLR["orange"], CLR["pink"],
                  "#9C27B0", "#00BCD4", "#FF5722", "#8BC34A"]
        pad = 4
        x = pad
        avail = w - 2 * pad

        for i, cl in enumerate(self.clips):
            dur = cl["trim_out"] - cl["trim_in"]
            seg_w = max(8, int((dur / total) * avail))
            color = colors[i % len(colors)]

            c.create_rectangle(x, 8, x + seg_w, h - 8,
                               fill=color, outline="#111111", width=1)

            # Label
            if seg_w > 40:
                name = cl["name"][:seg_w // 7]
                c.create_text(x + seg_w // 2, h // 2 - 6,
                              text=name, fill="white",
                              font=(UI_FONT, 7, "bold"))
                c.create_text(x + seg_w // 2, h // 2 + 8,
                              text=_fmt(dur), fill="#DDDDDD",
                              font=(MONO_FONT, 6))

            x += seg_w + 1

    # ── Preview & Render ──────────────────────────────────────────────
    def _preview_all(self):
        if not self.clips:
            messagebox.showwarning(t("sequencer.no_clips_title"), t("sequencer.no_clips_message"))
            return
        # Quick: just preview first clip
        c = self.clips[0]
        if self.preview_proc:
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
        self.preview_proc = launch_preview(c["path"], start_time=c["trim_in"])

    def _render(self):
        if not self.clips:
            messagebox.showwarning(t("sequencer.no_clips_title"), t("sequencer.no_clips_message"))
            return

        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        self._btn_run.config(state="disabled", text=t("app.status.queued_btn"))
        self.log(self.console, f"Rendering sequence: {len(self.clips)} clips…")

        def _worker(progress_cb, cancel_fn):
            ffmpeg = get_binary_path("ffmpeg")
            tmp_dir = tempfile.mkdtemp(prefix="xfpro_seq_")
            copy = self._copy_mode.get()
            crf = self._crf_var.get()

            # Step 1: Trim each clip to temp files
            trimmed = []
            for i, cl in enumerate(self.clips):
                tmp_out = os.path.join(tmp_dir, f"clip_{i:03d}.mp4")
                ss = cl["trim_in"]
                dur = cl["trim_out"] - cl["trim_in"]

                if copy:
                    cmd = [ffmpeg, "-ss", str(ss), "-i", cl["path"],
                           "-t", str(dur), "-c", "copy",
                           "-avoid_negative_ts", "make_zero",
                           tmp_out, "-y"]
                else:
                    cmd = [ffmpeg, "-ss", str(ss), "-i", cl["path"],
                           "-t", str(dur),
                           "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                           "-c:a", "aac", "-b:a", "192k",
                           "-movflags", "+faststart", tmp_out, "-y"]

                if cancel_fn():
                    return -1
                progress_cb(f"  [{i + 1}/{len(self.clips)}] Trimming: {cl['name']}")
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        creationflags=CREATE_NO_WINDOW)
                proc.communicate()
                if os.path.exists(tmp_out):
                    trimmed.append(tmp_out)

            if not trimmed:
                progress_cb("❌ No clips were trimmed successfully.")
                return 1

            # Step 2: Concat via concat demuxer
            list_file = os.path.join(tmp_dir, "concat.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for p in trimmed:
                    f.write(f"file '{p}'\n")

            if copy:
                cmd = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_file, "-c", "copy",
                       "-movflags", t("dynamics.faststart"), out, "-y"]
            else:
                cmd = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_file,
                       t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                       t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                       "-movflags", t("dynamics.faststart"), out, "-y"]

            progress_cb("Concatenating clips…")
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
            for p in trimmed:
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
            self._btn_run.config(text=t("crossfader.rendering"))

        def _on_progress(tid, line):
            self.log(self.console, line)

        def _on_complete(tid, rc):
            self._btn_run.config(state="normal", text=t("sequencer.render_sequence"))
            self.show_result(rc, out)

        self.enqueue_render(
            "Sequencer",
            output_path=out,
            worker_fn=_worker,
            on_start=_on_start,
            on_progress=_on_progress,
            on_complete=_on_complete,
        )
