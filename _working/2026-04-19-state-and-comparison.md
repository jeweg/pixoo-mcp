## Review

I read through `pixoo/__init__.py`, `pixoo/server.py`, `pixoo/__main__.py`, `PROTOCOL.md`, and the README, then compared against the cyanheads/pixoo-mcp-server feature set.

### What you have today

A focused, single-package Python project with two layers:

- `pixoo.Pixoo` library — buffer-based drawing (pixel, line, rect, circle, gradient, bar, image, PICO-8 text), full device control (brightness, channels, clock face, scoreboard, white balance, mirror, buzzer, reboot, GIF-from-URL), animations via `push_animation` (with ~60-frame hardware limit detection and warning), auto-cancel of running animations on `push()` via brightness-masked channel switch, LAN discovery, the firmware-bug counter workaround, and a `hold()` loop to fight off the phone app.
- `pixoo.server` — FastMCP-backed MCP server exposing 4 tools (`draw`, `show_image`, `show_text`, `device_control`) plus a parallel REST API for non-MCP clients, all wrapped with an asyncio lock and a screen-wake.

### How cyanheads/pixoo-mcp-server compares

Same surface (4 tools), but the design philosophy is **declarative scene composition** rather than procedural buffer ops:

| Their tool | Idea |
|---|---|
| `pixoo_compose` | One scene object with `background`, `elements[]` (text / image / sprite / rect / circle / line / bitmap / pixels), drawn back-to-front. Hex/named colors. Optional `frames` + per-element `animate` keyframes (linear lerp for numbers, color lerp for hex, snap for booleans). Can save PNG/GIF previews and skip device push. |
| `pixoo_push_image` | URL-or-path → image with `fit: contain/cover/fill` and resampling `kernel: nearest/lanczos3/mitchell`. |
| `pixoo_text` | Native scrolling overlay (same as ours). |
| `pixoo_control` | Same axes as ours, plus `clock` face. |

They ship two bitmap fonts (5x7 standard + 3x5 compact), inline-bitmap and explicit-pixel element types, sprite sheet loading with palette overrides, and pluggable storage / OTel / JWT-OAuth (server template stuff, not really pixel-related).

---

## Where we have real gaps

These are the ideas I'd actually steal:

**1. Hex / named colors everywhere.** Right now every shape needs `r`, `g`, `b` as separate ints, which roughly triples the JSON an agent has to write. A `color: "#ff8800"` (or `"red"`) helper that falls through to `(r,g,b)` would be a one-function change in `_exec_draw_commands` plus a small `parse_color()` helper.

**2. Inline `bitmap` op.** Their format is genuinely clever for tiny icons:

```json
{"op":"bitmap","x":28,"y":40,"scale":2,
 "palette":["","#ff4488","#cc2266"],
 "data":["0120210","1111111","0111110","0011100","0001000"]}
```

Empty string in palette = transparent. This is the single most LLM-friendly drawing primitive — agents can generate hearts, arrows, weather icons, sprites in one call without doing pixel math.

**3. Declarative animation with keyframes.** `push_animation` exists in the library but isn't reachable from MCP, and it requires the caller to snapshot buffers manually. Adding a `draw_animation(frames=N, speed_ms=, elements=[...with optional animate:{prop:[[frame,value],...]}])` tool would make animations a single LLM-readable JSON object instead of N separate tool calls. The implementation can re-use your existing buffer + `push_animation`.

**4. Render-to-file / preview without push.** Add `output: "/path/to.png"` and `push: false` to `draw`. Lets agents iterate on layouts without spamming the device or even needing one connected — and gives users a way to debug what an agent thought it was drawing. `_buffer` is already a flat RGB array, so it's a 5-line `Image.frombytes("RGB", (s,s), bytes(self._buffer)).save(path)`.

**5. Image `fit` modes.** Today `draw_image` has `pad: bool`. Splitting into `fit: "contain"|"cover"|"fill"` matches user mental models better. Same Pillow primitives (`thumbnail`, `ImageOps.pad`, `ImageOps.fit`, `resize`).

**6. A second bitmap font.** PICO-8 (3x5) is great but cramped on 16x16 or for prominent labels. A 5x7 "standard" font would be a nice option — many MIT-licensed bitmap fonts already in the wild, e.g. tom-thumb or the one cyanheads uses.

**7. More device controls in MCP.** `pixoo/__init__.py` already exposes `set_channel`, `set_clock`, `set_visualizer`, `set_scoreboard`, `set_white_balance`, `set_mirror`, `set_startup_channel`, `play_gif_url`, `reboot` — but `device_control` only surfaces `brightness/on/off/clear_text/info/buzzer`. Adding `clock`, `channel`, `scoreboard`, `play_gif_url`, `reboot` would expose existing capability for free.

**8. SVG support** in `show_image` (and `draw_image`). cyanheads supports it via their image pipeline. We'd need `cairosvg` or `svglib`, optional dep.

---

## Where we are already stronger (don't lose these)

- **LAN discovery** via the Divoom cloud endpoint — they don't have it.
- **`hold()` re-push loop** to fight the phone app reclaiming the display — unique and very valuable; document this more prominently.
- **REST API alongside MCP** — much friendlier for `curl` / cron / Home Assistant integration than MCP-only.
- **Auto counter reset** for the 300-push firmware bug — they handle it too, but ours is well-documented in `PROTOCOL.md`.
- **CLI with built-in patterns** (`plasma`, `nyan`, `smiley`, `checker`, `rainbow`, `animation`) — great for smoke-testing a new device.
- **`PROTOCOL.md`** — best protocol writeup I've seen for this device, including the firmware command list and gotchas.
- **Docker compose** with host networking out of the box.
- **Standalone examples** (`dashboard.py`, `clock.py`, `game_of_life.py`, `weather_card.py`).

---

## Other interesting feature ideas

Independent of cyanheads:

**A. Notification / "ping me" tool.** One MCP call that does buzzer + flash brightness + scrolling text. Genuine quality-of-life win for agentic workflows ("tell me when the build's done").

**B. Built-in icon set as MCP resources.** Ship ~20 tiny bitmaps (weather, status, arrows, hearts, check/cross) accessible as MCP resources or via a `{"op":"icon","name":"sun","x":0,"y":0}` op. Lets agents draw recognizable stuff without inventing pixel art every time.

**C. Dashboard layout helper.** `{"op":"panel","title":"CPU","value":"42%","bar":0.42,...}` — composes title + bar + value in one op. Agents reach for dashboards constantly; making them a primitive would save tokens and produce more consistent output.

**D. Live device weather & time.** The firmware has `Weather/GetForecastWeatherInfo` and `Device/GetDeviceTime` (per `PROTOCOL.md`); these could power a `weather` op that overlays the device's own forecast without needing an external API key.

**E. Alarm / timer / stopwatch tools.** `Tools/SetTimer`, `Tools/SetStopWatch`, `Alarm/*` are all in the firmware command list — currently unused. Easy MCP wins for "set a 5-minute pomodoro on the screen".

**F. Read-back of MCP state as resources.** Expose the current `Channel/GetAllConf`, current channel, last-rendered preview PNG as MCP **resources** rather than tool calls. Agents and IDEs can discover device state without "spending" a tool call. (FastMCP supports this.)

**G. ANSI / unicode → pixoo renderer.** Take an arbitrary string of emoji/box-drawing characters and rasterize via Pillow + a TrueType font. Lets the LLM say `"┌─[ok]─┐"` and get reasonable output without building it pixel-by-pixel.

**H. Screen capture by composition.** Since the device doesn't return its own framebuffer, expose a `last_frame_png` resource of whatever you most-recently pushed. Closes the "what does the screen actually look like?" gap during debugging.

**I. Sprite sheet / GIF playback.** Load an animated GIF (via Pillow), downsample frames, and stream via `push_animation`. Trivial to add — `Image.open(...).seek(i)` in a loop — and unlocks a huge content library.

**J. Pure-color helper ops.** `{"op":"hsv","h":0.5,"s":1,"v":1}` so agents can do `for h in 0..1 -> draw_rect` rainbows without calling `hsv_to_rgb` manually in their head.

**K. `clear` defaulting to black.** Minor: today `clear` requires r/g/b. Treating it as `r=0,g=0,b=0` by default (and `bg` color when given) would shrink most JSON.

---

## My suggested priority order

If you want a single "next PR", I'd combine these because they're the highest leverage per line of code:

1. `parse_color()` accepting `"#rgb"` / `"#rrggbb"` / `[r,g,b]` / named colors, used everywhere in `_exec_draw_commands` and `send_text`. *(Halves prompt size for almost every call.)*
2. `bitmap` op with a palette + char-grid. *(Unlocks icons and tiny sprites.)*
3. `output` and `push: false` on `draw`. *(Enables previews and offline iteration.)*
4. Promote `push_animation` to an MCP `animate` tool with declarative frames. *(Removes the only major capability gap vs cyanheads.)*
5. Expose `channel`, `clock`, `scoreboard`, `play_gif_url`, `reboot` in `device_control`. *(Pure surface area you've already implemented.)*
