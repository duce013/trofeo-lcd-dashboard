"""Draws the Duce logo (angular "D" with a ROG-style slash, cyan glow) -> dash/duce.ico + dash/duce.png.

Re-run after changing colors/shape: python tools/make_logo.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dash")
S = 1024  # draw big, downscale for crisp small icons
BG, CARD, ACC, WHITE = (3, 7, 10, 255), (7, 16, 21, 255), (46, 230, 242, 255), (234, 252, 255, 255)


def chamfer_rect(box, c):
    x0, y0, x1, y1 = box
    return [(x0 + c, y0), (x1, y0), (x1, y1 - c), (x1 - c, y1), (x0, y1), (x0, y0 + c)]


def d_shape(box, cut):
    """Angular D: flat left side, two bevels on the right."""
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y1 - cut), (x1 - cut, y1), (x0, y1)]


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    badge = chamfer_rect((40, 40, S - 40, S - 40), 170)
    d.polygon(badge, fill=CARD)
    d.line(badge + [badge[0]], fill=(18, 67, 75, 255), width=14)

    # glowing D outline on its own layer
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    outer = d_shape((250, 230, 790, 794), 190)
    inner = d_shape((362, 342, 678, 682), 110)
    g.polygon(outer, fill=ACC)
    g.polygon(inner, fill=(0, 0, 0, 0))
    # ROG-style diagonal slash cutting through the letter
    g.polygon([(150, 700), (215, 700), (880, 250), (815, 250)], fill=(0, 0, 0, 0))
    halo = glow.filter(ImageFilter.GaussianBlur(38))
    img = Image.alpha_composite(img, halo)
    img = Image.alpha_composite(img, glow)

    # white accent shard in the slash + corner ticks, like the dashboard cards
    d = ImageDraw.Draw(img)
    d.polygon([(205, 690), (232, 690), (860, 268), (833, 268)], fill=WHITE)
    for pts in ([(40, 380), (40, 210), (210, 40), (380, 40)], [(S - 40, S - 380), (S - 40, S - 210), (S - 210, S - 40), (S - 380, S - 40)]):
        d.line(pts, fill=ACC, width=22, joint="curve")
    return img


if __name__ == "__main__":
    img = draw()
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "duce.png"))
    img.save(os.path.join(OUT, "duce.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    check = Image.open(os.path.join(OUT, "duce.ico"))
    assert (256, 256) in check.info.get("sizes", {(256, 256)}), check.info
    print("logo written to", OUT)
