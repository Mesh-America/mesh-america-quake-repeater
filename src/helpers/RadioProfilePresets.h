#pragma once
#include <string.h>

namespace mesh { namespace cli {

// Use the ordinary tuple path for validation, persistence and remote replies.
inline const char* radio2PresetTuple(const char* name) {
  if (!strcmp(name, "mediamesh")) return "911.150,250,7,5,rxtx,auto";
  if (!strcmp(name, "mediamesh-range")) return "911.150,125,7,5,rxtx,auto";
  return nullptr;
}

} }
