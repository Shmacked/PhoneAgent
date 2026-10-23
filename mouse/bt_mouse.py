#!/usr/bin/env python3
"""Makes this Linux (WSL) machine show up to your iPhone as a Bluetooth mouse.

Runs inside WSL as root, with the PC's Bluetooth chip handed over by usbipd.
Windows programs control the pointer by sending one-line commands to
127.0.0.1:7777 (WSL forwards it to Windows):

    status              -> "no-adapter" | "waiting" (for the iPhone) | "connected"
    move DX DY          relative move in mouse counts (split into small, even steps)
    home                shove the pointer into the top-left corner
    down / up / click   press, release, or press+release the left button
    scroll N            wheel (positive = up)
    pace STEP MS        step size and pause per step used by move (default 8, 8)
    quit                stop this program

Every command answers one line: "ok", a status word, or "err <reason>".
"""
from __future__ import annotations

import glob
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
FW_CACHE = HERE / "firmware"
CMD_PORT = 7777
NAME = "Phone Mouse"
PSM_CTRL, PSM_INTR = 17, 19
FW_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/"

# A plain 3-button mouse with a wheel (also valid as a "boot" mouse report).
HID_DESCRIPTOR = (
    "05010902a1010901a100"                # Generic Desktop / Mouse / Pointer / Physical
    "05091901290315002501950375018102"    # 3 buttons
    "950175058103"                        # 5 bits padding
    "05010930093109381581257f750895038106"  # X, Y, wheel: -127..127, relative
    "c0c0"
)

SDP_RECORD = f"""<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001"><sequence><uuid value="0x1124"/></sequence></attribute>
  <attribute id="0x0004"><sequence>
    <sequence><uuid value="0x0100"/><uint16 value="0x0011"/></sequence>
    <sequence><uuid value="0x0011"/></sequence>
  </sequence></attribute>
  <attribute id="0x0005"><sequence><uuid value="0x1002"/></sequence></attribute>
  <attribute id="0x0006"><sequence>
    <uint16 value="0x656e"/><uint16 value="0x006a"/><uint16 value="0x0100"/>
  </sequence></attribute>
  <attribute id="0x0009"><sequence>
    <sequence><uuid value="0x1124"/><uint16 value="0x0101"/></sequence>
  </sequence></attribute>
  <attribute id="0x000d"><sequence><sequence>
    <sequence><uuid value="0x0100"/><uint16 value="0x0013"/></sequence>
    <sequence><uuid value="0x0011"/></sequence>
  </sequence></sequence></attribute>
  <attribute id="0x0100"><text value="{NAME}"/></attribute>
  <attribute id="0x0101"><text value="Bluetooth mouse"/></attribute>
  <attribute id="0x0102"><text value="phone-mouse"/></attribute>
  <attribute id="0x0200"><uint16 value="0x0100"/></attribute>
  <attribute id="0x0201"><uint16 value="0x0111"/></attribute>
  <attribute id="0x0202"><uint8 value="0x80"/></attribute>
  <attribute id="0x0203"><uint8 value="0x00"/></attribute>
  <attribute id="0x0204"><boolean value="true"/></attribute>
  <attribute id="0x0205"><boolean value="true"/></attribute>
  <attribute id="0x0206"><sequence><sequence>
    <uint8 value="0x22"/><text encoding="hex" value="{HID_DESCRIPTOR}"/>
  </sequence></sequence></attribute>
  <attribute id="0x0207"><sequence><sequence>
    <uint16 value="0x0409"/><uint16 value="0x0100"/>
  </sequence></sequence></attribute>
  <attribute id="0x020b"><uint16 value="0x0100"/></attribute>
  <attribute id="0x020c"><uint16 value="0x0c80"/></attribute>
  <attribute id="0x020d"><boolean value="true"/></attribute>
  <attribute id="0x020e"><boolean value="true"/></attribute>
</record>
"""


LOG = HERE / "log.txt"


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sh(*cmd: str) -> int:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except OSError:
        return 127


# ------------------------------------------------------------------ firmware
# WSL's kernel can't see this Linux's /lib/firmware, so firmware requests fail.
# With the "sysfs fallback" switched on, the kernel instead waits for a program to
# hand it the file through /sys/class/firmware/. This thread is that program.

def _firmware_bytes(name: str) -> bytes | None:
    cached = FW_CACHE / name
    if cached.exists():
        return cached.read_bytes()
    data = None
    for local in (Path("/lib/firmware") / name, Path("/lib/firmware") / (name + ".zst")):
        if local.exists():
            if local.suffix == ".zst":
                r = subprocess.run(["zstd", "-dc", str(local)], capture_output=True)
                data = r.stdout if r.returncode == 0 else None
            else:
                data = local.read_bytes()
            break
    if data is None:
        try:
            log(f"Downloading firmware {name} ...")
            with urllib.request.urlopen(FW_URL + name, timeout=30) as resp:
                data = resp.read()
        except Exception as e:
            log(f"  couldn't download {name}: {e}")
            return None
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def firmware_feeder() -> None:
    try:
        Path("/proc/sys/kernel/firmware_config/force_sysfs_fallback").write_text("1")
        Path("/proc/sys/kernel/firmware_config/ignore_sysfs_fallback").write_text("0")
    except OSError as e:
        log(f"Note: couldn't switch on firmware fallback ({e}).")
    seen: set[str] = set()
    while True:
        for d in glob.glob("/sys/class/firmware/*/loading"):
            entry = os.path.dirname(d)
            key = entry + str(os.stat(d).st_ino)
            if key in seen:
                continue
            seen.add(key)
            name = os.path.basename(entry).replace("!", "/")
            data = _firmware_bytes(name)
            try:
                Path(d).write_text("1")
                if data is not None:
                    with open(os.path.join(entry, "data"), "wb") as f:
                        f.write(data)
                    Path(d).write_text("0")
                    log(f"Gave the kernel firmware {name} ({len(data)} bytes)")
                else:
                    Path(d).write_text("-1")
                    log(f"No firmware file {name}; the kernel will skip it")
            except OSError as e:
                log(f"Firmware hand-off for {name} failed: {e}")
        time.sleep(0.2)


# ------------------------------------------------------------------ BlueZ
def ensure_bluez() -> None:
    if not os.path.exists("/run/dbus/system_bus_socket"):
        os.makedirs("/run/dbus", exist_ok=True)
        sh("dbus-daemon", "--system", "--fork")
        time.sleep(0.5)
    sh("pkill", "-x", "bluetoothd")
    time.sleep(0.3)
    daemon = next((p for p in ("/usr/libexec/bluetooth/bluetoothd", "/usr/lib/bluetooth/bluetoothd")
                   if os.path.exists(p)), "bluetoothd")
    # "input" off: that plugin would claim the HID channels we need to listen on.
    subprocess.Popen([daemon, "-n", "--noplugin=input", "-f", str(HERE / "main.conf")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)


class Agent(dbus.service.Object):
    """Accepts pairing without a code ("Just Works")."""
    IFACE = "org.bluez.Agent1"

    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus

    def _trust(self, device):
        try:
            props = dbus.Interface(self.bus.get_object("org.bluez", device), "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        except Exception:
            pass

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method(IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        self._trust(device)
        return "0000"

    @dbus.service.method(IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        self._trust(device)
        return dbus.UInt32(0)

    @dbus.service.method(IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method(IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method(IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log("Pairing request accepted")
        self._trust(device)

    @dbus.service.method(IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        self._trust(device)

    @dbus.service.method(IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        self._trust(device)

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Cancel(self):
        pass


class Profile(dbus.service.Object):
    """Only exists so BlueZ publishes our HID service record."""
    IFACE = "org.bluez.Profile1"

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method(IFACE, in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device, fd, props):
        os.close(fd.take())

    @dbus.service.method(IFACE, in_signature="o", out_signature="")
    def RequestDisconnection(self, device):
        pass


def find_adapter(bus) -> str | None:
    mgr = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    for path, ifaces in mgr.GetManagedObjects().items():
        if "org.bluez.Adapter1" in ifaces:
            return str(path)
    return None


# ------------------------------------------------------------------ the mouse
class Mouse:
    def __init__(self):
        self.lock = threading.Lock()
        self.ctrl: socket.socket | None = None
        self.intr: socket.socket | None = None
        self.host: str | None = None
        self.buttons = 0
        self.adapter_ready = False
        self.step, self.pause = 8, 0.008

    # --- connection
    @property
    def connected(self) -> bool:
        return self.intr is not None

    def status(self) -> str:
        if not self.adapter_ready:
            return "no-adapter"
        return "connected" if self.connected else "waiting"

    def drop(self, why: str = "") -> None:
        with self.lock:
            was = self.connected
            for s in (self.intr, self.ctrl):
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass
            self.ctrl = self.intr = None
        if was:
            log(f"iPhone disconnected{': ' + why if why else ''}")

    def _remember(self, addr: str) -> None:
        self.host = addr
        try:
            STATE.write_text(json.dumps({"host": addr}))
        except OSError:
            pass

    def _connected(self, ctrl, intr, addr):
        with self.lock:
            self.ctrl, self.intr = ctrl, intr
        self._remember(addr)
        log(f"iPhone connected ({addr})")
        threading.Thread(target=self._control_loop, args=(ctrl,), daemon=True).start()

    def listen(self) -> None:
        srv_c = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        srv_i = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        for s, psm in ((srv_c, PSM_CTRL), (srv_i, PSM_INTR)):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((socket.BDADDR_ANY, psm))
            s.listen(1)
        while True:
            c, (addr, _) = srv_c.accept()
            srv_i.settimeout(10)
            try:
                i, _ = srv_i.accept()
            except socket.timeout:
                c.close()
                continue
            finally:
                srv_i.settimeout(None)
            self.drop("replaced by a new connection")
            self._connected(c, i, addr)

    def reconnect_loop(self) -> None:
        """A paired iPhone doesn't always reconnect by itself; knock on its door."""
        try:
            self.host = json.loads(STATE.read_text()).get("host")
        except (OSError, ValueError):
            pass
        while True:
            time.sleep(5)
            if self.connected or not self.host or not self.adapter_ready:
                continue
            c = i = None
            try:
                c = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
                c.settimeout(5)
                c.connect((self.host, PSM_CTRL))
                i = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
                i.settimeout(5)
                i.connect((self.host, PSM_INTR))
                c.settimeout(None)
                i.settimeout(None)
                if not self.connected:
                    self._connected(c, i, self.host)
                    continue
            except OSError:
                pass
            for s in (c, i):
                if s:
                    s.close()
            time.sleep(10)

    def _control_loop(self, ctrl: socket.socket) -> None:
        """Answer the few housekeeping messages an iPhone sends on the control channel."""
        while True:
            try:
                msg = ctrl.recv(64)
            except OSError:
                msg = b""
            if not msg:
                if ctrl is self.ctrl:
                    self.drop()
                return
            kind = msg[0] >> 4
            try:
                if kind == 0x1 and (msg[0] & 0x0F) == 0x5:   # virtual cable unplug
                    self.drop("unplugged")
                    return
                if kind in (0x5, 0x7, 0x9):                    # SET_REPORT / SET_PROTOCOL / SET_IDLE
                    ctrl.send(b"\x00")
                elif kind == 0x4:                              # GET_REPORT
                    ctrl.send(bytes([0xA1, self.buttons, 0, 0, 0]))
                elif kind == 0x6:                              # GET_PROTOCOL
                    ctrl.send(b"\xa0\x01")
                elif kind == 0x8:                              # GET_IDLE
                    ctrl.send(b"\xa0\x00")
                else:
                    ctrl.send(b"\x03")                         # unsupported
            except OSError:
                pass

    # --- reports
    def _send(self, dx: int = 0, dy: int = 0, wheel: int = 0) -> None:
        intr = self.intr
        if intr is None:
            raise ConnectionError("iPhone not connected")
        try:
            intr.send(bytes([0xA1, self.buttons & 7, dx & 0xFF, dy & 0xFF, wheel & 0xFF]))
        except OSError as e:
            self.drop(str(e))
            raise ConnectionError("iPhone disconnected") from e

    def move(self, dx: int, dy: int, step: int | None = None, pause: float | None = None) -> None:
        step = max(1, min(127, step or self.step))
        pause = self.pause if pause is None else pause
        n = max(1, -(-max(abs(dx), abs(dy)) // step))
        sx = sy = 0
        for k in range(1, n + 1):
            tx, ty = round(dx * k / n), round(dy * k / n)
            self._send(tx - sx, ty - sy)
            sx, sy = tx, ty
            time.sleep(pause)

    def home(self) -> None:
        for _ in range(40):
            self._send(-127, -127)
            time.sleep(0.004)
        time.sleep(0.1)

    def button(self, down: bool) -> None:
        self.buttons = (self.buttons | 1) if down else (self.buttons & ~1)
        self._send()
        time.sleep(0.03)

    def scroll(self, n: int) -> None:
        for _ in range(abs(n)):
            self._send(wheel=1 if n > 0 else -1)
            time.sleep(0.02)


# ------------------------------------------------------------------ commands from Windows
def command_server(mouse: Mouse, loop: GLib.MainLoop) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", CMD_PORT))
    srv.listen(4)

    def handle(conn: socket.socket) -> None:
        f = conn.makefile("rw", encoding="utf-8", newline="\n")
        for line in f:
            parts = line.split()
            if not parts:
                continue
            cmd, args = parts[0].lower(), parts[1:]
            try:
                if cmd == "status":
                    reply = mouse.status()
                elif cmd == "move":
                    mouse.move(int(args[0]), int(args[1]),
                               int(args[2]) if len(args) > 2 else None,
                               float(args[3]) / 1000 if len(args) > 3 else None)
                    reply = "ok"
                elif cmd == "home":
                    mouse.home(); reply = "ok"
                elif cmd == "down":
                    mouse.button(True); reply = "ok"
                elif cmd == "up":
                    mouse.button(False); reply = "ok"
                elif cmd in ("click", "tap"):
                    mouse.button(True); time.sleep(0.05); mouse.button(False); reply = "ok"
                elif cmd == "scroll":
                    mouse.scroll(int(args[0])); reply = "ok"
                elif cmd == "pace":
                    mouse.step, mouse.pause = int(args[0]), float(args[1]) / 1000; reply = "ok"
                elif cmd == "quit":
                    f.write("ok\n"); f.flush()
                    GLib.idle_add(loop.quit)
                    return
                else:
                    reply = f"err unknown command {cmd}"
            except (IndexError, ValueError):
                reply = "err bad arguments"
            except ConnectionError as e:
                reply = f"err {e}"
            f.write(reply + "\n")
            f.flush()
        conn.close()

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def setup_adapter(bus, mouse: Mouse, agent_path: str, profile_path: str) -> None:
    """Wait for the Bluetooth chip, then make it a discoverable mouse."""
    log("Waiting for the Bluetooth chip (Windows hands it over with usbipd) ...")
    sh("modprobe", "btusb")
    adapter = None
    while adapter is None:
        try:
            adapter = find_adapter(bus)
        except dbus.DBusException:
            pass
        if adapter is None:
            time.sleep(1)
    log(f"Bluetooth chip found: {adapter}")
    time.sleep(1.5)  # let the firmware settle
    props = dbus.Interface(bus.get_object("org.bluez", adapter), "org.freedesktop.DBus.Properties")
    a = "org.bluez.Adapter1"
    for _ in range(10):
        try:
            props.Set(a, "Powered", dbus.Boolean(True))
            break
        except dbus.DBusException as e:
            log(f"  powering on ... ({e.get_dbus_message()})")
            time.sleep(1.5)
    sh("btmgmt", "--index", adapter.rsplit("hci", 1)[-1], "class", "5", "128")  # peripheral / pointing device
    for key, val in (("Alias", dbus.String(NAME)), ("DiscoverableTimeout", dbus.UInt32(0)),
                     ("PairableTimeout", dbus.UInt32(0)), ("Pairable", dbus.Boolean(True)),
                     ("Discoverable", dbus.Boolean(True))):
        try:
            props.Set(a, key, val)
        except dbus.DBusException as e:
            log(f"  couldn't set {key}: {e.get_dbus_message()}")

    agents = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
    agents.RegisterAgent(agent_path, "NoInputNoOutput")
    agents.RequestDefaultAgent(agent_path)
    profiles = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
    profiles.RegisterProfile(profile_path, "00001124-0000-1000-8000-00805f9b34fb", {
        "ServiceRecord": SDP_RECORD, "Role": "server",
        "RequireAuthentication": dbus.Boolean(False), "RequireAuthorization": dbus.Boolean(False),
    })
    mouse.adapter_ready = True
    try:
        info = {k: props.Get(a, k) for k in ("Address", "Class", "Powered", "Discoverable", "Pairable")}
        log("Adapter: " + ", ".join(f"{k}={hex(v) if k == 'Class' else v}" for k, v in info.items()))
    except dbus.DBusException:
        pass
    log(f'Ready. On the iPhone open Settings > Bluetooth and tap "{NAME}".')


def watch_devices(bus) -> None:
    """Log what nearby devices (the iPhone) do: show up, pair, connect."""
    def changed(iface, props, _inv, path=None):
        if iface != "org.bluez.Device1":
            return
        keys = {k: bool(v) for k, v in props.items() if k in ("Paired", "Connected", "Trusted", "Bonded")}
        if keys:
            log(f"Device {str(path).rsplit('/', 1)[-1]}: {keys}")

    def added(path, ifaces):
        d = ifaces.get("org.bluez.Device1")
        if d and (d.get("Paired") or d.get("Connected")):
            log(f"Device {d.get('Alias', '')} {d.get('Address', '')} paired={bool(d.get('Paired'))}")

    bus.add_signal_receiver(changed, dbus_interface="org.freedesktop.DBus.Properties",
                            signal_name="PropertiesChanged", path_keyword="path", bus_name="org.bluez")
    bus.add_signal_receiver(added, dbus_interface="org.freedesktop.DBus.ObjectManager",
                            signal_name="InterfacesAdded", bus_name="org.bluez")


def main() -> None:
    if os.geteuid() != 0:
        sys.exit("Run as root (on Windows: wsl -u root; on Linux: sudo).")
    threading.Thread(target=firmware_feeder, daemon=True).start()
    ensure_bluez()

    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
    mouse = Mouse()
    agent_path, profile_path = "/phonemouse/agent", "/phonemouse/profile"
    Agent(bus, agent_path)
    Profile(bus, profile_path)

    try:
        LOG.write_text("")
    except OSError:
        pass
    watch_devices(bus)
    threading.Thread(target=command_server, args=(mouse, loop), daemon=True).start()
    log(f"Listening for commands on 127.0.0.1:{CMD_PORT}")

    def start():
        setup_adapter(bus, mouse, agent_path, profile_path)
        threading.Thread(target=mouse.listen, daemon=True).start()
        threading.Thread(target=mouse.reconnect_loop, daemon=True).start()

    threading.Thread(target=start, daemon=True).start()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    mouse.drop("stopping")
    sh("pkill", "-x", "bluetoothd")
    log("Stopped.")


if __name__ == "__main__":
    main()
