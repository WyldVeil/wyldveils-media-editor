"""
tabs/system/home.py  ─  Home / launch screen

A landing page that shows every tab as a clickable card, organised by the
same category structure used in the sidebar, plus a Favourites section
populated from the user's saved favourites in settings.json.

Each card has:
  • a clickable body that navigates to that tab
  • a star toggle (☆ / ★) on the right that adds/removes the tab from
    the user's Favourites list (persisted to settings.json under
    "favourite_tabs")

The tab itself is registered in HIDDEN so it never appears in the
sidebar - it's reachable as the launch page and via the persistent
"🏠 Home" button on the content header bar (see main.py).
"""

import tkinter as tk

from tabs.base_tab import BaseTab, CLR, UI_FONT
from core import settings as _settings


# Categories that are valid favourite/jump targets. We re-import lazily
# inside _build_ui to avoid circular imports - registry.py imports nearly
# every tab class, and tabs.system imports from this file.
def _registry():
    from tabs.registry import TOOLS, PINNED
    return TOOLS, PINNED


_FAV_KEY = "favourite_tabs"


class HomeTab(BaseTab):
    """Launch / overview screen with category grids and favourites."""

    # Card layout constants
    _CARD_WIDTH    = 200
    _CARD_HEIGHT   = 56
    _GRID_PAD_X    = 8
    _GRID_PAD_Y    = 8
    _MIN_COLS      = 2
    _MAX_COLS      = 6

    def __init__(self, parent):
        super().__init__(parent)
        self._navigate = None  # set by main.py after construction
        self._sections_frame = None
        self._fav_section_frame = None
        self._build_ui()
        # Re-render when window is resized so the grid reflows.
        self.bind("<Configure>", self._on_resize, add=True)

    # ── Public hook used by main.py ──────────────────────────────────────────
    def set_navigator(self, fn):
        """fn(name: str) -> None  - called when a card is clicked."""
        self._navigate = fn

    # ── Favourites helpers ───────────────────────────────────────────────────
    def _favourites(self):
        favs = _settings.get(_FAV_KEY, []) or []
        return [f for f in favs if isinstance(f, str)]

    def _save_favourites(self, favs):
        # Dedup while preserving order.
        seen = set()
        clean = []
        for f in favs:
            if f and f not in seen:
                seen.add(f)
                clean.append(f)
        _settings.set(_FAV_KEY, clean)

    def _is_fav(self, name):
        return name in self._favourites()

    def _toggle_fav(self, name):
        favs = self._favourites()
        if name in favs:
            favs = [f for f in favs if f != name]
        else:
            favs.append(name)
        self._save_favourites(favs)
        self._refresh()

    # ── UI build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        inner = tk.Frame(hdr, bg=CLR["panel"])
        inner.pack(fill="x", padx=22, pady=(16, 14))
        tk.Label(
            inner, text="🏠  Home",
            font=(UI_FONT, 16, "bold"),
            bg=CLR["panel"], fg=CLR["accent"], anchor="w",
        ).pack(side="top", anchor="w")
        tk.Label(
            inner, text="Pick a tool to get started. Star the ones you "
                       "use most to pin them to your Favourites.",
            font=(UI_FONT, 9),
            bg=CLR["panel"], fg=CLR["fgdim"], anchor="w",
        ).pack(side="top", anchor="w", pady=(2, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Scrollable content
        outer = tk.Frame(self, bg=CLR["bg"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=CLR["bg"], highlightthickness=0)
        from tkinter import ttk
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=CLR["bg"])
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        self._scroll_canvas = canvas
        self._scroll_body = body

        def _on_body_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(body_win, width=e.width)
            self._render_sections()
        canvas.bind("<Configure>", _on_canvas_configure)

        self._sections_frame = body
        self._render_sections()

    # ── Render / refresh ─────────────────────────────────────────────────────
    def _refresh(self):
        self._render_sections()

    def _on_resize(self, _e):
        # Debounce-ish: re-render on configure events. Cheap to redraw.
        self._render_sections()

    def _render_sections(self):
        body = self._sections_frame
        if body is None or not body.winfo_exists():
            return
        # Clear existing children
        for w in body.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        TOOLS, PINNED = _registry()

        # Build a name → class lookup so favourites can resolve to a target.
        all_tabs = []
        for items in TOOLS.values():
            for name, cls in items:
                all_tabs.append((name, cls))
        # All-in-One pinned tab: the actual sidebar key includes a "⚡ "
        # prefix, but from the user's perspective it's just the tab name.
        # We use the same display name here so favourites match what they
        # see in the sidebar.
        if PINNED:
            aio_name, aio_cls = PINNED
            sidebar_key = "⚡ " + aio_name
            all_tabs.append((sidebar_key, aio_cls))

        valid_names = {n for n, _ in all_tabs}

        # 1. Favourites section
        favs = [f for f in self._favourites() if f in valid_names]
        if favs:
            self._render_section_header(body, "⭐  Favourites",
                                        accent=CLR["orange"])
            self._render_grid(body, favs)
            tk.Frame(body, bg=CLR["bg"], height=10).pack(fill="x")

        # 2. Each TOOLS category
        # The pinned All-in-One gets its own "Quick Tools" section first if
        # it isn't already favourited.
        if PINNED:
            aio_sidebar_key = "⚡ " + PINNED[0]
            self._render_section_header(body, "⚡  Quick Tools",
                                        accent=CLR["accent"])
            self._render_grid(body, [aio_sidebar_key])
            tk.Frame(body, bg=CLR["bg"], height=10).pack(fill="x")

        for category, items in TOOLS.items():
            self._render_section_header(body, category)
            self._render_grid(body, [n for n, _ in items])
            tk.Frame(body, bg=CLR["bg"], height=10).pack(fill="x")

    def _render_section_header(self, parent, label, accent=None):
        if accent is None:
            accent = CLR["accent"]
        row = tk.Frame(parent, bg=CLR["bg"])
        row.pack(fill="x", padx=20, pady=(14, 6))
        tk.Label(
            row, text=label,
            font=(UI_FONT, 11, "bold"),
            bg=CLR["bg"], fg=accent, anchor="w",
        ).pack(side="left", anchor="w")
        # Thin horizontal rule under header
        rule = tk.Frame(parent, bg=CLR["border"], height=1)
        rule.pack(fill="x", padx=20)

    def _render_grid(self, parent, names):
        if not names:
            return
        grid = tk.Frame(parent, bg=CLR["bg"])
        grid.pack(fill="x", padx=20, pady=(8, 0))

        # Column count based on parent width.
        try:
            avail = self._scroll_body.winfo_width() or self.winfo_width() or 1000
        except Exception:
            avail = 1000
        col_w = self._CARD_WIDTH + 2 * self._GRID_PAD_X
        cols = max(self._MIN_COLS, min(self._MAX_COLS, max(1, avail // col_w)))

        for i, name in enumerate(names):
            r, c = divmod(i, cols)
            self._build_card(grid, name).grid(
                row=r, column=c,
                padx=self._GRID_PAD_X, pady=self._GRID_PAD_Y,
                sticky="nsew",
            )
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="cards")

    def _build_card(self, parent, name):
        """A single tab card: clickable body + star toggle on the right."""
        is_fav = self._is_fav(name)
        card = tk.Frame(
            parent, bg=CLR["panel"],
            highlightthickness=1,
            highlightbackground=CLR["border"],
            cursor="hand2",
        )
        card.config(width=self._CARD_WIDTH, height=self._CARD_HEIGHT)
        card.pack_propagate(False)

        # Tab name (left, fills space)
        name_lbl = tk.Label(
            card, text=name,
            font=(UI_FONT, 10, "bold"),
            bg=CLR["panel"], fg=CLR["fg"],
            anchor="w", padx=12,
            cursor="hand2",
        )
        name_lbl.pack(side="left", fill="both", expand=True)

        # Star toggle (right)
        star_text = "★" if is_fav else "☆"
        star_color = CLR["orange"] if is_fav else CLR["fgdim"]
        star_lbl = tk.Label(
            card, text=star_text,
            font=(UI_FONT, 14),
            bg=CLR["panel"], fg=star_color,
            padx=12, cursor="hand2",
        )
        star_lbl.pack(side="right", fill="y")

        # Click handlers - star toggles favourite (no navigation), the rest
        # of the card body navigates.
        def on_navigate(_e=None, n=name):
            if self._navigate:
                self._navigate(n)

        def on_toggle(_e=None, n=name):
            self._toggle_fav(n)
            return "break"  # prevent the click from also bubbling to body

        for w in (card, name_lbl):
            w.bind("<Button-1>", on_navigate)
        star_lbl.bind("<Button-1>", on_toggle)

        # Hover effect
        hover_bg = CLR.get("sb_hover") or "#2A2A2A"
        normal_bg = CLR["panel"]

        def on_enter(_e):
            try:
                card.config(bg=hover_bg, highlightbackground=CLR["accent"])
                name_lbl.config(bg=hover_bg)
                star_lbl.config(bg=hover_bg)
            except Exception:
                pass

        def on_leave(_e):
            try:
                card.config(bg=normal_bg, highlightbackground=CLR["border"])
                name_lbl.config(bg=normal_bg)
                star_lbl.config(bg=normal_bg)
            except Exception:
                pass

        for w in (card, name_lbl, star_lbl):
            w.bind("<Enter>", on_enter, add=True)
            w.bind("<Leave>", on_leave, add=True)

        return card
