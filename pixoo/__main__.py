"""
CLI for the pixoo module.

    python -m pixoo [IP] [command] [args...]

Examples:
    python -m pixoo 10.0.0.42 smiley
    python -m pixoo plasma                 # auto-discover or use PIXOO_IP
    python -m pixoo image photo.png
    python -m pixoo text "Hello!"
    python -m pixoo brightness 80
    python -m pixoo info
    python -m pixoo discover
"""

from __future__ import annotations

import math
import sys

from . import Pixoo, discover, hsv_to_rgb

DEFAULT_IP = None


# ---------------------------------------------------------------------------
# Demo patterns
# ---------------------------------------------------------------------------

def pattern_smiley(p: Pixoo):
    s = p.size
    c = s // 2
    p.clear(0, 0, 40)
    p.draw_circle(c, c, s * 27 // 64, 255, 220, 0, filled=True)
    p.draw_circle(c - s * 10 // 64, c - s * 8 // 64, s * 4 // 64, 40, 40, 40, filled=True)
    p.draw_circle(c + s * 10 // 64, c - s * 8 // 64, s * 4 // 64, 40, 40, 40, filled=True)
    mouth_r = s * 16 // 64
    for angle in range(20, 161):
        rad = math.radians(angle)
        x = int(c + mouth_r * math.cos(rad))
        y = int(c + s * 2 // 64 + mouth_r * math.sin(rad))
        p.set_pixel(x, y, 40, 40, 40)
        p.set_pixel(x, y + 1, 40, 40, 40)


def pattern_rainbow(p: Pixoo):
    s = p.size
    for y in range(s):
        for x in range(s):
            r, g, b = hsv_to_rgb((x + y) / (s * 2.0))
            p.set_pixel(x, y, r, g, b)


def pattern_checker(p: Pixoo):
    s = p.size
    cell = max(1, s // 8)
    for y in range(s):
        for x in range(s):
            if ((x // cell) + (y // cell)) % 2 == 0:
                p.set_pixel(x, y, 255, 50, 50)
            else:
                p.set_pixel(x, y, 50, 50, 255)


def pattern_plasma(p: Pixoo):
    s = p.size
    for y in range(s):
        for x in range(s):
            v = math.sin(x / 8.0) + math.sin(y / 6.0)
            v += math.sin((x + y) / 10.0)
            v += math.sin(math.sqrt(x * x + y * y) / 8.0)
            r, g, b = hsv_to_rgb((v / 4.0 + 0.5) % 1.0)
            p.set_pixel(x, y, r, g, b)


def pattern_nyan(p: Pixoo):
    s = p.size
    c = s // 2
    colors = [
        (255, 0, 0), (255, 165, 0), (255, 255, 0),
        (0, 255, 0), (0, 100, 255), (100, 0, 255),
    ]
    stripe_h = s // len(colors)
    for i, (cr, cg, cb) in enumerate(colors):
        p.draw_rect(0, i * stripe_h, s, stripe_h, cr, cg, cb, filled=True)
    bw = s * 20 // 64
    bh = s * 28 // 64
    bx = c - bw // 2
    by = c - bh // 2 - s * 4 // 64
    p.draw_rect(bx, by, bw, bh, 140, 140, 140, filled=True)
    ear = s * 6 // 64
    p.draw_rect(bx, by - ear, ear, ear, 140, 140, 140, filled=True)
    p.draw_rect(bx + bw - ear, by - ear, ear, ear, 140, 140, 140, filled=True)
    eye_y = by + bh * 3 // 10
    p.set_pixel(bx + bw * 3 // 10, eye_y, 255, 255, 255)
    p.set_pixel(bx + bw * 7 // 10, eye_y, 255, 255, 255)


PATTERNS = {
    "smiley": pattern_smiley,
    "rainbow": pattern_rainbow,
    "checker": pattern_checker,
    "plasma": pattern_plasma,
    "nyan": pattern_nyan,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def usage():
    names = ", ".join(PATTERNS)
    print(f"""\
Usage: python -m pixoo [IP] <command> [args...]

  Patterns:   {names}
  image       <path>             Load an image file onto the display
  animation                      Spinning dot animation demo
  text        <message>          Display scrolling text
  brightness  <0-100>            Set display brightness
  info                           Show device configuration
  on / off                       Turn screen on/off
  buzz                           Sound the buzzer
  reboot                         Reboot the device
  discover                       Find Pixoo devices on the LAN

Add --hold to any pattern/image command to re-push every 10s
and prevent the phone app from reclaiming the display:
  python -m pixoo smiley --hold
  python -m pixoo smiley --hold 300   (hold for 5 min)

IP can be passed as the first argument, set via PIXOO_IP env var,
or auto-discovered via the Divoom cloud.""")


def main(argv: list[str] | None = None):
    args = argv or sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        usage()
        return

    # "discover" doesn't need an IP
    if args[0] == "discover":
        print("Querying Divoom cloud for devices on this LAN...")
        devices = discover()
        if devices:
            for d in devices:
                print(f"  {d.get('DeviceName', '?'):20s}  {d.get('DevicePrivateIP', '?')}")
        else:
            print("  No devices found.")
        return

    # Figure out IP vs command
    ip = DEFAULT_IP
    rest = args
    if args[0][0].isdigit():
        ip = args[0]
        rest = args[1:]

    if ip is None:
        import os
        ip = os.environ.get("PIXOO_IP")
    if ip is None:
        devices = discover()
        if devices:
            ip = devices[0].get("DevicePrivateIP")
            print(f"Auto-discovered device at {ip}")
    if ip is None:
        print("No IP provided and no device found. Pass an IP or set PIXOO_IP.")
        return

    cmd = rest[0] if rest else "smiley"
    cmd_args = [a for a in rest[1:] if a != "--hold"]
    hold = "--hold" in rest[1:]
    hold_seconds = 600
    if hold and cmd_args:
        try:
            hold_seconds = int(cmd_args[-1])
            cmd_args = cmd_args[:-1]
        except ValueError:
            pass

    p = Pixoo(ip)

    if cmd in PATTERNS:
        print(f"Drawing '{cmd}' on {ip} ...")
        PATTERNS[cmd](p)
        print(p.push())
        if hold:
            print(f"Holding display for {hold_seconds}s (Ctrl-C to stop) ...")
            try:
                p.hold(hold_seconds)
            except KeyboardInterrupt:
                print("\nStopped.")

    elif cmd == "image":
        path = cmd_args[0] if cmd_args else None
        if not path:
            print("Usage: python -m pixoo [IP] image <path>")
            return
        print(f"Loading {path} onto {ip} ...")
        p.draw_image(path)
        print(p.push())
        if hold:
            print(f"Holding display for {hold_seconds}s (Ctrl-C to stop) ...")
            try:
                p.hold(hold_seconds)
            except KeyboardInterrupt:
                print("\nStopped.")

    elif cmd == "text":
        msg = cmd_args[0] if cmd_args else "Hello!"
        print(p.send_text(msg, speed=100))

    elif cmd == "animation":
        print(f"Sending spinning animation to {ip} ...")
        c = p.size // 2
        orbit = p.size * 20 // 64
        dot_r = max(2, p.size * 6 // 64)
        frames = []
        for t in range(10):
            p.clear(0, 0, 0)
            rad = math.radians(t * 36)
            x = int(c + orbit * math.cos(rad))
            y = int(c + orbit * math.sin(rad))
            p.draw_circle(x, y, dot_r, 255, 100, 0, filled=True)
            frames.append(p.snapshot())
        print(p.push_animation(frames, speed_ms=150))

    elif cmd == "brightness":
        level = int(cmd_args[0]) if cmd_args else 50
        print(p.set_brightness(level))

    elif cmd == "info":
        import json as _json
        print(_json.dumps(p.get_config(), indent=2))

    elif cmd == "on":
        print(p.screen_on())

    elif cmd == "off":
        print(p.screen_off())

    elif cmd == "buzz":
        print(p.buzzer())

    elif cmd == "reboot":
        print(p.reboot())

    elif cmd == "scoreboard":
        blue = int(cmd_args[0]) if len(cmd_args) > 0 else 0
        red = int(cmd_args[1]) if len(cmd_args) > 1 else 0
        print(p.set_scoreboard(blue, red))

    elif cmd == "clock":
        cid = int(cmd_args[0]) if cmd_args else 195
        print(p.set_clock(cid))

    else:
        print(f"Unknown command: {cmd}")
        usage()


if __name__ == "__main__":
    main()
