"""
tab_muter.py  ─  The Muter
Silence specific time ranges in a video. Perfect for beeping out words,
removing music sections, or scrubbing sensitive audio.
Also includes a fast stream-copy option to mute an entire video instantly.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


class MuterTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.ranges = []   # list of dicts: {"start": var, "end": var, "row": frame, "dur_lbl": label}
        self._build_ui()

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔇  " + t("tab.the_muter"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("muter.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Source Video ──
        sf = tk.Frame(self, bg=CLR["bg"])
        sf.pack(pady=(20, 10))
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, bg=CLR["input_bg"], fg=CLR["input_fg"], relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", bg=CLR["panel"], fg=CLR["fg"], relief="flat").pack(side="left")

        # ── Mode Selection ──
        mode_f = tk.Frame(self, bg=CLR["bg"])
        mode_f.pack(pady=5)
        
        self.mute_mode = tk.StringVar(value="ranges")
        tk.Radiobutton(mode_f, text=t("muter.mode_ranges"), variable=self.mute_mode, value="ranges",
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], font=(UI_FONT, 10),
                       command=self._toggle_mode).pack(side="left", padx=10)
        tk.Radiobutton(mode_f, text=t("muter.mode_all"), variable=self.mute_mode, value="all",
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"], font=(UI_FONT, 10),
                       command=self._toggle_mode).pack(side="left", padx=10)

        # ── Dynamic Wrapper for Ranges & Options ──
        self.ranges_wrapper = tk.Frame(self, bg=CLR["bg"])
        self.ranges_wrapper.pack(fill="both", expand=True, padx=20, pady=5)

        # Ranges Box
        self.lf = tk.LabelFrame(self.ranges_wrapper, text=t("muter.mute_ranges_section"), bg=CLR["bg"], fg=CLR["fgdim"], padx=10, pady=8)
        self.lf.pack(fill="both", expand=True, pady=8)

        hdr_row = tk.Frame(self.lf, bg=CLR["bg"])
        hdr_row.pack(fill="x")
        tk.Label(hdr_row, text="#", width=3, bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Label(hdr_row, text=t("muter.range_start_col"), width=12, bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Label(hdr_row, text=t("muter.range_end_col"), width=12, bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        tk.Label(hdr_row, text=t("muter.range_duration_col"), width=10, bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")

        self.ranges_frame = tk.Frame(self.lf, bg=CLR["bg"])
        self.ranges_frame.pack(fill="both", expand=True)

        btn_row = tk.Frame(self.lf, bg=CLR["bg"])
        btn_row.pack(pady=10)
        tk.Button(btn_row, text=t("muter.add_range_button"), bg=CLR["panel"], fg=CLR["fg"], relief="flat",
                  command=self._add_range).pack(side="left", padx=6)
        tk.Button(btn_row, text=t("muter.remove_last_button"), bg=CLR["panel"], fg=CLR["fg"], relief="flat",
                  command=self._remove_last).pack(side="left", padx=6)

        # Options Box
        self.opt = tk.Frame(self.ranges_wrapper, bg=CLR["bg"])
        self.opt.pack(pady=4)
        self.beep_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.opt, text=t("muter.beep_checkbox"), variable=self.beep_var,
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"]).pack(side="left")
        tk.Label(self.opt, text="  " + t("muter.fade_label"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(14, 0))
        self.fade_var = tk.StringVar(value="0.05")
        tk.Entry(self.opt, textvariable=self.fade_var, width=5, bg=CLR["input_bg"], fg=CLR["input_fg"], relief="flat").pack(side="left", padx=4)

        # ── Output & Render ──
        self.out_frame = tk.Frame(self, bg=CLR["bg"])
        self.out_frame.pack(pady=10)
        
        of = tk.Frame(self.out_frame, bg=CLR["bg"])
        of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, bg=CLR["input_bg"], fg=CLR["input_fg"], relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", bg=CLR["panel"], fg=CLR["fg"], relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self.out_frame, text=t("muter.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["red"], fg="white", height=2, width=28, command=self._render, relief="flat")
        self.btn_render.pack(pady=10)

        cf = tk.Frame(self, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # Seed one range
        self._add_range()

    def _toggle_mode(self):
        """Hides the range selection tools when 'Mute entire video' is selected."""
        if self.mute_mode.get() == "all":
            self.ranges_wrapper.pack_forget()
        else:
            self.ranges_wrapper.pack(fill="both", expand=True, padx=20, pady=5, before=self.out_frame)

    def _add_range(self):
        idx = len(self.ranges)
        row = tk.Frame(self.ranges_frame, bg=CLR["bg"])
        row.pack(fill="x", pady=4)
        tk.Label(row, text=str(idx + 1), width=3, bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        sv = tk.StringVar(value="0")
        ev = tk.StringVar(value="5")
        for var in (sv, ev):
            tk.Entry(row, textvariable=var, width=10, bg=CLR["input_bg"], fg=CLR["input_fg"], relief="flat").pack(side="left", padx=4)
            var.trace_add("write", lambda *_, r=(sv, ev, row): self._update_dur(r))
        dur_lbl = tk.Label(row, text=t("muter.5_00s"), width=10, bg=CLR["bg"], fg=CLR["fgdim"])
        dur_lbl.pack(side="left")
        self.ranges.append({"start": sv, "end": ev, "row": row, "dur_lbl": dur_lbl})

    def _update_dur(self, entry):
        sv, ev, row = entry[0], entry[1], entry[2] if len(entry) > 2 else None
        try:
            d = float(ev.get()) - float(sv.get())
            for r in self.ranges:
                if r["start"] is sv:
                    r["dur_lbl"].config(text=f"{d:.2f}s" if d >= 0 else "⚠ invalid")
        except Exception:
            pass

    def _remove_last(self):
        if self.ranges:
            r = self.ranges.pop()
            r["row"].destroy()

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)

        ffmpeg = get_binary_path("ffmpeg.exe")

        # ── Mode: Mute Entire Video (Fast stream-copy) ──
        if self.mute_mode.get() == "all":
            cmd = [ffmpeg, "-i", self.file_path, 
                   t("dynamics.c_v"), "copy", "-an", 
                   "-movflags", t("dynamics.faststart"), out, "-y"]
            self.log(self.console, t("log.muter.muting_entire_video_fast_stream_copy"))
            self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                            btn=self.btn_render, btn_label=t("muter.apply_button"))
            return

        # ── Mode: Mute Specific Ranges (Re-encode audio) ──
        if not self.ranges:
            messagebox.showwarning(t("muter.no_ranges_title"), t("muter.no_ranges_message"))
            return

        fade = self.fade_var.get()
        beep = self.beep_var.get()

        valid_ranges = []
        for r in self.ranges:
            try:
                s = float(r["start"].get())
                e = float(r["end"].get())
                if e > s:
                    valid_ranges.append((s, e))
            except ValueError:
                continue

        if not valid_ranges:
            messagebox.showwarning(t("muter.bad_ranges_title"), t("muter.bad_ranges_message"))
            return

        cond = "+".join(f"between(t,{s},{e})" for s, e in valid_ranges)

        if beep:
            fc = (f"[0:a]volume=enable='{cond}':volume=0[muted];"
                  f"aevalsrc=0.3*sin(2*PI*1000*t)*({cond}):c=1:s=44100[beep];"
                  f"[muted][beep]amix=inputs=2:duration=first[aout]")
            cmd = [ffmpeg, "-i", self.file_path,
                   "-filter_complex", fc,
                   "-map", t("muter.0_v_0"), "-map", "[aout]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                   "-movflags", "+faststart", out, "-y"]
        else:
            vol_parts = [f"volume=enable='between(t,{s},{e})':volume=0"
                         for s, e in valid_ranges]
            af = ",".join(vol_parts)
            cmd = [ffmpeg, "-i", self.file_path, "-af", af,
                   t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k",
                   "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Muting {len(valid_ranges)} specific range(s)…")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("muter.apply_button"))