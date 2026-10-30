#include <helpers/ui/CompanionMessageHistory.h>
#include <cassert>
#include <cstring>

using History = mesh::ui::CompanionMessageHistory<3, 78>;

// Own-message styling uses the Entry's existing alignment padding. Every
// other board retains the same 32-message history allocation.
struct PreviousEntry {
  uint64_t heard_millis;
  int queue_index;
  bool unread;
  int channel_idx;
  char channel_name[32];
  char origin[62];
  char message[78];
};
static_assert(sizeof(History::Entry) == sizeof(PreviousEntry),
              "own-message metadata changed the shared history RAM budget");

int main() {
  History history;
  history.add(100, 0, "Public", "Ch 0 Public [1h]:", "Alice: received", 2);
  history.add(200, 0, "Public", "Self", "sent", -1, true);
  assert(history.count() == 2 && history.unreadCount() == 1);
  assert(history.newest(0)->own_sent && !history.newest(0)->unread);
  assert(history.newest(0)->queue_index == -1);
  assert(!history.newest(1)->own_sent && history.newest(1)->unread);

  // App queue reads shift only received-message indices. They do not make a
  // locally sent message look pending or mark the received one as read.
  history.queueRemoved(0);
  assert(history.newest(0)->queue_index == -1);
  assert(history.newest(1)->queue_index == 1);
  assert(history.unreadCount() == 1);
  history.queueRemoved(1);
  assert(history.newest(1)->queue_index == -1);
  assert(history.unreadCount() == 1);

  history.add(300, -1, "", "Bob [direct]:", "direct", 0);
  history.add(400, 0, "Public", "Self", "new sent", -1, true);
  assert(history.count() == 3 && history.unreadCount() == 1);
  assert(std::strcmp(history.newest(0)->message, "new sent") == 0);
  assert(history.newest(2)->own_sent && !history.newest(2)->unread);
  history.markRead(history.newest(1));
  assert(history.unreadCount() == 0);
}
