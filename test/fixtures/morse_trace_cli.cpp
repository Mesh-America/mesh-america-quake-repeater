#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
struct TraceRadio : TestRadio {
  mesh::MorseRssiTrace trace;
  bool fail_read=false;
  uint32_t total_override=0;
  size_t morseTraceLength() const override { return trace.length(); }
  uint32_t morseTraceTotal() const override { return total_override ? total_override : trace.total(); }
  bool morseTraceTruncated() const override { return trace.truncated(); }
  bool readMorseTrace(size_t offset,mesh::MorseRssiTraceEntry& out) const override {
    return !fail_read && trace.read(offset,out);
  }
};
static void sparse_ring_and_decoder_hook() {
  mesh::MorseRssiTrace trace;
  trace.sample(-110,0,8); trace.sample(-110,520,0); trace.sample(-80,521,5);
  assert(trace.length()==0); // no learning, idle/noise, or debounce-only history
  trace.sample(-80,525,3); trace.sample(-76,527,3);
  assert(trace.length()==1);
  mesh::MorseRssiTraceEntry row;
  assert(trace.read(0,row) && row.millis==525 && row.rssi_dbm==-80 && row.flags==3);
  trace.sample(-110,570,0); assert(trace.length()==2);
  trace.sample(-110,60570,0); assert(trace.length()==3); // quiet anchor keeps deltas bounded
  trace.sample(-110,200000,0);
  assert(trace.length()==1 && trace.truncated() && trace.total()==4);
  assert(trace.read(0,row) && row.millis==200000);
  assert(!trace.read(1,row) && !trace.read(size_t(-1),row));
  trace.clear(); assert(!trace.length() && !trace.total() && !trace.truncated());
  mesh::MorseRx rx; rx.setTrace(&trace);
  assert(rx.start(25,60000,100)==mesh::MorseRxResult::Started);
  for (uint32_t time=100; time<620; ++time) rx.sample(-110,time);
  assert(trace.length()==0);
  for (uint32_t time=620; time<668; ++time) rx.sample(-80,time);
  for (uint32_t time=668; time<1004; ++time) rx.sample(-110,time);
  rx.stop(1004);
  assert(trace.length()==2 && rx.text()[0]=='E');
  const auto retained=trace.total(); rx.sample(-80,1005); assert(trace.total()==retained);
  assert(rx.start(25,60000,2000)==mesh::MorseRxResult::Started && !trace.length());
}
#endif
int main() {
  char reply[157]={};
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  sparse_ring_and_decoder_hook();
  TraceRadio radio; radio.rx_supported=true;
  assert(mesh::handleMorseCommand(&radio,"morse trace",reply,sizeof(reply)));
  assert(std::string(reply).find("> 000/000 t=0 n=END x=0 ")==0);
  for (size_t entry=0; entry<mesh::MorseRssiTrace::Capacity+10; ++entry)
    radio.trace.sample(entry%2 ? -110 : -80,uint32_t(entry*48),entry%2 ? 0 : 3);
  assert(radio.trace.length()==512 && radio.trace.total()==522 && radio.trace.truncated());
  mesh::MorseRssiTraceEntry row;
  for (size_t entry=0; entry<512; ++entry) {
    assert(radio.trace.read(entry,row) && row.millis==(entry+10)*48);
  }
  size_t offset=0;
  while (offset<radio.trace.length()) {
    const auto command=std::string("morse trace ")+std::to_string(offset);
    uint8_t guarded[161]; memset(guarded,0xa5,sizeof(guarded)); memcpy(guarded,"AB|",3);
    assert(mesh::handleMorseCommand(&radio,command.c_str(),reinterpret_cast<char*>(guarded+3),157));
    assert(!memcmp(guarded,"AB|",3) && guarded[160]==0xa5);
    const std::string page(reinterpret_cast<char*>(guarded+3));
    assert(page.find("t=522")!=std::string::npos && page.find("x=1")!=std::string::npos);
    assert(page.size()<157);
    const auto marker=page.find("n="); assert(marker!=std::string::npos);
    if (page.substr(marker+2,3)=="END") break;
    const auto next=std::stoul(page.substr(marker+2,3));
    assert(next>offset && next<=offset+8); offset=next;
  }
  for (const char* command : {"morse trace -1","morse trace 513","morse trace 1x","morse trace 4294967296","morse trace 1 2"}) {
    assert(mesh::handleMorseCommand(&radio,command,reply,sizeof(reply)) && !strncmp(reply,"Error:",6));
  }
  assert(mesh::handleMorseCommand(&radio,"morse trace 512",reply,sizeof(reply)) && strstr(reply,"n=END"));
  radio.fail_read=true;
  assert(mesh::handleMorseCommand(&radio,"morse trace",reply,sizeof(reply)) && strstr(reply,"trace changed"));
  radio.fail_read=false; radio.total_override=0xffffffffU;
  assert(mesh::handleMorseCommand(&radio,"morse trace",reply,sizeof(reply)) && strstr(reply,"t=4294967295"));
  char small[8]; memset(small,'X',sizeof(small));
  assert(mesh::handleMorseCommand(&radio,"morse trace",small,sizeof(small)) && small[7]==0);
  mesh::usable=false;
  assert(mesh::handleMorseCommand(&radio,"morse trace",reply,sizeof(reply)) && strncmp(reply,"Error:",6));
  mesh::MorseReplyHandoff handoff; const uint8_t actor[32]={1};
  handoff.beginCommand(actor); assert(handoff.stage(902100,25,60000,100)); handoff.endCommand();
  assert(!mesh::handleMorseReplyCommand(handoff,&radio,"morse\ttrace 0",reply,sizeof(reply),100));
  assert(handoff.pending() && !radio.rx_starts && !radio.starts);
#else
  TestRadio radio; radio.rx_supported=true;
  assert(mesh::handleMorseCommand(&radio,"morse trace",reply,sizeof(reply)) && !strncmp(reply,"Error:",6));
  assert(!radio.rx_starts && !radio.starts);
#endif
}
