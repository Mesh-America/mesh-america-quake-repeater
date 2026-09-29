"""Read cached manufacturer artifacts for the optional, hash-pinned audit.

No network access or device writes. Normalize only the declared bootloader
window; application/SoftDevice bytes in a combined image are never searched.
"""
import io
import json
import struct
import zipfile


def bootloader_image(raw, record):
    start = int(record["start"], 0)
    image = bytearray(b"\xff" * record["size"])
    end = start + len(image)
    written = {}

    def put(address, data):
        for pos, value in enumerate(data, address):
            if start <= pos < end:
                if pos in written and written[pos] != value:
                    raise ValueError("conflicting flash bytes")
                written[pos] = value
                image[pos - start] = value

    if record.get("member"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            raw = archive.read(record["member"])
    kind = record["format"]
    if kind == "hex":
        base = 0
        eof = False
        for line in raw.decode("ascii").splitlines():
            if not line:
                continue
            if eof or not line.startswith(":"):
                raise ValueError("invalid Intel HEX record")
            data = bytes.fromhex(line[1:])
            if len(data) < 5 or len(data) != data[0] + 5 or sum(data) & 0xff:
                raise ValueError("Intel HEX length/checksum")
            address = int.from_bytes(data[1:3], "big")
            payload, record_type = data[4:-1], data[3]
            if record_type == 0:
                put(base + address, payload)
            elif record_type in (2, 4):
                if len(payload) != 2 or address != 0:
                    raise ValueError("invalid Intel HEX extended address")
                base = int.from_bytes(payload, "big") << (4 if record_type == 2 else 16)
            elif record_type == 1:
                if payload or address != 0:
                    raise ValueError("invalid Intel HEX EOF")
                eof = True
            elif record_type not in (3, 5):
                raise ValueError("unknown Intel HEX record type")
        if not eof:
            raise ValueError("missing Intel HEX EOF")
    elif kind == "uf2":
        if not raw or len(raw) % 512:
            raise ValueError("invalid UF2 length")
        for offset in range(0, len(raw), 512):
            block = raw[offset:offset + 512]
            magic0, magic1, flags, address, length = struct.unpack_from("<IIIII", block)
            if (magic0, magic1) != (0x0a324655, 0x9e5d5157) or \
                    struct.unpack_from("<I", block, 508)[0] != 0x0ab16f30 or length > 476:
                raise ValueError("invalid UF2 block")
            if not flags & 1:  # NOT_MAIN_FLASH blocks aren't executable flash
                put(address, block[32:32 + length])
    elif kind == "dfu":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))["manifest"]
            part = manifest["softdevice_bootloader"]
            data = archive.read(part["bin_file"])
            sd_size, bl_size = part["sd_size"], part["bl_size"]
            if sd_size + bl_size != len(data) or bl_size > len(image):
                raise ValueError("DFU bootloader length mismatch")
            put(start, data[sd_size:])
    else:
        raise ValueError("unknown artifact format: " + kind)
    return bytes(image)
