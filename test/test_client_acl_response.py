#!/usr/bin/env python3
"""Execute legacy ACL replies through the production route and replay guards."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/client_acl_response"

# Unmodified official decoder, meshcore-dev/meshcore_py commit
# 1e6fdd47a36ae32c30246a8486b7a9492665579f, src/meshcore/parsing.py (MIT).
# https://github.com/meshcore-dev/meshcore_py/blob/1e6fdd47a36ae32c30246a8486b7a9492665579f/src/meshcore/parsing.py
def parse_acl(buf):
    i = 0
    res = []
    while i + 7 <= len(buf):
        key = buf[i : i + 6].hex()
        perm = buf[i + 6]
        if key != "000000000000":
            res.append({"key": key, "perm": perm})
        i = i + 7
    return res


def production_acl_methods():
    source = (ROOT / "examples/simple_repeater/MyMesh.cpp").read_text()
    handler = extract_braced(source, "int MyMesh::handleRequest(")
    prefix = handler[:handler.index("  if (payload[0] == REQ_TYPE_GET_STATUS)")]
    acl = extract_braced(handler, "if (payload[0] == REQ_TYPE_GET_ACCESS_LIST)")
    generated = prefix + acl + "\nreturn 0;\n}\n"
    receive = extract_braced(source, "if (type == PAYLOAD_TYPE_REQ) { // request")
    generated += """
    void MyMesh::receive(mesh::Packet* packet, uint8_t* data, size_t len) {
      ClientInfo* client = &sender;
      const uint8_t type = PAYLOAD_TYPE_REQ;
      uint8_t secret[PUB_KEY_SIZE] = {};
    """ + receive + "\n}\n"
    mesh_source = (ROOT / "src/Mesh.cpp").read_text()
    generated += "namespace mesh {\n"
    generated += "#define MAX_COMBINED_PATH (MAX_PACKET_PAYLOAD - 2 - CIPHER_BLOCK_SIZE)\n"
    for signature in (
        "Packet* Mesh::createPathReturn(const Identity& dest,",
        "Packet* Mesh::createPathReturn(const uint8_t* dest_hash,",
        "Packet* Mesh::createDatagram(",
    ):
        generated += extract_braced(mesh_source, signature) + "\n"
    packet_source = (ROOT / "src/Packet.cpp").read_text()
    for signature in ("Packet::Packet()", "bool Packet::isValidPathLen("):
        generated += extract_braced(packet_source, signature) + "\n"
    generated += "}\n"
    return generated


class ClientAclResponseTest(unittest.TestCase):
    def test_production_acl_route_admission_and_replay(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        generated = production_acl_methods()
        with tempfile.TemporaryDirectory(prefix=".tmp-acl-response-", dir=ROOT) as directory:
            work = Path(directory)
            (work / "production.inc").write_text(generated, encoding="ascii")
            binary = work / "acl-response.exe"
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                       f"-I{work}", f"-I{ROOT / 'src'}",
                       str(FIXTURE / "test_client_acl_response.cpp"), "-o", str(binary)]
            if sys.platform.startswith("linux"):
                command[1:1] = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                                "-fno-pie", "-no-pie"]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("ACL route and replay checks passed", checked.stdout)
            decoded = 0
            for line in checked.stdout.splitlines():
                if not line.startswith("LEGACY:"):
                    continue
                _, expected, body = line.split(":")
                result = parse_acl(bytes.fromhex(body))
                self.assertEqual(len(result), int(expected))
                self.assertTrue(all(entry["perm"] == 3 for entry in result))
                decoded += 1
            self.assertGreaterEqual(decoded, 10)

    def test_admission_result_and_default_capacity_wiring(self):
        source = (ROOT / "examples/simple_repeater/MyMesh.cpp").read_text()
        header = (ROOT / "examples/simple_repeater/MyMesh.h").read_text()
        wrapper = extract_braced(source, "bool MyMesh::sendClientReply(")
        self.assertIn("return sendClientReplyWithFallbackScope(", wrapper)
        self.assertIn("bool sendClientReply(", header)
        self.assertIn("size_t reply_capacity = MAX_PACKET_PAYLOAD - CIPHER_MAC_SIZE - (CIPHER_BLOCK_SIZE - 1)", header)
        self.assertIn("if (len < 5) return;", source)

    def test_same_clock_generates_login_and_binary_request_tags(self):
        source = (ROOT / "src/helpers/BaseChatMesh.cpp").read_text()
        for signature in ("int BaseChatMesh::sendLogin(",
                          "bool BaseChatMesh::allocateRequestTag("):
            body = extract_braced(source, signature)
            self.assertEqual(body.count("getRTCClock()->getCurrentTimeUnique()"), 1)


if __name__ == "__main__":
    unittest.main()
