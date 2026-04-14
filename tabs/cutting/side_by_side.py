"""
tab_sidebyside.py  ─  Side-by-Side / Before-After
Create split-screen comparison videos:
  • Before / After colour grade
  • A/B codec comparison
  • Reaction video (two faces side by side)
  • Tutorial split (screen + presenter)
  • Vertical split with animated divider

Layouts: horizontal split, vertical split, grid (2×2).
Optional: animated wipe divider, labels, audio source selection.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


LAYOUTS = {
    t("side_by_side.horizontal_split"):    "hstack",
    t("side_by_side.vertical_split"):    "vstack",
    t("side_by_side.grid_layout"):            "grid",
    t("side_by_side.wipe_layout"):"wipe",
}

AUDIO_SOURCES = {
    t("side_by_side.audio_left_top"):    "0",
    t("side_by_side.audio_right_bottom"):"1",
    t("side_by_side.audio_mix"):            "mix",
    t("side_by_side.audio_none"):            "none",
}


class SideBySideTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.clips = ["", "", "", ""]   # up to 4
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="⬛⬜  " + t("tab.side_by_side"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("side_by_side.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Input clips ───────────────────────────────────────────────────
        inp_lf = tk.LabelFrame(self, text=t("section.input_clips"), padx=14, pady=10)
        inp_lf.pack(fill="x", padx=16, pady=8)

        self.clip_vars   = []
        self.clip_labels = [t("side_by_side.left_top"), t("side_by_side.right_bottom"),
                             t("side_by_side.top_right_grid"), t("side_by_side.bottom_right_grid")]
        self.clip_rows   = []   # frames to show/hide

        for i in range(4):
            row = tk.Frame(inp_lf)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{self.clip_labels[i]}:",
                     width=22, anchor="e").pack(side="left")
            var = tk.StringVar()
            self.clip_vars.append(var)
            tk.Entry(row, textvariable=var, width=55, relief="flat").pack(side="left", padx=6)

            def _b(idx=i, v=var):
                p = filedialog.askopenfilename(
                    filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"),
                               ("All", t("ducker.item_2"))])
                if p:
                    self.clips[idx] = p
                    v.set(p)
            tk.Button(row, text="…", width=2, command=_b, cursor="hand2", relief="flat").pack(side="left")
            self.clip_rows.append(row)

        # Initially hide grid-only clips
        for row in self.clip_rows[2:]:
            row.pack_forget()

        # ── Layout ────────────────────────────────────────────────────────
        lay_lf = tk.LabelFrame(self, text=f"  {t('side_by_side.layout_section')}  ", padx=14, pady=10)
        lay_lf.pack(fill="x", padx=16, pady=4)

        lay_row = tk.Frame(lay_lf); lay_row.pack(fill="x")
        tk.Label(lay_row, text=t("side_by_side.layout_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.layout_var = tk.StringVar(value=list(LAYOUTS.keys())[0])
        lay_cb = ttk.Combobox(lay_row, textvariable=self.layout_var,
                               values=list(LAYOUTS.keys()),
                               state="readonly", width=40)
        lay_cb.pack(side="left", padx=8)
        lay_cb.bind("<<ComboboxSelected>>", self._on_layout_change)

        # ── Options ───────────────────────────────────────────────────────
        opts = tk.LabelFrame(self, text=t("section.options"), padx=14, pady=10)
        opts.pack(fill="x", padx=16, pady=4)

        # Two-column
        oc = tk.Frame(opts); oc.pack(fill="x")
        ol = tk.Frame(oc); ol.pack(side="left", fill="both", expand=True, padx=(0,8))
        or_ = tk.Frame(oc); or_.pack(side="left", fill="both", expand=True)

        # Resolution
        r0 = tk.Frame(ol); r0.pack(fill="x", pady=3)
        tk.Label(r0, text=t("side_by_side.output_resolution_label"), font=(UI_FONT, 9, "bold")).pack(side="left")
        self.res_var = tk.StringVar(value="1920×1080")
        ttk.Combobox(r0, textvariable=self.res_var,
                     values=["3840×2160", "1920×1080", "1280×720", "854×480",
                              t("side_by_side.side_by_side_match_left_clip")],
                     state="readonly", width=16).pack(side="left", padx=6)

        # Labels
        r1 = tk.Frame(ol); r1.pack(fill="x", pady=3)
        self.labels_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r1, text=t("side_by_side.draw_labels_checkbox"),
                       variable=self.labels_var,
                       command=self._toggle_labels).pack(side="left")

        self.labels_f = tk.Frame(ol)
        self.labels_f.pack(fill="x")
        self.label_vars = []
        for i, default in enumerate(["Before", "After", "Clip C", "Clip D"]):
            lf = tk.Frame(self.labels_f)
            lf.pack(fill="x", pady=1)
            tk.Label(lf, text=f"Label {i+1}:", width=8).pack(side="left")
            var = tk.StringVar(value=default)
            self.label_vars.append(var)
            tk.Entry(lf, textvariable=var, width=16, relief="flat").pack(side="left", padx=4)

        # Label style
        ls = tk.Frame(ol); ls.pack(fill="x", pady=2)
        tk.Label(ls, text=t("side_by_side.label_font_size_label")).pack(side="left")
        self.label_size_var = tk.StringVar(value="36")
        tk.Entry(ls, textvariable=self.label_size_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(ls, text=f"  {t('side_by_side.label_position_label')}").pack(side="left")
        self.label_pos_var = tk.StringVar(value="Top-Left")
        ttk.Combobox(ls, textvariable=self.label_pos_var,
                     values=["Top-Left", "Bottom-Left", "Top-Centre"],
                     state="readonly", width=12).pack(side="left", padx=4)

        # Wipe options (only for wipe layout)
        self.wipe_lf = tk.LabelFrame(or_, text=f"  {t('side_by_side.wipe_section')}  ", padx=12, pady=6)
        self.wipe_speed_var = tk.StringVar(value="0")
        tk.Label(self.wipe_lf, text=t("side_by_side.wipe_speed_label")).pack(anchor="w")
        tk.Scale(self.wipe_lf, variable=self.wipe_speed_var,
                 from_=0, to=100, orient="horizontal", length=200).pack()
        self.wipe_pos_var = tk.StringVar(value="50")
        tk.Label(self.wipe_lf, text=t("side_by_side.static_position_label")).pack(anchor="w")
        tk.Entry(self.wipe_lf, textvariable=self.wipe_pos_var, width=5, relief="flat").pack(anchor="w")
        self.divider_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.wipe_lf, text=t("side_by_side.draw_divider_checkbox"),
                       variable=self.divider_var).pack(anchor="w")

        # Audio
        au = tk.Frame(or_); au.pack(fill="x", pady=4)
        tk.Label(au, text=t("side_by_side.audio_source_label"), font=(UI_FONT, 9, "bold")).pack(side="left")
        self.audio_var = tk.StringVar(value=list(AUDIO_SOURCES.keys())[0])
        ttk.Combobox(au, textvariable=self.audio_var,
                     values=list(AUDIO_SOURCES.keys()),
                     state="readonly", width=22).pack(side="left", padx=6)

        # Quality
        qu = tk.Frame(or_); qu.pack(fill="x", pady=4)
        tk.Label(qu, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(qu, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(qu, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(qu, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # Loop & speed
        ls_lf = tk.LabelFrame(or_, text=f"  {t('side_by_side.sync_speed_section')}  ", padx=12, pady=8)
        ls_lf.pack(fill="x", pady=4)

        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ls_lf, text=t("side_by_side.loop_shorter_checkbox"),
                       variable=self.loop_var, font=(UI_FONT, 10)).pack(anchor="w")
        tk.Label(ls_lf, text=t("side_by_side.loops_the_shorter_clip_until_the_longer_finishes"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

        sp0 = tk.Frame(ls_lf); sp0.pack(fill="x", pady=(6,2))
        tk.Label(sp0, text=t("side_by_side.left_top_video_speed"), width=22, anchor="w").pack(side="left")
        self.speed_l_var = tk.StringVar(value="1.0")
        ttk.Combobox(sp0, textvariable=self.speed_l_var,
                     values=["0.25","0.5","0.75","1.0","1.25","1.5","2.0"],
                     state="normal", width=6).pack(side="left", padx=4)
        tk.Label(sp0, text=t("side_by_side.1_0_normal"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left")

        sp1 = tk.Frame(ls_lf); sp1.pack(fill="x", pady=2)
        tk.Label(sp1, text=t("side_by_side.right_bottom_video_speed"), width=22, anchor="w").pack(side="left")
        self.speed_r_var = tk.StringVar(value="1.0")
        ttk.Combobox(sp1, textvariable=self.speed_r_var,
                     values=["0.25","0.5","0.75","1.0","1.25","1.5","2.0"],
                     state="normal", width=6).pack(side="left", padx=4)
        tk.Label(sp1, text=t("side_by_side.e_g_0_5_half_speed_slo_mo"), fg=CLR["fgdim"],
                 font=(UI_FONT, 8)).pack(side="left")

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=12, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("side_by_side.render_button"),
            font=(UI_FONT, 12, "bold"), bg="#37474F", fg="white",
            height=2, width=24, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_layout_change()

    # ─────────────────────────────────────────────────────────────────────
    def _on_layout_change(self, *_):
        layout = LAYOUTS[self.layout_var.get()]
        is_grid = layout == "grid"
        is_wipe = layout == "wipe"
        for row in self.clip_rows[2:]:
            if is_grid:
                row.pack(fill="x", pady=2)
            else:
                row.pack_forget()
        if is_wipe:
            self.wipe_lf.pack(fill="x", pady=4)
        else:
            self.wipe_lf.pack_forget()

    def _toggle_labels(self):
        if self.labels_var.get():
            self.labels_f.pack(fill="x")
        else:
            self.labels_f.pack_forget()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _get_clips(self):
        layout = LAYOUTS[self.layout_var.get()]
        if layout == "grid":
            clips = [c for c in self.clips if c and os.path.exists(c)]
            if len(clips) < 2:
                messagebox.showwarning(t("side_by_side.need_clips_title"), t("side_by_side.need_clips_message"))
                return None
            return clips[:4]
        else:
            a = self.clips[0]; b = self.clips[1]
            if not a or not os.path.exists(a):
                messagebox.showwarning(t("side_by_side.missing_clip_title"), t("side_by_side.missing_first_clip"))
                return None
            if not b or not os.path.exists(b):
                messagebox.showwarning(t("side_by_side.missing_clip_title"), t("side_by_side.missing_second_clip"))
                return None
            return [a, b]

    def _get_res(self):
        v = self.res_var.get()
        if "×" in v and "Match" not in v:
            parts = v.split("×")
            return int(parts[0]), int(parts[1])
        return None, None

    def _build_filter(self, clips):
        """Build filter_complex for chosen layout."""
        layout = LAYOUTS[self.layout_var.get()]
        n      = len(clips)
        w, h   = self._get_res()

        # Normalise all clips to same resolution
        norm_w = w or 960
        norm_h = h or 540
        if layout in ("hstack", "wipe"):
            norm_w = (w or 1920) // 2
            norm_h = h or 1080
        elif layout == "vstack":
            norm_w = w or 1920
            norm_h = (h or 1080) // 2

        scale = f"scale={norm_w}:{norm_h}:force_original_aspect_ratio=decrease,pad={norm_w}:{norm_h}:(ow-iw)/2:(oh-ih)/2"

        # Speed factors per clip
        try:
            spd_l = float(getattr(self, "speed_l_var", tk.StringVar(value="1.0")).get())
        except (ValueError, AttributeError): spd_l = 1.0
        try:
            spd_r = float(getattr(self, "speed_r_var", tk.StringVar(value="1.0")).get())
        except (ValueError, AttributeError): spd_r = 1.0

        speed_factors = [spd_l, spd_r, 1.0, 1.0]  # up to 4 clips

        def _apply_speed(clip_idx):
            s = speed_factors[clip_idx] if clip_idx < len(speed_factors) else 1.0
            if abs(s - 1.0) < 0.01:
                return scale
            # setpts=0.5*PTS = 2x speed; setpts=2*PTS = 0.5x speed
            pts = f"{1.0/s:.4f}*PTS"
            atempo = s
            return f"{scale},setpts={pts}"

        loop_shorter = getattr(self, "loop_var", tk.BooleanVar(value=False)).get()
        prep_parts = []
        for i in range(n):
            sf = _apply_speed(i)
            if loop_shorter and n == 2:
                # loop=999 lets FFmpeg loop; -shortest will cut at the longer
                prep_parts.append(f"[{i}:v]loop=999:size=32767:start=0,{sf}[c{i}]")
            else:
                prep_parts.append(f"[{i}:v]{sf}[c{i}]")
        prep = ";".join(prep_parts)

        # Labels
        label_filters = []
        if self.labels_var.get():
            pos_lbl = self.label_pos_var.get()
            lbl_size = self.label_size_var.get()
            for i, lv in enumerate(self.label_vars[:n]):
                lbl = lv.get().replace("'","")
                if pos_lbl == "Top-Left":
                    lx, ly = "20", "20"
                elif pos_lbl == "Bottom-Left":
                    lx, ly = "20", f"h-text_h-20"
                else:
                    lx, ly = "(w-text_w)/2", "20"
                label_filters.append(
                    f"[c{i}]drawtext=text='{lbl}':fontsize={lbl_size}:"
                    f"fontcolor=white:box=1:boxcolor=black@0.6:"
                    f"x={lx}:y={ly}[lc{i}]")
            labelled = [f"[lc{i}]" for i in range(n)]
        else:
            labelled = [f"[c{i}]" for i in range(n)]

        if layout == "hstack":
            stack = f"{labelled[0]}{labelled[1]}hstack=inputs=2[out]"
        elif layout == "vstack":
            stack = f"{labelled[0]}{labelled[1]}vstack=inputs=2[out]"
        elif layout == "grid":
            # 2×2 grid
            top    = f"{labelled[0]}{labelled[1]}hstack=inputs=2[top]"
            bottom = f"{labelled[2] if n>2 else labelled[0]}{labelled[3] if n>3 else labelled[1]}hstack=inputs=2[bot]"
            stack  = f"{top};{bottom};[top][bot]vstack=inputs=2[out]"
        else:  # wipe
            pos_pct = int(self.wipe_pos_var.get() or "50")
            wipe_w  = norm_w * pos_pct // 100
            # Overlay left clip cropped to wipe_w on right clip
            stack = (f"{labelled[0]}crop={wipe_w}:ih:0:0[left_crop];"
                     f"{labelled[1]}[left_crop]overlay=0:0[out_raw];"
                     f"[out_raw]drawbox={wipe_w}:0:4:ih:white:fill[out]"
                     if self.divider_var.get() else
                     f"{labelled[0]}crop={wipe_w}:ih:0:0[left_crop];"
                     f"{labelled[1]}[left_crop]overlay=0:0[out]")

        label_chain = ";".join(label_filters) + ";" if label_filters else ""
        fc = prep + ";" + label_chain + stack
        return fc

    def _preview(self):
        clips = self._get_clips()
        if not clips: return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay = get_binary_path("ffplay.exe")
        fc = self._build_filter(clips)
        cmd = [ffplay]
        for c in clips:
            cmd += ["-i", c]
        cmd += ["-filter_complex", fc, "-map", "[out]",
                "-window_title", "Split Preview", "-x", "960", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        clips = self._get_clips()
        if not clips: return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")
        fc = self._build_filter(clips)

        # Audio
        audio_key = self.audio_var.get()
        audio_src = AUDIO_SOURCES[audio_key]
        if audio_src == "none":
            audio_args = ["-an"]
        elif audio_src == "mix":
            n = len(clips)
            mix = "".join(f"[{i}:a]" for i in range(n)) + f"amix=inputs={n}[aout]"
            fc  = fc + ";" + mix
            audio_args = ["-map", "[aout]"]
        else:
            audio_args = ["-map", f"{audio_src}:a?"]

        cmd = [ffmpeg]
        for c in clips:
            cmd += ["-i", c]
        cmd += ["-filter_complex", fc,
                "-map", "[out]"] + audio_args
        cmd += ["-c:v", "libx264", "-crf", self.crf_var.get(),
                "-preset", self.preset_var.get(),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", out, "-y"]

        self.log(self.console, f"Rendering {self.layout_var.get().split('(')[0].strip()}…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("side_by_side.render_button"))
