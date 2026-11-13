"""Generate HostsKeeper app icon (.ico + .png). Requires Pillow: pip install pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "hostskeeper" / "resources"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, size // 32)
    pad = size // 16
    bg = (30, 41, 59, 255)
    accent = (34, 197, 94, 255)
    face = (51, 65, 85, 255)
    metal = (148, 163, 184, 255)
    keyhole = (15, 23, 42, 255)
    d.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=size // 5,
        fill=bg,
    )
    x0, y0 = size * 0.22, size * 0.20
    x1, y1 = size * 0.78, size * 0.72
    d.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=size // 12,
        fill=face,
        outline=metal,
        width=max(1, m),
    )
    for i in (0.38, 0.50, 0.62):
        y = y0 + (y1 - y0) * i
        d.line(
            [x0 + m * 2, y, x1 - m * 2, y],
            fill=(71, 85, 105, 255),
            width=max(1, m // 2),
        )
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2 - size * 0.02
    r = size * 0.07
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=keyhole)
    stem_w = size * 0.045
    stem_h = size * 0.10
    d.rounded_rectangle(
        [cx - stem_w, cy + r * 0.4, cx + stem_w, cy + r * 0.4 + stem_h],
        radius=stem_w / 2,
        fill=keyhole,
    )
    bar_y0, bar_y1 = size * 0.78, size * 0.88
    d.rounded_rectangle(
        [size * 0.22, bar_y0, size * 0.78, bar_y1],
        radius=size // 20,
        fill=(15, 23, 42, 255),
    )
    cw = size * 0.08
    ch = (bar_y1 - bar_y0) * 0.55
    cx0 = size * 0.28
    cy0 = (bar_y0 + bar_y1 - ch) / 2
    d.rectangle([cx0, cy0, cx0 + cw, cy0 + ch], fill=accent)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    images = [make(s) for s in SIZES]
    ico = OUT / "hostskeeper.ico"
    images[-1].save(
        ico,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    png = OUT / "hostskeeper.png"
    images[-1].save(png)
    print(f"wrote {ico} ({ico.stat().st_size} bytes)")
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
