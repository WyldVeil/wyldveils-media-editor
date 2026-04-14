"""
tab_chaptermarkers.py  ─  YouTube Chapter Marker Generator
Build a list of chapter timestamps and titles, then export in
YouTube-ready format to paste into your video description.

Features:
  • Load a video and scrub the timeline to find chapter points
  • Click "Mark Here" to stamp the current position
  • Edit chapter names inline
  • Export as:
      - YouTube description text (MM:SS Title)
      - SRT chapter file  (for video players)
      - JSON  (for programmatic use)
      - VTT WebVTT chapters
  • Import from existing SRT or plain-text chapter files
  • Validates YouTube's requirements (≥3 chapters, first at 0:00)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re
import json

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration
from core.i18n import t


def _fmt_yt(secs: float) -> str:
    """Format seconds as M:SS or H:MM:SS for YouTube."""
    secs = int(secs)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_srt_tc(secs: float) -> str:
    """Format seconds as HH:MM:SS,000 for SRT."""
    h = int(secs) // 3600
    m = (int(secs) % 3600) // 60
    s = int(secs) % 60
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class Chapter:
    def __init__(self, time_secs: float, title: str):
        self.time  = time_secs
        self.title = title


class ChapterMarkersTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._duration = 0.0
        self.chapters: list[Chapter] = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="📑  " + t("tab.chapter_markers"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr,
                 text=t("chapter_markers.subtitle"),
                 bg=CLR["panel"], fg=CLR["fgdim"]).pack(side="left")

        # ── Source video ──────────────────────────────────────────────────
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")
        self.dur_lbl = tk.Label(sf, text="", fg=CLR["fgdim"])
        self.dur_lbl.pack(side="left", padx=8)

        # ── Timeline scrubber ─────────────────────────────────────────────
        scrub_lf = tk.LabelFrame(self, text=f"  {t('chapter_markers.timeline_section')}  ", padx=14, pady=10)
        scrub_lf.pack(fill="x", padx=16, pady=6)

        self.timeline = tk.Scale(scrub_lf, from_=0, to=100,
                                  orient="horizontal", length=700,
                                  resolution=0.1,
                                  command=self._on_scrub)
        self.timeline.pack(fill="x")

        ts_row = tk.Frame(scrub_lf); ts_row.pack(fill="x", pady=4)
        tk.Label(ts_row, text=t("chapter_markers.current_position_label")).pack(side="left")
        self.pos_lbl = tk.Label(ts_row, text="0:00", fg=CLR["accent"],
                                 font=(UI_FONT, 14, "bold"), width=10)
        self.pos_lbl.pack(side="left", padx=8)

        tk.Label(ts_row, text=f"  {t('chapter_markers.jump_to_label')}").pack(side="left")
        self.jump_var = tk.StringVar()
        jump_e = tk.Entry(ts_row, textvariable=self.jump_var, width=7, relief="flat")
        jump_e.pack(side="left", padx=4)
        jump_e.bind("<Return>", lambda e: self._jump())
        tk.Button(ts_row, text="Go", command=self._jump, width=4, cursor="hand2", relief="flat").pack(side="left", padx=2)

        # Quick jump %
        for pct in [0, 10, 25, 50, 75, 90, 100]:
            tk.Button(ts_row, text=f"{pct}%", width=4, bg="#333",
                      fg=CLR["fg"], font=(UI_FONT, 8),
                      command=lambda p=pct: self._jump_pct(p)).pack(side="left", padx=1)

        # ── Mark + name ───────────────────────────────────────────────────
        mark_row = tk.Frame(self); mark_row.pack(fill="x", padx=16, pady=4)
        tk.Label(mark_row, text=t("chapter_markers.chapter_title_label")).pack(side="left")
        self.new_title_var = tk.StringVar(value="Chapter")
        title_entry = tk.Entry(mark_row, textvariable=self.new_title_var, width=30, relief="flat")
        title_entry.pack(side="left", padx=8)

        self.btn_mark = tk.Button(mark_row, text=f"📌  {t('chapter_markers.mark_here_button')}",
                                   bg=CLR["green"], fg="white",
                                   font=(UI_FONT, 11, "bold"),
                                   width=14, command=self._mark_here)
        self.btn_mark.pack(side="left", padx=8)
        tk.Button(mark_row, text=f"➕ {t('chapter_markers.add_at_zero_button')}",
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=lambda: self._add_chapter(0.0, "Intro")).pack(side="left", padx=4)

        # Auto-number
        auto_row = tk.Frame(self); auto_row.pack(anchor="w", padx=16, pady=2)
        self.autonumber_var = tk.BooleanVar(value=True)
        tk.Checkbutton(auto_row,
                       text=t("chapter_markers.auto_number_checkbox"),
                       variable=self.autonumber_var).pack(side="left")
        self.prefix_var = tk.StringVar(value="Chapter")
        tk.Entry(auto_row, textvariable=self.prefix_var, width=12, relief="flat").pack(side="left", padx=6)

        # ── Chapter list ──────────────────────────────────────────────────
        list_hdr = tk.Frame(self); list_hdr.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(list_hdr, text=t("chapter_markers.chapter_list"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(side="left")
        self.count_lbl = tk.Label(list_hdr, text=t("chapter_markers.0_chapters"),
                                   fg=CLR["fgdim"], font=(UI_FONT, 9))
        self.count_lbl.pack(side="left", padx=10)

        cols = ("timestamp", "title")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                  selectmode="browse", height=8)
        self.tree.heading("timestamp", text=t("chapter_markers.timestamp_col"))
        self.tree.heading("title",     text=t("chapter_markers.title_col"))
        self.tree.column("timestamp", width=120, anchor="center")
        self.tree.column("title",     width=500)
        tree_sb = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.config(yscrollcommand=tree_sb.set)
        self.tree.pack(side="left", fill="both", expand=False,
                       padx=(16, 0), pady=4)
        tree_sb.pack(side="left", fill="y", pady=4)
        self.tree.bind("<Double-Button-1>", self._edit_selected)
        self.tree.bind("<Delete>", lambda e: self._remove_selected())

        # List action buttons
        list_btns = tk.Frame(self)
        list_btns.pack(side="left", padx=8, anchor="n", pady=4)
        for txt, cmd, bg in [
            ("✏  Edit Title",                            self._edit_selected,  "#3A3A3A"),
            (f"🗑  {t('chapter_markers.remove_button')}",  self._remove_selected,"#3A3A3A"),
            (f"⬆  {t('chapter_markers.move_up_button')}",  self._move_up,        "#3A3A3A"),
            (f"⬇  {t('chapter_markers.move_down_button')}",self._move_down,      "#3A3A3A"),
            (f"🧹  {t('chapter_markers.clear_all_button')}",self._clear_all,      "#3A3A3A"),
            ("📂  Import .srt",                           self._import_srt,     "#3A3A3A"),
        ]:
            tk.Button(list_btns, text=txt, bg=bg, fg=CLR["fg"],
                      width=16, command=cmd).pack(pady=2)

        # ── Preview pane ──────────────────────────────────────────────────
        # (rest of the UI continues below the side-by-side)
        self.tree.pack_configure(side="left", expand=True)

        # ── Validation ────────────────────────────────────────────────────
        self.valid_lbl = tk.Label(self, text="", font=(UI_FONT, 9),
                                   fg=CLR["fgdim"])
        self.valid_lbl.pack(anchor="w", padx=16)

        # ── Export ────────────────────────────────────────────────────────
        export_lf = tk.LabelFrame(self, text=f"  {t('chapter_markers.export_section')}  ", padx=14, pady=8)
        export_lf.pack(fill="x", padx=16, pady=6)

        exp_row = tk.Frame(export_lf); exp_row.pack(fill="x")
        for fmt, cmd in [
            (f"📋  {t('chapter_markers.copy_youtube_button')}", self._copy_youtube),
            (f"📄  {t('chapter_markers.save_txt_button')}",     self._save_txt),
            (f"📄  {t('chapter_markers.save_srt_button')}",     self._save_srt),
            ("📄  Save .vtt",                                    self._save_vtt),
            ("📄  Save .json",                                   self._save_json),
        ]:
            tk.Button(exp_row, text=fmt, bg=CLR["accent"], fg="black",
                      font=(UI_FONT, 9, "bold"), width=18,
                      command=cmd).pack(side="left", padx=4)

        # Output preview
        preview_lf = tk.LabelFrame(self, text=f"  {t('chapter_markers.preview_section')}  ",
                                    padx=10, pady=6)
        preview_lf.pack(fill="x", padx=16, pady=4)
        self.preview_text = tk.Text(preview_lf, height=8,
                                     bg=CLR["bg"], fg="#EEEEEE",
                                     font=(MONO_FONT, 10))
        self.preview_text.pack(fill="x")

    # ─────────────────────────────────────────────────────────────────────
    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            self._duration = get_video_duration(p)
            m, s = divmod(int(self._duration), 60)
            self.dur_lbl.config(text=f"{m}m {s}s", fg=CLR["fgdim"])
            self.timeline.config(to=self._duration)

    def _on_scrub(self, val):
        t = float(val)
        self.pos_lbl.config(text=_fmt_yt(t))

    def _jump(self):
        try:
            t = float(self.jump_var.get())
            self.timeline.set(min(t, self._duration))
        except ValueError:
            pass

    def _jump_pct(self, pct):
        t = self._duration * pct / 100
        self.timeline.set(t)

    def _mark_here(self):
        t     = float(self.timeline.get())
        title = self.new_title_var.get().strip()
        if not title:
            title = f"Chapter {len(self.chapters)+1}"
        if self.autonumber_var.get():
            prefix = self.prefix_var.get().strip() or "Chapter"
            title  = f"{prefix} {len(self.chapters)+1}"
        self._add_chapter(t, title)

    def _add_chapter(self, ts: float, title: str):
        # Prevent duplicate timestamps
        if any(abs(c.time - ts) < 0.5 for c in self.chapters):
            messagebox.showwarning(t("common.warning"),
                                   f"A chapter already exists near {_fmt_yt(ts)}.")
            return
        c = Chapter(ts, title)
        self.chapters.append(c)
        self.chapters.sort(key=lambda x: x.time)
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.chapters):
            self.tree.insert("", tk.END, iid=str(i),
                             values=(_fmt_yt(c.time), c.title))
        n = len(self.chapters)
        self.count_lbl.config(text=f"{n} chapter{'s' if n!=1 else ''}")
        self._validate()
        self._update_preview()

    def _validate(self):
        issues = []
        n = len(self.chapters)
        if n < 3:
            issues.append(f"⚠  YouTube requires at least 3 chapters (you have {n}).")
        if self.chapters and self.chapters[0].time > 0.5:
            issues.append("⚠  First chapter must start at 0:00.")
        if n >= 3 and not issues:
            self.valid_lbl.config(text=t("chapter_markers.valid_for_youtube_chapters"), fg=CLR["green"])
        else:
            self.valid_lbl.config(text="  ".join(issues), fg=CLR["orange"])

    def _update_preview(self):
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", tk.END)
        for c in self.chapters:
            self.preview_text.insert(tk.END, f"{_fmt_yt(c.time)} {c.title}\n")
        self.preview_text.config(state="disabled")

    def _edit_selected(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        c   = self.chapters[idx]
        dlg = tk.Toplevel(self)
        dlg.title("Edit Chapter")
        dlg.geometry("400x150")
        dlg.grab_set()
        tk.Label(dlg, text=t("chapter_markers.timestamp_s")).pack(pady=(14, 2))
        ts_var = tk.StringVar(value=str(c.time))
        tk.Entry(dlg, textvariable=ts_var, width=12, relief="flat").pack()
        tk.Label(dlg, text=t("chapter_markers.title")).pack(pady=(8, 2))
        ti_var = tk.StringVar(value=c.title)
        tk.Entry(dlg, textvariable=ti_var, width=34).pack()

        def _save():
            try:
                c.time  = float(ts_var.get())
                c.title = ti_var.get().strip()
                self.chapters.sort(key=lambda x: x.time)
                self._refresh_tree()
                dlg.destroy()
            except ValueError:
                messagebox.showerror(t("common.error"), "Enter a valid number for timestamp.")
        tk.Button(dlg, text="Save", command=_save, bg=CLR["green"], fg="white", cursor="hand2", relief="flat").pack(pady=10)

    def _remove_selected(self):
        sel = self.tree.selection()
        if sel:
            del self.chapters[int(sel[0])]
            self._refresh_tree()

    def _move_up(self):
        sel = self.tree.selection()
        if not sel or int(sel[0]) == 0: return
        i = int(sel[0])
        self.chapters[i], self.chapters[i-1] = self.chapters[i-1], self.chapters[i]
        self._refresh_tree()
        self.tree.selection_set(str(i-1))

    def _move_down(self):
        sel = self.tree.selection()
        if not sel or int(sel[0]) >= len(self.chapters)-1: return
        i = int(sel[0])
        self.chapters[i], self.chapters[i+1] = self.chapters[i+1], self.chapters[i]
        self._refresh_tree()
        self.tree.selection_set(str(i+1))

    def _clear_all(self):
        if messagebox.askyesno(t("msg.clear_title"), t("msg.remove_all_chapters")):
            self.chapters.clear()
            self._refresh_tree()

    def _import_srt(self):
        p = filedialog.askopenfilename(
            filetypes=[(t("chapter_markers.srt_text"), "*.srt *.txt"), ("All", t("ducker.item_2"))])
        if not p: return
        with open(p) as f:
            content = f.read()
        # Try SRT format: 00:01:23,000 --> ...
        srt_re = re.compile(
            r"(\d+:\d{2}:\d{2}),\d{3}\s*-->\s*.*\n(.*)")
        matches = srt_re.findall(content)
        if matches:
            for tc, title in matches:
                h, m, s = map(int, tc.split(":"))
                t = h*3600 + m*60 + s
                self._add_chapter(float(t), title.strip())
        else:
            # Plain text: MM:SS Title
            for line in content.splitlines():
                m = re.match(r"(\d+):(\d{2})\s+(.*)", line.strip())
                if m:
                    t = int(m.group(1))*60 + int(m.group(2))
                    self._add_chapter(float(t), m.group(3).strip())

    # ── Export methods ────────────────────────────────────────────────────
    def _yt_text(self):
        return "\n".join(f"{_fmt_yt(c.time)} {c.title}" for c in self.chapters)

    def _copy_youtube(self):
        txt = self._yt_text()
        self.clipboard_clear()
        self.clipboard_append(txt)
        messagebox.showinfo(t("msg.copied_title"), t("msg.chapters_copied"))

    def _save_txt(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt",
                                          filetypes=[("Text", "*.txt")])
        if p:
            with open(p, "w") as f:
                f.write(self._yt_text())
            messagebox.showinfo("Saved", f"Saved to {os.path.basename(p)}")

    def _save_srt(self):
        p = filedialog.asksaveasfilename(defaultextension=".srt",
                                          filetypes=[("SRT", "*.srt")])
        if not p: return
        lines = []
        for i, c in enumerate(self.chapters):
            end_t = (self.chapters[i+1].time - 0.001
                     if i+1 < len(self.chapters)
                     else self._duration or c.time + 10)
            lines.append(str(i+1))
            lines.append(f"{_fmt_srt_tc(c.time)} --> {_fmt_srt_tc(end_t)}")
            lines.append(c.title)
            lines.append("")
        with open(p, "w") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Saved", f"SRT saved to {os.path.basename(p)}")

    def _save_vtt(self):
        p = filedialog.asksaveasfilename(defaultextension=".vtt",
                                          filetypes=[("WebVTT", "*.vtt")])
        if not p: return
        lines = ["WEBVTT", ""]
        for i, c in enumerate(self.chapters):
            end_t = (self.chapters[i+1].time - 0.001
                     if i+1 < len(self.chapters)
                     else self._duration or c.time + 10)
            def vtt_tc(s):
                h = int(s)//3600; m=(int(s)%3600)//60; sec=int(s)%60
                ms=int((s-int(s))*1000)
                return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"
            lines.append(f"{vtt_tc(c.time)} --> {vtt_tc(end_t)}")
            lines.append(c.title)
            lines.append("")
        with open(p, "w") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Saved", f"VTT saved to {os.path.basename(p)}")

    def _save_json(self):
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                          filetypes=[("JSON", t("chapter_markers.json"))])
        if not p: return
        data = [{"time": c.time, "timestamp": _fmt_yt(c.time),
                 "title": c.title} for c in self.chapters]
        with open(p, "w") as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", f"JSON saved to {os.path.basename(p)}")
