"""Run the production laboratory audio-preview dispatch without any hardware actions."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_radio_receive_contract import method

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which("g++")
SIGNATURE = "bool UITask::handleButtonAudioTest(const char* command, char* reply, size_t size)"

STUBS = r'''
#include <cassert>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include <helpers/ui/ButtonVoice.h>
#define PIN_USER_BTN 6
struct Button {
 unsigned calls=0;
 bool injectPresses(uint8_t,uint32_t){++calls;return true;}
};
struct Buzzer {
 bool quiet=true,playing=true,available=true;
 unsigned calls=0,status_calls=0,gain_calls=0;
 ButtonVoicePrompt last=ButtonVoicePrompt::Ready;
 bool allow_quiet=false;
 bool speakButton(ButtonVoicePrompt prompt,bool allowQuiet=false) {
   ++calls;last=prompt;allow_quiet=allowQuiet;
   if(!available)return false;
   playing=true;return true;
 }
 bool voiceGain(unsigned){++gain_calls;return true;}
 void voiceStatus(char* reply,size_t size){++status_calls;snprintf(reply,size,"voice stub");}
};
struct UITask {
 Button button;
 Button* _userButton=&button;
#ifdef PIN_BUZZER
 Buzzer buzzer;
#endif
#if defined(PIN_BUZZER) && MESH_GPS_VOICE
 bool _shutdown_pending=false;
#endif
 // No button/action/persistence APIs exist in this fixture: preview code must
 // compile and execute without calling any of those real-world operations.
 unsigned settings_marker=12345;
#ifdef MESH_BUTTON_AUDIO_HIL
 bool handleButtonAudioTest(const char* command,char* reply,size_t size);
#endif
};
'''

ENABLED_MAIN = r'''
int main(){
 UITask ui;char reply[180];
 struct Mapping {const char* name;ButtonVoicePrompt prompt;};
 const Mapping mappings[]={
  {"ready",ButtonVoicePrompt::Ready},
  {"notificationCleared",ButtonVoicePrompt::NotificationCleared},
  {"advertQueued",ButtonVoicePrompt::AdvertQueued},
  {"advertFailed",ButtonVoicePrompt::AdvertFailed},
  {"soundOn",ButtonVoicePrompt::SoundOn},
  {"soundOff",ButtonVoicePrompt::SoundOff},
  {"gpsOn",ButtonVoicePrompt::GpsOn},
  {"gpsOff",ButtonVoicePrompt::GpsOff},
  {"actionFailed",ButtonVoicePrompt::ActionFailed},
  {"usbSetup",ButtonVoicePrompt::UsbSetup},
  {"shuttingDown",ButtonVoicePrompt::ShuttingDown},
  {"restarting",ButtonVoicePrompt::Restarting},
#ifdef HAS_DRV2605
  {"alertsSoundVibration",ButtonVoicePrompt::AlertsSoundVibration},
  {"alertsSoundOnly",ButtonVoicePrompt::AlertsSoundOnly},
  {"alertsVibrationOnly",ButtonVoicePrompt::AlertsVibrationOnly},
  {"alertsSilent",ButtonVoicePrompt::AlertsSilent},
#endif
 };
 for(const auto& mapping:mappings){
  auto calls=ui.buzzer.calls;
  std::string command=std::string("hil voice play ")+mapping.name;
  assert(ui.handleButtonAudioTest(command.c_str(),reply,sizeof(reply)));
  assert(std::string(reply)==std::string("OK - preview only: ")+mapping.name);
  assert(ui.buzzer.calls==calls+1&&ui.buzzer.last==mapping.prompt);
  assert(ui.buzzer.allow_quiet&&ui.buzzer.quiet&&ui.buzzer.playing);
  assert(!ui._shutdown_pending&&ui.settings_marker==12345&&ui.button.calls==0);
 }
#ifndef HAS_DRV2605
 // Other screenless boards omit the X1-only recordings and reject their
 // preview names before changing any currently playing confirmation.
 for(const char* name:{"alertsSoundVibration","alertsSoundOnly","alertsVibrationOnly","alertsSilent"}){
  auto calls=ui.buzzer.calls;auto last=ui.buzzer.last;
  std::string command=std::string("hil voice play ")+name;
  assert(ui.handleButtonAudioTest(command.c_str(),reply,sizeof(reply)));
  assert(std::string(reply)=="Error: unknown voice preview name");
  assert(ui.buzzer.calls==calls&&ui.buzzer.last==last&&ui.buzzer.playing);
 }
#endif
 // Unknown/case-mismatched/extended names may not preempt active playback.
 for(const char* name:{"","unknown","Ready","soundOn extra","shuttingdown"}){
  auto calls=ui.buzzer.calls;auto last=ui.buzzer.last;
  std::string command=std::string("hil voice play ")+name;
  assert(ui.handleButtonAudioTest(command.c_str(),reply,sizeof(reply)));
  assert(std::string(reply)=="Error: unknown voice preview name");
  assert(ui.buzzer.calls==calls&&ui.buzzer.last==last&&ui.buzzer.playing);
 }
 ui._shutdown_pending=true;
 for(const auto& mapping:mappings){
  auto calls=ui.buzzer.calls;auto last=ui.buzzer.last;
  std::string command=std::string("hil voice play ")+mapping.name;
  assert(ui.handleButtonAudioTest(command.c_str(),reply,sizeof(reply)));
  assert(std::string(reply)=="Error: shutdown pending; preview refused");
  assert(ui.buzzer.calls==calls&&ui.buzzer.last==last&&ui.buzzer.playing);
  assert(ui._shutdown_pending&&ui.settings_marker==12345&&ui.button.calls==0);
 }
 ui._shutdown_pending=false;ui.buzzer.available=false;
 assert(ui.handleButtonAudioTest("hil voice play ready",reply,sizeof(reply)));
 assert(std::string(reply)=="Error: voice preview unavailable");
 assert(ui.buzzer.quiet&&!ui._shutdown_pending&&ui.settings_marker==12345);
 ui.buzzer.available=true;
 char tiny[12];memset(tiny,'x',sizeof(tiny));
 assert(ui.handleButtonAudioTest("hil voice play restarting",tiny,9));
 assert(tiny[8]==0&&tiny[9]=='x'&&tiny[10]=='x'&&tiny[11]=='x');
 char zero='x';
 assert(ui.handleButtonAudioTest("hil voice play ready",&zero,0)&&zero=='x');
 // Existing laboratory commands and unrelated command routing stay intact.
 assert(ui.handleButtonAudioTest("hil voice gain 8",reply,sizeof(reply)));
 assert(ui.buzzer.gain_calls==1&&std::string(reply)=="OK - speech gain 8");
 assert(ui.handleButtonAudioTest("hil voice status",reply,sizeof(reply)));
 assert(ui.buzzer.status_calls==1&&std::string(reply)=="voice stub");
 assert(!ui.handleButtonAudioTest("get gps",reply,sizeof(reply)));
}
'''

DISABLED_MAIN = r'''
int main(){
 UITask ui;char reply[180];
 assert(ui.handleButtonAudioTest("hil voice play shuttingDown",reply,sizeof(reply)));
 assert(std::string(reply)=="Error: voice preview unsupported");
 assert(ui.settings_marker==12345&&ui.button.calls==0);
#ifdef PIN_BUZZER
 assert(ui.buzzer.calls==0&&ui.buzzer.quiet&&ui.buzzer.playing);
#endif
}
'''


@unittest.skipUnless(COMPILER, "A native C++ compiler is needed for preview dispatch tests")
class Tests(unittest.TestCase):
    def build(self, flags, main):
        source = (ROOT / "examples/companion_radio/ui-orig/UITask.cpp").read_text()
        handler = method(source, SIGNATURE)
        # Keep the actual production method's outer laboratory-only gate.
        start = source.index(SIGNATURE)
        self.assertEqual(source[:start].rstrip().splitlines()[-1], "#ifdef MESH_BUTTON_AUDIO_HIL")
        end = start + len(handler)
        self.assertTrue(source[end:].lstrip().startswith("#endif"))
        unit = (flags + STUBS + "\n#ifdef MESH_BUTTON_AUDIO_HIL\n"
                + handler + "\n#endif\n" + main)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "preview.cpp"
            binary = directory / "preview"
            path.write_text(unit)
            subprocess.run(
                [COMPILER, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-I" + str(ROOT / "src"), str(path), "-o", str(binary)],
                check=True, timeout=30,
            )
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_all_prompt_previews_are_courtesy_audio_only_and_reject_preemption(self):
        self.build(
            "#include <initializer_list>\n#define MESH_BUTTON_AUDIO_HIL 1\n"
            "#define PIN_BUZZER 25\n#define HAS_DRV2605 1\n#define MESH_GPS_VOICE 1\n", ENABLED_MAIN)

    def test_non_vibrating_board_omits_and_rejects_x1_only_mode_previews(self):
        self.build(
            "#include <initializer_list>\n#define MESH_BUTTON_AUDIO_HIL 1\n"
            "#define PIN_BUZZER 21\n#define MESH_GPS_VOICE 1\n", ENABLED_MAIN)

    def test_voice_disabled_build_rejects_preview_without_preempting(self):
        self.build(
            "#define MESH_BUTTON_AUDIO_HIL 1\n#define PIN_BUZZER 25\n"
            "#define MESH_GPS_VOICE 0\n", DISABLED_MAIN)

    def test_no_buzzer_build_rejects_preview(self):
        self.build("#define MESH_BUTTON_AUDIO_HIL 1\n#define MESH_GPS_VOICE 0\n", DISABLED_MAIN)

    def test_production_build_has_no_preview_handler(self):
        self.build(
            "#define PIN_BUZZER 25\n#define MESH_GPS_VOICE 1\n",
            "int main(){UITask ui;assert(ui.settings_marker==12345);}\n")


if __name__ == "__main__":
    unittest.main()
