#!/usr/bin/env python3
"""Analog clock that updates in real time.

Works on all display sizes (16, 32, 64).  Showcases:
  - draw_circle (clock face)
  - draw_line (clock hands via trigonometry)
  - draw_text (digital readout, centered)
  - set_pixel (hour markers)
  - push in a live loop
  - save_gif (optional, with --gif flag)

Press Ctrl-C to stop.
"""

import math
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo


def draw_hand(p, cx, cy, angle_deg, length, r, g, b, width=1):
    """Draw a clock hand from center at the given angle (0° = 12 o'clock)."""
    rad = math.radians(angle_deg - 90)
    ex = cx + length * math.cos(rad)
    ey = cy + length * math.sin(rad)
    p.draw_line(cx, cy, int(ex), int(ey), r, g, b)
    if width > 1:
        for offset in (-1, 1):
            rad2 = math.radians(angle_deg)
            ox, oy = offset * math.cos(rad2), offset * math.sin(rad2)
            p.draw_line(cx + int(ox), cy + int(oy),
                        int(ex + ox), int(ey + oy), r, g, b)


def draw_clock(p: Pixoo, now: datetime):
    s = p.size
    cx = cy = s // 2
    face_r = s // 2 - 2

    p.clear(0, 0, 15)

    p.draw_circle(cx, cy, face_r, 40, 40, 80)

    for h in range(12):
        angle = math.radians(h * 30 - 90)
        mx = int(cx + (face_r - 1) * math.cos(angle))
        my = int(cy + (face_r - 1) * math.sin(angle))
        p.set_pixel(mx, my, 100, 100, 160)

    hour_angle = (now.hour % 12 + now.minute / 60) * 30
    min_angle = (now.minute + now.second / 60) * 6
    sec_angle = now.second * 6

    hour_len = max(3, int(face_r * 0.5))
    min_len = max(4, int(face_r * 0.75))
    sec_len = max(5, int(face_r * 0.85))

    draw_hand(p, cx, cy, hour_angle, hour_len, 220, 220, 255, width=2 if s >= 64 else 1)
    draw_hand(p, cx, cy, min_angle, min_len, 180, 180, 220)
    draw_hand(p, cx, cy, sec_angle, sec_len, 255, 60, 60)

    p.set_pixel(cx, cy, 255, 255, 255)

    if s >= 32:
        time_str = now.strftime("%H:%M")
        p.draw_text(time_str, cx, s - 7, 140, 140, 180, align="center")


GIF_FRAMES = 30


if __name__ == "__main__":
    save_gif = "--gif" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--gif"]
    ip = args[0] if args else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python clock.py <IP> [--gif]  (or set PIXOO_IP)")
        sys.exit(1)
    p = Pixoo(ip)

    if save_gif:
        from datetime import timedelta

        print(f"Capturing {GIF_FRAMES} frames for GIF on {p}...")
        now = datetime.now()
        snapshots = []
        for i in range(GIF_FRAMES):
            draw_clock(p, now + timedelta(seconds=i))
            snapshots.append(p.snapshot())
        p.save_gif("clock.gif", snapshots, speed_ms=1000)
        print("Saved preview to clock.gif")
    else:
        print(f"Running clock on {p}  (Ctrl-C to stop)")
        try:
            while True:
                draw_clock(p, datetime.now())
                p.push()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
