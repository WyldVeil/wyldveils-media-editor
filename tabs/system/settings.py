"""
tab_settings.py  ─  Quick Settings

A stripped-down panel for quick access to the most commonly adjusted
preferences without navigating to Advanced Settings.
Reads and writes the same settings.json as AdvancedSettingsTab via the
centralised core.settings module (no duplicated load/save logic).
"""
import tkinter as tk
from tkinter import ttk, filedialog

import os

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.settings import load_settings, save_settings
from core.i18n import t


class SettingsTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.settings = load_settings()
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="⚙  " + t("tab.settings"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("settings.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        lf = tk.LabelFrame(self, text=f"  {t('settings.encoding_defaults_section')}  ", padx=20, pady=14)
        lf.pack(fill="x", padx=24, pady=14)

        rows = [
            (t("settings.settings_default_crf_label"), "default_crf", "18", None),
            (t("settings.settings_default_preset_label"), "default_preset", "fast",
             ["ultrafast", "superfast", "veryfast", "faster", "fast",
              "medium", "slow", "slower", "veryslow"]),
            (t("settings.default_audio_label"), "default_audio_bitrate", "192k",
             ["96k", "128k", "192k", "256k", "320k"]),
        ]

        self._vars = {}
        for i, (label, key, default, choices) in enumerate(rows):
            tk.Label(lf, text=label, width=24, anchor="e").grid(
                row=i, column=0, pady=8)
            var = tk.StringVar(value=self.settings.get(key, default))
            self._vars[key] = var
            if choices:
                ttk.Combobox(lf, textvariable=var, values=choices,
                             state="readonly", width=16).grid(
                    row=i, column=1, sticky="w", padx=10)
            else:
                tk.Entry(lf, textvariable=var, width=8, relief="flat").grid(
                    row=i, column=1, sticky="w", padx=10)

        # Output folder
        of_row = tk.Frame(lf)
        of_row.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=8)
        tk.Label(of_row, text=t("settings.output_folder_label"),
                 width=24, anchor="e").pack(side="left")
        self._out_var = tk.StringVar(
            value=self.settings.get("default_output_folder", ""))
        tk.Entry(of_row, textvariable=self._out_var, width=44, relief="flat").pack(
            side="left", padx=8)
        tk.Button(
            of_row, text=t("btn.browse"),
            command=lambda: self._out_var.set(
                filedialog.askdirectory() or self._out_var.get()
            )
        ).pack(side="left")

        # Auto-open
        self._auto_open = tk.BooleanVar(
            value=self.settings.get("auto_open_output", False))
        tk.Checkbutton(
            lf,
            text=t("settings.auto_open_checkbox"),
            variable=self._auto_open,
        ).grid(row=len(rows) + 1, column=0, columnspan=3, sticky="w", pady=4)

        # Save button
        btn_f = tk.Frame(self)
        btn_f.pack(pady=16)
        tk.Button(
            btn_f, text=t("settings.save_settings_button"),
            bg=CLR["green"], fg="white",
            font=(UI_FONT, 11, "bold"),
            command=self._save,
        ).pack(side="left", padx=8)
        self._status = tk.Label(btn_f, text="", fg=CLR["green"])
        self._status.pack(side="left", padx=8)

        tk.Label(
            self,
            text=t("settings.subtitle"),
            fg=CLR["fgdim"], font=(UI_FONT, 9),
        ).pack(pady=8)

    def _save(self):
        for key, var in self._vars.items():
            self.settings[key] = var.get()
        self.settings["default_output_folder"] = self._out_var.get()
        self.settings["auto_open_output"]       = self._auto_open.get()

        if save_settings(self.settings):
            self._status.config(text=f"✅  {t('settings.saved_confirmation')}", fg=CLR["green"])
        else:
            self._status.config(text=f"❌  {t('settings.save_failed')}", fg=CLR["red"])
