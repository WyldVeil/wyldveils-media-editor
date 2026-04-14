"""
tab_autosubs.py  ─  Auto-Subtitles (Speech-to-Text)
Generates subtitle files from any video using OpenAI Whisper.
Whisper runs 100% locally - no internet, no API key needed.

Workflow:
  1. Load video
  2. Choose Whisper model (tiny → large)
  3. Choose language (or auto-detect)
  4. Generate → get an SRT file
  5. Optionally burn the SRT into the video immediately

Requires:  pip install openai-whisper
           (also needs ffmpeg on PATH or in bin/)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import subprocess
import threading
import os
import sys
import shutil

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW, open_in_explorer
from core.i18n import t


# ── Whisper model info ────────────────────────────────────────────────────
MODELS = {
    t("auto_subs.tiny_75_mb_fastest_lowest_accuracy"):   "tiny",
    t("auto_subs.base_150_mb_fast_decent_accuracy"):      "base",
    t("auto_subs.small_490_mb_good_balance"):               "small",
    t("auto_subs.medium_1_5_gb_great_accuracy_slower"):     "medium",
    t("auto_subs.large_3_1_gb_best_accuracy_slowest"):     "large",
    t("auto_subs.large_v2_3_1_gb_best_recommended"):         "large-v2",
    t("auto_subs.large_v3_3_1_gb_latest"):                    "large-v3",
}

LANGUAGES = [
    "auto-detect",
    "English", "Spanish", "French", "German", "Italian", "Portuguese",
    "Dutch", "Russian", "Chinese", "Japanese", "Korean", "Arabic",
    "Hindi", "Turkish", "Polish", "Swedish", "Norwegian", "Danish",
    "Finnish", "Czech", "Romanian", "Hungarian", "Ukrainian",
]

LANG_CODES = {
    "auto-detect": None, "English": "en", "Spanish": "es", "French": "fr",
    "German": "de", "Italian": "it", "Portuguese": "pt", "Dutch": "nl",
    "Russian": "ru", "Chinese": "zh", "Japanese": "ja", "Korean": "ko",
    "Arabic": "ar", "Hindi": "hi", "Turkish": "tr", "Polish": "pl",
    "Swedish": "sv", "Norwegian": "no", "Danish": "da", "Finnish": "fi",
    "Czech": "cs", "Romanian": "ro", "Hungarian": "hu", "Ukrainian": "uk",
}

OUTPUT_FORMATS = ["srt", "vtt", "txt", "tsv", "json"]


def _whisper_available():
    try:
        import whisper
        return True, whisper.__version__ if hasattr(whisper, "__version__") else "installed"
    except ImportError:
        return False, None


def _faster_whisper_available():
    try:
        import faster_whisper
        return True
    except ImportError:
        return False


class AutoSubsTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path   = ""
        self._cancel     = threading.Event()
        self._srt_path   = ""
        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="💬  " + t("tab.auto_subtitles"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("auto_subs.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Whisper status banner ─────────────────────────────────────────
        self.status_banner = tk.Frame(self, bg="#1A2A1A", relief="groove", bd=1)
        self.status_banner.pack(fill="x", padx=16, pady=(8, 4))
        self.whisper_lbl = tk.Label(self.status_banner,
                                     text=t("karaoke.checking_for_whisper"),
                                     bg="#1A2A1A", fg=CLR["fgdim"],
                                     font=(MONO_FONT, 9))
        self.whisper_lbl.pack(side="left", padx=12, pady=6)
        tk.Button(self.status_banner, text=t("auto_subs.install_whisper_button"),
                  bg="#2E7D32", fg="white",
                  command=self._install_whisper).pack(side="right", padx=8, pady=4)

        self.after(100, self._check_whisper)

        # ── Source file ───────────────────────────────────────────────────
        sf = tk.Frame(self); sf.pack(pady=8)
        tk.Label(sf, text=t("auto_subs.source_video_audio"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Options ───────────────────────────────────────────────────────
        opts = tk.LabelFrame(self, text=t("auto_subs.transcription_section"), padx=14, pady=10)
        opts.pack(fill="x", padx=16, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("auto_subs.whisper_model_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.model_var = tk.StringVar(value=list(MODELS.keys())[2])  # small default
        model_cb = ttk.Combobox(r0, textvariable=self.model_var,
                                 values=list(MODELS.keys()),
                                 state="readonly", width=46)
        model_cb.pack(side="left", padx=8)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("common.language"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.lang_var = tk.StringVar(value="auto-detect")
        ttk.Combobox(r1, textvariable=self.lang_var, values=LANGUAGES,
                     state="readonly", width=18).pack(side="left", padx=8)
        tk.Label(r1, text=t("auto_subs.output_format_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.fmt_var = tk.StringVar(value="srt")
        ttk.Combobox(r1, textvariable=self.fmt_var, values=OUTPUT_FORMATS,
                     state="readonly", width=6).pack(side="left", padx=8)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        self.translate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r2,
                       text=t("auto_subs.translate_checkbox"),
                       variable=self.translate_var).pack(side="left")

        r3 = tk.Frame(opts); r3.pack(fill="x", pady=4)
        tk.Label(r3, text=t("auto_subs.word_level_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.word_ts_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text=t("auto_subs.word_enabled_option"),
                       variable=self.word_ts_var).pack(side="left", padx=8)

        r4 = tk.Frame(opts); r4.pack(fill="x", pady=4)
        tk.Label(r4, text=t("auto_subs.max_segment_label"),
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        self.max_words_var = tk.StringVar(value="0")
        ttk.Combobox(r4, textvariable=self.max_words_var,
                     values=[t("auto_subs.0_auto"), "5", "8", "10", "12", "15"],
                     state="normal", width=10).pack(side="left", padx=8)
        tk.Label(r4, text=t("auto_subs.max_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Output SRT path ───────────────────────────────────────────────
        srt_f = tk.Frame(self); srt_f.pack(pady=4)
        tk.Label(srt_f, text=t("auto_subs.save_subtitles_as"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.srt_var = tk.StringVar()
        tk.Entry(srt_f, textvariable=self.srt_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(srt_f, text=t("btn.browse"), command=self._browse_srt, cursor="hand2", relief="flat").pack(side="left")

        # ── Burn-in option ────────────────────────────────────────────────
        burn_lf = tk.LabelFrame(self, text=t("auto_subs.burn_section"),
                                 padx=14, pady=8)
        burn_lf.pack(fill="x", padx=16, pady=4)

        b0 = tk.Frame(burn_lf); b0.pack(fill="x")
        self.burn_var = tk.BooleanVar(value=False)
        tk.Checkbutton(b0, text=t("auto_subs.burn_checkbox"),
                       variable=self.burn_var,
                       command=self._toggle_burn).pack(side="left")

        self.burn_opts_f = tk.Frame(burn_lf)
        tk.Label(self.burn_opts_f, text=t("auto_subs.burned_video_output")).pack(side="left")
        self.burned_out_var = tk.StringVar()
        tk.Entry(self.burn_opts_f, textvariable=self.burned_out_var,
                 width=48).pack(side="left", padx=6)
        tk.Button(self.burn_opts_f, text="…",
                  command=self._browse_burned_out, width=2).pack(side="left")

        # Style options for burn
        self.burn_style_f = tk.Frame(burn_lf)
        for label, attr, default in [
            ("Font size:", "burn_size_var", "24"),
            ("CRF:",       "burn_crf_var",  "18"),
        ]:
            tk.Label(self.burn_style_f, text=label).pack(side="left", padx=(8, 0))
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            tk.Entry(self.burn_style_f, textvariable=var, width=5, relief="flat").pack(side="left", padx=4)

        # ── Action buttons ────────────────────────────────────────────────
        btn_row = tk.Frame(self); btn_row.pack(pady=10)
        self.btn_generate = tk.Button(
            btn_row, text=t("auto_subs.generate_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#7B1FA2", fg="white",
            height=2, width=26,
            command=self._generate)
        self.btn_generate.pack(side="left", padx=8)

        self.btn_burn_only = tk.Button(
            btn_row, text=t("auto_subs.burn_only_button"),
            font=(UI_FONT, 10),
            bg=CLR["orange"], fg="white",
            height=2, width=16,
            command=self._burn_only)
        self.btn_burn_only.pack(side="left", padx=8)

        tk.Button(btn_row, text=t("auto_subs.open_srt"),
                  font=(UI_FONT, 10), bg=CLR["panel"], fg=CLR["fg"],
                  height=2, width=12,
                  command=self._open_srt).pack(side="left", padx=4)

        # Progress
        self.prog_lbl = tk.Label(self, text="", fg=CLR["accent"],
                                  font=(UI_FONT, 10, "bold"))
        self.prog_lbl.pack()
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=600)
        self.progress.pack(pady=2)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=6)
        self.console, csb = self.make_console(cf, height=9)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    def _toggle_burn(self):
        if self.burn_var.get():
            self.burn_opts_f.pack(fill="x", pady=4)
            self.burn_style_f.pack(anchor="w", pady=2)
        else:
            self.burn_opts_f.pack_forget()
            self.burn_style_f.pack_forget()

    def _check_whisper(self):
        ok, ver = _whisper_available()
        fw = _faster_whisper_available()
        if ok:
            self.whisper_lbl.config(
                text=f"✅  openai-whisper {ver} detected and ready.",
                fg=CLR["green"], bg="#1A2A1A")
            self.status_banner.config(bg="#1A2A1A")
        elif fw:
            self.whisper_lbl.config(
                text=t("auto_subs.faster_whisper_detected_and_ready"),
                fg=CLR["green"], bg="#1A2A1A")
        else:
            self.whisper_lbl.config(
                text=t("auto_subs.whisper_not_found"),
                fg=CLR["orange"], bg="#2A1A00")
            self.status_banner.config(bg="#2A1A00")

    def _install_whisper(self):
        self.log(self.console, t("log.auto_subs.installing_openai_whisper_this_may_take_a_few_minu"))
        self.log(self.console, t("log.auto_subs.pip_install_openai_whisper"))

        def _work():
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "openai-whisper"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
            for line in iter(proc.stdout.readline, ""):
                self.log(self.console, line.rstrip())
            proc.stdout.close(); proc.wait()
            self.after(0, self._check_whisper)
            if proc.returncode == 0:
                self.log(self.console, t("log.auto_subs.installation_complete"))
            else:
                self.log(self.console, t("log.auto_subs.installation_failed_try_running_pip_manually"))

        self.run_in_thread(_work)

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.flac"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.srt_var.set(base + ".srt")
            self.burned_out_var.set(base + "_subtitled.mp4")

    def _browse_srt(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".srt",
            filetypes=[("SRT", "*.srt"), ("VTT", "*.vtt"), ("Text", "*.txt")])
        if p: self.srt_var.set(p)

    def _browse_burned_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.burned_out_var.set(p)

    def _open_srt(self):
        srt = self.srt_var.get().strip()
        if srt and os.path.exists(srt):
            open_in_explorer(srt)
        else:
            messagebox.showinfo(t("common.warning"), "Generate subtitles first.")

    # ─────────────────────────────────────────────────────────────────────
    def _generate(self):
        src = self.src_var.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), t("auto_subs.no_file_message"))
            return

        ok, _ = _whisper_available()
        fw    = _faster_whisper_available()
        if not ok and not fw:
            messagebox.showerror(
                t("msg.whisper_not_installed_title"),
                t("msg.whisper_not_installed"))
            return

        srt_out = self.srt_var.get().strip()
        if not srt_out:
            base    = os.path.splitext(src)[0]
            srt_out = base + ".srt"
            self.srt_var.set(srt_out)

        self._cancel.clear()
        self.btn_generate.config(state="disabled", text=t("auto_subs.transcribing"))
        self.progress.start(10)
        self.prog_lbl.config(text=t("auto_subs.loading_model"))
        self.console.delete("1.0", tk.END)

        self.run_in_thread(self._transcribe_worker, src, srt_out, ok)

    def _transcribe_worker(self, src, srt_out, use_openai_whisper):
        try:
            model_label = self.model_var.get()
            model_name  = MODELS[model_label]
            lang        = LANG_CODES.get(self.lang_var.get())
            translate   = self.translate_var.get()
            fmt         = self.fmt_var.get()

            self._log(f"Model:    {model_name}")
            self._log(f"Language: {self.lang_var.get()}")
            self._log(f"Task:     {'translate' if translate else 'transcribe'}")
            self._log(f"Format:   {fmt}")
            self._log("")
            self._log(t("log.auto_subs.loading_model_first_run_downloads_weights_subseque"))

            import whisper

            self._status("Loading model…")
            model = whisper.load_model(model_name)
            self._log(f"✅  Model loaded.")
            self._status("Transcribing…")
            self._log(t("log.auto_subs.transcribing_audio_this_may_take_a_while_for_long"))

            options = {
                "task": "translate" if translate else "transcribe",
                "verbose": True,
            }
            if lang:
                options["language"] = lang

            max_words = self.max_words_var.get().replace(" (auto)", "").strip()
            if max_words and max_words != "0":
                options["word_timestamps"] = True
                options["max_words_per_segment"] = int(max_words)
            elif self.word_ts_var.get():
                options["word_timestamps"] = True

            result = model.transcribe(src, **options)

            # Write output
            out_dir  = os.path.dirname(srt_out)
            base_name= os.path.splitext(os.path.basename(srt_out))[0]

            writer = whisper.utils.get_writer(fmt, out_dir)
            writer(result, base_name)

            # whisper writes to <out_dir>/<base_name>.<fmt>
            written = os.path.join(out_dir, f"{base_name}.{fmt}")

            # Rename to what the user asked for if different
            if written != srt_out and os.path.exists(written):
                shutil.move(written, srt_out)

            self._log(f"\n✅  Subtitles saved to:\n   {srt_out}")
            self._srt_path = srt_out
            self._status("Done!")

            # Burn in if requested
            if self.burn_var.get():
                self.after(0, lambda: self._burn_srt_into_video(srt_out))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Done", f"Subtitles generated!\n\n{srt_out}"))

        except Exception as e:
            self._log(f"\n❌  Error: {e}")
            self._log(t("log.karaoke.ntroubleshooting"))
            self._log(t("log.auto_subs.make_sure_ffmpeg_is_in_your_path_or_the_app_s_bin"))
            self._log(t("log.auto_subs.for_gpu_acceleration_pip_install_torch_torchvisio"))
            self._log(t("log.auto_subs.try_a_smaller_model_tiny_or_base_for_speed"))
            self.after(0, lambda: messagebox.showerror(t("common.error"), str(e)))
        finally:
            self.after(0, self._finish_generate)

    def _finish_generate(self):
        self.btn_generate.config(state="normal", text=t("auto_subs.generate_subtitles"))
        self.progress.stop()
        self.prog_lbl.config(text="")

    def _burn_only(self):
        """Burn an existing SRT into the video without re-transcribing."""
        srt = self.srt_var.get().strip()
        src = self.src_var.get().strip()
        if not src:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not srt or not os.path.exists(srt):
            srt = filedialog.askopenfilename(
                filetypes=[("Subtitles", "*.srt *.ass *.vtt"), ("All", t("ducker.item_2"))])
        if not srt: return
        self.srt_var.set(srt)
        self._burn_srt_into_video(srt)

    def _burn_srt_into_video(self, srt_path):
        src = self.src_var.get().strip()
        out = self.burned_out_var.get().strip()
        if not out:
            base = os.path.splitext(src)[0]
            out  = base + "_subtitled.mp4"
            self.burned_out_var.set(out)

        ffmpeg    = get_binary_path("ffmpeg.exe")
        safe_srt  = srt_path.replace("\\", "/").replace(":", "\\:")
        font_size = self.burn_size_var.get() if hasattr(self, "burn_size_var") else "24"
        crf       = self.burn_crf_var.get()  if hasattr(self, "burn_crf_var")  else "18"

        style = (f"FontSize={font_size},PrimaryColour=&HFFFFFF&,"
                 f"OutlineColour=&H000000&,Outline=2,Alignment=2,MarginV=20")
        vf = f"subtitles='{safe_srt}':force_style='{style}'"

        cmd = [ffmpeg, "-i", src, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self._log(f"\nBurning subtitles → {os.path.basename(out)}")
        self.progress.start(10)
        self.btn_generate.config(state="disabled")

        def done(rc):
            self.progress.stop()
            self.btn_generate.config(state="normal", text=t("auto_subs.generate_subtitles"))
            self.show_result(rc, out)

        self.run_ffmpeg(cmd, self.console, on_done=done,
                        btn=None)

    def _log(self, msg):
        self.after(0, lambda m=msg: [
            self.console.insert(tk.END, m + "\n"),
            self.console.see(tk.END)])

    def _status(self, msg):
        self.after(0, lambda m=msg: self.prog_lbl.config(text=m))
