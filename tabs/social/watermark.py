import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import subprocess
import os
import math
from tabs.base_tab import BaseTab, CLR, UI_FONT, MONO_FONT
from core.hardware import get_binary_path
from core.i18n import t

class TextBurnerTab(BaseTab):
    def __init__(self, parent):
        super().__init__(parent)
        self.file_path = ""
        self.preview_proc = None
        
        # --- Variables ---
        self.text_var = tk.StringVar(value="STUDIO PRO")
        self.font_size = tk.StringVar(value="64")
        
        # Typography
        self.font_var = tk.StringVar(value="Montserrat")
        self.color_var = tk.StringVar(value="#FFFFFF")
        self.opacity_var = tk.DoubleVar(value=1.0)
        self.is_bold = tk.BooleanVar(value=False)
        self.is_italic = tk.BooleanVar(value=False)
        self.shadow_var = tk.BooleanVar(value=True)
        self.outline_var = tk.BooleanVar(value=True)
        
        # Position & Motion
        self.pos_var = tk.StringVar(value="Center")
        self.custom_x = tk.StringVar(value="100")
        self.custom_y = tk.StringVar(value="100")
        self.angle_var = tk.StringVar(value="45")
        
        # Random Jumper Settings
        self.jump_freq = tk.StringVar(value="3") # Jump every X seconds
        self.rand_timing = tk.BooleanVar(value=False)
        self.jump_min = tk.StringVar(value="1")
        self.jump_max = tk.StringVar(value="5")
        
        # Timing Variables
        self.timing_mode = tk.StringVar(value="Always") 
        self.time_ranges = tk.StringVar(value="0-5, 20-25")
        self.fade_var = tk.BooleanVar(value=True)

        self.build_ui()
        
        # Listener to dynamically show/hide inputs when dropdown changes
        self.pos_var.trace_add("write", self.on_pos_change)
        self.rand_timing.trace_add("write", self.on_pos_change)

    def build_ui(self):
        top_f = tk.Frame(self); top_f.pack(pady=10)
        tk.Label(top_f, text=t("common.source_video")).pack(side="left")
        self.ent_path = tk.Entry(top_f, width=50, relief="flat")
        self.ent_path.pack(side="left", padx=5)
        tk.Button(top_f, text=t("btn.browse"), command=self.load_file, cursor="hand2", relief="flat").pack(side="left")

        # --- STYLE PANEL ---
        style_f = tk.LabelFrame(self, text=f" {t('watermark.typography_section')} ", padx=15, pady=10)
        style_f.pack(pady=5, padx=20, fill="x")

        tk.Label(style_f, text=t("intro_maker.text_label")).grid(row=0, column=0, sticky="w")
        tk.Entry(style_f, textvariable=self.text_var, width=30, relief="flat").grid(row=0, column=1, columnspan=2, sticky="w", pady=5)

        # Updated to exactly match your downloaded font folder!
        font_list = [
            "Anton", "Bangers", "BebasNeue", "Bungee", "Impact", 
            "Inter", "Lato", "LuckiestGuy", "Montserrat", "OpenSans", 
            "Poppins", "Raleway", "RobotoBlack", "TheBoldFont"
        ]
        
        tk.Label(style_f, text=t("hard_subber.font_label")).grid(row=1, column=0, sticky="w")
        ttk.Combobox(style_f, textvariable=self.font_var, values=font_list, state="readonly", width=15).grid(row=1, column=1, sticky="w")

        tk.Button(style_f, text=t("watermark.pick_color"), command=self.pick_color, cursor="hand2", relief="flat").grid(row=0, column=3, padx=10)
        
        tk.Checkbutton(style_f, text="Bold", variable=self.is_bold).grid(row=1, column=2, sticky="w")
        tk.Checkbutton(style_f, text="Italic", variable=self.is_italic).grid(row=1, column=3, sticky="w")
        
        # New FX
        fx_frame = tk.Frame(style_f)
        fx_frame.grid(row=2, column=1, columnspan=3, sticky="w", pady=5)
        tk.Checkbutton(fx_frame, text=t("watermark.drop_shadow"), variable=self.shadow_var).pack(side="left", padx=5)
        tk.Checkbutton(fx_frame, text=t("watermark.black_outline"), variable=self.outline_var).pack(side="left", padx=5)
        
        tk.Label(style_f, text=t("watermark.opacity_label")).grid(row=2, column=4, sticky="w")
        tk.Scale(style_f, from_=0.1, to=1.0, resolution=0.1, orient="horizontal", variable=self.opacity_var).grid(row=2, column=5)

        # --- ANIMATION & POSITION PANEL ---
        anim_f = tk.LabelFrame(self, text=f" {t('watermark.position_section')} ", padx=15, pady=10)
        anim_f.pack(pady=5, padx=20, fill="x")

        pos_options = [
            t("watermark.top_left"), t("watermark.top_right"), t("watermark.top_center"), 
            t("hard_subber.bottom_left"), t("hard_subber.bottom_right"), t("watermark.bottom_center"), 
            "Center", t("watermark.custom_coordinates"), 
            t("watermark.bouncing_dvd_mode"), t("watermark.random_jumps")
        ]
        ttk.Combobox(anim_f, textvariable=self.pos_var, values=pos_options, state="readonly", width=20).grid(row=0, column=0, padx=5)
        
        tk.Label(anim_f, text=t("hard_subber.size_label")).grid(row=0, column=1, padx=5)
        tk.Entry(anim_f, textvariable=self.font_size, width=5, relief="flat").grid(row=0, column=2)

        # Dynamic Options Frame (This changes based on dropdown)
        self.dyn_f = tk.Frame(anim_f)
        self.dyn_f.grid(row=1, column=0, columnspan=5, sticky="w", pady=10)

        # --- TIMING PANEL ---
        time_f = tk.LabelFrame(self, text=f" {t('watermark.timing_section')} ", padx=15, pady=10)
        time_f.pack(pady=5, padx=20, fill="x")

        tk.Radiobutton(time_f, text=t("watermark.always_visible"), variable=self.timing_mode, value="Always").grid(row=0, column=0, sticky="w")
        tk.Radiobutton(time_f, text=t("watermark.specific_seconds"), variable=self.timing_mode, value="Specific").grid(row=1, column=0, sticky="w")
        
        tk.Entry(time_f, textvariable=self.time_ranges, width=20, relief="flat").grid(row=1, column=1, padx=5)
        tk.Label(time_f, text=t("watermark.e_g_0_5_15_20"), font=(UI_FONT, 8)).grid(row=1, column=2)

        tk.Checkbutton(time_f, text=t("watermark.smooth_fade_in_out"), variable=self.fade_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        # Action Buttons
        btn_f = tk.Frame(self); btn_f.pack(pady=20)
        tk.Button(btn_f, text=t("watermark.preview"), bg=CLR["accent"], fg="white", width=15, command=self.preview_text, cursor="hand2", relief="flat").pack(side="left", padx=10)
        self.btn_render = tk.Button(btn_f, text=t("watermark.render"), bg="#E91E63", fg="white", width=15, font=(UI_FONT, 10, "bold"), command=self.run_render, cursor="hand2", relief="flat")
        self.btn_render.pack(side="left", padx=10)

        # Console
        cf = tk.Frame(self); cf.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.console, csb = self.make_console(cf, height=6)
        self.console.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")

        # Initialize dynamic frame state
        self.on_pos_change()

    def on_pos_change(self, *args):
        """Clears and rebuilds the dynamic input frame based on Position selection."""
        for widget in self.dyn_f.winfo_children():
            widget.destroy()

        mode = self.pos_var.get()
        if mode == t("watermark.custom_coordinates"):
            tk.Label(self.dyn_f, text=t("watermark.x_pos")).pack(side="left")
            tk.Entry(self.dyn_f, textvariable=self.custom_x, width=6, relief="flat").pack(side="left", padx=5)
            tk.Label(self.dyn_f, text=t("watermark.y_pos")).pack(side="left")
            tk.Entry(self.dyn_f, textvariable=self.custom_y, width=6, relief="flat").pack(side="left", padx=5)

        elif mode == t("watermark.bouncing_dvd_mode"):
            tk.Label(self.dyn_f, text=t("watermark.bounce_angle_deg")).pack(side="left")
            tk.Entry(self.dyn_f, textvariable=self.angle_var, width=6, relief="flat").pack(side="left", padx=5)

        elif mode == t("watermark.random_jumps"):
            tk.Label(self.dyn_f, text=t("watermark.jump_every")).pack(side="left")
            tk.Entry(self.dyn_f, textvariable=self.jump_freq, width=4, relief="flat").pack(side="left", padx=2)
            tk.Label(self.dyn_f, text="secs").pack(side="left", padx=(0, 15))
            
            tk.Checkbutton(self.dyn_f, text=t("watermark.randomize_interval"), variable=self.rand_timing).pack(side="left")
            
            if self.rand_timing.get():
                tk.Label(self.dyn_f, text=t("watermark.min")).pack(side="left")
                tk.Entry(self.dyn_f, textvariable=self.jump_min, width=4, relief="flat").pack(side="left")
                tk.Label(self.dyn_f, text=t("watermark.max")).pack(side="left")
                tk.Entry(self.dyn_f, textvariable=self.jump_max, width=4, relief="flat").pack(side="left")

    def pick_color(self):
        color = colorchooser.askcolor(title="Select Watermark Color")[1]
        if color: self.color_var.set(color)

    def get_font_path(self):
        # This file lives at tabs/social/watermark.py — go up THREE levels to reach project root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Get the base name from the dropdown (e.g. "BebasNeue")
        font_base = self.font_var.get().replace(" ", "")
        
        # Check if Bold is requested
        if self.is_bold.get():
            # Try to find the specific bold version (e.g. "Montserrat-Bold.ttf")
            bold_path = os.path.join(base_dir, "assets", "fonts", f"{font_base}-Bold.ttf")
            if os.path.exists(bold_path):
                return bold_path
                
        # If not bold, or if the bold version doesn't exist, try the standard name
        normal_path = os.path.join(base_dir, "assets", "fonts", f"{font_base}.ttf")
        if os.path.exists(normal_path):
            return normal_path
            
        # Ultimate Fallback if someone deletes a file by accident
        fallback = os.path.join(base_dir, "assets", "fonts", "Montserrat.ttf")
        return fallback if os.path.exists(fallback) else None

    def get_filter_string(self):
        font_p = self.get_font_path()
        if not font_p: return None
        safe_p = font_p.replace("\\", "/").replace(":", "\\:")
        
        txt = self.text_var.get().replace("'", "")
        size = self.font_size.get()
        pos = self.pos_var.get()
        
        color_val = self.color_var.get().replace("#", "")
        base_alpha = self.opacity_var.get()

        # 1. Coordinate Logic
        x, y = "(w-text_w)/2", "(h-text_h)-50"
        
        if pos == t("watermark.top_left"): x, y = "50", "50"
        elif pos == t("watermark.top_right"): x, y = "(w-text_w)-50", "50"
        elif pos == t("hard_subber.bottom_left"): x, y = "50", "(h-text_h)-50"
        elif pos == t("hard_subber.bottom_right"): x, y = "(w-text_w)-50", "(h-text_h)-50"

        elif pos == t("watermark.custom_coordinates"):
            x, y = self.custom_x.get(), self.custom_y.get()

        elif pos == t("watermark.bouncing_dvd_mode"):
            angle = float(self.angle_var.get() or 45)
            vx, vy = 300 * math.cos(math.radians(angle)), 300 * math.sin(math.radians(angle))
            x = f"'(abs(mod({vx}*t, 2*(w-text_w))-(w-text_w)))'"
            y = f"'(abs(mod({vy}*t, 2*(h-text_h))-(h-text_h)))'"

        elif pos == t("watermark.random_jumps"):
            # The insane math for pseudo-random jumping
            if self.rand_timing.get():
                min_v = float(self.jump_min.get() or 1)
                max_v = float(self.jump_max.get() or 5)
                # Uses a sine wave to smoothly oscillate the jump interval between min and max
                freq = f"({min_v}+abs(sin(t/10))*({max_v}-{min_v}))"
            else:
                freq = str(float(self.jump_freq.get() or 3))
                
            # THE FIX: Deterministic Sine-Wave Hashing
            # mod(abs(sin(SEED)*43758), 1) generates a stable random number between 0.0 and 1.0
            # It ONLY generates a new number when trunc(t/freq) increments to the next integer.
            x = f"'(mod(abs(sin((trunc(t/{freq})+11)*12.9898)*43758.5453),1)*(w-text_w))'"
            y = f"'(mod(abs(sin((trunc(t/{freq})+17)*78.233)*43758.5453),1)*(h-text_h))'"

        # 2. Styling (Shadow / Outline)
        style_str = ""
        if self.shadow_var.get():
            style_str += ":shadowcolor=black@0.8:shadowx=4:shadowy=4"
        if self.outline_var.get():
            style_str += ":bordercolor=black@0.9:borderw=3"

        # 3. Alpha Math Logic
        if self.timing_mode.get() == "Specific":
            ranges = self.time_ranges.get().replace(" ", "").split(",")
            logic_parts = []
            for r in ranges:
                if "-" in r:
                    start, end = r.split("-")
                    if self.fade_var.get():
                        logic_parts.append(f"between(t,{start},{end})*min(min(t-{start},1),min({end}-t,1))")
                    else:
                        logic_parts.append(f"between(t,{start},{end})")
            
            combined_logic = " + ".join(logic_parts)
            alpha_val = f"'{base_alpha}*({combined_logic})'"
        else:
            alpha_val = str(base_alpha)

        return (f"drawtext=fontfile='{safe_p}':text='{txt}':fontsize={size}:"
                f"x={x}:y={y}:fontcolor=0x{color_val}:alpha={alpha_val}{style_str}")

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[(t("silence.video_files"), "*.mp4 *.mov *.mkv *.avi")])
        if path:
            self.file_path = path
            self.ent_path.delete(0, tk.END)
            self.ent_path.insert(0, path)

    def preview_text(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("watermark.no_source_message"))
            return
        f_str = self.get_filter_string()
        if not f_str:
            messagebox.showerror(t("common.warning"),
                                 "Font file not found in assets/fonts/. Pick a different font or restore the missing TTF.")
            return
        if self.preview_proc:
            try: self.preview_proc.terminate()
            except Exception: pass

        ffplay = get_binary_path("ffplay.exe")
        cmd = [
            ffplay, "-i", os.path.normpath(self.file_path), 
            "-vf", f"format=yuv420p,{f_str}", 
            "-window_title", "Preview", "-x", "800", "-autoexit"
        ]
        
        app = self.winfo_toplevel()
        if hasattr(app, "log_debug"):
            app.log_debug(f"RUNNING: {' '.join(cmd)}")
            
        self.preview_proc = subprocess.Popen(cmd)

    def run_render(self):
        if not self.file_path:
            messagebox.showwarning(t("common.warning"), t("watermark.no_source_message"))
            return
        f_str = self.get_filter_string()
        if not f_str:
            messagebox.showerror(t("common.warning"),
                                 "Font file not found in assets/fonts/. Pick a different font or restore the missing TTF.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".mp4",
                                           filetypes=[("MP4", "*.mp4")])
        if not out: return
        cmd = [get_binary_path("ffmpeg.exe"), "-i", self.file_path,
               "-vf", f"format=yuv420p,{f_str}",
               t("dynamics.c_v"), "libx264", "-crf", "18", t("dynamics.c_a"), "copy",
               "-movflags", t("dynamics.faststart"), out, "-y"]
        self.log(self.console, f"Rendering → {os.path.basename(out)}")
        self.run_ffmpeg(cmd, self.console,
                        on_done=lambda rc: self.show_result(rc, out),
                        btn=self.btn_render, btn_label="🔥 RENDER")