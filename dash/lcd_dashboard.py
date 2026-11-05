"""Full-screen dashboard on the vertical Trofeo LCD (462x1920).

Sections (RAM, hardware, media, Claude, notes), their order, colors and the media file all come
from custom.json, which the settings window edits; changes show up within one refresh.
"""
from __future__ import annotations

import ctypes
import json
import os
import time
import tkinter as tk

import mss
import psutil

import claude_info
import hw_info
import media

REFRESH_MS = 2000
PROC_EVERY_S = 6
PANEL_SIZES = ((462, 1920), (1920, 462))
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TrofeoLCD")
CUSTOM_PATH = os.path.join(DATA_DIR, "custom.json")
DEVICES_PATH = os.path.join(DATA_DIR, "devices.json")  # read by the settings window
GAP = 18

# Defaults matched to the user's build: white ROG case, ice-cyan fan rings, dark interior.
DEFAULT_THEME = {"bg": "#03070a", "card": "#071015", "fg": "#eafcff", "dim": "#6b8a93",
                 "accent": "#2ee6f2", "edge": "#12434b", "track": "#0e232a",
                 "warn": "#ffb547", "bad": "#ff3b5c"}
SECTIONS = ["ram", "hw", "media", "claude", "notes"]
DEFAULTS = {"order": SECTIONS, "show": {"ram": True, "hw": True, "media": True, "claude": False, "notes": False},
            "processes": 8, "hidden_devices": [], "media": {"path": "", "fit": "cover"},
            "theme": DEFAULT_THEME, "title": "", "items": [], "notes_height": 300}
FONT, FONT_NUM = "Bahnschrift", "Bahnschrift"  # Bahnschrift: DIN-like digits; Georgian falls back to Segoe UI
CHAMFER = 16
CLAUDE_CARD_H = 560


def load_custom() -> dict:
    """custom.json merged over DEFAULTS; a broken file falls back to defaults plus an error note."""
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CUSTOM_PATH, encoding="utf-8-sig") as f:
            user = json.load(f)
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as e:
        cfg["error"] = f"custom.json: {e}"
        return cfg
    if not isinstance(user, dict):
        return cfg
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    for k in SECTIONS:  # older files used show_ram / show_hw / show_claude
        if f"show_{k}" in user:
            cfg["show"][k] = bool(user[f"show_{k}"])
    cfg["order"] = [s for s in cfg["order"] if s in SECTIONS] + [s for s in SECTIONS if s not in cfg["order"]]
    return cfg


def find_panel():
    with (mss.MSS if hasattr(mss, "MSS") else mss.mss)() as s:
        for m in s.monitors[1:]:
            if (m["width"], m["height"]) in PANEL_SIZES:
                return m
    return None


def fmt_tokens(n):
    if n is None:
        return "--"
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else str(n)


class Dashboard:
    def __init__(self, root, mon):
        self.root = root
        self.w, self.h = mon["width"], mon["height"]
        root.overrideredirect(True)
        root.geometry(f"{self.w}x{self.h}+{mon['left']}+{mon['top']}")
        self.c = tk.Canvas(root, width=self.w, height=self.h, highlightthickness=0)
        self.c.pack()
        self.player = media.Player(root)
        self.procs, self.procs_at = [], 0.0
        self.t = dict(DEFAULT_THEME)
        self.devices_seen = None
        root.bind("<Escape>", lambda e: root.destroy())
        self.tick()

    # ── drawing helpers ────────────────────────────────────────────
    def level(self, pct):
        return self.t["accent"] if pct < 60 else self.t["warn"] if pct < 85 else self.t["bad"]

    def text(self, x, y, s, size, color=None, weight="normal", anchor="nw", wrap=0, num=False):
        font = (FONT_NUM if num else FONT, size, weight)
        return self.c.create_text(x, y, text=s, fill=color or self.t["fg"], font=font, anchor=anchor, width=wrap)

    def bar(self, y, pct, color, x=24, h=6):
        x1 = self.w - x
        self.c.create_rectangle(x, y, x1, y + h, fill=self.t["track"], width=0)
        end = x + (x1 - x) * min(max(pct, 0), 100) / 100
        if end > x:
            self.c.create_rectangle(x, y, end, y + h, fill=color, width=0)
            self.c.create_rectangle(end - 3, y - 2, end, y + h + 2, fill=self.t["fg"], width=0)  # LED-like tip

    def card(self, y0, y1, title=""):
        """Chamfered panel echoing the angular fan frames, with accent corner ticks."""
        x0, x1, c, a = 10, self.w - 10, CHAMFER, self.t["accent"]
        pts = [x0 + c, y0, x1, y0, x1, y1 - c, x1 - c, y1, x0, y1, x0, y0 + c]
        self.c.create_polygon(pts, fill=self.t["card"], outline=self.t["edge"], width=1)
        self.c.create_line(x0, y0 + c + 28, x0, y0 + c, x0 + c, y0, x0 + c + 28, y0, fill=a, width=2)
        self.c.create_line(x1, y1 - c - 28, x1, y1 - c, x1 - c, y1, x1 - c - 28, y1, fill=a, width=2)
        if title:
            self.c.create_rectangle(26, y0 + 22, 30, y0 + 40, fill=a, width=0)
            self.text(40, y0 + 18, title, 15, weight="bold")

    def ring(self, cx, cy, r, pct, color, width=14):
        box = (cx - r, cy - r, cx + r, cy + r)
        self.c.create_oval(*box, outline=self.t["track"], width=width)
        if pct > 0:
            self.c.create_arc(*box, start=90, extent=-3.6 * min(pct, 99.9), style=tk.ARC, outline=color, width=width)

    def kv(self, x, y, label, value):
        self.text(x, y, label, 11, self.t["dim"])
        self.text(x, y + 18, value, 20, num=True)

    # ── sections: each has height(cfg) and draw(y, height, cfg) ──────
    def ram_height(self, cfg):
        return 334 + 34 * max(0, int(cfg["processes"]))

    def draw_ram(self, y, hgt, cfg):
        vm = psutil.virtual_memory()
        gb = 1024 ** 3
        self.card(y, y + hgt, "MEMORY")
        col = self.level(vm.percent)
        cx, cy = 122, y + 160
        self.ring(cx, cy, 92, vm.percent, col)
        self.text(cx, cy - 6, f"{vm.percent:.0f}", 54, weight="bold", anchor="center", num=True)
        self.text(cx, cy + 36, "% USED", 11, self.t["dim"], anchor="center")
        self.kv(254, y + 82, "USED", f"{vm.used / gb:.1f} GB")
        self.kv(254, y + 142, "FREE", f"{vm.available / gb:.1f} GB")
        self.kv(254, y + 202, "TOTAL", f"{vm.total / gb:.1f} GB")
        n = max(0, int(cfg["processes"]))
        if not n:
            return
        if time.time() - self.procs_at > PROC_EVERY_S:
            self.procs = self.top_procs(n)
            self.procs_at = time.time()
        yy = y + 290
        self.text(26, yy, "PROCESSES", 12, self.t["accent"])
        self.c.create_line(128, yy + 10, self.w - 26, yy + 10, fill=self.t["edge"])
        yy += 34
        top = self.procs[0][1] if self.procs else 1
        for name, rss in self.procs[:n]:
            self.text(26, yy, name.removesuffix(".exe")[:24], 13)
            self.text(self.w - 26, yy, f"{rss / gb:.2f} GB", 13, self.t["dim"], anchor="ne", num=True)
            self.c.create_rectangle(26, yy + 24, 26 + (self.w - 52) * rss / top, yy + 26, fill=self.t["edge"], width=0)
            yy += 34

    @staticmethod
    def top_procs(n):
        agg = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            mi = p.info.get("memory_info")
            if mi and p.info.get("name"):
                agg[p.info["name"]] = agg.get(p.info["name"], 0) + mi.rss
        return sorted(agg.items(), key=lambda kv: -kv[1])[:n]

    def hw_devices(self, cfg):
        devices, err = hw_info.snapshot()
        names = [n for n, _ in devices]
        if names and names != self.devices_seen:  # let the settings window list them
            self.devices_seen = names
            try:
                with open(DEVICES_PATH, "w", encoding="utf-8") as f:
                    json.dump(names, f, ensure_ascii=False)
            except OSError:
                pass
        hidden = set(cfg["hidden_devices"])
        return [(n, r) for n, r in devices if n not in hidden], err

    def hw_height(self, cfg):
        devices, err = self.hw_devices(cfg)
        if err or not devices:
            return 120
        body = sum(48 + sum(28 + (10 if pct is not None else 0) for _, _, pct in rows) for _, rows in devices)
        return 64 + body

    def draw_hw(self, y, hgt, cfg):
        devices, err = self.hw_devices(cfg)
        self.card(y, y + hgt, "HARDWARE")
        yy = y + 64
        if err or not devices:
            self.text(26, yy, err or "Reading sensors…", 13, self.t["bad"] if err else self.t["dim"], wrap=self.w - 52)
            return
        for name, rows in devices:
            self.text(26, yy, name[:34].upper(), 12, self.t["accent"], "bold", num=True)
            yy += 22
            self.c.create_line(26, yy, self.w - 26, yy, fill=self.t["edge"])
            yy += 10
            for label, val, pct in rows:
                self.text(26, yy, label[:22], 13)
                self.text(self.w - 26, yy, val, 15, anchor="ne", num=True)
                yy += 28
                if pct is not None:
                    self.bar(yy - 4, pct, self.level(pct), x=26, h=4)
                    yy += 10
            yy += 16

    def draw_media(self, y, hgt, cfg):
        self.card(y, y + hgt)
        m = cfg["media"]
        inset = 14
        box = (10 + inset, y + inset, self.w - 20 - 2 * inset, hgt - 2 * inset)
        if not m.get("path") or not os.path.isfile(m["path"]):
            self.player.hide()
            self.text(self.w // 2, y + hgt // 2, "Choose a video in Settings", 13, self.t["dim"], anchor="center")
            return
        if box[3] < 40:
            self.player.hide()
            return
        self.player.label.configure(bg=self.t["card"])
        self.player.show(m["path"], m.get("fit", "cover"), box)

    def draw_claude(self, y, hgt, cfg):
        info = claude_info.snapshot()
        self.card(y, y + hgt, "Claude")
        if not info:
            self.text(26, y + 56, "No session found", 15, self.t["dim"])
            return
        yy = y + 60
        self.text(26, yy, info["model"], 20, weight="bold", num=True)
        yy += 50
        for label, val in (("Context", fmt_tokens(info.get("context_tokens"))),
                           ("Output tokens", fmt_tokens(info.get("output_tokens")))):
            self.text(26, yy, label, 13)
            self.text(self.w - 26, yy, val, 15, anchor="ne", num=True)
            yy += 32
        for label, key in (("5 hours", "five_hour"), ("Week", "seven_day")):
            win = info.get(key) or {}
            p = win.get("used_percentage")
            self.text(26, yy, label, 13)
            self.text(self.w - 26, yy, "--" if p is None else f"{p:.0f}%", 15, anchor="ne", num=True)
            yy += 28
            if p is not None:
                self.bar(yy, p, self.level(p), x=26, h=4)
                yy += 14

    def draw_notes(self, y, hgt, cfg):
        self.card(y, y + hgt, str(cfg.get("title", "")))
        yy = y + 60
        for it in cfg.get("items") or []:
            it = {"text": it} if isinstance(it, str) else it
            tid = self.text(26, yy, str(it.get("text", "")), int(it.get("size", 14)), it.get("color"),
                            "bold" if it.get("bold") else "normal", wrap=self.w - 52)
            yy = self.c.bbox(tid)[3] + int(it.get("gap", 10))
            if yy > y + hgt - 20:
                break

    # ── layout ─────────────────────────────────────────────────────
    def tick(self):
        try:
            cfg = load_custom()
            self.t = {**DEFAULT_THEME, **cfg["theme"]}
            self.c.configure(bg=self.t["bg"])
            self.root.configure(bg=self.t["bg"])
            self.c.delete("all")
            shown = [s for s in cfg["order"] if cfg["show"].get(s)]
            fixed = {"ram": lambda: self.ram_height(cfg), "hw": lambda: self.hw_height(cfg),
                     "claude": lambda: CLAUDE_CARD_H, "notes": lambda: int(cfg["notes_height"])}
            heights = {s: fixed[s]() for s in shown if s in fixed}
            free = self.h - 12 - 12 - sum(heights.values()) - GAP * (len(shown) - 1)
            if "media" in shown:
                heights["media"] = max(0, free)
            else:
                self.player.hide()
            y = 12
            for s in shown:
                hgt = heights[s]
                if y + hgt > self.h - 12:  # out of room: clip rather than overlap
                    hgt = self.h - 12 - y
                if hgt < 60:
                    if s == "media":
                        self.player.hide()
                    continue
                getattr(self, f"draw_{s}")(y, hgt, cfg)
                y += hgt + GAP
            if cfg.get("error"):
                self.text(26, self.h - 40, cfg["error"][:70], 10, self.t["bad"])
        except Exception as e:  # keep the screen alive; show the error instead of dying
            self.text(24, self.h - 60, f"error: {e}"[:60], 11, "#ff3b5c")
        self.root.after(REFRESH_MS, self.tick)


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, so geometry matches the LCD
    mon = find_panel()
    while mon is None:
        time.sleep(5)
        mon = find_panel()
    root = tk.Tk()
    Dashboard(root, mon)
    root.mainloop()


if __name__ == "__main__":
    main()
