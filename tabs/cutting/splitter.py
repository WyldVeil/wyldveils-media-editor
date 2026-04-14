"""
tab_multisplitter.py  ─  Manual Multi-Splitter
Extract multiple different segments from a single video into separate files.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import threading

from tabs.base_tab import BaseTab, VideoTimeline, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


def _fmt(seconds):
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"

class MultiSplitterTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.duration = 0.0
        self.split_rows = []
        self._build_ui()

    def _build_ui(self):
        self.make_header(self, t("tab.manual_multi_splitter"),
                         t("splitter.subtitle"),
                         icon="✂️")

        # Source File
        sf = tk.Frame(self, bg=CLR["bg"])
        sf.pack(fill="x", padx=20, pady=10)
        tk.Label(sf, text=t("common.source_video"), bg=CLR["bg"], fg=CLR["fg"], font=(UI_FONT, 10)).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=50, bg=CLR["input_bg"], fg=CLR["input_fg"], font=(UI_FONT, 10)).pack(side="left", padx=10)
        tk.Button(sf, text=t("btn.browse"), command=self._browse_file, bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")

        # Timeline
        tl_frame = tk.LabelFrame(self, text=t("splitter.timeline_section") if t("splitter.timeline_section") != "splitter.timeline_section" else "Timeline",
                                 bg=CLR["bg"], fg=CLR["fgdim"], padx=10, pady=6)
        tl_frame.pack(fill="x", padx=20, pady=(6, 2))
        self._timeline = VideoTimeline(tl_frame, on_change=self._on_timeline_change,
                                       height=90, show_handles=True)
        self._timeline.pack(fill="x", padx=4, pady=4)
        self._tl_info = tk.Label(tl_frame, text="No file loaded", bg=CLR["bg"],
                                 fg=CLR["fgdim"], font=(MONO_FONT, 9))
        self._tl_info.pack(anchor="w", padx=4)

        # Options
        opt_f = tk.Frame(self, bg=CLR["bg"])
        opt_f.pack(fill="x", padx=20, pady=5)
        self.copy_mode = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_f, text=t("splitter.stream_copy_checkbox"), variable=self.copy_mode, bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"]).pack(side="left")

        # Splits Container
        self.splits_container = tk.LabelFrame(self, text=t("splitter.split_regions_section"), bg=CLR["bg"], fg=CLR["fgdim"], padx=10, pady=10)
        self.splits_container.pack(fill="both", expand=True, padx=20, pady=10)
        
        btn_f = tk.Frame(self.splits_container, bg=CLR["bg"])
        btn_f.pack(fill="x", pady=(0, 10))
        tk.Button(btn_f, text=t("splitter.add_split_button"), command=self._add_row, bg=CLR["panel"], fg=CLR["fg"]).pack(side="left")

        self.rows_frame = tk.Frame(self.splits_container, bg=CLR["bg"])
        self.rows_frame.pack(fill="both", expand=True)

        # Add first row by default
        self._add_row()

        # Render Button & Console
        self.btn_render = tk.Button(self, text=t("splitter.batch_extract_button"), font=(UI_FONT, 11, "bold"), bg=CLR["green"], fg="white", command=self._render_all)
        self.btn_render.pack(pady=10)
        cf = tk.Frame(self, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _browse_file(self):
        p = filedialog.askopenfilename(filetypes=[(t("silence.video_files"), "*.mp4 *.mov *.mkv *.avi *.webm")])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self.duration = get_video_duration(p)
            self._timeline.set_duration(self.duration)
            self._timeline.set_range(0, self.duration)
            self._tl_info.config(
                text=f"{os.path.basename(p)}  ·  {_fmt(self.duration)} total")

    def _on_timeline_change(self, start, end, playhead):
        self._tl_info.config(
            text=f"Start {_fmt(start)}  ·  End {_fmt(end)}  ·  Playhead {_fmt(playhead)}")

    def _add_row(self):
        if len(self.split_rows) >= 10:
            messagebox.showwarning(t("splitter.limit_reached_title"), t("splitter.limit_reached_message"))
            return

        idx = len(self.split_rows) + 1
        row = tk.Frame(self.rows_frame, bg=CLR["bg"])
        row.pack(fill="x", pady=4)

        tk.Label(row, text=f"Clip {idx}:", bg=CLR["bg"], fg=CLR["accent"], width=6).pack(side="left")
        
        tk.Label(row, text=t("splitter.start_label"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(10,2))
        start_var = tk.StringVar(value="00:00:00")
        tk.Entry(row, textvariable=start_var, width=10, bg=CLR["input_bg"], fg=CLR["input_fg"]).pack(side="left")

        tk.Label(row, text=t("splitter.end_label"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(10,2))
        end_var = tk.StringVar(value="00:00:10")
        tk.Entry(row, textvariable=end_var, width=10, bg=CLR["input_bg"], fg=CLR["input_fg"]).pack(side="left")

        tk.Label(row, text=t("splitter.suffix_label"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(10,2))
        suffix_var = tk.StringVar(value=f"_clip{idx}")
        tk.Entry(row, textvariable=suffix_var, width=15, bg=CLR["input_bg"], fg=CLR["input_fg"]).pack(side="left")

        btn_rm = tk.Button(row, text="❌", bg=CLR["bg"], fg=CLR["red"], command=lambda r=row: self._remove_row(r))
        btn_rm.pack(side="left", padx=10)

        self.split_rows.append({"frame": row, "start": start_var, "end": end_var, "suffix": suffix_var})

    def _remove_row(self, row_frame):
        row_frame.destroy()
        self.split_rows = [r for r in self.split_rows if r["frame"] != row_frame]

    def _render_all(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not self.split_rows:
            return

        self.btn_render.config(state="disabled", text=t("splitter.processing"))
        
        def _work():
            ffmpeg = get_binary_path("ffmpeg.exe")
            base, ext = os.path.splitext(self.file_path)
            
            for i, data in enumerate(self.split_rows):
                s = data["start"].get()
                e = data["end"].get()
                suf = data["suffix"].get()
                out = f"{base}{suf}{ext}"
                
                self.log(self.console, f"\n▶ Processing {i+1}/{len(self.split_rows)}: {s} to {e} -> {suf}{ext}")
                
                cmd = [ffmpeg, "-ss", s, "-to", e, "-i", self.file_path]
                if self.copy_mode.get():
                    cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
                else:
                    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-b:a", "192k"]
                
                cmd += ["-movflags", "+faststart", out, "-y"]
                
                proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if proc.returncode == 0:
                    self.log(self.console, f"✅ Saved successfully.")
                else:
                    self.log(self.console, f"❌ Error: {proc.stderr[-200:]}")
            
            self.after(0, lambda: self.btn_render.config(state="normal", text=t("splitter.batch_extract_button")))
            self.after(0, lambda: messagebox.showinfo(t("msg.done_title"), t("msg.batch_split_done")))

        threading.Thread(target=_work, daemon=True).start()