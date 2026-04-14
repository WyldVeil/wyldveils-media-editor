"""
tab_rotateflip.py  ─  Rotate & Flip
Rotate video 90°/180°/270° and/or flip horizontally/vertically.
Handles the most common problem in video editing: phone footage shot sideways.
Uses transpose/hflip/vflip filters. Stream-copy audio.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t
import sys as _sys
CREATE_NO_WINDOW = 0x08000000 if _sys.platform == "win32" else 0


class RotateFlipTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔄  " + t("tab.rotate_flip"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("rotate_flip.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=14)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Visual rotation picker ────────────────────────────────────────
        rot_lf = tk.LabelFrame(self, text=t("rotate_flip.rotation_section"), padx=20, pady=14)
        rot_lf.pack(fill="x", padx=20, pady=6)

        btn_row = tk.Frame(rot_lf); btn_row.pack(pady=4)
        self.rotate_var = tk.StringVar(value="0")

        rot_options = [
            (t("rotate_flip.rotate_flip_rotation_0"),     "0",    t("rotate_flip.2a2a2a")),
            (t("rotate_flip.rotate_flip_rotation_90_cw"), "90",   t("rotate_flip.1a3a5c")),
            (t("rotate_flip.rotate_flip_rotation_180"),   "180",  t("rotate_flip.1a3a5c")),
            (t("rotate_flip.rotate_flip_rotation_90_ccw"),"270",  t("rotate_flip.1a3a5c")),
        ]

        self._rot_buttons = {}
        for label, val, bg in rot_options:
            btn = tk.Button(
                btn_row, text=label,
                width=12, height=3,
                bg=bg, fg="white",
                font=(UI_FONT, 10),
                relief="raised",
                command=lambda v=val: self._select_rotation(v))
            btn.pack(side="left", padx=8)
            self._rot_buttons[val] = btn

        # ── Flip options ─────────────────────────────────────────────────
        flip_lf = tk.LabelFrame(self, text=t("rotate_flip.flip_section"), padx=20, pady=12)
        flip_lf.pack(fill="x", padx=20, pady=6)

        flip_row = tk.Frame(flip_lf); flip_row.pack()
        self.flip_h_var = tk.BooleanVar(value=False)
        self.flip_v_var = tk.BooleanVar(value=False)

        tk.Checkbutton(flip_row,
                       text=t("rotate_flip.flip_horizontal"),
                       variable=self.flip_h_var,
                       font=(UI_FONT, 11)).pack(side="left", padx=20)
        tk.Checkbutton(flip_row,
                       text=t("rotate_flip.flip_vertical"),
                       variable=self.flip_v_var,
                       font=(UI_FONT, 11)).pack(side="left", padx=20)

        # ── Preview of transformation ─────────────────────────────────────
        desc_lf = tk.LabelFrame(self, text=t("rotate_flip.resulting_transform_section"), padx=14, pady=8)
        desc_lf.pack(fill="x", padx=20, pady=4)
        self.desc_lbl = tk.Label(desc_lf,
                                  text=t("rotate_flip.no_transform"),
                                  fg=CLR["accent"], font=(MONO_FONT, 10))
        self.desc_lbl.pack(anchor="w")
        self.filter_lbl = tk.Label(desc_lf, text="", fg=CLR["fgdim"],
                                    font=(MONO_FONT, 9))
        self.filter_lbl.pack(anchor="w")

        # Update description live
        for var in (self.flip_h_var, self.flip_v_var):
            var.trace_add("write", lambda *_: self._update_desc())

        # ── Encode options ────────────────────────────────────────────────
        enc_lf = tk.LabelFrame(self, text=t("section.encode_options"), padx=14, pady=8)
        enc_lf.pack(fill="x", padx=20, pady=4)
        enc_row = tk.Frame(enc_lf); enc_row.pack(fill="x")

        self.copy_var = tk.BooleanVar(value=False)
        copy_cb = tk.Checkbutton(enc_row,
                                  text=t("rotate_flip.stream_copy_checkbox"),
                                  variable=self.copy_var,
                                  command=self._update_desc)
        copy_cb.pack(side="left")

        tk.Label(enc_row, text=t("rotate_flip.crf")).pack(side="left", padx=(20, 4))
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(enc_row, textvariable=self.crf_var, width=4, relief="flat").pack(side="left")
        tk.Label(enc_row, text=t("rotate_flip.preset")).pack(side="left", padx=(12, 4))
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(enc_row, textvariable=self.preset_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left")

        # ── Output & buttons ─────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=8)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row2 = tk.Frame(self); btn_row2.pack(pady=6)
        tk.Button(btn_row2, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=14, font=(UI_FONT, 10), command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row2, text=t("rotate_flip.apply_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=24, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._select_rotation("0")   # highlight default - must be last, needs all vars
        self._update_desc()

    # ─────────────────────────────────────────────────────────────────────
    def _select_rotation(self, val):
        self.rotate_var.set(val)
        for v, btn in self._rot_buttons.items():
            btn.config(bg="#4FC3F7" if v == val else "#2A2A2A",
                       fg="black" if v == val else "white",
                       relief="sunken" if v == val else "raised")
        self._update_desc()

    def _build_filter(self):
        """Return (vf_string, can_stream_copy)."""
        rot   = self.rotate_var.get()
        hflip = self.flip_h_var.get()
        vflip = self.flip_v_var.get()
        parts = []

        # Rotation via transpose (keeps metadata correct)
        if rot == "90":
            parts.append("transpose=1")    # 90° CW
        elif rot == "180":
            parts += ["hflip", "vflip"]    # 180° = hflip + vflip
        elif rot == "270":
            parts.append("transpose=2")    # 90° CCW

        if hflip:
            parts.append("hflip")
        if vflip:
            parts.append("vflip")

        # Can stream-copy only for pure flips / 180° (no reshape)
        can_copy = rot in ("0", "180") and not (rot == "0" and not hflip and not vflip)
        return ",".join(parts) if parts else None, can_copy

    def _update_desc(self, *_):
        rot   = self.rotate_var.get()
        hflip = self.flip_h_var.get()
        vflip = self.flip_v_var.get()
        parts = []
        if rot != "0":
            parts.append(f"Rotate {rot}°")
        if hflip:
            parts.append("Mirror horizontal")
        if vflip:
            parts.append("Flip vertical")

        desc = "  →  ".join(parts) if parts else "No transformation (pass-through)"
        vf, can_copy = self._build_filter()
        self.desc_lbl.config(text=desc)
        self.filter_lbl.config(
            text=f"-vf \"{vf}\"" if vf else "(no filter needed)",
            fg=CLR["fgdim"])

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_rotated.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv")])
        if p: self.out_var.set(p)

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("rotate_flip.no_file_title"), t("rotate_flip.no_file_message"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        vf, _ = self._build_filter()
        ffplay = get_binary_path("ffplay.exe")
        cmd = [ffplay, "-i", self.file_path,
               "-window_title", t("rotate_flip.rotate_flip_preview"), "-x", "800", "-autoexit"]
        if vf:
            cmd += ["-vf", vf]
        self.preview_proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out: return
        self.out_var.set(out)

        vf, can_copy = self._build_filter()
        if not vf:
            messagebox.showinfo(t("rotate_flip.nothing_to_do_title"), t("rotate_flip.nothing_to_do_message"))
            return

        ffmpeg = get_binary_path("ffmpeg.exe")
        use_copy = self.copy_var.get() and can_copy

        # Note: stream-copy (-c:v copy) cannot be used with -vf filters.
        # For "instant" flips we still need to re-encode, but ultrafast preset
        # makes it nearly as fast.  Always add movflags+faststart for seekability.
        if use_copy:
            # Ultrafast re-encode: near-lossless speed, fully seekable output
            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", vf,
                   t("dynamics.c_v"), "libx264", "-crf", "0", "-preset", "ultrafast",
                   t("dynamics.c_a"), "copy",
                   "-movflags", t("dynamics.faststart"),
                   "-g", "30",
                   out, "-y"]
        else:
            cmd = [ffmpeg, "-i", self.file_path,
                   "-vf", vf,
                   t("dynamics.c_v"), "libx264",
                   "-crf", self.crf_var.get(),
                   "-preset", self.preset_var.get(),
                   t("dynamics.c_a"), "copy",
                   "-movflags", t("dynamics.faststart"),
                   "-g", "30",
                   out, "-y"]

        self.log(self.console, f"Applying: {vf}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("rotate_flip.apply_button"))
