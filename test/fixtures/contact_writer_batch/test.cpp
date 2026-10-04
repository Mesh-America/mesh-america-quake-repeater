// Executes the real CFT with the existing stdio-admission model.
#include "FakeFilesystem.h"
#define FILESYSTEM FakeFilesystem
#include "transaction_under_test.h"
#include <cstdio>

using Writer = mesh::ContactFileTransaction;
using Progress = Writer::CommitProgress;
using Bytes = std::vector<uint8_t>;
Bytes image(size_t bytes) {
  Bytes result(bytes);
  for (size_t i = 0; i < bytes; ++i) result[i] = uint8_t(i * 23 + i / 7);
  return result;
}
bool presence(FakeFilesystem* fs, const char* path, bool& found) {
  ++fs->metadata_probes;
  if (fs->metadata_error) return false;
  found = fs->exists(path);
  return true;
}
void begin(Writer& writer, bool background) {
  for (unsigned i = 0; !writer && i < 8; ++i)
    assert(writer.serviceBegin(background) != Writer::BeginProgress::Failed);
  assert(writer);
}
void records(Writer& writer, const Bytes& bytes, size_t cap) {
  assert(bytes.size() % 152 == 0);
  for (size_t offset = 0; offset < bytes.size(); offset += 152) {
    const unsigned before = SPIFFS.backend_writes;
    assert(writer.write(bytes.data() + offset, 152) == 152);
    assert(SPIFFS.backend_writes - before <= 1);
    assert(SPIFFS.largest_backend_write <= cap);
  }
}
Progress finish(Writer& writer, unsigned budget = 8) {
  Progress progress = Progress::Pending;
  for (unsigned i = 0; progress == Progress::Pending && i < 2000; ++i)
    progress = writer.serviceCommit(true, budget);
  assert(progress != Progress::Pending);
  return progress;
}
void measure(unsigned count, bool background) {
  SPIFFS = FakeFilesystem(); SPIFFS.emulate_stdio = true;
  const Bytes bytes = image(count * 152);
  Writer writer(&SPIFFS, "/contacts3", presence, true);
  begin(writer, background);
  const unsigned configurations = SPIFFS.buffer_config_calls;
  assert(writer.serviceBegin(!background) == Writer::BeginProgress::Ready);
  assert(SPIFFS.buffer_config_calls == configurations); // selection latched
  const size_t cap = background ? 502 : 251;
  records(writer, bytes, cap);
  assert(SPIFFS.writes == count);
  assert(SPIFFS.backend_writes == bytes.size() / cap);
  assert(finish(writer) == Progress::Succeeded);
  assert(SPIFFS.files.at("/contacts3") == bytes);
  assert(SPIFFS.backend_writes == (bytes.size() + cap - 1) / cap);
  assert(SPIFFS.largest_backend_write <= cap);
  assert(SPIFFS.missing_remove_logs == 0);
  printf("{\"records\":%u,\"background\":%s,\"bytes\":%zu,\"logical_writes\":%u,"
         "\"backend_writes\":%u,\"largest_backend_write\":%zu}\n",
         count, background ? "true" : "false", bytes.size(), SPIFFS.writes,
         SPIFFS.backend_writes, SPIFFS.largest_backend_write);
}
void synchronousDefault() {
  SPIFFS = FakeFilesystem(); SPIFFS.emulate_stdio = true;
  const Bytes bytes = image(347 * 152);
  Writer writer(&SPIFFS, "/contacts3", presence);
  assert(writer); records(writer, bytes, 251);
  assert(writer.commit());
  assert(SPIFFS.backend_writes == 211 && SPIFFS.largest_backend_write == 251);
  assert(SPIFFS.files.at("/contacts3") == bytes);
}
void configureTime(bool earlier, bool configure) {
  SPIFFS = FakeFilesystem(); SPIFFS.emulate_stdio = true;
  Writer writer(&SPIFFS, "/contacts3", presence, true);
  // Reach the open stream without configuring it, regardless of whether
  // background preparation also retires an earlier backup.
  unsigned passes = 0;
  while (SPIFFS.opens == 0) {
    assert(++passes < 16);
    assert(writer.serviceBegin(earlier) == Writer::BeginProgress::Pending);
  }
  assert(SPIFFS.buffer_config_calls == 0 && SPIFFS.writes == 0);
  assert(writer.serviceBegin(configure) == Writer::BeginProgress::Ready);
  const unsigned configurations = SPIFFS.buffer_config_calls;
  assert(writer.serviceBegin(!configure) == Writer::BeginProgress::Ready);
  assert(SPIFFS.buffer_config_calls == configurations);
  records(writer, image(4 * 152), configure ? 502 : 251);
  assert(SPIFFS.largest_backend_write == (configure ? 502 : 251));
}
void cancellation() {
  // gcd(152,502)=2:251 records are exactly76 full502 buffers.
  for (bool background : {false,true}) for (unsigned n : {1U,2U,3U,4U,250U,251U,252U,347U}) {
    SPIFFS = FakeFilesystem(); SPIFFS.emulate_stdio = true;
    const Bytes old = image(152), next = image(n * 152);
    SPIFFS.files["/contacts3"] = old;
    const size_t cap = background ? 502 : 251;
    unsigned before_close = 0;
    {
      Writer writer(&SPIFFS, "/contacts3", presence, true); begin(writer,background);
      records(writer,next,cap);
      assert(SPIFFS.backend_writes == next.size() / cap);
      before_close = SPIFFS.backend_writes;
      assert(SPIFFS.files.at("/contacts3") == old);
    }
    assert(SPIFFS.backend_writes-before_close == unsigned(next.size()%cap != 0));
    assert(SPIFFS.backend_writes == (next.size()+cap-1)/cap);
    assert(SPIFFS.largest_backend_write <= cap);
    assert(SPIFFS.files.at("/contacts3") == old && !SPIFFS.exists("/contacts3.tmp"));
  }
}
void setupFailures() {
  for (bool background : {false,true}) for (unsigned fault : {1U,2U,3U}) {
    SPIFFS=FakeFilesystem(); SPIFFS.emulate_stdio=true;
    const Bytes old=image(152); SPIFFS.files["/contacts3"]=old;
    if (fault==1) SPIFFS.fail_buffer_config=1;
    if (fault==2) SPIFFS.metadata_error=true;
    if (fault==3) SPIFFS.fail_create=SPIFFS.partial_create_failure=true;
    {
      Writer writer(&SPIFFS,"/contacts3",presence,true);
      auto result=Writer::BeginProgress::Pending;
      for (unsigned i=0;result==Writer::BeginProgress::Pending && i<8;++i)
        result=writer.serviceBegin(background);
      assert(result==Writer::BeginProgress::Failed && !writer);
      assert(writer.write(old.data(),old.size())==0);
      assert(writer.serviceCommit()==Progress::Failed);
      assert(SPIFFS.writes==0 && SPIFFS.backend_writes==0 && SPIFFS.reads==0);
    }
    assert(SPIFFS.files.at("/contacts3")==old);
    if(fault!=2) assert(!SPIFFS.exists("/contacts3.tmp"));
  }
}
void faultsAndCrash() {
  for (bool background : {false,true}) for(unsigned fault : {0U,1U,2U,3U,4U,5U}) {
    SPIFFS=FakeFilesystem(); SPIFFS.emulate_stdio=true;
    const Bytes old=image(152),next=image(4*152);SPIFFS.files["/contacts3"]=old;
    {
      Writer writer(&SPIFFS,"/contacts3",presence,true);begin(writer,background);
      if(fault==1) {
        SPIFFS.max_write=151;
        assert(writer.write(next.data(),152)==151);
      } else records(writer,next,background?502:251);
      if(fault==2) SPIFFS.fail_read="/contacts3.tmp";
      if(fault==3) SPIFFS.fail_rename=1;
      if(fault==4) SPIFFS.fail_rename=2;
      if(fault==5) {
        assert(writer.serviceCommit()==Progress::Pending); // flush before corrupting temp
        SPIFFS.files.at("/contacts3.tmp")[30]^=1;
      }
      const auto result=finish(writer);
      assert(result==(fault==0?Progress::Succeeded:Progress::Failed));
    }
    assert(SPIFFS.files.at("/contacts3")== (fault==0?next:old));
    assert(!SPIFFS.exists("/contacts3.tmp"));
    const auto snapshots=SPIFFS.rename_snapshots;
    for (const auto& snapshot:snapshots) {
      SPIFFS=FakeFilesystem();SPIFFS.files=snapshot;
      assert(Writer::recover(&SPIFFS,"/contacts3",presence));
      const auto& recovered=SPIFFS.files.at("/contacts3");
      assert(recovered==old || recovered==next);
    }
  }
}
int main(int argc,char** argv) {
  const std::string mode=argc>1?argv[1]:"all";
  if(mode=="measure") {
    for(unsigned n : {347U,349U,350U}) for(bool background : {false,true}) measure(n,background);
  } else if(mode=="default") synchronousDefault();
  else if(mode=="configure") {configureTime(true,false);configureTime(false,true);}
  else if(mode=="cancel") cancellation();
  else if(mode=="faults") {setupFailures();faultsAndCrash();}
  else assert(false && "unknown fixture mode");
}
