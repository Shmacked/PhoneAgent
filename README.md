# PhoneAgent

PhoneAgent lets a Windows or Linux computer drive an iPhone. The computer shows up on the phone as a Bluetooth mouse, receives the screen over AirPlay, and can tap, drag, and scroll. A person can send those commands, or a local or remote vision model can look at the mirror and decide the next tap.

Nothing is installed on the iPhone, and no Apple ID is required.

macOS can receive the AirPlay picture and run the Python tools. It cannot pretend to be a Bluetooth mouse, so taps have to be hosted on Windows or Linux.

## System requirements

The phone and the computer must be on the same Wi-Fi. On the iPhone, turn on AssistiveTouch (Settings → Accessibility → Touch → AssistiveTouch) and turn off Automatically Hide Pointer (Settings → Accessibility → Pointer Control).

| Piece | Windows 10 or 11 | Linux | macOS |
|-------|------------------|-------|-------|
| AirPlay receiver (UxPlay) | Yes, built with MSYS2 | Yes | Yes |
| Bluetooth pointer | Yes, through WSL Ubuntu | Yes, native BlueZ | No |
| Screen capture and taps | Yes | Yes. An X11 session, with `wmctrl` installed | Capture only |
| Vision-model tasks | Yes | Yes | Yes, once a pointer is available on that machine |

Also required:

- Python 3.12 or newer
- A Bluetooth adapter on the machine that runs the pointer
- An iPhone

While the pointer is running on Windows, Windows itself has no Bluetooth. `mouse\Give Bluetooth back to Windows.bat` returns the adapter. On Linux, PhoneAgent stops the normal Bluetooth service and starts its own while the mouse is running.

## Install

Clone this folder, then follow the section for the computer that will run it.

### Windows

1. Double-click `mouse\Set up phone mouse.bat`. Once, it installs usbipd, Ubuntu 24.04 in WSL, and BlueZ, and copies the mouse program into Ubuntu.
2. Install [MSYS2](https://www.msys2.org/) at `C:\msys64` if it is not already there, then double-click `Build UxPlay.bat`. That builds [UxPlay](https://github.com/FDH2/UxPlay).
3. Python dependencies are installed into `.venv` the first time you start the agent. You need the Windows `py` launcher or [uv](https://docs.astral.sh/uv/).

### Linux

Install the window tool and the Python venv package, then build UxPlay:

```bash
sudo apt install wmctrl python3-venv python3-pip
bash build_uxplay_unix.sh
export PATH="$HOME/.local/bin:$PATH"
```

`build_uxplay_unix.sh` installs the GStreamer, OpenSSL, libplist, and Avahi build packages on apt-based systems, builds UxPlay, and installs `uxplay` into `~/.local/bin`. On other distributions, install those libraries yourself and run `SKIP_DEPS=1 bash build_uxplay_unix.sh`.

The pointer also needs BlueZ and the Python D-Bus bindings:

```bash
sudo apt install bluez python3-dbus python3-gi
```

Use an X11 session, or XWayland. `wmctrl` is how the agent finds the mirror window.

### macOS

Install Homebrew, then build the AirPlay receiver:

```bash
bash build_uxplay_unix.sh
export PATH="$HOME/.local/bin:$PATH"
```

Python 3.12 can come from Homebrew (`brew install python@3.12`). The Bluetooth pointer cannot run on macOS.

## Configure

All of the settings live in `config.json`.

| Key | Meaning |
|-----|---------|
| `airplay_name` | The only place to set the Screen Mirroring name. The iPhone lists this name. |
| `mirror_title` | Substring of the mirror window title. Windows with the Direct3D 12 sink uses `Direct3D12 Renderer`. If that title is not found, the agent also tries `airplay_name` and `uxplay`. Run `python -m phone_remote windows` to see titles. |
| `videosink` | GStreamer sink for UxPlay. Leave empty for the platform default: `d3d12videosink` on Windows, `autovideosink` on Linux and macOS. If the picture is black on Windows, set `d3d11videosink`. |
| `phone_mouse_dir` | Folder with the mouse scripts. `mouse` is relative to this repo. |
| `mouse_host`, `mouse_port` | Where the pointer listens. The default is `127.0.0.1:7777` on the same machine. |
| `phone_aspect` | Height divided by width, used to crop the phone out of the mirror window. |
| `gain` | Extra X and Y scale applied on top of `data/mouse.json`. |
| `llm.provider` | `openai` for any OpenAI-compatible server, or `anthropic`. |
| `llm.base_url` | Server root. Include `/v1` for OpenAI-compatible hosts. |
| `llm.model` | Model name. Empty asks a local OpenAI server which model is loaded. The model must accept images. |
| `llm.max_steps` | How many actions one model task may take. |
| `msys_shell` | Windows only. Path to `msys2_shell.cmd` when it is not `C:\msys64\msys2_shell.cmd`. |

Put a remote model's API key in the `PHONEAGENT_LLM_API_KEY` environment variable. `llm.api_key` is a fallback so the key does not have to be stored in the repo. A local server can leave the key empty.

A screenshot is sent to `llm.base_url` on every model step. A local address stays on this machine. A public address sends the picture to that service.

| Where the model runs | `provider` | `base_url` | `model` |
|----------------------|------------|------------|---------|
| LM Studio | `openai` | `http://127.0.0.1:1234/v1` | empty uses the loaded model |
| Ollama | `openai` | `http://127.0.0.1:11434/v1` | a vision model, such as `qwen2.5vl` |
| OpenAI | `openai` | `https://api.openai.com/v1` | a vision model, such as `gpt-4o` |
| Anthropic | `anthropic` | `https://api.anthropic.com` | a vision model, such as `claude-sonnet-4-5` |

`data/mouse.json` is a starter pointer calibration from one phone and one mirror size. Recalibrate on each new machine or phone.

## Use

### Start it

On Windows, double-click `Start PhoneAgent.bat`.

On Linux or macOS:

```bash
bash start.sh
```

That starts UxPlay under `airplay_name` if it is not already running, starts the pointer on Linux (it asks for sudo), waits until the iPhone connects, and watches `data/remote/cmd.txt`.

On the iPhone: Control Center → Screen Mirroring → the `airplay_name` value. The first time, also open Settings → Bluetooth and tap **Phone Mouse**. A paired phone reconnects on its own.

If UxPlay is already open, it keeps the name it was started with. Close that window and start again after changing `airplay_name`.

### Calibrate

The pointer has to be visible and the phone has to stay still.

- Windows: double-click `Calibrate pointer.bat`
- Linux: `bash start.sh --calibrate`

This writes `data/mouse.json`. Do it again if taps miss.

### Commands

Write one line at a time to `data/remote/cmd.txt`. The first token is an id. Each id runs once. Results append to `data/remote/done.txt`. Commands that change the screen refresh `data/remote/shot.png`.

```
1 shot
2 status
3 tap 0.50 0.72
4 drag 0.35 0.55 0.65 0.55 0.4
5 home
6 wait 1.5
7 scroll -3
8 do Open the Clock app
```

Coordinates are fractions of the cropped phone picture: `(0, 0)` is the top-left, `(1, 1)` is the bottom-right.

Taps and drags move from the last known pointer position, then look at the mirror and correct before pressing. The corner is used only when that position is unknown, or when the pointer cannot be seen near the target. The last position is remembered in `data/pointer.json`.

From a shell in this folder, with the virtualenv's Python:

```bash
python -m phone_remote status
python -m phone_remote windows
python -m phone_remote shot
python -m phone_remote tap 0.5 0.5
python -m phone_remote queue 42 tap 0.5 0.72
python -m phone_remote do "Open the Clock app"
```

On Windows the launcher creates `.venv\Scripts\python.exe`. On Linux and macOS it creates `.venv/bin/python`. Use that interpreter if `python` is not the virtualenv.

While `Start PhoneAgent.bat` or `bash start.sh` is already running, send work through the command file so a second process is not also moving the pointer:

```bash
python -m phone_remote queue 8 do Open the Clock app
```

`do` sends each new mirror shot to the model in `config.json`. The model replies with one tap, drag, scroll, or wait. The agent runs it and stops when the model says it is done, or after `llm.max_steps`.

The pointer is one finger. Pinch-zoom still needs a real two-finger gesture. There is no hardware keyboard. To type, tap the field, then tap the on-screen keys. A model does the same thing from the picture.

### What is in the folder

| Path | Role |
|------|------|
| `phone_remote/` | Window capture, pointer math, command agent, model loop |
| `mouse/` | Bluetooth mouse. On Windows this is handed to Ubuntu in WSL. On Linux, `start.sh` runs it with sudo. |
| `data/mouse.json` | Pointer calibration |
| `data/remote/` | Live `cmd.txt`, `shot.png`, `done.txt` |
| `config.json` | AirPlay name, window title, video sink, model server |
| `Build UxPlay.bat` | Windows build of the AirPlay receiver |
| `build_uxplay_unix.sh` | Linux and macOS build of the AirPlay receiver |
| `start.sh` | Linux and macOS launcher |
| `Calibrate pointer.bat` | Windows calibration |
