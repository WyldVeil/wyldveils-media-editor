"""
tab_audioextractor.py  ─  Audio Extractor
Rip audio from any video file into MP3, WAV, FLAC, AAC, or OGG.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


FORMAT_MAP = {
    "MP3":  (".mp3",  ["-c:a", "libmp3lame"]),
    "AAC":  (".aac",  ["-c:a", "aac"]),
    "WAV":  (".wav",  ["-c:a", "pcm_s16le"]),
    "FLAC": (".flac", ["-c:a", "flac"]),
    "OGG":  (".ogg",  ["-c:a", "libvorbis"]),
    "M4A":  (".m4a",  ["-c:a", "aac"]),
}


class AudioExtractorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎵  " + t("tab.audio_extractor"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("extractor.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=14)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Options
        opts = tk.LabelFrame(self, text=t("extractor.extraction_options_section"), padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("extractor.output_format_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.fmt_var = tk.StringVar(value="MP3")
        fmt_cb = ttk.Combobox(r0, textvariable=self.fmt_var, values=list(FORMAT_MAP.keys()),
                              state="readonly", width=8)
        fmt_cb.pack(side="left", padx=8)
        fmt_cb.bind("<<ComboboxSelected>>", self._on_fmt_change)

        tk.Label(r0, text=t("common.quality"), font=(UI_FONT, 10, "bold")).pack(side="left", padx=(20, 4))
        self.bitrate_var = tk.StringVar(value="320k")
        self.br_cb = ttk.Combobox(r0, textvariable=self.bitrate_var,
                                   values=["96k", "128k", "192k", "256k", "320k"],
                                   state="readonly", width=7)
        self.br_cb.pack(side="left", padx=4)

        # Lossless note
        self.lossless_lbl = tk.Label(opts, text="", fg=CLR["fgdim"], font=(UI_FONT, 9, "italic"))
        self.lossless_lbl.pack(anchor="w")

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("common.start_s")).pack(side="left")
        self.start_var = tk.StringVar(value="0")
        tk.Entry(r1, textvariable=self.start_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(r1, text=t("common.end_s")).pack(side="left", padx=(12, 0))
        self.end_var = tk.StringVar(value="0")
        tk.Entry(r1, textvariable=self.end_var, width=7, relief="flat").pack(side="left", padx=4)
        self.normalize_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r1, text=t("extractor.normalize_checkbox"),
                       variable=self.normalize_var).pack(side="left", padx=20)

        # Output
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("extractor.extract_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_fmt_change(self, *_):
        fmt = self.fmt_var.get()
        lossless = fmt in ("WAV", "FLAC")
        self.br_cb.config(state="disabled" if lossless else "readonly")
        self.lossless_lbl.config(
            text=t("extractor.lossless_note") if lossless else "")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("extractor.video_audio"), "*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.aac"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        ext = FORMAT_MAP[self.fmt_var.get()][0]
        p = filedialog.asksaveasfilename(defaultextension=ext,
                                         filetypes=[(self.fmt_var.get(), f"*{ext}")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(
                defaultextension=FORMAT_MAP[self.fmt_var.get()][0],
                filetypes=[(self.fmt_var.get(), f"*{FORMAT_MAP[self.fmt_var.get()][0]}")])
        if not out:
            return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        fmt, codec_args = FORMAT_MAP[self.fmt_var.get()]
        lossless = fmt in (".wav", ".flac")

        cmd = [ffmpeg, "-i", self.file_path]
        ss = self.start_var.get()
        end = self.end_var.get()
        if ss and ss != "0":
            cmd += ["-ss", ss]
        if end and end != "0":
            cmd += ["-to", end]

        cmd += codec_args
        if not lossless:
            cmd += ["-b:a", self.bitrate_var.get()]

        if self.normalize_var.get():
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]

        cmd += ["-vn", out, "-y"]

        self.log(self.console, f"Extracting audio → {self.fmt_var.get()}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("extractor.extract_button"))
