# pixoo-mcp

Python library and MCP server for [Divoom Pixoo](https://divoom.com/products/pixoo-64) LED displays (16x16, 32x32, 64x64).

Draw pixels, shapes, text, and images on the display over Wi-Fi. Includes an
[MCP](https://modelcontextprotocol.io/) server so AI agents can use the display
as an output device.

## Quick start

```python
from pixoo import Pixoo

p = Pixoo("10.0.0.42")       # size=64 by default
p.clear(0, 0, 40)
p.draw_text("Hello!", 2, 2, 255, 255, 255)
p.draw_bar(2, 12, 60, 5, 0.75, 0, 255, 0)
p.push()
```

## Installation

```bash
pip install .                  # library only (requires requests)
pip install ".[images]"        # + Pillow for image loading
pip install ".[server]"        # + MCP server dependencies
```

Or without pyproject.toml:

```bash
pip install -r requirements.txt              # library + images
pip install -r requirements-server.txt       # + MCP server
```

## CLI

```bash
python -m pixoo 10.0.0.42 smiley
python -m pixoo plasma              # auto-discovers device
python -m pixoo image photo.png
python -m pixoo text "Hello!"
python -m pixoo discover
```

If no IP is given, the module checks `PIXOO_IP` env var, then tries
auto-discovery via the Divoom cloud.

## Library API

### Constructor

```python
Pixoo(ip, port=80, *, size=64, refresh_connection=True, debug=False)
```

`size` must be 16, 32, or 64 matching your hardware model.

### Drawing

| Method | Description |
|--------|-------------|
| `clear(r, g, b)` | Fill buffer with a solid colour |
| `set_pixel(x, y, r, g, b)` | Set a single pixel |
| `draw_line(x0, y0, x1, y1, r, g, b)` | Line between two points |
| `draw_rect(x, y, w, h, r, g, b, filled=False)` | Rectangle (outline or filled) |
| `draw_circle(cx, cy, radius, r, g, b, filled=False)` | Circle (outline or filled) |
| `draw_gradient(x, y, w, h, r0, g0, b0, r1, g1, b1, direction=)` | Linear gradient fill. Blends from (r0,g0,b0) to (r1,g1,b1). `direction`: `"vertical"` (top→bottom, default) or `"horizontal"` (left→right) |
| `draw_bar(x, y, w, h, value, r, g, b, ...)` | Progress bar. `value` 0.0–1.0, unfilled portion uses `bg_r/bg_g/bg_b` (default 40) |
| `draw_text(text, x, y, r, g, b, align=, max_width=)` | Bitmap text (PICO-8 font, see below) |
| `draw_image(source, xy=(0,0))` | Load image (path, file, or PIL Image); auto-resizes to fit |
| `push()` | Send buffer to the display |

### Text features

- PICO-8 bitmap font: 3x5 pixel glyphs, 4px character width
- `align`: `"left"` (default), `"center"`, `"right"`
- `max_width`: word-wrap to fit within N pixels
- Supports `\n` for explicit line breaks

### Device control

`set_brightness`, `screen_on`, `screen_off`, `buzzer`, `set_channel`,
`send_text` (device-side scrolling text), `get_config`, `reboot`, and more.

## Examples

The `examples/` directory has standalone demos that showcase the library:

| Script | Size | What it shows |
|--------|------|---------------|
| `dashboard.py` | all | System-monitor panel with text, progress bars, dividers |
| `clock.py` | all | Analog clock with trig-drawn hands, live-updating |
| `game_of_life.py` | all | Conway's Game of Life as a looping animation |
| `weather_card.py` | 64 | Rich weather card with icon, word-wrapped forecast, humidity bar |

Run any example:

```bash
python examples/dashboard.py 10.0.0.42
PIXOO_IP=10.0.0.42 python examples/clock.py
```

## MCP server

Run as an MCP server for AI agents:

```bash
# stdio (for local IDE integration)
python -m pixoo.server --ip 10.0.0.42

# HTTP (for remote/Docker)
python -m pixoo.server --http --port 9100
PIXOO_IP=10.0.0.42 python -m pixoo.server --http
```

### Docker

```bash
docker build -t pixoo-mcp .
docker run -d --network host -e PIXOO_IP=10.0.0.42 pixoo-mcp
```

### Cursor IDE

Add to `~/.cursor/mcp.json` for global access:

```json
{
  "mcpServers": {
    "pixoo": {
      "url": "http://localhost:9100/mcp"
    }
  }
}
```

### MCP tools

| Tool | Description |
|------|-------------|
| `draw(commands)` | Batch draw operations: clear, pixel, line, rect, circle, text, bar, gradient |
| `show_image(url)` | Fetch and display an image from a URL |
| `show_text(text, ...)` | Device-side scrolling/static text overlay |
| `device_control(action, ...)` | Brightness, screen on/off, info, buzzer |

## License

MIT. See [LICENSE](LICENSE).

PICO-8 font data derived from [SomethingWithComputers/pixoo](https://github.com/SomethingWithComputers/pixoo) (MIT).
