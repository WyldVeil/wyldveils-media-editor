"""
tab_presetmanager.py  ─  Preset Manager
Save, load, and manage named encoding presets.
Presets store the full FFmpeg command template with placeholders
{INPUT} and {OUTPUT}. Can be exported/imported as JSON.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import json
import os
import subprocess
import threading

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t

PRESETS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "encode_presets.json")

# Built-in starter presets
BUILT_IN = [
    {
        "name": t("presets.instagram_reel_1080_1920_h_264"),
        "category": "Social",
        "description": t("presets.vertical_9_16_for_instagram_reels_and_tiktok"),
        "cmd": '-i {INPUT} -vf t("presets.scale_1080_1920_force_original_aspect_ratio_decr") -c:v libx264 -crf 20 -preset fast -c:a aac -b:a 192k {OUTPUT}',
    },
    {
        "name": t("presets.youtube_upload_1080p_h_264_high_quality"),
        "category": "Web",
        "description": "Optimised for YouTube's recommended settings.",
        "cmd": '-i {INPUT} -vf t("presets.scale_1920_1080_force_original_aspect_ratio_decr") -c:v libx264 -crf 16 -preset slow -c:a aac -b:a 320k {OUTPUT}',
    },
    {
        "name": t("presets.quick_compress_h_265_crf_28"),
        "category": "Compression",
        "description": t("presets.shrink_file_size_fast_half_the_size_of_h_264_at"),
        "cmd": "-i {INPUT} -c:v libx265 -crf 28 -preset fast -c:a aac -b:a 128k {OUTPUT}",
    },
    {
        "name": t("presets.archive_master_lossless_h_265"),
        "category": "Archive",
        "description": t("presets.lossless_encode_for_long_term_archival_storage"),
        "cmd": "-i {INPUT} -c:v libx265 -x265-params lossless=1 -c:a flac {OUTPUT}",
    },
    {
        "name": t("presets.streaming_proxy_low_bitrate_h_264"),
        "category": "Proxy",
        "description": t("presets.fast_tiny_proxy_for_editing_on_slow_machines"),
        "cmd": '-i {INPUT} -vf t("presets.scale_iw_4_ih_4") -c:v libx264 -crf 28 -preset ultrafast -c:a aac -b:a 96k {OUTPUT}',
    },
    {
        "name": t("presets.audio_only_hq_aac"),
        "category": "Audio",
        "description": t("presets.strip_video_keep_audio_as_high_quality_aac"),
        "cmd": "-i {INPUT} -vn -c:a aac -b:a 320k {OUTPUT}",
    },
    {
        "name": t("presets.webm_for_web_vp9_2_pass"),
        "category": "Web",
        "description": t("presets.efficient_vp9_webm_for_web_embedding"),
        "cmd": "-i {INPUT} -c:v libvpx-vp9 -b:v 1M -pass 1 -an -f webm /dev/null && ffmpeg -i {INPUT} -c:v libvpx-vp9 -b:v 1M -pass 2 -c:a libopus -b:a 128k {OUTPUT}",
    },
    {
        "name": t("presets.4k_downscale_to_1080p_lanczos"),
        "category": "Compression",
        "description": t("presets.downscale_4k_footage_to_1080p_with_best_quality"),
        "cmd": '-i {INPUT} -vf t("presets.scale_1920_1080_flags_lanczos") -c:v libx264 -crf 18 -preset medium -c:a copy {OUTPUT}',
    },
]


def _load_presets():
    presets = list(BUILT_IN)
    try:
        if os.path.exists(PRESETS_FILE):
            with open(PRESETS_FILE) as f:
                custom = json.load(f)
            # Merge: built-ins first, then user presets
            bi_names = {p["name"] for p in BUILT_IN}
            presets += [p for p in custom if p.get("name") not in bi_names]
    except Exception:
        pass
    return presets


def _save_user_presets(presets):
    # Save only non-built-in presets
    bi_names = {p["name"] for p in BUILT_IN}
    user_only = [p for p in presets if p.get("name") not in bi_names]
    try:
        with open(PRESETS_FILE, "w") as f:
            json.dump(user_only, f, indent=2)
        return True
    except Exception as e:
        print(f"Preset save error: {e}")
        return False


class PresetManagerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.presets = _load_presets()
        self._selected_idx = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="💾  " + t("tab.preset_manager"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("presets.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Main paned layout ─────────────────────────────────────────────
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6,
                               bg="#AAAAAA")
        paned.pack(fill="both", expand=True, padx=10, pady=8)

        left  = tk.Frame(paned, width=420)
        right = tk.Frame(paned, width=560)
        paned.add(left,  minsize=280)
        paned.add(right, minsize=320)

        self._build_list(left)
        self._build_editor(right)

        # Seed list
        self._refresh_list()

    # ── Preset list ───────────────────────────────────────────────────────
    def _build_list(self, parent):
        tk.Label(parent, text="PRESETS", font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        # Filter / search
        search_f = tk.Frame(parent); search_f.pack(fill="x", padx=6, pady=2)
        tk.Label(search_f, text="🔍").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_list())
        tk.Entry(search_f, textvariable=self.search_var,
                 width=30).pack(side="left", padx=4)
        tk.Label(search_f, text=t("presets.category_label")).pack(side="left", padx=(12, 4))
        self.cat_filter_var = tk.StringVar(value="All")
        self.cat_cb = ttk.Combobox(search_f, textvariable=self.cat_filter_var,
                                    values=["All"], state="readonly", width=12)
        self.cat_cb.pack(side="left")
        self.cat_filter_var.trace_add("write", lambda *_: self._refresh_list())

        # Treeview
        cols = ("name", "category")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings",
                                  selectmode="browse", height=20)
        self.tree.heading("name",     text=t("presets.preset_name_col"))
        self.tree.heading("category", text="Category")
        self.tree.column("name",     width=270, stretch=True)
        self.tree.column("category", width=90)
        self.tree.tag_configure("builtin", foreground="#888888")
        self.tree.tag_configure("custom",  foreground="#EEEEEE")

        tsb = ttk.Scrollbar(parent, command=self.tree.yview)
        self.tree.config(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", lambda e: self._quick_run())

        # Action buttons
        btn_f = tk.Frame(parent); btn_f.pack(fill="x", padx=6, pady=6)
        for txt, bg, cmd in [
            ("▶ Quick Run",    CLR["green"], self._quick_run),
            ("🗑 Delete",      "#3A3A3A",    self._delete_selected),
            ("📋 Duplicate",   "#3A3A3A",    self._duplicate),
            ("📤 Export",      "#3A3A3A",    self._export_presets),
            ("📥 Import",      "#3A3A3A",    self._import_presets),
        ]:
            tk.Button(btn_f, text=txt, bg=bg, fg=CLR["fg"],
                      font=(UI_FONT, 8), command=cmd).pack(side="left", padx=2)

    # ── Editor panel ──────────────────────────────────────────────────────
    def _build_editor(self, parent):
        tk.Label(parent, text=t("presets.editor_section"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        ef = tk.Frame(parent)
        ef.pack(fill="both", expand=True, padx=8)

        fields = [
            (t("presets.name_label"),        "ed_name_var",     None),
            (t("presets.category_label"),    "ed_cat_var",
             ["Social","Web","Compression","Archive","Proxy","Audio","Custom"]),
            ("Description:", "ed_desc_var",     None),
        ]

        for label, attr, choices in fields:
            row = tk.Frame(ef); row.pack(fill="x", pady=4)
            tk.Label(row, text=label, width=12, anchor="e").pack(side="left")
            var = tk.StringVar()
            setattr(self, attr, var)
            if choices:
                ttk.Combobox(row, textvariable=var, values=choices,
                             width=22).pack(side="left", padx=6)
            else:
                tk.Entry(row, textvariable=var, width=42, relief="flat").pack(side="left", padx=6)

        # FFmpeg command template
        cmd_lbl = tk.Frame(ef); cmd_lbl.pack(fill="x", pady=(8, 2))
        tk.Label(cmd_lbl, text=t("presets.command_label"),
                 font=(UI_FONT, 9, "bold")).pack(side="left")
        tk.Label(cmd_lbl,
                 text="  Use {INPUT} and {OUTPUT} as placeholders",
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left")

        self.ed_cmd_text = scrolledtext.ScrolledText(
            ef, height=7, font=(MONO_FONT, 9),
            bg=CLR["bg"], fg="#00FF88", wrap="word")
        self.ed_cmd_text.pack(fill="x", pady=2)

        # Help examples
        help_lf = tk.LabelFrame(ef, text=f"  {t('presets.quick_insert_section')}  ", padx=8, pady=4)
        help_lf.pack(fill="x", pady=4)
        snippets = [
            ("H.264",      t("presets.c_v_libx264_crf_18_preset_fast")),
            ("H.265",      t("presets.c_v_libx265_crf_22_preset_fast")),
            (t("presets.scale_1080"), '-vf t("presets.scale_1920_1080")'),
            ("AAC audio",  t("presets.c_a_aac_b_a_192k")),
            ("Copy all",   t("presets.c_copy")),
            (t("presets.strip_audio"),"-an"),
        ]
        for label, snippet in snippets:
            tk.Button(help_lf, text=label, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 8),
                      command=lambda s=snippet: self._insert_snippet(s)
                      ).pack(side="left", padx=2)

        # Buttons
        act_f = tk.Frame(ef); act_f.pack(fill="x", pady=8)
        tk.Button(act_f, text=t("presets.save_button"), bg=CLR["accent"], fg="black",
                  font=(UI_FONT, 10, "bold"), command=self._save_preset
                  ).pack(side="left", padx=4)
        tk.Button(act_f, text=t("presets.new_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._new_preset).pack(side="left", padx=4)
        tk.Button(act_f, text=t("presets.clear_button"), bg=CLR["panel"], fg=CLR["fg"],
                  command=self._clear_editor).pack(side="left", padx=4)

        # ── Quick Run section ─────────────────────────────────────────────
        run_lf = tk.LabelFrame(ef, text=f"  {t('presets.quick_run_section')}  ",
                                padx=10, pady=8)
        run_lf.pack(fill="x", pady=6)

        run_row = tk.Frame(run_lf); run_row.pack(fill="x")
        tk.Label(run_row, text=t("webm_maker.input")).pack(side="left")
        self.run_src_var = tk.StringVar()
        tk.Entry(run_row, textvariable=self.run_src_var, width=36, relief="flat").pack(side="left", padx=4)
        tk.Button(run_row, text="…", command=self._browse_run_src, width=2, cursor="hand2", relief="flat").pack(side="left")

        run_row2 = tk.Frame(run_lf); run_row2.pack(fill="x", pady=4)
        tk.Label(run_row2, text=t("encode_queue.output_label")).pack(side="left")
        self.run_out_var = tk.StringVar()
        tk.Entry(run_row2, textvariable=self.run_out_var, width=36, relief="flat").pack(side="left", padx=4)
        tk.Button(run_row2, text="…", command=self._browse_run_out, width=2, cursor="hand2", relief="flat").pack(side="left")

        self.btn_run = tk.Button(run_lf, text=t("presets.run_now_button"),
                                  bg=CLR["green"], fg="white",
                                  font=(UI_FONT, 11, "bold"), height=2,
                                  command=self._quick_run)
        self.btn_run.pack(pady=4, fill="x")

        # Console
        self.console = scrolledtext.ScrolledText(
            ef, height=6, bg=CLR["console_bg"], fg="#00FF88", font=(MONO_FONT, 8))
        self.console.pack(fill="both", expand=True, pady=4)

    # ═══════════════════════════════════════════════════════════════════════
    #  List logic
    # ═══════════════════════════════════════════════════════════════════════
    def _refresh_list(self):
        search = self.search_var.get().lower()
        cat    = self.cat_filter_var.get()

        # Update category dropdown
        cats = sorted({"All"} | {p.get("category", "Custom")
                                  for p in self.presets})
        self.cat_cb.config(values=cats)

        self.tree.delete(*self.tree.get_children())
        bi_names = {p["name"] for p in BUILT_IN}
        for i, p in enumerate(self.presets):
            if search and search not in p["name"].lower() \
                    and search not in p.get("description","").lower():
                continue
            if cat != "All" and p.get("category", "Custom") != cat:
                continue
            tag = "builtin" if p["name"] in bi_names else "custom"
            self.tree.insert("", tk.END, iid=str(i),
                             values=(p["name"], p.get("category","Custom")),
                             tags=(tag,))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        self._selected_idx = idx
        p = self.presets[idx]
        self.ed_name_var.set(p.get("name",""))
        self.ed_cat_var.set(p.get("category","Custom"))
        self.ed_desc_var.set(p.get("description",""))
        self.ed_cmd_text.delete("1.0", tk.END)
        self.ed_cmd_text.insert(tk.END, p.get("cmd",""))
        # Auto-fill output name hint
        src = self.run_src_var.get()
        if src:
            base = os.path.splitext(src)[0]
            self.run_out_var.set(base + "_preset.mp4")

    def _new_preset(self):
        self._selected_idx = None
        self._clear_editor()

    def _clear_editor(self):
        self.ed_name_var.set("")
        self.ed_cat_var.set("Custom")
        self.ed_desc_var.set("")
        self.ed_cmd_text.delete("1.0", tk.END)

    def _insert_snippet(self, s):
        self.ed_cmd_text.insert(tk.INSERT, " " + s + " ")

    def _save_preset(self):
        name = self.ed_name_var.get().strip()
        cmd  = self.ed_cmd_text.get("1.0", tk.END).strip()
        if not name:
            messagebox.showwarning(t("common.warning"), "Enter a preset name.")
            return
        if not cmd:
            messagebox.showwarning(t("common.warning"), "Enter an FFmpeg command template.")
            return

        entry = {
            "name":        name,
            "category":    self.ed_cat_var.get(),
            "description": self.ed_desc_var.get(),
            "cmd":         cmd,
        }

        bi_names = {p["name"] for p in BUILT_IN}
        if name in bi_names:
            messagebox.showwarning(t("common.warning"),
                                   "Built-in presets cannot be overwritten.\n"
                                   "Change the name to save as a new custom preset.")
            return

        # Update existing or append
        existing = next((i for i, p in enumerate(self.presets)
                         if p["name"] == name), None)
        if existing is not None:
            self.presets[existing] = entry
        else:
            self.presets.append(entry)

        _save_user_presets(self.presets)
        self._refresh_list()
        messagebox.showinfo("Saved", f'Preset "{name}" saved.')

    def _delete_selected(self):
        if self._selected_idx is None: return
        p = self.presets[self._selected_idx]
        bi_names = {p2["name"] for p2 in BUILT_IN}
        if p["name"] in bi_names:
            messagebox.showwarning(t("common.warning"), "Built-in presets cannot be deleted.")
            return
        if messagebox.askyesno("Delete", f'Delete preset "{p["name"]}"?'):
            del self.presets[self._selected_idx]
            self._selected_idx = None
            _save_user_presets(self.presets)
            self._refresh_list()

    def _duplicate(self):
        if self._selected_idx is None: return
        p = dict(self.presets[self._selected_idx])
        p["name"] = p["name"] + " (copy)"
        self.presets.append(p)
        _save_user_presets(self.presets)
        self._refresh_list()

    def _export_presets(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", t("chapter_markers.json"))])
        if path:
            with open(path, "w") as f:
                json.dump(self.presets, f, indent=2)
            messagebox.showinfo("Exported", f"Presets exported to {os.path.basename(path)}")

    def _import_presets(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", t("chapter_markers.json"))])
        if not path: return
        try:
            with open(path) as f:
                imported = json.load(f)
            added = 0
            existing_names = {p["name"] for p in self.presets}
            for p in imported:
                if p.get("name") and p["name"] not in existing_names:
                    self.presets.append(p)
                    added += 1
            _save_user_presets(self.presets)
            self._refresh_list()
            messagebox.showinfo("Imported", f"Added {added} new preset(s).")
        except Exception as e:
            messagebox.showerror(t("common.error"), str(e))

    # ── Quick run ─────────────────────────────────────────────────────────
    def _browse_run_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.run_src_var.set(p)
            base = os.path.splitext(p)[0]
            self.run_out_var.set(base + "_preset.mp4")

    def _browse_run_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("All", t("ducker.item_2"))])
        if p: self.run_out_var.set(p)

    def _quick_run(self):
        if self._selected_idx is None:
            messagebox.showinfo(t("msg.no_preset_title"), t("msg.select_preset"))
            return
        src = self.run_src_var.get().strip()
        out = self.run_out_var.get().strip()
        if not src:
            src = filedialog.askopenfilename(
                filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"), ("All", t("ducker.item_2"))])
        if not src: return
        if not out:
            base = os.path.splitext(src)[0]
            out  = base + "_preset.mp4"
        self.run_src_var.set(src)
        self.run_out_var.set(out)

        p = self.presets[self._selected_idx]
        cmd_template = p.get("cmd","")
        if not cmd_template:
            messagebox.showwarning(t("common.warning"), "This preset has no command.")
            return

        ffmpeg = get_binary_path("ffmpeg.exe")
        # Build full command
        full = f'"{ffmpeg}" ' + cmd_template.replace("{INPUT}", f'"{src}"') \
                                             .replace("{OUTPUT}", f'"{out}" -y')

        self.console.insert(tk.END, f"\n▶ Running preset: {p['name']}\n")
        self.console.insert(tk.END, f"$ {full}\n\n")
        self.console.see(tk.END)

        self.btn_run.config(state="disabled", text=t("app.status.queued_btn"))

        import platform as _platform
        if _platform.system() == "Windows":
            shell_cmd = ["cmd.exe", "/c", full]
        else:
            shell_cmd = [t("presets.bin_sh"), "-c", full]

        _out = out

        def _worker_fn(progress_cb, cancel_fn):
            proc = subprocess.Popen(
                shell_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
            for line in iter(proc.stdout.readline, ""):
                if cancel_fn():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                progress_cb(line.rstrip())
            proc.stdout.close()
            proc.wait()
            return proc.returncode

        def _on_start(tid):
            self.btn_run.config(text=t("presets.running"))

        def _on_progress(tid, line):
            self.after(0, lambda l=line: [
                self.console.insert(tk.END, l + "\n"),
                self.console.see(tk.END)])

        def _on_complete(tid, rc):
            self.btn_run.config(state="normal", text=t("presets.run_now_button"))
            self.show_result(rc, _out)

        self.enqueue_render(
            f"Preset: {p['name']}",
            output_path=_out,
            worker_fn=_worker_fn,
            on_start=_on_start,
            on_progress=_on_progress,
            on_complete=_on_complete,
        )
