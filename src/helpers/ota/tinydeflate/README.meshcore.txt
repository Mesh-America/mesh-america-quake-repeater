Compact bounded device raw-DEFLATE encoder
=========================================

Derived from https://github.com/pfalcon/uzlib
Revision: 6d60d651a4499a64f2e5b21b4cc08d98cb84b5c1
Original files: src/genlz77.c, src/defl_static.c

Only the greedy single-probe LZ77/fixed-Huffman encoder is integrated. The
existing strict tinf decoder is reused; no second decoder, zlib/gzip wrapper,
checksum, or dynamic-Huffman implementation is added. The compressor is
compiled as C through ../OtaTinf.c with the existing local size optimization.

MeshCore modifications are marked in deflate.c. Hash buckets hold 16-bit
offsets+1 into the current <=2048-byte input instead of pointers. 512 buckets
need 1024 bytes, calloc'ed for one call then freed (OOM falls back to raw).
Hash bits may be 7..10; any override is also counted by the runtime RAM gate.
There is no persistent dictionary, no shared mutable state, and no input copy.
Output uses the caller's disjoint proof scratch, bounded at every byte write;
overflow/incompressible blocks return failure and the untouched raw input is
sent instead. The state is small on the stack (24 bytes on 32-bit targets),
with no recursion. Match searches stop at 258 bytes; all tail reads are bounded.
Repeated/reordered blocks produce identical bytes, independent of addresses.

Only eligible non-seeder ESP32/external-storage nRF52 targets compile the
encoder. Runtime qualification also gates adaptive RAK boards. Host supplied
precompressed blocks retain priority, and source-only Companions/internal-only
nRF52 receivers retain their existing decoder and raw path without this code.

The original Zlib and PuTTY MIT-compatible licenses are preserved in LICENSE
and the source notices. Modified source is not represented as upstream.
