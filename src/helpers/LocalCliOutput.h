#pragma once

#include <Arduino.h>
#include <string.h>

namespace mesh {

// A local listing belongs to its requesting connection. Advance one bounded
// chunk per mesh loop and retain unwritten bytes when the client is slow.
template<class FileHandle> class LocalCliOutput {
public:
  using RowReader = size_t (*)(void*, size_t&, char*, size_t);
private:
  Stream* _output = nullptr;
  FileHandle _file;
  size_t _remaining = 0;
  RowReader _rows = nullptr;
  void* _context = nullptr;
  size_t _row = 0;
  char _pending[160] = {};
  size_t _size = 0, _offset = 0;
  bool _ending = false;

public:
  LocalCliOutput() = default;
  explicit LocalCliOutput(FileHandle file) : _file(file) {}
  bool busy() const { return _output != nullptr; }
  bool owns(const Stream& output) const { return _output == &output; }
  void cancel() {
    if (_file) _file.close();
    _output = nullptr;
    _rows = nullptr;
    _context = nullptr;
    _remaining = _size = _offset = _row = 0;
    _ending = false;
    memset(_pending, 0, sizeof(_pending));
  }
  bool startFile(Stream& output, FileHandle file) {
    if (busy()) { if (file) file.close(); return false; }
    _output = &output;
    _file = file;
    // Snapshot the length: live logging cannot extend this dump indefinitely.
    _remaining = _file ? _file.size() : 0;
    return true;
  }
  bool startRows(Stream& output, RowReader rows, void* context,
                 const char* header) {
    if (busy()) return false;
    _output = &output;
    _rows = rows;
    _context = context;
    _size = snprintf(_pending, sizeof(_pending), "%s", header);
    if (_size >= sizeof(_pending)) _size = sizeof(_pending) - 1;
    return true;
  }
  void service() {
    if (!busy()) return;
    if (_offset == _size) {
      _size = _offset = 0;
      if (_ending) { cancel(); return; }
      if (_rows) {
        _size = _rows(_context, _row, _pending, sizeof(_pending));
        if (_size == 0) { cancel(); return; }
        if (_size >= sizeof(_pending)) { cancel(); return; }
      } else if (_remaining) {
        const size_t count = _remaining < sizeof(_pending)
            ? _remaining : sizeof(_pending);
        const int got = _file.read(reinterpret_cast<uint8_t*>(_pending), count);
        if (got <= 0) {
          _size = snprintf(_pending, sizeof(_pending), "\r\nError: log read failed\r\n");
          _ending = true;
        } else {
          _size = static_cast<size_t>(got);
          _remaining -= _size;
        }
      } else {
        _size = snprintf(_pending, sizeof(_pending), "\r\n   EOF\r\n");
        _ending = true;
      }
    }
    const int room = _output->availableForWrite();
    if (room <= 0) return;
    const size_t count = _size - _offset < static_cast<size_t>(room)
        ? _size - _offset : static_cast<size_t>(room);
    _offset += _output->write(
        reinterpret_cast<const uint8_t*>(_pending + _offset), count);
  }
};
} // namespace mesh
