"""
tab_waveformeditor.py  ─  Audio Waveform Editor

Visual waveform display of a video/audio file with the ability to:
  • See the full waveform at a glance (rendered as a canvas)
  • Mark in/out points for cutting audio sections
  • Adjust volume on selected regions (boost/duck)
  • Mute specific sections
  • Export the modified audio or the full video with modified audio

Essential for editors who need to spot audio peaks, silences,
or specific dialogue sections visually.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import struct
import wave
import tempfile
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class WaveformEditorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self._waveform_data = []  # list of peak values
        self._mark_in = 0.0
        self._mark_out = 0.0
        self._regions = []  # list of (start, end, action, value)
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.waveform_editor"),
                         t("waveform.subtitle"),
                         icon="🎵")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._info_lbl = tk.Label(sf, text="", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._info_lbl.pack(side="left", padx=10)

        self._btn_analyze = tk.Button(
            sf, text=t("waveform.analyze"), bg=CLR["accent"], fg="white",
            font=(UI_FONT, 9, "bold"), cursor="hand2", command=self._analyze)
        self._btn_analyze.pack(side="left", padx=6)

        # ── Waveform canvas ───────────────────────────────────────────────
        wf_lf = tk.LabelFrame(self, text=f"  {t('waveform.mark_info_section')}  ",
                              padx=8, pady=6, font=(UI_FONT, 9, "bold"))
        wf_lf.pack(fill="x", padx=20, pady=6)

        self._canvas = tk.Canvas(wf_lf, bg=CLR["console_bg"], height=140,
                                 highlightthickness=0)
        self._canvas.pack(fill="x")
        self._canvas.bind("<ButtonPress-1>", self._on_click)
        self._canvas.bind("<Shift-ButtonPress-1>", self._on_shift_click)
        self._canvas.bind("<Configure>", lambda _: self._draw_waveform())

        # ── Mark info ─────────────────────────────────────────────────────
        mk_f = tk.Frame(self)
        mk_f.pack(fill="x", padx=20, pady=4)

        tk.Label(mk_f, text=t("waveform.in_label"), font=(UI_FONT, 10, "bold"),
                 fg=CLR["green"]).pack(side="left")
        self._in_lbl = tk.Label(mk_f, text="00:00.00", font=(MONO_FONT, 10),
                                fg=CLR["green"], width=10)
        self._in_lbl.pack(side="left", padx=(4, 16))

        tk.Label(mk_f, text=t("waveform.out_label"), font=(UI_FONT, 10, "bold"),
                 fg=CLR["red"]).pack(side="left")
        self._out_lbl = tk.Label(mk_f, text="00:00.00", font=(MONO_FONT, 10),
                                 fg=CLR["red"], width=10)
        self._out_lbl.pack(side="left", padx=(4, 16))

        tk.Label(mk_f, text=t("waveform.selection_label"), font=(UI_FONT, 10)).pack(side="left")
        self._sel_lbl = tk.Label(mk_f, text=t("waveform.0_00s"), font=(MONO_FONT, 10),
                                 fg=CLR["accent"], width=10)
        self._sel_lbl.pack(side="left")

        # ── Region actions ────────────────────────────────────────────────
        act_lf = tk.LabelFrame(self, text=f"  {t('waveform.region_actions_section')}  ",
                               padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        act_lf.pack(fill="x", padx=20, pady=6)

        ar1 = tk.Frame(act_lf)
        ar1.pack(fill="x", pady=4)

        tk.Button(ar1, text=t("waveform.mute_button"), bg=CLR["red"], fg="white",
                  font=(UI_FONT, 10, "bold"), cursor="hand2", width=16,
                  command=lambda: self._add_region("mute")).pack(side="left", padx=4)

        tk.Button(ar1, text=t("waveform.boost_button"), bg=CLR["green"], fg="white",
                  font=(UI_FONT, 10, "bold"), cursor="hand2", width=16,
                  command=lambda: self._add_region("boost")).pack(side="left", padx=4)

        tk.Button(ar1, text=t("waveform.duck_button"), bg=CLR["orange"], fg="white",
                  font=(UI_FONT, 10, "bold"), cursor="hand2", width=16,
                  command=lambda: self._add_region("duck")).pack(side="left", padx=4)

        tk.Label(ar1, text=t("waveform.amount_label"), font=(UI_FONT, 10)).pack(side="left", padx=(20, 0))
        self._vol_adj = tk.StringVar(value="6")
        tk.Entry(ar1, textvariable=self._vol_adj, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(ar1, text=t("waveform.db_label"), fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # ── Region list ───────────────────────────────────────────────────
        reg_lf = tk.LabelFrame(self, text=f"  {t('waveform.applied_regions_section')}  ", padx=10, pady=6,
                               font=(UI_FONT, 9, "bold"))
        reg_lf.pack(fill="x", padx=20, pady=4)

        self._region_list = tk.Listbox(
            reg_lf, bg=CLR["console_bg"], fg=CLR["console_fg"],
            font=(MONO_FONT, 9), height=4, relief="flat", bd=0)
        self._region_list.pack(fill="x", side="left", expand=True)
        reg_btn_f = tk.Frame(reg_lf)
        reg_btn_f.pack(side="right", padx=6)
        tk.Button(reg_btn_f, text=t("batch_joiner.btn_remove"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._remove_region).pack(pady=2)
        tk.Button(reg_btn_f, text=t("waveform.clear_all"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2",
                  command=self._clear_regions).pack(pady=2)

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
        self._export_mode = tk.StringVar(value="video")
        tk.Radiobutton(opt_f, text=t("waveform.export_video_option"),
                       variable=self._export_mode, value="video",
                       font=(UI_FONT, 10)).pack(side="left", padx=(0, 20))
        tk.Radiobutton(opt_f, text=t("waveform.export_audio_option"),
                       variable=self._export_mode, value="audio",
                       font=(UI_FONT, 10)).pack(side="left")

        # ── Run ───────────────────────────────────────────────────────────
        self._btn_run = tk.Button(
            self, text=t("waveform.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack(pady=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Waveform analysis ─────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.aac *.flac *.m4a"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self._src_var.set(p)
            self.duration = get_video_duration(p)
            self._info_lbl.config(text=_fmt(self.duration))
            self._mark_in = 0.0
            self._mark_out = self.duration
            self._in_lbl.config(text=_fmt(0))
            self._out_lbl.config(text=_fmt(self.duration))

    def _browse_out(self):
        ext = ".mp4" if self._export_mode.get() == "video" else ".mp3"
        p = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[("MP4", "*.mp4"), ("MP3", "*.mp3"),
                       ("WAV", "*.wav"), ("All", t("ducker.item_2"))])
        if p:
            self._out_var.set(p)

    def _analyze(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("waveform.no_file_message"))
            return

        self._btn_analyze.config(state="disabled", text=t("waveform.analyzing"))
        self.log(self.console, t("log.waveform.extracting_waveform_data"))

        def _worker():
            try:
                tmp_wav = os.path.join(tempfile.gettempdir(), "_xfpro_waveform.wav")
                ffmpeg = get_binary_path("ffmpeg")

                # Extract audio as low-res wav for visualization
                cmd = [ffmpeg, "-i", self.file_path,
                       "-ac", "1", "-ar", "8000",
                       "-sample_fmt", "s16",
                       tmp_wav, "-y"]
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      creationflags=CREATE_NO_WINDOW, timeout=120)

                # Read WAV peaks
                peaks = []
                with wave.open(tmp_wav, 'rb') as wf:
                    n_frames = wf.getnframes()
                    sample_width = wf.getsampwidth()
                    raw = wf.readframes(n_frames)

                    # Downsample to ~800 visual bins
                    n_bins = 800
                    frames_per_bin = max(1, n_frames // n_bins)

                    for i in range(n_bins):
                        start = i * frames_per_bin * sample_width
                        end = start + frames_per_bin * sample_width
                        chunk = raw[start:end]

                        if len(chunk) < sample_width:
                            peaks.append(0)
                            continue

                        # Get peak amplitude in this bin
                        max_val = 0
                        for j in range(0, len(chunk) - 1, sample_width):
                            val = abs(struct.unpack_from('<h', chunk, j)[0])
                            if val > max_val:
                                max_val = val
                        peaks.append(max_val)

                self._waveform_data = peaks

                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass

                self.after(0, self._draw_waveform)
                self.after(0, lambda: self.log(self.console, f"Waveform loaded: {len(peaks)} bins"))
            except Exception as e:
                self.after(0, lambda: self.log(self.console, f"Error: {e}"))
            finally:
                self.after(0, lambda: self._btn_analyze.config(
                    state="normal", text=t("waveform.analyze")))

        self.run_in_thread(_worker)

    def _draw_waveform(self):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10:
            return

        mid = h // 2

        if not self._waveform_data:
            c.create_text(w // 2, mid, text="Click 'Analyze' to load waveform",
                          fill=CLR["fgdim"], font=(UI_FONT, 11))
            return

        # Draw center line
        c.create_line(0, mid, w, mid, fill="#333333", width=1)

        # Draw waveform
        max_peak = max(self._waveform_data) if self._waveform_data else 1
        if max_peak == 0:
            max_peak = 1

        n = len(self._waveform_data)
        bar_w = max(1, w / n)

        for i, peak in enumerate(self._waveform_data):
            x = int(i * w / n)
            amp = int((peak / max_peak) * (mid - 8))
            color = CLR["accent"]
            # Check if in a region
            t = (i / n) * self.duration if self.duration > 0 else 0
            for rs, re, act, val in self._regions:
                if rs <= t <= re:
                    if act == "mute":
                        color = CLR["red"]
                    elif act == "boost":
                        color = CLR["green"]
                    elif act == "duck":
                        color = CLR["orange"]
                    break

            c.create_line(x, mid - amp, x, mid + amp, fill=color, width=max(1, int(bar_w)))

        # Draw selection markers
        if self.duration > 0:
            in_x = int((self._mark_in / self.duration) * w)
            out_x = int((self._mark_out / self.duration) * w)

            # Selection region
            if out_x > in_x:
                c.create_rectangle(in_x, 0, out_x, h, fill="", outline=CLR["accent"],
                                   width=1, dash=(4, 2))

            # In marker (green)
            c.create_line(in_x, 0, in_x, h, fill=CLR["green"], width=2)
            c.create_text(in_x + 3, 10, text=f"IN {_fmt(self._mark_in)}",
                          fill=CLR["green"], font=(UI_FONT, 7, "bold"), anchor="w")

            # Out marker (red)
            c.create_line(out_x, 0, out_x, h, fill=CLR["red"], width=2)
            c.create_text(out_x - 3, 10, text=f"OUT {_fmt(self._mark_out)}",
                          fill=CLR["red"], font=(UI_FONT, 7, "bold"), anchor="e")

        # Time ticks
        if self.duration > 0:
            for i in range(11):
                tx = int(i * w / 10)
                t = self.duration * i / 10
                c.create_line(tx, h - 12, tx, h - 4, fill="#555555")
                c.create_text(tx, h - 2, text=_fmt(t), fill="#555555",
                              font=(UI_FONT, 6), anchor="s")

    def _on_click(self, ev):
        if self.duration <= 0:
            return
        w = self._canvas.winfo_width()
        t = (ev.x / w) * self.duration
        t = max(0.0, min(t, self.duration))
        self._mark_in = t
        self._in_lbl.config(text=_fmt(t))
        self._update_sel()
        self._draw_waveform()

    def _on_shift_click(self, ev):
        if self.duration <= 0:
            return
        w = self._canvas.winfo_width()
        t = (ev.x / w) * self.duration
        t = max(0.0, min(t, self.duration))
        self._mark_out = t
        self._out_lbl.config(text=_fmt(t))
        self._update_sel()
        self._draw_waveform()

    def _update_sel(self):
        sel = abs(self._mark_out - self._mark_in)
        self._sel_lbl.config(text=f"{sel:.2f}s")

    # ── Region management ─────────────────────────────────────────────
    def _add_region(self, action):
        s = min(self._mark_in, self._mark_out)
        e = max(self._mark_in, self._mark_out)
        if e - s < 0.01:
            messagebox.showwarning(t("waveform.no_selection_title"), t("waveform.no_selection_message"))
            return
        try:
            vol = float(self._vol_adj.get())
        except ValueError:
            vol = 6.0

        self._regions.append((s, e, action, vol))
        label = {"mute": "MUTE", "boost": f"BOOST +{vol}dB", "duck": f"DUCK -{vol}dB"}
        self._region_list.insert("end",
            f"  {_fmt(s)} → {_fmt(e)}  [{label.get(action, action)}]")
        self._draw_waveform()
        self.log(self.console, f"Region added: {label.get(action)} at {_fmt(s)} → {_fmt(e)}")

    def _remove_region(self):
        sel = self._region_list.curselection()
        if sel:
            idx = sel[0]
            self._region_list.delete(idx)
            if idx < len(self._regions):
                self._regions.pop(idx)
            self._draw_waveform()

    def _clear_regions(self):
        self._regions.clear()
        self._region_list.delete(0, "end")
        self._draw_waveform()

    # ── Render ────────────────────────────────────────────────────────
    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("common.no_input"))
            return
        if not self._regions:
            messagebox.showwarning(t("waveform.no_regions_title"), t("waveform.no_regions_message"))
            return

        out = self._out_var.get().strip()
        if not out:
            ext = ".mp4" if self._export_mode.get() == "video" else ".mp3"
            out = filedialog.asksaveasfilename(
                defaultextension=ext,
                filetypes=[("MP4", "*.mp4"), ("MP3", "*.mp3"), ("WAV", "*.wav")])
        if not out:
            return
        self._out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg")

        # Build audio filter chain
        af_parts = []
        for s, e, action, val in self._regions:
            if action == "mute":
                af_parts.append(f"volume=enable='between(t,{s},{e})':volume=0")
            elif action == "boost":
                af_parts.append(f"volume=enable='between(t,{s},{e})':volume={val}dB")
            elif action == "duck":
                af_parts.append(f"volume=enable='between(t,{s},{e})':volume=-{val:.1f}dB")

        af = ",".join(af_parts)

        if self._export_mode.get() == "video":
            cmd = [ffmpeg, "-i", self.file_path,
                   "-af", af, t("dynamics.c_v"), "copy",
                   t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                   "-movflags", t("dynamics.faststart"), out, "-y"]
        else:
            cmd = [ffmpeg, "-i", self.file_path,
                   "-af", af, "-vn", out, "-y"]

        self.log(self.console, f"Applying {len(self._regions)} region(s)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label=t("waveform.apply_button"))
