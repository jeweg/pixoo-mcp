#!/usr/bin/env python3
"""Pixel-art scene built from bitmap sprites.

64px only.  Showcases:
  - draw_bitmap (palette + character-grid sprites at various scales)
  - draw_gradient (sky and water)
  - parse_color / CSS colour names
  - save_png (export the buffer to a file)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pixoo import Pixoo, parse_color


def pixel_art(p: Pixoo):
    if p.size < 64:
        print("This example is designed for 64x64 displays.")
        return

    # --- sky gradient (dark blue → deep purple at horizon) ---
    p.draw_gradient(0, 0, 64, 42, *parse_color("#000830"), *parse_color("#1a0040"))

    # --- stars (scattered single pixels) ---
    stars = [
        (5, 3), (12, 7), (20, 2), (28, 9), (35, 4),
        (42, 6), (50, 1), (8, 14), (15, 11), (3, 20),
        (22, 16), (38, 12), (55, 8), (18, 18), (45, 15),
    ]
    for x, y in stars:
        p.set_pixel(x, y, *parse_color("white"))

    # --- crescent moon ---
    p.draw_circle(50, 10, 7, *parse_color("#ffcc00"), filled=True)
    p.draw_circle(53, 8, 6, *parse_color("#000830"), filled=True)

    # --- mountains (bitmap, dark silhouette with subtle shading) ---
    mountain_palette = [
        None,             # 0 = transparent
        (20, 15, 40),     # 1 = dark purple-grey
        (30, 25, 55),     # 2 = mid
        (15, 10, 30),     # 3 = darkest
    ]
    mountain_data = [
        "0000000000001000000000000000000000010000000000000000000000100000",
        "0000000000012100000000000000000000121000000000000000000001210000",
        "0000000000121210000000001000000001212100000000010000000012321000",
        "0000000001212321000000012100000012132100000000121000000123213100",
        "0000010012132132100000121210001213213210000001213100012132132100",
        "0000121121321321210001213213012132132132100012132131121321321310",
        "1001213213213213213101321321321321321321310121321321321321321321",
        "2112132132132132132132132132132132132132132132132132132132132132",
    ]
    p.draw_bitmap(0, 27, mountain_palette, mountain_data)

    # --- ground ---
    p.draw_rect(0, 35, 64, 7, *parse_color("#0a1a0a"), filled=True)
    p.draw_gradient(0, 35, 64, 3, *parse_color("#1a0040"), *parse_color("#0a1a0a"))

    # --- tree (trunk + foliage bitmap) ---
    p.draw_line(20, 41, 20, 30, *parse_color("#3a2010"))
    p.draw_line(21, 41, 21, 30, *parse_color("#4a2a15"))
    tree_palette = [None, (0, 85, 0), (0, 119, 0), (0, 153, 0), (0, 51, 0)]
    tree_data = [
        "00010200300",
        "00201302100",
        "01323123210",
        "23132313230",
        "03121321200",
        "00130210300",
        "00010030000",
    ]
    p.draw_bitmap(13, 23, tree_palette, tree_data)

    # --- campfire ---
    fire_palette = [
        None,
        parse_color("#ff4400"),
        parse_color("#ff6600"),
        parse_color("#ff8800"),
        parse_color("#ffaa00"),
        parse_color("#552200"),
        parse_color("#331100"),
    ]
    fire_data = [
        "000010100000",
        "000121210000",
        "001232321000",
        "012343432100",
        "012343432100",
        "001234321000",
        "000565650000",
        "000656560000",
        "000565650000",
    ]
    p.draw_bitmap(35, 28, fire_palette, fire_data, scale=1)

    # --- ember sparks ---
    for x, y, c in [(38, 26, "#ff8800"), (42, 25, "#ffaa00"), (40, 24, "#ff6600")]:
        p.set_pixel(x, y, *parse_color(c))

    # --- lake / water ---
    p.draw_gradient(0, 42, 64, 20, *parse_color("#001a33"), *parse_color("#002244"))
    p.draw_line(0, 42, 63, 42, *parse_color("#003355"))

    # --- moon reflection on water ---
    reflection = [None, parse_color("#004466"), parse_color("#003355")]
    reflection_data = [
        "00001000001000",
        "00012100012100",
        "00121210121210",
        "01212121212100",
    ]
    p.draw_bitmap(22, 44, reflection, reflection_data)

    # --- flowers along the shore ---
    flower_specs = [
        (2,  38, ["#ffff00", "#ffcc00", "#ffaa00"]),      # yellow
        (56, 38, ["#ff00ff", "#cc00cc", "#ff44ff"]),       # magenta
        (12, 39, ["#00ffaa", "#00cc88", "#00aa66"]),       # teal
        (48, 39, ["#ff6688", "#ff4466", "#cc3355"]),       # rose
    ]
    flower_data = ["01010", "12121", "01010", "00100"]
    for fx, fy, colours in flower_specs:
        pal = [None] + [parse_color(c) for c in colours]
        p.draw_bitmap(fx, fy, pal, flower_data)

    # --- fireflies over the water ---
    for x, y in [(5, 50), (15, 53), (40, 48), (55, 51), (32, 55)]:
        p.set_pixel(x, y, *parse_color("#ffcc00"))


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PIXOO_IP")
    if not ip:
        print("Usage: python pixel_art.py <IP>  (or set PIXOO_IP)")
        sys.exit(1)
    p = Pixoo(ip, size=64)
    pixel_art(p)
    print(p.push())
    p.save_png("pixel_art.png")
    print("Saved preview to pixel_art.png")
