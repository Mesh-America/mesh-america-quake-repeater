#!/usr/bin/env python3
"""Run the real ESP32 self-metadata accessor against host-only partition stubs."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def method(text, signature):
    """Extract a real method, as in test_t096_full_memory, without ESP-IDF headers."""
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


HARNESS = r'''
#include <helpers/ota/FirmwareInfo.h>
#include <helpers/ota/OtaByteIO.h>
#include <cassert>
#include <cstring>
#include <iostream>
#include <vector>

struct esp_partition_t { uint32_t address; uint32_t size; };
static esp_partition_t running = {0x10000, 0x400000};
static bool present = true;
static std::vector<uint8_t> flash;
static unsigned reads = 0;
static uint64_t bytes_read = 0;
static unsigned fail_call = 0;
static bool fail_trailer = false;
static bool corrupt_trailer_read = false;
constexpr int ESP_OK = 0;

const esp_partition_t* esp_ota_get_running_partition() {
  return present ? &running : nullptr;
}
int esp_partition_read(const esp_partition_t* p, uint32_t off, void* dst, uint32_t len) {
  ++reads;
  if (reads == fail_call || (fail_trailer && len == mesh::ota::ENDF_LEN)) return -1;
  assert(p == &running && uint64_t(off) + len <= p->size);
  assert(uint64_t(off) + len <= flash.size());
  memcpy(dst, flash.data() + off, len);
  if (corrupt_trailer_read && len == mesh::ota::ENDF_LEN) static_cast<uint8_t*>(dst)[0] = '?';
  bytes_read += len;
  return ESP_OK;
}

namespace mesh { namespace ota {
@ACCESSOR@
} }
using namespace mesh::ota;

static void image(uint32_t body, uint8_t tag) {
  assert(uint64_t(body) + ENDF_LEN <= running.size);
  flash.assign(running.size, 0xA5);
  uint8_t* trailer = flash.data() + body;
  memcpy(trailer, ENDF_MAGIC, 4);
  wr_u32le(trailer + 4, body);
  memset(trailer + 8, tag, 8);
  wr_u32le(trailer + 16, 0x01110100u + tag);
  wr_u32le(trailer + 20, 0xA0000000u + tag);
  memset(trailer + 24, 'A' + tag, 32);
}
static void expect_info(const SelfFwInfo& info, uint32_t body, uint8_t tag) {
  assert(info.valid && info.body_len == body && info.endf_offset == body);
  assert(info.image_len == body + ENDF_LEN);
  for (uint8_t value : info.body_hash) assert(value == tag);
  assert(info.fw_version == 0x01110100u + tag && info.target_id == 0xA0000000u + tag);
  for (unsigned i = 0; i < 32; ++i) assert(info.hw_id[i] == 'A' + tag);
  assert(info.hw_id[32] == 0);
}
static void expect_empty(const SelfFwInfo& info) {
  assert(!info.valid && !info.body_len && !info.image_len && !info.endf_offset);
  assert(!info.fw_version && !info.target_id);
  for (uint8_t value : info.body_hash) assert(value == 0);
  for (char value : info.hw_id) assert(value == 0);
}
static void invalidate() {
  present = false;
  SelfFwInfo out;
  assert(!ota_self_firmware(out));
  expect_empty(out);
  present = true;
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string which = argv[1];
  SelfFwInfo out;
  if (which == "production") {
    // 812 logical 2-KiB OTA blocks, like the current full V4 image.
    constexpr uint32_t body = 1661216;
    image(body, 1);
    assert(ota_self_firmware(out));
    expect_info(out, body, 1);
    assert(reads >= 3244 && reads <= 3250);
    const unsigned initial_reads = reads;
    const uint64_t initial_bytes = bytes_read;
    for (unsigned i = 0; i < 50; ++i) {
      out = SelfFwInfo();
      assert(ota_self_firmware(out));
      expect_info(out, body, 1);
    }
    assert(reads == initial_reads && bytes_read == initial_bytes);
    std::cout << initial_reads << " partition reads, " << initial_bytes
              << " bytes on first scan; zero extra reads for 50 cached calls\n";
  } else if (which == "address") {
    image(4096, 1);
    assert(ota_self_firmware(out));
    const unsigned first = reads;
    running.address = 0x410000;
    image(8192, 2);
    assert(ota_self_firmware(out));
    expect_info(out, 8192, 2);
    assert(reads > first);
    const unsigned second = reads;
    running.address = 0x10000;
    image(1024, 3);
    assert(ota_self_firmware(out));
    expect_info(out, 1024, 3);
    assert(reads > second);
  } else if (which == "size") {
    image(4096, 1);
    assert(ota_self_firmware(out));
    const unsigned first = reads;
    running.size = 0x200000;
    image(1024, 2);
    assert(ota_self_firmware(out));
    expect_info(out, 1024, 2);
    assert(reads > first);
    running.size = ENDF_LEN - 1;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    running.size = 0x200000;
    image(512, 3);
    assert(ota_self_firmware(out));
    expect_info(out, 512, 3);
  } else if (which == "null") {
    image(4096, 1);
    assert(ota_self_firmware(out));
    const unsigned first = reads;
    present = false;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    assert(reads == first);
    present = true;
    image(1024, 2);
    assert(ota_self_firmware(out));
    expect_info(out, 1024, 2);
    assert(reads > first);
  } else if (which == "read_failure") {
    image(4096, 1);
    fail_call = 1;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    fail_call = 0;
    assert(ota_self_firmware(out));
    expect_info(out, 4096, 1);
    const unsigned complete = reads;
    assert(ota_self_firmware(out) && reads == complete);
  } else if (which == "trailer_failure") {
    image(4096, 1);
    fail_trailer = true;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    const unsigned first = reads;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    assert(reads == first * 2);
    fail_trailer = false;
    assert(ota_self_firmware(out));
    expect_info(out, 4096, 1);
    const unsigned complete = reads;
    assert(ota_self_firmware(out) && reads == complete);
  } else if (which == "invalid") {
    running.size = 8192;
    image(4096, 1);
    wr_u32le(flash.data() + 4096 + 4, 4095); // Marker with the wrong absolute body length.
    assert(!ota_self_firmware(out));
    expect_empty(out);
    const unsigned first = reads;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    assert(reads == first * 2);
    image(4096, 2);
    assert(ota_self_firmware(out));
    expect_info(out, 4096, 2);
    invalidate();
    flash.assign(running.size, 0xA5); // No trailer at all remains retryable.
    assert(!ota_self_firmware(out));
    expect_empty(out);
    image(1024, 3);
    assert(ota_self_firmware(out));
    expect_info(out, 1024, 3);
  } else if (which == "reread_mismatch") {
    image(4096, 1);
    corrupt_trailer_read = true;
    assert(!ota_self_firmware(out));
    expect_empty(out);
    const unsigned first = reads;
    corrupt_trailer_read = false;
    assert(ota_self_firmware(out));
    expect_info(out, 4096, 1);
    assert(reads > first);
  } else if (which == "edges") {
    // Exercise the overlap/chunk boundary and trailer ending at the partition boundary.
    for (uint32_t body : {0u, 1u, 511u, 512u, 513u, 1023u, 4095u, 4096u}) {
      invalidate();
      running.size = body + ENDF_LEN;
      image(body, 1);
      assert(ota_self_firmware(out));
      expect_info(out, body, 1);
      const unsigned complete = reads;
      assert(ota_self_firmware(out) && reads == complete);
    }
  } else {
    assert(false && "unknown test case");
  }
}
'''


class OtaSelfMetadataCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="meshcore-self-metadata-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = Path(cls.temp.name) / ("self_metadata.exe" if os.name == "nt" else "self_metadata")
        accessor = method((ROOT / "src/helpers/ota/OtaSelf.cpp").read_text(encoding="utf-8"),
                          "bool ota_self_firmware(SelfFwInfo& out)")
        source = HARNESS.replace("@ACCESSOR@", accessor)
        built = subprocess.run(["c++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                                "-I", str(ROOT / "src"), "-x", "c++", "-", "-o", str(cls.binary)],
                               input=source, text=True, capture_output=True)
        if built.returncode:
            raise AssertionError(built.stderr)

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_production_sized_image_is_scanned_once(self):
        self.assertIn("zero extra reads for 50 cached calls", self.run_case("production"))

    def test_a_b_partition_address_changes_require_a_new_scan(self):
        self.run_case("address")

    def test_partition_size_change_and_shrink_invalidate_cache(self):
        self.run_case("size")

    def test_null_partition_clears_out_and_previous_success(self):
        self.run_case("null")

    def test_initial_read_failure_is_retryable(self):
        self.run_case("read_failure")

    def test_whole_trailer_read_failure_never_publishes_partial_info(self):
        self.run_case("trailer_failure")

    def test_invalid_or_missing_trailers_are_not_cached(self):
        self.run_case("invalid")

    def test_whole_trailer_reread_mismatch_is_not_cached(self):
        self.run_case("reread_mismatch")

    def test_chunk_overlap_and_partition_boundary(self):
        self.run_case("edges")


if __name__ == "__main__":
    unittest.main()
