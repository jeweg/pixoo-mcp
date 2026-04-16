# Divoom Pixoo 64 — Protocol Notes

Reverse-engineered from traffic analysis, firmware strings, the
[Grayda/pixoo_api](https://github.com/Grayda/pixoo_api) notes, the
[SomethingWithComputers/pixoo](https://github.com/SomethingWithComputers/pixoo)
PyPI library, and our own experiments.

## Transport

Every command is an HTTP POST to `http://<device-ip>/post` with a JSON body.
The device listens on port 80.  There is no authentication.

```
POST /post HTTP/1.1
Content-Type: application/json

{"Command": "Channel/GetAllConf"}
```

Responses are JSON with an `error_code` field (0 = success).

There are two APIs:
- **Local API** — direct HTTP to the device on port 80 (what we use)
- **Cloud API** — `https://appin.divoom-gz.com/` (used by the phone app,
  supports alarms, gallery uploads, user accounts, etc.)

## Channels

The display has four channels.  Only one is active at a time.

| Index | Name       | Description                                        |
|-------|------------|----------------------------------------------------|
| 0     | Faces      | Clock faces / widgets configured via the phone app  |
| 1     | Cloud      | Cloud-synced content                                |
| 2     | Visualizer | Audio equalizer / VU meter                         |
| 3     | Custom     | Content pushed via `Draw/SendHttpGif`              |

### Channel commands

| Command                     | Payload                 | Notes                              |
|-----------------------------|-------------------------|------------------------------------|
| `Channel/GetIndex`          | —                       | Returns `{"SelectIndex": N}`       |
| `Channel/SetIndex`          | `{"SelectIndex": N}`    | Switch to channel N                |
| `Channel/GetAllConf`        | —                       | Full config dump (see below)       |
| `Channel/SetStartupChannel` | `{"ChannelId": N}`      | Which channel to show after reboot |
| `Channel/OnOffScreen`       | `{"OnOff": 0\|1}`       | Turn display on/off                |
| `Channel/SetBrightness`     | `{"Brightness": 0-100}` | Set backlight brightness           |
| `Channel/SetClockSelectId`  | `{"ClockId": N}`        | Pick a clock face                  |
| `Channel/SetEqPosition`     | `{"EqPosition": N}`     | Pick a visualizer style            |

### Channel priority / phone app conflict

There is **no priority system** — last command wins.  When you `push()` a
frame, the device switches to channel 3.  But if the Divoom phone app sends
a `Channel/SetIndex` for channel 0 (to show a clock face, stock ticker, or
weather), the device obeys and your custom content disappears.

Workarounds:
- Disconnect / close the phone app.
- Set the startup channel to 3 so reboots land on Custom.
- Re-push periodically from a script.

## Drawing pixels

### Buffer format

A full frame is **64 × 64 pixels × 3 bytes (RGB) = 12 288 bytes**, then
**base64-encoded** into the `PicData` field.  Pixel order is left-to-right,
top-to-bottom (y=0 is the top row).

### Draw/SendHttpGif

Push one or more frames to the display.

```json
{
  "Command": "Draw/SendHttpGif",
  "PicNum": 1,
  "PicWidth": 64,
  "PicOffset": 0,
  "PicID": 1,
  "PicSpeed": 1000,
  "PicData": "<base64 RGB data>"
}
```

| Field       | Description                                               |
|-------------|-----------------------------------------------------------|
| `PicNum`    | Total number of frames in this animation                  |
| `PicWidth`  | Display size — 16, 32, or 64                              |
| `PicOffset` | Frame index, 0-based (0 to PicNum-1)                      |
| `PicID`     | Unique, monotonically increasing ID                        |
| `PicSpeed`  | Frame duration in milliseconds                             |
| `PicData`   | Base64-encoded raw RGB bytes (12 288 bytes for 64×64)      |

For animations, send multiple `Draw/SendHttpGif` requests in sequence, each
with the same `PicID` but incrementing `PicOffset`.  **Cannot** be batched
via `Draw/CommandList`.

### Counter / PicID management

The `PicID` must be unique and larger than the previous value.  After ~300
pushes the device stops responding (firmware bug).

- `Draw/GetHttpGifId` — returns `{"PicId": N}`, the current counter
- `Draw/ResetHttpGifId` — resets the counter to 0

Auto-reset every ~32 frames to stay stable.

### Limits

- Max ~40 frames per animation (device may crash beyond this).
- A "Loading.." animation plays briefly when receiving an animation.
- Single-frame pushes are instant.
- Text overlay (`Draw/SendHttpText`) only works on top of `Draw/SendHttpGif`
  content, not on SD card GIFs or gallery images.

## Text overlay

The device can render text on top of custom content using its built-in fonts.

```json
{
  "Command": "Draw/SendHttpText",
  "TextId": 1,
  "x": 0,
  "y": 0,
  "dir": 0,
  "font": 2,
  "TextWidth": 64,
  "speed": 0,
  "align": 1,
  "color": "#FFFFFF",
  "TextString": "Hello"
}
```

| Field       | Description                                      |
|-------------|--------------------------------------------------|
| `TextId`    | Identifier 0–19 (can have multiple texts)        |
| `font`      | Font index 0–7 (some substitute symbols)         |
| `speed`     | 0 = static, >0 = scroll speed in ms              |
| `dir`       | Scroll direction: 0 = left, 1 = right            |
| `color`     | Hex color string `"#RRGGBB"`                     |

Clear all text: `Draw/ClearHttpText`.

Font quirks (from Grayda's notes):
- Font 18 replaces `u`/`d` with up/down arrows.
- Font 20 replaces `c`/`f` with `°C`/`°F`.
- Some font/character combos crash the device.
- Scrolling right may invert the string.
- Full font list: `https://app.divoom-gz.com/Device/GetTimeDialFontList`

## Device commands

| Command                       | Payload                                                  | Notes                              |
|-------------------------------|----------------------------------------------------------|------------------------------------|
| `Device/GetDeviceTime`        | —                                                        | Returns UTC and local time          |
| `Device/SetHighLightMode`     | `{"Mode": true\|false}`                                  | High-contrast mode                  |
| `Device/SetMirrorMode`        | `{"Mode": true\|false}`                                  | Mirror the display                  |
| `Device/SetWhiteBalance`      | `{"RValue": 0-100, "GValue": 0-100, "BValue": 0-100}`   | White balance per channel          |
| `Device/PlayBuzzer`           | `{"ActiveTimeInCycle": ms, "OffTimeInCycle": ms, "PlayTotalTime": ms}` | Buzz the buzzer |
| `Device/SysReboot`            | —                                                        | Reboot the device                   |
| `Device/PlayTFGif`            | `{"FileType": N, "FileName": "..."}`                     | Play GIF (0=SD file, 1=SD dir, 2=URL) |
| `Tools/SetNoiseStatus`        | `{"NoiseStatus": true\|false}`                           | Noise meter on/off                  |
| `Tools/SetScoreBoard`         | `{"BlueScore": 0-999, "RedScore": 0-999}`                | Scoreboard display                  |
| `Tools/SetTimer`              | (unknown payload)                                        | Countdown timer                     |
| `Tools/SetStopWatch`          | (unknown payload)                                        | Stopwatch                           |

## Config dump

`Channel/GetAllConf` returns:

```json
{
  "error_code": 0,
  "Brightness": 50,
  "RotationFlag": 0,
  "ClockTime": 0,
  "GalleryTime": 0,
  "SingleGalleyTime": -1,
  "PowerOnChannelId": 0,
  "GalleryShowTimeFlag": 0,
  "CurClockId": 195,
  "Time24Flag": 1,
  "TemperatureMode": 0,
  "GyrateAngle": 0,
  "MirrorFlag": 0,
  "LightSwitch": 1
}
```

| Field              | Meaning                                              |
|--------------------|------------------------------------------------------|
| `Brightness`       | Current brightness 0–100                             |
| `PowerOnChannelId` | Channel shown at boot (0–3)                          |
| `CurClockId`       | Active clock face ID                                 |
| `Time24Flag`       | 1 = 24h format, 0 = 12h                             |
| `TemperatureMode`  | 0 = Celsius, 1 = Fahrenheit                          |
| `GyrateAngle`      | Screen rotation angle                                |
| `MirrorFlag`       | Display mirroring                                    |
| `LightSwitch`      | 1 = screen on, 0 = screen off                        |
| `RotationFlag`     | Auto-rotation enabled                                |

## Device discovery

The Divoom cloud can report devices on the same LAN:

```
POST https://app.divoom-gz.com/Device/ReturnSameLANDevice
```

Returns a `DeviceList` with `DeviceName`, `DevicePrivateIP`, `DeviceId`, etc.
No authentication required for this endpoint.

## Firmware command list

Full list of commands found in the firmware binary (`divoom-92.bin`) and the
decompiled APK, beyond what's documented above:

<details>
<summary>Firmware commands (local API)</summary>

```
Alarm/Del, Alarm/Listen
Channel/AddEqData, Channel/CleanCustom, Channel/CloudIndex,
Channel/DeleteCustom, Channel/DeleteEq, Channel/GetAllConf,
Channel/GetAllCustomTime, Channel/GetClockInfo, Channel/GetConfig,
Channel/GetCustomPageIndex, Channel/GetCustomTime,
Channel/GetEqPosition, Channel/GetEqTime, Channel/GetIndex,
Channel/GetNightView, Channel/GetStartupChannel,
Channel/GetSubscribeTime, Channel/OnOffScreen,
Channel/SetAllCustomTime, Channel/SetBrightness,
Channel/SetClockConfig, Channel/SetClockSelectId,
Channel/SetConfig, Channel/SetCustom, Channel/SetCustomId,
Channel/SetCustomPageIndex, Channel/SetEqPosition,
Channel/SetEqTime, Channel/SetIndex, Channel/SetNightView,
Channel/SetProduceTime, Channel/SetStartupChannel,
Channel/SetSubscribe, Channel/SetSubscribeTime
Device/AppRestartMqtt, Device/AutoUpgradePush, Device/BindUser,
Device/ClearResetFlag, Device/CloseClockTimer, Device/Connect,
Device/ConnectApp, Device/DeleteResetAll, Device/Disconnect,
Device/DisconnectMqtt, Device/ExitSubscribeDisp,
Device/GetAlarm, Device/GetAppIP, Device/GetBlueName,
Device/GetClockInfo, Device/GetClockList, Device/GetCustomList,
Device/GetDailyLunarInfo, Device/GetDeviceId, Device/GetDeviceTime,
Device/GetEqDataList, Device/GetExpertLast,
Device/GetFavoriteList, Device/GetFileByApp,
Device/GetHistoryClockList, Device/GetHotList,
Device/GetMemorial, Device/GetSomeAlbum, Device/GetSomeFontInfo,
Device/GetTimeDialAppPic, Device/GetTimeDialFont,
Device/GetTimePlan, Device/GetUserDefineList,
Device/GetWeatherInfo, Device/Hearbeat, Device/Init,
Device/OpenHttpRecord, Device/PlayBuzzer, Device/PlayTFGif,
Device/PushAppIP, Device/ResetAll, Device/SetAlarm,
Device/SetBlueName, Device/SetDisTempMode,
Device/SetHighLightMode, Device/SetMemorial,
Device/SetMirrorMode, Device/SetScreenRotationAngle,
Device/SetUTC, Device/SetWhiteBalance, Device/ShareDevice,
Device/Unbind, Device/UpLoadExpertLast,
Device/UpdateDevicePublicIP, Device/UpdateLogLevel,
Device/UpgradeRecord, Device/SysReboot
Draw/ClearHttpText, Draw/CommandList, Draw/DeleteTempFile,
Draw/ExitSync, Draw/GetHttpGifId, Draw/NeedLocalData,
Draw/NeedSendDraw, Draw/ResetHttpGifId, Draw/Send,
Draw/SendHttpGif, Draw/SendHttpItemList, Draw/SendHttpText,
Draw/SendLocal, Draw/SendRealTimeEQ, Draw/SendRemote,
Draw/SetInfo, Draw/SetSpeedMode, Draw/Sync,
Draw/UpLoadAndSend, Draw/UpLoadEqAndSend,
Draw/UseHTTPCommandSource
Tools/GetNoiseStatus, Tools/GetScoreBoard, Tools/GetStopWatch,
Tools/GetTimer, Tools/SetNoiseStatus, Tools/SetScoreBoard,
Tools/SetStopWatch, Tools/SetTimer
Sleep/ExitTest, Sleep/Get, Sleep/Set, Sleep/Test
Sys/FormatTF, Sys/GetBrightness, Sys/GetConf, Sys/LogAndLat,
Sys/PlayTFGif, Sys/PoweronMode, Sys/PushUpdate, Sys/SetConf,
Sys/TimeZone
DivoomIfft/* (IFTTT integration endpoints)
Lamda/* (Alexa/Lambda integration endpoints)
Weather/GetForecastWeatherInfo, Weather/GetRealWeatherInfo
```

</details>

<details>
<summary>Cloud API commands (appin.divoom-gz.com)</summary>

The phone app talks to `https://appin.divoom-gz.com/` for features not
available on the local API: alarms, gallery uploads, user accounts, MQTT,
community features, firmware updates, etc.  Requires `Token` + `UserId`
from `UserLogin`.

Notable: the cloud runs an MQTT server on the same host.  The device
connects to it (not the other way around), so blocking
`appin.divoom-gz.com` at the DNS level would cut off cloud features but
keep local API control intact.

</details>

## Gotchas

- **PicData encoding**: must be **base64**, not hex.  The official docs are
  ambiguous but base64 is what works.
- **Draw/UseHTTPCommandSource**: exists in firmware strings but causes
  the device to hang when called.  Don't use it.
- **Draw/CommandList**: cannot batch `Draw/SendHttpGif` frames.  Must send
  them as separate HTTP requests.
- **Counter overflow**: device stops responding after ~300 `SendHttpGif`
  calls.  Reset the counter periodically.
- **Phone app**: constantly reconnects and can override your content at
  any time by switching channels.
- **y=0 is top**: coordinate system has origin at top-left, y increases
  downward (matters for drawing arcs, smileys, etc.).
- **The app phones home**: makes calls to `rongcfg.com` and `rongnav.com`
  (likely telemetry).  Consider blocking at the network level.
- **Screen rotation**: `GyrateAngle` in config, set via
  `Device/SetScreenRotationAngle`.
