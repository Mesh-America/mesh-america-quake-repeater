"""Run the production notification file format against a fault-injected filesystem."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''#pragma once
#include <map>
#include <string>
#include <vector>
#include <cstring>
#include <cstdint>
#include <algorithm>
struct FakeFS;
struct File {
  FakeFS* fs = nullptr;
  std::string name;
  size_t cursor = 0;
  File() = default;
  explicit File(FakeFS& storage):fs(&storage) {}
  File(FakeFS* storage,const char* path):fs(storage),name(path) {}
  explicit operator bool() const { return fs != nullptr; }
  bool open(const char*,int);
  size_t size() const;
  size_t read(uint8_t*,size_t);
  size_t write(const uint8_t*,size_t);
  void close() {}
};
struct FakeFS {
  std::map<std::string,std::vector<uint8_t>> files;
  bool fail_write=false,fail_publish=false;
  int read_limit=-1,write_limit=-1;
  size_t largest_read=0;
  std::string fail_remove_path,fail_rename_from;
  std::vector<uint8_t> replacement_tmp;
  void beforeRead(const char* path) {
    if(std::string(path)=="/notify_prefs.tmp"&&!replacement_tmp.empty()) {
      files[path]=replacement_tmp;replacement_tmp.clear();
    }
  }
  bool exists(const char* path) { return files.count(path); }
  bool remove(const char* path) {
    if(fail_remove_path==path)return false;
    files.erase(path);return true;
  }
  bool rename(const char* from,const char* to) {
    if(fail_publish && std::string(from)=="/notify_prefs.tmp")return false;
    if(fail_rename_from==from)return false;
    if(!exists(from)||exists(to))return false;
    files[to]=files[from];files.erase(from);return true;
  }
  File open(const char* path,const char* mode,bool=false) {
    if(*mode=='w')files[path].clear();
    else beforeRead(path);
    return exists(path)?File(this,path):File();
  }
};
inline bool File::open(const char* path,int mode) {
  if(mode==2)fs->files[path].clear();
  else fs->beforeRead(path);
  if(!fs->exists(path))return false;
  name=path;cursor=0;return true;
}
inline size_t File::size() const { return fs->files.at(name).size(); }
inline size_t File::read(uint8_t* out,size_t n) {
  fs->largest_read=std::max(fs->largest_read,n);
  if(fs->read_limit>=0) {
    if(cursor>=size_t(fs->read_limit))return 0;
    n=std::min(n,size_t(fs->read_limit)-cursor);
  }
  auto& bytes=fs->files[name];n=std::min(n,bytes.size()-cursor);
  memcpy(out,bytes.data()+cursor,n);cursor+=n;return n;
}
inline size_t File::write(const uint8_t* in,size_t n) {
  if(fs->fail_write)return 0;
  if(fs->write_limit>=0) {
    if(cursor>=size_t(fs->write_limit))return 0;
    n=std::min(n,size_t(fs->write_limit)-cursor);
  }
  auto& bytes=fs->files[name];bytes.resize(cursor+n);
  memcpy(bytes.data()+cursor,in,n);cursor+=n;return n;
}
#define FILESYSTEM FakeFS
#define FILE_O_READ 1
#define FILE_O_WRITE 2
'''
PROGRAM = r'''
#include <cassert>
#include "NotificationSettingsFile.h"
using namespace mesh::notify;
static void resetDefaults() {
  Settings prefs;
  prefs.enabled=1;prefs.outputs=0;
  for(auto& rule:prefs.rules) {
    memset(rule.selector.key,0xa5,sizeof(rule.selector.key));
    rule.selector.kind=Channel;rule.selector.when=Offline;
    for(auto* pulse:{&rule.vibration,&rule.led,&rule.gpio}) {
      pulse->count=MAX_PULSES;for(auto& ms:pulse->ms)ms=123;
    }
    memset(rule.sound,'a',sizeof(rule.sound));
    rule.fields=0x1ff;rule.repeat=3;rule.gap=17;
    rule.pin=21;rule.screen=1;rule.stop=Never;rule.used=1;rule.remote=1;
  }
  const auto* address=&prefs;
  resetSettings(prefs);
  assert(address==&prefs&&prefs.enabled==0&&prefs.outputs==31);
  for(const auto& rule:prefs.rules) {
    assert(rule.selector.kind==All&&rule.selector.when==Any);
    for(auto b:rule.selector.key)assert(b==0);
    for(const auto* pulse:{&rule.vibration,&rule.led,&rule.gpio}) {
      assert(pulse->count==0);for(auto ms:pulse->ms)assert(ms==0);
    }
    for(auto c:rule.sound)assert(c==0);
    assert(rule.fields==0&&rule.repeat==1&&rule.gap==500);
    assert(rule.pin==-1&&rule.screen==-1&&rule.stop==Button);
    assert(rule.used==0&&rule.remote==0);
  }
}

static void boundedVerificationAndFaults() {
  FakeFS fs;Settings prefs;
  prefs.enabled=1;prefs.outputs=7;
  assert(writeSettings(&fs,prefs));
  const auto original=fs.files.at("/notify_prefs");
  assert(verifySettingsFile(&fs,"/notify_prefs",&prefs));
  prefs.outputs=3;
  assert(verifySettingsFile(&fs,"/notify_prefs"));
  assert(!verifySettingsFile(&fs,"/notify_prefs",&prefs));

  // Even a substituted record with its own valid checksum must not publish.
  FakeFS other;Settings different;different.outputs=9;
  assert(writeSettings(&other,different));
  fs.replacement_tmp=other.files.at("/notify_prefs");
  assert(!writeSettings(&fs,prefs));
  assert(fs.files.at("/notify_prefs")==original);

  for(int limit:{0,5,6,7,63,70,int(sizeof(prefs)+6),int(sizeof(prefs)+9)}) {
    fs.read_limit=limit;fs.largest_read=0;
    assert(!writeSettings(&fs,prefs));
    assert(fs.files.at("/notify_prefs")==original);
    assert(fs.largest_read<=128);
  }
  fs.read_limit=-1;
  for(int limit:{0,5,6,7,int(sizeof(prefs)+6),int(sizeof(prefs)+9)}) {
    fs.write_limit=limit;
    assert(!writeSettings(&fs,prefs));
    assert(fs.files.at("/notify_prefs")==original);
  }
  fs.write_limit=-1;

  fs.fail_rename_from="/notify_prefs";
  assert(!writeSettings(&fs,prefs));
  assert(fs.files.at("/notify_prefs")==original);
  fs.fail_rename_from.clear();
  fs.files["/notify_prefs.bak"]=original;
  fs.fail_remove_path="/notify_prefs.bak";
  assert(!writeSettings(&fs,prefs));
  assert(fs.files.at("/notify_prefs")==original);
  assert(fs.files.at("/notify_prefs.bak")==original);
  fs.fail_remove_path.clear();
  fs.largest_read=0;
  assert(writeSettings(&fs,prefs));
  assert(fs.largest_read<=128);
  assert(!fs.exists("/notify_prefs.bak"));
  assert(verifySettingsFile(&fs,"/notify_prefs",&prefs));
}

int main() {
  resetDefaults();
  boundedVerificationAndFaults();
  FakeFS fs;Settings prefs,loaded;
  assert(!readSettings(nullptr,"/notify_prefs",loaded));
  assert(!verifySettingsFile(nullptr,"/notify_prefs"));
  assert(!writeSettings(nullptr,prefs));
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  assert(!verifySettingsFile(&fs,"/notify_prefs"));
  prefs.enabled=1;prefs.outputs=7;
  auto& rule=prefs.rules[0];rule.used=1;
  assert(parseSelector(("room:"+std::string(64,'a')).c_str(),rule.selector));
  assert(setField(rule,FRemote,"on"));
  assert(setField(rule,FVibe,"50,300,40,20,500"));
  assert(writeSettings(&fs,prefs));
  assert(readSettings(&fs,"/notify_prefs",loaded));
  assert(!memcmp(&prefs,&loaded,sizeof(prefs)));
  const auto original=fs.files.at("/notify_prefs");
  prefs.outputs=3;
  fs.fail_write=true;
  assert(!writeSettings(&fs,prefs));
  assert(fs.files.at("/notify_prefs")==original);
  fs.fail_write=false;fs.fail_publish=true;
  assert(!writeSettings(&fs,prefs));
  assert(readSettings(&fs,"/notify_prefs",loaded));
  assert(loaded.outputs==7);
  // Preserve the recovery copy if the primary is already damaged.
  fs.files["/notify_prefs.bak"]=original;
  fs.files["/notify_prefs"][8]^=1;
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  assert(!writeSettings(&fs,prefs));
  assert(readSettings(&fs,"/notify_prefs",loaded));
  assert(loaded.outputs==7);
  fs.fail_publish=false;
  assert(writeSettings(&fs,prefs));
  assert(readSettings(&fs,"/notify_prefs",loaded));
  assert(loaded.outputs==3);
  const auto good=fs.files["/notify_prefs"];
  for(size_t index:{size_t(0),size_t(4),size_t(8),good.size()-1}) {
    fs.files["/notify_prefs"]=good;fs.files["/notify_prefs"][index]^=1;
    assert(!readSettings(&fs,"/notify_prefs",loaded));
    assert(!verifySettingsFile(&fs,"/notify_prefs"));
  }
  fs.files["/notify_prefs"]=good;fs.files["/notify_prefs"].pop_back();
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  assert(!verifySettingsFile(&fs,"/notify_prefs"));
  fs.files["/notify_prefs"]=good;fs.files["/notify_prefs"].push_back(0);
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  assert(!verifySettingsFile(&fs,"/notify_prefs"));
  // Interrupted publication can load its good backup, then save again.
  fs.files.erase("/notify_prefs");fs.files["/notify_prefs.bak"]=good;
  assert(readSettings(&fs,"/notify_prefs.bak",loaded));
  assert(writeSettings(&fs,loaded));
  assert(fs.files["/notify_prefs"]==good);
}
'''

# Out-of-line declarations retain filesystem calls in the ARM compiler's
# stack report. The file object matches the nRF52 file handle's rough size.
ARM_STUB = r'''#pragma once
#include <stddef.h>
#include <stdint.h>
class FakeFS;
class File {
  uintptr_t opaque[28];
public:
  explicit File(FakeFS&);
  bool open(const char*,int);
  size_t size() const;
  int read(uint8_t*,size_t);
  size_t write(const uint8_t*,size_t);
  void close();
};
class FakeFS {
public:
  bool exists(const char*);
  bool remove(const char*);
  bool rename(const char*,const char*);
};
#define FILESYSTEM FakeFS
#define FILE_O_READ 1
#define FILE_O_WRITE 2
'''
ARM_PROGRAM = r'''
#include "NotificationSettingsFile.h"
extern "C" __attribute__((noinline)) bool save_settings(
    FILESYSTEM* fs,const mesh::notify::Settings& prefs) {
  return mesh::notify::writeSettings(fs,prefs);
}
extern "C" __attribute__((noinline)) void reset_settings(mesh::notify::Settings& prefs) {
  mesh::notify::resetSettings(prefs);
}
'''

class NotificationSettingsTests(unittest.TestCase):
    def test_roundtrip_corruption_and_failed_publication_on_each_fs_api(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/"helpers").mkdir()
            (folder/"helpers/IdentityStore.h").write_text(STUB)
            (folder/"test.cpp").write_text(PROGRAM)
            flags=[]
            env=os.environ.copy()
            if os.name!='nt':
                flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer',
                       '-fno-pie','-no-pie']
            for platform in ("ESP32_PLATFORM", "NRF52_PLATFORM", "STM32_PLATFORM"):
                with self.subTest(platform=platform):
                    binary=folder/platform
                    subprocess.run(["g++","-std=c++17","-Wall","-Wextra","-Werror",*flags,
                        "-Wno-misleading-indentation","-D"+platform,"-I"+str(folder),
                        "-I"+str(ROOT/"src"),"-I"+str(ROOT/"examples/companion_radio"),
                        str(folder/"test.cpp"),"-o",str(binary)],check=True)
                    subprocess.run([str(binary)],check=True,env=env)

    def test_arm_storage_and_reset_frames_do_not_copy_entire_settings(self):
        compiler=shutil.which('arm-none-eabi-g++')
        if not compiler:
            packages=Path.home()/'.platformio/packages'
            candidates=sorted(packages.glob('toolchain-gccarmnoneeabi*/bin/arm-none-eabi-g++'))
            if candidates:compiler=str(candidates[0])
        if not compiler:self.skipTest('ARM compiler unavailable')
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'helpers').mkdir()
            (folder/'helpers/IdentityStore.h').write_text(ARM_STUB)
            source=folder/'storage.cpp';source.write_text(ARM_PROGRAM)
            subprocess.run([compiler,'-std=c++17','-mcpu=cortex-m4','-mthumb','-Os',
                '-fstack-usage','-DNRF52_PLATFORM','-I'+str(folder),
                '-I'+str(ROOT/'src'),'-I'+str(ROOT/'examples/companion_radio'),
                '-c',str(source),'-o',str(folder/'storage.o')],check=True)
            frames={}
            for line in (folder/'storage.su').read_text().splitlines():
                name,size,kind=line.rsplit('\t',2)
                self.assertEqual(kind,'static',line)
                frames[name]=int(size)
            self.assertTrue(frames)
            # Before the fix writeSettings and reset used 2408 and 2280 bytes
            # respectively with this same filesystem declaration on Cortex-M4.
            self.assertLessEqual(max(frames.values()),384,frames)
            reset=next(size for name,size in frames.items() if 'reset_settings(' in name)
            self.assertLessEqual(reset,32,frames)

if __name__=="__main__":
    unittest.main()
