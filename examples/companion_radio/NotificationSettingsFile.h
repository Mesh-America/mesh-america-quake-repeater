#pragma once
#include <helpers/IdentityStore.h>
#include <helpers/CompanionNotificationPolicy.h>

namespace mesh { namespace notify {
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
  Settings checked;
  if(!ok||!readSettings(fs,temporary,checked)||memcmp(&checked,&prefs,sizeof(prefs)))return false;
  if(fs->exists(path)) {
    if(readSettings(fs,path,checked)) {
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
