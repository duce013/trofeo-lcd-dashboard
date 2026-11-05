"""Settings window for the LCD dashboard (CustomTkinter). Edits custom.json; the dashboard
picks changes up within one refresh (~2 s)."""
from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import lcd_dashboard as dash
import media
import updater
from version import VERSION

ORIENT = {"Vertical": "portrait", "Horizontal": "landscape"}

HERE = os.path.dirname(os.path.abspath(__file__))  # in the exe this is the unpack folder
LOGO_PNG, LOGO_ICO = os.path.join(HERE, "duce.png"), os.path.join(HERE, "duce.ico")

NAMES = {"ram": "Memory", "hw": "Hardware", "media": "Video / animation",
         "claude": "Claude", "notes": "Notes"}
COLOR_NAMES = {"accent": "Accent", "bg": "Background", "card": "Card", "fg": "Text", "dim": "Muted text",
               "edge": "Border", "track": "Bar track", "warn": "Warning", "bad": "Critical"}
PRESETS = {
    "Cyan ROG": dash.DEFAULT_THEME,
    "ROG Red": {"accent": "#ff2a3d", "edge": "#4b1218", "track": "#2a0e12", "card": "#100607", "bg": "#070304"},
    "Purple": {"accent": "#b46bff", "edge": "#33204b", "track": "#1c1229", "card": "#0c0812", "bg": "#060409"},
    "Green": {"accent": "#39ff88", "edge": "#134b2c", "track": "#0e2a19", "card": "#06100a", "bg": "#030704"},
    "White": {"accent": "#ffffff", "edge": "#3a4248", "track": "#1e2428", "card": "#0b0e10", "bg": "#050607"},
}

# window palette (same family as the LCD)
WIN, SIDE, CARD, BORDER = "#070c10", "#0a1217", "#0e171d", "#16303a"
FG, DIM, ACC, ACC_DARK, HOVER = "#e8f8fb", "#6f8c95", "#2ee6f2", "#0d3a40", "#13262e"
PAGES = [("layout", "Layout", "▤"), ("media", "Video", "▶"), ("colors", "Colors", "◐"),
         ("devices", "Devices", "▣"), ("notes", "Notes", "✎")]


def save(cfg):
    os.makedirs(dash.DATA_DIR, exist_ok=True)
    tmp = dash.CUSTOM_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if k != "error"}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dash.CUSTOM_PATH)  # atomic: the dashboard never reads half a file


def font(size=13, weight="normal", num=False):
    return ctk.CTkFont(family="Bahnschrift" if num else "Segoe UI", size=size, weight=weight)


def thumbnail(path, size=(420, 236)):
    """First frame of a video (or the image itself), cover-fitted for the preview card."""
    try:
        if os.path.splitext(path)[1].lower() in media.IMAGE_EXT:
            img = Image.open(path).convert("RGB")
        else:
            cap = media.cv2.VideoCapture(path)
            cap.set(media.cv2.CAP_PROP_POS_FRAMES, int(cap.get(media.cv2.CAP_PROP_FRAME_COUNT) or 0) // 3)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return None
            img = Image.fromarray(media.cv2.cvtColor(frame, media.cv2.COLOR_BGR2RGB))
        return media.fit_frame(img, *size, "cover")
    except Exception:
        return None


class Settings:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.cfg = dash.load_custom()
        self.colors = dict(self.cfg["theme"])
        self.show_vars = {s: tk.BooleanVar(value=bool(self.cfg["show"].get(s))) for s in dash.SECTIONS}
        root.title("TrofeoLCD")
        root.geometry("980x680")
        root.minsize(900, 600)
        root.configure(fg_color=WIN)

        side = ctk.CTkFrame(root, width=220, corner_radius=0, fg_color=SIDE)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(anchor="w", padx=18, pady=(24, 0))
        if os.path.isfile(LOGO_PNG):
            self._logo = ctk.CTkImage(Image.open(LOGO_PNG), size=(52, 52))
            ctk.CTkLabel(brand, image=self._logo, text="").pack(side="left", padx=(0, 10))
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        ctk.CTkLabel(names, text="TROFEO", font=font(24, "bold", num=True), text_color=ACC).pack(anchor="w")
        ctk.CTkLabel(names, text="LCD CONTROL · DUCE", font=font(10, num=True), text_color=DIM).pack(anchor="w")
        if os.path.isfile(LOGO_ICO):  # CTk sets its own icon shortly after start, so set ours after it
            root.after(300, lambda: root.iconbitmap(LOGO_ICO))
        ctk.CTkFrame(side, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=22)
        self.nav = {}
        for key, label, icon in PAGES:
            b = ctk.CTkButton(side, text=f"  {icon}   {label}", anchor="w", height=42, corner_radius=10,
                              font=font(14), fg_color="transparent", hover_color=HOVER, text_color=FG,
                              command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=14, pady=3)
            self.nav[key] = b
        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=20)
        self.status = ctk.CTkLabel(bottom, text="", font=font(12), text_color=ACC, wraplength=180, justify="left")
        self.status.pack(anchor="w", pady=(0, 10))
        ver = ctk.CTkFrame(bottom, fg_color="transparent")
        ver.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(ver, text=f"v{VERSION}", font=font(12, num=True), text_color=DIM).pack(side="left")
        self.update_btn = ctk.CTkButton(ver, text="Check for updates", height=28, corner_radius=8, font=font(12),
                                        fg_color="transparent", border_width=1, border_color=BORDER,
                                        hover_color=HOVER, text_color=ACC, command=self.check_update)
        self.update_btn.pack(side="right")
        self.update_info = None
        threading.Thread(target=self._check_quietly, daemon=True).start()
        ctk.CTkButton(bottom, text="Save", height=44, corner_radius=12, font=font(15, "bold"),
                      fg_color=ACC, hover_color="#22c4cf", text_color="#031014", command=self.apply).pack(fill="x")
        ctk.CTkButton(bottom, text="Reset", height=34, corner_radius=10, font=font(12),
                      fg_color="transparent", border_width=1, border_color=BORDER, hover_color=HOVER,
                      text_color=DIM, command=self.reset).pack(fill="x", pady=(8, 0))

        self.body = ctk.CTkFrame(root, fg_color="transparent")
        self.body.pack(side="left", fill="both", expand=True, padx=28, pady=24)
        self.pages = {}
        for key, label, _ in PAGES:
            page = ctk.CTkScrollableFrame(self.body, fg_color="transparent", scrollbar_button_color=HOVER)
            getattr(self, f"page_{key}")(page)
            self.pages[key] = page
        self.show_page("layout")

    # ── building blocks ─────────────────────────────────────────────
    def show_page(self, key):
        for k, p in self.pages.items():
            p.pack_forget()
            self.nav[k].configure(fg_color="transparent", text_color=FG)
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].configure(fg_color=ACC_DARK, text_color=ACC)

    def header(self, parent, title, sub):
        ctk.CTkLabel(parent, text=title, font=font(24, "bold"), text_color=FG).pack(anchor="w")
        ctk.CTkLabel(parent, text=sub, font=font(13), text_color=DIM).pack(anchor="w", pady=(2, 18))

    def card(self, parent, title=None):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        c.pack(fill="x", pady=(0, 14))
        if title:
            ctk.CTkLabel(c, text=title.upper(), font=font(11, "bold", num=True), text_color=ACC).pack(anchor="w", padx=20, pady=(16, 6))
        return c

    def switch(self, parent, text, var):
        return ctk.CTkSwitch(parent, text=text, variable=var, font=font(14), text_color=FG, progress_color=ACC,
                             button_color=FG, button_hover_color="#ffffff", fg_color="#22343c")

    def slider_row(self, parent, label, var, lo, hi, steps):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(4, 16))
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, font=font(14), text_color=FG).pack(side="left")
        val = ctk.CTkLabel(top, text=str(var.get()), font=font(16, "bold", num=True), text_color=ACC)
        val.pack(side="right")
        ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, variable=var, progress_color=ACC,
                      button_color=FG, button_hover_color="#ffffff", fg_color="#22343c",
                      command=lambda v: val.configure(text=str(int(v)))).pack(fill="x", pady=(8, 0))

    # ── pages ───────────────────────────────────────────────────────
    def page_layout(self, p):
        self.header(p, "Layout", "How the screen is mounted and what it shows")
        o = self.card(p, "Orientation")
        now = self.current_orientation() or self.cfg.get("orientation", "portrait")
        self.orient = tk.StringVar(value="Horizontal" if now == "landscape" else "Vertical")
        ctk.CTkSegmentedButton(o, values=list(ORIENT), variable=self.orient, font=font(13), height=36,
                               corner_radius=10, fg_color="#0b1419", selected_color=ACC_DARK,
                               selected_hover_color=ACC_DARK, unselected_color="#0b1419",
                               unselected_hover_color=HOVER, text_color=FG).pack(anchor="w", padx=20, pady=(4, 6))
        ctk.CTkLabel(o, text="Vertical: 462×1920, sections stack top to bottom. Horizontal: 1920×462, sections side by side.",
                     font=font(12), text_color=DIM).pack(anchor="w", padx=20, pady=(0, 16))
        c = self.card(p, "Sections")
        self.rows = ctk.CTkFrame(c, fg_color="transparent")
        self.rows.pack(fill="x", padx=12, pady=(0, 12))
        self.draw_rows()
        c2 = self.card(p, "Sizes")
        self.procs = tk.IntVar(value=int(self.cfg["processes"]))
        self.slider_row(c2, "Processes shown", self.procs, 0, 15, 15)
        self.notes_h = tk.IntVar(value=int(self.cfg["notes_height"]))
        self.slider_row(c2, "Notes height", self.notes_h, 100, 1200, 55)
        ctk.CTkLabel(p, text="The video fills whatever space is left.", font=font(12), text_color=DIM).pack(anchor="w")

    def draw_rows(self):
        for w in self.rows.winfo_children():
            w.destroy()
        order = self.cfg["order"]
        for i, sec in enumerate(order):
            r = ctk.CTkFrame(self.rows, fg_color="#0b1419", corner_radius=10)
            r.pack(fill="x", pady=4)
            ctk.CTkLabel(r, text=f"{i + 1:02d}", font=font(13, "bold", num=True), text_color=DIM, width=34).pack(side="left", padx=(12, 4), pady=10)
            self.switch(r, NAMES[sec], self.show_vars[sec]).pack(side="left", padx=6)
            for sym, d in (("↓", 1), ("↑", -1)):
                ctk.CTkButton(r, text=sym, width=34, height=30, corner_radius=8, font=font(14, "bold"),
                              fg_color="#13232a", hover_color=ACC_DARK, text_color=ACC,
                              state="normal" if 0 <= i + d < len(order) else "disabled",
                              command=lambda i=i, d=d: self.move(i, d)).pack(side="right", padx=(0, 8))

    def move(self, i, d):
        order = self.cfg["order"]
        order[i], order[i + d] = order[i + d], order[i]
        self.draw_rows()

    def page_media(self, p):
        self.header(p, "Video / animation", "Loops in the space at the bottom of the screen")
        m = self.cfg["media"]
        self.media_path = tk.StringVar(value=m.get("path", ""))
        c = self.card(p, "Now playing")
        self.thumb = ctk.CTkLabel(c, text="", width=420, height=236, fg_color="#050a0d", corner_radius=12)
        self.thumb.pack(anchor="w", padx=20, pady=(4, 8))
        self.media_name = ctk.CTkLabel(c, text="", font=font(13), text_color=FG)
        self.media_name.pack(anchor="w", padx=20)
        btns = ctk.CTkFrame(c, fg_color="transparent")
        btns.pack(anchor="w", padx=20, pady=(12, 8))
        ctk.CTkButton(btns, text="Choose file…", height=38, corner_radius=10, font=font(14, "bold"),
                      fg_color=ACC, hover_color="#22c4cf", text_color="#031014", command=self.pick_media).pack(side="left")
        ctk.CTkButton(btns, text="Remove", height=38, corner_radius=10, font=font(13), fg_color="transparent",
                      border_width=1, border_color=BORDER, hover_color=HOVER, text_color=DIM,
                      command=lambda: self.set_media("")).pack(side="left", padx=10)
        self.progress = ctk.CTkProgressBar(c, progress_color=ACC, fg_color="#22343c", height=6)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(4, 18))
        c2 = self.card(p, "Fit")
        self.fit = tk.StringVar(value={"cover": "Fill", "contain": "Fit whole"}[m.get("fit", "cover")])
        ctk.CTkSegmentedButton(c2, values=["Fill", "Fit whole"], variable=self.fit,
                               font=font(13), height=36, corner_radius=10, fg_color="#0b1419",
                               selected_color=ACC_DARK, selected_hover_color=ACC_DARK,
                               unselected_color="#0b1419", unselected_hover_color=HOVER, text_color=FG).pack(anchor="w", padx=20, pady=(4, 18))
        ctk.CTkLabel(p, text="MP4 · MOV · AVI · MKV · WEBM · GIF · PNG · JPG — large videos are shrunk once for the LCD.",
                     font=font(12), text_color=DIM).pack(anchor="w")
        self.set_media(self.media_path.get())

    def set_media(self, path):
        self.media_path.set(path)
        name = os.path.basename(path) if path else "Nothing selected"
        self.media_name.configure(text=name)
        img = thumbnail(path) if path and os.path.isfile(path) else None
        self._thumb_img = ctk.CTkImage(img, size=img.size) if img else None
        self.thumb.configure(image=self._thumb_img, text="" if img else "▶  No video")

    def pick_media(self):
        src = filedialog.askopenfilename(title="Video or animation", filetypes=[
            ("Video / animation / image", "*.mp4 *.mov *.avi *.mkv *.webm *.gif *.m4v *.wmv *.png *.jpg *.jpeg *.webp *.bmp"),
            ("All files", "*.*")])
        if not src:
            return
        self.flash("Preparing video…")
        self.progress.set(0)

        def work():
            try:
                dst = media.prepare(src, progress=lambda f: self.root.after(0, self.progress.set, f))
                self.root.after(0, self.media_ready, dst)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Video", str(e))

        threading.Thread(target=work, daemon=True).start()

    def media_ready(self, dst):
        self.progress.set(1)
        self.set_media(dst)
        self.apply()

    def page_colors(self, p):
        self.header(p, "Colors", "Pick a preset or set each color")
        c = self.card(p, "Presets")
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 14))
        for i, (name, vals) in enumerate(PRESETS.items()):
            t = {**dash.DEFAULT_THEME, **vals}
            tile = ctk.CTkFrame(grid, fg_color=t["card"], corner_radius=12, border_width=2, border_color=t["edge"])
            tile.grid(row=0, column=i, padx=6, sticky="ew")
            grid.grid_columnconfigure(i, weight=1)
            dots = ctk.CTkFrame(tile, fg_color="transparent")
            dots.pack(pady=(14, 6))
            for col in (t["accent"], t["fg"], t["edge"]):
                ctk.CTkFrame(dots, width=14, height=14, corner_radius=7, fg_color=col).pack(side="left", padx=2)
            ctk.CTkLabel(tile, text=name, font=font(12, "bold"), text_color=t["accent"]).pack(pady=(0, 12))
            for w in (tile, dots, *dots.winfo_children(), *tile.winfo_children()):
                w.bind("<Button-1>", lambda e, v=vals: self.set_colors(v))
                w.configure(cursor="hand2")
        c2 = self.card(p, "Custom colors")
        g = ctk.CTkFrame(c2, fg_color="transparent")
        g.pack(fill="x", padx=20, pady=(0, 16))
        self.swatches = {}
        for i, (key, label) in enumerate(COLOR_NAMES.items()):
            r, col = divmod(i, 2)
            cell = ctk.CTkFrame(g, fg_color="transparent")
            cell.grid(row=r, column=col, sticky="w", padx=(0, 30), pady=6)
            sw = ctk.CTkButton(cell, text="", width=36, height=36, corner_radius=18, border_width=2,
                               border_color=BORDER, command=lambda k=key: self.pick_color(k))
            sw.pack(side="left")
            box = ctk.CTkFrame(cell, fg_color="transparent")
            box.pack(side="left", padx=10)
            ctk.CTkLabel(box, text=label, font=font(13), text_color=FG).pack(anchor="w")
            hexl = ctk.CTkLabel(box, text="", font=font(11, num=True), text_color=DIM)
            hexl.pack(anchor="w")
            self.swatches[key] = (sw, hexl)
        self.paint_swatches()

    def set_colors(self, vals):
        self.colors = {**dash.DEFAULT_THEME, **vals}
        self.paint_swatches()
        self.flash("Preset applied — press Save")

    def pick_color(self, key):
        c = colorchooser.askcolor(color=self.colors.get(key), title=COLOR_NAMES[key])[1]
        if c:
            self.colors[key] = c
            self.paint_swatches()

    def paint_swatches(self):
        for k, (b, hexl) in self.swatches.items():
            col = self.colors.get(k, "#000000")
            b.configure(fg_color=col, hover_color=col)
            hexl.configure(text=col.upper())

    def page_devices(self, p):
        self.header(p, "Devices", "Which ones show in the Hardware section")
        c = self.card(p, "Sensors")
        try:
            with open(dash.DEVICES_PATH, encoding="utf-8") as fh:
                names = json.load(fh)
        except (OSError, ValueError):
            names = []
        hidden = set(self.cfg["hidden_devices"])
        names += [n for n in hidden if n not in names]
        self.dev_vars = {n: tk.BooleanVar(value=n not in hidden) for n in names}
        for n, v in self.dev_vars.items():
            r = ctk.CTkFrame(c, fg_color="#0b1419", corner_radius=10)
            r.pack(fill="x", padx=12, pady=4)
            self.switch(r, n, v).pack(side="left", padx=14, pady=10)
        if not names:
            ctk.CTkLabel(c, text="The list appears once the dashboard has run.", font=font(13), text_color=DIM).pack(anchor="w", padx=20)
        ctk.CTkFrame(c, height=8, fg_color="transparent").pack()

    def page_notes(self, p):
        self.header(p, "Notes", "Your own text on the screen — enable it in Layout")
        c = self.card(p, "Title")
        self.title = tk.StringVar(value=self.cfg.get("title", ""))
        ctk.CTkEntry(c, textvariable=self.title, height=38, corner_radius=10, font=font(14), fg_color="#0b1419",
                     border_color=BORDER, text_color=FG).pack(fill="x", padx=20, pady=(0, 18))
        c2 = self.card(p, "Text — one item per line")
        self.notes = ctk.CTkTextbox(c2, height=260, corner_radius=10, font=font(14), fg_color="#0b1419",
                                    border_color=BORDER, border_width=1, text_color=FG)
        self.notes.pack(fill="x", padx=20, pady=(0, 18))
        lines = [it if isinstance(it, str) else it.get("text", "") for it in self.cfg.get("items") or []]
        self.notes.insert("1.0", "\n".join(lines))

    # ── save / reset ────────────────────────────────────────────────
    def flash(self, text):
        self.status.configure(text=text)

    def collect(self):
        cfg = self.cfg
        cfg["show"] = {s: v.get() for s, v in self.show_vars.items()}
        for k in [k for k in cfg if k.startswith("show_")]:
            del cfg[k]  # old-style flags would override the switches
        cfg["processes"] = int(self.procs.get())
        cfg["notes_height"] = int(self.notes_h.get())
        cfg["media"] = {"path": self.media_path.get(),
                        "fit": "contain" if self.fit.get() == "Fit whole" else "cover"}
        cfg["theme"] = self.colors
        cfg["orientation"] = ORIENT[self.orient.get()]
        cfg["hidden_devices"] = [n for n, v in self.dev_vars.items() if not v.get()]
        cfg["title"] = self.title.get()
        cfg["items"] = [ln for ln in self.notes.get("1.0", "end").splitlines() if ln.strip()]
        return cfg

    # ── orientation ─────────────────────────────────────────────────
    @staticmethod
    def current_orientation():
        try:
            import extended_display
            return extended_display.current_orientation()
        except Exception:
            return None

    def apply_orientation(self, want):
        if want == self.current_orientation():
            return ""
        try:
            import extended_display
            ok = extended_display.set_orientation(want == "portrait")
        except Exception:
            ok = False
        return "\nScreen turned — it restarts in a few seconds" if ok else "\nCouldn't turn the screen (is it connected?)"

    # ── updates ─────────────────────────────────────────────────────
    def _check_quietly(self):
        try:
            tag, url, page = updater.latest()
        except Exception:
            return  # offline: stay silent, the button still works
        if url and updater.is_newer(tag):
            self.update_info = (tag, url)
            self.root.after(0, lambda: self.update_btn.configure(text=f"Update to {tag}", fg_color=ACC,
                                                                   text_color="#031014", hover_color="#22c4cf"))

    def check_update(self):
        self.flash("Checking for updates…")

        def work():
            try:
                tag, url, page = updater.latest()
            except Exception as e:
                self.root.after(0, self.flash, f"Update check failed:\n{e}")
                return
            if not url or not updater.is_newer(tag):
                self.root.after(0, self.flash, f"✓ You're up to date (v{VERSION})")
                return
            self.root.after(0, self.offer_update, tag, url)

        threading.Thread(target=work, daemon=True).start()

    def offer_update(self, tag, url):
        if not messagebox.askyesno("Update available", f"Version {tag} is available (you have v{VERSION}).\n\n"
                                   "Download and install it now? The screen restarts for a moment."):
            self.flash("")
            return
        self.flash("Downloading update…")

        def work():
            try:
                exe = updater.download(url, progress=lambda f: self.root.after(0, self.flash, f"Downloading… {f * 100:.0f}%"))
            except Exception as e:
                self.root.after(0, self.flash, f"Download failed:\n{e}")
                return
            self.root.after(0, self.install_update, exe)

        threading.Thread(target=work, daemon=True).start()

    def install_update(self, exe):
        if updater.run_installer(exe):
            self.flash("Installing…")
            self.root.after(1500, self.root.destroy)  # the installer closes old copies anyway
        else:
            self.flash("Install was cancelled")

    def apply(self):
        try:
            cfg = self.collect()
            save(cfg)
            note = self.apply_orientation(cfg["orientation"])
            self.flash("✓ Saved\nThe LCD updates in 2 s" + note)
        except (OSError, ValueError, tk.TclError) as e:
            messagebox.showerror("Save", str(e))

    def reset(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults? (the video stays)"):
            cfg = json.loads(json.dumps(dash.DEFAULTS))
            cfg["media"]["path"] = self.media_path.get()
            save(cfg)
            self.root.destroy()
            main()


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    Settings(root)
    try:  # dark title bar even when Windows itself is in light mode
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        root.withdraw()
        root.deiconify()  # repaint so the new title bar colour shows
    except (OSError, AttributeError, NameError):
        pass
    root.mainloop()


if __name__ == "__main__":
    main()
