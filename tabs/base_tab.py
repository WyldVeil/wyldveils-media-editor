"""
base_tab.py  ─  Shared utilities for all Studio Pro tabs.

Provides:
  • CLR - live skin color dict
  • BaseTab - base class for all tool tabs
  • make_header, make_console, make_file_row, make_section,
    make_render_btn, make_labeled_entry - UI factory helpers
"""
import tkinter as tk
from tkinter import ttk
import subprocess
import threading
import time
import os

from core.hardware import get_binary_path, CREATE_NO_WINDOW, open_in_explorer
from core.skins import UI_FONT, MONO_FONT
from core.i18n import t


def _load_clr():
    try:
        from core.skins import get_skin, load_skin_name
        skin = get_skin(load_skin_name())
        return {
            "bg":         skin["content"],
            "panel":      skin["panel"],
            "accent":     skin["accent"],
            "fg":         skin["fg"],
            "fgdim":      skin["fgdim"],
            "green":      skin["green"],
            "red":        skin["red"],
            "orange":     skin["orange"],
            "pink":       skin["pink"],
            "console_bg": skin["console_bg"],
            "console_fg": skin["console_fg"],
            "border":     skin.get("border", "#2C2C2C"),
            "input_bg":   skin.get("input_bg", "#1E1E1E"),
            "input_fg":   skin.get("input_fg", "#E2E2E2"),
        }
    except Exception:
        return {
            "bg": "#1A1A1A", "panel": "#212121", "accent": "#3A8EE6",
            "fg": "#E2E2E2", "fgdim": "#7A7A7A", "green": "#2ECC71",
            "red": "#E74C3C", "orange": "#F39C12", "pink": "#C0392B",
            "console_bg": "#0A0A0A", "console_fg": "#00E676",
            "border": "#2C2C2C", "input_bg": "#1E1E1E", "input_fg": "#E2E2E2",
        }


CLR = _load_clr()


# ─────────────────────────────────────────────────────────────────────────────
#  UI factory helpers (module-level so tabs can use them directly)
# ─────────────────────────────────────────────────────────────────────────────

def make_header(parent, title, subtitle="", icon=""):
    """
    Professional two-row tab header:
      ┌───────────────────────────────────────────┐
      │  ICON  Title                              │
      │        Subtitle description               │
      └───────────────────────────────────────────┘
    Returns the outer header frame.
    """
    hdr = tk.Frame(parent, bg=CLR["panel"])
    hdr.pack(fill="x")

    inner = tk.Frame(hdr, bg=CLR["panel"])
    inner.pack(fill="x", padx=22, pady=(14, 12))

    left = tk.Frame(inner, bg=CLR["panel"])
    left.pack(side="left", fill="both", expand=True)

    title_text = f"{icon}  {title}".strip() if icon else title
    tk.Label(left, text=title_text,
             font=(UI_FONT, 14, "bold"),
             bg=CLR["panel"], fg=CLR["accent"],
             anchor="w").pack(side="top", fill="x")

    if subtitle:
        tk.Label(left, text=subtitle,
                 font=(UI_FONT, 9),
                 bg=CLR["panel"], fg=CLR["fgdim"],
                 anchor="w").pack(side="top", fill="x", pady=(2, 0))

    # Bottom border
    tk.Frame(parent, bg=CLR["border"], height=1).pack(fill="x")
    return hdr


def make_section(parent, title="", padx=20, pady=(8, 4)):
    """
    Return a styled LabelFrame for grouping related controls.
    Matches the professional card appearance.
    """
    lf = tk.LabelFrame(
        parent,
        text=f"  {title}  " if title else "",
        bg=CLR["bg"],
        fg=CLR["fgdim"],
        font=(UI_FONT, 8, "bold"),
        bd=1,
        relief="solid",
        padx=14, pady=8,
        highlightthickness=0,
    )
    # LabelFrame borders are drawn in the widget's fg - set border via relief
    lf.pack(fill="x", padx=padx, pady=pady)
    return lf


def make_console(parent, height=8):
    """
    Styled console text widget + scrollbar.
    Returns (Text, Scrollbar) - caller packs them.
    """
    c = tk.Text(
        parent,
        height=height,
        bg=CLR["console_bg"],
        fg=CLR["console_fg"],
        font=(MONO_FONT, 9),
        wrap="none",
        relief="flat",
        bd=0,
        insertbackground=CLR["console_fg"],
        selectbackground=CLR["accent"],
        selectforeground="#FFFFFF",
        padx=12, pady=8,
        highlightthickness=0,
    )
    # Tag for green "Done" lines
    c.tag_configure("success", foreground=CLR["green"])
    c.tag_configure("error",   foreground=CLR["red"])
    c.tag_configure("warn",    foreground=CLR["orange"])
    c.tag_configure("info",    foreground=CLR["accent"])
    c.tag_configure("dim",     foreground=CLR["fgdim"])

    sb = ttk.Scrollbar(parent, command=c.yview)
    c.configure(yscrollcommand=sb.set)
    return c, sb


def make_file_row(parent, label, var, browse_cmd, width=52, label_width=18):
    """
    Standard source/output file row with consistent label alignment.
    Returns the row Frame.
    """
    f = tk.Frame(parent, bg=CLR["bg"])
    tk.Label(f, text=label,
             font=(UI_FONT, 9, "bold"),
             width=label_width, anchor="e",
             bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left")
    tk.Entry(f, textvariable=var, width=width,
             relief="flat",
             bg=CLR["input_bg"], fg=CLR["input_fg"],
             insertbackground=CLR["accent"],
             highlightthickness=1,
             highlightbackground=CLR["border"],
             highlightcolor=CLR["accent"],
             font=(UI_FONT, 9)).pack(side="left", padx=8)
    btn = tk.Button(f, text=t("btn.browse"),
                    font=(UI_FONT, 9),
                    bg=CLR["panel"], fg=CLR["fg"],
                    activebackground=CLR["accent"],
                    activeforeground="#FFFFFF",
                    relief="flat", cursor="hand2",
                    padx=10, pady=3,
                    command=browse_cmd)
    btn.pack(side="left")
    return f


def make_labeled_entry(parent, label, var, width=8, tooltip=""):
    """Inline label + entry, optionally with a dim tooltip/hint."""
    f = tk.Frame(parent, bg=CLR["bg"])
    tk.Label(f, text=label,
             font=(UI_FONT, 9),
             bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
    tk.Entry(f, textvariable=var, width=width,
             relief="flat",
             bg=CLR["input_bg"], fg=CLR["input_fg"],
             insertbackground=CLR["accent"],
             highlightthickness=0,
             font=(UI_FONT, 9)).pack(side="left", padx=4)
    if tooltip:
        tk.Label(f, text=tooltip,
                 fg=CLR["fgdim"],
                 bg=CLR["bg"],
                 font=(UI_FONT, 8)).pack(side="left", padx=(2, 0))
    return f


def make_render_btn(parent, text, command, color=None, width=24):
    """
    Large, prominent render/action button.
    Uses accent color by default; pass color= to override (green/orange/red).
    """
    bg = color or CLR["accent"]
    # Compute a darker active state
    btn = tk.Button(
        parent,
        text=text,
        font=(UI_FONT, 11, "bold"),
        bg=bg,
        fg="#FFFFFF",
        activebackground=CLR["fgdim"],
        activeforeground="#FFFFFF",
        relief="flat",
        cursor="hand2",
        height=2,
        width=width,
        bd=0,
        highlightthickness=0,
        command=command,
    )
    return btn


# ─────────────────────────────────────────────────────────────────────────────
#  ToolTip - hover tooltip for any widget
# ─────────────────────────────────────────────────────────────────────────────

class ToolTip:
    """
    Hover tooltip that appears after a short delay.

    Usage::

        btn = tk.Button(parent, text="Render")
        ToolTip(btn, "Start rendering the output file (Ctrl+S)")

    Or via the helper::

        add_tooltip(btn, "Start rendering the output file")
    """

    _DELAY = 500      # ms before showing
    _WRAP  = 280      # max tooltip width in pixels

    def __init__(self, widget, text):
        self._widget = widget
        self._text   = text
        self._tip    = None
        self._after  = None
        widget.bind("<Enter>",  self._on_enter, add=True)
        widget.bind("<Leave>",  self._on_leave, add=True)
        widget.bind("<Button>", self._on_leave, add=True)

    def _on_enter(self, event=None):
        self._cancel()
        self._after = self._widget.after(self._DELAY, self._show)

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after:
            self._widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self._text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        # Attempt to remove from taskbar on Windows
        try:
            tw.wm_attributes("-toolwindow", True)
        except Exception:
            pass
        lbl = tk.Label(tw, text=self._text,
                       bg="#2A2A2A", fg="#E0E0E0",
                       font=(UI_FONT, 8),
                       relief="solid", bd=1,
                       wraplength=self._WRAP,
                       justify="left",
                       padx=8, pady=5)
        lbl.pack()

    def _hide(self):
        if self._tip:
            self._tip.destroy()
            self._tip = None


def add_tooltip(widget, text):
    """Convenience function to attach a tooltip to any widget."""
    return ToolTip(widget, text)


# ─────────────────────────────────────────────────────────────────────────────
#  VideoTimeline - reusable canvas timeline with dual handles + playhead
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_tl(seconds):
    """Format seconds for timeline display."""
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"
    return f"{int(m):02d}:{s:05.2f}"


class VideoTimeline(tk.Frame):
    """
    Reusable dual-handle timeline with playhead scrubber.

    Drop-in widget for any tab that needs a visual time range selector.
    Provides start/end handles (draggable), a playhead, tick marks,
    and optional preview integration via callback.

    Usage::

        tl = VideoTimeline(parent, on_change=my_callback)
        tl.pack(fill="x", padx=20, pady=4)
        tl.set_duration(120.5)            # set total duration in seconds
        tl.set_range(10.0, 90.0)          # set start/end programmatically
        s, e = tl.get_range()             # read current start/end
        t = tl.get_playhead()             # read playhead position
    """

    _PAD     = 28      # horizontal padding
    _HR      = 8       # handle radius
    _HEIGHT  = 100     # default canvas height

    def __init__(self, parent, on_change=None, height=None, show_handles=True):
        super().__init__(parent, bg=CLR["bg"])
        self._duration    = 0.0
        self._start       = 0.0
        self._end         = 0.0
        self._playhead    = 0.0
        self._dragging    = None
        self._on_change   = on_change    # callback(start, end, playhead)
        self._show_handles = show_handles
        ch = height or self._HEIGHT

        # Canvas
        self._canvas = tk.Canvas(self, bg="#0D0D0D", height=ch,
                                  highlightthickness=0, bd=0)
        self._canvas.pack(fill="x", padx=4, pady=4)
        self._canvas.bind("<Configure>",      lambda _: self._draw())
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", lambda _: self._on_release())

        # Info strip below canvas
        info = tk.Frame(self, bg=CLR["bg"])
        info.pack(fill="x", padx=8)
        self._pos_lbl = tk.Label(info, text="00:00.00",
                                  fg=CLR["accent"], bg=CLR["bg"],
                                  font=(MONO_FONT, 9, "bold"))
        self._pos_lbl.pack(side="left")
        self._range_lbl = tk.Label(info, text="",
                                    fg=CLR["fgdim"], bg=CLR["bg"],
                                    font=(MONO_FONT, 8))
        self._range_lbl.pack(side="right")

    # ── Public API ────────────────────────────────────────────────────────

    def set_duration(self, dur):
        self._duration = max(0.0, dur)
        self._end = self._duration
        self._start = 0.0
        self._playhead = 0.0
        self._draw()

    def set_range(self, start, end):
        self._start = max(0.0, min(start, self._duration))
        self._end   = max(self._start, min(end, self._duration))
        self._draw()
        self._fire_change()

    def get_range(self):
        return (self._start, self._end)

    def get_playhead(self):
        return self._playhead

    def set_playhead(self, t):
        self._playhead = max(0.0, min(t, self._duration))
        self._draw()

    # ── Coordinate helpers ────────────────────────────────────────────────

    def _t2x(self, t, w):
        p = self._PAD
        if self._duration <= 0:
            return p
        return p + int((t / self._duration) * (w - 2 * p))

    def _x2t(self, x, w):
        p = self._PAD
        if self._duration <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - p) / max(1, w - 2 * p))) * self._duration

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw(self):
        c = self._canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 20:
            return
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill="#0D0D0D", outline="")

        if self._duration <= 0:
            c.create_text(w // 2, h // 2,
                          text="Load a file to see the timeline",
                          fill=CLR["fgdim"], font=(UI_FONT, 10))
            return

        cy = h // 2

        # Track background
        c.create_rectangle(self._PAD, cy - 5, w - self._PAD, cy + 5,
                           fill="#222222", outline="")

        if self._show_handles:
            # Selection highlight
            xs = self._t2x(self._start, w)
            xe = self._t2x(self._end, w)
            c.create_rectangle(xs, cy - 5, xe, cy + 5,
                               fill="#1A5A98", outline="")

        # Tick marks + time labels
        num_ticks = min(20, max(5, w // 80))
        for i in range(num_ticks + 1):
            frac = i / num_ticks
            tx = self._t2x(self._duration * frac, w)
            c.create_line(tx, cy + 7, tx, cy + 14, fill="#444444")
            tick_t = self._duration * frac
            c.create_text(tx, cy + 23, text=_fmt_tl(tick_t),
                          fill="#555555", font=(UI_FONT, 7))

        # Playhead
        xp = self._t2x(self._playhead, w)
        c.create_line(xp, cy - 20, xp, cy + 20, fill="#FFEB3B", width=2)
        c.create_polygon(xp - 6, cy - 20, xp + 6, cy - 20, xp, cy - 11,
                         fill="#FFEB3B", outline="#000000", width=1)

        if self._show_handles:
            # Start handle (green)
            c.create_oval(xs - self._HR, cy - self._HR,
                          xs + self._HR, cy + self._HR,
                          fill="#4CAF50", outline="white", width=2)
            c.create_text(xs, cy - 20,
                          text=f"IN {_fmt_tl(self._start)}",
                          fill="#4CAF50", font=(MONO_FONT, 8, "bold"))

            # End handle (red)
            c.create_oval(xe - self._HR, cy - self._HR,
                          xe + self._HR, cy + self._HR,
                          fill="#F44336", outline="white", width=2)
            c.create_text(xe, cy + 34,
                          text=f"OUT {_fmt_tl(self._end)}",
                          fill="#F44336", font=(MONO_FONT, 8, "bold"))

            # Selection duration
            sel = max(0.0, self._end - self._start)
            c.create_text((xs + xe) // 2, 12,
                          text=f"Selection: {_fmt_tl(sel)}",
                          fill="white", font=(UI_FONT, 9, "bold"))

        # Update info labels
        self._pos_lbl.config(text=_fmt_tl(self._playhead))
        if self._show_handles:
            sel = max(0.0, self._end - self._start)
            self._range_lbl.config(
                text=f"{_fmt_tl(self._start)} \u2192 {_fmt_tl(self._end)}  "
                     f"({_fmt_tl(sel)})")

    # ── Interaction ───────────────────────────────────────────────────────

    def _on_press(self, ev):
        w = self._canvas.winfo_width()
        if self._duration <= 0:
            return
        def near(a, b):
            return abs(a - b) < 14

        if self._show_handles:
            xs = self._t2x(self._start, w)
            xe = self._t2x(self._end, w)
            if near(ev.x, xs):
                self._dragging = "start"
                return
            if near(ev.x, xe):
                self._dragging = "end"
                return

        # Click anywhere else = move playhead
        self._dragging = "playhead"
        self._playhead = self._x2t(ev.x, w)
        self._draw()
        self._fire_change()

    def _on_drag(self, ev):
        if not self._dragging:
            return
        w = self._canvas.winfo_width()
        t = self._x2t(ev.x, w)

        if self._dragging == "start":
            self._start = max(0.0, min(t, self._end - 0.1))
        elif self._dragging == "end":
            self._end = max(self._start + 0.1, min(t, self._duration))
        elif self._dragging == "playhead":
            self._playhead = max(0.0, min(t, self._duration))

        self._draw()
        self._fire_change()

    def _on_release(self):
        self._dragging = None

    def _fire_change(self):
        if self._on_change:
            self._on_change(self._start, self._end, self._playhead)


# ─────────────────────────────────────────────────────────────────────────────
#  BaseTab
# ─────────────────────────────────────────────────────────────────────────────

class BaseTab(ttk.Frame):
    """
    Common base class for all Studio Pro tool tabs.

    Key API:
      log(widget, msg)                 - thread-safe append to console Text
      log_tagged(widget, msg, tag)     - append with colour tag
      run_ffmpeg(cmd, console, ...)    - run FFmpeg in background thread
      run_in_thread(func, ...)         - run arbitrary function in background
      show_result(returncode, out)     - success/error feedback
      make_header / make_console / ... - UI helpers (also module-level)
    """

    # Expose module-level helpers as static/class methods so tabs can use
    # either BaseTab.make_console() or self.make_console()
    make_header        = staticmethod(make_header)
    make_section       = staticmethod(make_section)
    make_console       = staticmethod(make_console)
    make_file_row      = staticmethod(make_file_row)
    make_labeled_entry = staticmethod(make_labeled_entry)
    make_render_btn    = staticmethod(make_render_btn)
    VideoTimeline      = VideoTimeline      # expose for easy access
    ToolTip            = ToolTip
    add_tooltip        = staticmethod(add_tooltip)

    def __init__(self, parent):
        super().__init__(parent)
        self._render_thread = None
        self.preview_proc   = None

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, widget, msg):
        """Thread-safe append to a console Text widget."""
        def _do():
            try:
                widget.insert(tk.END, f"{msg}\n")
                widget.see(tk.END)
                widget.update_idletasks()
            except Exception:
                pass
        self.after(0, _do)

    def log_tagged(self, widget, msg, tag=""):
        """Append with a colour tag (success, error, warn, info, dim)."""
        def _do():
            try:
                start = widget.index(tk.END)
                widget.insert(tk.END, f"{msg}\n")
                if tag:
                    end = widget.index(tk.END)
                    widget.tag_add(tag, f"{start} linestart", end)
                widget.see(tk.END)
                widget.update_idletasks()
            except Exception:
                pass
        self.after(0, _do)

    def log_debug(self, msg):
        app = self.winfo_toplevel()
        if hasattr(app, "log_debug"):
            app.log_debug(msg)

    # ── Thread helpers ────────────────────────────────────────────────────────

    def run_in_thread(self, func, *args, **kwargs):
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t

    # ── Queue bridge ──────────────────────────────────────────────────────────

    def enqueue_render(
        self,
        task_name: str,
        output_path: str = "",
        *,
        cmd=None,
        cmds=None,
        worker_fn=None,
        on_start=None,
        on_progress=None,
        on_complete=None,
    ) -> str:
        """
        Submit a render job to the global RenderQueueManager.

        Provide exactly one of:
          cmd        - a single FFmpeg command list
          cmds       - a list of FFmpeg command lists (run sequentially)
          worker_fn  - callable(progress_cb, cancel_fn) -> int  for complex
                       multi-step workflows

        Callbacks are invoked on the Tkinter main thread:
          on_start(task_id)
          on_progress(task_id, line)
          on_complete(task_id, returncode)

        Returns the task_id string.
        """
        from core.queue_manager import RenderQueueManager
        return RenderQueueManager.get_instance().enqueue(
            name=task_name,
            output_path=output_path,
            cmd=cmd,
            cmds=cmds,
            worker_fn=worker_fn,
            on_start=on_start,
            on_progress=on_progress,
            on_complete=on_complete,
        )

    # ── FFmpeg runner ─────────────────────────────────────────────────────────

    def run_ffmpeg(self, cmd, console=None, on_done=None,
                   btn=None, btn_label="▶  Run"):
        """
        Submit an FFmpeg command to the global background render queue.
        Streams output to console, manages button state, and updates the
        status bar.  The task is queued and will start as soon as the
        worker thread is free - existing renders are never interrupted.
        """
        app = self.winfo_toplevel()

        # Disable the button immediately so the user can't double-submit
        if btn:
            self.after(0, lambda: btn.config(
                state="disabled", text=t("app.status.queued_btn")))
        if hasattr(app, "set_status"):
            self.after(0, lambda: app.set_status(t("app.status.queued")))

        self.log_debug("Queuing: " + " ".join(str(c) for c in cmd))

        # Record submission time; elapsed includes any queue wait - we reset
        # t_start to the actual start time inside on_start.
        _t = [time.time()]   # mutable container so closure can update it

        def _on_start(task_id):
            _t[0] = time.time()            # reset to actual start
            if btn:
                btn.config(text=t("app.status.processing_btn"))
            if hasattr(app, "set_status"):
                app.set_status(t("app.status.processing"))

        def _on_progress(task_id, line):
            if console:
                self.log(console, line)
            # Feed progress to status bar progress bar
            if hasattr(app, "update_render_progress"):
                app.update_render_progress(line)

        def _on_complete(task_id, returncode):
            elapsed = time.time() - _t[0]
            elapsed_str = (f"{elapsed:.1f}s" if elapsed < 60
                           else f"{int(elapsed//60)}m {int(elapsed%60)}s")
            if btn:
                btn.config(state="normal", text=btn_label)
            if hasattr(app, "set_status"):
                if returncode == 0:
                    app.set_status(t("app.status.done", elapsed=elapsed_str))
                else:
                    app.set_status(t("app.status.error_code", code=returncode),
                                   color=CLR["red"])
            if on_done:
                on_done(returncode)

        self._render_thread = self.enqueue_render(
            "Render",
            cmd=cmd,
            on_start=_on_start,
            on_progress=_on_progress,
            on_complete=_on_complete,
        )

    # ── Result display ────────────────────────────────────────────────────────

    def show_result(self, returncode, out_path=""):
        """
        Show success or error feedback.
        Success: messagebox with optional 'Open folder' action.
        Error:   error dialog with instructions.
        """
        from tkinter import messagebox
        if returncode == 0:
            msg = "{}\n\n{}".format(t("common.complete"), out_path) if out_path else t("common.complete")
            messagebox.showinfo(t("common.done"), msg)
            if out_path:
                try:
                    from core.settings import load_settings
                    if load_settings().get("auto_open_output", False):
                        folder = (os.path.dirname(out_path)
                                  if not os.path.isdir(out_path) else out_path)
                        open_in_explorer(folder)
                except Exception:
                    pass
        else:
            messagebox.showerror(
                t("common.render_error_title"),
                t("common.render_error_msg", code=returncode))

    # ── Convenience ───────────────────────────────────────────────────────────

    @staticmethod
    def open_path(path):
        return open_in_explorer(path)
