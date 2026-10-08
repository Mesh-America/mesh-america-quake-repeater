#!/usr/bin/env python3
"""Run production contact streaming with interleaved USB and paced BLE clients."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <limits>
#include <vector>
#include "helpers/ArduinoSerialInterface.h"
#include "helpers/MultiSerialInterface.h"
#define PUB_KEY_SIZE 32
#define MAX_PATH_SIZE 64
template<class... Args> static void ignoreDebug(Args&&...) {}
#define MESH_DEBUG_PRINTLN(...) ignoreDebug(__VA_ARGS__)
namespace StrHelper {
static void strzcpy(void* out,const char* in,size_t size) {
  memset(out,0,size);memcpy(out,in,std::min(size,strlen(in)));
}
}
@CONSTANTS@
@BUFFER@
struct ContactInfo {
  struct { uint8_t pub_key[32]{}; } id;
  uint8_t type=1, flags=0, out_path_len=0;
  char name[32]{};
  uint32_t last_advert_timestamp=0, gps_lat=0, gps_lon=0, lastmod=1;
  bool copyPathTo(uint8_t* out) const { memset(out,0,MAX_PATH_SIZE); return true; }
};
struct ContactsIterator {
  unsigned next=0, count=0;
  template<class T> bool hasNext(T*,ContactInfo& c) {
    if(next==count) return false;
    c=ContactInfo(); c.id.pub_key[0]=static_cast<uint8_t>(++next);
    snprintf(c.name,sizeof(c.name),"HIL-%u",next);
    c.lastmod=next; return true;
  }
};
struct Ble : BaseSerialInterface {
  bool enabled=false, connected=true;
  unsigned last_write=0, capacity=4;
  std::deque<std::vector<uint8_t>> input, pending;
  std::vector<std::vector<uint8_t>> delivered;
  void enable() override { enabled=true; }
  void disable() override { enabled=false; }
  bool isEnabled() const override { return enabled; }
  bool isConnected() const override { return connected; }
  bool isReadBusy() const override { return !input.empty(); }
  bool isWriteBusy() const override { return millis()-last_write<60; }
  size_t writeFrame(const uint8_t* src,size_t n) override {
    if(!enabled||!connected||pending.size()>=capacity) return 0;
    pending.emplace_back(src,src+n); return n;
  }
  size_t checkRecvFrame(uint8_t* dest) override {
    if(connected&&!pending.empty()&&!isWriteBusy()) {
      delivered.push_back(pending.front()); pending.pop_front(); last_write=millis();
    }
    if(!connected||input.empty()) return 0;
    auto frame=input.front(); input.pop_front();
    memcpy(dest,frame.data(),frame.size()); return frame.size();
  }
};
struct MyMesh {
  BaseSerialInterface* _serial=nullptr;
  struct Clock { unsigned getMillis() const {return millis();} } clock, *_ms=&clock;
  struct Store { bool hasIncompleteContactLoad() const {return false;} } store, *_store=&store;
  ContactsIterator _iter;
  BaseSerialInterface* _iter_reply_route=nullptr;
  ContactInfo _iter_pending_contact;
  uint32_t _iter_filter_since=0, _iter_next_frame_at=0, _iter_total_count=0;
  uint32_t _iter_table_revision=0, _most_recent_lastmod=0;
  bool _iter_started=false, _iter_start_pending=false, _iter_contact_pending=false;
  unsigned contacts=54, revision=1;
  uint8_t out_frame[MAX_FRAME_SIZE+4]{},cmd_frame[MAX_FRAME_SIZE+1]{};
  bool millisHasNowPassed(uint32_t time) const {return static_cast<int32_t>(time-millis())<0;}
  uint32_t futureMillis(uint32_t delta) const {return millis()+delta;}
  uint32_t getContactTableRevision() const {return revision;}
  unsigned getNumContacts() const {return contacts;}
  ContactsIterator startContactsIterator() {return {0,contacts};}
  void writeErrFrame(uint8_t error) {
    uint8_t reply[]={RESP_CODE_ERR,error}; assert(_serial->writeFrame(reply,2)==2);
  }
  void cancelSerialOperationsForRoute(BaseSerialInterface*) {}
  void stopContactsIterator();
  void cancelSerialResponseStream(BaseSerialInterface* route=nullptr);
  bool writeContactRespFrame(uint8_t,const ContactInfo&,BaseSerialInterface* route=nullptr);
  void checkSerialInterface();
  void handleCmdFrame(size_t len) {
    @GET_CONTACTS@
    else if(cmd_frame[0]==CMD_APP_START&&len>=8) {
      @APP_BEGIN@
      memset(out_frame,0xA5,70);out_frame[0]=RESP_CODE_SELF_INFO;
      assert(_serial->writeFrame(out_frame,70)==70);
    } else {
      assert(cmd_frame[0]==CMD_GET_BATT_AND_STORAGE);
      memset(out_frame,0x5A,11);out_frame[0]=RESP_CODE_BATT_AND_STORAGE;
      assert(_serial->writeFrame(out_frame,11)==11);
    }
  }
};
@METHODS@
struct Fixture {
  BufferStream stream;
  ArduinoSerialInterface usb;
  Ble ble;
  MultiSerialInterface manager;
  MyMesh mesh;
  bool drain_usb=true;
  Fixture() {
    g_mock_millis=100;
    usb.begin(stream); usb.enableFlowControl(true);
    assert(manager.addInterface(InterfaceType::Bluetooth,&ble));
    assert(manager.addInterface(InterfaceType::USB,&usb)); manager.enable();
    mesh._serial=&manager;
  }
  void step() {
    if(drain_usb) stream.write_capacity=4096;
    mesh.checkSerialInterface(); manager.loop(); ++g_mock_millis;
  }
  void run(unsigned count) {while(count--) step();}
  void sendUsb(std::initializer_list<uint8_t> payload) {
    const uint8_t header[]={'<',static_cast<uint8_t>(payload.size()),0};
    stream.push(header,3); stream.push(payload.begin(),payload.size());
  }
  std::vector<std::vector<uint8_t>> usbFrames() const {
    std::vector<std::vector<uint8_t>> frames;
    for(size_t pos=0;pos<stream.output.size();) {
      assert(stream.output[pos]=='>'&&pos+3<=stream.output.size());
      size_t n=stream.output[pos+1]|(stream.output[pos+2]<<8);
      assert(n>0&&pos+n+3<=stream.output.size());
      frames.emplace_back(stream.output.begin()+pos+3,stream.output.begin()+pos+3+n);
      pos+=n+3;
    }
    return frames;
  }
  void startBle() {ble.input.push_back({CMD_GET_CONTACTS});step();assert(mesh._iter_started);}
  void finish() {run(6000);assert(!mesh._iter_started);}
};
static unsigned count(const std::vector<std::vector<uint8_t>>& frames,uint8_t type) {
  return std::count_if(frames.begin(),frames.end(),[type](const auto& f){return f[0]==type;});
}
static void assertBleSnapshot(const Fixture& f,unsigned contacts=54) {
  assert(count(f.ble.delivered,RESP_CODE_CONTACTS_START)==1);
  assert(count(f.ble.delivered,RESP_CODE_CONTACT)==contacts);
  assert(count(f.ble.delivered,RESP_CODE_END_OF_CONTACTS)==1);
  for(unsigned i=1;i<=contacts;++i) {
    auto at=std::find_if(f.ble.delivered.begin(),f.ble.delivered.end(),[i](const auto& v){return v[0]==RESP_CODE_CONTACT&&v[1]==i;});
    assert(at!=f.ble.delivered.end());
  }
}
int main() {
  // Fifty-four BLE contacts need over three seconds, but each independent USB
  // request is handled immediately, even when it arrives on every loop pass.
  {
    Fixture f;f.startBle();unsigned queries=0,apps=0;
    for(unsigned now=0;now<4000;++now) {
      const bool app=now%97==96;
      if(app) {
        f.mesh.cancelSerialResponseStream(&f.usb);
        f.manager.forgetReplyRouteForDisconnected(&f.usb);f.usb.resetSessionState();
        f.sendUsb({CMD_APP_START,0,0,0,0,0,0,0});++apps;
      } else {f.sendUsb({CMD_GET_BATT_AND_STORAGE});++queries;}
      f.step();assert(f.usbFrames().size()==queries+apps);
    }
    f.finish();assertBleSnapshot(f);
    assert(count(f.usbFrames(),RESP_CODE_CONTACT)==0);
    assert(count(f.usbFrames(),RESP_CODE_CONTACTS_START)==0);
    assert(count(f.usbFrames(),RESP_CODE_SELF_INFO)==apps);
    assert(count(f.usbFrames(),RESP_CODE_BATT_AND_STORAGE)==queries);
    for(const auto& response:f.usbFrames()) {
      assert(response.size()==(response[0]==RESP_CODE_SELF_INFO?70u:11u));
      assert(response.back()==(response[0]==RESP_CODE_SELF_INFO?0xA5:0x5A));
    }
  }
  // A second client cannot replace the sole contact iterator; its ERR remains
  // on that client's route, while the BLE list keeps its original destination.
  {
    Fixture f;f.startBle();f.sendUsb({CMD_GET_CONTACTS,0xFF,0xFF,0xFF,0xFF});f.step();
    assert(f.usbFrames().size()==1&&f.usbFrames()[0][0]==RESP_CODE_ERR);
    assert(f.usbFrames()[0][1]==ERR_CODE_BAD_STATE);
    f.finish();assertBleSnapshot(f);
  }
  // Session loss cancels only its contact stream, irrespective of whichever
  // interface supplied the newest command. No remaining contacts leak to USB.
  {
    Fixture f;f.startBle();f.sendUsb({CMD_GET_BATT_AND_STORAGE});f.step();
    f.mesh.cancelSerialResponseStream(&f.usb);assert(f.mesh._iter_started);
    f.mesh.cancelSerialResponseStream(&f.ble);assert(!f.mesh._iter_started);
    f.run(300);assert(count(f.usbFrames(),RESP_CODE_CONTACT)==0);
  }
  {
    Fixture f;f.startBle();f.ble.connected=false;f.step();assert(!f.mesh._iter_started);
    f.sendUsb({CMD_GET_BATT_AND_STORAGE});f.step();assert(f.usbFrames()[0][0]==RESP_CODE_BATT_AND_STORAGE);
  }
  // The cached contact survives a failed BLE admission and an intervening
  // command which overwrites both shared command/output scratch buffers.
  {
    Fixture f;f.mesh.contacts=3;f.startBle();f.ble.capacity=0;f.run(70);
    assert(f.mesh._iter_contact_pending&&f.mesh._iter_pending_contact.id.pub_key[0]==1);
    f.sendUsb({CMD_GET_BATT_AND_STORAGE});f.step();
    assert(f.usbFrames()[0].back()==0x5A&&f.mesh._iter_contact_pending);
    f.ble.capacity=4;f.finish();assertBleSnapshot(f,3);
  }
  {
    Fixture f;f.startBle();f.ble.input.push_back({CMD_APP_START,0,0,0,0,0,0,0});
    f.step();assert(!f.mesh._iter_started);f.run(300);
    assert(count(f.ble.delivered,RESP_CODE_SELF_INFO)==1);
    assert(count(f.usbFrames(),RESP_CODE_SELF_INFO)==0);
  }
  // A backed-up USB contact stream also leaves BLE queries responsive; once
  // capacity returns, every START/contact/END is retained on the USB route.
  {
    Fixture f;f.drain_usb=false;f.stream.write_capacity=0;
    f.sendUsb({CMD_GET_CONTACTS});f.step();assert(f.mesh._iter_started);
    f.mesh.cancelSerialResponseStream(&f.ble);assert(f.mesh._iter_started);
    f.ble.input.push_back({CMD_GET_CONTACTS});f.step();
    f.ble.input.push_back({CMD_GET_BATT_AND_STORAGE});f.step();f.run(100);
    assert(count(f.ble.delivered,RESP_CODE_ERR)==1);
    assert(count(f.ble.delivered,RESP_CODE_BATT_AND_STORAGE)==1);
    f.drain_usb=true;f.finish();
    assert(count(f.usbFrames(),RESP_CODE_CONTACTS_START)==1);
    assert(count(f.usbFrames(),RESP_CODE_CONTACT)==54);
    assert(count(f.usbFrames(),RESP_CODE_END_OF_CONTACTS)==1);
    assert(count(f.ble.delivered,RESP_CODE_CONTACT)==0);
  }
}
'''


class ContactStreamConcurrencyTests(unittest.TestCase):
    def test_paced_stream_keeps_routes_without_blocking_other_clients(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('a host C++17 compiler is required')
        mesh = (ROOT / 'examples/companion_radio/MyMesh.cpp').read_text()
        native = (ROOT / 'test/test_serial_mode_switch/test_serial_mode_switch.cpp').read_text()
        constants = '\n'.join(re.findall(
            r'^#define (?:CONTACT_STREAM_FRAME_INTERVAL_MS|CMD_GET_CONTACTS|CMD_APP_START|CMD_GET_BATT_AND_STORAGE|RESP_CODE_ERR|RESP_CODE_CONTACTS_START|RESP_CODE_CONTACT|RESP_CODE_END_OF_CONTACTS|RESP_CODE_SELF_INFO|RESP_CODE_BATT_AND_STORAGE|ERR_CODE_BAD_STATE|ERR_CODE_FILE_IO_ERROR)\s+.+$',
            mesh, re.MULTILINE))
        contacts = extract_braced(mesh, '} else if (cmd_frame[0] == CMD_GET_CONTACTS').replace('} else if', 'if', 1)
        app = extract_braced(mesh, '} else if (cmd_frame[0] == CMD_APP_START')
        app = app[app.index('{') + 1:app.index('    int i = 0;')]
        methods = '\n'.join(extract_braced(mesh, sig) for sig in (
            'bool MyMesh::writeContactRespFrame(', 'void MyMesh::stopContactsIterator(',
            'void MyMesh::cancelSerialResponseStream(', 'void MyMesh::checkSerialInterface()',
        ))
        program = HARNESS.replace('@CONSTANTS@', constants).replace('@BUFFER@', extract_braced(native, 'class BufferStream') + ';')
        program = program.replace('@GET_CONTACTS@', contacts).replace('@APP_BEGIN@', app).replace('@METHODS@', methods)
        sanitizers = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-pie', '-no-pie'] if sys.platform.startswith('linux') else []
        with tempfile.TemporaryDirectory(prefix='meshcore-contact-concurrency-') as directory:
            binary = Path(directory) / 'concurrency'
            result = subprocess.run([
                compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-sign-compare',
                *sanitizers,
                f'-I{ROOT / "test/mocks"}', f'-I{ROOT / "src"}', '-x', 'c++', '-',
                str(ROOT / 'src/helpers/ArduinoSerialInterface.cpp'), '-o', str(binary),
            ], input=program, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
