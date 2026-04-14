"""
core/skins.py  ─  Skin / theming engine

Reads skin.json, re-colours the sidebar, content, ttk styles, and
base_tab CLR palette.  Mystical skin gets animated star particles.

Supports LIVE skin switching via apply_skin() - no restart needed.
"""
import tkinter as tk
from tkinter import ttk
import os
import json
import random
import sys

SKIN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skin.json")

# ── Platform-aware font selection ─────────────────────────────────────────────
def _detect_ui_font():
    if sys.platform == "win32":
        return "Segoe UI"
    elif sys.platform == "darwin":
        return "SF Pro Display"
    return "Ubuntu"

def _detect_mono_font():
    if sys.platform == "win32":
        return "Consolas"
    elif sys.platform == "darwin":
        return "Menlo"
    return "Ubuntu Mono"

UI_FONT   = _detect_ui_font()
MONO_FONT = _detect_mono_font()

# ── Default colors for the Custom skin (based on Classic) ────────────────────
_CUSTOM_DEFAULTS: dict = {
    "sb_bg":      "#111111", "sb_cat":     "#424242", "sb_btn":     "#B0B0B0",
    "sb_hover":   "#1C1C1C", "sb_active":  "#212121", "accent":     "#3A8EE6",
    "content":    "#1A1A1A", "panel":      "#212121", "fg":         "#E2E2E2",
    "fgdim":      "#7A7A7A", "green":      "#2ECC71", "red":        "#E74C3C",
    "orange":     "#F39C12", "pink":       "#C0392B",
    "console_bg": "#0A0A0A", "console_fg": "#00E676",
    "border":     "#2C2C2C", "input_bg":   "#1E1E1E", "input_fg":   "#E2E2E2",
    "stars": False,
    "desc": "Your personal color scheme.",
}

SKINS = {
    "Classic": {
        # Professional dark - all surfaces dark, blue-cyan accent
        "sb_bg":      "#111111", "sb_cat":     "#424242", "sb_btn":     "#B0B0B0",
        "sb_hover":   "#1C1C1C", "sb_active":  "#212121", "accent":     "#3A8EE6",
        "content":    "#1A1A1A", "panel":      "#212121", "fg":         "#E2E2E2",
        "fgdim":      "#7A7A7A", "green":      "#2ECC71", "red":        "#E74C3C",
        "orange":     "#F39C12", "pink":       "#C0392B",
        "console_bg": "#0A0A0A", "console_fg": "#00E676",
        "border":     "#2C2C2C", "input_bg":   "#1E1E1E", "input_fg":   "#E2E2E2",
        "stars": False,
        "desc": "Professional dark. Premiere Pro inspired.",
    },
    "Space": {
        "sb_bg":      "#080812", "sb_cat":     "#24244A", "sb_btn":     "#00E890",
        "sb_hover":   "#10102A", "sb_active":  "#18183A", "accent":     "#00E890",
        "content":    "#0B0B18", "panel":      "#10102A", "fg":         "#00E890",
        "fgdim":      "#2E6644", "green":      "#00CC77", "red":        "#FF2255",
        "orange":     "#FF9900", "pink":       "#FF22AA",
        "console_bg": "#040410", "console_fg": "#00FFCC",
        "border":     "#1E1E3A", "input_bg":   "#141428", "input_fg":   "#00E890",
        "stars": False,
        "desc": "Deep space: dark navy with electric neon green.",
    },
    "Night": {
        "sb_bg":      "#0B1C2A", "sb_cat":     "#284660", "sb_btn":     "#A8DFE8",
        "sb_hover":   "#162E40", "sb_active":  "#1B3650", "accent":     "#22BDD0",
        "content":    "#0D1E2E", "panel":      "#112232", "fg":         "#A8DFE8",
        "fgdim":      "#3E5A6C", "green":      "#1E9E92", "red":        "#EF4444",
        "orange":     "#F59E0B", "pink":       "#E8407A",
        "console_bg": "#080F18", "console_fg": "#4DD0E1",
        "border":     "#1A3040", "input_bg":   "#112232", "input_fg":   "#A8DFE8",
        "stars": False,
        "desc": "Deep teal night mode. Easy on the eyes.",
    },
    "Dark Mode": {
        "sb_bg":      "#1A1A1C", "sb_cat":     "#363638", "sb_btn":     "#E2E2E6",
        "sb_hover":   "#2A2A2C", "sb_active":  "#383838", "accent":     "#0A84FF",
        "content":    "#1A1A1C", "panel":      "#2A2A2C", "fg":         "#E2E2E6",
        "fgdim":      "#8A8A90", "green":      "#28C952", "red":        "#FF3A30",
        "orange":     "#FF9F05", "pink":       "#FF3058",
        "console_bg": "#000000", "console_fg": "#30D14A",
        "border":     "#363638", "input_bg":   "#2A2A2C", "input_fg":   "#E2E2E6",
        "stars": False,
        "desc": "System dark mode. Matches macOS / Windows dark UI.",
    },
    "Low Blue": {
        "sb_bg":      "#181000", "sb_cat":     "#3A2C00", "sb_btn":     "#FFD060",
        "sb_hover":   "#281C00", "sb_active":  "#302200", "accent":     "#FFB000",
        "content":    "#181000", "panel":      "#201600", "fg":         "#FFD060",
        "fgdim":      "#725A2A", "green":      "#88BB40", "red":        "#F44336",
        "orange":     "#FF8800", "pink":       "#F06090",
        "console_bg": "#100C00", "console_fg": "#FF9800",
        "border":     "#2A2000", "input_bg":   "#201600", "input_fg":   "#FFD060",
        "stars": False,
        "desc": "Warm amber tones. Minimal blue light for late-night editing.",
    },
    "Mystical": {
        "sb_bg":      "#0C0818", "sb_cat":     "#28184A", "sb_btn":     "#CC88D8",
        "sb_hover":   "#180828", "sb_active":  "#201040", "accent":     "#A840BC",
        "content":    "#0C0818", "panel":      "#180828", "fg":         "#DDB8E8",
        "fgdim":      "#60407A", "green":      "#7B1FA2", "red":        "#E8186A",
        "orange":     "#FF6800", "pink":       "#F080B0",
        "console_bg": "#070518", "console_fg": "#CC88D8",
        "border":     "#28184A", "input_bg":   "#180828", "input_fg":   "#DDB8E8",
        "stars": True,
        "desc": "Fantasy purple with falling star particles ✨",
    },
    "Custom": {
        **_CUSTOM_DEFAULTS,
    },
}


def load_skin_name() -> str:
    try:
        if os.path.exists(SKIN_FILE):
            with open(SKIN_FILE) as f:
                return json.load(f).get("name", "Classic")
    except Exception:
        pass
    return "Classic"


def save_skin_name(name: str):
    try:
        with open(SKIN_FILE, "w") as f:
            json.dump({"name": name}, f)
    except Exception:
        pass


def get_skin(name: str) -> dict:
    """Return the skin dict for *name*.
    For "Custom", overlay saved user colours from settings.json on top of defaults.
    """
    if name == "Custom":
        skin = dict(_CUSTOM_DEFAULTS)
        try:
            from core.settings import load_settings as _ls
            saved = _ls()
            prefix = "custom_color_"
            for key, val in saved.items():
                if key.startswith(prefix):
                    color_key = key[len(prefix):]
                    if color_key in skin:
                        skin[color_key] = val
        except Exception:
            pass
        return skin
    return SKINS.get(name, SKINS["Classic"])


def save_custom_color(color_key: str, value: str) -> None:
    """Persist a single custom-skin color to settings.json."""
    try:
        from core.settings import load_settings as _ls, save_settings as _ss
        data = _ls()
        data[f"custom_color_{color_key}"] = value
        _ss(data)
    except Exception as exc:
        print(f"[Skins] save_custom_color failed: {exc}")


# ── Module-level state for star animation ────────────────────────────────────
_star_canvas   = None
_star_toplevel = None      # click-through Toplevel overlay (Windows)
_star_data: list = []
_star_after_id = None
# Unique chroma-key colour - never used in any real skin palette
_STAR_CHROMA   = "#010203"
# Speed multiplier: 1.0 = default, <1 slower, >1 faster
_star_speed_mult: float = 1.0
# Star count (density)
_star_count: int = 55


def get_star_speed() -> float:
    """Return the current star speed multiplier."""
    return _star_speed_mult


def set_star_speed(mult: float) -> None:
    """Set the star speed multiplier live (no restart needed)."""
    global _star_speed_mult
    _star_speed_mult = float(mult)


def get_star_count() -> int:
    """Return the current star density count."""
    return _star_count


def set_star_count(count: int) -> None:
    """Set the number of stars. Takes effect on next skin apply."""
    global _star_count
    _star_count = max(10, int(count))


def _stop_stars():
    """Kill any running star animation and destroy all overlay widgets."""
    global _star_canvas, _star_toplevel, _star_data, _star_after_id
    if _star_after_id is not None:
        try:
            if _star_canvas and _star_canvas.winfo_exists():
                _star_canvas.after_cancel(_star_after_id)
        except Exception:
            pass
        _star_after_id = None
    # Destroying the Toplevel also destroys the canvas inside it
    if _star_toplevel is not None:
        try:
            if _star_toplevel.winfo_exists():
                _star_toplevel.destroy()
        except Exception:
            pass
        _star_toplevel = None
        _star_canvas   = None
    elif _star_canvas is not None:
        try:
            if _star_canvas.winfo_exists():
                _star_canvas.destroy()
        except Exception:
            pass
        _star_canvas = None
    _star_data.clear()


def _start_stars(app: tk.Tk, skin: dict, inner_frame=None):
    """Spawn the Mystical falling-star particle overlay across the full window.

    On Windows: creates a borderless click-through Toplevel that sits over the
    entire app. The background is chroma-keyed transparent (-transparentcolor),
    so only the star glyphs are visible. WS_EX_TRANSPARENT lets all mouse events
    fall through to the main window beneath.

    On other platforms: falls back to a canvas on the app root (limited effect).
    The inner_frame parameter is accepted for API compatibility but not used.
    """
    global _star_canvas, _star_toplevel, _star_data, _star_after_id

    _stop_stars()

    # Load persisted speed / density preferences
    try:
        from core.settings import get as _get_setting
        set_star_speed(_get_setting("star_speed", 1.0))
        set_star_count(int(_get_setting("star_count", 55)))
    except Exception:
        pass
    CHARS   = ["✦", "✧", "⋆", "·", "˚", "∘", "*"]
    COLOURS = ["#E1BEE7", "#CE93D8", "#BA68C8",
               "#AB47BC", "#F3E5F5", "#D1C4E9",
               "#B39DDB", "#EDE7F6"]

    if sys.platform == "win32":
        import ctypes

        _star_toplevel = tk.Toplevel(app)
        _star_toplevel.overrideredirect(True)
        _star_toplevel.configure(bg=_STAR_CHROMA)
        _star_toplevel.attributes("-transparentcolor", _STAR_CHROMA)
        _star_toplevel.attributes("-topmost", True)
        _star_toplevel.lift()

        # Apply WS_EX_TRANSPARENT | WS_EX_LAYERED so the overlay is
        # completely click-through - all mouse events reach the app below.
        def _make_clickthrough():
            try:
                _star_toplevel.update_idletasks()
                raw = _star_toplevel.winfo_id()
                hwnd = ctypes.windll.user32.GetParent(raw) or raw
                GWL_EXSTYLE     = -20
                WS_EX_LAYERED   = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            except Exception:
                pass
        app.after(80, _make_clickthrough)

        _star_canvas = tk.Canvas(
            _star_toplevel, bg=_STAR_CHROMA, highlightthickness=0, bd=0)
        _star_canvas.pack(fill="both", expand=True)

        # Keep overlay geometry in sync with main window (move / resize)
        def _sync():
            if _star_toplevel is None or not _star_toplevel.winfo_exists():
                return
            try:
                if app.state() == "iconic":
                    _star_toplevel.withdraw()
                else:
                    _star_toplevel.deiconify()
                    x = app.winfo_rootx()
                    y = app.winfo_rooty()
                    w = app.winfo_width()
                    h = app.winfo_height()
                    _star_toplevel.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
            _star_toplevel.after(500, _sync)

        # Bind to Configure for immediate response to resize/move
        def _on_configure(event):
            try:
                if _star_toplevel and _star_toplevel.winfo_exists():
                    x = app.winfo_rootx()
                    y = app.winfo_rooty()
                    w = app.winfo_width()
                    h = app.winfo_height()
                    _star_toplevel.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
        app.bind("<Configure>", _on_configure, add=True)
        app.after(50, _sync)

    else:
        # Non-Windows fallback - canvas on root, lower behind content
        _star_canvas = tk.Canvas(app, bg=skin["sb_bg"],
                                  highlightthickness=0, bd=0)
        _star_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        try:
            _star_canvas.lower()
        except Exception:
            pass

    # _star_data is populated lazily on the first tick.
    # We use the MAIN APP window dimensions (always reliable) rather than the
    # canvas/Toplevel dimensions, which lag behind until the geometry manager
    # has completed at least one layout pass after _sync fires.

    def _get_wh():
        """Return (W, H) using app dims - the overlay always matches the app."""
        W = app.winfo_width()
        H = app.winfo_height()
        if W < 100: W = 1440
        if H < 100: H = 900
        return W, H

    def _tick():
        global _star_after_id
        if _star_canvas is None or not _star_canvas.winfo_exists():
            return

        W, H = _get_wh()

        # Lazy init - runs once, using reliable app dimensions.
        if not _star_data:
            n = _star_count
            slot_w = W / n
            for i in range(n):
                _star_data.append({
                    "x":     slot_w * i + random.uniform(0, slot_w),
                    "y":     random.uniform(-120, H + 200),
                    "speed": random.uniform(0.5, 1.8),
                    "char":  random.choice(CHARS),
                    "col":   random.choice(COLOURS),
                    "size":  random.randint(8, 16),
                    "drift": random.uniform(-0.2, 0.2),
                    "id":    None,
                })

        for s in _star_data:
            if s["id"] is not None:
                try:
                    _star_canvas.delete(s["id"])
                except Exception:
                    pass
                s["id"] = None

            s["y"] += s["speed"] * _star_speed_mult
            s["x"] += s["drift"] * _star_speed_mult

            if s["y"] > H + 20:
                # Re-enter from a random x across the full width
                s["y"] = random.uniform(-30, -5)
                s["x"] = random.uniform(0, W)
                s["speed"] = random.uniform(0.5, 1.8)
                s["char"]  = random.choice(CHARS)
                s["col"]   = random.choice(COLOURS)
                s["size"]  = random.randint(8, 16)
                s["drift"] = random.uniform(-0.2, 0.2)
            if s["x"] < 0: s["x"] = W
            if s["x"] > W: s["x"] = 0

            s["id"] = _star_canvas.create_text(
                int(s["x"]), int(s["y"]),
                text=s["char"],
                fill=s["col"],
                font=(UI_FONT, s["size"]))

        _star_after_id = _star_canvas.after(50, _tick)

    _star_canvas.after(50, _tick)


# ── Global tk option cascading ────────────────────────────────────────────────

def apply_default_options(app: tk.Tk, skin: dict):
    """
    Set tk option_add defaults so EVERY tk widget (in all 67 tabs) inherits
    dark-theme colors without touching individual tab files.
    Called at startup BEFORE tabs are created, and again on skin switch.
    """
    try:
        app.option_clear()
        P = "widgetDefault"  # lowest priority - explicit widget settings override
        c = skin["content"]
        fg = skin["fg"]
        i_bg = skin.get("input_bg", "#222222")
        i_fg = skin.get("input_fg", "#E2E2E2")
        bdr  = skin.get("border",   "#2C2C2C")
        pnl  = skin["panel"]
        acc  = skin["accent"]

        # Frame / generic background
        app.option_add("*Background",                  c,     P)
        app.option_add("*Foreground",                  fg,    P)
        app.option_add("*Font",                        f"{{{UI_FONT}}} 10", P)
        app.option_add("*activeBackground",            pnl,   P)
        app.option_add("*activeForeground",            fg,    P)
        app.option_add("*disabledForeground",          bdr,   P)

        # Label
        app.option_add("*Label.Background",            c,     P)
        app.option_add("*Label.Foreground",            fg,    P)
        app.option_add("*Label.BorderWidth",           "0",   P)

        # LabelFrame
        app.option_add("*LabelFrame.Background",       c,     P)
        app.option_add("*LabelFrame.Foreground",       skin["fgdim"], P)
        app.option_add("*LabelFrame.Relief",           "solid", P)
        app.option_add("*LabelFrame.BorderWidth",      "1",   P)
        app.option_add("*LabelFrame.Bd",               "1",   P)
        app.option_add("*LabelFrame.Font",
                       f"{{{UI_FONT}}} 9 bold", P)

        # Entry
        app.option_add("*Entry.Background",            i_bg,  P)
        app.option_add("*Entry.Foreground",            i_fg,  P)
        app.option_add("*Entry.InsertBackground",      i_fg,  P)
        app.option_add("*Entry.SelectBackground",      acc,   P)
        app.option_add("*Entry.SelectForeground",      "#FFFFFF", P)
        app.option_add("*Entry.Relief",                "flat", P)
        app.option_add("*Entry.BorderWidth",           "1",   P)
        app.option_add("*Entry.HighlightThickness",    "0",   P)

        # Spinbox
        app.option_add("*Spinbox.Background",          i_bg,  P)
        app.option_add("*Spinbox.Foreground",          i_fg,  P)
        app.option_add("*Spinbox.InsertBackground",    i_fg,  P)
        app.option_add("*Spinbox.SelectBackground",    acc,   P)
        app.option_add("*Spinbox.Relief",              "flat", P)
        app.option_add("*Spinbox.ButtonBackground",    pnl,   P)
        app.option_add("*Spinbox.HighlightThickness",  "0",   P)

        # Button
        app.option_add("*Button.Background",           pnl,   P)
        app.option_add("*Button.Foreground",           fg,    P)
        app.option_add("*Button.ActiveBackground",     skin["sb_hover"], P)
        app.option_add("*Button.ActiveForeground",     "#FFFFFF", P)
        app.option_add("*Button.Relief",               "flat", P)
        app.option_add("*Button.BorderWidth",          "0",   P)
        app.option_add("*Button.Cursor",               "hand2", P)
        app.option_add("*Button.HighlightThickness",   "0",   P)
        app.option_add("*Button.PadX",                 "10",  P)
        app.option_add("*Button.PadY",                 "5",   P)

        # Checkbutton
        app.option_add("*Checkbutton.Background",      c,     P)
        app.option_add("*Checkbutton.Foreground",      fg,    P)
        app.option_add("*Checkbutton.SelectColor",     pnl,   P)
        app.option_add("*Checkbutton.ActiveBackground",c,     P)
        app.option_add("*Checkbutton.ActiveForeground",acc,   P)
        app.option_add("*Checkbutton.HighlightThickness","0", P)

        # Radiobutton
        app.option_add("*Radiobutton.Background",      c,     P)
        app.option_add("*Radiobutton.Foreground",      fg,    P)
        app.option_add("*Radiobutton.SelectColor",     acc,   P)
        app.option_add("*Radiobutton.ActiveBackground",c,     P)
        app.option_add("*Radiobutton.ActiveForeground",acc,   P)
        app.option_add("*Radiobutton.HighlightThickness","0", P)

        # Scale (slider)
        app.option_add("*Scale.Background",            c,     P)
        app.option_add("*Scale.Foreground",            fg,    P)
        app.option_add("*Scale.TroughColor",           bdr,   P)
        app.option_add("*Scale.ActiveBackground",      acc,   P)
        app.option_add("*Scale.SliderRelief",          "flat", P)
        app.option_add("*Scale.HighlightThickness",    "0",   P)
        app.option_add("*Scale.BorderWidth",           "0",   P)

        # Listbox
        app.option_add("*Listbox.Background",          i_bg,  P)
        app.option_add("*Listbox.Foreground",          i_fg,  P)
        app.option_add("*Listbox.SelectBackground",    acc,   P)
        app.option_add("*Listbox.SelectForeground",    "#FFFFFF", P)
        app.option_add("*Listbox.Relief",              "flat", P)
        app.option_add("*Listbox.BorderWidth",         "0",   P)
        app.option_add("*Listbox.HighlightThickness",  "0",   P)

        # Text (used for console log areas)
        app.option_add("*Text.Background",             skin["console_bg"], P)
        app.option_add("*Text.Foreground",             skin["console_fg"], P)
        app.option_add("*Text.InsertBackground",       skin["console_fg"], P)
        app.option_add("*Text.SelectBackground",       acc,   P)
        app.option_add("*Text.Relief",                 "flat", P)
        app.option_add("*Text.BorderWidth",            "0",   P)
        app.option_add("*Text.HighlightThickness",     "0",   P)

        # Canvas
        app.option_add("*Canvas.Background",           c,     P)
        app.option_add("*Canvas.HighlightThickness",   "0",   P)

        # Menu
        app.option_add("*Menu.Background",             pnl,   P)
        app.option_add("*Menu.Foreground",             fg,    P)
        app.option_add("*Menu.ActiveBackground",       acc,   P)
        app.option_add("*Menu.ActiveForeground",       "#FFFFFF", P)
        app.option_add("*Menu.Relief",                 "flat", P)
        app.option_add("*Menu.BorderWidth",            "1",   P)
        app.option_add("*Menu.TearOff",                "0",   P)

    except Exception:
        pass


# ── Main entry point ─────────────────────────────────────────────────────────

def apply_skin(app: tk.Tk, sidebar_container: tk.Frame,
               content_container: tk.Frame,
               btn_refs: dict,
               inner_frame=None,
               indicator_refs: dict = None,
               *_ignored):
    """
    Apply the currently saved skin to the live app.
    Safe to call multiple times (live switching).
    """
    name = load_skin_name()
    skin = get_skin(name)

    # ── 0. Cascade option_add to ALL tk widgets (new creations + live switch) ─
    apply_default_options(app, skin)

    # ── 1. Update CLR in base_tab so new tab instances use new colours ────
    try:
        import tabs.base_tab as bt
        bt.CLR.update({
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
        })
    except Exception:
        pass

    # ── 2. Sidebar background ─────────────────────────────────────────────
    _recolour_frame(sidebar_container, skin["sb_bg"])

    # ── 3. Sidebar buttons ────────────────────────────────────────────────
    for btn_name, btn in btn_refs.items():
        try:
            btn.config(
                bg=skin["sb_bg"],
                fg=skin["sb_btn"],
                activebackground=skin["sb_hover"],
                activeforeground="#FFFFFF",
            )
        except Exception:
            pass

    # Re-highlight active button
    try:
        current = getattr(app, "current_page", None)
        if current and current in btn_refs:
            btn_refs[current].config(
                bg=skin["sb_active"], fg=skin["accent"],
                font=(UI_FONT, 10, "bold"))
    except Exception:
        pass

    # ── 4. Sidebar indicator bars ─────────────────────────────────────────
    if indicator_refs:
        try:
            current = getattr(app, "current_page", None)
            for page_name, indicator in indicator_refs.items():
                if indicator.winfo_exists():
                    if page_name == current:
                        indicator.config(bg=skin["accent"])
                    else:
                        indicator.config(bg=skin["sb_bg"])
        except Exception:
            pass

    # ── 5. Content area + all child backgrounds ───────────────────────────
    try:
        content_container.config(bg=skin["content"])
        _recolour_widget_tree(content_container, skin)
    except Exception:
        pass

    # ── 6. ttk styles ─────────────────────────────────────────────────────
    _apply_ttk_styles(skin)

    # ── 7. Stars ──────────────────────────────────────────────────────────
    if skin.get("stars"):
        _start_stars(app, skin, inner_frame)
    else:
        _stop_stars()


def _apply_ttk_styles(skin: dict):
    """Apply comprehensive ttk styling."""
    try:
        style = ttk.Style()
        c   = skin["content"]
        pnl = skin["panel"]
        acc = skin["accent"]
        fg  = skin["fg"]
        fdm = skin["fgdim"]
        bdr = skin.get("border", "#2C2C2C")
        i_bg = skin.get("input_bg", "#1E1E1E")
        i_fg = skin.get("input_fg", "#E2E2E2")

        style.configure("TFrame",        background=c)
        style.configure("TLabel",        background=c, foreground=fg,
                        font=(UI_FONT, 10))
        style.configure("TCheckbutton",  background=c, foreground=fg,
                        font=(UI_FONT, 10))
        style.configure("TRadiobutton",  background=c, foreground=fg,
                        font=(UI_FONT, 10))

        # LabelFrame - clear bordered panel
        style.configure("TLabelframe",   background=c,
                        bordercolor=bdr, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label",
                        background=c, foreground=fdm,
                        font=(UI_FONT, 9, "bold"))

        # Scrollbar
        style.configure("TScrollbar",
                        background=pnl, troughcolor=skin["sb_bg"],
                        arrowcolor=fdm, borderwidth=0, relief="flat",
                        gripcount=0)
        style.map("TScrollbar",
                  background=[("active", bdr), ("!active", pnl)])

        # Notebook
        style.configure("TNotebook",     background=pnl, tabmargins=[0, 2, 0, 0])
        style.configure("TNotebook.Tab", padding=[14, 8], font=(UI_FONT, 9))
        style.map("TNotebook.Tab",
                  background=[("selected",  skin["sb_active"]),
                               ("!selected", skin["sb_bg"])],
                  foreground=[("selected",  acc),
                               ("!selected", skin["sb_btn"])])

        # Entry
        style.configure("TEntry",
                        fieldbackground=i_bg, foreground=i_fg,
                        insertcolor=i_fg, borderwidth=1, relief="flat",
                        font=(UI_FONT, 10), padding=4)

        # Combobox
        style.configure("TCombobox",
                        fieldbackground=i_bg, foreground=i_fg,
                        selectbackground=acc, selectforeground="#FFFFFF",
                        arrowcolor=fdm, borderwidth=1, relief="flat",
                        font=(UI_FONT, 10))
        style.map("TCombobox",
                  fieldbackground=[("readonly", i_bg)],
                  foreground=[("readonly", i_fg)],
                  selectbackground=[("readonly", acc)])

        # Progressbar
        style.configure("TProgressbar",
                        background=acc, troughcolor=bdr,
                        borderwidth=0, thickness=4)

        # Checkbutton + Radiobutton maps
        style.map("TCheckbutton",
                  background=[("active", c)],
                  foreground=[("active", acc)])
        style.map("TRadiobutton",
                  background=[("active", c)],
                  foreground=[("active", acc)])

    except Exception:
        pass


def _recolour_frame(widget, bg_col: str):
    """Recursively set bg on Frame/Label/Checkbutton sidebar children."""
    try:
        cls = widget.winfo_class()
        if cls in ("Frame", "Label", "Checkbutton"):
            widget.config(bg=bg_col)
    except Exception:
        pass
    try:
        for child in widget.winfo_children():
            _recolour_frame(child, bg_col)
    except Exception:
        pass


def _recolour_widget_tree(widget, skin: dict):
    """
    Recursively update background colors in the content area for live skin switch.
    Only updates widgets that don't have explicit color overrides (checks for
    common surface color patterns to avoid incorrectly recoloring accent buttons).
    """
    try:
        cls = widget.winfo_class()
        c   = skin["content"]
        pnl = skin["panel"]
        i_bg = skin.get("input_bg", "#1E1E1E")

        if cls == "Frame":
            try: widget.config(bg=c)
            except Exception: pass
        elif cls == "Label":
            try: widget.config(bg=c, fg=skin["fg"])
            except Exception: pass
        elif cls == "LabelFrame":
            try: widget.config(bg=c, fg=skin["fgdim"])
            except Exception: pass

        for child in widget.winfo_children():
            _recolour_widget_tree(child, skin)
    except Exception:
        pass
