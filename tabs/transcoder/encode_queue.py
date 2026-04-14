"""
tab_encodequeue.py  ─  Global Render Queue Dashboard
======================================================
Live view of every task in the RenderQueueManager - whether submitted from
this tab or any other tab in the app.

Left panel  - queue treeview (all tasks, live-refreshed)
Right panel - job settings editor for queueing new encode jobs from here
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import os
import uuid
import time

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


VIDEO_CODECS = ["libx264", "libx265", "libvpx-vp9", "libvpx",
                "prores_ks", "dnxhd", "copy"]
AUDIO_CODECS = ["aac", "libmp3lame", "libopus", "libvorbis", "flac",
                "pcm_s16le", "copy", "none"]
PRESETS      = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]
RESOLUTIONS  = ["Source", "3840x2160", "2560x1440", "1920x1080",
                "1280x720", "854x480", "640x360"]


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


# ─────────────────────────────────────────────────────────────────────────────
#  Job  -  settings model for encoding jobs added through the editor panel
# ─────────────────────────────────────────────────────────────────────────────

class Job:
    """Settings model for one encode job created in the editor panel."""
    def __init__(self):
        self.src        = ""
        self.out        = ""
        self.vcodec     = "libx264"
        self.crf        = "18"
        self.preset     = "fast"
        self.resolution = "Source"
        self.fps        = "Source"
        self.acodec     = "aac"
        self.abitrate   = "192k"
        self.extra_vf   = ""
        self.extra_args = ""

    def build_cmd(self, ffmpeg):
        cmd = [ffmpeg, "-i", self.src]

        if self.vcodec != "copy":
            cmd += ["-c:v", self.vcodec]
            if self.vcodec not in ("prores_ks", "dnxhd", "libvpx", "libvpx-vp9"):
                cmd += ["-crf", self.crf, "-preset", self.preset]
            elif self.vcodec in ("libvpx", "libvpx-vp9"):
                cmd += ["-b:v", "0", "-crf", self.crf]
        else:
            cmd += ["-c:v", "copy"]

        vf_parts = []
        if self.resolution != "Source":
            w, h = self.resolution.split("x")
            vf_parts.append(
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        if self.fps not in ("Source", "0", ""):
            vf_parts.append(f"fps={self.fps}")
        if self.extra_vf.strip():
            vf_parts.append(self.extra_vf.strip())
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]

        if self.acodec == "none":
            cmd += ["-an"]
        elif self.acodec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", self.acodec, "-b:a", self.abitrate]

        if self.extra_args.strip():
            import shlex
            try:
                cmd += shlex.split(self.extra_args)
            except Exception:
                pass

        cmd += [self.out, "-y"]
        return cmd


# ─────────────────────────────────────────────────────────────────────────────
#  EncodeQueueTab
# ─────────────────────────────────────────────────────────────────────────────

class EncodeQueueTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self._editor_job: Job | None = None
        self._selected_task_id: str | None = None
        self._build_ui()

        # Wire to global queue
        from core.queue_manager import RenderQueueManager
        self._qmgr = RenderQueueManager.get_instance()
        self._qmgr.register_update_callback(self._refresh_queue_tree)
        self._refresh_queue_tree()

    # ═══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📋  " + t("tab.encode_queue"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner,
                 text=t("encode_queue.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Paned layout
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6,
                               bg="#AAAAAA")
        paned.pack(fill="both", expand=True, padx=10, pady=8)

        left  = tk.Frame(paned, width=540)
        paned.add(left, minsize=340)
        right = tk.Frame(paned, width=480)
        paned.add(right, minsize=320)

        self._build_queue_panel(left)
        self._build_editor_panel(right)

    # ── Queue list panel ──────────────────────────────────────────────────
    def _build_queue_panel(self, parent):
        tk.Label(parent, text=t("encode_queue.queue_section"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        cols = ("status", "name", "output", "elapsed", "progress")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings",
                                 selectmode="browse", height=18)
        for col, txt, w, stretch in [
            ("status",   t("encode_queue.status_col"),   72,  False),
            ("name",     t("encode_queue.task_col"),     160, True),
            ("output",   t("encode_queue.output_col"),   140, True),
            ("elapsed",  t("encode_queue.elapsed_col"),  70,  False),
            ("progress", t("encode_queue.progress_col"), 220, True),
        ]:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, stretch=stretch)

        self.tree.tag_configure("done",      foreground="#4CAF50")
        self.tree.tag_configure("failed",    foreground="#F44336")
        self.tree.tag_configure("cancelled", foreground="#888888")
        self.tree.tag_configure("active",    foreground="#4FC3F7")
        self.tree.tag_configure("pending",   foreground="#EEEEEE")

        tsb = ttk.Scrollbar(parent, command=self.tree.yview)
        self.tree.config(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Control buttons
        btn_f = tk.Frame(parent)
        btn_f.pack(fill="x", padx=4, pady=6)
        self._btn_cancel = tk.Button(
            btn_f, text=t("encode_queue.cancel_button"),
            bg=CLR["red"], fg="white", font=(UI_FONT, 9, "bold"),
            command=self._cancel_selected)
        self._btn_cancel.pack(side="left", padx=4)
        tk.Button(btn_f, text=t("encode_queue.clear_finished_button"),
                  bg=CLR["panel"], fg=CLR["fg"], font=(UI_FONT, 9),
                  command=self._clear_finished).pack(side="left", padx=4)

        # Stats label
        self._stats_lbl = tk.Label(parent, text="", fg=CLR["fgdim"],
                                    font=(UI_FONT, 9))
        self._stats_lbl.pack(anchor="w", padx=8)

        # Console for selected task's last progress
        tk.Label(parent, text=t("encode_queue.task_log_section"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))
        self.console = scrolledtext.ScrolledText(
            parent, height=7,
            bg=CLR["console_bg"], fg="#00FF88",
            font=(MONO_FONT, 8))
        self.console.pack(fill="both", expand=True, padx=4, pady=4)

    # ── Job editor panel ─────────────────────────────────────────────────
    def _build_editor_panel(self, parent):
        tk.Label(parent, text=t("encode_queue.editor_section"), font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        scroll_canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical",
                           command=scroll_canvas.yview)
        self.editor_frame = tk.Frame(scroll_canvas)
        scroll_canvas.create_window((0, 0), window=self.editor_frame, anchor="nw")
        self.editor_frame.bind("<Configure>",
            lambda e: scroll_canvas.configure(
                scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.configure(yscrollcommand=sb.set)
        scroll_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ef  = self.editor_frame
        pad = {"padx": 10, "pady": 4}

        # Source / output
        self.ed_src_var = tk.StringVar()
        f_src = tk.Frame(ef); f_src.pack(fill="x", **pad)
        tk.Label(f_src, text=t("encode_queue.source_label"), width=14, anchor="e").pack(side="left")
        tk.Entry(f_src, textvariable=self.ed_src_var, width=32,
                 relief="flat").pack(side="left", padx=4)
        tk.Button(f_src, text="…", width=2,
                  command=self._ed_browse_src).pack(side="left")

        self.ed_out_var = tk.StringVar()
        f_out = tk.Frame(ef); f_out.pack(fill="x", **pad)
        tk.Label(f_out, text=t("encode_queue.output_label"), width=14, anchor="e").pack(side="left")
        tk.Entry(f_out, textvariable=self.ed_out_var, width=32,
                 relief="flat").pack(side="left", padx=4)
        tk.Button(f_out, text="…", width=2,
                  command=self._ed_browse_out).pack(side="left")

        # Codec / quality fields
        fields = [
            (t("encode_queue.video_codec"), "ed_vcodec_var", VIDEO_CODECS,   "libx264"),
            (t("common.crf"),          "ed_crf_var",    None,           "18"),
            (t("common.preset"),       "ed_preset_var", PRESETS,        "fast"),
            (t("common.resolution"),   "ed_res_var",    RESOLUTIONS,    "Source"),
            (t("batch_joiner.lbl_fps"),          "ed_fps_var",
             ["Source", "23.976", "24", "25", "29.97", "30", "50", "60"], "Source"),
            ("Audio codec:",  "ed_acodec_var", AUDIO_CODECS,   "aac"),
            ("Audio bitrate:", "ed_abitrate_var",
             ["64k", "96k", "128k", "192k", "256k", "320k"], "192k"),
        ]
        for label, attr, choices, default in fields:
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            f = tk.Frame(ef); f.pack(fill="x", **pad)
            tk.Label(f, text=label, width=14, anchor="e").pack(side="left")
            if choices:
                ttk.Combobox(f, textvariable=var, values=choices,
                             state="readonly", width=18).pack(side="left", padx=4)
            else:
                tk.Entry(f, textvariable=var, width=8,
                         relief="flat").pack(side="left", padx=4)

        for label, attr in [("Extra -vf:",   "ed_evf_var"),
                             ("Extra args:",  "ed_eargs_var")]:
            var = tk.StringVar()
            setattr(self, attr, var)
            f = tk.Frame(ef); f.pack(fill="x", **pad)
            tk.Label(f, text=label, width=14, anchor="e").pack(side="left")
            tk.Entry(f, textvariable=var, width=34,
                     relief="flat").pack(side="left", padx=4)

        # Submit button
        tk.Button(
            ef, text=t("encode_queue.add_to_queue_button"),
            bg=CLR["green"], fg="black",
            font=(UI_FONT, 10, "bold"),
            command=self._add_to_queue,
        ).pack(pady=10, padx=10, fill="x")

        # Add folder button
        tk.Button(
            ef, text=t("encode_queue.add_folder_button"),
            bg=CLR["panel"], fg=CLR["fg"],
            font=(UI_FONT, 9),
            command=self._add_folder,
        ).pack(pady=(0, 6), padx=10, fill="x")

    # ═══════════════════════════════════════════════════════════════════════
    #  Queue tree refresh  (called by RenderQueueManager update callback)
    # ═══════════════════════════════════════════════════════════════════════
    def _refresh_queue_tree(self):
        tasks = self._qmgr.get_all_tasks()

        # Preserve selection
        sel_id = self._selected_task_id

        self.tree.delete(*self.tree.get_children())
        for t in tasks:
            elapsed = ""
            if t.started_at:
                end = t.finished_at or time.time()
                elapsed = _fmt_elapsed(end - t.started_at)

            progress = t.progress[:60] if t.progress else ""
            out_name = os.path.basename(t.output_path) if t.output_path else "-"

            self.tree.insert(
                "", tk.END, iid=t.id,
                values=(t.status.upper(), t.name, out_name, elapsed, progress),
                tags=(t.status,),
            )

        # Re-select
        if sel_id:
            try:
                self.tree.selection_set(sel_id)
            except Exception:
                pass

        # Stats
        active, pending, done, failed = self._qmgr.get_stats()
        total = len(tasks)
        self._stats_lbl.config(
            text=f"{total} tasks  ·  {active} active  ·  {pending} pending  "
                 f"·  {done} done  ·  {failed} failed")

    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self._selected_task_id = sel[0]
        # Show latest progress in console
        tasks = self._qmgr.get_all_tasks()
        for t in tasks:
            if t.id == self._selected_task_id:
                if t.progress:
                    self.console.delete("1.0", tk.END)
                    self.console.insert(tk.END, f"[{t.name}]\n{t.progress}\n")
                break

    def _cancel_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(t("encode_queue.nothing_selected_title"), t("encode_queue.nothing_selected_message"))
            return
        self._qmgr.cancel(sel[0])

    def _clear_finished(self):
        self._qmgr.clear_finished()

    # ═══════════════════════════════════════════════════════════════════════
    #  Editor: add new encode jobs
    # ═══════════════════════════════════════════════════════════════════════
    def _ed_browse_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.ed_src_var.set(p)
            if not self.ed_out_var.get():
                self.ed_out_var.set(os.path.splitext(p)[0] + "_encoded.mp4")

    def _ed_browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All", t("ducker.item_2"))])
        if p:
            self.ed_out_var.set(p)

    def _add_to_queue(self):
        src = self.ed_src_var.get().strip()
        out = self.ed_out_var.get().strip()
        if not src:
            messagebox.showwarning(t("encode_queue.no_source_title"), t("encode_queue.no_source_message"))
            return
        if not out:
            out = os.path.splitext(src)[0] + "_encoded.mp4"
            self.ed_out_var.set(out)

        j = self._read_editor()
        j.src = src
        j.out = out

        ffmpeg = get_binary_path("ffmpeg.exe")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        except Exception:
            pass

        cmd = j.build_cmd(ffmpeg)
        task_name = os.path.basename(src)

        self.enqueue_render(
            task_name,
            output_path=out,
            cmd=cmd,
            on_progress=lambda tid, line: self._on_task_progress(tid, line),
            on_complete=lambda tid, rc: self._on_task_complete(tid, rc, out),
        )

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
        ffmpeg = get_binary_path("ffmpeg.exe")
        count = 0
        for fn in sorted(os.listdir(folder)):
            if os.path.splitext(fn)[1].lower() not in exts:
                continue
            src = os.path.join(folder, fn)
            out = os.path.join(folder, os.path.splitext(fn)[0] + "_encoded.mp4")
            j = self._read_editor()
            j.src = src
            j.out = out
            cmd = j.build_cmd(ffmpeg)
            self.enqueue_render(
                fn, output_path=out, cmd=cmd,
                on_progress=lambda tid, line: self._on_task_progress(tid, line),
                on_complete=lambda tid, rc: self._on_task_complete(tid, rc, out),
            )
            count += 1
        if count:
            messagebox.showinfo("Queued", f"{count} files added to the render queue.")
        else:
            messagebox.showwarning(t("common.warning"), "No supported video files found.")

    def _read_editor(self) -> Job:
        j = Job()
        j.vcodec    = self.ed_vcodec_var.get()
        j.crf       = self.ed_crf_var.get()
        j.preset    = self.ed_preset_var.get()
        j.resolution= self.ed_res_var.get()
        j.fps       = self.ed_fps_var.get()
        j.acodec    = self.ed_acodec_var.get()
        j.abitrate  = self.ed_abitrate_var.get()
        j.extra_vf  = self.ed_evf_var.get()
        j.extra_args= self.ed_eargs_var.get()
        return j

    def _on_task_progress(self, task_id, line):
        if self._selected_task_id == task_id:
            try:
                self.console.insert(tk.END, line + "\n")
                self.console.see(tk.END)
            except Exception:
                pass

    def _on_task_complete(self, task_id, returncode, out_path):
        if returncode != 0:
            messagebox.showerror(
                "Encode Failed",
                f"Task finished with error code {returncode}.\n"
                f"Check the queue log for details.\nOutput: {out_path}")
