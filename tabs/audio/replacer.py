"""
tab_audioreplacer.py  ─  Audio Replacer
Replace or mix the audio track of a video with a new audio file.
Supports offset, volume mixing, and fade in/out.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration
from core.i18n import t


class AudioReplacerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.video_path = ""
        self.audio_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔄  " + t("tab.audio_replacer"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("replacer.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Input files
        pick = tk.LabelFrame(self, text=t("section.input_files"), padx=15, pady=8)
        pick.pack(fill="x", padx=20, pady=8)

        for row, label, attr, ft in [
            (0, t("common.source_video"), "video_path",
             [("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", "*.*")]),
            (1, t("replacer.new_audio_section"), "audio_path",
             [("Audio / Video", "*.mp3 *.aac *.wav *.flac *.ogg *.mp4 *.mov"), ("All", "*.*")]),
        ]:
            tk.Label(pick, text=label, font=(UI_FONT, 9, "bold")).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(pick, textvariable=var, width=60, relief="flat").grid(row=row, column=1, padx=8)

            def _b(a=attr, v=var, f=ft):
                p = filedialog.askopenfilename(filetypes=f)
                if p:
                    setattr(self, a, p)
                    v.set(p)

            tk.Button(pick, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").grid(row=row, column=2)

        # Options
        opts = tk.LabelFrame(self, text=t("replacer.replacement_options_section"), padx=15, pady=8)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("replacer.mode_label")).pack(side="left")
        self.mode_var = tk.StringVar(value=t("replacer.mode_replace"))
        ttk.Combobox(r0, textvariable=self.mode_var,
                     values=[t("replacer.replacer_replacer_mode_replace"), t("replacer.replacer_replacer_mode_mix_50"),
                              t("replacer.replacer_replacer_mode_mix_custom"), t("replacer.replacer_replacer_mode_strip")],
                     state="readonly", width=28).pack(side="left", padx=6)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("replacer.new_audio_volume_label")).pack(side="left")
        self.new_vol = tk.DoubleVar(value=1.0)
        tk.Scale(r1, variable=self.new_vol, from_=0.0, to=2.0, resolution=0.05,
                 orient="horizontal", length=180).pack(side="left", padx=6)
        tk.Label(r1, text=t("replacer.original_volume_label")).pack(side="left", padx=(14, 0))
        self.orig_vol = tk.DoubleVar(value=0.5)
        tk.Scale(r1, variable=self.orig_vol, from_=0.0, to=2.0, resolution=0.05,
                 orient="horizontal", length=180).pack(side="left", padx=6)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("replacer.audio_offset_label")).pack(side="left")
        self.offset_var = tk.StringVar(value="0")
        tk.Entry(r2, textvariable=self.offset_var, width=6, relief="flat").pack(side="left", padx=4)
        tk.Label(r2, text=t("replacer.offset_hint")).pack(side="left")
        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r2, text=t("replacer.loop_audio_checkbox"),
                       variable=self.loop_var).pack(side="left", padx=20)

        r3 = tk.Frame(opts); r3.pack(fill="x", pady=4)
        self.fade_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text=t("replacer.fade_checkbox"), variable=self.fade_var).pack(side="left")
        self.trim_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r3, text=t("replacer.trim_checkbox"), variable=self.trim_var).pack(side="left", padx=20)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("replacer.replace_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["orange"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.video_path:
            messagebox.showwarning(t("replacer.no_video_title"), t("replacer.no_video_message"))
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        mode = self.mode_var.get()
        offset = self.offset_var.get()

        if mode == t("replacer.mode_strip"):
            cmd = [ffmpeg, "-i", self.video_path, t("dynamics.c_v"), "copy", "-an", "-movflags", t("dynamics.faststart"), out, "-y"]
        elif mode == t("replacer.mode_replace") or not self.audio_path:
            if not self.audio_path:
                messagebox.showwarning(t("replacer.no_audio_title"), t("replacer.no_audio_message"))
                return
            filters = []
            nvol = self.new_vol.get()
            if nvol != 1.0:
                filters.append(f"volume={nvol}")
            if self.fade_var.get():
                filters.append("afade=t=in:st=0:d=0.5")
                vid_dur = get_video_duration(self.video_path)
                if vid_dur > 0.5:
                    filters.append(f"afade=t=out:st={vid_dur - 0.5:.3f}:d=0.5")
            af = ",".join(filters) if filters else None

            cmd = [ffmpeg, "-i", self.video_path]
            if float(offset) > 0:
                cmd += ["-itsoffset", offset]
            if self.loop_var.get():
                cmd += ["-stream_loop", "-1"]
            cmd += ["-i", self.audio_path]
            if self.trim_var.get():
                cmd += ["-shortest"]
            if af:
                cmd += ["-af", af]
            cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-map", "0:v:0", "-map", "1:a:0", "-movflags", "+faststart", out, "-y"]
        else:
            # Mix
            if not self.audio_path:
                messagebox.showwarning(t("replacer.no_audio_title"), t("replacer.no_audio_message"))
                return
            nvol = self.new_vol.get()
            ovol = self.orig_vol.get()
            mix_filter = (f"[0:a]volume={ovol}[orig];"
                          f"[1:a]volume={nvol}[new];"
                          f"[orig][new]amix=inputs=2:duration=first[aout]")
            cmd = [ffmpeg, "-i", self.video_path, "-i", self.audio_path,
                   "-filter_complex", mix_filter,
                   "-map", t("muter.0_v_0"), "-map", "[aout]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", out, "-y"]

        self.log(self.console, f"Mode: {mode}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("replacer.replace_button"))
