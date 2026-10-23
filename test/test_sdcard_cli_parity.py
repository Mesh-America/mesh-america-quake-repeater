#!/usr/bin/env python3
"""Compile the shared production SD CLI against stateful storage boundaries."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

ARDUINO = r'''
#pragma once
#include <stdint.h>
extern uint32_t clock_ms;
inline uint32_t millis() { return clock_ms; }
'''
BOARD = '#pragma once\nnamespace mesh { class MainBoard {}; }\n'
CONTEXT = r'''
#pragma once
#include <MeshCore.h>
#include <stdint.h>
#include <stdio.h>
namespace mesh { namespace ota {
inline bool ethernet_owned = false;
inline bool rak4631_ethernet_owns_spi() { return ethernet_owned; }
struct OtaManager {
  enum State { IDLE, FETCHING, COMPLETE };
  State state = IDLE;
  unsigned resets = 0;
  State fetchState() const { return state; }
  void reset_session() { ++resets; state = IDLE; }
  void want(unsigned) {}
  void want_mid(const uint8_t*) {}
};
struct FetchStore {
  bool internal = false, sd = true;
  uint32_t staged = 0;
  bool usesInternal() const { return internal; }
  bool usesSd() const { return sd; }
  uint32_t staged_size() const { return staged; }
};
struct OtaStoreSdNrf52 {
  unsigned formats = 0, erases = 0, spaces = 0, lists = 0;
  uint16_t page = 0;
  bool format_ok = true, erase_ok = true, read_ok = true;
  bool formatCard(MainBoard&) { ++formats; return format_ok; }
  bool eraseCard(MainBoard&) { ++erases; return erase_ok; }
  bool getSpace(MainBoard&, uint64_t& used, uint64_t& free) {
    ++spaces; used = 12; free = 34; return read_ok;
  }
  bool listFiles(MainBoard&, uint16_t p, char* reply, size_t cap) {
    ++lists; page = p; snprintf(reply, cap, "> files page=%u", unsigned(p)); return read_ok;
  }
  const char* last_error() const { return "card unavailable"; }
};
struct OtaContext {
  OtaManager manager;
  FetchStore fetch_store;
  OtaStoreSdNrf52 card;
  bool apply_pending = false;
  uint32_t session_started_ms = 1;
  OtaManager::State prev_fstate = OtaManager::FETCHING;
  unsigned prepares = 0, finishes = 0;
  OtaStoreSdNrf52& sdStagingStore() { return card; }
  void prepareSdCardReset() { ++prepares; }
  void finishSdCardReset(uint32_t) { ++finishes; }
};
inline OtaContext context;
inline bool acquired = false, out_of_memory = false;
inline unsigned acquisitions = 0, accesses = 0;
inline bool ota_acquire_context(char* reply, size_t cap) {
  ++acquisitions;
  if (out_of_memory) { snprintf(reply, cap, "ERR mOTA out of memory"); return false; }
  acquired = true; return true;
}
inline OtaContext& ota_ctx() {
  if (!acquired) __builtin_trap();
  ++accesses; return context;
}
} }
'''
HARNESS = r'''
#include <helpers/SdCardCLI.h>
#include <helpers/ota/OtaContext.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
uint32_t clock_ms = 500000;
int main() {
  using namespace mesh::ota;
  mesh::MainBoard board;
  mesh::cli::SdCardCLIState state;
  struct Reply { char text[160]; char sentinel[8] = "guarded"; } reply{};
  auto command = [&](const char* value) {
    bool handled = mesh::cli::handleSdCardCommand(state, board, value, reply.text, sizeof(reply.text));
    assert(strcmp(reply.sentinel, "guarded") == 0); return handled;
  };
  assert(!command("get sdcardoops"));
  assert(!command("set unrelated"));
  for (const char* value : {"get sdcard", "get sdcard *", "get sdcard format", "get sdcard erase"}) {
    assert(command(value)); assert(strstr(reply.text, "never"));
  }
  for (const char* value : {"get sdcard invalid", "get sdcard ls 0", "get sdcard dir -1",
                            "get sdcard dir 65536", "get sdcard lsoops", "get sdcard dir 2 extra",
                            "set sdcard format unknown"}) {
    assert(command(value)); assert(strncmp(reply.text, "Error:", 6) == 0);
  }
  assert(!acquisitions && !accesses);
#if defined(OTA_RAK15002_SD_STORE)
  ethernet_owned = true;
  for (const char* value : {"get sdcard free", "get sdcard ls", "set sdcard format --force", "set sdcard erase --force"}) {
    assert(command(value)); assert(strstr(reply.text, "Ethernet off"));
    assert(!acquisitions && !accesses && !context.prepares && !context.manager.resets);
  }
  ethernet_owned = false;
#endif
  out_of_memory = true;
  assert(command("get sdcard free")); assert(strstr(reply.text, "out of memory"));
  assert(!accesses && !context.card.spaces);
  out_of_memory = false;
  assert(command("get sdcard free")); assert(strstr(reply.text, "12 B") && strstr(reply.text, "34 B"));
  assert(command("get sdcard dir 65535")); assert(context.card.page == 65535);
  context.card.read_ok = false;
  assert(command("get sdcard free")); assert(strstr(reply.text, "card unavailable"));
  assert(command("get sdcard ls")); assert(strstr(reply.text, "card unavailable"));
  context.card.read_ok = true;
  context.apply_pending = true;
  assert(command("set sdcard format --force"));
  assert(strstr(reply.text, "apply is pending") && !context.prepares && !context.card.formats);
  context.apply_pending = false;
  context.card.format_ok = false;
  assert(command("set sdcard format"));
  assert(strstr(reply.text, "format failed") && context.prepares == 1 && context.finishes == 1);
  assert(!state.format_recorded);
  context.card.format_ok = true;
  assert(command("set sdcard format")); assert(state.format_recorded && state.format_at == clock_ms);
  unsigned formats = context.card.formats;
  assert(command("set sdcard format")); assert(strstr(reply.text, "--force") && context.card.formats == formats);
  assert(command("set sdcard format --force")); assert(context.card.formats == formats + 1);
  context.card.erase_ok = false;
  assert(command("set sdcard erase")); assert(strstr(reply.text, "erase failed"));
  assert(!state.erase_recorded && context.prepares == context.finishes);
  context.card.erase_ok = true; context.card.format_ok = false;
  assert(command("set sdcard erase")); assert(strstr(reply.text, "erased but format failed"));
  assert(state.erase_recorded && context.prepares == context.finishes);
  context.card.format_ok = true;
  assert(command("set sdcard erase --force")); assert(strstr(reply.text, "erase and format complete"));
  // uint32_t wrap must retain the same five-minute cooldown semantics.
  state.format_recorded = true; state.format_at = 0xfffffff0u; clock_ms = 20;
  formats = context.card.formats;
  assert(command("set sdcard format")); assert(context.card.formats == formats);
  clock_ms += 300000;
  assert(command("set sdcard format")); assert(context.card.formats == formats + 1);
  // Short framed replies are always bounded, including failed operations.
  struct Tiny { char text[8]; char sentinel[8] = "guarded"; } tiny{};
  assert(mesh::cli::handleSdCardCommand(state, board, "get sdcard *", tiny.text, sizeof(tiny.text)));
  assert(tiny.text[7] == 0 && strcmp(tiny.sentinel, "guarded") == 0);
  assert(mesh::cli::handleSdCardCommand(state, board, "set sdcard format --force", tiny.text, sizeof(tiny.text)));
  assert(tiny.text[7] == 0 && strcmp(tiny.sentinel, "guarded") == 0);
  assert(mesh::cli::handleSdCardCommand(state, board, "set sdcard erase --force", tiny.text, sizeof(tiny.text)));
  assert(tiny.text[7] == 0 && strcmp(tiny.sentinel, "guarded") == 0);
  assert(!mesh::cli::handleSdCardCommand(state, board, nullptr, reply.text, sizeof(reply.text)));
  assert(!mesh::cli::handleSdCardCommand(state, board, "get sdcard", nullptr, 0));
}
'''


class SdCardCLIParityTests(unittest.TestCase):
    def compile_and_run(self, defines):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('host C++17 compiler required')
        with tempfile.TemporaryDirectory(prefix='sdcard-cli-') as folder:
            work = Path(folder)
            for name, text in {'Arduino.h': ARDUINO, 'MeshCore.h': BOARD,
                               'helpers/ota/OtaContext.h': CONTEXT,
                               'main.cpp': HARNESS}.items():
                path = work / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            sanitizer = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                         '-fno-pie', '-no-pie'] if sys.platform.startswith('linux') else []
            result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                *sanitizer, *['-D' + value for value in ['NRF52_PLATFORM', 'OTA_SD_STORE', *defines]],
                '-I' + str(work), '-I' + str(ROOT / 'src'), str(ROOT / 'src/helpers/SdCardCLI.cpp'),
                str(work / 'main.cpp'), '-o', str(work / 'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(work / 'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_shared_cpp_handles_legacy_sd_and_source_only_profiles(self):
        for defines in ([], ['OTA_SEEDER_ONLY'], ['OTA_TOWER_AUTO_STORE'],
                        ['OTA_RAK15002_SD_STORE', 'OTA_RAK_AUTO_STORE'],
                        ['OTA_RAK15002_SD_STORE', 'OTA_SEEDER_ONLY']):
            with self.subTest(defines=defines):
                self.compile_and_run(defines)

    def test_common_cli_delegates_to_same_implementation(self):
        source = (ROOT / 'src/helpers/CommonCLI.cpp').read_text()
        self.assertIn('handleSdCardSet(_sdcard_cli, *_board, config, reply, 160)', source)
        self.assertIn('handleSdCardGet(_sdcard_cli, *_board, config, reply, 160)', source)
        self.assertNotIn('context.prepareSdCardReset()', source)
        header = (ROOT / 'src/helpers/CommonCLI.h').read_text()
        self.assertIn('mesh::cli::SdCardCLIState _sdcard_cli;', header)


if __name__ == '__main__':
    unittest.main()
