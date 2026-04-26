"""
tab_youtubedownloader.py  ─  Video Downloader & Media Extractor

Front-end UI for the third-party yt-dlp tool. Provides real-time progress,
audio extraction, SponsorBlock, chapter-aware trimming, batch/playlist
queue, subtitle download, live stream recording, cookies/auth, download
history, format filtering, and complete FFmpeg encode settings.

NOTE: yt-dlp is independent open-source software. WyldVeil Media Editor
merely launches yt-dlp as a subprocess; it does not host, distribute, or
modify it. See the on-screen disclaimer in _build_disclaimer() for the
legal terms presented to the user.

Requirements
------------
  yt-dlp must be available as one of:
    1. bin/yt-dlp.exe  (drop it next to ffmpeg.exe - recommended)
    2. yt-dlp on the system PATH  (pip install yt-dlp)
"""

import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from core.hardware import CREATE_NO_WINDOW, get_binary_path
from tabs.base_tab import BaseTab, CLR, MONO_FONT, UI_FONT
from core.i18n import t


# ─────────────────────────────────────────────────────────────────────────────
#  Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_ytdlp() -> str | None:
    """Return the path to the yt-dlp executable, or None if not found."""
    try:
        p = get_binary_path("yt-dlp")
        if os.path.isfile(p):
            return p
    except Exception:
        pass
    for name in ("yt-dlp", "yt-dlp.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _ffmpeg_dir() -> str:
    """Directory that contains the bundled ffmpeg binary."""
    try:
        return os.path.dirname(get_binary_path("ffmpeg"))
    except Exception:
        return ""


def _ffmpeg_exe() -> str:
    try:
        p = get_binary_path("ffmpeg")
        if os.path.isfile(p):
            return p
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


def _fmt_dur(seconds) -> str:
    s = max(0, int(seconds or 0))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _parse_time(t: str) -> float:
    t = t.strip()
    try:
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".qve_yt_history.json")

_DL_PROGRESS_RE = re.compile(
    r'\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+\s*\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)'
)

_FFMPEG_TIME_RE = re.compile(r'time=(\d+):(\d+):([\d.]+)')


# ─────────────────────────────────────────────────────────────────────────────
#  Main Tab Class
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeDownloaderTab(BaseTab):

    def __init__(self, parent):
        super().__init__(parent)
        # Bug fix: Removed self.configure(bg=CLR["bg"]) to prevent ttk styling crash

        self._video_info: dict = {}
        self._format_options: list[tuple[str, str]] = []
        self._thumb_photo = None
        self._active_proc = None
        self._batch_running = False
        self._record_proc = None
        self._record_start: float = 0.0
        self._history: list[dict] = []
        self._history_visible = True
        self._batch_visible = False
        # Last value we auto-suggested into the "Save to" box. Used to detect
        # whether the user has manually changed it: if the box still matches
        # the auto-suggestion, a new fetch is allowed to refresh it; if the
        # user typed/browsed something else, we leave it alone.
        self._last_auto_out: str = ""

        self._load_history()
        self._build_ui()
        self.after(200, self._check_ytdlp)

    # ─────────────────────────────────────────────────────────────────────────
    #  History persistence
    # ─────────────────────────────────────────────────────────────────────────

    def _load_history(self):
        try:
            if os.path.isfile(_HISTORY_FILE):
                with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
        except Exception:
            self._history = []

    def _save_history(self):
        try:
            with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _append_history(self, title: str, duration: str, url: str, file_path: str):
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "title": title,
            "duration": duration,
            "url": url,
            "file": file_path,
        }
        self._history.append(entry)
        self._save_history()
        self.after(0, self._refresh_history_tree)

    # ─────────────────────────────────────────────────────────────────────────
    #  UI Build
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Outer scrollable frame
        outer = tk.Frame(self, bg=CLR["bg"])
        outer.pack(fill="both", expand=True)

        canvas_scroll = tk.Canvas(outer, bg=CLR["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas_scroll.yview)
        canvas_scroll.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas_scroll.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(canvas_scroll, bg=CLR["bg"])
        self._scroll_win = canvas_scroll.create_window((0, 0), window=self._scroll_frame, anchor="nw")

        def _on_configure(event):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
            canvas_scroll.itemconfig(self._scroll_win, width=canvas_scroll.winfo_width())

        self._scroll_frame.bind("<Configure>", _on_configure)
        canvas_scroll.bind("<Configure>", lambda e: canvas_scroll.itemconfig(
            self._scroll_win, width=e.width))

        root = self._scroll_frame

        # 1. Header
        self.make_header(
            root,
            t("tab.youtube_downloader"),
            t("youtube.tab_description"),
            icon="▶",
        )

        # 1b. Legal / third-party disclaimer (always visible)
        self._build_disclaimer(root)

        # 2. URL row
        self._build_url_row(root)

        # 3. Info panel
        self._build_info_panel(root)

        # 4. Settings notebook
        self._build_settings_notebook(root)

        # 5. Time range / chapters
        self._build_time_range(root)

        # 6. Output row
        self._build_output_row(root)

        # 7. Progress row
        self._build_progress_row(root)

        # 8. Action buttons
        self._build_action_buttons(root)

        # 9. Batch panel (hidden by default)
        self._build_batch_panel(root)

        # 10. Console
        cf = tk.Frame(root, bg=CLR["bg"])
        cf.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # 11. History panel
        self._build_history_panel(root)

    # ── Legal disclaimer ─────────────────────────────────────────────────────

    def _build_disclaimer(self, root):
        """
        Always-visible legal notice. Distances WyldVeil Media Editor from
        the third-party yt-dlp tool and the platforms it interacts with,
        and shifts compliance/copyright responsibility onto the user.

        Kept in English by design: legal language can shift meaning when
        translated, and this notice exists to document the user's accepted
        terms in a single canonical form.
        """
        outer = tk.Frame(
            root, bg=CLR["bg"],
            highlightthickness=1,
            highlightbackground=CLR["orange"],
        )
        outer.pack(fill="x", padx=20, pady=(10, 4))

        inner = tk.Frame(outer, bg=CLR["bg"])
        inner.pack(fill="x", padx=12, pady=8)

        tk.Label(
            inner,
            text="⚠  Important Notice: Third-Party Tool & User Responsibility",
            font=(UI_FONT, 10, "bold"),
            bg=CLR["bg"], fg=CLR["orange"],
            anchor="w",
        ).pack(fill="x")

        body = (
            "This feature is a user-interface front-end for "
            "yt-dlp, an independent open-source command-line program "
            "developed and maintained by third parties. WyldVeil Media "
            "Editor is NOT affiliated with, endorsed by, or responsible "
            "for yt-dlp, any website or platform yt-dlp may interact "
            "with, or any content downloaded through it. yt-dlp is "
            "executed as a separate process; WyldVeil neither hosts nor "
            "modifies it.\n\n"
            "By using this feature you acknowledge and agree that:\n"
            "  •  You are solely responsible for complying with the "
            "Terms of Service, robots.txt, and acceptable-use policies "
            "of any website or platform you access.\n"
            "  •  You will only download content that you own, that is "
            "in the public domain, or for which you have explicit "
            "permission from the rightsholder (including, where "
            "applicable, fair use / fair dealing in your jurisdiction).\n"
            "  •  You are solely responsible for complying with all "
            "applicable copyright, intellectual-property, privacy, "
            "broadcasting, and computer-misuse laws in your "
            "jurisdiction and the jurisdiction of the content's origin.\n"
            "  •  You will not use this software to circumvent technical "
            "protection measures, paywalls, geographic restrictions, or "
            "DRM where doing so is unlawful.\n"
            "  •  This software is provided \"AS IS\", WITHOUT WARRANTY "
            "OF ANY KIND, express or implied. To the maximum extent "
            "permitted by law, WyldVeil and its contributors disclaim "
            "all liability for any direct, indirect, incidental, "
            "special, consequential, or punitive damages arising out "
            "of or relating to your use of this feature, including "
            "without limitation any claim by a rightsholder, platform "
            "operator, regulator, or other third party.\n\n"
            "If you do not agree to these terms, do not use this "
            "feature."
        )
        tk.Label(
            inner,
            text=body,
            font=(UI_FONT, 8),
            bg=CLR["bg"], fg=CLR["fgdim"],
            anchor="w", justify="left",
            wraplength=900,
        ).pack(fill="x", pady=(4, 0))

    # ── URL row ──────────────────────────────────────────────────────────────

    def _build_url_row(self, root):
        url_f = tk.Frame(root, bg=CLR["bg"])
        url_f.pack(fill="x", padx=20, pady=(14, 8))

        tk.Label(url_f, text=t("youtube.url"), font=(UI_FONT, 10, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            url_f, textvariable=self._url_var, width=52,
            relief="flat", font=(UI_FONT, 10),
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            insertbackground=CLR["accent"],
            highlightthickness=1,
            highlightbackground=CLR["border"],
            highlightcolor=CLR["accent"])
        self._url_entry.pack(side="left", padx=8)
        self._url_entry.bind("<<Paste>>", self._on_paste)

        # Playlist Toggle
        self._playlist_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            url_f, text="Playlist", variable=self._playlist_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fgdim"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"],
            cursor="hand2"
        ).pack(side="left", padx=(0, 8))

        def _btn(text, cmd, bg=None):
            b = tk.Button(url_f, text=text, relief="flat",
                          font=(UI_FONT, 9), cursor="hand2",
                          bg=bg or CLR["panel"], fg=CLR["fg"] if not bg else "white",
                          activebackground=CLR["accent"], activeforeground="white",
                          padx=8, pady=3, command=cmd)
            b.pack(side="left", padx=(0, 5))
            return b

        self._btn_fetch   = _btn("🔍 Fetch Info", self._on_fetch)
        self._btn_preview = _btn("▶ Preview",     self._preview, bg=CLR["accent"])
        _btn("🌐 Browser", self._open_browser)
        self._btn_record  = tk.Button(
            url_f, text=t("youtube.record"), relief="flat",
            font=(UI_FONT, 9), cursor="hand2",
            bg=CLR["red"], fg="white",
            activebackground=CLR["pink"], activeforeground="white",
            padx=8, pady=3, state="disabled",
            command=self._start_record)
        self._btn_record.pack(side="left", padx=(0, 5))

    # ── Info panel ───────────────────────────────────────────────────────────

    def _build_info_panel(self, root):
        info_lf = tk.LabelFrame(
            root, text=t("youtube.video_info"),
            padx=10, pady=8,
            font=(UI_FONT, 9, "bold"),
            bg=CLR["bg"], fg=CLR["fgdim"],
            bd=1, relief="solid")
        info_lf.pack(fill="x", padx=20, pady=(0, 8))

        self._thumb_canvas = tk.Canvas(
            info_lf, width=256, height=144, bg="#0A0A0A",
            highlightthickness=1, highlightbackground=CLR["border"])
        self._thumb_canvas.pack(side="left", padx=(0, 14))
        self._thumb_canvas.create_text(128, 72, text="...",
                                       fill=CLR["fgdim"], font=(UI_FONT, 13))

        meta_right = tk.Frame(info_lf, bg=CLR["bg"])
        meta_right.pack(side="left", fill="both", expand=True, anchor="n")

        self._title_var   = tk.StringVar(value="-")
        self._dur_var     = tk.StringVar(value="-")
        self._channel_var = tk.StringVar(value="-")
        self._views_var   = tk.StringVar(value="-")
        self._live_var    = tk.StringVar(value="")

        for lbl_text, var in [
            ("Title:",    self._title_var),
            ("Duration:", self._dur_var),
            ("Channel:",  self._channel_var),
            ("Views:",    self._views_var),
        ]:
            row = tk.Frame(meta_right, bg=CLR["bg"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl_text, font=(UI_FONT, 9, "bold"),
                     width=10, anchor="e", bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
            tk.Label(row, textvariable=var, font=(UI_FONT, 9),
                     wraplength=400, justify="left", anchor="w",
                     bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=6)

        live_row = tk.Frame(meta_right, bg=CLR["bg"])
        live_row.pack(fill="x", pady=2)
        self._live_badge = tk.Label(live_row, textvariable=self._live_var,
                                    font=(UI_FONT, 9, "bold"),
                                    bg=CLR["red"], fg="white", padx=6, pady=1)

        thumb_btn = tk.Button(
            meta_right, text=t("youtube.save_thumbnail"), relief="flat",
            font=(UI_FONT, 9), cursor="hand2",
            bg=CLR["panel"], fg=CLR["fg"],
            activebackground=CLR["accent"], activeforeground="white",
            command=self._save_thumbnail)
        thumb_btn.pack(anchor="w", pady=(6, 0))

    # ── Settings notebook ────────────────────────────────────────────────────

    def _build_settings_notebook(self, root):
        nb_frame = tk.Frame(root, bg=CLR["bg"])
        nb_frame.pack(fill="x", padx=20, pady=(0, 8))

        style = ttk.Style()
        try:
            style.configure("YT.TNotebook", background=CLR["bg"])
            style.configure("YT.TNotebook.Tab", font=(UI_FONT, 9),
                            padding=[8, 4])
        except Exception:
            pass

        self._settings_nb = ttk.Notebook(nb_frame)
        self._settings_nb.pack(fill="x")

        # Tab 1: Quality
        self._tab_quality = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_quality, text="Quality")
        self._build_quality_tab(self._tab_quality)

        # Tab 2: Encode
        self._tab_encode = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_encode, text="Encode")
        self._build_encode_tab(self._tab_encode)

        # Tab 3: Audio Only
        self._tab_audio = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_audio, text=t("youtube.audio_only"))
        self._build_audio_tab(self._tab_audio)

        # Tab 4: Subtitles & Meta (Upgraded)
        self._tab_subs = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_subs, text=t("youtube.subs_meta"))
        self._build_subs_tab(self._tab_subs)

        # Tab 5: SponsorBlock
        self._tab_sponsor = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_sponsor, text="SponsorBlock")
        self._build_sponsorblock_tab(self._tab_sponsor)

        # Tab 6: Auth / Network (Upgraded)
        self._tab_auth = tk.Frame(self._settings_nb, bg=CLR["bg"], padx=10, pady=8)
        self._settings_nb.add(self._tab_auth, text=t("youtube.network_advanced"))
        self._build_auth_tab(self._tab_auth)

    def _build_quality_tab(self, parent):
        # Format filter radios
        filter_row = tk.Frame(parent, bg=CLR["bg"])
        filter_row.pack(fill="x", pady=(0, 6))
        tk.Label(filter_row, text=t("youtube.filter"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")

        self._filter_var = tk.StringVar(value="All")
        for label in ("All", "4K", "1080p", "720p", "480p", "Audio only"):
            tk.Radiobutton(
                filter_row, text=label, variable=self._filter_var, value=label,
                font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
                activebackground=CLR["bg"], selectcolor=CLR["panel"],
                command=self._apply_format_filter
            ).pack(side="left", padx=4)

        # Quality combobox + size estimate
        q_row = tk.Frame(parent, bg=CLR["bg"])
        q_row.pack(fill="x", pady=(0, 6))
        tk.Label(q_row, text=t("common.quality"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self._format_cb = ttk.Combobox(q_row, state="readonly", width=58,
                                       font=(UI_FONT, 9))
        self._format_cb["values"] = ["(fetch video info first)"]
        self._format_cb.current(0)
        self._format_cb.pack(side="left", padx=8)
        self._format_cb.bind("<<ComboboxSelected>>", self._on_format_selected)

        self._size_var = tk.StringVar(value="")
        tk.Label(q_row, textvariable=self._size_var,
                 font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["orange"]).pack(side="left")

        # Download mode radios
        mode_lf = tk.LabelFrame(parent, text=f"  {t('youtube.download_mode_section')}  ",
                                font=(UI_FONT, 8, "bold"),
                                bg=CLR["bg"], fg=CLR["fgdim"],
                                bd=1, relief="solid", padx=10, pady=6)
        mode_lf.pack(fill="x", pady=(4, 0))

        self._dl_mode = tk.StringVar(value="copy")
        modes = [
            ("copy",   t("youtube.direct_copy_remux_to_chosen_container_no_re_enco")),
            ("encode", t("youtube.re_encode_download_best_ffmpeg_with_encode_setti")),
            ("audio",  t("youtube.audio_only_yt_dlp_x_with_chosen_audio_format_bit")),
        ]
        for val, label in modes:
            tk.Radiobutton(
                mode_lf, text=label, variable=self._dl_mode, value=val,
                font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
                activebackground=CLR["bg"], selectcolor=CLR["panel"]
            ).pack(anchor="w", pady=1)

    def _build_encode_tab(self, parent):
        def _row(p, lbl, widget_factory, pady=3):
            r = tk.Frame(p, bg=CLR["bg"])
            r.pack(fill="x", pady=pady)
            tk.Label(r, text=lbl, font=(UI_FONT, 9),
                     width=18, anchor="e",
                     bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
            widget_factory(r)
            return r

        def _combo(parent_row, var, values, width=22):
            cb = ttk.Combobox(parent_row, textvariable=var, values=values,
                              state="readonly", width=width, font=(UI_FONT, 9))
            cb.pack(side="left", padx=6)
            return cb

        col_left  = tk.Frame(parent, bg=CLR["bg"])
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 16))
        col_right = tk.Frame(parent, bg=CLR["bg"])
        col_right.pack(side="left", fill="both", expand=True)

        # Left column
        self._vcodec_var = tk.StringVar(value="libx264")
        _row(col_left, "Video codec:",
             lambda p: _combo(p, self._vcodec_var,
                              ["libx264", "libx265", "libsvtav1",
                               "libvpx-vp9", "prores_ks", "copy"]))

        self._acodec_var = tk.StringVar(value="aac")
        _row(col_left, "Audio codec:",
             lambda p: _combo(p, self._acodec_var,
                              ["aac", "libmp3lame", "flac", "libopus",
                               "libvorbis", "copy"]))

        self._container_var = tk.StringVar(value="mp4")
        _row(col_left, "Container:",
             lambda p: _combo(p, self._container_var,
                              ["mp4", "mkv", "webm", "mov"], width=12))

        self._preset_var = tk.StringVar(value="fast")
        _row(col_left, "Preset:",
             lambda p: _combo(p, self._preset_var,
                              ["ultrafast", "superfast", "veryfast", "faster",
                               "fast", "medium", "slow", "slower", "veryslow"],
                              width=14))

        self._res_var = tk.StringVar(value="Original")
        res_row = tk.Frame(col_left, bg=CLR["bg"])
        res_row.pack(fill="x", pady=3)
        tk.Label(res_row, text=t("common.resolution"), font=(UI_FONT, 9),
                 width=18, anchor="e", bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        res_cb = ttk.Combobox(
            res_row, textvariable=self._res_var,
            values=["Original", "3840×2160", "2560×1440", "1920×1080",
                    "1280×720", "854×480", "640×360", t("youtube.smart_reframe_custom")],
            state="readonly", width=14, font=(UI_FONT, 9))
        res_cb.pack(side="left", padx=6)
        self._custom_res_var = tk.StringVar(value="1280×720")
        self._custom_res_entry = tk.Entry(
            res_row, textvariable=self._custom_res_var, width=10,
            relief="flat", font=(UI_FONT, 9),
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            insertbackground=CLR["accent"])
        res_cb.bind("<<ComboboxSelected>>",
                    lambda e: (self._custom_res_entry.pack(side="left", padx=4)
                               if self._res_var.get() == "Custom…"
                               else self._custom_res_entry.pack_forget()))

        # Right column
        crf_row = tk.Frame(col_right, bg=CLR["bg"])
        crf_row.pack(fill="x", pady=3)
        tk.Label(crf_row, text=t("youtube.crf_0_51"), font=(UI_FONT, 9),
                 width=16, anchor="e", bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        self._crf_var = tk.IntVar(value=18)
        crf_scale = tk.Scale(
            crf_row, variable=self._crf_var, from_=0, to=51,
            orient="horizontal", length=120,
            bg=CLR["panel"], fg=CLR["fg"], troughcolor=CLR["bg"],
            highlightthickness=0, command=lambda v: self._crf_entry_var.set(str(int(float(v)))))
        crf_scale.pack(side="left", padx=4)
        self._crf_entry_var = tk.StringVar(value="18")
        crf_entry = tk.Entry(crf_row, textvariable=self._crf_entry_var,
                             width=4, relief="flat", font=(UI_FONT, 9),
                             bg=CLR["input_bg"], fg=CLR["input_fg"],
                             insertbackground=CLR["accent"])
        crf_entry.pack(side="left", padx=4)
        crf_entry.bind("<Return>", lambda e: self._crf_var.set(
            max(0, min(51, int(self._crf_entry_var.get() or 18)))))

        self._abitrate_var = tk.StringVar(value="192k")
        _row(col_right, "Audio bitrate:",
             lambda p: _combo(p, self._abitrate_var,
                              ["320k", "256k", "192k", "128k", "96k", "64k"],
                              width=10))

        self._asamplerate_var = tk.StringVar(value="48000")
        _row(col_right, "Sample rate:",
             lambda p: _combo(p, self._asamplerate_var,
                              ["48000", "44100", "22050"], width=10))

    def _build_audio_tab(self, parent):
        r1 = tk.Frame(parent, bg=CLR["bg"])
        r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("tts.audio_format_label"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self._audio_fmt_var = tk.StringVar(value="mp3")
        ttk.Combobox(
            r1, textvariable=self._audio_fmt_var,
            values=["mp3", "aac", "flac", "opus", "wav", "m4a"],
            state="readonly", width=10, font=(UI_FONT, 9)
        ).pack(side="left", padx=8)

        r2 = tk.Frame(parent, bg=CLR["bg"])
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("youtube.audio_quality"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self._audio_quality_var = tk.StringVar(value="0")
        ttk.Combobox(
            r2, textvariable=self._audio_quality_var,
            values=[t("youtube.youtube_0_best"), "2", "4", t("youtube.youtube_5_medium"), "7", t("youtube.youtube_9_worst")],
            state="readonly", width=14, font=(UI_FONT, 9)
        ).pack(side="left", padx=8)

        r3 = tk.Frame(parent, bg=CLR["bg"])
        r3.pack(fill="x", pady=4)
        self._embed_thumb_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            r3, text=t("youtube.embed_thumbnail"), variable=self._embed_thumb_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left")
        self._add_metadata_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            r3, text=t("youtube.add_metadata_tags"), variable=self._add_metadata_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=16)

    def _build_subs_tab(self, parent):
        # Subtitles logic
        r1 = tk.Frame(parent, bg=CLR["bg"])
        r1.pack(fill="x", pady=4)
        self._dl_subs_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            r1, text=t("youtube.download_subtitles"), variable=self._dl_subs_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left")

        r2 = tk.Frame(parent, bg=CLR["bg"])
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("common.language"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        self._sub_lang_var = tk.StringVar(value="en")
        self._sub_lang_cb = ttk.Combobox(
            r2, textvariable=self._sub_lang_var,
            values=["en", "es", "fr", "de", "ja", "zh", "pt", "ar"],
            width=14, font=(UI_FONT, 9))
        self._sub_lang_cb.pack(side="left", padx=6)

        self._sub_auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            r2, text=t("youtube.include_auto_generated"), variable=self._sub_auto_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=10)

        r3 = tk.Frame(parent, bg=CLR["bg"])
        r3.pack(fill="x", pady=4)
        tk.Label(r3, text=t("common.format"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        self._sub_fmt_var = tk.StringVar(value="srt")
        ttk.Combobox(
            r3, textvariable=self._sub_fmt_var,
            values=["srt", "vtt", "ass"],
            state="readonly", width=8, font=(UI_FONT, 9)
        ).pack(side="left", padx=6)

        r4 = tk.Frame(parent, bg=CLR["bg"])
        r4.pack(fill="x", pady=4)
        self._embed_subs_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            r4, text=t("youtube.embed_subtitles_in_container"), variable=self._embed_subs_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left")
        self._burn_subs_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            r4, text=t("youtube.burn_into_video_hardcode"), variable=self._burn_subs_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=16)

        # Metadata & Chapters (Upgraded features)
        tk.Frame(parent, bg=CLR["border"], height=1).pack(fill="x", pady=8)
        tk.Label(parent, text=t("youtube.metadata_extra"), font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(anchor="w", pady=(0, 4))
                 
        meta_r = tk.Frame(parent, bg=CLR["bg"])
        meta_r.pack(fill="x")
        self._embed_chapters_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            meta_r, text=t("youtube.embed_chapters"), variable=self._embed_chapters_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left")
        
        self._embed_metadata_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            meta_r, text=t("youtube.embed_video_metadata"), variable=self._embed_metadata_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=16)

    def _build_sponsorblock_tab(self, parent):
        tk.Label(parent, text=t("youtube.skip_remove_these_segment_types"),
                 font=(UI_FONT, 9, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(anchor="w", pady=(0, 6))

        cats = [
            ("sponsor",        "Sponsor"),
            ("intro",          "Intro"),
            ("outro",          "Outro"),
            ("selfpromo",      "Self-promo"),
            ("interaction",    t("youtube.interaction_reminder")),
            ("preview",        t("youtube.preview_recap")),
            ("music_offtopic", t("youtube.non_music_section")),
        ]
        self._sb_vars: dict[str, tk.BooleanVar] = {}
        grid = tk.Frame(parent, bg=CLR["bg"])
        grid.pack(fill="x")
        for i, (key, label) in enumerate(cats):
            var = tk.BooleanVar(value=(key == "sponsor"))
            self._sb_vars[key] = var
            tk.Checkbutton(
                grid, text=label, variable=var,
                font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
                activebackground=CLR["bg"], selectcolor=CLR["panel"]
            ).grid(row=i // 4, column=i % 4, sticky="w", padx=8, pady=2)

        action_row = tk.Frame(parent, bg=CLR["bg"])
        action_row.pack(fill="x", pady=(8, 0))
        tk.Label(action_row, text=t("youtube.action"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        self._sb_action_var = tk.StringVar(value="remove")
        tk.Radiobutton(
            action_row, text=t("youtube.remove_segments"),
            variable=self._sb_action_var, value="remove",
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=8)
        tk.Radiobutton(
            action_row, text=t("youtube.mark_as_chapters"),
            variable=self._sb_action_var, value="mark",
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=4)

    def _build_auth_tab(self, parent):
        def _labeled_entry(parent_row, lbl, var, width=32, show=None):
            r = tk.Frame(parent_row, bg=CLR["bg"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=lbl, font=(UI_FONT, 9),
                     width=14, anchor="e",
                     bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
            kw = {"show": show} if show else {}
            tk.Entry(r, textvariable=var, width=width,
                     relief="flat", font=(UI_FONT, 9),
                     bg=CLR["input_bg"], fg=CLR["input_fg"],
                     insertbackground=CLR["accent"],
                     highlightthickness=1,
                     highlightbackground=CLR["border"],
                     highlightcolor=CLR["accent"], **kw).pack(side="left", padx=6)
            return r

        self._cookies_var   = tk.StringVar()
        self._username_var  = tk.StringVar()
        self._password_var  = tk.StringVar()
        self._ratelimit_var = tk.StringVar()
        self._proxy_var     = tk.StringVar()
        self._custom_args_var = tk.StringVar()

        # Cookies file row
        cookies_row = tk.Frame(parent, bg=CLR["bg"])
        cookies_row.pack(fill="x", pady=3)
        tk.Label(cookies_row, text=t("youtube.cookies_txt"), font=(UI_FONT, 9),
                 width=14, anchor="e",
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
        tk.Entry(cookies_row, textvariable=self._cookies_var, width=28,
                 relief="flat", font=(UI_FONT, 9),
                 bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 highlightthickness=1,
                 highlightbackground=CLR["border"],
                 highlightcolor=CLR["accent"]).pack(side="left", padx=6)
        tk.Button(cookies_row, text=t("btn.browse"), relief="flat",
                  font=(UI_FONT, 9), cursor="hand2",
                  bg=CLR["panel"], fg=CLR["fg"],
                  activebackground=CLR["accent"], activeforeground="white",
                  command=self._browse_cookies).pack(side="left")

        _labeled_entry(parent, "Username:", self._username_var)
        _labeled_entry(parent, "Password:", self._password_var, show="*")
        _labeled_entry(parent, "Rate limit:", self._ratelimit_var, width=14)
        tk.Label(parent, text=t("youtube.e_g_1m_500k_leave_blank_for_unlimited"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w", padx=20)
        _labeled_entry(parent, "Proxy:", self._proxy_var, width=28)
        tk.Label(parent, text=t("youtube.e_g_socks5_127_0_0_1_1080"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w", padx=20)

        tk.Frame(parent, bg=CLR["border"], height=1).pack(fill="x", pady=6)
        
        # Advanced: Aria2c & Custom arguments
        aria_row = tk.Frame(parent, bg=CLR["bg"])
        aria_row.pack(fill="x", pady=3)
        self._use_aria2c_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            aria_row, text=t("youtube.use_aria2c_fast_external_downloader_requires_ari"), 
            variable=self._use_aria2c_var,
            font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"]
        ).pack(side="left", padx=4)

        _labeled_entry(parent, "Custom yt-dlp args:", self._custom_args_var, width=40)
        tk.Label(parent, text=t("youtube.e_g_write_comments_dateafter_now_7days"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w", padx=20)


    # ── Time range / chapters ────────────────────────────────────────────────

    def _build_time_range(self, root):
        trim_lf = tk.LabelFrame(
            root, text=t("youtube.time_range"),
            padx=10, pady=8,
            font=(UI_FONT, 9, "bold"),
            bg=CLR["bg"], fg=CLR["fgdim"],
            bd=1, relief="solid")
        trim_lf.pack(fill="x", padx=20, pady=(0, 8))

        left_f = tk.Frame(trim_lf, bg=CLR["bg"])
        left_f.pack(side="left", fill="both", expand=True)

        right_f = tk.Frame(trim_lf, bg=CLR["bg"])
        right_f.pack(side="right", fill="y", padx=(16, 0))

        # Trim controls
        trim_row = tk.Frame(left_f, bg=CLR["bg"])
        trim_row.pack(fill="x")
        self._trim_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            trim_row, text=t("youtube.trim_section_only"),
            variable=self._trim_var, font=(UI_FONT, 9),
            bg=CLR["bg"], fg=CLR["fg"],
            activebackground=CLR["bg"], selectcolor=CLR["panel"],
            command=self._on_trim_toggle
        ).pack(side="left")

        tk.Label(trim_row, text=t("youtube.from"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left", padx=(16, 0))
        self._start_var = tk.StringVar(value="00:00:00")
        self._start_ent = tk.Entry(
            trim_row, textvariable=self._start_var,
            width=10, relief="flat", font=(MONO_FONT, 9),
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            insertbackground=CLR["accent"],
            state="disabled")
        self._start_ent.pack(side="left", padx=4)

        tk.Label(trim_row, text=t("youtube.to"), font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self._end_var = tk.StringVar(value="00:00:00")
        self._end_ent = tk.Entry(
            trim_row, textvariable=self._end_var,
            width=10, relief="flat", font=(MONO_FONT, 9),
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            insertbackground=CLR["accent"],
            state="disabled")
        self._end_ent.pack(side="left", padx=4)

        tk.Label(trim_row, text=t("youtube.hh_mm_ss"), font=(UI_FONT, 8),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=(4, 0))

        # Chapters listbox
        tk.Label(right_f, text=t("youtube.chapters_click_to_set_trim_range"),
                 font=(UI_FONT, 8), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w")
        ch_box_f = tk.Frame(right_f, bg=CLR["bg"])
        ch_box_f.pack(fill="both", expand=True)
        self._chapters_lb = tk.Listbox(
            ch_box_f, height=4, width=44,
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            font=(MONO_FONT, 8),
            selectbackground=CLR["accent"],
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground=CLR["border"])
        ch_sb = ttk.Scrollbar(ch_box_f, orient="vertical",
                              command=self._chapters_lb.yview)
        self._chapters_lb.configure(yscrollcommand=ch_sb.set)
        self._chapters_lb.pack(side="left", fill="both", expand=True)
        ch_sb.pack(side="right", fill="y")
        self._chapters_lb.bind("<<ListboxSelect>>", self._on_chapter_select)
        self._chapters_data: list[dict] = []

    # ── Output row ───────────────────────────────────────────────────────────

    def _build_output_row(self, root):
        out_f = tk.Frame(root, bg=CLR["bg"])
        out_f.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(out_f, text=t("youtube.save_to"), font=(UI_FONT, 10, "bold"),
                 bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
        self._out_var = tk.StringVar()
        tk.Entry(out_f, textvariable=self._out_var, width=54,
                 relief="flat", font=(UI_FONT, 10),
                 bg=CLR["input_bg"], fg=CLR["input_fg"],
                 insertbackground=CLR["accent"],
                 highlightthickness=1,
                 highlightbackground=CLR["border"],
                 highlightcolor=CLR["accent"]).pack(side="left", padx=8)
        tk.Button(out_f, text=t("btn.browse"), relief="flat",
                  font=(UI_FONT, 9), cursor="hand2",
                  bg=CLR["panel"], fg=CLR["fg"],
                  activebackground=CLR["accent"], activeforeground="white",
                  command=self._browse_out).pack(side="left")
        tk.Button(out_f, text=t("youtube.open_folder"), relief="flat",
                  font=(UI_FONT, 9), cursor="hand2",
                  bg=CLR["panel"], fg=CLR["fg"],
                  activebackground=CLR["accent"], activeforeground="white",
                  command=self._open_output_folder).pack(side="left", padx=(6, 0))

    # ── Progress row ─────────────────────────────────────────────────────────

    def _build_progress_row(self, root):
        prog_f = tk.Frame(root, bg=CLR["bg"])
        prog_f.pack(fill="x", padx=20, pady=(0, 6))
        self._progress = ttk.Progressbar(
            prog_f, orient="horizontal", mode="determinate", length=100)
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._prog_status_var = tk.StringVar(value="")
        tk.Label(prog_f, textvariable=self._prog_status_var,
                 font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["orange"],
                 width=38, anchor="w").pack(side="left")

    # ── Action buttons ───────────────────────────────────────────────────────

    def _build_action_buttons(self, root):
        btn_f = tk.Frame(root, bg=CLR["bg"])
        btn_f.pack(pady=8)

        self._btn_dl = tk.Button(
            btn_f, text=t("youtube.download"),
            font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white",
            height=2, width=20, cursor="hand2", relief="flat",
            activebackground=CLR["accent"], activeforeground="white",
            command=self._download)
        self._btn_dl.pack(side="left", padx=6)

        self._btn_cancel = tk.Button(
            btn_f, text=t("youtube.cancel"),
            font=(UI_FONT, 10),
            bg=CLR["red"], fg="white",
            height=2, width=12, cursor="hand2", relief="flat",
            state="disabled",
            activebackground=CLR["pink"], activeforeground="white",
            command=self._cancel_download)
        self._btn_cancel.pack(side="left", padx=6)

        self._btn_batch_toggle = tk.Button(
            btn_f, text=t("youtube.batch_mode"),
            font=(UI_FONT, 10),
            bg=CLR["panel"], fg=CLR["fg"],
            height=2, width=14, cursor="hand2", relief="flat",
            activebackground=CLR["accent"], activeforeground="white",
            command=self._toggle_batch)
        self._btn_batch_toggle.pack(side="left", padx=6)

    # ── Batch panel ──────────────────────────────────────────────────────────

    def _build_batch_panel(self, root):
        self._batch_frame = tk.LabelFrame(
            root, text=t("youtube.batch_queue"),
            padx=10, pady=8,
            font=(UI_FONT, 9, "bold"),
            bg=CLR["bg"], fg=CLR["fgdim"],
            bd=1, relief="solid")
        # Do NOT pack yet - hidden by default

        # URL textarea
        url_area_f = tk.Frame(self._batch_frame, bg=CLR["bg"])
        url_area_f.pack(fill="x", pady=(0, 6))
        tk.Label(url_area_f, text=t("youtube.paste_urls_one_per_line"),
                 font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fgdim"]).pack(anchor="w")
        self._batch_text = tk.Text(
            url_area_f, height=4, width=70,
            bg=CLR["input_bg"], fg=CLR["input_fg"],
            font=(MONO_FONT, 9), relief="flat",
            insertbackground=CLR["accent"],
            highlightthickness=1,
            highlightbackground=CLR["border"])
        self._batch_text.pack(fill="x")

        batch_ctrl_f = tk.Frame(self._batch_frame, bg=CLR["bg"])
        batch_ctrl_f.pack(fill="x", pady=(4, 6))
        tk.Button(
            batch_ctrl_f, text=t("youtube.add_urls"), relief="flat",
            font=(UI_FONT, 9), cursor="hand2",
            bg=CLR["panel"], fg=CLR["fg"],
            activebackground=CLR["accent"], activeforeground="white",
            command=self._batch_add_urls
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            batch_ctrl_f, text="Clear", relief="flat",
            font=(UI_FONT, 9), cursor="hand2",
            bg=CLR["panel"], fg=CLR["fg"],
            activebackground=CLR["red"], activeforeground="white",
            command=self._batch_clear
        ).pack(side="left")

        # Queue treeview
        tree_f = tk.Frame(self._batch_frame, bg=CLR["bg"])
        tree_f.pack(fill="both", expand=True)
        cols = ("Title", "URL", "Status")
        self._batch_tree = ttk.Treeview(tree_f, columns=cols, show="headings", height=5)
        for col in cols:
            self._batch_tree.heading(col, text=col)
        self._batch_tree.column("Title",  width=220)
        self._batch_tree.column("URL",    width=280)
        self._batch_tree.column("Status", width=120)
        b_sb = ttk.Scrollbar(tree_f, orient="vertical",
                             command=self._batch_tree.yview)
        self._batch_tree.configure(yscrollcommand=b_sb.set)
        self._batch_tree.pack(side="left", fill="both", expand=True)
        b_sb.pack(side="right", fill="y")

        batch_act_f = tk.Frame(self._batch_frame, bg=CLR["bg"])
        batch_act_f.pack(fill="x", pady=(6, 0))
        self._btn_dl_all = tk.Button(
            batch_act_f, text=t("youtube.download_all"), relief="flat",
            font=(UI_FONT, 10, "bold"), cursor="hand2",
            bg=CLR["green"], fg="white",
            activebackground=CLR["accent"], activeforeground="white",
            command=self._batch_download_all)
        self._btn_dl_all.pack(side="left", padx=(0, 8))
        self._btn_stop_batch = tk.Button(
            batch_act_f, text=t("youtube.stop_batch"), relief="flat",
            font=(UI_FONT, 10), cursor="hand2",
            bg=CLR["red"], fg="white",
            activebackground=CLR["pink"], activeforeground="white",
            state="disabled",
            command=self._batch_stop)
        self._btn_stop_batch.pack(side="left")

    # ── History panel ────────────────────────────────────────────────────────

    def _build_history_panel(self, root):
        hist_hdr = tk.Frame(root, bg=CLR["panel"])
        hist_hdr.pack(fill="x", padx=20, pady=(8, 0))
        self._hist_toggle_btn = tk.Button(
            hist_hdr, text=t("youtube.download_history"),
            font=(UI_FONT, 9, "bold"), relief="flat", cursor="hand2",
            bg=CLR["panel"], fg=CLR["fg"],
            activebackground=CLR["panel"], activeforeground=CLR["accent"],
            command=self._toggle_history, anchor="w")
        self._hist_toggle_btn.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        tk.Button(
            hist_hdr, text=t("youtube.clear_history"), relief="flat",
            font=(UI_FONT, 8), cursor="hand2",
            bg=CLR["panel"], fg=CLR["fgdim"],
            activebackground=CLR["red"], activeforeground="white",
            command=self._clear_history
        ).pack(side="right", padx=6)

        self._hist_body = tk.Frame(root, bg=CLR["bg"])
        self._hist_body.pack(fill="x", padx=20, pady=(0, 10))

        hist_cols = ("Date", "Title", "Duration", "File")
        self._hist_tree = ttk.Treeview(
            self._hist_body, columns=hist_cols, show="headings", height=5)
        for col in hist_cols:
            self._hist_tree.heading(col, text=col)
        self._hist_tree.column("Date",     width=130)
        self._hist_tree.column("Title",    width=260)
        self._hist_tree.column("Duration", width=80)
        self._hist_tree.column("File",     width=220)
        hist_sb = ttk.Scrollbar(self._hist_body, orient="vertical",
                                command=self._hist_tree.yview)
        self._hist_tree.configure(yscrollcommand=hist_sb.set)
        self._hist_tree.pack(side="left", fill="both", expand=True)
        hist_sb.pack(side="right", fill="y")
        self._hist_tree.bind("<Double-1>", self._on_history_dclick)
        self._refresh_history_tree()

    # ─────────────────────────────────────────────────────────────────────────
    #  Startup check
    # ─────────────────────────────────────────────────────────────────────────

    def _check_ytdlp(self):
        p = _find_ytdlp()
        if p:
            # Query the exact version directly from the CLI
            try:
                r = subprocess.run([p, "--version"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                ver = r.stdout.strip()
                self.log_tagged(self.console, f"✔ yt-dlp found (v{ver}).", "success")
                
                # Safely pass it to the Main UI's status bar!
                try:
                    self.winfo_toplevel().set_ytdlp_status(ver, p)
                except Exception:
                    pass
            except Exception:
                self.log_tagged(self.console, "✔ yt-dlp found.", "success")
        else:
            self.log_tagged(
                self.console,
                "⚠  yt-dlp not found.  Options:\n"
                "   • pip install yt-dlp\n"
                "   • Download yt-dlp.exe → place in bin/ next to ffmpeg.exe\n"
                "   • https://github.com/yt-dlp/yt-dlp/releases\n",
                "warn")

    # ─────────────────────────────────────────────────────────────────────────
    #  Event handlers - simple
    # ─────────────────────────────────────────────────────────────────────────

    def _on_trim_toggle(self):
        state = "normal" if self._trim_var.get() else "disabled"
        self._start_ent.config(state=state)
        self._end_ent.config(state=state)

    def _open_browser(self):
        url = self._url_var.get().strip()
        if url:
            webbrowser.open(url)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"),
                       ("WebM", "*.webm"), (t("youtube.all_files"), t("ducker.item_2"))])
        if p:
            self._out_var.set(p)

    def _browse_cookies(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("youtube.text_cookies"), "*.txt"), (t("youtube.all_files"), t("ducker.item_2"))])
        if p:
            self._cookies_var.set(p)

    def _open_output_folder(self):
        p = self._out_var.get().strip()
        if p:
            folder = os.path.dirname(p) if not os.path.isdir(p) else p
            if os.path.isdir(folder):
                try:
                    from core.hardware import open_in_explorer
                    open_in_explorer(folder)
                except Exception:
                    import subprocess as sp
                    sp.Popen(["explorer", folder])

    def _on_paste(self, event):
        self.after(200, self._auto_fetch_after_paste)

    def _auto_fetch_after_paste(self):
        url = self._url_var.get().strip()
        if url and ("youtube.com" in url or "youtu.be" in url or
                    "vimeo.com" in url or "twitch.tv" in url or
                    "twitter.com" in url or "tiktok.com" in url):
            self._on_fetch()

    def _on_format_selected(self, event=None):
        idx = self._format_cb.current()
        if 0 <= idx < len(self._format_options):
            label, _ = self._format_options[idx]
            m = re.search(r'~([\d.]+\s*\w+)', label)
            if m:
                self._size_var.set(f"~{m.group(1)}")
            else:
                self._size_var.set("")

    def _on_chapter_select(self, event=None):
        sel = self._chapters_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._chapters_data):
            chap = self._chapters_data[idx]
            self._trim_var.set(True)
            self._on_trim_toggle()
            self._start_var.set(_fmt_dur(chap.get("start_time", 0)))
            self._end_var.set(_fmt_dur(chap.get("end_time", 0)))

    def _toggle_batch(self):
        self._batch_visible = not self._batch_visible
        if self._batch_visible:
            self._batch_frame.pack(fill="x", padx=20, pady=(0, 8))
        else:
            self._batch_frame.pack_forget()

    def _toggle_history(self):
        self._history_visible = not self._history_visible
        if self._history_visible:
            self._hist_body.pack(fill="x", padx=20, pady=(0, 10))
            self._hist_toggle_btn.config(text=t("youtube.download_history"))
        else:
            self._hist_body.pack_forget()
            self._hist_toggle_btn.config(text="▶  " + t("tab.youtube_downloader"))

    def _save_thumbnail(self):
        if self._thumb_photo is None:
            messagebox.showwarning(t("common.warning"), "Fetch video info first.")
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if not p:
            return
        try:
            # PIL required for saving
            from PIL import Image
            img = self._thumb_pil_image
            img.save(p)
            self.log_tagged(self.console, f"✔ Thumbnail saved: {p}", "success")
        except Exception as e:
            messagebox.showerror(t("common.error"), f"Could not save thumbnail:\n{e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Format filter
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_format_filter(self):
        flt = self._filter_var.get()
        if not self._format_options:
            return
        filtered = []
        for label, fmt_str in self._format_options:
            if flt == "All":
                filtered.append(label)
            elif flt == "4K" and "2160p" in label:
                filtered.append(label)
            elif flt == "1080p" and "1080p" in label:
                filtered.append(label)
            elif flt == "720p" and "720p" in label:
                filtered.append(label)
            elif flt == "480p" and "480p" in label:
                filtered.append(label)
            elif flt == "Audio only" and ("audio" in label.lower() or
                                          "(video only" not in label.lower()):
                filtered.append(label)
        if not filtered:
            filtered = [self._format_options[0][0]]
        self._format_cb["values"] = filtered
        self._format_cb.current(0)
        self._size_var.set("")

    # ─────────────────────────────────────────────────────────────────────────
    #  Fetch video info
    # ─────────────────────────────────────────────────────────────────────────

    def _on_fetch(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning(t("common.warning"), "Paste a video URL first.")
            return
        ytdlp = _find_ytdlp()
        if not ytdlp:
            messagebox.showerror(t("common.error"),
                "yt-dlp is required.\n\n"
                "Install:  pip install yt-dlp\n"
                "or place yt-dlp.exe in bin/ next to ffmpeg.exe")
            return
        self._btn_fetch.config(state="disabled", text=t("youtube.fetching"))
        self.log(self.console, f"↳ Fetching info: {url}")
        threading.Thread(
            target=self._fetch_worker, args=(url, ytdlp), daemon=True).start()

    def _fetch_worker(self, url: str, ytdlp: str):
        try:
            from core import network as _net
            # Check playlist flag dynamically
            playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
            cmd = [ytdlp, playlist_flag, "-J", url]
            # Apply user network settings to the info-fetch call too.
            net_args = _net.build_yt_dlp_args()
            if net_args:
                cmd = [ytdlp] + net_args + cmd[1:]
            r = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=45,
                creationflags=CREATE_NO_WINDOW,
                env=_net.subprocess_env())
            if r.returncode != 0:
                snippet = (r.stderr or r.stdout or "")[:600]
                self.after(0, lambda s=snippet: self.log_tagged(
                    self.console, f"⚠ yt-dlp error:\n{s}", "error"))
                return
            info = json.loads(r.stdout)
            self.after(0, lambda i=info: self._populate_info(i))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self.log_tagged(
                self.console, "⚠ Timed out fetching video info.", "error"))
        except Exception as exc:
            self.after(0, lambda e=exc: self.log_tagged(
                self.console, f"⚠ Fetch error: {e}", "error"))
        finally:
            self.after(0, lambda: self._btn_fetch.config(
                state="normal", text=t("youtube.fetch_info")))

    def _populate_info(self, info: dict):
        self._video_info = info
        title   = info.get("title") or "Unknown"
        dur     = info.get("duration") or 0
        channel = info.get("uploader") or info.get("channel") or "-"
        views   = info.get("view_count")
        is_live = bool(info.get("is_live"))

        self._title_var.set(title)
        self._dur_var.set(_fmt_dur(dur))
        self._channel_var.set(channel)
        self._views_var.set(f"{views:,}" if isinstance(views, int) else "-")

        # Live badge + record button
        if is_live:
            self._live_var.set("  ⏺ LIVE  ")
            self._live_badge.pack(side="left", padx=4)
            self._btn_record.config(state="normal")
            self.log_tagged(self.console, "⏺ Live stream detected.", "warn")
        else:
            self._live_var.set("")
            self._live_badge.pack_forget()
            self._btn_record.config(state="disabled")

        self._populate_formats(info.get("formats", []))
        self._populate_chapters(info.get("chapters") or [])
        self._populate_subtitle_langs(info)

        # Auto-suggest output filename. Refresh on every fetch unless the
        # user has manually edited the field since our last suggestion -
        # otherwise the first download's name would stick for every URL
        # afterwards.
        current = self._out_var.get().strip()
        if (not current) or current == self._last_auto_out:
            safe = "".join(
                c if c.isalnum() or c in " _-." else "_" for c in title)[:64]
            dl_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            if self._playlist_var.get():
                new_out = os.path.join(dl_dir, "%(title)s.%(ext)s")
            else:
                new_out = os.path.join(dl_dir, safe.strip("_") + ".mp4")
            self._out_var.set(new_out)
            self._last_auto_out = new_out

        if dur:
            self._end_var.set(_fmt_dur(dur))

        thumb_url = info.get("thumbnail")
        if thumb_url:
            threading.Thread(
                target=self._load_thumbnail, args=(thumb_url,), daemon=True).start()

        self.log_tagged(self.console,
            f"✔ {title}  [{_fmt_dur(dur)}]", "success")

    def _populate_formats(self, formats: list):
        if not formats:
            return
            
        vfmts = sorted(
            [f for f in formats
             if (f.get("vcodec") or "none") != "none" and f.get("height")],
            key=lambda f: (f.get("height", 0), f.get("fps") or 0),
            reverse=True)

        self._format_options = [
            ("⭐  Best available  (auto-select highest quality video + audio)",
             "bestvideo+bestaudio/best"),
        ]
        seen: set = set()
        for f in vfmts:
            fid = f.get("format_id", "?")
            h   = f.get("height", 0)
            fps = int(f.get("fps") or 0)
            ext = f.get("ext", "?")
            vc  = (f.get("vcodec") or "?").split(".")[0]
            ac  = f.get("acodec") or "none"
            fs  = f.get("filesize") or f.get("filesize_approx")

            key = (h, fps, ext, vc)
            if key in seen:
                continue
            seen.add(key)

            has_audio = ac and ac != "none"
            fps_s  = f"  {fps}fps" if fps else ""
            size_s = f"  ~{fs / 1_000_000:.0f} MB" if fs else ""
            aud_s  = "  +audio" if has_audio else "  (video only, audio auto-added)"
            label  = f"{h}p{fps_s}  ·  {ext}  ·  {vc}{aud_s}{size_s}  [id {fid}]"
            fmt_str = fid if has_audio else f"{fid}+bestaudio/best"
            self._format_options.append((label, fmt_str))

        self._format_cb["values"] = [o[0] for o in self._format_options]
        self._format_cb.current(0)
        self._size_var.set("")

    def _populate_chapters(self, chapters: list):
        self._chapters_data = chapters
        self._chapters_lb.delete(0, tk.END)
        for ch in chapters:
            st = _fmt_dur(ch.get("start_time", 0))
            title = ch.get("title", "")
            self._chapters_lb.insert(tk.END, f"{st}  {title}")

    def _populate_subtitle_langs(self, info: dict):
        manual_langs = set(info.get("subtitles", {}).keys())
        auto_langs   = set(info.get("automatic_captions", {}).keys())
        all_langs = sorted(manual_langs | auto_langs)
        labeled = []
        for lang in all_langs:
            if lang in manual_langs:
                labeled.append(lang)
            else:
                labeled.append(f"(auto) {lang}")
        if labeled:
            self._sub_lang_cb["values"] = labeled
            if "en" in manual_langs:
                self._sub_lang_var.set("en")
            elif labeled:
                self._sub_lang_var.set(labeled[0])

    def _load_thumbnail(self, thumb_url: str):
        # Pillow is an optional dep - try the project's auto-install helper
        # first, then a plain import as a fallback. If both fail, surface
        # the reason instead of silently leaving the canvas blank.
        Image = ImageTk = None
        try:
            from core.deps import require
            pil = require("Pillow", import_name="PIL")
            if pil is not None:
                from PIL import Image as _Image, ImageTk as _ImageTk
                Image, ImageTk = _Image, _ImageTk
        except Exception:
            pass
        if Image is None:
            try:
                from PIL import Image as _Image, ImageTk as _ImageTk
                Image, ImageTk = _Image, _ImageTk
            except ImportError:
                self.after(0, lambda: self._set_thumbnail_message(
                    "Pillow not installed\n(pip install Pillow)\n\n"
                    "Thumbnails disabled"))
                self.after(0, lambda: self.log_tagged(
                    self.console,
                    "ℹ Thumbnail preview disabled: Pillow could not be "
                    "loaded or auto-installed. Run `pip install Pillow` "
                    "to enable.",
                    "warn"))
                return
        try:
            from core import network as _net
            with _net.urlopen(thumb_url, timeout=12,
                              headers={"User-Agent": "Mozilla/5.0"}) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data)).convert("RGB")
            self._thumb_pil_image = img.copy()
            img = img.resize((256, 144), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.after(0, lambda p=photo: self._set_thumbnail(p))
        except Exception as exc:
            err = str(exc) or type(exc).__name__
            self.after(0, lambda e=err: self._set_thumbnail_message(
                f"Thumbnail failed:\n{e[:80]}"))
            self.after(0, lambda e=err: self.log_tagged(
                self.console, f"⚠ Thumbnail load error: {e}", "warn"))

    def _set_thumbnail(self, photo):
        self._thumb_photo = photo
        self._thumb_canvas.delete("all")
        self._thumb_canvas.create_image(0, 0, anchor="nw", image=photo)

    def _set_thumbnail_message(self, msg: str):
        """Render a short status message into the thumbnail canvas."""
        try:
            self._thumb_canvas.delete("all")
            self._thumb_canvas.create_text(
                128, 72, text=msg, fill=CLR["fgdim"],
                font=(UI_FONT, 9), justify="center", width=240)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Preview
    # ─────────────────────────────────────────────────────────────────────────

    def _preview(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning(t("common.warning"), "Paste a video URL first.")
            return
        ytdlp = _find_ytdlp()
        if not ytdlp:
            self._open_browser()
            return
        self._btn_preview.config(state="disabled", text=t("youtube.loading"))
        self.log(self.console, t("log.youtube.resolving_stream_for_preview"))

        def _worker():
            try:
                from core import network as _net
                playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
                r = subprocess.run(
                    [ytdlp] + _net.build_yt_dlp_args() + [playlist_flag, "-g",
                     "-f", "best[height<=720][ext=mp4]/best[height<=720]/best",
                     url],
                    capture_output=True, text=True, timeout=25,
                    creationflags=CREATE_NO_WINDOW,
                    env=_net.subprocess_env())
                lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                if not lines:
                    self.after(0, lambda: self.log_tagged(
                        self.console,
                        "⚠ Could not resolve stream URL for preview.", "error"))
                    return
                stream_url = lines[0]
                try:
                    ffplay = get_binary_path("ffplay")
                except Exception:
                    ffplay = shutil.which("ffplay") or "ffplay"
                self.preview_proc = subprocess.Popen(
                    [ffplay, "-autoexit",
                     "-window_title", "Video Preview - Quintessential Video Editor",
                     stream_url],
                    creationflags=CREATE_NO_WINDOW,
                    env=_net.subprocess_env())
                self.after(0, lambda: self.log_tagged(
                    self.console, "▶ Playing in ffplay.", "info"))
            except Exception as exc:
                self.after(0, lambda e=exc: self.log_tagged(
                    self.console, f"⚠ Preview error: {e}", "error"))
            finally:
                self.after(0, lambda: self._btn_preview.config(
                    state="normal", text=t("youtube.preview")))

        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  Live recording
    # ─────────────────────────────────────────────────────────────────────────

    def _start_record(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning(t("common.warning"), "Paste a live stream URL first.")
            return
        ytdlp = _find_ytdlp()
        if not ytdlp:
            messagebox.showerror(t("common.error"), "Install yt-dlp first.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        out_template = os.path.join(out_dir, f"recording_{ts}.%(ext)s")

        from core import network as _net
        cmd = [ytdlp] + _net.build_yt_dlp_args() + [
               "-f", "best", "--live-from-start",
               "-o", out_template, url]

        ff_dir = _ffmpeg_dir()
        if ff_dir:
            cmd += ["--ffmpeg-location", ff_dir]

        self.log(self.console, f"⏺ Starting live recording → {out_template}")
        self._btn_record.config(state="disabled", text=t("youtube.recording"))
        self._record_start = time.time()

        def _worker():
            try:
                self._record_proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
                    env=_net.subprocess_env())
                for line in iter(self._record_proc.stdout.readline, ""):
                    stripped = line.rstrip()
                    if stripped:
                        elapsed = int(time.time() - self._record_start)
                        h, r = divmod(elapsed, 3600)
                        m, s = divmod(r, 60)
                        et = f"[{h:02d}:{m:02d}:{s:02d}]"
                        self.after(0, lambda msg=f"{et} {stripped}":
                                   self.log(self.console, msg))
                self._record_proc.stdout.close()
                self._record_proc.wait()
            except Exception as exc:
                self.after(0, lambda e=exc: self.log_tagged(
                    self.console, f"⚠ Record error: {e}", "error"))
            finally:
                self.after(0, lambda: self._btn_record.config(
                    state="normal", text=t("youtube.record")))
                self._record_proc = None

        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  yt-dlp streaming subprocess
    # ─────────────────────────────────────────────────────────────────────────

    def _stream_ytdlp(self, cmd: list,
                      on_line=None, on_progress=None, on_done=None):
        """Run yt-dlp; parse progress lines; call callbacks. Blocks until done."""
        from core import network as _net
        self.after(0, lambda: self.log(self.console, "CMD: " + " ".join(str(c) for c in cmd)))
        try:
            self._active_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
                env=_net.subprocess_env())
            for line in iter(self._active_proc.stdout.readline, ""):
                stripped = line.rstrip()
                if not stripped:
                    continue
                m = _DL_PROGRESS_RE.search(stripped)
                if m and on_progress:
                    pct  = float(m.group(1))
                    size = m.group(2).strip()
                    spd  = m.group(3).strip()
                    eta  = m.group(4).strip()
                    self.after(0, lambda p=pct, sz=size, sp=spd, et=eta:
                               on_progress(p, sz, sp, et))
                else:
                    if on_line:
                        self.after(0, lambda s=stripped: on_line(s))
                    else:
                        self.after(0, lambda s=stripped: self.log(self.console, s))
            self._active_proc.stdout.close()
            self._active_proc.wait()
            rc = self._active_proc.returncode
        except Exception as exc:
            self.after(0, lambda e=exc: self.log_tagged(
                self.console, f"⚠ yt-dlp error: {e}", "error"))
            rc = 1
        finally:
            self._active_proc = None

        if on_done:
            self.after(0, lambda c=rc: on_done(c))

    def _on_progress_update(self, pct: float, size: str, speed: str, eta: str):
        self._progress["value"] = pct
        self._prog_status_var.set(
            f"{pct:.1f}%  {size}  {speed}/s  ETA {eta}")

    def _cancel_download(self):
        # yt-dlp typically spawns ffmpeg (and optionally aria2c) as child
        # processes. proc.terminate() only kills yt-dlp itself, leaving the
        # children running and the download effectively continuing. Kill
        # the whole process tree instead.
        proc = self._active_proc
        if proc:
            try:
                self._kill_process_tree(proc)
            except Exception as exc:
                self.log_tagged(
                    self.console, f"⚠ Cancel error: {exc}", "warn")
        self._batch_running = False
        self.log_tagged(self.console, "⏹ Download cancelled.", "warn")
        self._reset_download_ui()

    def _kill_process_tree(self, proc):
        """Best-effort kill of *proc* and all of its descendants."""
        if proc is None or proc.poll() is not None:
            return
        pid = proc.pid
        import sys as _sys
        if _sys.platform == "win32":
            # taskkill /F /T kills the process tree forcefully.
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                # Fallback to plain terminate if taskkill is unavailable.
                try:
                    proc.terminate()
                except Exception:
                    pass
        else:
            # POSIX: signal the whole process group.
            try:
                import os as _os
                import signal as _signal
                _os.killpg(_os.getpgid(pid), _signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _reset_download_ui(self):
        self._btn_dl.config(state="normal", text=t("youtube.download"))
        self._btn_cancel.config(state="disabled")
        self._progress["value"] = 0
        self._prog_status_var.set("")

    # ─────────────────────────────────────────────────────────────────────────
    #  Build extra yt-dlp args
    # ─────────────────────────────────────────────────────────────────────────

    def _build_common_ytdlp_args(self) -> list:
        # Start with the app-wide network settings (proxy, rate limit,
        # timeout, IP version, source address, user agent, SSL verify).
        # Any per-tab overrides below come later in the argv so yt-dlp
        # picks them up as the winning value.
        from core import network as _net
        args = list(_net.build_yt_dlp_args())
        # Auth / Network
        cookies = self._cookies_var.get().strip()
        if cookies and os.path.isfile(cookies):
            args += ["--cookies", cookies]
        username = self._username_var.get().strip()
        if username:
            args += ["--username", username]
        password = self._password_var.get().strip()
        if password:
            args += ["--password", password]
        ratelimit = self._ratelimit_var.get().strip()
        if ratelimit:
            args += ["--rate-limit", ratelimit]
        proxy = self._proxy_var.get().strip()
        if proxy:
            args += ["--proxy", proxy]
            
        # Advanced Networking
        if self._use_aria2c_var.get():
            args += ["--downloader", "aria2c", "--downloader-args", "aria2c:-x 16 -s 16 -k 1M"]
            
        # Metadata
        if self._embed_chapters_var.get():
            args += ["--embed-chapters"]
        if self._embed_metadata_var.get():
            args += ["--embed-metadata"]
            
        # SponsorBlock
        sb_cats = [k for k, v in self._sb_vars.items() if v.get()]
        if sb_cats:
            cat_str = ",".join(sb_cats)
            if self._sb_action_var.get() == "mark":
                args += ["--sponsorblock-mark", cat_str]
            else:
                args += ["--sponsorblock-remove", cat_str]
                
        # Custom arguments 
        custom_args = self._custom_args_var.get().strip()
        if custom_args:
            args += shlex.split(custom_args)
            
        return args

    def _build_trim_args(self) -> list | None:
        """Returns trim args or None. Returns False-y empty list if no trim."""
        if not self._trim_var.get():
            return []
        s0 = _parse_time(self._start_var.get())
        s1 = _parse_time(self._end_var.get())
        if s1 <= s0:
            messagebox.showwarning(t("common.warning"), "'To' must be after 'From'.")
            return None
        return ["--download-sections", f"*{s0:.3f}-{s1:.3f}",
                "--force-keyframes-at-cuts"]

    # ─────────────────────────────────────────────────────────────────────────
    #  FFmpeg encode command builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_encode_cmd(self, inp: str, out: str,
                          sub_path: str = "") -> list:
        ffmpeg = _ffmpeg_exe()
        cmd = [ffmpeg, "-i", inp]

        vcodec = self._vcodec_var.get()
        acodec = self._acodec_var.get()
        container = self._container_var.get()
        preset = self._preset_var.get()
        res = self._res_var.get()
        abitrate = self._abitrate_var.get()
        asamplerate = self._asamplerate_var.get()
        crf = int(self._crf_var.get())

        # Video codec
        if vcodec == "copy":
            cmd += ["-c:v", "copy"]
        elif vcodec == "prores_ks":
            cmd += ["-c:v", "prores_ks", "-profile:v", "3"]
        elif vcodec == "libsvtav1":
            cmd += ["-c:v", "libsvtav1", "-preset", "4", "-crf", str(crf)]
        elif vcodec == "libvpx-vp9":
            cmd += ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
                    "-deadline", "good", "-cpu-used", "2"]
        else:
            cmd += ["-c:v", vcodec, "-crf", str(crf), "-preset", preset]

        # Resolution scaling
        if res != "Original":
            if res == "Custom…":
                custom = self._custom_res_var.get().strip()
                # Accept both 1280x720 and 1280×720
                custom = custom.replace("×", "x")
                parts = custom.split("x")
                if len(parts) == 2:
                    w, h = parts[0].strip(), parts[1].strip()
                    cmd += ["-vf", f"scale={w}:{h}"]
            else:
                res_clean = res.replace("×", "x")
                parts = res_clean.split("x")
                if len(parts) == 2:
                    cmd += ["-vf", f"scale={parts[0]}:{parts[1]}"]

        # Subtitle burn-in (overrides plain vf, append to filter chain)
        if sub_path and os.path.isfile(sub_path):
            escaped = sub_path.replace("\\", "/").replace(":", "\\:")
            # Check if we already added -vf
            if "-vf" in cmd:
                vi = cmd.index("-vf")
                existing = cmd[vi + 1]
                cmd[vi + 1] = f"{existing},subtitles={escaped}"
            else:
                cmd += ["-vf", f"subtitles={escaped}"]

        # Audio codec
        if acodec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", acodec]
            if acodec in ("aac", "libmp3lame", "libopus", "libvorbis"):
                cmd += ["-b:a", abitrate]
            if acodec != "flac":
                cmd += ["-ar", asamplerate]

        # Container extras
        if container == "mp4":
            cmd += ["-movflags", "+faststart"]

        cmd += [out, "-y"]
        return cmd

    # ─────────────────────────────────────────────────────────────────────────
    #  Main download entry point
    # ─────────────────────────────────────────────────────────────────────────

    def _download(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning(t("common.warning"), "Paste a video URL first.")
            return
        out = self._out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(
                defaultextension=".mp4",
                filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"),
                           (t("youtube.all_files"), t("ducker.item_2"))])
        if not out:
            return
        self._out_var.set(out)

        ytdlp = _find_ytdlp()
        if not ytdlp:
            messagebox.showerror(t("common.error"),
                "Install:  pip install yt-dlp\n"
                "or place yt-dlp.exe in bin/ next to ffmpeg.exe")
            return

        trim_args = self._build_trim_args()
        if trim_args is None:
            return

        mode = self._dl_mode.get()
        self._btn_dl.config(state="disabled", text=t("youtube.downloading"))
        self._btn_cancel.config(state="normal")
        self._progress["value"] = 0
        self._prog_status_var.set("Starting…")

        if mode == "audio":
            threading.Thread(
                target=self._run_audio_only,
                args=(url, out, ytdlp, trim_args), daemon=True).start()
        elif mode == "encode":
            threading.Thread(
                target=self._run_reencode,
                args=(url, out, ytdlp, trim_args), daemon=True).start()
        else:
            threading.Thread(
                target=self._run_direct_copy,
                args=(url, out, ytdlp, trim_args), daemon=True).start()

    # ── Direct copy ──────────────────────────────────────────────────────────

    def _run_direct_copy(self, url: str, out: str,
                         ytdlp: str, trim_args: list):
        idx = self._format_cb.current()
        fmt_str = (self._format_options[idx][1]
                   if 0 <= idx < len(self._format_options)
                   else "bestvideo+bestaudio/best")
        container = self._container_var.get()
        ff_dir = _ffmpeg_dir()

        playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
        cmd = [ytdlp, playlist_flag,
               "-f", fmt_str,
               "--merge-output-format", container,
               "--force-overwrites"]
        if ff_dir:
            cmd += ["--ffmpeg-location", ff_dir]

        # Subtitles
        if self._dl_subs_var.get():
            lang = self._sub_lang_var.get().replace("(auto) ", "")
            cmd += ["--write-sub", "--sub-lang", lang,
                    "--sub-format", self._sub_fmt_var.get()]
            if self._sub_auto_var.get():
                cmd += ["--write-auto-sub"]
            if self._embed_subs_var.get():
                cmd += ["--embed-subs"]

        cmd += self._build_common_ytdlp_args()
        cmd += trim_args
        cmd += ["-o", out, url]

        self._stream_ytdlp(
            cmd,
            on_line=lambda s: self.log(self.console, s),
            on_progress=self._on_progress_update,
            on_done=lambda rc: self._on_single_done(rc, out))

    # ── Audio only ───────────────────────────────────────────────────────────

    def _run_audio_only(self, url: str, out: str,
                        ytdlp: str, trim_args: list):
        audio_fmt = self._audio_fmt_var.get()
        quality   = self._audio_quality_var.get().split()[0]
        ff_dir    = _ffmpeg_dir()

        # Derive output path with audio extension
        base = os.path.splitext(out)[0]
        audio_out = base + "." + audio_fmt

        playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
        cmd = [ytdlp, playlist_flag, "-x",
               "--audio-format", audio_fmt,
               "--audio-quality", quality,
               "--force-overwrites"]
        if ff_dir:
            cmd += ["--ffmpeg-location", ff_dir]
        if self._embed_thumb_var.get():
            cmd += ["--embed-thumbnail"]
        if self._add_metadata_var.get():
            cmd += ["--add-metadata"]

        cmd += self._build_common_ytdlp_args()
        cmd += trim_args
        cmd += ["-o", audio_out, url]

        # Mirror the post-processed audio path back into the box, and treat
        # it as still auto-managed so the next fetched URL refreshes it.
        def _sync_audio_out(p=audio_out):
            self._out_var.set(p)
            self._last_auto_out = p
        self.after(0, _sync_audio_out)
        self._stream_ytdlp(
            cmd,
            on_line=lambda s: self.log(self.console, s),
            on_progress=self._on_progress_update,
            on_done=lambda rc: self._on_single_done(rc, audio_out))

    # ── Re-encode ────────────────────────────────────────────────────────────

    def _run_reencode(self, url: str, out: str,
                      ytdlp: str, trim_args: list):
        tmp = os.path.join(tempfile.gettempdir(), f"_cf_yt_tmp_{os.getpid()}.mkv")
        ff_dir = _ffmpeg_dir()

        playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
        cmd = [ytdlp, playlist_flag,
               "-f", t("youtube.bestvideo_bestaudio_best"),
               "--merge-output-format", "mkv",
               "--force-overwrites"]
        if ff_dir:
            cmd += ["--ffmpeg-location", ff_dir]
        cmd += self._build_common_ytdlp_args()
        cmd += trim_args
        cmd += ["-o", tmp, url]

        # Phase 1: download
        self.after(0, lambda: self.log(self.console,
                                       t("log.youtube.downloading_best_quality")))

        def _dl_done(rc: int):
            if rc != 0:
                self.log_tagged(self.console,
                                f"⚠ Download failed (code {rc})", "error")
                self._reset_download_ui()
                return
            self.log(self.console, t("log.youtube.re_encoding_with_ffmpeg"))
            self._btn_dl.config(text=t("youtube.encoding"))
            self._progress["value"] = 0
            self._prog_status_var.set("Encoding…")

            # Phase 2: optional sub burn-in
            sub_path = ""
            if self._dl_subs_var.get() and self._burn_subs_var.get():
                sub_path = self._download_sub_for_burn(url, ytdlp)

            enc_cmd = self._build_encode_cmd(tmp, out, sub_path=sub_path)
            threading.Thread(
                target=self._run_ffmpeg_encode,
                args=(enc_cmd, tmp, out), daemon=True).start()

        self._stream_ytdlp(
            cmd,
            on_line=lambda s: self.log(self.console, s),
            on_progress=self._on_progress_update,
            on_done=_dl_done)

    def _download_sub_for_burn(self, url: str, ytdlp: str) -> str:
        """Download subtitle to a temp file and return the path."""
        lang = self._sub_lang_var.get().replace("(auto) ", "")
        sub_fmt = self._sub_fmt_var.get()
        tmp_dir = tempfile.mkdtemp(prefix="cf_subs_")
        tmp_base = os.path.join(tmp_dir, "sub")
        
        from core import network as _net
        playlist_flag = "--yes-playlist" if self._playlist_var.get() else "--no-playlist"
        cmd = [ytdlp] + _net.build_yt_dlp_args() + [playlist_flag, "--write-sub",
               "--skip-download",
               "--sub-lang", lang,
               "--sub-format", sub_fmt,
               "-o", tmp_base, url]
        if self._sub_auto_var.get():
            cmd.insert(-3, "--write-auto-sub")
        try:
            subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=CREATE_NO_WINDOW,
                           env=_net.subprocess_env())
        except Exception:
            pass
        # Find the downloaded sub file
        for fname in os.listdir(tmp_dir):
            if fname.startswith("sub") and fname.endswith(
                    ("." + sub_fmt, ".srt", ".vtt", ".ass")):
                return os.path.join(tmp_dir, fname)
        return ""

    def _run_ffmpeg_encode(self, cmd: list, tmp: str, out: str):
        total_dur = self._video_info.get("duration", 0) or 0

        def _worker(progress_cb, cancel_fn):
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
                self._active_proc = proc
                for line in iter(proc.stdout.readline, ""):
                    if cancel_fn():
                        proc.terminate()
                        self._active_proc = None
                        return -1
                    stripped = line.rstrip()
                    if not stripped:
                        continue
                    m = _FFMPEG_TIME_RE.search(stripped)
                    if m and total_dur > 0:
                        elapsed = (int(m.group(1)) * 3600 +
                                   int(m.group(2)) * 60 +
                                   float(m.group(3)))
                        pct = min(100.0, (elapsed / total_dur) * 100)
                        self.after(0, lambda p=pct, t=elapsed:
                                   self._on_encode_progress(p, t, total_dur))
                    else:
                        progress_cb(stripped)
                proc.stdout.close()
                proc.wait()
                rc = proc.returncode
            except Exception as exc:
                self.after(0, lambda e=exc: self.log_tagged(
                    self.console, f"⚠ Encode error: {e}", "error"))
                rc = 1
            finally:
                self._active_proc = None
            return rc

        def _on_done(task_id, rc):
            try:
                os.remove(tmp)
            except Exception:
                pass
            self.after(0, lambda c=rc: self._on_single_done(c, out))

        self.enqueue_render(
            f"YT Encode: {os.path.basename(out)}",
            output_path=out,
            worker_fn=_worker,
            on_progress=lambda tid, line: self.after(0, lambda s=line: self.log(self.console, s)),
            on_complete=_on_done,
        )

    def _on_encode_progress(self, pct: float, elapsed: float, total: float):
        self._progress["value"] = pct
        remaining = max(0, total - elapsed)
        h, r = divmod(int(remaining), 3600)
        m, s = divmod(r, 60)
        self._prog_status_var.set(
            f"Encoding {pct:.1f}%  ETA {h:02d}:{m:02d}:{s:02d}")

    # ─────────────────────────────────────────────────────────────────────────
    #  Post-download
    # ─────────────────────────────────────────────────────────────────────────

    def _on_single_done(self, rc: int, out_path: str):
        self._reset_download_ui()
        if rc == 0:
            self._progress["value"] = 100
            self._prog_status_var.set("✔ Complete!")
            self.log_tagged(self.console, f"✔ Saved: {out_path}", "success")
            title    = self._title_var.get()
            duration = self._dur_var.get()
            url      = self._url_var.get().strip()
            self._append_history(title, duration, url, out_path)
            self.show_result(0, out_path)
        else:
            self._prog_status_var.set(f"✘ Error (code {rc})")
            self.log_tagged(self.console, f"⚠ Failed (code {rc})", "error")

    # ─────────────────────────────────────────────────────────────────────────
    #  Batch queue
    # ─────────────────────────────────────────────────────────────────────────

    def _batch_add_urls(self):
        raw = self._batch_text.get("1.0", tk.END).strip()
        urls = [l.strip() for l in raw.splitlines() if l.strip()]
        for url in urls:
            self._batch_tree.insert("", tk.END, values=("-", url, "Queued"))
        self._batch_text.delete("1.0", tk.END)

    def _batch_clear(self):
        for item in self._batch_tree.get_children():
            self._batch_tree.delete(item)

    def _batch_download_all(self):
        items = self._batch_tree.get_children()
        if not items:
            messagebox.showwarning(t("common.warning"), "Add URLs to the queue first.")
            return
        ytdlp = _find_ytdlp()
        if not ytdlp:
            messagebox.showerror(t("common.error"),
                "Install yt-dlp first.")
            return
        self._batch_running = True
        self._btn_dl_all.config(state="disabled")
        self._btn_stop_batch.config(state="normal")
        threading.Thread(
            target=self._batch_worker, args=(items, ytdlp), daemon=True).start()

    def _batch_worker(self, items, ytdlp: str):
        for item in items:
            if not self._batch_running:
                break
            vals = self._batch_tree.item(item, "values")
            url  = vals[1] if vals else ""
            if not url:
                continue

            self.after(0, lambda i=item: self._batch_tree.item(
                i, values=(self._batch_tree.item(i, "values")[0],
                            self._batch_tree.item(i, "values")[1],
                            "Fetching…")))

            # Quick title fetch
            title = "-"
            try:
                r = subprocess.run(
                    [ytdlp, "--no-playlist", "--get-title", url],
                    capture_output=True, text=True, timeout=20,
                    creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0:
                    title = r.stdout.strip().splitlines()[0][:60]
            except Exception:
                pass

            self.after(0, lambda i=item, t=title: self._batch_tree.item(
                i, values=(t,
                            self._batch_tree.item(i, "values")[1],
                            "Downloading…")))

            dl_dir   = os.path.join(os.path.expanduser("~"), "Downloads")
            out_path = os.path.join(dl_dir, "%(title)s.%(ext)s")
            ff_dir   = _ffmpeg_dir()

            cmd = [ytdlp, "--yes-playlist",
                   "-f", t("youtube.bestvideo_bestaudio_best"),
                   "--merge-output-format", self._container_var.get(),
                   "--force-overwrites"]
            if ff_dir:
                cmd += ["--ffmpeg-location", ff_dir]
            cmd += self._build_common_ytdlp_args()
            cmd += ["-o", out_path, url]

            rc = self._run_ytdlp_sync_batch(cmd)
            status = "✔ Done" if rc == 0 else f"✘ Error ({rc})"

            self.after(0, lambda i=item, t=title, s=status:
                       self._batch_tree.item(i, values=(t,
                           self._batch_tree.item(i, "values")[1], s)))
            if rc == 0:
                self._append_history(title, "-", url, dl_dir)

        self.after(0, self._batch_finished)

    def _run_ytdlp_sync_batch(self, cmd: list) -> int:
        from core import network as _net
        self.after(0, lambda: self.log(self.console, "BATCH CMD: " + " ".join(cmd)))
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
                env=_net.subprocess_env())
            self._active_proc = proc
            for line in iter(proc.stdout.readline, ""):
                stripped = line.rstrip()
                if stripped:
                    m = _DL_PROGRESS_RE.search(stripped)
                    if m:
                        pct = float(m.group(1))
                        spd = m.group(3).strip()
                        self.after(0, lambda p=pct, s=spd:
                                   self._on_progress_update(p, "-", s, "-"))
                    else:
                        self.after(0, lambda s=stripped: self.log(self.console, s))
            proc.stdout.close()
            proc.wait()
            self._active_proc = None
            return proc.returncode
        except Exception as exc:
            self.after(0, lambda e=exc: self.log_tagged(
                self.console, f"⚠ Batch error: {e}", "error"))
            self._active_proc = None
            return 1

    def _batch_stop(self):
        self._batch_running = False
        proc = self._active_proc
        if proc:
            try:
                self._kill_process_tree(proc)
            except Exception:
                pass
        self.log_tagged(self.console, "⏹ Batch stopped.", "warn")

    def _batch_finished(self):
        self._batch_running = False
        self._btn_dl_all.config(state="normal")
        self._btn_stop_batch.config(state="disabled")
        self._progress["value"] = 0
        self._prog_status_var.set("Batch complete.")
        self.log_tagged(self.console, "✔ Batch download finished.", "success")

    # ─────────────────────────────────────────────────────────────────────────
    #  History
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_history_tree(self):
        for item in self._hist_tree.get_children():
            self._hist_tree.delete(item)
        for entry in reversed(self._history[-200:]):
            ts    = entry.get("ts", "")
            title = entry.get("title", "")
            dur   = entry.get("duration", "")
            fpath = entry.get("file", "")
            self._hist_tree.insert(
                "", tk.END,
                values=(ts, title[:50], dur, fpath),
                tags=("entry",))

    def _on_history_dclick(self, event):
        sel = self._hist_tree.selection()
        if not sel:
            return
        vals = self._hist_tree.item(sel[0], "values")
        fpath = vals[3] if vals and len(vals) > 3 else ""
        if not fpath:
            return
        folder = os.path.dirname(fpath) if os.path.isfile(fpath) else fpath
        if os.path.isdir(folder):
            try:
                from core.hardware import open_in_explorer
                open_in_explorer(folder)
            except Exception:
                import subprocess as sp
                sp.Popen(["explorer", folder])

    def _clear_history(self):
        if messagebox.askyesno(t("msg.clear_history_title"), t("msg.delete_all_history")):
            self._history = []
            self._save_history()
            self._refresh_history_tree()