"""
pixoo — control a Divoom Pixoo LED display over its local HTTP API.

Supports the Pixoo 16 (16x16), Pixoo 32 (32x32), and Pixoo 64 (64x64).

    from pixoo import Pixoo

    p = Pixoo("10.0.0.42")          # default size=64
    p.clear(0, 0, 0)
    p.draw_circle(32, 32, 20, 255, 0, 0, filled=True)
    p.push()

API reference: every command is ``POST http://<ip>/post`` with a JSON body.
Pixel buffers are ``size * size * 3`` bytes (RGB), base64-encoded in ``PicData``.

Channel system
--------------
The device has four channels:

    0 = Faces (clock / widgets — the phone app configures these)
    1 = Cloud Channel
    2 = Visualizer (audio EQ)
    3 = Custom (what ``push()`` draws into)

Calling ``push()`` automatically switches the device to channel 3.  However,
the **phone app can switch the channel back** at any time (e.g. to show a
clock face, stock ticker, or weather widget on channel 0).  There is no way
to "lock out" the app — the last command wins.

To stay visible you can either:
- Close / disconnect the phone app,
- Call ``set_startup_channel(3)`` so the device boots into Custom, or
- Re-push periodically from a script.
"""

from __future__ import annotations

import base64
import time

import requests

__all__ = ["Pixoo", "discover", "hsv_to_rgb"]

# ---------------------------------------------------------------------------
# Optional PIL support — gracefully degrade if not installed
# ---------------------------------------------------------------------------
try:
    from PIL import Image, ImageOps

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ---------------------------------------------------------------------------
# Divoom cloud endpoint used for LAN discovery
# ---------------------------------------------------------------------------
_DIVOOM_DISCOVER_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"

# Firmware bug: the device stops responding after ~300 buffer pushes.
# Auto-reset the counter every N frames to stay healthy.
_COUNTER_RESET_LIMIT = 32


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(timeout: float = 5) -> list[dict]:
    """Ask the Divoom cloud which Pixoo devices are on the same LAN.

    Returns a list of dicts with keys like ``DeviceName``, ``DevicePrivateIP``,
    ``DeviceId``, etc.  Returns ``[]`` on failure.
    """
    try:
        resp = requests.post(_DIVOOM_DISCOVER_URL, timeout=timeout)
        data = resp.json()
        if data.get("ReturnCode") == 0:
            return data.get("DeviceList", [])
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Pixoo
# ---------------------------------------------------------------------------

_VALID_SIZES = (16, 32, 64)


class Pixoo:
    """Draw on a Divoom Pixoo display (16x16, 32x32, or 64x64) over Wi-Fi."""

    def __init__(
        self,
        ip: str,
        port: int = 80,
        *,
        size: int = 64,
        refresh_connection: bool = True,
        debug: bool = False,
    ):
        if size not in _VALID_SIZES:
            raise ValueError(f"size must be one of {_VALID_SIZES}, got {size}")
        self.ip = ip
        self.size = size
        self.debug = debug
        self._url = f"http://{ip}:{port}/post"
        self._refresh = refresh_connection
        self._counter: int = 0
        self._pushes: int = 0
        self._buffer = bytearray(self.size * self.size * 3)

        if self.ping():
            self._load_counter()
            if self._refresh and self._counter > _COUNTER_RESET_LIMIT:
                self._reset_counter()

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    def _post(self, command: str, **kwargs) -> dict:
        payload = {"Command": command, **kwargs}
        if self.debug:
            print(f"[>] {command}")
        try:
            resp = requests.post(self._url, json=payload, timeout=10)
            data = resp.json()
        except requests.RequestException as exc:
            if self.debug:
                print(f"[!] {command}: {exc}")
            return {"error_code": -1, "error": str(exc)}
        if self.debug and data.get("error_code", 0) != 0:
            print(f"[!] {data}")
        return data

    def ping(self, timeout: float = 3) -> bool:
        """Return True if the device is reachable."""
        try:
            resp = requests.post(
                self._url,
                json={"Command": "Channel/GetIndex"},
                timeout=timeout,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Counter management (firmware stability workaround)
    # ------------------------------------------------------------------

    def _load_counter(self):
        try:
            data = self._post("Draw/GetHttpGifId")
            self._counter = int(data.get("PicId", 0))
        except Exception:
            self._counter = 0

    def _reset_counter(self):
        self._post("Draw/ResetHttpGifId")
        self._counter = 0

    # ------------------------------------------------------------------
    # Device controls
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Return all device configuration."""
        return self._post("Channel/GetAllConf")

    def get_time(self) -> dict:
        return self._post("Device/GetDeviceTime")

    def set_brightness(self, level: int) -> dict:
        """Set display brightness (0–100)."""
        return self._post("Channel/SetBrightness", Brightness=_clamp(level, 0, 100))

    def get_channel(self) -> int:
        """Return the current channel index."""
        data = self._post("Channel/GetIndex")
        return data.get("SelectIndex", -1)

    def set_channel(self, index: int) -> dict:
        """Switch channel.  0=Faces, 1=Cloud, 2=Visualizer, 3=Custom."""
        return self._post("Channel/SetIndex", SelectIndex=index)

    def set_startup_channel(self, index: int) -> dict:
        """Set which channel the device boots into (survives reboot)."""
        return self._post("Channel/SetStartupChannel", ChannelId=index)

    def set_clock(self, clock_id: int) -> dict:
        """Select a clock/face by ID."""
        return self._post("Channel/SetClockSelectId", ClockId=clock_id)

    def set_visualizer(self, position: int) -> dict:
        """Select an equalizer visualizer."""
        return self._post("Channel/SetEqPosition", EqPosition=position)

    def set_screen(self, on: bool = True) -> dict:
        """Turn the screen on or off."""
        return self._post("Channel/OnOffScreen", OnOff=1 if on else 0)

    def screen_on(self) -> dict:
        return self.set_screen(True)

    def screen_off(self) -> dict:
        return self.set_screen(False)

    def set_mirror(self, on: bool = False) -> dict:
        return self._post("Device/SetMirrorMode", Mode=on)

    def set_highlight(self, on: bool = True) -> dict:
        return self._post("Device/SetHighLightMode", Mode=on)

    def set_white_balance(self, r: int, g: int, b: int) -> dict:
        """Set white balance (each channel 0–100)."""
        return self._post(
            "Device/SetWhiteBalance",
            RValue=_clamp(r, 0, 100),
            GValue=_clamp(g, 0, 100),
            BValue=_clamp(b, 0, 100),
        )

    def set_noise(self, on: bool = True) -> dict:
        return self._post("Tools/SetNoiseStatus", NoiseStatus=on)

    def set_scoreboard(self, blue: int, red: int) -> dict:
        return self._post(
            "Tools/SetScoreBoard",
            BlueScore=_clamp(blue, 0, 999),
            RedScore=_clamp(red, 0, 999),
        )

    def buzzer(
        self,
        active_ms: int = 500,
        inactive_ms: int = 500,
        total_ms: int = 3000,
    ) -> dict:
        """Buzz the device buzzer."""
        return self._post(
            "Device/PlayBuzzer",
            ActiveTimeInCycle=active_ms,
            OffTimeInCycle=inactive_ms,
            PlayTotalTime=total_ms,
        )

    def reboot(self) -> dict:
        return self._post("Device/SysReboot")

    def play_gif_url(self, url: str) -> dict:
        """Play a GIF from a URL on the device."""
        return self._post("Device/PlayTFGif", FileType=2, FileName=url)

    # ------------------------------------------------------------------
    # Drawing — buffer manipulation
    # ------------------------------------------------------------------

    def clear(self, r: int = 0, g: int = 0, b: int = 0):
        """Fill the entire buffer with one colour."""
        pixel = bytes([r, g, b])
        self._buffer[:] = pixel * (self.size * self.size)

    def fill(self, r: int = 0, g: int = 0, b: int = 0):
        """Alias for :meth:`clear`."""
        self.clear(r, g, b)

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int):
        if 0 <= x < self.size and 0 <= y < self.size:
            off = (y * self.size + x) * 3
            self._buffer[off] = r
            self._buffer[off + 1] = g
            self._buffer[off + 2] = b

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        if not (0 <= x < self.size and 0 <= y < self.size):
            return (0, 0, 0)
        off = (y * self.size + x) * 3
        return self._buffer[off], self._buffer[off + 1], self._buffer[off + 2]

    def draw_line(self, x0: int, y0: int, x1: int, y1: int, r: int, g: int, b: int):
        """Bresenham's line algorithm."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set_pixel(x0, y0, r, g, b)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def draw_rect(
        self, x: int, y: int, w: int, h: int, r: int, g: int, b: int,
        *, filled: bool = False,
    ):
        if filled:
            for dy in range(h):
                py = y + dy
                if 0 <= py < self.size:
                    x_start = max(0, x)
                    x_end = min(self.size, x + w)
                    if x_start < x_end:
                        off = (py * self.size + x_start) * 3
                        chunk = bytes([r, g, b]) * (x_end - x_start)
                        self._buffer[off : off + len(chunk)] = chunk
        else:
            self.draw_line(x, y, x + w - 1, y, r, g, b)
            self.draw_line(x, y + h - 1, x + w - 1, y + h - 1, r, g, b)
            self.draw_line(x, y, x, y + h - 1, r, g, b)
            self.draw_line(x + w - 1, y, x + w - 1, y + h - 1, r, g, b)

    def draw_circle(
        self, cx: int, cy: int, radius: int, r: int, g: int, b: int,
        *, filled: bool = False,
    ):
        # Midpoint circle with optional fill
        x = 0
        y = radius
        d = 1 - radius
        while x <= y:
            if filled:
                self._hline(cx - y, cx + y, cy + x, r, g, b)
                self._hline(cx - y, cx + y, cy - x, r, g, b)
                self._hline(cx - x, cx + x, cy + y, r, g, b)
                self._hline(cx - x, cx + x, cy - y, r, g, b)
            else:
                for sx, sy in [
                    (cx + x, cy + y), (cx - x, cy + y),
                    (cx + x, cy - y), (cx - x, cy - y),
                    (cx + y, cy + x), (cx - y, cy + x),
                    (cx + y, cy - x), (cx - y, cy - x),
                ]:
                    self.set_pixel(sx, sy, r, g, b)
            if d < 0:
                d += 2 * x + 3
            else:
                d += 2 * (x - y) + 5
                y -= 1
            x += 1

    def _hline(self, x0: int, x1: int, y: int, r: int, g: int, b: int):
        if 0 <= y < self.size:
            x0 = max(0, x0)
            x1 = min(self.size - 1, x1)
            if x0 <= x1:
                off = (y * self.size + x0) * 3
                chunk = bytes([r, g, b]) * (x1 - x0 + 1)
                self._buffer[off : off + len(chunk)] = chunk

    # ------------------------------------------------------------------
    # Image loading (requires Pillow)
    # ------------------------------------------------------------------

    def draw_image(
        self,
        source,
        xy: tuple[int, int] = (0, 0),
        *,
        resample=None,
        pad: bool = False,
    ):
        """Load an image file (path, file object, or PIL Image) into the buffer.

        Automatically resizes to fit the display.  Requires ``Pillow``.
        """
        if not _HAS_PIL:
            raise ImportError("Pillow is required for draw_image: pip install Pillow")

        img = source if isinstance(source, Image.Image) else Image.open(source)

        if resample is None:
            resample = Image.Resampling.NEAREST

        if img.size[0] > self.size or img.size[1] > self.size:
            if pad:
                img = ImageOps.pad(img, (self.size, self.size), resample)
            else:
                img.thumbnail((self.size, self.size), resample)

        rgb = img.convert("RGB")
        iw, ih = rgb.size
        raw = rgb.tobytes()
        ox, oy = xy

        for row in range(ih):
            dst_y = oy + row
            if not (0 <= dst_y < self.size):
                continue
            src_off = row * iw * 3
            dst_x0 = max(0, ox)
            dst_x1 = min(self.size, ox + iw)
            if dst_x0 >= dst_x1:
                continue
            crop_left = dst_x0 - ox
            crop_right = dst_x1 - ox
            src_start = src_off + crop_left * 3
            src_end = src_off + crop_right * 3
            dst_off = (dst_y * self.size + dst_x0) * 3
            self._buffer[dst_off : dst_off + (src_end - src_start)] = raw[src_start:src_end]

    # ------------------------------------------------------------------
    # Push buffer to the device
    # ------------------------------------------------------------------

    def push(self) -> dict:
        """Send the current buffer to the display as a single frame."""
        self._counter += 1
        if self._refresh and self._counter >= _COUNTER_RESET_LIMIT:
            self._reset_counter()
            self._counter = 1

        pic_data = base64.b64encode(bytes(self._buffer)).decode("ascii")
        result = self._post(
            "Draw/SendHttpGif",
            PicNum=1,
            PicWidth=self.size,
            PicOffset=0,
            PicID=self._counter,
            PicSpeed=1000,
            PicData=pic_data,
        )
        self._pushes += 1
        return result

    def push_animation(self, frames: list[bytes | bytearray], speed_ms: int = 100) -> list[dict]:
        """Send multiple frame buffers as a looping animation.

        Each frame must be a ``size * size * 3`` byte RGB buffer.
        Tip: build frames by drawing into the buffer, then snapshot with
        ``bytes(p._buffer)`` before drawing the next frame.
        """
        self._counter += 1
        if self._refresh and self._counter >= _COUNTER_RESET_LIMIT:
            self._reset_counter()
            self._counter = 1

        results = []
        for i, frame in enumerate(frames):
            pic_data = base64.b64encode(bytes(frame)).decode("ascii")
            results.append(self._post(
                "Draw/SendHttpGif",
                PicNum=len(frames),
                PicWidth=self.size,
                PicOffset=i,
                PicID=self._counter,
                PicSpeed=speed_ms,
                PicData=pic_data,
            ))
        self._pushes += 1
        return results

    def snapshot(self) -> bytes:
        """Return a copy of the current buffer (useful for building animations)."""
        return bytes(self._buffer)

    def hold(self, seconds: float = 60, interval: float = 10):
        """Re-push the current buffer periodically to prevent the phone app
        from reclaiming the display.  Blocks for *seconds*."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.push()
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(interval, remaining))

    # ------------------------------------------------------------------
    # Gradient fill
    # ------------------------------------------------------------------

    def draw_gradient(
        self,
        x: int, y: int, w: int, h: int,
        r0: int, g0: int, b0: int,
        r1: int, g1: int, b1: int,
        *,
        direction: str = "vertical",
    ):
        """Fill a rectangle with a linear gradient between two colours.

        *direction*: ``"vertical"`` (top to bottom, default) or
        ``"horizontal"`` (left to right).
        """
        if w <= 0 or h <= 0:
            return
        steps = h if direction == "vertical" else w
        for i in range(steps):
            t = i / max(1, steps - 1)
            cr = int(r0 + (r1 - r0) * t)
            cg = int(g0 + (g1 - g0) * t)
            cb = int(b0 + (b1 - b0) * t)
            if direction == "vertical":
                py = y + i
                if 0 <= py < self.size:
                    x_start = max(0, x)
                    x_end = min(self.size, x + w)
                    if x_start < x_end:
                        off = (py * self.size + x_start) * 3
                        chunk = bytes([cr, cg, cb]) * (x_end - x_start)
                        self._buffer[off : off + len(chunk)] = chunk
            else:
                px = x + i
                if 0 <= px < self.size:
                    y_start = max(0, y)
                    y_end = min(self.size, y + h)
                    for py in range(y_start, y_end):
                        off = (py * self.size + px) * 3
                        self._buffer[off] = cr
                        self._buffer[off + 1] = cg
                        self._buffer[off + 2] = cb

    # ------------------------------------------------------------------
    # Progress / gauge bar
    # ------------------------------------------------------------------

    def draw_bar(
        self, x: int, y: int, w: int, h: int, value: float,
        r: int, g: int, b: int,
        bg_r: int = 40, bg_g: int = 40, bg_b: int = 40,
    ):
        """Draw a horizontal progress bar.

        *value* is clamped to 0.0–1.0.  The filled portion uses (r, g, b),
        the remaining background uses (bg_r, bg_g, bg_b).
        """
        value = max(0.0, min(1.0, value))
        filled_w = int(w * value + 0.5)
        if filled_w > 0:
            self.draw_rect(x, y, filled_w, h, r, g, b, filled=True)
        remaining = w - filled_w
        if remaining > 0:
            self.draw_rect(x + filled_w, y, remaining, h, bg_r, bg_g, bg_b, filled=True)

    # ------------------------------------------------------------------
    # Client-side bitmap text (PICO-8 font, 3x5 glyphs, 4px cell width)
    # ------------------------------------------------------------------

    def draw_char(self, ch: str, x: int, y: int, r: int, g: int, b: int) -> int:
        """Render a single character into the buffer. Returns glyph width (3)."""
        glyph = _FONT_PICO8.get(ch)
        if glyph is None:
            return 3
        for i, bit in enumerate(glyph):
            if bit:
                self.set_pixel(x + i % 3, y + i // 3, r, g, b)
        return 3

    def text_width(self, text: str) -> int:
        """Return the pixel width of a string (no wrapping)."""
        return max(0, len(text) * 4 - 1) if text else 0

    def draw_text(
        self, text: str, x: int, y: int, r: int, g: int, b: int,
        *, align: str = "left", max_width: int = 0,
    ):
        """Render a string into the pixel buffer using the built-in PICO-8 font.

        Each character occupies a 4px-wide cell (3px glyph + 1px gap).
        Lines are 6px tall (5px glyph + 1px gap).  On a 64px display that
        gives 16 chars/line and ~10 lines.

        *align*: ``"left"`` (default), ``"center"``, or ``"right"``.
        Alignment is relative to *x*.  For center/right, *x* is the
        center-point or right edge respectively.

        *max_width*: if > 0, wrap words so no line exceeds this many pixels.
        Lines are broken on spaces when possible, or mid-word if a single
        word is too long.  Explicit ``\\n`` always starts a new line.
        """
        if max_width <= 0:
            max_width = 0
        chars_per_line = max_width // 4 if max_width else 0

        lines = self._wrap_text(text, chars_per_line)

        for line in lines:
            lw = self.text_width(line)
            if align == "right":
                cx = x - lw
            elif align == "center":
                cx = x - lw // 2
            else:
                cx = x
            for ch in line:
                self.draw_char(ch, cx, y, r, g, b)
                cx += 4
            y += 6

    @staticmethod
    def _wrap_text(text: str, chars_per_line: int) -> list[str]:
        """Split text into lines, respecting \\n and optional word wrap."""
        raw_lines = text.split("\n")
        if chars_per_line <= 0:
            return raw_lines

        result: list[str] = []
        for raw in raw_lines:
            if not raw:
                result.append("")
                continue
            words = raw.split(" ")
            current = ""
            for word in words:
                while len(word) > chars_per_line:
                    space = chars_per_line - len(current)
                    if current:
                        current += word[:space]
                        result.append(current)
                        word = word[space:]
                        current = ""
                    else:
                        result.append(word[:chars_per_line])
                        word = word[chars_per_line:]
                if not current:
                    current = word
                elif len(current) + 1 + len(word) <= chars_per_line:
                    current += " " + word
                else:
                    result.append(current)
                    current = word
            result.append(current)
        return result

    # ------------------------------------------------------------------
    # Device-side text overlay
    # ------------------------------------------------------------------

    def send_text(
        self,
        text: str,
        *,
        x: int = 0,
        y: int = 0,
        color: str = "#FFFFFF",
        identifier: int = 1,
        font: int = 2,
        width: int = 0,
        speed: int = 0,
        direction: int = 0,
    ) -> dict:
        """Display text using the device's built-in renderer.

        *speed* 0 = static, >0 = scroll speed in ms.
        *font* 0–7.  *direction* 0 = left, 1 = right.
        """
        return self._post(
            "Draw/SendHttpText",
            TextId=_clamp(identifier, 0, 19),
            x=x, y=y, dir=direction, font=font,
            TextWidth=width or self.size, speed=speed,
            align=1, color=color, TextString=text,
        )

    def clear_text(self) -> dict:
        return self._post("Draw/ClearHttpText")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __repr__(self):
        return f"Pixoo({self.ip!r}, size={self.size})"


# ---------------------------------------------------------------------------
# PICO-8 bitmap font (3x5 glyphs as flat 0/1 lists)
# Source: SomethingWithComputers/pixoo (MIT license)
# ---------------------------------------------------------------------------

_FONT_PICO8 = {
    '0': [1,1,1, 1,0,1, 1,0,1, 1,0,1, 1,1,1],
    '1': [1,1,0, 0,1,0, 0,1,0, 0,1,0, 1,1,1],
    '2': [1,1,1, 0,0,1, 1,1,1, 1,0,0, 1,1,1],
    '3': [1,1,1, 0,0,1, 0,1,1, 0,0,1, 1,1,1],
    '4': [1,0,1, 1,0,1, 1,1,1, 0,0,1, 0,0,1],
    '5': [1,1,1, 1,0,0, 1,1,1, 0,0,1, 1,1,1],
    '6': [1,0,0, 1,0,0, 1,1,1, 1,0,1, 1,1,1],
    '7': [1,1,1, 0,0,1, 0,0,1, 0,0,1, 0,0,1],
    '8': [1,1,1, 1,0,1, 1,1,1, 1,0,1, 1,1,1],
    '9': [1,1,1, 1,0,1, 1,1,1, 0,0,1, 0,0,1],
    'A': [1,1,1, 1,0,1, 1,1,1, 1,0,1, 1,0,1],
    'B': [1,1,1, 1,0,1, 1,1,0, 1,0,1, 1,1,1],
    'C': [0,1,1, 1,0,0, 1,0,0, 1,0,0, 0,1,1],
    'D': [1,1,0, 1,0,1, 1,0,1, 1,0,1, 1,1,1],
    'E': [1,1,1, 1,0,0, 1,1,0, 1,0,0, 1,1,1],
    'F': [1,1,1, 1,0,0, 1,1,0, 1,0,0, 1,0,0],
    'G': [0,1,1, 1,0,0, 1,0,0, 1,0,1, 1,1,1],
    'H': [1,0,1, 1,0,1, 1,1,1, 1,0,1, 1,0,1],
    'I': [1,1,1, 0,1,0, 0,1,0, 0,1,0, 1,1,1],
    'J': [1,1,1, 0,1,0, 0,1,0, 0,1,0, 1,1,0],
    'K': [1,0,1, 1,0,1, 1,1,0, 1,0,1, 1,0,1],
    'L': [1,0,0, 1,0,0, 1,0,0, 1,0,0, 1,1,1],
    'M': [1,1,1, 1,1,1, 1,0,1, 1,0,1, 1,0,1],
    'N': [1,1,0, 1,0,1, 1,0,1, 1,0,1, 1,0,1],
    'O': [0,1,1, 1,0,1, 1,0,1, 1,0,1, 1,1,0],
    'P': [1,1,1, 1,0,1, 1,1,1, 1,0,0, 1,0,0],
    'Q': [0,1,0, 1,0,1, 1,0,1, 1,1,0, 0,1,1],
    'R': [1,1,1, 1,0,1, 1,1,0, 1,0,1, 1,0,1],
    'S': [0,1,1, 1,0,0, 1,1,1, 0,0,1, 1,1,0],
    'T': [1,1,1, 0,1,0, 0,1,0, 0,1,0, 0,1,0],
    'U': [1,0,1, 1,0,1, 1,0,1, 1,0,1, 0,1,1],
    'V': [1,0,1, 1,0,1, 1,0,1, 1,1,1, 0,1,0],
    'W': [1,0,1, 1,0,1, 1,0,1, 1,1,1, 1,1,1],
    'X': [1,0,1, 1,0,1, 0,1,0, 1,0,1, 1,0,1],
    'Y': [1,0,1, 1,0,1, 1,1,1, 0,0,1, 1,1,1],
    'Z': [1,1,1, 0,0,1, 0,1,0, 1,0,0, 1,1,1],
    'a': [0,0,0, 0,1,1, 1,0,1, 1,1,1, 1,0,1],
    'b': [0,0,0, 1,1,0, 1,1,0, 1,0,1, 1,1,1],
    'c': [0,0,0, 0,1,1, 1,0,0, 1,0,0, 0,1,1],
    'd': [0,0,0, 1,1,0, 1,0,1, 1,0,1, 1,1,0],
    'e': [0,0,0, 1,1,1, 1,1,0, 1,0,0, 0,1,1],
    'f': [0,0,0, 1,1,1, 1,1,0, 1,0,0, 1,0,0],
    'g': [0,0,0, 0,1,1, 1,0,0, 1,0,1, 1,1,1],
    'h': [0,0,0, 1,0,1, 1,0,1, 1,1,1, 1,0,1],
    'i': [0,0,0, 1,1,1, 0,1,0, 0,1,0, 1,1,1],
    'j': [0,0,0, 1,1,1, 0,1,0, 0,1,0, 1,1,0],
    'k': [0,0,0, 1,0,1, 1,1,0, 1,0,1, 1,0,1],
    'l': [0,0,0, 1,0,0, 1,0,0, 1,0,0, 0,1,1],
    'm': [0,0,0, 1,1,1, 1,1,1, 1,0,1, 1,0,1],
    'n': [0,0,0, 1,1,0, 1,0,1, 1,0,1, 1,0,1],
    'o': [0,0,0, 0,1,1, 1,0,1, 1,0,1, 1,1,0],
    'p': [0,0,0, 0,1,1, 1,0,1, 1,1,1, 1,0,0],
    'q': [0,0,0, 0,1,0, 1,0,1, 1,1,0, 0,1,1],
    'r': [0,0,0, 1,1,0, 1,0,1, 1,1,0, 1,0,1],
    's': [0,0,0, 0,1,1, 1,0,0, 0,0,1, 1,1,0],
    't': [0,0,0, 1,1,1, 0,1,0, 0,1,0, 0,1,0],
    'u': [0,0,0, 1,0,1, 1,0,1, 1,0,1, 0,1,1],
    'v': [0,0,0, 1,0,1, 1,0,1, 1,1,1, 0,1,0],
    'w': [0,0,0, 1,0,1, 1,0,1, 1,1,1, 1,1,1],
    'x': [0,0,0, 1,0,1, 0,1,0, 0,1,0, 1,0,1],
    'y': [0,0,0, 1,0,1, 1,1,1, 0,0,1, 1,1,0],
    'z': [0,0,0, 1,1,1, 0,0,1, 1,0,0, 1,1,1],
    ' ': [0,0,0, 0,0,0, 0,0,0, 0,0,0, 0,0,0],
    '!': [0,1,0, 0,1,0, 0,1,0, 0,0,0, 0,1,0],
    "'": [0,1,0, 1,0,0, 0,0,0, 0,0,0, 0,0,0],
    '(': [0,1,0, 1,0,0, 1,0,0, 1,0,0, 0,1,0],
    ')': [0,1,0, 0,0,1, 0,0,1, 0,0,1, 0,1,0],
    '+': [0,0,0, 0,1,0, 1,1,1, 0,1,0, 0,0,0],
    ',': [0,0,0, 0,0,0, 0,0,0, 0,1,0, 1,0,0],
    '-': [0,0,0, 0,0,0, 1,1,1, 0,0,0, 0,0,0],
    '.': [0,0,0, 0,0,0, 0,0,0, 0,0,0, 0,1,0],
    '/': [0,0,1, 0,1,0, 0,1,0, 0,1,0, 1,0,0],
    ':': [0,0,0, 0,1,0, 0,0,0, 0,1,0, 0,0,0],
    ';': [0,0,0, 0,1,0, 0,0,0, 0,1,0, 1,0,0],
    '<': [0,0,1, 0,1,0, 1,0,0, 0,1,0, 0,0,1],
    '=': [0,0,0, 1,1,1, 0,0,0, 1,1,1, 0,0,0],
    '>': [1,0,0, 0,1,0, 0,0,1, 0,1,0, 1,0,0],
    '?': [1,1,1, 0,0,1, 0,1,1, 0,0,0, 0,1,0],
    '@': [0,1,0, 1,0,1, 1,0,1, 1,0,0, 0,1,1],
    '$': [1,1,1, 1,1,0, 0,1,1, 1,1,1, 0,1,0],
    '%': [1,0,1, 0,0,1, 0,1,0, 1,0,0, 1,0,1],
    '[': [1,1,0, 1,0,0, 1,0,0, 1,0,0, 1,1,0],
    ']': [0,1,1, 0,0,1, 0,0,1, 0,0,1, 0,1,1],
    '^': [0,1,0, 1,0,1, 0,0,0, 0,0,0, 0,0,0],
    '_': [0,0,0, 0,0,0, 0,0,0, 0,0,0, 1,1,1],
    '{': [0,1,1, 0,1,0, 1,1,0, 0,1,0, 0,1,1],
    '|': [0,1,0, 0,1,0, 0,1,0, 0,1,0, 0,1,0],
    '}': [1,1,0, 0,1,0, 0,1,1, 0,1,0, 1,1,0],
    '~': [0,0,0, 0,0,1, 1,1,1, 1,0,0, 0,0,0],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def hsv_to_rgb(h: float, s: float = 1.0, v: float = 1.0) -> tuple[int, int, int]:
    """Convert HSV (each 0.0–1.0) to an (r, g, b) tuple of ints."""
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i %= 6
    if i == 0:   r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    else:        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)
