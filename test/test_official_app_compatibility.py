#!/usr/bin/env python3
"""Execute pinned stock app code against actual firmware ACL/radio outputs.

The public web build is the source witness, not proof of the installed iOS app.
The whole app remains outside Git. A changed upstream bundle fails its SHA gate;
an explicit source-pin update is required, never silent parser replacement.
No PlatformIO, devices, app fork, settings writes or real radio are involved.
"""

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request

from test_client_acl_response import production_acl_methods
from test_companion_primary_radio_persistence import production_primary_radio_harness
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
APP_URL = "https://app.meshcore.nz/main.dart.js"
APP_SHA256 = "84bc39a950735aaffa93d912556852a4c22e235d0cc4e4d04790113207f13a68"
APP_BYTES = 9494192
JS = ROOT / "test/fixtures/official_app_compatibility/app_contract.js"
SANITIZERS = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])


def official_app_bundle():
    explicit = os.environ.get("MESHCORE_OFFICIAL_APP_BUNDLE")
    path = Path(explicit) if explicit else (
        Path.home() / ".cache/meshcore-tests" / APP_SHA256 / "main.dart.js")
    if not path.exists():
        if explicit:
            raise AssertionError(f"Missing explicit official app bundle: {path}")
        with urllib.request.urlopen(APP_URL, timeout=45) as response:
            data = response.read(APP_BYTES + 1)
        if len(data) != APP_BYTES or hashlib.sha256(data).hexdigest() != APP_SHA256:
            raise AssertionError("Official app changed: obtain the pinned cached build or review/update its source pin")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    data = path.read_bytes()
    if len(data) != APP_BYTES or hashlib.sha256(data).hexdigest() != APP_SHA256:
        raise AssertionError(f"Official app source SHA/size mismatch: {path}")
    return path.resolve()


def checked(command, timeout=60):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def acl_outputs(work, compiler, app_request):
    source = production_acl_methods()
    packet = (ROOT / "src/Packet.cpp").read_text()
    source += "namespace mesh {\n" + "\n".join(extract_braced(packet, signature) for signature in (
        "size_t Packet::writePath(", "int Packet::getRawLength() const",
        "uint8_t Packet::writeTo(uint8_t dest[]) const")) + "\n}\n"
    (work / "production.inc").write_text(source, encoding="ascii")
    fixture = (ROOT / "test/fixtures/client_acl_response/test_client_acl_response.cpp").read_text()
    fixture = fixture[:fixture.index("int main()")]
    request = ",".join(str(byte) for byte in bytes.fromhex(app_request))
    fixture += r'''
int main() {
  uint8_t app_query[] = {APP_QUERY};
  static_assert(sizeof(app_query) == 7, "Exact stock app ACL request schema");
  for (bool flood : {false, true}) for (uint8_t path_len : {0, 0x60})
      for (unsigned clients : {0, 1, 22, 23, 24, 25, 32, 256}) {
    MyMesh target; fill(target.acl, clients);
    target.sender.last_timestamp = 50;
    mesh::Packet request; request.header = flood ? ROUTE_TYPE_FLOOD : ROUTE_TYPE_DIRECT;
    request.path_len = path_len;
    uint8_t plaintext[11]; uint32_t tag = 51;
    memcpy(plaintext, &tag, 4); memcpy(plaintext + 4, app_query, sizeof(app_query));
    uint8_t secret[PUB_KEY_SIZE] = {};
    auto* transmitted = target.createDatagram(PAYLOAD_TYPE_REQ, target.sender.id,
                                             secret, plaintext, sizeof(plaintext));
    // Radio send boundaries set the route bits after packet construction.
    assert(transmitted != nullptr); transmitted->header |= ROUTE_TYPE_DIRECT;
    assert(transmitted && transmitted->payload_len == 20 && transmitted->getRawLength() == 22);
    target.receive(&request, plaintext, sizeof(plaintext));
    assert(target.queued == 1 && target.sender.last_timestamp == tag);
    auto* reply = target.last_reply; assert(reply != nullptr);
    reply->header |= flood ? ROUTE_TYPE_FLOOD : ROUTE_TYPE_DIRECT;
    const unsigned capacity = mesh::clientACLReplyCapacity(flood, path_len);
    const unsigned entries = std::min(clients, (capacity - 4) / 7);
    const unsigned route_bytes = (path_len & 63) * ((path_len >> 6) + 1);
    const size_t body_offset = 2 * PATH_HASH_SIZE + CIPHER_MAC_SIZE + 4
        + (flood ? 2 + route_bytes : 0);
    if (!flood && clients == 1) {
      assert(sizeof(plaintext) == 11 && reply->payload_len == 20 && reply->getRawLength() == 22);
      uint8_t wire[MAX_PACKET_PAYLOAD + MAX_PATH_SIZE + 6];
      assert(reply->writeTo(wire) == 22); // 11 plaintext -> 16 cipher -> 20 payload -> 22 wire.
    }
    print_legacy(reply->payload + body_offset, entries, reply->payload_len - body_offset);
  }
}
'''.replace("APP_QUERY", request)
    (work / "acl.cpp").write_text(fixture, encoding="ascii")
    binary = work / "acl.exe"
    checked([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter", "-Wno-unused-function", *SANITIZERS,
             f"-I{work}", f"-I{ROOT / 'src'}", str(work / "acl.cpp"), "-o", str(binary)])
    output = checked([str(binary)], timeout=20)
    records = []
    for line in output.splitlines():
        if line.startswith("LEGACY:"):
            _, entries, body = line.split(":")
            records.append({"entries": int(entries), "body": body})
    if len(records) != 32:
        raise AssertionError(output)
    return records


def radio_outputs(work, compiler):
    harness = production_primary_radio_harness()
    # Execute the same production Companion dispatch, shared preferences parser
    # and CommonCLI infrastructure branch with automatic/explicit preambles.
    begin = harness.index("int main()")
    harness = harness[:begin] + r'''
int main() {
  for (uint32_t timestamp : {0U, 1700000000U}) for (uint16_t preamble : {0U, 48U}) {
    MyMesh node; assert(node._radio_profiles.savePrimaryPreamble(preamble));
    node.radio.p.primary_temporary = true;
    node.radio.p.primary.freq = 915; node.radio.p.primary.preamble = 96;
    node.radio.p.secondary.params = {916, 125, 64, 8, 6};
    node.radio.p.secondary.mode = mesh::RadioProfileMode::RxTx;
    printf("RADIO:%s\n", node.command("get radio", timestamp));
    Infrastructure repeater; char reply[160] = {};
    repeater.radioCommand(reply); printf("RADIO:%s\n", reply);
  }
}
'''
    utils = (ROOT / "test/mocks/Utils.h").read_text().replace("class Utils {\npublic:", """class Utils {
public:
 static void printHex(Stream&,const uint8_t*,size_t){assert(false);}
 static void fromHex(uint8_t*,size_t,const char*){assert(false);}
""")
    (work / "Utils.h").write_text("#include <Arduino.h>\n#include <cassert>\n" + utils, encoding="ascii")
    (work / "Identity.h").write_text((ROOT / "test/mocks/Identity.h").read_text(), encoding="ascii")
    transaction = (ROOT / "src/helpers/ContactFileTransaction.h").read_text()
    (work / "ContactFileTransaction.h").write_text(transaction.replace(
        '#include "IdentityStore.h"', '#include <helpers/IdentityStore.h>'), encoding="ascii")
    (work / "radio.cpp").write_text(harness, encoding="ascii")
    binary = work / "radio.exe"
    checked([compiler, "-std=c++17", "-Wall", "-Wextra", "-Wno-unused-function",
             "-Wno-unused-parameter", "-Wno-sign-compare", "-Wno-reorder",
             "-DESP32_PLATFORM=1", *SANITIZERS,
             f"-I{work}", f"-I{ROOT / 'test/fixtures/radio_profiles/mocks'}",
             f"-I{ROOT / 'test/mocks'}", f"-I{ROOT / 'src'}", f"-I{ROOT / 'src/helpers'}", f"-I{ROOT}",
             str(work / "radio.cpp"), *[str(ROOT / "src/helpers" / name) for name in (
                 "ConfigSerializer.cpp", "DynamicConfigSerializer.cpp", "CommonRadioPrefs.cpp",
                 "TxtDataHelpers.cpp", "RadioProfileCLI.cpp")], "-o", str(binary)])
    output = checked([str(binary)], timeout=20)
    replies = [line.removeprefix("RADIO:") for line in output.splitlines() if line.startswith("RADIO:")]
    if len(replies) != 8:
        raise AssertionError(output)
    return replies


class OfficialAppCompatibilityTests(unittest.TestCase):
    def test_pinned_app_functions_with_production_request_and_outputs(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        node = shutil.which("node")
        self.assertIsNotNone(compiler, "native C++ compiler required")
        self.assertIsNotNone(node, "Node.js required for actual stock app functions")
        bundle = official_app_bundle()
        with tempfile.TemporaryDirectory(prefix="meshcore-official-app-") as directory:
            work = Path(directory)
            config = work / "input.json"
            config.write_text(json.dumps({"bundle": str(bundle), "mode": "build"}), encoding="ascii")
            generated = json.loads(checked([node, str(JS), str(config)], timeout=20))
            config.write_text(json.dumps({"bundle": str(bundle), "mode": "check",
                "acl": acl_outputs(work, compiler, generated["request"]),
                "radio": radio_outputs(work, compiler)}), encoding="ascii")
            result = json.loads(checked([node, str(JS), str(config)], timeout=20))
            self.assertEqual(result["acl_cases"], 32)
            self.assertEqual(result["radio_screens"], 3)
            self.assertTrue(result["stock_sent_race_witness"])
            self.assertFalse(result["actual_ios_cause_proven"])


if __name__ == "__main__":
    unittest.main()
