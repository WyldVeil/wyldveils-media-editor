"""
tab_sharpen.py  ─  Sharpen
Two sharpening algorithms:
  • Unsharp Mask  - the industry standard, fine-grained luma/chroma control
  • Lapsharp       - edge-detection based, great for detail recovery after downscale

Strength presets, live preview.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


# (label, luma_size, luma_amount, chroma_size, chroma_amount)
UNSHARP_PRESETS = {
    t("sharpen.subtle_very_light_touch"):              (3, 0.3, 3, 0.0),
    t("sharpen.light_after_downscale_soft_footage"):(5, 0.6, 5, 0.0),
    t("sharpen.medium_general_use"):                   (5, 1.0, 5, 0.0),
    t("sharpen.strong_detail_recovery"):               (7, 1.5, 7, 0.0),
    t("sharpen.aggressive_heavily_blurred_input"):     (7, 2.5, 7, 0.3),
    "Custom":                                   None,
}


class SharpenTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path    = ""
        self.preview_proc = None
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🔪  " + t("tab.sharpen"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("sharpen.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=10)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=60, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # ── Algorithm choice ─────────────────────────────────────────────
        algo_lf = tk.LabelFrame(self, text=t("section.algorithm"), padx=16, pady=10)
        algo_lf.pack(fill="x", padx=20, pady=6)

        self.algo_var = tk.StringVar(value="unsharp")
        for val, label, desc in [
            ("unsharp",  t("sharpen.unsharp_option"),
             t("sharpen.unsharp_hint")),
            ("lapsharp", t("sharpen.lapsharp_option"),
             t("sharpen.lapsharp_hint")),
        ]:
            col = tk.Frame(algo_lf); col.pack(side="left", padx=24)
            tk.Radiobutton(col, text=label, variable=self.algo_var, value=val,
                           font=(UI_FONT, 11, "bold"),
                           command=self._on_algo_change).pack(anchor="w")
            tk.Label(col, text=desc, fg=CLR["fgdim"], font=(UI_FONT, 8),
                     wraplength=280, justify="left").pack(anchor="w")

        # ── Unsharp Mask panel ────────────────────────────────────────────
        self.unsharp_lf = tk.LabelFrame(self, text=f"  {t('sharpen.unsharp_controls_section')}  ",
                                         padx=16, pady=10)
        self.unsharp_lf.pack(fill="x", padx=20, pady=4)

        # Preset
        preset_row = tk.Frame(self.unsharp_lf); preset_row.pack(fill="x", pady=(0, 8))
        tk.Label(preset_row, text=t("sharpen.preset_label"), font=(UI_FONT, 9, "bold")).pack(side="left")
        self.um_preset_var = tk.StringVar(value=list(UNSHARP_PRESETS.keys())[1])
        preset_cb = ttk.Combobox(preset_row, textvariable=self.um_preset_var,
                                  values=list(UNSHARP_PRESETS.keys()),
                                  state="readonly", width=38)
        preset_cb.pack(side="left", padx=8)
        preset_cb.bind("<<ComboboxSelected>>", self._apply_um_preset)

        um_sliders = [
            (t("sharpen.sharpen_luma_matrix_label"),   "um_ls",  3, 23, 5,  2, t("sharpen.odd_numbers_only_3_23_larger_wider_blur_radius")),
            (t("sharpen.sharpen_luma_amount_label"),   "um_la", -1.5, 3.0, 1.0, 0.1, t("sharpen.positive_sharpen_negative_blur")),
            (t("sharpen.sharpen_chroma_matrix_label"), "um_cs",  3, 23, 5,  2, t("sharpen.colour_channel_blur_radius")),
            (t("sharpen.sharpen_chroma_amount_label"), "um_ca", -1.5, 3.0, 0.0, 0.1, t("sharpen.usually_0_to_avoid_colour_fringing")),
        ]

        self._um_vars = {}
        self._um_lbls = {}
        for label, attr, lo, hi, default, res, tip in um_sliders:
            row = tk.Frame(self.unsharp_lf); row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=20, anchor="e").pack(side="left")
            var = tk.DoubleVar(value=default)
            self._um_vars[attr] = var
            sl = tk.Scale(row, variable=var, from_=lo, to=hi,
                          resolution=res, orient="horizontal", length=240,
                          command=lambda v, a=attr: self._on_um_slider(a))
            sl.pack(side="left", padx=6)
            lbl = tk.Label(row, text=str(default), width=5, fg=CLR["accent"])
            lbl.pack(side="left")
            self._um_lbls[attr] = lbl
            tk.Label(row, text=tip, fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(side="left", padx=6)

        # ── Lapsharp panel ────────────────────────────────────────────────
        self.lapsharp_lf = tk.LabelFrame(self, text=f"  {t('sharpen.lapsharp_controls_section')}  ",
                                          padx=16, pady=10)

        ls_row = tk.Frame(self.lapsharp_lf); ls_row.pack(fill="x", pady=4)
        tk.Label(ls_row, text=t("sharpen.strength_label"), width=10, anchor="e").pack(side="left")
        self.ls_strength_var = tk.DoubleVar(value=0.2)
        tk.Scale(ls_row, variable=self.ls_strength_var,
                 from_=0.01, to=1.0, resolution=0.01,
                 orient="horizontal", length=280,
                 command=lambda v: self._update_filter_lbl()).pack(side="left", padx=6)
        tk.Label(self.lapsharp_lf,
                 text=t("sharpen.0_1_0_2_subtle_0_4_0_6_strong_0_7_aggressive"),
                 fg=CLR["fgdim"], font=(UI_FONT, 8)).pack(anchor="w")

        # Filter display
        self.filter_lbl = tk.Label(self, text="", fg=CLR["fgdim"],
                                    font=(MONO_FONT, 9))
        self.filter_lbl.pack(anchor="w", padx=22, pady=(2, 0))

        # ── Encode options ────────────────────────────────────────────────
        enc_f = tk.Frame(self); enc_f.pack(padx=22, pady=4, fill="x")
        tk.Label(enc_f, text=t("common.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(enc_f, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(enc_f, text=t("rotate_flip.preset")).pack(side="left")
        self.preset_enc_var = tk.StringVar(value="medium")
        ttk.Combobox(enc_f, textvariable=self.preset_enc_var,
                     values=["ultrafast","fast","medium","slow"],
                     state="readonly", width=10).pack(side="left", padx=4)

        # ── Output ────────────────────────────────────────────────────────
        of = tk.Frame(self); of.pack(pady=6)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=62, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        btn_row = tk.Frame(self); btn_row.pack(pady=8)
        tk.Button(btn_row, text=t("rotate_flip.preview_button"), bg=CLR["accent"], fg="white",
                  width=14, command=self._preview).pack(side="left", padx=8)
        self.btn_render = tk.Button(
            btn_row, text=t("sharpen.apply_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, width=22, command=self._render)
        self.btn_render.pack(side="left", padx=8)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=5)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        self._on_algo_change()
        self._update_filter_lbl()

    # ─────────────────────────────────────────────────────────────────────
    def _on_algo_change(self):
        if self.algo_var.get() == "unsharp":
            self.lapsharp_lf.pack_forget()
            self.unsharp_lf.pack(fill="x", padx=20, pady=4)
        else:
            self.unsharp_lf.pack_forget()
            self.lapsharp_lf.pack(fill="x", padx=20, pady=4)
        self._update_filter_lbl()

    def _on_um_slider(self, attr):
        self._um_lbls[attr].config(text=f"{self._um_vars[attr].get():.2f}")
        # Snap matrix sizes to odd numbers
        if attr in ("um_ls", "um_cs"):
            v = int(self._um_vars[attr].get())
            if v % 2 == 0:
                v = max(3, v + 1)
                self._um_vars[attr].set(v)
        self._update_filter_lbl()

    def _apply_um_preset(self, *_):
        p = UNSHARP_PRESETS.get(self.um_preset_var.get())
        if not p: return
        ls, la, cs, ca = p
        self._um_vars["um_ls"].set(ls)
        self._um_vars["um_la"].set(la)
        self._um_vars["um_cs"].set(cs)
        self._um_vars["um_ca"].set(ca)
        for a in self._um_lbls:
            self._um_lbls[a].config(text=f"{self._um_vars[a].get():.2f}")
        self._update_filter_lbl()

    def _build_filter(self):
        if self.algo_var.get() == "unsharp":
            ls = int(self._um_vars["um_ls"].get())
            la = self._um_vars["um_la"].get()
            cs = int(self._um_vars["um_cs"].get())
            ca = self._um_vars["um_ca"].get()
            # Ensure odd
            ls = ls if ls % 2 else ls + 1
            cs = cs if cs % 2 else cs + 1
            return f"unsharp={ls}:{ls}:{la:.2f}:{cs}:{cs}:{ca:.2f}"
        else:
            strength = self.ls_strength_var.get()
            return f"lapsharp=strength={strength:.3f}"

    def _update_filter_lbl(self):
        self.filter_lbl.config(text=f"Filter:  {self._build_filter()}")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(base + "_sharpened.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p: self.out_var.set(p)

    def _preview(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass
        ffplay = get_binary_path("ffplay.exe")
        vf = self._build_filter()
        cmd = [ffplay, "-i", self.file_path, "-vf", vf,
               "-window_title", t("sharpen.sharpen_preview"), "-x", "800", "-autoexit"]
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

        ffmpeg = get_binary_path("ffmpeg.exe")
        vf = self._build_filter()
        cmd = [ffmpeg, "-i", self.file_path, "-vf", vf,
               t("dynamics.c_v"), "libx264", "-crf", self.crf_var.get(),
               "-preset", self.preset_enc_var.get(),
               t("dynamics.c_a"), "copy", "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, f"Filter: {vf}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("sharpen.apply_button"))
