#pragma once
#include <helpers/IdentityStore.h>
#include <helpers/CompanionNotificationPolicy.h>
#include <new>

namespace mesh { namespace notify {
// Construct defaults in their existing storage. Assignment creates a full
// Settings temporary that stays on the loop stack throughout startup.
inline void resetSettings(Settings& prefs) {
  prefs.~Settings();
  ::new (static_cast<void*>(&prefs)) Settings();
}

// Separate versioned storage keeps old CompanionNodePrefs layouts unchanged.
// Record size detects an incompatible layout rather than applying stale pins.
inline uint32_t checksum(const Settings& prefs) {
  uint32_t h=2166136261UL;
  const uint8_t* p=reinterpret_cast<const uint8_t*>(&prefs);
  for(size_t i=0;i<sizeof(prefs);++i)h=(h^p[i])*16777619UL;
  return h;
}
inline bool readSettings(FILESYSTEM* fs,const char* path,Settings& prefs) {
  if(!fs)return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*fs);if(!file.open(path,FILE_O_READ))return false;
#else
  File file=fs->open(path,"r");if(!file)return false;
#endif
  uint8_t head[6]={};uint32_t digest=0;
  bool ok=file.size()==sizeof(prefs)+sizeof(head)+sizeof(digest)
    &&file.read(head,sizeof(head))==sizeof(head)&&!memcmp(head,"NTF1",4)
    &&(uint16_t(head[4])|(uint16_t(head[5])<<8))==sizeof(prefs)
    &&file.read(reinterpret_cast<uint8_t*>(&prefs),sizeof(prefs))==sizeof(prefs)
    &&file.read(reinterpret_cast<uint8_t*>(&digest),sizeof(digest))==sizeof(digest);
  file.close();return ok&&digest==checksum(prefs);
}

// Validate a record without holding another complete Settings on the stack.
// Publication also compares every byte with the requested settings, so a
// valid but different record cannot pass read-back verification.
inline bool verifySettingsFile(FILESYSTEM* fs, const char* path,
                               const Settings* expected = nullptr) {
  if (!fs) return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*fs);
  if (!file.open(path, FILE_O_READ)) return false;
#else
  File file = fs->open(path, "r");
  if (!file) return false;
#endif
  uint8_t head[6] = {};
  bool ok = file.size() == sizeof(Settings) + sizeof(head) + sizeof(uint32_t)
      && file.read(head, sizeof(head)) == sizeof(head)
      && !memcmp(head, "NTF1", 4)
      && (uint16_t(head[4]) | (uint16_t(head[5]) << 8)) == sizeof(Settings);
  uint8_t chunk[64];
  uint32_t digest = 2166136261UL;
  const uint8_t* expected_bytes = reinterpret_cast<const uint8_t*>(expected);
  for (size_t offset = 0; ok && offset < sizeof(Settings);) {
    size_t count = sizeof(Settings) - offset;
    if (count > sizeof(chunk)) count = sizeof(chunk);
    ok = file.read(chunk, count) == count
        && (!expected || !memcmp(chunk, expected_bytes + offset, count));
    if (!ok) break;
    for (size_t i = 0; i < count; ++i) digest = (digest ^ chunk[i]) * 16777619UL;
    offset += count;
  }
  uint32_t stored_digest = 0;
  ok = ok && file.read(reinterpret_cast<uint8_t*>(&stored_digest),
                       sizeof(stored_digest)) == sizeof(stored_digest)
      && stored_digest == digest;
  file.close();
  return ok;
}

inline bool writeSettings(FILESYSTEM* fs,const Settings& prefs) {
  if(!fs)return false;
  const char* path="/notify_prefs",*temporary="/notify_prefs.tmp",*backup="/notify_prefs.bak";
  fs->remove(temporary);
  if(fs->exists(temporary))return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  File file(*fs);if(!file.open(temporary,FILE_O_WRITE))return false;
#elif defined(ESP32_PLATFORM)
  File file=fs->open(temporary,"w",true);if(!file)return false;
#else
  File file=fs->open(temporary,"w");if(!file)return false;
#endif
  uint8_t head[]={ 'N','T','F','1',uint8_t(sizeof(prefs)),uint8_t(sizeof(prefs)>>8) };
  uint32_t digest=checksum(prefs);
  bool ok=file.write(head,sizeof(head))==sizeof(head)
    &&file.write(reinterpret_cast<const uint8_t*>(&prefs),sizeof(prefs))==sizeof(prefs)
    &&file.write(reinterpret_cast<uint8_t*>(&digest),sizeof(digest))==sizeof(digest);
  file.close();
  if(!ok||!verifySettingsFile(fs,temporary,&prefs))return false;
  if(fs->exists(path)) {
    if(verifySettingsFile(fs,path)) {
      if(fs->exists(backup)&&!fs->remove(backup))return false;
      if(!fs->rename(path,backup))return false;
    } else if(!fs->remove(path))return false; // Keep the good recovery copy.
  }
  if(!fs->rename(temporary,path)) {
    if(fs->exists(backup))fs->rename(backup,path);
    return false;
  }
  fs->remove(backup);return true;
}
static_assert(sizeof(Settings)<=3072,"Keep notification settings within the nRF52 RAM budget");
} }
