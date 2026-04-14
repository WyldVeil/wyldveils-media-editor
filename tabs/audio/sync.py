"""
tab_audiosync.py  ─  Audio Sync Shifter
Shift audio forwards or backwards relative to the video track.
Handles positive (delay audio) and negative (advance audio) offsets.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t


class AudioSyncTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="⏱  " + t("tab.audio_sync_shifter"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("sync.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # Source
        sf = tk.Frame(self); sf.pack(pady=14)
        tk.Label(sf, text=t("common.source_video"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.src_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.src_var, width=58, relief="flat").pack(side="left", padx=8)
        tk.Button(sf, text=t("btn.browse"), command=self._browse, cursor="hand2", relief="flat").pack(side="left")

        # Controls
        ctrl = tk.LabelFrame(self, text=t("sync.adjustment_section"), padx=20, pady=14)
        ctrl.pack(fill="x", padx=20, pady=8)

        tk.Label(ctrl, text=t("sync.offset_label"), font=(UI_FONT, 12, "bold")).grid(row=0, column=0, sticky="w")
        self.offset_var = tk.StringVar(value="0.000")
        offset_entry = tk.Entry(ctrl, textvariable=self.offset_var, width=10,
                                font=(MONO_FONT, 14), justify="center")
        offset_entry.grid(row=0, column=1, padx=10)

        tk.Label(ctrl, text=t("sync.offset_hint"),
                 fg=CLR["fgdim"]).grid(row=0, column=2, sticky="w")

        # Quick buttons
        btn_row = tk.Frame(ctrl); btn_row.grid(row=1, column=0, columnspan=3, pady=8)
        for delta, label in [(-1.0, "-1.0s"), (-0.5, "-0.5s"), (-0.1, "-100ms"),
                              (-0.033, "-33ms"), (0.033, "+33ms"), (0.1, "+100ms"),
                              (0.5, "+0.5s"), (1.0, "+1.0s")]:
            tk.Button(btn_row, text=label, width=7, bg="#333", fg=CLR["fg"],
                      command=lambda d=delta: self._nudge(d)).pack(side="left", padx=2)

        # Audio track selection
        r2 = tk.Frame(ctrl); r2.grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        tk.Label(r2, text=t("sync.audio_track_label")).pack(side="left")
        self.track_var = tk.StringVar(value="0")
        tk.Entry(r2, textvariable=self.track_var, width=3, relief="flat").pack(side="left", padx=4)
        tk.Label(r2, text=t("sync.track_hint"), fg=CLR["fgdim"]).pack(side="left")

        self.method_var = tk.StringVar(value=t("sync.method_itsoffset"))
        tk.Label(r2, text=f"   {t('sync.method_label')}").pack(side="left", padx=(20, 4))
        ttk.Combobox(r2, textvariable=self.method_var,
                     values=[t("sync.sync_sync_method_itsoffset"),
                              t("sync.sync_sync_method_adelay")],
                     state="readonly", width=32).pack(side="left")

        # Output
        of = tk.Frame(self); of.pack(pady=5)
        tk.Label(of, text=t("common.output_file"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=65, relief="flat").pack(side="left", padx=8)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            self, text=t("sync.apply_button"), font=(UI_FONT, 12, "bold"),
            bg=CLR["green"], fg="white", height=2, width=28, command=self._render)
        self.btn_render.pack(pady=12)

        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=4)
        self.console, csb = self.make_console(cf, height=7)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    def _nudge(self, delta):
        try:
            v = float(self.offset_var.get()) + delta
            self.offset_var.set(f"{v:.3f}")
        except ValueError:
            self.offset_var.set(f"{delta:.3f}")

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("All", t("ducker.item_2"))])
        if p:
            self.file_path = p
            self.src_var.set(p)
            base = os.path.splitext(p)[0]
            self.out_var.set(f"{base}_synced.mp4")

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4", "*.mp4")])
        if p:
            self.out_var.set(p)

    def _render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("common.no_input"))
            return
        if not os.path.isfile(self.file_path):
            messagebox.showwarning(t("common.warning"), f"Could not find:\n{self.file_path}")
            return
        try:
            offset = float(self.offset_var.get())
        except ValueError:
            messagebox.showwarning(t("sync.bad_input_title"), t("sync.bad_input_message"))
            return

        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        self.out_var.set(out)
        out_dir = os.path.dirname(out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        ffmpeg = get_binary_path("ffmpeg.exe")

        if t("sync.method_itsoffset") in self.method_var.get():
            if offset >= 0:
                # Delay audio: offset the audio input
                cmd = [ffmpeg, "-i", self.file_path,
                       "-itsoffset", str(offset), "-i", self.file_path,
                       "-map", t("sync.1_v_0"), "-map", t("sync.0_a_0"),
                       "-c", "copy", "-shortest", "-movflags", t("dynamics.faststart"), out, "-y"]
            else:
                # Advance audio: offset the video
                cmd = [ffmpeg,
                       "-itsoffset", str(-offset), "-i", self.file_path,
                       "-i", self.file_path,
                       "-map", t("muter.0_v_0"), "-map", t("sync.1_a_0"),
                       "-c", "copy", "-shortest", "-movflags", t("dynamics.faststart"), out, "-y"]
        else:
            # adelay filter - positive ms only; advance done by trim
            ms = int(offset * 1000)
            if ms >= 0:
                af = f"adelay={ms}|{ms}"
                cmd = [ffmpeg, "-i", self.file_path, "-af", af,
                       t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k", "-movflags", t("dynamics.faststart"), out, "-y"]
            else:
                # trim audio
                af = f"atrim=start={-offset}"
                cmd = [ffmpeg, "-i", self.file_path, "-af", af,
                       t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "256k",
                       "-shortest", "-movflags", t("dynamics.faststart"), out, "-y"]

        self.log(self.console, f"Shifting audio by {offset:+.3f}s")
        self.run_ffmpeg(cmd, self.console, on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label=t("sync.apply_button"))
