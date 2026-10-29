"""Execute the opt-in local radio trace CLI without radio, USB or PlatformIO."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER = "helpers/radiolib/ESP32RadioTraceCLI.h"
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>
#include <helpers/radiolib/ESP32RadioTraceCLI.h>
static uint64_t clock_us=1234567890123ULL;
namespace mesh { namespace radiotrace {
Trace storage;
Trace& trace() { return storage; }
uint64_t nowUs() { return clock_us; }
} }
using namespace mesh::radiotrace;
static char reply[160];
[[maybe_unused]] static const char* command(const char* value) {
  std::memset(reply,'?',sizeof(reply));
  assert(handleTraceCommand(value,reply,sizeof(reply)));
  assert(std::memchr(reply,0,sizeof(reply)));
  return reply;
}
[[maybe_unused]] static void error(const char* value) {
  assert(!std::strncmp(command(value),"Error:",6));
}
'''


class RadioTraceCliTests(unittest.TestCase):
    def native(self, body, flags=("-DESP32_PLATFORM=1", "-DMESH_HIL_RADIO_TRACE=1"), harness=HARNESS):
        with tempfile.TemporaryDirectory(prefix="radio-trace-cli-") as folder:
            root = Path(folder)
            (root / "esp_system.h").write_text(
                "#include <stdint.h>\ninline uint32_t esp_random() { return 0x12345678; }\n", encoding="ascii")
            cpp, binary = root / "test.cpp", root / "test"
            cpp.write_text(harness + body, encoding="ascii")
            built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                                    *flags, "-I", str(root), "-I", str(ROOT / "src"), str(cpp), "-o", str(binary)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            return subprocess.check_output(["nm", "-C", str(binary)], text=True)

    def test_clock_nonce_boot_identity_and_strict_arm_lifecycle(self):
        self.native(r'''
int main() {
  assert(!std::strcmp(command("get radio.trace clock aBCd0123456789ef"),
      "> rt=1 boot=1234567812345678 session=0 nonce=aBCd0123456789ef us=1234567890123"));
  for(const char* invalid:{"", "-1", "0123456789abcde", "0123456789abcdef0", "0123456789abcdeg", "0123456789abcdef "}) {
    char text[96];std::snprintf(text,sizeof(text),"get radio.trace clock %s",invalid);error(text);
  }
  assert(!std::strncmp(command("set radio.trace arm 50 1000"),"OK",2));
  assert(storage.session==1 && storage.state==State::Armed);
  assert(storage.epoch_us==clock_us+50000 && storage.end_us==clock_us+1050000);
  error("set radio.trace arm 0 100");assert(storage.session==1);
  clock_us+=50000;command("get radio.trace");assert(storage.state==State::Capturing);
  error("get radio.trace tx 0");
  command("set radio.trace stop");assert(storage.state==State::Frozen);
  assert(!std::strncmp(command("set radio.trace arm 180000 180000"),"OK",2));
  assert(storage.session==2);
  clock_us=storage.end_us;command("get radio.trace");assert(storage.state==State::Frozen);
}
''', harness="#include <initializer_list>\n" + HARNESS)

    def test_malformed_commands_do_not_arm_or_claim_unrelated_names(self):
        self.native(r'''
int main() {
  for(const char* text:{"set radio.trace", "set radio.trace arm", "set radio.trace arm -1 1",
      "set radio.trace arm 0 0", "set radio.trace arm 180001 1", "set radio.trace arm 0 180001",
      "set radio.trace arm 4294967296 1", "set radio.trace arm 1 4294967296",
      "set radio.trace arm 1", "set radio.trace arm 1 1 x", "set radio.trace arm  1 1",
      "set radio.trace arm 1  1", "get radio.trace rx -1", "get radio.trace rx 4294967296",
      "get radio.trace rx 0 trailing", "get radio.trace tx", "get radio.trace stats "}) {
    error(text);assert(storage.session==0 && storage.state==State::Off);
  }
  for(const char* text:{"get radio.tracex", "set radio.traceX", "get radio", "trace"})
    assert(!handleTraceCommand(text,reply,sizeof(reply)));
  assert(!handleTraceCommand(nullptr,reply,sizeof(reply)));
  assert(!handleTraceCommand("get radio.trace",nullptr,sizeof(reply)));
  assert(!handleTraceCommand("get radio.trace",reply,0));
}
''', harness="#include <initializer_list>\n" + HARNESS)

    def test_frozen_record_schema_bounds_and_frame_capacity(self):
        self.native(r'''
int main() {
  storage.state=State::Frozen;storage.session=UINT32_MAX;
  storage.epoch_us=storage.end_us=UINT64_MAX;storage.flags=UINT32_MAX;
  assert(std::strlen(command("get radio.trace"))<sizeof(reply)-1);
  assert(!std::strcmp(command("get radio.trace marker"),"> MCRFTRACE1:RX192:TX40"));
  storage.span_count=storage.rx_count=storage.tx_count=storage.bucket_count=1;
  storage.spans[0]={1,UINT32_MAX,3,UINT16_MAX,1,10};
  storage.rx[0]={1,2,3,4,0xabcdef0123456789ULL,101,UINT16_MAX,1,4,0};
  storage.tx[0]={0xabcdef0123456789ULL,1,2,3,4,5,652288,101,1,4,9};
  storage.buckets[0]={3000000,12,34,56,78};
  assert(!std::strcmp(command("get radio.trace span 0"),"> span=0,1,4294967295,3,65535,1,10"));
  assert(!std::strcmp(command("get radio.trace rx 0"),"> rx=0,1,2,3,4,abcdef0123456789,101,65535,1,4"));
  assert(!std::strcmp(command("get radio.trace tx 0"),"> tx=0,abcdef0123456789,1,2,3,4,5,652288,101,1,4,9"));
  assert(!std::strcmp(command("get radio.trace bucket 0"),"> bucket=0,3000000,12,34,56,78"));
  for(const char* kind:{"span","rx","tx","bucket"}) {
    char text[64];std::snprintf(text,sizeof(text),"get radio.trace %s 1",kind);error(text);
  }
  std::memset(storage.tx,0xff,sizeof(storage.tx));command("get radio.trace tx 0");
  assert(std::strlen(reply)<sizeof(reply)-1);
  storage.span_count=storage.rx_count=storage.tx_count=storage.bucket_count=UINT32_MAX;
  storage.span_dropped=storage.rx_dropped=storage.tx_dropped=UINT32_MAX;
  storage.max_scan_gap_us=storage.max_visit_overdue_us=storage.max_blackout_us=UINT32_MAX;
  storage.spi_errors=storage.invalidations=storage.context_errors=UINT32_MAX;
  command("get radio.trace stats");assert(std::strlen(reply)<sizeof(reply)-1);
  command("get radio.trace gaps");assert(std::strlen(reply)<sizeof(reply)-1);
  error("get radio.trace tx 40");error("get radio.trace span 192");
  char tiny[2]={'?', '?'};assert(handleTraceCommand("get radio.trace",tiny,sizeof(tiny)) && tiny[1]==0);
}
''', harness="#include <initializer_list>\n" + HARNESS)

    def test_tx_only_has_no_receive_records_and_correct_marker(self):
        self.native(r'''
int main() {
  assert(SpanCapacity==0 && RxCapacity==0 && BucketCapacity==0 && TxCapacity==40);
  assert(!std::strcmp(command("get radio.trace marker"),"> MCRFTRACE1:TXONLY40"));
  storage.state=State::Frozen;storage.rx_count=storage.span_count=storage.bucket_count=1;
  error("get radio.trace rx 0");error("get radio.trace span 0");error("get radio.trace bucket 0");
}
''', flags=("-DESP32_PLATFORM=1", "-DMESH_HIL_RADIO_TRACE=1", "-DMESH_HIL_RADIO_TRACE_TX_ONLY=1"))

    def test_disabled_header_has_no_trace_state_or_formatter(self):
        for flags in ((), ("-DESP32_PLATFORM=1", "-DMESH_HIL_RADIO_TRACE=0")):
            symbols = self.native("int main() {return 0;}\n", flags=flags,
                                  harness=f"#include <{HEADER}>\n")
            self.assertNotIn("radiotrace", symbols)

    def test_actual_direct_dispatch_excludes_lora_admin(self):
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
        start = source.index("bool MyMesh::handleDirectCommand(")
        direct = source[start:source.index("#if MESH_ENABLE_ONE_KEY_DM", start)]
        hook = re.search(r"#if defined\(ESP32_PLATFORM\) && defined\(MESH_HIL_RADIO_TRACE\) && MESH_HIL_RADIO_TRACE\n"
                         r"  if \(mesh::radiotrace::handleTraceCommand\(command, reply, reply_size\)\) return true;\n#endif", direct)
        self.assertIsNotNone(hook)
        guard = re.search(r"if \(sender_timestamp == 0 && handleDirectCommand\([^\n]+", source)
        self.assertIsNotNone(guard)
        self.native(r'''
struct MyMesh {
  bool handleDirectCommand(const char* command,char* reply,size_t reply_size) {
@HOOK@
    return false;
  }
  bool handleCommand(const char* command,uint32_t sender_timestamp,char* reply) {
    const size_t reply_capacity=160;
    @GUARD@
    return false;
  }
};
int main() {
  MyMesh mesh;
  assert(!mesh.handleCommand("set radio.trace arm 0 1000",1,reply));
  assert(storage.session==0);
  assert(mesh.handleCommand("set radio.trace arm 0 1000",0,reply));
  assert(storage.session==1);
}
'''.replace("@HOOK@", hook.group()).replace("@GUARD@", guard.group()))


if __name__ == "__main__":
    unittest.main()
