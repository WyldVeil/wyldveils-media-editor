"""
tab_reverser.py  ─  Video Reverser

Reverse video playback - full clip or a selected time range.
Options for reversing video only, audio only, or both.
Includes a "boomerang" mode (forward → reverse → forward loop)
popular in meme and reaction content.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os

from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW
from core.i18n import t


def _fmt(seconds):
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class ReverserTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.video_reverser"),
                         t("reverser.subtitle"),
                         icon="⏪")

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
        tl_lf = tk.LabelFrame(self, text=t("section.timeline"), padx=15, pady=8,
                               font=(UI_FONT, 9, "bold"))
        tl_lf.pack(fill="x", padx=20, pady=6)
        self._timeline = VideoTimeline(tl_lf, on_change=self._on_timeline_change,
                                       height=90, show_handles=True)
        self._timeline.pack(fill="x")

        # ── Mode ──────────────────────────────────────────────────────────
        mode_lf = tk.LabelFrame(self, text=t("reverser.reverse_mode_section"), padx=15, pady=10,
                                font=(UI_FONT, 9, "bold"))
        mode_lf.pack(fill="x", padx=20, pady=8)

        self._mode_var = tk.StringVar(value="full_reverse")
        modes = [
            ("full_reverse",  t("reverser.reverser_full_reverse_label"),
             t("reverser.reverser_full_reverse_desc")),
            ("range_reverse", t("reverser.reverser_range_reverse_label"),
             t("reverser.reverser_range_reverse_desc")),
            ("boomerang",     t("reverser.reverser_boomerang_label"),
             t("reverser.reverser_boomerang_desc")),
            ("ping_pong",     t("reverser.reverser_ping_pong_label"),
             t("reverser.reverser_ping_pong_desc")),
        ]
        for val, label, desc in modes:
            row = tk.Frame(mode_lf, bg=CLR["bg"])
            row.pack(fill="x", pady=2)
            tk.Radiobutton(row, text=label, variable=self._mode_var, value=val,
                           font=(UI_FONT, 10), command=self._on_mode,
                           bg=CLR["bg"]).pack(side="left")
            tk.Label(row, text=desc, fg=CLR["fgdim"], font=(UI_FONT, 9),
                     bg=CLR["bg"]).pack(side="left", padx=(8, 0))

        # ── Range frame (shown for range_reverse) ─────────────────────────
        self._range_f = tk.LabelFrame(self, text=t("section.time_range"), padx=15, pady=8,
                                      font=(UI_FONT, 9, "bold"))
        rr = tk.Frame(self._range_f)
        rr.pack(fill="x")
        tk.Label(rr, text=t("splitter.start_label"), font=(UI_FONT, 10)).pack(side="left")
        self._range_start = tk.StringVar(value="0.0")
        tk.Entry(rr, textvariable=self._range_start, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(rr, text=t("splitter.end_label"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._range_end = tk.StringVar(value="5.0")
        tk.Entry(rr, textvariable=self._range_end, width=10, relief="flat",
                 font=(MONO_FONT, 10)).pack(side="left", padx=6)
        tk.Label(rr, text=t("reverser.seconds"), fg=CLR["fgdim"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)

        # ── Ping-pong frame ───────────────────────────────────────────────
        self._pp_f = tk.LabelFrame(self, text=t("reverser.ping_pong_repeats_section"), padx=15, pady=8,
                                   font=(UI_FONT, 9, "bold"))
        ppr = tk.Frame(self._pp_f)
        ppr.pack(fill="x")
        tk.Label(ppr, text=t("reverser.loop_count_label"), font=(UI_FONT, 10)).pack(side="left")
        self._loop_count = tk.IntVar(value=3)
        tk.Spinbox(ppr, from_=2, to=20, textvariable=self._loop_count, width=5,
                   font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Label(ppr, text=t("reverser.loop_info"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # ── Options ───────────────────────────────────────────────────────
        opt_lf = tk.LabelFrame(self, text=t("section.options"), padx=15, pady=8,
                               font=(UI_FONT, 9, "bold"))
        opt_lf.pack(fill="x", padx=20, pady=6)

        or1 = tk.Frame(opt_lf)
        or1.pack(fill="x", pady=2)
        self._rev_video = tk.BooleanVar(value=True)
        tk.Checkbutton(or1, text=t("reverser.reverse_video_checkbox"), variable=self._rev_video,
                       font=(UI_FONT, 10)).pack(side="left", padx=(0, 20))
        self._rev_audio = tk.BooleanVar(value=True)
        tk.Checkbutton(or1, text=t("reverser.reverse_audio_checkbox"), variable=self._rev_audio,
                       font=(UI_FONT, 10)).pack(side="left", padx=(0, 20))
        self._strip_audio = tk.BooleanVar(value=False)
        tk.Checkbutton(or1, text=t("reverser.strip_audio_checkbox"),
                       variable=self._strip_audio,
                       font=(UI_FONT, 10)).pack(side="left")

        or2 = tk.Frame(opt_lf)
        or2.pack(fill="x", pady=4)
        tk.Label(or2, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(or2, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)
        tk.Label(or2, text=t("common.preset"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._preset_var = tk.StringVar(value="fast")
        ttk.Combobox(or2, textvariable=self._preset_var, width=12,
                     values=["ultrafast", "superfast", "veryfast", "faster",
                             "fast", "medium", "slow"],
                     state="readonly").pack(side="left", padx=6)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=8)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=58, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        tk.Button(bf, text=t("reverser.preview"), bg=CLR["accent"], fg="white",
                  width=18, font=(UI_FONT, 10), cursor="hand2",
                  command=self._preview).pack(side="left", padx=8)
        self._btn_run = tk.Button(
            bf, text=t("reverser.reverse_video"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack(side="left", padx=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_mode()

    def _on_mode(self):
        mode = self._mode_var.get()
        self._range_f.pack_forget()
        self._pp_f.pack_forget()
        if mode == "range_reverse":
            self._range_f.pack(fill="x", padx=20, pady=6)
        elif mode == "ping_pong":
            self._pp_f.pack(fill="x", padx=20, pady=6)

    def _on_timeline_change(self, start, end):
        self._range_start.set(str(round(start, 2)))
        self._range_end.set(str(round(end, 2)))

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
            self._range_end.set(str(round(min(5.0, self.duration), 2)))

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    def _get_output(self):
        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if out:
            self._out_var.set(out)
        return out

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        launch_preview(self.file_path)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self._get_output()
        if not out:
            return

        ffmpeg = get_binary_path("ffmpeg")
        mode = self._mode_var.get()
        crf = self._crf_var.get()
        preset = self._preset_var.get()
        strip = hasattr(self, '_strip_audio') and self._strip_audio.get()

        vf_parts = []
        af_parts = []

        if mode == "full_reverse":
            if self._rev_video.get():
                vf_parts.append("reverse")
            if self._rev_audio.get() and not strip:
                af_parts.append("areverse")
            self.log(self.console, t("log.reverser.full_reverse"))

        elif mode == "range_reverse":
            try:
                ss = float(self._range_start.get())
                ee = float(self._range_end.get())
            except ValueError:
                messagebox.showerror(t("reverser.bad_range_title"), t("reverser.bad_range_message"))
                return
            if ee <= ss:
                messagebox.showerror(t("reverser.bad_range_title"), t("reverser.bad_range_order"))
                return
            # Trim to range, then reverse
            cmd = [ffmpeg, "-ss", str(ss), "-to", str(ee), "-i", self.file_path]
            filt_v = "reverse"
            filt_a = "areverse" if self._rev_audio.get() and not strip else None
            cmd += ["-vf", filt_v]
            if filt_a:
                cmd += ["-af", filt_a]
            elif strip:
                cmd += ["-an"]
            cmd += ["-c:v", "libx264", "-crf", crf, "-preset", preset,
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out, "-y"]
            self.log(self.console, f"Range reverse: {_fmt(ss)} → {_fmt(ee)}")
            self.run_ffmpeg(cmd, self.console,
                            on_done=lambda rc: self.show_result(rc, out),
                            btn=self._btn_run, btn_label="⏪  REVERSE VIDEO")
            return

        elif mode == "boomerang":
            # Forward + reversed copy concatenated
            vf_parts = ["split[main][rev]",
                        "[rev]reverse[reversed]",
                        "[main][reversed]concat=n=2:v=1:a=0"]
            strip = True  # Boomerang typically has no audio
            self.log(self.console, t("log.reverser.boomerang_forward_reverse"))

        elif mode == "ping_pong":
            loops = self._loop_count.get()
            # Build a complex filter that ping-pongs
            vf_parts = [
                "split[main][rev]",
                "[rev]reverse[reversed]",
                f"[main][reversed]concat=n=2:v=1:a=0[ppout]",
                f"[ppout]loop=loop={loops - 1}:size=32767",
            ]
            strip = True
            self.log(self.console, f"Ping-pong × {loops}…")

        cmd = [ffmpeg, "-i", self.file_path]

        if mode in ("boomerang", "ping_pong"):
            cmd += ["-filter_complex", vf_parts[0] if len(vf_parts) == 1
                    else ";".join(vf_parts)]
        else:
            if vf_parts:
                cmd += ["-vf", ",".join(vf_parts)]
            if af_parts and not strip:
                cmd += ["-af", ",".join(af_parts)]

        if strip:
            cmd += ["-an"]
        else:
            if "-af" not in cmd and "-an" not in cmd:
                cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd += ["-c:v", "libx264", "-crf", crf, "-preset", preset,
                "-movflags", "+faststart", out, "-y"]

        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label="⏪  REVERSE VIDEO")
