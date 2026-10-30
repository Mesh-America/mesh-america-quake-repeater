"""Read-only CLI/tool inventory for the identity-bound Mercerwood Morse bench."""
import json
import subprocess
import time

import serial
from serial.tools import list_ports

EXPECTED = {"9AB3B64C641BA927": "RAK4631", "651F8E496197F882": "Heltec T096"}


def port_is_unowned(device):
    """Only an explicit, error-free fuser 'no users' result permits access."""
    owner = subprocess.run(["sudo", "-n", "fuser", device],
                           capture_output=True, text=True, timeout=10)
    if owner.returncode == 0:
        return False
    if owner.returncode == 1 and not owner.stdout.strip() and not owner.stderr.strip():
        return True
    raise RuntimeError(f"Cannot verify that {device} is unowned (fuser rc {owner.returncode})")


def read_quiet(port, limit=2.0):
    data = bytearray()
    until = time.monotonic() + limit
    quiet = time.monotonic() + 0.2
    while time.monotonic() < until and time.monotonic() < quiet:
        chunk = port.read(port.in_waiting or 1)
        if chunk:
            data.extend(chunk)
            quiet = time.monotonic() + 0.2
    return data.decode("utf-8", errors="replace")


def main():
    refused = False
    for command in (["hostname"], ["sudo", "-n", "true"],
                    ["find", "/home/mikec/meshfirmware", "-maxdepth", "2", "-iname", "*custom*"],
                    ["ls", "-la", "/home/mikec/meshfirmware/.customfirmware"]):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({"command": command, "refused": True, "err": str(exc)}), flush=True)
            if command == ["sudo", "-n", "true"]:
                return 1
            continue
        print(json.dumps({"command": command, "rc": result.returncode,
                          "out": result.stdout, "err": result.stderr}), flush=True)
        if command == ["sudo", "-n", "true"] and result.returncode != 0:
            return 1
    for item in list_ports.comports():
        ident = (item.serial_number or "").upper()
        if ident not in EXPECTED or item.interface == "MeshCore Logging":
            continue
        try:
            unowned = port_is_unowned(item.device)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({"board": EXPECTED[ident], "serial": ident,
                              "port": item.device, "refused": True, "err": str(exc)}), flush=True)
            refused = True
            continue
        if not unowned:
            print(json.dumps({"board": EXPECTED[ident], "serial": ident,
                              "port": item.device, "busy": True}), flush=True)
            continue
        port = serial.Serial(port=None, baudrate=115200, timeout=0.03, exclusive=True)
        port.dtr = True
        port.rts = False
        port.port = item.device
        entered = False
        try:
            port.open()
            read_quiet(port)
            port.write(b"+++MESHCORE-TERM-START\n")
            hello = read_quiet(port)
            entered = "WELCOME" in hello
            if not entered:
                print(json.dumps({"board": EXPECTED[ident], "serial": ident,
                                  "port": item.device, "refused": True,
                                  "err": "Text terminal entry was not confirmed"}), flush=True)
                refused = True
                continue
            results = {}
            for command in ("ver", "board", "get name", "get radio", "get tx", "get radio2.status"):
                port.write((command + "\n").encode())
                results[command] = read_quiet(port)
            print(json.dumps({"board": EXPECTED[ident], "serial": ident,
                              "port": item.device, "hello": hello,
                              "commands": results}), flush=True)
        finally:
            try:
                if entered:
                    port.write(b"+++MESHCORE-TERM-STOP\n")
            finally:
                port.close()
    return int(refused)


if __name__ == "__main__":
    raise SystemExit(main())
