"""
tab_videocollage.py  ─  Video Collage / Grid Layout

Combine 2-9 videos into a single grid layout (2×1, 2×2, 3×3, etc.)
playing simultaneously.  Popular for:
  • Multi-cam gameplay / IRL streams
  • Before/after comparisons
  • Reaction compilations
  • "Every angle" moments

Uses FFmpeg's xstack filter for precise grid positioning.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (    get_binary_path, get_video_duration, CREATE_NO_WINDOW,
)
from core.i18n import t


def _fmt(seconds):
    m, s = divmod(max(0, seconds), 60)
    return f"{int(m):02d}:{s:05.2f}"


LAYOUTS = {
    t("collage.2_1_side_by_side"):    {"cols": 2, "rows": 1, "slots": 2},
    "1×2 (Stacked)":         {"cols": 1, "rows": 2, "slots": 2},
    "2×2 (Quad Grid)":       {"cols": 2, "rows": 2, "slots": 4},
    "3×1 (Triple Wide)":     {"cols": 3, "rows": 1, "slots": 3},
    "1×3 (Triple Tall)":     {"cols": 1, "rows": 3, "slots": 3},
    "3×2 (Six Pack)":        {"cols": 3, "rows": 2, "slots": 6},
    "3×3 (Nine Grid)":       {"cols": 3, "rows": 3, "slots": 9},
    "2×1 + 1 (PiP Style)":  {"cols": 2, "rows": 2, "slots": 3, "custom": "pip"},
}


class VideoCollageTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._slots = []  # list of {path, name, duration}
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.video_collage"),
                         t("collage.subtitle"),
                         icon="🎞")

        # ── Layout picker ─────────────────────────────────────────────────
        layout_lf = tk.LabelFrame(self, text=f"  {t('collage.grid_layout_section')}  ", padx=15, pady=10,
                                  font=(UI_FONT, 9, "bold"))
        layout_lf.pack(fill="x", padx=20, pady=(10, 6))

        self._layout_var = tk.StringVar(value="2×2 (Quad Grid)")
        lr = tk.Frame(layout_lf)
        lr.pack(fill="x")
        for layout_name in LAYOUTS:
            tk.Radiobutton(lr, text=layout_name, variable=self._layout_var,
                           value=layout_name, font=(UI_FONT, 10),
                           command=self._on_layout_change).pack(anchor="w", pady=1)

        # ── Grid preview canvas ───────────────────────────────────────────
        self._grid_canvas = tk.Canvas(layout_lf, bg=CLR["console_bg"],
                                      width=280, height=160, highlightthickness=0)
        self._grid_canvas.pack(side="right", padx=10, pady=4)

        # ── Video slots ───────────────────────────────────────────────────
        slots_lf = tk.LabelFrame(self, text=f"  {t('collage.video_slots_section')}  ", padx=15, pady=8,
                                 font=(UI_FONT, 9, "bold"))
        slots_lf.pack(fill="both", expand=True, padx=20, pady=6)

        # Toolbar
        stb = tk.Frame(slots_lf, bg=CLR["panel"])
        stb.pack(fill="x", pady=(0, 6))
        tk.Button(stb, text="➕ " + t("collage.add_videos_button"), bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 10, "bold"), cursor="hand2", relief="flat",
                  command=self._add_videos).pack(side="left", padx=4)
        tk.Button(stb, text="🗑 " + t("collage.remove_button"), bg=CLR["red"], fg="white",
                  font=(UI_FONT, 9), cursor="hand2", relief="flat",
                  command=self._remove_selected).pack(side="left", padx=4)
        tk.Button(stb, text="⬆", bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 11, "bold"), cursor="hand2", relief="flat", width=3,
                  command=self._move_up).pack(side="left", padx=2)
        tk.Button(stb, text="⬇", bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 11, "bold"), cursor="hand2", relief="flat", width=3,
                  command=self._move_down).pack(side="left", padx=2)
        tk.Button(stb, text="🗑 " + t("collage.clear_button"), bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 9), cursor="hand2", relief="flat",
                  command=self._clear_all).pack(side="left", padx=8)

        self._slot_count_lbl = tk.Label(stb, text=t("collage.0_videos_loaded"),
                                        bg=CLR["panel"], fg=CLR["fgdim"],
                                        font=(UI_FONT, 10))
        self._slot_count_lbl.pack(side="right", padx=8)

        # Listbox
        list_f = tk.Frame(slots_lf)
        list_f.pack(fill="both", expand=True)
        self._slot_list = tk.Listbox(
            list_f, bg=CLR["console_bg"], fg=CLR["console_fg"],
            font=(MONO_FONT, 9), selectmode="browse", height=5,
            relief="flat", bd=0)
        lsb = ttk.Scrollbar(list_f, command=self._slot_list.yview)
        self._slot_list.config(yscrollcommand=lsb.set)
        self._slot_list.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

        # ── Output settings ───────────────────────────────────────────────
        out_lf = tk.LabelFrame(self, text=f"  {t('collage.output_settings_section')}  ", padx=15, pady=8,
                               font=(UI_FONT, 9, "bold"))
        out_lf.pack(fill="x", padx=20, pady=6)

        or1 = tk.Frame(out_lf)
        or1.pack(fill="x", pady=3)
        tk.Label(or1, text=t("collage.output_resolution_label"), font=(UI_FONT, 10)).pack(side="left")
        self._out_w = tk.StringVar(value="1920")
        tk.Entry(or1, textvariable=self._out_w, width=6, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(or1, text="×", font=(UI_FONT, 10)).pack(side="left")
        self._out_h = tk.StringVar(value="1080")
        tk.Entry(or1, textvariable=self._out_h, width=6, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)

        # Quick presets
        for w, h, lbl in [(1920, 1080, "1080p"), (1280, 720, "720p"),
                           (3840, 2160, "4K"), (1080, 1920, "9:16")]:
            tk.Button(or1, text=lbl, bg=CLR["panel"], fg=CLR["fg"],
                      font=(UI_FONT, 9), cursor="hand2", width=5,
                      command=lambda _w=w, _h=h: (self._out_w.set(str(_w)),
                                                   self._out_h.set(str(_h)))
                      ).pack(side="left", padx=2)

        or2 = tk.Frame(out_lf)
        or2.pack(fill="x", pady=3)
        tk.Label(or2, text=t("common.crf"), font=(UI_FONT, 10)).pack(side="left")
        self._crf_var = tk.StringVar(value="18")
        tk.Entry(or2, textvariable=self._crf_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=6)

        tk.Label(or2, text=t("collage.grid_padding_label"), font=(UI_FONT, 10)).pack(side="left", padx=(16, 0))
        self._pad_var = tk.StringVar(value="4")
        tk.Entry(or2, textvariable=self._pad_var, width=4, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=4)
        tk.Label(or2, text=t("collage.px_label"), fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")

        tk.Label(or2, text="  " + t("collage.bg_color_label"), font=(UI_FONT, 10)).pack(side="left", padx=(12, 0))
        self._bg_color = tk.StringVar(value="black")
        ttk.Combobox(or2, textvariable=self._bg_color, width=8,
                     values=["black", "white", "gray", t("collage.collage_1e1e1e")],
                     state="readonly").pack(side="left", padx=4)

        self._duration_mode = tk.StringVar(value="shortest")
        or3 = tk.Frame(out_lf)
        or3.pack(fill="x", pady=3)
        tk.Label(or3, text=t("collage.duration_section"), font=(UI_FONT, 10)).pack(side="left")
        tk.Radiobutton(or3, text=t("collage.shortest_option"), variable=self._duration_mode,
                       value="shortest", font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Radiobutton(or3, text=t("collage.longest_option"),
                       variable=self._duration_mode, value="longest",
                       font=(UI_FONT, 10)).pack(side="left", padx=8)

        # ── Output file ───────────────────────────────────────────────────
        of = tk.Frame(self)
        of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=55, relief="flat",
                 font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2",
                  relief="flat", font=(UI_FONT, 9)).pack(side="left")

        # ── Run ───────────────────────────────────────────────────────────
        bf = tk.Frame(self)
        bf.pack(pady=8)
        self._btn_run = tk.Button(
            bf, text=t("collage.build_collage"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=26,
            cursor="hand2", command=self._render)
        self._btn_run.pack()

        # ── Console ───────────────────────────────────────────────────────
        cf = tk.Frame(self)
        cf.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_layout_change()

    # ── Layout change → redraw grid preview ───────────────────────────
    def _on_layout_change(self):
        self._draw_grid_preview()

    def _draw_grid_preview(self):
        c = self._grid_canvas
        c.delete("all")
        cw, ch = 280, 160

        layout_name = self._layout_var.get()
        info = LAYOUTS.get(layout_name, {"cols": 2, "rows": 2, "slots": 4})
        cols, rows = info["cols"], info["rows"]
        pad = 4
        cell_w = (cw - pad * (cols + 1)) // cols
        cell_h = (ch - pad * (rows + 1)) // rows

        colors = [CLR["accent"], CLR["green"], CLR["orange"], CLR["pink"],
                  "#9C27B0", "#00BCD4", "#FF5722", "#8BC34A", "#FFEB3B"]

        slot = 0
        for r in range(rows):
            for col in range(cols):
                if slot >= info["slots"]:
                    break
                x1 = pad + col * (cell_w + pad)
                y1 = pad + r * (cell_h + pad)
                x2 = x1 + cell_w
                y2 = y1 + cell_h
                color = colors[slot % len(colors)]
                c.create_rectangle(x1, y1, x2, y2, fill=color, outline="#333333")
                # Label
                label = f"#{slot + 1}"
                if slot < len(self._slots):
                    label = self._slots[slot]["name"][:8]
                c.create_text((x1 + x2) // 2, (y1 + y2) // 2, text=label,
                              fill="white", font=(UI_FONT, 8, "bold"))
                slot += 1

    # ── Slot management ───────────────────────────────────────────────
    def _add_videos(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                       ("All", t("ducker.item_2"))])
        for p in paths:
            dur = get_video_duration(p)
            self._slots.append({
                "path": p,
                "name": os.path.basename(p),
                "duration": dur,
            })
        self._refresh_list()

    def _remove_selected(self):
        sel = self._slot_list.curselection()
        if sel:
            self._slots.pop(sel[0])
            self._refresh_list()

    def _move_up(self):
        sel = self._slot_list.curselection()
        if sel and sel[0] > 0:
            i = sel[0]
            self._slots[i - 1], self._slots[i] = self._slots[i], self._slots[i - 1]
            self._refresh_list()
            self._slot_list.selection_set(i - 1)

    def _move_down(self):
        sel = self._slot_list.curselection()
        if sel and sel[0] < len(self._slots) - 1:
            i = sel[0]
            self._slots[i + 1], self._slots[i] = self._slots[i], self._slots[i + 1]
            self._refresh_list()
            self._slot_list.selection_set(i + 1)

    def _clear_all(self):
        self._slots.clear()
        self._refresh_list()

    def _refresh_list(self):
        self._slot_list.delete(0, "end")
        for i, s in enumerate(self._slots):
            self._slot_list.insert("end",
                f"  #{i + 1}   {s['name']:<40s}  {_fmt(s['duration'])}")
        self._slot_count_lbl.config(text=f"{len(self._slots)} videos loaded")
        self._draw_grid_preview()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self._out_var.set(p)

    # ── Render ────────────────────────────────────────────────────────
    def _render(self):
        layout_name = self._layout_var.get()
        info = LAYOUTS.get(layout_name, {"cols": 2, "rows": 2, "slots": 4})
        needed = info["slots"]

        if len(self._slots) < needed:
            messagebox.showwarning(t("collage.not_enough_title"),
                f"This layout needs {needed} videos. "
                f"You have {len(self._slots)}.")
            return

        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self._out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg")
        cols, rows = info["cols"], info["rows"]

        try:
            total_w = int(self._out_w.get())
            total_h = int(self._out_h.get())
            pad = int(self._pad_var.get())
        except ValueError:
            messagebox.showerror(t("common.error"), "Check resolution/padding values.")
            return

        crf = self._crf_var.get()
        bg = self._bg_color.get()

        # Cell dimensions
        cell_w = (total_w - pad * (cols + 1)) // cols
        cell_h = (total_h - pad * (rows + 1)) // rows

        # Build FFmpeg command
        cmd = []
        for i in range(needed):
            cmd += ["-i", self._slots[i]["path"]]

        # Build filter_complex
        # 1. Scale each input to cell size
        fc_parts = []
        for i in range(needed):
            fc_parts.append(
                f"[{i}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
                f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:{bg},"
                f"setsar=1[v{i}]")

        # 2. Build xstack layout string
        layout_strs = []
        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= needed:
                    break
                x = pad + c * (cell_w + pad)
                y = pad + r * (cell_h + pad)
                layout_strs.append(f"{x}_{y}")
                idx += 1

        inputs_str = "".join(f"[v{i}]" for i in range(needed))
        layout_str = "|".join(layout_strs)

        fc_parts.append(
            f"{inputs_str}xstack=inputs={needed}:layout={layout_str}:fill={bg}[vout]"
        )

        # Scale to final output size
        fc_parts.append(
            f"[vout]scale={total_w}:{total_h}:force_original_aspect_ratio=decrease,"
            f"pad={total_w}:{total_h}:(ow-iw)/2:(oh-ih)/2:{bg}[final]"
        )

        fc = ";".join(fc_parts)

        shortest = "-shortest" if self._duration_mode.get() == "shortest" else ""

        full_cmd = [ffmpeg] + cmd + [
            "-filter_complex", fc,
            "-map", "[final]",
            "-map", "0:a?",
            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
        ]
        if shortest:
            full_cmd.append("-shortest")
        full_cmd += [out, "-y"]

        self.log(self.console, f"Building {cols}×{rows} collage ({cell_w}×{cell_h} per cell)…")
        self.run_ffmpeg(full_cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_run, btn_label="🎞  BUILD COLLAGE")
