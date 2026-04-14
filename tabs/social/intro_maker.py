"""
tab_intromaker.py  ─  Intro / Outro Maker
Generate animated title card bumpers for YouTube channel branding.

Can produce:
  • Standalone intro/outro video clip
  • Prepend intro to an existing video
  • Append outro to an existing video
  • Both together

Uses FFmpeg lavfi (colour source) + drawtext with fade animations.
Fully offline - no templates needed.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import subprocess
import os
import tempfile
import json
import shutil

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


ANIMATIONS = {
    t("intro_maker.fade_in_fade_out"):         "fade",
    t("intro_maker.slide_up_fade_out"):        "slide_up",
    t("intro_maker.zoom_in"):                     "zoom",
    "Typewriter":                  "typewriter",
    t("intro_maker.static_no_animation"):      "static",
}

BG_STYLES = {
    t("intro_maker.solid_colour"):                "solid",
    t("intro_maker.horizontal_gradient"):         "gradient_h",
    t("intro_maker.vertical_gradient"):           "gradient_v",
    t("intro_maker.dark_cinematic_black"):      "black",
    t("intro_maker.custom_image_video"):          "custom",
}

RESOLUTIONS = {
    t("intro_maker.1920_1080_full_hd"): (1920, 1080),
    t("intro_maker.3840_2160_4k"):      (3840, 2160),
    t("intro_maker.1280_720_hd"):      (1280, 720),
    t("intro_maker.1080_1920_9_16_vertical"): (1080, 1920),
    t("intro_maker.1080_1080_square"):  (1080, 1080),
}


class IntroMakerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.bg_custom_path = ""
        self.main_video_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🎬  " + t("tab.intro_outro_maker"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("intro_maker.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Notebook for sections
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=14, pady=8)

        self._build_design_tab(nb)
        self._build_text_tab(nb)
        self._build_attach_tab(nb)

    # ── Design tab ────────────────────────────────────────────────────────
    def _build_design_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=f"  🎨  {t('intro_maker.design_tab')}  ")

        # Two columns
        cols = tk.Frame(f); cols.pack(fill="both", expand=True, padx=14, pady=8)
        left  = tk.Frame(cols); left.pack(side="left", fill="both", expand=True, padx=(0,6))
        right = tk.Frame(cols); right.pack(side="left", fill="both", expand=True, padx=(6,0))

        # ── Background ────────────────────────────────────────────────────
        bg_lf = tk.LabelFrame(left, text=f"  {t('intro_maker.background_section')}  ", padx=14, pady=10)
        bg_lf.pack(fill="x", pady=(0, 6))

        self.bg_style_var = tk.StringVar(value="Solid colour")
        bg_cb = ttk.Combobox(bg_lf, textvariable=self.bg_style_var,
                              values=list(BG_STYLES.keys()),
                              state="readonly", width=28)
        bg_cb.pack(anchor="w")
        bg_cb.bind("<<ComboboxSelected>>", self._on_bg_change)

        color_row = tk.Frame(bg_lf); color_row.pack(fill="x", pady=6)
        tk.Label(color_row, text=t("intro_maker.primary_colour_label")).pack(side="left")
        self.bg_color1 = "#1A1A2E"
        self.color1_btn = tk.Button(color_row, text=t("intro_maker.1a1a2e"),
                                     bg="#1A1A2E", fg="white", width=12,
                                     command=lambda: self._pick_color("bg1"))
        self.color1_btn.pack(side="left", padx=6)
        tk.Label(color_row, text=t("intro_maker.secondary_label")).pack(side="left")
        self.bg_color2 = "#16213E"
        self.color2_btn = tk.Button(color_row, text=t("intro_maker.16213e"),
                                     bg="#16213E", fg="white", width=12,
                                     command=lambda: self._pick_color("bg2"))
        self.color2_btn.pack(side="left", padx=6)

        self.bg_custom_f = tk.Frame(bg_lf)
        tk.Label(self.bg_custom_f, text=t("intro_maker.background_file_label")).pack(side="left")
        self.bg_custom_var = tk.StringVar()
        tk.Entry(self.bg_custom_f, textvariable=self.bg_custom_var, width=32, relief="flat").pack(side="left", padx=4)
        tk.Button(self.bg_custom_f, text="…", width=2,
                  command=self._browse_bg_custom).pack(side="left")

        # ── Duration & resolution ──────────────────────────────────────────
        dur_lf = tk.LabelFrame(left, text=f"  {t('intro_maker.duration_size_section')}  ", padx=14, pady=10)
        dur_lf.pack(fill="x", pady=(0, 6))

        d0 = tk.Frame(dur_lf); d0.pack(fill="x", pady=3)
        tk.Label(d0, text=t("intro_maker.duration_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.duration_var = tk.StringVar(value="5")
        tk.Entry(d0, textvariable=self.duration_var, width=5, font=(UI_FONT, 12), relief="flat").pack(side="left", padx=8)
        for v in ["3", "5", "7", "10"]:
            tk.Button(d0, text=f"{v}s", width=4, bg="#333", fg=CLR["fg"],
                      command=lambda val=v: self.duration_var.set(val)).pack(side="left", padx=2)

        d1 = tk.Frame(dur_lf); d1.pack(fill="x", pady=3)
        tk.Label(d1, text=t("common.resolution"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.res_var = tk.StringVar(value=list(RESOLUTIONS.keys())[0])
        ttk.Combobox(d1, textvariable=self.res_var, values=list(RESOLUTIONS.keys()),
                     state="readonly", width=24).pack(side="left", padx=8)

        d2 = tk.Frame(dur_lf); d2.pack(fill="x", pady=3)
        tk.Label(d2, text=t("batch_joiner.lbl_fps")).pack(side="left")
        self.fps_var = tk.StringVar(value="30")
        ttk.Combobox(d2, textvariable=self.fps_var,
                     values=["24", "25", "30", "50", "60"], state="readonly", width=6).pack(side="left", padx=4)

        # ── Animation ─────────────────────────────────────────────────────
        anim_lf = tk.LabelFrame(right, text=f"  {t('intro_maker.text_animation_section')}  ", padx=14, pady=10)
        anim_lf.pack(fill="x", pady=(0, 6))

        self.anim_var = tk.StringVar(value=list(ANIMATIONS.keys())[0])
        for key in ANIMATIONS:
            tk.Radiobutton(anim_lf, text=key, variable=self.anim_var,
                           value=key, font=(UI_FONT, 10)).pack(anchor="w", pady=1)

        a_row = tk.Frame(anim_lf); a_row.pack(fill="x", pady=4)
        tk.Label(a_row, text=t("intro_maker.fade_duration_label")).pack(side="left")
        self.fade_dur_var = tk.StringVar(value="0.8")
        tk.Entry(a_row, textvariable=self.fade_dur_var, width=5, relief="flat").pack(side="left", padx=4)

        # ── Output file ────────────────────────────────────────────────────
        out_lf = tk.LabelFrame(right, text=f"  {t('intro_maker.output_section')}  ", padx=14, pady=8)
        out_lf.pack(fill="x", pady=(0, 6))

        out_row = tk.Frame(out_lf); out_row.pack(fill="x")
        self.out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.out_var, width=36, relief="flat").pack(side="left")
        tk.Button(out_row, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left", padx=6)

        btn_row = tk.Frame(right); btn_row.pack(pady=8)
        self.btn_gen = tk.Button(
            btn_row, text=t("intro_maker.generate_button"),
            font=(UI_FONT, 12, "bold"), bg="#7B1FA2", fg="white",
            height=2, width=22, command=self._generate_bumper)
        self.btn_gen.pack()

        cf = tk.Frame(right); cf.pack(fill="both", expand=True, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Text tab ──────────────────────────────────────────────────────────
    def _build_text_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=f"  ✏  {t('intro_maker.text_tab')}  ")

        outer = tk.Frame(f); outer.pack(fill="both", expand=True, padx=14, pady=10)
        left  = tk.Frame(outer); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right = tk.Frame(outer); right.pack(side="left", fill="both", expand=True)

        # Main title
        t_lf = tk.LabelFrame(left, text=f"  {t('intro_maker.title_line_section')}  ", padx=14, pady=10)
        t_lf.pack(fill="x", pady=(0, 6))

        tk.Label(t_lf, text=t("intro_maker.text_label"), font=(UI_FONT, 10, "bold")).pack(anchor="w")
        self.title_var = tk.StringVar(value="My Channel")
        tk.Entry(t_lf, textvariable=self.title_var, width=38,
                 font=(UI_FONT, 13)).pack(fill="x", pady=4)

        t0 = tk.Frame(t_lf); t0.pack(fill="x", pady=3)
        tk.Label(t0, text=t("intro_maker.font_size_label")).pack(side="left")
        self.title_size_var = tk.StringVar(value="72")
        tk.Entry(t0, textvariable=self.title_size_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(t0, text=f"  {t('intro_maker.colour_label')}").pack(side="left")
        self.title_color = "#FFFFFF"
        self.title_color_btn = tk.Button(t0, text="  White  ",
                                          bg="#FFFFFF", fg="black", width=10,
                                          command=lambda: self._pick_color("title"))
        self.title_color_btn.pack(side="left", padx=4)

        t1 = tk.Frame(t_lf); t1.pack(fill="x", pady=3)
        tk.Label(t1, text=t("intro_maker.font_label")).pack(side="left")
        self.title_font_var = tk.StringVar(value="Arial")
        ttk.Combobox(t1, textvariable=self.title_font_var,
                     values=["Arial","Impact","Helvetica","Verdana",
                              "Georgia",t("intro_maker.hard_subber_times_new_roman"),t("intro_maker.hard_subber_courier_new")],
                     width=18).pack(side="left", padx=4)

        t2 = tk.Frame(t_lf); t2.pack(fill="x", pady=3)
        self.title_bold_var = tk.BooleanVar(value=True)
        tk.Checkbutton(t2, text="Bold", variable=self.title_bold_var).pack(side="left")
        self.title_shadow_var = tk.BooleanVar(value=True)
        tk.Checkbutton(t2, text=t("intro_maker.shadow_checkbox"), variable=self.title_shadow_var).pack(side="left", padx=8)
        self.title_outline_var = tk.BooleanVar(value=False)
        tk.Checkbutton(t2, text="Outline", variable=self.title_outline_var).pack(side="left")

        # Subtitle line
        s_lf = tk.LabelFrame(left, text=f"  {t('intro_maker.subtitle_line_section')}  ", padx=14, pady=10)
        s_lf.pack(fill="x", pady=(0, 6))

        self.sub_var = tk.StringVar(value="Subscribe · Like · Comment")
        tk.Entry(s_lf, textvariable=self.sub_var, width=38, relief="flat").pack(fill="x", pady=4)
        s0 = tk.Frame(s_lf); s0.pack(fill="x")
        tk.Label(s0, text=t("hard_subber.size_label")).pack(side="left")
        self.sub_size_var = tk.StringVar(value="36")
        tk.Entry(s0, textvariable=self.sub_size_var, width=5, relief="flat").pack(side="left", padx=4)
        tk.Label(s0, text=f"  {t('intro_maker.colour_label')}").pack(side="left")
        self.sub_color = "#AAAAAA"
        self.sub_color_btn = tk.Button(s0, text="  Grey  ",
                                        bg="#AAAAAA", fg="black", width=10,
                                        command=lambda: self._pick_color("sub"))
        self.sub_color_btn.pack(side="left", padx=4)

        # Position
        pos_lf = tk.LabelFrame(right, text=f"  {t('intro_maker.text_position_section')}  ", padx=14, pady=10)
        pos_lf.pack(fill="x", pady=(0, 6))
        self.text_pos_var = tk.StringVar(value="Centre")
        for pos in ["Centre", "Lower Third", "Top Centre", "Custom"]:
            tk.Radiobutton(pos_lf, text=pos, variable=self.text_pos_var,
                           value=pos, font=(UI_FONT, 10)).pack(anchor="w", pady=2)

        c_pos_f = tk.Frame(pos_lf)
        tk.Label(c_pos_f, text=t("intro_maker.y_offset_px_from_centre")).pack(side="left")
        self.title_y_offset_var = tk.StringVar(value="0")
        tk.Entry(c_pos_f, textvariable=self.title_y_offset_var, width=6, relief="flat").pack(side="left", padx=4)
        c_pos_f.pack(anchor="w", pady=4)

    # ── Attach tab ────────────────────────────────────────────────────────
    def _build_attach_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=f"  📎  {t('intro_maker.attach_tab')}  ")

        tk.Label(f, text=t("intro_maker.prepend_an_intro_append_an_outro_to_an_existing"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=14, pady=8)

        main_f = tk.Frame(f); main_f.pack(fill="x", padx=14, pady=4)
        tk.Label(main_f, text=t("intro_maker.main_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.main_var = tk.StringVar()
        tk.Entry(main_f, textvariable=self.main_var, width=55, relief="flat").pack(side="left", padx=8)
        tk.Button(main_f, text=t("btn.browse"),
                  command=lambda: self._browse_main()).pack(side="left")

        mode_lf = tk.LabelFrame(f, text=f"  {t('intro_maker.attach_mode_section')}  ", padx=14, pady=8)
        mode_lf.pack(fill="x", padx=14, pady=6)
        self.attach_mode_var = tk.StringVar(value="prepend")
        for val, label in [("prepend", t("intro_maker.prepend_option")),
                            ("append",  t("intro_maker.append_option")),
                            ("both",    t("intro_maker.both_option"))]:
            tk.Radiobutton(mode_lf, text=label, variable=self.attach_mode_var,
                           value=val, font=(UI_FONT, 10)).pack(anchor="w", pady=2)

        note = tk.LabelFrame(f, text=f"  {t('intro_maker.note_section')}  ", padx=14, pady=6)
        note.pack(fill="x", padx=14, pady=4)
        tk.Label(note,
                 text=("The bumper will be re-encoded to match the main video's resolution.\n"
                       "Generate the standalone bumper first (Design tab), then attach it here."),
                 fg=CLR["fgdim"], justify="left").pack(anchor="w")

        out_f = tk.Frame(f); out_f.pack(fill="x", padx=14, pady=6)
        tk.Label(out_f, text=t("crossfader.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.attach_out_var = tk.StringVar()
        tk.Entry(out_f, textvariable=self.attach_out_var, width=55, relief="flat").pack(side="left", padx=8)
        tk.Button(out_f, text=t("common.save_as"), command=self._browse_attach_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_attach = tk.Button(
            f, text=t("intro_maker.attach_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=24, command=self._attach)
        self.btn_attach.pack(pady=10)

        cf2 = tk.Frame(f); cf2.pack(fill="both", expand=True, padx=14, pady=4)
        cons2, csb2 = self.make_console(cf2, height=6)
        cons2.pack(side="left", fill="both", expand=True)
        csb2.pack(side="right", fill="y")
        self.attach_console = cons2

    # ═══════════════════════════════════════════════════════════════════════
    def _on_bg_change(self, *_):
        if self.bg_style_var.get() == t("intro_maker.custom_image_video"):
            self.bg_custom_f.pack(fill="x", pady=4)
        else:
            self.bg_custom_f.pack_forget()

    def _pick_color(self, target):
        c = colorchooser.askcolor()
        if not c[1]: return
        hex_c = c[1]
        fg = "black" if sum(int(hex_c[i:i+2], 16) for i in (1,3,5)) > 400 else "white"
        if target == "bg1":
            self.bg_color1 = hex_c
            self.color1_btn.config(bg=hex_c, fg=fg, text=f"  {hex_c}  ")
        elif target == "bg2":
            self.bg_color2 = hex_c
            self.color2_btn.config(bg=hex_c, fg=fg, text=f"  {hex_c}  ")
        elif target == "title":
            self.title_color = hex_c
            self.title_color_btn.config(bg=hex_c, fg=fg, text=f"  {hex_c}  ")
        elif target == "sub":
            self.sub_color = hex_c
            self.sub_color_btn.config(bg=hex_c, fg=fg, text=f"  {hex_c}  ")

    def _browse_bg_custom(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("intro_maker.image_video"), "*.jpg *.jpeg *.png *.mp4 *.mov"), ("All", t("ducker.item_2"))])
        if p:
            self.bg_custom_path = p
            self.bg_custom_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _browse_main(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", t("ducker.item_2"))])
        if p:
            self.main_video_path = p
            self.main_var.set(p)

    def _browse_attach_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.attach_out_var.set(p)

    def _build_text_filters(self, w, h, dur):
        """Build drawtext filter strings for title and subtitle."""
        title      = self.title_var.get().replace("'", "").replace(":", "\\:")
        sub        = self.sub_var.get().replace("'", "").replace(":", "\\:")
        t_size     = self.title_size_var.get()
        s_size     = self.sub_size_var.get()
        t_color    = self.title_color.lstrip("#")
        s_color    = self.sub_color.lstrip("#")
        t_font     = self.title_font_var.get()
        t_bold     = ":bold=1" if self.title_bold_var.get() else ""
        shadow     = ":shadowcolor=black@0.8:shadowx=3:shadowy=3" if self.title_shadow_var.get() else ""
        outline    = ":bordercolor=black@0.9:borderw=3" if self.title_outline_var.get() else ""
        fade_dur   = float(self.fade_dur_var.get() or "0.8")

        pos = self.text_pos_var.get()
        if pos == "Centre":
            t_x, t_y = "(w-text_w)/2", "(h-text_h)/2"
            s_x, s_y = "(w-text_w)/2", f"(h-text_h)/2+{int(t_size)+20}"
        elif pos == "Lower Third":
            t_x, t_y = "80", f"{int(h*0.65)}"
            s_x, s_y = "80", f"{int(h*0.65)+int(t_size)+10}"
        elif pos == "Top Centre":
            t_x, t_y = "(w-text_w)/2", "80"
            s_x, s_y = "(w-text_w)/2", f"80+{int(t_size)+10}"
        else:
            y_off = int(self.title_y_offset_var.get() or "0")
            t_x, t_y = "(w-text_w)/2", f"(h-text_h)/2+{y_off}"
            s_x, s_y = "(w-text_w)/2", f"(h-text_h)/2+{y_off+int(t_size)+20}"

        anim = self.anim_var.get()
        if "Fade" in anim:
            alpha = f"'if(lt(t,{fade_dur}),t/{fade_dur},if(gt(t,{dur}-{fade_dur}),({dur}-t)/{fade_dur},1))'"
        elif "Static" in anim:
            alpha = "1"
        else:
            alpha = f"'if(lt(t,{fade_dur}),t/{fade_dur},1)'"

        title_filter = (f"drawtext=text='{title}':fontsize={t_size}"
                        f":fontcolor=0x{t_color}:alpha={alpha}"
                        f":x={t_x}:y={t_y}:font={t_font}{t_bold}{shadow}{outline}")

        sub_filter = ""
        if sub.strip():
            sub_filter = (f",drawtext=text='{sub}':fontsize={s_size}"
                          f":fontcolor=0x{s_color}:alpha={alpha}"
                          f":x={s_x}:y={s_y}")

        return title_filter + sub_filter

    def _generate_bumper(self):
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        res_key = self.res_var.get()
        w, h   = RESOLUTIONS[res_key]
        dur    = self.duration_var.get()
        fps    = self.fps_var.get()
        style  = BG_STYLES[self.bg_style_var.get()]

        # Background source
        if style == "solid":
            c = self.bg_color1.lstrip("#")
            bg_input  = ["-f", "lavfi", "-i",
                         f"color=c={c}:size={w}x{h}:rate={fps}:duration={dur}"]
        elif style in ("gradient_h", "gradient_v"):
            # Approximate gradient with two halves
            c1 = self.bg_color1.lstrip("#")
            bg_input = ["-f", "lavfi", "-i",
                        f"color=c={c1}:size={w}x{h}:rate={fps}:duration={dur}"]
        elif style == "black":
            bg_input = ["-f", "lavfi", "-i",
                        f"color=c=black:size={w}x{h}:rate={fps}:duration={dur}"]
        elif style == "custom" and self.bg_custom_path:
            if self.bg_custom_path.lower().endswith((".jpg",".jpeg",".png")):
                bg_input = ["-loop", "1", "-i", self.bg_custom_path,
                            "-t", dur]
            else:
                bg_input = ["-stream_loop", "-1", "-i", self.bg_custom_path,
                            "-t", dur]
        else:
            bg_input = ["-f", "lavfi", "-i",
                        f"color=c=000000:size={w}x{h}:rate={fps}:duration={dur}"]

        text_filter = self._build_text_filters(w, h, float(dur))

        cmd = ([ffmpeg] + bg_input
               + ["-vf", text_filter,
                  "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                  "-t", dur, "-an", "-movflags", "+faststart", out, "-y"])

        self.log(self.console, f"Generating {w}×{h} bumper ({dur}s)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_gen, btn_label=t("intro_maker.generate_button"))

    def _attach(self):
        bumper = self.out_var.get().strip()
        main   = self.main_var.get().strip()
        out    = self.attach_out_var.get().strip()

        if not bumper or not os.path.exists(bumper):
            messagebox.showwarning(t("common.warning"), "Generate the bumper first (Design tab).")
            return
        if not main or not os.path.exists(main):
            messagebox.showwarning(t("common.warning"), "Select the main video to attach to.")
            return
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.attach_out_var.set(out)

        mode   = self.attach_mode_var.get()
        ffmpeg = get_binary_path("ffmpeg.exe")
        tmp    = tempfile.mkdtemp()

        def _work():
            # Re-encode bumper to match main resolution
            # Get main video resolution
            ffprobe = get_binary_path("ffprobe.exe")
            rr = subprocess.run([ffprobe, "-v","error","-show_entries",
                         "stream=width,height","-of","json", main],
                        capture_output=True, text=True,
                        creationflags=CREATE_NO_WINDOW)
            mw, mh = 1920, 1080
            try:
                d = json.loads(rr.stdout)
                s = next(s for s in d["streams"] if s.get("width"))
                mw, mh = s["width"], s["height"]
            except Exception:
                pass

            bumper_matched = os.path.join(tmp, "bumper_matched.mp4")
            self.log(self.attach_console, f"Matching bumper to {mw}×{mh}…")
            r1 = subprocess.run([ffmpeg, "-i", bumper,
                         "-vf", f"scale={mw}:{mh}:force_original_aspect_ratio=decrease,"
                                f"pad={mw}:{mh}:(ow-iw)/2:(oh-ih)/2",
                         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                         "-c:a", "aac", "-b:a", "192k",
                         bumper_matched, "-y"],
                        capture_output=True, creationflags=CREATE_NO_WINDOW)

            # Build concat list
            list_path = os.path.join(tmp, "list.txt")
            if mode == "prepend":
                clips = [bumper_matched, main]
            elif mode == "append":
                clips = [main, bumper_matched]
            else:
                clips = [bumper_matched, main, bumper_matched]

            with open(list_path, "w") as f:
                for c in clips:
                    f.write(f"file '{c}'\n")

            self.log(self.attach_console, t("log.splicer.concatenating"))
            r2 = subprocess.run([ffmpeg, "-f", "concat", "-safe", "0",
                         "-i", list_path, "-c", "copy", "-movflags", "+faststart", out, "-y"],
                        capture_output=True, creationflags=CREATE_NO_WINDOW)

            try: shutil.rmtree(tmp)
            except Exception: pass

            self.after(0, lambda: self.show_result(r2.returncode, out))

        self.run_in_thread(_work)
