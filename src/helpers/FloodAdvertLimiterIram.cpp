#include "FloodAdvertLimiter.h"

#if FLOOD_ADVERT_IRAM_WORD_STORAGE
namespace mesh {

// The pinned SDK collects .iram.bss.* in its existing NOLOAD IRAM section,
// then reserves it through _iram_end. These are distinct SRAM0 words, not a
// D/IRAM alias already counted as byte-accessible heap. Never expose a byte
// pointer into this bank to memcpy, crypto, a transport or a DMA engine.
static_assert(FLOOD_ADVERT_SOURCE_SLOTS == 128, "Retain every advert-source record");
alignas(4) static uint32_t iram_advert_words[128 * 35]
    __attribute__((section(".iram.bss.mesh_flood_advert")));

volatile uint32_t* floodAdvertIramBank() { return iram_advert_words; }

const void*& FloodAdvertLimiter::iramOwner() {
  // Ordinary BSS clears this on every boot, including deep-sleep wake. The
  // NOLOAD word bank is explicitly reset before any record is consumed.
  static const void* owner = nullptr;
  return owner;
}

FloodAdvertLimiter::FloodAdvertLimiter(volatile uint32_t* entries, size_t capacity)
    : _entries(entries), _capacity(capacity) {
  if (!entries || reinterpret_cast<uintptr_t>(entries) % 4
      || capacity != FLOOD_ADVERT_SOURCE_SLOTS || iramOwner()) abort();
  iramOwner() = this;
}

FloodAdvertLimiter::~FloodAdvertLimiter() {
  if (iramOwner() != this) abort();
  iramOwner() = nullptr;
}

void FloodAdvertLimiter::requireIramOwner(size_t index) const {
  if (iramOwner() != this || index >= _capacity) abort();
}

void FloodAdvertLimiter::loadEntry(size_t index, Entry& dest) const {
  requireIramOwner(index);
  for (size_t word = 0; word < EntryWords; ++word) {
    const uint32_t value = _entries[index * EntryWords + word];
    memcpy(reinterpret_cast<unsigned char*>(&dest) + word * 4, &value, 4);
  }
}

void FloodAdvertLimiter::storeEntry(size_t index, const Entry& source) {
  requireIramOwner(index);
  for (size_t word = 0; word < EntryWords; ++word) {
    uint32_t value;
    memcpy(&value, reinterpret_cast<const unsigned char*>(&source) + word * 4, 4);
    _entries[index * EntryWords + word] = value;
  }
}

FloodAdvertLimiter::EntryTail FloodAdvertLimiter::readTail(size_t index) const {
  requireIramOwner(index);
  const uint32_t value = _entries[index * EntryWords + offsetof(Entry, forwarded) / 4];
  EntryTail tail;
  memcpy(&tail, &value, sizeof(tail));
  return tail;
}

void FloodAdvertLimiter::writeTail(size_t index, EntryTail tail) {
  requireIramOwner(index);
  uint32_t value;
  memcpy(&value, &tail, sizeof(value));
  _entries[index * EntryWords + offsetof(Entry, forwarded) / 4] = value;
}

uint32_t FloodAdvertLimiter::readStamp(size_t index, size_t offset) const {
  requireIramOwner(index);
  if (offset % 4 || offset >= sizeof(Entry)) abort();
  return _entries[index * EntryWords + offset / 4];
}

bool FloodAdvertLimiter::keyMatches(size_t index, const uint8_t* key, size_t length) const {
  requireIramOwner(index);
  if (length != PREFIX_BYTES && length != PUB_KEY_SIZE) abort();
  uint32_t scratch[PUB_KEY_SIZE / 4];
  for (size_t word = 0; word < (length + 3) / 4; ++word)
    scratch[word] = _entries[index * EntryWords + word];
  return memcmp(scratch, key, length) == 0;
}

size_t FloodAdvertLimiter::findIndex(const uint8_t* key) const {
  for (size_t i = 0; i < _capacity; ++i)
    if ((readTail(i).flags & ACTIVE) && keyMatches(i, key, PUB_KEY_SIZE)) return i;
  return _capacity;
}

void FloodAdvertLimiter::reset() {
  if (iramOwner() != this) abort();
  // Volatile uint32_t stores are essential: a byte memset is invalid in IRAM.
  for (size_t word = 0; word < _capacity * EntryWords; ++word) _entries[word] = 0;
  _last_sweep = 0;
}

void FloodAdvertLimiter::clear(const uint8_t* key) {
  const size_t i = findIndex(key);
  if (i == _capacity) return;
  EntryTail tail = readTail(i);
  tail.flags = 0;
  writeTail(i, tail);
}

void FloodAdvertLimiter::refresh(uint32_t now) {
  Entry entry;
  for (size_t i = 0; i < _capacity; ++i) {
    if (!(readTail(i).flags & ACTIVE)) continue;
    loadEntry(i, entry);
    advance(entry, now);
    storeEntry(i, entry);
  }
  _last_sweep = now;
}

bool FloodAdvertLimiter::needsShorterPath(const uint8_t* key, uint8_t hops, uint32_t now) {
  refresh(now);
  const size_t i = findIndex(key);
  return i != _capacity && hops < readTail(i).min_hops;
}

void FloodAdvertLimiter::noteKnownCopy(const uint8_t* key, const uint8_t* hash, uint32_t now) {
  refresh(now);
  const size_t i = findIndex(key);
  if (i == _capacity) return;
  Entry entry;
  loadEntry(i, entry);
  if (hashIndex(entry, hash) >= 0) {
    entry.last_heard = now;
    storeEntry(i, entry);
  }
}

void FloodAdvertLimiter::observe(const uint8_t* key, const uint8_t* hash, uint8_t hops,
                                 uint32_t now, bool previously_seen) {
  refresh(now);
  size_t index = findIndex(key);
  Entry entry;
  if (index == _capacity) {
    if (previously_seen) return;
    uint32_t start = now;
    for (size_t i = 0; i < _capacity; ++i) {
      EntryTail tail = readTail(i);
      if ((tail.flags & ACTIVE) && keyMatches(i, key, PREFIX_BYTES)) {
        start = readStamp(i, offsetof(Entry, window_start));
        if (tail.min_hops < hops) hops = tail.min_hops;
        break;
      }
    }
    size_t oldest = _capacity;
    uint32_t oldest_heard = 0;
    for (size_t i = 0; i < _capacity; ++i) {
      EntryTail tail = readTail(i);
      if (!(tail.flags & ACTIVE)) { index = i; break; }
      const uint32_t heard = readStamp(i, offsetof(Entry, last_heard));
      if (!(tail.flags & (BAD | PREVIOUS_OVER)) && tail.count <= allowance(tail.min_hops)
          && (oldest == _capacity || uint32_t(now - heard) > uint32_t(now - oldest_heard))) {
        oldest = i;
        oldest_heard = heard;
      }
    }
    if (index == _capacity) index = oldest;
    if (index == _capacity) return;
    memset(&entry, 0, sizeof(entry));
    memcpy(entry.key, key, PUB_KEY_SIZE);
    entry.window_start = start;
    entry.min_hops = hops;
    entry.flags = ACTIVE;
  } else {
    loadEntry(index, entry);
  }
  entry.last_heard = now;
  if (hops < entry.min_hops) entry.min_hops = hops;
  storeEntry(index, entry);
  for (size_t i = 0; i < _capacity; ++i) {
    EntryTail tail = readTail(i);
    if ((tail.flags & ACTIVE) && keyMatches(i, key, PREFIX_BYTES) && hops < tail.min_hops) {
      tail.min_hops = hops;
      writeTail(i, tail);
    }
  }
  loadEntry(index, entry);
  if (previously_seen || hashIndex(entry, hash) >= 0 || entry.count == HASH_SLOTS) return;
  memcpy(entry.hashes[entry.count++], hash, MAX_HASH_SIZE);
  if (entry.count > allowance(entry.min_hops)) {
    entry.last_violation = now;
    if (entry.flags & PREVIOUS_OVER) entry.flags |= BAD;
  }
  storeEntry(index, entry);
}

FloodAdvertLimiter::Decision FloodAdvertLimiter::check(const uint8_t* key, const uint8_t* hash,
                                                      uint32_t now) {
  refresh(now);
  const size_t index = findIndex(key);
  if (index == _capacity) return Decision::Capacity;
  Entry entry;
  loadEntry(index, entry);
  const int idx = hashIndex(entry, hash);
  if (idx < 0) return Decision::Quota;
  if (entry.forwarded & (1U << idx)) return Decision::Duplicate;
  if ((entry.flags & (BAD | HAS_FORWARDED)) == (BAD | HAS_FORWARDED)
      && uint32_t(now - entry.last_forwarded) < BAD_INTERVAL_MS) return Decision::BadList;
  uint8_t hops = entry.min_hops;
  unsigned forwarded = 0;
  for (size_t i = 0; i < _capacity; ++i) {
    EntryTail other = readTail(i);
    if (!(other.flags & ACTIVE) || !keyMatches(i, key, PREFIX_BYTES)) continue;
    if (other.min_hops < hops) hops = other.min_hops;
    for (uint16_t bits = other.forwarded; bits; bits &= bits - 1) ++forwarded;
  }
  return forwarded < allowance(hops) ? Decision::Allow : Decision::Quota;
}

void FloodAdvertLimiter::commit(const uint8_t* key, const uint8_t* hash, uint32_t now) {
  const size_t i = findIndex(key);
  if (i == _capacity) return;
  Entry entry;
  loadEntry(i, entry);
  const int idx = hashIndex(entry, hash);
  if (idx < 0) return;
  entry.forwarded |= uint16_t(1U << idx);
  entry.last_forwarded = now;
  entry.flags |= HAS_FORWARDED;
  storeEntry(i, entry);
}

bool FloodAdvertLimiter::isBad(const uint8_t* key, uint32_t now) {
  refresh(now);
  const size_t i = findIndex(key);
  return i != _capacity && (readTail(i).flags & BAD);
}

size_t FloodAdvertLimiter::listLimited(uint32_t now, size_t offset, LimitedEntry* dest, size_t count) {
  refresh(now);
  size_t total = 0;
  Entry entry;
  for (size_t i = 0; i < _capacity; ++i) {
    if (!(readTail(i).flags & ACTIVE)) continue;
    loadEntry(i, entry);
    unsigned forwarded = 0;
    uint8_t hops = entry.min_hops;
    for (size_t j = 0; j < _capacity; ++j) {
      EntryTail other = readTail(j);
      if (!(other.flags & ACTIVE) || !keyMatches(j, entry.key, PREFIX_BYTES)) continue;
      if (other.min_hops < hops) hops = other.min_hops;
      for (uint16_t bits = other.forwarded; bits; bits &= bits - 1) ++forwarded;
    }
    const uint8_t quota = allowance(hops);
    uint8_t reasons = 0;
    if (forwarded >= quota) reasons |= WindowQuota;
    if (entry.count == HASH_SLOTS) reasons |= ReceiveHistory;
    if (entry.flags & BAD) reasons |= BadListRule;
    if (!reasons) continue;
    if (dest && total >= offset && total - offset < count) {
      LimitedEntry& out = dest[total - offset];
      memcpy(out.key, entry.key, PUB_KEY_SIZE);
      out.forwarded = forwarded;
      out.quota = quota;
      out.hops = hops;
      out.reasons = reasons;
      out.wait_ms = reasons & (WindowQuota | ReceiveHistory)
          ? WINDOW_MS - uint32_t(now - entry.window_start) : 0;
      out.recovery_ms = 0;
      if (reasons & BadListRule) {
        out.recovery_ms = RECOVERY_MS - uint32_t(now - entry.last_violation);
        if (entry.flags & HAS_FORWARDED) {
          const uint32_t bad_wait = BAD_INTERVAL_MS - uint32_t(now - entry.last_forwarded);
          if (bad_wait > out.wait_ms) out.wait_ms = bad_wait;
        }
      }
    }
    ++total;
  }
  return total;
}

} // namespace mesh
#endif
