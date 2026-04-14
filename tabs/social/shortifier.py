"""
tab_shortifier.py  ─  The Shortifier
Reframes and formats videos for every major social platform.
Handles aspect ratio cropping, letterboxing/pillarboxing, blur background fills,
and optional duration trimming.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
import json
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, detect_gpu, CREATE_NO_WINDOW
from core.i18n import t


PLATFORMS = {
    t("shortifier.youtube_shorts_9_16_1080_1920"): (1080, 1920, "9:16"),
    t("shortifier.youtube_shorts_4k_9_16_2160_3840"): (2160, 3840, "9:16"),
    t("shortifier.tiktok_9_16_1080_1920"): (1080, 1920, "9:16"),
    t("shortifier.instagram_reel_9_16_1080_1920"): (1080, 1920, "9:16"),
    t("shortifier.instagram_post_1_1_1080_1080"):  (1080, 1080, "1:1"),
    t("shortifier.instagram_story_9_16_1080_1920"): (1080, 1920, "9:16"),
    t("shortifier.twitter_x_16_9_1920_1080"): (1920, 1080, "16:9"),
    t("shortifier.facebook_16_9_1920_1080"): (1920, 1080, "16:9"),
    t("shortifier.linkedin_1_1_1080_1080"):  (1080, 1080, "1:1"),
    t("shortifier.youtube_16_9_1920_1080"): (1920, 1080, "16:9"),
    t("shortifier.youtube_4k_16_9_3840_2160"): (3840, 2160, "16:9"),
    t("shortifier.snapchat_9_16_1080_1920"): (1080, 1920, "9:16"),
    t("smart_reframe.custom"):                                (0,    0,    "custom"),
}

CROP_POSITIONS = [
    t("shortifier.center_smart"),
    "Top",
    "Bottom",
    "Left",
    "Right",
]

BG_MODES = [
    t("shortifier.blurred_video_cinematic"),
    t("smart_reframe.fill_black_bars"),
    t("shortifier.white_bars"),
    t("shortifier.color_fill"),
    t("shortifier.mirror_fill"),
]


class ShortifierTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📱  " + t("tab.the_shortifier"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("shortifier.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source file
        src_f = tk.Frame(self); src_f.pack(pady=10)
        tk.Label(src_f, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(src_f, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(src_f, text=t("btn.browse"), command=self._browse_src, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(src_f, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=10)

        # Main options row
        opts = tk.LabelFrame(self, text=f"  {t('shortifier.format_options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        # Platform picker
        tk.Label(opts, text=t("shortifier.platform_label"), font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        self.platform_var = tk.StringVar(value=list(PLATFORMS.keys())[0])
        plat_cb = ttk.Combobox(opts, textvariable=self.platform_var,
                               values=list(PLATFORMS.keys()), state="readonly", width=38)
        plat_cb.grid(row=0, column=1, padx=8, sticky="w")
        plat_cb.bind("<<ComboboxSelected>>", self._on_platform_change)

        # Custom dims (shown only for Custom)
        self.custom_f = tk.Frame(opts)
        tk.Label(self.custom_f, text="W:").pack(side="left")
        self.cust_w = tk.StringVar(value="1080")
        tk.Entry(self.custom_f, textvariable=self.cust_w, width=6, relief="flat").pack(side="left", padx=3)
        tk.Label(self.custom_f, text="H:").pack(side="left")
        self.cust_h = tk.StringVar(value="1920")
        tk.Entry(self.custom_f, textvariable=self.cust_h, width=6, relief="flat").pack(side="left", padx=3)
        self.custom_f.grid(row=0, column=2, padx=8)
        self.custom_f.grid_remove()

        # Crop position
        tk.Label(opts, text=t("shortifier.crop_position_label"), font=(UI_FONT, 10, "bold")).grid(row=1, column=0, sticky="w", pady=6)
        self.crop_var = tk.StringVar(value=CROP_POSITIONS[0])
        ttk.Combobox(opts, textvariable=self.crop_var, values=CROP_POSITIONS,
                     state="readonly", width=22).grid(row=1, column=1, sticky="w")

        # Background fill mode
        tk.Label(opts, text=t("shortifier.background_fill_label"), font=(UI_FONT, 10, "bold")).grid(row=2, column=0, sticky="w")
        self.bg_var = tk.StringVar(value=BG_MODES[0])
        bg_cb = ttk.Combobox(opts, textvariable=self.bg_var, values=BG_MODES,
                              state="readonly", width=28)
        bg_cb.grid(row=2, column=1, sticky="w")
        bg_cb.bind("<<ComboboxSelected>>", self._on_bg_change)
        self.color_btn = tk.Button(opts, text=t("shortifier.pick_color_button"), command=self._pick_bg_color, cursor="hand2", relief="flat")
        self.color_btn.grid(row=2, column=2, padx=8)
        self.color_btn.grid_remove()
        self.bg_color = "#000000"

        # Quality / duration
        q_f = tk.Frame(opts); q_f.grid(row=3, column=0, columnspan=4, sticky="w", pady=6)
        tk.Label(q_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(q_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(q_f, text=t("shortifier.max_duration_label")).pack(side="left", padx=(20, 4))
        self.maxdur_var = tk.StringVar(value="0")
        tk.Entry(q_f, textvariable=self.maxdur_var, width=6, relief="flat").pack(side="left")
        self.mute_var = tk.BooleanVar(value=False)
        tk.Checkbutton(q_f, text=t("shortifier.mute_checkbox"), variable=self.mute_var).pack(side="left", padx=20)

        # Output
        out_f = tk.Frame(self); out_f.pack(pady=5)
        tk.Label(out_f, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(out_f, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(out_f, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Render button
        self.btn_render = tk.Button(
            self, text=t("shortifier.format_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["pink"], fg="white", height=2, width=30, command=self._render)
        self.btn_render.pack(pady=10)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, sb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _browse_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            dur = get_video_duration(p)
            m, s = divmod(int(dur), 60)
            self.dur_lbl.config(text=f"  {m}m {s}s")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _on_platform_change(self, *_):
        plat = self.platform_var.get()
        if "Custom" in plat:
            self.custom_f.grid()
        else:
            self.custom_f.grid_remove()

    def _on_bg_change(self, *_):
        if self.bg_var.get() == t("shortifier.color_fill"):
            self.color_btn.grid()
        else:
            self.color_btn.grid_remove()

    def _pick_bg_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor()[1]
        if c:
            self.bg_color = c

    def _is_10bit(self, file_path):
        """Uses ffprobe to detect if the source video has a 10-bit or higher pixel format."""
        ffprobe = get_binary_path("ffprobe.exe")
        cmd = [
            ffprobe, "-v", "error", "-select_streams", t("freeze_frame.v_0"),
            "-show_entries", t("smart_reframe.stream_pix_fmt"), "-of", "json", file_path
        ]
        try:
            result = subprocess.check_output(cmd, creationflags=CREATE_NO_WINDOW)
            data = json.loads(result)
            pix_fmt = data.get('streams', [{}])[0].get('pix_fmt', '')
            return "10" in pix_fmt or "12" in pix_fmt
        except Exception:
            return False

    def _get_hw_encode_args(self, is_10bit, crf_val):
        """Uses core.hardware.detect_gpu() to set up the appropriate encoder."""
        vendor = detect_gpu()

        args = []
        if vendor == "nvidia":
            if is_10bit:
                # NVENC H.264 doesn't handle 10-bit gracefully; switch to HEVC
                args += ["-c:v", "hevc_nvenc", "-pix_fmt", "p010le", "-profile:v", "main10", "-preset", "p4", "-cq", crf_val, "-b:v", "0"]
            else:
                args += ["-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-preset", "p4", "-cq", crf_val, "-b:v", "0"]
        elif vendor == "amd":
            if is_10bit:
                args += ["-c:v", "hevc_amf", "-pix_fmt", "yuv420p10le", "-profile:v", "main10", "-rc", "cqp", "-qp_i", crf_val, "-qp_p", crf_val, "-quality", "speed"]
            else:
                args += ["-c:v", "h264_amf", "-pix_fmt", "yuv420p", "-rc", "cqp", "-qp_i", crf_val, "-qp_p", crf_val, "-quality", "speed"]
        elif vendor == "apple":
            if is_10bit:
                args += ["-c:v", "hevc_videotoolbox", "-profile:v", "main10", "-q:v", "65"]
            else:
                args += ["-c:v", "h264_videotoolbox", "-q:v", "65"]
        else:
            # CPU Fallback
            args += ["-c:v", "libx264"]
            if is_10bit:
                args += ["-pix_fmt", "yuv420p10le", "-profile:v", "high10"]
            else:
                args += ["-pix_fmt", "yuv420p"]
            args += ["-crf", crf_val, "-preset", "fast"]

        # Log to the GUI console
        self.log(self.console, f"⚙️ Auto-Selected Encoder: {args[1]} (10-bit mode: {is_10bit})")
        return args

    def _build_filter(self, tw, th):
        """Build the ffmpeg -vf filter string."""
        crop_pos = self.crop_var.get()
        bg_mode  = self.bg_var.get()

        # Crop gravity
        gravity_map = {
            "Center (Smart)": "center",
            "Top":    "north",
            "Bottom": "south",
            "Left":   "west",
            "Right":  "east",
        }
        grav = gravity_map.get(crop_pos, "center")

        # Scale + crop for the foreground
        fg = (f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
              f"crop={tw}:{th}:exact=1")

        if bg_mode == "Blurred Video (cinematic)":
            # OPTIMIZED BLUR: Scale to 1/4 size, blur lightly, scale back up.
            # This saves the CPU from doing heavy boxblur math on 4K resolutions.
            sw, sh = tw // 4, th // 4
            bg = (f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
                  f"crop={sw}:{sh}:exact=1,"
                  f"boxblur=luma_radius=10:luma_power=1,"
                  f"scale={tw}:{th}")
            
            filt = (f"[0:v]split=2[bg][fg_raw];"
                    f"[bg]{bg}[bgblur];"
                    f"[fg_raw]{fg}[fgcrop];"
                    f"[bgblur][fgcrop]overlay=(W-w)/2:(H-h)/2")
        elif bg_mode == "Mirror fill":
            bg = (f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
                  f"crop={tw}:{th}:exact=1,"
                  f"hflip")
            filt = (f"[0:v]split=2[bg][fg_raw];"
                    f"[bg]{bg}[bgmirr];"
                    f"[fg_raw]{fg}[fgcrop];"
                    f"[bgmirr][fgcrop]overlay=(W-w)/2:(H-h)/2")
        else:
            # Pad with color
            if bg_mode == "Black bars":
                color = "black"
            elif bg_mode == "White bars":
                color = "white"
            else:
                color = self.bg_color.lstrip("#")
                color = f"0x{color}"
            filt = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                    f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={color}")

        return filt

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        plat = self.platform_var.get()
        info = PLATFORMS[plat]
        if "Custom" in plat:
            try:
                tw, th = int(self.cust_w.get()), int(self.cust_h.get())
            except ValueError:
                messagebox.showerror(t("common.error"), "Enter valid width/height.")
                return
        else:
            tw, th = info[0], info[1]

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)

        filt = self._build_filter(tw, th)
        ffmpeg = get_binary_path("ffmpeg.exe")

        cmd = [ffmpeg, "-i", self.file_path]

        maxdur = self.maxdur_var.get().strip()
        if maxdur and maxdur != "0":
            cmd += ["-t", maxdur]

        # Cleaned up filter logic
        if "[0:v]split" in filt:
            cmd += ["-filter_complex", filt]
        else:
            cmd += ["-vf", filt]

        # Encoding parameters (Auto-Hardware Detect via core.hardware)
        is_10bit = self._is_10bit(self.file_path)
        cmd += self._get_hw_encode_args(is_10bit, self.crf_var.get())
        
        if self.mute_var.get():
            cmd += ["-an"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            
        cmd += ["-movflags", "+faststart", out, "-y"]

        self.log(self.console, f"── Rendering {plat.split('(')[0].strip()} → {tw}×{th} ──")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("shortifier.format_button"))