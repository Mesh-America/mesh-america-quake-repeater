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

// Match the single-button UI: double click is Previous, click is Next, and
// hold is Enter/exit. Measure with the reader's font, including tiny panels.
inline ButtonReaderHintLayout makeButtonReaderHintLayout(
    DisplayDriver& text, int line_height, int bottom) {
  ButtonReaderHintLayout layout = {
      0, line_height, 1, {"<- 2tap  1tap ->  long press:exit", nullptr, nullptr}};
  if (text.getTextWidth(layout.lines[0]) > text.width()
      && text.getTextWidth("<-2tap 1tap-> hold:exit") <= text.width()) {
    layout.lines[0] = "<-2tap 1tap-> hold:exit";
  }
  if (text.getTextWidth(layout.lines[0]) > text.width()) {
    layout.line_count = 2;
    layout.lines[0] = "<- 2tap  1tap ->";
    layout.lines[1] = "long press:exit";
    if (text.getTextWidth(layout.lines[0]) > text.width()
        || text.getTextWidth(layout.lines[1]) > text.width()) {
      layout.line_count = 3;
      layout.lines[0] = "<- 2tap";
      layout.lines[1] = "1tap ->";
      layout.lines[2] = "hold:exit";
    }
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
