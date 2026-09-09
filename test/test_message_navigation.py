#!/usr/bin/env python3
"""Exercise actual button routing and message filters with a host display."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

PREAMBLE = r'''
#include <Arduino.h>
#include <helpers/ui/UIScreen.h>
#include <helpers/ui/MomentaryButton.h>
#include <helpers/ui/CompanionMessageHistory.h>
#include <helpers/ui/ReaderNavigationHint.h>
#include <helpers/ui/DisplayTextLayout.h>
#include <cassert>
#include <string>
#include <vector>
#define UI_SMALL_MESSAGE_FONT 0
#define UI_BUTTON_READER_HINT 1
#define UI_MESSAGE_CHANNEL_FOOTER 0
#define UI_COMPACT_MESSAGE_STATUS 0
#define UI_MSG_PREVIEW_SIZE 161
#define MAX_GROUP_CHANNELS 4
#define AUTO_OFF_MILLIS 15000
#define MESH_DEBUG_PRINTLN(...)
ColorVal UIColor::window_bkg=0, UIColor::title_bkg=0, UIColor::title_txt=1;
ColorVal UIColor::primary_txt=1, UIColor::secondary_txt=1, UIColor::warning_txt=1;
ColorVal UIColor::popup_bkg=0, UIColor::popup_txt=1, UIColor::corp_blue=1;
uint64_t companionMessageNowMillis() { return millis(); }
uint64_t companionMessageElapsedMillis(uint64_t when) { return millis()-when; }
struct StrHelper {
  static void strncpy(char* out,const char* in,size_t size) { snprintf(out,size,"%s",in); }
};
struct ChannelDetails { char name[32]; };
struct Mesh {
  bool getChannel(int channel,ChannelDetails& details) const {
    const char* names[]={"Public","","Second","Empty"};
    if (channel<0 || channel>=MAX_GROUP_CHANNELS) return false;
    snprintf(details.name,sizeof(details.name),"%s",names[channel]);
    return true;
  }
} the_mesh;
struct Display : DisplayDriver {
  struct Line { int x,y; std::string text; };
  std::vector<Line> lines;
  int x=0,y=0;
  bool on=true;
  Display() : DisplayDriver(128,64) {}
  bool isOn() override { return on; }
  void turnOn() override { on=true; }
  void turnOff() override { on=false; }
  void clear() override { lines.clear(); }
  void startFrame(ColorVal=0) override { clear(); }
  void endFrame() override {}
  void setTextSize(int) override {}
  void setColor(ColorVal) override {}
  void setCursor(int a,int b) override { x=a;y=b; }
  uint16_t getTextWidth(const char* text) override { return strlen(text)*4; }
  void print(const char* text) override {
    assert(x>=0 && x+getTextWidth(text)<=width());
    assert(y>=0 && y+8<=height());
    lines.push_back({x,y,text});
  }
  void fillRect(int a,int b,int w,int h) override {
    assert(a>=0 && b>=0 && a+w<=width() && b+h<=height());
  }
  void drawRect(int a,int b,int w,int h) override { fillRect(a,b,w,h); }
  void drawXbm(int,int,const uint8_t*,int,int) override {}
  bool contains(const char* text) const {
    for (const auto& line:lines) if (line.text==text) return true;
    return false;
  }
};
struct Screen : UIScreen {
  uint8_t key=0;
  int render(DisplayDriver&) override { return 0; }
  bool handleInput(char c) override { key=static_cast<uint8_t>(c); return true; }
};
MomentaryButton user_btn(7,1000,true,true,true);
class UITask {
public:
  DisplayDriver* _display;
  UIScreen* curr=nullptr;
  UIScreen* msg_preview=nullptr;
  UIScreen* home=nullptr;
  UIScreen* john_reader=nullptr;
  uint32_t _auto_off=0,_next_refresh=0;
  int buzzer_changes=0;
  explicit UITask(DisplayDriver& display) : _display(&display) {}
  bool isJohnReaderActive() const { return john_reader && curr==john_reader; }
  void gotoHomeScreen() { curr=home; }
  void toggleBuzzer() { ++buzzer_changes; }
  char handleLongPress(char c) { return c; }
  char handleMultiClick(char,bool);
  char handleDoubleClick(char);
  char checkDisplayOn(char);
  void pollButton();
};
'''

SCENARIOS = r'''
void gesture(UITask& task,int count) {
  for (int tap=0;tap<count;++tap) {
    g_mock_pin_levels[7]=LOW; task.pollButton();
    g_mock_millis+=25; task.pollButton();
    g_mock_pin_levels[7]=HIGH; task.pollButton();
    g_mock_millis+=25; task.pollButton();
    if (tap+1<count) { g_mock_millis+=80; task.pollButton(); }
  }
  g_mock_millis+=280; task.pollButton();
}
int main() {
  resetArduinoMock();
  g_mock_pin_levels[7]=HIGH;
  user_btn.begin(); user_btn.enableQuadrupleClick();
  Display display;
  UITask task(display);
  Screen home,group;
  MsgPreviewScreen messages(&task);
  task.home=&home; task.msg_preview=task.curr=&messages; task.john_reader=&group;
  messages.addPreview(1,"Alice","public old",0,"Public");
  messages.addPreview(1,"Bob","public new",0,"Public");
  messages.addPreview(1,"Carol","second",2,"Second");
  messages.addPreview(0xFF,"Dan","direct message",-1,nullptr);
  auto expect=[&](const char* header,const char* body) {
    assert(task.curr==&messages);
    display.clear(); messages.render(display);
    assert(display.contains(header) && display.contains(body));
    assert(task.buzzer_changes==0);
  };
  expect("DM 1/1","direct message");
  gesture(task,3); expect("All 1/4","direct message");
  gesture(task,3); expect("Ch 0 1/2","public new");
  gesture(task,1); expect("Ch 0 2/2","public old");
  gesture(task,2); expect("Ch 0 1/2","public new");
  gesture(task,1); expect("Ch 0 2/2","public old");
  gesture(task,4); expect("All 1/4","direct message");
  gesture(task,3); expect("Ch 0 1/2","public new");
  gesture(task,3); expect("Ch 2 1/1","second"); // unused slot 1 is skipped
  gesture(task,3); expect("Ch 3 0/0","No buffered messages");
  gesture(task,3); expect("DM 1/1","direct message");
  gesture(task,3); expect("All 1/4","direct message");
  gesture(task,4); expect("DM 1/1","direct message");
  display.on=false;
  gesture(task,4); // waking consumes the entire gesture
  assert(display.on); expect("DM 1/1","direct message");
  gesture(task,4); expect("Ch 3 0/0","No buffered messages");
  gesture(task,4); expect("Ch 2 1/1","second");
  // Long press exits, without a delayed tap changing the home screen.
  g_mock_pin_levels[7]=LOW; task.pollButton();
  g_mock_millis+=25; task.pollButton();
  g_mock_millis+=1000; task.pollButton();
  assert(task.curr==&home);
  g_mock_pin_levels[7]=HIGH; task.pollButton();
  g_mock_millis+=25; task.pollButton();
  g_mock_millis+=280; task.pollButton();
  assert(home.key==0);
#if COMPANION_FEATURE_JOHN
  task.curr=&group;
  gesture(task,3); assert(group.key==KEY_DOWN);
  gesture(task,4); assert(group.key==KEY_UP);
  assert(task.buzzer_changes==0);
#endif
  task.curr=&home;
  gesture(task,3); assert(task.buzzer_changes==1);
  gesture(task,4); assert(task.buzzer_changes==2);
}
'''


class MessageNavigationTest(unittest.TestCase):
    def test_button_events_change_channels_and_keep_other_actions(self):
        source = (ROOT / "examples/companion_radio/ui-new/UITask.cpp").read_text()
        start = source.index(
            "  if (ev == BUTTON_EVENT_CLICK) {\n    c = checkDisplayOn(KEY_NEXT);",
            source.index("void UITask::loop()"))
        button_route = source[start:source.index("  #endif", start)]
        implementation = "\n".join(extract_braced(source, signature) for signature in (
            "char UITask::checkDisplayOn(", "char UITask::handleDoubleClick(",
            "char UITask::handleMultiClick("))
        implementation += "\n" + extract_braced(source, "class MsgPreviewScreen :") + ";\n"
        implementation += "void UITask::pollButton() { char c=0; int ev=user_btn.check();\n"
        implementation += button_route + "\nif(c && curr) curr->handleInput(c);\n}\n"
        for enabled in (0, 1):
            for signedness in ("-fsigned-char", "-funsigned-char"):
                with self.subTest(feature=enabled, signedness=signedness), tempfile.TemporaryDirectory() as temp:
                    binary = Path(temp) / "navigation"
                    result = subprocess.run([
                        "c++", "-std=c++17", signedness,
                        f"-DCOMPANION_FEATURE_JOHN={enabled}",
                        "-I" + str(ROOT / "src"), "-I" + str(ROOT / "test/mocks"),
                        "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                        "-x", "c++", "-", str(ROOT / "src/helpers/ui/MomentaryButton.cpp"),
                        "-o", str(binary),
                    ], input=PREAMBLE + implementation + SCENARIOS, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(binary)], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
