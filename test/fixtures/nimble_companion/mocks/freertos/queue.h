#pragma once
#include "FreeRTOS.h"
#include <deque>
#include <vector>
#include <cstring>
struct StaticQueue_t {
  size_t capacity = 0, size = 0;
  std::deque<std::vector<uint8_t>> frames;
};
using QueueHandle_t = StaticQueue_t*;
inline QueueHandle_t xQueueCreateStatic(size_t capacity, size_t size,
                                        uint8_t*, StaticQueue_t* queue) {
  queue->capacity = capacity;
  queue->size = size;
  queue->frames.clear();
  return queue;
}
inline size_t uxQueueMessagesWaiting(QueueHandle_t queue) { return queue->frames.size(); }
inline int xQueueReset(QueueHandle_t queue) { queue->frames.clear(); return pdTRUE; }
inline int xQueueSend(QueueHandle_t queue, const void* value, int) {
  if (queue->frames.size() == queue->capacity) return 0;
  const auto* bytes = static_cast<const uint8_t*>(value);
  queue->frames.emplace_back(bytes, bytes + queue->size);
  return pdTRUE;
}
inline int xQueueReceive(QueueHandle_t queue, void* value, int) {
  if (queue->frames.empty()) return 0;
  memcpy(value, queue->frames.front().data(), queue->size);
  queue->frames.pop_front();
  return pdTRUE;
}
