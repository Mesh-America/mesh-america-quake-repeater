#!/usr/bin/env python3
"""Run production ESP contact transactions with inline paths, including PSRAM."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_t096_full_memory import method

ROOT = Path(__file__).resolve().parents[1]


class UncachedESPContactsTest(unittest.TestCase):
    def test_actual_psram_cache_policy_and_cooperative_durability(self):
        self.run_fixture(["-DBOARD_HAS_PSRAM=1"])

    def test_explicit_uncached_qualification_configuration(self):
        self.run_fixture(["-DMESH_CONTACT_CACHE=0"])

    def run_fixture(self, policy):
        with tempfile.TemporaryDirectory(prefix="mesh-esp-inline-contacts-") as directory:
            temp = Path(directory)
            source = (ROOT / "examples/companion_radio/DataStore.cpp").read_text()
            header = (ROOT / "examples/companion_radio/DataStore.h").read_text()
            start = header.index("  mesh::ContactFileTransaction* _contact_write")
            end = header.index("\n#endif", start)
            (temp / "contact_write_state_under_test.h").write_text(header[start:end])
            signatures = (
                "static bool serializeContactRecord(",
                "static bool deserializeContactRecord(",
                "DataStore::~DataStore()",
                "void DataStore::cancelContactWrite(",
                "bool DataStore::serviceContactWrite(",
                "bool DataStore::markContactDirty(",
                "bool DataStore::releaseContact(",
                "bool DataStore::serviceContactWrites(",
                "bool DataStore::saveContacts(",
                "bool DataStore::flushContactWrites(",
                "bool DataStore::hasPendingContactWrites() const",
                "bool DataStore::hasIncompleteContactLoad() const",
                "void DataStore::loadContacts(",
                "inline void makeBlobPath(",
            )
            implementation = "\n".join(method(source, signature) for signature in signatures)
            # Only the native SDK stat seam is substituted. The production
            # presence logic still distinguishes ENOENT from metadata failure.
            presence = method(source, "static bool companionPathPresence(")
            presence = presence.replace("::stat(vfs_path, &info)",
                                        "fixtureStat(fs, vfs_path, &info)")
            (temp / "presence_under_test.h").write_text(presence)
            # NRF/STM and ESP implementations have the same public signature.
            delete_start = source.rindex("bool DataStore::deleteBlobByKey(")
            implementation += "\n" + method(source[delete_start:],
                                            "bool DataStore::deleteBlobByKey(")
            utils = (ROOT / "src/Utils.cpp").read_text()
            implementation += "\nnamespace mesh {\n"
            implementation += 'static const char hex_chars[] = "0123456789ABCDEF";\n'
            implementation += method(utils, "void Utils::toHex(") + "\n}\n"
            (temp / "store_under_test.h").write_text(implementation)
            packet = (ROOT / "src/Packet.cpp").read_text()
            (temp / "packet_under_test.h").write_text("namespace mesh {\n" + "\n".join(
                method(packet, signature) for signature in (
                    "bool Packet::isValidPathLen(", "size_t Packet::writePath(",
                    "uint8_t Packet::copyPath("))
                + "\n}\n")
            binary = temp / "test"
            result = subprocess.run([
                "c++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-DESP32_PLATFORM=1", "-DCOMPANION_RADIO_FULL=1", *policy,
                "-I", str(ROOT / "test/fixtures/contact_cache/mocks"),
                "-I", str(ROOT / "test/fixtures/contact_cache"),
                "-I", str(ROOT / "lib/ed25519"), "-I", str(ROOT / "src"),
                "-I", str(temp),
                str(ROOT / "test/fixtures/contact_persistence/test_esp32_uncached.cpp"),
                "-lcrypto", "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
