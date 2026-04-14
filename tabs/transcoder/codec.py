"""
tab_codeccruncher.py  ─  Codec Cruncher
Re-encode video with full control over codec, bitrate, and quality.
Supports H.264, H.265/HEVC, AV1, VP9, ProRes, DNxHD.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, detect_gpu
from core.i18n import t


CODECS = {
    t("codec.h_264_libx264"):     {"vcodec": "libx264",   "pix": "yuv420p",    "has_crf": True,  "preset": True},
    "H.265 / HEVC (libx265)": {"vcodec": "libx265", "pix": "yuv420p",   "has_crf": True,  "preset": True},
    "AV1 (libaom-av1)":    {"vcodec": "libaom-av1","pix": "yuv420p",    "has_crf": True,  "preset": False},
    "VP9 (libvpx-vp9)":    {"vcodec": "libvpx-vp9","pix": "yuv420p",   "has_crf": True,  "preset": False},
    "ProRes 422 HQ":        {"vcodec": "prores_ks", "pix": "yuv422p10le","has_crf": False, "preset": False,
                             "extra": ["-profile:v", "3"]},
    "ProRes 4444":          {"vcodec": "prores_ks", "pix": "yuva444p10le","has_crf": False,"preset": False,
                             "extra": ["-profile:v", "4"]},
    "DNxHD 185 (Avid)":    {"vcodec": "dnxhd",     "pix": "yuv422p",    "has_crf": False, "preset": False,
                             "extra": ["-vb", "185M"]},
    "Copy (no re-encode)":  {"vcodec": "copy",      "pix": None,         "has_crf": False, "preset": False},
}

AUDIO_CODECS = {
    "AAC 256k":     ["-c:a", "aac", "-b:a", "256k"],
    "AAC 192k":     ["-c:a", "aac", "-b:a", "192k"],
    "MP3 320k":     ["-c:a", "libmp3lame", "-b:a", "320k"],
    "FLAC":         ["-c:a", "flac"],
    "PCM 24-bit":   ["-c:a", "pcm_s24le"],
    "Copy":         ["-c:a", "copy"],
    t("codec.remove_audio"): ["-an"],
}


class CodecCruncherTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.gpu = detect_gpu()
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔩  " + t("tab.codec_cruncher"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("codec.desc_subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Video codec
        vc = tk.LabelFrame(self, text=t("section.video_codec"), padx=15, pady=8)
        vc.pack(fill="x", padx=20, pady=5)

        r0 = tk.Frame(vc); r0.pack(fill="x", pady=3)
        tk.Label(r0, text=t("common.codec"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.codec_var = tk.StringVar(value=list(CODECS.keys())[0])
        codec_cb = ttk.Combobox(r0, textvariable=self.codec_var, values=list(CODECS.keys()),
                                state="readonly", width=28)
        codec_cb.pack(side="left", padx=8)
        codec_cb.bind("<<ComboboxSelected>>", self._on_codec_change)

        r1 = tk.Frame(vc); r1.pack(fill="x", pady=3)
        tk.Label(r1, text=t("codec.lbl_crf_quality")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        self.crf_entry = tk.Entry(r1, textvariable=self.crf_var, width=5, relief="flat")
        self.crf_entry.pack(side="left", padx=4)
        tk.Label(r1, text=t("codec.lbl_preset")).pack(side="left", padx=(12, 0))
        self.preset_var = tk.StringVar(value="medium")
        self.preset_cb = ttk.Combobox(r1, textvariable=self.preset_var,
                                       values=["ultrafast","superfast","veryfast","faster","fast",
                                               "medium","slow","slower","veryslow"],
                                       state="readonly", width=12)
        self.preset_cb.pack(side="left", padx=4)
        tk.Label(r1, text=t("codec.lbl_pixel_format")).pack(side="left", padx=(12, 0))
        self.pix_var = tk.StringVar(value="yuv420p")
        ttk.Combobox(r1, textvariable=self.pix_var,
                     values=["yuv420p", "yuv422p", "yuv444p",
                              "yuv420p10le", "yuv422p10le"],
                     state="readonly", width=14).pack(side="left", padx=4)

        # GPU accel note
        gpu_f = tk.Frame(vc); gpu_f.pack(anchor="w", pady=2)
        tk.Label(gpu_f, text=f"GPU: {self.gpu.upper()}",
                 fg=CLR["green"] if self.gpu != "cpu" else CLR["fgdim"]).pack(side="left")
        self.hwaccel_var = tk.BooleanVar(value=self.gpu != "cpu")
        tk.Checkbutton(gpu_f, text=t("codec.opt_hwaccel"),
                       variable=self.hwaccel_var).pack(side="left", padx=10)

        # Audio codec
        ac = tk.LabelFrame(self, text=t("section.audio_codec"), padx=15, pady=8)
        ac.pack(fill="x", padx=20, pady=5)
        r2 = tk.Frame(ac); r2.pack(fill="x")
        tk.Label(r2, text=t("codec.lbl_audio")).pack(side="left")
        self.audio_var = tk.StringVar(value="AAC 256k")
        ttk.Combobox(r2, textvariable=self.audio_var, values=list(AUDIO_CODECS.keys()),
                     state="readonly", width=16).pack(side="left", padx=6)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("codec.btn_encode"), font=(UI_FONT, 12, "bold"),
            bg=CLR["accent"], fg="black", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_codec_change(self, *_):
        info = CODECS[self.codec_var.get()]
        state = "normal" if info["has_crf"] else "disabled"
        self.crf_entry.config(state=state)
        pstate = "readonly" if info["preset"] else "disabled"
        self.preset_cb.config(state=pstate)
        if info.get("pix"):
            self.pix_var.set(info["pix"])

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        ext = ".mov" if "ProRes" in self.codec_var.get() or "DNx" in self.codec_var.get() else ".mp4"
        p = filedialog.asksaveasfilename(defaultextension=ext,
                                         filetypes=[("Video", f"*{ext}"), ("All", t("ducker.item_2"))])
        if p: self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("codec.msg_no_file_title"), t("codec.msg_no_file"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4")
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        info = CODECS[self.codec_var.get()]
        vcodec = info["vcodec"]

        # HW accel override
        if self.hwaccel_var.get() and self.gpu == "nvidia" and vcodec == "libx265":
            vcodec = "hevc_nvenc"
        elif self.hwaccel_var.get() and self.gpu == "nvidia" and vcodec == "libx264":
            vcodec = "h264_nvenc"

        cmd = [ffmpeg, "-i", self.file_path, t("dynamics.c_v"), vcodec]

        if info["has_crf"]:
            cmd += ["-crf", self.crf_var.get()]
        if info["preset"] and "nvenc" not in vcodec:
            cmd += ["-preset", self.preset_var.get()]
        if info.get("pix") and vcodec != "copy":
            cmd += ["-pix_fmt", self.pix_var.get()]
        for e in info.get("extra", []):
            cmd.append(e)

        cmd += AUDIO_CODECS[self.audio_var.get()]
        cmd += ["-movflags", "+faststart", out, "-y"]

        self.log(self.console, f"Encoding with {vcodec}…")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("codec.btn_encode"))
