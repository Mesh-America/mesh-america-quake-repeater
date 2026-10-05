#if defined(ESP32_PLATFORM)
#include "BootFileSystem.h"
#include "BootFilePresence.h"
#include <dirent.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sdkconfig.h>

namespace mesh {
namespace {
constexpr size_t InventoryCapacity = 8192;
#if defined(CONFIG_SPIFFS_OBJ_NAME_LEN)
constexpr size_t MaximumPathLength = CONFIG_SPIFFS_OBJ_NAME_LEN - 1;
#else
constexpr size_t MaximumPathLength = 0;
#endif
Esp32BootFileSystem* active_inventory = nullptr;

// SPIFFS has flat names with implicit directories. Ambiguous path spellings
// must use the backend, which owns their interpretation.
bool normalPath(const char* path) {
  if (path == nullptr || path[0] != '/' || path[1] == 0) return false;
  const size_t length = strnlen(path, MaximumPathLength + 1);
  if (length > MaximumPathLength || path[length - 1] == '/') return false;
  const char* segment = path + 1;
  for (const char* cursor = segment;; ++cursor) {
    if (*cursor == '/' || *cursor == 0) {
      const size_t count = cursor - segment;
      if (count == 0 || (count == 1 && segment[0] == '.')
          || (count == 2 && segment[0] == '.' && segment[1] == '.')) return false;
      if (*cursor == 0) return true;
      segment = cursor + 1;
    }
  }
}
}  // namespace

Esp32BootFileSystem::Delegate::Delegate(Esp32BootFileSystem& owner,
                                      fs::FSImplPtr backend)
    : owner_(owner), backend_(backend) {
  if (backend_) mountpoint(backend_->mountpoint());
}

Esp32BootFileSystem::Esp32BootFileSystem(fs::FS& source)
    : fs::FS(source), delegate_(*this, _impl) {
  // Aliasing reuses the original shared_ptr control block; constructing the
  // view requires no allocation. Its delegate has static lifetime in the app.
  if (_impl) _impl = fs::FSImplPtr(_impl, &delegate_);
}

bool Esp32BootFileSystem::beginInventory() {
  // Never rebuild after a mutation: a returned writable handle can continue
  // changing the backend after open() has returned.
  if (inventory_attempted_) return false;
  inventory_attempted_ = true;
  if (active_inventory != nullptr || MaximumPathLength < 2
      || delegate_.mountpoint() == nullptr
      || strcmp(delegate_.mountpoint(), "/spiffs") != 0) return false;
  char* names = static_cast<char*>(::malloc(InventoryCapacity));
  if (names == nullptr) return false;
  DIR* directory = ::opendir(delegate_.mountpoint());
  if (directory == nullptr) {
    ::free(names);
    return false;
  }
  size_t used = 0;
  bool complete = false;
  while (true) {
    errno = 0;
    struct dirent* entry = ::readdir(directory);
    if (entry == nullptr) {
      complete = errno == 0;
      break;
    }
    const size_t raw_length = strnlen(entry->d_name, sizeof(entry->d_name));
    if (raw_length == 0 || raw_length == sizeof(entry->d_name)) break;
    const char* name = entry->d_name;
    if (name[0] == '/') ++name;
    const size_t length = raw_length - (name != entry->d_name ? 1 : 0);
    if (length == 0 || length + 1 > MaximumPathLength
        || length + 2 > InventoryCapacity - used) break;
    names[used] = '/';
    memcpy(names + used + 1, name, length + 1);
    if (!normalPath(names + used)) break;
    used += length + 2;
  }
  if (::closedir(directory) != 0) complete = false;
  if (!complete) {
    ::free(names);
    return false;
  }
  // Release the enumeration scratch before allocating persisted-state owners.
  // An empty inventory needs no retained storage; a small one keeps only names.
  if (used == 0) {
    ::free(names);
    names = nullptr;
  } else {
    char* compact = static_cast<char*>(::realloc(names, used));
    if (compact == nullptr) {
      ::free(names);
      return false;
    }
    names = compact;
  }
  names_ = names;
  names_used_ = used;
  inventory_active_ = true;
  active_inventory = this;
  detail::Esp32BootAbsenceRegistry& registry = detail::esp32BootAbsenceRegistry();
  registry.owner = static_cast<fs::FS*>(this);
  registry.context = this;
  registry.known_absent = &Esp32BootFileSystem::queryAbsent;
  return true;
}

void Esp32BootFileSystem::endInventory() {
  inventory_attempted_ = true;
  inventory_active_ = false;
  if (active_inventory == this) {
    active_inventory = nullptr;
    detail::Esp32BootAbsenceRegistry& registry = detail::esp32BootAbsenceRegistry();
    registry = detail::Esp32BootAbsenceRegistry();
  }
  ::free(names_);
  names_ = nullptr;
  names_used_ = 0;
}

void endEsp32BootFileInventory() {
  if (active_inventory != nullptr) active_inventory->endInventory();
}

bool Esp32BootFileSystem::queryAbsent(const void* context, const char* path) {
  return static_cast<const Esp32BootFileSystem*>(context)->knownAbsent(path);
}

bool Esp32BootFileSystem::knownAbsent(const char* path) const {
  if (!inventory_active_ || !normalPath(path)) return false;
  const size_t length = strlen(path);
  for (size_t offset = 0; offset < names_used_;) {
    const char* name = names_ + offset;
    const size_t name_length = strlen(name);
    // Exact filenames are case sensitive. Native SPIFFS directory prefix
    // enumeration is case insensitive, so keep its virtual directories too.
    if (strcmp(name, path) == 0
        || (name_length > length && name[length] == '/'
            && strncasecmp(name, path, length) == 0)) return false;
    offset += name_length + 1;
  }
  return true;
}

fs::FileImplPtr Esp32BootFileSystem::Delegate::open(const char* path,
                                                   const char* mode, bool create) {
  const bool readonly = mode != nullptr
      && (strcmp(mode, "r") == 0 || strcmp(mode, "rb") == 0) && !create;
  if (!readonly) owner_.endInventory();
  else if (owner_.knownAbsent(path)) return fs::FileImplPtr();
  return backend_->open(path, mode, create);
}

bool Esp32BootFileSystem::Delegate::exists(const char* path) {
  return !owner_.knownAbsent(path) && backend_->exists(path);
}

bool Esp32BootFileSystem::Delegate::rename(const char* from, const char* to) {
  owner_.endInventory();
  return backend_->rename(from, to);
}

bool Esp32BootFileSystem::Delegate::remove(const char* path) {
  owner_.endInventory();
  return backend_->remove(path);
}

bool Esp32BootFileSystem::Delegate::mkdir(const char* path) {
  owner_.endInventory();
  return backend_->mkdir(path);
}

bool Esp32BootFileSystem::Delegate::rmdir(const char* path) {
  owner_.endInventory();
  return backend_->rmdir(path);
}
}  // namespace mesh
#endif
