#include <helpers/ui/SSD1306Display.h>
#include <cassert>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
void save(const char* file) {
  auto& c=*Adafruit_SSD1306::last;
  std::ofstream f(file);
  f << "P1\n128 64\n";
  for (int y=0;y<64;y++) { for (int x=0;x<128;x++) f << c.getPixel(x,y) << ' '; f << '\n'; }
}
int main(int argc, char** argv) {
  SSD1306Display d;
  assert(d.begin());
  auto& c=*Adafruit_SSD1306::last;
  const char* message="GIANT KILLER: Out on the Mercerwood mesh today, just the V4 and a small battery Checking the smaller font so the rest of this message is visible. 0123456789 END";
  d.startFrame();
  d.setCursor(0,0); d.print("Message 3/29");
  d.setCursor(86,0); d.print("1m ago");
  d.drawRect(0,11,128,1);
  d.setCursor(0,14); d.print("Ch 0 Public [4h]:");
  d.setCursor(0,25);
#if UI_SSD1306_PICOPIXEL_MESSAGES == 1
  d.printWordWrap(message,128);
#else
  d.print(std::string(message,77).c_str());
#endif
  if (argc > 1) save(argv[1]);
#if UI_SSD1306_PICOPIXEL_MESSAGES == 1
  std::string shown;
  for (const auto& g:c.glyphs) {
    shown += g.c;
    if (g.w && g.h) assert(g.x>=0 && g.x+g.w<=128 && g.y>=25 && g.y+g.h<=64);
  }
  assert(shown==message);
  assert(c.outside==0);
  assert(d.getTextWidth("ABC")==18); // regular font restored
  d.setCursor(0,0); d.print("Regular font");
  assert(d.getTextWidth("ABC")==18);
  int checks=1;
  for (int rotation:{0,90,180,270}) for (int top:{0,25,55,58,59,63,64}) {
    d.setRotationDegrees(rotation);
    d.startFrame(); d.setCursor(0,top);
    d.printWordWrap(std::string(160,'W').c_str(),d.width());
    for (const auto& g:c.glyphs) {
      if (g.w && g.h) assert(g.x>=0 && g.x+g.w<=d.width() && g.y>=top && g.y+g.h<=d.height());
    }
    if (!c.glyphs.empty()) {
      std::string row;
      for (const auto& g:c.glyphs) row += g.c;
      while (!row.empty() && row.back()==' ') row.pop_back();
      assert(row==std::string(160, 'W') || (row.size()>=3 && row.substr(row.size()-3)=="..."));
    }
    assert(c.outside==0);
    ++checks;
  }
  d.setRotationDegrees(0);
  for (int ch=32;ch<=126;ch++) {
    d.startFrame(); d.setCursor(0,25);
    d.printWordWrap(std::string(160,char(ch)).c_str(),128);
    assert(c.outside==0);
    ++checks;
  }
  d.startFrame(); d.setCursor(0,25);
  d.printWordWrap("A\xDB" "B",128);
  assert(c.glyphs.size()==3 && c.glyphs[1].c=='?');
  std::cout << "Checks: " << checks+1 << "; sample characters: " << shown.size() << "; sample: " << shown << '\n';
#endif
}
