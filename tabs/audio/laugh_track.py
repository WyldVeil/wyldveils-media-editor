"""
tab_laughtrack.py  ─  Laugh Track Remover

Remove or reduce canned laugh tracks from sitcoms using either
classic FFmpeg DSP filters, or state-of-the-art AI Stem Separation.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
import threading
import sys
import shutil

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, launch_preview, CREATE_NO_WINDOW, detect_gpu
)
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class LaughTrackRemoverTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.preview_proc = None
        self._ai_cancel_fn = None   # set when AI task is running in the queue
        
        # Determine paths
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.bin_dir = os.path.join(self.base_dir, 'bin')
        os.makedirs(self.bin_dir, exist_ok=True)
        
        # We assume Windows for the standalone exe download in this implementation
        self.ai_binary = os.path.join(self.bin_dir, "audio-separator.exe")
        
        self._build_ui()
        self._check_ai_tools()

    def _build_ui(self):
        self.make_header(
            self, t("tab.laugh_track_remover"),
            t("laugh_track.subtitle"))

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self)
        sf.pack(fill="x", padx=20, pady=(10, 4))
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")
        self._info_lbl = tk.Label(sf, text="", fg=CLR.get("fgdim", "#888888"),
                                  font=(MONO_FONT, 9))
        self._info_lbl.pack(side="left", padx=10)

        # ── Engine Selector ───────────────────────────────────────────────
        eng_f = tk.Frame(self)
        eng_f.pack(fill="x", padx=20, pady=(4, 8))
        tk.Label(eng_f, text=t("laugh_track.engine_section"), font=(UI_FONT, 10, "bold")).pack(side="left")

        self._engine_var = tk.StringVar(value="ffmpeg")
        tk.Radiobutton(eng_f, text=t("laugh_track.ffmpeg_option"),
                       variable=self._engine_var, value="ffmpeg",
                       font=(UI_FONT, 10), command=self._toggle_engine_ui).pack(side="left", padx=10)
        tk.Radiobutton(eng_f, text=t("laugh_track.ai_stem_option"),
                       variable=self._engine_var, value="ai",
                       font=(UI_FONT, 10, "bold"), fg=CLR.get("accent", "#0078D7"),
                       command=self._toggle_engine_ui).pack(side="left")

        # ── Engine Container Frame ────────────────────────────────────────
        # This prevents Tkinter layout crashes when swapping sections
        self.engine_container = tk.Frame(self)
        self.engine_container.pack(fill="x", pady=0)

        # ==================================================================
        # AI LAUGHTER REMOVAL SECTION
        # ==================================================================
        # 1. Added "Experimental" to the label frame
        self.ai_lf = tk.LabelFrame(self.engine_container, text=f"  {t('laugh_track.ai_experimental_option')}  ",
                                   padx=15, pady=10, font=(UI_FONT, 9, "bold"), fg=CLR.get("accent", "#0078D7"))
        
        self.ai_status_lbl = tk.Label(self.ai_lf, text=t("laugh_track.checking_for_ai_tools"), font=(UI_FONT, 10, "bold"))
        self.ai_status_lbl.pack(anchor="w", pady=(0, 5))

        self.ai_instructions_f = tk.Frame(self.ai_lf)
        
        # 2. Updated and expanded the instruction text
        # Dynamically detect hardware to provide the correct installation commands
        gpu_type = detect_gpu()
        
        if gpu_type == "nvidia":
            install_cmds = (
                "1. Install the Nvidia CUDA version of PyTorch (Run in terminal):\n"
                "   pip uninstall torch -y\n"
                "   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121\n\n"
                "2. Install the AI separator tool:\n"
                "   pip install audio-separator[gpu]"
            )
        elif gpu_type == "amd":
            install_cmds = (
                "1. Install the AMD DirectML version of PyTorch (Run in terminal):\n"
                "   pip uninstall torch -y\n"
                "   pip install torch-directml\n\n"
                "2. Install the AI separator tool for AMD:\n"
                "   pip install audio-separator[env]\n"
                "   pip install onnxruntime-directml"
            )
        else:
            install_cmds = (
                "1. Install the standard CPU version of PyTorch (Run in terminal):\n"
                "   pip uninstall torch -y\n"
                "   pip install torch torchvision torchaudio\n\n"
                "2. Install the AI separator tool:\n"
                "   pip install audio-separator[cpu]"
            )

        instr_text = (
            "To use this experimental AI engine, you must install the required packages:\n\n"
            f"{install_cmds}\n\n"
            "3. (Optional) For maximum stability, locate the generated 'audio-separator.exe'\n"
            "   and copy it directly into this application's /bin/ folder."
        )
        
        # Create a container frame specifically for the text box and its scrollbar
        txt_container = tk.Frame(self.ai_instructions_f, bg=CLR.get("panel", "#222222"))
        txt_container.pack(anchor="w", pady=5)  # <-- Removed fill="x"

        # Create the vertical scrollbar
        txt_scroll = ttk.Scrollbar(txt_container, orient="vertical")
        txt_scroll.pack(side="right", fill="y")

        # Create the text widget
        txt = tk.Text(txt_container, height=7, width=86, bg=CLR.get("panel", "#222222"), fg=CLR.get("fg", "#FFFFFF"),
                      font=(MONO_FONT, 9), relief="flat", yscrollcommand=txt_scroll.set)
        txt.insert("1.0", instr_text)
        txt.config(state="disabled") 
        txt.pack(side="left")  # <-- Removed fill="both" and expand=True

        # Link the scrollbar to the text widget's vertical view
        txt_scroll.config(command=txt.yview)

        tk.Button(self.ai_instructions_f, text=t("laugh_track.i_have_installed_the_tools_check_again"), 
                  bg=CLR.get("panel", "#222222"), fg=CLR.get("fg", "#FFFFFF"), font=(UI_FONT, 9), cursor="hand2", 
                  command=self._check_ai_tools).pack(anchor="w", pady=5)

        self.ai_model_f = tk.Frame(self.ai_lf)
        tk.Label(self.ai_model_f, text=t("common.model"), font=(UI_FONT, 10)).pack(side="left", pady=5)
        self._ai_model = tk.StringVar(value="mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt")
        tk.Entry(self.ai_model_f, textvariable=self._ai_model, width=50, font=(MONO_FONT, 10)).pack(side="left", padx=8, pady=5)
        tk.Label(self.ai_model_f, text=t("laugh_track.requires_internet_on_first_run"), fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 9)).pack(side="left", pady=5)


        # ==================================================================
        # FFMPEG TOOLS SECTION
        # ==================================================================
        self.ffmpeg_lf = tk.LabelFrame(
            self.engine_container, text=t("laugh_track.ffmpeg_tools_enable_one_or_more_they_stack"),
            padx=15, pady=10, font=(UI_FONT, 9, "bold"), fg=CLR.get("fgdim", "#888888"))

        # --- 1. Noise Profile ---
        self._use_profile = tk.BooleanVar(value=True)
        np_header = tk.Frame(self.ffmpeg_lf)
        np_header.pack(fill="x", pady=(0, 2))
        tk.Checkbutton(np_header, text=t("laugh_track.spectral_section"),
                       variable=self._use_profile, font=(UI_FONT, 10, "bold"),
                       command=self._toggle_sections).pack(side="left")
        
        self._profile_f = tk.Frame(self.ffmpeg_lf)
        pr1 = tk.Frame(self._profile_f)
        pr1.pack(fill="x", pady=2)
        tk.Label(pr1, text=t("laugh_track.laugh_sample_start_label"), width=18, anchor="e").pack(side="left")
        self._sample_start = tk.StringVar(value="0.0")
        tk.Entry(pr1, textvariable=self._sample_start, width=10).pack(side="left", padx=6)
        tk.Label(pr1, text=t("laugh_track.laugh_sample_end_label")).pack(side="left", padx=(8, 0))
        self._sample_end = tk.StringVar(value="3.0")
        tk.Entry(pr1, textvariable=self._sample_end, width=10).pack(side="left", padx=6)

        pr2 = tk.Frame(self._profile_f)
        pr2.pack(fill="x", pady=4)
        tk.Label(pr2, text=t("laugh_track.reduction_strength_label"), width=18, anchor="e").pack(side="left")
        self._nr_strength = tk.DoubleVar(value=20.0)
        tk.Scale(pr2, variable=self._nr_strength, from_=6, to=50, resolution=1, orient="horizontal").pack(side="left", padx=6)

        pr3 = tk.Frame(self._profile_f)
        pr3.pack(fill="x", pady=2)
        tk.Label(pr3, text=t("laugh_track.noise_floor"), width=18, anchor="e").pack(side="left")
        self._noise_floor = tk.DoubleVar(value=-30.0)
        tk.Scale(pr3, variable=self._noise_floor, from_=-60, to=-10, resolution=1, orient="horizontal").pack(side="left", padx=6)

        # --- 2. Center Channel ---
        self._use_center = tk.BooleanVar(value=False)
        cc_header = tk.Frame(self.ffmpeg_lf)
        cc_header.pack(fill="x", pady=(0, 2))
        tk.Checkbutton(cc_header, text=t("laugh_track.center_channel_section"),
                       variable=self._use_center, font=(UI_FONT, 10, "bold"),
                       command=self._toggle_sections).pack(side="left")

        self._center_f = tk.Frame(self.ffmpeg_lf)
        cr1 = tk.Frame(self._center_f)
        cr1.pack(fill="x", pady=2)
        tk.Label(cr1, text=t("laugh_track.center_strength_label"), width=18, anchor="e").pack(side="left")
        self._center_mix = tk.DoubleVar(value=0.8)
        tk.Scale(cr1, variable=self._center_mix, from_=0.5, to=1.0, resolution=0.05, orient="horizontal").pack(side="left", padx=6)

        self._stereo_cancel = tk.BooleanVar(value=False)
        tk.Checkbutton(self._center_f, text=t("laugh_track.aggressive_checkbox"), variable=self._stereo_cancel).pack(anchor="w", padx=120)

        # --- 3. Frequency Sculpt ---
        self._use_eq = tk.BooleanVar(value=False)
        eq_header = tk.Frame(self.ffmpeg_lf)
        eq_header.pack(fill="x", pady=(0, 2))
        tk.Checkbutton(eq_header, text=t("laugh_track.frequency_section"),
                       variable=self._use_eq, font=(UI_FONT, 10, "bold"),
                       command=self._toggle_sections).pack(side="left")

        self._eq_f = tk.Frame(self.ffmpeg_lf)
        er1 = tk.Frame(self._eq_f)
        er1.pack(fill="x", pady=2)
        tk.Label(er1, text=t("laugh_track.low_cut_label"), width=18, anchor="e").pack(side="left")
        self._eq_low = tk.StringVar(value="300")
        tk.Entry(er1, textvariable=self._eq_low, width=6).pack(side="left", padx=4)
        tk.Label(er1, text=t("laugh_track.high_cut_label")).pack(side="left", padx=(12, 0))
        self._eq_high = tk.StringVar(value="5000")
        tk.Entry(er1, textvariable=self._eq_high, width=6).pack(side="left", padx=4)

        er2 = tk.Frame(self._eq_f)
        er2.pack(fill="x", pady=2)
        tk.Label(er2, text=t("laugh_track.cut_depth_label"), width=18, anchor="e").pack(side="left")
        self._eq_depth = tk.DoubleVar(value=8.0)
        tk.Scale(er2, variable=self._eq_depth, from_=2, to=24, resolution=1, orient="horizontal").pack(side="left", padx=6)

        # --- 4. Smart Gate ---
        self._use_gate = tk.BooleanVar(value=False)
        gt_header = tk.Frame(self.ffmpeg_lf)
        gt_header.pack(fill="x", pady=(0, 2))
        tk.Checkbutton(gt_header, text=t("laugh_track.smart_gate_section"),
                       variable=self._use_gate, font=(UI_FONT, 10, "bold"),
                       command=self._toggle_sections).pack(side="left")

        self._gate_f = tk.Frame(self.ffmpeg_lf)
        gr1 = tk.Frame(self._gate_f)
        gr1.pack(fill="x", pady=2)
        tk.Label(gr1, text=t("laugh_track.gate_threshold_label"), width=18, anchor="e").pack(side="left")
        self._gate_thresh = tk.DoubleVar(value=-18.0)
        tk.Scale(gr1, variable=self._gate_thresh, from_=-40, to=-6, resolution=1, orient="horizontal").pack(side="left", padx=6)

        gr2 = tk.Frame(self._gate_f)
        gr2.pack(fill="x", pady=2)
        tk.Label(gr2, text=t("laugh_track.compression_ratio_label"), width=18, anchor="e").pack(side="left")
        self._gate_ratio = tk.DoubleVar(value=4.0)
        tk.Scale(gr2, variable=self._gate_ratio, from_=2, to=20, resolution=0.5, orient="horizontal").pack(side="left", padx=6)

        # ── Output ────────────────────────────────────────────────────────
        out_lf = tk.LabelFrame(self, text=t("section.output"), padx=15, pady=8, font=(UI_FONT, 9, "bold"))
        out_lf.pack(fill="x", padx=20, pady=4)

        of1 = tk.Frame(out_lf)
        of1.pack(fill="x", pady=2)
        tk.Label(of1, text=t("common.output_file"), font=(UI_FONT, 10, "bold"), width=12, anchor="e").pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of1, textvariable=self._out_var, width=52, font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of1, text=t("common.save_as"), command=self._browse_out, cursor="hand2").pack(side="left")

        of2 = tk.Frame(out_lf)
        of2.pack(fill="x", pady=4)
        self._export_mode = tk.StringVar(value="video")
        tk.Radiobutton(of2, text=t("laugh_track.video_option"), variable=self._export_mode, value="video").pack(side="left", padx=(0, 20))
        tk.Radiobutton(of2, text=t("laugh_track.audio_option"), variable=self._export_mode, value="audio").pack(side="left")

        # ── Action buttons ────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=10)
        self._btn_preview = tk.Button(bf, text=t("laugh_track.preview_button"), bg=CLR.get("panel", "#222222"), fg=CLR.get("fg", "#FFFFFF"), width=18, cursor="hand2", command=self._preview_result)
        self._btn_preview.pack(side="left", padx=8)

        self._btn_run = tk.Button(
            bf, text=t("laugh_track.remove_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR.get("green", "#4CAF50"), fg="white", height=2, width=28,
            cursor="hand2", command=self._render)
        self._btn_run.pack(side="left", padx=8)

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # ==================================================================
        # Initialize UI layout states AFTER all widgets are fully created!
        # ==================================================================
        self._toggle_sections()
        self._toggle_engine_ui()

    # ── UI Toggles ────────────────────────────────────────────────────
    def _toggle_engine_ui(self):
        """Show/hide sections safely inside the container."""
        if self._engine_var.get() == "ai":
            self.ffmpeg_lf.pack_forget()
            self.ai_lf.pack(fill="x", padx=20, pady=4)
            self._btn_preview.config(state="disabled") 
        else:
            self.ai_lf.pack_forget()
            self.ffmpeg_lf.pack(fill="x", padx=20, pady=4)
            self._btn_preview.config(state="normal")

    def _toggle_sections(self):
        """Unpack all and repack in order to maintain layout integrity."""
        for f in [self._profile_f, self._center_f, self._eq_f, self._gate_f]:
            f.pack_forget()
            
        for var, frame in [
            (self._use_profile, self._profile_f),
            (self._use_center,  self._center_f),
            (self._use_eq,      self._eq_f),
            (self._use_gate,    self._gate_f),
        ]:
            if var.get():
                frame.pack(fill="x", padx=20, pady=2)

# ── AI Tools Management ───────────────────────────────────────────
    def _find_ai_cli(self):
        """Prioritizes the bundled /bin/ exe, then falls back to hunting system paths."""
        import glob

        # --- DEV OVERRIDE ---
        if os.environ.get("CROSSFADER_NO_AI_TEST") == "1":
            return None
        # --------------------

        # 1. THE BUNDLED /bin/ EXE (Priority #1)
        if hasattr(self, 'ai_binary') and os.path.exists(self.ai_binary):
            return self.ai_binary

        # 2. Standard PATH check
        if shutil.which("audio-separator"):
            return shutil.which("audio-separator")

        # 3. Prepare search directories (Fallback)
        search_dirs = [
            os.path.join(os.path.dirname(sys.executable), "Scripts"),
            os.path.join(os.path.dirname(sys.executable), "bin"),
        ]

        # 4. Aggressive AppData hunting (Fallback for dev environments)
        if os.name == "nt":
            localappdata = os.environ.get("LOCALAPPDATA", "")
            appdata = os.environ.get("APPDATA", "")
            
            if localappdata:
                search_dirs.extend(glob.glob(os.path.join(localappdata, "Packages", "PythonSoftware*", "LocalCache", "local-packages", "Python3*", "Scripts")))
            if appdata:
                search_dirs.extend(glob.glob(os.path.join(appdata, "Python", "Python3*", "Scripts")))

        # 5. Check all discovered fallback paths
        exe_name = "audio-separator.exe" if os.name == "nt" else "audio-separator"
        for d in search_dirs:
            candidate = os.path.join(d, exe_name)
            if os.path.exists(candidate):
                return candidate

        return None

    def _check_ai_tools(self):
        """Checks for the CLI wrapper using the wildcard hunter."""
        if self._find_ai_cli():
            self.ai_status_lbl.config(text=t("laugh_track.ai_tools_detected_ready"), fg=CLR.get("green", "#4CAF50"))
            self.ai_instructions_f.pack_forget()
            self.ai_model_f.pack(fill="x", pady=5)
        else:
            self.ai_status_lbl.config(text=t("laugh_track.ai_tools_missing"), fg="red")
            self.ai_model_f.pack_forget()
            self.ai_instructions_f.pack(fill="x", pady=5)

    # ── File browsing ─────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(filetypes=[("Media", "*.mp4 *.mkv *.mp3 *.wav *.aac"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self._src_var.set(p)
            self.duration = get_video_duration(p)
            self._info_lbl.config(text=_fmt(self.duration))

    def _browse_out(self):
        ext = ".mp4" if self._export_mode.get() == "video" else ".wav"
        p = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[("MP4", "*.mp4"), ("WAV", "*.wav")])
        if p:
            self._out_var.set(p)

    # ── Render Logic ──────────────────────────────────────────────────
    def _build_af(self):
        """Return the combined -af filter string for FFmpeg mode."""
        filters = []
        if self._use_profile.get():
            filters.append(f"afftdn=nr={self._nr_strength.get():.0f}:nf={self._noise_floor.get():.0f}:tn=1")
        if self._use_center.get():
            mix = self._center_mix.get()
            if self._stereo_cancel.get():
                filters.append(f"pan=stereo|c0={mix:.2f}*c0+{mix:.2f}*c1|c1={mix:.2f}*c0+{mix:.2f}*c1")
            else:
                side = 1.0 - mix
                filters.append(f"pan=stereo|c0={mix:.2f}*c0+{side:.2f}*c1|c1={side:.2f}*c0+{mix:.2f}*c1")
        if self._use_eq.get():
            depth = self._eq_depth.get()
            filters.append(f"equalizer=f=2650:t=h:w=4700:g=-{depth:.0f}")
        if self._use_gate.get():
            filters.append(f"acompressor=threshold={self._gate_thresh.get():.0f}dB:ratio={self._gate_ratio.get():.1f}:attack=5:release=200:makeup=2")
        return ",".join(filters) if filters else None

    def _preview_result(self):
        if not self.file_path or self._engine_var.get() == "ai": return
        af = self._build_af()
        if not af: return
        ffplay = get_binary_path("ffplay")
        cmd = [ffplay, "-i", self.file_path, "-af", af, "-t", "30", "-window_title", t("laugh_track.ffmpeg_preview"), "-x", "800", "-y", "450"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("waveform.no_file_title"), t("common.no_input"))
            return

        out = self._out_var.get().strip()
        if not out:
            ext = ".mp4" if self._export_mode.get() == "video" else ".wav"
            out = filedialog.asksaveasfilename(defaultextension=ext)
            if not out: return
            self._out_var.set(out)

        self._btn_run.config(state="disabled")

        if self._engine_var.get() == "ffmpeg":
            self._render_ffmpeg(out)
        else:
            _out = out
            def _ai_worker_fn(progress_cb, cancel_fn):
                self._ai_cancel_fn = cancel_fn
                self._render_ai(_out)
                self._ai_cancel_fn = None
                return 0
            self.enqueue_render("Laugh Track (AI)", output_path=_out,
                                worker_fn=_ai_worker_fn)

    def _render_ffmpeg(self, out):
        af = self._build_af()
        if not af:
            self._btn_run.config(state="normal")
            return
            
        ffmpeg = get_binary_path("ffmpeg")
        cmd = [ffmpeg, "-i", self.file_path, "-af", af]
        
        if self._export_mode.get() == "video":
            # Added -vsync 0 to safely pass through VFR timestamps
            cmd += ["-c:v", "copy", "-vsync", "0", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-vn"]
            
        cmd += [out, "-y"]
        self.log(self.console, f"Running FFmpeg engine with filters: {af}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out), btn=self._btn_run, btn_label=t("laugh_track.remove_button"))

    def _render_ai(self, out):
        """Executes the AI Stem Separation via the official CLI wrapper in a background thread."""
        import tkinter as tk

        # Hunt down the official pip wrapper
        ai_cli = self._find_ai_cli()

        if not ai_cli:
            self.log(self.console, t("log.laugh_track.error_audio_separator_cli_not_found_anywhere_on_yo"))
            self.after(0, lambda: self._btn_run.config(state="normal"))
            return

        ffmpeg = get_binary_path("ffmpeg")
        temp_dir = tempfile.gettempdir()
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        temp_wav = os.path.join(temp_dir, f"{base_name}_temp_audio.wav")

        try:
            # Step 1: Extract Audio (if video)
            self.log(self.console, t("log.laugh_track.step_1_extracting_audio_for_ai_processing"))
            subprocess.run([ffmpeg, "-i", self.file_path, "-vn", "-c:a", "pcm_s16le", temp_wav, "-y"], 
                           creationflags=CREATE_NO_WINDOW, check=True)

            # Step 2: Run AI Separator
            self.log(self.console, f"Step 2: Running AI inference (Model: {self._ai_model.get()})...")
            
            cmd_ai = [
                ai_cli, temp_wav,
                "--model_filename", self._ai_model.get().strip(),
                "--output_dir", temp_dir,
                "--output_format", "WAV",
                "--log_level", "DEBUG"
            ]
            
            # Pipe output to capture progress natively
            process = subprocess.Popen(cmd_ai, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, creationflags=CREATE_NO_WINDOW)
            for line in iter(process.stdout.readline, ""):
                if self._ai_cancel_fn and self._ai_cancel_fn():
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    break
                if line.strip():
                    self.after(0, lambda l=line.strip(): [self.console.insert(tk.END, l + "\n"), self.console.see(tk.END)])
            process.wait()

            if process.returncode != 0:
                raise Exception("AI separator returned an error.")

            # Step 3: Find the correct output stem
            self.log(self.console, t("log.laugh_track.locating_separated_stems"))
            
            clean_audio_file = None
            
            # 1. Look for the dialogue stem (named differently depending on the model)
            valid_dialogue_tags = [t("laugh_track.other"), t("laugh_track.vocals"), t("laugh_track.no_crowd"), t("laugh_track.speech")]
            
            for f in os.listdir(temp_dir):
                if base_name in f and f.endswith(".wav"):
                    if any(tag in f for tag in valid_dialogue_tags):
                        clean_audio_file = os.path.join(temp_dir, f)
                        break

            if not clean_audio_file:
                raise FileNotFoundError("Could not locate the separated dialogue file.")

            # Step 4: Mux Output
            self.log(self.console, t("log.laugh_track.step_4_creating_final_file"))
            cmd_mux = [ffmpeg, "-y", "-i", self.file_path, "-i", clean_audio_file]
            
            if self._export_mode.get() == "video":
                # Map original video, map new AI audio
                cmd_mux += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-vsync", "0", "-c:a", "aac", "-b:a", "192k"]
            else:
                cmd_mux += ["-map", "1:a:0", "-c:a", "pcm_s16le"]
                
            cmd_mux.append(out)
            subprocess.run(cmd_mux, creationflags=CREATE_NO_WINDOW, check=True)

            self.log(self.console, f"SUCCESS! Saved to: {out}")
            
            # Clean up temp files
            try:
                os.remove(temp_wav)
                for f in os.listdir(temp_dir):
                    if base_name in f and f.endswith(".wav"):
                        os.remove(os.path.join(temp_dir, f))
            except Exception: pass

        except Exception as e:
            self.log(self.console, f"ERROR during AI render: {str(e)}")
            
        finally:
            self.after(0, lambda: self._btn_run.config(state="normal"))