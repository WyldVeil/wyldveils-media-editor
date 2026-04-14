"""
tab_crossfader.py  ─  Crossfader
Join multiple video clips with smooth transitions (xfade + acrossfade).

Encoding modes
──────────────
• Standard  - re-encodes every frame. Simple, always works.
• Fast       - stream-copies the untouched middle of each clip (instant),
               re-encodes ONLY the T-second overlap windows, then
               concatenates. Audio is intelligently matched to the first 
               clip's codec to preserve maximum original quality.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import json
import threading
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import (
    detect_gpu, get_binary_path, CREATE_NO_WINDOW,
    get_latest_online_version, get_local_version,
    download_and_extract_ffmpeg,
)
from core.i18n import t

# ── Transition catalogue ──────────────────────────────────────────────────
TRANSITIONS = [
    "fade", "fadeblack", "fadewhite", "fadegrays",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "circleopen", "circleclose",
    "dissolve", "pixelize", "radial",
    "smoothleft", "smoothright", "hblur",
]
TRANS_DEFAULT = "fade"

AUDIO_CURVES = [
    "tri", "qsin", "hsin", "esinc", "log", "ipar", "qua", "cub", "squ", "cbr"
]

MAX_CLIPS = 10


class CrossfaderTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)

        self.current_mode   = detect_gpu()
        self.clip_rows      = []   # list of dicts: {frame, var, lbl, trans_var}
        self.clip_data      = []   # ffprobe metadata cache

        self.quality_var    = tk.StringVar(value="High")
        self.audio_var      = tk.StringVar(value="Normal Audio")
        self.audio_curve_var= tk.StringVar(value="tri")
        self.bit_depth_var  = tk.StringVar(value="8-bit")
        self.trans_dur_var  = tk.StringVar(value="2")
        self.trans_type_var = tk.StringVar(value=TRANS_DEFAULT)
        self.per_clip_trans = tk.BooleanVar(value=False)
        self.encode_mode    = tk.StringVar(value="fast")

        self._build_ui()

    # ── Empty metadata template ───────────────────────────────────────────
    @staticmethod
    def _empty_meta():
        return {"path": "", "dur": 0, "fps": 60, "w": 1920,
                "h": 1080, "size": 0, "bit_depth": 8, "has_audio": False,
                "a_codec": ""}

    # ─────────────────────────────────────────────────────────────────────
    #  UI construction
    # ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CLR.get("panel", "#222222"))
        hdr.pack(fill="x")
        tk.Label(hdr, text="✦  " + t("tab.crossfader"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR.get("panel", "#222222"), fg=CLR.get("accent", "#0078D7")).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("crossfader.join_clips_with_smooth_transitions"),
                 bg=CLR.get("panel", "#222222"), fg=CLR.get("fgdim", "#888888")).pack(side="left")

        # ── Scrollable body ───────────────────────────────────────────────
        body_canvas = tk.Canvas(self, highlightthickness=0)
        body_sb     = ttk.Scrollbar(self, orient="vertical",
                                    command=body_canvas.yview)
        self._inner = tk.Frame(body_canvas)
        body_canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: body_canvas.configure(
                             scrollregion=body_canvas.bbox("all")))
        body_canvas.configure(yscrollcommand=body_sb.set)
        body_sb.pack(side="right", fill="y")
        body_canvas.pack(side="left", fill="both", expand=True)

        self._build_clips_section(self._inner)
        self._build_transition_section(self._inner)
        self._build_encoding_section(self._inner)
        self._build_output_section(self._inner)
        self._build_render_section(self._inner)

    # ── Clips section ─────────────────────────────────────────────────────
    def _build_clips_section(self, parent):
        lf = tk.LabelFrame(parent, text=" 🎬  " + t("section.clips"),
                            padx=10, pady=8)
        lf.pack(fill="x", padx=16, pady=8)

        # Column headers
        hdr = tk.Frame(lf); hdr.pack(fill="x", pady=(0, 4))
        for txt, w in [("#", 3), ("File", 55), ("Metadata", 38),
                        ("Transition ↓", 16), ("", 14)]:
            tk.Label(hdr, text=txt, width=w, font=(UI_FONT, 8, "bold"),
                     fg=CLR.get("fgdim", "#888888"), anchor="w").pack(side="left", padx=2)

        self._clips_frame = tk.Frame(lf)
        self._clips_frame.pack(fill="x")

        # Add clip button
        btn_row = tk.Frame(lf); btn_row.pack(fill="x", pady=(6, 0))
        self.btn_add_clip = tk.Button(btn_row,
                                       text=t("crossfader.add_clip"),
                                       bg=CLR.get("panel", "#222222"), fg=CLR.get("fg", "#FFFFFF"),
                                       relief="flat", cursor="hand2",
                                       command=self._add_clip_row)
        self.btn_add_clip.pack(side="left", padx=4)
        tk.Label(btn_row,
                 text=t("crossfader.max_10_clips"),
                 fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 8)).pack(side="left", padx=8)

        # Seed with 2 rows
        self._add_clip_row()
        self._add_clip_row()

    # ── Transition section ────────────────────────────────────────────────
    def _build_transition_section(self, parent):
        lf = tk.LabelFrame(parent, text=" 🎞  " + t("section.transition"), padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        row1 = tk.Frame(lf); row1.pack(fill="x", pady=2)

        # Duration
        tk.Label(row1, text=t("gif_maker.duration_label"), font=(UI_FONT, 10, "bold"),
                 width=16, anchor="e").pack(side="left")
        tk.Spinbox(row1, from_=1, to=10,
                   textvariable=self.trans_dur_var,
                   command=self._rebuild_clip_trans_labels,
                   width=6, font=(UI_FONT, 11)).pack(side="left", padx=8)
        self.trans_dur_var.trace_add("write",
            lambda *_: self._rebuild_clip_trans_labels())

        # Global type
        tk.Label(row1, text=t("crossfader.video_type"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._global_trans_cb = ttk.Combobox(
            row1, textvariable=self.trans_type_var,
            values=TRANSITIONS, state="readonly", width=16)
        self._global_trans_cb.pack(side="left", padx=8)
        self.trans_type_var.trace_add("write",
            lambda *_: self._apply_global_trans())

        # Audio Curve
        tk.Label(row1, text=t("crossfader.audio_curve"), font=(UI_FONT, 10, "bold")).pack(side="left", padx=(16, 0))
        ttk.Combobox(row1, textvariable=self.audio_curve_var, values=AUDIO_CURVES, state="readonly", width=8).pack(side="left", padx=8)

        # Per-clip toggle
        row2 = tk.Frame(lf); row2.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(row2,
                       text=t("crossfader.use_different_transition_for_each_clip_pair"),
                       variable=self.per_clip_trans,
                       command=self._toggle_per_clip_trans,
                       font=(UI_FONT, 10)).pack(side="left")
        tk.Label(row2,
                 text=t("crossfader.overrides_the_global_setting_above_per_pair"),
                 fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 8)).pack(side="left")

        # Transition Behavior
        row3 = tk.Frame(lf); row3.pack(fill="x", pady=(8, 0))
        tk.Label(row3, text=t("crossfader.behavior"), font=(UI_FONT, 10, "bold"), width=16, anchor="e").pack(side="left")

        self.trans_behavior_var = tk.StringVar(value="overlap")
        def _on_behavior_change(*args):
            if self.trans_behavior_var.get() == "freeze":
                self.encode_mode.set("standard")

        tk.Radiobutton(row3, text=t("crossfader.overlap_standard_merges_action_consumes_time"),
                       variable=self.trans_behavior_var, value="overlap",
                       command=_on_behavior_change,
                       font=(UI_FONT, 10)).pack(side="left", padx=8)
        tk.Radiobutton(row3, text=t("crossfader.freeze_frame_preserves_action_freezes_video_at_c"),
                       variable=self.trans_behavior_var, value="freeze",
                       command=_on_behavior_change,
                       font=(UI_FONT, 10)).pack(side="left", padx=8)

    # ── Encoding section ──────────────────────────────────────────────────
    def _build_encoding_section(self, parent):
        lf = tk.LabelFrame(parent, text=" ⚙  " + t("section.encoding"), padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        mode_row = tk.Frame(lf); mode_row.pack(fill="x", pady=2)

        tk.Radiobutton(mode_row,
                       text=t("crossfader.fast_stream_copy_whole_clips_re_encode"),
                       variable=self.encode_mode, value="fast",
                       font=(UI_FONT, 10)).pack(anchor="w")
        tk.Label(mode_row,
                 text=t("crossfader.10_100_faster_than_standard_for_long_clips"),
                 fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 8)).pack(anchor="w")

        tk.Radiobutton(mode_row,
                       text=t("crossfader.standard_re_encode_every_frame"),
                       variable=self.encode_mode, value="standard",
                       font=(UI_FONT, 10)).pack(anchor="w", pady=(6, 0))
        tk.Label(mode_row,
                 text=t("crossfader.needed_if_clips_have_different_codecs"),
                 fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 8)).pack(anchor="w")

        sep = tk.Frame(lf, bg="#333", height=1)
        sep.pack(fill="x", pady=6)

        opts = tk.Frame(lf); opts.pack(fill="x")

        # Quality
        q_frame = tk.Frame(opts); q_frame.pack(side="left", padx=(0, 20))
        tk.Label(q_frame, text=t("crossfader.quality_standard_mode"),
                 font=(UI_FONT, 9, "bold")).pack(anchor="w")
        for q in [("Very High", "Very High (Slowest)"),
                  ("High",      "High"),
                  ("Good",      "Good"),
                  ("Low",       "Low"),
                  ("Lowest",    "Lowest (Fastest)")]:
            tk.Radiobutton(q_frame, text=q[1],
                           variable=self.quality_var, value=q[0],
                           font=(UI_FONT, 9)).pack(anchor="w")

        # Audio
        a_frame = tk.Frame(opts); a_frame.pack(side="left", padx=(0, 20))
        tk.Label(a_frame, text=t("crossfader.audio"), font=(UI_FONT, 9, "bold")).pack(anchor="w")
        for a in ["No Audio", "Normal Audio", "HQ Audio"]:
            tk.Radiobutton(a_frame, text=a,
                           variable=self.audio_var, value=a,
                           font=(UI_FONT, 9)).pack(anchor="w")

        # Bit depth
        bd_frame = tk.Frame(opts); bd_frame.pack(side="left", padx=(0, 20))
        self.bd_label = tk.Label(bd_frame, text=t("crossfader.bit_depth"),
                                  font=(UI_FONT, 9, "bold"))
        self.bd_label.pack(anchor="w")
        for bd in ["8-bit", "10-bit"]:
            tk.Radiobutton(bd_frame, text=bd,
                           variable=self.bit_depth_var, value=bd,
                           font=(UI_FONT, 9)).pack(anchor="w")

        # Hardware
        hw_frame = tk.Frame(opts); hw_frame.pack(side="left")
        tk.Label(hw_frame, text=t("crossfader.hardware"),
                 font=(UI_FONT, 9, "bold")).pack(anchor="w")
        tk.Label(hw_frame, text=self.current_mode.upper(),
                 fg=CLR.get("accent", "#0078D7"), font=(MONO_FONT, 10)).pack(anchor="w")
        tk.Label(hw_frame, text=t("crossfader.auto_detected"),
                 fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 7)).pack(anchor="w")

    # ── Output section ────────────────────────────────────────────────────
    def _build_output_section(self, parent):
        lf = tk.LabelFrame(parent, text=" 💾  " + t("section.output"), padx=14, pady=8)
        lf.pack(fill="x", padx=16, pady=4)

        row = tk.Frame(lf); row.pack(fill="x")
        tk.Label(row, text=t("crossfader.output_file"), font=(UI_FONT, 10, "bold"),
                 width=14, anchor="e").pack(side="left")
        self.entry_out = tk.Entry(row, width=64, relief="flat")
        self.entry_out.pack(side="left", padx=8)
        tk.Button(row, text=t("common.save_as"),
                  command=self._browse_output).pack(side="left")

    # ── Render section ────────────────────────────────────────────────────
    def _build_render_section(self, parent):
        btn_row = tk.Frame(parent); btn_row.pack(pady=10, padx=16, fill="x")

        self.run_btn = tk.Button(
            btn_row,
            text=t("crossfader.render_crossfade"),
            font=(UI_FONT, 14, "bold"),
            bg=CLR.get("green", "#4CAF50"), fg="white",
            height=2, width=28,
            state="disabled",
            command=self._start_render)
        self.run_btn.pack(side="left", padx=6)

        self._status_lbl = tk.Label(btn_row, text="",
                                     fg=CLR.get("accent", "#0078D7"), font=(UI_FONT, 9))
        self._status_lbl.pack(side="left", padx=12)

        cf = tk.Frame(parent); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=10)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    #  Clip row management
    # ─────────────────────────────────────────────────────────────────────
    def _add_clip_row(self):
        if len(self.clip_rows) >= MAX_CLIPS:
            return

        idx = len(self.clip_rows)
        self.clip_data.append(self._empty_meta())

        row = tk.Frame(self._clips_frame, relief="groove", bd=1)
        row.pack(fill="x", pady=2)

        # Index label
        num_lbl = tk.Label(row, text=f"{idx+1}", width=3,
                           font=(UI_FONT, 9, "bold"),
                           fg=CLR.get("accent", "#0078D7"))
        num_lbl.pack(side="left", padx=4)

        # Path entry
        var = tk.StringVar()
        entry = tk.Entry(row, textvariable=var, width=52,
                         font=(MONO_FONT, 9))
        entry.pack(side="left", padx=4)
        entry.bind("<FocusOut>", lambda e, i=idx: self._on_entry_update(i))
        entry.bind("<Return>",   lambda e, i=idx: self._on_entry_update(i))

        tk.Button(row, text="…", width=3,
                  command=lambda i=idx: self._browse_clip(i)).pack(side="left")

        # Metadata label
        meta_lbl = tk.Label(row, text=t("common.no_file_loaded"),
                             fg=CLR.get("fgdim", "#888888"), font=(UI_FONT, 8),
                             width=36, anchor="w")
        meta_lbl.pack(side="left", padx=6)

        # Per-pair transition (hidden unless per_clip_trans is on)
        trans_var = tk.StringVar(value=self.trans_type_var.get())
        trans_cb  = ttk.Combobox(row, textvariable=trans_var,
                                  values=TRANSITIONS,
                                  state="readonly", width=14)
        if idx > 0 and self.per_clip_trans.get():
            trans_cb.pack(side="left", padx=4)

        # Reorder + remove buttons
        ctrl = tk.Frame(row); ctrl.pack(side="right", padx=4)
        tk.Button(ctrl, text="↑", width=2,
                  command=lambda i=idx: self._move_clip(i, -1)).pack(side="left")
        tk.Button(ctrl, text="↓", width=2,
                  command=lambda i=idx: self._move_clip(i, +1)).pack(side="left")
        tk.Button(ctrl, text="✕", width=2, fg=CLR.get("red", "#EF5350"),
                  command=lambda i=idx: self._remove_clip(i)).pack(side="left", padx=(4, 0))

        self.clip_rows.append({
            "frame":    row,
            "var":      var,
            "lbl":      meta_lbl,
            "trans_var":trans_var,
            "trans_cb": trans_cb,
            "num_lbl":  num_lbl,
        })

        if len(self.clip_rows) >= MAX_CLIPS:
            self.btn_add_clip.config(state="disabled")

        self._validate()

    def _remove_clip(self, idx):
        if len(self.clip_rows) <= 2:
            messagebox.showwarning(t("common.warning"),
                                   "At least 2 clips are required.")
            return
        self.clip_rows[idx]["frame"].destroy()
        self.clip_rows.pop(idx)
        self.clip_data.pop(idx)
        self.btn_add_clip.config(state="normal")
        self._renumber_clips()
        self._validate()

    def _move_clip(self, idx, direction):
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.clip_rows):
            return
        # Swap data
        self.clip_rows[idx], self.clip_rows[new_idx] = \
            self.clip_rows[new_idx], self.clip_rows[idx]
        self.clip_data[idx], self.clip_data[new_idx] = \
            self.clip_data[new_idx], self.clip_data[idx]

        # Re-pack in new order
        for r in self.clip_rows:
            r["frame"].pack_forget()
        for r in self.clip_rows:
            r["frame"].pack(fill="x", pady=2)

        self._renumber_clips()
        self._validate()

    def _renumber_clips(self):
        for i, r in enumerate(self.clip_rows):
            r["num_lbl"].config(text=str(i + 1))
            # Rebind callbacks with correct index
            for widget in r["frame"].winfo_children():
                if isinstance(widget, tk.Entry):
                    widget.unbind("<FocusOut>")
                    widget.unbind("<Return>")
                    widget.bind("<FocusOut>", lambda e, i=i: self._on_entry_update(i))
                    widget.bind("<Return>",   lambda e, i=i: self._on_entry_update(i))

    def _rebuild_clip_trans_labels(self):
        """Called when per_clip_trans or global type changes - show/hide per-pair dropdowns."""
        self._toggle_per_clip_trans()

    def _toggle_per_clip_trans(self):
        show = self.per_clip_trans.get()
        for i, r in enumerate(self.clip_rows):
            if i == 0:
                r["trans_cb"].pack_forget()  # no transition before clip 0
                continue
            if show:
                r["trans_cb"].pack(side="left", padx=4,
                                   before=self._find_ctrl_frame(r))
            else:
                r["trans_cb"].pack_forget()

    def _find_ctrl_frame(self, row_dict):
        """Find the ctrl frame (↑↓✕ buttons) inside a row frame."""
        for widget in row_dict["frame"].winfo_children():
            if isinstance(widget, tk.Frame):
                return widget
        return row_dict["frame"]

    def _apply_global_trans(self):
        """Copy global transition type to all per-clip dropdowns."""
        val = self.trans_type_var.get()
        for r in self.clip_rows:
            r["trans_var"].set(val)

    # ─────────────────────────────────────────────────────────────────────
    #  File handling & metadata
    # ─────────────────────────────────────────────────────────────────────
    def _browse_clip(self, idx):
        path = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mkv *.avi *.mov *.webm"),
                       ("All", t("ducker.item_2"))])
        if path:
            self.clip_rows[idx]["var"].set(path)
            self._on_entry_update(idx)
            # Auto-suggest output path from first clip
            if idx == 0 and not self.entry_out.get().strip():
                base = os.path.splitext(path)[0]
                self.entry_out.delete(0, tk.END)
                self.entry_out.insert(0, base + "_crossfaded.mp4")

    def _on_entry_update(self, idx):
        path = self.clip_rows[idx]["var"].get().strip()
        if self.clip_data[idx].get("path") != path:
            self._load_metadata(path, idx)
            self._suggest_bit_depth()
            self._validate()

    def _load_metadata(self, path, idx):
        if not path or not os.path.exists(path):
            self.clip_data[idx] = self._empty_meta()
            self.clip_rows[idx]["lbl"].config(text=t("crossfader.file_not_found"), fg="#EF5350")
            return
        try:
            ffprobe = get_binary_path("ffprobe.exe")
            cmd = [ffprobe, "-v", "error",
                   "-show_entries",
                   "format=duration,size:stream=codec_type,codec_name,r_frame_rate,width,height,pix_fmt",
                   "-of", "json", path]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    creationflags=CREATE_NO_WINDOW)
            data   = json.loads(result.stdout)
            fmt    = data.get("format", {})
            streams= data.get("streams", [])
            vs     = next((s for s in streams
                           if s.get("codec_type") == "video"), {})
            
            # Smart Audio Match Setup: Extract specific audio codec
            audio_s = next((s for s in streams if s.get("codec_type") == "audio"), {})
            a_codec = audio_s.get("codec_name", "")

            num, den = map(int, vs.get("r_frame_rate", "60/1").split("/"))
            fps      = num / den if den else 60.0
            pix      = vs.get("pix_fmt", "")

            self.clip_data[idx] = {
                "path":      path,
                "dur":       float(fmt.get("duration", 0)),
                "fps":       round(fps, 3),
                "w":         int(vs.get("width", 1920)),
                "h":         int(vs.get("height", 1080)),
                "size":      int(fmt.get("size", 0)) / (1024 * 1024),
                "bit_depth": 10 if ("10" in pix or "12" in pix) else 8,
                "has_audio": bool(a_codec),
                "a_codec":   a_codec,
            }
            self.clip_rows[idx]["lbl"].config(
                text=self._fmt_meta(self.clip_data[idx]),
                fg=CLR.get("fgdim", "#888888"))
        except Exception as e:
            self.clip_data[idx] = self._empty_meta()
            self.clip_rows[idx]["lbl"].config(
                text=f"Error reading file: {e}", fg="#EF5350")

    @staticmethod
    def _fmt_meta(d):
        if not d["dur"]:
            return "No file loaded."
        m, s = divmod(int(d["dur"]), 60)
        a_info = f"🔊 ({d['a_codec']})" if d['has_audio'] else '🔇'
        return (f"{d['w']}×{d['h']}  {d['fps']:.2f}fps  "
                f"{m}m{s:02d}s  {d['size']:.1f}MB  "
                f"{d['bit_depth']}-bit  "
                f"{a_info}")

    def _suggest_bit_depth(self):
        valid = [d for d in self.clip_data if d["dur"] > 0]
        if any(c["bit_depth"] == 10 for c in valid):
            self.bit_depth_var.set("10-bit")
            self.bd_label.config(text=t("crossfader.bit_depth_10_bit_suggested"))
        else:
            self.bit_depth_var.set("8-bit")
            self.bd_label.config(text=t("crossfader.bit_depth"))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if path:
            self.entry_out.delete(0, tk.END)
            self.entry_out.insert(0, path)
            self._validate()

    # ─────────────────────────────────────────────────────────────────────
    #  Validation
    # ─────────────────────────────────────────────────────────────────────
    def _validate(self):
        if not hasattr(self, "run_btn"):
            return
        valid = [i for i, d in enumerate(self.clip_data) if d["dur"] > 0]
        if len(valid) >= 2:
            self.run_btn.config(state="normal")
        else:
            self.run_btn.config(state="disabled")

    # ─────────────────────────────────────────────────────────────────────
    #  Render dispatch
    # ─────────────────────────────────────────────────────────────────────
    def _active_clips(self):
        return [(i, self.clip_data[i], self.clip_rows[i])
                for i in range(len(self.clip_rows))
                if self.clip_data[i]["dur"] > 0]

    def _get_trans_dur(self):
        try:
            return max(1, int(self.trans_dur_var.get()))
        except ValueError:
            return 2

    def _get_video_codec(self, pix_fmt):
        q = self.quality_var.get()
        if self.current_mode == "nvidia":
            preset, cq = {"Very High": ("p7", 10), "High": ("p6", 15),
                           "Good": ("p4", 20), "Low": ("p2", 28),
                           "Lowest": ("p1", 35)}.get(q, ("p6", 15))
            return (f"-c:v hevc_nvenc -preset {preset} "
                    f"-rc vbr -cq {cq} -pix_fmt {pix_fmt}")
        elif self.current_mode == "amd":
            qp = {"Very High": 12, "High": 18, "Good": 24,
                  "Low": 30, "Lowest": 40}.get(q, 18)
            return (f"-c:v hevc_amf -quality quality -rc cqp "
                    f"-qp_i {qp} -qp_p {qp} -pix_fmt {pix_fmt}")
        else:
            preset, crf = {"Very High": ("slow", 10), "High": ("medium", 16),
                           "Good": ("fast", 22), "Low": ("faster", 28),
                           "Lowest": ("veryfast", 34)}.get(q, ("medium", 16))
            return (f"-c:v libx265 -crf {crf} "
                    f"-preset {preset} -pix_fmt {pix_fmt}")

    def _start_render(self):
        clips = self._active_clips()
        if len(clips) < 2:
            messagebox.showwarning(t("common.warning"),
                                   "Add at least 2 clips with valid files.")
            return
        out = self.entry_out.get().strip() or "crossfaded_output.mp4"
        self.entry_out.delete(0, tk.END)
        self.entry_out.insert(0, out)

        if self.encode_mode.get() == "fast":
            if getattr(self, "trans_behavior_var", None) and self.trans_behavior_var.get() == "freeze":
                self.log(self.console, t("log.crossfader.freeze_frame_mode_requires_standard_encoding_switc"))
                self.encode_mode.set("standard")
                self._render_standard(clips, out)
            else:
                self._render_fast(clips, out)
        else:
            self._render_standard(clips, out)

    # ─────────────────────────────────────────────────────────────────────
    #  Standard render  (full re-encode, single FFmpeg pass)
    # ─────────────────────────────────────────────────────────────────────
    def _render_standard(self, clips, out):
        ffmpeg      = get_binary_path("ffmpeg.exe")
        T           = self._get_trans_dur()
        pix_fmt     = "yuv420p10le" if self.bit_depth_var.get() == "10-bit" else "yuv420p"
        audio_curve = self.audio_curve_var.get()

        target_w   = max(c[1]["w"]   for c in clips)
        target_h   = max(c[1]["h"]   for c in clips)
        target_fps = max(c[1]["fps"] for c in clips)

        scale = (f"scale={target_w}:{target_h}:"
                 f"force_original_aspect_ratio=decrease,"
                 f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2")
        vprep = f"{scale},fps={target_fps},setpts=PTS-STARTPTS,settb=AVTB"

        is_freeze = getattr(self, "trans_behavior_var", None) and self.trans_behavior_var.get() == "freeze"

        inputs = []
        for _, d, _ in clips:
            inputs += ["-i", d["path"]]

        fc = ""
        for i, (_, d, r) in enumerate(clips):
            vf = vprep
            if is_freeze:
                tpad_args = []
                if i > 0:
                    tpad_args.append(f"start_mode=clone:start_duration={T}")
                if i < len(clips) - 1:
                    tpad_args.append(f"stop_mode=clone:stop_duration={T}")
                if tpad_args:
                    vf += f",tpad={':'.join(tpad_args)}"

            fc += f"[{i}:v]{vf}[v{i}]; "

        last_v  = "[v0]"
        offset  = 0
        dur_accum = 0

        for i in range(1, len(clips)):
            trans = (clips[i][2]["trans_var"].get()
                     if self.per_clip_trans.get()
                     else self.trans_type_var.get())

            if is_freeze:
                dur_accum += clips[i-1][1]["dur"]
                offset = dur_accum + (i - 1) * T
            else:
                offset += clips[i-1][1]["dur"] - T

            out_tag = f"[xf{i}]" if i < len(clips) - 1 else "[vout]"
            fc += (f"{last_v}[v{i}]xfade=transition={trans}:"
                   f"duration={T}:offset={offset:.3f}{out_tag}; ")
            last_v = f"[xf{i}]"

        map_args   = ["-map", "[vout]"]
        audio_args = []
        audio_mode = self.audio_var.get()
        all_audio  = all(c[1]["has_audio"] for c in clips)

        if audio_mode != "No Audio" and all_audio:
            for i in range(len(clips)):
                af = ""
                if is_freeze:
                    apad_args = []
                    if i > 0:
                        apad_args.append(f"delays={T*1000}:all=1")
                    if apad_args:
                        af += f"adelay={':'.join(apad_args)}"

                    if i < len(clips) - 1:
                        if af: af += ","
                        af += f"apad=pad_dur={T}"

                if af:
                    fc += f"[{i}:a]{af}[a_pad{i}]; "
                else:
                    fc += f"[{i}:a]anull[a_pad{i}]; "

            last_a = "[a_pad0]"
            for i in range(1, len(clips)):
                out_a = f"[a{i}]" if i < len(clips) - 1 else "[aout]"
                fc += f"{last_a}[a_pad{i}]acrossfade=d={T}:curve1={audio_curve}:curve2={audio_curve}{out_a}; "
                last_a = f"[a{i}]"
            
            map_args  += ["-map", "[aout]"]
            brate      = "320k" if audio_mode == "HQ Audio" else "192k"
            
            # Use the Smart Audio Match logic even in standard mode!
            codec_map = {
                "aac": "aac", "mp3": "libmp3lame", "opus": "libopus",
                "vorbis": "libvorbis", "flac": "flac", "ac3": "ac3"
            }
            target_acodec = clips[0][1].get("a_codec") or "aac"
            target_encoder = codec_map.get(target_acodec, "aac")
            
            audio_args = [t("dynamics.c_a"), target_encoder, t("dynamics.b_a"), brate]

        vcodec = self._get_video_codec(pix_fmt).split()

        cmd = ([ffmpeg] + inputs
               + ["-filter_complex", fc.rstrip("; ")]
               + map_args + vcodec + audio_args
               + [out, "-y"])

        mode_str = "Freeze-Frame" if is_freeze else "Standard"
        self.log(self.console,
                 f"{mode_str} mode: re-encoding {len(clips)} clips…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.run_btn,
                        btn_label="🚀  RENDER CROSSFADE")

    # ─────────────────────────────────────────────────────────────────────
    #  Fast render  (stream-copy bodies, re-encode ONLY overlap windows)
    # ─────────────────────────────────────────────────────────────────────
    def _render_fast(self, clips, out):
        ffmpeg      = get_binary_path("ffmpeg.exe")
        T           = self._get_trans_dur()
        tmpdir      = tempfile.mkdtemp(prefix="crossfader_")
        pix_fmt     = "yuv420p10le" if self.bit_depth_var.get() == "10-bit" else "yuv420p"
        audio_mode  = self.audio_var.get()
        audio_curve = self.audio_curve_var.get()
        all_audio   = all(c[1]["has_audio"] for c in clips)
        do_audio    = (audio_mode != "No Audio" and all_audio)
        brate       = "320k" if audio_mode == "HQ Audio" else "192k"
        
        target_w   = max(c[1]["w"]   for c in clips) or 1920
        target_h   = max(c[1]["h"]   for c in clips) or 1080
        target_fps = max(c[1]["fps"] for c in clips) or 30

        # SMART AUDIO MATCH: Determine Master Audio Codec from Clip 1
        codec_map = {
            "aac": "aac", "mp3": "libmp3lame", "opus": "libopus",
            "vorbis": "libvorbis", "flac": "flac", "ac3": "ac3"
        }
        target_acodec = clips[0][1].get("a_codec") or "aac"
        target_aencoder = codec_map.get(target_acodec, "aac")

        self.log(self.console,
                 f"Fast mode: {len(clips)} clips, {T}s transitions.")
        if do_audio:
            self.log(self.console, f"Smart Audio Match active: Aligning project to '{target_acodec}' format.")
        
        self.run_btn.config(state="disabled", text=t("app.status.queued_btn"))

        def _task(progress_cb, cancel_fn):
            """worker_fn for the global render queue."""
            try:
                raw_body_segs = []
                trans_segs    = []

                scale_vf = (f"scale={target_w}:{target_h}:"
                            f"force_original_aspect_ratio=decrease,"
                            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                            f"fps={target_fps:.3f},"
                            f"setpts=PTS-STARTPTS,settb=AVTB")

                for i, (_, d, r) in enumerate(clips):
                    path_i = d["path"]
                    dur_i  = d["dur"]
                    clip_acodec = d.get("a_codec")

                    if not do_audio:
                        body_a_args = ["-an"]
                    elif clip_acodec == target_acodec:
                        body_a_args = [t("dynamics.c_a"), "copy"]
                    else:
                        body_a_args = [t("dynamics.c_a"), target_aencoder, t("dynamics.b_a"), brate]

                    body_start = T if i > 0 else 0.0
                    body_end   = dur_i - T if i < len(clips) - 1 else dur_i
                    body_dur   = body_end - body_start

                    if body_dur > 0.05:
                        body_path = os.path.join(tmpdir, f"body_{i}.mkv")
                        self._run_cmd_queued(
                            [ffmpeg,
                             "-ss", f"{body_start:.4f}",
                             "-i",  path_i,
                             "-t",  f"{body_dur:.4f}",
                             "-c:v", "copy"] + body_a_args +
                            ["-avoid_negative_ts", "make_zero",
                             "-reset_timestamps",  "1",
                             body_path, "-y"],
                            progress_cb, cancel_fn)
                        raw_body_segs.append((i, body_path))

                    if i < len(clips) - 1:
                        next_path  = clips[i + 1][1]["path"]
                        trans_type = (r["trans_var"].get()
                                      if self.per_clip_trans.get()
                                      else self.trans_type_var.get())

                        tail_p = os.path.join(tmpdir, f"tail_{i}.mkv")
                        head_p = os.path.join(tmpdir, f"head_{i+1}.mkv")
                        trans_a_args = (["-c:a", target_aencoder, "-b:a", brate]
                                        if do_audio else ["-an"])

                        self._run_cmd_queued(
                            [ffmpeg, "-sseof", f"-{T:.4f}", "-i", path_i,
                             "-t", f"{T:.4f}", "-vf", scale_vf,
                             "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                             "-pix_fmt", pix_fmt] + trans_a_args +
                            ["-avoid_negative_ts", "make_zero",
                             "-reset_timestamps", "1", tail_p, "-y"],
                            progress_cb, cancel_fn)

                        self._run_cmd_queued(
                            [ffmpeg, "-i", next_path, "-t", f"{T:.4f}",
                             "-vf", scale_vf,
                             "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                             "-pix_fmt", pix_fmt] + trans_a_args +
                            ["-avoid_negative_ts", "make_zero",
                             "-reset_timestamps", "1", head_p, "-y"],
                            progress_cb, cancel_fn)

                        trans_p = os.path.join(tmpdir, f"trans_{i}.mkv")
                        fc = (f"[0:v][1:v]xfade=transition={trans_type}:"
                              f"duration={T}:offset=0[vout]")
                        x_map   = ["-map", "[vout]"]
                        x_audio: list = []
                        if do_audio:
                            fc      += (f";[0:a][1:a]acrossfade=d={T}:"
                                        f"curve1={audio_curve}:curve2={audio_curve}[aout]")
                            x_map   += ["-map", "[aout]"]
                            x_audio  = [t("dynamics.c_a"), target_aencoder, t("dynamics.b_a"), brate]

                        self._run_cmd_queued(
                            [ffmpeg, "-i", tail_p, "-i", head_p,
                             "-filter_complex", fc]
                            + x_map
                            + ["-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                               "-pix_fmt", pix_fmt] + x_audio
                            + ["-avoid_negative_ts", "make_zero",
                               "-reset_timestamps", "1",
                               trans_p, "-y"],
                            progress_cb, cancel_fn)
                        trans_segs.append((i, trans_p))

                body_dict = dict(raw_body_segs)
                final_segs = []
                trans_dict = dict(trans_segs)
                for i in range(len(clips)):
                    if i in body_dict:
                        final_segs.append(body_dict[i])
                    if i in trans_dict:
                        final_segs.append(trans_dict[i])

                list_path = os.path.join(tmpdir, "concat_list.txt")
                with open(list_path, "w", encoding='utf-8') as lf:
                    for seg in final_segs:
                        safe_seg = seg.replace("'", "'\\''")
                        lf.write(f"file '{safe_seg}'\n")

                progress_cb(f"Concatenating {len(final_segs)} segments…")
                a_out = (["-c:a", "copy"] if do_audio else ["-an"])

                self._run_cmd_queued(
                    [ffmpeg, "-f", "concat", "-safe", "0",
                     "-i", list_path, "-c", "copy"] + a_out +
                    ["-movflags", "+faststart", out, "-y"],
                    progress_cb, cancel_fn)
                return 0

            except RuntimeError as e:
                progress_cb(f"[ERROR] {e}")
                return 1
            except Exception as e:
                progress_cb(f"[ERROR] {e}")
                return 1

        def _on_start(tid):
            self.run_btn.config(text=t("crossfader.rendering"))

        def _on_progress(tid, line):
            self.log(self.console, line)

        def _on_complete(tid, rc):
            self.run_btn.config(state="normal", text=t("crossfader.u0001f680_render_crossfade"))
            self.show_result(rc, out)

        self.enqueue_render(
            "Crossfader",
            output_path=out,
            worker_fn=_task,
            on_start=_on_start,
            on_progress=_on_progress,
            on_complete=_on_complete,
        )

    def _run_cmd_queued(self, cmd, progress_cb, cancel_fn):
        """Run one FFmpeg command synchronously inside a queue worker_fn."""
        progress_cb("$ " + " ".join(
            f'"{a}"' if " " in str(a) else str(a) for a in cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
        for line in iter(proc.stdout.readline, ""):
            if cancel_fn():
                try:
                    proc.terminate()
                except Exception:
                    pass
                proc.stdout.close()
                proc.wait()
                raise RuntimeError("Cancelled")
            stripped = line.rstrip()
            if stripped:
                progress_cb(stripped)
        proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg exited {proc.returncode}")

    def _log_main(self, msg):
        self.after(0, lambda m=msg: self.log(self.console, m))