#!/usr/bin/env python3
"""Run remote CW listening only after the exact physical reply copies drain."""
from pathlib import Path
import unittest
from test_morse_tx import compile_run, portable_radio_header
from test_radio_receive_contract import method
from test_radio_reply_mutation import LIFECYCLE

ROOT = Path(__file__).resolve().parents[1]


class MorseReplyHandoffTests(unittest.TestCase):
    def test_rx_disabled_handoff_is_stateless_and_never_calls_radio(self):
        code = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {",1)[0]
        code += """
#include <helpers/MorseReplyHandoff.h>
int main() {
  static_assert(MESH_ENABLE_MORSE_RX==0,"test must use the flash-saving RX gate");
  static_assert(sizeof(mesh::MorseReplyHandoff)==1,"disabled handoff must retain no session state");
  mesh::MorseReplyHandoff h; TestRadio radio; radio.rx_supported=true;
  uint8_t actor[32]={1}; int packet=0,copy=1;
  h.beginCommand(actor);
  assert(!h.remoteCommand() && !h.pending() && !h.generation() && h.actor()==nullptr);
  assert(!h.stage(902100,25,60000,0xfffffff0));
  h.prepareReply(&packet); h.copy(&packet,&copy); h.armReply(&packet,true);
  h.complete(&packet); h.fail(&copy); h.endCommand();
  assert(!h.contains(&packet) && !h.ownsReply(&packet) && !h.ownsReply(&copy));
  for(uint32_t now : {0U,30000U,0xffffffffU}) {
    assert(!h.service(&radio,now,true,true,902100,25));
    assert(!h.service(nullptr,now,false,false,0,0));
  }
  h.cancel(); h.armReply(nullptr,false);
  assert(!h.pending() && !h.generation() && radio.rx_starts==0 && radio.rx_stops==0);
  char reply[160];
  assert(mesh::handleMorseCommand(&radio,"morse send SOS",reply,sizeof(reply)));
  assert(radio.starts==1 && radio.active && radio.rx_starts==0);
}
"""
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self,code,flags=("-Wno-unused-parameter","-DMESH_ENABLE_MORSE_RX=0"),headers={
                    "Dispatcher.h":portable_radio_header(),"helpers/IdentityStore.h":fs_mock,
                    "helpers/TempRadioReplyBarrier.h":"#error disabled handoff must not compile the reply barrier\n"})

    def test_actual_shared_handoff_remote_parser_and_all_copy_deadlines(self):
        code = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        code += (ROOT / "test/fixtures/morse_reply_handoff.cpp").read_text(encoding="ascii")
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self, code, flags=("-Wno-unused-parameter",), headers={
                    "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

    def test_actual_common_loop_reauthorizes_full_acl_identity_after_phy_completion(self):
        code = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        common = (ROOT / "src/helpers/CommonCLI.cpp").read_text(encoding="utf-8")
        code += (ROOT / "test/fixtures/morse_reply_loop.cpp").read_text(encoding="ascii").replace(
            "@LOOP@", method(common, "void CommonCLI::loop("))
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self, code, flags=("-Wno-unused-parameter",), headers={
                    "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

    def test_actual_all_infrastructure_and_tracker_phy_callbacks_own_exact_copies(self):
        first = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        lifecycle = LIFECYCLE.split("int main() {", 1)[0]
        lifecycle = lifecycle.replace("struct Packet {};", "struct Packet { int getPayloadType() const { return 3; } void calculatePacketHash(uint8_t* out) const { memset(out, 0, 8); } };")
        lifecycle = lifecycle.replace("  struct NoMorseReply {\n    void complete(const void*) {}\n    void fail(const void*) {}\n    void copy(const void*, const void*) {}\n  } morse;", "  mesh::MorseReplyHandoff morse;")
        lifecycle = lifecycle.replace("NoMorseReply& morseReply()", "mesh::MorseReplyHandoff& morseReply()")
        lifecycle = lifecycle.replace("  CLI _cli;", "  CLI _cli;\n  bool tracker_pending=false, tracker_sent=false; uint32_t tracker_reply_until=0; uint8_t tracker_packet_hash[8]={};\n  uint32_t futureMillis(uint32_t delay) { return now_ms+delay; }")
        lifecycle = "#define MAX_HASH_SIZE 8\n#define PAYLOAD_TYPE_REQ 1\nnamespace mesh { namespace tracker { constexpr unsigned kReplyWindowSeconds=30; } }\n" + lifecycle
        main = (ROOT / "test/fixtures/morse_reply_role_callbacks.cpp").read_text(encoding="ascii")
        specs = [
            ("repeater", "MyMesh", "examples/simple_repeater/MyMesh.cpp", None),
            ("room", "MyMesh", "examples/simple_room_server/MyMesh.cpp", None),
            ("sensor", "SensorMesh", "examples/simple_sensor/SensorMesh.cpp", None),
            ("tracker", "SensorMesh", "examples/simple_sensor/Tracker.cpp", "examples/simple_sensor/SensorMesh.cpp"),
            ("companion", "MyMesh", "examples/companion_radio/MyMesh.cpp", None),
        ]
        for name, role, path, copy_path in specs:
            with self.subTest(role=name):
                source = (ROOT / path).read_text(encoding="utf-8")
                methods = "\n".join(method(source, signature) for signature in (
                    f"void {role}::onSendComplete(", f"void {role}::onSendFail("))
                copy_source = (ROOT / (copy_path or path)).read_text(encoding="utf-8")
                methods += "\n" + method(copy_source, f"void {role}::onRadioProfileCopyQueued(")
                if name == "repeater":
                    methods += "\n" + method(source, "void MyMesh::finishRadioReply(")
                role_fixture = lifecycle.replace("MyMesh", role)
                if name == "companion":
                    role_fixture = role_fixture.replace("  CLI _cli;", "  CLI _cli;\n  mesh::MorseReplyHandoff& _morse_reply = _cli.morse;")
                code = first + role_fixture.replace("@METHODS@", methods)
                code += main.replace("@ROLE@", role)
                fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
                compile_run(self, code, flags=("-Wno-unused-parameter",), headers={
                            "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

    def test_actual_companion_admission_actor_allocation_and_queue_failure(self):
        first = (ROOT / "test/fixtures/morse_cli.cpp").read_text(encoding="ascii").split("int main() {", 1)[0]
        source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text(encoding="utf-8")
        methods = "\n".join(method(source, signature) for signature in (
            "void MyMesh::onCLICommandRecv(", "void MyMesh::onCLIReplyPrepared(", "void MyMesh::onCLIReplyQueued("))
        code = first + (ROOT / "test/fixtures/morse_reply_companion.cpp").read_text(encoding="ascii").replace("@METHODS@", methods)
        fs_mock = (ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h").read_text(encoding="ascii")
        compile_run(self, code, flags=("-Wno-unused-parameter",), headers={
                    "Dispatcher.h": portable_radio_header(), "helpers/IdentityStore.h": fs_mock})

        base = (ROOT / "src/helpers/BaseChatMesh.cpp").read_text(encoding="utf-8")
        recv = method(base, "void BaseChatMesh::onPeerDataRecv(")
        begin = recv.index("onCLIReplyPrepared(from, reply_pkt)")
        end = recv.index("onCLIReplyQueued(from, reply_pkt, queued)", begin)
        self.assertLess(begin, recv.index("queued = sendFloodScoped", begin))
        self.assertLess(begin, recv.index("queued = sendDirect", begin))
        self.assertLess(recv.index("queued = sendDirect", begin), end)
        self.assertIn("else onCLIReplyQueued(from, nullptr, false)", recv[end:])


if __name__ == "__main__":
    unittest.main()
