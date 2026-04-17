"""
Pixoo MCP + HTTP server.

Exposes the Pixoo library as MCP tools (for AI agents) and REST endpoints
(for containers / scripts).

MCP (stdio, for Cursor):
    python -m pixoo.server

HTTP (for containers + MCP-over-HTTP):
    python -m pixoo.server --http [--port 9100]

Environment:
    PIXOO_IP   device IP (required, or auto-discovered)
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import Pixoo

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_PIXOO_IP = os.environ.get("PIXOO_IP", "")
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
        _pixoo = Pixoo(_PIXOO_IP)
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


def _exec_draw_commands(p: Pixoo, commands: list[dict]):
    """Execute a batch of draw commands on a Pixoo instance (synchronous)."""
    for cmd in commands:
        op = cmd.get("op") or cmd.get("type") or ""
        op = op.lower()
        if op == "clear" or op == "fill":
            p.clear(cmd.get("r", 0), cmd.get("g", 0), cmd.get("b", 0))
        elif op == "pixel":
            p.set_pixel(cmd["x"], cmd["y"], cmd["r"], cmd["g"], cmd["b"])
        elif op == "line":
            p.draw_line(cmd["x0"], cmd["y0"], cmd["x1"], cmd["y1"],
                        cmd["r"], cmd["g"], cmd["b"])
        elif op == "rect":
            p.draw_rect(cmd["x"], cmd["y"], cmd["w"], cmd["h"],
                        cmd["r"], cmd["g"], cmd["b"],
                        filled=cmd.get("filled", False))
        elif op == "circle":
            p.draw_circle(cmd["cx"], cmd["cy"], cmd["radius"],
                          cmd["r"], cmd["g"], cmd["b"],
                          filled=cmd.get("filled", False))
        elif op == "text":
            p.draw_text(cmd["text"], cmd.get("x", 0), cmd.get("y", 0),
                        cmd.get("r", 255), cmd.get("g", 255), cmd.get("b", 255),
                        align=cmd.get("align", "left"),
                        max_width=cmd.get("max_width", 0))
        elif op == "bar":
            p.draw_bar(cmd["x"], cmd["y"], cmd["w"], cmd["h"],
                       cmd["value"],
                       cmd.get("r", 0), cmd.get("g", 255), cmd.get("b", 0),
                       cmd.get("bg_r", 40), cmd.get("bg_g", 40), cmd.get("bg_b", 40))
        elif op == "gradient":
            p.draw_gradient(cmd["x"], cmd["y"], cmd["w"], cmd["h"],
                            cmd["r0"], cmd["g0"], cmd["b0"],
                            cmd["r1"], cmd["g1"], cmd["b1"],
                            direction=cmd.get("direction", "vertical"))


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="pixoo",
    instructions="""\
Control a Divoom Pixoo LED display.

Call device_control(action="info") first to discover the display resolution
and capabilities before drawing. The display size varies by model (16x16,
32x32, or 64x64 pixels).

Tools:
  draw           — draw shapes and text on the display (batch of commands, single call)
  show_image     — display an image from a URL
  show_text      — scrolling text ticker (device-rendered, overlays on top of everything)
  device_control — brightness, screen on/off, info, buzzer

Two ways to show text:
  1. draw({"op":"text",...}) — renders text as pixels into the buffer. Composable
     with other draw ops. Use for dashboards, labels, static readouts.
  2. show_text(...) — uses the device's built-in text renderer. Overlays on top
     of whatever is displayed. Supports auto-scrolling for long messages.
     Use for scrolling tickers or temporary notifications.

Coordinate system: x 0-(size-1) left-to-right, y 0-(size-1) top-to-bottom.
Colors are RGB 0-255.

Quick example — draw a red circle on black:
  draw([{"op":"clear"},{"op":"circle","cx":32,"cy":32,"radius":20,"r":255,"g":0,"b":0,"filled":true}])
""",
)


# ---------------------------------------------------------------------------
# MCP tools — designed for one-call-per-action
# ---------------------------------------------------------------------------


@mcp.tool
async def draw(commands: list[dict[str, Any]]) -> str:
    """Draw on the Pixoo display and push to the device in one call.

    Takes a list of draw command objects. The buffer is NOT auto-cleared —
    add a clear command first if you want a fresh canvas.
    Call device_control(action="info") to discover the display resolution.

    Pixels outside the display bounds are silently clipped (not an error).
    Shapes can extend past the edges — only the visible portion is drawn.

    Available commands (each is a dict with "op" and parameters):

      {"op":"clear", "r":0, "g":0, "b":0}
          Fill the entire buffer with a color. Put this first for a fresh canvas.

      {"op":"pixel", "x":10, "y":20, "r":255, "g":0, "b":0}
          Set a single pixel.

      {"op":"line", "x0":0, "y0":0, "x1":63, "y1":63, "r":255, "g":255, "b":255}
          Draw a line between two points.

      {"op":"rect", "x":5, "y":5, "w":20, "h":10, "r":0, "g":255, "b":0, "filled":true}
          Draw a rectangle (top-left corner, width, height).

      {"op":"circle", "cx":32, "cy":32, "radius":15, "r":255, "g":0, "b":0, "filled":true}
          Draw a circle (center, radius).

      {"op":"text", "x":0, "y":0, "text":"Hello", "r":255, "g":255, "b":255}
          Render bitmap text into the pixel buffer (PICO-8 font, 3x5 glyphs,
          4px per char). Composable with other draw ops — use for dashboards,
          labels, static readouts. For scrolling text, use show_text() instead.
          16 chars/line on 64px, 10 lines (6px line height). Supports \\n.
          Optional: "align":"left"|"center"|"right" (default "left").
            For center/right, x is the center-point or right edge.
          Optional: "max_width":60 — word-wrap to fit within this many pixels.

      {"op":"bar", "x":2, "y":50, "w":60, "h":5, "value":0.75, "r":0, "g":255, "b":0}
          Horizontal progress bar. value is 0.0–1.0. Unfilled portion uses
          bg_r/bg_g/bg_b (default 40,40,40).

      {"op":"gradient", "x":0, "y":0, "w":64, "h":64,
       "r0":0, "g0":0, "b0":60, "r1":0, "g1":0, "b1":0}
          Fill a rectangle with a linear gradient between two colours.
          (r0,g0,b0) is the start colour, (r1,g1,b1) is the end colour.
          Optional: "direction":"vertical" (default, top→bottom) or "horizontal".
          Useful as a background — draw the gradient first, then layer shapes/text.

    Example — yellow circle on dark blue:
      [{"op":"clear","r":0,"g":0,"b":40},
       {"op":"circle","cx":32,"cy":32,"radius":20,"r":255,"g":220,"b":0,"filled":true}]

    Example — status indicator with colored bars:
      [{"op":"clear"},
       {"op":"rect","x":2,"y":2,"w":60,"h":12,"r":0,"g":200,"b":0,"filled":true},
       {"op":"rect","x":2,"y":18,"w":40,"h":12,"r":255,"g":165,"b":0,"filled":true},
       {"op":"rect","x":2,"y":34,"w":55,"h":12,"r":0,"g":100,"b":255,"filled":true}]
    """
    p = _get_pixoo()

    async with _lock:
        loop = asyncio.get_event_loop()

        def do():
            _ensure_screen_on_sync(p)
            _exec_draw_commands(p, commands)
            return p.push()

        result = await loop.run_in_executor(None, do)

    ok = result.get("error_code", -1) == 0
    return f"Drew {len(commands)} commands and pushed: {'ok' if ok else result}"


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


@mcp.tool
async def device_control(
    action: str,
    value: int | str | None = None,
) -> str:
    """Control the Pixoo device. One tool for all device actions.

    Actions:
      "brightness" (value: 0-100)   — set display brightness
      "on"                          — turn screen on
      "off"                         — turn screen off
      "clear_text"                  — remove text overlays
      "info"                        — get device config (returns JSON)
      "buzzer"                      — sound the buzzer
    """
    p = _get_pixoo()
    action = action.lower().strip()

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
    else:
        return f"Unknown action: {action}"

    ok = result.get("error_code", -1) == 0
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
    async with _lock:
        loop = asyncio.get_event_loop()

        def do():
            _ensure_screen_on_sync(p)
            _exec_draw_commands(p, commands)
            return p.push()

        result = await loop.run_in_executor(None, do)
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pixoo MCP + HTTP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server (default: stdio MCP)")
    parser.add_argument("--port", type=int, default=9100, help="HTTP port (default 9100)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind address")
    parser.add_argument("--ip", default=None, help="Pixoo device IP")
    args = parser.parse_args()

    if args.ip:
        global _PIXOO_IP
        _PIXOO_IP = args.ip

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
