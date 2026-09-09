#pragma once

#include "DisplayDriver.h"

namespace mesh {
namespace ui {

struct ButtonReaderHintLayout {
  int top;
  int line_height;
  int line_count;
  const char* lines[3];
};

// Alternate page and group navigation within the same footer. Measure both
// views so changing the hint never repaginates text or hides a message row.
inline ButtonReaderHintLayout makeButtonReaderHintLayout(
    DisplayDriver& text, int line_height, int bottom, bool show_groups = false) {
  ButtonReaderHintLayout layout = {
      0, line_height, 1, {"<- 2 tap  1 tap ->  long press: exit", nullptr, nullptr}};
  const char* group_line = "<<- 4 tap  3 tap ->>";
  if (text.getTextWidth(layout.lines[0]) > text.width()
      && text.getTextWidth("<-2 tap 1 tap-> hold: X") <= text.width()) {
    layout.lines[0] = "<-2 tap 1 tap-> hold: X";
  }
  if (text.getTextWidth(layout.lines[0]) > text.width()
      || text.getTextWidth(group_line) > text.width()) {
    layout.line_count = 2;
    layout.lines[0] = "<- 2 tap  1 tap ->";
    layout.lines[1] = "long press: exit";
    if (text.getTextWidth(layout.lines[0]) > text.width()
        || text.getTextWidth(group_line) > text.width()
        || text.getTextWidth(layout.lines[1]) > text.width()) {
      layout.line_count = 3;
      layout.lines[0] = "<- 2 tap";
      layout.lines[1] = "1 tap ->";
      layout.lines[2] = "hold: X";
    }
  }
  if (show_groups) {
    layout.lines[0] = layout.line_count < 3 ? group_line : "<<- 4 tap";
    if (layout.line_count == 3) layout.lines[1] = "3 tap ->>";
  }
  layout.top = bottom - layout.line_count * line_height;
  if (layout.top < 0) layout.top = 0;
  return layout;
}

inline void drawButtonReaderHint(DisplayDriver& text,
                                 const ButtonReaderHintLayout& layout) {
  text.setColor(UIColor::window_bkg);
  text.fillRect(0, layout.top, text.width(),
                layout.line_count * layout.line_height);
  text.setColor(UIColor::secondary_txt);
  for (int row = 0; row < layout.line_count; ++row) {
    text.drawTextCentered(text.width() / 2,
                          layout.top + row * layout.line_height,
                          layout.lines[row]);
  }
}

}  // namespace ui
}  // namespace mesh
