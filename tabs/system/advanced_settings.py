"""
tab_advancedsettings.py  ─  Advanced Settings

System information, FFmpeg management, app preferences, skins, and
developer tools.  All settings I/O is delegated to core.settings -
no duplicated load/save logic.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import subprocess
import threading
import os
import platform
import json
import math

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.skins import (SKINS, save_skin_name, apply_skin, load_skin_name,
                        set_star_speed, get_star_speed,
                        set_star_count, get_star_count,
                        get_skin, save_custom_color, _CUSTOM_DEFAULTS)
from core.hardware import (
    get_binary_path, get_local_version, get_latest_online_version,
    download_and_extract_ffmpeg, detect_gpu, CREATE_NO_WINDOW,
    open_in_explorer,
)
from core.settings import load_settings, save_settings
from core.i18n import SUPPORTED_LANGUAGES, LANGUAGE_NAMES, get_language, set_language
from core.i18n import t


class AdvancedSettingsTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.settings    = load_settings()
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚙  " + t("tab.advanced_settings"),
                 font=(UI_FONT, 16, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(
            side="left", padx=20, pady=12)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=15, pady=10)

        self._build_ffmpeg_tab(nb)
        self._build_defaults_tab(nb)
        self._build_networking_tab(nb)
        self._build_skins_tab(nb)
        self._build_language_tab(nb)
        self._build_system_tab(nb)
        self._build_dev_tab(nb)

    # ─── FFmpeg Management ────────────────────────────────────────────────────
    def _build_ffmpeg_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  FFmpeg  ")

        tk.Label(f, text=t("adv.ffmpeg_management"),
                 font=(UI_FONT, 12, "bold")).pack(pady=(20, 10))

        ver_f = tk.LabelFrame(f, text=f"  {t('advanced_settings.version_status_section')}  ", padx=15, pady=10)
        ver_f.pack(fill="x", padx=20, pady=8)

        self.local_ver_lbl  = tk.Label(ver_f, text=t("advanced_settings.local_checking"),
                                       font=(MONO_FONT, 11))
        self.local_ver_lbl.pack(anchor="w")
        self.online_ver_lbl = tk.Label(ver_f, text=t("advanced_settings.online_checking"),
                                       font=(MONO_FONT, 11))
        self.online_ver_lbl.pack(anchor="w")

        btn_row = tk.Frame(ver_f)
        btn_row.pack(anchor="w", pady=8)
        tk.Button(btn_row, text=t("advanced_settings.check_versions"),
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=lambda: threading.Thread(
                      target=self._check_versions, daemon=True).start()
                  ).pack(side="left", padx=4)
        tk.Button(btn_row, text=t("advanced_settings.download_update_ffmpeg"),
                  bg=CLR["green"], fg="white",
                  command=self._download_ffmpeg).pack(side="left", padx=4)
        tk.Button(btn_row, text=t("advanced_settings.open_bin_folder"),
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=self._open_bin).pack(side="left", padx=4)

        cust_f = tk.LabelFrame(f, text=f"  {t('advanced_settings.custom_ffmpeg_section')}  ",
                               padx=15, pady=10)
        cust_f.pack(fill="x", padx=20, pady=5)
        tk.Label(cust_f,
                 text=t("adv.ffmpeg_path_label"),
                 fg=CLR["fgdim"]).pack(anchor="w")
        path_row = tk.Frame(cust_f)
        path_row.pack(fill="x", pady=4)
        self.ffmpeg_path_var = tk.StringVar(
            value=self.settings.get("ffmpeg_path_override", ""))
        tk.Entry(path_row, textvariable=self.ffmpeg_path_var,
                 width=60).pack(side="left")
        tk.Button(path_row, text=t("btn.browse"),
                  command=lambda: self._browse_binary(
                      "ffmpeg_path_override", self.ffmpeg_path_var)
                  ).pack(side="left", padx=6)

        self.upd_console = scrolledtext.ScrolledText(
            f, height=8, bg=CLR["console_bg"], fg="#00FF88", font=(MONO_FONT, 9))
        self.upd_console.pack(fill="both", expand=True, padx=20, pady=8)

        threading.Thread(target=self._check_versions, daemon=True).start()

    def _check_versions(self):
        local  = get_local_version()
        online = get_latest_online_version()
        status = ("✅ Up to date"
                  if local == online
                  else "⚠ Update available ({})".format(online))
        self.after(0, lambda: self.local_ver_lbl.config(
            text=t("advanced_settings.local").format(local)))
        self.after(0, lambda: self.online_ver_lbl.config(
            text=t("advanced_settings.online").format(online, status)))

    def _download_ffmpeg(self):
        def _log(msg):
            self.after(0, lambda m=msg: [
                self.upd_console.insert(tk.END, m + "\n"),
                self.upd_console.see(tk.END)])

        def _work():
            ok = download_and_extract_ffmpeg(_log)
            if ok:
                self.after(0, self._check_versions)

        threading.Thread(target=_work, daemon=True).start()

    def _open_bin(self):
        bin_dir = os.path.dirname(get_binary_path("ffmpeg"))
        if not open_in_explorer(bin_dir):
            messagebox.showinfo("Bin folder", bin_dir)

    def _browse_binary(self, key, var):
        p = filedialog.askopenfilename(
            filetypes=[("Executable", t("advanced_settings.exe")), ("All", t("ducker.item_2"))])
        if p:
            var.set(p)
            self.settings[key] = p

    # ─── Defaults ─────────────────────────────────────────────────────────────
    def _build_defaults_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Defaults  ")
        tk.Label(f, text=t("adv.encoding_defaults"),
                 font=(UI_FONT, 12, "bold")).pack(pady=(20, 10))

        opts = tk.LabelFrame(f, text=f"  {t('advanced_settings.default_encode_section')}  ",
                             padx=20, pady=12)
        opts.pack(fill="x", padx=20, pady=8)

        rows = [
            ("Default CRF:", "default_crf", "18", None),
            ("Default Preset:", "default_preset", "fast",
             ["ultrafast", "superfast", "veryfast", "faster", "fast",
              "medium", "slow", "slower", "veryslow"]),
            ("Default Audio Bitrate:", "default_audio_bitrate", "192k",
             ["96k", "128k", "192k", "256k", "320k"]),
        ]

        self._settings_vars = {}
        for i, (label, key, default, choices) in enumerate(rows):
            tk.Label(opts, text=label, width=24, anchor="e").grid(
                row=i, column=0, pady=6)
            var = tk.StringVar(value=self.settings.get(key, default))
            self._settings_vars[key] = var
            if choices:
                ttk.Combobox(opts, textvariable=var, values=choices,
                             state="readonly", width=16).grid(
                    row=i, column=1, sticky="w", padx=8)
            else:
                tk.Entry(opts, textvariable=var, width=8, relief="flat").grid(
                    row=i, column=1, sticky="w", padx=8)

        of = tk.Frame(opts)
        of.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=6)
        tk.Label(of, text="Default Output Folder:",
                 width=24, anchor="e").pack(side="left")
        self.out_folder_var = tk.StringVar(
            value=self.settings.get("default_output_folder", ""))
        tk.Entry(of, textvariable=self.out_folder_var,
                 width=40).pack(side="left", padx=8)
        tk.Button(
            of, text=t("btn.browse"),
            command=lambda: self.out_folder_var.set(
                filedialog.askdirectory() or self.out_folder_var.get())
        ).pack(side="left")

        self.auto_open_var = tk.BooleanVar(
            value=self.settings.get("auto_open_output", False))
        tk.Checkbutton(opts,
                       text="Auto-open output folder after render",
                       variable=self.auto_open_var).grid(
            row=len(rows) + 1, column=0, columnspan=3, sticky="w", pady=4)

        tk.Button(f, text=t("advanced_settings.save_settings"),
                  bg=CLR["green"], fg="white",
                  font=(UI_FONT, 11, "bold"),
                  command=self._save_settings).pack(pady=15)
        self.save_lbl = tk.Label(f, text="", fg=CLR["green"])
        self.save_lbl.pack()

    def _save_settings(self):
        for key, var in self._settings_vars.items():
            self.settings[key] = var.get()
        self.settings["default_output_folder"] = self.out_folder_var.get()
        self.settings["auto_open_output"]       = self.auto_open_var.get()
        self.settings["ffmpeg_path_override"]    = self.ffmpeg_path_var.get()
        if save_settings(self.settings):
            self.save_lbl.config(text=t("advanced_settings.settings_saved"), fg=CLR["green"])
        else:
            self.save_lbl.config(text=t("advanced_settings.save_failed"), fg=CLR["red"])

    # ─── Networking ───────────────────────────────────────────────────────────
    def _build_networking_tab(self, nb):
        from core import network as _net

        f = ttk.Frame(nb)
        nb.add(f, text="  Networking  ")

        # Scrollable body, since the form has many rows.
        outer = tk.Frame(f, bg=CLR["bg"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=CLR["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=CLR["bg"])
        canvas_win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, w=canvas_win: canvas.itemconfig(w, width=e.width))

        tk.Label(body,
                 text="Network settings apply to all in-app fetches "
                      "(version checks, thumbnails) and to every yt-dlp / "
                      "ffmpeg / pip subprocess started by the app.",
                 font=(UI_FONT, 9), bg=CLR["bg"], fg=CLR["fgdim"],
                 wraplength=720, justify="left").pack(
            anchor="w", padx=20, pady=(14, 8))

        # Load saved values into form variables.
        cfg = _net.get()
        self._net_vars = {}
        for key, default in _net.DEFAULTS.items():
            val = cfg.get(key, default)
            if isinstance(default, bool):
                v = tk.BooleanVar(value=bool(val))
            else:
                v = tk.StringVar(value="" if val is None else str(val))
            self._net_vars[key] = v

        def _section(parent, title):
            lf = tk.LabelFrame(parent, text=f"  {title}  ",
                               padx=14, pady=10,
                               bg=CLR["bg"], fg=CLR["fgdim"],
                               font=(UI_FONT, 9, "bold"),
                               bd=1, relief="solid")
            lf.pack(fill="x", padx=20, pady=6)
            return lf

        def _row(parent, label, key, widget_factory, hint=""):
            r = tk.Frame(parent, bg=CLR["bg"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, font=(UI_FONT, 9),
                     width=22, anchor="e",
                     bg=CLR["bg"], fg=CLR["fg"]).pack(side="left")
            widget_factory(r)
            default = _net.DEFAULTS[key]
            default_str = "(default)" if default in (False, "", "auto", True) \
                else f"(default: {default})"
            reset_btn = tk.Button(
                r, text="↺", font=(UI_FONT, 9),
                bg=CLR["panel"], fg=CLR["fg"],
                relief="flat", cursor="hand2",
                width=2, padx=2, pady=0,
                command=lambda k=key: self._net_reset_field(k))
            reset_btn.pack(side="left", padx=4)
            self.add_tooltip(reset_btn, f"Reset to default {default_str}")
            if hint:
                tk.Label(r, text=hint, font=(UI_FONT, 8),
                         bg=CLR["bg"], fg=CLR["fgdim"]).pack(
                    side="left", padx=(6, 0))
            return r

        # ── Quick presets ──────────────────────────────────────────────
        ps = _section(body, "Quick Presets")
        ps_row = tk.Frame(ps, bg=CLR["bg"])
        ps_row.pack(anchor="w")
        tk.Label(ps_row, text="One-click setups:",
                 font=(UI_FONT, 9),
                 bg=CLR["bg"], fg=CLR["fgdim"]).pack(side="left", padx=(0, 8))

        def _preset_btn(label, pid):
            return tk.Button(
                ps_row, text=label,
                bg=CLR["panel"], fg=CLR["fg"],
                font=(UI_FONT, 9),
                activebackground=CLR["accent"], activeforeground="white",
                relief="flat", cursor="hand2", padx=10, pady=3,
                command=lambda p=pid: self._net_apply_preset(p))

        _preset_btn("Direct (no proxy)", "direct").pack(side="left", padx=3)
        _preset_btn("System defaults",   "system").pack(side="left", padx=3)
        _preset_btn("Tor (127.0.0.1:9050)", "tor").pack(side="left", padx=3)
        _preset_btn("Local HTTP (127.0.0.1:8080)", "local_http").pack(side="left", padx=3)

        # ── Proxy ──────────────────────────────────────────────────────
        px = _section(body, "Proxy")

        en_row = tk.Frame(px, bg=CLR["bg"])
        en_row.pack(fill="x", pady=2)
        tk.Checkbutton(en_row, text="Route all traffic through a proxy",
                       variable=self._net_vars["network.proxy_enabled"],
                       bg=CLR["bg"], fg=CLR["fg"],
                       activebackground=CLR["bg"]).pack(side="left")

        def _scheme_widget(parent):
            ttk.Combobox(parent,
                         textvariable=self._net_vars["network.proxy_scheme"],
                         values=["http", "https", "socks4", "socks5", "socks5h"],
                         state="readonly", width=10,
                         font=(UI_FONT, 9)).pack(side="left", padx=6)

        _row(px, "Scheme:", "network.proxy_scheme", _scheme_widget,
             hint="(SOCKS proxies are honoured by yt-dlp / ffmpeg; "
                  "in-app urllib falls back to direct.)")

        def _host_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.proxy_host"],
                     width=22, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(px, "Host:", "network.proxy_host", _host_widget)

        def _port_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.proxy_port"],
                     width=8, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(px, "Port:", "network.proxy_port", _port_widget,
             hint="(blank if no proxy)")

        def _user_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.proxy_user"],
                     width=22, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(px, "Username:", "network.proxy_user", _user_widget,
             hint="(optional)")

        def _pass_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.proxy_pass"],
                     width=22, show="*", relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(px, "Password:", "network.proxy_pass", _pass_widget,
             hint="(optional)")

        def _np_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.no_proxy"],
                     width=40, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(px, "Bypass list:", "network.no_proxy", _np_widget,
             hint="(comma-separated hosts that skip the proxy)")

        # ── Bandwidth & timeouts ────────────────────────────────────────
        bw = _section(body, "Bandwidth and Timeouts")

        def _rate_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.bandwidth_limit"],
                     width=10, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(bw, "Download rate cap:", "network.bandwidth_limit", _rate_widget,
             hint="(e.g. 1M, 500K, 50K. Blank = unlimited)")

        def _ct_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.connect_timeout"],
                     width=6, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(bw, "Connect timeout (s):", "network.connect_timeout", _ct_widget)

        def _so_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.socket_timeout"],
                     width=6, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(bw, "Socket timeout (s):", "network.socket_timeout", _so_widget)

        # ── Identity ────────────────────────────────────────────────────
        idn = _section(body, "Identity")

        def _ua_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.user_agent"],
                     width=44, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(idn, "User-Agent:", "network.user_agent", _ua_widget,
             hint="(blank = library default)")

        def _ipv_widget(parent):
            ttk.Combobox(parent,
                         textvariable=self._net_vars["network.ip_version"],
                         values=["auto", "ipv4", "ipv6"],
                         state="readonly", width=8,
                         font=(UI_FONT, 9)).pack(side="left", padx=6)

        _row(idn, "IP version:", "network.ip_version", _ipv_widget)

        def _src_widget(parent):
            tk.Entry(parent,
                     textvariable=self._net_vars["network.source_address"],
                     width=22, relief="flat",
                     bg=CLR["input_bg"], fg=CLR["input_fg"]
                     ).pack(side="left", padx=6)

        _row(idn, "Source address:", "network.source_address", _src_widget,
             hint="(bind to a specific local IP)")

        # ── Security ────────────────────────────────────────────────────
        sec = _section(body, "Security")
        sec_row1 = tk.Frame(sec, bg=CLR["bg"])
        sec_row1.pack(fill="x", pady=2)
        tk.Checkbutton(sec_row1, text="Verify SSL certificates",
                       variable=self._net_vars["network.verify_ssl"],
                       bg=CLR["bg"], fg=CLR["fg"],
                       activebackground=CLR["bg"]).pack(side="left")
        ssl_reset = tk.Button(
            sec_row1, text="↺", font=(UI_FONT, 9),
            bg=CLR["panel"], fg=CLR["fg"],
            relief="flat", cursor="hand2", width=2, padx=2,
            command=lambda: self._net_reset_field("network.verify_ssl"))
        ssl_reset.pack(side="left", padx=8)
        self.add_tooltip(ssl_reset, "Reset to default (on)")

        sec_row2 = tk.Frame(sec, bg=CLR["bg"])
        sec_row2.pack(fill="x", pady=2)
        tk.Checkbutton(sec_row2, text="Allow plain HTTP downloads",
                       variable=self._net_vars["network.allow_http"],
                       bg=CLR["bg"], fg=CLR["fg"],
                       activebackground=CLR["bg"]).pack(side="left")
        http_reset = tk.Button(
            sec_row2, text="↺", font=(UI_FONT, 9),
            bg=CLR["panel"], fg=CLR["fg"],
            relief="flat", cursor="hand2", width=2, padx=2,
            command=lambda: self._net_reset_field("network.allow_http"))
        http_reset.pack(side="left", padx=8)
        self.add_tooltip(http_reset, "Reset to default (on)")

        # ── Action row ─────────────────────────────────────────────────
        actions = tk.Frame(body, bg=CLR["bg"])
        actions.pack(fill="x", padx=20, pady=(14, 12))

        tk.Button(actions, text="Save",
                  bg=CLR["green"], fg="white",
                  font=(UI_FONT, 11, "bold"),
                  activebackground=CLR["accent"], activeforeground="white",
                  relief="flat", cursor="hand2", padx=18, pady=6,
                  command=self._net_save).pack(side="left", padx=4)

        tk.Button(actions, text="Test Connection",
                  bg=CLR["panel"], fg=CLR["fg"],
                  font=(UI_FONT, 10),
                  activebackground=CLR["accent"], activeforeground="white",
                  relief="flat", cursor="hand2", padx=14, pady=6,
                  command=self._net_test).pack(side="left", padx=4)

        tk.Button(actions, text="Reset all networking settings",
                  bg=CLR["panel"], fg=CLR["red"],
                  font=(UI_FONT, 10),
                  activebackground=CLR["red"], activeforeground="white",
                  relief="flat", cursor="hand2", padx=14, pady=6,
                  command=self._net_reset_all).pack(side="right", padx=4)

        self._net_status_lbl = tk.Label(
            body, text="", font=(UI_FONT, 9),
            bg=CLR["bg"], fg=CLR["fgdim"], anchor="w", justify="left",
            wraplength=820)
        self._net_status_lbl.pack(fill="x", padx=20, pady=(0, 14))

    def _net_collect(self):
        """Read every form variable into a settings-ready dict."""
        from core import network as _net
        out = {}
        for key, var in self._net_vars.items():
            default = _net.DEFAULTS[key]
            v = var.get()
            if isinstance(default, bool):
                out[key] = bool(v)
            else:
                out[key] = v
        return out

    def _net_save(self):
        from core.settings import load_settings, save_settings
        s = load_settings()
        s.update(self._net_collect())
        ok = save_settings(s)
        self._net_status_lbl.config(
            text=("Saved." if ok else "Save failed."),
            fg=(CLR["green"] if ok else CLR["red"]))

    def _net_test(self):
        from core import network as _net
        # Test against the *form* values, not the saved ones, so the user
        # can validate before clicking Save.
        cfg = dict(_net.DEFAULTS)
        cfg.update(self._net_collect())
        self._net_status_lbl.config(text="Testing…", fg=CLR["fgdim"])
        self.update_idletasks()

        def _work():
            ok, msg = _net.test(cfg=cfg)
            colour = CLR["green"] if ok else CLR["red"]
            self.after(0, lambda: self._net_status_lbl.config(
                text=("Connection OK: " + msg) if ok
                else ("Connection failed: " + msg),
                fg=colour))

        threading.Thread(target=_work, daemon=True).start()

    def _net_reset_field(self, key):
        from core import network as _net
        if key not in _net.DEFAULTS:
            return
        default = _net.DEFAULTS[key]
        var = self._net_vars.get(key)
        if var is None:
            return
        if isinstance(default, bool):
            var.set(bool(default))
        else:
            var.set(str(default))
        self._net_status_lbl.config(
            text=f"{key} reset (not saved yet).", fg=CLR["fgdim"])

    def _net_reset_all(self):
        from core import network as _net
        if not messagebox.askyesno(
                "Reset networking",
                "Reset every networking setting to its default?\n\n"
                "This clears any proxy, bandwidth cap, custom User-Agent, "
                "and other overrides you have made."):
            return
        _net.reset_all()
        # Refresh form variables from defaults.
        for key, default in _net.DEFAULTS.items():
            var = self._net_vars.get(key)
            if var is None:
                continue
            if isinstance(default, bool):
                var.set(bool(default))
            else:
                var.set(str(default))
        self._net_status_lbl.config(
            text="All networking settings reset to defaults and saved.",
            fg=CLR["green"])

    def _net_apply_preset(self, preset_id):
        from core import network as _net
        preset = _net.PRESETS.get(preset_id, {})
        if not preset:
            return
        # Apply preset values to the form variables (don't save until the
        # user clicks Save, so they can review and tweak first).
        for key, value in preset.items():
            var = self._net_vars.get(key)
            if var is None:
                continue
            if isinstance(_net.DEFAULTS.get(key), bool):
                var.set(bool(value))
            else:
                var.set(str(value))
        self._net_status_lbl.config(
            text=f"Preset '{preset_id}' applied to form. Click Save to persist.",
            fg=CLR["fgdim"])

    # ─── Skins ────────────────────────────────────────────────────────────────
    def _build_skins_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text=t("advanced_settings.skins"))

        # Inner notebook: Themes | Custom
        inner_nb = ttk.Notebook(outer)
        inner_nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_themes_subtab(inner_nb)
        self._build_custom_subtab(inner_nb)

    # ── Themes sub-tab ────────────────────────────────────────────────────────
    def _build_themes_subtab(self, inner_nb):
        f = ttk.Frame(inner_nb)
        inner_nb.add(f, text="  Themes  ")

        tk.Label(f, text=t("adv.skins_title"),
                 font=(UI_FONT, 12, "bold")).pack(pady=(16, 4))
        tk.Label(f,
                 text=t("adv.skins_subtitle"),
                 fg=CLR["fgdim"]).pack()

        current_skin = load_skin_name()
        self._skin_var = tk.StringVar(value=current_skin)

        # Scrollable card grid
        scroll_canvas = tk.Canvas(f, highlightthickness=0)
        scroll_canvas.pack(fill="both", expand=True, padx=8, pady=8)
        vsb = ttk.Scrollbar(f, orient="vertical", command=scroll_canvas.yview)
        vsb.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        scroll_canvas.configure(yscrollcommand=vsb.set)

        grid_host = tk.Frame(scroll_canvas)
        scroll_canvas.create_window((0, 0), window=grid_host, anchor="nw")

        def _on_resize(evt):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        grid_host.bind("<Configure>", _on_resize)

        # Theme cards (exclude "Custom" - it lives in the Custom tab)
        theme_names = [n for n in SKINS.keys() if n != "Custom"]
        COLS = 3
        self._skin_previews = {}

        for idx, name in enumerate(theme_names):
            skin = SKINS[name]
            row  = idx // COLS
            col  = idx  % COLS

            card = tk.Frame(grid_host, relief="raised", bd=2,
                            bg=skin["sb_bg"],
                            highlightthickness=3,
                            highlightbackground=skin["accent"])
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            grid_host.columnconfigure(col, weight=1)

            c = tk.Canvas(card, width=180, height=80,
                          bg=skin["sb_bg"], highlightthickness=0)
            c.pack(pady=(8, 4))
            c.create_rectangle(0, 0, 40, 80, fill=skin["sb_bg"], outline="")
            c.create_rectangle(42, 0, 180, 80,
                               fill=skin.get("content", "#1E1E1E"), outline="")
            for i in range(4):
                c.create_rectangle(
                    4, 8 + i * 18, 36, 20 + i * 18,
                    fill=skin["sb_hover"] if i == 1 else skin["sb_bg"],
                    outline="")
                c.create_text(20, 14 + i * 18, text="─",
                              fill=skin["sb_btn"], font=(UI_FONT, 7))
            c.create_rectangle(44, 8, 176, 26, fill=skin["panel"], outline="")
            c.create_text(110, 17, text=name, fill=skin["accent"],
                          font=(UI_FONT, 8, "bold"))
            if skin.get("stars"):
                for sx, sy in [(20, 5), (60, 15), (120, 8),
                               (155, 30), (80, 55), (30, 65)]:
                    c.create_text(sx, sy, text="✦", fill=skin["accent"],
                                  font=(UI_FONT, 6))
            self._skin_previews[name] = c

            tk.Label(card, text=name, font=(UI_FONT, 11, "bold"),
                     bg=skin["sb_bg"], fg=skin["accent"]).pack()
            tk.Label(card, text=skin["desc"], font=(UI_FONT, 8),
                     bg=skin["sb_bg"], fg=skin["sb_btn"],
                     wraplength=170, justify="center").pack(pady=(2, 6))

            rb = tk.Radiobutton(
                card, text=t("advanced_settings.select_this_skin"),
                variable=self._skin_var, value=name,
                bg=skin["sb_bg"], fg=skin["accent"],
                selectcolor=skin["sb_active"],
                activebackground=skin["sb_hover"],
                font=(UI_FONT, 9),
                command=lambda n=name: self._on_skin_select(n))
            rb.pack(pady=(0, 8))

        apply_f = tk.Frame(f)
        apply_f.pack(pady=10)
        tk.Button(apply_f, text=t("advanced_settings.apply_skin_now"),
                  bg=CLR["accent"], fg="black",
                  font=(UI_FONT, 12, "bold"),
                  command=self._apply_skin).pack(side="left", padx=8)
        self._skin_status = tk.Label(apply_f, text="", fg=CLR["green"])
        self._skin_status.pack(side="left", padx=8)

        tk.Label(
            f,
            text=(
                "✨  Mystical includes animated falling star particles across the app window.\n"
                "All skins apply instantly. No restart required."
            ),
            fg=CLR["fgdim"], font=(UI_FONT, 8),
        ).pack(pady=(2, 6))

        # ── Star speed control (only visible when Mystical is active) ─────────
        self._star_speed_frame = tk.LabelFrame(
            f, text=t("advanced_settings.star_speed"), padx=16, pady=10)

        speed_row = tk.Frame(self._star_speed_frame)
        speed_row.pack(fill="x")
        tk.Label(speed_row, text="Slow", font=(UI_FONT, 8),
                 fg=CLR["fgdim"]).pack(side="left")

        from core.settings import get as _cfg_get
        saved_speed = float(_cfg_get("star_speed", 1.0))
        self._star_speed_var = tk.DoubleVar(value=saved_speed)

        speed_slider = tk.Scale(
            speed_row,
            from_=0.15, to=4.0,
            resolution=0.05,
            orient="horizontal",
            variable=self._star_speed_var,
            showvalue=False,
            length=280,
            command=self._on_star_speed_change,
            bg="#3D1060", activebackground="#A840BC",
            troughcolor="#28184A",
            highlightthickness=1, highlightbackground="#6A2F8A",
            sliderrelief="raised", bd=2,
        )
        speed_slider.pack(side="left", padx=8, fill="x", expand=True)
        tk.Label(speed_row, text="Fast", font=(UI_FONT, 8),
                 fg=CLR["fgdim"]).pack(side="left")

        self._star_speed_lbl = tk.Label(
            self._star_speed_frame,
            text=self._speed_label(saved_speed),
            font=(UI_FONT, 8), fg=CLR["fgdim"])
        self._star_speed_lbl.pack()

        # ── Star density (count) ───────────────────────────────────────────
        tk.Frame(self._star_speed_frame, height=6).pack()  # spacer

        density_row = tk.Frame(self._star_speed_frame)
        density_row.pack(fill="x")
        tk.Label(density_row, text="Few", font=(UI_FONT, 8),
                 fg=CLR["fgdim"]).pack(side="left")

        saved_count = int(_cfg_get("star_count", 55))
        self._star_count_var = tk.IntVar(value=saved_count)

        density_slider = tk.Scale(
            density_row,
            from_=10, to=120,
            resolution=1,
            orient="horizontal",
            variable=self._star_count_var,
            showvalue=False,
            length=280,
            command=self._on_star_count_change,
            bg="#3D1060", activebackground="#A840BC",
            troughcolor="#28184A",
            highlightthickness=1, highlightbackground="#6A2F8A",
            sliderrelief="raised", bd=2,
        )
        density_slider.pack(side="left", padx=8, fill="x", expand=True)
        tk.Label(density_row, text="Many", font=(UI_FONT, 8),
                 fg=CLR["fgdim"]).pack(side="left")

        self._star_count_lbl = tk.Label(
            self._star_speed_frame,
            text=f"{saved_count} stars",
            font=(UI_FONT, 8), fg=CLR["fgdim"])
        self._star_count_lbl.pack()

        self._update_star_speed_visibility(current_skin)

    # ── Custom skin sub-tab ───────────────────────────────────────────────────
    def _build_custom_subtab(self, inner_nb):
        """Scrollable color-property editor for the 'Custom' skin."""
        f = ttk.Frame(inner_nb)
        inner_nb.add(f, text="  Custom  ")

        # Header
        hdr = tk.Frame(f)
        hdr.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(hdr, text=t("adv.custom_title"),
                 font=(UI_FONT, 12, "bold")).pack(side="left")
        tk.Button(hdr, text=t("advanced_settings.apply_custom_skin"),
                  bg=CLR["accent"], fg="black",
                  font=(UI_FONT, 10, "bold"),
                  command=self._apply_custom_skin).pack(side="right", padx=4)
        self._custom_status = tk.Label(hdr, text="", fg=CLR["green"])
        self._custom_status.pack(side="right", padx=8)

        tk.Label(f,
                 text=t("adv.custom_subtitle"),
                 fg=CLR["fgdim"], font=(UI_FONT, 9)).pack(pady=(0, 8))

        # Scrollable area
        wrapper = tk.Frame(f)
        wrapper.pack(fill="both", expand=True, padx=12)

        canvas = tk.Canvas(wrapper, highlightthickness=0)
        vsb    = ttk.Scrollbar(wrapper, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(evt):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        def _resize_inner(evt):
            canvas.itemconfig(win_id, width=evt.width)
        canvas.bind("<Configure>", _resize_inner)

        def _scroll(evt):
            canvas.yview_scroll(int(-evt.delta / 120) * 2, "units")
        canvas.bind("<MouseWheel>", _scroll)
        inner.bind("<MouseWheel>", _scroll)

        # Load current custom colors
        current_custom = get_skin("Custom")
        self._custom_vars: dict[str, tk.StringVar] = {}

        # Color sections: (Section title, [(display_label, color_key), ...])
        sections = [
            ("Sidebar", [
                (t("advanced_settings.sidebar_background"),       "sb_bg"),
                (t("advanced_settings.category_header"),          "sb_cat"),
                (t("advanced_settings.button_text_icons"),      "sb_btn"),
                (t("advanced_settings.button_hover_background"),  "sb_hover"),
                (t("advanced_settings.active_button_background"), "sb_active"),
            ]),
            ("Content Area", [
                ("Content background",       "content"),
                ("Panel / card background",  "panel"),
                ("Primary text",             "fg"),
                ("Dimmed / secondary text",  "fgdim"),
                ("Border color",             "border"),
            ]),
            ("Accent & Inputs", [
                ("Accent color",             "accent"),
                ("Input field background",   "input_bg"),
                ("Input field text",         "input_fg"),
            ]),
            ("Status Colors", [
                ("Success / green",          "green"),
                ("Error / red",              "red"),
                ("Warning / orange",         "orange"),
                ("Highlight / pink",         "pink"),
            ]),
            ("Console", [
                ("Console background",       "console_bg"),
                ("Console text",             "console_fg"),
            ]),
        ]

        for section_title, props in sections:
            sec_frame = tk.LabelFrame(inner, text=f"  {section_title}  ",
                                      padx=12, pady=10)
            sec_frame.pack(fill="x", padx=8, pady=(8, 4))
            sec_frame.bind("<MouseWheel>", _scroll)

            for label_text, key in props:
                row = tk.Frame(sec_frame)
                row.pack(fill="x", pady=3)
                row.bind("<MouseWheel>", _scroll)

                initial = current_custom.get(key, _CUSTOM_DEFAULTS.get(key, "#222222"))
                var = tk.StringVar(value=initial)
                self._custom_vars[key] = var

                tk.Label(row, text=label_text, width=26,
                         anchor="w", font=(UI_FONT, 9)).pack(side="left")

                # Color swatch
                swatch = tk.Label(row, width=4, bg=initial, relief="solid", bd=1)
                swatch.pack(side="left", padx=(4, 2))

                # Hex entry
                entry = tk.Entry(row, textvariable=var, width=9,
                                 font=(MONO_FONT, 9))
                entry.pack(side="left", padx=2)

                # Pick button - closure captures key, var, swatch
                def _pick(k=key, v=var, sw=swatch):
                    from tkinter import colorchooser
                    current_hex = v.get()
                    try:
                        rgb, hex_color = colorchooser.askcolor(
                            color=current_hex, title=f"Choose color for {k}")
                    except Exception:
                        return
                    if hex_color:
                        hex_color = hex_color.upper()
                        v.set(hex_color)
                        try:
                            sw.configure(bg=hex_color)
                        except Exception:
                            pass
                        save_custom_color(k, hex_color)
                        # Update live preview swatch
                        self._custom_status.config(
                            text=t("advanced_settings.saved"), fg=CLR["green"])

                tk.Button(row, text=t("advanced_settings.pick"), command=_pick,
                          font=(UI_FONT, 8)).pack(side="left", padx=4)

                # Keep swatch in sync when user types directly in entry
                def _sync_swatch(evt, sw=swatch, v=var, k=key):
                    val = v.get().strip()
                    if len(val) in (4, 7) and val.startswith("#"):
                        try:
                            sw.configure(bg=val)
                            save_custom_color(k, val.upper())
                            self._custom_status.config(
                                text=t("advanced_settings.saved"), fg=CLR["green"])
                        except Exception:
                            pass
                entry.bind("<FocusOut>", _sync_swatch)
                entry.bind("<Return>",   _sync_swatch)

        # Reset to defaults button
        reset_row = tk.Frame(inner)
        reset_row.pack(fill="x", padx=8, pady=(12, 8))
        tk.Button(reset_row, text=t("advanced_settings.reset_to_defaults"),
                  bg=CLR["panel"], fg=CLR["fgdim"],
                  font=(UI_FONT, 9),
                  command=self._reset_custom_defaults).pack(side="left")

    def _apply_custom_skin(self):
        """Select 'Custom' and apply it live."""
        self._skin_var.set("Custom")
        self._on_skin_select("Custom")

    def _reset_custom_defaults(self):
        """Reset all custom color vars to _CUSTOM_DEFAULTS."""
        from core.settings import load_settings as _ls, save_settings as _ss
        data = _ls()
        prefix = "custom_color_"
        for key, val in _CUSTOM_DEFAULTS.items():
            if isinstance(val, str) and val.startswith("#"):
                self._custom_vars[key].set(val)
                data[f"{prefix}{key}"] = val
        _ss(data)
        try:
            self._custom_status.config(text=t("advanced_settings.reset_to_defaults_2"), fg=CLR["green"])
        except Exception:
            pass

    def _on_skin_select(self, name):
        """Save and apply the selected skin live, immediately."""
        save_skin_name(name)
        self._update_star_speed_visibility(name)
        try:
            app = self.winfo_toplevel()
            apply_skin(
                app,
                app.sidebar_container,
                app.content_container,
                app._btn_refs,
            )
            self._skin_status.config(
                text="✅  '{}' applied live!".format(name),
                fg=CLR["accent"])
        except Exception:
            self._skin_status.config(
                text=t("advanced_settings.saved_reopen_to_see_full_effect"),
                fg=CLR["green"])

    def _apply_skin(self):
        self._on_skin_select(self._skin_var.get())

    def _update_star_speed_visibility(self, skin_name: str):
        """Show the star-speed panel only when a stars-enabled skin is active."""
        try:
            skin = get_skin(skin_name)
            if skin.get("stars"):
                self._star_speed_frame.pack(padx=20, pady=(0, 12), fill="x")
            else:
                self._star_speed_frame.pack_forget()
        except Exception:
            pass

    @staticmethod
    def _speed_label(mult: float) -> str:
        if mult < 0.4:   return "Very slow"
        if mult < 0.75:  return "Slow"
        if mult < 1.35:  return "Default"
        if mult < 2.2:   return "Fast"
        return "Very fast"

    def _on_star_speed_change(self, value):
        mult = float(value)
        set_star_speed(mult)
        try:
            self._star_speed_lbl.config(text=self._speed_label(mult))
        except Exception:
            pass
        from core.settings import set as _cfg_set
        _cfg_set("star_speed", mult)

    def _on_star_count_change(self, value):
        count = int(float(value))
        set_star_count(count)
        try:
            self._star_count_lbl.config(text=f"{count} stars")
        except Exception:
            pass
        from core.settings import set as _cfg_set
        _cfg_set("star_count", count)
        # Restart stars so density takes effect immediately
        try:
            from core.skins import _start_stars, get_skin, load_skin_name
            app = self.winfo_toplevel()
            skin_name = load_skin_name()
            if get_skin(skin_name).get("stars"):
                _start_stars(app, get_skin(skin_name),
                             getattr(app, "_inner", None))
        except Exception:
            pass

    # ─── Language ─────────────────────────────────────────────────────────────
    def _build_language_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("advanced_settings.language"))

        tk.Label(f, text=t("advanced_settings.language_langue_idioma"),
                 font=(UI_FONT, 12, "bold")).pack(pady=(20, 4))
        tk.Label(f, text=t("lang.subtitle"),
                 font=(UI_FONT, 9), fg=CLR["fgdim"]).pack(pady=(0, 18))

        info_f = tk.Frame(f)
        info_f.pack(anchor="center")

        # Current language row
        row1 = tk.Frame(info_f)
        row1.pack(anchor="w", pady=4)
        tk.Label(row1, text=t("lang.current"), font=(UI_FONT, 10)).pack(side="left", padx=(0, 8))
        cur_code = get_language()
        cur_name = LANGUAGE_NAMES.get(cur_code, cur_code)
        tk.Label(row1, text=cur_name, font=(UI_FONT, 10, "bold"),
                 fg=CLR["accent"]).pack(side="left")

        # Select language row
        row2 = tk.Frame(info_f)
        row2.pack(anchor="w", pady=(12, 4))
        tk.Label(row2, text=t("advanced_settings.select_language"), font=(UI_FONT, 10)).pack(side="left", padx=(0, 8))

        display_names = [LANGUAGE_NAMES.get(c, c) for c in SUPPORTED_LANGUAGES]
        self._lang_var = tk.StringVar(value=LANGUAGE_NAMES.get(cur_code, cur_code))
        lang_cb = ttk.Combobox(row2, textvariable=self._lang_var,
                               values=display_names, state="readonly", width=28,
                               font=(UI_FONT, 10))
        lang_cb.pack(side="left")

        # Save button
        def _save_language():
            chosen_name = self._lang_var.get()
            # Reverse look up: name → code
            code = next((c for c in SUPPORTED_LANGUAGES
                         if LANGUAGE_NAMES.get(c) == chosen_name), None)
            if not code:
                return
            set_language(code)
            msg_lbl.config(
                text=t("advanced_settings.language_saved_please_restart_the_app_to_apply_t"),
                fg=CLR["green"])

        tk.Button(info_f, text=t("advanced_settings.save_language"),
                  bg=CLR["accent"], fg="white",
                  font=(UI_FONT, 10), padx=14, pady=4,
                  relief="flat", cursor="hand2",
                  command=_save_language).pack(pady=14)

        msg_lbl = tk.Label(info_f, text="", font=(UI_FONT, 9), fg=CLR["green"],
                           wraplength=400, justify="center")
        msg_lbl.pack()

    # ─── System Info ──────────────────────────────────────────────────────────
    def _build_system_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text=t("advanced_settings.system_info"))

        hdr2 = tk.Frame(f)
        hdr2.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(hdr2, text=t("adv.sys_hardware"),
                 font=(UI_FONT, 12, "bold")).pack(side="left")
        tk.Button(hdr2, text=t("advanced_settings.refresh"),
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=lambda: threading.Thread(
                      target=lambda: self._load_sysinfo(info_area),
                      daemon=True).start()
                  ).pack(side="right")

        info_area = scrolledtext.ScrolledText(
            f, height=28, bg=CLR["console_bg"], fg="#00FF88",
            font=(MONO_FONT, 10), insertbackground="#00FF88")
        info_area.pack(fill="both", expand=True, padx=20, pady=8)

        threading.Thread(
            target=lambda: self._load_sysinfo(info_area),
            daemon=True).start()

    def _load_sysinfo(self, area):
        lines = []

        def sep(title=""):
            lines.append("")
            if title:
                lines.append("──── {} ".format(title) + "─" * max(0, 46 - len(title)))
            else:
                lines.append("─" * 52)

        def ps(cmd):
            """Run a PowerShell command, return stdout string."""
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", cmd],
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW)
            return r.stdout.strip()

        is_win = platform.system() == "Windows"

        # ── OS ────────────────────────────────────────────────────────────
        sep("OPERATING SYSTEM")
        lines.append("  Platform:     {} {}".format(
            platform.system(), platform.release()))
        lines.append("  Version:      {}".format(platform.version()[:70]))
        lines.append("  Architecture: {}".format(platform.machine()))
        lines.append("  Hostname:     {}".format(platform.node()))
        if is_win:
            try:
                reg = ps(
                    "Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT"
                    "\\CurrentVersion' | Select-Object ProductName, "
                    "DisplayVersion, CurrentBuildNumber | ConvertTo-Json")
                rv = json.loads(reg)
                product   = rv.get("ProductName", "")
                disp_ver  = rv.get("DisplayVersion", "")
                build_num = int(rv.get("CurrentBuildNumber", 0) or 0)
                if build_num >= 22000 and "Windows 10" in product:
                    product = product.replace("Windows 10", "Windows 11")
                lines.append("  Edition:      {} {}".format(
                    product, disp_ver).strip())
                lines.append("  Build:        {}  ({})".format(
                    build_num, disp_ver))
                uptime_s = ps(
                    "(Get-Date) - (gcim Win32_OperatingSystem).LastBootUpTime"
                    " | Select-Object -ExpandProperty TotalSeconds")
                if uptime_s:
                    secs = int(float(uptime_s))
                    h, m = divmod(secs // 60, 60)
                    lines.append("  Uptime:       {}h {}m".format(h, m))
            except Exception:
                pass

        # ── CPU ───────────────────────────────────────────────────────────
        sep("PROCESSOR (CPU)")
        try:
            if is_win:
                name    = ps("(Get-CimInstance Win32_Processor).Name")
                cores   = ps("(Get-CimInstance Win32_Processor).NumberOfCores")
                threads = ps("(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors")
                mhz     = ps("(Get-CimInstance Win32_Processor).MaxClockSpeed")
                lines.append("  Model:        {}".format(name))
                lines.append("  Cores:        {}  /  Threads: {}".format(
                    cores, threads))
                if mhz:
                    try:
                        lines.append("  Base clock:   {:.2f} GHz  ({} MHz)".format(
                            float(mhz) / 1000, mhz))
                    except ValueError:
                        lines.append("  Base clock:   {} MHz".format(mhz))
                load = ps("(Get-CimInstance Win32_Processor).LoadPercentage")
                if load:
                    lines.append("  Current load: {}%".format(load))
            else:
                r = subprocess.run(["lscpu"], capture_output=True, text=True)
                for line in r.stdout.splitlines():
                    for key in ("Model name", "CPU(s)", "Thread(s)", "MHz"):
                        if line.strip().startswith(key):
                            lines.append("  {}".format(line.strip()))
        except Exception as exc:
            lines.append("  (CPU error: {})".format(exc))

        # ── RAM ───────────────────────────────────────────────────────────
        sep("MEMORY (RAM)")
        try:
            if is_win:
                total    = ps("(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize")
                free     = ps("(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory")
                total_kb = int(total)
                free_kb  = int(free)
                used_kb  = total_kb - free_kb
                pct      = used_kb / total_kb * 100 if total_kb else 0
                lines.append("  Total:        {:.1f} GB".format(total_kb / 1024 / 1024))
                lines.append("  Used:         {:.1f} GB  ({:.0f}%)".format(
                    used_kb / 1024 / 1024, pct))
                lines.append("  Free:         {:.1f} GB".format(free_kb / 1024 / 1024))
                try:
                    sticks = ps(
                        'Get-CimInstance Win32_PhysicalMemory | '
                        'ForEach-Object { "$($_.Capacity/1GB)GB $($_.Speed)MHz $($_.Manufacturer)" }')
                    if sticks:
                        for stick in sticks.splitlines()[:4]:
                            lines.append("  Stick:        {}".format(stick.strip()))
                except Exception:
                    pass
            else:
                r = subprocess.run(["free", "-h"], capture_output=True, text=True)
                for line in r.stdout.splitlines():
                    if line.startswith("Mem"):
                        p = line.split()
                        lines.append("  Total: {}  Used: {}  Free: {}".format(
                            p[1], p[2], p[3]))
        except Exception as exc:
            lines.append("  (RAM error: {})".format(exc))

        # ── Disk ──────────────────────────────────────────────────────────
        sep("DISK / STORAGE")
        try:
            if is_win:
                drives_raw = ps(
                    'Get-CimInstance Win32_DiskDrive | '
                    'ForEach-Object { "$($_.Model)|$([math]::Round($_.Size/1GB))GB|$($_.MediaType)" }')
                if drives_raw:
                    for d in drives_raw.splitlines():
                        parts = d.strip().split("|")
                        if len(parts) >= 2:
                            lines.append("  Drive:        {}  ({})".format(
                                parts[0], parts[1]))
                vols = ps(
                    'Get-PSDrive -PSProvider FileSystem | '
                    'Where-Object { $_.Used -ne $null } | '
                    'ForEach-Object { "$($_.Name):|$([math]::Round(($_.Used+$_.Free)/1GB,0))GB total'
                    '|$([math]::Round($_.Used/1GB,1))GB used|$([math]::Round($_.Free/1GB,1))GB free" }')
                if vols:
                    for v in vols.splitlines():
                        p = v.strip().split("|")
                        if len(p) >= 4:
                            lines.append("  {:<5} {:<14} {:<14} {}".format(
                                p[0], p[1], p[2], p[3]))
            else:
                r = subprocess.run(["df", "-h", "-x", "tmpfs", "-x", "devtmpfs"],
                           capture_output=True, text=True)
                for line in r.stdout.splitlines()[1:6]:
                    lines.append("  {}".format(line))
        except Exception as exc:
            lines.append("  (Disk error: {})".format(exc))

        # ── GPU ───────────────────────────────────────────────────────────
        sep("GRAPHICS (GPU)")
        try:
            hw_accel = detect_gpu().upper()
            lines.append("  HW accel:     {}".format(hw_accel))
            if is_win:
                gpus = ps(
                    'Get-CimInstance Win32_VideoController | '
                    'ForEach-Object { "$($_.Name)|$($_.DriverVersion)" }')
                if gpus:
                    for g in gpus.splitlines():
                        p = g.strip().split("|")
                        if p[0]:
                            lines.append("  GPU:          {}".format(p[0]))
                            if len(p) > 1 and p[1]:
                                lines.append("  Driver:       {}".format(p[1]))

                vram_mb = None
                if hw_accel == "NVIDIA":
                    try:
                        r = subprocess.run(
                            ["nvidia-smi", "--query-gpu=memory.total",
                             "--format=csv,noheader,nounits"],
                            capture_output=True, text=True,
                            creationflags=CREATE_NO_WINDOW)
                        vram_mb = int(r.stdout.strip().splitlines()[0].strip())
                    except Exception:
                        pass

                if vram_mb is None:
                    try:
                        reg_vram = ps(
                            "$key = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class"
                            "\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000'; "
                            "(Get-ItemProperty -Path $key -ErrorAction SilentlyContinue)"
                            ".\"HardwareInformation.MemorySize\"")
                        if reg_vram and reg_vram.strip():
                            vram_mb = int(reg_vram.strip()) // (1024 * 1024)
                    except Exception:
                        pass

                if vram_mb and vram_mb > 0:
                    if vram_mb >= 1024:
                        lines.append("  VRAM:         {:.0f} GB  ({} MB)".format(
                            vram_mb / 1024, vram_mb))
                    else:
                        lines.append("  VRAM:         {} MB".format(vram_mb))
        except Exception as exc:
            lines.append("  (GPU error: {})".format(exc))

        # ── Network ───────────────────────────────────────────────────────
        sep("NETWORK")
        try:
            lines.append("  Hostname:     {}".format(platform.node()))
            lan_ip = None
            if is_win:
                VPN_KEYWORDS = ("nordlynx", "nordvpn", "openvpn", "wireguard",
                                "vpn", "virtual", "loopback", "bluetooth",
                                "vmware", "vethernet", "hyper-v")
                try:
                    ipc = subprocess.run(["ipconfig"], capture_output=True, text=True,
                                 creationflags=CREATE_NO_WINDOW)
                    current_adapter = ""
                    skip_adapter    = False
                    for line in ipc.stdout.splitlines():
                        if line and not line.startswith(" "):
                            current_adapter = line.lower()
                            skip_adapter = any(k in current_adapter
                                               for k in VPN_KEYWORDS)
                        if skip_adapter:
                            continue
                        stripped = line.strip()
                        if "IPv4 Address" in stripped and ":" in stripped:
                            ip = stripped.split(":")[-1].strip().rstrip(
                                "(Preferred)").strip()
                            if ip.startswith("192.168.") or (
                                    ip.startswith("10.") and not ip.startswith("10.5.")):
                                lan_ip = ip
                                break
                            elif ip.startswith("172."):
                                lan_ip = ip
                except Exception:
                    pass

            if not lan_ip:
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    lan_ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    lan_ip = "Unknown"

            lines.append("  LAN IP:       {}".format(lan_ip))

            import urllib.request as _ur
            try:
                pub = _ur.urlopen(
                    "https://api.ipify.org", timeout=4
                ).read().decode().strip()
                lines.append("  Public IP:    {}".format(pub))
            except Exception:
                try:
                    pub = _ur.urlopen(
                        "https://checkip.amazonaws.com", timeout=4
                    ).read().decode().strip()
                    lines.append("  Public IP:    {}".format(pub))
                except Exception:
                    lines.append("  Public IP:    (unavailable, check connection)")
        except Exception as exc:
            lines.append("  (Network error: {})".format(exc))

        # ── Python & App ──────────────────────────────────────────────────
        sep("PYTHON & APPLICATION")
        import sys
        from core import APP_VERSION
        lines.append("  Python:       {}  ({})".format(
            platform.python_version(), sys.executable[:60]))
        lines.append("  tkinter:      {}".format(tk.TkVersion))
        lines.append("  App version:  {}".format(APP_VERSION))
        lines.append("  App root:     {}".format(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

        # ── FFmpeg ────────────────────────────────────────────────────────
        sep("FFMPEG")
        ffmpeg   = get_binary_path("ffmpeg")
        local_v  = get_local_version()
        lines.append("  Binary:       {}".format(ffmpeg))
        lines.append("  Exists:       {}".format(os.path.exists(ffmpeg)))
        lines.append("  Version:      {}".format(local_v))
        try:
            r = subprocess.run([ffmpeg, "-codecs"],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
            hw = [l.strip() for l in r.stdout.split("\n")
                  if any(x in l for x in
                         ["nvenc", "amf", "qsv", "videotoolbox"])]
            lines.append("  HW codecs:    {} found".format(len(hw)))
            for h in hw[:8]:
                lines.append("    {}".format(h[:70]))
        except Exception:
            lines.append("  Could not query codecs.")

        sep()
        lines.append("  ← Refresh to update live stats")

        text = "\n".join(lines)
        self.after(0, lambda: [
            area.config(state="normal"),
            area.delete("1.0", tk.END),
            area.insert(tk.END, text),
            area.config(state="disabled")])

    # ─── Developer ────────────────────────────────────────────────────────────
    def _build_dev_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  Developer  ")

        tk.Label(f, text=t("advanced_settings.ffmpeg_command_runner"),
                 font=(UI_FONT, 12, "bold")).pack(pady=(20, 10))
        tk.Label(f, text=t("advanced_settings.run_any_custom_ffmpeg_command"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=20)

        self.dev_cmd_var = tk.StringVar()
        cmd_entry = tk.Entry(f, textvariable=self.dev_cmd_var,
                             font=(MONO_FONT, 10), width=100)
        cmd_entry.pack(fill="x", padx=20, pady=4)
        cmd_entry.bind("<Return>", lambda _: self._run_dev_cmd())

        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w", padx=20, pady=4)
        tk.Button(btn_row, text=t("advanced_settings.run"),
                  bg=CLR["green"], fg="white",
                  command=self._run_dev_cmd).pack(side="left", padx=4)
        tk.Button(btn_row, text=t("advanced_settings.clear"),
                  bg=CLR["panel"], fg=CLR["fg"],
                  command=lambda: self.dev_console.delete(
                      "1.0", tk.END)).pack(side="left", padx=4)
        tk.Button(btn_row, text=t("advanced_settings.paste_version"),
                  command=lambda: self.dev_cmd_var.set(
                      '"{}" -version'.format(get_binary_path("ffmpeg"))),
                  bg=CLR["panel"], fg=CLR["fg"]).pack(side="left", padx=4)
        tk.Button(btn_row, text=t("advanced_settings.paste_codecs"),
                  command=lambda: self.dev_cmd_var.set(
                      '"{}" -codecs'.format(get_binary_path("ffmpeg"))),
                  bg=CLR["panel"], fg=CLR["fg"]).pack(side="left", padx=4)

        tk.Label(f, text=t("encode_queue.output_label"), fg=CLR["fgdim"]).pack(
            anchor="w", padx=20, pady=(8, 2))
        self.dev_console = scrolledtext.ScrolledText(
            f, height=20, bg=CLR["console_bg"], fg="#00FF88", font=(MONO_FONT, 9))
        self.dev_console.pack(fill="both", expand=True, padx=20, pady=4)

    def _run_dev_cmd(self):
        cmd_str = self.dev_cmd_var.get().strip()
        if not cmd_str:
            return
        self.dev_console.insert(tk.END, "$ {}\n".format(cmd_str))
        self.dev_console.see(tk.END)

        def _work():
            import shlex
            try:
                parts = shlex.split(cmd_str)
            except Exception:
                parts = cmd_str.split()
            proc = subprocess.Popen(
                parts, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=CREATE_NO_WINDOW)
            for line in iter(proc.stdout.readline, ""):
                self.after(0, lambda l=line: [
                    self.dev_console.insert(tk.END, l),
                    self.dev_console.see(tk.END)])
            proc.stdout.close()
            proc.wait()
            self.after(0, lambda: self.dev_console.insert(
                tk.END, "\n[Exited {}]\n".format(proc.returncode)))

        threading.Thread(target=_work, daemon=True).start()
