#!/usr/bin/env python3
"""System-monitor style dashboard.

Works on all display sizes (16, 32, 64).  Showcases:
  - draw_text (with alignment)
  - draw_bar (progress bars)
  - draw_rect (panels / dividers)
  - draw_line (separators)
  - clear
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo


def dashboard(p: Pixoo):
    s = p.size
    p.clear(0, 0, 0)

    if s >= 64:
        # --- 64px: full dashboard with header, 3 labelled bars, footer ---
        p.draw_rect(0, 0, s, 9, 20, 20, 50, filled=True)
        p.draw_text("SYSTEM", s // 2, 1, 200, 200, 255, align="center")
        p.draw_line(0, 9, s - 1, 9, 40, 40, 80)

        metrics = [
            ("CPU",  0.72, 0, 220, 100),
            ("MEM",  0.45, 100, 180, 255),
            ("DISK", 0.88, 255, 160, 0),
        ]
        y = 14
        for label, value, r, g, b in metrics:
            p.draw_text(label, 1, y, 150, 150, 150)
            p.draw_bar(18, y, 42, 5, value, r, g, b)
            pct = f"{int(value * 100)}%"
            p.draw_text(pct, s - 1, y, r, g, b, align="right")
            y += 10

        p.draw_line(0, y - 4, s - 1, y - 4, 40, 40, 80)

        p.draw_rect(0, y - 1, s, 12, 15, 15, 30, filled=True)
        p.draw_text("eth0", 1, y, 80, 255, 80)
        p.draw_text("UP", s - 1, y, 0, 255, 0, align="right")
        p.draw_text("192.168.1.42", s // 2, y + 6, 120, 120, 120, align="center")

        p.draw_rect(0, s - 7, s, 7, 20, 20, 50, filled=True)
        p.draw_text("12:34", s // 2, s - 6, 180, 180, 255, align="center")

    elif s >= 32:
        # --- 32px: compact 3-bar dashboard ---
        p.draw_text("SYS", s // 2, 0, 200, 200, 255, align="center")
        p.draw_line(0, 6, s - 1, 6, 40, 40, 80)

        bars = [
            (0.72, 0, 220, 100),
            (0.45, 100, 180, 255),
            (0.88, 255, 160, 0),
        ]
        y = 9
        for value, r, g, b in bars:
            p.draw_bar(1, y, s - 2, 4, value, r, g, b)
            y += 7

        p.draw_text("72 45 88", s // 2, s - 6, 150, 150, 150, align="center")

    else:
        # --- 16px: minimal bars ---
        bars = [
            (0.72, 0, 220, 100),
            (0.45, 100, 180, 255),
            (0.88, 255, 160, 0),
        ]
        y = 1
        for value, r, g, b in bars:
            p.draw_bar(1, y, s - 2, 3, value, r, g, b)
            y += 5


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python dashboard.py <IP>  (or set PIXOO_IP)")
        sys.exit(1)
    p = Pixoo(ip)
    dashboard(p)
    print(p.push())
