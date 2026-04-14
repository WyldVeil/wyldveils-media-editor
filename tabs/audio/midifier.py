"""
tab_midifier.py  ─  MIDIfier

Three-stage audio pipeline:
  1. Audio → MIDI   (librosa pitch detection + pretty_midi)
  2. MIDI  → WAV    (FluidSynth + GeneralUser GS SoundFont)
  3. WAV   → MP3    (FFmpeg 256 kbps)

Produces a high-quality MIDI re-render of any song.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import sys
import threading
import shutil
import tempfile
import platform

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT, add_tooltip
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ── Paths ────────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SOUNDFONTS_DIR = os.path.join(_ROOT, "soundfonts")
_GENERALUSER_SF2 = os.path.join(_SOUNDFONTS_DIR, "GeneralUser_GS.sf2")

# FluidSynth Windows binary (bundled)
_FLUIDSYNTH_DIR = os.path.join(_ROOT, "bin", "fluidsynth")
_FLUIDSYNTH_EXE = os.path.join(_FLUIDSYNTH_DIR, "bin", "fluidsynth.exe")
_FLUIDSYNTH_URL = (
    "https://github.com/FluidSynth/fluidsynth/releases/download/v2.4.1/"
    "fluidsynth-2.4.1-win10-x64.zip"
)

# Well-known install locations to search for FluidSynth + SF2
_SEARCH_PATHS_FS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                 "Microsoft Music Producer", "FluidSynth"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), "FluidSynth", "bin"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "FluidSynth", "bin"),
]
_SEARCH_PATHS_SF2 = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                 "Microsoft Music Producer", "FluidSynth"),
    os.path.join(os.environ.get("USERPROFILE", ""), ".fluidsynth"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "soundfonts"),
]


def _find_fluidsynth():
    """Search for fluidsynth executable in known locations."""
    # 1. Bundled
    if os.path.isfile(_FLUIDSYNTH_EXE):
        return _FLUIDSYNTH_EXE
    # 2. Known install paths
    for d in _SEARCH_PATHS_FS:
        for name in ("fluidsynth.exe", "fluidsynth"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
    # 3. System PATH
    return shutil.which("fluidsynth")


def _find_soundfont():
    """Search for GeneralUser GS .sf2 in known locations."""
    # 1. Bundled
    if os.path.isfile(_GENERALUSER_SF2):
        return _GENERALUSER_SF2
    # 2. Known install paths
    for d in _SEARCH_PATHS_SF2:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.lower().endswith(".sf2") and "general" in f.lower():
                return os.path.join(d, f)
    # 3. Any .sf2 in known paths
    for d in _SEARCH_PATHS_SF2:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.lower().endswith(".sf2"):
                return os.path.join(d, f)
    # 4. pretty_midi bundled TimGM6mb (fallback, lower quality)
    try:
        import pretty_midi
        pm_sf2 = os.path.join(os.path.dirname(pretty_midi.__file__),
                               "TimGM6mb.sf2")
        if os.path.isfile(pm_sf2):
            return pm_sf2
    except Exception:
        pass
    return None


class MIDIfierTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._deps_ok = False
        self._fs_path = None   # resolved fluidsynth path
        self._sf2_path = None  # resolved soundfont path
        self._build_ui()
        self.run_in_thread(self._check_deps)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.make_header(self, t("tab.midifier"),
                         subtitle=t("midifier.subtitle"),
                         icon="\U0001F3B9")

        # Scrollable body
        outer = tk.Frame(self, bg=CLR["bg"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=CLR["bg"], highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self._inner = tk.Frame(canvas, bg=CLR["bg"])
        self._inner.bind("<Configure>",
                         lambda e: canvas.configure(
                             scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _on_mw(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mw)
        self._inner.bind("<MouseWheel>", _on_mw)

        # ── Dependencies status ──────────────────────────────────────────
        dep_sec = self.make_section(self._inner, title=t("midifier.section.deps"))
        self._dep_lbl = tk.Label(
            dep_sec, text=t("midifier.checking_deps"),
            font=(MONO_FONT, 9), anchor="w", justify="left",
            bg=CLR["bg"], fg=CLR["fgdim"])
        self._dep_lbl.pack(fill="x", padx=4, pady=2)
        self._dep_btn = tk.Button(
            dep_sec, text=t("midifier.install_btn"),
            font=(UI_FONT, 9, "bold"),
            bg=CLR["accent"], fg="white",
            relief="flat", cursor="hand2",
            command=self._install_deps)
        add_tooltip(self._dep_btn, t("midifier.install_tooltip"))

        # ── Source ───────────────────────────────────────────────────────
        src_sec = self.make_section(self._inner, title=t("midifier.section.source"))
        self.src_var = tk.StringVar()
        row = self.make_file_row(src_sec, t("midifier.input_file"), self.src_var,
                                 self._browse_src)
        row.pack(fill="x", pady=4)

        # ── Pipeline overview ────────────────────────────────────────────
        pipe_sec = self.make_section(self._inner, title=t("midifier.section.pipeline"))
        steps = [
            ("1", t("midifier.step1_title"), t("midifier.step1_desc")),
            ("2", t("midifier.step2_title"), t("midifier.step2_desc")),
            ("3", t("midifier.step3_title"), t("midifier.step3_desc")),
        ]
        for num, title, desc in steps:
            sf = tk.Frame(pipe_sec, bg=CLR["bg"])
            sf.pack(fill="x", pady=3, padx=4)
            tk.Label(sf, text=f"  {num} ",
                     font=(UI_FONT, 11, "bold"),
                     bg=CLR["accent"], fg="white",
                     width=3).pack(side="left", padx=(0, 8))
            tf = tk.Frame(sf, bg=CLR["bg"])
            tf.pack(side="left", fill="x", expand=True)
            tk.Label(tf, text=title,
                     font=(UI_FONT, 10, "bold"),
                     bg=CLR["bg"], fg=CLR["fg"],
                     anchor="w").pack(fill="x")
            tk.Label(tf, text=desc,
                     font=(UI_FONT, 8),
                     bg=CLR["bg"], fg=CLR["fgdim"],
                     anchor="w", wraplength=500).pack(fill="x")

        # ── Options ──────────────────────────────────────────────────────
        opt_sec = self.make_section(self._inner, title=t("midifier.section.options"))

        r0 = tk.Frame(opt_sec, bg=CLR["bg"])
        r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("midifier.midi_program"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.program_var = tk.StringVar(value="0 - Acoustic Grand Piano")
        programs = [
            "0 - Acoustic Grand Piano",
            "4 - Electric Piano",
            "24 - Nylon Guitar",
            "25 - Steel Guitar",
            "33 - Electric Bass",
            "40 - Violin",
            "48 - String Ensemble",
            "56 - Trumpet",
            "65 - Alto Sax",
            "73 - Flute",
            "80 - Square Lead (Synth)",
            "88 - Pad (New Age)",
        ]
        ttk.Combobox(r0, textvariable=self.program_var,
                     values=programs, state="readonly",
                     width=30).pack(side="left", padx=8)

        r1 = tk.Frame(opt_sec, bg=CLR["bg"])
        r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("midifier.gain_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.gain_var = tk.StringVar(value="1.0")
        tk.Entry(r1, textvariable=self.gain_var, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r1, text=t("midifier.gain_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"],
                 fg=CLR["fgdim"]).pack(side="left", padx=4)

        r2 = tk.Frame(opt_sec, bg=CLR["bg"])
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("midifier.sample_rate"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.sr_var = tk.StringVar(value="44100")
        ttk.Combobox(r2, textvariable=self.sr_var,
                     values=["22050", "44100", "48000"],
                     state="readonly", width=8).pack(side="left", padx=8)
        tk.Label(r2, text="Hz", font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        r3 = tk.Frame(opt_sec, bg=CLR["bg"])
        r3.pack(fill="x", pady=4)
        self.save_midi_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text=t("midifier.save_midi"),
                       variable=self.save_midi_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left")

        r4 = tk.Frame(opt_sec, bg=CLR["bg"])
        r4.pack(fill="x", pady=4)
        tk.Label(r4, text=t("midifier.note_thresh"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.note_thresh_var = tk.StringVar(value="0.5")
        tk.Entry(r4, textvariable=self.note_thresh_var, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r4, text=t("midifier.note_thresh_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"],
                 fg=CLR["fgdim"]).pack(side="left", padx=4)

        r5 = tk.Frame(opt_sec, bg=CLR["bg"])
        r5.pack(fill="x", pady=4)
        tk.Label(r5, text=t("midifier.min_note"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.min_note_var = tk.StringVar(value="0.05")
        tk.Entry(r5, textvariable=self.min_note_var, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r5, text=t("midifier.min_note_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"],
                 fg=CLR["fgdim"]).pack(side="left", padx=4)

        # ── Output ───────────────────────────────────────────────────────
        out_sec = self.make_section(self._inner, title=t("midifier.section.output"))
        self.out_var = tk.StringVar()
        out_row = self.make_file_row(out_sec, t("midifier.save_as"), self.out_var,
                                     self._browse_out)
        out_row.pack(fill="x", pady=4)

        # ── Run button ───────────────────────────────────────────────────
        btn_f = tk.Frame(self._inner, bg=CLR["bg"])
        btn_f.pack(fill="x", pady=(12, 6))
        self.btn_run = self.make_render_btn(
            btn_f, t("midifier.run_btn"),
            self._run, color=CLR["green"], width=30)
        self.btn_run.pack(pady=4)
        add_tooltip(self.btn_run, t("midifier.run_tooltip"))

        # ── Console ──────────────────────────────────────────────────────
        cf = tk.Frame(self._inner, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 14))
        self.console, csb = self.make_console(cf, height=10)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Browse ────────────────────────────────────────────────────────────

    def _browse_src(self):
        p = filedialog.askopenfilename(
            title="Open audio file",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.flac *.aac *.m4a *.ogg "
                                "*.opus *.wma *.aiff *.mp4 *.mkv *.mov"),
                ("All files", "*.*"),
            ])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            if not self.out_var.get():
                self.out_var.set(base + "_midified.mp3")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            title="Save MP3 as", defaultextension=".mp3",
            filetypes=[("MP3", "*.mp3"), ("All files", "*.*")])
        if p:
            self.out_var.set(p)

    # ── Dependency management ────────────────────────────────────────────

    def _check_deps(self):
        """Check if all dependencies are available."""
        status = []
        ok = True

        # 1. librosa + pretty_midi
        try:
            import librosa       # noqa: F401
            import pretty_midi   # noqa: F401
            status.append("  \u2713  librosa + pretty_midi (audio \u2192 MIDI)")
        except ImportError:
            status.append("  \u2717  librosa + pretty_midi (not installed)")
            ok = False

        # 2. FluidSynth binary
        self._fs_path = _find_fluidsynth()
        if self._fs_path:
            status.append(f"  \u2713  FluidSynth ({os.path.dirname(self._fs_path)})")
        else:
            status.append("  \u2717  FluidSynth (not found)")
            ok = False

        # 3. SoundFont
        self._sf2_path = _find_soundfont()
        if self._sf2_path:
            name = os.path.basename(self._sf2_path)
            status.append(f"  \u2713  SoundFont: {name}")
        else:
            status.append("  \u2717  SoundFont .sf2 (not found)")
            ok = False

        # 4. FFmpeg
        ffmpeg = get_binary_path("ffmpeg")
        if os.path.isfile(ffmpeg):
            status.append("  \u2713  FFmpeg (WAV \u2192 MP3)")
        else:
            status.append("  \u2717  FFmpeg (not found)")
            ok = False

        self._deps_ok = ok
        info = "\n".join(status)

        def _update():
            self._dep_lbl.config(
                text=info,
                fg=CLR["green"] if ok else CLR["orange"])
            if not ok:
                self._dep_btn.pack(fill="x", padx=4, pady=(6, 4))
            else:
                self._dep_btn.pack_forget()
        self.after(0, _update)

    def _install_deps(self):
        """Install missing dependencies in background."""
        self._dep_btn.config(state="disabled", text="Installing...")
        self.log(self.console, "Installing dependencies...")

        def _work():
            # 1. Install librosa + pretty_midi via vendored pip
            try:
                import librosa  # noqa: F401
            except ImportError:
                self.log(self.console,
                         "Installing librosa + pretty_midi...")
                try:
                    from core.deps import require
                    lr = require("librosa", import_name="librosa")
                    pm = require("pretty_midi", import_name="pretty_midi")
                    if lr and pm:
                        self.log_tagged(self.console,
                                        "  librosa + pretty_midi installed",
                                        "success")
                    else:
                        self.log_tagged(self.console,
                                        "  Install failed - try manually:\n"
                                        "  pip install librosa pretty_midi",
                                        "error")
                except Exception as e:
                    self.log_tagged(self.console,
                                    f"  Install error: {e}", "error")

            # 2. Download FluidSynth if not found anywhere
            if not _find_fluidsynth():
                self.log(self.console, "Downloading FluidSynth...")
                try:
                    self._download_fluidsynth()
                    self.log_tagged(self.console,
                                    "  FluidSynth downloaded", "success")
                except Exception as e:
                    self.log_tagged(self.console,
                                    f"  FluidSynth download failed: {e}",
                                    "error")

            # 3. SoundFont - copy from local if found, else inform user
            if not _find_soundfont():
                self.log(self.console,
                         "SoundFont not found automatically.")
                self.log(self.console,
                         "  Please download GeneralUser GS from:")
                self.log(self.console,
                         "  https://schristiancollins.com/generaluser.php")
                self.log(self.console,
                         f"  Place the .sf2 file in: {_SOUNDFONTS_DIR}")

            self.after(0, lambda: self._dep_btn.config(
                state="normal", text=t("midifier.install_btn")))
            self._check_deps()

        self.run_in_thread(_work)

    def _download_fluidsynth(self):
        """Download and extract FluidSynth for Windows."""
        import urllib.request
        import zipfile
        import io

        os.makedirs(os.path.join(_ROOT, "bin"), exist_ok=True)
        self.log(self.console, "  Downloading from GitHub...")

        req = urllib.request.Request(
            _FLUIDSYNTH_URL,
            headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=120)
        data = resp.read()
        mb = len(data) // (1024 * 1024)
        self.log(self.console, f"  Extracting ({mb} MB)...")

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            top = zf.namelist()[0].split("/")[0]
            zf.extractall(os.path.join(_ROOT, "bin"))
            extracted = os.path.join(_ROOT, "bin", top)
            if extracted != _FLUIDSYNTH_DIR:
                if os.path.exists(_FLUIDSYNTH_DIR):
                    shutil.rmtree(_FLUIDSYNTH_DIR)
                os.rename(extracted, _FLUIDSYNTH_DIR)

    # ── Audio → MIDI conversion ──────────────────────────────────────────

    def _audio_to_midi(self, audio_path, midi_path):
        """Convert audio to MIDI using polyphonic CQT-based transcription.

        Uses the Constant-Q Transform (CQT) which maps directly to musical
        pitches, enabling detection of multiple simultaneous notes - essential
        for real songs with vocals, bass, drums, chords, etc.
        """
        import librosa
        import numpy as np
        import pretty_midi

        self.log(self.console, "  Loading audio...")
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)
        self.log(self.console,
                 f"  Duration: {duration:.1f}s, "
                 f"Sample rate: {sr} Hz")

        # ── CQT spectrogram (84 bins = 7 octaves, C1-B7) ────────────
        self.log(self.console,
                 "  Computing CQT spectrogram (polyphonic)...")
        n_bins = 84                       # 7 octaves
        bins_per_octave = 12              # chromatic
        hop = 512
        C = np.abs(librosa.cqt(
            y, sr=sr,
            hop_length=hop,
            n_bins=n_bins,
            bins_per_octave=bins_per_octave,
            fmin=librosa.note_to_hz("C1"),
        ))

        # Convert to dB and normalise to 0-1
        C_db = librosa.amplitude_to_db(C, ref=C.max())
        # C_db ranges from 0 (loudest) to ~ -80 (silence)
        # Normalise so 0 = silence, 1 = loudest
        C_norm = np.clip((C_db + 80.0) / 80.0, 0.0, 1.0)

        frame_times = librosa.frames_to_time(
            np.arange(C_norm.shape[1]), sr=sr, hop_length=hop)

        # ── Threshold + peak-picking ─────────────────────────────────
        note_thresh = float(self.note_thresh_var.get() or 0.5)
        min_dur = float(self.min_note_var.get() or 0.05)

        self.log(self.console,
                 f"  Extracting notes (threshold={note_thresh})...")

        # Build piano-roll with spectral peak-picking to reduce
        # leakage: a bin must be above threshold AND be a local
        # maximum in the pitch dimension (within +/-2 bins)
        piano_roll = np.zeros_like(C_norm, dtype=np.uint8)
        for t_idx in range(C_norm.shape[1]):
            col = C_norm[:, t_idx]
            for p in range(n_bins):
                if col[p] < note_thresh:
                    continue
                # Check if this is a local peak in pitch
                lo = max(0, p - 2)
                hi = min(n_bins, p + 3)
                if col[p] >= col[lo:hi].max() - 0.05:
                    piano_roll[p, t_idx] = 1

        # ── Convert piano-roll to MIDI notes ─────────────────────────
        midi = pretty_midi.PrettyMIDI(initial_tempo=120)
        program_num = int(self.program_var.get().split(" - ")[0])
        instrument = pretty_midi.Instrument(program=program_num)

        # MIDI note offset: CQT bin 0 = C1 = MIDI 24
        midi_offset = 24
        note_count = 0
        min_frames = max(1, int(min_dur * sr / hop))

        for pitch_bin in range(n_bins):
            midi_note = pitch_bin + midi_offset
            if midi_note > 127:
                continue

            # Find contiguous runs of 1s in this pitch row
            row = piano_roll[pitch_bin]
            in_note = False
            start_frame = 0

            for frame_idx in range(len(row)):
                if row[frame_idx] and not in_note:
                    # Note onset
                    in_note = True
                    start_frame = frame_idx
                elif not row[frame_idx] and in_note:
                    # Note offset
                    in_note = False
                    length = frame_idx - start_frame
                    if length >= min_frames:
                        t_start = frame_times[start_frame]
                        t_end = frame_times[min(frame_idx,
                                                len(frame_times) - 1)]
                        # Velocity from average energy during the note
                        avg_energy = float(np.mean(
                            C_norm[pitch_bin,
                                   start_frame:frame_idx]))
                        velocity = int(np.clip(
                            avg_energy * 127, 30, 127))

                        note = pretty_midi.Note(
                            velocity=velocity,
                            pitch=midi_note,
                            start=t_start,
                            end=t_end)
                        instrument.notes.append(note)
                        note_count += 1

            # Handle note that extends to end of track
            if in_note:
                length = len(row) - start_frame
                if length >= min_frames:
                    t_start = frame_times[start_frame]
                    t_end = frame_times[-1]
                    avg_energy = float(np.mean(
                        C_norm[pitch_bin, start_frame:]))
                    velocity = int(np.clip(
                        avg_energy * 127, 30, 127))
                    note = pretty_midi.Note(
                        velocity=velocity,
                        pitch=midi_note,
                        start=t_start,
                        end=t_end)
                    instrument.notes.append(note)
                    note_count += 1

        midi.instruments.append(instrument)
        midi.write(midi_path)

        self.log_tagged(self.console,
                        f"  MIDI created: {note_count} notes, "
                        f"{os.path.getsize(midi_path) / 1024:.1f} KB",
                        "success")

    # ── Main pipeline ────────────────────────────────────────────────────

    def _run(self):
        if not self.file_path:
            messagebox.showwarning(t("midifier.no_input"),
                                   t("midifier.no_input"))
            return
        if not self._deps_ok:
            messagebox.showwarning(t("midifier.missing_deps"),
                                   t("midifier.missing_deps"))
            return

        out = self.out_var.get().strip()
        if not out:
            self._browse_out()
            out = self.out_var.get().strip()
        if not out:
            return

        self.btn_run.config(state="disabled", text="Processing...")
        self.log(self.console, "")
        self.log_tagged(self.console,
                        t("midifier.starting"), "info")

        def _pipeline():
            tmp_dir = tempfile.mkdtemp(prefix="midifier_")
            midi_path = os.path.join(tmp_dir, "transcription.mid")
            wav_path = os.path.join(tmp_dir, "rendered.wav")
            success = False

            try:
                # ── Stage 1: Audio → MIDI ────────────────────────────────
                self.log_tagged(self.console,
                                "\n\u2500 " + t("midifier.stage1"), "info")
                self._audio_to_midi(self.file_path, midi_path)

                if not os.path.isfile(midi_path):
                    self.log_tagged(self.console,
                                    "  MIDI generation failed", "error")
                    return

                # Save MIDI copy if requested
                if self.save_midi_var.get():
                    midi_save = os.path.splitext(out)[0] + ".mid"
                    shutil.copy2(midi_path, midi_save)
                    self.log(self.console,
                             f"  MIDI saved: {midi_save}")

                # ── Stage 2: MIDI → WAV (FluidSynth) ────────────────────
                self.log_tagged(self.console,
                                "\n\u2500 " + t("midifier.stage2"), "info")

                fs_exe = self._fs_path
                sf2 = self._sf2_path
                if not fs_exe or not sf2:
                    self.log_tagged(self.console,
                                    t("midifier.fs_or_sf2_missing"),
                                    "error")
                    return

                gain = self.gain_var.get() or "1.0"
                sr = self.sr_var.get() or "44100"

                cmd_fs = [
                    fs_exe, "-ni",
                    "-g", gain, "-r", sr,
                    "-F", wav_path,
                    sf2, midi_path,
                ]

                sf2_name = os.path.basename(sf2)
                self.log(self.console, f"  SoundFont: {sf2_name}")
                self.log(self.console,
                         f"  Sample rate: {sr} Hz, Gain: {gain}")
                self.log(self.console, "  Rendering...")

                proc = subprocess.run(
                    cmd_fs, capture_output=True, text=True,
                    timeout=600, creationflags=CREATE_NO_WINDOW)

                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "unknown")[-400:]
                    self.log_tagged(self.console,
                                    f"  FluidSynth error:\n  {err}",
                                    "error")
                    return

                if not os.path.isfile(wav_path):
                    self.log_tagged(self.console,
                                    "  WAV render failed", "error")
                    return

                wav_mb = os.path.getsize(wav_path) / (1024 * 1024)
                self.log_tagged(self.console,
                                f"  WAV rendered: {wav_mb:.1f} MB",
                                "success")

                # ── Stage 3: WAV → MP3 (FFmpeg 256k) ────────────────────
                self.log_tagged(self.console,
                                "\n\u2500 " + t("midifier.stage3"), "info")

                ffmpeg = get_binary_path("ffmpeg")
                cmd_ff = [
                    ffmpeg, "-i", wav_path,
                    "-c:a", "libmp3lame",
                    "-b:a", "256k",
                    "-ar", sr,
                    out, "-y",
                ]

                self.log(self.console, "  Encoding MP3...")
                proc = subprocess.run(
                    cmd_ff, capture_output=True, text=True,
                    timeout=300, creationflags=CREATE_NO_WINDOW)

                if proc.returncode != 0:
                    err = (proc.stderr or "")[-300:]
                    self.log_tagged(self.console,
                                    f"  FFmpeg error: {err}", "error")
                    return

                mp3_mb = os.path.getsize(out) / (1024 * 1024)
                self.log_tagged(self.console,
                                f"  MP3 saved: {mp3_mb:.1f} MB",
                                "success")

                success = True
                self.log_tagged(self.console,
                                f"\n\u2713  MIDIfication complete!  "
                                f"{wav_mb:.1f} MB WAV \u2192 "
                                f"{mp3_mb:.1f} MB MP3", "success")

            except Exception as e:
                import traceback
                self.log_tagged(self.console,
                                f"\nError: {e}", "error")
                self.log(self.console, traceback.format_exc())
            finally:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
                self.after(0, lambda: self.btn_run.config(
                    state="normal", text=t("midifier.run_btn")))
                if success:
                    self.after(0, lambda: self.show_result(0, out))

        self.run_in_thread(_pipeline)
