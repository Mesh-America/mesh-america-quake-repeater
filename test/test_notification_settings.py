"""Run the production notification file format against a fault-injected filesystem."""
from pathlib import Path
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
  bool exists(const char* path) { return files.count(path); }
  bool remove(const char* path) { files.erase(path);return true; }
  bool rename(const char* from,const char* to) {
    if(fail_publish && std::string(from)=="/notify_prefs.tmp")return false;
    if(!exists(from)||exists(to))return false;
    files[to]=files[from];files.erase(from);return true;
  }
  File open(const char* path,const char* mode,bool=false) {
    if(*mode=='w')files[path].clear();
    return exists(path)?File(this,path):File();
  }
};
inline bool File::open(const char* path,int mode) {
  if(mode==2)fs->files[path].clear();
  if(!fs->exists(path))return false;
  name=path;cursor=0;return true;
}
inline size_t File::size() const { return fs->files.at(name).size(); }
inline size_t File::read(uint8_t* out,size_t n) {
  auto& bytes=fs->files[name];n=std::min(n,bytes.size()-cursor);
  memcpy(out,bytes.data()+cursor,n);cursor+=n;return n;
}
inline size_t File::write(const uint8_t* in,size_t n) {
  if(fs->fail_write)return 0;
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
int main() {
  FakeFS fs;Settings prefs,loaded;
  assert(!readSettings(nullptr,"/notify_prefs",loaded));
  assert(!writeSettings(nullptr,prefs));
  assert(!readSettings(&fs,"/notify_prefs",loaded));
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
  }
  fs.files["/notify_prefs"]=good;fs.files["/notify_prefs"].pop_back();
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  fs.files["/notify_prefs"]=good;fs.files["/notify_prefs"].push_back(0);
  assert(!readSettings(&fs,"/notify_prefs",loaded));
  // Interrupted publication can load its good backup, then save again.
  fs.files.erase("/notify_prefs");fs.files["/notify_prefs.bak"]=good;
  assert(readSettings(&fs,"/notify_prefs.bak",loaded));
  assert(writeSettings(&fs,loaded));
  assert(fs.files["/notify_prefs"]==good);
}
'''

class NotificationSettingsTests(unittest.TestCase):
    def test_roundtrip_corruption_and_failed_publication_on_each_fs_api(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/"helpers").mkdir()
            (folder/"helpers/IdentityStore.h").write_text(STUB)
            (folder/"test.cpp").write_text(PROGRAM)
            for platform in ("ESP32_PLATFORM", "NRF52_PLATFORM", "STM32_PLATFORM"):
                with self.subTest(platform=platform):
                    binary=folder/platform
                    subprocess.run(["g++","-std=c++17","-Wall","-Wextra","-Werror",
                        "-Wno-misleading-indentation","-D"+platform,"-I"+str(folder),
                        "-I"+str(ROOT/"src"),"-I"+str(ROOT/"examples/companion_radio"),
                        str(folder/"test.cpp"),"-o",str(binary)],check=True)
                    subprocess.run([str(binary)],check=True)

if __name__=="__main__":
    unittest.main()
