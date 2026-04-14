"""
tab_slideshowmaker.py  ─  Slideshow Maker
Turn a folder of images into a polished video with:
  • Ken Burns pan/zoom effect per slide
  • Crossfade / wipe transitions between slides
  • Per-slide caption text
  • Background music track (auto-fades at end)
  • Configurable duration per slide

A staple YouTube use case: travel montages, photo recaps,
before/after galleries, tutorial image sequences.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import tempfile
import threading
import re
import json
import shutil

from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path, CREATE_NO_WINDOW
from core.i18n import t


TRANSITIONS = {
    "Crossfade":         "fade",
    t("slideshow.fade_to_black"):     "fadeblack",
    t("slideshow.fade_to_white"):     "fadewhite",
    t("slideshow.slide_left"):        "slideleft",
    t("slideshow.slide_right"):       "slideright",
    t("slideshow.slide_up"):          "slideup",
    t("slideshow.wipe_left"):         "wipeleft",
    t("slideshow.radial_wipe"):       "radial",
    "None (cut)":        None,
}

KEN_BURNS_MODES = {
    t("slideshow.zoom_in_wide_close"):   "zoom_in",
    t("slideshow.zoom_out_close_wide"):   "zoom_out",
    t("slideshow.pan_right"):                  "pan_right",
    t("slideshow.pan_left"):                   "pan_left",
    t("slideshow.pan_up"):                     "pan_up",
    t("slideshow.random_varies_per_slide"):  "random",
    "None (static)":              "static",
}

RESOLUTIONS = {
    t("slideshow.1920_1080_youtube"):    (1920, 1080),
    t("slideshow.3840_2160_4k_youtube"): (3840, 2160),
    t("intro_maker.1280_720_hd"):         (1280, 720),
    t("slideshow.1080_1920_9_16_reel"):  (1080, 1920),
    t("slideshow.1080_1080_square"):     (1080, 1080),
}


class SlideshowMakerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.image_paths = []     # list of str
        self.captions    = {}     # idx → str
        self.music_path  = ""
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=CLR["panel"])
        hdr.pack(fill="x")
        hdr_inner = tk.Frame(hdr, bg=CLR["panel"])
        hdr_inner.pack(fill="x", padx=20, pady=(14, 13))
        tk.Label(hdr_inner, text="🖼  " + t("tab.slideshow_maker"), font=(UI_FONT, 15, "bold"),
                 bg=CLR["panel"], fg=CLR["accent"]).pack(side="left")
        tk.Label(hdr_inner, text=t("slideshow.subtitle"),
                 font=(UI_FONT, 10), bg=CLR["panel"],
                 fg=CLR["fgdim"]).pack(side="left", padx=(16, 0))
        tk.Frame(self, bg=CLR["border"], height=1).pack(fill="x")

        # ── Main paned layout ─────────────────────────────────────────────
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=5,
                               bg="#888888")
        paned.pack(fill="both", expand=True, padx=10, pady=6)

        left  = tk.Frame(paned, width=420)
        right = tk.Frame(paned, width=480)
        paned.add(left,  minsize=300)
        paned.add(right, minsize=340)

        self._build_slide_panel(left)
        self._build_options_panel(right)

    # ── Slide list ────────────────────────────────────────────────────────
    def _build_slide_panel(self, parent):
        tk.Label(parent, text="SLIDES", font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        # Listbox with scrollbar
        lf = tk.Frame(parent)
        lf.pack(fill="both", expand=True, padx=6)
        self.listbox = tk.Listbox(lf, selectmode="single",
                                   font=(MONO_FONT, 9), height=16,
                                   bg=CLR["bg"], fg=CLR["fg"],
                                   selectbackground=CLR["accent"],
                                   selectforeground="black")
        sb = ttk.Scrollbar(lf, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_slide_select)

        # Slide count
        self.count_lbl = tk.Label(parent, text=t("slideshow.0_slides"), fg=CLR["fgdim"],
                                   font=(UI_FONT, 9))
        self.count_lbl.pack(anchor="w", padx=8)

        # Buttons
        btn_f = tk.Frame(parent); btn_f.pack(fill="x", padx=6, pady=4)
        for txt, cmd, bg in [
            ("➕ Add Images",  self._add_images,   "#3A3A3A"),
            ("📁 Add Folder",  self._add_folder,   "#3A3A3A"),
            ("⬆",              self._move_up,      "#3A3A3A"),
            ("⬇",              self._move_down,    "#3A3A3A"),
            ("🗑 Remove",       self._remove_sel,   "#3A3A3A"),
            ("🧹 Clear",        self._clear_all,    "#3A3A3A"),
        ]:
            tk.Button(btn_f, text=txt, bg=bg, fg=CLR["fg"],
                      font=(UI_FONT, 8), command=cmd).pack(side="left", padx=2)

        # Per-slide caption editor
        cap_lf = tk.LabelFrame(parent, text=f"  {t('slideshow.caption_label')}  ",
                                padx=8, pady=6)
        cap_lf.pack(fill="x", padx=6, pady=4)
        self.cap_var = tk.StringVar()
        self.cap_entry = tk.Entry(cap_lf, textvariable=self.cap_var, width=40, relief="flat")
        self.cap_entry.pack(side="left", fill="x", expand=True)
        tk.Button(cap_lf, text=t("slideshow.apply_button"), bg=CLR["accent"], fg="black",
                  command=self._save_caption).pack(side="left", padx=4)

        # Music
        music_lf = tk.LabelFrame(parent, text=f"  🎵  {t('slideshow.background_music_section')}  ",
                                  padx=8, pady=6)
        music_lf.pack(fill="x", padx=6, pady=4)
        m_row = tk.Frame(music_lf); m_row.pack(fill="x")
        self.music_var = tk.StringVar()
        tk.Entry(m_row, textvariable=self.music_var, width=34, relief="flat").pack(side="left")
        tk.Button(m_row, text="…", width=2, command=self._browse_music, cursor="hand2", relief="flat").pack(side="left", padx=4)
        tk.Button(m_row, text="✕", width=2,
                  command=lambda: (self.music_var.set(""), setattr(self, "music_path", ""))
                  ).pack(side="left")
        m2 = tk.Frame(music_lf); m2.pack(fill="x", pady=4)
        self.fade_music_var = tk.BooleanVar(value=True)
        tk.Checkbutton(m2, text=t("slideshow.fade_music_checkbox"),
                       variable=self.fade_music_var).pack(side="left")
        tk.Label(m2, text=f"  {t('slideshow.volume_label')}").pack(side="left")
        self.music_vol_var = tk.DoubleVar(value=0.7)
        tk.Scale(m2, variable=self.music_vol_var, from_=0.1, to=1.5,
                 resolution=0.05, orient="horizontal", length=120).pack(side="left")

    # ── Options panel ─────────────────────────────────────────────────────
    def _build_options_panel(self, parent):
        tk.Label(parent, text="OPTIONS", font=(UI_FONT, 9, "bold"),
                 fg=CLR["fgdim"]).pack(anchor="w", padx=8, pady=(6, 2))

        # Timing
        time_lf = tk.LabelFrame(parent, text=f"  ⏱  {t('slideshow.timing_section')}  ",
                                 padx=12, pady=8)
        time_lf.pack(fill="x", padx=8, pady=4)

        t0 = tk.Frame(time_lf); t0.pack(fill="x", pady=2)
        tk.Label(t0, text=t("slideshow.duration_label"),
                 font=(UI_FONT, 10, "bold")).pack(side="left")
        self.dur_var = tk.StringVar(value="4")
        tk.Entry(t0, textvariable=self.dur_var, width=5, relief="flat").pack(side="left", padx=6)
        for d in ["2","3","4","5","6","8","10"]:
            tk.Button(t0, text=f"{d}s", width=3, bg="#333", fg=CLR["fg"],
                      font=(UI_FONT, 8),
                      command=lambda v=d: self.dur_var.set(v)).pack(side="left", padx=1)

        t1 = tk.Frame(time_lf); t1.pack(fill="x", pady=2)
        tk.Label(t1, text=t("slideshow.transition_duration_label")).pack(side="left")
        self.trans_dur_var = tk.StringVar(value="1.0")
        tk.Entry(t1, textvariable=self.trans_dur_var, width=5, relief="flat").pack(side="left", padx=6)

        # Ken Burns
        kb_lf = tk.LabelFrame(parent, text=f"  🎥  {t('slideshow.ken_burns_section')}  ",
                               padx=12, pady=8)
        kb_lf.pack(fill="x", padx=8, pady=4)

        self.kb_var = tk.StringVar(value=list(KEN_BURNS_MODES.keys())[0])
        ttk.Combobox(kb_lf, textvariable=self.kb_var,
                     values=list(KEN_BURNS_MODES.keys()),
                     state="readonly", width=32).pack(anchor="w")

        kb_str_row = tk.Frame(kb_lf); kb_str_row.pack(fill="x", pady=4)
        tk.Label(kb_str_row, text=t("slideshow.zoom_amount_label")).pack(side="left")
        self.kb_zoom_var = tk.DoubleVar(value=1.1)
        tk.Scale(kb_str_row, variable=self.kb_zoom_var, from_=1.0, to=1.5,
                 resolution=0.01, orient="horizontal", length=200).pack(side="left", padx=6)
        self.kb_lbl = tk.Label(kb_str_row, text="1.10×", width=6, fg=CLR["accent"])
        self.kb_lbl.pack(side="left")
        self.kb_zoom_var.trace_add("write", lambda *_: self.kb_lbl.config(
            text=f"{self.kb_zoom_var.get():.2f}×"))

        # Transitions
        trans_lf = tk.LabelFrame(parent, text=f"  🔀  {t('slideshow.transition_section')}  ",
                                  padx=12, pady=8)
        trans_lf.pack(fill="x", padx=8, pady=4)

        self.trans_var = tk.StringVar(value="Crossfade")
        ttk.Combobox(trans_lf, textvariable=self.trans_var,
                     values=list(TRANSITIONS.keys()),
                     state="readonly", width=24).pack(anchor="w")

        # Resolution & quality
        rq_lf = tk.LabelFrame(parent, text=f"  📐  {t('slideshow.output_settings_section')}  ",
                               padx=12, pady=8)
        rq_lf.pack(fill="x", padx=8, pady=4)

        rq0 = tk.Frame(rq_lf); rq0.pack(fill="x", pady=2)
        tk.Label(rq0, text=t("common.resolution")).pack(side="left")
        self.res_var = tk.StringVar(value=list(RESOLUTIONS.keys())[0])
        ttk.Combobox(rq0, textvariable=self.res_var,
                     values=list(RESOLUTIONS.keys()),
                     state="readonly", width=28).pack(side="left", padx=6)

        rq1 = tk.Frame(rq_lf); rq1.pack(fill="x", pady=2)
        tk.Label(rq1, text=t("batch_joiner.lbl_fps")).pack(side="left")
        self.fps_var = tk.StringVar(value="30")
        ttk.Combobox(rq1, textvariable=self.fps_var,
                     values=["24","25","30","50","60"],
                     state="readonly", width=6).pack(side="left", padx=4)
        tk.Label(rq1, text=t("rotate_flip.crf")).pack(side="left")
        self.crf_var = tk.StringVar(value="18")
        tk.Entry(rq1, textvariable=self.crf_var, width=4, relief="flat").pack(side="left", padx=4)

        # Caption style
        cap_lf2 = tk.LabelFrame(parent, text=f"  💬  {t('slideshow.caption_style_section')}  ",
                                 padx=12, pady=6)
        cap_lf2.pack(fill="x", padx=8, pady=4)

        cs = tk.Frame(cap_lf2); cs.pack(fill="x")
        self.cap_on_var = tk.BooleanVar(value=True)
        tk.Checkbutton(cs, text=t("slideshow.show_captions_checkbox"),
                       variable=self.cap_on_var).pack(side="left")
        tk.Label(cs, text=t("slideshow.size")).pack(side="left")
        self.cap_size_var = tk.StringVar(value="40")
        tk.Entry(cs, textvariable=self.cap_size_var, width=4, relief="flat").pack(side="left", padx=4)
        tk.Label(cs, text=t("slideshow.position")).pack(side="left")
        self.cap_pos_var = tk.StringVar(value="Bottom Centre")
        ttk.Combobox(cs, textvariable=self.cap_pos_var,
                     values=[t("hard_subber.hard_subber_bottom_centre"),t("hard_subber.hard_subber_top_centre"),t("hard_subber.hard_subber_bottom_left"),t("slideshow.slideshow_lower_third")],
                     state="readonly", width=14).pack(side="left", padx=4)

        # Output & render
        of = tk.Frame(parent); of.pack(fill="x", padx=8, pady=6)
        tk.Label(of, text=t("encode_queue.output_label"), font=(UI_FONT, 10, "bold")).pack(side="left")
        self.out_var = tk.StringVar()
        tk.Entry(of, textvariable=self.out_var, width=36, relief="flat").pack(side="left", padx=6)
        tk.Button(of, text=t("common.save_as"), command=self._browse_out, cursor="hand2", relief="flat").pack(side="left")

        self.btn_render = tk.Button(
            parent, text=t("slideshow.render_button"),
            font=(UI_FONT, 12, "bold"), bg=CLR["green"], fg="white",
            height=2, command=self._render)
        self.btn_render.pack(fill="x", padx=8, pady=6)

        self.prog_lbl = tk.Label(parent, text="", fg=CLR["accent"],
                                  font=(UI_FONT, 9, "bold"))
        self.prog_lbl.pack()

        cf = tk.Frame(parent); cf.pack(fill="both", expand=True, padx=8, pady=4)
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

    # ─────────────────────────────────────────────────────────────────────
    def _add_images(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp *.tiff"),
                       ("All", t("ducker.item_2"))])
        for p in paths:
            if p not in self.image_paths:
                self.image_paths.append(p)
                self.listbox.insert(tk.END, f"  {os.path.basename(p)}")
        self._update_count()

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if not folder: return
        exts = {".jpg",".jpeg",".png",".bmp",".webp",".tiff",".tif"}
        for f in sorted(os.listdir(folder)):
            if os.path.splitext(f)[1].lower() in exts:
                full = os.path.join(folder, f)
                if full not in self.image_paths:
                    self.image_paths.append(full)
                    self.listbox.insert(tk.END, f"  {f}")
        self._update_count()

    def _move_up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0: return
        i = sel[0]
        self.image_paths[i], self.image_paths[i-1] = self.image_paths[i-1], self.image_paths[i]
        txt = self.listbox.get(i); prev = self.listbox.get(i-1)
        self.listbox.delete(i-1, i)
        self.listbox.insert(i-1, txt); self.listbox.insert(i, prev)
        self.listbox.selection_set(i-1)

    def _move_down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= self.listbox.size()-1: return
        i = sel[0]
        self.image_paths[i], self.image_paths[i+1] = self.image_paths[i+1], self.image_paths[i]
        txt = self.listbox.get(i); nxt = self.listbox.get(i+1)
        self.listbox.delete(i, i+1)
        self.listbox.insert(i, nxt); self.listbox.insert(i+1, txt)
        self.listbox.selection_set(i+1)

    def _remove_sel(self):
        sel = self.listbox.curselection()
        if sel:
            i = sel[0]
            self.image_paths.pop(i)
            self.listbox.delete(i)
            if i in self.captions: del self.captions[i]
        self._update_count()

    def _clear_all(self):
        self.image_paths.clear()
        self.captions.clear()
        self.listbox.delete(0, tk.END)
        self._update_count()

    def _update_count(self):
        n = len(self.image_paths)
        self.count_lbl.config(text=f"{n} slide{'s' if n != 1 else ''}")

    def _on_slide_select(self, _=None):
        sel = self.listbox.curselection()
        if sel:
            self.cap_var.set(self.captions.get(sel[0], ""))

    def _save_caption(self):
        sel = self.listbox.curselection()
        if sel:
            self.captions[sel[0]] = self.cap_var.get()

    def _browse_music(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio", "*.mp3 *.aac *.wav *.flac *.ogg"), ("All",t("ducker.item_2"))])
        if p:
            self.music_path = p
            self.music_var.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".mp4",
                                          filetypes=[("MP4","*.mp4")])
        if p: self.out_var.set(p)

    # ── Render ───────────────────────────────────────────────────────────
    def _render(self):
        if len(self.image_paths) < 2:
            messagebox.showwarning(t("common.warning"),
                                   "Add at least 2 images to create a slideshow.")
            return
        out = self.out_var.get().strip()
        if not out:
            out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                               filetypes=[("MP4","*.mp4")])
        if not out: return
        self.out_var.set(out)

        self.btn_render.config(state="disabled", text=t("crossfader.rendering"))
        self.run_in_thread(self._render_worker, out)

    def _render_worker(self, out):
        ffmpeg  = get_binary_path("ffmpeg.exe")
        w, h    = RESOLUTIONS[self.res_var.get()]
        fps     = self.fps_var.get()
        dur     = float(self.dur_var.get() or "4")
        td      = float(self.trans_dur_var.get() or "1")
        crf     = self.crf_var.get()
        kb_mode = KEN_BURNS_MODES[self.kb_var.get()]
        zoom    = self.kb_zoom_var.get()
        trans   = TRANSITIONS[self.trans_var.get()]
        tmp_dir = tempfile.mkdtemp()
        n       = len(self.image_paths)

        try:
            # Step 1: render each slide to a short clip
            slide_clips = []
            for i, img_path in enumerate(self.image_paths):
                self.after(0, lambda i=i: self.prog_lbl.config(
                    text=f"Rendering slide {i+1}/{n}…"))
                self.log(self.console, f"[{i+1}/{n}] {os.path.basename(img_path)}")

                clip_path = os.path.join(tmp_dir, f"slide_{i:04d}.mp4")
                slide_clips.append(clip_path)

                # Ken Burns filter
                frames = int(dur * int(fps))
                if kb_mode == "static":
                    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
                else:
                    z_end = zoom
                    if kb_mode == "zoom_in":
                        z_expr = f"zoom+0.0015"
                        x_expr = "iw/2-(iw/zoom/2)"
                        y_expr = "ih/2-(ih/zoom/2)"
                    elif kb_mode == "zoom_out":
                        z_expr = f"if(lte(zoom,1.0),{z_end},{z_end}-0.0015)"
                        x_expr = "iw/2-(iw/zoom/2)"
                        y_expr = "ih/2-(ih/zoom/2)"
                    elif kb_mode == "pan_right":
                        z_expr = str(z_end)
                        x_expr = f"if(lte(x,iw-iw/zoom),x+1,iw-iw/zoom)"
                        y_expr = "ih/2-(ih/zoom/2)"
                    elif kb_mode == "pan_left":
                        z_expr = str(z_end)
                        x_expr = f"if(gte(x,0),x-1,0)"
                        y_expr = "ih/2-(ih/zoom/2)"
                    elif kb_mode == "pan_up":
                        z_expr = str(z_end)
                        x_expr = "iw/2-(iw/zoom/2)"
                        y_expr = f"if(gte(y,0),y-1,0)"
                    else:  # random - alternate
                        if i % 2 == 0:
                            z_expr = "zoom+0.001"; x_expr = "iw/2-(iw/zoom/2)"; y_expr = "ih/2-(ih/zoom/2)"
                        else:
                            z_expr = str(z_end); x_expr = "if(lte(x,iw-iw/zoom),x+1,iw-iw/zoom)"; y_expr = "ih/2-(ih/zoom/2)"

                    vf = (f"scale={int(w*z_end)}:{int(h*z_end)}:force_original_aspect_ratio=increase,"
                          f"crop={w}:{h},setsar=1,"
                          f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
                          f":d={frames}:s={w}x{h}:fps={fps}")

                # Caption
                cap = self.captions.get(i, "")
                if cap and self.cap_on_var.get():
                    cap_safe  = cap.replace("'", "").replace(":", "\\:")
                    cap_size  = self.cap_size_var.get()
                    cap_pos   = self.cap_pos_var.get()
                    if cap_pos == "Bottom Centre":
                        cx, cy = "(w-text_w)/2", "h-text_h-30"
                    elif cap_pos == "Top Centre":
                        cx, cy = "(w-text_w)/2", "30"
                    elif cap_pos == "Lower Third":
                        cx, cy = "80", "h*0.75"
                    else:
                        cx, cy = "30", "h-text_h-30"
                    vf += (f",drawtext=text='{cap_safe}':fontsize={cap_size}:"
                           f"fontcolor=white:box=1:boxcolor=black@0.5:"
                           f"x={cx}:y={cy}")

                cmd = [ffmpeg, "-loop", "1", "-i", img_path,
                       "-vf", vf, "-t", str(dur),
                       t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                       "-pix_fmt", "yuv420p", "-an", clip_path, "-y"]
                r = subprocess.run(cmd, capture_output=True,
                                   creationflags=CREATE_NO_WINDOW)
                if r.returncode != 0:
                    self.log(self.console,
                             f"  ⚠ Slide {i+1} failed:\n{r.stderr.decode()[-300:]}")

            # Step 2: concatenate with transitions (xfade)
            self.after(0, lambda: self.prog_lbl.config(text=t("slideshow.joining_slides")))
            self.log(self.console, t("log.slideshow.joining_clips_with_transitions"))

            if trans and len(slide_clips) > 1:
                # Build filter_complex xfade chain
                inputs = " ".join(f"-i {c}" for c in slide_clips)
                n_clips = len(slide_clips)
                fc_parts = []
                last = "[0:v]"
                offset = dur - td
                for j in range(1, n_clips):
                    out_tag = "[v]" if j == n_clips-1 else f"[vt{j}]"
                    fc_parts.append(
                        f"{last}[{j}:v]xfade=transition={trans}"
                        f":duration={td}:offset={offset:.3f}{out_tag}")
                    last = f"[vt{j}]"
                    offset += dur - td
                fc = ";".join(fc_parts)

                cmd_join = [ffmpeg]
                for c in slide_clips:
                    cmd_join += ["-i", c]
                cmd_join += ["-filter_complex", fc,
                             "-map", "[v]",
                             "-c:v", "libx264", "-crf", crf, "-preset", "fast",
                             "-pix_fmt", "yuv420p"]
            else:
                # Simple concat
                list_path = os.path.join(tmp_dir, "list.txt")
                with open(list_path, "w") as f:
                    for c in slide_clips:
                        f.write(f"file '{c}'\n")
                cmd_join = [ffmpeg, "-f", "concat", "-safe", "0",
                            "-i", list_path,
                            t("dynamics.c_v"), "libx264", "-crf", crf, "-preset", "fast",
                            "-pix_fmt", "yuv420p"]

            tmp_vid = os.path.join(tmp_dir, "video_only.mp4")
            cmd_join += [tmp_vid, "-y"]
            r = subprocess.run(cmd_join, capture_output=True,
                               creationflags=CREATE_NO_WINDOW)
            if r.returncode != 0:
                self.log(self.console, f"Join failed:\n{r.stderr.decode()[-400:]}")
                self.after(0, lambda: self.show_result(1))
                return

            # Step 3: add music if present
            if self.music_path and os.path.exists(self.music_path):
                self.log(self.console, t("log.slideshow.adding_music"))
                vol  = self.music_vol_var.get()
                fade = self.fade_music_var.get()

                # Get total video duration
                ffprobe = get_binary_path("ffprobe.exe")
                rr = subprocess.run(
                    [ffprobe,"-v","error","-show_entries","format=duration",
                     "-of","json", tmp_vid],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW)
                total_dur = float(json.loads(rr.stdout).get("format",{}).get("duration",0) or 0)

                af = f"volume={vol:.2f}"
                if fade and total_dur > 2:
                    af += f",afade=t=out:st={max(0,total_dur-2):.2f}:d=2"

                cmd_mux = [ffmpeg, "-i", tmp_vid,
                           "-stream_loop", "-1", "-i", self.music_path,
                           "-af", af,
                           t("dynamics.c_v"), "copy", t("dynamics.c_a"), "aac", t("dynamics.b_a"), "192k",
                           "-shortest", "-movflags", t("dynamics.faststart"), out, "-y"]
            else:
                cmd_mux = [ffmpeg, "-i", tmp_vid,
                           "-c", "copy", "-an", "-movflags", t("dynamics.faststart"), out, "-y"]

            r_final = subprocess.run(cmd_mux, capture_output=True,
                                     creationflags=CREATE_NO_WINDOW)

            # Cleanup
            try: shutil.rmtree(tmp_dir)
            except Exception: pass

            self.after(0, lambda: self.show_result(r_final.returncode, out))
            self.after(0, lambda: self.prog_lbl.config(
                text=t("slideshow.slideshow_complete") if r_final.returncode == 0 else "❌  Failed"))

        except Exception as e:
            self.log(self.console, f"❌  Error: {e}")
            self.after(0, lambda: self.show_result(1))
        finally:
            self.after(0, lambda: self.btn_render.config(
                state="normal", text=t("slideshow.render_button")))
