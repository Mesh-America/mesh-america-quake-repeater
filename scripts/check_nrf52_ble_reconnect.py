#!/usr/bin/env python3
"""Hardware regression: preserve a bonded UART subscription across reboot.

Requires bleak and an already paired test device. This reboots that device;
it does not clear bonds or change its preferences. Pair with the device's
current PIN before running. Only the selected BLE address is accessed.
"""

import argparse
import asyncio
import json
import sys
import time

from bleak import BleakClient


RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
REV = "00001534-1212-efde-1523-785feabcd123"


def report(test, **values):
    print(json.dumps(dict(test=test, **values)), flush=True)


async def paired_client(address):
    if sys.platform != "linux":
        return BleakClient(address, timeout=30)
    # Use BlueZ's existing paired device, rather than requiring a new scanner
    # sighting immediately after every disconnect. This is also how a phone
    # reconnects to a known paired peripheral.
    from bleak.backends.device import BLEDevice
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    path = "/org/bluez/hci0/dev_" + address.upper().replace(":", "_")
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(Message(
            destination="org.bluez", path=path,
            interface="org.freedesktop.DBus.Properties", member="GetAll",
            signature="s", body=["org.bluez.Device1"]))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError("Pair the selected device before running this test")
        props = {key: value.value for key, value in reply.body[0].items()}
        if props.get("Address", "").upper() != address.upper() or not props.get("Paired"):
            raise RuntimeError("Selected BlueZ device is not paired")
        device = BLEDevice(address, props.get("Name"), {"path": path, "props": props})
        return BleakClient(device, timeout=30)
    finally:
        bus.disconnect()


async def prepare(client):
    # BlueZ needs to exchange MTU before using larger UART notifications.
    acquire = getattr(client._backend, "_acquire_mtu", None)
    if acquire:
        await acquire()
    # An encrypted characteristic forces bond-based security without an
    # application write or a notification subscription.
    await client.read_gatt_char(REV)


async def read_cccd(client):
    char = client.services.get_characteristic(TX)
    desc = next(d for d in char.descriptors if d.uuid.startswith("00002902-"))
    return int.from_bytes(await client.read_gatt_descriptor(desc.handle), "little")


async def wait_disconnected(client, timeout):
    deadline = time.monotonic() + timeout
    while client.is_connected:
        if time.monotonic() >= deadline:
            raise TimeoutError("Device did not release the Bluetooth link")
        await asyncio.sleep(0.1)


async def check_commands(client, args):
    queue = asyncio.Queue()
    await client.start_notify(TX, lambda _, data: queue.put_nowait(bytes(data)))

    async def request(payload, prefix):
        await client.write_gatt_char(RX, payload, response=True)
        deadline = time.monotonic() + 10
        while True:
            data = await asyncio.wait_for(queue.get(), deadline - time.monotonic())
            if data.startswith(prefix):
                return data
            if data.startswith(b"\x01"):
                raise RuntimeError("Companion command returned error " + data.hex())

    info = await request(b"\x16\x0e", b"\x0d")
    board = info[20:60].split(b"\0")[0].decode("ascii")
    if board != args.board:
        raise RuntimeError("Wrong board: " + board)
    report("device_identity", board=board, address=args.address, protocol=info[1])
    for cmd in ("ver", "get tx", "get radio", "get name"):
        data = await request(b"\x42B1|" + cmd.encode("ascii") + b"\0", b"\x1dB1|")
        reply = data[4:].decode("ascii")
        if cmd == "ver" and args.version not in reply:
            raise RuntimeError("Unexpected firmware: " + reply)
        if "Unknown command" in reply or "Not Supported" in reply:
            raise RuntimeError(reply)
        report("app_cli", command=cmd, trailing_nul=True, reply=reply)


async def run(args):
    async with await paired_client(args.address) as client:
        await prepare(client)
        await check_commands(client, args)
        value = await read_cccd(client)
        if value != 1:
            raise RuntimeError("UART notifications not enabled: " + str(value))
        # Give the callback worker time to persist the new subscription.
        await asyncio.sleep(3)
        report("subscription_before_reboot", cccd=value)
        try:
            await client.write_gatt_char(RX, b"\x13reboot", response=True)
        except Exception:
            if client.is_connected:
                raise
        await wait_disconnected(client, 10)
        report("application_reboot", passed=True)

    await asyncio.sleep(10)
    async with await paired_client(args.address) as client:
        await prepare(client)
        # MUST precede start_notify: otherwise the host's subscription write
        # would conceal lost persistent CCCD state.
        value = await read_cccd(client)
        report("bonded_cold_reconnect_without_resubscribing", cccd=value)
        if value != 1:
            raise RuntimeError("Bond survived reboot but UART subscription was lost")
        # Also reproduce iOS Connected / no Companion session. No UART writes
        # occur on this connection; firmware must release it automatically.
        started = time.monotonic()
        await wait_disconnected(client, 22)
        report("secured_idle_link_disconnected",
               seconds=round(time.monotonic() - started, 2), passed=True,
               cause_requires_trace=True)

    await asyncio.sleep(2)
    async with await paired_client(args.address) as client:
        await prepare(client)
        await check_commands(client, args)
        report("normal_reconnect_after_recovery", passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--board", required=True, help="Exact DeviceInfo model")
    parser.add_argument("--version", required=True, help="Expected CLI version substring")
    parser.add_argument("--reboot", action="store_true", required=True,
                        help="Acknowledge that the selected test node will reboot")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
