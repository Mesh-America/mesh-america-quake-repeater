"""Run Companion master mute and live UI synchronization with inert drivers."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

import test_gps_voice_buttons as voice
from test_radio_receive_contract import method


ROOT = Path(__file__).resolve().parents[1]
ARDUINO = voice.ARDUINO.replace(
    "inline unsigned pin_writes[64]={};",
    "inline unsigned pin_writes[64]={}, high_writes[64]={};").replace(
    "pin_states[pin]=value;++pin_writes[pin];",
    "pin_states[pin]=value;++pin_writes[pin];if(value==HIGH)++high_writes[pin];")
ARDUINO += "\ninline void delay(unsigned) {}\n"
WIRE = "#pragma once\nstruct TwoWire {};\ninline TwoWire Wire;\n"
ADAFRUIT = r'''
#pragma once
#include <Arduino.h>
#include <Wire.h>
#define DRV2605_MODE_INTTRIG 0
#define DRV2605_MODE_REALTIME 5
#define DRV2605_REG_FEEDBACK 0x1a
#define DRV2605_REG_GO 0x0c
struct MockDriver {
 bool found=true;
 uint8_t registers[32]={};
 unsigned writes=0;
};
inline MockDriver hardware;
class Adafruit_DRV2605 {
public:
 bool begin(TwoWire*) { return hardware.found; }
 void writeRegister8(uint8_t reg,uint8_t value) {
   hardware.registers[reg]=value;++hardware.writes;
 }
 uint8_t readRegister8(uint8_t reg) { return hardware.registers[reg]; }
 void selectLibrary(uint8_t value) { writeRegister8(3,value); }
 void setMode(uint8_t value) { writeRegister8(1,value); }
 void setWaveform(uint8_t slot,uint8_t value) { writeRegister8(4+slot,value); }
 void setRealtimeValue(uint8_t value) { writeRegister8(2,value); }
 void go() { writeRegister8(DRV2605_REG_GO,1); }
 void stop() { writeRegister8(DRV2605_REG_GO,0); }
};
'''

BUZZER = r'''
#include <cassert>
#define PIN_BUZZER 25
#define PIN_BUZZER_EN 37
#define MESH_GPS_VOICE @VOICE@
#include <helpers/ui/buzzer.cpp>
uint32_t now_ms=100;
int main() {
 genericBuzzer buzzer;buzzer.begin();
 assert(buzzer.isQuiet()&&pin_states[PIN_BUZZER]==LOW&&pin_states[PIN_BUZZER_EN]==LOW);
 assert(high_writes[PIN_BUZZER]==0&&high_writes[PIN_BUZZER_EN]==0);
 buzzer.quiet(false);
 buzzer.playNotification("alert:d=4,o=5,b=120:c");
 assert(buzzer.isPlaying());
 buzzer.quiet(true);
 assert(!buzzer.isPlaying()&&pin_states[PIN_BUZZER_EN]==LOW);
 auto starts=rtttl::begins;
 buzzer.playNotification("alert:d=4,o=5,b=120:c");
 assert(!buzzer.isPlaying()&&rtttl::begins==starts);
 assert(pin_states[PIN_BUZZER_EN]==LOW);
#if MESH_GPS_VOICE
 // A rejected background melody cannot cancel explicit courtesy speech.
 assert(buzzer.speakButton(ButtonVoicePrompt::SoundOff,true));
 buzzer.playNotification("alert:d=4,o=5,b=120:c");
 buzzer.stopNotification();
 assert(buzzer.isQuiet()&&buzzer.isPlaying());
 auto cancelled=gps_voice.cancelled();
 buzzer.loop();now_ms+=100;buzzer.loop();
 assert(registers.ENABLE);
 buzzer.playNotification("alert:d=4,o=5,b=120:c");
 assert(registers.ENABLE&&gps_voice.cancelled()==cancelled);
 buzzer.stop();
#endif
 buzzer.quiet(false);
 buzzer.playNotification("alert:d=4,o=5,b=120:c");
 assert(buzzer.isPlaying()&&rtttl::begins==starts+1);
 buzzer.stopNotification();assert(!buzzer.isPlaying());
}
'''

VIBRATION = r'''
#include <cassert>
@FLAGS@
#include <helpers/ui/GenericVibration.cpp>
#include <helpers/ui/DRV2605Vibration.cpp>
uint32_t now_ms=100;
#ifdef HAS_DRV2605
using Vibration = DRV2605Vibration;
bool active() { return hardware.registers[1]!=0x40; }
#else
using Vibration = GenericVibration;
bool active() { return pin_states[PIN_VIBRATION]==HIGH; }
#endif
int main() {
 Vibration motor;motor.begin();
 motor.trigger();assert(active());
 motor.quiet(true);assert(!active()&&!motor.isVibrating());
 motor.trigger();motor.pulse(true);motor.loop();
 assert(motor.isQuiet()&&!active()&&!motor.isVibrating());
 motor.pulse(false);assert(!active());
 motor.quiet(false);
 motor.pulse(true);assert(active());
 motor.quiet(true);assert(!active());
 motor.quiet(false);
 now_ms+=6000;motor.trigger();assert(active());
 motor.stop();assert(!active());
#ifdef HAS_DRV2605
 hardware.found=false;motor.begin();
 auto writes=hardware.writes;
 motor.quiet(true);motor.trigger(true);motor.pulse(true);motor.pulse(false);
 assert(hardware.writes==writes&&!motor.isVibrating());
#endif
}
'''

UI = r'''
#include <cassert>
#define MESH_GPS_VOICE 0
@FLAGS@
#include <helpers/ui/buzzer.cpp>
#include <helpers/ui/GenericVibration.cpp>
#include <helpers/ui/DRV2605Vibration.cpp>
uint32_t now_ms=100;
struct CompanionNodePrefs { uint8_t buzzer_quiet=0,vibe_quiet=0; };
struct UITask {
 CompanionNodePrefs* _node_prefs=nullptr;
#ifdef PIN_BUZZER
 genericBuzzer buzzer;
#endif
#ifdef HAS_DRV2605
 DRV2605Vibration vibration;
#elif defined(PIN_VIBRATION)
 GenericVibration vibration;
#endif
 void syncAlertPreferences();
 void notificationMelody(const char*);
 void notificationVibration(bool);
};
@METHODS@
int main() {
 UITask ui;ui.syncAlertPreferences();
 CompanionNodePrefs prefs;ui._node_prefs=&prefs;
#ifdef PIN_BUZZER
 ui.buzzer.begin();ui.buzzer.quiet(false);ui.notificationMelody("alert:d=4,o=5,b=120:c");
 assert(ui.buzzer.isPlaying());
#endif
#if defined(HAS_DRV2605) || defined(PIN_VIBRATION)
 ui.vibration.begin();ui.notificationVibration(true);
#endif
 prefs.buzzer_quiet=prefs.vibe_quiet=1;
 ui.syncAlertPreferences();
#ifdef PIN_BUZZER
 assert(ui.buzzer.isQuiet()&&!ui.buzzer.isPlaying());
 ui.notificationMelody("alert:d=4,o=5,b=120:c");
 assert(!ui.buzzer.isPlaying());
#endif
#if defined(HAS_DRV2605) || defined(PIN_VIBRATION)
 assert(ui.vibration.isQuiet()&&!ui.vibration.isVibrating());
 ui.notificationVibration(true);
#ifdef HAS_DRV2605
 assert(hardware.registers[1]==0x40);
 auto writes=hardware.writes;
 ui.syncAlertPreferences();ui.syncAlertPreferences();
 assert(hardware.writes==writes); // unchanged prefs must not add I2C traffic
#else
 assert(pin_states[PIN_VIBRATION]==LOW);
#endif
#endif
 prefs.buzzer_quiet=prefs.vibe_quiet=0;
 ui.syncAlertPreferences();
#ifdef PIN_BUZZER
 ui.notificationMelody("alert:d=4,o=5,b=120:c");
 assert(ui.buzzer.isPlaying());
 ui.notificationMelody(nullptr);assert(!ui.buzzer.isPlaying());
#endif
#if defined(HAS_DRV2605) || defined(PIN_VIBRATION)
 ui.notificationVibration(true);
#ifdef HAS_DRV2605
 assert(hardware.registers[1]==DRV2605_MODE_REALTIME);
#else
 assert(pin_states[PIN_VIBRATION]==HIGH);
#endif
 ui.notificationVibration(false);
#endif
}
'''


class CompanionAlertDriversTests(unittest.TestCase):
    def build(self, source):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "a host C++ compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-alerts-") as directory:
            directory = Path(directory)
            for name, content in (("Arduino.h", ARDUINO), ("Wire.h", WIRE),
                                  ("Adafruit_DRV2605.h", ADAFRUIT),
                                  ("HardwarePWM.h", voice.PWM),
                                  ("NonBlockingRtttl.h", voice.RTTTL)):
                (directory / name).write_text(content)
            cpp = directory / "test.cpp"
            exe = directory / ("test.exe" if os.name == "nt" else "test")
            cpp.write_text(source)
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                     "-Wno-unused-parameter", "-I", str(directory),
                                     "-I", str(ROOT / "src"), str(cpp), "-o", str(exe)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_programmable_sound_obeys_mute_and_preserves_courtesy_speech(self):
        for speech in (0, 1):
            with self.subTest(speech=speech):
                self.build(BUZZER.replace("@VOICE@", str(speech)))

    def test_gpio_and_drv2605_mute_stops_active_effects_and_blocks_every_entry(self):
        for flags in ("#define PIN_VIBRATION 12", "#define HAS_DRV2605 1"):
            with self.subTest(flags=flags):
                self.build(VIBRATION.replace("@FLAGS@", flags))

    def test_each_ui_applies_saved_changes_without_reboot_or_repeated_driver_writes(self):
        for ui in ("ui-orig", "ui-new", "ui-tiny"):
            source = (ROOT / "examples/companion_radio" / ui / "UITask.cpp").read_text()
            methods = "\n".join(method(source, signature) for signature in (
                "void UITask::syncAlertPreferences()",
                "void UITask::notificationMelody(const char* text)",
                "void UITask::notificationVibration(bool on)",
            ))
            for flags in ("#define PIN_BUZZER 25\n#define PIN_VIBRATION 12",
                          "#define PIN_BUZZER 25", "#define HAS_DRV2605 1", ""):
                with self.subTest(ui=ui, flags=flags):
                    self.build(UI.replace("@FLAGS@", flags).replace("@METHODS@", methods))
            loop = method(source, "void UITask::loop()")
            self.assertRegex(loop, r"\{\s*syncAlertPreferences\(\);")


if __name__ == "__main__":
    unittest.main()
