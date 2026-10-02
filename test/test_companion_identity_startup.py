#!/usr/bin/env python3
"""Execute the actual Companion identity-loading branch and its UI transitions."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

IDENTITY_STUB = r'''
#pragma once
#include <stdint.h>
namespace mesh {
struct Identity { uint8_t pub_key[32] = {}; };
struct LocalIdentity : Identity {};
}
'''

HARNESS = r'''
#include <helpers/IdentityGeneration.h>
#include <cassert>
#include <string>
#include <vector>
#define DISPLAY_CLASS TestDisplay
#define MESH_DEBUG_PRINTLN(...) do {} while (0)
namespace mesh { namespace ui {
struct StartupScreen {
  std::string status;
  std::vector<std::string> phases;
  void set(const char* next) { status = next; phases.push_back(status); }
  void starting() { set("Starting..."); }
  void loadingIdentity() { set("Loading identity"); }
  void generatingKey() { set("Generating key"); }
  void savingIdentity() { set("Saving identity"); }
  static void progress(void*) {}
};
}}
mesh::ui::StartupScreen screen;
struct Board {
  unsigned reboots = 0;
  void reboot() { ++reboots; }
} board;
struct Store {
  bool loaded = true, allowed = true, save_ok = true;
  unsigned saves = 0;
  uint8_t prefix = 0x5a;
  bool loadMainIdentity(mesh::LocalIdentity& identity) {
    assert(screen.status == "Loading identity");
    identity.pub_key[0] = prefix;
    return loaded;
  }
  bool canCreateMainIdentity() const { return allowed; }
  bool saveMainIdentity(const mesh::LocalIdentity&) {
    assert(screen.status == "Saving identity");
    assert(mesh::identityGenerationProgress().callback == nullptr);
    ++saves;
    return save_ok;
  }
} store;
unsigned generated = 0;
bool valid_generated_key = true;
mesh::LocalIdentity radio_new_identity() {
  assert(screen.status == "Generating key");
  ++generated;
  mesh::LocalIdentity identity;
  identity.pub_key[0] = valid_generated_key ? 0x42 : 0xff;
  return identity;
}
mesh::LocalIdentity self_id;
static void bootIdentity() {
  Store* _store = &store;
  mesh::ui::StartupScreen* startup_screen = &screen;
  @IDENTITY_BRANCH@
}
static void reset() {
  screen = {};
  store = {};
  board = {};
  generated = 0;
  valid_generated_key = true;
  self_id = {};
}
int main() {
  reset();
  store.allowed = false; // A valid saved identity never needs creation permission.
  bootIdentity();
  assert(generated == 0 && store.saves == 0 && board.reboots == 0);
  assert(self_id.pub_key[0] == 0x5a);
  assert((screen.phases == std::vector<std::string>{"Loading identity", "Starting..."}));

  reset();
  store.loaded = false;
  bootIdentity();
  assert(generated == 1 && store.saves == 1 && board.reboots == 0);
  assert((screen.phases == std::vector<std::string>{
      "Loading identity", "Generating key", "Saving identity", "Starting..."}));

  reset();
  store.loaded = false;
  store.allowed = false; // Unreadable identity: fail closed, do not replace it.
  bootIdentity();
  assert(generated == 0 && store.saves == 0 && board.reboots == 1);
  assert((screen.phases == std::vector<std::string>{"Loading identity"}));

  reset();
  store.prefix = 0xff; // Existing reserved-prefix policy is unchanged.
  bootIdentity();
  assert(generated == 1 && store.saves == 1 && self_id.pub_key[0] == 0x42);

  reset();
  store.loaded = false;
  store.save_ok = false;
  bootIdentity();
  assert(generated == 1 && store.saves == 1 && board.reboots == 1);
  assert(screen.status == "Starting...");

  reset();
  store.loaded = false;
  valid_generated_key = false;
  bootIdentity();
  assert(generated == mesh::MAX_LOCAL_IDENTITY_GENERATION_ATTEMPTS);
  assert(store.saves == 0 && board.reboots == 1 && screen.status == "Starting...");
  assert(mesh::identityGenerationProgress().callback == nullptr);
}
'''


class CompanionIdentityStartupTests(unittest.TestCase):
    def test_saved_missing_unreadable_and_failed_identity_transitions(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        begin = source.index("void MyMesh::begin(")
        start = source.index("#ifdef DISPLAY_CLASS\n  if (startup_screen != nullptr) startup_screen->loadingIdentity();", begin)
        end = source.index("#if defined(ENABLE_OTA)\n  mesh::ota::ota_refresh_seeder_identity", start)
        program = HARNESS.replace("@IDENTITY_BRANCH@", source[start:end])
        with tempfile.TemporaryDirectory(prefix="mesh-identity-startup-") as temp:
            cpp, binary = Path(temp) / "test.cpp", Path(temp) / "test"
            (Path(temp) / "Identity.h").write_text(IDENTITY_STUB)
            cpp.write_text(program)
            result = subprocess.run([
                "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                "-I", temp, "-I", str(ROOT / "src"), str(cpp), "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
