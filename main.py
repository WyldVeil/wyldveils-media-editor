"""
main.py  -  Quintessential Video Editor  ·  Version 1.14
Application entry point. Builds the professional dark sidebar, registers
every tab, and manages page navigation, search, and preview cleanup.
"""
import tkinter as tk
from tkinter import messagebox, ttk
import ctypes
import sys
import os
import subprocess
import threading
import platform

from core import APP_VERSION
from core.state import state as _app_state
from core.hardware import get_binary_path, download_and_extract_ffmpeg, CREATE_NO_WINDOW
from core.i18n import t, init as _i18n_init

# Initialise i18n before any UI is constructed
_i18n_init()

# ── Platform constants ────────────────────────────────────────────────────────
_IS_MAC = platform.system() == "Darwin"

# ── High-DPI fix (Windows only) ───────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)        # type: ignore[attr-defined]
except Exception:
    pass

# ── Skin engine ───────────────────────────────────────────────────────────────
from core.skins import (apply_skin, apply_default_options,
                         load_skin_name, get_skin, UI_FONT, MONO_FONT)

# ── Tab registry (single source of truth for all tool tabs) ──────────────────
from tabs.registry import TOOLS, PINNED, HIDDEN

# ── Sidebar width ─────────────────────────────────────────────────────────────
SB_WIDTH = 272

# ── Category header → i18n key ────────────────────────────────────────────────
_CAT_I18N = {
    "✂  CUTTING ROOM":       "cat.cutting",
    "📱  SOCIAL & FORMAT":   "cat.social",
    "🔊  AUDIO ENGINEERING": "cat.audio",
    "⚙  TRANSCODER":         "cat.transcoder",
    "🎨  COLOR & VISUALS":   "cat.visuals",
    "🛠  SYSTEM":             "cat.system",
}

def _cat_label(category: str) -> str:
    """Return the translated category header (uppercase) for display."""
    key = _CAT_I18N.get(category.strip())
    if key:
        return t(key).upper()
    return category.strip().upper()

def _tab_label(name: str) -> str:
    """Return the translated display name for a sidebar tool button."""
    import re
    slug = re.sub(r'_+', '_',
        name.lower()
            .replace(' ', '_').replace('-', '_')
            .replace('/', '_').replace('&', '').strip('_'))
    translated = t("tab." + slug)
    # t() returns the key itself when not found - fall back to original name
    return translated if not translated.startswith("tab.") else name


class PlaceholderTab(ttk.Frame):
    """Shown for any tab whose class failed to initialise."""
    def __init__(self, parent, title):
        super().__init__(parent)
        tk.Label(self, text="⚙  {}".format(title),
                 font=(UI_FONT, 22, "bold"), fg="#404040").pack(pady=(140, 12))
        tk.Label(self, text=t("app.under_construction"),
                 font=(UI_FONT, 12), fg="#505050").pack()


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Quintessential Video Editor  ·  Version 1.14")
        self.geometry("1480x920")
        self.minsize(1100, 700)

        # ── Global state ──────────────────────────────────────────────────────
        self.debug_mode = tk.BooleanVar(value=False)
        self._ytdlp_path = None
        # Latest known versions (set by background fetches). Used by the
        # status-bar click handlers to decide whether to offer an update or
        # just confirm the local copy is current.
        self._ffmpeg_latest_version: str | None = None
        self._ytdlp_latest_version:  str | None = None
        self._ffmpeg_local_version:  str | None = None
        self._ytdlp_local_version:   str | None = None

        # ── Load skin FIRST - cascade options before any tab widget is created ─
        self._skin_data = get_skin(load_skin_name())
        apply_default_options(self, self._skin_data)

        # ── ttk Style ─────────────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use("clam")
        from core.skins import _apply_ttk_styles
        _apply_ttk_styles(self._skin_data)

        # ── Status bar (at the very bottom, before content) ───────────────────
        self._build_status_bar()

        # ── Root frame that holds sidebar + content ───────────────────────────
        root_frame = tk.Frame(self, bg=self._skin_data["sb_bg"])
        root_frame.pack(fill="both", expand=True)

        self.sidebar_container = tk.Frame(
            root_frame, bg=self._skin_data["sb_bg"], width=SB_WIDTH)
        self.sidebar_container.pack(side="left", fill="y")
        self.sidebar_container.pack_propagate(False)

        # 1-pixel separator between sidebar and content
        tk.Frame(root_frame,
                 bg=self._skin_data.get("border", "#2C2C2C"),
                 width=1).pack(side="left", fill="y")

        self.content_container = tk.Frame(
            root_frame, bg=self._skin_data["content"])
        self.content_container.pack(side="right", fill="both", expand=True)

        # Persistent top bar with a Home button - always visible on top of
        # every tab so the user can return to the launch screen at any time.
        skin = self._skin_data
        self._content_top_bar = tk.Frame(
            self.content_container, bg=skin["panel"], height=32)
        self._content_top_bar.pack(side="top", fill="x")
        self._content_top_bar.pack_propagate(False)

        self._home_btn = tk.Button(
            self._content_top_bar, text="🏠  Home",
            font=(UI_FONT, 9, "bold"),
            bg=skin["panel"], fg=skin["fg"],
            activebackground=skin.get("sb_hover", "#2A2A2A"),
            activeforeground="#FFFFFF",
            relief="flat", cursor="hand2",
            bd=0, padx=14, pady=4,
            command=lambda: self.show_page("Home"))
        self._home_btn.pack(side="left", padx=10, pady=4)

        tk.Frame(self.content_container,
                 bg=skin.get("border", "#2C2C2C"),
                 height=1).pack(side="top", fill="x")

        # Inner content area where the active tab is actually packed.
        # Tabs were previously parented to content_container directly;
        # now they go inside content_area which leaves the top bar
        # untouched between page swaps.
        self._content_area = tk.Frame(
            self.content_container, bg=skin["content"])
        self._content_area.pack(side="top", fill="both", expand=True)

        self.pages           = {}   # name → tab instance (None until first visit)
        self._tab_classes    = {}   # name → tab class (for lazy init)
        self.current_page    = None
        self._btn_refs       = {}
        self._indicator_refs = {}
        self._tool_rows      = []   # (name_lower, row_frame) for search
        self._cat_sections   = {}   # category → (hdr_row, items_frame, expanded_var)

        self._build_menubar()
        self._build_sidebar()

        # ── Mousewheel ────────────────────────────────────────────────────────
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>",   self._on_mousewheel)
        self.bind_all("<Button-5>",   self._on_mousewheel)

        # Commit the sidebar scrollregion after the window is fully laid out.
        # <Configure> bindings fire during construction before the canvas is
        # mapped, so bbox("all") may return None at that point.
        def _fix_scrollregion():
            try:
                self._inner.update_idletasks()
                self._sidebar_canvas.configure(
                    scrollregion=self._sidebar_canvas.bbox("all"))
            except Exception:
                pass
        self.after_idle(_fix_scrollregion)

        # ── Apply full skin ───────────────────────────────────────────────────
        apply_skin(
            self,
            self.sidebar_container,
            self.content_container,
            self._btn_refs,
            self._inner,
            indicator_refs=self._indicator_refs,
        )

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # ── Initialise global render queue ────────────────────────────────────
        from core.queue_manager import RenderQueueManager
        _qmgr = RenderQueueManager.get_instance()
        _qmgr.set_tk_root(self)
        _qmgr.register_update_callback(self._update_queue_status)

        self.show_page("Home")

        # ── Drag-and-drop file loading ────────────────────────────────────────
        self._init_drag_drop()

        # ── Probe FFmpeg in background ────────────────────────────────────────
        threading.Thread(target=self._check_ffmpeg, daemon=True).start()

        # ── Startup chime ─────────────────────────────────────────────────────
        threading.Thread(target=self._play_intro_sound, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  Status bar & Updates
    # ─────────────────────────────────────────────────────────────────────────
    def _build_status_bar(self):
        skin = self._skin_data
        SB   = skin["sb_bg"]
        FDM  = skin["fgdim"]
        BDR  = skin.get("border", "#2C2C2C")

        bar = tk.Frame(self, bg=SB, height=26)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=BDR, height=1).pack(side="top", fill="x")
        self._status_bar_frame = bar

        inner = tk.Frame(bar, bg=SB)
        inner.pack(fill="both", expand=True, padx=12)

        self._status_dot = tk.Label(inner, text="●", bg=SB,
                                     fg=skin["green"], font=(UI_FONT, 7))
        self._status_dot.pack(side="left", pady=5)

        self._status_lbl = tk.Label(inner, text="  " + t("app.status.ready"),
                                     bg=SB, fg=FDM, font=(UI_FONT, 8))
        self._status_lbl.pack(side="left")

        tk.Frame(inner, bg=BDR, width=1).pack(side="left", fill="y", pady=5, padx=10)

        self._status_tool = tk.Label(inner, text="", bg=SB, fg=FDM, font=(UI_FONT, 8))
        self._status_tool.pack(side="left")

        # System Updates Section (Right Side)
        tk.Frame(inner, bg=BDR, width=1).pack(side="right", fill="y", pady=5, padx=10)
        
        # FFmpeg Status (Clickable for global updates)
        self._status_ffmpeg = tk.Label(inner, text=t("app.status.ffmpeg_checking"),
                                        bg=SB, fg=FDM, font=(UI_FONT, 8, "bold"), cursor="hand2")
        self._status_ffmpeg.pack(side="right", padx=6)
        self._status_ffmpeg.bind("<Button-1>", lambda e: self._prompt_ffmpeg_update())

        tk.Frame(inner, bg=BDR, width=1).pack(side="right", fill="y", pady=5, padx=10)

        # YT-DLP Status (Hidden by default, shown on YouTube tab)
        self._status_ytdlp = tk.Label(inner, text="", bg=SB, fg=skin["accent"],
                                      font=(UI_FONT, 8, "bold"), cursor="hand2")
        # Pack hidden initially
        self._status_ytdlp.bind("<Button-1>", lambda e: self._update_ytdlp_process())

        # ── Render progress bar ───────────────────────────────────────────────
        tk.Frame(inner, bg=BDR, width=1).pack(side="left", fill="y", pady=5, padx=10)

        self._progress_frame = tk.Frame(inner, bg=SB)
        # Hidden by default - shown during renders
        self._progress_bar = ttk.Progressbar(
            self._progress_frame, mode="determinate",
            length=140, maximum=100)
        self._progress_bar.pack(side="left", pady=6)
        self._progress_pct = tk.Label(self._progress_frame, text="",
                                       bg=SB, fg=skin["accent"],
                                       font=(MONO_FONT, 8, "bold"))
        self._progress_pct.pack(side="left", padx=(4, 0))
        self._render_duration = 0.0   # total duration for progress calc

        # ── Queue Status indicator (always visible) ───────────────────────────
        tk.Frame(inner, bg=BDR, width=1).pack(side="left", fill="y", pady=5, padx=10)
        self._queue_status_lbl = tk.Label(
            inner, text=t("app.queue.idle"),
            bg=SB, fg=FDM, font=(UI_FONT, 8, "bold"), cursor="hand2")
        self._queue_status_lbl.pack(side="left", padx=4)
        self._queue_status_lbl.bind(
            "<Button-1>", lambda e: self.show_page("Encode Queue"))

    def _play_intro_sound(self):
        """Generate and play a soft startup chime using stdlib only (no extra deps).

        A short C-major arpeggio (C5→E5→G5→C6) followed by a sustained dyad,
        rendered as a 44.1 kHz 16-bit mono WAV in memory and played asynchronously.
        """
        import wave, struct, math, io
        RATE = 44100

        def _note(freq, dur, vol=0.28):
            n = int(RATE * dur)
            out = []
            for i in range(n):
                t = i / RATE
                # ADSR-style: fast attack, smooth exponential decay
                env = (1.0 - math.exp(-t * 55.0)) * math.exp(-t * 5.5)
                # Fundamental + soft 2nd harmonic for warmth
                s = math.sin(2 * math.pi * freq * t) + 0.18 * math.sin(4 * math.pi * freq * t)
                out.append(env * vol * s / 1.18)
            return out

        # Ascending arpeggio: C5 E5 G5 C6
        samples: list = []
        for freq, dur in [(523.25, 0.13), (659.25, 0.13), (783.99, 0.14), (1046.50, 0.17)]:
            samples.extend(_note(freq, dur))

        # Soft sustained dyad (C5 + G5) as a gentle tail
        n_tail = int(RATE * 0.45)
        for i in range(n_tail):
            t = i / RATE
            env = (1.0 - math.exp(-t * 18.0)) * math.exp(-t * 3.2)
            s = (math.sin(2 * math.pi * 523.25 * t) +
                 math.sin(2 * math.pi * 783.99 * t)) * 0.5
            samples.append(env * 0.22 * s)

        # Encode as 16-bit mono WAV
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(b''.join(
                struct.pack('<h', max(-32767, min(32767, int(s * 32767))))
                for s in samples
            ))
        wav_data = buf.getvalue()

        try:
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(wav_data, winsound.SND_MEMORY)
            elif sys.platform == 'darwin':
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    f.write(wav_data)
                    tmp = f.name
                subprocess.run(['afplay', tmp], timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try: os.remove(tmp)
                except Exception: pass
        except Exception:
            pass

    # ── Version helpers (network) ────────────────────────────────────────────
    @staticmethod
    def _fetch_latest_ffmpeg_version():
        """Return the latest FFmpeg release tag from gyan.dev, or None on failure."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                "https://www.gyan.dev/ffmpeg/builds/release-version",
                timeout=4) as r:
                txt = r.read().decode("utf-8").strip()
                return txt.split("-")[0] or None
        except Exception:
            return None

    @staticmethod
    def _fetch_latest_ytdlp_version():
        """Return the latest yt-dlp release tag from GitHub, or None on failure."""
        import urllib.request, json as _json
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": "QVE-update-check"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = _json.loads(r.read().decode("utf-8"))
                tag = (data.get("tag_name") or "").lstrip("v").strip()
                return tag or None
        except Exception:
            return None

    # ── FFmpeg status / update ───────────────────────────────────────────────
    def _check_ffmpeg(self):
        """Read local FFmpeg version, then asynchronously compare with latest."""
        local = None
        try:
            ffmpeg = get_binary_path("ffmpeg.exe")
            r = subprocess.run([ffmpeg, "-version"], capture_output=True,
                               text=True, timeout=5, creationflags=CREATE_NO_WINDOW)
            for part in (r.stdout or "").split():
                if part and (part[0].isdigit() or part.startswith("n")):
                    local = part.lstrip("n").split("-")[0]
                    break
        except Exception:
            local = None

        if not local:
            self._ffmpeg_local_version = None
            self.after(0, lambda: self._status_ffmpeg.config(
                text=t("app.status.ffmpeg_missing_click_install"),
                fg=self._skin_data["red"], cursor="hand2"))
            return

        self._ffmpeg_local_version = local
        # Show local version with "checking..." while we hit the network.
        self.after(0, lambda v=local: self._status_ffmpeg.config(
            text=f"FFmpeg {v} (checking…)",
            fg=self._skin_data["fgdim"], cursor="watch"))
        threading.Thread(
            target=self._compare_ffmpeg_versions,
            args=(local,), daemon=True).start()

    def _compare_ffmpeg_versions(self, local: str):
        latest = self._fetch_latest_ffmpeg_version()
        self._ffmpeg_latest_version = latest
        skin = self._skin_data

        if latest is None:
            # Offline / fetch failed - leave click-to-update available so the
            # user can still try to refresh manually.
            self.after(0, lambda v=local: self._status_ffmpeg.config(
                text=f"FFmpeg {v} (offline)",
                fg=skin["fgdim"], cursor="hand2"))
            return

        if latest == local:
            self.after(0, lambda v=local: self._status_ffmpeg.config(
                text=f"FFmpeg {v} (up to date)",
                fg=skin["green"], cursor="arrow"))
        else:
            self.after(0, lambda v=local, n=latest: self._status_ffmpeg.config(
                text=f"FFmpeg {v} → {n} (Click to Update)",
                fg=skin["orange"], cursor="hand2"))

    def _prompt_ffmpeg_update(self):
        # If we already know the local copy is current, just confirm and bail
        # out instead of triggering a pointless re-download.
        if (self._ffmpeg_latest_version
                and self._ffmpeg_local_version
                and self._ffmpeg_latest_version == self._ffmpeg_local_version):
            messagebox.showinfo(
                t("msg.ffmpeg_update_title"),
                f"FFmpeg {self._ffmpeg_local_version} is already up to date.")
            return
        if not messagebox.askyesno(t("msg.ffmpeg_update_title"), t("msg.ffmpeg_update_confirm")):
            return
        self._status_ffmpeg.config(text=t("app.status.ffmpeg_downloading"), fg=self._skin_data["orange"])

        def _task():
            def log_redirect(msg):
                self.set_status(msg)
            ok = download_and_extract_ffmpeg(log_redirect)
            self.after(0, self._check_ffmpeg)
            if ok:
                self.after(0, lambda: messagebox.showinfo(t("msg.ffmpeg_update_success_title"), t("msg.ffmpeg_update_success")))
            else:
                self.after(0, lambda: messagebox.showerror(t("msg.ffmpeg_update_failed_title"), t("msg.ffmpeg_update_failed")))

        threading.Thread(target=_task, daemon=True).start()

    # ── yt-dlp status / update ───────────────────────────────────────────────
    def set_ytdlp_status(self, version: str, bin_path: str):
        """Called by the YouTube tab once it's resolved a yt-dlp binary."""
        self._ytdlp_path = bin_path
        self._ytdlp_local_version = version
        # Show "checking..." while we ask GitHub for the latest tag.
        self._status_ytdlp.config(
            text=f"yt-dlp v{version} (checking…)",
            fg=self._skin_data["fgdim"], cursor="watch")
        threading.Thread(
            target=self._compare_ytdlp_versions,
            args=(version,), daemon=True).start()

    def _compare_ytdlp_versions(self, local: str):
        latest = self._fetch_latest_ytdlp_version()
        self._ytdlp_latest_version = latest
        skin = self._skin_data

        if latest is None:
            self.after(0, lambda v=local: self._status_ytdlp.config(
                text=f"yt-dlp v{v} (offline)",
                fg=skin["fgdim"], cursor="hand2"))
            return

        if latest == local:
            self.after(0, lambda v=local: self._status_ytdlp.config(
                text=f"yt-dlp v{v} (up to date)",
                fg=skin["green"], cursor="arrow"))
        else:
            self.after(0, lambda v=local, n=latest: self._status_ytdlp.config(
                text=f"yt-dlp v{v} → v{n} (Click to Update)",
                fg=skin["orange"], cursor="hand2"))

    def _update_ytdlp_process(self):
        if not self._ytdlp_path:
            return
        # Already current? Don't run -U; just confirm.
        if (self._ytdlp_latest_version
                and self._ytdlp_local_version
                and self._ytdlp_latest_version == self._ytdlp_local_version):
            messagebox.showinfo(
                t("msg.ytdlp_update_title"),
                f"yt-dlp v{self._ytdlp_local_version} is already up to date.")
            return
        if not messagebox.askyesno(t("msg.ytdlp_update_title"), t("msg.ytdlp_update_confirm")):
            return

        self._status_ytdlp.config(text=t("app.status.ytdlp_updating"), fg=self._skin_data["orange"])
        self.set_status(t("app.status.ytdlp_updating"))

        def _task():
            try:
                r = subprocess.run([self._ytdlp_path, "-U"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                # Re-check version
                ver_check = subprocess.run([self._ytdlp_path, "--version"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                new_ver = ver_check.stdout.strip()
                self.after(0, lambda: self.set_ytdlp_status(new_ver, self._ytdlp_path))
                self.after(0, lambda: self.set_status(t("msg.ytdlp_update_complete"), color=self._skin_data["green"]))
                self.after(0, lambda: messagebox.showinfo(t("msg.ytdlp_update_title2"), r.stdout))
            except Exception:
                self.after(0, lambda: self.set_status(t("msg.ytdlp_update_failed"), color=self._skin_data["red"]))
                self.after(0, lambda: self._status_ytdlp.config(text=t("app.status.ytdlp_update_failed")))

        threading.Thread(target=_task, daemon=True).start()

    def _update_queue_status(self):
        """Refresh the queue status label and progress bar in the status bar."""
        try:
            from core.queue_manager import RenderQueueManager
            active, pending, done, failed = RenderQueueManager.get_instance().get_stats()
            skin = self._skin_data
            if active > 0 or pending > 0:
                parts = []
                if active:
                    parts.append(f"{active} active")
                if pending:
                    parts.append(f"{pending} pending")
                self._queue_status_lbl.config(
                    text=t("app.queue.busy", n=" | ".join(parts)),
                    fg=skin["orange"])
                # Show progress bar during active renders
                self._progress_frame.pack(side="left", padx=(4, 0))
            elif failed > 0:
                self._queue_status_lbl.config(
                    text=f"Queue: {done} done | {failed} failed",
                    fg=skin["red"])
                self._hide_progress()
            elif done > 0:
                self._queue_status_lbl.config(
                    text=f"Queue: {done} done \u2713",
                    fg=skin["green"])
                self._hide_progress()
            else:
                self._queue_status_lbl.config(
                    text=t("app.queue.idle"),
                    fg=skin["fgdim"])
                self._hide_progress()
        except Exception:
            pass

    def _hide_progress(self):
        """Hide the progress bar and reset it."""
        try:
            self._progress_frame.pack_forget()
            self._progress_bar["value"] = 0
            self._progress_pct.config(text="")
            self._render_duration = 0.0
        except Exception:
            pass

    def update_render_progress(self, line):
        """Parse FFmpeg output line for time= and update the progress bar.

        Called from queue_manager progress callbacks.
        """
        import re
        try:
            # Extract duration from 'Duration: HH:MM:SS.xx' lines
            dur_m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if dur_m:
                self._render_duration = (float(dur_m.group(1)) * 3600
                                         + float(dur_m.group(2)) * 60
                                         + float(dur_m.group(3)))

            # Extract current time from 'time=HH:MM:SS.xx' or 'time=SS.xx'
            time_m = re.search(r'time=\s*(\d+):(\d+):([\d.]+)', line)
            if time_m and self._render_duration > 0:
                current = (float(time_m.group(1)) * 3600
                          + float(time_m.group(2)) * 60
                          + float(time_m.group(3)))
                pct = min(100.0, (current / self._render_duration) * 100)
                self._progress_bar["value"] = pct
                self._progress_pct.config(text=f"{pct:.0f}%")
        except Exception:
            pass

    def set_status(self, message, color=None):
        skin = self._skin_data
        c = color or skin["fgdim"]
        try:
            self._status_lbl.config(text=f"  {message}", fg=c)
            if any(w in message for w in ("Processing", "Rendering", "Encoding", "Updating", "Downloading")):
                self._status_dot.config(fg=skin["orange"])
            elif any(w in message.lower() for w in ("done", "complete", "success")):
                self._status_dot.config(fg=skin["green"])
            elif any(w in message.lower() for w in ("error", "failed", "fail")):
                self._status_dot.config(fg=skin["red"])
            else:
                self._status_dot.config(fg=skin["green"])
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Skin
    # ─────────────────────────────────────────────────────────────────────────
    def _refresh_skin_cache(self):
        self._skin_data = get_skin(load_skin_name())

    def _apply_skin_live(self, name):
        from core.skins import save_skin_name
        save_skin_name(name)
        self._refresh_skin_cache()
        skin = self._skin_data
        apply_default_options(self, skin)
        apply_skin(self, self.sidebar_container, self.content_container,
                   self._btn_refs, self._inner, indicator_refs=self._indicator_refs)
        self._skin_menu_var.set(name)
        if self.current_page and self.current_page in self._indicator_refs:
            try:
                self._indicator_refs[self.current_page].config(bg=skin["accent"])
            except Exception:
                pass
        # Recolour status bar
        try:
            SB = skin["sb_bg"]
            for w in self._status_bar_frame.winfo_children():
                try:
                    w.config(bg=SB)
                    for c in w.winfo_children():
                        try: c.config(bg=SB)
                        except Exception: pass
                except Exception:
                    pass
            self._status_bar_frame.config(bg=SB)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Mousewheel
    # ─────────────────────────────────────────────────────────────────────────
    def _on_mousewheel(self, event):
        # Cross-platform delta mapping - 3 units per notch matches typical
        # desktop scroll speed (Windows default is 3 lines per notch).
        if event.num == 4:
            delta = 3
        elif event.num == 5:
            delta = -3
        elif _IS_MAC:
            delta = -event.delta * 3
        else:
            delta = int(-event.delta / 120) * 3

        # If the cursor is anywhere inside the sidebar, scroll the sidebar canvas
        # directly - the parent-walk below can miss it when tabs contain canvases.
        try:
            sc = self.sidebar_container
            if (sc.winfo_rootx() <= event.x_root < sc.winfo_rootx() + sc.winfo_width()
                    and sc.winfo_rooty() <= event.y_root < sc.winfo_rooty() + sc.winfo_height()):
                self._sidebar_canvas.yview_scroll(delta, "units")
                return
        except Exception:
            pass

        # Content area: walk up the widget tree to find the nearest scrollable canvas.
        widget = event.widget
        while widget is not None:
            if isinstance(widget, tk.Canvas):
                try:
                    if widget.cget("yscrollcommand"):
                        widget.yview_scroll(delta, "units")
                        return
                except Exception:
                    pass
            try:
                widget = widget.master
            except Exception:
                break

    # ─────────────────────────────────────────────────────────────────────────
    #  Menu bar
    # ─────────────────────────────────────────────────────────────────────────
    def _build_menubar(self):
        skin = self._skin_data
        mb = tk.Menu(self, bg=skin["panel"], fg=skin["fg"],
                     activebackground=skin["accent"],
                     activeforeground="#FFFFFF",
                     relief="flat", bd=0)
        self.config(menu=mb)

        def _mksub():
            return tk.Menu(mb, tearoff=0,
                           bg=skin["panel"], fg=skin["fg"],
                           activebackground=skin["accent"],
                           activeforeground="#FFFFFF",
                           relief="flat", bd=0)

        m_file = _mksub()
        mb.add_cascade(label="File", menu=m_file)
        m_file.add_command(label="Home",
                           command=lambda: self.show_page("Home"))
        m_file.add_separator()
        m_file.add_command(label="Open video file…",
                           command=self._menu_open_file, accelerator="Ctrl+O")
        m_file.add_separator()
        self._recent_menu = _mksub()
        m_file.add_cascade(label="Recent Files", menu=self._recent_menu)
        self._rebuild_recent_menu()
        m_file.add_separator()
        m_file.add_command(label="Open output folder…",
                           command=self._menu_open_output_folder)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self._on_closing,
                           accelerator="Alt+F4")

        m_edit = _mksub()
        mb.add_cascade(label="Edit", menu=m_edit)
        m_edit.add_command(label="Quick Settings",
                           command=lambda: self.show_page("Settings"))
        m_edit.add_command(label="Advanced Settings",
                           command=lambda: self.show_page("Advanced Settings"))
        m_edit.add_separator()
        m_edit.add_checkbutton(label="Debug mode", variable=self.debug_mode)

        m_cut = _mksub()
        mb.add_cascade(label="Cutting Room", menu=m_cut)
        for n in ["Crossfader", "Quick Trimmer", "Manual Multi-Splitter", "The Splicer", "Batch Joiner",
                  "Rotate & Flip", "Side-by-Side", "Beat Sync Cutter",
                  "Smart Reframe", "Manual Crop", "Video Reverser",
                  "Freeze Frame", "Clip Looper", "Multi-Clip Sequencer",
                  "Scene Detector"]:
            m_cut.add_command(label=n, command=lambda n=n: self.show_page(n))

        m_social = _mksub()
        mb.add_cascade(label="Social", menu=m_social)
        for n in ["The Shortifier", "Auto-Cropper", "Pro GIF Maker",
                  "WebM Maker", "Watermarker", "Image Watermark", "Hard-Subber",
                  "Auto-Subtitles", "Animated Titles", "Frame Extractor",
                  "Intro/Outro Maker", "Slideshow Maker", "Chapter Markers",
                  "Thumbnail Maker", "Video Collage", "Video Downloader"]:
            m_social.add_command(label=n, command=lambda n=n: self.show_page(n))

        m_audio = _mksub()
        mb.add_cascade(label="Audio", menu=m_audio)
        for n in ["Silence Remover", "Audio Extractor", "Audio Replacer",
                  "Loudness Normalizer", "Audio Sync Shifter", "The Muter",
                  "Audio Dynamics", "Audio Mixer", "Voice Isolation",
                  "Voice Changer", "TTS Voice-Over", "Waveform Editor",
                  "Laugh Track Remover", "Music Ducker", "Karaoke Generator",
                  "Audio Converter", "MIDIfier"]:
            m_audio.add_command(label=n, command=lambda n=n: self.show_page(n))

        m_trans = _mksub()
        mb.add_cascade(label="Transcoder", menu=m_trans)
        for n in ["Universal Downsizer", "Proxy Generator", "Codec Cruncher",
                  "Format Converter", "Resolution Scaler",
                  "Framerate Interpolator", "Encode Queue", "Preset Manager"]:
            m_trans.add_command(label=n, command=lambda n=n: self.show_page(n))

        m_color = _mksub()
        mb.add_cascade(label="Color", menu=m_color)
        for n in ["Media Generator", "Special Effects", "LUT Applicator", "Basic Color Corrector",
                  "Colour Match", "Video Scopes", "Speed Ramper",
                  "Deshaker", "Green Screen Keyer", "Denoise",
                  "Deinterlace", "Sharpen", "Picture-in-Picture",
                  "Privacy Blur", "Animated Zoom", "Transition Studio"]:
            m_color.add_command(label=n, command=lambda n=n: self.show_page(n))

        m_view = _mksub()
        mb.add_cascade(label="View", menu=m_view)

        m_skins = tk.Menu(m_view, tearoff=0,
                          bg=skin["panel"], fg=skin["fg"],
                          activebackground=skin["accent"],
                          activeforeground="#FFFFFF")
        m_view.add_cascade(label="Theme", menu=m_skins)
        from core.skins import SKINS
        self._skin_menu_var = tk.StringVar(value=load_skin_name())
        for sn in SKINS:
            m_skins.add_radiobutton(label=sn, variable=self._skin_menu_var,
                                     value=sn,
                                     command=lambda n=sn: self._apply_skin_live(n))

        m_view.add_separator()
        m_view.add_command(label="Jump to top of sidebar",
                           command=self._sidebar_scroll_top)
        m_view.add_command(label="Expand all categories",
                           command=lambda: self._set_all_categories(True))
        m_view.add_command(label="Collapse all categories",
                           command=lambda: self._set_all_categories(False))

        m_help = tk.Menu(mb, tearoff=0, bg=skin["panel"], fg=skin["fg"],
                         activebackground=skin["accent"], activeforeground="#FFFFFF")
        mb.add_cascade(label="Help", menu=m_help)
        m_help.add_command(label="Keyboard Shortcuts", command=self._menu_shortcuts)
        m_help.add_command(label="System Info", command=self._menu_system_info)
        m_help.add_separator()
        m_help.add_command(label="About Quintessential Video Editor",
                           command=self._menu_about)

        self._menubar = mb
        self.bind("<Control-o>", lambda e: self._menu_open_file())

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        self.bind("<space>",     self._kb_play_pause)
        self.bind("i",          self._kb_set_in)
        self.bind("o",          self._kb_set_out)
        self.bind("<Home>",     self._kb_go_start)
        self.bind("<End>",      self._kb_go_end)
        self.bind("<Left>",     self._kb_nudge_left)
        self.bind("<Right>",    self._kb_nudge_right)
        self.bind("<Control-s>", self._kb_render)
        self.bind("<Escape>",   self._kb_stop_preview)

    # ── Keyboard shortcut handlers ───────────────────────────────────────────

    def _kb_focused_on_entry(self):
        """Return True if focus is on a text entry (don't hijack typing)."""
        w = self.focus_get()
        return isinstance(w, (tk.Entry, tk.Text, ttk.Entry))

    def _kb_play_pause(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if not page:
            return
        # Try launching preview at current playhead
        if hasattr(page, "preview_proc") and page.preview_proc:
            try:
                page.preview_proc.terminate()
                page.preview_proc = None
            except Exception:
                pass
            return
        # Launch preview
        fp = getattr(page, "file_path", "")
        if not fp or not os.path.isfile(fp):
            return
        start = 0.0
        if hasattr(page, "_timeline"):
            start = page._timeline.get_playhead()
        elif hasattr(page, "_scrub"):
            try:
                start = float(page._scrub.get())
            except (ValueError, tk.TclError):
                pass
        from core.hardware import launch_preview
        page.preview_proc = launch_preview(fp, start_time=start)

    def _kb_set_in(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if not page:
            return
        if hasattr(page, "_timeline") and page._timeline._show_handles:
            tl = page._timeline
            tl._start = tl._playhead
            tl._draw()
            tl._fire_change()
        elif hasattr(page, "_start_var") and hasattr(page, "_scrub"):
            try:
                from tabs.cutting.trimmer import fmt_time
                page._start_var.set(fmt_time(float(page._scrub.get())))
                if hasattr(page, "_apply_typed_times"):
                    page._apply_typed_times()
            except Exception:
                pass

    def _kb_set_out(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if not page:
            return
        if hasattr(page, "_timeline") and page._timeline._show_handles:
            tl = page._timeline
            tl._end = tl._playhead
            tl._draw()
            tl._fire_change()
        elif hasattr(page, "_end_var") and hasattr(page, "_scrub"):
            try:
                from tabs.cutting.trimmer import fmt_time
                page._end_var.set(fmt_time(float(page._scrub.get())))
                if hasattr(page, "_apply_typed_times"):
                    page._apply_typed_times()
            except Exception:
                pass

    def _kb_go_start(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if page and hasattr(page, "_timeline"):
            page._timeline.set_playhead(0.0)
        elif page and hasattr(page, "_scrub"):
            page._scrub.set(0.0)

    def _kb_go_end(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if page and hasattr(page, "_timeline"):
            page._timeline.set_playhead(page._timeline._duration)
        elif page and hasattr(page, "_scrub"):
            dur = getattr(page, "duration", 0)
            page._scrub.set(dur)

    def _kb_nudge_left(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if page and hasattr(page, "_timeline"):
            tl = page._timeline
            tl.set_playhead(max(0, tl._playhead - 1.0))
        elif page and hasattr(page, "_scrub"):
            try:
                page._scrub.set(max(0, float(page._scrub.get()) - 1.0))
            except (ValueError, tk.TclError):
                pass

    def _kb_nudge_right(self, event=None):
        if self._kb_focused_on_entry():
            return
        page = self.pages.get(self.current_page)
        if page and hasattr(page, "_timeline"):
            tl = page._timeline
            tl.set_playhead(min(tl._duration, tl._playhead + 1.0))
        elif page and hasattr(page, "_scrub"):
            try:
                dur = getattr(page, "duration", 9999)
                page._scrub.set(min(dur, float(page._scrub.get()) + 1.0))
            except (ValueError, tk.TclError):
                pass

    def _kb_render(self, event=None):
        page = self.pages.get(self.current_page)
        if not page:
            return
        # Find the render/export button and invoke it
        for attr in ("_btn_trim", "btn_render", "_btn_render", "btn_export",
                     "_btn_export", "_btn_run", "btn_run"):
            btn = getattr(page, attr, None)
            if btn and isinstance(btn, tk.Button):
                try:
                    btn.invoke()
                except Exception:
                    pass
                return "break"

    def _kb_stop_preview(self, event=None):
        self._stop_active_previews(closing=False)

    # ── Menu callbacks ────────────────────────────────────────────────────────
    def _menu_open_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Open video file",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.m4v"),
                        ("All files", "*.*")])
        if not path:
            return
        self._add_recent_file(path)
        page = self.pages.get(self.current_page)
        if page is None:
            return
        loaded = False
        for attr in ("_src_var", "src_var"):
            if hasattr(page, attr):
                try:
                    getattr(page, attr).set(path)
                    page.file_path = path
                    if hasattr(page, "duration"):
                        from core.hardware import get_video_duration
                        page.duration = get_video_duration(path)
                        for a in ("_scrub_sc", "_scrub"):
                            if hasattr(page, a):
                                getattr(page, a).config(to=max(page.duration, 1))
                        if hasattr(page, "_draw"):
                            page._draw()
                    base = os.path.splitext(path)[0]
                    for oa in ("_out_var", "out_var"):
                        if hasattr(page, oa) and not getattr(page, oa).get():
                            getattr(page, oa).set(base + "_output.mp4")
                    loaded = True
                    break
                except Exception:
                    pass
        if not loaded and hasattr(page, "file_path"):
            page.file_path = path
            loaded = True
        if loaded:
            self.title("Quintessential Video Editor  ·  {}  ·  {}".format(
                self.current_page, os.path.basename(path)))
        else:
            messagebox.showinfo("File opened",
                "Use the Browse button within '{}' to load files.\n\n"
                "Path:\n{}".format(self.current_page, path))

    def _menu_open_output_folder(self):
        from core.hardware import open_in_explorer
        folder = ""
        page = self.pages.get(self.current_page)
        if page:
            for attr in ("_out_var", "out_var", "out_path_var"):
                if hasattr(page, attr):
                    try:
                        val = getattr(page, attr).get().strip()
                        if val:
                            candidate = (os.path.dirname(val)
                                         if not os.path.isdir(val) else val)
                            if os.path.exists(candidate):
                                folder = candidate
                                break
                    except Exception:
                        pass
        if not folder:
            from core.settings import load_settings
            folder = load_settings().get("default_output_folder", "")
        if not folder or not os.path.exists(folder):
            from tkinter import filedialog
            folder = filedialog.askdirectory(title="Choose folder to open")
        if folder and os.path.exists(folder):
            open_in_explorer(folder)

    def _sidebar_scroll_top(self):
        try:
            self._sidebar_canvas.yview_moveto(0)
        except Exception:
            pass

    def _set_all_categories(self, expanded: bool):
        for cat, (hdr_row, items_frame, exp_var) in self._cat_sections.items():
            try:
                arrow = hdr_row._arrow_lbl
                if expanded:
                    items_frame.pack(fill="x", after=hdr_row)
                    exp_var.set(True)
                    arrow.config(text="▾")
                else:
                    items_frame.pack_forget()
                    exp_var.set(False)
                    arrow.config(text="▸")
            except Exception:
                pass
        try:
            self._inner.update_idletasks()
            self._sidebar_canvas.configure(
                scrollregion=self._sidebar_canvas.bbox("all"))
        except Exception:
            pass

    def _menu_system_info(self):
        self.show_page("Advanced Settings")
        page = self.pages.get("Advanced Settings")
        if not page:
            return
        def _find_nb(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Notebook):
                    return c
                r = _find_nb(c)
                if r:
                    return r
            return None
        try:
            nb = _find_nb(page)
            if nb:
                nb.select(3)
        except Exception:
            pass

    def _menu_shortcuts(self):
        messagebox.showinfo("Keyboard Shortcuts",
            "PLAYBACK\n"
            "  Space          Play / pause preview\n"
            "  Escape         Stop preview\n\n"
            "NAVIGATION\n"
            "  Home           Go to start\n"
            "  End            Go to end\n"
            "  Left / Right   Nudge playhead \u00b11 sec\n\n"
            "EDITING\n"
            "  I              Set IN point at playhead\n"
            "  O              Set OUT point at playhead\n"
            "  Ctrl+S         Start render / export\n\n"
            "FILE\n"
            "  Ctrl+O         Open file\n"
            "  Drag & Drop    Drop files onto window\n")

    def _menu_about(self):
        messagebox.showinfo("About Quintessential Video Editor",
            "Quintessential Video Editor  ·  Version 1.14\n"
            "Version {}\n\n"
            "A self-contained video and audio processing suite\n"
            "powered by FFmpeg.\n\n"
            "71 tools  ·  6 themes  ·  Windows / Linux / macOS".format(
                APP_VERSION))

    # ─────────────────────────────────────────────────────────────────────────
    #  Sidebar
    # ─────────────────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        skin   = self._skin_data
        SB_BG  = skin["sb_bg"]
        ACCENT = skin["accent"]
        BORDER = skin.get("border", "#2C2C2C")

        # ── Static header (logo + AIO pinned + search) ─────────────────────────
        static_top = tk.Frame(self.sidebar_container, bg=SB_BG)
        static_top.pack(side="top", fill="x")

        # Wordmark
        logo_f = tk.Frame(static_top, bg=SB_BG)
        logo_f.pack(fill="x", padx=16, pady=(20, 0))

        badge = tk.Canvas(logo_f, width=38, height=34, bg=SB_BG,
                           highlightthickness=0)
        badge.pack(side="left", padx=(0, 12))
        badge.create_rectangle(0, 0, 38, 34, fill=ACCENT, outline="")
        badge.create_text(19, 17, text="QV", fill="#FFFFFF",
                           font=(UI_FONT, 13, "bold"))

        nf = tk.Frame(logo_f, bg=SB_BG)
        nf.pack(side="left", anchor="w")
        tk.Label(nf, text="QUINTESSENTIAL",
                 font=(UI_FONT, 11, "bold"),
                 bg=SB_BG, fg="#CCCCCC").pack(anchor="w")
        tk.Label(nf, text=t("app.subtitle"),
                 font=(UI_FONT, 8), bg=SB_BG, fg="#424242").pack(anchor="w")

        tk.Frame(static_top, bg=BORDER, height=1).pack(fill="x",
                                                         padx=14, pady=(16, 0))

        # All-in-One pinned  (lazy - initialized on first click)
        _aio_key = "⚡ " + PINNED[0]
        self._tab_classes[_aio_key] = PINNED[1]
        self.pages[_aio_key] = None

        aio_row = tk.Frame(static_top, bg=SB_BG)
        aio_row.pack(fill="x", padx=6, pady=(8, 5))
        aio_ind = tk.Frame(aio_row, bg=SB_BG, width=3)
        aio_ind.pack(side="left", fill="y")
        aio_ind.pack_propagate(False)
        aio_btn = tk.Button(
            aio_row, text="   ⚡  {}".format(t("tab.all_in_one")),
            font=(UI_FONT, 10, "bold"),
            bg=SB_BG, fg=ACCENT, relief="flat", anchor="w",
            cursor="hand2",
            activebackground=skin["sb_hover"], activeforeground="#FFFFFF",
            command=lambda n=_aio_key: self.show_page(n),
            bd=0, padx=0, pady=5,
        )
        aio_btn.pack(side="left", fill="x", expand=True)
        aio_btn.bind("<Enter>",
                     lambda e, b=aio_btn: b.config(bg=self._skin_data["sb_hover"]))
        aio_btn.bind("<Leave>",
                     lambda e, b=aio_btn, n=_aio_key: b.config(
                         bg=(self._skin_data["sb_active"]
                             if self.current_page == n
                             else self._skin_data["sb_bg"])))
        self._btn_refs[_aio_key]       = aio_btn
        self._indicator_refs[_aio_key] = aio_ind

        tk.Frame(static_top, bg=BORDER, height=1).pack(fill="x",
                                                         padx=14, pady=(4, 0))

        # Search box
        srch_outer = tk.Frame(static_top, bg=SB_BG)
        srch_outer.pack(fill="x", padx=12, pady=(10, 8))

        i_bg = skin.get("input_bg", "#1E1E1E")
        srch_bdr = tk.Frame(srch_outer, bg=BORDER)
        srch_bdr.pack(fill="x")
        srch_inner = tk.Frame(srch_bdr, bg=i_bg)
        srch_inner.pack(fill="x", padx=1, pady=1)

        tk.Label(srch_inner, text="⌕", bg=i_bg, fg="#484848",
                 font=(UI_FONT, 11)).pack(side="left", padx=(7, 0), pady=3)

        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(
            srch_inner, textvariable=self._search_var,
            bg=i_bg, fg="#808080",
            insertbackground=ACCENT,
            relief="flat", bd=0, font=(UI_FONT, 9),
            highlightthickness=0,
        )
        self._search_entry.pack(side="left", fill="x", expand=True,
                                 padx=(4, 6), pady=4)
        self._search_ph = t("app.search_placeholder")
        self._search_entry.insert(0, self._search_ph)
        self._search_entry.bind("<FocusIn>",  self._on_search_focus)
        self._search_entry.bind("<FocusOut>", self._on_search_blur)
        self._search_var.trace_add("write", self._filter_sidebar)

        self._search_clear = tk.Label(srch_inner, text="✕",
                                       bg=i_bg, fg="#484848",
                                       font=(UI_FONT, 8), cursor="hand2")
        self._search_clear.pack(side="right", padx=(0, 6))
        self._search_clear.pack_forget()
        self._search_clear.bind("<Button-1>", self._clear_search)

        tk.Frame(static_top, bg=BORDER, height=1).pack(fill="x", padx=14)

        # ── Scrollable tools ──────────────────────────────────────────────────
        scroll_f = tk.Frame(self.sidebar_container, bg=SB_BG)
        scroll_f.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_f, bg=SB_BG,
                           highlightthickness=0, yscrollincrement=20)
        self._sidebar_canvas = canvas
        vsb = ttk.Scrollbar(scroll_f, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=SB_BG)
        self._inner = inner

        _iw = SB_WIDTH - 18
        canvas.create_window((0, 0), window=inner, anchor="nw", width=_iw)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=vsb.set)

        canvas.unbind_class("Canvas", "<<FocusIn>>")

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # ── Tool definitions (sourced from tabs/registry.py) ─────────────────
        for category, items in TOOLS.items():
            expanded = tk.BooleanVar(value=True)

            # Category header
            hdr_row = tk.Frame(inner, bg=SB_BG, cursor="hand2")
            hdr_row.pack(fill="x", pady=(10, 0))

            arrow_lbl = tk.Label(hdr_row, text="▾", bg=SB_BG,
                                  fg="#484848", font=(UI_FONT, 7),
                                  cursor="hand2")
            arrow_lbl.pack(side="left", padx=(14, 0), pady=2)
            hdr_row._arrow_lbl = arrow_lbl

            cat_lbl = tk.Label(hdr_row,
                                text=_cat_label(category),
                                font=(UI_FONT, 7, "bold"),
                                bg=SB_BG, fg=skin["sb_cat"],
                                anchor="w", cursor="hand2")
            cat_lbl.pack(side="left", padx=(5, 4), pady=2,
                          fill="x", expand=True)

            count_bg = skin.get("input_bg", "#1E1E1E")
            tk.Label(hdr_row, text=str(len(items)),
                     bg=count_bg, fg="#4A4A4A",
                     font=(UI_FONT, 7),
                     padx=5, pady=1).pack(side="right", padx=(0, 12), pady=4)

            items_frame = tk.Frame(inner, bg=SB_BG)
            items_frame.pack(fill="x")

            self._cat_sections[category] = (hdr_row, items_frame, expanded)

            def _make_toggle(ef=items_frame, al=arrow_lbl, ev=expanded, hr=hdr_row):
                def toggle(*_):
                    if ev.get():
                        ef.pack_forget()
                        ev.set(False)
                        al.config(text="▸")
                    else:
                        ef.pack(fill="x", after=hr)
                        ev.set(True)
                        al.config(text="▾")
                    inner.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
                return toggle

            _tog = _make_toggle()
            for w in (hdr_row, cat_lbl, arrow_lbl):
                w.bind("<Button-1>", _tog)

            # Tool buttons  (tabs are lazy - instantiated on first visit)
            for name, tab_cls in items:
                self._tab_classes[name] = tab_cls
                self.pages[name] = None  # sentinel; initialized in show_page()

                row_f = tk.Frame(items_frame, bg=SB_BG)
                row_f.pack(fill="x", padx=6, pady=0)

                ind = tk.Frame(row_f, bg=SB_BG, width=3)
                ind.pack(side="left", fill="y")
                ind.pack_propagate(False)

                btn = tk.Button(
                    row_f,
                    text="    {}".format(_tab_label(name)),
                    font=(UI_FONT, 9),
                    bg=SB_BG, fg=skin["sb_btn"],
                    relief="flat", anchor="w",
                    cursor="hand2",
                    activebackground=skin["sb_hover"],
                    activeforeground="#FFFFFF",
                    command=lambda n=name: self.show_page(n),
                    bd=0, padx=0, pady=3,
                )
                btn.pack(side="left", fill="x", expand=True)
                btn.bind("<Enter>",
                         lambda e, b=btn: b.config(
                             bg=self._skin_data["sb_hover"]))
                btn.bind("<Leave>",
                         lambda e, b=btn, n=name: b.config(
                             bg=(self._skin_data["sb_active"]
                                 if self.current_page == n
                                 else self._skin_data["sb_bg"])))

                self._btn_refs[name]       = btn
                self._indicator_refs[name] = ind
                self._tool_rows.append((name.lower(), row_f))

        tk.Frame(inner, bg=SB_BG, height=20).pack()

        # Footer
        footer = tk.Frame(self.sidebar_container, bg=SB_BG)
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg=BORDER, height=1).pack(fill="x")
        fi = tk.Frame(footer, bg=SB_BG)
        fi.pack(fill="x", padx=14, pady=7)
        tk.Label(fi, text="v{}  Version 1.14".format(APP_VERSION),
                 bg=SB_BG, fg="#343434",
                 font=(UI_FONT, 8)).pack(side="left")
        self.debug_cb = tk.Checkbutton(
            fi, text="DEBUG", variable=self.debug_mode,
            bg=SB_BG, fg="#343434", selectcolor=SB_BG,
            activebackground=SB_BG, font=(UI_FONT, 8), cursor="hand2")
        self.debug_cb.pack(side="right")

        # Hidden pages (not in sidebar) - also lazy
        for name, tab_cls in HIDDEN.items():
            if name not in self.pages:
                self._tab_classes[name] = tab_cls
                self.pages[name] = None

    # ── Search ────────────────────────────────────────────────────────────────
    def _on_search_focus(self, event):
        if self._search_entry.get() == self._search_ph:
            self._search_entry.delete(0, tk.END)
            self._search_entry.config(
                fg=self._skin_data.get("input_fg", "#E2E2E2"))

    def _on_search_blur(self, event):
        if not self._search_entry.get():
            self._search_entry.insert(0, self._search_ph)
            self._search_entry.config(fg="#808080")
            self._search_clear.pack_forget()

    def _clear_search(self, event=None):
        self._search_entry.delete(0, tk.END)
        self._on_search_blur(None)
        self._filter_sidebar()

    def _filter_sidebar(self, *_):
        # Debounce: cancel any pending filter and schedule a new one
        if hasattr(self, '_search_after_id') and self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(80, self._do_filter_sidebar)

    def _do_filter_sidebar(self):
        self._search_after_id = None
        query = self._search_var.get().strip().lower()
        searching = bool(query) and query != self._search_ph.lower()

        if searching:
            self._search_clear.pack(side="right", padx=(0, 6))
        else:
            self._search_clear.pack_forget()

        # First pass: show/hide each tool row
        visible_parents = set()
        for tool_name, row_f in self._tool_rows:
            match = not searching or query in tool_name
            try:
                if match:
                    row_f.pack(fill="x", padx=6, pady=0)
                    # Identify which items_frame this belongs to
                    visible_parents.add(row_f.master)
                else:
                    row_f.pack_forget()
            except Exception:
                pass

        # Second pass: show/hide category headers
        for cat, (hdr_row, items_frame, exp_var) in self._cat_sections.items():
            if searching:
                if items_frame in visible_parents:
                    hdr_row.pack(fill="x", pady=(10, 0))
                    items_frame.pack(fill="x", after=hdr_row)
                else:
                    hdr_row.pack_forget()
                    items_frame.pack_forget()
            else:
                hdr_row.pack(fill="x", pady=(10, 0))
                if exp_var.get():
                    items_frame.pack(fill="x", after=hdr_row)
                else:
                    items_frame.pack_forget()

        try:
            self._inner.update_idletasks()
            self._sidebar_canvas.configure(
                scrollregion=self._sidebar_canvas.bbox("all"))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Logging
    # ─────────────────────────────────────────────────────────────────────────
    def log_debug(self, message):
        if self.debug_mode.get():
            print("[DEBUG] {}".format(message))

    # ─────────────────────────────────────────────────────────────────────────
    #  Navigation
    # ─────────────────────────────────────────────────────────────────────────
    def show_page(self, page_name):
        self._stop_active_previews(closing=False)
        skin = self._skin_data

        if self.pages.get(page_name) is None and page_name in self._tab_classes:
            try:
                self.pages[page_name] = self._tab_classes[page_name](
                    self._content_area)
            except Exception as exc:
                self.log_debug(f"Error loading {page_name}: {exc}")
                self.pages[page_name] = PlaceholderTab(
                    self._content_area, page_name)
            # The Home tab needs a way to navigate to other tabs. Inject
            # the navigator after construction (avoids passing the App
            # instance into the tab constructor).
            page = self.pages[page_name]
            if hasattr(page, "set_navigator"):
                try:
                    page.set_navigator(self.show_page)
                except Exception:
                    pass

        if page_name not in self.pages or self.pages[page_name] is None:
            return

        # Handle Contextual Status Bar items
        if page_name == "Video Downloader":
            self._status_ytdlp.pack(side="right", padx=(0, 6), before=self._status_ffmpeg)
        else:
            self._status_ytdlp.pack_forget()

        if self.current_page and self.current_page in self._btn_refs:
            self._btn_refs[self.current_page].config(
                bg=skin["sb_bg"], fg=skin["sb_btn"], font=(UI_FONT, 9))
        if self.current_page and self.current_page in self._indicator_refs:
            try: self._indicator_refs[self.current_page].config(bg=skin["sb_bg"])
            except Exception: pass

        if self.current_page and self.pages.get(self.current_page) is not None:
            self.pages[self.current_page].pack_forget()

        self.pages[page_name].pack(fill="both", expand=True)
        self.current_page = page_name
        _app_state.set("active_tab", page_name)

        if page_name in self._btn_refs:
            self._btn_refs[page_name].config(
                bg=skin["sb_active"], fg=skin["accent"], font=(UI_FONT, 9, "bold"))
        if page_name in self._indicator_refs:
            try: self._indicator_refs[page_name].config(bg=skin["accent"])
            except Exception: pass

        self.title("Quintessential Video Editor  ·  {}".format(_tab_label(page_name)))
        try: self._status_tool.config(text=_tab_label(page_name))
        except Exception: pass

        self._scroll_to_active(page_name)

    def _scroll_to_active(self, page_name):
        try:
            if page_name not in self._btn_refs:
                return
            btn = self._btn_refs[page_name]
            self._sidebar_canvas.update_idletasks()
            total_h = self._sidebar_canvas.bbox("all")[3]
            if not total_h:
                return
            canvas_h = self._sidebar_canvas.winfo_height()
            y = btn.winfo_rooty() - self._inner.winfo_rooty()
            cur_top, cur_bot = self._sidebar_canvas.yview()
            frac = y / max(total_h, 1)
            if frac < cur_top:
                self._sidebar_canvas.yview_moveto(max(0, frac - 0.05))
            elif frac + 30 / total_h > cur_bot:
                self._sidebar_canvas.yview_moveto(
                    min(1, frac - canvas_h / total_h + 0.05))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Cleanup
    # ─────────────────────────────────────────────────────────────────────────
    def _stop_active_previews(self, closing=False):
        """
        Kill only preview (ffplay) processes.
        If closing=True, also kill interactive screen-recording processes.
        """
        # Attributes that hold ffplay preview handles
        PREVIEW_ATTRS = ("preview_proc",)
        
        # Attributes that hold interactive recording handles (screen recorder,
        # live-stream capture). We only kill these when the app closes, allowing
        # them to continue in the background if the user switches tabs.
        RECORD_ATTRS  = ("record_proc", "_record_proc")

        for page in self.pages.values():
            if page is None:
                continue

            for attr in PREVIEW_ATTRS:
                p = getattr(page, attr, None)
                if p and hasattr(p, "terminate"):
                    try:
                        p.terminate()
                        setattr(page, attr, None)
                    except Exception:
                        pass

            if closing:
                for attr in RECORD_ATTRS:
                    p = getattr(page, attr, None)
                    if p and hasattr(p, "terminate"):
                        try:
                            p.terminate()
                            setattr(page, attr, None)
                        except Exception:
                            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Drag-and-drop
    # ─────────────────────────────────────────────────────────────────────────
    def _init_drag_drop(self):
        """Set up file drag-and-drop using windnd (auto-installed) on Windows."""
        if sys.platform != "win32":
            return
        try:
            from core.deps import require
            windnd = require("windnd", import_name="windnd")
            if windnd is None:
                return
            windnd.hook_dropfiles(self, func=self._handle_drop)
            self.log_debug("Drag-and-drop enabled")
        except Exception as e:
            self.log_debug(f"Drag-and-drop init failed: {e}")

    def _handle_drop(self, file_list):
        """Handle files dropped onto the app window."""
        if not file_list:
            return
        # windnd passes bytes paths on Windows
        paths = []
        for f in file_list:
            if isinstance(f, bytes):
                paths.append(f.decode("utf-8", errors="replace"))
            else:
                paths.append(str(f))

        if not paths:
            return

        path = paths[0]  # use first file
        if not os.path.isfile(path):
            return

        # Add to recent files
        self._add_recent_file(path)

        # Load into current tab
        page = self.pages.get(self.current_page)
        if page is None:
            return

        loaded = False
        for attr in ("_src_var", "src_var"):
            if hasattr(page, attr):
                try:
                    getattr(page, attr).set(path)
                    if hasattr(page, "file_path"):
                        page.file_path = path
                    if hasattr(page, "duration"):
                        from core.hardware import get_video_duration
                        page.duration = get_video_duration(path)
                        if hasattr(page, "_timeline"):
                            page._timeline.set_duration(page.duration)
                        for a in ("_scrub_sc", "_scrub"):
                            if hasattr(page, a):
                                getattr(page, a).config(to=max(page.duration, 1))
                        if hasattr(page, "_draw"):
                            page._draw()
                    # Auto-fill output path
                    base = os.path.splitext(path)[0]
                    for oa in ("_out_var", "out_var"):
                        if hasattr(page, oa) and not getattr(page, oa).get():
                            getattr(page, oa).set(base + "_output.mp4")
                    loaded = True
                    break
                except Exception:
                    pass
        if not loaded and hasattr(page, "file_path"):
            page.file_path = path
            loaded = True

        if loaded:
            self.title("Quintessential Video Editor  ·  {}  ·  {}".format(
                self.current_page, os.path.basename(path)))
            self.set_status("Loaded: {}".format(os.path.basename(path)),
                           color=self._skin_data["green"])
        else:
            self.set_status("Drop: use Browse in '{}' to load files".format(
                self.current_page))

    # ─────────────────────────────────────────────────────────────────────────
    #  Recent files
    # ─────────────────────────────────────────────────────────────────────────
    _MAX_RECENT = 10

    def _load_recent_files(self):
        from core.settings import load_settings
        return load_settings().get("recent_files", [])

    def _add_recent_file(self, path):
        from core.settings import load_settings, save_settings
        settings = load_settings()
        recent = settings.get("recent_files", [])
        # Normalise path
        path = os.path.normpath(path)
        # Remove if already present (will re-add at top)
        recent = [r for r in recent if os.path.normpath(r) != path]
        recent.insert(0, path)
        recent = recent[:self._MAX_RECENT]
        settings["recent_files"] = recent
        save_settings(settings)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        if not hasattr(self, "_recent_menu"):
            return
        menu = self._recent_menu
        menu.delete(0, tk.END)
        recent = self._load_recent_files()
        if not recent:
            menu.add_command(label="(no recent files)", state="disabled")
            return
        for path in recent:
            basename = os.path.basename(path)
            menu.add_command(
                label=basename,
                command=lambda p=path: self._open_recent(p))
        menu.add_separator()
        menu.add_command(label="Clear Recent Files",
                         command=self._clear_recent_files)

    def _open_recent(self, path):
        if not os.path.isfile(path):
            messagebox.showwarning("File Not Found",
                                   f"File no longer exists:\n{path}")
            return
        self._add_recent_file(path)
        # Reuse the menu open logic
        page = self.pages.get(self.current_page)
        if page is None:
            return
        for attr in ("_src_var", "src_var"):
            if hasattr(page, attr):
                try:
                    getattr(page, attr).set(path)
                    if hasattr(page, "file_path"):
                        page.file_path = path
                    if hasattr(page, "duration"):
                        from core.hardware import get_video_duration
                        page.duration = get_video_duration(path)
                        if hasattr(page, "_timeline"):
                            page._timeline.set_duration(page.duration)
                    base = os.path.splitext(path)[0]
                    for oa in ("_out_var", "out_var"):
                        if hasattr(page, oa) and not getattr(page, oa).get():
                            getattr(page, oa).set(base + "_output.mp4")
                except Exception:
                    pass
                break
        self.title("Quintessential Video Editor  ·  {}  ·  {}".format(
            self.current_page, os.path.basename(path)))
        self.set_status("Loaded: {}".format(os.path.basename(path)),
                       color=self._skin_data["green"])

    def _clear_recent_files(self):
        from core.settings import load_settings, save_settings
        settings = load_settings()
        settings["recent_files"] = []
        save_settings(settings)
        self._rebuild_recent_menu()

    def _on_closing(self):
        self._stop_active_previews(closing=True)
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import multiprocessing

    # CRITICAL: This line prevents the infinite opening of .exe windows
    # when using PyInstaller/cx_Freeze on Windows!
    multiprocessing.freeze_support()

    if "--no-ai" in sys.argv:
        os.environ["CROSSFADER_NO_AI_TEST"] = "1"

    app = App()
    app.mainloop()