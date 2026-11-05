"""Looping video / GIF / image for the dashboard's bottom area.

prepare() makes a small LCD-friendly copy once (big 4K clips would cost a CPU core to decode live);
Player shows it in a Tk label placed over the dashboard canvas.
"""
from __future__ import annotations

import os
import shutil
import time

import cv2
from PIL import Image, ImageTk

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TrofeoLCD")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
MAX_SIDE = 960
MAX_FPS = 24.0  # the LCD link tops out around 24 fps
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif", ".m4v", ".wmv"}


def prepare(src: str, progress=None) -> str:
    """Copy/convert src into MEDIA_DIR; returns the path the dashboard should play."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    ext = ext.lower()
    if ext in IMAGE_EXT:
        dst = os.path.join(MEDIA_DIR, stem + ext)
        shutil.copy2(src, dst)
        return dst
    if ext not in VIDEO_EXT:
        raise ValueError(f"unsupported file type: {ext}")
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or MAX_FPS
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = min(1.0, MAX_SIDE / max(w, h))
    size = (max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2))
    out_fps = min(fps, MAX_FPS)
    dst = os.path.join(MEDIA_DIR, stem + "_lcd.mp4")
    tmp = dst + ".tmp.mp4"
    out = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), out_fps, size)
    step, acc, i = fps / out_fps, 0.0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            i += 1
            acc += 1
            if acc < step:
                continue  # drop frames to reach out_fps
            acc -= step
            out.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
            if progress and total:
                progress(i / total)
    finally:
        cap.release()
        out.release()
    os.replace(tmp, dst)
    return dst


def fit_frame(img: Image.Image, w: int, h: int, mode: str) -> Image.Image:
    """cover = fill and crop the overflow, contain = show all with black bars."""
    sw, sh = img.size
    if mode == "contain":
        s = min(w / sw, h / sh)
        r = img.resize((max(1, int(sw * s)), max(1, int(sh * s))), Image.BILINEAR)
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        canvas.paste(r, ((w - r.width) // 2, (h - r.height) // 2))
        return canvas
    s = max(w / sw, h / sh)
    r = img.resize((max(w, int(sw * s + 0.5)), max(h, int(sh * s + 0.5))), Image.BILINEAR)
    left, top = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((left, top, left + w, top + h))


class Player:
    def __init__(self, root, bg="#000000"):
        import tkinter as tk
        self.root = root
        self.label = tk.Label(root, bg=bg, bd=0, highlightthickness=0)
        self.cap = self.still = self.photo = self.job = None
        self.path = self.fit = self.box = None
        self.delay = int(1000 / MAX_FPS)

    def show(self, path: str | None, fit: str, box: tuple[int, int, int, int]):
        """Called every dashboard tick; only reacts to changes."""
        if box != self.box:
            self.box = box
            x, y, w, h = box
            self.label.place(x=x, y=y, width=w, height=h)
            if self.still is not None:
                self._paint(self.still)
        if (path, fit) != (self.path, self.fit):
            self.path, self.fit = path, fit
            self._open()

    def hide(self):
        self._close()
        self.label.place_forget()
        self.box = self.path = None

    def _close(self):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        if self.cap is not None:
            self.cap.release()
        self.cap = self.still = None
        self.label.configure(image="")

    def _open(self):
        self._close()
        if not self.path or not os.path.isfile(self.path):
            return
        if os.path.splitext(self.path)[1].lower() in IMAGE_EXT:
            self.still = Image.open(self.path).convert("RGB")
            self._paint(self.still)
            return
        self.cap = cv2.VideoCapture(self.path)
        self.fps = min(self.cap.get(cv2.CAP_PROP_FPS) or MAX_FPS, MAX_FPS)
        self.t0, self.shown = time.perf_counter(), -1
        self._next()

    def _next(self):
        # Clock-driven: work out which frame is due now and skip any we fell behind on,
        # instead of "decode, sleep a fixed delay" which drifts slower than the video.
        due = int((time.perf_counter() - self.t0) * self.fps)
        frame = None
        while self.shown < due:
            ok = self.cap.grab()
            if not ok:  # loop back to the start
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self.t0, self.shown, due = time.perf_counter(), -1, 0
                ok = self.cap.grab()
                if not ok:
                    break
            self.shown += 1
            if self.shown == due:
                frame = self.cap.retrieve()[1]
        if frame is not None:
            self._paint_bgr(frame)
        wait = (self.t0 + (self.shown + 1) / self.fps - time.perf_counter()) * 1000
        self.job = self.root.after(max(1, int(wait)), self._next)

    def _paint_bgr(self, frame):
        """Resize with OpenCV (much faster than PIL at this size), then hand Tk the result."""
        if not self.box:
            return
        _, _, w, h = self.box
        fh, fw = frame.shape[:2]
        if (self.fit or "cover") == "cover":
            s = max(w / fw, h / fh)
            r = cv2.resize(frame, (max(w, round(fw * s)), max(h, round(fh * s))), interpolation=cv2.INTER_LINEAR)
            y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
            r = r[y0:y0 + h, x0:x0 + w]
            img = Image.fromarray(cv2.cvtColor(r, cv2.COLOR_BGR2RGB))
        else:
            img = fit_frame(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), w, h, "contain")
        self.photo = ImageTk.PhotoImage(img)
        self.label.configure(image=self.photo)

    def _paint(self, img):
        if not self.box:
            return
        _, _, w, h = self.box
        self.photo = ImageTk.PhotoImage(fit_frame(img, w, h, self.fit or "cover"))
        self.label.configure(image=self.photo)


if __name__ == "__main__":
    a = fit_frame(Image.new("RGB", (960, 540)), 438, 600, "cover")
    b = fit_frame(Image.new("RGB", (960, 540)), 438, 600, "contain")
    assert a.size == b.size == (438, 600), (a.size, b.size)
    print("fit ok")
