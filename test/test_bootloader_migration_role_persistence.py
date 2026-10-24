"""Exercise embedded migration gates against the roles' normal ACL saves."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from cpp_source import body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <cassert>
#include <cstdint>
#include <type_traits>
#include "helpers/LazyPersistence.h"
#define LAZY_CONTACTS_WRITE_DELAY 5000
#define MESH_DEBUG_PRINTLN(...) ((void)0)
static uint32_t now = 70000;
static bool millisHasNowPassed(unsigned long deadline) {
  return int32_t(now - uint32_t(deadline)) > 0;
}
static unsigned long futureMillis(uint32_t delay) { return uint32_t(now + delay); }
struct Base { virtual bool prepareForOtaReboot() { return true; } };
struct Role : Base {
  using MyMesh = Role;
  unsigned long dirty_contacts_expiry = 75000;
  uint8_t contacts_save_failures = 0;
  static bool saveFilter(int*) { return true; }
  void* _fs = nullptr;
  struct Acl {
    bool succeeds = false;
    unsigned saves = 0;
    bool save(void*, bool (*)(int*) = nullptr) { saves++; return succeeds; }
  } acl;
  @GATE@
  void servicePersistence() {
    @SAVE@
  }
};
int main() {
  Role role;
#ifdef OTA_BOOTLOADER_MIGRATION
  static_assert(std::is_same<decltype(&Role::prepareForOtaReboot), bool (Role::*)()>::value,
                "embedded role must override the reboot gate");
  assert(!role.prepareForOtaReboot());
  role.servicePersistence();
  assert(role.acl.saves == 0 && !role.prepareForOtaReboot());
  now = 75001;
  role.servicePersistence();
  assert(role.acl.saves == 1 && role.contacts_save_failures == 1);
  assert(!role.prepareForOtaReboot());
  // Repeated migration polls must not bypass the failed save's backoff.
  now = 80000;
  for (unsigned poll = 0; poll < 100; poll++) {
    assert(!role.prepareForOtaReboot());
    role.servicePersistence();
  }
  assert(role.acl.saves == 1);
  role.acl.succeeds = true;
  now = 80002;
  role.servicePersistence();
  assert(role.acl.saves == 2 && role.contacts_save_failures == 0);
  assert(role.dirty_contacts_expiry == 0 && role.prepareForOtaReboot());
#else
  // Ordinary firmware retains the base implementation without an override.
  assert(role.prepareForOtaReboot());
  static_assert(std::is_same<decltype(&Role::prepareForOtaReboot), bool (Base::*)()>::value,
                "ordinary role must retain its base reboot gate");
#endif
}
'''

MESH_SOURCE = r'''
#include <cassert>
namespace ota {
static bool due = false, pending = false;
static unsigned context_polls = 0, ticks = 0;
static bool last_ready = false, last_idle = false;
struct OtaContext {
  bool idle = true;
  bool embeddedBootloaderIdle() const { return idle; }
};
static OtaContext* active = nullptr;
static bool bootloader_migration_service_due() { return due; }
static bool bootloader_migration_pending() { return pending; }
static const OtaContext* ota_context_if_active() { context_polls++; return active; }
static void bootloader_migration_tick(bool ready, bool idle) {
  ticks++; last_ready = ready; last_idle = idle;
}
}
struct Mesh {
  bool radio_busy = false, persistence_ready = false;
  unsigned persistence_checks = 0;
  bool hasPendingRadioWork() const { return radio_busy; }
  bool prepareForOtaReboot() { persistence_checks++; return persistence_ready; }
  void service() { @SERVICE@ }
};
int main() {
  Mesh mesh;
  mesh.service();
  assert(ota::ticks == 0 && ota::context_polls == 0);
  ota::due = true;
  mesh.service();
  // Startup checks work with a released workspace and no persistence flush.
  assert(ota::ticks == 1 && ota::context_polls == 1);
  assert(ota::last_ready && ota::last_idle && mesh.persistence_checks == 0);
  ota::pending = true;
  mesh.service();
  assert(!ota::last_ready && ota::last_idle && mesh.persistence_checks == 1);
  mesh.persistence_ready = true;
  mesh.service();
  assert(ota::last_ready && ota::last_idle && mesh.persistence_checks == 2);
  mesh.radio_busy = true;
  mesh.service();
  assert(!ota::last_ready && ota::last_idle && mesh.persistence_checks == 2);
  mesh.radio_busy = false;
  ota::OtaContext context;
  context.idle = false;
  ota::active = &context;
  mesh.service();
  assert(!ota::last_ready && !ota::last_idle && mesh.persistence_checks == 2);
  ota::pending = false;
  context.idle = true;
  mesh.service();
  assert(ota::last_ready && ota::last_idle && mesh.persistence_checks == 2);
}
'''


class BootloaderMigrationRolePersistenceTest(unittest.TestCase):
    def test_mesh_services_startup_checks_without_allocating_an_ota_workspace(self):
        source = (ROOT / "src/Mesh.cpp").read_text(encoding="utf-8")
        maintenance = body(source, "void __attribute__((noinline)) Mesh::serviceLoopMaintenance()")
        service = body(maintenance, "if (ota::bootloader_migration_service_due())")
        dynamic_context = maintenance.index("#if OTA_DYNAMIC_CONTEXT")
        self.assertLess(maintenance.index(service) + len(service), dynamic_context)
        released = body(maintenance[dynamic_context:], "if (!ota::ota_context_if_active())")
        self.assertIn("return;", released)
        # Allocating ota_ctx() merely to poll would defeat dynamic-context RAM savings.
        self.assertNotRegex(service, r"\bota_ctx\s*\(")
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        sanitize = [] if os.name == "nt" else [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        with tempfile.TemporaryDirectory(prefix="migration-mesh-service-") as directory:
            unit = Path(directory) / "service.cpp"
            binary = Path(directory) / ("service.exe" if os.name == "nt" else "service")
            unit.write_text(MESH_SOURCE.replace("@SERVICE@", service), encoding="ascii")
            built = subprocess.run([
                compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                *sanitize, str(unit), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)

    def test_repeater_and_room_wait_for_the_normal_acl_save(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        sanitize = [] if os.name == "nt" else [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        with tempfile.TemporaryDirectory(prefix="migration-role-persistence-") as directory:
            for role in ("simple_repeater", "simple_room_server"):
                header = (ROOT / "examples" / role / "MyMesh.h").read_text(encoding="utf-8")
                source = (ROOT / "examples" / role / "MyMesh.cpp").read_text(encoding="utf-8")
                gate = re.search(
                    r"#if defined\(OTA_BOOTLOADER_MIGRATION\)\n"
                    r"\s*bool prepareForOtaReboot\(\) override \{.*?\n\s*\}\n#endif",
                    header, re.DOTALL)
                self.assertIsNotNone(gate, role)
                save = body(source, "if (dirty_contacts_expiry && millisHasNowPassed(dirty_contacts_expiry))")
                generated = SOURCE.replace("@GATE@", gate.group()).replace("@SAVE@", save)
                for embedded in (False, True):
                    with self.subTest(role=role, embedded=embedded):
                        unit = Path(directory) / (role + ".cpp")
                        binary = Path(directory) / (role + (".exe" if os.name == "nt" else ""))
                        unit.write_text(generated, encoding="ascii")
                        built = subprocess.run([
                            compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-function", *sanitize,
                            *(["-DOTA_BOOTLOADER_MIGRATION=1"] if embedded else []),
                            "-I", str(ROOT / "src"), str(unit), "-o", str(binary),
                        ], capture_output=True, text=True, timeout=60)
                        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                        tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)


if __name__ == "__main__":
    unittest.main()
