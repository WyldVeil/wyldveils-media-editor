"""
tab_karaoke.py  ─  Karaoke Video Generator

Turns any music video into a singalong karaoke track in three steps:
  1. Whisper (word_timestamps=True) transcribes every word with precise timing.
  2. An ASS subtitle file is built using \\kf (fill-karaoke) tags so that each
     word's colour animates left-to-right as it is sung - yellow = upcoming,
     green = filling in as you sing it.  Standard karaoke machine behaviour.
  3. FFmpeg renders the final video:
       • Centre-channel vocal cancellation removes the lead vocals
       • curves filter darkens the video for legibility
       • ass= filter burns the karaoke subtitles at the bottom of the frame
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import threading
import os
import sys
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ── Constants ─────────────────────────────────────────────────────────────────

MODELS = {
    t("karaoke.tiny_75_mb_fastest_rough"):  "tiny",
    t("karaoke.base_150_mb_fast_decent"):    "base",
    t("karaoke.small_490_mb_balanced"):        "small",
    t("karaoke.medium_1_5_gb_accurate"):        "medium",
    t("karaoke.large_v3_3_1_gb_best"):           "large-v3",
}

LANGUAGES = [
    "auto-detect", "English", "Spanish", "French", "German", "Italian",
    "Portuguese", "Dutch", "Russian", "Chinese", "Japanese", "Korean",
    "Arabic", "Hindi", "Turkish", "Polish",
]

LANG_CODES = {
    "auto-detect": None, "English": "en", "Spanish": "es", "French": "fr",
    "German": "de",      "Italian": "it", "Portuguese": "pt", "Dutch": "nl",
    "Russian": "ru",     "Chinese": "zh", "Japanese": "ja",  "Korean": "ko",
    "Arabic": "ar",      "Hindi": "hi",   "Turkish": "tr",   "Polish": "pl",
}

# ASS colours are &HAABBGGRR  (AA=alpha 00=opaque, then BGR, then R last)
ASS_COLOURS = {
    "Yellow":  "&H0000FFFF",   # #FFFF00
    "White":   "&H00FFFFFF",   # #FFFFFF
    "Cyan":    "&H00FFFF00",   # #00FFFF
    "Green":   "&H0000FF00",   # #00FF00
    "Pink":    "&H008080FF",   # #FF8080 - soft pink, readable
    "Orange":  "&H000080FF",   # #FF8000
}


# ── ASS builder ───────────────────────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    """Format seconds → ASS timestamp  H:MM:SS.cs"""
    total_cs = int(round(seconds * 100))
    cs  = total_cs % 100
    s   = (total_cs // 100) % 60
    m   = (total_cs // 6000) % 60
    h   = total_cs // 360000
    return "{:d}:{:02d}:{:02d}.{:02d}".format(h, m, s, cs)


def _build_ass(segments, path, font_size, primary, secondary,
               res_x=1920, res_y=1080):
    """
    Write an ASS karaoke file.

    primary   = colour that fills in as the word is sung  (e.g. green)
    secondary = colour of words waiting to be sung         (e.g. yellow)

    Each Dialogue line uses \\kf<cs> tags (fill karaoke, centiseconds).
    The fill animation sweeps left-to-right within each word as it is sung,
    which is exactly what you see on a real karaoke machine.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        "PlayResX: {rx}\n"
        "PlayResY: {ry}\n"
        "Timer: 100.0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Bold=-1 (yes), Alignment=2 (bottom-centre), Outline=3, Shadow=1
        "Style: Karaoke,Arial,{fs},{pri},{sec},&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,40,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text\n"
    ).format(rx=res_x, ry=res_y, fs=font_size, pri=primary, sec=secondary)

    dialogue_lines = []

    for seg in segments:
        words = seg.get("words") or []

        if not words:
            # No word-level data - treat whole segment as one karaoke block
            text = seg.get("text", "").strip()
            if not text:
                continue
            t0, t1 = seg["start"], seg["end"]
            dur_cs = max(1, int(round((t1 - t0) * 100)))
            dialogue_lines.append(
                "Dialogue: 0,{s},{e},Karaoke,,0,0,0,,{{\\kf{d}}}{t}\n".format(
                    s=_ass_time(t0), e=_ass_time(t1), d=dur_cs, t=text)
            )
            continue

        # Build the \\kf chain, accounting for silence gaps between words
        seg_start = words[0]["start"]
        seg_end   = words[-1]["end"]
        prev_end  = seg_start
        parts     = []

        for w in words:
            w_start   = w.get("start", prev_end)
            w_end     = w.get("end",   w_start + 0.1)
            word_text = w.get("word",  "")

            # Silence/gap before this word
            gap_cs = max(0, int(round((w_start - prev_end) * 100)))
            if gap_cs > 0:
                # Invisible gap token - keeps timing aligned
                parts.append("{{\\kf{}}} ".format(gap_cs))

            dur_cs = max(1, int(round((w_end - w_start) * 100)))
            parts.append("{{\\kf{}}}{}".format(dur_cs, word_text))
            prev_end = w_end

        text_body = "".join(parts)
        dialogue_lines.append(
            "Dialogue: 0,{s},{e},Karaoke,,0,0,0,,{t}\n".format(
                s=_ass_time(seg_start),
                e=_ass_time(seg_end),
                t=text_body,
            )
        )

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.writelines(dialogue_lines)

    return len(dialogue_lines)


# ── Tab ───────────────────────────────────────────────────────────────────────

def _whisper_ok():
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


class KaraokeTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._build_ui()

    # ─── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎤  " + t("tab.karaoke_generator"),
                 font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner,
                 text=t("karaoke.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Whisper status banner ──────────────────────────────────────────
        self._banner = tk.Frame(self, bg="#1A2A1A", relief="groove", bd=1)
        self._banner.pack(fill="x", padx=16, pady=(8, 4))
        self._whisper_lbl = tk.Label(
            self._banner, text=t("karaoke.checking_for_whisper"),
            bg="#1A2A1A", fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._whisper_lbl.pack(side="left", padx=12, pady=6)
        tk.Button(self._banner, text=t("karaoke.install_whisper_button"),
                  bg="#2E7D32", fg="white",
                  command=self._install_whisper).pack(side="right", padx=8, pady=4)
        self.after(120, self._check_whisper)

        # ── Source ────────────────────────────────────────────────────────
        r1 = tk.Frame(self)
        r1.pack(fill="x", padx=16, pady=8)
        tk.Label(r1, text=t("karaoke.music_video_label"),
                 font=(UI_FONT, 10, "bold"), width=16, anchor="e").pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(r1, textvariable=self._src_var, width=60,
                 relief="flat").pack(side="left", padx=8)
        tk.Button(r1, text=t("btn.browse"), command=self._browse_src,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Settings ──────────────────────────────────────────────────────
        sf = tk.LabelFrame(self, text=f"  {t('karaoke.karaoke_settings_section')}  ", padx=16, pady=10)
        sf.pack(fill="x", padx=20, pady=6)

        # Whisper model + language
        ra = tk.Frame(sf); ra.pack(fill="x", pady=3)
        tk.Label(ra, text=t("karaoke.whisper_model_label"), width=16, anchor="e").pack(side="left")
        self._model_var = tk.StringVar(value=list(MODELS.keys())[2])
        ttk.Combobox(ra, textvariable=self._model_var,
                     values=list(MODELS.keys()),
                     state="readonly", width=34).pack(side="left", padx=8)
        tk.Label(ra, text=t("karaoke.language")).pack(side="left")
        self._lang_var = tk.StringVar(value="auto-detect")
        ttk.Combobox(ra, textvariable=self._lang_var, values=LANGUAGES,
                     state="readonly", width=14).pack(side="left", padx=8)

        # Video darkness
        rb = tk.Frame(sf); rb.pack(fill="x", pady=3)
        tk.Label(rb, text=t("karaoke.video_darkness_label"), width=16, anchor="e").pack(side="left")
        self._darkness = tk.DoubleVar(value=0.28)
        tk.Scale(rb, variable=self._darkness, from_=0.05, to=0.65,
                 resolution=0.01, orient="horizontal",
                 length=200).pack(side="left", padx=8)
        self._dark_lbl = tk.Label(rb, text="", width=7, fg=CLR["accent"])
        self._dark_lbl.pack(side="left")
        self._darkness.trace_add("write", self._update_dark_lbl)
        self._update_dark_lbl()
        tk.Label(rb, text=t("karaoke.max_brightness_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=12)

        # Font size + colours
        rc = tk.Frame(sf); rc.pack(fill="x", pady=3)
        tk.Label(rc, text=t("karaoke.subtitle_font_label"), width=16, anchor="e").pack(side="left")
        self._font_size = tk.StringVar(value="72")
        tk.Entry(rc, textvariable=self._font_size, width=5,
                 relief="flat").pack(side="left", padx=(8, 16))
        tk.Label(rc, text=f"{t('karaoke.px_label')}   {t('karaoke.unsung_colour_label')}").pack(side="left")
        self._col_unsung = tk.StringVar(value="Yellow")
        ttk.Combobox(rc, textvariable=self._col_unsung,
                     values=list(ASS_COLOURS.keys()),
                     state="readonly", width=8).pack(side="left", padx=6)
        tk.Label(rc, text=f"  {t('karaoke.fill_colour_label')}").pack(side="left")
        self._col_sung = tk.StringVar(value="Green")
        ttk.Combobox(rc, textvariable=self._col_sung,
                     values=list(ASS_COLOURS.keys()),
                     state="readonly", width=8).pack(side="left", padx=6)
        tk.Label(rc, text=t("karaoke.colour_as_sung_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=8)

        # Vocal removal checkbox
        rd = tk.Frame(sf); rd.pack(fill="x", pady=3)
        self._rm_vocals = tk.BooleanVar(value=True)
        tk.Checkbutton(
            rd,
            text=t("karaoke.remove_vocals_checkbox"),
            variable=self._rm_vocals,
        ).pack(side="left")

        # ── Output ────────────────────────────────────────────────────────
        ro = tk.Frame(self)
        ro.pack(fill="x", padx=16, pady=6)
        tk.Label(ro, text=t("common.output_file"),
                 font=(UI_FONT, 10, "bold"), width=16, anchor="e").pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(ro, textvariable=self._out_var, width=60,
                 relief="flat").pack(side="left", padx=8)
        tk.Button(ro, text=t("common.save_as"), command=self._browse_out,
                  cursor="hand2", relief="flat").pack(side="left")

        # ── Action buttons ─────────────────────────────────────────────────
        btn_row = tk.Frame(self)
        btn_row.pack(pady=8)
        self._btn_go = tk.Button(
            btn_row, text=t("karaoke.generate_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#7B1FA2", fg="white",
            height=2, width=26,
            command=self._generate)
        self._btn_go.pack(side="left", padx=8)
        self._btn_stop = tk.Button(
            btn_row, text=t("btn.stop"),
            font=(UI_FONT, 10), bg=CLR["red"], fg="white",
            height=2, width=10, state="disabled",
            command=self._stop)
        self._btn_stop.pack(side="left", padx=4)

        # Progress
        self._prog_lbl = tk.Label(self, text="",
                                   fg=CLR["accent"], font=(UI_FONT, 10, "bold"))
        self._prog_lbl.pack()
        self._progress = ttk.Progressbar(self, mode="indeterminate", length=600)
        self._progress.pack(pady=2)

        # Console
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─── Helpers ──────────────────────────────────────────────────────────────
    def _update_dark_lbl(self, *_):
        pct = int(self._darkness.get() * 100)
        self._dark_lbl.config(text=t("karaoke.bright").format(pct))

    def _check_whisper(self):
        if _whisper_ok():
            self._whisper_lbl.config(
                text=t("karaoke.openai_whisper_detected_and_ready"),
                fg=CLR["green"], bg="#1A2A1A")
            self._banner.config(bg="#1A2A1A")
        else:
            self._whisper_lbl.config(
                text=t("karaoke.whisper_not_found"),
                fg=CLR["orange"], bg="#2A1A00")
            self._banner.config(bg="#2A1A00")

    def _install_whisper(self):
        self._log(t("log.karaoke.installing_openai_whisper_may_take_a_few_minutes"))

        def _work():
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "openai-whisper"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
            for line in iter(proc.stdout.readline, ""):
                self._log(line.rstrip())
            proc.stdout.close()
            proc.wait()
            self.after(0, self._check_whisper)
            if proc.returncode == 0:
                self._log(t("log.karaoke.whisper_installed_successfully"))
            else:
                self._log(t("log.karaoke.installation_failed_try_pip_install_openai_whisper"))

        self.run_in_thread(_work)

    def _browse_src(self):
        p = filedialog.askopenfilename(
            title="Select music video",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self._src_var.set(p)
            if not self._out_var.get():
                self._out_var.set(os.path.splitext(p)[0] + "_karaoke.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p:
            self._out_var.set(p)

    def _log(self, msg):
        self.after(0, lambda m=msg: [
            self.console.insert(tk.END, m + "\n"),
            self.console.see(tk.END),
        ])

    def _status(self, msg):
        self.after(0, lambda m=msg: self._prog_lbl.config(text=m))

    def _stop(self):
        self._cancel.set()
        self._log(t("log.karaoke.cancelling"))

    # ─── Generate ─────────────────────────────────────────────────────────────
    def _generate(self):
        src = self._src_var.get().strip()
        out = self._out_var.get().strip()

        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("karaoke.no_source_message"))
            return
        if not _whisper_ok():
            messagebox.showerror(
                t("karaoke.whisper_not_installed_title"),
                t("karaoke.install_first_message"))
            return
        if not out:
            out = filedialog.asksaveasfilename(
                defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        self._cancel.clear()
        self._btn_go.config(state="disabled", text=t("app.status.queued_btn"))
        self._btn_stop.config(state="normal")
        self._progress.start(10)
        self.console.delete("1.0", tk.END)

        _src, _out = src, out

        def _worker_fn(progress_cb, cancel_fn):
            # Bridge queue cancel to local flag so FFmpeg loop respects it
            if cancel_fn():
                self._cancel.set()
            self.after(0, lambda: self._btn_go.config(text=t("karaoke.working")))
            self._worker(_src, _out)
            return 1 if self._cancel.is_set() else 0

        self.enqueue_render("Karaoke", output_path=_out, worker_fn=_worker_fn)

    # ─── Background worker ────────────────────────────────────────────────────
    def _worker(self, src, out):
        tmp_dir  = tempfile.mkdtemp()
        ass_path = os.path.join(tmp_dir, "karaoke.ass")

        try:
            model_name = MODELS[self._model_var.get()]
            lang       = LANG_CODES.get(self._lang_var.get())
            darkness   = float(self._darkness.get())
            font_size  = max(12, int(self._font_size.get()))
            primary    = ASS_COLOURS.get(self._col_sung.get(),  ASS_COLOURS["Green"])
            secondary  = ASS_COLOURS.get(self._col_unsung.get(), ASS_COLOURS["Yellow"])
            rm_vocals  = self._rm_vocals.get()

            # ── Step 1: Transcribe ────────────────────────────────────────
            self._status("Step 1/3: Loading Whisper model…")
            self._log("▶ Loading Whisper '{}' …".format(model_name))
            self._log(t("log.karaoke.first_run_downloads_weights_subsequent_runs_are_i"))

            import whisper

            model = whisper.load_model(model_name)
            self._log(t("log.karaoke.model_loaded"))

            if self._cancel.is_set():
                return

            self._status("Step 1/3: Transcribing lyrics…")
            self._log(t("log.karaoke.transcribing_with_word_level_timestamps"))

            opts = {"task": "transcribe", "word_timestamps": True, "verbose": False}
            if lang:
                opts["language"] = lang

            result = model.transcribe(src, **opts)
            n_segs = len(result.get("segments", []))
            self._log("✅  Transcription done. {} lyric segments.".format(n_segs))

            if self._cancel.is_set():
                return

            # ── Step 2: Build ASS file ────────────────────────────────────
            self._status("Step 2/3: Building karaoke subtitles…")
            self._log(t("log.karaoke.generating_karaoke_ass_subtitle_file"))

            n_lines = _build_ass(
                result.get("segments", []),
                ass_path,
                font_size=font_size,
                primary=primary,
                secondary=secondary,
            )
            self._log("✅  ASS file ready. {} dialogue lines.".format(n_lines))

            if self._cancel.is_set():
                return

            # ── Step 3: FFmpeg render ─────────────────────────────────────
            self._status("Step 3/3: Rendering karaoke video…")
            self._log(t("log.karaoke.running_ffmpeg_darken_vocals_subtitles"))

            ffmpeg   = get_binary_path("ffmpeg.exe")
            # ASS path escaping for FFmpeg filter strings on Windows
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")

            # curves=  darkens the video: maps max brightness 1.0 → {darkness}
            # ass=     burns the karaoke subtitles
            vf = "curves=all='0/0 1/{d}',ass='{a}'".format(
                d=darkness, a=safe_ass)

            cmd = [ffmpeg, "-y", "-i", src]

            if rm_vocals:
                # Subtract right from left (and vice versa) to cancel
                # centre-panned vocals while keeping the stereo bed.
                # L_out = L_in - R_in,  R_out = R_in - L_in
                cmd += ["-af", "pan=stereo|c0=c0-c1|c1=c1-c0"]

            cmd += [
                "-vf", vf,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "256k",
                "-movflags", "+faststart",
                out,
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=CREATE_NO_WINDOW)

            for line in iter(proc.stdout.readline, ""):
                if self._cancel.is_set():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    self._log(t("log.karaoke.render_cancelled"))
                    break
                stripped = line.rstrip()
                if stripped:
                    self._log(stripped)

            proc.stdout.close()
            proc.wait()
            rc = proc.returncode

            if not self._cancel.is_set():
                self.after(0, lambda: self.show_result(rc, out))

        except ValueError:
            self._log(t("log.karaoke.font_size_must_be_a_whole_number"))
            self.after(0, lambda: messagebox.showerror(
                t("msg.bad_input_title"), t("msg.font_size_whole_number")))
        except Exception as exc:
            self._log("\n❌  Error: {}".format(exc))
            self._log(t("log.karaoke.ntroubleshooting"))
            self._log(t("log.karaoke.ensure_ffmpeg_is_in_the_app_s_bin_folder_or_on_pa"))
            self._log(t("log.karaoke.try_a_smaller_whisper_model_tiny_base_for_speed"))
            self._log(t("log.karaoke.gpu_acceleration_pip_install_torch_torchvision_to"))
            self.after(0, lambda e=exc: messagebox.showerror(
                "Karaoke generation failed", str(e)))
        finally:
            # Clean up temp ASS file
            try:
                if os.path.exists(ass_path):
                    os.remove(ass_path)
                os.rmdir(tmp_dir)
            except OSError:
                pass
            self.after(0, self._finish)

    def _finish(self):
        self._btn_go.config(state="normal", text=t("karaoke.generate_button"))
        self._btn_stop.config(state="disabled")
        self._progress.stop()
        self._status("")
