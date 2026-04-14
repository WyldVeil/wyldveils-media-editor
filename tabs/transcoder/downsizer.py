"""
tab_universal_downsizer.py  ─  Universal Downsizer
Target a specific file size (MB) and let the app calculate the bitrates,
codecs, and scaling required to hit that target optimally.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shlex
import subprocess
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW, get_audio_bitrate_kbps
from core.i18n import t

class UniversalDownsizerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._duration = 0.0
        self._hw_encoders = {"h264": "libx264", "hevc": "libx265"} # Safe defaults
        
        # Probe hardware encoders in the background so UI doesn't freeze
        threading.Thread(target=self._probe_hardware_encoders, daemon=True).start()
        
        self._build_ui()

    def _probe_hardware_encoders(self):
        """Silently queries FFmpeg for available hardware encoders."""
        try:
            ff = get_binary_path("ffmpeg")
            result = subprocess.check_output(
                [ff, "-encoders"], 
                creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8"
            )
            
            # Check HEVC (H.265) Hardware
            if "hevc_nvenc" in result: self._hw_encoders["hevc"] = "hevc_nvenc"
            elif "hevc_amf" in result: self._hw_encoders["hevc"] = "hevc_amf"
            elif "hevc_qsv" in result: self._hw_encoders["hevc"] = "hevc_qsv"
            elif "hevc_videotoolbox" in result: self._hw_encoders["hevc"] = "hevc_videotoolbox"

            # Check AVC (H.264) Hardware
            if "h264_nvenc" in result: self._hw_encoders["h264"] = "h264_nvenc"
            elif "h264_amf" in result: self._hw_encoders["h264"] = "h264_amf"
            elif "h264_qsv" in result: self._hw_encoders["h264"] = "h264_qsv"
            elif "h264_videotoolbox" in result: self._hw_encoders["h264"] = "h264_videotoolbox"
            
        except Exception:
            pass # Stick to CPU defaults if probe fails

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🗜️  " + t("tab.universal_downsizer"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("downsizer.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Main Content Container ────────────────────────────────────────
        content = tk.Frame(self, bg=CLR["bg"], padx=20, pady=20)
        content.pack(fill="both", expand=True)

        # 1. File I/O
        self._src_var = tk.StringVar()
        self._out_var = tk.StringVar()
        self._src_var.trace_add("write", self._on_src_changed)

        r1 = tk.Frame(content, bg=CLR["bg"])
        r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("common.source_video"), font=(UI_FONT, 10, "bold"), bg=CLR["bg"], fg=CLR["fg"], width=18, anchor="e").pack(side="left")
        tk.Entry(r1, textvariable=self._src_var, width=65, bg=CLR["panel"], fg=CLR["fg"], insertbackground=CLR["fg"], relief="flat", bd=4).pack(side="left", padx=8)
        tk.Button(r1, text=t("btn.browse"), bg=CLR["panel"], fg=CLR["fg"], command=self._browse_src, cursor="hand2", relief="flat").pack(side="left")

        r2 = tk.Frame(content, bg=CLR["bg"])
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.output_file"), font=(UI_FONT, 10, "bold"), bg=CLR["bg"], fg=CLR["fg"], width=18, anchor="e").pack(side="left")
        tk.Entry(r2, textvariable=self._out_var, width=65, bg=CLR["panel"], fg=CLR["fg"], insertbackground=CLR["fg"], relief="flat", bd=4).pack(side="left", padx=8)
        tk.Button(r2, text=t("common.save_as"), bg=CLR["panel"], fg=CLR["fg"], command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Duration & Analysis Label
        self._analysis_lbl = tk.Label(content, text=t("downsizer.ready_select_a_video_to_analyze"), font=(MONO_FONT, 10), bg=CLR["bg"], fg=CLR["accent"], pady=10)
        self._analysis_lbl.pack(fill="x")

        tk.Frame(content, bg=CLR["panel"], height=2).pack(fill="x", pady=10)

        # 2. Target Size
        r3 = tk.Frame(content, bg=CLR["bg"])
        r3.pack(fill="x", pady=10)
        tk.Label(r3, text=t("downsizer.target_size_label"), font=(UI_FONT, 12, "bold"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(10, 5))
        
        self._target_mb = tk.StringVar(value="25.0")
        mb_entry = tk.Entry(r3, textvariable=self._target_mb, width=8, font=(UI_FONT, 12, "bold"), bg=CLR["panel"], fg="#00FF88", insertbackground=CLR["fg"], relief="flat", bd=4, justify="center")
        mb_entry.pack(side="left", padx=5)
        tk.Label(r3, text=t("downsizer.mb_label"), font=(UI_FONT, 11), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        # 3. Permissions (Checkboxes)
        perms_frame = tk.LabelFrame(content, text=t("downsizer.permissions_section"), bg=CLR["bg"], fg=CLR["accent"], font=(UI_FONT, 10, "bold"), padx=15, pady=10)
        perms_frame.pack(fill="x", pady=15, padx=10)
        tk.Label(perms_frame, text=t("downsizer.permissions_intro"), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w", pady=(0, 10))

        self._allow_res = tk.BooleanVar(value=True)
        self._allow_fps = tk.BooleanVar(value=True)
        self._allow_codec = tk.BooleanVar(value=True)
        self._allow_audio = tk.BooleanVar(value=True)

        tk.Checkbutton(perms_frame, text=t("downsizer.permission_resolution"), variable=self._allow_res, bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], activebackground=CLR["bg"]).pack(anchor="w", pady=2)
        tk.Checkbutton(perms_frame, text=t("downsizer.permission_framerate"), variable=self._allow_fps, bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], activebackground=CLR["bg"]).pack(anchor="w", pady=2)
        tk.Checkbutton(perms_frame, text=t("downsizer.permission_codec"), variable=self._allow_codec, bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], activebackground=CLR["bg"]).pack(anchor="w", pady=2)
        tk.Checkbutton(perms_frame, text=t("downsizer.permission_audio"), variable=self._allow_audio, bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], activebackground=CLR["bg"]).pack(anchor="w", pady=2)

        # 4. Controls
        btn_frame = tk.Frame(content, bg=CLR["bg"])
        btn_frame.pack(fill="x", pady=20)

        self._btn_render = tk.Button(btn_frame, text=t("downsizer.render_button"), font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="black", height=2, width=30, cursor="hand2", command=self._start_render, relief="flat", bd=0)
        self._btn_render.pack(side="left", padx=10)

        self._btn_stop = tk.Button(btn_frame, text=t("downsizer.stop_button"), font=(UI_FONT, 12, "bold"), bg="#D32F2F", fg="white", height=2, width=10, cursor="hand2", state="disabled", command=self._stop_render, relief="flat", bd=0)
        self._btn_stop.pack(side="left")

        # Console
        self.console, csb = self.make_console(content, height=8)
        self.console.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        csb.pack(side="right", fill="y")

    def _browse_src(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("All", t("ducker.item_2"))])
        if p:
            self._src_var.set(p)
            ext = os.path.splitext(p)[1]
            if not self._out_var.get():
                self._out_var.set(os.path.splitext(p)[0] + f"_downsized{ext}")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("Video", "*.mp4 *.mkv *.mov"), ("All", t("ducker.item_2"))])
        if p: self._out_var.set(p)

    def _on_src_changed(self, *_):
        path = self._src_var.get()
        if os.path.exists(path):
            threading.Thread(target=self._analyze_file, args=(path,), daemon=True).start()

    def _analyze_file(self, path):
        dur = get_video_duration(path)
        self._duration = dur
        if dur:
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            self.after(0, lambda: self._analysis_lbl.config(
                text=f"Loaded: {os.path.basename(path)}  |  Duration: {dur:.2f}s  |  Current Size: {file_size_mb:.1f} MB"
            ))

    def _start_render(self):
        src = self._src_var.get().strip()
        out = self._out_var.get().strip()
        
        if not src or not os.path.exists(src):
            messagebox.showwarning(t("common.warning"), "Valid source file required.")
            return

        try:
            target_mb = float(self._target_mb.get().strip())
        except ValueError:
            messagebox.showwarning(t("common.warning"), "Target size must be a valid number.")
            return

        if self._duration <= 0:
            self._duration = get_video_duration(src)
            if self._duration <= 0:
                messagebox.showerror(t("common.error"), "Could not read video duration. Cannot calculate bitrate.")
                return

        # --- NEW: PROBE SOURCE FILE FOR AUDIO, 10-BIT, AND HDR ---
        ff = get_binary_path("ffmpeg")
        has_audio = False
        is_10bit = False
        is_hdr = False
        
        try:
            # ffmpeg -i returns exit code 1 when no output is specified
            subprocess.check_output(
                [ff, "-hide_banner", "-i", src],
                creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8"
            )
        except subprocess.CalledProcessError as e:
            probe_out = e.output
            has_audio = " Audio:" in probe_out
            is_10bit = "10le" in probe_out or "Main 10" in probe_out or "10-bit" in probe_out
            is_hdr = "bt2020" in probe_out or "smpte2084" in probe_out

        # --- THE MATH ---
        # 1 MB = 8192 kilobits. We target 95% of the requested size to ensure we don't accidentally overshoot.
        target_kbits = target_mb * 8192 * 0.95
        total_bitrate_kbps = target_kbits / self._duration

        # Determine Audio Bitrate
        audio_bitrate = 128
        if not has_audio:
            audio_bitrate = 0
            self.log(self.console, t("log.downsizer.no_audio_stream_detected_dedicating_100_of_bitrat"))
        elif self._allow_audio.get():
            if total_bitrate_kbps < 1000: audio_bitrate = 96
            if total_bitrate_kbps < 500: audio_bitrate = 64
        else:
            # Query the actual source audio bitrate since we are copying it
            actual_audio_kbps = get_audio_bitrate_kbps(src)
            if actual_audio_kbps > 0:
                audio_bitrate = int(actual_audio_kbps)
            else:
                # Fallback: MKV files sometimes hide bitrates. Assume a massive 1500 kbps 
                # to prevent file size blowouts if it's an uncompressed DTS/TrueHD track.
                self.log(self.console, t("log.downsizer.could_not_read_exact_source_audio_bitrate_reservi"))
                audio_bitrate = 1500
            
        video_bitrate = int(total_bitrate_kbps - audio_bitrate)

        if video_bitrate < 50:
            messagebox.showerror(t("downsizer.impossible_title"), f"Target is too small. Calculated video bitrate is {video_bitrate} kbps, which will look like abstract art or fail completely.")
            return

        # Determine Codec (Hardware accelerated where possible)
        vcodec = self._hw_encoders["h264"]
        if is_10bit:
            # NEW: Force HEVC for 10-bit sources as H.264 doesn't support it well on hardware
            vcodec = self._hw_encoders.get("hevc", "libx265")
            self.log(self.console, t("log.downsizer.10_bit_source_detected_upgrading_to_hevc_to_prese"))
        elif self._allow_codec.get() and video_bitrate < 2000:
            vcodec = self._hw_encoders["hevc"] # Upgrade to HEVC for better low-bitrate quality
            
        # Determine Filters (Degradation)
        vf = []
        # Increased threshold from 2500 to 3000 to catch more high-bitrate edge cases
        if self._allow_res.get() and video_bitrate < 3000: 
            # Scale down to 720p maximum, keeping aspect ratio. If already smaller, it does nothing.
            vf.append("scale='min(1280,iw)':'-2'")
        if self._allow_fps.get() and video_bitrate < 1500:
            # Drop to 30fps maximum to save bandwidth for individual frames
            vf.append("fps=30")

        # Build Command
        cmd = [ff, "-y", "-i", src]
        
        if vf:
            cmd.extend(["-vf", ",".join(vf)])

        cmd.extend([
            "-c:v", vcodec,
            "-b:v", f"{video_bitrate}k",
            "-maxrate", f"{int(video_bitrate * 1.2)}k", # Buffer constraint for accurate sizing
            "-bufsize", f"{int(video_bitrate * 2)}k",
        ])

        # --- NEW: Inject 10-bit and HDR flags if required ---
        if is_10bit:
            # NVIDIA requires 'p010le' for 10-bit hardware encoding. CPU requires 'yuv420p10le'.
            pix_fmt = "p010le" if "nvenc" in vcodec else "yuv420p10le"
            cmd.extend(["-pix_fmt", pix_fmt, "-profile:v", "main10"])
            
        if is_hdr:
            cmd.extend([
                "-color_primaries", "bt2020",
                "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc"
            ])

        # Hardware-specific preset overrides for efficiency
        if "nvenc" in vcodec: cmd.extend(["-preset", "p6"]) # High quality NVENC preset
        elif "libx" in vcodec: cmd.extend(["-preset", "medium"])

        # MODIFIED: Only process audio if the file actually has it
        if has_audio:
            if self._allow_audio.get():
                cmd.extend(["-c:a", "aac", "-b:a", f"{audio_bitrate}k"])
            else:
                cmd.extend(["-c:a", "copy"])

        cmd.extend(["-movflags", "+faststart", out, "-y"])

        self.log(self.console, f"▶ Targeting {target_mb}MB limit...")
        self.log(self.console, f"  Calculated Video Bitrate: {video_bitrate} kbps | Audio: {audio_bitrate} kbps")
        self.log(self.console, f"  Using Encoder: {vcodec} (Auto-detected hardware)")
        
        self._btn_stop.config(state="normal")
        self.run_ffmpeg(cmd, self.console, on_done=self._on_done, btn=self._btn_render, btn_label=t("downsizer.render_button"))

    def _on_done(self, rc):
        self._btn_stop.config(state="disabled")
        out = self._out_var.get().strip()
        self.show_result(rc, out)
        
        if rc == 0 and os.path.exists(out):
            final_mb = os.path.getsize(out) / (1024 * 1024)
            self.log(self.console, f"\n✅ Finished! Final File Size: {final_mb:.2f} MB")

    def _stop_render(self):
        proc = getattr(self, "proc", getattr(self, "_proc", getattr(self, "current_process", None)))
        if proc and hasattr(proc, "terminate"):
            try: proc.terminate()
            except Exception: pass
        else:
            if os.name == 'nt': os.system("taskkill /F /IM ffmpeg.exe /T >nul 2>&1")

        self.log(self.console, t("log.all_in_one.render_forcibly_stopped_by_user"))
        self._btn_stop.config(state="disabled")
        self._btn_render.config(state="normal", text=t("downsizer.render_button"))