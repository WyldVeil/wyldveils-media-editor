"""
tab_beatsynccutter.py  ─  Beat Sync Cutter
Detects beat timestamps in a music/audio track using FFmpeg's
`ebur128` and `astats` filters combined with peak detection, then:

  Mode 1 - Mark only: export a text file of beat timestamps
  Mode 2 - Auto-cut:  slice a source video at beat boundaries and
                      re-join as a rhythmically-edited clip
  Mode 3 - Chapter markers: export YouTube-formatted chapter list

Beat detection uses FFmpeg's `silencedetect` on a high-passed,
compressed version of the audio to find transient peaks - effective
for music with a clear beat (electronic, pop, hip-hop, drums).

For the auto-cut mode the user can set:
  • Beat subdivision (every 1st, 2nd, 4th beat)
  • Minimum clip length (ignores beats that are too close together)
  • Max number of cuts
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import shutil
import tempfile
import json

from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


def _detect_beats(ffmpeg_path, audio_path, sensitivity=0.15, min_gap=0.2):
    """
    Detect beat/transient onsets using a high-pass + dynamics trick.
    Returns sorted list of beat timestamps (seconds, float).
    """
    # Strategy: apply high-pass filter to isolate transients,
    # then use volumedetect + manual peak scanning via stderr parsing.
    # We use `astats` frame-by-frame at short intervals to find RMS peaks.

    cmd = [
        ffmpeg_path,
        "-i", audio_path,
        "-af", (
            # 1. High-pass to isolate kick/snare attack transients
            "highpass=f=80,"
            # 2. Heavy compression to make all beats equally loud
            "acompressor=threshold=0.05:ratio=20:attack=1:release=10,"
            # 3. astats every 0.05s chunk - we'll parse RMS from stderr
            "astats=length=0.05:metadata=1:reset=1,"
            "ametadata=mode=print:file=-"
        ),
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=CREATE_NO_WINDOW)
    output = result.stderr + result.stdout

    # Parse RMS_level lines
    rms_values = []
    time_re  = re.compile(r"pts_time:([\d.]+)")
    rms_re   = re.compile(r"lavfi\.astats\.Overall\.RMS_level=([-\d.]+)")

    current_t   = None
    for line in output.split("\n"):
        tm = time_re.search(line)
        rm = rms_re.search(line)
        if tm:
            current_t = float(tm.group(1))
        if rm and current_t is not None:
            try:
                rms_str = rm.group(1).strip()
                # FFmpeg can output '-', '-inf', 'nan', or '-nan' for silence
                if rms_str in ('-', '-inf', 'nan', '-nan', 'inf'):
                    rms_db = -200.0
                else:
                    rms_db = float(rms_str)
            except (ValueError, TypeError):
                rms_db = -200.0
            # Convert dB to linear
            if rms_db > -100:
                rms_lin = 10 ** (rms_db / 20)
                rms_values.append((current_t, rms_lin))
            current_t = None

    if not rms_values:
        return []

    # Find peaks: a beat is where RMS exceeds `sensitivity` times the
    # rolling max, with at least `min_gap` seconds between beats.
    max_rms   = max(v for _, v in rms_values)
    threshold = max_rms * sensitivity

    beats       = []
    last_beat_t = -999

    for i in range(1, len(rms_values) - 1):
        t, rms = rms_values[i]
        if (rms > threshold
                and rms >= rms_values[i-1][1]
                and rms >= rms_values[i+1][1]
                and (t - last_beat_t) >= min_gap):
            beats.append(round(t, 3))
            last_beat_t = t

    return beats


def _fmt_timestamp(secs: float) -> str:
    """Format seconds as MM:SS for YouTube chapters."""
    m = int(secs) // 60
    s = int(secs) % 60
    return f"{m:02d}:{s:02d}"


class BeatSyncCutterTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.audio_path = ""
        self.video_path = ""
        self._beats: list = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🥁  " + t("tab.beat_sync_cutter"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("beat_sync.desc"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Input files ───────────────────────────────────────────────────
        inp = tk.LabelFrame(self, text=t("section.input_files"), padx=14, pady=8)
        inp.pack(fill="x", padx=16, pady=8)

        for label, attr, tip in [
            ("🎵  Music / Audio  (beat source):", "audio",
             "The track whose beats will be detected."),
            ("🎬  Video to cut  (optional):", "video",
             "The video to slice at beat points. Leave blank for marks-only mode."),
        ]:
            row = tk.Frame(inp); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=32, anchor="w",
                     font=(UI_FONT, 9, "bold")).pack(side="left")
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(row, textvariable=var, width=50, relief="flat").pack(side="left", padx=6)

            def _b(a=attr, v=var):
                ft = ([("Audio/Video",
                        "*.mp3 *.wav *.aac *.flac *.ogg *.mp4 *.mov"),
                       ("All", "*.*")]
                      if a == "audio"
                      else [("Video", "*.mp4 *.mov *.mkv *.avi"),
                             ("All", "*.*")])
                p = filedialog.askopenfilename(filetypes=ft)
                if p:
                    setattr(self, a + "_path", p)
                    v.set(p)
                    try:
                        self.duration = get_video_duration(p)
                        self._timeline.set_duration(self.duration)
                    except Exception:
                        pass
            tk.Button(row, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").pack(side="left")
            tk.Label(inp, text=f"  ℹ  {tip}", fg=CLR["fgdim"],
                     font=(UI_FONT, 8)).pack(anchor="w")

        # ── Video timeline ────────────────────────────────────────────────
        tl_lf = tk.LabelFrame(self, text=t("beat_sync.sect_beat_timeline"), padx=14, pady=8)
        tl_lf.pack(fill="x", padx=20, pady=4)
        self._timeline = VideoTimeline(tl_lf, on_change=self._on_timeline_change,
                                       height=90, show_handles=False)
        self._timeline.pack(fill="x")

        # ── Detection options ─────────────────────────────────────────────
        det_lf = tk.LabelFrame(self, text=t("beat_sync.sect_beat_detection"), padx=14, pady=10)
        det_lf.pack(fill="x", padx=16, pady=4)

        d0 = tk.Frame(det_lf); d0.pack(fill="x", pady=3)
        tk.Label(d0, text=t("beat_sync.lbl_sensitivity"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.sens_var = tk.DoubleVar(value=0.15)
        tk.Scale(d0, variable=self.sens_var, from_=0.05, to=0.80,
                 resolution=0.01, orient="horizontal", length=220).pack(side="left", padx=8)
        self.sens_lbl = tk.Label(d0, text="0.15", width=5, fg=CLR["accent"])
        self.sens_lbl.pack(side="left")
        self.sens_var.trace_add("write", lambda *_: self.sens_lbl.config(
            text=f"{self.sens_var.get():.2f}"))
        tk.Label(d0, text=t("beat_sync.desc_sensitivity_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        d1 = tk.Frame(det_lf); d1.pack(fill="x", pady=3)
        tk.Label(d1, text=t("beat_sync.lbl_min_gap")).pack(side="left")
        self.mingap_var = tk.StringVar(value="0.2")
        tk.Entry(d1, textvariable=self.mingap_var, width=5, relief="flat").pack(side="left", padx=6)
        tk.Label(d1, text=t("beat_sync.desc_min_gap_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        self.btn_detect = tk.Button(det_lf, text=t("beat_sync.btn_detect_beats"),
                                     bg=CLR["accent"], fg="black",
                                     font=(UI_FONT, 10, "bold"),
                                     command=self._detect)
        self.btn_detect.pack(anchor="w", pady=6)

        # Beat results panel
        res_lf = tk.LabelFrame(self, text=t("beat_sync.sect_detected_beats"), padx=10, pady=6)
        res_lf.pack(fill="x", padx=16, pady=4)

        self.beat_text = tk.Text(res_lf, height=4, bg=CLR["console_bg"],
                                  fg="#00FF88", font=(MONO_FONT, 9),
                                  wrap="word")
        self.beat_text.pack(fill="x")
        self.beat_text.insert(tk.END, "Run detection first…")
        self.beat_text.config(state="disabled")

        # ── Cut options ───────────────────────────────────────────────────
        cut_lf = tk.LabelFrame(self, text=t("beat_sync.sect_auto_cut_options"), padx=14, pady=10)
        cut_lf.pack(fill="x", padx=16, pady=4)

        c0 = tk.Frame(cut_lf); c0.pack(fill="x", pady=3)
        tk.Label(c0, text=t("beat_sync.lbl_mode"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.mode_var = tk.StringVar(value="Auto-cut video to beats")
        ttk.Combobox(c0, textvariable=self.mode_var,
                     values=["Auto-cut video to beats",
                              t("beat_sync.beat_sync_export_beat_timestamps_txt"),
                              t("beat_sync.beat_sync_export_youtube_chapters_txt"),
                              t("beat_sync.beat_sync_export_edl_cut_list_edl")],
                     state="readonly", width=32).pack(side="left", padx=8)

        c1 = tk.Frame(cut_lf); c1.pack(fill="x", pady=3)
        tk.Label(c1, text=t("beat_sync.lbl_nth_beat")).pack(side="left")
        self.nth_var = tk.StringVar(value="1")
        ttk.Combobox(c1, textvariable=self.nth_var,
                     values=[t("beat_sync.beat_sync_1_every_beat"), t("beat_sync.beat_sync_2_every_2nd"),
                              t("beat_sync.beat_sync_4_every_bar"), t("beat_sync.beat_sync_8_every_2_bars")],
                     state="readonly", width=18).pack(side="left", padx=6)

        c2 = tk.Frame(cut_lf); c2.pack(fill="x", pady=3)
        tk.Label(c2, text=t("beat_sync.lbl_min_clip_length")).pack(side="left")
        self.minclip_var = tk.StringVar(value="0.5")
        tk.Entry(c2, textvariable=self.minclip_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(c2, text=t("beat_sync.lbl_max_cuts")).pack(side="left")
        self.maxcuts_var = tk.StringVar(value="0")
        tk.Entry(c2, textvariable=self.maxcuts_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(c2, text=t("beat_sync.0_unlimited"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Chapter name prefix ───────────────────────────────────────────
        ch_f = tk.Frame(cut_lf); ch_f.pack(fill="x", pady=3)
        tk.Label(ch_f, text=t("beat_sync.chapter_name_prefix")).pack(side="left")
        self.ch_prefix_var = tk.StringVar(value="Chapter")
        tk.Entry(ch_f, textvariable=self.ch_prefix_var, width=16, relief="flat").pack(side="left", padx=4)
        tk.Label(ch_f, text="  (e.g. 'Chapter 1', 'Part 1', etc.)",
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(fill="x", padx=16, pady=5)
        tk.Label(of, text=t("beat_sync.output_file_folder"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("beat_sync.apply_beat_sync"),
            font=(UI_FONT, 12, "bold"),
            bg="#6A1B9A", fg="white",
            height=2, command=self._render)
        self.btn_render.pack(pady=8, padx=16, fill="x")

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    def _on_timeline_change(self, start, end, playhead):
        """Called when the user moves the playhead on the timeline."""
        pass

    def _browse_out(self):
        mode = self.mode_var.get()
        if "video" in mode.lower():
            p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                              filetypes=[("MP4","*.mp4")])
        else:
            p = filedialog.asksaveasfilename(defaultextension=".txt",
                                              filetypes=[("Text","*.txt"),
                                                         ("EDL",t("beat_sync.edl"))])
        if p: self.out_var.set(p)

    def _detect(self):
        src = self.audio_path or self.video_path
        if not src:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        self.btn_detect.config(state="disabled", text=t("beat_sync.detecting"))
        self.log(self.console, t("log.beat_sync.detecting_beats"))

        def _work():
            try:
                ffmpeg = get_binary_path("ffmpeg.exe")
                beats  = _detect_beats(
                    ffmpeg, src,
                    sensitivity=self.sens_var.get(),
                    min_gap=float(self.mingap_var.get() or "0.2"))
                self._beats = beats
                self.after(0, lambda: self._show_beats(beats))
            except Exception as e:
                self.log(self.console, f"❌  Detection error: {e}")
            finally:
                self.after(0, lambda: self.btn_detect.config(
                    state="normal", text=t("beat_sync.btn_detect_beats")))

        self.run_in_thread(_work)

    def _show_beats(self, beats):
        self.beat_text.config(state="normal")
        self.beat_text.delete("1.0", tk.END)
        if beats:
            ts_str = "  ".join(f"{b:.3f}s" for b in beats[:40])
            suffix = f"  … (+{len(beats)-40} more)" if len(beats) > 40 else ""
            self.beat_text.insert(tk.END,
                                   f"{len(beats)} beats detected:\n{ts_str}{suffix}")
            self.log(self.console, f"✅  {len(beats)} beats found.")
        else:
            self.beat_text.insert(tk.END,
                                   "No beats found. Try lowering sensitivity.")
            self.log(self.console, t("log.beat_sync.no_beats_detected_try_lower_sensitivity"))
        self.beat_text.config(state="disabled")

    def _get_filtered_beats(self):
        """Apply nth-beat and min-clip filtering."""
        if not self._beats:
            return []
        nth_str = self.nth_var.get().split(" ")[0]
        try:
            nth = int(nth_str)
        except ValueError:
            nth = 1
        filtered = [b for i, b in enumerate(self._beats) if i % nth == 0]

        min_len = float(self.minclip_var.get() or "0.5")
        result  = []
        for b in filtered:
            if not result or (b - result[-1]) >= min_len:
                result.append(b)

        max_cuts = int(self.maxcuts_var.get() or "0")
        if max_cuts > 0:
            result = result[:max_cuts]

        return result

    def _render(self):
        if not self._beats:
            messagebox.showwarning(t("common.warning"),
                                   "Run beat detection first.")
            return
        mode = self.mode_var.get()
        out  = self.out_var.get().strip()

        if "video" in mode.lower():
            if not self.video_path:
                messagebox.showwarning(t("common.warning"),
                                       "Select a video file for auto-cut mode.")
                return
            if not out:
                out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                                   filetypes=[("MP4","*.mp4")])
            if not out: return
            self.out_var.set(out)
            self._autocut(out)

        else:
            if not out:
                out = filedialog.asksaveasfilename(defaultextension=".txt",
                                                   filetypes=[("Text","*.txt")])
            if not out: return
            self.out_var.set(out)
            if "chapter" in mode.lower():
                self._export_chapters(out)
            elif "edl" in mode.lower():
                self._export_edl(out)
            else:
                self._export_timestamps(out)

    def _autocut(self, out):
        """Slice video at beat points and concat."""
        beats  = self._get_filtered_beats()
        ffmpeg = get_binary_path("ffmpeg.exe")
        tmp    = tempfile.mkdtemp()

        vid_dur = get_video_duration(self.video_path)

        # Build cut boundaries
        boundaries = beats + [vid_dur]
        if boundaries[0] > 0:
            boundaries.insert(0, 0.0)

        self.log(self.console, f"Cutting {len(boundaries)-1} segments at beat points…")

        def _work():
            clips = []
            for i in range(len(boundaries) - 1):
                ss  = boundaries[i]
                dur = boundaries[i+1] - ss
                if dur < 0.1:
                    continue
                clip = os.path.join(tmp, f"beat_{i:04d}.mp4")
                cmd  = [ffmpeg, "-ss", str(ss), "-t", str(dur),
                        "-i", self.video_path,
                        "-c", "copy", clip, "-y"]
                subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
                clips.append(clip)

            list_path = os.path.join(tmp, "list.txt")
            with open(list_path, "w") as f:
                for c in clips:
                    f.write(f"file '{c}'\n")

            self.log(self.console, t("log.beat_sync.joining_clips"))
            cmd_cat = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_path, "-c", "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
            r = subprocess.run(cmd_cat, capture_output=True, creationflags=CREATE_NO_WINDOW)

            try: shutil.rmtree(tmp)
            except Exception: pass

            self.after(0, lambda: self.show_result(r.returncode, out))

        self.run_in_thread(_work)

    def _export_timestamps(self, out):
        beats = self._get_filtered_beats()
        with open(out, "w") as f:
            for b in beats:
                f.write(f"{b:.3f}\n")
        self.log(self.console, f"Exported {len(beats)} timestamps → {out}")
        messagebox.showinfo("Exported",
                            f"{len(beats)} beat timestamps saved to:\n{out}")

    def _export_chapters(self, out):
        beats  = self._get_filtered_beats()
        prefix = self.ch_prefix_var.get().strip() or "Chapter"
        lines  = []
        # YouTube requires 00:00 at the start
        if not beats or beats[0] > 0.5:
            lines.append(f"00:00 {prefix} 0 - Intro")
        for i, b in enumerate(beats):
            lines.append(f"{_fmt_timestamp(b)} {prefix} {i+1}")
        text = "\n".join(lines)
        with open(out, "w") as f:
            f.write(text)
        self.log(self.console, f"Chapter markers:\n{text}")
        messagebox.showinfo("Chapters exported",
                            f"Paste this into your YouTube description:\n\n{text}")

    def _export_edl(self, out):
        beats = self._get_filtered_beats()
        lines = [t("beat_sync.title_beat_sync_edl"), t("beat_sync.fcm_non_drop_frame"), ""]
        for i, b in enumerate(beats):
            tc = _fmt_timestamp(b)
            lines.append(f"{i+1:03d}  AX  V  C  {tc} {tc} {tc} {tc}")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        self.log(self.console, f"EDL exported → {out}")
        messagebox.showinfo("EDL exported", f"Saved to:\n{out}")
