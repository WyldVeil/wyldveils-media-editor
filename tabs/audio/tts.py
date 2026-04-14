"""
tab_ttsvoiceover.py  ─  TTS Voice-Over
Generate natural-sounding voice-over from text using Microsoft Edge TTS
(free, no API key, 10 high-quality neural voices) and burn it into a video
or export as standalone audio.

Dependencies are auto-installed into  <project_root>/libs/  on first run.
No manual pip install required.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import sys
import threading
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# ── Engine availability  (auto-installs into libs/ on first run) ──────────
from core.deps import require, is_available
from core.i18n import t

edge_tts  = require("edge-tts",  import_name="edge_tts")
pyttsx3   = require("pyttsx3",   import_name="pyttsx3",  auto_install=False)

EDGE_TTS_OK = edge_tts  is not None
PYTTSX3_OK  = pyttsx3   is not None

# ── Voice catalogue ───────────────────────────────────────────────────────
VOICES = [
    # (Display name,              edge-tts voice ID,                  description)
    # Brian = en-GB-RyanNeural: the closest Edge TTS match to the famous
    # Amazon Polly "Brian" - warm, natural British male, the voice everyone
    # knows from the internet. (Polly Brian is proprietary; this is the
    # best free equivalent.)
    (t("tts.brian_british_male"),   "en-GB-RyanNeural",                 t("tts.warm_british_male_closest_free_match_to_the_famo")),
    (t("tts.aria_us_female"),      "en-US-AriaNeural",                 t("tts.warm_expressive_american_female_great_for_ads")),
    (t("tts.jenny_us_female"),      "en-US-JennyNeural",                t("tts.friendly_conversational_american_female")),
    (t("tts.guy_us_male"),        "en-US-GuyNeural",                  t("tts.clear_neutral_american_male_good_for_narration")),
    (t("tts.emma_us_female"),      "en-US-EmmaMultilingualNeural",     t("tts.natural_engaging_american_female")),
    (t("tts.davis_us_male"),        "en-US-DavisNeural",                t("tts.casual_approachable_american_male")),
    (t("tts.sonia_british_female"), "en-GB-SoniaNeural",                t("tts.polished_british_female_professional_tone")),
    (t("tts.thomas_british_male"),   "en-GB-ThomasNeural",               t("tts.clear_confident_british_male_great_for_explainer")),
    (t("tts.natasha_au_female"),     "en-AU-NatashaNeural",              t("tts.clear_australian_female_friendly_and_bright")),
    (t("tts.clara_ca_female"),      "en-CA-ClaraNeural",                t("tts.smooth_canadian_female_neutral_and_trustworthy")),
]

VOICE_NAMES   = [v[0] for v in VOICES]
VOICE_IDS     = {v[0]: v[1] for v in VOICES}
VOICE_DESCS   = {v[0]: v[2] for v in VOICES}

# ── Style presets ─────────────────────────────────────────────────────────
STYLE_PRESETS = {
    "Normal":           {"rate": "+0%",   "pitch": "+0Hz",  "volume": "+0%"},
    "Podcast  (warm)":  {"rate": "-5%",   "pitch": "-2Hz",  "volume": "+5%"},
    "Narrator (slow)":  {"rate": "-15%",  "pitch": "-4Hz",  "volume": "+0%"},
    "Fast-read":        {"rate": "+25%",  "pitch": "+0Hz",  "volume": "+0%"},
    "Dramatic":         {"rate": "-10%",  "pitch": "-8Hz",  "volume": "+10%"},
    "Energetic  (ads)": {"rate": "+15%",  "pitch": "+4Hz",  "volume": "+10%"},
    "Whisper":          {"rate": "-20%",  "pitch": "-10Hz", "volume": "-20%"},
    "Audiobook":        {"rate": "-8%",   "pitch": "-2Hz",  "volume": "+0%"},
}

# Average reading speed for duration estimate
WORDS_PER_MINUTE_BASE = 150


class TTSVoiceOverTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._tts_audio_path = ""   # last generated TTS audio file
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🗣  " + t("tab.tts_voice_over"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("tts.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Engine status banner ──────────────────────────────────────────
        self._build_engine_banner()

        # ── Scrollable body ───────────────────────────────────────────────
        body_canvas = tk.Canvas(self, highlightthickness=0)
        body_sb     = ttk.Scrollbar(self, orient="vertical",
                                    command=body_canvas.yview)
        inner = tk.Frame(body_canvas)
        body_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: body_canvas.configure(
                       scrollregion=body_canvas.bbox("all")))
        body_canvas.configure(yscrollcommand=body_sb.set)
        body_sb.pack(side="right", fill="y")
        body_canvas.pack(side="left", fill="both", expand=True)

        self._build_text_section(inner)
        self._build_voice_section(inner)
        self._build_settings_section(inner)
        self._build_output_section(inner)
        self._build_video_section(inner)
        self._build_extras_section(inner)
        self._build_action_buttons(inner)
        self._build_console_section(inner)

        self._update_stats()

    # ── Engine banner ─────────────────────────────────────────────────────
    def _build_engine_banner(self):
        banner = tk.Frame(self, bg="#1A2A1A" if EDGE_TTS_OK else "#2A1A1A",
                          pady=4)
        banner.pack(fill="x")
        if EDGE_TTS_OK:
            tk.Label(banner,
                     text=t("tts.edge_tts_engine_ready_10_neural_voices_available"),
                     bg="#1A2A1A", fg="#66BB6A",
                     font=(UI_FONT, 9)).pack(side="left", padx=16)
            self._engine_var = tk.StringVar(value="edge-tts  (Neural, recommended)")
        else:
            tk.Label(banner,
                     text=t("tts.edge_tts_not_installed_run_pip_install_edge_tts"),
                     bg="#2A1A1A", fg="#EF9A9A",
                     font=(UI_FONT, 9)).pack(side="left", padx=16)
            self._engine_var = tk.StringVar(
                value="pyttsx3  (Offline)" if PYTTSX3_OK else "No engine available")

        # Engine selector (only relevant if both are installed)
        if EDGE_TTS_OK and PYTTSX3_OK:
            tk.Label(banner, text=t("tts.engine"), bg=banner["bg"],
                     fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")
            ttk.Combobox(banner, textvariable=self._engine_var,
                         values=[t("tts.tts_edge_tts_neural_recommended"),
                                 t("tts.tts_pyttsx3_offline")],
                         state="readonly", width=28).pack(side="left", padx=4)

    # ── Text section ──────────────────────────────────────────────────────
    def _build_text_section(self, parent):
        lf = tk.LabelFrame(parent, text=f"  📝  {t('tts.script_section')}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=6)

        # Toolbar
        tb = tk.Frame(lf); tb.pack(fill="x", pady=(0, 4))
        tk.Button(tb, text=t("tts.load_file_button"),
                  command=self._load_text_file).pack(side="left", padx=2)
        tk.Button(tb, text=t("tts.clear_button"),
                  command=self._clear_text).pack(side="left", padx=2)
        tk.Button(tb, text=t("tts.paste_button"),
                  command=self._paste_text).pack(side="left", padx=2)

        self._stats_lbl = tk.Label(tb, text="", fg=CLR["fgdim"],
                                    font=(UI_FONT, 9))
        self._stats_lbl.pack(side="right", padx=8)

        # Text area
        txt_frame = tk.Frame(lf)
        txt_frame.pack(fill="both", expand=True)
        self.text_box = tk.Text(txt_frame, height=8, wrap="word",
                                font=(MONO_FONT, 11),
                                relief="sunken", bd=1,
                                undo=True)
        txt_sb = ttk.Scrollbar(txt_frame, command=self.text_box.yview)
        self.text_box.configure(yscrollcommand=txt_sb.set)
        self.text_box.pack(side="left", fill="both", expand=True)
        txt_sb.pack(side="right", fill="y")
        self.text_box.bind("<KeyRelease>", lambda e: self._update_stats())

        # Placeholder hint
        self.text_box.insert("1.0",
            "Type or paste your script here…\n\n"
            "Tip: Use punctuation for natural pauses. "
            "Commas = short pause, full stops = longer pause.")
        self.text_box.bind("<FocusIn>",  self._clear_placeholder)

    # ── Voice section ─────────────────────────────────────────────────────
    def _build_voice_section(self, parent):
        lf = tk.LabelFrame(parent, text=f"  {t('tts.voice_section')}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        top = tk.Frame(lf); top.pack(fill="x")

        # Voice picker
        tk.Label(top, text=t("tts.voice_label"), font=(UI_FONT, 10, "bold"),
                 width=8, anchor="e").pack(side="left")
        self.voice_var = tk.StringVar(value=VOICE_NAMES[0])
        voice_cb = ttk.Combobox(top, textvariable=self.voice_var,
                                 values=VOICE_NAMES, state="readonly", width=28)
        voice_cb.pack(side="left", padx=8)
        voice_cb.bind("<<ComboboxSelected>>", self._on_voice_change)

        # Description label
        self._voice_desc_lbl = tk.Label(top,
                                         text=VOICE_DESCS[VOICE_NAMES[0]],
                                         fg=CLR["fgdim"], font=(UI_FONT, 9),
                                         anchor="w")
        self._voice_desc_lbl.pack(side="left", padx=8)

        # (Preview voice button is in the player bar below)

        # Style preset
        bottom = tk.Frame(lf); bottom.pack(fill="x", pady=(6, 0))
        tk.Label(bottom, text=t("common.preset"), font=(UI_FONT, 10, "bold"),
                 width=8, anchor="e").pack(side="left")
        self.preset_var = tk.StringVar(value="Normal")
        preset_cb = ttk.Combobox(bottom, textvariable=self.preset_var,
                                  values=list(STYLE_PRESETS.keys()),
                                  state="readonly", width=22)
        preset_cb.pack(side="left", padx=8)
        preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)
        tk.Label(bottom, text=t("tts.quick_style_presets_apply_rate_pitch_volume_toge"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left", padx=4)

    # ── Settings section ──────────────────────────────────────────────────
    def _build_settings_section(self, parent):
        lf = tk.LabelFrame(parent, text=f"  ⚙  {t('tts.voice_settings_section')}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        def _slider_row(frame, label, var, lo, hi, default, fmt_fn, unit=""):
            row = tk.Frame(frame); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=16, anchor="e",
                     font=(UI_FONT, 9)).pack(side="left")
            sl = tk.Scale(row, variable=var, from_=lo, to=hi,
                          resolution=1, orient="horizontal", length=260)
            sl.pack(side="left", padx=6)
            lbl = tk.Label(row, text=fmt_fn(default) + unit, width=9,
                           fg=CLR["accent"], font=(MONO_FONT, 9))
            lbl.pack(side="left")
            var.trace_add("write",
                lambda *_, l=lbl, v=var, f=fmt_fn, u=unit:
                l.config(text=f(v.get()) + u))
            return sl

        # Rate:   -50 … +100  (percent)
        self.rate_var  = tk.IntVar(value=0)
        # Pitch:  -20 … +20   (Hz)
        self.pitch_var = tk.IntVar(value=0)
        # Volume: -50 … +50   (percent)
        self.vol_var   = tk.IntVar(value=0)

        def rate_fmt(v):  return f"+{v}%" if v >= 0 else f"{v}%"
        def pitch_fmt(v): return f"+{v}Hz" if v >= 0 else f"{v}Hz"
        def vol_fmt(v):   return f"+{v}%" if v >= 0 else f"{v}%"

        _slider_row(lf, t("tts.speed_label"),         self.rate_var,  -50, 100, 0, rate_fmt)
        _slider_row(lf, t("tts.pitch_label"),         self.pitch_var, -20,  20, 0, pitch_fmt)
        _slider_row(lf, t("tts.volume_offset_label"), self.vol_var,   -50,  50, 0, vol_fmt)

        note = tk.Frame(lf); note.pack(fill="x", pady=(4, 0))
        tk.Label(note,
                 text=t("tts.ℹ_rate_and_pitch_only_apply_with_edge_tts"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

    # ── Output section ────────────────────────────────────────────────────
    def _build_output_section(self, parent):
        lf = tk.LabelFrame(parent, text=f"  🎧  {t('tts.output_mode_section')}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        self.mode_var = tk.StringVar(value="standalone")
        mode_row = tk.Frame(lf); mode_row.pack(fill="x")
        tk.Radiobutton(mode_row, text=t("tts.standalone_option"),
                       variable=self.mode_var, value="standalone",
                       command=self._on_mode_change,
                       font=(UI_FONT, 10)).pack(side="left", padx=12)
        tk.Radiobutton(mode_row, text=t("tts.burn_into_video_option"),
                       variable=self.mode_var, value="video",
                       command=self._on_mode_change,
                       font=(UI_FONT, 10)).pack(side="left", padx=12)

        # Format picker
        fmt_row = tk.Frame(lf); fmt_row.pack(fill="x", pady=4)
        tk.Label(fmt_row, text=t("tts.audio_format_label"), width=16, anchor="e").pack(side="left")
        self.audio_fmt_var = tk.StringVar(value="MP3  320k")
        ttk.Combobox(fmt_row, textvariable=self.audio_fmt_var,
                     values=["MP3  320k", "MP3  192k", "WAV  (lossless)",
                              "AAC  256k", "FLAC  (lossless)"],
                     state="readonly", width=18).pack(side="left", padx=8)

        # Output path
        out_row = tk.Frame(lf); out_row.pack(fill="x", pady=4)
        tk.Label(out_row, text=t("common.output_file"), width=16, anchor="e").pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.out_var, width=52, relief="flat").pack(side="left", padx=8)
        tk.Button(out_row, text=t("common.save_as"),
                  command=self._browse_out).pack(side="left")

    # ── Video section ─────────────────────────────────────────────────────
    def _build_video_section(self, parent):
        self._video_lf = tk.LabelFrame(parent, text=f"  🎬  {t('tts.video_section')}  ",
                                        padx=14, pady=8)
        # Packed/hidden by _on_mode_change

        vid_row = tk.Frame(self._video_lf); vid_row.pack(fill="x", pady=2)
        tk.Label(vid_row, text=t("tts.source_video_label"), width=16, anchor="e").pack(side="left")
        self.vid_var = tk.StringVar()
        self._vid_path = ""
        tk.Entry(vid_row, textvariable=self.vid_var, width=52, relief="flat").pack(side="left", padx=8)
        tk.Button(vid_row, text=t("btn.browse"),
                  command=self._browse_video).pack(side="left")

        # Timestamp
        ts_row = tk.Frame(self._video_lf); ts_row.pack(fill="x", pady=2)
        tk.Label(ts_row, text=t("tts.insert_at_label"), width=16, anchor="e").pack(side="left")
        self.timestamp_var = tk.StringVar(value="0")
        tk.Entry(ts_row, textvariable=self.timestamp_var, width=10, relief="flat").pack(side="left", padx=8)
        tk.Label(ts_row,
                 text=t("tts.insert_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        # Mix mode
        mix_row = tk.Frame(self._video_lf); mix_row.pack(fill="x", pady=2)
        tk.Label(mix_row, text=t("tts.audio_mode_label"), width=16, anchor="e").pack(side="left")
        self.mix_mode_var = tk.StringVar(value="mix")
        tk.Radiobutton(mix_row, text=t("tts.mix_option"),
                       variable=self.mix_mode_var, value="mix").pack(side="left", padx=8)
        tk.Radiobutton(mix_row, text=t("tts.replace_option"),
                       variable=self.mix_mode_var, value="replace").pack(side="left", padx=8)

        # Original audio volume (only relevant for mix mode)
        orig_row = tk.Frame(self._video_lf); orig_row.pack(fill="x", pady=2)
        tk.Label(orig_row, text=t("tts.orig_vol_label"), width=16, anchor="e").pack(side="left")
        self.orig_vol_var = tk.DoubleVar(value=0.5)
        tk.Scale(orig_row, variable=self.orig_vol_var, from_=0, to=1.0,
                 resolution=0.05, orient="horizontal", length=180).pack(side="left", padx=8)
        orig_lbl = tk.Label(orig_row, text="50%", fg=CLR["accent"],
                             font=(MONO_FONT, 9), width=6)
        orig_lbl.pack(side="left")
        self.orig_vol_var.trace_add("write",
            lambda *_: orig_lbl.config(
                text=f"{int(self.orig_vol_var.get()*100)}%"))
        tk.Label(orig_row, text=t("tts.original_video_audio_when_mixing"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left", padx=6)

        # Video output format
        vfmt_row = tk.Frame(self._video_lf); vfmt_row.pack(fill="x", pady=2)
        tk.Label(vfmt_row, text=t("tts.video_output"), width=16, anchor="e").pack(side="left")
        self.vid_fmt_var = tk.StringVar(value="Copy video stream  (fast, no re-encode)")
        ttk.Combobox(vfmt_row, textvariable=self.vid_fmt_var,
                     values=["Copy video stream  (fast, no re-encode)",
                              t("tts.tts_re_encode_h_264_crf_18_high_quality"),
                              t("tts.tts_re_encode_h_264_crf_23_balanced")],
                     state="readonly", width=38).pack(side="left", padx=8)

    # ── Extras section ────────────────────────────────────────────────────
    def _build_extras_section(self, parent):
        lf = tk.LabelFrame(parent, text=f"  {t('tts.extra_options_section')}  ", padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        row1 = tk.Frame(lf); row1.pack(fill="x", pady=2)
        self.srt_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row1,
                       text=t("tts.export_srt_subtitle_file_alongside_output"),
                       variable=self.srt_var,
                       font=(UI_FONT, 10)).pack(side="left")

        row2 = tk.Frame(lf); row2.pack(fill="x", pady=2)
        self.normalise_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row2,
                       text=t("tts.auto_normalise_tts_audio_to_16_lufs_broadcast_st"),
                       variable=self.normalise_var,
                       font=(UI_FONT, 10)).pack(side="left")

        row3 = tk.Frame(lf); row3.pack(fill="x", pady=2)
        tk.Label(row3, text=t("tts.silence_padding")).pack(side="left")
        tk.Label(row3, text=t("tts.before"), fg=CLR["fgdim"]).pack(side="left", padx=(8, 2))
        self.pad_before_var = tk.StringVar(value="0.0")
        tk.Entry(row3, textvariable=self.pad_before_var, width=5, relief="flat").pack(side="left")
        tk.Label(row3, text=t("tts.s_after"), fg=CLR["fgdim"]).pack(side="left", padx=(4, 2))
        self.pad_after_var = tk.StringVar(value="0.3")
        tk.Entry(row3, textvariable=self.pad_after_var, width=5, relief="flat").pack(side="left")
        tk.Label(row3, text="s", fg=CLR["fgdim"]).pack(side="left", padx=2)
        tk.Label(row3,
                 text=t("tts.adds_silence_before_after_speech_in_the_output_f"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left", padx=8)

    # ── Action buttons ────────────────────────────────────────────────────
    def _build_action_buttons(self, parent):
        btn_row = tk.Frame(parent); btn_row.pack(pady=(10, 4), padx=16, fill="x")

        tk.Button(btn_row,
                  text=t("tts.generate_preview_button"),
                  bg="#1565C0", fg="white",
                  font=(UI_FONT, 11),
                  width=20,
                  command=self._generate_preview).pack(side="left", padx=6)

        tk.Button(btn_row,
                  text=t("tts.voice_sample"),
                  bg="#37474F", fg="white",
                  font=(UI_FONT, 11),
                  width=16,
                  command=self._preview_voice).pack(side="left", padx=6)

        self.btn_render = tk.Button(
            btn_row,
            text=t("tts.generate_export_button"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white",
            height=2, width=26,
            command=self._render)
        self.btn_render.pack(side="left", padx=6)

        # Status label for async feedback
        self._gen_status = tk.Label(btn_row, text="",
                                     fg=CLR["accent"], font=(UI_FONT, 9))
        self._gen_status.pack(side="left", padx=12)

        # ── In-tab player bar ─────────────────────────────────────────────
        player_lf = tk.LabelFrame(parent, text=f"  {t('tts.preview_player_section')}  ",
                                   padx=12, pady=6)
        player_lf.pack(fill="x", padx=16, pady=(0, 6))

        ctrl = tk.Frame(player_lf); ctrl.pack(fill="x")

        self._btn_play = tk.Button(ctrl, text=t("tts.play_button"),
                                    bg="#1B5E20", fg="white",
                                    width=10, font=(UI_FONT, 10),
                                    state="disabled",
                                    command=self._player_play)
        self._btn_play.pack(side="left", padx=4)

        self._btn_stop = tk.Button(ctrl, text=t("tts.stop_button"),
                                    bg="#B71C1C", fg="white",
                                    width=10, font=(UI_FONT, 10),
                                    state="disabled",
                                    command=self._player_stop)
        self._btn_stop.pack(side="left", padx=4)

        self._player_time_lbl = tk.Label(ctrl, text="--:--",
                                          fg=CLR["accent"],
                                          font=(MONO_FONT, 10), width=6)
        self._player_time_lbl.pack(side="left", padx=8)

        self._player_file_lbl = tk.Label(ctrl, text=t("tts.no_audio_yet"),
                                          fg=CLR["fgdim"], font=(UI_FONT, 9),
                                          anchor="w")
        self._player_file_lbl.pack(side="left", padx=4, fill="x", expand=True)

        self._player_proc  = None   # ffplay subprocess
        self._player_path  = ""     # path to currently loaded audio
        self._player_timer = None   # after() id for clock update

    # ── Console ───────────────────────────────────────────────────────────
    def _build_console_section(self, parent):
        cf = tk.Frame(parent); cf.pack(fill="both", expand=True, padx=16, pady=6)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────
    def _clear_placeholder(self, event):
        content = self.text_box.get("1.0", "end-1c")
        if content.startswith("Type or paste your script here"):
            self.text_box.delete("1.0", "end")

    def _clear_text(self):
        self.text_box.delete("1.0", "end")
        self._update_stats()

    def _paste_text(self):
        try:
            text = self.clipboard_get()
            self.text_box.insert(tk.INSERT, text)
            self._update_stats()
        except Exception:
            pass

    def _load_text_file(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("tts.text_files"), "*.txt *.srt *.md"), ("All", t("ducker.item_2"))])
        if p:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                self.text_box.delete("1.0", "end")
                self.text_box.insert("1.0", f.read())
            self._update_stats()

    def _update_stats(self):
        content = self._get_text()
        chars = len(content)
        words = len(content.split()) if content.strip() else 0
        # Estimate duration based on rate
        wpm = WORDS_PER_MINUTE_BASE * (1 + self.rate_var.get() / 100) \
              if hasattr(self, "rate_var") else WORDS_PER_MINUTE_BASE
        wpm = max(60, wpm)
        secs = (words / wpm) * 60 if words else 0
        m, s = divmod(int(secs), 60)
        dur_str = f"{m}m {s:02d}s" if m else f"{s}s"
        self._stats_lbl.config(
            text=f"{chars:,} chars  │  {words:,} words  │  ~{dur_str}")

    def _get_text(self):
        t = self.text_box.get("1.0", "end-1c").strip()
        if t.startswith("Type or paste your script here"):
            return ""
        return t

    def _on_voice_change(self, *_):
        name = self.voice_var.get()
        self._voice_desc_lbl.config(text=VOICE_DESCS.get(name, ""))

    def _apply_preset(self, *_):
        p = STYLE_PRESETS.get(self.preset_var.get(), {})
        if p:
            def parse_int(s):
                return int(s.replace("%", "").replace("Hz", "").replace("+", ""))
            if hasattr(self, "rate_var"):
                self.rate_var.set(parse_int(p["rate"]))
                self.pitch_var.set(parse_int(p["pitch"]))
                self.vol_var.set(parse_int(p["volume"]))

    def _on_mode_change(self):
        if self.mode_var.get() == "video":
            self._video_lf.pack(fill="x", padx=16, pady=4,
                                 after=self._video_lf.master.children.get(
                                     list(self._video_lf.master.children)[-2], self._video_lf))
        else:
            self._video_lf.pack_forget()

    def _browse_video(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self._vid_path = p
            self.vid_var.set(p)
            base = os.path.splitext(p)[0]
            if not self.out_var.get():
                self.out_var.set(base + "_voiceover.mp4")

    def _browse_out(self):
        mode = self.mode_var.get()
        if mode == "video":
            ext = ".mp4"
            ft  = [("MP4", "*.mp4"), ("MKV", "*.mkv")]
        else:
            fmt = self.audio_fmt_var.get()
            ext = (".wav" if "WAV" in fmt else
                   ".flac" if "FLAC" in fmt else
                   ".aac" if "AAC" in fmt else ".mp3")
            ft  = [(ext.upper().strip("."), f"*{ext}")]
        p = filedialog.asksaveasfilename(defaultextension=ext, filetypes=ft)
        if p:
            self.out_var.set(p)

    # ─────────────────────────────────────────────────────────────────────
    #  TTS generation
    # ─────────────────────────────────────────────────────────────────────
    def _edge_voice_str(self):
        name  = self.voice_var.get()
        vid   = VOICE_IDS.get(name, "en-US-BrianMultilingualNeural")
        rate  = self.rate_var.get()
        pitch = self.pitch_var.get()
        vol   = self.vol_var.get()
        rate_s  = f"+{rate}%"  if rate  >= 0 else f"{rate}%"
        pitch_s = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
        vol_s   = f"+{vol}%"   if vol   >= 0 else f"{vol}%"
        return vid, rate_s, pitch_s, vol_s

    def _generate_tts_async(self, text, out_path, with_subs=False):
        """
        Runs edge-tts in a background thread.
        Returns (audio_path, srt_string_or_None).
        Calls self._on_tts_done(audio_path, srt) on the main thread when done.
        """
        if not EDGE_TTS_OK:
            return self._generate_tts_pyttsx3(text, out_path)

        voice_id, rate, pitch, volume = self._edge_voice_str()

        def _run():
            try:
                import asyncio as _aio
                srt_text = None

                async def _gen():
                    nonlocal srt_text
                    communicate = edge_tts.Communicate(
                        text, voice_id,
                        rate=rate, pitch=pitch, volume=volume)
                    if with_subs:
                        subs = edge_tts.SubMaker()
                        with open(out_path, "wb") as f:
                            async for chunk in communicate.stream():
                                if chunk["type"] == "audio":
                                    f.write(chunk["data"])
                                elif chunk["type"] == "WordBoundary":
                                    try:
                                        # edge-tts >=7: positional int args
                                        subs.create_sub(
                                            chunk["offset"],
                                            chunk["duration"],
                                            chunk["text"])
                                    except TypeError:
                                        # edge-tts <7: tuple arg
                                        subs.create_sub(
                                            (chunk["offset"], chunk["duration"]),
                                            chunk["text"])
                        # get_srt() in edge-tts >=7; generate_subs() in older
                        srt_text = (subs.get_srt() if hasattr(subs, "get_srt")
                                    else subs.generate_subs())
                    else:
                        await communicate.save(out_path)

                _aio.run(_gen())
                self.after(0, lambda: self._on_tts_done(out_path, srt_text))
            except Exception as e:
                self.after(0, lambda err=e: self._on_tts_error(str(err)))

        threading.Thread(target=_run, daemon=True).start()

    def _generate_tts_pyttsx3(self, text, out_path):
        """Offline fallback using pyttsx3."""
        if not PYTTSX3_OK:
            self._on_tts_error("No TTS engine available. Install edge-tts or pyttsx3.")
            return

        def _run():
            try:
                engine = pyttsx3.init()
                engine.save_to_file(text, out_path)
                engine.runAndWait()
                self.after(0, lambda: self._on_tts_done(out_path, None))
            except Exception as e:
                self.after(0, lambda err=e: self._on_tts_error(str(err)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_tts_done(self, audio_path, srt_text):
        self._tts_audio_path = audio_path
        self._pending_srt    = srt_text
        self._gen_status.config(text=t("tts.tts_generated"), fg="#66BB6A")
        self.log(self.console, f"TTS audio ready: {os.path.basename(audio_path)}")
        if srt_text:
            self.log(self.console, t("log.tts.srt_subtitle_data_captured"))
        # Signal the waiting render thread
        if hasattr(self, "_tts_ready_event"):
            self._tts_ready_event.set()

    def _on_tts_error(self, msg):
        self._gen_status.config(text=f"❌  {msg}", fg="#EF9A9A")
        self.log(self.console, f"[TTS ERROR] {msg}")
        if hasattr(self, "_tts_ready_event"):
            self._tts_ready_event.set()   # unblock render even on error

    # ─────────────────────────────────────────────────────────────────────
    #  In-tab player (ffplay -nodisp)
    # ─────────────────────────────────────────────────────────────────────
    def _player_load(self, path: str):
        """Load a generated audio file into the in-tab player."""
        self._player_stop()
        self._player_path = path
        name = os.path.basename(path)
        self._player_file_lbl.config(text=name)
        self._btn_play.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._player_time_lbl.config(text="00:00")

    def _player_play(self):
        """Play _player_path via ffplay -nodisp (no window, audio only)."""
        if not self._player_path or not os.path.exists(self._player_path):
            return
        self._player_stop()
        ffplay = get_binary_path("ffplay.exe")
        cmd = [ffplay, "-nodisp", "-autoexit",
               "-loglevel", "quiet", self._player_path]
        try:
            self._player_proc = __import__("subprocess").Popen(
                cmd, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.log(self.console, f"[WARN] ffplay failed: {e}")
            return
        self._player_start_time = __import__("time").time()
        self._btn_play.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._player_tick()

    def _player_stop(self):
        """Stop playback and reset the timer."""
        if self._player_proc:
            try:
                self._player_proc.terminate()
            except Exception:
                pass
            self._player_proc = None
        if self._player_timer:
            try:
                self.after_cancel(self._player_timer)
            except Exception:
                pass
            self._player_timer = None
        self._player_time_lbl.config(text="00:00")
        if self._player_path:
            self._btn_play.config(state="normal")
        self._btn_stop.config(state="disabled")

    def _player_tick(self):
        """Update the elapsed-time counter every second."""
        if self._player_proc and self._player_proc.poll() is None:
            elapsed = int(__import__("time").time() - self._player_start_time)
            m, s = divmod(elapsed, 60)
            self._player_time_lbl.config(text=f"{m:02d}:{s:02d}")
            self._player_timer = self.after(1000, self._player_tick)
        else:
            # Playback finished naturally
            self._player_stop()

    # ─────────────────────────────────────────────────────────────────────
    #  Preview (generate + load into player, no export)
    # ─────────────────────────────────────────────────────────────────────
    def _preview_voice(self):
        """Generate a short voice sample sentence and load into player."""
        name   = self.voice_var.get().split("(")[0].strip()
        sample = (f"Hello, this is {name}. "
                  f"I can narrate your videos, create podcasts, "
                  f"or add voice-over to any project.")
        self._gen_status.config(text=t("tts.generating_voice_sample"), fg=CLR["accent"])
        tmp = tempfile.mktemp(suffix="_voice_sample.mp3")

        orig_done = self._on_tts_done

        def _patched_done(path, srt):
            self._on_tts_done = orig_done
            orig_done(path, srt)
            self.after(0, lambda: self._player_load(path))
            self.after(0, lambda: self._player_play())

        self._on_tts_done = _patched_done
        if EDGE_TTS_OK:
            self._generate_tts_async(sample, tmp, with_subs=False)
        else:
            self._generate_tts_pyttsx3(sample, tmp)

    def _generate_preview(self):
        """Generate TTS for the full script and load into the in-tab player."""
        text = self._get_text()
        if not text:
            messagebox.showwarning(t("common.warning"), "Enter some text first.")
            return
        self._gen_status.config(text=t("tts.generating"), fg=CLR["accent"])
        self.log(self.console, t("log.tts.generating_tts_preview"))
        tmp = tempfile.mktemp(suffix="_tts_preview.mp3")

        orig_done = self._on_tts_done

        def _patched_done(path, srt):
            self._on_tts_done = orig_done
            orig_done(path, srt)
            self.after(0, lambda: self._player_load(path))
            self.after(0, lambda: self._player_play())
            self.log(self.console, t("log.tts.loaded_into_in_tab_player_press_play_to_replay"))

        self._on_tts_done = _patched_done
        if EDGE_TTS_OK:
            self._generate_tts_async(text, tmp, with_subs=self.srt_var.get())
        else:
            self._generate_tts_pyttsx3(text, tmp)

    # ─────────────────────────────────────────────────────────────────────
    #  Main render
    # ─────────────────────────────────────────────────────────────────────
    def _render(self):
        text = self._get_text()
        if not text:
            messagebox.showwarning(t("common.warning"), "Enter some text in the script box.")
            return

        out = self.out_var.get().strip()
        if not out:
            self._browse_out()
            out = self.out_var.get().strip()
        if not out:
            return

        if self.mode_var.get() == "video" and not self._vid_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        self.btn_render.config(state="disabled", text=t("tts.generating_tts"))
        self._gen_status.config(text=t("tts.running_tts_engine"), fg=CLR["accent"])
        self.log(self.console, t("log.tts.step_1_2_generating_tts_audio"))

        # TTS goes to a temp file; FFmpeg then processes it
        tts_tmp = tempfile.mktemp(suffix="_tts_raw.mp3")
        self._tts_ready_event = threading.Event()

        def _on_tts_complete(path, srt_text):
            self._tts_audio_path = path
            self._pending_srt    = srt_text
            self._gen_status.config(text=t("tts.tts_done_processing"), fg="#66BB6A")
            self.log(self.console, t("log.tts.step_2_2_processing_with_ffmpeg"))
            # Must run FFmpeg on main thread (tkinter safety)
            self.after(0, lambda: self._ffmpeg_stage(path, srt_text, out))

        self._on_tts_done = _on_tts_complete

        if EDGE_TTS_OK:
            self._generate_tts_async(text, tts_tmp, with_subs=self.srt_var.get())
        else:
            self._generate_tts_pyttsx3(text, tts_tmp)

    def _ffmpeg_stage(self, tts_path, srt_text, out):
        """Called after TTS is ready. Builds and runs the FFmpeg command."""
        if not os.path.exists(tts_path):
            self.log(self.console, t("log.tts.error_tts_file_not_found_generation_may_have_fail"))
            self.btn_render.config(state="normal", text=t("tts.generate_export"))
            return

        ffmpeg = get_binary_path("ffmpeg.exe")
        mode   = self.mode_var.get()

        # ── Build audio filter for TTS track ─────────────────────────────
        vol_offset = self.vol_var.get()
        vol_factor = 1.0 + vol_offset / 100.0

        try:
            pad_b = float(self.pad_before_var.get())
        except ValueError:
            pad_b = 0.0
        try:
            pad_a = float(self.pad_after_var.get())
        except ValueError:
            pad_a = 0.3

        tts_filter_parts = [f"volume={vol_factor:.3f}"]
        if pad_b > 0 or pad_a > 0:
            tts_filter_parts.append(
                f"adelay={int(pad_b*1000)}|{int(pad_b*1000)}")
        if self.normalise_var.get():
            tts_filter_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        tts_filter = ",".join(tts_filter_parts)

        # ── Standalone audio ──────────────────────────────────────────────
        if mode == "standalone":
            cmd = [ffmpeg, "-i", tts_path,
                   "-af", tts_filter]
            fmt = self.audio_fmt_var.get()
            if "WAV" in fmt:
                cmd += ["-c:a", "pcm_s16le"]
            elif "FLAC" in fmt:
                cmd += ["-c:a", "flac"]
            elif "AAC" in fmt:
                cmd += ["-c:a", "aac", "-b:a", "256k"]
            else:
                brate = "320k" if "320" in fmt else "192k"
                cmd += ["-c:a", "libmp3lame", "-b:a", brate]
            cmd += [out, "-y"]

        # ── Burn into video ───────────────────────────────────────────────
        else:
            vid  = self._vid_path
            try:
                offset = float(self.timestamp_var.get())
            except ValueError:
                offset = 0.0

            mix_mode = self.mix_mode_var.get()
            orig_vol = self.orig_vol_var.get()

            # inputs: [0] = video, [1] = TTS audio (with optional offset)
            cmd = [ffmpeg, "-i", vid]
            if offset > 0:
                cmd += ["-itsoffset", str(offset)]
            cmd += ["-i", tts_path]

            if mix_mode == "replace":
                # Just use TTS audio, drop original
                fc = f"[1:a]{tts_filter}[tts_out]"
                map_audio = "[tts_out]"
            else:
                # Mix TTS + original video audio
                fc = (f"[0:a]volume={orig_vol:.3f}[orig];"
                      f"[1:a]{tts_filter}[tts];"
                      f"[orig][tts]amix=inputs=2:duration=first[aout]")
                map_audio = "[aout]"

            # Video codec
            vid_fmt = self.vid_fmt_var.get()
            if "copy" in vid_fmt.lower():
                v_codec = [t("dynamics.c_v"), "copy"]
            else:
                crf = "18" if "18" in vid_fmt else "23"
                v_codec = [t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast"]

            cmd += ["-filter_complex", fc,
                    "-map", "0:v", "-map", map_audio]
            cmd += v_codec + ["-c:a", "aac", "-b:a", "256k",
                               "-shortest", out, "-y"]

        # ── Save SRT if requested ─────────────────────────────────────────
        if self.srt_var.get() and srt_text:
            srt_path = os.path.splitext(out)[0] + ".srt"
            try:
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_text)
                self.log(self.console, f"SRT saved: {os.path.basename(srt_path)}")
            except Exception as e:
                self.log(self.console, f"[WARN] Could not save SRT: {e}")

        self.log(self.console, f"FFmpeg command ready, rendering → {os.path.basename(out)}")

        def _done(rc):
            self.btn_render.config(state="normal", text=t("tts.generate_export"))
            self._gen_status.config(text="")
            self.show_result(rc, out)

        self.run_ffmpeg(cmd, self.console,
                        on_done=_done,
                        btn=self.btn_render,
                        btn_label="🗣  GENERATE & EXPORT")
