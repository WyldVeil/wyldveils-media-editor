"""
tab_proxygen.py  ─  Proxy Generator
Creates lightweight proxy files for smooth editing on slow machines.
Generates DNxHD, ProRes Proxy, or simple H.264 low-res copies.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


PROXY_PRESETS = {
    t("proxy.h_264_proxy_1_4_res_crf_28"):     {"scale": 0.25, "codec": "libx264",     "extra": ["-crf", "28", "-preset", "ultrafast"]},
    "H.264 Half-res (CRF 23)":            {"scale": 0.50, "codec": "libx264",     "extra": ["-crf", "23", "-preset", "ultrafast"]},
    "H.265 Proxy (1/4 res, CRF 30)":     {"scale": 0.25, "codec": "libx265",     "extra": ["-crf", "30", "-preset", "ultrafast"]},
    "DNxHD 36 (Avid proxy)":             {"scale": 0.50, "codec": "dnxhd",       "extra": ["-vb", "36M", "-pix_fmt", "yuv422p"]},
    "ProRes Proxy (Apple)":               {"scale": 0.50, "codec": "prores_ks",   "extra": ["-profile:v", "0"]},
    "MJPEG Draft (1/4 res)":              {"scale": 0.25, "codec": "mjpeg",       "extra": ["-q:v", "5"]},
}


class ProxyGenTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_paths = []
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="⚙  " + t("tab.proxy_generator"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("proxy.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # File list
        lf = tk.LabelFrame(self, text=f"  {t('section.input_files')}  ", padx=10, pady=8)
        lf.pack(fill="both", expand=True, padx=20, pady=8)
        self.listbox = tk.Listbox(lf, height=8, bg=CLR["bg"], fg=CLR["fg"],
                                   font=(MONO_FONT, 10), selectbackground=CLR["accent"])
        sb = ttk.Scrollbar(lf, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_f = tk.Frame(self); btn_f.pack(pady=4)
        tk.Button(btn_f, text=t("converter.btn_add_files"),  bg=CLR["panel"], fg=CLR["fg"], command=self._add, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(btn_f, text=t("encode_queue.add_folder_button"),   bg=CLR["panel"], fg=CLR["fg"], command=self._add_folder, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(btn_f, text=t("converter.btn_remove"),       bg=CLR["panel"], fg=CLR["fg"], command=self._remove, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(btn_f, text=t("converter.btn_clear"),        bg=CLR["panel"], fg=CLR["fg"], command=self._clear, cursor="hand2", relief="flat").pack(side="left", padx=4)

        # Options
        opts = tk.LabelFrame(self, text=t("proxy.proxy_options_section"), padx=15, pady=8)
        opts.pack(fill="x", padx=20, pady=6)
        r0 = tk.Frame(opts); r0.pack(fill="x", pady=4)
        tk.Label(r0, text=t("proxy.preset_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.preset_var = tk.StringVar(value=list(PROXY_PRESETS.keys())[0])
        ttk.Combobox(r0, textvariable=self.preset_var, values=list(PROXY_PRESETS.keys()),
                     state="readonly", width=40).pack(side="left", padx=8)

        r1 = tk.Frame(opts); r1.pack(fill="x", pady=4)
        tk.Label(r1, text=t("common.output_folder")).pack(side="left")
        self.out_dir_var = tk.StringVar()
        tk.Entry(r1, textvariable=self.out_dir_var, width=50, relief="flat").pack(side="left", padx=6)
        tk.Button(r1, text=t("btn.browse"), command=self._browse_dir, cursor="hand2", relief="flat").pack(side="left")
        tk.Label(r1, text=t("proxy.blank_next_to_originals"), fg=CLR["fgdim"]).pack(side="left", padx=6)

        r2 = tk.Frame(opts); r2.pack(fill="x", pady=4)
        tk.Label(r2, text=t("proxy.suffix_label")).pack(side="left")
        self.suffix_var = tk.StringVar(value="_PROXY")
        tk.Entry(r2, textvariable=self.suffix_var, width=12, relief="flat").pack(side="left", padx=4)
        self.audio_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text=t("proxy.audio_checkbox"), variable=self.audio_var).pack(side="left", padx=20)

        self.btn_render = tk.Button(
            self, text=t("proxy.render_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["orange"], fg="white", height=2, width=30, command=self._render)
        self.btn_render.pack(pady=10)

        self.prog_lbl = tk.Label(self, text="", fg=CLR["fgdim"])
        self.prog_lbl.pack()

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _add(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        for p in paths:
            if p not in self.file_paths:
                self.file_paths.append(p)
                self.listbox.insert(tk.END, f"  {os.path.basename(p)}")

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if not folder: return
        exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v"}
        for f in sorted(os.listdir(folder)):
            if os.path.splitext(f)[1].lower() in exts:
                full = os.path.join(folder, f)
                if full not in self.file_paths:
                    self.file_paths.append(full)
                    self.listbox.insert(tk.END, f"  {f}")

    def _remove(self):
        sel = self.listbox.curselection()
        if sel:
            self.file_paths.pop(sel[0])
            self.listbox.delete(sel[0])

    def _clear(self):
        self.file_paths.clear()
        self.listbox.delete(0, tk.END)

    def _browse_dir(self):
        p = filedialog.askdirectory()
        if p: self.out_dir_var.set(p)

    def _render(self):
        if not self.file_paths:
            messagebox.showwarning(t("common.warning"), "Add source files first.")
            return
        preset = PROXY_PRESETS[self.preset_var.get()]
        scale  = preset["scale"]
        codec  = preset["codec"]
        extra  = preset["extra"]
        suffix = self.suffix_var.get()
        out_dir = self.out_dir_var.get().strip()
        paths  = self.file_paths[:]

        def _work():
            for i, src in enumerate(paths):
                base = os.path.splitext(os.path.basename(src))[0]
                ext  = ".mov" if codec in ("prores_ks", "dnxhd") else ".mp4"
                dst_dir = out_dir if out_dir else os.path.dirname(src)
                os.makedirs(dst_dir, exist_ok=True)
                out = os.path.join(dst_dir, f"{base}{suffix}{ext}")

                ffmpeg = get_binary_path("ffmpeg.exe")
                vf = f"scale=iw*{scale}:ih*{scale}"
                cmd = [ffmpeg, "-i", src, "-vf", vf, t("dynamics.c_v"), codec] + extra
                if self.audio_var.get():
                    cmd += ["-c:a", "aac", "-b:a", "96k"]
                else:
                    cmd += ["-an"]
                cmd += ["-movflags", "+faststart", out, "-y"]

                self.after(0, lambda i=i, n=len(paths): self.prog_lbl.config(
                    text=f"Processing {i+1} / {n}…"))
                self.log(self.console, f"[{i+1}/{len(paths)}] {os.path.basename(src)} → {os.path.basename(out)}")
                subprocess.run(cmd, capture_output=True,
                               creationflags=CREATE_NO_WINDOW)

            self.after(0, lambda: self.prog_lbl.config(text=f"✅ Done! {len(paths)} proxies created."))
            self.after(0, lambda: messagebox.showinfo("Done", f"{len(paths)} proxy file(s) generated."))

        self.run_in_thread(_work)
