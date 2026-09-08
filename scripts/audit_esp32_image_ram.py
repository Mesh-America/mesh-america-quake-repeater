#!/usr/bin/env python3
"""Read an older ESP image's allocator tables using a matching SDK ELF layout.

For release audits when the original ELF was not retained. The immutable region
and capability tables must match the reference ELF exactly (only relocated type
name pointers differ). Reservations are read from the image being audited, never
copied from the reference. New builds always use check_firmware_ram.py directly.
"""

from pathlib import Path
import re
import struct

from firmware_elf import FirmwareElf
from check_firmware_ram import esp32_heap_regions, subtract_regions

CHIPS = {0: "esp32", 5: "esp32c3", 9: "esp32s3", 13: "esp32c6"}
MEMORY_WINDOWS = {
    "esp32": [(0x3F800000, 0x40000000), (0x40070000, 0x400A0000), (0x50000000, 0x50002000)],
    "esp32s3": [(0x3C000000, 0x3E000000), (0x3FC80000, 0x3FD00000),
                (0x40370000, 0x403E0000), (0x600FE000, 0x60100000)],
    "esp32c3": [(0x3FC80000, 0x3FCE0000), (0x40380000, 0x403E0000), (0x50000000, 0x50002000)],
    "esp32c6": [(0x40800000, 0x40880000), (0x50000000, 0x50004000)],
}


class EspImage:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if len(self.data) < 24 or self.data[0] != 0xE9 or not 1 <= self.data[1] <= 16:
            raise ValueError("expected an unmerged ESP application image")
        self.mcu = CHIPS.get(struct.unpack_from("<H", self.data, 12)[0])
        if self.mcu is None:
            raise ValueError("unsupported ESP image chip ID")
        self.segments = []
        offset = 24
        for _ in range(self.data[1]):
            if offset + 8 > len(self.data):
                raise ValueError("truncated ESP segment header")
            address, size = struct.unpack_from("<2I", self.data, offset)
            offset += 8
            if offset + size > len(self.data) or address + size > 0x100000000:
                raise ValueError("truncated ESP segment")
            if address and size:
                self.segments.append((address, self.data[offset:offset + size]))
            offset += size
        self.symbols = {}

    def read(self, address, size):
        for start, data in self.segments:
            if start <= address and address + size <= start + len(data):
                return data[address - start:address - start + size]
        raise ValueError(f"ESP image has no initialized data at {address:#x}")

    def address(self, name):
        return self.symbols[name][0]

    def words(self, name, count=1):
        if name == "soc_memory_region_count":
            return (self.region_count,)
        return struct.unpack("<" + "I" * count, self.read(self.address(name), count * 4))

    def find_unique(self, pattern):
        matches = [start + match.start() for start, data in self.segments
                   for match in re.finditer(pattern, data, re.DOTALL)]
        if len(matches) != 1:
            raise ValueError(f"allocator signature matched {len(matches)} times; matching ELF/rebuild required")
        return matches[0]

    def load_layout(self, reference):
        self.region_count = reference.words("soc_memory_region_count")[0]
        regions_size = reference.symbols["soc_memory_regions"][1]
        regions = reference.read(reference.address("soc_memory_regions"), regions_size)
        address = self.find_unique(re.escape(regions))
        self.symbols["soc_memory_regions"] = (address, regions_size, 1)
        region_stride = regions_size // self.region_count
        type_stride = {16: 20, 20: 16}.get(region_stride)
        if type_stride is None:
            raise ValueError("unsupported allocator ABI")
        types_size = reference.symbols["soc_memory_types"][1]
        types = reference.read(reference.address("soc_memory_types"), types_size)
        pattern = b"".join(b".{4}" + re.escape(types[i + 4:i + type_stride])
                           for i in range(0, types_size, type_stride))
        address = self.find_unique(pattern)
        self.symbols["soc_memory_types"] = (address, types_size, 1)
        # First reservation is the fixed RTC noinit guard in these pinned SDKs.
        # Its unique bytes locate the linked reservation section even on RISC-V,
        # where exception/unwind data follows it in the same image segment.
        prefix = reference.read(reference.address("soc_reserved_memory_region_start"), 8)
        start = self.find_unique(re.escape(prefix))
        end = start
        while end - start < 1024:
            try:
                lower, upper = struct.unpack("<2I", self.read(end, 8))
            except ValueError:
                break
            if not any(a <= lower <= upper <= b for a, b in MEMORY_WINDOWS[self.mcu]):
                break
            end += 8
        if end - start < 24 or end - start >= 1024:
            raise ValueError("invalid allocator reservation section")
        self.symbols["soc_reserved_memory_region_start"] = (start, 0, 1)
        self.symbols["soc_reserved_memory_region_end"] = (end, 0, 1)
        # These reservations must cover every initialized internal RAM segment.
        # This catches a partial/incorrectly located reservation section.
        reserved = list(struct.iter_unpack("<2I", self.read(start, end - start)))
        for address, data in self.segments:
            dram_window = {"esp32": (0x3FFAE000, 0x40000000),
                           "esp32s3": (0x3FC80000, 0x3FD00000),
                           "esp32c3": (0x3FC80000, 0x3FCE0000),
                           "esp32c6": (0x40800000, 0x40880000)}[self.mcu]
            internal = dram_window[0] <= address < dram_window[1]
            external = (self.mcu == "esp32" and 0x3F800000 <= address < 0x3FC00000
                        or self.mcu == "esp32s3" and 0x3D000000 <= address < 0x3E000000)
            if internal and not external and subtract_regions([(address, address + len(data), 0)], [(a, b + 16) for a, b in reserved]):
                raise ValueError(f"reservation section does not cover loaded RAM at {address:#x}")


def image_heap_regions(image_path, reference_elf):
    image = EspImage(image_path)
    image.load_layout(FirmwareElf(reference_elf))
    return image.mcu, esp32_heap_regions(image, image.mcu)
