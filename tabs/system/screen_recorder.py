"""
tab_screenrecorder.py  -  Screen Recorder
Capture your desktop. Use Simple mode for instant captures
(Full Screen, Area, or Window), or Advanced mode for precise control.

Advanced mode features:
  • Global hotkey (Alt+F9) to start/stop recording without touching the app
  • Custom output folder + filename template ({date}, {time}, {counter} tokens)
  • Auto-stop after configurable duration (adds -t to FFmpeg)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import ctypes
import ctypes.wintypes
import os
import sys
import threading
import time
from datetime import datetime

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ─────────────────────────────────────────────────────────────────────────────
#  Region selector overlay
# ─────────────────────────────────────────────────────────────────────────────
class AreaSelector(tk.Toplevel):
    """Transparent overlay for clicking and dragging to select a screen region."""
    def __init__(self, master, callback):
        super().__init__(master)
        self.attributes("-alpha", 0.3, "-fullscreen", True, "-topmost", True)
        self.config(bg="black", cursor="cross")
        self.overrideredirect(True)

        self.callback = callback
        self.start_x = self.start_y = None
        self.rect = None

        self.canvas = tk.Canvas(self, cursor="cross", bg="grey", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>",   self.on_press)
        self.canvas.bind("<B1-Motion>",        self.on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self.on_release)
        self.bind("<Escape>", lambda e: self.destroy())

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, 1, 1, outline="red", width=3)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1, y1 = self.start_x, self.start_y
        x2, y2 = event.x, event.y
        rx, ry = min(x1, x2), min(y1, y2)
        rw, rh = abs(x1 - x2), abs(y1 - y2)
        if rw % 2 != 0: rw -= 1
        if rh % 2 != 0: rh -= 1
        self.callback(rx, ry, rw, rh)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  Window click-to-pick overlay
# ─────────────────────────────────────────────────────────────────────────────
class WindowPicker(tk.Toplevel):
    """
    Near-invisible fullscreen overlay.  Click on any window to capture its
    title.  After the overlay closes we query WindowFromPoint so the correct
    window (not the overlay) is identified.
    """
    def __init__(self, master, callback):
        super().__init__(master)
        self._master  = master
        self.callback = callback

        self.attributes("-alpha", 0.05, "-fullscreen", True, "-topmost", True)
        self.config(bg="#000000", cursor="hand2")
        self.overrideredirect(True)

        # Instruction banner centred on screen
        banner = tk.Frame(self, bg="#1a1a2e", padx=30, pady=20)
        banner.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(banner, text=t("screen_recorder.click_on_the_window_you_want_to_record"),
                 font=(UI_FONT, 18, "bold"), bg="#1a1a2e", fg="white").pack()
        tk.Label(banner, text=t("screen_recorder.press_esc_to_cancel"),
                 font=(UI_FONT, 10), bg="#1a1a2e", fg="#aaaaaa").pack(pady=(6, 0))

        self.bind("<ButtonPress-1>", self._on_click)
        self.bind("<Escape>",        lambda e: self.destroy())

    def _on_click(self, event):
        sx, sy = event.x_root, event.y_root
        # Destroy FIRST so the overlay is gone before WindowFromPoint runs
        self.destroy()
        # Give Windows a couple frames to remove the overlay from z-order
        self._master.after(120, lambda: self._resolve_window(sx, sy))

    def _resolve_window(self, sx, sy):
        if sys.platform != "win32":
            return

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [("left",   ctypes.c_long), ("top",    ctypes.c_long),
                        ("right",  ctypes.c_long), ("bottom", ctypes.c_long)]

        GA_ROOT = 2
        pt   = POINT(sx, sy)
        hwnd = ctypes.windll.user32.WindowFromPoint(pt)
        hwnd = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)

        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        # Capture the window's screen rect so we can use desktop-region capture
        # (immune to title changes that happen when the user navigates tabs).
        rect = RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        x = rect.left
        y = rect.top
        w = rect.right  - rect.left
        h = rect.bottom - rect.top
        win_rect = (x, y, w, h) if (w > 0 and h > 0) else None

        if title or win_rect:
            self.callback(title, win_rect)
        else:
            messagebox.showwarning(t("common.warning"),
                "Couldn't read a title from that window. "
                "Try clicking the title bar directly, or enter the name manually.")


# ─────────────────────────────────────────────────────────────────────────────
#  Main tab
# ─────────────────────────────────────────────────────────────────────────────
class ScreenRecorderTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.record_proc   = None
        self.output_path   = ""
        self.selected_region = None      # (x, y, w, h) - screen area
        self._window_rect    = None      # (x, y, w, h) - picked window bounds
        self._recording    = False
        self._rec_counter  = 0           # increments each recording for {counter} token
        self._hotkey_active = False

        # ── Advanced recording variables ──────────────────────────────────────
        self.fps_var      = tk.StringVar(value="60")
        self.vcodec_var   = tk.StringVar(value="libx264 (CPU - High Compatibility)")
        self.preset_var   = tk.StringVar(value="superfast")
        self.crf_var      = tk.IntVar(value=18)
        self.pix_fmt_var  = tk.StringVar(value="yuv420p (Standard)")

        # Dynamic Audio Sources
        self.audio_src1_var = tk.StringVar(value="None")
        self.audio_src2_var = tk.StringVar(value="None")
        self.acodec_var     = tk.StringVar(value="aac")

        self.container_var = tk.StringVar(value=".mp4")
        self.cursor_var    = tk.BooleanVar(value=True)

        # Window-title capture (Advanced mode)
        self.window_title_var  = tk.StringVar(value="")   # empty = full screen / region
        self.capture_mode_var  = tk.StringVar(value="desktop")  # "desktop" | "window"

        # OBS feature 1 – global hotkey
        self.hotkey_var    = tk.StringVar(value="Alt+F9")
        self.hotkey_enabled_var = tk.BooleanVar(value=False)

        # OBS feature 2 – output path / filename template
        _desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.out_folder_var   = tk.StringVar(value=_desktop)
        self.out_template_var = tk.StringVar(value="StudioCapture_{date}_{time}")

        # OBS feature 3 – auto-stop timer
        self.autostop_var     = tk.BooleanVar(value=False)
        self.autostop_hh_var  = tk.StringVar(value="00")
        self.autostop_mm_var  = tk.StringVar(value="05")
        self.autostop_ss_var  = tk.StringVar(value="00")

        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.make_header(self, t("tab.screen_recorder"),
                         t("screen_recorder.subtitle"),
                         icon="🖥️")

        nb_frame = tk.Frame(self, bg=CLR["bg"])
        nb_frame.pack(fill="x", padx=20, pady=10)

        self.notebook = ttk.Notebook(nb_frame)
        self.notebook.pack(fill="x", expand=True)

        self.tab_express = tk.Frame(self.notebook, bg=CLR["bg"], padx=20, pady=30)
        self.notebook.add(self.tab_express, text=t("screen_recorder.simple"))
        self._build_express_tab()

        self.tab_studio = tk.Frame(self.notebook, bg=CLR["bg"], padx=20, pady=15)
        self.notebook.add(self.tab_studio, text=t("screen_recorder.advanced"))
        self._build_studio_tab()

        # Universal stop button
        ctl_f = tk.Frame(self, bg=CLR["bg"])
        ctl_f.pack(pady=(10, 5))
        self.btn_stop = tk.Button(
            ctl_f, text=t("screen_recorder.stop_recording"),
            font=(UI_FONT, 12, "bold"), bg=CLR["panel"], fg=CLR["fg"],
            state="disabled", width=25, command=self._stop)
        self.btn_stop.pack()

        cf = tk.Frame(self, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        self.console, csb = self.make_console(cf, height=8)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────────
    #  Express Tab
    # ─────────────────────────────────────────────────────────────────────────
    def _build_express_tab(self):
        tk.Label(self.tab_express,
                 text=t("screen_recorder.instant_screen_capture_with_sensible_defaults"),
                 font=(UI_FONT, 14, "italic"),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(pady=(0, 20))

        self.btn_start_express = tk.Button(
            self.tab_express, text=t("screen_recorder.quick_record_full_screen"),
            font=(UI_FONT, 12, "bold"), bg=CLR["red"], fg="white",
            height=2, width=40, cursor="hand2", command=self._start_express)
        self.btn_start_express.pack(pady=5)

        self.btn_start_express_area = tk.Button(
            self.tab_express, text=t("screen_recorder.record_a_specific_area"),
            font=(UI_FONT, 10, "bold"), bg=CLR["panel"], fg=CLR["accent"],
            height=2, width=45, cursor="hand2", command=self._start_express_area)
        self.btn_start_express_area.pack(pady=5)

        self.btn_start_express_window = tk.Button(
            self.tab_express, text=t("screen_recorder.record_a_specific_window"),
            font=(UI_FONT, 10, "bold"), bg=CLR["panel"], fg=CLR["accent"],
            height=2, width=45, cursor="hand2", command=self._start_express_window)
        self.btn_start_express_window.pack(pady=5)

        tk.Label(self.tab_express,
                 text=t("screen_recorder.30fps_x264_ultrafast_output_saved_to_desktop"),
                 font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fgdim"]).pack(pady=(15, 0))

    # ─────────────────────────────────────────────────────────────────────────
    #  Pro Studio Tab
    # ─────────────────────────────────────────────────────────────────────────
    def _build_studio_tab(self):
        # ── Capture source ────────────────────────────────────────────────────
        src_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.capture_source_section')} ",
                              bg=CLR["bg"], fg=CLR["fgdim"],
                              font=(UI_FONT, 9), padx=10, pady=8)
        src_f.pack(fill="x", pady=(0, 8))

        # Row 0: desktop vs window radio
        mode_row = tk.Frame(src_f, bg=CLR["bg"])
        mode_row.pack(fill="x")
        tk.Radiobutton(mode_row, text=t("screen_recorder.full_screen_region"),
                       variable=self.capture_mode_var, value="desktop",
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"],
                       command=self._on_mode_change).pack(side="left")
        tk.Radiobutton(mode_row, text=t("screen_recorder.specific_window"),
                       variable=self.capture_mode_var, value="window",
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"],
                       command=self._on_mode_change).pack(side="left", padx=(20, 0))

        # Row 1: Region selector (visible in desktop mode)
        self.region_row = tk.Frame(src_f, bg=CLR["bg"])
        self.region_row.pack(fill="x", pady=(6, 0))
        tk.Button(self.region_row, text=t("screen_recorder.select_area"),
                  font=(UI_FONT, 9, "bold"), bg=CLR["panel"], fg=CLR["accent"],
                  cursor="hand2", command=self._pick_area).pack(side="left")
        self.lbl_region = tk.Label(self.region_row,
                                   text=t("screen_recorder.current_full_screen"),
                                   font=(MONO_FONT, 9), bg=CLR["bg"], fg=CLR["fgdim"])
        self.lbl_region.pack(side="left", padx=8)
        tk.Button(self.region_row, text="Reset",
                  font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"],
                  relief="flat", cursor="hand2", command=self._reset_area).pack(side="left")

        # Row 2: Window picker (visible in window mode)
        self.window_row = tk.Frame(src_f, bg=CLR["bg"])
        self.window_row.pack(fill="x", pady=(6, 0))
        tk.Button(self.window_row, text=t("screen_recorder.click_a_window"),
                  font=(UI_FONT, 9, "bold"), bg=CLR["panel"], fg=CLR["accent"],
                  cursor="hand2", command=self._pick_window_studio).pack(side="left")
        tk.Label(self.window_row, text=t("screen_recorder.or_type_title"),
                 bg=CLR["bg"], fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(side="left")
        self._win_entry = tk.Entry(self.window_row, textvariable=self.window_title_var,
                                   width=30, bg=CLR["panel"], fg=CLR["fg"],
                                   insertbackground=CLR["fg"])
        self._win_entry.pack(side="left", padx=4)
        self.lbl_window = tk.Label(self.window_row, text="",
                                   font=(MONO_FONT, 8), bg=CLR["bg"], fg=CLR["green"])
        self.lbl_window.pack(side="left", padx=4)

        self._on_mode_change()   # set initial visibility

        # ── Video Settings ────────────────────────────────────────────────────
        tk.Frame(self.tab_studio, bg=CLR["border"], height=1).pack(fill="x", pady=6)
        vid_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.video_section')} ",
                              bg=CLR["bg"], fg=CLR["fgdim"],
                              font=(UI_FONT, 9), padx=10, pady=8)
        vid_f.pack(fill="x", pady=(0, 6))

        tk.Label(vid_f, text=t("common.codec"), bg=CLR["bg"], fg=CLR["fg"],
                 width=12, anchor="e").grid(row=0, column=0, pady=4)
        ttk.Combobox(vid_f, textvariable=self.vcodec_var, width=32, state="readonly",
                     values=["libx264 (CPU - High Compatibility)",
                             "libx265 (CPU - High Efficiency)",
                             "h264_nvenc (NVIDIA GPU)", "hevc_nvenc (NVIDIA GPU)",
                             "h264_amf (AMD GPU)",      "libsvtav1 (AV1 - Next Gen)",
                             ]).grid(row=0, column=1, padx=5)

        tk.Label(vid_f, text=t("screen_recorder.framerate"), bg=CLR["bg"], fg=CLR["fg"],
                 width=10, anchor="e").grid(row=0, column=2, pady=4)
        ttk.Combobox(vid_f, textvariable=self.fps_var, width=8,
                     values=["24", "30", "60", "120"]).grid(row=0, column=3, padx=5)

        tk.Label(vid_f, text=t("codec.lbl_crf_quality"), bg=CLR["bg"], fg=CLR["fg"],
                 width=12, anchor="e").grid(row=1, column=0, pady=4)
        crf_row = tk.Frame(vid_f, bg=CLR["bg"])
        crf_row.grid(row=1, column=1, sticky="w", padx=5)
        tk.Scale(crf_row, variable=self.crf_var, from_=0, to=51,
                 orient="horizontal", length=150,
                 bg=CLR["bg"], fg=CLR["fg"], highlightthickness=0).pack(side="left")
        tk.Label(crf_row, text=t("screen_recorder.lower_better_18_lossless"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=5)

        tk.Label(vid_f, text=t("codec.lbl_pixel_format"), bg=CLR["bg"], fg=CLR["fg"],
                 width=12, anchor="e").grid(row=2, column=0, pady=4)
        ttk.Combobox(vid_f, textvariable=self.pix_fmt_var, width=32, state="readonly",
                     values=["yuv420p (Standard)",
                             "yuv444p (Full Color, large file)"]).grid(row=2, column=1, padx=5)

        tk.Label(vid_f, text=t("screen_recorder.encoder_preset"), bg=CLR["bg"], fg=CLR["fg"],
                 width=10, anchor="e").grid(row=2, column=2, pady=4)
        ttk.Combobox(vid_f, textvariable=self.preset_var, width=12, state="readonly",
                     values=["ultrafast", "superfast", "veryfast",
                             "faster", "fast", "medium", "slow"]).grid(row=2, column=3, padx=5)

        # ── Audio Devices (Dynamic) ────────────────────────────────────────────
        aud_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.audio_sources_section')} ",
                              bg=CLR["bg"], fg=CLR["fgdim"],
                              font=(UI_FONT, 9), padx=10, pady=8)
        aud_f.pack(fill="x", pady=(0, 6))

        tk.Label(aud_f, text=t("screen_recorder.source_1"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=0, column=0, sticky="e", pady=4)
        self.cb_audio1 = ttk.Combobox(aud_f, textvariable=self.audio_src1_var, width=28, state="readonly")
        self.cb_audio1.grid(row=0, column=1, padx=5, sticky="w")
        
        tk.Label(aud_f, text=t("screen_recorder.source_2"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=0, column=2, sticky="e", padx=(15, 0))
        self.cb_audio2 = ttk.Combobox(aud_f, textvariable=self.audio_src2_var, width=28, state="readonly")
        self.cb_audio2.grid(row=0, column=3, padx=5, sticky="w")

        tk.Label(aud_f, text=t("codec.lbl_audio"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=1, column=0, sticky="e", pady=8)
        ttk.Combobox(aud_f, textvariable=self.acodec_var, width=10, state="readonly",
                     values=["aac", "flac", "libopus", "pcm_s16le"]).grid(row=1, column=1, sticky="w", padx=5)

        tk.Checkbutton(aud_f, text=t("screen_recorder.capture_mouse_cursor"),
                       variable=self.cursor_var,
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"]).grid(row=1, column=2, columnspan=2, sticky="w", padx=15)

        tk.Label(aud_f, text=t("screen_recorder.container"), bg=CLR["bg"], fg=CLR["fg"]).grid(row=2, column=0, sticky="e")
        ttk.Combobox(aud_f, textvariable=self.container_var, width=10, state="readonly",
                     values=[".mp4", ".mkv", ".mov"]).grid(row=2, column=1, sticky="w", padx=5)

        # Start the background scan for audio hardware
        self.cb_audio1.set("Loading devices...")
        threading.Thread(target=self._load_audio_devices, daemon=True).start()

        # ── OBS Feature 1 – Global Hotkey ─────────────────────────────────────
        hotkey_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.hotkey_section')} ",
                                 bg=CLR["bg"], fg=CLR["fgdim"],
                                 font=(UI_FONT, 9), padx=10, pady=8)
        hotkey_f.pack(fill="x", pady=(0, 6))

        tk.Checkbutton(hotkey_f, text=t("screen_recorder.enable_global_start_stop_hotkey"),
                       variable=self.hotkey_enabled_var,
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"],
                       command=self._on_hotkey_toggle).pack(side="left")
        tk.Label(hotkey_f, text=t("screen_recorder.hotkey"), bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(20, 4))
        ttk.Combobox(hotkey_f, textvariable=self.hotkey_var, width=10, state="readonly",
                     values=["Alt+F9", "Alt+F10", "Ctrl+Alt+R"]).pack(side="left")
        self.lbl_hotkey_status = tk.Label(hotkey_f, text=t("screen_recorder.inactive"),
                                          font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"])
        self.lbl_hotkey_status.pack(side="left", padx=8)

        # ── OBS Feature 2 – Output Path ───────────────────────────────────────
        path_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.output_path_section')} ",
                               bg=CLR["bg"], fg=CLR["fgdim"],
                               font=(UI_FONT, 9), padx=10, pady=8)
        path_f.pack(fill="x", pady=(0, 6))

        r0 = tk.Frame(path_f, bg=CLR["bg"]); r0.pack(fill="x")
        tk.Label(r0, text=t("screen_recorder.folder"), bg=CLR["bg"], fg=CLR["fg"], width=10, anchor="e").pack(side="left")
        tk.Entry(r0, textvariable=self.out_folder_var, width=38,
                 bg=CLR["panel"], fg=CLR["fg"], insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Button(r0, text=t("btn.browse"), font=(UI_FONT, 8),
                  bg=CLR["panel"], fg=CLR["accent"], cursor="hand2",
                  command=self._browse_output_folder).pack(side="left")

        r1 = tk.Frame(path_f, bg=CLR["bg"]); r1.pack(fill="x", pady=(6, 0))
        tk.Label(r1, text=t("screen_recorder.filename"), bg=CLR["bg"], fg=CLR["fg"], width=10, anchor="e").pack(side="left")
        tk.Entry(r1, textvariable=self.out_template_var, width=38,
                 bg=CLR["panel"], fg=CLR["fg"], insertbackground=CLR["fg"]).pack(side="left", padx=4)
        tk.Label(r1, text="tokens: {date}  {time}  {counter}",
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=4)

        # ── OBS Feature 3 – Auto-Stop Timer ───────────────────────────────────
        timer_f = tk.LabelFrame(self.tab_studio, text=f" {t('screen_recorder.auto_stop_section')} ",
                                bg=CLR["bg"], fg=CLR["fgdim"],
                                font=(UI_FONT, 9), padx=10, pady=8)
        timer_f.pack(fill="x", pady=(0, 8))

        tk.Checkbutton(timer_f, text="Auto-stop recording after:",
                       variable=self.autostop_var,
                       bg=CLR["bg"], fg=CLR["fg"], selectcolor=CLR["panel"]).pack(side="left")

        def _hms_entry(var, label):
            tk.Label(timer_f, text=label, bg=CLR["bg"], fg=CLR["fgdim"],
                     font=(UI_FONT, 9)).pack(side="left", padx=(8, 2))
            e = tk.Entry(timer_f, textvariable=var, width=3,
                         bg=CLR["panel"], fg=CLR["fg"],
                         insertbackground=CLR["fg"], justify="center")
            e.pack(side="left")
            return e

        _hms_entry(self.autostop_hh_var, "HH:")
        _hms_entry(self.autostop_mm_var, "MM:")
        _hms_entry(self.autostop_ss_var, "SS")
        tk.Label(timer_f, text=t("screen_recorder.00_05_00_5_minutes"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=6)

        # ── Start button ──────────────────────────────────────────────────────
        self.btn_start_pro = tk.Button(
            self.tab_studio, text=t("screen_recorder.start_studio_recording"),
            font=(UI_FONT, 12, "bold"), bg=CLR["red"], fg="white",
            cursor="hand2", command=self._start_pro)
        self.btn_start_pro.pack(pady=(10, 0))

    # ─────────────────────────────────────────────────────────────────────────
    #  Audio Hardware Scanning
    # ─────────────────────────────────────────────────────────────────────────
    def _load_audio_devices(self):
        devices = ["None"]
        try:
            ffmpeg = get_binary_path("ffmpeg.exe")
            if sys.platform == "win32":
                r = subprocess.run([ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                                   stderr=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW)
                in_audio = False
                for line in r.stderr.splitlines():
                    if "DirectShow audio devices" in line:
                        in_audio = True
                    elif "DirectShow video devices" in line:
                        in_audio = False
                    elif in_audio and '"' in line and "Alternative name" not in line:
                        dev = line.split('"')[1]
                        if dev not in devices:
                            devices.append(dev)
            elif sys.platform == "darwin":
                devices.extend(["0 (Default)", "1"])
            else:
                devices.extend(["default"])
        except Exception as e:
            pass # Keep silent, fallback to None is acceptable

        self.after(0, lambda: self._update_audio_dropdowns(devices))

    def _update_audio_dropdowns(self, devices):
        try:
            self.cb_audio1.config(values=devices)
            self.cb_audio2.config(values=devices)
            
            # SMART AUTO-SELECT: Try to find system audio if available
            sys_audio = next((d for d in devices if any(x in d.lower() for x in ["stereo mix", "what u hear", "mezcla", "wave out"])), "None")
            self.audio_src1_var.set(sys_audio)
            
            # Leave source 2 as None (for secondary mic)
            self.audio_src2_var.set("None")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Mode toggle (desktop vs window)
    # ─────────────────────────────────────────────────────────────────────────
    def _on_mode_change(self):
        if self.capture_mode_var.get() == "desktop":
            self.region_row.pack(fill="x", pady=(6, 0))
            self.window_row.pack_forget()
        else:
            self.region_row.pack_forget()
            self.window_row.pack(fill="x", pady=(6, 0))

    # ─────────────────────────────────────────────────────────────────────────
    #  Region selection
    # ─────────────────────────────────────────────────────────────────────────
    def _pick_area(self):
        AreaSelector(self, self._set_region)

    def _set_region(self, x, y, w, h):
        self.selected_region = (x, y, w, h)
        self.lbl_region.config(text=f"  {w}×{h} at ({x}, {y})", fg=CLR["green"])
        self.log(self.console, f"Target region: {w}×{h} at offset ({x}, {y})")

    def _reset_area(self):
        self.selected_region = None
        self.lbl_region.config(text=t("screen_recorder.current_full_screen"), fg=CLR["fgdim"])

    # ─────────────────────────────────────────────────────────────────────────
    #  Window click-to-pick
    # ─────────────────────────────────────────────────────────────────────────
    def _pick_window_studio(self):
        if sys.platform != "win32":
            messagebox.showinfo(t("msg.os_limitation_title"), t("msg.window_capture_windows_only"))
            return
        WindowPicker(self, self._set_window_title)

    def _set_window_title(self, title: str, rect=None):
        self.window_title_var.set(title)
        self._window_rect = rect
        self.lbl_window.config(text=f"✔ {title[:40]}")
        self.log(self.console, f"Window selected: \"{title}\"")

    # ─────────────────────────────────────────────────────────────────────────
    #  Output path helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _browse_output_folder(self):
        folder = filedialog.askdirectory(title="Choose output folder",
                                         initialdir=self.out_folder_var.get())
        if folder:
            self.out_folder_var.set(folder)

    def _resolve_output_path(self, ext: str) -> str:
        self._rec_counter += 1
        template = self.out_template_var.get() or "StudioCapture_{date}_{time}"
        now = datetime.now()
        name = (template
                .replace("{date}",    now.strftime("%Y%m%d"))
                .replace("{time}",    now.strftime("%H%M%S"))
                .replace("{counter}", str(self._rec_counter)))
        folder = self.out_folder_var.get() or os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, name + ext)

    # ─────────────────────────────────────────────────────────────────────────
    #  OBS Feature 1 – Global Hotkey
    # ─────────────────────────────────────────────────────────────────────────
    _HOTKEY_MAP = {
        "Alt+F9":     (0x0001, 0x78),   # MOD_ALT,      VK_F9
        "Alt+F10":    (0x0001, 0x79),   # MOD_ALT,      VK_F10
        "Ctrl+Alt+R": (0x0003, 0x52),   # MOD_ALT|CTRL, VK_R
    }

    def _on_hotkey_toggle(self):
        if self.hotkey_enabled_var.get():
            self._start_hotkey_listener()
        else:
            self._stop_hotkey_listener()

    def _start_hotkey_listener(self):
        if sys.platform != "win32":
            messagebox.showinfo(t("msg.unsupported_title"), t("msg.hotkeys_windows_only"))
            self.hotkey_enabled_var.set(False)
            return

        key_name = self.hotkey_var.get()
        mod, vk  = self._HOTKEY_MAP.get(key_name, (0x0001, 0x78))

        ok = ctypes.windll.user32.RegisterHotKey(None, 9901, mod, vk)
        if not ok:
            messagebox.showerror(t("common.error"),
                f"Could not register {key_name}.\n"
                "Another application may be using it.")
            self.hotkey_enabled_var.set(False)
            return

        self._hotkey_active = True
        self.lbl_hotkey_status.config(text=f"  ● {key_name} active", fg=CLR["green"])
        self.log(self.console, f"Global hotkey {key_name} registered.")

        def _listen():
            MSG = ctypes.wintypes.MSG()
            while self._hotkey_active:
                if ctypes.windll.user32.PeekMessageW(
                        ctypes.byref(MSG), None, 0x0312, 0x0312, 1):  # WM_HOTKEY
                    if MSG.wParam == 9901:
                        self.after(0, self._hotkey_triggered)
                time.sleep(0.04)

        threading.Thread(target=_listen, daemon=True).start()

    def _stop_hotkey_listener(self):
        self._hotkey_active = False
        if sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(None, 9901)
        self.lbl_hotkey_status.config(text=t("screen_recorder.inactive"), fg=CLR["fgdim"])
        self.log(self.console, t("log.screen_recorder.global_hotkey_unregistered"))

    def _hotkey_triggered(self):
        if self._recording:
            self._stop()
        else:
            # Hotkey only toggles Advanced mode when on that tab
            if self.notebook.index(self.notebook.select()) == 1:
                self._start_pro()
            else:
                self._start_express()

    # ─────────────────────────────────────────────────────────────────────────
    #  Express Mode logic
    # ─────────────────────────────────────────────────────────────────────────
    def _get_express_audio_args(self):
        """Helper to inject automatically detected audio into Simple mode recordings."""
        src = self.audio_src1_var.get()
        if not src or src in ("None", "Loading devices..."):
            self.log(self.console, t("log.screen_recorder.warning_no_audio_device_found_recording_video_only"))
            return [], []
            
        inputs = []
        if sys.platform == "win32":
            inputs = ["-thread_queue_size", "1024", "-f", "dshow", "-i", f"audio={src}"]
        elif sys.platform == "darwin":
            inputs = ["-f", "avfoundation", "-i", f":{src}"]
        else:
            inputs = ["-f", "pulse", "-i", src]
            
        # Audio encode flags + Explicit mapping
        maps = [t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k", "-map", t("screen_recorder.0_v"), "-map", t("screen_recorder.1_a")]
        return inputs, maps

    def _start_express(self):
        self.output_path = os.path.join(
            os.path.expanduser("~"), "Desktop", "ScreenRecord.mp4")
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-y"]
        
        # Video Input
        if sys.platform == "win32":
            cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", "30", "-i", "desktop"]
        elif sys.platform == "darwin":
            cmd += ["-f", "avfoundation", "-framerate", "30", "-i", "1"]
        else:
            cmd += ["-f", "x11grab", "-framerate", "30", "-i", ":0.0"]
            
        # Audio Input
        aud_in, aud_map = self._get_express_audio_args()
        cmd += aud_in
        
        # Encoding & Output
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        cmd += aud_map
        cmd += [self.output_path]
        
        self._execute_ffmpeg(cmd, "Simple: Full Screen")

    def _start_express_area(self):
        AreaSelector(self, self._execute_express_area)

    def _execute_express_area(self, x, y, w, h):
        self.output_path = os.path.join(
            os.path.expanduser("~"), "Desktop", "AreaRecord.mp4")
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd = [ffmpeg, "-y"]
        
        # Video Input
        if sys.platform == "win32":
            cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", "30",
                    "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop"]
        elif sys.platform == "darwin":
            cmd += ["-f", "avfoundation", "-framerate", "30", "-i", "1",
                    "-vf", f"crop={w}:{h}:{x}:{y}"]
        else:
            cmd += ["-f", "x11grab", "-framerate", "30",
                    "-video_size", f"{w}x{h}", "-i", f":0.0+{x},{y}"]
                    
        # Audio Input
        aud_in, aud_map = self._get_express_audio_args()
        cmd += aud_in
        
        # Encoding & Output
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        cmd += aud_map
        cmd += [self.output_path]
        
        self._execute_ffmpeg(cmd, "Simple: Area")

    def _start_express_window(self):
        """Click on any window to start recording it instantly."""
        if sys.platform != "win32":
            messagebox.showinfo(t("msg.os_limitation_title"), t("msg.click_pick_windows_only"))
            return
        WindowPicker(self, self._execute_express_window)

    def _execute_express_window(self, title: str, rect=None):
        self.output_path = os.path.join(
            os.path.expanduser("~"), "Desktop", "WindowRecord.mp4")
        ffmpeg = get_binary_path("ffmpeg.exe")

        cmd = [ffmpeg, "-y"]

        # Video Input
        if rect and sys.platform == "win32":
            x, y, w, h = rect
            w = max(2, w // 2 * 2)   # libx264 requires even dimensions
            h = max(2, h // 2 * 2)
            cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", "30",
                    "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop"]
            self.log(self.console,
                     f"Capturing window region: \"{title}\" at {x},{y} {w}x{h}")
        else:
            cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", "30",
                    "-i", f"title={title}"]
            self.log(self.console, f"Targeting window by title: \"{title}\"")

        # Audio Input
        aud_in, aud_map = self._get_express_audio_args()
        cmd += aud_in
        
        # Encoding & Output
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        cmd += aud_map
        cmd += [self.output_path]

        self._execute_ffmpeg(cmd, "Simple: Window")

    # ─────────────────────────────────────────────────────────────────────────
    #  Pro Studio logic
    # ─────────────────────────────────────────────────────────────────────────
    def _start_pro(self):
        ffmpeg = get_binary_path("ffmpeg.exe")
        ext    = self.container_var.get()
        self.output_path = self._resolve_output_path(ext)
        fps    = self.fps_var.get()

        cmd = [ffmpeg, "-y"]

        # ── Auto-stop duration (OBS feature 3) ───────────────────────────────
        if self.autostop_var.get():
            try:
                hh = int(self.autostop_hh_var.get())
                mm = int(self.autostop_mm_var.get())
                ss = int(self.autostop_ss_var.get())
                total_s = hh * 3600 + mm * 60 + ss
                if total_s > 0:
                    cmd += ["-t", str(total_s)]
                    self.log(self.console, f"Auto-stop set: {hh:02d}:{mm:02d}:{ss:02d}")
            except ValueError:
                pass

        # ── Input 0: Video Source ────────────────────────────────────────────
        if sys.platform == "win32":
            # Add thread queue size to prevent buffer overflow when capturing video + audio
            cmd += ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", fps]
            if not self.cursor_var.get():
                cmd += ["-draw_mouse", "0"]

            if self.capture_mode_var.get() == "window":
                win_title = self.window_title_var.get().strip()
                if not win_title and not self._window_rect:
                    messagebox.showerror(t("common.error"), "Switch to 'Specific Window' mode and pick or type a window title.")
                    return
                if self._window_rect:
                    x, y, w, h = self._window_rect
                    w = max(2, w // 2 * 2)
                    h = max(2, h // 2 * 2)
                    cmd += ["-offset_x", str(x), "-offset_y", str(y),
                            "-video_size", f"{w}x{h}", "-i", "desktop"]
                    self.log(self.console, f"Capturing window region: \"{win_title}\" at {x},{y} {w}x{h}")
                else:
                    cmd += ["-i", f"title={win_title}"]
                    self.log(self.console, f"Capturing window by title: \"{win_title}\"")
            else:
                if self.selected_region:
                    x, y, w, h = self.selected_region
                    cmd += ["-offset_x", str(x), "-offset_y", str(y),
                            "-video_size", f"{w}x{h}"]
                cmd += ["-i", "desktop"]

        elif sys.platform == "darwin":
            cmd += ["-f", "avfoundation", "-framerate", fps, "-i", "1"]
        else:
            cmd += ["-f", "x11grab", "-framerate", fps, "-i", ":0.0"]

        # ── Inputs 1 & 2: Audio Sources ───────────────────────────────────────
        src1 = self.audio_src1_var.get()
        src2 = self.audio_src2_var.get()
        audio_inputs = 0
        
        if sys.platform == "win32":
            for src in (src1, src2):
                if src and src != "None" and "Loading" not in src:
                    # Buffer safety for audio streams to prevent dropping frames
                    cmd += ["-thread_queue_size", "1024", "-f", "dshow", "-i", f"audio={src}"]
                    audio_inputs += 1
        elif sys.platform == "darwin":
            if src1 and src1 not in ("None", "Loading devices..."):
                cmd += ["-f", "avfoundation", "-i", f":{src1}"]
                audio_inputs += 1
        else:
            if src1 and src1 not in ("None", "Loading devices..."):
                cmd += ["-f", "pulse", "-i", src1]
                audio_inputs += 1

        # ── Video encoding ────────────────────────────────────────────────────
        vcodec  = self.vcodec_var.get().split(" ")[0]
        pix_fmt = self.pix_fmt_var.get().split(" ")[0]
        cmd += ["-c:v", vcodec, "-preset", self.preset_var.get(), "-pix_fmt", pix_fmt]

        if "nvenc" not in vcodec and "amf" not in vcodec:
            cmd += ["-crf", str(self.crf_var.get())]
        else:
            cmd += ["-rc", "vbr", "-cq", str(self.crf_var.get()), "-b:v", "0"]

        # ── Audio encoding & Filters ──────────────────────────────────────────
        if audio_inputs == 0:
            self.log(self.console, t("log.screen_recorder.warning_audio_sources_set_to_none_recording_video"))
        elif audio_inputs > 0:
            cmd += ["-c:a", self.acodec_var.get(), "-b:a", "320k"]
            if audio_inputs == 1:
                # EXPLICIT MAPPING: Forces FFmpeg to properly glue video and audio together
                cmd += ["-map", "0:v", "-map", "1:a"]
            elif audio_inputs == 2:
                cmd += ["-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest[aout]", 
                        "-map", "0:v", "-map", "[aout]"]

        cmd.append(self.output_path)
        self._execute_ffmpeg(cmd, "Advanced")

    # ─────────────────────────────────────────────────────────────────────────
    #  Execution & teardown
    # ─────────────────────────────────────────────────────────────────────────
    def _execute_ffmpeg(self, cmd, mode_name):
        self._recording = True
        self.log(self.console, f"[{mode_name}] Recording → {self.output_path}")

        self.btn_start_express.config(state="disabled")
        self.btn_start_express_area.config(state="disabled")
        self.btn_start_express_window.config(state="disabled")
        self.btn_start_pro.config(state="disabled", text=t("screen_recorder.recording"))
        self.btn_stop.config(state="normal", bg=CLR["red"], fg="white")

        def _run():
            try:
                self.record_proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, creationflags=CREATE_NO_WINDOW)
                for line in iter(self.record_proc.stdout.readline, ""):
                    if "time=" in line or "error" in line.lower() or "warning" in line.lower():
                        self.after(0, lambda l=line: [
                            self.console.insert(tk.END, l),
                            self.console.see(tk.END)])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(t("common.error"), str(e)))
                self.after(0, self._stop)

        threading.Thread(target=_run, daemon=True).start()

    def _stop(self):
        self._recording = False
        proc = self.record_proc
        self.record_proc = None
        self.btn_stop.config(state="disabled", bg=CLR["panel"], fg=CLR["fg"])
        self.log(self.console, t("log.screen_recorder.stopping_flushing_file_headers"))

        out_path = self.output_path

        def _do_stop():
            if proc is not None:
                try:
                    # 'q' + newline is the clean FFmpeg quit signal
                    proc.stdin.write("q\n")
                    proc.stdin.flush()
                    proc.wait(timeout=8)
                except Exception:
                    try: proc.terminate()
                    except Exception: pass
            self.after(0, lambda: self._on_stop_done(out_path))

        threading.Thread(target=_do_stop, daemon=True).start()

    def _on_stop_done(self, out_path):
        self.btn_start_express.config(state="normal")
        self.btn_start_express_area.config(state="normal")
        self.btn_start_express_window.config(state="normal")
        self.btn_start_pro.config(state="normal", text=t("screen_recorder.start_studio_recording"))
        self.log(self.console, f"Saved: {out_path}")

    def on_close(self):
        """Called when the tab is destroyed / app exits."""
        self._stop_hotkey_listener()
        super().on_close() if hasattr(super(), "on_close") else None