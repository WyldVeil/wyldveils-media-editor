"""
tab_trimmer.py  ─  Quick Trimmer
Precise clip trimmer with a visual dual-handle canvas timeline,
inline ffplay preview, and lossless or re-encoded export.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT, add_tooltip
from core.hardware import (    get_binary_path, get_video_duration,
    launch_preview, CREATE_NO_WINDOW,
)
from core.i18n import t

def fmt_time(seconds):
    """Convert raw seconds into HH:MM:SS.mmm or MM:SS.mmm"""
    if seconds < 0: seconds = 0
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        # Use :06.3f to ensure 3 decimal places (milliseconds)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    return f"{int(m):02d}:{s:06.3f}"

def parse_time(time_str):
    """Parse HH:MM:SS.ms, MM:SS.ms, or raw seconds back into a float."""
    try:
        ts = str(time_str).strip()
        if not ts: return 0.0
        if ':' not in ts:
            return float(ts)
        parts = ts.split(':')
        if len(parts) == 3:  # HH:MM:SS
            return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
        elif len(parts) == 2:  # MM:SS
            return float(parts[0])*60 + float(parts[1])
    except ValueError:
        return 0.0
    return 0.0


class TrimmerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path    = ""
        self.duration     = 0.0
        self.preview_proc = None
        
        # StringVars to hold human-readable times
        self._start_var   = tk.StringVar(value="00:00.00")
        self._end_var     = tk.StringVar(value="00:00.00")
        self._scrub       = tk.DoubleVar(value=0.0)
        
        self._copy_mode   = tk.BooleanVar(value=True)
        self._crf_var     = tk.StringVar(value="18")
        self._dragging    = None
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="✂  " + t("tab.quick_trimmer"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("trimmer.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source row
        sf = tk.Frame(self); sf.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self._src_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Canvas timeline
        tl_lf = tk.LabelFrame(self, text=t("trimmer.timeline_section"),
                               padx=8, pady=6)
        tl_lf.pack(fill="x", padx=20, pady=4)
        self._canvas = tk.Canvas(tl_lf, bg=CLR["console_bg"], height=110, highlightthickness=0)
        self._canvas.pack(fill="x")
        self._canvas.bind("<Configure>",     lambda _: self._draw())
        self._canvas.bind("<ButtonPress-1>",  self._on_press)
        self._canvas.bind("<B1-Motion>",      self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",lambda _: self._release())

        # Info strip
        inf = tk.Frame(self); inf.pack(fill="x", padx=20, pady=2)
        self._info_lbl = tk.Label(inf, text=t("common.no_file_loaded"), fg=CLR["fgdim"],
                                  font=(MONO_FONT, 9))
        self._info_lbl.pack(side="left")
        self._dur_lbl = tk.Label(inf, text="", fg=CLR["accent"],
                                 font=(MONO_FONT, 9, "bold"))
        self._dur_lbl.pack(side="right")

        # Marker controls
        mk = tk.LabelFrame(self, text=t("trimmer.clip_boundaries_section"), padx=14, pady=8)
        mk.pack(fill="x", padx=20, pady=4)

        r1 = tk.Frame(mk); r1.pack(fill="x", pady=2)
        tk.Label(r1, text=t("trimmer.keep_from_label"), font=(UI_FONT, 10, "bold"), width=14, anchor="e").pack(side="left")
        self._start_ent = tk.Entry(r1, textvariable=self._start_var, width=12, font=(MONO_FONT, 10), relief="flat")
        self._start_ent.pack(side="left", padx=6)
        self._start_ent.bind("<Return>", self._apply_typed_times)
        self._start_ent.bind("<FocusOut>", self._apply_typed_times)
        
        tk.Button(r1, text=t("trimmer.set_to_preview_start"), bg=CLR["panel"], fg="white",
                  command=lambda: self._start_var.set(fmt_time(self._scrub.get())) or self._apply_typed_times()).pack(side="left", padx=4)
        tk.Label(r1, text=t("trimmer.start_handle_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        r2 = tk.Frame(mk); r2.pack(fill="x", pady=2)
        tk.Label(r2, text=t("trimmer.keep_until_label"), font=(UI_FONT, 10, "bold"), width=14, anchor="e").pack(side="left")
        self._end_ent = tk.Entry(r2, textvariable=self._end_var, width=12, font=(MONO_FONT, 10), relief="flat")
        self._end_ent.pack(side="left", padx=6)
        self._end_ent.bind("<Return>", self._apply_typed_times)
        self._end_ent.bind("<FocusOut>", self._apply_typed_times)
        
        tk.Button(r2, text=t("trimmer.set_to_preview_end"), bg=CLR["panel"], fg="white",
                  command=lambda: self._end_var.set(fmt_time(self._scrub.get())) or self._apply_typed_times()).pack(side="left", padx=4)
        tk.Label(r2, text=t("trimmer.end_handle_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        r3 = tk.Frame(mk); r3.pack(fill="x", pady=8)
        tk.Label(r3, text=t("trimmer.preview_time_label"), font=(UI_FONT, 10, "bold"), width=14, anchor="e").pack(side="left")
        self._scrub_sc = tk.Scale(r3, variable=self._scrub, from_=0, to=100,
                                   resolution=0.05, orient="horizontal", length=440,
                                   command=self._on_scrub, bg=CLR["panel"], fg=CLR["fg"],
                                   troughcolor=CLR["bg"], highlightthickness=0)
        self._scrub_sc.pack(side="left", padx=6)
        self._scrub_lbl = tk.Label(r3, text="00:00.00", fg=CLR["accent"],
                                    font=(MONO_FONT, 10), width=9)
        self._scrub_lbl.pack(side="left")
        tk.Button(r3, text=t("trimmer.show_frame_button"), bg=CLR["accent"], fg="white",
                  command=self._preview_at_scrub).pack(side="left", padx=8)

        # Encode options
        enc = tk.LabelFrame(self, text=t("section.export_options"), padx=14, pady=6)
        enc.pack(fill="x", padx=20, pady=4)
        er = tk.Frame(enc); er.pack(fill="x")
        tk.Checkbutton(er, text=t("trimmer.stream_copy_checkbox"),
                       variable=self._copy_mode, font=(UI_FONT, 10),
                       command=self._toggle_enc).pack(side="left")
        self._enc_row = tk.Frame(enc)
        tk.Label(self._enc_row, text=t("common.crf")).pack(side="left")
        tk.Entry(self._enc_row, textvariable=self._crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(self._enc_row, text=t("trimmer.crf_hint"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        # Output + action buttons
        of = tk.Frame(self); of.pack(fill="x", padx=20, pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(of, textvariable=self._out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        bf = tk.Frame(self); bf.pack(pady=8)
        prev_btn = tk.Button(bf, text=t("trimmer.preview_selected_button"), bg=CLR["accent"], fg="white",
                  width=28, command=self._preview_selection)
        prev_btn.pack(side="left", padx=8)
        add_tooltip(prev_btn, "Preview the selected region in ffplay (Space)")
        self._btn_trim = tk.Button(bf, text=t("trimmer.export_button"),
                                   font=(UI_FONT, 12, "bold"),
                                   bg=CLR["green"], fg="black",
                                   height=2, width=28,
                                   command=self._run_trim)
        self._btn_trim.pack(side="left", padx=8)
        add_tooltip(self._btn_trim, "Export the trimmed clip (Ctrl+S)")

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─── File loading ─────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if not p: return
        self.file_path = p
        self._src_var.set(p)
        self.duration = get_video_duration(p)
        base = os.path.splitext(p)[0]
        self._out_var.set(base + "_trimmed.mp4")
        
        self._start_var.set("00:00.00")
        self._end_var.set(fmt_time(self.duration))
        self._scrub.set(0.0)
        self._scrub_sc.config(to=max(self.duration, 1))
        
        self._info_lbl.config(text=f"{os.path.basename(p)}  ·  {fmt_time(self.duration)} total")
        self._update_dur()
        self._draw()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p: self._out_var.set(p)

    # ─── Canvas timeline ──────────────────────────────────────────────────
    _HR = 9   # handle radius

    def _t2x(self, t, w):
        p = 24
        if self.duration <= 0: return p
        return p + int((t / self.duration) * (w - 2 * p))

    def _x2t(self, x, w):
        p = 24
        if self.duration <= 0: return 0.0
        return max(0.0, min(1.0, (x - p) / max(1, w - 2 * p))) * self.duration

    def _apply_typed_times(self, *_):
        """Called when user types a time and hits Enter or clicks away."""
        s_sec = parse_time(self._start_var.get())
        e_sec = parse_time(self._end_var.get())
        
        # Enforce bounds
        s_sec = max(0.0, min(s_sec, self.duration - 0.1))
        e_sec = max(s_sec + 0.1, min(e_sec, self.duration))
        
        # Reformat nicely in the boxes
        self._start_var.set(fmt_time(s_sec))
        self._end_var.set(fmt_time(e_sec))
        
        # Move the playhead to the new start time so the UI slider updates
        self._scrub.set(s_sec)
        self._scrub_lbl.config(text=fmt_time(s_sec))
        
        self._update_dur()
        self._draw()

    def _draw(self, *_):
        c = self._canvas
        w = c.winfo_width(); h = c.winfo_height()
        if w < 10: return
        
        try:
            c.delete("all")
            c.create_rectangle(0, 0, w, h, fill="#0D0D0D", outline="")
            if self.duration <= 0:
                c.create_text(w // 2, h // 2, text=t("trimmer.load_a_video_to_see_the_timeline"),
                              fill=CLR["fgdim"], font=(UI_FONT, 10)); return
            cy = h // 2
            
            s_sec = parse_time(self._start_var.get())
            e_sec = parse_time(self._end_var.get())
            
            xs = self._t2x(s_sec, w)
            xe = self._t2x(e_sec, w)
            xp = self._t2x(float(self._scrub.get()), w)
            
            # Track
            c.create_rectangle(24, cy-4, w-24, cy+4, fill="#2A2A2A", outline="")
            # Selection
            c.create_rectangle(xs, cy-4, xe, cy+4, fill="#1A5A98", outline="")
            
            # Tick marks
            for i in range(11):
                tx = self._t2x(self.duration * i / 10, w)
                c.create_line(tx, cy+6, tx, cy+14, fill="#444444")
                tick_time = self.duration * i / 10
                c.create_text(tx, cy+22, text=f"{int(tick_time//60):02d}:{int(tick_time%60):02d}",
                              fill="#444444", font=(UI_FONT, 7))
                              
            # Playhead (Vertical line + Triangle)
            # Draw line slicing through the track
            c.create_line(xp, cy-18, xp, cy+18, fill="#FFEB3B", width=2)
            # Draw downward triangle on top
            c.create_polygon(xp-7, cy-18, xp+7, cy-18, xp, cy-8,
                             fill="#FFEB3B", outline="#000000", width=1)
                             
            # Start handle (green)
            c.create_oval(xs-self._HR, cy-self._HR, xs+self._HR, cy+self._HR,
                          fill="#4CAF50", outline="white", width=2)
            c.create_text(xs, cy-20, text=f"START {fmt_time(s_sec)}",
                          fill="#4CAF50", font=(MONO_FONT, 8, "bold"))
                          
            # End handle (red)
            c.create_oval(xe-self._HR, cy-self._HR, xe+self._HR, cy+self._HR,
                          fill="#F44336", outline="white", width=2)
            c.create_text(xe, cy+36, text=f"END {fmt_time(e_sec)}",
                          fill="#F44336", font=(MONO_FONT, 8, "bold"))
                          
            # Selection duration header
            sel = max(0.0, e_sec - s_sec)
            c.create_text((xs+xe)//2, 14, text=f"Clip Length: {fmt_time(sel)}",
                          fill="white", font=(UI_FONT, 9, "bold"))
        except Exception as e:
            self.log_debug(f"Canvas draw error: {e}")

    def _on_press(self, ev):
        w   = self._canvas.winfo_width()
        cy  = self._canvas.winfo_height() // 2
        
        s_sec = parse_time(self._start_var.get())
        e_sec = parse_time(self._end_var.get())
        
        try:
            xs = self._t2x(s_sec, w)
            xe = self._t2x(e_sec, w)
            xp = self._t2x(float(self._scrub.get()), w)
        except (ValueError, tk.TclError):
            return
            
        def near(a, b): return abs(a - b) < 14
        
        if near(ev.x, xs):   self._dragging = "start"
        elif near(ev.x, xe): self._dragging = "end"
        elif near(ev.x, xp): self._dragging = "scrub"
        else:
            self._dragging = "scrub"
            self._scrub.set(self._x2t(ev.x, w))
            self._draw()

    def _on_drag(self, ev):
        if not self._dragging: return
        w = self._canvas.winfo_width()
        t = self._x2t(ev.x, w)
        
        s_sec = parse_time(self._start_var.get())
        e_sec = parse_time(self._end_var.get())
        
        if self._dragging == "start":
            t = max(0.0, min(t, e_sec - 0.1))
            self._start_var.set(fmt_time(t))
        elif self._dragging == "end":
            t = max(s_sec + 0.1, min(t, self.duration))
            self._end_var.set(fmt_time(t))
        elif self._dragging == "scrub":
            t = max(0.0, min(t, self.duration))
            self._scrub.set(t)
            self._scrub_lbl.config(text=fmt_time(t))
            
        self._update_dur()
        self._draw()

    def _release(self):
        self._dragging = None

    def _update_dur(self):
        try:
            s_sec = parse_time(self._start_var.get())
            e_sec = parse_time(self._end_var.get())
            sel = max(0.0, e_sec - s_sec)
            self._dur_lbl.config(text=f"Clip Length: {fmt_time(sel)}")
        except Exception:
            pass

    def _on_scrub(self, val):
        try:
            self._scrub_lbl.config(text=fmt_time(float(val)))
        except (ValueError, tk.TclError):
            pass
        self._draw()

    def _toggle_enc(self):
        if self._copy_mode.get():
            self._enc_row.pack_forget()
        else:
            self._enc_row.pack(fill="x", pady=4)

    # ─── Preview ─────────────────────────────────────────────────────────
    def _preview_at_scrub(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        self.preview_proc = launch_preview(self.file_path, start_time=self._scrub.get())

    def _preview_selection(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
            
        ss = parse_time(self._start_var.get())
        ee = parse_time(self._end_var.get())
        dur = max(0.1, ee - ss)
        
        ffplay = get_binary_path("ffplay.exe")
        cmd = [ffplay, "-ss", str(ss), "-i", self.file_path,
               "-t", str(dur), "-loop", "0",
               "-window_title", f"Trim Preview  {fmt_time(ss)} – {fmt_time(ee)}",
               "-x", "800", "-y", "450", "-loglevel", "quiet"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    # ─── Trim / Export ────────────────────────────────────────────────────
    def _run_trim(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
            
        ss = parse_time(self._start_var.get())
        end = parse_time(self._end_var.get())
        dur = end - ss
        
        if dur <= 0:
            messagebox.showerror(t("trimmer.invalid_range_error"), t("trimmer.invalid_range_message"))
            return
            
        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self._out_var.set(out)
        
        ffmpeg = get_binary_path("ffmpeg.exe")
        
        if self._copy_mode.get():
            cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                   "-t", str(dur), "-c", "copy",
                   "-avoid_negative_ts", "make_zero",
                   "-movflags", t("dynamics.faststart"),
                   out, "-y"]
            self.log(self.console, f"Stream-copy trim: {fmt_time(ss)} – {fmt_time(end)}  ({fmt_time(dur)})")
        else:
            cmd = [ffmpeg, "-ss", str(ss), "-i", self.file_path,
                   "-t", str(dur),
                   t("dynamics.c_v"), "libx264", "-crf", self._crf_var.get(), "-preset", "fast",
                   t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                   "-movflags", t("dynamics.faststart"),
                   out, "-y"]
            self.log(self.console, f"Re-encode trim: {fmt_time(ss)} – {fmt_time(end)}  CRF={self._crf_var.get()}")
            
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self._btn_trim, btn_label=t("trimmer.export_button"))