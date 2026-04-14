"""
tab_batchjoiner.py  ─  Batch Joiner
Drag-and-drop queue of video files, optionally re-encode to a uniform
spec, then concatenate them all in order into a single output file.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, get_video_duration, CREATE_NO_WINDOW
from core.i18n import t


class BatchJoinerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_paths = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="📎  " + t("tab.batch_joiner"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("batch_joiner.desc"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File list
        lf = tk.LabelFrame(self, text=t("batch_joiner.sect_video_queue"),
                           padx=10, pady=6)
        lf.pack(fill="both", expand=True, padx=20, pady=8)

        self.listbox = tk.Listbox(lf, selectmode="single", font=(MONO_FONT, 10), relief="flat", bd=1,
                                  height=14, activestyle="dotbox",
                                  bg=CLR["bg"], fg=CLR["fg"],
                                  selectbackground=CLR["accent"], selectforeground="black")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Buttons row
        btn_f = tk.Frame(self)
        btn_f.pack(pady=5)
        for txt, cmd, bg in [
            (t("batch_joiner.btn_add_files"),   self._add_files,   "#3A3A3A"),
            (t("batch_joiner.btn_add_folder"),  self._add_folder,  "#3A3A3A"),
            (t("batch_joiner.btn_move_up"),     self._move_up,     "#3A3A3A"),
            (t("batch_joiner.btn_move_down"),   self._move_down,   "#3A3A3A"),
            (t("batch_joiner.btn_remove"),      self._remove_sel,  "#3A3A3A"),
            (t("batch_joiner.btn_clear_all"),   self._clear,       "#3A3A3A"),
        ]:
            tk.Button(btn_f, text=txt, bg=bg, fg=CLR["fg"], width=13,
                      command=cmd).pack(side="left", padx=4)

        # Options
        opt_lf = tk.LabelFrame(self, text=t("section.output_options"), padx=15, pady=8)
        opt_lf.pack(fill="x", padx=20, pady=5)

        # Row 1
        r1 = tk.Frame(opt_lf); r1.pack(fill="x", pady=3)
        self.reencode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r1, text=t("batch_joiner.opt_reencode"),
                       variable=self.reencode_var,
                       command=self._toggle_encode_opts).pack(side="left")

        # Row 2 - encode options (shown/hidden)
        self.enc_frame = tk.Frame(opt_lf)
        tk.Label(self.enc_frame, text=t("common.resolution")).pack(side="left")
        self.res_var = tk.StringVar(value="1920x1080")
        ttk.Combobox(self.enc_frame, textvariable=self.res_var, width=12,
                     values=["3840x2160", "2560x1440", "1920x1080", "1280x720",
                              "854x480", t("batch_joiner.batch_joiner_keep_highest")], state="readonly").pack(side="left", padx=4)
        tk.Label(self.enc_frame, text=t("batch_joiner.lbl_fps")).pack(side="left")
        self.fps_var = tk.StringVar(value="30")
        ttk.Combobox(self.enc_frame, textvariable=self.fps_var, width=6,
                     values=["24", "25", "30", "50", "60", t("batch_joiner.batch_joiner_keep_highest")], state="readonly").pack(side="left", padx=4)
        tk.Label(self.enc_frame, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(self.enc_frame, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(self.enc_frame, text=t("batch_joiner.lbl_audio")).pack(side="left")
        self.audio_var = tk.StringVar(value="192k")
        ttk.Combobox(self.enc_frame, textvariable=self.audio_var, width=7,
                     values=["96k", "128k", "192k", "256k", "320k"], state="readonly").pack(side="left", padx=4)

        # Output
        out_row = tk.Frame(self); out_row.pack(pady=5)
        tk.Label(out_row, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(out_row, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(out_row, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        # Render
        self.btn_render = tk.Button(
            self, text=t("batch_joiner.btn_join"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=30, command=self._render)
        self.btn_render.pack(pady=8)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _toggle_encode_opts(self):
        if self.reencode_var.get():
            self.enc_frame.pack(fill="x", pady=4)
        else:
            self.enc_frame.pack_forget()

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.flv"), ("All", t("ducker.item_2"))])
        for p in paths:
            if p not in self.file_paths:
                self.file_paths.append(p)
                self.listbox.insert(tk.END, f"  {os.path.basename(p)}")

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
        for f in sorted(os.listdir(folder)):
            if os.path.splitext(f)[1].lower() in exts:
                full = os.path.join(folder, f)
                if full not in self.file_paths:
                    self.file_paths.append(full)
                    self.listbox.insert(tk.END, f"  {f}")

    def _move_up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        self.file_paths[i], self.file_paths[i-1] = self.file_paths[i-1], self.file_paths[i]
        txt = self.listbox.get(i)
        prev = self.listbox.get(i-1)
        self.listbox.delete(i-1, i)
        self.listbox.insert(i-1, txt)
        self.listbox.insert(i, prev)
        self.listbox.selection_set(i-1)

    def _move_down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= self.listbox.size() - 1:
            return
        i = sel[0]
        self.file_paths[i], self.file_paths[i+1] = self.file_paths[i+1], self.file_paths[i]
        txt = self.listbox.get(i)
        nxt = self.listbox.get(i+1)
        self.listbox.delete(i, i+1)
        self.listbox.insert(i, nxt)
        self.listbox.insert(i+1, txt)
        self.listbox.selection_set(i+1)

    def _remove_sel(self):
        sel = self.listbox.curselection()
        if sel:
            i = sel[0]
            self.file_paths.pop(i)
            self.listbox.delete(i)

    def _clear(self):
        self.file_paths.clear()
        self.listbox.delete(0, tk.END)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if len(self.file_paths) < 2:
            messagebox.showwarning(t("common.warning"), t("batch_joiner.msg_too_few_files"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)
        ffmpeg = get_binary_path("ffmpeg.exe")

        if self.reencode_var.get():
            self._render_reencode(out, ffmpeg)
        else:
            self._render_copy(out, ffmpeg)

    def _render_copy(self, out, ffmpeg):
        self.log(self.console, t("log.batch_joiner.stream_copy_join_fast_requires_matching_specs"))
        tmp_dir = tempfile.mkdtemp()
        list_path = os.path.join(tmp_dir, "list.txt")
        with open(list_path, "w") as f:
            for p in self.file_paths:
                # Use forward slashes for FFmpeg compatibility
                f.write(f"file '{p.replace(chr(92), '/')}'\n")

        self.log(self.console, f"Joining {len(self.file_paths)} files (stream-copy)…")
        cmd = [ffmpeg, "-f", "concat", "-safe", "0",
               "-i", list_path, "-c", "copy",
               "-movflags", t("dynamics.faststart"),
               out, "-y"]

        def done(rc):
            self.show_result(rc, out)
            try: os.remove(list_path); os.rmdir(tmp_dir)
            except Exception: pass

        self.run_ffmpeg(cmd, self.console, on_done=done,
                        btn=self.btn_render, btn_label=t("batch_joiner.btn_join"))

    def _render_reencode(self, out, ffmpeg):
        self.log(self.console, t("log.batch_joiner.re_encode_join"))
        res = self.res_var.get()
        fps = self.fps_var.get()
        crf = self.crf_var.get()
        abr = self.audio_var.get()
        tmp_dir = tempfile.mkdtemp()
        paths = self.file_paths[:]

        def _work():
            tmp_files = []
            for i, src in enumerate(paths):
                tmp = os.path.join(tmp_dir, f"enc_{i:04d}.mp4")
                tmp_files.append(tmp)
                if res == "Keep Highest":
                    vf = ""
                else:
                    # Convert "1920x1080" -> "1920:1080" for FFmpeg scale filter
                    res_ffmpeg = res.replace("x", ":")
                    res_w, res_h = res.split("x")
                    vf = (f"scale={res_ffmpeg}:force_original_aspect_ratio=decrease,"
                          f"pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,"
                          f"setpts=PTS-STARTPTS")
                vf_fps = f"fps={fps}" if fps != "Keep Highest" else ""
                filters = ",".join(filter(None, [vf, vf_fps]))

                cmd = [ffmpeg, "-i", src]
                if filters:
                    cmd += ["-vf", filters]
                cmd += ["-c:v", "libx264", "-crf", crf, "-preset", "fast",
                        "-c:a", "aac", "-b:a", abr, tmp, "-y"]

                self.log(self.console, f"[{i+1}/{len(paths)}] Encoding {os.path.basename(src)}…")
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=CREATE_NO_WINDOW)
                if r.returncode != 0:
                    self.log(self.console, f"  ⚠ Encode error segment {i+1}:")
                    self.log(self.console, r.stderr[-400:])

            list_path = os.path.join(tmp_dir, "list.txt")
            with open(list_path, "w") as f:
                for p in tmp_files:
                    f.write(f"file '{p}'\n")

            cmd_cat = [ffmpeg, "-f", "concat", "-safe", "0",
                       "-i", list_path, "-c", "copy", out, "-y"]
            self.log(self.console, t("log.batch_joiner.concatenating_encoded_segments"))
            proc = subprocess.run(cmd_cat, capture_output=True, creationflags=CREATE_NO_WINDOW)

            for p in tmp_files:
                try: os.remove(p)
                except Exception: pass
            try: os.rmdir(tmp_dir)
            except Exception: pass

            self.after(0, lambda: self.show_result(proc.returncode, out))

        self.run_in_thread(_work)
