#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <vector>

// Model the pinned FILE* buffering boundary, not NOR page operations or time.
// The production transaction and CRC implementation are compiled below.
class FileSystem;
struct Stream {
  FileSystem* fs;
  std::string path;
  bool writing;
  size_t buffer_size = 4096, position = 0, backend_position = 0, cursor = 0;
  std::vector<uint8_t> buffer;
};
class File {
  std::shared_ptr<Stream> stream;
public:
  File() = default;
  File(FileSystem* fs, const char* path, bool writing)
      : stream(std::make_shared<Stream>(Stream{fs, path, writing})) {}
  explicit operator bool() const { return bool(stream); }
  bool setBufferSize(size_t);
  size_t size() const;
  size_t read(uint8_t*, size_t);
  size_t write(const uint8_t*, size_t);
  void flush();
  void close() { flush(); stream.reset(); }
};
class FileSystem {
public:
  using Files = std::map<std::string, std::vector<uint8_t>>;
  Files files;
  unsigned reads = 0, writes = 0, backend_reads = 0, backend_writes = 0;
  unsigned config_calls = 0, closes = 0, renames = 0;
  unsigned fail_config = 0, short_read_call = 0, fail_rename = 0;
  size_t largest_read = 0, largest_backend_read = 0, max_write = SIZE_MAX;
  bool fail_open_read = false, fail_open_write = false;
  std::vector<Files> rename_snapshots;
  bool exists(const char* path) { return files.count(path) != 0; }
  bool remove(const char* path) { return files.erase(path) != 0; }
  bool rename(const char* from, const char* to) {
    ++renames;
    if (renames == fail_rename || !exists(from) || exists(to)) return false;
    files[to] = files.at(from);
    files.erase(from);
    rename_snapshots.push_back(files);
    return true;
  }
  File open(const char* path, const char* mode, bool = false) {
    const bool writing = *mode == 'w';
    if (writing ? fail_open_write : fail_open_read || !exists(path)) return File();
    if (writing) files[path].clear();
    return File(this, path, writing);
  }
};
bool File::setBufferSize(size_t size) {
  if (!stream) return false;
  if (++stream->fs->config_calls == stream->fs->fail_config) return false;
  assert(stream->buffer.empty() && stream->position == 0);
  stream->buffer_size = size;
  return true;
}
size_t File::size() const { return stream ? stream->fs->files.at(stream->path).size() : 0; }
void File::flush() {
  if (!stream || !stream->writing || stream->buffer.empty()) return;
  auto& fs = *stream->fs;
  ++fs.backend_writes;
  auto& target = fs.files.at(stream->path);
  target.insert(target.end(), stream->buffer.begin(), stream->buffer.end());
  stream->buffer.clear();
}
size_t File::write(const uint8_t* data, size_t length) {
  if (!stream || !stream->writing) return 0;
  auto& fs = *stream->fs;
  ++fs.writes;
  const size_t accepted = std::min(length, fs.max_write);
  size_t copied = 0;
  while (copied < accepted) {
    const size_t n = std::min(accepted - copied, stream->buffer_size - stream->buffer.size());
    stream->buffer.insert(stream->buffer.end(), data + copied, data + copied + n);
    copied += n;
    if (stream->buffer.size() == stream->buffer_size) flush();
  }
  return accepted;
}
size_t File::read(uint8_t* data, size_t length) {
  if (!stream || stream->writing) return 0;
  auto& fs = *stream->fs;
  ++fs.reads;
  fs.largest_read = std::max(fs.largest_read, length);
  if (fs.reads == fs.short_read_call) --length;
  const auto& source = fs.files.at(stream->path);
  size_t copied = 0;
  while (copied < length) {
    if (stream->cursor == stream->buffer.size()) {
      const size_t available = source.size() - std::min(source.size(), stream->backend_position);
      const size_t n = std::min(stream->buffer_size, available);
      if (!n) break;
      ++fs.backend_reads;
      fs.largest_backend_read = std::max(fs.largest_backend_read, n);
      stream->buffer.assign(source.begin() + stream->backend_position,
                            source.begin() + stream->backend_position + n);
      stream->backend_position += n;
      stream->cursor = 0;
    }
    const size_t n = std::min(length - copied, stream->buffer.size() - stream->cursor);
    memcpy(data + copied, stream->buffer.data() + stream->cursor, n);
    stream->cursor += n;
    copied += n;
  }
  stream->position += copied;
  return copied;
}
#define FILESYSTEM FileSystem
unsigned fixture_commit_calls = 0;
#include "transaction_under_test.h"
using Writer = mesh::ContactFileTransaction;
using Progress = Writer::CommitProgress;

std::vector<uint8_t> image(size_t bytes) {
  std::vector<uint8_t> result(bytes);
  for (size_t i = 0; i < bytes; ++i) result[i] = (i * 37 + i / 251) & 255;
  return result;
}
void writeImage(Writer& writer, const std::vector<uint8_t>& bytes) {
  for (size_t offset = 0; offset < bytes.size();) {
    const size_t count = std::min(size_t(152), bytes.size() - offset);
    assert(writer.write(bytes.data() + offset, count) == count);
    offset += count;
  }
}
unsigned effectiveBudget(unsigned requested) {
#if defined(ESP32_PLATFORM)
  return std::max(1U, std::min(8U, requested));
#else
  (void)requested;
  return 1;
#endif
}

struct Measurement {
  unsigned passes, logical_reads, backend_reads, max_pass_reads, max_pass_refills;
};
Measurement verify(size_t bytes, unsigned budget, bool use_default = false) {
  FileSystem fs;
  const auto old = image(21), next = image(bytes);
  fs.files["/contacts3"] = old;
  Writer writer(&fs, "/contacts3");
  assert(writer);
  writeImage(writer, next);
  unsigned passes = 0, max_reads = 0, max_refills = 0, data_passes = 0;
  Progress result = Progress::Pending;
  while (result == Progress::Pending) {
    const unsigned before_reads = fs.reads, before_backend = fs.backend_reads;
    const bool was_ready = writer.readyToPublish();
    result = use_default ? writer.serviceCommit() : writer.serviceCommit(true, budget);
    assert(++passes < 10000);
    const unsigned reads = fs.reads - before_reads, refills = fs.backend_reads - before_backend;
    max_reads = std::max(max_reads, reads);
    max_refills = std::max(max_refills, refills);
    const unsigned bound = use_default ? 1 : effectiveBudget(budget);
    assert(reads <= bound);
#if defined(ESP32_PLATFORM)
    assert(refills <= (bound + 1) / 2);
#endif
    if (reads) {
      ++data_passes;
      assert(!writer.readyToPublish()); // close/CRC comparison is a later pass
    }
    if (result == Progress::Pending) assert(fs.files.at("/contacts3") == old);
    else assert(was_ready); // publication never shares a CRC read pass
  }
  assert(result == Progress::Succeeded);
  const unsigned bound = use_default ? 1 : effectiveBudget(budget);
  assert(data_passes == (bytes + 64 * bound - 1) / (64 * bound));
  assert(passes == data_passes + 4);
  assert(fs.files.at("/contacts3") == next);
  assert(fs.reads == (bytes + 63) / 64);
  assert(fs.largest_read <= 64);
#if defined(ESP32_PLATFORM)
  assert(fs.largest_backend_read <= 128);
  assert(fs.backend_reads == (bytes + 127) / 128);
#endif
  return {passes, fs.reads, fs.backend_reads, max_reads, max_refills};
}
void limitsAndTails() {
  for (size_t bytes : {size_t(0), size_t(1), size_t(63), size_t(64), size_t(65),
                       size_t(127), size_t(128), size_t(129), size_t(511),
                       size_t(512), size_t(513), size_t(152 * 347)}) {
    verify(bytes, 1, true);
    for (unsigned budget : {0U, 1U, 2U, 8U, 9U, UINT32_MAX}) verify(bytes, budget);
  }
  FileSystem fs;
  Writer writer(&fs, "/sync");
  writeImage(writer, image(347 * 152));
  fixture_commit_calls = 0;
  assert(writer.commit());
  assert(fixture_commit_calls == 829); // actual commit() drains default-one passes
}
void readFailureAndCorruption() {
  const auto old = image(19), next = image(1536);
  for (unsigned failed_read = 1; failed_read <= 16; ++failed_read) {
    FileSystem fs;
    fs.files["/contacts3"] = old;
    Writer writer(&fs, "/contacts3");
    writeImage(writer, next);
    fs.short_read_call = failed_read;
    Progress result = Progress::Pending;
    for (unsigned i = 0; result == Progress::Pending && i < 100; ++i)
      result = writer.serviceCommit(true, 8);
    assert(result == Progress::Failed);
    assert(fs.files.at("/contacts3") == old && !fs.exists("/contacts3.tmp"));
  }
  for (unsigned corruption : {0U, 63U, 64U, 127U, 511U, 512U, 1535U}) {
    FileSystem fs;
    fs.files["/contacts3"] = old;
    Writer writer(&fs, "/contacts3");
    writeImage(writer, next);
    assert(writer.serviceCommit(true, 8) == Progress::Pending); // flush
    fs.files.at("/contacts3.tmp")[corruption] ^= 1;
    Progress result = Progress::Pending;
    while (result == Progress::Pending) result = writer.serviceCommit(true, 8);
    assert(result == Progress::Failed && fs.files.at("/contacts3") == old);
  }
}
void cancellationAndCrash() {
  const auto old = image(19), next = image(1536);
  for (unsigned stop = 0; stop < 8; ++stop) {
    FileSystem fs;
    fs.files["/contacts3"] = old;
    Writer writer(&fs, "/contacts3");
    writeImage(writer, next);
    for (unsigned i = 0; i < stop; ++i) {
      const auto result = writer.serviceCommit(true, 8);
      if (result == Progress::Succeeded) break;
    }
    if (fs.files.at("/contacts3") == old) {
      const unsigned reads = fs.reads;
      assert(writer.serviceCommit(false, 8) == Progress::Failed);
      assert(fs.reads == reads && !fs.exists("/contacts3.tmp"));
    }
    // Simulate boot from the durable map before any destructor can run.
    FileSystem reboot;
    reboot.files = fs.files;
    assert(Writer::recover(&reboot, "/contacts3"));
    assert(reboot.files.at("/contacts3") == old || reboot.files.at("/contacts3") == next);
  }
  for (unsigned failure : {0U, 1U, 2U, 3U}) {
    FileSystem fs;
    fs.files["/contacts3"] = old;
    Writer writer(&fs, "/contacts3");
    writeImage(writer, next);
    fs.fail_rename = failure;
    Progress result = Progress::Pending;
    while (result == Progress::Pending) result = writer.serviceCommit(true, 8);
    assert(result == (failure == 1 || failure == 2 ? Progress::Failed : Progress::Succeeded));
    assert(fs.files.at("/contacts3") == (result == Progress::Succeeded ? next : old));
    for (const auto& snapshot : fs.rename_snapshots) {
      FileSystem reboot;
      reboot.files = snapshot;
      assert(Writer::recover(&reboot, "/contacts3"));
      assert(reboot.files.at("/contacts3") == old || reboot.files.at("/contacts3") == next);
    }
  }
}
void setupFailures() {
  for (unsigned fail_config : {1U, 2U}) {
    FileSystem fs;
    fs.files["/contacts3"] = image(19);
    fs.fail_config = fail_config;
    Writer writer(&fs, "/contacts3");
    if (fail_config == 1) { assert(!writer); continue; }
    writeImage(writer, image(512));
    assert(writer.serviceCommit(true, 8) == Progress::Pending);
    assert(writer.serviceCommit(true, 8) == Progress::Failed);
    assert(fs.reads == 0 && fs.files.at("/contacts3") == image(19));
  }
  FileSystem fs;
  fs.files["/contacts3"] = image(19);
  Writer writer(&fs, "/contacts3");
  writeImage(writer, image(512));
  fs.fail_open_read = true;
  assert(writer.serviceCommit(true, 8) == Progress::Pending);
  assert(writer.serviceCommit(true, 8) == Progress::Failed);
  assert(fs.reads == 0 && fs.files.at("/contacts3") == image(19));
}
int main() {
  limitsAndTails();
  readFailureAndCorruption();
  cancellationAndCrash();
#if defined(ESP32_PLATFORM)
  setupFailures();
#endif
  const auto one = verify(347 * 152, 1), eight = verify(347 * 152, 8);
  printf("{\"one_passes\":%u,\"eight_passes\":%u,\"logical_reads\":%u,"
         "\"backend_reads\":%u,\"max_pass_reads\":%u,\"max_pass_refills\":%u}\n",
         one.passes, eight.passes, eight.logical_reads, eight.backend_reads,
         eight.max_pass_reads, eight.max_pass_refills);
}
