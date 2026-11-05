"""Full-screen dashboard on the Trofeo LCD — vertical (462x1920) or horizontal (1920x462).

Sections (RAM, hardware, media, Claude, notes), their order, colors and the media file all come
from custom.json, which the settings window edits; changes show up within one refresh.
Vertical: sections stack top to bottom. Horizontal: they sit side by side and the hardware card
wraps into columns. Either way the media section takes whatever space is left.
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
MARGIN = 12

# Defaults matched to the user's build: white ROG case, ice-cyan fan rings, dark interior.
DEFAULT_THEME = {"bg": "#03070a", "card": "#071015", "fg": "#eafcff", "dim": "#6b8a93",
                 "accent": "#2ee6f2", "edge": "#12434b", "track": "#0e232a",
                 "warn": "#ffb547", "bad": "#ff3b5c"}
SECTIONS = ["ram", "hw", "media", "claude", "notes"]
DEFAULTS = {"order": SECTIONS, "show": {"ram": True, "hw": True, "media": True, "claude": False, "notes": False},
            "processes": 8, "hidden_devices": [], "media": {"path": "", "fit": "cover"},
            "theme": DEFAULT_THEME, "title": "", "items": [], "notes_height": 300,
            "orientation": "auto"}
FONT, FONT_NUM = "Bahnschrift", "Bahnschrift"
CHAMFER = 16
RAM_W = 440        # horizontal layout: fixed column widths
HW_COL_W = 300
CLAUDE_SIZE = 560  # vertical height / horizontal width
PROC_ROW = 34
RAM_HEAD = 334     # ring + numbers + "PROCESSES" header


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


def device_height(rows):
    return 48 + sum(28 + (10 if pct is not None else 0) for _, _, pct in rows)


def flow_columns(devices, col_h):
    """Split hardware devices into columns no taller than col_h (a device never splits)."""
    cols, cur, used = [], [], 0
    for dev in devices:
        h = device_height(dev[1])
        if cur and used + h > col_h:
            cols.append(cur)
            cur, used = [], 0
        cur.append(dev)
        used += h
    if cur:
        cols.append(cur)
    return cols


class Dashboard:
    def __init__(self, root, mon):
        self.root = root
        self.mon = None
        root.overrideredirect(True)
        self.c = tk.Canvas(root, highlightthickness=0)
        self.c.pack()
        self.player = media.Player(root)
        self.procs, self.procs_at = [], 0.0
        self.t = dict(DEFAULT_THEME)
        self.devices_seen = None
        self.place(mon)
        root.bind("<Escape>", lambda e: root.destroy())
        self.tick()

    def place(self, mon):
        """(Re)fit the window to the panel display — it changes shape when the orientation flips."""
        key = (mon["left"], mon["top"], mon["width"], mon["height"])
        if key == self.mon:
            return
        self.mon = key
        self.w, self.h = mon["width"], mon["height"]
        self.root.geometry(f"{self.w}x{self.h}+{mon['left']}+{mon['top']}")
        self.c.configure(width=self.w, height=self.h)

    @property
    def horizontal(self):
        return self.w > self.h

    # ── drawing helpers ────────────────────────────────────────────
    def level(self, pct):
        return self.t["accent"] if pct < 60 else self.t["warn"] if pct < 85 else self.t["bad"]

    def text(self, x, y, s, size, color=None, weight="normal", anchor="nw", wrap=0):
        return self.c.create_text(x, y, text=s, fill=color or self.t["fg"], font=(FONT, size, weight),
                                  anchor=anchor, width=wrap)

    def bar(self, x0, x1, y, pct, color, h=6):
        self.c.create_rectangle(x0, y, x1, y + h, fill=self.t["track"], width=0)
        end = x0 + (x1 - x0) * min(max(pct, 0), 100) / 100
        if end > x0:
            self.c.create_rectangle(x0, y, end, y + h, fill=color, width=0)
            self.c.create_rectangle(end - 3, y - 2, end, y + h + 2, fill=self.t["fg"], width=0)  # LED-like tip

    def card(self, box, title=""):
        """Chamfered panel echoing the angular fan frames, with accent corner ticks."""
        x0, y0, x1, y1 = box
        c, a = CHAMFER, self.t["accent"]
        pts = [x0 + c, y0, x1, y0, x1, y1 - c, x1 - c, y1, x0, y1, x0, y0 + c]
        self.c.create_polygon(pts, fill=self.t["card"], outline=self.t["edge"], width=1)
        self.c.create_line(x0, y0 + c + 28, x0, y0 + c, x0 + c, y0, x0 + c + 28, y0, fill=a, width=2)
        self.c.create_line(x1, y1 - c - 28, x1, y1 - c, x1 - c, y1, x1 - c - 28, y1, fill=a, width=2)
        if title:
            self.c.create_rectangle(x0 + 16, y0 + 22, x0 + 20, y0 + 40, fill=a, width=0)
            self.text(x0 + 30, y0 + 18, title, 15, weight="bold")

    def ring(self, cx, cy, r, pct, color, width=14):
        box = (cx - r, cy - r, cx + r, cy + r)
        self.c.create_oval(*box, outline=self.t["track"], width=width)
        if pct > 0:
            self.c.create_arc(*box, start=90, extent=-3.6 * min(pct, 99.9), style=tk.ARC, outline=color, width=width)

    def kv(self, x, y, label, value):
        self.text(x, y, label, 11, self.t["dim"])
        self.text(x, y + 18, value, 20)

    # ── section sizes along the stacking axis ───────────────────────
    def size_ram(self, cfg, cross):
        if self.horizontal:
            return RAM_W
        return RAM_HEAD + PROC_ROW * max(0, int(cfg["processes"]))

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

    def size_hw(self, cfg, cross):
        devices, err = self.hw_devices(cfg)
        if self.horizontal:
            if err or not devices:
                return HW_COL_W + 32
            return 32 + HW_COL_W * len(flow_columns(devices, cross - 80))
        if err or not devices:
            return 120
        return 64 + sum(device_height(r) for _, r in devices)

    def size_claude(self, cfg, cross):
        return CLAUDE_SIZE if not self.horizontal else 420

    def size_notes(self, cfg, cross):
        return int(cfg["notes_height"])

    # ── sections: draw inside box = (x0, y0, x1, y1) ────────────────
    def draw_ram(self, box, cfg):
        x0, y0, x1, y1 = box
        vm = psutil.virtual_memory()
        gb = 1024 ** 3
        self.card(box, "MEMORY")
        col = self.level(vm.percent)
        cx, cy = x0 + 112, y0 + 160
        self.ring(cx, cy, 92, vm.percent, col)
        self.text(cx, cy - 6, f"{vm.percent:.0f}", 54, weight="bold", anchor="center")
        self.text(cx, cy + 36, "% USED", 11, self.t["dim"], anchor="center")
        self.kv(x0 + 244, y0 + 82, "USED", f"{vm.used / gb:.1f} GB")
        self.kv(x0 + 244, y0 + 142, "FREE", f"{vm.available / gb:.1f} GB")
        self.kv(x0 + 244, y0 + 202, "TOTAL", f"{vm.total / gb:.1f} GB")
        fits = max(0, (y1 - y0 - RAM_HEAD) // PROC_ROW)
        n = min(max(0, int(cfg["processes"])), fits)
        if not n:
            return
        if time.time() - self.procs_at > PROC_EVERY_S:
            self.procs = self.top_procs(15)
            self.procs_at = time.time()
        L, R = x0 + 16, x1 - 16
        yy = y0 + 290
        self.text(L, yy, "PROCESSES", 12, self.t["accent"])
        self.c.create_line(L + 102, yy + 10, R, yy + 10, fill=self.t["edge"])
        yy += 34
        top = self.procs[0][1] if self.procs else 1
        for name, rss in self.procs[:n]:
            self.text(L, yy, name.removesuffix(".exe")[:24], 13)
            self.text(R, yy, f"{rss / gb:.2f} GB", 13, self.t["dim"], anchor="ne")
            self.c.create_rectangle(L, yy + 24, L + (R - L) * rss / top, yy + 26, fill=self.t["edge"], width=0)
            yy += PROC_ROW

    @staticmethod
    def top_procs(n):
        agg = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            mi = p.info.get("memory_info")
            if mi and p.info.get("name"):
                agg[p.info["name"]] = agg.get(p.info["name"], 0) + mi.rss
        return sorted(agg.items(), key=lambda kv: -kv[1])[:n]

    def draw_hw(self, box, cfg):
        x0, y0, x1, y1 = box
        devices, err = self.hw_devices(cfg)
        self.card(box, "HARDWARE")
        if err or not devices:
            self.text(x0 + 16, y0 + 64, err or "Reading sensors…", 13,
                      self.t["bad"] if err else self.t["dim"], wrap=x1 - x0 - 32)
            return
        cols = flow_columns(devices, y1 - y0 - 80) if self.horizontal else [devices]
        col_w = (x1 - x0 - 32) / len(cols)
        for i, col in enumerate(cols):
            L = x0 + 16 + i * col_w
            R = L + col_w - (16 if len(cols) > 1 else 0)
            yy = y0 + 64
            for name, rows in col:
                self.text(L, yy, name[:30].upper(), 12, self.t["accent"], "bold")
                yy += 22
                self.c.create_line(L, yy, R, yy, fill=self.t["edge"])
                yy += 10
                for label, val, pct in rows:
                    if yy > y1 - 30:
                        break
                    self.text(L, yy, label[:22], 13)
                    self.text(R, yy, val, 15, anchor="ne")
                    yy += 28
                    if pct is not None:
                        self.bar(L, R, yy - 4, pct, self.level(pct), h=4)
                        yy += 10
                yy += 16

    def draw_media(self, box, cfg):
        x0, y0, x1, y1 = box
        self.card(box)
        m = cfg["media"]
        inset = 14
        inner = (x0 + inset, y0 + inset, x1 - x0 - 2 * inset, y1 - y0 - 2 * inset)
        if not m.get("path") or not os.path.isfile(m["path"]):
            self.player.hide()
            self.text((x0 + x1) // 2, (y0 + y1) // 2, "Choose a video in Settings", 13, self.t["dim"], anchor="center")
            return
        if inner[2] < 40 or inner[3] < 40:
            self.player.hide()
            return
        self.player.label.configure(bg=self.t["card"])
        self.player.show(m["path"], m.get("fit", "cover"), inner)

    def draw_claude(self, box, cfg):
        x0, y0, x1, y1 = box
        L, R = x0 + 16, x1 - 16
        info = claude_info.snapshot()
        self.card(box, "Claude")
        if not info:
            self.text(L, y0 + 56, "No session found", 15, self.t["dim"])
            return
        yy = y0 + 60
        self.text(L, yy, info["model"], 20, weight="bold")
        yy += 50
        for label, val in (("Context", fmt_tokens(info.get("context_tokens"))),
                           ("Output tokens", fmt_tokens(info.get("output_tokens")))):
            self.text(L, yy, label, 13)
            self.text(R, yy, val, 15, anchor="ne")
            yy += 32
        for label, key in (("5 hours", "five_hour"), ("Week", "seven_day")):
            win = info.get(key) or {}
            p = win.get("used_percentage")
            self.text(L, yy, label, 13)
            self.text(R, yy, "--" if p is None else f"{p:.0f}%", 15, anchor="ne")
            yy += 28
            if p is not None:
                self.bar(L, R, yy, p, self.level(p), h=4)
                yy += 14

    def draw_notes(self, box, cfg):
        x0, y0, x1, y1 = box
        self.card(box, str(cfg.get("title", "")))
        yy = y0 + 60
        for it in cfg.get("items") or []:
            it = {"text": it} if isinstance(it, str) else it
            tid = self.text(x0 + 16, yy, str(it.get("text", "")), int(it.get("size", 14)), it.get("color"),
                            "bold" if it.get("bold") else "normal", wrap=x1 - x0 - 32)
            yy = self.c.bbox(tid)[3] + int(it.get("gap", 10))
            if yy > y1 - 20:
                break

    # ── layout ─────────────────────────────────────────────────────
    def layout(self, cfg):
        """[(section, box)] along the stacking axis; media takes what's left."""
        shown = [s for s in cfg["order"] if cfg["show"].get(s)]
        main = (self.w if self.horizontal else self.h) - 2 * MARGIN
        cross = (self.h if self.horizontal else self.w) - 2 * MARGIN
        sizes = {s: getattr(self, f"size_{s}")(cfg, cross) for s in shown if s != "media"}
        if "media" in shown:
            sizes["media"] = max(0, main - sum(sizes.values()) - GAP * (len(shown) - 1))
        out, pos, end = [], MARGIN, MARGIN + main
        for s in shown:
            size = min(sizes[s], end - pos)  # out of room: clip rather than overlap
            if size >= 60:
                if self.horizontal:
                    out.append((s, (pos, MARGIN, pos + size, MARGIN + cross)))
                else:
                    out.append((s, (MARGIN - 2, pos, MARGIN - 2 + cross + 4, pos + size)))
            pos += size + GAP
        return out

    def tick(self):
        try:
            mon = find_panel()
            if mon:
                self.place(mon)
            cfg = load_custom()
            self.t = {**DEFAULT_THEME, **cfg["theme"]}
            self.c.configure(bg=self.t["bg"])
            self.root.configure(bg=self.t["bg"])
            self.c.delete("all")
            boxes = self.layout(cfg)
            if "media" not in [s for s, _ in boxes]:
                self.player.hide()
            for s, box in boxes:
                getattr(self, f"draw_{s}")(box, cfg)
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
