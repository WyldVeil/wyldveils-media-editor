"""
tab_audiomixer.py  ─  Multi-track Audio Mixer
Mix up to 8 audio tracks (narration, music, SFX, etc.) over a video,
each with independent volume, pan, fade-in/out, and time offset.

This is the DaVinci Resolve Fairlight use case for creators:
  • Layer a voice-over on top of a video
  • Add background music at reduced volume
  • Add sound effects at specific timestamps
  • Pan audio left/right for spatial effect
  • Each track has a visual fader

The result is the original video re-encoded with the new mixed audio.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


MAX_TRACKS = 8

TRACK_TYPES = [
    t("mixer.narration_voice"),
    t("mixer.background_music"),
    t("mixer.sound_effect"),
    t("mixer.instrumental"),
    t("mixer.ambient_room_tone"),
    t("mixer.original_video_audio"),
    t("mixer.interview"),
    t("mixer.other"),
]


class Track:
    def __init__(self, idx):
        self.idx       = idx
        self.path      = ""
        self.path_var  = tk.StringVar()
        self.type_var  = tk.StringVar(value=TRACK_TYPES[idx % len(TRACK_TYPES)])
        self.vol_var   = tk.DoubleVar(value=1.0)
        self.pan_var   = tk.DoubleVar(value=0.0)   # -1 = full left, +1 = full right
        self.offset_var= tk.StringVar(value="0")   # seconds into video
        self.fadein_var = tk.StringVar(value="0")
        self.fadeout_var= tk.StringVar(value="0")
        self.mute_var  = tk.BooleanVar(value=False)
        self.solo_var  = tk.BooleanVar(value=False)
        self.loop_var  = tk.BooleanVar(value=False)
        self.enabled   = tk.BooleanVar(value=True)


class AudioMixerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.video_path = ""
        self.tracks     = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎚  " + t("tab.audio_mixer"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner,
                 text=t("mixer.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Video source
        vid_f = tk.Frame(self); vid_f.pack(fill="x", padx=16, pady=6)
        tk.Label(vid_f, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.vid_var = tk.StringVar()
        tk.Entry(vid_f, textvariable=self.vid_var, width=56, relief="flat").pack(side="left", padx=8)
        tk.Button(vid_f, text=t("btn.browse"), command=self._browse_video, cursor="hand2", relief="flat").pack(side="left")
        self.vid_dur_lbl = tk.Label(vid_f, text="", fg=CLR["fgdim"])
        self.vid_dur_lbl.pack(side="left", padx=8)

        # Keep original video audio?
        va_row = tk.Frame(self); va_row.pack(anchor="w", padx=16, pady=2)
        self.keep_vid_audio_var = tk.BooleanVar(value=False)
        tk.Checkbutton(va_row,
                       text=t("mixer.include_original_checkbox"),
                       variable=self.keep_vid_audio_var).pack(side="left")
        self.vid_audio_vol_var = tk.DoubleVar(value=0.5)
        tk.Label(va_row, text=f"  {t('mixer.volume_label')}").pack(side="left", padx=(12, 0))
        tk.Scale(va_row, variable=self.vid_audio_vol_var, from_=0, to=2,
                 resolution=0.05, orient="horizontal", length=120).pack(side="left")

        # ── Track grid ────────────────────────────────────────────────────
        tk.Frame(self, bg="#333", height=1).pack(fill="x", padx=16, pady=4)

        # Column headers
        hdr_f = tk.Frame(self)
        hdr_f.pack(fill="x", padx=16)
        for txt, w in [(t("mixer.track_col"), 18), (t("mixer.source_file_col"), 24), (t("mixer.track_type_col"), 20),
                        ("Vol", 12), (t("mixer.pan_col"), 12), (t("mixer.start_col"), 8),
                        (t("mixer.fade_up_col"), 6), (t("mixer.fade_down_col"), 6), (t("mixer.loop_col"), 5),
                        ("Mute", 5), ("", 4)]:
            tk.Label(hdr_f, text=txt, width=w, font=(UI_FONT, 8, "bold"),
                     fg=CLR["fgdim"], anchor="w").pack(side="left", padx=1)

        # Scrollable track rows
        track_canvas = tk.Canvas(self, height=300, highlightthickness=0)
        track_sb = ttk.Scrollbar(self, orient="vertical",
                                  command=track_canvas.yview)
        self.track_frame = tk.Frame(track_canvas)
        track_canvas.create_window((0, 0), window=self.track_frame, anchor="nw")
        self.track_frame.bind("<Configure>",
                              lambda e: track_canvas.configure(
                                  scrollregion=track_canvas.bbox("all")))
        track_canvas.configure(yscrollcommand=track_sb.set)
        track_canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        track_sb.pack(side="right", fill="y")

        # Add track button - must exist before _add_track() is called
        add_row = tk.Frame(self); add_row.pack(anchor="w", padx=16, pady=4)
        tk.Button(add_row, text=t("mixer.add_track_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._add_track).pack(side="left", padx=4)
        tk.Button(add_row, text=t("mixer.remove_last_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._remove_last_track).pack(side="left", padx=4)
        self.track_count_lbl = tk.Label(add_row, text=t("mixer.0_tracks"),
                                         fg=CLR["fgdim"], font=(UI_FONT, 9))
        self.track_count_lbl.pack(side="left", padx=12)

        # Add initial 3 tracks (track_count_lbl now exists)
        for _ in range(3):
            self._add_track()

        # ── Master output ─────────────────────────────────────────────────
        tk.Frame(self, bg="#333", height=1).pack(fill="x", padx=16, pady=4)
        master_f = tk.Frame(self); master_f.pack(fill="x", padx=16, pady=4)
        tk.Label(master_f, text=f"🎚  {t('mixer.master_volume_label')}",
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        self.master_vol_var = tk.DoubleVar(value=1.0)
        tk.Scale(master_f, variable=self.master_vol_var, from_=0, to=2.0,
                 resolution=0.05, orient="horizontal", length=200).pack(side="left", padx=8)
        self.master_lbl = tk.Label(master_f, text="100%", width=5, fg=CLR["accent"])
        self.master_lbl.pack(side="left")
        self.master_vol_var.trace_add("write", lambda *_: self.master_lbl.config(
            text=f"{int(self.master_vol_var.get()*100)}%"))

        norm_row = tk.Frame(self); norm_row.pack(anchor="w", padx=16, pady=2)
        self.normalize_var = tk.BooleanVar(value=True)
        tk.Checkbutton(norm_row,
                       text=t("mixer.normalize_checkbox"),
                       variable=self.normalize_var).pack(side="left")
        tk.Label(norm_row, text=f"  {t('mixer.output_format_label')}").pack(side="left", padx=(16, 0))
        self.out_fmt_var = tk.StringVar(value="AAC 256k  (keep video)")
        ttk.Combobox(norm_row, textvariable=self.out_fmt_var,
                     values=["AAC 256k  (keep video)", "AAC 320k  (keep video)",
                              "MP3 320k  (audio only)", "WAV  (audio only)",
                              "FLAC  (audio only)"],
                     state="readonly", width=24).pack(side="left", padx=4)

        # Output file
        of = tk.Frame(self); of.pack(fill="x", padx=16, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("mixer.mix_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#1565C0", fg="white",
            height=2, command=self._render)
        self.btn_render.pack(pady=8, padx=16, fill="x")

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    def _add_track(self):
        if len(self.tracks) >= MAX_TRACKS:
            messagebox.showinfo("Max tracks",
                                f"Maximum {MAX_TRACKS} tracks supported.")
            return
        t = Track(len(self.tracks))
        self.tracks.append(t)
        self._draw_track_row(t)
        self.track_count_lbl.config(text=f"{len(self.tracks)} tracks")

    def _draw_track_row(self, t: Track):
        row = tk.Frame(self.track_frame, relief="groove", bd=1)
        row.pack(fill="x", pady=2)
        t.row = row

        # Track number + enable
        head = tk.Frame(row, width=140); head.pack(side="left")
        tk.Label(head, text=f"T{t.idx+1}", width=3,
                 font=(UI_FONT, 9, "bold"), fg=CLR["accent"]).pack(side="left")
        tk.Checkbutton(head, variable=t.enabled).pack(side="left")

        # File browse
        file_entry = tk.Entry(row, textvariable=t.path_var, width=22,
                              font=(MONO_FONT, 8))
        file_entry.pack(side="left", padx=2)

        def _browse(tr=t):
            p = filedialog.askopenfilename(
                filetypes=[(t("mixer.audio_video"),
                            "*.mp3 *.wav *.aac *.flac *.ogg *.mp4 *.mov"),
                           ("All",t("ducker.item_2"))])
            if p:
                tr.path = p
                tr.path_var.set(os.path.basename(p))
                tr._full_path = p
        tk.Button(row, text="…", width=2, command=_browse, cursor="hand2", relief="flat").pack(side="left", padx=1)

        # Type
        ttk.Combobox(row, textvariable=t.type_var,
                     values=TRACK_TYPES, state="readonly",
                     width=16).pack(side="left", padx=2)

        # Volume fader (the centrepiece)
        vol_f = tk.Frame(row); vol_f.pack(side="left", padx=2)
        tk.Scale(vol_f, variable=t.vol_var, from_=0, to=2,
                 resolution=0.05, orient="horizontal", length=90).pack()
        vol_lbl = tk.Label(vol_f, text="100%", width=4, fg=CLR["accent"],
                           font=(UI_FONT, 7))
        vol_lbl.pack()
        t.vol_var.trace_add("write", lambda *_, l=vol_lbl, v=t.vol_var:
                            l.config(text=f"{int(v.get()*100)}%"))

        # Pan
        pan_f = tk.Frame(row); pan_f.pack(side="left", padx=2)
        tk.Scale(pan_f, variable=t.pan_var, from_=-1, to=1,
                 resolution=0.05, orient="horizontal", length=80).pack()
        pan_lbl = tk.Label(pan_f, text="C", width=3, fg=CLR["fgdim"],
                           font=(UI_FONT, 7))
        pan_lbl.pack()
        t.pan_var.trace_add("write", lambda *_, l=pan_lbl, v=t.pan_var: l.config(
            text="L" if v.get() < -0.1 else ("R" if v.get() > 0.1 else "C")))

        # Offset, fade in, fade out
        for var, w in [(t.offset_var, 6), (t.fadein_var, 4), (t.fadeout_var, 4)]:
            tk.Entry(row, textvariable=var, width=w,
                     font=(MONO_FONT, 8)).pack(side="left", padx=2)

        # Loop, Mute
        tk.Checkbutton(row, variable=t.loop_var, text="↻",
                       font=(UI_FONT, 8)).pack(side="left")
        tk.Checkbutton(row, variable=t.mute_var, text="M",
                       font=(UI_FONT, 8, "bold"),
                       fg=CLR["red"]).pack(side="left")

    def _remove_last_track(self):
        if self.tracks:
            t = self.tracks.pop()
            t.row.destroy()
            self.track_count_lbl.config(text=f"{len(self.tracks)} tracks")

    def _browse_video(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All",t("ducker.item_2"))])
        if p:
            self.video_path = p
            self.vid_var.set(p)
            from core.hardware import get_video_duration
            dur = get_video_duration(p)
            m, s = divmod(int(dur), 60)
            self.vid_dur_lbl.config(text=f"{m}m {s}s", fg=CLR["fgdim"])
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_mixed.mp4")

    def _browse_out(self):
        fmt = self.out_fmt_var.get()
        if "audio only" in fmt.lower():
            ext = ".mp3" if "MP3" in fmt else (".wav" if "WAV" in fmt else
                  (".flac" if "FLAC" in fmt else ".aac"))
        else:
            ext = ".mp4"
        p = filedialog.asksaveasfilename(defaultextension=ext,
                                          filetypes=[("Media", f"*{ext}")])
        if p: self.out_var.set(p)

    # ── Render ────────────────────────────────────────────────────────────
    def _render(self):
        if not self.video_path:
            messagebox.showwarning(t("mixer.no_video_title"), t("mixer.no_video_message"))
            return

        active = [t for t in self.tracks
                  if t.enabled.get() and not t.mute_var.get()
                  and (t.path or getattr(t, "_full_path", ""))]
        if not active and not self.keep_vid_audio_var.get():
            messagebox.showwarning(t("mixer.no_tracks_title"), t("mixer.no_tracks_message"))
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4","*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg   = get_binary_path("ffmpeg.exe")
        fmt      = self.out_fmt_var.get()
        audio_only = "audio only" in fmt.lower()

        # Build inputs
        cmd = [ffmpeg, "-i", self.video_path]
        n_audio_inputs = 0

        # Original video audio
        orig_audio_idx = None
        if self.keep_vid_audio_var.get():
            # video is input 0; its audio stream is [0:a]
            orig_audio_idx = 0

        # Add track audio inputs
        track_input_map = {}  # track → ffmpeg input index
        for t in active:
            path = getattr(t, "_full_path", t.path)
            if not path or not os.path.exists(path):
                continue
            inp_idx = 1 + n_audio_inputs
            if t.loop_var.get():
                cmd += ["-stream_loop", "-1"]
            offset = t.offset_var.get().strip()
            if offset and float(offset) > 0:
                cmd += ["-itsoffset", offset]
            cmd += ["-i", path]
            track_input_map[t] = inp_idx
            n_audio_inputs += 1

        if not track_input_map and orig_audio_idx is None:
            messagebox.showwarning(t("mixer.no_tracks_title"),
                                   t("mixer.no_tracks_message"))
            return

        # Build filter_complex
        filter_parts = []
        mix_inputs   = []

        if orig_audio_idx is not None:
            vol = self.vid_audio_vol_var.get()
            filter_parts.append(f"[0:a]volume={vol:.3f}[orig_a]")
            mix_inputs.append("[orig_a]")

        for t, inp_idx in track_input_map.items():
            tag  = f"ta{inp_idx}"
            vol  = t.vol_var.get()
            pan  = t.pan_var.get()
            fi   = t.fadein_var.get().strip() or "0"
            fo   = t.fadeout_var.get().strip() or "0"
            parts_chain = [f"[{inp_idx}:a]volume={vol:.3f}"]

            if abs(pan) > 0.05:
                # Stereo pan: pan=-1→full left (l=1,r=0), pan=+1→full right (l=0,r=1)
                l_gain = min(1.0, 1.0 - pan)
                r_gain = min(1.0, 1.0 + pan)
                parts_chain.append(
                    f"pan=stereo|FL={l_gain:.3f}*FL|FR={r_gain:.3f}*FR")

            if float(fi) > 0:
                parts_chain.append(f"afade=t=in:st=0:d={fi}")
            if float(fo) > 0:
                from core.hardware import get_video_duration
                track_dur = get_video_duration(getattr(t, "_full_path", t.path))
                if track_dur > 0:
                    fade_st = max(0.0, track_dur - float(fo))
                    parts_chain.append(f"afade=t=out:st={fade_st:.3f}:d={fo}")
                else:
                    parts_chain.append(f"afade=t=out:st=0:d={fo}")

            chain = ",".join(parts_chain)
            filter_parts.append(f"{chain}[{tag}]")
            mix_inputs.append(f"[{tag}]")

        n_mix = len(mix_inputs)
        if n_mix == 1:
            # No amix needed
            filter_parts.append(f"{mix_inputs[0]}volume={self.master_vol_var.get():.3f}[aout]")
        else:
            mix_str = "".join(mix_inputs)
            filter_parts.append(
                f"{mix_str}amix=inputs={n_mix}:duration=first[mixed];"
                f"[mixed]volume={self.master_vol_var.get():.3f}[aout]")

        if self.normalize_var.get():
            filter_parts.append(
                "[aout]loudnorm=I=-16:TP=-1.5:LRA=11[final_a]")
            final_tag = "[final_a]"
        else:
            final_tag = "[aout]"

        fc = ";".join(filter_parts)

        # Codec args
        if "MP3" in fmt:
            acodec = [t("dynamics.c_a"),"libmp3lame",t("dynamics.b_a"),"320k"]
        elif "WAV" in fmt:
            acodec = [t("dynamics.c_a"),"pcm_s16le"]
        elif "FLAC" in fmt:
            acodec = [t("dynamics.c_a"),"flac"]
        else:
            bitrate = "320k" if "320" in fmt else "256k"
            acodec  = [t("dynamics.c_a"),"aac",t("dynamics.b_a"),bitrate]

        cmd += ["-filter_complex", fc]

        if audio_only:
            cmd += ["-map", final_tag, "-vn"] + acodec
        else:
            cmd += ["-map", "0:v", "-map", final_tag,
                    "-c:v", "copy"] + acodec + ["-shortest"]

        cmd += ["-movflags", "+faststart", out, "-y"]

        self.log(self.console,
                 f"Mixing {n_mix} source(s) → {os.path.basename(out)}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label=t("mixer.mix_button"))
