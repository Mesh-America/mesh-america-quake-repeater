#!/usr/bin/env python3
"""Render reader captures: default GFX headers plus actual adaptive-font pixels."""
import argparse
from pathlib import Path
import re
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("font", type=Path, help="Adafruit GFX Library/glcdfont.c")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.font.read_text(encoding="utf-8")
    source = source[source.index("font[] PROGMEM = {"):].split("};", 1)[0]
    source = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S)
    font = bytes(int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{2})", source))
    assert len(font) == 256 * 5
    frames = []
    for line in args.capture.read_text(encoding="utf-8").splitlines():
        if line.startswith("FRAME "):
            fields = line[6:].split(" ", 2)
            sized = len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit()
            width, height = map(int, fields[:2]) if sized else (128, 64)
            panel = Image.new("RGB", (width, height), "black")
            frames.append((fields[2] if sized else line[6:], panel))
            if not sized:  # Compatibility with the original text-only capture.
                ImageDraw.Draw(panel).line((0, 10, 127, 10), fill="white")
        elif line.startswith("PIXEL "):
            _, x, y = line.split()
            x, y = int(x), int(y)
            assert 0 <= x < width and 0 <= y < height
            panel.putpixel((x, y), (255, 255, 255))
        else:
            x, y, text = line.split("\t", 2)
            x, y = int(x), int(y)
            for char in text:
                for column in range(5):
                    bits = font[ord(char) * 5 + column]
                    for row in range(8):
                        if bits & (1 << row):
                            assert 0 <= x + column < width and 0 <= y + row < height
                            panel.putpixel((x + column, y + row), (255, 255, 255))
                x += 6
    scale = 4
    output = Image.new("RGB", (max(panel.width for _, panel in frames) * scale + 32,
                               sum(panel.height * scale + 48 for _, panel in frames) + 16), "#202733")
    draw = ImageDraw.Draw(output)
    top = 16
    for title, panel in frames:
        draw.text((16, top), title, fill="white")
        output.paste(panel.resize((panel.width * scale, panel.height * scale),
                                 Image.Resampling.NEAREST), (16, top + 24))
        top += panel.height * scale + 48
    output.save(args.output)


if __name__ == "__main__":
    main()
