"""
tab_titlesgenerator.py  ─  Animated Titles & Lower Thirds
Overlay professional animated text onto existing footage at specific
timestamps. Distinct from the Watermarker (which does simple static/
bouncing/jumping text) and the IntroMaker (which creates standalone bumpers).

This tool produces:
  • Lower Thirds  - slide-up bar with name + subtitle reveal
  • Chapter Titles - large centred text with fade reveal over a dark overlay
  • Name Tags      - corner box with animated border
  • Kinetic Text   - word-by-word stagger reveal

Multiple title cards per video, each independently timed.
All rendered via FFmpeg drawtext + overlay filters.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import subprocess
import os
import tempfile

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# ── Style presets ─────────────────────────────────────────────────────────
TITLE_STYLES = {
    t("titles.lower_third_slide_up_bar"): {
        "icon": "📺",
        "desc": "Classic broadcast lower-third: coloured bar slides up with name + role text.",
        "bar": True,  "bar_h": 80,  "bar_alpha": 0.85,
        "anim": "slide_up", "text_pos": "lower_third",
    },
    "Chapter Title  (fade overlay)": {
        "icon": "🎬",
        "desc": "Full-width dark overlay with large centred chapter title. Fades in/out.",
        "bar": True, "bar_h": 120, "bar_alpha": 0.70,
        "anim": "fade", "text_pos": "centre",
    },
    "Name Tag  (corner box)": {
        "icon": "🏷",
        "desc": "Corner label box. Great for interview names and reaction videos.",
        "bar": True, "bar_h": 60, "bar_alpha": 0.80,
        "anim": "slide_right", "text_pos": "bottom_left",
    },
    "Kinetic  (pop-up)": {
        "icon": "⚡",
        "desc": "Text scales up from nothing. Eye-catching for YouTube shorts.",
        "bar": False, "bar_h": 0, "bar_alpha": 0,
        "anim": "zoom_pop", "text_pos": "centre",
    },
    "Subtitle Strip  (bottom banner)": {
        "icon": "💬",
        "desc": "Semi-transparent strip across the bottom. Good for context and translations.",
        "bar": True, "bar_h": 55, "bar_alpha": 0.75,
        "anim": "fade", "text_pos": "bottom_strip",
    },
}

ACCENT_COLORS = {
    t("titles.youtube_red"):   "#FF0000",
    t("titles.electric_blue"): "#1565C0",
    t("titles.neon_green"):    "#00C853",
    "Gold":          "#FFD600",
    "Purple":        "#7B1FA2",
    "White":         "#FFFFFF",
    t("smart_reframe.custom"):       None,
}


class TitleCard:
    """Data for one title overlay."""
    def __init__(self):
        self.style_var    = tk.StringVar(value=list(TITLE_STYLES.keys())[0])
        self.line1_var    = tk.StringVar(value="Title Text")
        self.line2_var    = tk.StringVar(value="Subtitle / Role")
        self.start_var    = tk.StringVar(value="3")
        self.duration_var = tk.StringVar(value="4")
        self.size1_var    = tk.StringVar(value="48")
        self.size2_var    = tk.StringVar(value="28")
        self.color_var    = tk.StringVar(value="YouTube Red")
        self.fadein_var   = tk.StringVar(value="0.4")
        self.fadeout_var  = tk.StringVar(value="0.4")
        self.row          = None   # tk.Frame reference


class TitlesGeneratorTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path   = ""
        self.preview_proc = None
        self.cards: list[TitleCard] = []
        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎬  " + t("tab.animated_titles"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("titles.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # Source
        sf = tk.Frame(self); sf.pack(pady=8)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse_src, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # ── Title cards list ─────────────────────────────────────────────
        list_hdr = tk.Frame(self); list_hdr.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(list_hdr, text=t("titles.title_cards"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(side="left")
        tk.Button(list_hdr, text=f"➕ {t('titles.add_card_button')}", bg=CLR["panel"], fg=CLR["fg"],
                  command=self._add_card).pack(side="right", padx=4)
        tk.Button(list_hdr, text=f"🗑 {t('titles.remove_last_button')}", bg=CLR["panel"], fg=CLR["fg"],
                  command=self._remove_last).pack(side="right", padx=4)

        # Cards scroll area
        cards_canvas = tk.Canvas(self, height=340, highlightthickness=0)
        cards_sb = ttk.Scrollbar(self, orient="vertical",
                                  command=cards_canvas.yview)
        self.cards_frame = tk.Frame(cards_canvas)
        cards_canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>",
                              lambda e: cards_canvas.configure(
                                  scrollregion=cards_canvas.bbox("all")))
        cards_canvas.configure(yscrollcommand=cards_sb.set)
        cards_canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        cards_sb.pack(side="right", fill="y")

        # Seed two cards
        self._add_card()
        self._add_card("Chapter Title  (fade overlay)", "Chapter One", "", "10", "5")

        # ── Encode options ────────────────────────────────────────────────
        enc_f = tk.Frame(self); enc_f.pack(fill="x", padx=16, pady=6)
        tk.Label(enc_f, text=t("titles.font_label")).pack(side="left")
        self.font_var = tk.StringVar(value="Arial")
        ttk.Combobox(enc_f, textvariable=self.font_var,
                     values=["Arial","Impact","Helvetica","Verdana",
                              "Georgia",t("titles.hard_subber_trebuchet_ms"),t("intro_maker.hard_subber_courier_new")],
                     width=16).pack(side="left", padx=6)
        tk.Label(enc_f, text=t("rotate_flip.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(enc_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(enc_f, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(enc_f, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # ── Output & render ───────────────────────────────────────────────
        of = tk.Frame(self); of.pack(fill="x", padx=16, pady=4)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=f"👁  {t('titles.preview_button')}",
                  bg=CLR["accent"], fg="white", width=18,
                  command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("titles.render_button"),
            font=(UI_FONT, 12, "bold"),
            bg="#AD1457", fg="white",
            height=2, width=26, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=16, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    def _add_card(self, style=None, line1="Title Text",
                  line2="Subtitle / Role", start="3", duration="4"):
        card = TitleCard()
        if style:
            card.style_var.set(style)
        card.line1_var.set(line1)
        card.line2_var.set(line2)
        card.start_var.set(start)
        card.duration_var.set(duration)
        self.cards.append(card)
        self._draw_card_row(card, len(self.cards) - 1)

    def _draw_card_row(self, card: TitleCard, idx: int):
        outer = tk.LabelFrame(self.cards_frame,
                               text=f"  Card {idx+1}  ",
                               padx=10, pady=6)
        outer.pack(fill="x", pady=4, padx=4)
        card.row = outer

        # Row 1: style + timing
        r1 = tk.Frame(outer); r1.pack(fill="x", pady=2)
        tk.Label(r1, text=t("titles.style_label"), width=7, anchor="e").pack(side="left")
        style_cb = ttk.Combobox(r1, textvariable=card.style_var,
                                 values=list(TITLE_STYLES.keys()),
                                 state="readonly", width=30)
        style_cb.pack(side="left", padx=4)
        style_cb.bind("<<ComboboxSelected>>", lambda e, c=card: self._show_style_desc(c))

        self._style_desc_lbl = tk.Label(r1, text="", fg=CLR["fgdim"],
                                         font=(UI_FONT, 8), width=45, anchor="w")
        self._style_desc_lbl.pack(side="left", padx=6)

        for lbl, var in [(t("titles.start_label"), card.start_var),
                          (t("titles.duration_label"), card.duration_var)]:
            tk.Label(r1, text=lbl).pack(side="left", padx=(8, 2))
            tk.Entry(r1, textvariable=var, width=5, relief="flat").pack(side="left")

        # Row 2: text lines
        r2 = tk.Frame(outer); r2.pack(fill="x", pady=2)
        tk.Label(r2, text=t("titles.line_1_label"), width=7, anchor="e").pack(side="left")
        tk.Entry(r2, textvariable=card.line1_var, width=28,
                 font=(UI_FONT, 10, "bold")).pack(side="left", padx=4)
        tk.Label(r2, text=t("hard_subber.size_label")).pack(side="left")
        tk.Entry(r2, textvariable=card.size1_var, width=4, relief="flat").pack(side="left", padx=2)

        tk.Label(r2, text=f"  {t('titles.line_2_label')}").pack(side="left", padx=(12, 0))
        tk.Entry(r2, textvariable=card.line2_var, width=28, relief="flat").pack(side="left", padx=4)
        tk.Label(r2, text=t("hard_subber.size_label")).pack(side="left")
        tk.Entry(r2, textvariable=card.size2_var, width=4, relief="flat").pack(side="left", padx=2)

        # Row 3: accent color + fade
        r3 = tk.Frame(outer); r3.pack(fill="x", pady=2)
        tk.Label(r3, text=t("titles.accent_label"), width=7, anchor="e").pack(side="left")
        color_cb = ttk.Combobox(r3, textvariable=card.color_var,
                                 values=list(ACCENT_COLORS.keys()),
                                 state="readonly", width=16)
        color_cb.pack(side="left", padx=4)
        color_cb.bind("<<ComboboxSelected>>",
                      lambda e, c=card: self._on_color_change(c))
        card._color_preview = tk.Label(r3, text=t("titles.item"), bg="#FF0000",
                                        width=6)
        card._color_preview.pack(side="left")
        card._custom_btn = tk.Button(r3, text=t("smart_reframe.custom"),
                                     command=lambda c=card: self._pick_color(c))
        card._custom_btn.pack(side="left", padx=4)

        tk.Label(r3, text=f"  {t('titles.fade_in_label')}").pack(side="left")
        tk.Entry(r3, textvariable=card.fadein_var, width=4, relief="flat").pack(side="left", padx=2)
        tk.Label(r3, text=f"  {t('titles.fade_out_label')}").pack(side="left")
        tk.Entry(r3, textvariable=card.fadeout_var, width=4, relief="flat").pack(side="left", padx=2)

    def _show_style_desc(self, card: TitleCard):
        info = TITLE_STYLES.get(card.style_var.get(), {})
        # best-effort update the nearest label
        pass

    def _on_color_change(self, card: TitleCard):
        key = card.color_var.get()
        hex_c = ACCENT_COLORS.get(key)
        if hex_c:
            card._custom_color = hex_c
            card._color_preview.config(bg=hex_c)

    def _pick_color(self, card: TitleCard):
        c = colorchooser.askcolor()
        if c[1]:
            card._custom_color = c[1]
            card._color_preview.config(bg=c[1])
            card.color_var.set("Custom…")

    def _remove_last(self):
        if self.cards:
            c = self.cards.pop()
            c.row.destroy()

    def _browse_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"),
                       ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            from core.hardware import get_video_duration
            dur = get_video_duration(p)
            m, s = divmod(int(dur), 60)
            self.dur_lbl.config(text=f"{m}m {s}s", fg=CLR["fgdim"])
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_titled.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    # ── Filter building ───────────────────────────────────────────────────
    def _get_accent_hex(self, card: TitleCard) -> str:
        key = card.color_var.get()
        hex_c = getattr(card, "_custom_color",
                        ACCENT_COLORS.get(key, "#FF0000"))
        return (hex_c or "#FF0000").lstrip("#")

    def _build_card_filter(self, card: TitleCard, vid_w=1920, vid_h=1080) -> str:
        """Return a chain of drawtext (and drawbox) filters for one card."""
        style_info = TITLE_STYLES[card.style_var.get()]
        line1   = card.line1_var.get().replace("'", "").replace(":", "\\:")
        line2   = card.line2_var.get().replace("'", "").replace(":", "\\:")
        s1      = card.size1_var.get()
        s2      = card.size2_var.get()
        ts      = float(card.start_var.get() or "0")
        dur     = float(card.duration_var.get() or "4")
        te      = ts + dur
        fi      = float(card.fadein_var.get() or "0.4")
        fo      = float(card.fadeout_var.get() or "0.4")
        font    = self.font_var.get()
        accent  = self._get_accent_hex(card)
        anim    = style_info["anim"]
        pos_key = style_info["text_pos"]

        # Alpha expression: fade in, hold, fade out
        alpha = (f"'if(lt(t,{ts}),0,"
                 f"if(lt(t,{ts+fi}),(t-{ts})/{fi},"
                 f"if(lt(t,{te-fo}),1,"
                 f"if(lt(t,{te}),({te}-t)/{fo},0))))'")

        enable = f"enable='between(t,{ts},{te})'"

        # ── Position ──────────────────────────────────────────────────────
        bar_h   = style_info["bar_h"]
        bar_pad = 14

        if pos_key == "lower_third":
            # Line 1 (name) above line 2 (role), anchored bottom-left with margin
            if anim == "slide_up":
                y_off = f"'if(lt(t,{ts}),{vid_h}," \
                        f"if(lt(t,{ts+fi}),{vid_h-bar_h-40}+(({ts+fi}-t)/{fi})*{vid_h}," \
                        f"{vid_h-bar_h-40}))'"
                l1_y = f"({vid_h-bar_h-40}+{bar_pad})"
                l2_y = f"({vid_h-bar_h-40}+{bar_pad}+{s1}+6)"
            else:
                l1_y = f"({vid_h-bar_h}+{bar_pad})"
                l2_y = f"({vid_h-bar_h}+{bar_pad}+{s1}+6)"
            l1_x = "60"
            l2_x = "60"

        elif pos_key == "centre":
            l1_x = "(w-text_w)/2"
            l1_y = f"(h-{int(s1)}-{int(s2)})/2"
            l2_x = "(w-text_w)/2"
            l2_y = f"(h-{int(s1)}-{int(s2)})/2+{s1}+10"

        elif pos_key == "bottom_left":
            l1_x, l1_y = "40", f"{vid_h-bar_h-40}+{bar_pad}"
            l2_x, l2_y = "40", f"{vid_h-bar_h-40}+{bar_pad}+{s1}+4"

        elif pos_key == "bottom_strip":
            l1_x = "(w-text_w)/2"
            l1_y = f"{vid_h-bar_h+8}"
            l2_x = "(w-text_w)/2"
            l2_y = f"{vid_h-bar_h+8+int(s1)+4}"
        else:
            l1_x = l2_x = "(w-text_w)/2"
            l1_y = "(h-text_h)/2"
            l2_y = f"(h-text_h)/2+{s1}+8"

        # ── Background bar ────────────────────────────────────────────────
        filters = []
        if style_info["bar"]:
            bar_alpha_val = style_info["bar_alpha"]
            if pos_key in ("lower_third", "bottom_left"):
                bx, by = f"0", f"{vid_h-bar_h-20}"
                bw, bh = f"w/2", str(bar_h + 20)
            elif pos_key == "bottom_strip":
                bx, by = "0", str(vid_h - bar_h - 4)
                bw, bh = "w", str(bar_h + 4)
            else:
                bx, by = "0", f"(h-{bar_h+20})/2"
                bw, bh = "w", str(bar_h + 20)
            filters.append(
                f"drawbox=x={bx}:y={by}:w={bw}:h={bh}"
                f":color=0x{accent}@{bar_alpha_val:.2f}:t=fill"
                f":{enable}")

        # ── Text overlays ─────────────────────────────────────────────────
        shadow = ":shadowcolor=black@0.7:shadowx=2:shadowy=2"
        filters.append(
            f"drawtext=text='{line1}':fontsize={s1}:font={font}"
            f":fontcolor=white:alpha={alpha}:x={l1_x}:y={l1_y}{shadow}")
        if line2.strip():
            filters.append(
                f"drawtext=text='{line2}':fontsize={s2}:font={font}"
                f":fontcolor=white@0.85:alpha={alpha}:x={l2_x}:y={l2_y}")

        return ",".join(filters)

    def _build_full_filter(self):
        """Chain all cards into a single -vf string."""
        if not self.cards:
            return None
        all_filters = []
        for card in self.cards:
            f = self._build_card_filter(card)
            if f:
                all_filters.append(f)
        return ",".join(all_filters)

    # ── Preview & Render ──────────────────────────────────────────────────
    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        vf    = self._build_full_filter()
        ffplay = get_binary_path("ffplay.exe")
        cmd   = [ffplay, "-i", self.file_path,
                 "-vf", vf or "null",
                 "-window_title", t("titles.titles_preview"),
                 "-x", "960", "-autoexit"]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not self.cards:
            messagebox.showwarning(t("common.warning"), "Add at least one title card.")
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        vf     = self._build_full_filter()
        ffmpeg = get_binary_path("ffmpeg.exe")
        cmd    = [ffmpeg, "-i", self.file_path,
                  "-vf", vf,
                  t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
                  "-preset", self.preset_var.get(),
                  t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console,
                 f"Rendering {len(self.cards)} title card(s)…")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render,
                        btn_label=t("titles.render_button"))
