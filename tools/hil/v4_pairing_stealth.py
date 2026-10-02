#!/usr/bin/env python3
"""Exact-target BLE/OLED regression test; changes settings and reboots the V4.

Use only after a verified full-flash backup. The caller restores that backup
afterward. The helper does not read contacts/messages/private keys or request
LoRa transmissions; normal background radio activity is not disabled.
Requires pyserial, bleak and dbus-fast on the Bluetooth test host.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import threading
import time

import serial
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from dbus_fast import BusType, DBusError, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
PIN = 246810  # Deliberately not NimBLE's 123456 callback sentinel.


def report(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


async def call(bus, path, interface, member, signature='', body=None):
    reply = await asyncio.wait_for(bus.call(Message(
        destination='org.bluez', path=path, interface=interface, member=member,
        signature=signature, body=body or [])), 15)
    if reply.message_type == MessageType.ERROR:
        raise RuntimeError(f'{member}: {reply.error_name}: {reply.body}')
    return reply.body


async def props(bus, path):
    values = (await call(bus, path, 'org.freedesktop.DBus.Properties',
                         'GetAll', 's', ['org.bluez.Device1']))[0]
    return {key: value.value for key, value in values.items()}


class Agent(ServiceInterface):
    def __init__(self, target):
        super().__init__('org.bluez.Agent1')
        self.target = target
        self.requests = 0

    def check(self, device):
        if device != self.target:
            raise DBusError('org.bluez.Error.Rejected', 'Not the test V4')

    @method()
    async def RequestPasskey(self, device: 'o') -> 'u':
        self.check(device)
        self.requests += 1
        report('passkey_requested', address=device)
        # Leave the real pairing request outstanding long enough to capture
        # the physical display driver's frame, not a manually invoked callback.
        await asyncio.sleep(3)
        return PIN

    @method()
    def RequestPinCode(self, device: 'o') -> 's':
        self.check(device)
        return str(PIN)

    @method()
    def RequestAuthorization(self, device: 'o'):
        self.check(device)

    @method()
    def AuthorizeService(self, device: 'o', uuid: 's'):
        self.check(device)

    @method()
    def Cancel(self):
        report('pairing_cancelled')

    @method()
    def Release(self):
        pass


class USB:
    def __init__(self, path, output):
        self.output = output
        self.data = bytearray()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.port = serial.Serial(None, 115200, timeout=.05, exclusive=True)
        self.port.rts = False
        self.port.dtr = True
        self.port.port = path
        self.port.open()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        while not self.stop.is_set():
            value = self.port.read(max(1, self.port.in_waiting))
            with self.lock:
                self.data.extend(value)

    def snapshot(self):
        with self.lock:
            return bytes(self.data).decode('ascii', errors='replace')

    def command_sync(self, command, timeout=8):
        start = len(self.snapshot())
        self.port.write((command + '\r\n').encode('ascii'))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.snapshot()[start:]
            # Logging can follow a prompt immediately, without a newline.
            # Reply values are indented ("  > ..."), unlike the actual prompt.
            if command in response and '\n> ' in response:
                if 'Error:' in response or 'ERROR:' in response:
                    raise RuntimeError(f'{command}: {response}')
                return response
            time.sleep(.05)
        raise RuntimeError(f'USB timeout for {command}: {self.snapshot()[start:]}')

    async def command(self, command):
        value = await asyncio.to_thread(self.command_sync, command)
        # Do not publish the framebuffer or unrelated diagnostics as CLI text.
        clean = '\n'.join(line for line in value.splitlines()
                          if not line.startswith('UIHIL pixels='))
        report('usb', command=command, reply=clean)
        return value

    async def reboot(self):
        self.port.write(b'reboot\r\n')
        await asyncio.sleep(7)
        value = await self.command('ver')
        assert 'v1.17.1.8-preview4' in value, value

    def close(self):
        self.stop.set()
        self.reader.join(timeout=1)
        self.output.joinpath('usb.log').write_text(self.snapshot())
        self.port.close()


class Suite:
    def __init__(self, args):
        self.args = args
        self.output = Path(args.output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.usb = USB(args.serial, self.output)
        self.bus = None
        self.addresses = set()
        self.frames = 0

    def path(self, address):
        return '/org/bluez/hci0/dev_' + address.replace(':', '_')

    async def scan(self, expected=None):
        def matches(device, adv):
            return adv.local_name == self.args.name
        device = await BleakScanner.find_device_by_filter(
            matches, timeout=20, bluez={'adapter': 'hci0'})
        assert device is not None, 'Named target advertisement absent'
        address = device.address.upper()
        if expected:
            assert address == expected, (address, expected)
        self.addresses.add(address)
        report('discovery', address=address, name=self.args.name)
        return address

    async def forget(self, address):
        try:
            await props(self.bus, self.path(address))
        except RuntimeError:
            return
        await call(self.bus, '/org/bluez/hci0', 'org.bluez.Adapter1',
                   'RemoveDevice', 'o', [self.path(address)])

    @asynccontextmanager
    async def connect(self, address, fresh=True, expect_oled=False):
        if fresh:
            await self.forget(address)
            assert await BleakScanner.find_device_by_address(address, timeout=15)
        info = await props(self.bus, self.path(address))
        device = BLEDevice(address, info.get('Name'),
                           {'path': self.path(address), 'props': info})
        agent_path = '/org/meshcore/v4_preview4_pairing_agent'
        agent = Agent(self.path(address))
        self.bus.export(agent_path, agent)
        await call(self.bus, '/org/bluez', 'org.bluez.AgentManager1',
                   'RegisterAgent', 'os', [agent_path, 'KeyboardOnly'])
        await call(self.bus, '/org/bluez', 'org.bluez.AgentManager1',
                   'RequestDefaultAgent', 'o', [agent_path])
        start = len(self.usb.snapshot())
        client = BleakClient(device, pair=fresh, timeout=40)
        queue = asyncio.Queue()
        try:
            await client.connect()
            await client._backend._acquire_mtu()
            await client.start_notify(TX, lambda _, data: queue.put_nowait(bytes(data)))
            info = await props(self.bus, self.path(address))
            assert info.get('Paired') and info.get('Bonded'), info
            assert agent.requests == (1 if fresh else 0), agent.requests

            async def request(payload, expected):
                while not queue.empty():
                    queue.get_nowait()
                await client.write_gatt_char(RX, payload, response=True)
                while True:
                    value = await asyncio.wait_for(queue.get(), 10)
                    if value and value[0] == expected:
                        return value
                    assert not value or value[0] != 1, value.hex()

            info = await request(b'\x16\x0e', 13)
            assert b'Heltec' in info[20:60] or b'heltec' in info[20:60], info
            assert b'v1.17.1.8-preview4' in info[60:80], info
            assert await request(b'\x16\x0e' + bytes(174), 13) == info
            stats = await request(b'\x38\x00', 24)
            assert int.from_bytes(stats[8:10], 'little') == 0, stats.hex()
            await asyncio.sleep(2)
            stealth = await request(b'\x42get bluetooth.stealth', 29)
            assert b'bonded-peer-only' in stealth, stealth
            report('protected_ble_session', address=address, fresh=fresh,
                   mtu=client.mtu_size, pin_requests=agent.requests,
                   error_flags=0, stealth=stealth[1:].decode())
            if expect_oled:
                trace = self.usb.snapshot()[start:]
                assert re.search(r'UIHIL .*on=1 pairing=1 ble=0 usb=1', trace), trace
                frames = re.findall(r'UIHIL pixels=([0-9a-f]{2048})', trace)
                assert frames, 'No complete real OLED framebuffer captured'
                for frame in frames:
                    self.frames += 1
                    self.output.joinpath(f'pairing-{self.frames}.oled.bin').write_bytes(bytes.fromhex(frame))
                report('oled_pairing_wake', usb_connected=True, frames=len(frames),
                       pin=PIN, bytes_per_frame=1024)
            yield client
        finally:
            if client.is_connected:
                await client.disconnect()
            await call(self.bus, '/org/bluez', 'org.bluez.AgentManager1',
                       'UnregisterAgent', 'o', [agent_path])
            self.bus.unexport(agent_path)

    async def mode(self, value):
        await self.usb.command('set bluetooth.mac ' + value)
        await self.usb.reboot()
        return await self.scan()

    async def run(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            await asyncio.sleep(7)
            assert 'v1.17.1.8-preview4' in await self.usb.command('ver')
            for command in (f'set pin {PIN}', 'set bluetooth on',
                            'set bluetooth.name ' + self.args.name,
                            'set display.usb.mode button-pairing',
                            'set usb.logging on reboot'):
                await self.usb.command(command)
            await self.usb.reboot()
            assert re.search(r'UIHIL .*startup=3\b', self.usb.snapshot()), 'Saved-key boot must only show Starting/Loading'
            assert 'startup=7' not in self.usb.snapshot() and 'startup=15' not in self.usb.snapshot()
            report('saved_identity_startup', phases=['Starting', 'Loading identity'], generated=False)
            await self.usb.command('set display.usb.mode pairing')
            await self.usb.command('set bluetooth.stealth on')
            address = await self.mode(self.args.custom_address)
            async with self.connect(address, expect_oled=True):
                pass
            async with self.connect(address, fresh=False):
                pass
            await self.usb.reboot()
            async with self.connect(address, fresh=False):
                pass
            report('stealth_bonded_reconnect_and_reboot', address=address)
            first = await self.mode('random')
            await self.usb.reboot()
            await self.scan(first)
            report('saved_random_retained', address=first)
            first = await self.mode('random-after-connect')
            await self.usb.reboot()
            await self.scan(first)
            report('unused_boot_retained', address=first)
            async with self.connect(first, expect_oled=True):
                pass
            assert 'armed for next boot' in await self.usb.command('get bluetooth.mac')
            await self.usb.reboot()
            second = await self.scan()
            assert first != second, (first, second)
            report('authenticated_boot_rotated', before=first, after=second, stealth=True)
            first = await self.mode('random-every-boot')
            await self.usb.reboot()
            second = await self.scan()
            assert first != second, (first, second)
            report('every_boot_rotated', before=first, after=second, stealth=True)
            keys = set(re.findall(r'UIHIL .*key=([0-9A-Fa-f]{64})', self.usb.snapshot()))
            assert len(keys) == 1, ('Public identity changed during test', keys)
            report('suite_passed', addresses=len(self.addresses), oled_frames=self.frames,
                   identity_preserved=True)
        finally:
            for address in self.addresses:
                try:
                    await self.forget(address)
                except Exception as exc:
                    report('cleanup_warning', address=address, error=str(exc))
            self.usb.close()
            self.bus.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--name', default='HIL-V4-preview4')
    parser.add_argument('--custom-address', default='DE:04:26:10:02:01', type=str.upper)
    parser.add_argument('--inspect', action='store_true', help='Read-only pre/post-flash identity and settings snapshot')
    parser.add_argument('--allow-settings-changes', action='store_true')
    args = parser.parse_args()
    assert '44:1B:F6:69:CF:98' in args.serial, 'Unexpected USB serial identity'
    assert re.fullmatch(r'[A-Za-z0-9_-]{1,24}', args.name), 'Invalid diagnostic name'
    assert re.fullmatch(r'[C-F][0-9A-F](?::[0-9A-F]{2}){5}', args.custom_address), 'Not a random-static address'
    if args.inspect:
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        usb = USB(args.serial, output)
        try:
            snapshot = {command: usb.command_sync(command) for command in (
                'ver', 'board', 'get bluetooth',
                'get bluetooth.mac', 'get bluetooth.stealth', 'get bluetooth.name',
                'get display.usb.mode', 'get usb.logging')}
            output.joinpath('snapshot.json').write_text(json.dumps(snapshot, indent=2))
            report('snapshot', **snapshot)
        finally:
            usb.close()
    else:
        assert args.allow_settings_changes, 'Full-flash backup and --allow-settings-changes required'
        asyncio.run(Suite(args).run())
