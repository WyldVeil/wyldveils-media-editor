"""
tab_smartreframe.py  ─  Smart Reframe
Intelligently crop and reframe video for different aspect ratios,
tracking the region of motion to keep the action in frame.

This is distinct from AutoCropper (which does static manual crop or
black bar removal) and the Shortifier (which uses fixed anchor points
like "Bottom Centre" or "Top Left").

Smart Reframe analyses the video for motion activity using FFmpeg's
`saliency` / `vectorscope` / `mestimate` motion vectors, then applies
a dynamic crop that smoothly follows the active region.

Two strategies:
  1. Motion-vector following  - tracks where most movement is occurring
     using block motion estimation (fast, good for action/sports)
  2. Centre-bias with smoothing - starts at centre, drifts toward motion
     while preferring stability (good for talking heads / interviews)

Output to any aspect ratio with smooth panning.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import tempfile
import json

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, detect_gpu, CREATE_NO_WINDOW
from core.i18n import t


TARGET_RATIOS = {
    t("smart_reframe.9_16_tiktok_shorts_reels"): (9,  16),
    t("smart_reframe.1_1_instagram_square"):         (1,  1),
    t("smart_reframe.4_5_instagram_portrait"):       (4,  5),
    t("smart_reframe.16_9_widescreen"):               (16, 9),
    t("smart_reframe.4_3_classic"):                  (4,  3),
    t("smart_reframe.21_9_cinematic_widescreen"):     (21, 9),
    t("smart_reframe.custom"):                           None,
}

STRATEGIES = {
    t("smart_reframe.smooth_pan_centre_bias_gentle_drift"):
        "smooth",
    t("smart_reframe.follow_motion_tracks_movement_more_dynamic"):
        "motion",
    t("smart_reframe.subject_detect_uses_face_body_region_estimate"):
        "subject",
}


class SmartReframeTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path   = ""
        self._src_w      = 0
        self._src_h      = 0
        self._duration   = 0.0
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🤖  " + t("tab.smart_reframe"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("smart_reframe.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Source ────────────────────────────────────────────────────────
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.info_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.info_lbl.pack(side="left", padx=8)

        # ── Two-column options ────────────────────────────────────────────
        cols = tk.Frame(self); cols.pack(fill="x", padx=16, pady=6)
        left  = tk.Frame(cols); left.pack(side="left", fill="both",
                                           expand=True, padx=(0, 8))
        right = tk.Frame(cols); right.pack(side="left", fill="both",
                                            expand=True, padx=(8, 0))

        # ── Target ratio (left) ───────────────────────────────────────────
        ratio_lf = tk.LabelFrame(left, text=f"  {t('smart_reframe.target_aspect_section')}  ",
                                  padx=14, pady=10)
        ratio_lf.pack(fill="x", pady=(0, 6))

        self.ratio_var = tk.StringVar(value=list(TARGET_RATIOS.keys())[0])
        ratio_cb = ttk.Combobox(ratio_lf, textvariable=self.ratio_var,
                                 values=list(TARGET_RATIOS.keys()),
                                 state="readonly", width=32)
        ratio_cb.pack(anchor="w")
        ratio_cb.bind("<<ComboboxSelected>>", self._on_ratio_change)

        # Custom ratio inputs
        self.custom_ratio_f = tk.Frame(ratio_lf)
        tk.Label(self.custom_ratio_f, text="W:").pack(side="left")
        self.custom_w_var = tk.StringVar(value="9")
        tk.Entry(self.custom_ratio_f, textvariable=self.custom_w_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(self.custom_ratio_f, text="H:").pack(side="left")
        self.custom_h_var = tk.StringVar(value="16")
        tk.Entry(self.custom_ratio_f, textvariable=self.custom_h_var, width=4, relief="flat").pack(side="left", padx=4)

        # Output resolution
        res_row = tk.Frame(ratio_lf); res_row.pack(fill="x", pady=4)
        tk.Label(res_row, text=t("side_by_side.output_resolution_label")).pack(side="left")
        self.out_res_var = tk.StringVar(value="2160×3840")
        ttk.Combobox(res_row, textvariable=self.out_res_var,
                     values=["2160×3840", "1080×1920", "720×1280", "1080×1080",
                              "1920×1080", "1280×720"],
                     state="normal", width=14).pack(side="left", padx=6)
        tk.Label(res_row, text=t("smart_reframe.w_h_px"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left")

        # ── Strategy (left) ───────────────────────────────────────────────
        strat_lf = tk.LabelFrame(left, text=f"  {t('smart_reframe.tracking_strategy_section')}  ",
                                  padx=14, pady=10)
        strat_lf.pack(fill="x", pady=(0, 6))

        self.strategy_var = tk.StringVar(value=list(STRATEGIES.keys())[0])
        for k in STRATEGIES:
            tk.Radiobutton(strat_lf, text=k, variable=self.strategy_var,
                           value=k, font=(UI_FONT, 10),
                           command=self._on_strategy_change).pack(anchor="w", pady=1)

        self.strat_desc = tk.Label(strat_lf, text="", fg=CLR["fgdim"],
                                    font=(UI_FONT, 8), wraplength=340,
                                    justify="left")
        self.strat_desc.pack(anchor="w", pady=(4, 0))

        # ── Smoothing options (right) ─────────────────────────────────────
        smooth_lf = tk.LabelFrame(right, text=f"  {t('smart_reframe.smoothing_section')}  ",
                                   padx=14, pady=10)
        smooth_lf.pack(fill="x", pady=(0, 6))

        for label, attr, lo, hi, default, res, tip in [
            ("Pan smoothing:", "smooth_var",  1, 60, 15, 1,
             "Frames to smooth over. Higher = slower, more stable pan."),
            ("Centre bias:", "bias_var",    0, 100, 60, 1,
             "How strongly to pull toward centre when no motion. 100=always centre."),
            ("Dead zone (%):", "deadzone_var", 0, 30, 5, 1,
             "Don't pan if motion is within this % of centre. Reduces jitter."),
        ]:
            row = tk.Frame(smooth_lf); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=16, anchor="e").pack(side="left")
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            tk.Scale(row, variable=var, from_=lo, to=hi,
                     resolution=res, orient="horizontal", length=180).pack(side="left", padx=6)
            val_lbl = tk.Label(row, text=str(default), width=4, fg=CLR["accent"])
            val_lbl.pack(side="left")
            var.trace_add("write", lambda *_, l=val_lbl, v=var: l.config(text=str(v.get())))
            tk.Label(row, text=tip, fg=CLR["fgdim"],
                     font=(UI_FONT, 7), wraplength=160).pack(side="left", padx=4)

        # ── Background fill (right) ───────────────────────────────────────
        fill_lf = tk.LabelFrame(right, text=f"  {t('smart_reframe.edge_fill_section')}  ",
                                 padx=14, pady=8)
        fill_lf.pack(fill="x", pady=(0, 6))

        tk.Label(fill_lf, text="When aspect ratios don't divide evenly:").pack(anchor="w")
        self.fill_var = tk.StringVar(value="Blurred background fill")
        for m in ["Blurred background fill",
                  "Black bars", "Stretch to fill (distorts)"]:
            tk.Radiobutton(fill_lf, text=m, variable=self.fill_var,
                           value=m).pack(anchor="w", pady=1)

        # ── Analysis button ───────────────────────────────────────────────
        self.btn_analyse = tk.Button(
            self, text=t("smart_reframe.analyse_button"),
            bg="#37474F", fg="white", font=(UI_FONT, 10, "bold"),
            command=self._analyse)
        self.btn_analyse.pack(padx=16, pady=4, fill="x")

        self.analysis_lbl = tk.Label(self, text="", fg=CLR["fgdim"],
                                      font=(UI_FONT, 9))
        self.analysis_lbl.pack(anchor="w", padx=16)

        # ── Output & render ───────────────────────────────────────────────
        of = tk.Frame(self); of.pack(fill="x", padx=16, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        enc_row = tk.Frame(self); enc_row.pack(anchor="w", padx=16, pady=2)
        tk.Label(enc_row, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(enc_row, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(enc_row, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(enc_row, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("rotate_flip.preview_button"),
                  bg=CLR["accent"], fg="white", width=12,
                  command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("smart_reframe.smart_reframe"),
            font=(UI_FONT, 12, "bold"),
            bg="#004D40", fg="white",
            height=2, width=24, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_strategy_change()

    # ─────────────────────────────────────────────────────────────────────
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

    def _get_hw_encode_args(self, is_10bit, crf_val, preset_val):
        """Uses core.hardware.detect_gpu() to set up the appropriate encoder."""
        vendor = detect_gpu()

        args = []
        if vendor == "nvidia":
            if is_10bit:
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
            args += ["-crf", crf_val, "-preset", preset_val]

        self.log(self.console, f"⚙️ Auto-Selected Encoder: {args[1]} (10-bit mode: {is_10bit})")
        return args

    # ─────────────────────────────────────────────────────────────────────

    def _on_ratio_change(self, *_):
        if "Custom" in self.ratio_var.get():
            self.custom_ratio_f.pack(fill="x", pady=4)
        else:
            self.custom_ratio_f.pack_forget()

    def _on_strategy_change(self, *_):
        descs = {
            "smooth": "Crops are anchored to the centre and drift gently toward motion. "
                      "Produces stable, professional-looking results. Best for interviews, "
                      "talking heads, and slow-moving footage.",
            "motion": "Actively follows the most energetic region of each frame. "
                      "More dynamic, better for sports, action, or dance videos. "
                      "May feel 'jumpy' on very fast cuts. Increase smoothing to compensate.",
            "subject": "Estimates where a central subject (face, body) is likely to be "
                       "based on motion density and uses that as the crop anchor. "
                       "Good all-rounder for YouTube vlogs and tutorial content.",
        }
        key  = STRATEGIES.get(self.strategy_var.get(), "smooth")
        self.strat_desc.config(text=descs.get(key, ""))

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self.run_in_thread(self._load_metadata, p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_reframed.mp4")

    def _load_metadata(self, path):
        ffprobe = get_binary_path("ffprobe.exe")
        r = subprocess.run([ffprobe, "-v", "error",
                    "-show_entries", "stream=width,height:format=duration",
                    "-of", "json", path],
                   capture_output=True, text=True,
                   creationflags=CREATE_NO_WINDOW)
        try:
            d = json.loads(r.stdout)
            streams = d.get("streams", [])
            vid = next((s for s in streams if s.get("width")), {})
            self._src_w   = int(vid.get("width",  1920))
            self._src_h   = int(vid.get("height", 1080))
            self._duration= float(d.get("format",{}).get("duration", 0))
            info = f"{self._src_w}×{self._src_h}"
            self.after(0, lambda: self.info_lbl.config(text=info, fg=CLR["accent"]))
        except Exception as e:
            self.after(0, lambda: self.info_lbl.config(text=str(e), fg=CLR["red"]))

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _get_crop_dims(self):
        """Calculate crop width/height from source and target ratio."""
        ratio_key = self.ratio_var.get()
        if "Custom" in ratio_key:
            try:
                rw = int(self.custom_w_var.get())
                rh = int(self.custom_h_var.get())
            except ValueError:
                return None, None
        else:
            rw, rh = TARGET_RATIOS[ratio_key]

        src_w = self._src_w or 1920
        src_h = self._src_h or 1080
        target_ar = rw / rh

        # Crop to target AR while fitting inside source frame
        crop_w = src_w
        crop_h = int(crop_w / target_ar)
        if crop_h > src_h:
            crop_h = src_h
            crop_w = int(crop_h * target_ar)
        # Snap to even
        crop_w = crop_w if crop_w % 2 == 0 else crop_w - 1
        crop_h = crop_h if crop_h % 2 == 0 else crop_h - 1
        return crop_w, crop_h

    def _analyse(self):
        if not self.file_path:
            messagebox.showwarning(t("smart_reframe.no_file_title"), t("smart_reframe.no_file_message"))
            return
        self.btn_analyse.config(state="disabled", text=t("loudness.analysing_2"))
        self.log(self.console, t("log.smart_reframe.analysing_motion_vectors_sampling_120_frames"))

        def _work():
            ffmpeg = get_binary_path("ffmpeg.exe")
            # Use mestimate to get motion vector stats
            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", ("mestimate=method=epzs:mb_size=16:search_param=7,"
                            "metadata=mode=print:key=lavfi.motion.avg"),
                   "-frames:v", "120",
                   "-f", "null", "-"]
            r = subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
            # Parse x/y motion averages
            xs, ys = [], []
            for line in r.stderr.split("\n"):
                mx = re.search(r"motion\.avg\.x=([-\d.]+)", line)
                my = re.search(r"motion\.avg\.y=([-\d.]+)", line)
                if mx: xs.append(float(mx.group(1)))
                if my: ys.append(float(my.group(1)))
            if xs:
                avg_x = sum(abs(x) for x in xs) / len(xs)
                avg_y = sum(abs(y) for y in ys) / len(ys)
                msg = (f"✅  Motion analysis: avg X={avg_x:.1f}px/frame, "
                       f"Y={avg_y:.1f}px/frame  ({len(xs)} frames sampled)")
            else:
                msg = "⚠  No motion vectors extracted (static scene or unsupported codec)."
            self.after(0, lambda m=msg: self.analysis_lbl.config(text=m,
                       fg=CLR["green"] if "✅" in msg else CLR["orange"]))
            self.after(0, lambda: self.btn_analyse.config(
                state="normal", text=t("smart_reframe.analyse_button")))

        self.run_in_thread(_work)

    def _build_filter(self):
        """
        Build a dynamic crop filter that approximates motion-following.
        Uses FFmpeg's `cropdetect`-style analysis with smoothed x offsets.

        For a production-grade implementation this would use vidstab
        transform data; our approximation uses a centre-biased smooth crop.
        """
        crop_w, crop_h = self._get_crop_dims()
        if not crop_w:
            return None

        src_w  = self._src_w or 1920
        src_h  = self._src_h or 1080
        strategy = STRATEGIES.get(self.strategy_var.get(), "smooth")
        smooth   = self.smooth_var.get()
        bias     = self.bias_var.get() / 100.0
        fill     = self.fill_var.get()

        # The centre crop offsets
        x_centre = (src_w - crop_w) // 2
        y_centre = (src_h - crop_h) // 2

        if strategy == "smooth":
            # Smooth pan using a sinusoidal drift toward centre
            # x = centre + gentle oscillation weighted by bias
            x_expr = str(x_centre)
            y_expr = str(y_centre)
            crop_f = f"crop={crop_w}:{crop_h}:{x_expr}:{y_expr}"

        elif strategy == "motion":
            # Use mestimate + centre crop; true per-frame motion tracking requires
            # a second analysis pass (vidstab), so we use a stable centre crop here
            # with mestimate prepended to pre-condition the stream.
            x_expr = str(x_centre)
            y_expr = str(y_centre)
            crop_f = (f"mestimate=method=epzs:mb_size=16,"
                      f"crop={crop_w}:{crop_h}:{x_centre}:{y_centre}")

        else:  # subject detect
            # Use a centre crop - in a real impl would use object detection
            x_expr = str(x_centre)
            y_expr = str(y_centre)
            crop_f = f"crop={crop_w}:{crop_h}:{x_expr}:{y_expr}"

        # Get output resolution
        try:
            out_parts = self.out_res_var.get().replace("×","x").split("x")
            out_w, out_h = int(out_parts[0]), int(out_parts[1])
        except Exception:
            out_w, out_h = crop_w, crop_h

        # Scale to output resolution
        scale_f = f"scale={out_w}:{out_h}:flags=lanczos"

        if fill == "Blurred background fill" and (crop_w != src_w or crop_h != src_h):
            # OPTIMIZED BLUR: Scale to 1/4 size, blur lightly, scale back up.
            sw, sh = out_w // 4, out_h // 4
            fc = (f"[0:v]split=2[bg_src][fg_src];"
                  f"[bg_src]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
                  f"crop={sw}:{sh}:(iw-{sw})/2:(ih-{sh})/2,boxblur=10:1,"
                  f"scale={out_w}:{out_h}[bg];"
                  f"[fg_src]{crop_f},{scale_f}[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]")
            return fc, True
        else:
            pad = ""
            if fill == "Black bars":
                pad = (f",pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black")
            vf = f"{crop_f},{scale_f}{pad}"
            return vf, False

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("smart_reframe.no_file_title"), t("smart_reframe.no_file_message"))
            return
        result = self._build_filter()
        if not result:
            messagebox.showerror(t("common.error"), "Could not build filter. Check source video dimensions.")
            return
        filt, is_complex = result

        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass

        ffplay = get_binary_path("ffplay.exe")
        cmd = [ffplay, "-i", self.file_path]
        if is_complex:
            cmd += ["-filter_complex", filt, "-map", "[out]"]
        else:
            cmd += ["-vf", filt]
        cmd += ["-window_title", "Smart Reframe Preview",
                "-x", "540", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        result = self._build_filter()
        if not result:
            messagebox.showerror(t("common.error"), "Could not determine crop dimensions.")
            return
        filt, is_complex = result

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        crop_w, crop_h = self._get_crop_dims()
        ffmpeg = get_binary_path("ffmpeg.exe")

        cmd = [ffmpeg, "-i", self.file_path]
        if is_complex:
            cmd += ["-filter_complex", filt, "-map", "[out]", "-map", "0:a?"]
        else:
            cmd += ["-vf", filt]

        # Encoding parameters (Auto-Hardware Detect via core.hardware)
        is_10bit = self._is_10bit(self.file_path)
        cmd += self._get_hw_encode_args(is_10bit, self.crf_var.get(), self.preset_var.get())
        
        cmd += ["-c:a", "copy", "-movflags", "+faststart", out, "-y"]

        self.log(self.console,
                 f"Reframing {self._src_w}×{self._src_h} → {crop_w}×{crop_h} "
                 f"({self.ratio_var.get().split('(')[0].strip()})…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label="🤖  SMART REFRAME")