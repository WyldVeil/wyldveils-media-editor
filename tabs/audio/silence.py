import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t

class SilenceTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        
        # Settings
        self.threshold = tk.StringVar(value="-35") # dB
        self.min_silence = tk.StringVar(value="0.5") # Seconds
        self.padding = tk.StringVar(value="0.1") # Buffer
        
        self.build_ui()

    def build_ui(self):
        top_f = tk.Frame(self); top_f.pack(pady=20)
        tk.Label(top_f, text=t("common.source_video")).pack(side="left")
        self.ent_path = tk.Entry(top_f, width=50, relief="flat"); self.ent_path.pack(side="left", padx=5)
        tk.Button(top_f, text=t("btn.browse"), command=self.load_file, cursor="hand2", relief="flat").pack(side="left")

        controls = tk.LabelFrame(self, text=t("silence.engine_section"), padx=20, pady=20)
        controls.pack(pady=10, padx=20, fill="x")

        tk.Label(controls, text=t("silence.threshold_label")).grid(row=0, column=0, sticky="w")
        tk.Entry(controls, textvariable=self.threshold, width=10, relief="flat").grid(row=0, column=1, padx=5, pady=5)
        tk.Label(controls, text=t("silence.threshold_hint"), font=(UI_FONT, 8, "italic")).grid(row=0, column=2, sticky="w")

        tk.Label(controls, text=t("silence.min_silence_label")).grid(row=1, column=0, sticky="w")
        tk.Entry(controls, textvariable=self.min_silence, width=10, relief="flat").grid(row=1, column=1, padx=5, pady=5)

        tk.Label(controls, text=t("silence.padding_label")).grid(row=2, column=0, sticky="w")
        tk.Entry(controls, textvariable=self.padding, width=10, relief="flat").grid(row=2, column=1, padx=5, pady=5)

        self.btn_run = tk.Button(self, text=t("silence.generate_button"), bg="#4CAF50", fg="white",
                                 font=(UI_FONT, 12, "bold"), height=2, command=self.process_silence)
        self.btn_run.pack(pady=20)

        self.console = tk.Text(self, height=12, bg=CLR["bg"], fg="#00FF00", font=(MONO_FONT, 10))
        self.console.pack(padx=20, pady=10, fill="both", expand=True)

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[(t("silence.video_files"), "*.mp4 *.mov *.mkv")])
        if path:
            self.file_path = path
            self.ent_path.delete(0, tk.END); self.ent_path.insert(0, path)

    def log_msg(self, msg):
        self.console.insert(tk.END, f"> {msg}\n")
        self.console.see(tk.END)
        self.update()

    def get_video_duration(self, ffmpeg_path):
        cmd = [ffmpeg_path, "-i", self.file_path]
        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW)
        _, stderr = process.communicate()
        match = re.search(r"Duration:\s(\d+):(\d+):(\d+\.\d+)", stderr)
        if match:
            h, m, s = match.groups()
            return int(h)*3600 + int(m)*60 + float(s)
        return 0

    def process_silence(self):
        if not self.file_path: return
        self.console.delete("1.0", tk.END)
        
        ffmpeg = get_binary_path("ffmpeg.exe")
        thresh = self.threshold.get()
        duration = self.min_silence.get()
        pad = float(self.padding.get())

        self.log_msg(t("log.silence.step_1_analyzing_audio_peaks_video_decoding_disabl"))
        
        # Pass 1: Detection (Added -vn to skip video decoding during analysis)
        cmd_detect = [
            ffmpeg, "-i", self.file_path,
            "-vn", # <--- THE MAGIC FIX: Ignore video track during audio scan
            "-af", f"silencedetect=noise={thresh}dB:d={duration}",
            "-f", "null", "-"
        ]
        
        # Log the command to terminal
        app = self.winfo_toplevel()
        if hasattr(app, "log_debug"):
            app.log_debug(f"SILENCE DETECT CMD: {' '.join(cmd_detect)}")

        process = subprocess.Popen(cmd_detect, stderr=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW)
        _, stderr = process.communicate()

        # Log the raw output to terminal so we can see what FFmpeg actually did
        if hasattr(app, "log_debug"):
            app.log_debug(f"RAW FFMPEG OUTPUT (Last 500 chars):\n{stderr[-500:]}")

        # --- THE NEW SMART CHECK ---
        if "Output file does not contain any stream" in stderr:
            self.log_msg(t("log.silence.error_this_video_file_has_no_audio_track"))
            self.log_msg(t("log.silence.the_silence_remover_requires_a_video_with_sound"))
            messagebox.showerror(t("common.error"), "FFmpeg could not find an audio track in this file.")
            return
        # ---------------------------

        starts = re.findall(r"silence_start: ([\d\.]+)", stderr)
        ends = re.findall(r"silence_end: ([\d\.]+)", stderr)
        
        if not starts:
            self.log_msg(t("log.silence.no_silence_found"))
            self.log_msg(t("log.silence.try_changing_threshold_to_20_or_check_developer_de"))
            return

        full_dur = self.get_video_duration(ffmpeg)
        if full_dur == 0:
            self.log_msg(t("log.silence.warning_could_not_determine_video_duration"))
            full_dur = 999999 # Fallback safety
        
        # Pass 2: Calculate "Keep" Zones
        keep_zones = []
        last_end = 0.0
        
        for s, e in zip(starts, ends):
            start_f = float(s)
            end_f = float(e)
            
            keep_start = max(0, last_end - pad)
            keep_end = min(full_dur, start_f + pad)
            
            if keep_end > keep_start:
                keep_zones.append((keep_start, keep_end))
            last_end = end_f

        if last_end < full_dur:
            keep_zones.append((max(0, last_end - pad), full_dur))

        self.log_msg(f"✅ Found {len(starts)} silence gaps.")
        self.log_msg(f"✅ Constructing {len(keep_zones)} jump-cut segments...")

        # Pass 3: The "Magic" Filter
        select_v = " + ".join([f"between(t,{z[0]},{z[1]})" for z in keep_zones])

        out_path = filedialog.asksaveasfilename(defaultextension=".mp4", initialfile="jumpcut_result.mp4")
        if not out_path: return

        self.log_msg(t("log.silence.step_2_rendering_fast_paced_final_video"))

        cmd_render = [
            ffmpeg, "-i", self.file_path,
            "-vf", f"select='{select_v}',setpts=N/FRAME_RATE/TB",
            "-af", f"aselect='{select_v}',asetpts=N/SR/TB",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-c:a", "aac", out_path, "-y"
        ]

        if hasattr(app, "log_debug"):
            app.log_debug(f"RENDER CMD: {' '.join(cmd_render)}")

        def on_done(rc):
            if rc == 0:
                self.log_msg(t("log.silence.success_jump_cut_video_created"))
                messagebox.showinfo(t("msg.done_title"), t("msg.silence_done"))
            else:
                self.log_msg(t("log.silence.render_failed_check_terminal_for_details"))

        self.run_ffmpeg(cmd_render, self.console, on_done=on_done,
                        btn=self.btn_run, btn_label="⚡ GENERATE JUMP-CUTS")