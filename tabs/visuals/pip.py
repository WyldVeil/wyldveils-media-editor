"""
tab_pip.py  ─  Picture-in-Picture (PIP)
Overlay a foreground video (e.g. face-cam, reaction box) on top of a
background video. Full control over position, size, border, opacity,
corner rounding, and optional slide-in animation.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


POSITIONS = {
    "Top-Left":      ("20",              "20"),
    "Top-Right":     ("W-w-20",          "20"),
    "Bottom-Left":   ("20",              "H-h-20"),
    "Bottom-Right":  ("W-w-20",          "H-h-20"),
    "Centre":        ("(W-w)/2",         "(H-h)/2"),
    "Top-Centre":    ("(W-w)/2",         "20"),
    "Bottom-Centre": ("(W-w)/2",         "H-h-20"),
    "Custom":        ("custom",          "custom"),
}

ANIMATIONS = {
    "None  (static)":                  None,
    t("pip.slide_in_from_right"):             "slide_right",
    t("pip.slide_in_from_left"):              "slide_left",
    t("pip.slide_in_from_bottom"):            "slide_bottom",
    t("pip.fade_in"):                         "fade",
}


class PIPTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.bg_path   = ""
        self.fg_path   = ""
        self.preview_proc = None
        self._bg_dur   = 0.0
        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📺  " + t("tab.picture_in_picture"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("pip.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Input files ───────────────────────────────────────────────────
        inp = tk.LabelFrame(self, text=t("section.input_files"), padx=14, pady=8)
        inp.pack(fill="x", padx=16, pady=8)

        for row_idx, (label, attr, color_hint) in enumerate([
            (t("pip.background_label"), "bg_path", CLR["fg"]),
            (t("pip.foreground_label"), "fg_path", CLR["accent"]),
        ]):
            row = tk.Frame(inp); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=(UI_FONT, 9, "bold"),
                     fg=color_hint, width=30, anchor="w").pack(side="left")
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(row, textvariable=var, width=52, relief="flat").pack(side="left", padx=6)

            def _b(a=attr, v=var):
                p = filedialog.askopenfilename(
                    filetypes=[(t("color_match.video_image"),
                                "*.mp4 *.mov *.mkv *.avi *.webm *.png *.jpg"),
                               ("All", t("ducker.item_2"))])
                if p:
                    setattr(self, a, p)
                    v.set(p)
                    if a == "bg_path":
                        self._bg_dur = get_video_duration(p)
            tk.Button(row, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").pack(side="left")

        # ── Layout ────────────────────────────────────────────────────────
        cols = tk.Frame(self)
        cols.pack(fill="x", padx=16, pady=4)
        left  = tk.Frame(cols); left.pack(side="left", fill="both",
                                          expand=True, padx=(0, 8))
        right = tk.Frame(cols); right.pack(side="left", fill="both",
                                           expand=True, padx=(8, 0))

        # ════ LEFT ════════════════════════════════════════════════════════

        # ── Size ──────────────────────────────────────────────────────────
        size_lf = tk.LabelFrame(left, text=f"  {t('pip.size_section')}  ", padx=14, pady=10)
        size_lf.pack(fill="x", pady=(0, 6))

        self.size_mode_var = tk.StringVar(value="percent")
        tk.Radiobutton(size_lf, text=t("pip.of_background_width"),
                       variable=self.size_mode_var, value="percent",
                       command=self._on_size_mode).pack(anchor="w")
        tk.Radiobutton(size_lf, text=t("pip.exact_pixels"),
                       variable=self.size_mode_var, value="pixels",
                       command=self._on_size_mode).pack(anchor="w")

        pct_row = tk.Frame(size_lf); pct_row.pack(fill="x", pady=4)
        tk.Label(pct_row, text=t("pip.width")).pack(side="left")
        self.size_pct_var = tk.IntVar(value=30)
        tk.Scale(pct_row, variable=self.size_pct_var, from_=5, to=95,
                 orient="horizontal", length=200).pack(side="left", padx=6)
        self.size_pct_lbl = tk.Label(pct_row, text="30%", width=5, fg=CLR["accent"])
        self.size_pct_lbl.pack(side="left")
        self.size_pct_var.trace_add("write", lambda *_: self.size_pct_lbl.config(
            text=f"{self.size_pct_var.get()}%"))

        self.px_row = tk.Frame(size_lf)
        tk.Label(self.px_row, text="W:").pack(side="left")
        self.px_w_var = tk.StringVar(value="400")
        tk.Entry(self.px_row, textvariable=self.px_w_var, width=6, relief="flat").pack(side="left", padx=4)
        tk.Label(self.px_row, text="H:").pack(side="left")
        self.px_h_var = tk.StringVar(value="300")
        tk.Entry(self.px_row, textvariable=self.px_h_var, width=6, relief="flat").pack(side="left", padx=4)
        tk.Label(self.px_row, text=t("pip.1_auto_aspect"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Position ──────────────────────────────────────────────────────
        pos_lf = tk.LabelFrame(left, text=f"  {t('pip.position_section')}  ", padx=14, pady=10)
        pos_lf.pack(fill="x", pady=(0, 6))

        self.pos_var = tk.StringVar(value="Bottom-Right")
        pos_cb = ttk.Combobox(pos_lf, textvariable=self.pos_var,
                               values=list(POSITIONS.keys()),
                               state="readonly", width=22)
        pos_cb.pack(anchor="w")
        pos_cb.bind("<<ComboboxSelected>>", self._on_pos_change)

        self.custom_pos_f = tk.Frame(pos_lf)
        tk.Label(self.custom_pos_f, text="X:").pack(side="left")
        self.custom_x_var = tk.StringVar(value="20")
        tk.Entry(self.custom_pos_f, textvariable=self.custom_x_var, width=8, relief="flat").pack(side="left", padx=4)
        tk.Label(self.custom_pos_f, text="Y:").pack(side="left")
        self.custom_y_var = tk.StringVar(value="20")
        tk.Entry(self.custom_pos_f, textvariable=self.custom_y_var, width=8, relief="flat").pack(side="left", padx=4)
        tk.Label(self.custom_pos_f, text=t("pip.px_or_ffmpeg_expr_w_h_w_h"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Margin ────────────────────────────────────────────────────────
        marg_row = tk.Frame(pos_lf); marg_row.pack(fill="x", pady=4)
        tk.Label(marg_row, text=t("pip.edge_margin_px")).pack(side="left")
        self.margin_var = tk.StringVar(value="20")
        tk.Entry(marg_row, textvariable=self.margin_var, width=5, relief="flat").pack(side="left", padx=4)

        # ════ RIGHT ═══════════════════════════════════════════════════════

        # ── Border ────────────────────────────────────────────────────────
        border_lf = tk.LabelFrame(right, text=f"  {t('pip.border_section')}  ", padx=14, pady=10)
        border_lf.pack(fill="x", pady=(0, 6))

        b0 = tk.Frame(border_lf); b0.pack(fill="x", pady=2)
        tk.Label(b0, text=t("pip.border_thickness_label")).pack(side="left")
        self.border_var = tk.StringVar(value="3")
        tk.Entry(b0, textvariable=self.border_var, width=4, relief="flat").pack(side="left", padx=4)

        b1 = tk.Frame(border_lf); b1.pack(fill="x", pady=2)
        tk.Label(b1, text=t("pip.border_colour_label")).pack(side="left")
        self.border_color_btn = tk.Button(
            b1, text="  White  ", bg="#FFFFFF", fg="black", width=10,
            command=self._pick_border_color)
        self.border_color_btn.pack(side="left", padx=6)
        self.border_color = "#FFFFFF"

        b2 = tk.Frame(border_lf); b2.pack(fill="x", pady=2)
        tk.Label(b2, text=t("pip.corner_radius_0_square")).pack(side="left")
        self.corner_var = tk.StringVar(value="0")
        tk.Entry(b2, textvariable=self.corner_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(b2, text=t("pip.rounded_corners_via_crop_pad"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # ── Opacity ───────────────────────────────────────────────────────
        op_lf = tk.LabelFrame(right, text=f"  {t('pip.opacity_section')}  ", padx=14, pady=8)
        op_lf.pack(fill="x", pady=(0, 6))

        op_row = tk.Frame(op_lf); op_row.pack(fill="x")
        self.opacity_var = tk.DoubleVar(value=1.0)
        tk.Scale(op_row, variable=self.opacity_var, from_=0.1, to=1.0,
                 resolution=0.05, orient="horizontal", length=240).pack(side="left")
        self.op_lbl = tk.Label(op_row, text="100%", width=5, fg=CLR["accent"])
        self.op_lbl.pack(side="left")
        self.opacity_var.trace_add("write", lambda *_: self.op_lbl.config(
            text=f"{int(self.opacity_var.get()*100)}%"))

        # ── Animation ─────────────────────────────────────────────────────
        anim_lf = tk.LabelFrame(right, text=f"  {t('pip.animation_section')}  ", padx=14, pady=8)
        anim_lf.pack(fill="x", pady=(0, 6))

        self.anim_var = tk.StringVar(value=list(ANIMATIONS.keys())[0])
        ttk.Combobox(anim_lf, textvariable=self.anim_var,
                     values=list(ANIMATIONS.keys()),
                     state="readonly", width=32).pack(anchor="w")
        anim_dur_row = tk.Frame(anim_lf); anim_dur_row.pack(anchor="w", pady=4)
        tk.Label(anim_dur_row, text=t("pip.animation_duration_label")).pack(side="left")
        self.anim_dur_var = tk.StringVar(value="0.5")
        tk.Entry(anim_dur_row, textvariable=self.anim_dur_var, width=5, relief="flat").pack(side="left", padx=4)

        # ── Timing ────────────────────────────────────────────────────────
        time_lf = tk.LabelFrame(right, text=f"  {t('pip.timing_section')}  ", padx=14, pady=8)
        time_lf.pack(fill="x", pady=(0, 6))

        t_row = tk.Frame(time_lf); t_row.pack(fill="x")
        self.always_var = tk.BooleanVar(value=True)
        tk.Checkbutton(t_row, text=t("pip.always_visible_checkbox"),
                       variable=self.always_var,
                       command=self._toggle_timing).pack(side="left")

        self.timing_f = tk.Frame(time_lf)
        tk.Label(self.timing_f, text=t("pip.show_from_label")).pack(side="left")
        self.t_start_var = tk.StringVar(value="0")
        tk.Entry(self.timing_f, textvariable=self.t_start_var, width=7, relief="flat").pack(side="left", padx=4)
        tk.Label(self.timing_f, text=t("pip.show_to_label")).pack(side="left")
        self.t_end_var = tk.StringVar(value="30")
        tk.Entry(self.timing_f, textvariable=self.t_end_var, width=7, relief="flat").pack(side="left", padx=4)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=6)
        tk.Label(btn_row, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(btn_row, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Button(btn_row, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=12, command=self._preview).pack(side="left", padx=12)
        self.btn_render = tk.Button(
            btn_row, text=t("pip.render_button"),
            font=(UI_FONT, 12, "bold"), bg="#7B1FA2", fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_size_mode()

    # ─────────────────────────────────────────────────────────────────────
    def _on_size_mode(self):
        if self.size_mode_var.get() == "pixels":
            self.px_row.pack(fill="x", pady=4)
        else:
            self.px_row.pack_forget()

    def _on_pos_change(self, *_):
        if self.pos_var.get() == "Custom":
            self.custom_pos_f.pack(fill="x", pady=4)
        else:
            self.custom_pos_f.pack_forget()

    def _toggle_timing(self):
        if self.always_var.get():
            self.timing_f.pack_forget()
        else:
            self.timing_f.pack(fill="x", pady=4)

    def _pick_border_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor()
        if c[1]:
            self.border_color = c[1]
            self.border_color_btn.config(
                bg=c[1],
                text=f"  {c[1]}  ",
                fg="black" if sum(int(c[1][i:i+2], 16) for i in (1,3,5)) > 400 else "white")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _build_filter(self, preview=False):
        """Construct the FFmpeg filter_complex string."""
        margin = self.margin_var.get()

        # FG scale - use scale2ref to scale FG as a % of BG width
        if self.size_mode_var.get() == "percent":
            pct_val = self.size_pct_var.get()
            # scale2ref: scale FG width to pct% of BG width, height proportional
            scale_filter = (f"[1:v][0:v]scale2ref="
                            f"w=trunc(main_w*{pct_val/100:.4f}/2)*2:"
                            f"h=trunc(ow/dar/2)*2"
                            f"[fg_scaled][bg_ref]")
        else:
            w = self.px_w_var.get()
            h = self.px_h_var.get()
            scale_filter = f"[1:v]scale={w}:{h}[fg_scaled];[0:v]null[bg_ref]"

        # Border
        border_thick = int(self.border_var.get() or "0")
        border_color = self.border_color.lstrip("#")
        if border_thick > 0:
            pad_expr = (f"[fg_scaled]pad=iw+{border_thick*2}:ih+{border_thick*2}"
                        f":{border_thick}:{border_thick}:color={border_color}[fg_bordered]")
        else:
            pad_expr = "[fg_scaled]copy[fg_bordered]"

        # Position
        pos_key = self.pos_var.get()
        if pos_key == "Custom":
            x_expr = self.custom_x_var.get()
            y_expr = self.custom_y_var.get()
        else:
            x_tpl, y_tpl = POSITIONS[pos_key]
            # Replace margin placeholder
            x_expr = x_tpl.replace("20", margin)
            y_expr = y_tpl.replace("20", margin)

        # Opacity
        opacity = self.opacity_var.get()
        if opacity < 1.0:
            alpha_filter = f"[fg_bordered]format=rgba,colorchannelmixer=aa={opacity:.2f}[fg_alpha]"
            overlay_in = "[fg_alpha]"
        else:
            alpha_filter = None
            overlay_in = "[fg_bordered]"

        # Timing
        if not self.always_var.get():
            ts = self.t_start_var.get()
            te = self.t_end_var.get()
            enable_expr = f":enable='between(t,{ts},{te})'"
        else:
            enable_expr = ""

        # Animation
        anim_key = self.anim_var.get()
        anim_type = ANIMATIONS[anim_key]
        anim_dur  = float(self.anim_dur_var.get() or "0.5")
        if anim_type and not preview:
            if anim_type == "slide_right":
                x_expr = f"'if(lt(t,{anim_dur}),W-w*t/{anim_dur},{x_expr})'"
            elif anim_type == "slide_left":
                x_expr = f"'if(lt(t,{anim_dur}),-(w)*(1-t/{anim_dur}),{x_expr})'"
            elif anim_type == "slide_bottom":
                y_expr = f"'if(lt(t,{anim_dur}),H-h*t/{anim_dur},{y_expr})'"
            elif anim_type == "fade":
                # override opacity with animated alpha
                alpha_filter = (f"[fg_bordered]format=rgba,"
                                f"colorchannelmixer=aa='if(lt(t,{anim_dur}),t/{anim_dur},{opacity:.2f})'[fg_alpha]")
                overlay_in = "[fg_alpha]"

        overlay_expr = f"overlay={x_expr}:{y_expr}{enable_expr}"

        # Build full filter chain
        parts = [scale_filter, pad_expr]
        if alpha_filter:
            parts.append(alpha_filter)
        parts.append(f"[bg_ref]{overlay_in}{overlay_expr}")

        return ";".join(parts)

    def _preview(self):
        if not self.bg_path or not self.fg_path:
            messagebox.showwarning(t("pip.missing_files_title"), t("pip.missing_files_message"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay  = get_binary_path("ffplay.exe")
        fc = self._build_filter(preview=True)
        cmd = [ffplay, "-i", self.bg_path, "-i", self.fg_path,
               "-filter_complex", fc,
               "-window_title", t("pip.pip_preview"), "-x", "960", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.bg_path or not self.fg_path:
            messagebox.showwarning(t("pip.missing_files_title"), t("pip.missing_files_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        fc     = self._build_filter()

        cmd = [ffmpeg, "-i", self.bg_path, "-i", self.fg_path,
               "-filter_complex", fc,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(), "-preset", "fast",
               t("dynamics.c_a"), "copy", "-shortest", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, t("log.pip.building_pip_composite"))
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("pip.render_button"))
