"""Run the complete production FULL-room rule engine over host I/O boundaries."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

UTILS = r'''#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>
namespace mesh {
inline std::vector<uint8_t> test_plaintext;
inline bool test_decrypt_ok=false;
struct RNG { virtual ~RNG() = default; virtual void random(uint8_t*, size_t) = 0; };
struct Utils {
  static void sha256(uint8_t* out, size_t size, const uint8_t*, size_t) { memset(out, 0, size); }
  static bool isHexChar(char c) { return (c>='0'&&c<='9')||(c>='a'&&c<='f')||(c>='A'&&c<='F'); }
  static unsigned nibble(char c) { return c<='9' ? c-'0' : (c|32)-'a'+10; }
  static bool fromHex(uint8_t* out, int size, const char* text) {
    if (strlen(text)!=size_t(size)*2) return false;
    for (int i=0;i<size;++i) {
      if (!isHexChar(text[i*2])||!isHexChar(text[i*2+1])) return false;
      out[i]=uint8_t(nibble(text[i*2])*16+nibble(text[i*2+1]));
    }
    return true;
  }
  static void toHex(char* out,const uint8_t* bytes,size_t size) {
    const char* digits="0123456789ABCDEF";
    for(size_t i=0;i<size;++i) {out[i*2]=digits[bytes[i]>>4];out[i*2+1]=digits[bytes[i]&15];}
    out[size*2]=0;
  }
  // Explicit crypto boundary: only the budget test supplies authenticated
  // plaintext. These tests do not claim to verify ciphertext authentication.
  static int MACThenDecrypt(const uint8_t*,uint8_t* out,const uint8_t*,int) {
    if(!test_decrypt_ok)return 0;
    memcpy(out,test_plaintext.data(),test_plaintext.size());return int(test_plaintext.size());
  }
};
}
'''

BOUNDARIES = r'''#pragma once
#include <algorithm>
#include <cassert>
#include <cctype>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>
#include <Packet.h>
#include <Utils.h>
#define TXT_TYPE_PLAIN 0
class MemoryFS;
class File {
  MemoryFS* owner=nullptr;
  std::shared_ptr<std::vector<uint8_t>> bytes;
  size_t cursor=0;
public:
  File()=default;
  File(MemoryFS* fs,std::shared_ptr<std::vector<uint8_t>> data):owner(fs),bytes(data){}
  operator bool() const {return bool(bytes);}
  bool isDirectory() const {return false;}
  size_t size() const {return bytes ? bytes->size() : 0;}
  size_t available() const {return size()-cursor;}
  size_t read(uint8_t* out,size_t count) {
    count=std::min(count,available());
    if(count) memcpy(out,bytes->data()+cursor,count);
    cursor+=count;return count;
  }
  size_t write(const uint8_t*,size_t);
  void close() {bytes.reset();}
};
class MemoryFS {
public:
  std::map<std::string,std::shared_ptr<std::vector<uint8_t>>> files;
  std::set<std::string> faults;
  bool exists(const char* path) const {return files.count(path)!=0;}
  bool remove(const char* path) {return files.erase(path)!=0;}
  bool rename(const char* from,const char* to) {
    if(faults.count(std::string("rename:")+from+":"+to)||!exists(from)||exists(to))return false;
    files[to]=files[from];files.erase(from);return true;
  }
  File open(const char* path,const char* mode="r",bool=false) {
    if(faults.count(std::string("open:")+mode+":"+path))return {};
    if(mode[0]=='w')files[path]=std::make_shared<std::vector<uint8_t>>();
    return exists(path)?File(this,files[path]):File();
  }
};
inline size_t File::write(const uint8_t* data,size_t count) {
  if(!bytes)return 0;
  bytes->insert(bytes->end(),data,data+count);return count;
}
using FILESYSTEM=MemoryFS;
struct TransportKey {
  uint8_t key[16]{};
  bool isNull() const {for(auto byte:key)if(byte)return false;return true;}
  uint16_t calcTransportCode(const mesh::Packet*) const {return 0;}
};
#define REGION_DENY_FLOOD 1
struct RegionEntry {uint8_t flags=0;char name[32]{};bool isWildcard()const{return false;}};
struct RegionMap {
  static bool is_name_char(uint8_t c) {return std::isalnum(c)||c=='_'||c=='-';}
  RegionEntry* findByName(const char*) {return nullptr;}
  RegionEntry* findByNamePrefix(const char*) {return nullptr;}
  int getTransportKeysFor(const RegionEntry&,TransportKey*,int) {return 0;}
};
'''

PROGRAM = r'''
#include "FloodRuleEngine.h"
#include <cstdio>
mesh::Packet::Packet():header(ROUTE_TYPE_FLOOD),payload_len(0),path_len(0),
    transport_codes{},path{},payload{},_rssi(0),_snr(0),tx_cr(0),flood_retry_policy(0){}
struct TestRng:mesh::RNG {
  uint32_t value=0;unsigned calls=0;
  void random(uint8_t* out,size_t size) override {assert(size==4);memcpy(out,&value,4);++calls;}
};
static MemoryFS disk;
static RegionMap regions;
static TestRng rng;
static FloodRuleEngine rules;
static char reply[160];
void command(const char* text,bool success=true) {
  assert(rules.handleCommand(text,reply));
  assert((strncmp(reply,"Err",3)!=0)==success);
}
bool blocked(mesh::Packet& packet,uint32_t now=0,bool commit=false) {
  auto matches=rules.evaluate(&packet,false,true,nullptr);
  bool result=rules.shouldBlock(&packet,matches,now);
  if(!result&&commit)rules.commitRates(&packet,matches,now);
  return result;
}
void reboot() {rules.begin(&disk,&regions,&rng);}
uint32_t seedFor(const mesh::Packet& packet,unsigned slot,unsigned wanted) {
  for(uint32_t seed=0;;++seed)
    if(FloodRuleExtensions::probabilityRoll(&packet,seed,slot,0)%100==wanted)return seed;
}
int main() {
  reboot();command("del fr all");
  assert(!memcmp(disk.files.at("/flood_filter")->data(),"FPF7",4));
  mesh::Packet packet;packet.header=uint8_t(PAYLOAD_TYPE_ADVERT<<2)|ROUTE_TYPE_FLOOD;
  packet.payload_len=40;
  const uint32_t stable=FloodRuleExtensions::probabilityRoll(&packet,12345,3,0);
  packet.path[0]=0xAB;packet.setPathHashSizeAndCount(3,1);packet.transport_codes[0]=0x1234;
  packet.header=uint8_t(PAYLOAD_TYPE_ADVERT<<2)|ROUTE_TYPE_TRANSPORT_FLOOD;
  assert(stable==FloodRuleExtensions::probabilityRoll(&packet,12345,3,0));
  packet.header=uint8_t(PAYLOAD_TYPE_ADVERT<<2)|ROUTE_TYPE_FLOOD;
  assert(stable!=FloodRuleExtensions::probabilityRoll(&packet,12346,3,0));
  assert(stable!=FloodRuleExtensions::probabilityRoll(&packet,12345,4,0));
  assert(stable!=FloodRuleExtensions::probabilityRoll(&packet,12345,3,1));
  packet.payload[0]=1;assert(stable!=FloodRuleExtensions::probabilityRoll(&packet,12345,3,0));
  packet.payload[0]=0;
  command("set flood.rule.4 type=advert len=30-50 prob=25 drop");
  assert(!memcmp(disk.files.at("/flood_filter")->data(),"FPF8",4));
  rng.value=seedFor(packet,3,24);reboot();assert(blocked(packet));
  const unsigned draws=rng.calls;
  for(unsigned i=0;i<20;++i)assert(blocked(packet));
  assert(rng.calls==draws);
  rng.value=seedFor(packet,3,25);reboot();assert(!blocked(packet));
  packet.payload_len=29;assert(!blocked(packet));packet.payload_len=51;assert(!blocked(packet));
  packet.payload_len=40;rng.value=seedFor(packet,3,0);reboot();assert(blocked(packet));
  command("set fr.4 off");assert(!blocked(packet));reboot();assert(!blocked(packet));
  command("set fr.4 e=on");assert(blocked(packet));
  command("set fr.4 enabled=off");assert(!blocked(packet));
  command("get fr.4");assert(strstr(reply,"e=off"));
  command("set fr.4 enabled=on");assert(blocked(packet));
  command("set fr.5 any rt=d d");packet.header=uint8_t(PAYLOAD_TYPE_ACK<<2)|ROUTE_TYPE_DIRECT;
  assert(blocked(packet));packet.header=uint8_t(PAYLOAD_TYPE_ACK<<2)|ROUTE_TYPE_FLOOD;
  assert(!blocked(packet));
  command("set fr.5 any rt=d h=2+ d");packet.setPathHashSizeAndCount(1,3);
  packet.header=uint8_t(PAYLOAD_TYPE_ACK<<2)|ROUTE_TYPE_DIRECT;assert(!blocked(packet));
  command("set fr.5 any rt=d s=test",false);
  command("del fr all");
  packet.header=uint8_t(PAYLOAD_TYPE_ACK<<2)|ROUTE_TYPE_FLOOD;
  command("set fr.4 any pa=AABB>CCDD$ d");
  packet.setPathHashSizeAndCount(2,3);
  const uint8_t path[]={0,1,0xAA,0xBB,0xCC,0xDD};memcpy(packet.path,path,sizeof(path));
  assert(blocked(packet));packet.path[0]=0xAA;packet.path[1]=0xBB;
  packet.path[2]=0xCC;packet.path[3]=0xDD;packet.path[4]=0;packet.path[5]=1;
  assert(!blocked(packet));
  command("set fr.4 any pa=^AA>BB>CC>DD d");packet.setPathHashSizeAndCount(1,4);
  const uint8_t four[]={0xAA,0xBB,0xCC,0xDD};memcpy(packet.path,four,4);
  assert(blocked(packet));reboot();assert(blocked(packet));
  assert(!memcmp(disk.files.at("/flood_filter")->data(),"FPF8",4));
  command("get fr.4");assert(strstr(reply,"pa=^AA>BB>CC>DD"));
  command("set fr.4 any c=public n=\"^(Alice|Bob) Smith$\" x=\"^RX in place\" a");
  command("get fr.4 n");assert(!strcmp(reply,"> ^(Alice|Bob) Smith$"));
  command("get flood.rule.4 text");assert(!strcmp(reply,"> ^RX in place"));
  reboot();command("get fr.4 x");assert(!strcmp(reply,"> ^RX in place"));
  command("set fr.4 any c=hash:11 n=Alice d",false);
  command("set fr.4 any n=Alice d",false);
  command("set fr.4 any c=public n=\"unterminated d",false);
  command("get fr.4 n");assert(!strcmp(reply,"> ^(Alice|Bob) Smith$"));
  command("set fr.31 advert d");
  disk.faults.insert("open:w:/flood_filter.tmp");command("del fr all",false);
  command("get flood.rule.31");assert(strstr(reply,"advert"));
  command("set fr.31 off",false);command("get fr.31");assert(!strstr(reply,"e=off"));
  disk.faults.clear();command("del fr all");
  command("set fr.4 advert q=1");
  packet.header=uint8_t(PAYLOAD_TYPE_ADVERT<<2)|ROUTE_TYPE_FLOOD;
  assert(!blocked(packet,0,true));assert(blocked(packet,1));
  command("set fr.4 off");assert(!blocked(packet,2,true));
  command("set fr.4 on");assert(blocked(packet,3));
  assert(!blocked(packet,60000));
  command("del fr all");command("set fr.4 any l=0 d");
  packet.payload_len=0;assert(blocked(packet));packet.payload_len=1;assert(!blocked(packet));
  command("del fr all");
  for(unsigned slot=1;slot<=31;++slot) {
    char text[256];
    snprintf(text,sizeof(text),"set fr.%u any c=public x=(a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a|a)*z q=1 s=test stop",slot);
    command(text);
  }
  packet.header=uint8_t(PAYLOAD_TYPE_GRP_TXT<<2)|ROUTE_TYPE_FLOOD;
  packet.payload_len=179;packet.payload[0]=0;
  mesh::test_plaintext.assign(176,'a');
  memset(mesh::test_plaintext.data(),0,5);
  memcpy(mesh::test_plaintext.data()+5,"U: ",3);
  mesh::test_decrypt_ok=true;
  const uint32_t exhausted=rules.evaluate(&packet,false,true,nullptr);
  assert(exhausted==(uint32_t(1)<<31));
  assert(rules.shouldBlock(&packet,exhausted,0));
  bool scope_set=false,fast_track=false;
  assert(!rules.applyScope(&packet,exhausted,scope_set,fast_track));
  assert(!scope_set&&!fast_track);
  rules.commitRates(&packet,exhausted,0);
  mesh::test_decrypt_ok=false;
  assert(!rules.handleCommand("get fridge",reply));
  command("get fb",false);
  puts("FULL-room filter parser, persistence, route, path, probability and rollback passed");
}
'''


class RoomFilterExtensionTests(unittest.TestCase):
    def test_complete_production_engine(self):
        with tempfile.TemporaryDirectory(prefix="room-filter-extensions-") as directory:
            work = Path(directory)
            (work / "Utils.h").write_text(UTILS)
            (work / "boundaries.h").write_text(BOUNDARIES)
            (work / "RoomServerFeatures.h").write_text("#define MESH_ENABLE_ROOM_FLOOD_RULE_ENGINE 1\n")
            header = (ROOT / "examples/simple_room_server/FloodRuleEngine.h").read_text()
            for include in ("Arduino.h", "Mesh.h", "helpers/IdentityStore.h", "helpers/RegionMap.h"):
                header = header.replace(f"#include <{include}>", "")
            (work / "FloodRuleEngine.h").write_text('#include "boundaries.h"\n' + header)
            (work / "FloodRuleEngine.cpp").write_text(
                (ROOT / "examples/simple_room_server/FloodRuleEngine.cpp").read_text())
            (work / "test.cpp").write_text(PROGRAM)
            executable = work / ("test.exe" if os.name == "nt" else "test")
            sanitizer = [] if os.name == "nt" else [
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
            built = subprocess.run(["g++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra",
                "-Wno-unused-variable", *sanitizer, "-I", str(work), "-I", str(ROOT / "src"),
                str(work / "test.cpp"), str(work / "FloodRuleEngine.cpp"), "-o", str(executable)],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
