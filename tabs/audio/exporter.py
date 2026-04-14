"""
tab_audioexporter.py  ─  Audio Exporter

Comprehensive audio file converter / exporter.  Open any audio (or
video-with-audio) file and re-save it with full control over:

  • Output format (MP3, AAC/M4A, WAV, FLAC, OGG Vorbis, Opus, WMA, AIFF, ALAC, AC3)
  • Codec & encoder selection
  • Bitrate / quality (CBR, VBR, lossless)
  • Sample rate, bit depth, channel layout
  • Loudness normalization (EBU R128 / peak)
  • Trim (start / end time)
  • Fade in / fade out
  • Metadata (title, artist, album, genre, year, track, comment)
  • Max file-size targeting (auto-calculates bitrate)
  • ReplayGain tagging
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import json

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ── Format definitions ───────────────────────────────────────────────────────
#  key: (extension, codec_args, supports_bitrate, supports_vbr, supports_bit_depth)
FORMAT_DEFS = {
    "MP3": {
        "ext": ".mp3",
        "codec": ["-c:a", "libmp3lame"],
        "lossy": True,
        "bitrates": ["64k", "96k", "128k", "160k", "192k", "224k", "256k", "320k"],
        "default_br": "320k",
        "vbr_flag": "-q:a",
        "vbr_range": (0, 9),          # 0 = best
        "vbr_default": 2,
        "sample_rates": [8000, 11025, 16000, 22050, 32000, 44100, 48000],
    },
    "AAC (M4A)": {
        "ext": ".m4a",
        "codec": ["-c:a", "aac"],
        "lossy": True,
        "bitrates": ["64k", "96k", "128k", "160k", "192k", "256k", "320k"],
        "default_br": "256k",
        "vbr_flag": None,
        "sample_rates": [22050, 32000, 44100, 48000, 96000],
    },
    "OGG Vorbis": {
        "ext": ".ogg",
        "codec": ["-c:a", "libvorbis"],
        "lossy": True,
        "bitrates": ["64k", "96k", "128k", "160k", "192k", "256k", "320k"],
        "default_br": "192k",
        "vbr_flag": "-q:a",
        "vbr_range": (0, 10),         # 10 = best
        "vbr_default": 6,
        "sample_rates": [8000, 11025, 16000, 22050, 32000, 44100, 48000],
    },
    "Opus": {
        "ext": ".opus",
        "codec": ["-c:a", "libopus"],
        "lossy": True,
        "bitrates": ["32k", "48k", "64k", "96k", "128k", "160k", "192k", "256k", "320k", "450k", "510k"],
        "default_br": "128k",
        "vbr_flag": None,
        "sample_rates": [8000, 12000, 16000, 24000, 48000],
    },
    "WAV": {
        "ext": ".wav",
        "codec": [],  # set dynamically from bit depth
        "lossy": False,
        "bit_depths": {"16-bit": "pcm_s16le", "24-bit": "pcm_s24le", "32-bit": "pcm_s32le", "32-bit float": "pcm_f32le"},
        "default_depth": "16-bit",
        "sample_rates": [8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000],
    },
    "FLAC": {
        "ext": ".flac",
        "codec": ["-c:a", "flac"],
        "lossy": False,
        "bit_depths": {"16-bit": "s16", "24-bit": "s24", "32-bit": "s32"},
        "default_depth": "16-bit",
        "compression_range": (0, 12),   # 0 = fastest, 12 = smallest
        "compression_default": 5,
        "sample_rates": [8000, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000],
    },
    "ALAC (M4A)": {
        "ext": ".m4a",
        "codec": ["-c:a", "alac"],
        "lossy": False,
        "bit_depths": {"16-bit": "s16p", "24-bit": "s24p", "32-bit": "s32p"},
        "default_depth": "16-bit",
        "sample_rates": [44100, 48000, 88200, 96000, 176400, 192000],
    },
    "AIFF": {
        "ext": ".aiff",
        "codec": [],  # set from bit depth
        "lossy": False,
        "bit_depths": {"16-bit": "pcm_s16be", "24-bit": "pcm_s24be", "32-bit": "pcm_s32be"},
        "default_depth": "16-bit",
        "sample_rates": [22050, 32000, 44100, 48000, 88200, 96000],
    },
    "WMA": {
        "ext": ".wma",
        "codec": ["-c:a", "wmav2"],
        "lossy": True,
        "bitrates": ["64k", "96k", "128k", "160k", "192k", "256k", "320k"],
        "default_br": "192k",
        "vbr_flag": None,
        "sample_rates": [22050, 32000, 44100, 48000],
    },
    "AC3": {
        "ext": ".ac3",
        "codec": ["-c:a", "ac3"],
        "lossy": True,
        "bitrates": ["128k", "192k", "224k", "256k", "320k", "384k", "448k", "640k"],
        "default_br": "384k",
        "vbr_flag": None,
        "sample_rates": [32000, 44100, 48000],
    },
}

CHANNEL_LAYOUTS = [
    ("Auto (keep original)", ""),
    ("Mono",                 "1"),
    ("Stereo",               "2"),
    ("2.1 (3ch)",            "3"),
    ("4.0 Quad",             "4"),
    ("5.0 Surround",        "5"),
    ("5.1 Surround",        "6"),
    ("7.1 Surround",        "8"),
]

NORM_MODES = [
    "None",
    "EBU R128 (loudnorm)",
    "Peak normalize",
]


class AudioExporterTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._src_info = {}   # ffprobe metadata cache
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # -- header --
        self.make_header(self, t("tab.audio_converter"),
                         subtitle=t("exporter.subtitle"),
                         icon="\U0001F4BE")  # floppy disk

        # Scrollable body
        outer = tk.Frame(self, bg=CLR["bg"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=CLR["bg"], highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self._inner = tk.Frame(canvas, bg=CLR["bg"])
        self._inner.bind("<Configure>",
                         lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add=True)

        self._build_source_section()
        self._build_source_info_section()
        self._build_format_section()
        self._build_quality_section()
        self._build_sample_section()
        self._build_trim_section()
        self._build_effects_section()
        self._build_size_section()
        self._build_metadata_section()
        self._build_output_section()
        self._build_console_section()

    # ── Source ────────────────────────────────────────────────────────────────

    def _build_source_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.source"))
        self.src_var = tk.StringVar()
        row = self.make_file_row(sec, t("exporter.input_file"), self.src_var,
                                 self._browse_src)
        row.pack(fill="x", pady=4)

    def _build_source_info_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.source_info"))
        self._info_lbl = tk.Label(sec,
                                  text="  No file loaded - browse to open a file",
                                  font=(MONO_FONT, 9), anchor="w", justify="left",
                                  bg=CLR["bg"], fg=CLR["fgdim"])
        self._info_lbl.pack(fill="x", padx=4, pady=2)

    # ── Format ───────────────────────────────────────────────────────────────

    def _build_format_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.format"))
        row = tk.Frame(sec, bg=CLR["bg"])
        row.pack(fill="x", pady=4)

        tk.Label(row, text=t("exporter.format_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.fmt_var = tk.StringVar(value="MP3")
        cb = ttk.Combobox(row, textvariable=self.fmt_var,
                          values=list(FORMAT_DEFS.keys()),
                          state="readonly", width=16)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", self._on_format_change)

        self._fmt_note = tk.Label(row, text=t("exporter.lossy_note"),
                                  font=(UI_FONT, 8, "italic"),
                                  bg=CLR["bg"], fg=CLR["fgdim"])
        self._fmt_note.pack(side="left", padx=8)

    # ── Quality / Bitrate ────────────────────────────────────────────────────

    def _build_quality_section(self):
        self._qual_sec = self.make_section(self._inner, title=t("exporter.section.quality"))

        # Bitrate mode row
        r0 = tk.Frame(self._qual_sec, bg=CLR["bg"])
        r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("exporter.mode_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.br_mode_var = tk.StringVar(value="CBR")
        self._rb_cbr = tk.Radiobutton(r0, text=t("exporter.cbr"),
                                       variable=self.br_mode_var, value="CBR",
                                       bg=CLR["bg"], fg=CLR["fg"],
                                       selectcolor=CLR["input_bg"],
                                       activebackground=CLR["bg"],
                                       command=self._toggle_br_mode)
        self._rb_cbr.pack(side="left", padx=(12, 4))
        self._rb_vbr = tk.Radiobutton(r0, text=t("exporter.vbr"),
                                       variable=self.br_mode_var, value="VBR",
                                       bg=CLR["bg"], fg=CLR["fg"],
                                       selectcolor=CLR["input_bg"],
                                       activebackground=CLR["bg"],
                                       command=self._toggle_br_mode)
        self._rb_vbr.pack(side="left", padx=4)

        # CBR bitrate row
        self._cbr_row = tk.Frame(self._qual_sec, bg=CLR["bg"])
        self._cbr_row.pack(fill="x", pady=4)
        tk.Label(self._cbr_row, text=t("exporter.bitrate_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.bitrate_var = tk.StringVar(value="320k")
        self._br_cb = ttk.Combobox(self._cbr_row, textvariable=self.bitrate_var,
                                    values=FORMAT_DEFS["MP3"]["bitrates"],
                                    state="readonly", width=8)
        self._br_cb.pack(side="left", padx=8)

        # VBR quality row
        self._vbr_row = tk.Frame(self._qual_sec, bg=CLR["bg"])
        tk.Label(self._vbr_row, text=t("exporter.vbr_quality"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.vbr_var = tk.IntVar(value=2)
        self._vbr_scale = tk.Scale(self._vbr_row, from_=0, to=9,
                                    orient="horizontal", variable=self.vbr_var,
                                    length=200,
                                    bg=CLR["bg"], fg=CLR["fg"],
                                    troughcolor=CLR["input_bg"],
                                    highlightthickness=0)
        self._vbr_scale.pack(side="left", padx=8)
        self._vbr_hint = tk.Label(self._vbr_row, text="0 = best, 9 = smallest",
                                   font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"])
        self._vbr_hint.pack(side="left", padx=4)

        # Lossless bit depth row
        self._depth_row = tk.Frame(self._qual_sec, bg=CLR["bg"])
        tk.Label(self._depth_row, text=t("exporter.bit_depth"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.depth_var = tk.StringVar(value="16-bit")
        self._depth_cb = ttk.Combobox(self._depth_row, textvariable=self.depth_var,
                                       values=["16-bit", "24-bit", "32-bit"],
                                       state="readonly", width=12)
        self._depth_cb.pack(side="left", padx=8)

        # FLAC compression row
        self._comp_row = tk.Frame(self._qual_sec, bg=CLR["bg"])
        tk.Label(self._comp_row, text=t("exporter.compression"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.comp_var = tk.IntVar(value=5)
        self._comp_scale = tk.Scale(self._comp_row, from_=0, to=12,
                                     orient="horizontal", variable=self.comp_var,
                                     length=200,
                                     bg=CLR["bg"], fg=CLR["fg"],
                                     troughcolor=CLR["input_bg"],
                                     highlightthickness=0)
        self._comp_scale.pack(side="left", padx=8)
        tk.Label(self._comp_row, text=t("exporter.compression_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=4)

        # Initial state
        self._toggle_br_mode()

    # ── Sample rate & channels ───────────────────────────────────────────────

    def _build_sample_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.sample"))

        r0 = tk.Frame(sec, bg=CLR["bg"])
        r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("exporter.sample_rate"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.sr_var = tk.StringVar(value="Auto")
        sr_vals = ["Auto"] + [f"{r} Hz" for r in [8000, 11025, 16000, 22050,
                   32000, 44100, 48000, 88200, 96000, 176400, 192000]]
        self._sr_cb = ttk.Combobox(r0, textvariable=self.sr_var,
                                    values=sr_vals, state="readonly", width=14)
        self._sr_cb.pack(side="left", padx=8)

        tk.Label(r0, text=t("exporter.channels"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(20, 0))
        self.ch_var = tk.StringVar(value="Auto (keep original)")
        self._ch_cb = ttk.Combobox(r0, textvariable=self.ch_var,
                                    values=[c[0] for c in CHANNEL_LAYOUTS],
                                    state="readonly", width=20)
        self._ch_cb.pack(side="left", padx=8)

    # ── Trim ─────────────────────────────────────────────────────────────────

    def _build_trim_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.trim"))
        row = tk.Frame(sec, bg=CLR["bg"])
        row.pack(fill="x", pady=4)

        tk.Label(row, text=t("exporter.start_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.trim_start = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.trim_start, width=12,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(row, text=t("exporter.time_hint"), font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=(0, 16))

        tk.Label(row, text=t("exporter.end_label"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.trim_end = tk.StringVar(value="")
        tk.Entry(row, textvariable=self.trim_end, width=12,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(row, text=t("exporter.blank_hint"), font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

    # ── Effects (fade, normalize) ────────────────────────────────────────────

    def _build_effects_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.effects"))

        # Fades
        r0 = tk.Frame(sec, bg=CLR["bg"])
        r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("exporter.fade_in"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.fade_in = tk.StringVar(value="0")
        tk.Entry(r0, textvariable=self.fade_in, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r0, text=t("exporter.sec"), font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=(0, 16))

        tk.Label(r0, text=t("exporter.fade_out"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.fade_out = tk.StringVar(value="0")
        tk.Entry(r0, textvariable=self.fade_out, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r0, text=t("exporter.sec"), font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        # Volume
        r1 = tk.Frame(sec, bg=CLR["bg"])
        r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("exporter.volume_adjust"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.volume_var = tk.StringVar(value="0")
        tk.Entry(r1, textvariable=self.volume_var, width=6,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(r1, text=t("exporter.volume_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        # Normalization
        r2 = tk.Frame(sec, bg=CLR["bg"])
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("exporter.normalize"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.norm_var = tk.StringVar(value="None")
        ttk.Combobox(r2, textvariable=self.norm_var, values=NORM_MODES,
                     state="readonly", width=22).pack(side="left", padx=8)

        self._norm_opts = tk.Frame(sec, bg=CLR["bg"])
        self._norm_opts.pack(fill="x", pady=2)
        tk.Label(self._norm_opts, text="  " + t("exporter.target_lufs"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.lufs_var = tk.StringVar(value="-16.0")
        tk.Entry(self._norm_opts, textvariable=self.lufs_var, width=7,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(self._norm_opts, text=t("exporter.true_peak"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(12, 0))
        self.tp_var = tk.StringVar(value="-1.5")
        tk.Entry(self._norm_opts, textvariable=self.tp_var, width=7,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)
        tk.Label(self._norm_opts, text="dBTP", font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        # Mono mix-down
        r3 = tk.Frame(sec, bg=CLR["bg"])
        r3.pack(fill="x", pady=4)
        self.strip_silence_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text=t("exporter.strip_silence"),
                       variable=self.strip_silence_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left")

        self.replay_gain_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text=t("exporter.replay_gain"),
                       variable=self.replay_gain_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=(20, 0))

    # ── Max file size ────────────────────────────────────────────────────────

    def _build_size_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.size"))
        row = tk.Frame(sec, bg=CLR["bg"])
        row.pack(fill="x", pady=4)

        self.limit_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text=t("exporter.target_max_size"),
                       variable=self.limit_enabled,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left")
        self.max_size_var = tk.StringVar(value="10")
        tk.Entry(row, textvariable=self.max_size_var, width=8,
                 relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 font=(UI_FONT, 9)).pack(side="left", padx=4)

        self.size_unit_var = tk.StringVar(value="MB")
        ttk.Combobox(row, textvariable=self.size_unit_var,
                     values=["KB", "MB"], state="readonly",
                     width=4).pack(side="left", padx=4)
        tk.Label(row, text=t("exporter.auto_calc_hint"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=8)

    # ── Metadata ─────────────────────────────────────────────────────────────

    def _build_metadata_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.metadata"))

        self.meta_vars = {}
        fields = [
            ("Title",   "title",   30),
            ("Artist",  "artist",  30),
            ("Album",   "album",   30),
            ("Genre",   "genre",   16),
            ("Year",    "date",     8),
            ("Track #", "track",    6),
            ("Comment", "comment", 40),
        ]

        row = None
        for i, (label, key, w) in enumerate(fields):
            if i % 3 == 0:
                row = tk.Frame(sec, bg=CLR["bg"])
                row.pack(fill="x", pady=2)
            var = tk.StringVar(value="")
            self.meta_vars[key] = var
            tk.Label(row, text=label, font=(UI_FONT, 9),
                     bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(8, 0))
            tk.Entry(row, textvariable=var, width=w,
                     relief="flat", bg=CLR["input_bg"], fg=CLR["input_fg"],
                     insertbackground=CLR["accent"],
                     font=(UI_FONT, 9)).pack(side="left", padx=4)

        opts_row = tk.Frame(sec, bg=CLR["bg"])
        opts_row.pack(fill="x", pady=4)
        self.strip_meta_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts_row, text=t("exporter.strip_all_meta"),
                       variable=self.strip_meta_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=8)
        self.strip_art_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts_row, text=t("exporter.strip_art"),
                       variable=self.strip_art_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=8)
        self.copy_meta_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opts_row, text=t("exporter.copy_meta"),
                       variable=self.copy_meta_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=8)

    # ── Output ───────────────────────────────────────────────────────────────

    def _build_output_section(self):
        sec = self.make_section(self._inner, title=t("exporter.section.output"))
        self.out_var = tk.StringVar()
        row = self.make_file_row(sec, t("exporter.save_as"), self.out_var,
                                 self._browse_out)
        row.pack(fill="x", pady=4)

        # Overwrite warning
        opts = tk.Frame(sec, bg=CLR["bg"])
        opts.pack(fill="x", pady=2)
        self.overwrite_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text=t("exporter.overwrite"),
                       variable=self.overwrite_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=8)
        self.open_folder_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts, text=t("exporter.open_folder"),
                       variable=self.open_folder_var,
                       bg=CLR["bg"], fg=CLR["fg"],
                       selectcolor=CLR["input_bg"],
                       activebackground=CLR["bg"]).pack(side="left", padx=8)

        # Export button
        btn_row = tk.Frame(self._inner, bg=CLR["bg"])
        btn_row.pack(fill="x", pady=(12, 6))
        self.btn_export = self.make_render_btn(btn_row, t("exporter.export_btn"),
                                                self._export, color=CLR["green"],
                                                width=30)
        self.btn_export.pack(pady=4)

    # ── Console ──────────────────────────────────────────────────────────────

    def _build_console_section(self):
        cf = tk.Frame(self._inner, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 14))
        self.console, csb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _browse_src(self):
        p = filedialog.askopenfilename(
            title="Open audio / video file",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.flac *.aac *.m4a *.ogg *.opus "
                                "*.wma *.aiff *.ac3 *.alac *.ape *.wv"),
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts"),
                ("All files", "*.*"),
            ])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self._probe_source(p)

    def _browse_out(self):
        fmt_def = FORMAT_DEFS[self.fmt_var.get()]
        ext = fmt_def["ext"]
        p = filedialog.asksaveasfilename(
            title="Save audio as",
            defaultextension=ext,
            filetypes=[(self.fmt_var.get(), f"*{ext}"), ("All files", "*.*")])
        if p:
            self.out_var.set(p)

    def _probe_source(self, path):
        """Run ffprobe in background to populate source info."""
        def _do():
            ffprobe = get_binary_path("ffprobe.exe")
            cmd = [ffprobe, "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", path]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=CREATE_NO_WINDOW)
                data = json.loads(r.stdout)
            except Exception:
                self.after(0, lambda: self._info_lbl.config(
                    text="  Could not read file info", fg=CLR["red"]))
                return

            self._src_info = data
            fmt_info = data.get("format", {})
            # Find first audio stream
            audio_stream = None
            for s in data.get("streams", []):
                if s.get("codec_type") == "audio":
                    audio_stream = s
                    break

            if not audio_stream:
                self.after(0, lambda: self._info_lbl.config(
                    text="  No audio stream found in file", fg=CLR["red"]))
                return

            codec = audio_stream.get("codec_long_name",
                    audio_stream.get("codec_name", "?"))
            sr = audio_stream.get("sample_rate", "?")
            ch = audio_stream.get("channels", "?")
            ch_layout = audio_stream.get("channel_layout", "")
            bits = audio_stream.get("bits_per_raw_sample",
                   audio_stream.get("bits_per_sample", ""))
            duration = fmt_info.get("duration", "?")
            bitrate = fmt_info.get("bit_rate", "?")
            size = fmt_info.get("size", "?")

            try:
                dur_f = float(duration)
                dur_str = f"{int(dur_f//3600):02d}:{int((dur_f%3600)//60):02d}:{dur_f%60:05.2f}"
            except (ValueError, TypeError):
                dur_str = str(duration)

            try:
                br_str = f"{int(bitrate)//1000}k"
            except (ValueError, TypeError):
                br_str = str(bitrate)

            try:
                sz_mb = int(size) / (1024 * 1024)
                sz_str = f"{sz_mb:.2f} MB"
            except (ValueError, TypeError):
                sz_str = str(size)

            bits_str = f"  |  Depth: {bits}-bit" if bits else ""
            ch_str = f"{ch}ch" + (f" ({ch_layout})" if ch_layout else "")

            info = (f"  Codec: {codec}  |  {sr} Hz  |  {ch_str}{bits_str}\n"
                    f"  Duration: {dur_str}  |  Bitrate: {br_str}  |  "
                    f"Size: {sz_str}")

            # Auto-populate metadata fields from source tags
            tags = {**fmt_info.get("tags", {}),
                    **audio_stream.get("tags", {})}
            for key, var in self.meta_vars.items():
                val = tags.get(key, tags.get(key.upper(), ""))
                if val and not var.get():
                    self.after(0, lambda v=var, x=val: v.set(str(x)))

            self.after(0, lambda: self._info_lbl.config(
                text=info, fg=CLR["accent"]))
            self.after(0, lambda: self.log_tagged(
                self.console, f"Loaded: {os.path.basename(path)}", "info"))

        self.run_in_thread(_do)

    def _on_format_change(self, *_):
        """Reconfigure quality section when format changes."""
        fmt = self.fmt_var.get()
        fd = FORMAT_DEFS[fmt]

        # Update format note
        if fd["lossy"]:
            self._fmt_note.config(text=t("exporter.lossy_note"))
        else:
            self._fmt_note.config(text=t("exporter.lossless_uncompressed")
                                  if fmt in ("WAV", "AIFF")
                                  else t("exporter.lossless_compressed"))

        self._toggle_br_mode()

    def _toggle_br_mode(self):
        """Show/hide quality controls based on format + mode."""
        fmt = self.fmt_var.get()
        fd = FORMAT_DEFS[fmt]

        # Hide everything first
        self._cbr_row.pack_forget()
        self._vbr_row.pack_forget()
        self._depth_row.pack_forget()
        self._comp_row.pack_forget()

        if fd["lossy"]:
            # Lossy: show CBR/VBR controls
            self._rb_cbr.pack(side="left", padx=(12, 4))
            self._rb_vbr.pack(side="left", padx=4)

            # Update bitrate list
            self._br_cb.config(values=fd["bitrates"])
            self.bitrate_var.set(fd["default_br"])

            has_vbr = fd.get("vbr_flag") is not None

            if not has_vbr:
                self.br_mode_var.set("CBR")
            self._rb_vbr.config(state="normal" if has_vbr else "disabled")

            if self.br_mode_var.get() == "CBR" or not has_vbr:
                self._cbr_row.pack(fill="x", pady=4)
            else:
                self._vbr_row.pack(fill="x", pady=4)
                vr = fd.get("vbr_range", (0, 9))
                self._vbr_scale.config(from_=vr[0], to=vr[1])
                self.vbr_var.set(fd.get("vbr_default", vr[0]))
                self._vbr_hint.config(
                    text=f"{vr[0]} = {'best' if fd.get('ext') != '.ogg' else 'worst'}, "
                         f"{vr[1]} = {'smallest' if fd.get('ext') != '.ogg' else 'best'}")
        else:
            # Lossless: show bit depth
            self._rb_cbr.pack_forget()
            self._rb_vbr.pack_forget()

            depths = fd.get("bit_depths", {})
            if depths:
                self._depth_row.pack(fill="x", pady=4)
                self._depth_cb.config(values=list(depths.keys()))
                self.depth_var.set(fd.get("default_depth", "16-bit"))

            # FLAC compression
            if fmt == "FLAC":
                self._comp_row.pack(fill="x", pady=4)
                cr = fd.get("compression_range", (0, 12))
                self._comp_scale.config(from_=cr[0], to=cr[1])
                self.comp_var.set(fd.get("compression_default", 5))

    # ── Build FFmpeg command ─────────────────────────────────────────────────

    def _build_cmd(self, out_path):
        """Construct the full FFmpeg command from current UI state."""
        ffmpeg = get_binary_path("ffmpeg.exe")
        fmt = self.fmt_var.get()
        fd = FORMAT_DEFS[fmt]

        cmd = [ffmpeg]

        # Trim: start
        ss = self.trim_start.get().strip()
        if ss:
            cmd += ["-ss", ss]

        cmd += ["-i", self.file_path]

        # Trim: end
        to = self.trim_end.get().strip()
        if to:
            cmd += ["-to", to]

        # No video
        cmd += ["-vn"]

        # ── Codec ────────────────────────────────────────────────────────
        if fd["lossy"]:
            cmd += fd["codec"]

            if self.limit_enabled.get():
                # Auto-calculate bitrate from max size
                br = self._calc_bitrate_for_size()
                if br:
                    cmd += ["-b:a", f"{br}k"]
                else:
                    cmd += ["-b:a", self.bitrate_var.get()]
            elif self.br_mode_var.get() == "VBR" and fd.get("vbr_flag"):
                cmd += [fd["vbr_flag"], str(self.vbr_var.get())]
            else:
                cmd += ["-b:a", self.bitrate_var.get()]
        else:
            # Lossless
            depths = fd.get("bit_depths", {})
            depth_key = self.depth_var.get()
            if fmt in ("WAV", "AIFF"):
                codec_name = depths.get(depth_key, "pcm_s16le")
                cmd += ["-c:a", codec_name]
            elif fmt == "FLAC":
                cmd += fd["codec"]
                sample_fmt = depths.get(depth_key, "s16")
                cmd += ["-sample_fmt", sample_fmt]
                cmd += ["-compression_level", str(self.comp_var.get())]
            elif fmt == "ALAC (M4A)":
                cmd += fd["codec"]
                sample_fmt = depths.get(depth_key, "s16p")
                cmd += ["-sample_fmt", sample_fmt]
            else:
                cmd += fd["codec"]

        # ── Sample rate ──────────────────────────────────────────────────
        sr = self.sr_var.get()
        if sr != "Auto":
            sr_val = sr.replace(" Hz", "")
            cmd += ["-ar", sr_val]

        # ── Channels ─────────────────────────────────────────────────────
        ch_display = self.ch_var.get()
        for label, val in CHANNEL_LAYOUTS:
            if label == ch_display and val:
                cmd += ["-ac", val]
                break

        # ── Audio filters ────────────────────────────────────────────────
        af_parts = []

        # Volume adjust
        vol = self.volume_var.get().strip()
        if vol and vol != "0":
            af_parts.append(f"volume={vol}dB")

        # Fade in/out
        fi = self.fade_in.get().strip()
        if fi and fi != "0":
            af_parts.append(f"afade=t=in:st=0:d={fi}")
        fo = self.fade_out.get().strip()
        if fo and fo != "0":
            # Need duration for fade out start - use a large number,
            # FFmpeg will clamp to actual end
            af_parts.append(f"areverse,afade=t=in:d={fo},areverse")

        # Normalization
        norm = self.norm_var.get()
        if norm == "EBU R128 (loudnorm)":
            lufs = self.lufs_var.get()
            tp = self.tp_var.get()
            af_parts.append(f"loudnorm=I={lufs}:TP={tp}:LRA=11")
        elif norm == "Peak normalize":
            af_parts.append("dynaudnorm=p=0.95:g=3")

        # Strip silence
        if self.strip_silence_var.get():
            af_parts.append("silenceremove=start_periods=1:start_silence=0.1"
                           ":start_threshold=-50dB,"
                           "areverse,silenceremove=start_periods=1"
                           ":start_silence=0.1:start_threshold=-50dB,areverse")

        # ReplayGain
        if self.replay_gain_var.get():
            af_parts.append("replaygain")

        if af_parts:
            cmd += ["-af", ",".join(af_parts)]

        # ── Metadata ─────────────────────────────────────────────────────
        if self.strip_meta_var.get():
            cmd += ["-map_metadata", "-1"]
        elif self.copy_meta_var.get():
            pass  # metadata copies by default
        else:
            cmd += ["-map_metadata", "-1"]

        # User metadata tags
        for key, var in self.meta_vars.items():
            val = var.get().strip()
            if val:
                cmd += ["-metadata", f"{key}={val}"]

        # Strip cover art
        if self.strip_art_var.get():
            cmd += ["-map", "0:a"]

        # Overwrite
        if self.overwrite_var.get():
            cmd += ["-y"]

        cmd.append(out_path)
        return cmd

    def _calc_bitrate_for_size(self):
        """Calculate bitrate to hit target file size."""
        try:
            max_val = float(self.max_size_var.get())
            if self.size_unit_var.get() == "MB":
                max_bytes = max_val * 1024 * 1024
            else:
                max_bytes = max_val * 1024

            # Get duration from source info
            dur = float(self._src_info.get("format", {}).get("duration", 0))
            if dur <= 0:
                return None

            # Account for trim
            ss = self.trim_start.get().strip()
            to = self.trim_end.get().strip()
            start_s = self._parse_time(ss) if ss else 0
            end_s = self._parse_time(to) if to else dur
            trimmed_dur = end_s - start_s
            if trimmed_dur <= 0:
                trimmed_dur = dur

            # bitrate = (bytes * 8) / seconds, leave 5% margin for container
            target_bits = (max_bytes * 8 * 0.95) / trimmed_dur
            return int(target_bits / 1000)  # kbps
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    @staticmethod
    def _parse_time(s):
        """Parse HH:MM:SS or seconds string to float seconds."""
        s = s.strip()
        if not s:
            return 0
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
        return float(s)

    # ── Export ────────────────────────────────────────────────────────────────

    def _export(self):
        if not self.file_path:
            messagebox.showwarning(t("exporter.no_input"), t("exporter.no_input"))
            return

        out = self.out_var.get().strip()
        if not out:
            self._browse_out()
            out = self.out_var.get().strip()
        if not out:
            return

        # Confirm overwrite
        if not self.overwrite_var.get() and os.path.exists(out):
            if not messagebox.askyesno(t("exporter.overwrite_title"),
                                       f"File already exists:\n{out}\n\nOverwrite?"):
                return

        cmd = self._build_cmd(out)

        self.log(self.console, "")
        self.log_tagged(self.console,
                        f"Exporting: {os.path.basename(self.file_path)} "
                        f"-> {self.fmt_var.get()}", "info")
        self.log(self.console, f"  Output: {out}")

        def _on_done(rc):
            self.show_result(rc, out)
            if rc == 0 and self.open_folder_var.get():
                self.open_path(os.path.dirname(out))

        self.run_ffmpeg(cmd, self.console, on_done=_on_done,
                        btn=self.btn_export,
                        btn_label=t("exporter.export_btn"))
