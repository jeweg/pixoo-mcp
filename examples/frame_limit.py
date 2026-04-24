#!/usr/bin/env python3
"""Test the Pixoo's animation frame buffer limit.

Sends N frames as a single animation where each frame displays its
frame number (1, 2, 3, …).  The device silently drops frames past its
buffer limit while still returning HTTP 200, so you have to watch the
display to see which numbers actually cycle.

Empirical findings on a Pixoo-64:
  - 60 frames: all play reliably
  - 70 frames: all play (borderline)
  - 80 frames: only ~60-63 play, rest silently dropped

The limit appears to be a fixed memory budget (~60 frames for 64x64)
rather than a hard frame count, so content complexity may shift it
slightly.

Usage:
    python frame_limit.py <IP> [N]

N defaults to 60.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo


def build_number_frame(p: Pixoo, n: int, total: int):
    """Draw frame number *n* (1-based) centered on the display."""
    p.clear(0, 0, 0)

    label = str(n)
    char_w = 4
    char_h = 5
    text_w = len(label) * char_w - 1

    tx = (p.size - text_w) // 2
    ty = (p.size - char_h) // 2

    hue = n / total
    r = int(255 * max(0, min(1, abs(hue * 6 - 3) - 1)))
    g = int(255 * max(0, min(1, 2 - abs(hue * 6 - 2))))
    b = int(255 * max(0, min(1, 2 - abs(hue * 6 - 4))))
    r, g, b = max(r, 80), max(g, 80), max(b, 80)

    p.draw_text(label, tx, ty, r, g, b)


if __name__ == "__main__":
    args = sys.argv[1:]
    ip = args[0] if args else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python frame_limit.py <IP> [N]")
        sys.exit(1)

    total = int(args[1]) if len(args) > 1 else 60

    p = Pixoo(ip, size=64, refresh_connection=False)

    # Cancel any running animation cleanly
    p._animating = True
    p.clear(0, 0, 0)
    p.draw_text("...", 24, 29, 80, 80, 80, align="center")
    p.push()

    print(f"Building {total} frames...")
    frames = []
    for i in range(1, total + 1):
        build_number_frame(p, i, total)
        frames.append(p.snapshot())

    print(f"Sending {total}-frame animation (1s per frame)...")
    results = p.push_animation(frames, speed_ms=1000)

    errors = sum(1 for r in results if r.get("error_code", 0) not in (0, "0"))
    print(f"HTTP: {len(results) - errors} OK, {errors} errors")
    print(f"\nWatch the display — what's the highest number you see?")
