"""
Pixoo MCP + HTTP server.

Exposes the Pixoo library as MCP tools (for AI agents) and REST endpoints
(for containers / scripts).

MCP (stdio, for Cursor):
    python -m pixoo.server

HTTP (for containers + MCP-over-HTTP):
    python -m pixoo.server --http [--port 9100]

Environment:
    PIXOO_IP     device IP (required, or auto-discovered)
    PIXOO_SIZE   display resolution: 16, 32, or 64 (default 64)
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import Pixoo, parse_color

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_PIXOO_IP = os.environ.get("PIXOO_IP", "")
_PIXOO_SIZE = int(os.environ.get("PIXOO_SIZE", "64"))
_pixoo: Pixoo | None = None
_lock = asyncio.Lock()


def _get_pixoo() -> Pixoo:
    global _pixoo, _PIXOO_IP
    if _pixoo is None:
        if not _PIXOO_IP:
            from . import discover
            devices = discover()
            if devices:
                _PIXOO_IP = devices[0].get("DevicePrivateIP", "")
            if not _PIXOO_IP:
                raise RuntimeError("No PIXOO_IP set and no device found on LAN")
        _pixoo = Pixoo(_PIXOO_IP, size=_PIXOO_SIZE)
    return _pixoo


async def _run_locked(fn, *args, **kwargs):
    """Run a blocking Pixoo method in a thread, holding the lock."""
    async with _lock:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def _ensure_screen_on_sync(p: Pixoo):
    """Best-effort wake before visual updates."""
    try:
        # Some firmware/models report LightSwitch unreliably, so do an
        # idempotent wake call directly instead of branching on config.
        p.screen_on()
    except Exception:
        # Avoid blocking draw/text/image operations if wake fails.
        pass


# Required fields for each op, *excluding* colour fields.  Colours are
# validated separately via _color() because they accept either a single
# `color`/`bg`/`color0`/`color1` string or the legacy r/g/b triple.
_REQUIRED_DRAW_FIELDS: dict[str, tuple[str, ...]] = {
    "pixel": ("x", "y"),
    "line": ("x0", "y0", "x1", "y1"),
    "rect": ("x", "y", "w", "h"),
    "circle": ("cx", "cy", "radius"),
    "text": ("text",),
    "bar": ("x", "y", "w", "h", "value"),
    "gradient": ("x", "y", "w", "h"),
    "bitmap": ("x", "y", "palette", "data"),
}

# Which colour key(s) each op needs, so missing-colour errors are descriptive.
_REQUIRED_COLOR_KEYS: dict[str, tuple[str, ...]] = {
    "pixel": ("color",),
    "line": ("color",),
    "rect": ("color",),
    "circle": ("color",),
    # text + bar have sensible defaults, no colour required
    "gradient": ("color0", "color1"),
}


def _color(cmd: dict, key: str = "color",
           r_key: str = "r", g_key: str = "g", b_key: str = "b",
           default: tuple[int, int, int] | None = None) -> tuple[int, int, int]:
    """Pull a colour out of a command dict.

    Accepts either ``cmd[key]`` (any form `parse_color` understands) or the
    legacy ``cmd[r_key]``/``cmd[g_key]``/``cmd[b_key]`` triple, in that order
    of precedence.  Falls back to *default* if neither is present; raises
    ``KeyError`` if neither is present and no default is given.
    """
    if key in cmd:
        return parse_color(cmd[key])
    if r_key in cmd or g_key in cmd or b_key in cmd:
        return (
            int(cmd.get(r_key, 0)),
            int(cmd.get(g_key, 0)),
            int(cmd.get(b_key, 0)),
        )
    if default is not None:
        return default
    raise KeyError(key)


def _has_color(cmd: dict, key: str = "color",
               r_key: str = "r", g_key: str = "g", b_key: str = "b") -> bool:
    return key in cmd or r_key in cmd or g_key in cmd or b_key in cmd


def _validate_draw_command(cmd: dict, index: int) -> str:
    """Validate a draw command and return the normalized op."""
    op = str(cmd.get("op") or cmd.get("type") or "").lower().strip()
    if not op:
        raise ValueError(f"commands[{index}] is missing 'op'")

    if op in ("clear", "fill"):
        return op

    if op not in _REQUIRED_DRAW_FIELDS:
        supported = ", ".join(sorted(["clear", "fill", *_REQUIRED_DRAW_FIELDS.keys()]))
        raise ValueError(
            f"commands[{index}] has unsupported op '{op}'. Supported ops: {supported}"
        )

    missing = [field for field in _REQUIRED_DRAW_FIELDS[op] if field not in cmd]
    if missing:
        raise ValueError(
            f"commands[{index}] op '{op}' missing required fields: {', '.join(missing)}"
        )

    for color_key in _REQUIRED_COLOR_KEYS.get(op, ()):
        if color_key == "color":
            if not _has_color(cmd):
                raise ValueError(
                    f"commands[{index}] op '{op}' missing 'color' "
                    "(e.g. \"#ff8800\", \"red\", or [255,136,0])"
                )
        else:  # color0 / color1 for gradients
            n = color_key[-1]
            if not _has_color(cmd, color_key, f"r{n}", f"g{n}", f"b{n}"):
                raise ValueError(
                    f"commands[{index}] op '{op}' missing '{color_key}' "
                    f"(e.g. \"#ff8800\", \"red\", or [255,136,0])"
                )
    return op


def _exec_draw_commands(p: Pixoo, commands: list[dict]):
    """Execute a batch of draw commands on a Pixoo instance (synchronous)."""
    for i, cmd in enumerate(commands):
        op = _validate_draw_command(cmd, i)

        if op == "clear" or op == "fill":
            r, g, b = _color(cmd, default=(0, 0, 0))
            p.clear(r, g, b)

        elif op == "pixel":
            r, g, b = _color(cmd)
            p.set_pixel(cmd["x"], cmd["y"], r, g, b)

        elif op == "line":
            r, g, b = _color(cmd)
            p.draw_line(cmd["x0"], cmd["y0"], cmd["x1"], cmd["y1"], r, g, b)

        elif op == "rect":
            r, g, b = _color(cmd)
            p.draw_rect(cmd["x"], cmd["y"], cmd["w"], cmd["h"], r, g, b,
                        filled=cmd.get("filled", False))

        elif op == "circle":
            r, g, b = _color(cmd)
            p.draw_circle(cmd["cx"], cmd["cy"], cmd["radius"], r, g, b,
                          filled=cmd.get("filled", False))

        elif op == "text":
            r, g, b = _color(cmd, default=(255, 255, 255))
            p.draw_text(cmd["text"], cmd.get("x", 0), cmd.get("y", 0),
                        r, g, b,
                        align=cmd.get("align", "left"),
                        max_width=cmd.get("max_width", 0))

        elif op == "bar":
            r, g, b = _color(cmd, default=(0, 255, 0))
            br, bg, bb = _color(cmd, key="bg",
                                r_key="bg_r", g_key="bg_g", b_key="bg_b",
                                default=(40, 40, 40))
            p.draw_bar(cmd["x"], cmd["y"], cmd["w"], cmd["h"], cmd["value"],
                       r, g, b, br, bg, bb)

        elif op == "gradient":
            r0, g0, b0 = _color(cmd, key="color0",
                                r_key="r0", g_key="g0", b_key="b0")
            r1, g1, b1 = _color(cmd, key="color1",
                                r_key="r1", g_key="g1", b_key="b1")
            p.draw_gradient(cmd["x"], cmd["y"], cmd["w"], cmd["h"],
                            r0, g0, b0, r1, g1, b1,
                            direction=cmd.get("direction", "vertical"))

        elif op == "bitmap":
            raw_palette = cmd["palette"]
            if not isinstance(raw_palette, list):
                raise ValueError(f"commands[{i}] op 'bitmap' palette must be a list")
            palette: list[tuple[int, int, int] | None] = []
            for j, entry in enumerate(raw_palette):
                if entry is None or entry == "":
                    palette.append(None)
                else:
                    try:
                        palette.append(parse_color(entry))
                    except ValueError as exc:
                        raise ValueError(
                            f"commands[{i}] palette[{j}]: {exc}"
                        ) from None
            data = cmd["data"]
            if not isinstance(data, list) or not all(isinstance(r, str) for r in data):
                raise ValueError(
                    f"commands[{i}] op 'bitmap' data must be a list of strings"
                )
            scale = int(cmd.get("scale", 1))
            p.draw_bitmap(cmd["x"], cmd["y"], palette, data, scale=scale)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

def _make_instructions(size: int) -> str:
    max_coord = size - 1
    center = size // 2
    return f"""\
Control a Divoom Pixoo LED display.

Display: {size}x{size} pixels. Coordinates 0-{max_coord} (x left-to-right,
y top-to-bottom). Center: ({center}, {center}).

Tools:
  draw           — draw shapes and text on the display (batch of commands, single call)
  show_image     — display an image from a URL
  show_text      — scrolling text ticker (device-rendered, overlays on top of everything)
  device_control — brightness, screen on/off, info, buzzer

Two ways to show text:
  1. draw({{"op":"text",...}}) — renders text as pixels into the buffer. Composable
     with other draw ops. Use for dashboards, labels, static readouts.
  2. show_text(...) — uses the device's built-in text renderer. Overlays on top
     of whatever is displayed. Supports auto-scrolling for long messages.
     Use for scrolling tickers or temporary notifications.

Always use the "color" field with hex strings ("#ff0000") or CSS names ("red").
Do NOT use separate "r"/"g"/"b" keys.

Quick example — draw a red circle on black:
  draw([{{"op":"clear"}},{{"op":"circle","cx":{center},"cy":{center},"radius":20,"color":"red","filled":true}}])
"""


mcp = FastMCP(
    name="pixoo",
    instructions=_make_instructions(_PIXOO_SIZE),
)


# ---------------------------------------------------------------------------
# MCP tools — designed for one-call-per-action
# ---------------------------------------------------------------------------

# Passed to @mcp.tool(description=...) to bypass griffe's docstring parser,
# which truncates at the first "Foo:" line it interprets as an admonition.
_DRAW_DESCRIPTION = """\
Draw on the Pixoo display and push to the device in one call.

Takes a list of draw command objects. The buffer is NOT auto-cleared — \
add a clear command first if you want a fresh canvas.

Pixels outside the display bounds are silently clipped (not an error). \
Shapes can extend past the edges — only the visible portion is drawn.

Colours — every op accepts a "color" field. ALWAYS use it. Values:
  * Hex strings: "#ff8800", "#f80" (the "#" is optional)
  * CSS names: "red", "black", "orange", "cyan", "magenta", "pink", \
"purple", "lime", "darkblue", "lightgray", ...
  * RGB lists: [255, 136, 0]
Do NOT pass separate "r", "g", "b" keys — use the "color" field instead. \
For "bar" the background colour uses "bg" (e.g. "bg":"#222"). \
For "gradient" use "color0" and "color1".

Available commands (each is a dict with "op" and parameters):

  {"op":"clear", "color":"#000028"}
      Fill the entire buffer with a colour. Put this first for a fresh canvas. \
Colour defaults to black if omitted.

  {"op":"pixel", "x":10, "y":20, "color":"red"}
      Set a single pixel.

  {"op":"line", "x0":0, "y0":0, "x1":63, "y1":63, "color":"white"}
      Draw a line between two points.

  {"op":"rect", "x":5, "y":5, "w":20, "h":10, "color":"#0f0", "filled":true}
      Draw a rectangle (top-left corner, width, height).

  {"op":"circle", "cx":32, "cy":32, "radius":15, "color":"red", "filled":true}
      Draw a circle (center, radius).

  {"op":"text", "x":0, "y":0, "text":"Hello", "color":"white"}
      Render bitmap text into the pixel buffer (PICO-8 font, 3x5 glyphs, \
4px per char). Composable with other draw ops — use for dashboards, \
labels, static readouts. For scrolling text, use show_text() instead. \
16 chars/line on 64px, 10 lines (6px line height). Supports \\n.
      Optional: "align":"left"|"center"|"right" (default "left"). \
For center/right, x is the center-point or right edge.
      Optional: "max_width":60 — word-wrap to fit within this many pixels. \
Colour defaults to white if omitted.

  {"op":"bar", "x":2, "y":50, "w":60, "h":5, "value":0.75, \
"color":"lime", "bg":"#222"}
      Horizontal progress bar. value is 0.0–1.0. \
Defaults: color="lime", bg="#282828".

  {"op":"gradient", "x":0, "y":0, "w":64, "h":64, \
"color0":"#00003c", "color1":"#000000"}
      Fill a rectangle with a linear gradient between two colours. \
Optional: "direction":"vertical" (default, top-to-bottom) or "horizontal". \
Useful as a background — draw the gradient first, then layer shapes/text.

  {"op":"bitmap", "x":28, "y":40, "scale":2, \
"palette":["", "#ff4488", "#cc2266"], \
"data":["0120210","1111111","0111110","0011100","0001000"]}
      Draw a sprite from a small palette + character grid. Each character in \
a "data" row is a base-36 palette index (0-9, then a-z = indices 10-35). \
Empty string "" or null in the palette means TRANSPARENT — that pixel is \
skipped, leaving whatever was drawn underneath. \
Optional "scale" (default 1) upsamples nearest-neighbour: scale=2 turns \
each source pixel into a 2x2 block. \
Use this for icons, emoji, status glyphs, tiny sprites — much cheaper \
than dozens of "pixel" commands.

push (bool, default True) — send the buffer to the device. \
Set False for offline iteration / previews without touching hardware.

preview (bool, default False) — return a rendered preview so you can see \
what you drew: an ASCII grayscale grid (readable by any LLM client) and \
a PNG image content block (viewable by image-capable clients). \
Also saved as MCP resource pixoo://last-frame.png and HTTP /api/preview.png.

Example — yellow circle on dark blue:
  [{"op":"clear","color":"#000028"},\
{"op":"circle","cx":32,"cy":32,"radius":20,"color":"#ffdc00","filled":true}]

Example — status bars in three colours:
  [{"op":"clear"},\
{"op":"rect","x":2,"y":2,"w":60,"h":12,"color":"green","filled":true},\
{"op":"rect","x":2,"y":18,"w":40,"h":12,"color":"orange","filled":true},\
{"op":"rect","x":2,"y":34,"w":55,"h":12,"color":"#0064ff","filled":true}]

Example — pink heart layered on a dark gradient (transparency at work):
  [{"op":"gradient","x":0,"y":0,"w":64,"h":64,"color0":"#001a40","color1":"black"},\
{"op":"bitmap","x":24,"y":24,"scale":2,\
"palette":["","#ff4488","#cc2266"],\
"data":["0120210","1111111","0111110","0011100","0001000"]}]

Example — iterate without the device (preview-only):
  draw(commands=[...], push=False, preview=True)"""

_last_preview_png: bytes | None = None


@mcp.tool(description=_DRAW_DESCRIPTION)
async def draw(
    commands: list[dict[str, Any]],
    push: bool = True,
    preview: bool = False,
) -> Any:
    global _last_preview_png
    p = _get_pixoo()

    try:
        async with _lock:
            loop = asyncio.get_event_loop()

            def do():
                if push:
                    _ensure_screen_on_sync(p)
                _exec_draw_commands(p, commands)
                device_result = p.push() if push else None
                preview_png = p.to_png() if preview else None
                ascii_art = p.to_ascii() if preview else None
                return device_result, preview_png, ascii_art

            result, preview_png, ascii_art = await loop.run_in_executor(None, do)
    except (KeyError, TypeError, ValueError) as exc:
        return f"Draw failed: {exc}"

    if preview_png is not None:
        _last_preview_png = preview_png

    if push:
        ok = (result or {}).get("error_code", -1) == 0
        status = f"Drew {len(commands)} commands and pushed: {'ok' if ok else result}"
    else:
        status = f"Drew {len(commands)} commands (not pushed)"

    if not preview:
        return status

    return [
        status,
        f"Preview ({p.size}x{p.size}):\n{ascii_art}",
        Image(data=preview_png, format="png"),
    ]


@mcp.tool
async def show_image(url: str) -> str:
    """Display an image from a URL on the Pixoo. Fetches, scales to fit, pushes."""
    import httpx
    from PIL import Image

    resp = httpx.get(url, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))

    p = _get_pixoo()
    async with _lock:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: (_ensure_screen_on_sync(p), p.draw_image(img), p.push()),
        )
    return f"Image from {url} displayed"


@mcp.tool
async def show_text(
    text: str,
    color: str = "#FFFFFF",
    x: int = 0,
    y: int = 0,
    font: int = 2,
    speed: int = 100,
) -> str:
    """Scrolling text ticker using the device's built-in renderer.

    This is an overlay — it floats on top of whatever is on the display
    (drawings, images, etc.) and persists until cleared with
    device_control(action="clear_text").

    Use this for scrolling tickers or temporary notifications.
    For static text as part of a drawing, use draw({"op":"text",...}) instead.

    speed 0 = static, >0 = scroll speed in ms (100 is a good default).
    font: 0–7 (device built-in fonts, not the PICO-8 bitmap font).
    color: hex string like "#FF0000".
    """
    p = _get_pixoo()
    async with _lock:
        loop = asyncio.get_event_loop()

        def do():
            _ensure_screen_on_sync(p)
            return p.send_text(text, x=x, y=y, color=color, font=font, speed=speed)

        result = await loop.run_in_executor(None, do)
    ok = result.get("error_code", -1) == 0
    return f"Text '{text}' displayed: {'ok' if ok else result}"


# Channel name → index mapping (case-insensitive).  Integer 0–3 also accepted.
_CHANNEL_NAMES: dict[str, int] = {
    "faces":      0,
    "face":       0,
    "clock":      0,  # clock faces live on channel 0
    "cloud":      1,
    "visualizer": 2,
    "viz":        2,
    "eq":         2,
    "custom":     3,
}


def _resolve_channel(value) -> int:
    """Turn a channel spec ('custom', 3, 'Visualizer') into an index 0–3."""
    if value is None:
        raise ValueError("channel requires a value (0–3 or 'custom'/'faces'/'cloud'/'visualizer')")
    if isinstance(value, int):
        if 0 <= value <= 3:
            return value
        raise ValueError(f"channel index must be 0–3, got {value}")
    if isinstance(value, str):
        s = value.strip().lower()
        if s.isdigit():
            return _resolve_channel(int(s))
        if s in _CHANNEL_NAMES:
            return _CHANNEL_NAMES[s]
        raise ValueError(
            f"unknown channel '{value}'. Try one of: "
            + ", ".join(sorted(set(_CHANNEL_NAMES.keys())))
        )
    raise ValueError(f"unsupported channel type: {type(value).__name__}")


@mcp.tool
async def device_control(
    action: str,
    value: int | str | None = None,
) -> str:
    """Control the Pixoo device. One tool for all non-drawing device actions.

    Actions:
      "info"                          Get device config + display size (returns JSON).
      "brightness"     value=0–100    Set display backlight brightness.
      "on" / "off"                    Turn the screen on / off.
      "buzzer"                        Sound the device buzzer briefly.
      "clear_text"                    Remove all show_text(...) overlays.

      "channel"        value=name|int Switch the active channel. Accepts an index
                                      (0–3) or a name: "faces" (clock widgets,
                                      configured via the phone app), "cloud",
                                      "visualizer" (audio EQ), or "custom"
                                      (what `draw` paints into). Useful for
                                      handing the screen back to the user when
                                      done — `device_control("channel","faces")`.
      "startup_channel" value=name|int Which channel the device boots into.
                                      Set to "custom" to keep the device on your
                                      content after a power cycle.
      "clock"          value=int      Pick a clock face by ID (e.g. 195).
                                      Implicitly switches to the faces channel.
      "play_gif_url"   value=url      Play a GIF from a URL on the device's
                                      built-in player. Bypasses the pixel
                                      buffer entirely — good for animated
                                      content from giphy etc. The GIF is
                                      streamed by the device, not by us.
      "reboot"                        Reboot the device. Useful if firmware
                                      gets stuck (~300 push limit, etc.).

    Examples:
      device_control("info")
      device_control("brightness", 75)
      device_control("channel", "custom")
      device_control("clock", 195)
      device_control("play_gif_url", "https://media.giphy.com/.../rainbow.gif")
    """
    p = _get_pixoo()
    action = action.lower().strip()

    try:
        if action == "brightness":
            result = await _run_locked(p.set_brightness, int(value or 50))
        elif action == "on":
            result = await _run_locked(p.screen_on)
        elif action == "off":
            result = await _run_locked(p.screen_off)
        elif action == "clear_text":
            result = await _run_locked(p.clear_text)
        elif action == "info":
            config = await _run_locked(p.get_config)
            size = p.size
            info = {
                "display": {
                    "size": size,
                    "width": size,
                    "height": size,
                    "pixels": size * size,
                    "coordinate_range": f"0-{size - 1}",
                    "center": {"x": size // 2, "y": size // 2},
                },
                "ip": p.ip,
                "config": config,
            }
            return json.dumps(info, indent=2)
        elif action == "buzzer":
            result = await _run_locked(p.buzzer)
        elif action == "channel":
            idx = _resolve_channel(value)
            result = await _run_locked(p.set_channel, idx)
        elif action == "startup_channel":
            idx = _resolve_channel(value)
            result = await _run_locked(p.set_startup_channel, idx)
        elif action == "clock":
            if value is None:
                return "clock requires a clock-face id (integer, e.g. 195)"
            result = await _run_locked(p.set_clock, int(value))
        elif action == "play_gif_url":
            if not value or not isinstance(value, str):
                return "play_gif_url requires a URL string"
            result = await _run_locked(p.play_gif_url, value)
        elif action == "reboot":
            result = await _run_locked(p.reboot)
        else:
            return (
                f"Unknown action: {action!r}. Available: info, brightness, on, off, "
                "buzzer, clear_text, channel, startup_channel, clock, "
                "play_gif_url, reboot"
            )
    except (ValueError, TypeError) as exc:
        return f"{action} failed: {exc}"

    ok = (result or {}).get("error_code", -1) == 0
    return f"{action}: {'ok' if ok else result}"


# ---------------------------------------------------------------------------
# HTTP API (custom routes, available when running in --http mode)
# ---------------------------------------------------------------------------

def _json_ok(data=None):
    return JSONResponse({"ok": True, **(data or {})})


def _json_err(msg: str, status: int = 400):
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


@mcp.custom_route("/api/draw", methods=["POST"])
async def http_draw(request: Request):
    """Batch draw + push. Body: {"commands": [...]}"""
    body = await request.json()
    commands = body.get("commands", [])
    p = _get_pixoo()
    try:
        async with _lock:
            loop = asyncio.get_event_loop()

            def do():
                _ensure_screen_on_sync(p)
                _exec_draw_commands(p, commands)
                return p.push()

            result = await loop.run_in_executor(None, do)
    except (KeyError, TypeError, ValueError) as exc:
        return _json_err(f"draw validation error: {exc}", status=400)
    return _json_ok({"device": result, "commands": len(commands)})


@mcp.custom_route("/api/clear", methods=["POST"])
async def http_clear(request: Request):
    body = await request.json() if await request.body() else {}
    await _run_locked(_get_pixoo().clear, body.get("r", 0), body.get("g", 0), body.get("b", 0))
    return _json_ok()


@mcp.custom_route("/api/pixel", methods=["POST"])
async def http_pixel(request: Request):
    b = await request.json()
    await _run_locked(_get_pixoo().set_pixel, b["x"], b["y"], b["r"], b["g"], b["b"])
    return _json_ok()


@mcp.custom_route("/api/line", methods=["POST"])
async def http_line(request: Request):
    b = await request.json()
    await _run_locked(_get_pixoo().draw_line, b["x0"], b["y0"], b["x1"], b["y1"], b["r"], b["g"], b["b"])
    return _json_ok()


@mcp.custom_route("/api/rect", methods=["POST"])
async def http_rect(request: Request):
    b = await request.json()
    p = _get_pixoo()
    await _run_locked(p.draw_rect, b["x"], b["y"], b["w"], b["h"], b["r"], b["g"], b["b"], filled=b.get("filled", False))
    return _json_ok()


@mcp.custom_route("/api/circle", methods=["POST"])
async def http_circle(request: Request):
    b = await request.json()
    p = _get_pixoo()
    await _run_locked(p.draw_circle, b["cx"], b["cy"], b["radius"], b["r"], b["g"], b["b"], filled=b.get("filled", False))
    return _json_ok()


@mcp.custom_route("/api/push", methods=["POST"])
async def http_push(request: Request):
    result = await _run_locked(_get_pixoo().push)
    return _json_ok({"device": result})


@mcp.custom_route("/api/image", methods=["POST"])
async def http_image(request: Request):
    from PIL import Image

    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.json()
        url = body.get("url")
        if not url:
            return _json_err("missing 'url'")
        import httpx
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    else:
        raw = await request.body()
        img = Image.open(io.BytesIO(raw))

    p = _get_pixoo()
    async with _lock:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: (_ensure_screen_on_sync(p), p.draw_image(img), p.push()),
        )
    return _json_ok()


@mcp.custom_route("/api/text", methods=["POST"])
async def http_text(request: Request):
    b = await request.json()
    p = _get_pixoo()
    async with _lock:
        loop = asyncio.get_event_loop()

        def do():
            _ensure_screen_on_sync(p)
            return p.send_text(
                b["text"],
                x=b.get("x", 0),
                y=b.get("y", 0),
                color=b.get("color", "#FFFFFF"),
                font=b.get("font", 2),
                speed=b.get("speed", 0),
            )

        result = await loop.run_in_executor(None, do)
    return _json_ok({"device": result})


@mcp.custom_route("/api/brightness", methods=["POST"])
async def http_brightness(request: Request):
    b = await request.json()
    result = await _run_locked(_get_pixoo().set_brightness, b["level"])
    return _json_ok({"device": result})


@mcp.custom_route("/api/screen", methods=["POST"])
async def http_screen(request: Request):
    b = await request.json()
    p = _get_pixoo()
    fn = p.screen_on if b.get("on", True) else p.screen_off
    result = await _run_locked(fn)
    return _json_ok({"device": result})


@mcp.custom_route("/api/info", methods=["GET"])
async def http_info(request: Request):
    config = await _run_locked(_get_pixoo().get_config)
    return JSONResponse(config)


@mcp.custom_route("/api/preview.png", methods=["GET"])
async def http_preview(request: Request):
    """Return the last rendered preview (or the current buffer) as a PNG.

    Useful as an out-of-band debugging surface — open in a browser to see
    what the server most recently drew, even when running headless.
    """
    png = _last_preview_png
    if png is None:
        png = await _run_locked(_get_pixoo().to_png)
    return Response(content=png, media_type="image/png")


# ---------------------------------------------------------------------------
# MCP resources
# ---------------------------------------------------------------------------

@mcp.resource("pixoo://last-frame.png", mime_type="image/png")
def last_frame_resource() -> bytes:
    """Most recently rendered preview as a PNG.

    Populated by `draw(..., preview=True)`.  Falls back to the current
    buffer if no preview has been rendered yet.
    """
    if _last_preview_png is not None:
        return _last_preview_png
    return _get_pixoo().to_png()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _detect_size(ip: str, configured_size: int) -> int:
    """Try to auto-detect display size from a reachable device.

    If the device responds, derive size from its pixel count and use that.
    Otherwise fall back to *configured_size*.
    """
    try:
        probe = Pixoo(ip, size=configured_size)
        if not probe.ping(timeout=3):
            return configured_size
        config = probe.get_config()
        pixel_w = config.get("PixelW") or config.get("PixelCount")
        if pixel_w and int(pixel_w) in (16, 32, 64):
            return int(pixel_w)
    except Exception:
        pass
    return configured_size


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pixoo MCP + HTTP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server (default: stdio MCP)")
    parser.add_argument("--port", type=int, default=9100, help="HTTP port (default 9100)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind address")
    parser.add_argument("--ip", default=None, help="Pixoo device IP")
    parser.add_argument("--size", type=int, default=None,
                        help="Display size: 16, 32, or 64 (default: auto-detect, else 64)")
    args = parser.parse_args()

    global _PIXOO_IP, _PIXOO_SIZE

    if args.ip:
        _PIXOO_IP = args.ip

    if args.size is not None:
        _PIXOO_SIZE = args.size
    elif _PIXOO_IP:
        _PIXOO_SIZE = _detect_size(_PIXOO_IP, _PIXOO_SIZE)

    mcp.instructions = _make_instructions(_PIXOO_SIZE)
    print(f"pixoo-mcp: display={_PIXOO_SIZE}x{_PIXOO_SIZE}", file=sys.stderr)

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
