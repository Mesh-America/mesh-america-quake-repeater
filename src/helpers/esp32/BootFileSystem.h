#pragma once

#if defined(ESP32_PLATFORM)
#include <FS.h>
#include <FSImpl.h>

namespace mesh {

// This view must outlive every user of the filesystem (use static storage).
// Only known absence is cached; files and FileImpl handles stay SDK-owned.
class Esp32BootFileSystem : public fs::FS {
 public:
  explicit Esp32BootFileSystem(fs::FS& source);
  ~Esp32BootFileSystem() { endInventory(); }
  Esp32BootFileSystem(const Esp32BootFileSystem&) = delete;
  Esp32BootFileSystem& operator=(const Esp32BootFileSystem&) = delete;
  bool beginInventory();
  void endInventory();
  bool isInventoryActive() const { return inventory_active_; }

 private:
  class Delegate : public fs::FSImpl {
   public:
    Delegate(Esp32BootFileSystem& owner, fs::FSImplPtr backend);
    fs::FileImplPtr open(const char* path, const char* mode, bool create) override;
    bool exists(const char* path) override;
    bool rename(const char* from, const char* to) override;
    bool remove(const char* path) override;
    bool mkdir(const char* path) override;
    bool rmdir(const char* path) override;

   private:
    Esp32BootFileSystem& owner_;
    fs::FSImplPtr backend_;
  };

  static bool queryAbsent(const void* context, const char* path);
  bool knownAbsent(const char* path) const;
  Delegate delegate_;
  char* names_ = nullptr;
  size_t names_used_ = 0;
  bool inventory_active_ = false;
  bool inventory_attempted_ = false;
};

// Stop before starting any task that can access or modify persisted state.
void endEsp32BootFileInventory();
}  // namespace mesh
#endif
