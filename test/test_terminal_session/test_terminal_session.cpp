#include <gtest/gtest.h>
#include <helpers/TerminalSession.h>
#include <string>
#include <vector>

TEST(TerminalSession, AcceptsFullContactCardsAndErasesCommandAfterExecution) {
  mesh::TerminalCommandQueue q;
  const std::string card = "import meshcore://" + std::string(510, 'a');
  ASSERT_EQ(mesh::TerminalCommandQueue::Accepted, q.submit(1, card.c_str(), card.size()));
  EXPECT_STREQ(card.c_str(), q.command);
  q.finish();
  EXPECT_FALSE(q.pending);
  for (char byte : q.command) EXPECT_EQ(0, byte);
}

TEST(TerminalSession, RetriesNeverExecuteAgainIncludingAfterLaterCommands) {
  mesh::TerminalCommandQueue q;
  EXPECT_EQ(mesh::TerminalCommandQueue::Accepted, q.submit(1, "send hello", 10));
  EXPECT_EQ(mesh::TerminalCommandQueue::Replay, q.submit(1, "send hello", 10));
  q.finish();
  EXPECT_EQ(mesh::TerminalCommandQueue::Accepted, q.submit(2, "list", 4));
  q.finish();
  EXPECT_EQ(mesh::TerminalCommandQueue::Replay, q.submit(1, "send hello", 10));
  EXPECT_FALSE(q.pending);
}

TEST(TerminalSession, RejectsConcurrentAndOutOfOrderCommandsWithoutChangingQueue) {
  mesh::TerminalCommandQueue q;
  EXPECT_EQ(mesh::TerminalCommandQueue::OutOfOrder, q.submit(2, "list", 4));
  EXPECT_EQ(mesh::TerminalCommandQueue::Accepted, q.submit(1, "card", 4));
  EXPECT_EQ(mesh::TerminalCommandQueue::Busy, q.submit(2, "list", 4));
  EXPECT_STREQ("card", q.command);
  q.finish();
  EXPECT_EQ(mesh::TerminalCommandQueue::OutOfOrder, q.submit(3, "list", 4));
  EXPECT_EQ(mesh::TerminalCommandQueue::OutOfOrder, q.submit(0, "list", 4));
}

TEST(TerminalSession, ValidatesLengthAndRejectsEmbeddedCommands) {
  mesh::TerminalCommandQueue q;
  const std::string limit(mesh::kTerminalCommandCapacity - 1, 'x');
  const std::string oversized(mesh::kTerminalCommandCapacity, 'x');
  EXPECT_EQ(mesh::TerminalCommandQueue::Invalid, q.submit(1, oversized.c_str(), oversized.size()));
  EXPECT_EQ(mesh::TerminalCommandQueue::Invalid, q.submit(1, "list\nreboot", 11));
  EXPECT_EQ(mesh::TerminalCommandQueue::Invalid, q.submit(1, "list\rreboot", 11));
  EXPECT_EQ(mesh::TerminalCommandQueue::Invalid, q.submit(1, "list\0reboot", 11));
  EXPECT_EQ(mesh::TerminalCommandQueue::Invalid, q.submit(1, "", 0));
  EXPECT_EQ(mesh::TerminalCommandQueue::Accepted, q.submit(1, limit.c_str(), limit.size()));
}

TEST(TerminalSession, PagesAFull350ContactListAndAllowsReadRetries) {
  std::vector<char> storage(mesh::kTerminalOutputCapacity);
  mesh::TerminalOutputBuffer buffer(storage.data(), storage.size());
  std::string input;
  for (int i = 0; i < 350; ++i) input += "  " + std::string(31, 'n') + " (Repeater) - 123 days ago\r\n";
  buffer.append(reinterpret_cast<const uint8_t*>(input.data()), input.size());
  std::string actual;
  uint64_t cursor = 0;
  bool lost;
  char page[1025], retry[1025];
  while (cursor < buffer.end()) {
    uint64_t old = cursor;
    const size_t n = buffer.read(cursor, page, sizeof(page), lost);
    ASSERT_FALSE(lost);
    ASSERT_GT(n, 0u);
    EXPECT_EQ(n, buffer.read(old, retry, sizeof(retry), lost));
    EXPECT_STREQ(page, retry);
    actual.append(page, n);
  }
  EXPECT_EQ(input, actual);
}

TEST(TerminalSession, ReportsExpiredOutputAndNeverWritesOutsideCapacity) {
  char storage[6] = {'!', 0, 0, 0, 0, '!'};
  mesh::TerminalOutputBuffer buffer(storage + 1, 4);
  buffer.append(reinterpret_cast<const uint8_t*>("abcdef"), 6);
  char out[8];
  uint64_t cursor = 0;
  bool lost;
  EXPECT_EQ(4u, buffer.read(cursor, out, sizeof(out), lost));
  EXPECT_TRUE(lost);
  EXPECT_STREQ("cdef", out);
  EXPECT_EQ('!', storage[0]);
  EXPECT_EQ('!', storage[5]);
  EXPECT_EQ(0u, buffer.read(cursor, out, sizeof(out), lost));
  EXPECT_FALSE(lost);
}

TEST(TerminalSession, KeepsUtf8IntactAcrossOutputPages) {
  char storage[32];
  mesh::TerminalOutputBuffer buffer(storage, sizeof(storage));
  const std::string input = "ab\xF0\x9F\x98\x80" "cd\xC3\xA9" "ef";
  buffer.append(reinterpret_cast<const uint8_t*>(input.data()), input.size());
  char page[6];
  uint64_t cursor = 0;
  bool lost;
  EXPECT_EQ(2u, buffer.read(cursor, page, sizeof(page), lost));
  EXPECT_STREQ("ab", page);
  std::string actual(page);
  while (cursor < buffer.end()) {
    const size_t n = buffer.read(cursor, page, sizeof(page), lost);
    ASSERT_GT(n, 0u);
    actual.append(page, n);
  }
  EXPECT_EQ(input, actual);
}

TEST(TerminalSession, GrowingAndShrinkingPreservesUnreadTextAndAbsoluteCursors) {
  char small[4], large[12], reduced[4], out[16];
  mesh::TerminalOutputBuffer buffer(small, sizeof(small));
  buffer.append(reinterpret_cast<const uint8_t*>("abcdef"), 6);
  buffer.rebind(large, sizeof(large));
  buffer.append(reinterpret_cast<const uint8_t*>("ghijkl"), 6);
  uint64_t cursor = 0;
  bool lost;
  EXPECT_EQ(10u, buffer.read(cursor, out, sizeof(out), lost));
  EXPECT_TRUE(lost);
  EXPECT_STREQ("cdefghijkl", out);
  buffer.rebind(reduced, sizeof(reduced));
  cursor = 8;
  EXPECT_EQ(4u, buffer.read(cursor, out, sizeof(out), lost));
  EXPECT_FALSE(lost);
  EXPECT_STREQ("ijkl", out);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
