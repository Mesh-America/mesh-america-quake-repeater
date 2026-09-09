#include <gtest/gtest.h>
#include <helpers/LocalCliOutput.h>
#include <algorithm>
#include <string>

namespace {
struct FileState { std::string text; size_t reads = 0; bool closed = false, fail = false; };
struct File {
  FileState* state = nullptr;
  size_t offset = 0;
  explicit operator bool() const { return state && !state->closed; }
  size_t size() const { return state->text.size(); }
  void close() { if (state) state->closed = true; }
  int read(uint8_t* out, size_t count) {
    ++state->reads;
    if (state->fail) return -1;
    count = std::min(count, state->text.size() - offset);
    memcpy(out, state->text.data() + offset, count);
    offset += count;
    return count;
  }
};
struct Output : Stream {
  std::string text;
  int room = 40;
  size_t max_write = 7;
  int availableForWrite() override { return room; }
  size_t write(const uint8_t* data, size_t count) override {
    count = std::min(count, max_write);
    text.append(reinterpret_cast<const char*>(data), count);
    return count;
  }
};
void drain(mesh::LocalCliOutput<File>& job) {
  for (size_t n = 0; job.busy() && n < 100000; ++n) job.service();
  ASSERT_FALSE(job.busy());
}

TEST(LocalCliOutput, LargeFileIsLosslessWithPartialWritesAndLengthSnapshot) {
  FileState file{std::string(90000, 'x')};
  const auto expected = file.text;
  mesh::LocalCliOutput<File> job;
  Output output;
  ASSERT_TRUE(job.startFile(output, File{&file}));
  file.text += "new live log entries";
  drain(job);
  EXPECT_EQ(output.text, expected + "\r\n   EOF\r\n");
  EXPECT_TRUE(file.closed);
  EXPECT_EQ(file.reads, (expected.size() + 159) / 160);
}

TEST(LocalCliOutput, SlowClientDoesNotReadUnboundedDataOrStealOutput) {
  FileState file{std::string(4096, 'a')};
  mesh::LocalCliOutput<File> job;
  Output first, second;
  first.room = 0;
  ASSERT_TRUE(job.startFile(first, File{&file}));
  for (int i = 0; i < 1000; ++i) job.service();
  EXPECT_EQ(file.reads, 1u);
  EXPECT_TRUE(first.text.empty());
  EXPECT_TRUE(job.owns(first));
  EXPECT_FALSE(job.owns(second));
  FileState other{"different"};
  EXPECT_FALSE(job.startFile(second, File{&other}));
  EXPECT_TRUE(other.closed);
  first.room = 40;
  drain(job);
  EXPECT_EQ(first.text, file.text + "\r\n   EOF\r\n");
  EXPECT_TRUE(second.text.empty());
}

TEST(LocalCliOutput, CancelStopsOldOutputBeforeAReplacementConnection) {
  FileState old{"old connection secret"};
  mesh::LocalCliOutput<File> job;
  Output output;
  output.room = 0;
  ASSERT_TRUE(job.startFile(output, File{&old}));
  job.service();
  job.cancel();
  EXPECT_TRUE(old.closed);
  FileState replacement{"new connection"};
  ASSERT_TRUE(job.startFile(output, File{&replacement}));
  output.room = 40;
  drain(job);
  EXPECT_EQ(output.text, "new connection\r\n   EOF\r\n");
}

TEST(LocalCliOutput, AclRowsDrainCompletelyWithoutATableSizedBuffer) {
  mesh::LocalCliOutput<File> job;
  Output output;
  ASSERT_TRUE(job.startRows(output,
      [](void*, size_t& row, char* out, size_t capacity) -> size_t {
        if (row == 254) return 0;
        return snprintf(out, capacity, "03 %064u\r\n", static_cast<unsigned>(row++));
      }, nullptr, "ACL:\r\n"));
  drain(job);
  std::string expected = "ACL:\r\n";
  for (unsigned n = 0; n < 254; ++n) {
    char line[80];
    snprintf(line, sizeof(line), "03 %064u\r\n", n);
    expected += line;
  }
  EXPECT_EQ(output.text, expected);
}

TEST(LocalCliOutput, MissingAndFailedFilesEndWithoutBlockingTheNextCommand) {
  mesh::LocalCliOutput<File> job;
  Output output;
  ASSERT_TRUE(job.startFile(output, File{}));
  drain(job);
  EXPECT_EQ(output.text, "\r\n   EOF\r\n");
  output.text.clear();
  FileState file{"log"}; file.fail = true;
  ASSERT_TRUE(job.startFile(output, File{&file}));
  drain(job);
  EXPECT_EQ(output.text, "\r\nError: log read failed\r\n");
  EXPECT_TRUE(file.closed);
}
} // namespace

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
