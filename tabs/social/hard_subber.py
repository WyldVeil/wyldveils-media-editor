"""
tab_hardsubber.py  ─  Hard-Subber
Burns SRT or ASS/SSA subtitle files into a video as hard-coded subtitles.
Supports styling overrides for SRT files.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


class HardSubberTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.video_path = ""
        self.sub_path   = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="💬  " + t("tab.hard_subber"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("hard_subber.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File pickers
        pick_f = tk.LabelFrame(self, text=t("section.input_files"), padx=15, pady=8)
        pick_f.pack(fill="x", padx=20, pady=8)

        for row, label, attr, ftype in [
            (0, "Video File:", "video_path", [("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", "*.*")]),
            (1, "Subtitle File:", "sub_path", [("Subtitles", "*.srt *.ass *.ssa *.vtt"), ("All", "*.*")]),
        ]:
            tk.Label(pick_f, text=label, font=(UI_FONT, 9, "bold")).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            setattr(self, attr + "_var", var)
            tk.Entry(pick_f, textvariable=var, width=60, relief="flat").grid(row=row, column=1, padx=8)

            def _browse(a=attr, v=var, ft=ftype):
                p = filedialog.askopenfilename(filetypes=ft)
                if p:
                    setattr(self, a, p)
                    v.set(p)
                    if a == "sub_path":
                        ext = os.path.splitext(p)[1].lower()
                        self._on_sub_type(ext)

            tk.Button(pick_f, text=t("btn.browse"), command=_browse, cursor="hand2", relief="flat").grid(row=row, column=2)

        # Style overrides (only for SRT)
        self.style_lf = tk.LabelFrame(self, text=t("hard_subber.style_section"), padx=15, pady=8)
        self.style_lf.pack(fill="x", padx=20, pady=5)

        # Font
        r0 = tk.Frame(self.style_lf); r0.pack(fill="x", pady=3)
        tk.Label(r0, text=t("hard_subber.font_label")).pack(side="left")
        self.font_var = tk.StringVar(value="Arial")
        fonts = ["Arial", "Impact", "Helvetica", t("hard_subber.times_new_roman"),
                 t("hard_subber.courier_new"), "Verdana", t("hard_subber.trebuchet_ms")]
        ttk.Combobox(r0, textvariable=self.font_var, values=fonts, width=18).pack(side="left", padx=4)
        tk.Label(r0, text=t("hard_subber.size_label")).pack(side="left", padx=(12, 0))
        self.fsize_var = tk.StringVar(value="24")
        tk.Entry(r0, textvariable=self.fsize_var, width=5, relief="flat").pack(side="left", padx=4)
        self.bold_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r0, text=t("hard_subber.bold_checkbox"), variable=self.bold_var).pack(side="left", padx=6)

        # Colour
        r1 = tk.Frame(self.style_lf); r1.pack(fill="x", pady=3)
        tk.Label(r1, text=t("hard_subber.text_colour_label")).pack(side="left")
        self.txt_color = "&HFFFFFF&"
        self.txt_color_btn = tk.Button(r1, text=t("hard_subber.white"), bg="#FFFFFF", fg="black",
                                       width=10, command=lambda: self._pick_color("text"))
        self.txt_color_btn.pack(side="left", padx=4)
        tk.Label(r1, text=t("hard_subber.outline_label")).pack(side="left", padx=(12, 0))
        self.out_color = "&H000000&"
        self.out_color_btn = tk.Button(r1, text=t("hard_subber.black"), bg="#000000", fg="white",
                                       width=10, command=lambda: self._pick_color("outline"))
        self.out_color_btn.pack(side="left", padx=4)
        tk.Label(r1, text=t("hard_subber.outline_size_label")).pack(side="left", padx=(12, 0))
        self.outline_var = tk.StringVar(value="2")
        tk.Entry(r1, textvariable=self.outline_var, width=3, relief="flat").pack(side="left", padx=4)

        # Position
        r2 = tk.Frame(self.style_lf); r2.pack(fill="x", pady=3)
        tk.Label(r2, text=t("hard_subber.position_label")).pack(side="left")
        self.pos_var = tk.StringVar(value="Bottom Centre")
        ttk.Combobox(r2, textvariable=self.pos_var,
                     values=[t("hard_subber.hard_subber_bottom_centre"), t("hard_subber.hard_subber_top_centre"), t("hard_subber.hard_subber_middle_centre"),
                              t("hard_subber.hard_subber_bottom_left"), t("hard_subber.hard_subber_bottom_right")], state="readonly", width=18).pack(side="left", padx=4)
        tk.Label(r2, text=t("hard_subber.margin_label")).pack(side="left", padx=(12, 0))
        self.margin_var = tk.StringVar(value="20")
        tk.Entry(r2, textvariable=self.margin_var, width=4, relief="flat").pack(side="left", padx=4)

        self.ass_note = tk.Label(self, text=t("hard_subber.ass_note"),
                                 fg=CLR["fgdim"], font=(UI_FONT, 9, "italic"))

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Quality
        qf = tk.Frame(self); qf.pack()
        tk.Label(qf, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(qf, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(qf, text=t("common.preset")).pack(side="left", padx=(12, 0))
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(qf, textvariable=self.preset_var,
                     values=["ultrafast", "fast", "medium", "slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        self.btn_render = tk.Button(
            self, text=t("hard_subber.burn_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=12)

        cf2 = tk.Frame(self); cf2.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf2, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _on_sub_type(self, ext):
        if ext in (".srt", ".vtt"):
            self.style_lf.pack(fill="x", padx=20, pady=5)
            self.ass_note.pack_forget()
        else:
            self.style_lf.pack_forget()
            self.ass_note.pack(pady=4)

    def _pick_color(self, target):
        from tkinter import colorchooser as cc
        result = cc.askcolor()
        if result[1]:
            hex_color = result[1].lstrip("#")
            # Convert #RRGGBB → &HBBGGRR& (ASS format)
            r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            ass_color = f"&H{b}{g}{r}&"
            if target == "text":
                self.txt_color = ass_color
                self.txt_color_btn.config(bg=result[1], text=f"  {result[1]}")
            else:
                self.out_color = ass_color
                self.out_color_btn.config(bg=result[1], fg="white", text=f"  {result[1]}")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.video_path:
            messagebox.showwarning(t("common.warning"), t("hard_subber.no_video_message"))
            return
        if not self.sub_path:
            messagebox.showwarning(t("common.warning"), t("hard_subber.no_subs_message"))
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        ext = os.path.splitext(self.sub_path)[1].lower()

        if ext in (".ass", ".ssa"):
            # Use ass filter - styling from the file itself
            safe_sub = self.sub_path.replace("\\", "/").replace(":", "\\:")
            vf = f"ass='{safe_sub}'"
        else:
            # Build force_style from UI options
            bold = "1" if self.bold_var.get() else "0"
            pos_map = {
                "Bottom Centre": "2",
                "Top Centre": "8",
                "Middle Centre": "5",
                "Bottom Left": "1",
                "Bottom Right": "3",
            }
            alignment = pos_map.get(self.pos_var.get(), "2")
            margin     = self.margin_var.get()
            style = (f"FontName={self.font_var.get()},"
                     f"FontSize={self.fsize_var.get()},"
                     f"Bold={bold},"
                     f"PrimaryColour={self.txt_color},"
                     f"OutlineColour={self.out_color},"
                     f"Outline={self.outline_var.get()},"
                     f"Alignment={alignment},"
                     f"MarginV={margin}")
            safe_sub = self.sub_path.replace("\\", "/").replace(":", "\\:")
            vf = f"subtitles='{safe_sub}':force_style='{style}'"

        cmd = [ffmpeg, "-i", self.video_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Burning subtitles ({ext}) → {os.path.basename(out)}")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("hard_subber.burn_button"))
