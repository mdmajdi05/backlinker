#!/usr/bin/env python3
"""Generate the desktop application icons.

The script only uses the Python standard library so it can run on a clean
machine (no Pillow, no ImageMagick). It produces:

    icons/32x32.png        - Linux / tray icon
    icons/128x128.png      - Windows installer / app icon
    icons/128x128@2x.png   - macOS retina icon (256 px)
    icons/icon.png         - source icon (512 px)
    icons/icon.ico         - Windows icon (BMP entries)
    icons/icon.icns        - macOS icon (PNG entries)

These are *placeholder* icons for the open source build. Replace them with the
real brand assets before shipping - they are not signed and they are not
verified by Apple or Microsoft.

Usage:  python3 scripts/generate-icons.py [output-directory]
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

# Design tokens (mirrors packages/ui/src/styles.css).
ACCENT_TOP = (129, 140, 248)
ACCENT_BOTTOM = (67, 56, 202)
FOREGROUND = (255, 255, 255)

SUPERSAMPLE = 4


# ----------------------------------------------------------------------
# PNG helpers
# ----------------------------------------------------------------------
def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type "none"
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


class Canvas:
    """A simple RGBA canvas with alpha blending."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.pixels = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]

    def blend(self, x: int, y: int, color: tuple[int, int, int], alpha: float) -> None:
        if x < 0 or y < 0 or x >= self.size or y >= self.size or alpha <= 0:
            return
        alpha = min(1.0, alpha)
        r, g, b, a = self.pixels[y][x]
        inv = 1.0 - alpha
        self.pixels[y][x] = (
            int(color[0] * alpha + r * inv),
            int(color[1] * alpha + g * inv),
            int(color[2] * alpha + b * inv),
            int(255 * alpha + a * inv),
        )

    def rounded_rect(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        radius: float,
        color: tuple[int, int, int],
        alpha: float = 1.0,
    ) -> None:
        for y in range(int(top), int(bottom) + 1):
            for x in range(int(left), int(right) + 1):
                px, py = x + 0.5, y + 0.5
                if not (left <= px <= right and top <= py <= bottom):
                    continue
                # Distance to the rounded corners.
                dx = 0.0
                dy = 0.0
                if px < left + radius:
                    dx = left + radius - px
                elif px > right - radius:
                    dx = px - (right - radius)
                if py < top + radius:
                    dy = top + radius - py
                elif py > bottom - radius:
                    dy = py - (bottom - radius)
                if dx and dy:
                    distance = (dx * dx + dy * dy) ** 0.5
                    if distance > radius:
                        continue
                self.blend(x, y, color, alpha)

    def gradient_background(self, radius_ratio: float = 0.22) -> None:
        size = self.size
        radius = size * radius_ratio
        for y in range(size):
            t = y / max(1, size - 1)
            color = (
                int(ACCENT_TOP[0] + (ACCENT_BOTTOM[0] - ACCENT_TOP[0]) * t),
                int(ACCENT_TOP[1] + (ACCENT_BOTTOM[1] - ACCENT_TOP[1]) * t),
                int(ACCENT_TOP[2] + (ACCENT_BOTTOM[2] - ACCENT_TOP[2]) * t),
            )
            for x in range(size):
                px, py = x + 0.5, y + 0.5
                dx = 0.0
                dy = 0.0
                if px < radius:
                    dx = radius - px
                elif px > size - radius:
                    dx = px - (size - radius)
                if py < radius:
                    dy = radius - py
                elif py > size - radius:
                    dy = py - (size - radius)
                if dx and dy:
                    if (dx * dx + dy * dy) ** 0.5 > radius:
                        continue
                self.blend(x, y, color, 1.0)

    def downsample(self, factor: int) -> list[list[tuple[int, int, int, int]]]:
        size = self.size // factor
        result: list[list[tuple[int, int, int, int]]] = []
        for y in range(size):
            row: list[tuple[int, int, int, int]] = []
            for x in range(size):
                r = g = b = a = 0
                for sy in range(factor):
                    for sx in range(factor):
                        pr, pg, pb, pa = self.pixels[y * factor + sy][x * factor + sx]
                        r += pr * pa
                        g += pg * pa
                        b += pb * pa
                        a += pa
                if a == 0:
                    row.append((0, 0, 0, 0))
                else:
                    row.append((r // a, g // a, b // a, a // (factor * factor)))
            result.append(row)
        return result


def draw_icon(size: int) -> list[list[tuple[int, int, int, int]]]:
    """Draw the placeholder mark: three ascending bars on a rounded square."""
    canvas = Canvas(size * SUPERSAMPLE)
    canvas.gradient_background()

    scale = size * SUPERSAMPLE
    margin = scale * 0.26
    bar_width = scale * 0.13
    gap = scale * 0.09
    baseline = scale * 0.74
    heights = [scale * 0.16, scale * 0.28, scale * 0.42]

    x = margin
    for height in heights:
        canvas.rounded_rect(
            x,
            baseline - height,
            x + bar_width,
            baseline,
            bar_width * 0.35,
            FOREGROUND,
        )
        x += bar_width + gap

    # A small arrow head above the tallest bar.
    tip_x = margin + 2 * (bar_width + gap) + bar_width / 2
    tip_y = baseline - heights[-1] - scale * 0.16
    size_arrow = scale * 0.11
    canvas.rounded_rect(
        tip_x - size_arrow * 0.18,
        tip_y,
        tip_x + size_arrow * 0.18,
        tip_y + size_arrow * 0.8,
        size_arrow * 0.1,
        FOREGROUND,
    )
    canvas.rounded_rect(
        tip_x - size_arrow * 0.55,
        tip_y + size_arrow * 0.55,
        tip_x + size_arrow * 0.55,
        tip_y + size_arrow * 0.95,
        size_arrow * 0.16,
        FOREGROUND,
    )

    return canvas.downsample(SUPERSAMPLE)


# ----------------------------------------------------------------------
# ICO / ICNS containers
# ----------------------------------------------------------------------
def encode_ico(images: dict[int, list[list[tuple[int, int, int, int]]]]) -> bytes:
    """Build a classic (BMP based) .ico file."""
    entries = []
    payloads = []
    offset = 6 + 16 * len(images)

    for size in sorted(images):
        pixels = images[size]
        width = height = size
        header = struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height * 2,
            1,
            32,
            0,
            width * height * 4,
            0,
            0,
            0,
            0,
        )
        body = bytearray()
        for y in range(height - 1, -1, -1):
            for x in range(width):
                r, g, b, a = pixels[y][x]
                body += bytes((b, g, r, a))

        mask_row = ((width + 31) // 32) * 4
        mask = bytearray()
        for y in range(height - 1, -1, -1):
            bits = bytearray(mask_row)
            for x in range(width):
                if pixels[y][x][3] == 0:
                    bits[x // 8] |= 0x80 >> (x % 8)
            mask += bits

        data = header + bytes(body) + bytes(mask)
        entries.append(
            struct.pack(
                "<BBBBHHII",
                width if width < 256 else 0,
                height if height < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payloads.append(data)
        offset += len(data)

    return (
        struct.pack("<HHH", 0, 1, len(images))
        + b"".join(entries)
        + b"".join(payloads)
    )


def encode_icns(entries: list[tuple[bytes, bytes]]) -> bytes:
    """Build an .icns file from (type, png-bytes) pairs."""
    body = b""
    for icon_type, payload in entries:
        body += icon_type + struct.pack(">I", len(payload) + 8) + payload
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "src-tauri" / "icons"
    target.mkdir(parents=True, exist_ok=True)

    sizes = (32, 64, 128, 256, 512)
    rendered = {size: draw_icon(size) for size in sizes}

    for name, size in (
        ("32x32.png", 32),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
        ("icon.png", 512),
    ):
        path = target / name
        path.write_bytes(encode_png(size, size, rendered[size]))
        print(f"wrote {path}")

    ico = encode_ico({size: rendered[size] for size in (32, 64, 128, 256)})
    (target / "icon.ico").write_bytes(ico)
    print(f"wrote {target / 'icon.ico'}")

    icns = encode_icns(
        [
            (b"ic11", encode_png(32, 32, rendered[32])),
            (b"ic12", encode_png(64, 64, rendered[64])),
            (b"ic07", encode_png(128, 128, rendered[128])),
            (b"ic08", encode_png(256, 256, rendered[256])),
            (b"ic09", encode_png(512, 512, rendered[512])),
        ]
    )
    (target / "icon.icns").write_bytes(icns)
    print(f"wrote {target / 'icon.icns'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
