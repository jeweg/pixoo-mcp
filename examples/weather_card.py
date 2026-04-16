#!/usr/bin/env python3
"""Rich weather card — 64px Pixoo only.

Draws a detailed weather display with a sun icon, temperature, city name,
condition text (word-wrapped), and a humidity bar.  Showcases:
  - draw_circle (sun icon)
  - draw_line (sun rays)
  - draw_rect (panels, dividers)
  - draw_text (labels, alignment, word-wrap with max_width)
  - draw_bar (humidity gauge)
  - clear
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo


def draw_sun(p: Pixoo, cx: int, cy: int, radius: int):
    """Draw a simple sun: filled circle + rays."""
    p.draw_circle(cx, cy, radius, 255, 200, 0, filled=True)
    ray_len = radius + 3
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x0 = int(cx + (radius + 1) * math.cos(rad))
        y0 = int(cy + (radius + 1) * math.sin(rad))
        x1 = int(cx + ray_len * math.cos(rad))
        y1 = int(cy + ray_len * math.sin(rad))
        p.draw_line(x0, y0, x1, y1, 255, 220, 50)


def weather_card(p: Pixoo):
    if p.size < 64:
        print("This example is designed for 64x64 displays.")
        return

    s = p.size
    p.clear(10, 10, 30)

    # --- header ---
    p.draw_rect(0, 0, s, 9, 20, 15, 50, filled=True)
    p.draw_text("WEATHER", s // 2, 1, 180, 180, 255, align="center")

    # --- sun icon ---
    draw_sun(p, 14, 22, 5)

    # --- temperature ---
    p.draw_text("23C", 30, 15, 255, 255, 255)
    p.draw_text("Sunny", 30, 23, 255, 220, 100)

    # --- divider ---
    p.draw_line(0, 31, s - 1, 31, 40, 40, 80)

    # --- forecast text (word-wrapped) ---
    p.draw_text(
        "Clear skies through the evening",
        1, 34, 160, 160, 200,
        max_width=s - 2,
    )

    # --- humidity bar at bottom ---
    p.draw_line(0, 50, s - 1, 50, 40, 40, 80)
    p.draw_text("HUM", 1, 53, 100, 100, 140)
    p.draw_bar(18, 53, 32, 5, 0.62, 80, 160, 255)
    p.draw_text("62%", s - 1, 53, 80, 160, 255, align="right")

    # --- footer ---
    p.draw_rect(0, s - 6, s, 6, 20, 15, 50, filled=True)
    p.draw_text("Berlin", s // 2, s - 5, 140, 140, 180, align="center")


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python weather_card.py <IP>  (or set PIXOO_IP)")
        sys.exit(1)
    p = Pixoo(ip, size=64)
    weather_card(p)
    print(p.push())
