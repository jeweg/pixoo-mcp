#!/usr/bin/env python3
"""Conway's Game of Life as a looping animation.

Works on all display sizes (16, 32, 64).  Showcases:
  - set_pixel with hsv_to_rgb for colour
  - clear
  - snapshot / push_animation (multi-frame animation)
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo, hsv_to_rgb

FRAMES = 30
SEED_DENSITY = 0.35


def neighbours(grid, x, y, w, h):
    count = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = (x + dx) % w, (y + dy) % h
            count += grid[ny][nx]
    return count


def step(grid, w, h):
    new = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            n = neighbours(grid, x, y, w, h)
            if grid[y][x]:
                new[y][x] = 1 if n in (2, 3) else 0
            else:
                new[y][x] = 1 if n == 3 else 0
    return new


def game_of_life(p: Pixoo, frames: int = FRAMES):
    s = p.size
    random.seed(42)
    grid = [
        [1 if random.random() < SEED_DENSITY else 0 for _ in range(s)]
        for _ in range(s)
    ]

    snapshots = []
    for t in range(frames):
        p.clear(0, 0, 0)
        hue = t / frames
        for y in range(s):
            for x in range(s):
                if grid[y][x]:
                    r, g, b = hsv_to_rgb((hue + x / s * 0.3) % 1.0, 0.8, 1.0)
                    p.set_pixel(x, y, r, g, b)
        snapshots.append(p.snapshot())
        grid = step(grid, s, s)

    return snapshots


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python game_of_life.py <IP>  (or set PIXOO_IP)")
        sys.exit(1)
    p = Pixoo(ip)
    print(f"Generating {FRAMES} frames of Life on {p.size}x{p.size}...")
    frames = game_of_life(p)
    print(p.push_animation(frames, speed_ms=200))
