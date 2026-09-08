"""Small, dependency-free reader for the 32-bit little-endian firmware ELFs."""

from pathlib import Path
import struct


class FirmwareElf:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.data[:7] != b"\x7fELF\x01\x01\x01" or len(self.data) < 52:
            raise ValueError("expected a 32-bit little-endian firmware ELF")
        offset = self.unpack("I", 32)[0]
        entry_size, count, names_index = self.unpack("HHH", 46)
        if entry_size != 40 or not count or names_index >= count:
            raise ValueError("missing or invalid ELF section table")
        self.sections = [self.unpack("10I", offset + i * entry_size) for i in range(count)]
        self.symbols = {}
        for section in self.sections:
            if section[1] != 2:  # SHT_SYMTAB
                continue
            if section[9] != 16 or section[5] % 16 or section[6] >= count:
                raise ValueError("invalid ELF symbol table")
            strings = self.section_bytes(self.sections[section[6]])
            for pos in range(section[4], section[4] + section[5], 16):
                name, value, size, info, _, index = self.unpack("IIIBBH", pos)
                if not index or not name:
                    continue
                if name >= len(strings):
                    raise ValueError("invalid ELF symbol name")
                name = strings[name:].split(b"\0", 1)[0].decode("ascii")
                # Prefer global/weak definitions to same-named local symbols.
                if name not in self.symbols or info >> 4:
                    self.symbols[name] = (value, size, index)
        if not self.symbols:
            raise ValueError("firmware ELF has no defined symbols")

    def unpack(self, fmt, offset):
        try:
            return struct.unpack_from("<" + fmt, self.data, offset)
        except struct.error as error:
            raise ValueError("truncated firmware ELF") from error

    def section_bytes(self, section):
        offset, size = section[4:6]
        if offset + size > len(self.data):
            raise ValueError("truncated ELF section")
        return self.data[offset:offset + size]

    def address(self, name):
        if name not in self.symbols:
            raise ValueError(f"missing ELF symbol {name}")
        return self.symbols[name][0]

    def read(self, address, size):
        for section in self.sections:
            if section[1] == 8 or not section[2] & 2:  # NOBITS / not allocated
                continue
            start, length = section[3], section[5]
            if start <= address and address + size <= start + length:
                offset = address - start
                return self.section_bytes(section)[offset:offset + size]
        raise ValueError(f"ELF has no initialized data at {address:#x} ({size} bytes)")

    def words(self, name, count=1):
        return struct.unpack("<" + "I" * count, self.read(self.address(name), count * 4))
