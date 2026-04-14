"""
tab_greenkeyyer.py  ─  Green Screen Keyer
Chroma-key (green/blue screen) with background replacement.
Uses FFmpeg chromakey filter with similarity + blend controls.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


class GreenKeyerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.fg_path   = ""
        self.bg_path   = ""
        self.key_color = "#00FF00"  # default green
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🟩  " + t("tab.green_screen_keyer"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("green_key.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File pickers
        pick = tk.LabelFrame(self, text=t("section.input_files"), padx=15, pady=8)
        pick.pack(fill="x", padx=20, pady=8)

        for row, label, attr, ftypes in [
            (0, t("green_key.foreground_label"), "fg_path",
             [("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", "*.*")]),
            (1, t("green_key.background_label"), "bg_path",
             [("Media", "*.mp4 *.mov *.mkv *.jpg *.jpeg *.png *.webp"), ("All", "*.*")]),
        ]:
            tk.Label(pick, text=label, font=(UI_FONT, 9, "bold")).grid(
                row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(pick, textvariable=var, width=55, relief="flat").grid(row=row, column=1, padx=8)

            def _b(a=attr, v=var, ft=ftypes):
                p = filedialog.askopenfilename(filetypes=ft)
                if p:
                    setattr(self, a, p)
                    v.set(p)
            tk.Button(pick, text=t("btn.browse"), command=_b, cursor="hand2", relief="flat").grid(row=row, column=2)

        # Key colour picker
        key_f = tk.Frame(self); key_f.pack(pady=6)
        tk.Label(key_f, text=t("green_key.key_colour_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.color_preview = tk.Label(key_f, text=t("green_key.green_screen"),
                                       bg="#00FF00", fg="black", width=16)
        self.color_preview.pack(side="left", padx=8)
        tk.Button(key_f, text=t("green_key.change_colour"), command=self._pick_color, cursor="hand2", relief="flat").pack(side="left")

        # Presets
        for name, color in [("🟩 Green", "#00FF00"), ("🟦 Blue", "#0000FF"),
                              ("⬜ White", "#FFFFFF"), ("🔴 Red", "#FF0000")]:
            tk.Button(key_f, text=name, width=8, bg=CLR["panel"], fg=CLR["fg"],
                      command=lambda c=color: self._set_color(c)).pack(side="left", padx=3)

        # Options
        opts = tk.LabelFrame(self, text=f"  {t('green_key.key_options_section')}  ", padx=15, pady=10)
        opts.pack(fill="x", padx=20, pady=6)

        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("green_key.similarity_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.sim_var = tk.DoubleVar(value=0.10)
        tk.Scale(r0, variable=self.sim_var, from_=0.01, to=0.5,
                 resolution=0.01, orient="horizontal", length=250).pack(side="left", padx=6)
        tk.Label(r0, text=t("green_key.similarity_hint"),
                 fg=CLR["fgdim"]).pack(side="left", padx=6)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("green_key.blend_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.blend_var = tk.DoubleVar(value=0.10)
        tk.Scale(r1, variable=self.blend_var, from_=0.0, to=0.5,
                 resolution=0.01, orient="horizontal", length=250).pack(side="left", padx=6)
        tk.Label(r1, text=t("green_key.blend_hint"),
                 fg=CLR["fgdim"]).pack(side="left", padx=6)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(r2, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        self.bg_loop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text=t("green_key.loop_bg_checkbox"),
                       variable=self.bg_loop_var).pack(side="left", padx=20)

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("green_key.composite_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _pick_color(self):
        result = colorchooser.askcolor()
        if result[1]:
            self._set_color(result[1])

    def _set_color(self, hex_color):
        self.key_color = hex_color
        self.color_preview.config(bg=hex_color,
                                   text=f"  {hex_color.upper()}  ",
                                   fg="black" if hex_color.upper() in ("#FFFFFF", "#00FF00") else "white")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _render(self):
        if not self.fg_path:
            messagebox.showwarning(t("green_key.no_foreground_title"), t("green_key.no_foreground_message"))
            return
        if not self.bg_path:
            messagebox.showwarning(t("green_key.no_background_title"), t("green_key.no_background_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        sim    = self.sim_var.get()
        blend  = self.blend_var.get()
        color  = self.key_color
        is_img = self.bg_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))

        if is_img:
            # Image background: loop it as video
            bg_input = ["-loop", "1", "-i", self.bg_path]
        elif self.bg_loop_var.get():
            bg_input = ["-stream_loop", "-1", "-i", self.bg_path]
        else:
            bg_input = ["-i", self.bg_path]

        # Filter: key FG, scale BG to match FG dimensions, then composite
        filter_complex = (
            f"[0:v]chromakey={color}:{sim:.3f}:{blend:.3f}[fg_keyed];"
            f"[1:v][fg_keyed]scale2ref[bg_scaled][fg_ref];"
            f"[bg_scaled][fg_ref]overlay=shortest=1[out]"
        )

        cmd = ([ffmpeg, "-i", self.fg_path]
               + bg_input
               + ["-filter_complex", filter_complex,
                  "-map", "[out]",
                  "-map", "0:a?",
                  "-c:v", "libx264", "-crf", self.crf_var.get(),
                  "-preset", "fast", "-c:a", "aac", "-b:a", "192k",
                  "-shortest", "-movflags", "+faststart", out, "-y"])

        self.log(self.console, f"Keying colour {color} (sim={sim:.2f}, blend={blend:.2f})")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("green_key.composite_button"))
