#!/usr/bin/env python3
"""Pack the pinned public-domain source for the offline Reader into DEFLATE blocks."""
import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from zopfli_compress import (  # noqa: E402
    MAXIMUM_ITERATIONS, ZOPFLI_VERSION, raw_deflate_compress,
)

SOURCE = Path(__file__).with_name("reader-web.json")
HEADER = ROOT / "src/helpers/bible/ReaderData.generated.h"
BLOCK_SIZE = 4096
COMPRESSION_ITERATIONS = MAXIMUM_ITERATIONS
TOKEN_WORDS = 128
WORD = re.compile(rb" ?[A-Za-z]+")
ASCII_TYPOGRAPHY = str.maketrans({
    "\u00a0": " ", "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
})
CHAPTER_VERSES = (51, 25, 36, 54, 47, 71, 53, 59, 41, 42, 57,
                  50, 38, 31, 27, 33, 26, 40, 42, 31, 25)


def references():
    return [f"{c}:{v}" for c, count in enumerate(CHAPTER_VERSES, 1)
            for v in range(1, count + 1)]


def checked_text(value, limit):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("expected nonempty trimmed text")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("control/format characters are not allowed in terminal text")
    encoded = value.encode("utf-8")
    if len(encoded) > limit:
        raise ValueError(f"text exceeds {limit} UTF-8 bytes")
    return encoded


def ascii_verse(value, limit):
    # Keep the pinned source exact. Only the generated firmware copy changes
    # typography; never transliterate letters or silently discard characters.
    checked_text(value, limit * 3)
    try:
        encoded = value.translate(ASCII_TYPOGRAPHY).encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("unsupported non-ASCII character in Reader source") from error
    if len(encoded) > limit:
        raise ValueError(f"text exceeds {limit} ASCII bytes")
    return encoded


def source_verses(document, block_size=BLOCK_SIZE):
    checked_text(document["translation"], 24)
    checked_text(document["attribution"], 256)
    verses = document["verses"]
    if not isinstance(verses, dict) or set(verses) != set(references()):
        raise ValueError("source must explicitly include all 879 Reader references")
    return [ascii_verse(verses[ref], block_size - 1) if verses[ref] is not None else b""
            for ref in references()]


def token_dictionary(verses):
    """Choose exact, case-sensitive ASCII words deterministically, including spaces."""
    counts = Counter(match.group() for verse in verses for match in WORD.finditer(verse))
    gain = lambda word: (len(word) - 1) * counts[word] - len(word) - 2
    ordered = sorted(counts, key=lambda word: (gain(word), word), reverse=True)
    words, size = [], 0
    for word in ordered:
        if gain(word) <= 0:
            break
        if size + len(word) > 0xffff:
            continue
        words.append(word)
        size += len(word)
        if len(words) == TOKEN_WORDS:
            break
    return words


def dictionary_storage(words):
    return sum(map(len, words)) + 2 * (len(words) + 1) if words else 0


def token_blocks(document, block_size=BLOCK_SIZE):
    if block_size not in (1024, 2048, 4096):
        raise ValueError("block size must be 1024, 2048, or 4096")
    verses = source_verses(document, block_size)
    words = token_dictionary(verses)
    tokens = {word: bytes([128 + index]) for index, word in enumerate(words)}
    blocks, starts, current = [], [0], bytearray()
    expansion = 0
    for index, verse in enumerate(verses):
        encoded = WORD.sub(lambda match: tokens.get(match.group(), match.group()), verse)
        required = len(verse) + 1 if encoded != verse else 0
        # A very long, mostly unique verse may not fit beside its encoded
        # input. Retain it literally: lookup returns an all-ASCII verse in
        # place and needs no expansion area, preserving the original limit.
        if len(encoded) + 1 + required > block_size:
            encoded, required = verse, 0
        maximum = max(expansion, required)
        if len(current) + len(encoded) + 1 + maximum > block_size:
            blocks.append(bytes(current))
            current.clear()
            starts.append(index)
            expansion = 0
        current.extend(encoded + b"\0")
        expansion = max(expansion, required)
        if len(current) + expansion > block_size:
            raise AssertionError("Reader encoded block and selected output exceed scratch")
    if current:
        blocks.append(bytes(current))
    if not blocks:
        raise ValueError("source contains no verse text")
    return blocks, starts, words


@lru_cache(maxsize=128)
def compress_block(block):
    return raw_deflate_compress(block, numiterations=COMPRESSION_ITERATIONS)


def pack(document, block_size=BLOCK_SIZE, progress=None):
    blocks, starts, _ = token_blocks(document, block_size)
    packed, descriptors = bytearray(), []
    for ordinal, (first_verse, block) in enumerate(zip(starts, blocks), 1):
        compressed = compress_block(block)
        descriptors.append((len(packed), len(compressed), len(block), first_verse))
        packed.extend(compressed)
        if progress:
            progress(ordinal, len(blocks), len(packed))
    return bytes(packed), descriptors


def block_index_layout(blocks):
    """Use aligned halfword offsets when possible, retaining larger corpora."""
    if not blocks or any(not 0 <= block[0] <= 0xFFFFFFFF for block in blocks):
        raise ValueError("Reader block offsets must fit uint32_t")
    return ("uint16_t", 8) if max(block[0] for block in blocks) <= 0xFFFF else ("uint32_t", 12)


def render(document, progress=None):
    packed, blocks = pack(document, progress=progress)
    words = token_dictionary(source_verses(document))
    dictionary = b"".join(words)
    word_offsets, offset = [0], 0
    for word in words:
        offset += len(word)
        word_offsets.append(offset)
    offset_type, index_bytes = block_index_layout(blocks)
    digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
    lines = ["// Generated by tools/bible/pack_reader.py; do not edit.",
             f"// Compressed with Google Zopfli {ZOPFLI_VERSION} ({COMPRESSION_ITERATIONS} iterations).",
             "// Offline Reader corpus. Public domain; see tools/bible/README.md.",
             "// Firmware typography: ASCII quotes, apostrophes, dashes and spaces; wording unchanged.",
             "// Exact word tokens expand only the selected verse in the same 4 KiB scratch.",
             f"// Canonical source SHA-256: {digest}",
             "#pragma once", '#include "ReaderLookup.h"',
             "namespace mesh { namespace bible { namespace generated {",
             f'static_assert(kBlockSize == {BLOCK_SIZE}, "Regenerate Reader data after changing block size");',
             f"using ReaderBlockIndex = BlockIndexT<{offset_type}>;",
             f"using ReaderCorpus = {'TokenCorpusT' if words else 'CorpusT'}<{offset_type}>;",
             f'static_assert(sizeof(ReaderBlockIndex) == {index_bytes}, "Reader flash-size accounting expects a {index_bytes}-byte index");',
             "static const uint8_t readerData[] = {"]
    for start in range(0, len(packed), 20):
        lines.append("  " + ",".join(f"0x{v:02x}" for v in packed[start:start + 20]) + ",")
    lines += ["};", "static const ReaderBlockIndex readerBlocks[] = {"]
    lines += ["  {%d, %d, %d, %d}," % block for block in blocks]
    lines += ["};"]
    if words:
        lines += ["static const uint8_t readerWords[] = {"]
        for start in range(0, len(dictionary), 20):
            lines.append("  " + ",".join(f"0x{v:02x}" for v in dictionary[start:start + 20]) + ",")
        lines += ["};", "static const uint16_t readerWordOffsets[] = {",
                  "  " + ",".join(map(str, word_offsets)), "};"]
    lines += ["static const ReaderCorpus readerCorpus = {",
              f"  {json.dumps(document['translation'], ensure_ascii=False)},",
              f"  {json.dumps(document['attribution'], ensure_ascii=False)},",
              "  readerData, sizeof(readerData), readerBlocks,",
              "  sizeof(readerBlocks) / sizeof(readerBlocks[0]), kVerseCount" + ("," if words else "")]
    if words:
        lines += [f"  readerWords, sizeof(readerWords), readerWordOffsets, {len(words)}"]
    lines += ["};", "}}}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=HEADER)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compare", action="store_true", help="compare 1/2/4 KiB blocks without writing")
    parser.add_argument("--progress", action="store_true", help="report canonical block-compression progress")
    args = parser.parse_args()
    document = json.loads(args.source.read_text(encoding="utf-8"))
    if args.compare:
        for size in (1024, 2048, 4096):
            packed, blocks = pack(document, size)
            tables = len(blocks) * block_index_layout(blocks)[1]
            verses = source_verses(document, size)
            dictionary = dictionary_storage(token_dictionary(verses))
            plain = sum(len(verse) + 1 for verse in verses)
            total = len(packed) + tables + dictionary
            print(f"{size} byte blocks: {len(blocks)} blocks, {plain} plain, "
                  f"{len(packed)} compressed, {tables} index, {dictionary} dictionary, "
                  f"{total} total, {100 * (1 - total / plain):.2f}% saved")
        return
    progress = (lambda done, total, size: print(
        f"Reader block {done}/{total}: {size} compressed bytes", file=sys.stderr, flush=True)
        ) if args.progress else None
    header = render(document, progress=progress)
    if args.check:
        if args.output.read_text(encoding="utf-8") != header:
            raise SystemExit("Reader header differs; regenerate with tools/bible/pack_reader.py")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(header, encoding="utf-8", newline="\n")
    packed, blocks = pack(document)
    verses = source_verses(document)
    plain = sum(len(verse) + 1 for verse in verses)
    tables = len(blocks) * block_index_layout(blocks)[1]
    dictionary = dictionary_storage(token_dictionary(verses))
    print(f"Reader: {len(references())} verses, {len(blocks)} blocks; "
          f"{plain} plain bytes -> {len(packed)} DEFLATE + {tables} index "
          f"+ {dictionary} dictionary bytes "
          f"({100 * (1 - (len(packed) + tables + dictionary) / plain):.1f}% smaller incl. tables)")


if __name__ == "__main__":
    main()
