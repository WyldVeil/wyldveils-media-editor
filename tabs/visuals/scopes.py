"""
tab_videoscopes.py  ─  Video Scopes
Render industry-standard video scopes from any video file using FFmpeg's
built-in lavfi scope filters:

  • Waveform (luma + RGB parade)
  • Histogram (R/G/B/luma distribution)
  • Vectorscope (chrominance Cb/Cr)
  • Datascope (pixel value readout)

Two modes:
  1. Snapshot - analyse a single frame and display scope images
  2. Scope video - render a side-by-side scope overlay video for the
     whole clip (scope on right, video on left)

No external dependencies - pure FFmpeg.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW, open_in_explorer
from core.i18n import t


SCOPE_DEFS = {
    "Waveform (luma)": {
        "filter":  "waveform=mode=column:components=1:display=overlay:scale=ire",
        "desc":    "Shows brightness levels across the width of the frame. "
                   "IRE scale: 0 = black, 100 = white.",
    },
    "RGB Parade": {
        "filter":  "waveform=mode=column:components=7:display=parade:scale=ire",
        "desc":    "Three waveforms for Red, Green, Blue side by side. "
                   "Essential for white-balance and colour cast correction.",
    },
    "Histogram": {
        "filter":  "histogram=display_mode=stack:levels_mode=logarithmic",
        "desc":    "Distribution of pixel values. "
                   "Peaks at edges = clipping. Bunched in middle = flat/grey image.",
    },
    "Vectorscope": {
        "filter":  "vectorscope=m=color2:colorspace=601",
        "desc":    "Shows colour saturation and hue. "
                   "Flesh-line indicator. Useful for checking skin tones.",
    },
    "Datascope (pixel values)": {
        "filter":  "datascope=size=480x480:x=100:y=100",
        "desc":    "Shows raw R/G/B values at a specific pixel coordinate.",
    },
}

OVERLAY_LAYOUTS = {
    t("scopes.scope_right_of_video_side_by_side"): "hstack",
    t("scopes.scope_below_video"):                    "vstack",
    t("scopes.scope_only_no_source_video"):        "scope_only",
}


class VideoScopesTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path   = ""
        self._tmp_images = {}   # scope_name → path
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📊  " + t("tab.video_scopes"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("scopes.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=56, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # ── Two panels ────────────────────────────────────────────────────
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=5,
                               bg="#888888")
        paned.pack(fill="both", expand=True, padx=12, pady=6)

        left  = tk.Frame(paned, width=380)
        right = tk.Frame(paned)
        paned.add(left,  minsize=320)
        paned.add(right, minsize=380)

        self._build_controls(left)
        self._build_viewer(right)

    # ── Controls ──────────────────────────────────────────────────────────
    def _build_controls(self, parent):
        tk.Label(parent, text=t("scopes.scope_selection_section"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        # Scope checkboxes
        scope_lf = tk.LabelFrame(parent, text=f"  {t('scopes.scope_selection_section')}  ",
                                  padx=10, pady=8)
        scope_lf.pack(fill="x", padx=8, pady=4)

        self.scope_vars = {}
        for name, info in SCOPE_DEFS.items():
            var = tk.BooleanVar(value=(name in ("Waveform (luma)", "RGB Parade")))
            self.scope_vars[name] = var
            row = tk.Frame(scope_lf); row.pack(fill="x", pady=2)
            tk.Checkbutton(row, text=name, variable=var,
                           font=(UI_FONT, 10)).pack(side="left")
            tk.Label(row, text=info["desc"], fg=CLR["fgdim"],
                     font=(UI_FONT, 7), wraplength=290,
                     justify="left").pack(anchor="w", padx=20)

        # Snapshot timestamp
        snap_lf = tk.LabelFrame(parent, text=f"  {t('scopes.snapshot_section')}  ",
                                padx=10, pady=8)
        snap_lf.pack(fill="x", padx=8, pady=4)

        ts_row = tk.Frame(snap_lf); ts_row.pack(fill="x")
        tk.Label(ts_row, text=t("scopes.analyse_frame_label")).pack(side="left")
        self.ts_var = tk.StringVar(value="0")
        tk.Entry(ts_row, textvariable=self.ts_var, width=8, relief="flat").pack(side="left", padx=6)
        for pct in [0, 25, 50, 75]:
            tk.Button(ts_row, text=f"{pct}%", width=4, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 8),
                      command=lambda p=pct: self._set_pct(p)).pack(side="left", padx=2)

        self.btn_snap = tk.Button(snap_lf, text=t("scopes.snapshot_button"),
                                   bg=CLR["accent"], fg="black",
                                   font=(UI_FONT, 10, "bold"),
                                   command=self._run_snapshot)
        self.btn_snap.pack(fill="x", pady=6)

        # Scope video export
        vid_lf = tk.LabelFrame(parent, text=f"  {t('scopes.scope_video_section')}  ",
                                padx=10, pady=8)
        vid_lf.pack(fill="x", padx=8, pady=4)

        tk.Label(vid_lf, text=t("scopes.layout_label")).pack(anchor="w")
        self.layout_var = tk.StringVar(value=list(OVERLAY_LAYOUTS.keys())[0])
        ttk.Combobox(vid_lf, textvariable=self.layout_var,
                     values=list(OVERLAY_LAYOUTS.keys()),
                     state="readonly", width=36).pack(anchor="w", pady=4)

        out_row = tk.Frame(vid_lf); out_row.pack(fill="x")
        self.out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.out_var, width=28, relief="flat").pack(side="left")
        tk.Button(out_row, text="…", width=2,
                  command=self._browse_out).pack(side="left", padx=4)

        self.btn_vid = tk.Button(vid_lf, text=t("scopes.scope_video_button"),
                                  bg="#7B1FA2", fg="white",
                                  font=(UI_FONT, 10, "bold"),
                                  command=self._render_video)
        self.btn_vid.pack(fill="x", pady=6)

        # Status
        self.status_lbl = tk.Label(parent, text="", fg=CLR["accent"],
                                    font=(UI_FONT, 9, "bold"))
        self.status_lbl.pack(pady=4)

        # Console
        cf = tk.Frame(parent); cf.pack(fill="both", expand=True, padx=8, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ── Image viewer ──────────────────────────────────────────────────────
    def _build_viewer(self, parent):
        tk.Label(parent, text=t("scopes.scope_output"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        # Tab strip for each scope result
        self.viewer_nb = ttk.Notebook(parent)
        self.viewer_nb.pack(fill="both", expand=True, padx=6, pady=4)

        self.placeholder_frame = ttk.Frame(self.viewer_nb)
        self.viewer_nb.add(self.placeholder_frame, text=t("scopes.awaiting_analysis"))
        tk.Label(self.placeholder_frame,
                 text=("Select a video, choose scopes,\n"
                       "then click  📷 ANALYSE FRAME"),
                 font=(UI_FONT, 13), fg=CLR["fgdim"]).pack(expand=True)

    # ─────────────────────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            dur = get_video_duration(p)
            m, s = divmod(int(dur), 60)
            self.dur_lbl.config(text=f"{m}m {s}s")
            self._src_dur = dur

    def _set_pct(self, pct):
        dur = getattr(self, "_src_dur", 0)
        self.ts_var.set(f"{dur * pct / 100:.2f}")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    # ── Snapshot analysis ─────────────────────────────────────────────────
    def _run_snapshot(self):
        if not self.file_path:
            messagebox.showwarning(t("scopes.no_file_title"), t("scopes.no_file_message"))
            return
        selected = [name for name, var in self.scope_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning(t("scopes.no_scopes_title"), t("scopes.no_scopes_message"))
            return

        self.btn_snap.config(state="disabled", text=t("loudness.analysing_2"))
        self.status_lbl.config(text=t("scopes.rendering_scopes"))
        self.console.delete("1.0", tk.END)

        self.run_in_thread(self._snapshot_worker, selected)

    def _snapshot_worker(self, selected):
        ffmpeg  = get_binary_path("ffmpeg.exe")
        ts      = self.ts_var.get()
        tmp_dir = tempfile.mkdtemp()
        results = {}

        for name in selected:
            vf      = SCOPE_DEFS[name]["filter"]
            out_img = os.path.join(tmp_dir, f"scope_{name[:12].replace(' ','_')}.png")
            cmd = [ffmpeg, "-ss", ts, "-i", self.file_path,
                   "-vf", vf,
                   t("smart_reframe.frames_v"), "1",
                   t("frame_extractor.q_v"), "2", out_img, "-y"]
            self.log(self.console, f"Rendering: {name}")
            r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
            if r.returncode == 0 and os.path.exists(out_img):
                results[name] = out_img
            else:
                self.log(self.console, f"  ⚠ {name} failed: {r.stderr.decode()[-200:]}")

        self.after(0, lambda: self._display_scopes(results))
        self.after(0, lambda: self.btn_snap.config(state="normal",
                                                    text=t("scopes.snapshot_button")))
        self.after(0, lambda: self.status_lbl.config(
            text=f"✅  {len(results)} scope(s) rendered." if results
            else "❌  All scopes failed. Check console."))

    def _display_scopes(self, results):
        """Show each scope PNG in a notebook tab using PhotoImage."""
        # Clear existing tabs
        for tab in self.viewer_nb.tabs():
            self.viewer_nb.forget(tab)

        if not results:
            f = ttk.Frame(self.viewer_nb)
            self.viewer_nb.add(f, text="  Error  ")
            tk.Label(f, text=t("scopes.no_scopes_could_be_rendered_ncheck_the_console"),
                     fg=CLR["red"], font=(UI_FONT, 11)).pack(expand=True)
            return

        self._scope_images = {}   # keep refs alive

        for name, img_path in results.items():
            f = ttk.Frame(self.viewer_nb)
            self.viewer_nb.add(f, text=f"  {name.split('(')[0].strip()}  ")

            try:
                from PIL import Image, ImageTk
                img = Image.open(img_path)
                # Fit to roughly 700×500
                img.thumbnail((700, 500), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(f, image=photo, bg=CLR["console_bg"])
                lbl.pack(expand=True, fill="both")
                self._scope_images[name] = photo   # prevent GC
            except ImportError:
                # Pillow not available - offer file path
                tk.Label(f,
                         text=(f"Scope saved to:\n{img_path}\n\n"
                               "Install Pillow to view inline:\n"
                               "pip install Pillow"),
                         font=(MONO_FONT, 10), fg=CLR["accent"],
                         justify="center").pack(expand=True)
                btn = tk.Button(f, text=t("scopes.open_image_file"),
                                command=lambda p=img_path: open_in_explorer(p),
                                bg=CLR["panel"], fg=CLR["fg"])
                btn.pack(pady=8)

    # ── Scope video ───────────────────────────────────────────────────────
    def _render_video(self):
        if not self.file_path:
            messagebox.showwarning(t("scopes.no_file_title"), t("scopes.no_file_message"))
            return
        selected = [name for name, var in self.scope_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning(t("scopes.no_scopes_title"), t("scopes.no_scopes_message"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        scope_name = selected[0]   # use first selected scope for video
        vf_scope   = SCOPE_DEFS[scope_name]["filter"]
        layout     = OVERLAY_LAYOUTS[self.layout_var.get()]
        ffmpeg     = get_binary_path("ffmpeg.exe")

        if layout == "scope_only":
            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", vf_scope,
                   t("dynamics.c_v"), "libx264", "-crf", "18", "-preset", "fast",
                   t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        elif layout == "hstack":
            fc = (f"[0:v]split=2[src][scopein];"
                  f"[scopein]{vf_scope}[scope];"
                  f"[src][scope]hstack=inputs=2[out]")
            cmd = [ffmpeg, "-i", self.file_path,
                   "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                   "-c:a", "copy", "-movflags", "+faststart", out, "-y"]
        else:  # vstack
            fc = (f"[0:v]split=2[src][scopein];"
                  f"[scopein]{vf_scope}[scope];"
                  f"[src][scope]vstack=inputs=2[out]")
            cmd = [ffmpeg, "-i", self.file_path,
                   "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                   "-c:a", "copy", "-movflags", "+faststart", out, "-y"]

        self.log(self.console, f"Rendering scope video: {scope_name}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_vid,
                        btn_label=t("scopes.scope_video_button"))
