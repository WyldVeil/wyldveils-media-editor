"""
tab_formatconverter.py  ─  Format Converter
Convert between any video/audio container formats.
Attempts stream-copy first for speed; falls back to re-encode.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


OUTPUT_FORMATS = [
    "MP4", "MKV", "MOV", "AVI", "WEBM", "FLV", "TS", "M4V",
    "MP3", "AAC", "WAV", "FLAC", "OGG", "M4A",
]

FORMAT_NOTES = {
    "MP4":  "Best compatibility. H.264/AAC inside.",
    "MKV":  "Open container. Supports any codec.",
    "MOV":  "Apple QuickTime. ProRes native.",
    "AVI":  "Legacy Windows. Wide compat.",
    "WEBM": "Web streaming. VP9/Opus.",
    "FLV":  "Flash legacy. Avoid for new work.",
    "TS":   "Transport Stream. Broadcast.",
    "MP3":  "Audio only. Lossy.",
    "AAC":  "Audio only. High quality lossy.",
    "WAV":  "Audio only. Uncompressed PCM.",
    "FLAC": "Audio only. Lossless.",
}


class FormatConverterTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_paths = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔄  " + t("tab.format_converter"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("converter.desc_subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File list
        lf = tk.LabelFrame(self, text=t("section.input_files"), padx=10, pady=6)
        lf.pack(fill="both", expand=True, padx=20, pady=8)
        self.listbox = tk.Listbox(lf, height=7, bg=CLR["bg"], fg=CLR["fg"],
                                   font=(MONO_FONT, 10))
        sb = ttk.Scrollbar(lf, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_f = tk.Frame(self); btn_f.pack(pady=4)
        tk.Button(btn_f, text=t("converter.btn_add_files"),  bg=CLR["panel"], fg=CLR["fg"], command=self._add, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(btn_f, text=t("converter.btn_remove"),     bg=CLR["panel"], fg=CLR["fg"], command=self._remove, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(btn_f, text=t("converter.btn_clear"),      bg=CLR["panel"], fg=CLR["fg"], command=self._clear, cursor="hand2", relief="flat").pack(side="left", padx=4)

        # Options
        opts = tk.LabelFrame(self, text=t("converter.sect_conversion_options"), padx=15, pady=8)
        opts.pack(fill="x", padx=20, pady=5)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("converter.lbl_output_format"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.fmt_var = tk.StringVar(value="MP4")
        fmt_cb = ttk.Combobox(r0, textvariable=self.fmt_var, values=OUTPUT_FORMATS,
                              state="readonly", width=8)
        fmt_cb.pack(side="left", padx=8)
        fmt_cb.bind("<<ComboboxSelected>>", self._on_fmt)
        self.fmt_note = tk.Label(r0, text=FORMAT_NOTES.get("MP4", ""),
                                  fg=CLR["fgdim"], font=(UI_FONT, 9, "italic"))
        self.fmt_note.pack(side="left", padx=8)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        self.copy_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r1, text=t("converter.opt_stream_copy"),
                       variable=self.copy_var).pack(side="left")

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.output_folder")).pack(side="left")
        self.out_dir_var = tk.StringVar()
        tk.Entry(r2, textvariable=self.out_dir_var, width=50, relief="flat").pack(side="left", padx=6)
        tk.Button(r2, text=t("btn.browse"), command=self._browse_dir, cursor="hand2", relief="flat").pack(side="left")
        tk.Label(r2, text=t("converter.lbl_blank_hint"), fg=CLR["fgdim"]).pack(side="left", padx=6)

        self.btn_render = tk.Button(
            self, text=t("converter.btn_convert_all"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        self.prog_lbl = tk.Label(self, text="", fg=CLR["fgdim"])
        self.prog_lbl.pack()

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_fmt(self, *_):
        fmt = self.fmt_var.get()
        self.fmt_note.config(text=FORMAT_NOTES.get(fmt, ""))

    def _add(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.aac *.wav *.flac"), ("All", t("ducker.item_2"))])
        for p in paths:
            if p not in self.file_paths:
                self.file_paths.append(p)
                self.listbox.insert(tk.END, f"  {os.path.basename(p)}")

    def _remove(self):
        sel = self.listbox.curselection()
        if sel:
            self.file_paths.pop(sel[0])
            self.listbox.delete(sel[0])

    def _clear(self):
        self.file_paths.clear()
        self.listbox.delete(0, tk.END)

    def _browse_dir(self):
        p = filedialog.askdirectory()
        if p: self.out_dir_var.set(p)

    def _render(self):
        if not self.file_paths:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        fmt = self.fmt_var.get().lower()
        out_dir = self.out_dir_var.get().strip()
        copy = self.copy_var.get()
        paths = self.file_paths[:]

        def _work():
            ffmpeg = get_binary_path("ffmpeg.exe")
            for i, src in enumerate(paths):
                base = os.path.splitext(os.path.basename(src))[0]
                dst_dir = out_dir if out_dir else os.path.dirname(src)
                os.makedirs(dst_dir, exist_ok=True)
                out = os.path.join(dst_dir, f"{base}.{fmt}")
                if copy:
                    cmd = [ffmpeg, "-i", src, "-c", "copy", out, "-y"]
                else:
                    if fmt in ("mp3",):
                        cmd = [ffmpeg, "-i", src, "-vn", t("dynamics.c_a"), "libmp3lame",
                               t("dynamics.b_a"), "320k", out, "-y"]
                    elif fmt in ("wav",):
                        cmd = [ffmpeg, "-i", src, "-vn", t("dynamics.c_a"), "pcm_s16le", out, "-y"]
                    elif fmt in ("flac",):
                        cmd = [ffmpeg, "-i", src, "-vn", t("dynamics.c_a"), "flac", out, "-y"]
                    else:
                        cmd = [ffmpeg, "-i", src, t("dynamics.c_v"), "libx264", "-crf", "18",
                               t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", out, "-y"]

                self.after(0, lambda i=i, n=len(paths): self.prog_lbl.config(
                    text=f"File {i+1} of {n}…"))
                self.log(self.console, f"[{i+1}/{len(paths)}] → {os.path.basename(out)}")
                subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)

            self.after(0, lambda: self.prog_lbl.config(
                text=f"✅ Converted {len(paths)} file(s)."))
            self.after(0, lambda: messagebox.showinfo(t("common.done"), f"Converted {len(paths)} file(s)."))

        self.run_in_thread(_work)
