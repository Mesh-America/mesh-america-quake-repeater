#include "FakeFilesystem.h"
#define FILESYSTEM FakeFilesystem
#define private public
#include "transaction_under_test.h"
#undef private
#include <cstdio>
using Writer=mesh::ContactFileTransaction;
using Progress=Writer::CommitProgress;
using Bytes=std::vector<uint8_t>;
#if defined(ESP32_PLATFORM)
#define DEFER_BEGIN ,true
#else
#define DEFER_BEGIN
#endif
Bytes image(size_t n,uint8_t salt=0){Bytes out(n);for(size_t i=0;i<n;++i)out[i]=uint8_t(i*29+i/3+salt);return out;}
bool presence(FakeFilesystem* fs,const char* name,bool& found){++fs->metadata_probes;if(fs->metadata_error)return false;found=fs->exists(name);return true;}
void begin(Writer& w,bool coalesce=false){
#if defined(ESP32_PLATFORM)
 for(unsigned i=0;!w&&i<9;++i){const auto before=SPIFFS.startupOperations();assert(w.serviceBegin(coalesce)!=Writer::BeginProgress::Failed);assert(SPIFFS.startupOperations()-before<=1);}
#else
 (void)coalesce;
#endif
 assert(w);
}
void write(Writer& w,const Bytes& bytes){for(size_t i=0;i<bytes.size();i+=152){size_t n=std::min(size_t(152),bytes.size()-i);assert(w.write(bytes.data()+i,n)==n);}}
unsigned finish(Writer& w,bool defer,unsigned budget=8){Progress result=Progress::Pending;unsigned calls=0;while(result==Progress::Pending){assert(++calls<2000);result=w.serviceCommit(true,budget,defer);}assert(result==Progress::Succeeded);return calls;}
void reset(const Bytes& old){SPIFFS=FakeFilesystem();SPIFFS.emulate_stdio=true;SPIFFS.files["/contacts3"]=old;}
void contracts(){
 const auto old=image(304,1),next=image(608,2);
 for(bool deferred:{false,true}) for(bool coalesce:{false,true}) {
  reset(old);{
   Writer w(&SPIFFS,"/contacts3",presence DEFER_BEGIN);begin(w,coalesce);write(w,next);
   const unsigned removes=SPIFFS.removes;
   finish(w,deferred);
   assert(SPIFFS.files.at("/contacts3")==next);
#if defined(ESP32_PLATFORM)
   assert(SPIFFS.exists("/contacts3.bak")==deferred);
   assert(SPIFFS.removes-removes==unsigned(!deferred));
#else
   assert(!SPIFFS.exists("/contacts3.bak"));assert(SPIFFS.removes-removes==1);
#endif
  }
#if defined(ESP32_PLATFORM)
  if(deferred)assert(SPIFFS.files.at("/contacts3.bak")==old);
#endif
  assert(!SPIFFS.exists("/contacts3.tmp"));
 }
 // Default synchronous failures retain the pre-existing prior-generation backup.
#if defined(ESP32_PLATFORM)
 reset(old);const auto older=image(152,9);SPIFFS.files["/contacts3.bak"]=older;SPIFFS.fail_buffer_config=1;
 {Writer w(&SPIFFS,"/contacts3",presence);assert(!w);}
 assert(SPIFFS.files.at("/contacts3")==old&&SPIFFS.files.at("/contacts3.bak")==older);
 // RecoverFALSE skips retirement even when cleanupTRUE at Publish.
 reset(old);SPIFFS.files["/contacts3.bak"]=older;
 {Writer w(&SPIFFS,"/contacts3",presence,true);begin(w,false);assert(SPIFFS.files.at("/contacts3.bak")==older);write(w,next);finish(w,true);}
 assert(SPIFFS.files.at("/contacts3.bak")==old);
 // RecoverTRUE latches the retirement stage; ConfigureFALSE retains writer251.
 reset(old);SPIFFS.files["/contacts3.bak"]=older;
 {Writer w(&SPIFFS,"/contacts3",presence,true);
  for(unsigned i=0;i<3;++i)assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(w.serviceBegin(false)==Writer::BeginProgress::Pending);assert(!SPIFFS.exists("/contacts3.bak"));
  begin(w,false);write(w,next);finish(w,true);assert(SPIFFS.largest_backend_write==251);}
#endif
 // Default synchronous commit still cleans the old backup.
 reset(old);{Writer w(&SPIFFS,"/contacts3",presence);assert(w);write(w,next);assert(w.commit());}
 assert(!SPIFFS.exists("/contacts3.bak")&&SPIFFS.files.at("/contacts3")==next);
}
void retirement(){
#if defined(ESP32_PLATFORM)
 const auto old=image(304,1),older=image(152,2);reset(old);SPIFFS.files["/contacts3.bak"]=older;
 {
  Writer w(&SPIFFS,"/contacts3",presence,true);
  for(unsigned i=0;i<3;++i)assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(SPIFFS.files.at("/contacts3")==old&&SPIFFS.files.at("/contacts3.bak")==older);
  const auto removes=SPIFFS.removes,probes=SPIFFS.metadata_probes,opens=SPIFFS.opens;
  assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(SPIFFS.removes-removes==1&&SPIFFS.metadata_probes==probes&&SPIFFS.opens==opens);
  assert(!SPIFFS.exists("/contacts3.bak")&&SPIFFS.files.at("/contacts3")==old);
 }
 // Missing target recovers backup, updates flags and performs no removal.
 SPIFFS=FakeFilesystem();SPIFFS.files["/contacts3.bak"]=old;
 {
  Writer w(&SPIFFS,"/contacts3",presence,true);
  for(unsigned i=0;i<3;++i)assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(w._begin_target_exists&&!w._begin_backup_exists);
  assert(SPIFFS.files.at("/contacts3")==old&&!SPIFFS.exists("/contacts3.bak"));
  const auto removes=SPIFFS.removes;
  assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(SPIFFS.removes==removes&&SPIFFS.missing_remove_logs==0);
 }
 // Failed retirement stops before new/temp ownership; prior temp is untouched.
 reset(old);SPIFFS.files["/contacts3.bak"]=older;SPIFFS.files["/contacts3.tmp"]={9,8,7};SPIFFS.fail_remove=true;
 {
  Writer w(&SPIFFS,"/contacts3",presence,true);
  for(unsigned i=0;i<3;++i)assert(w.serviceBegin(true)==Writer::BeginProgress::Pending);
  assert(w.serviceBegin(true)==Writer::BeginProgress::Failed&&!w&&!w._owns_temp);
  assert(!w.commit()&&w.write(old.data(),old.size())==0);
  assert(SPIFFS.opens==0&&SPIFFS.writes==0);
 }
 assert(SPIFFS.files.at("/contacts3")==old&&SPIFFS.files.at("/contacts3.bak")==older);
 assert(SPIFFS.files.at("/contacts3.tmp")==Bytes({9,8,7}));
#endif
}
void repeatedAndCancel(){
#if defined(ESP32_PLATFORM)
 const auto old=image(152,1),next=image(608,2),last=image(760,3);reset(old);
 {Writer w(&SPIFFS,"/contacts3",presence,true);begin(w,true);write(w,next);finish(w,true);}
 assert(SPIFFS.files.at("/contacts3.bak")==old);
 for(unsigned completed=0;completed<=8;++completed) {
  reset(next);SPIFFS.files["/contacts3.bak"]=old;
  {
   Writer w(&SPIFFS,"/contacts3",presence,true);
   for(unsigned i=0;i<completed;++i){const auto n=SPIFFS.startupOperations();assert(w.serviceBegin(true)!=Writer::BeginProgress::Failed);assert(SPIFFS.startupOperations()-n<=1);}
   if(w)write(w,last);
   assert(SPIFFS.files.at("/contacts3")==next);
  }
  assert(SPIFFS.files.at("/contacts3")==next);
  assert(SPIFFS.exists("/contacts3.bak")==bool(completed<4));
  FakeFilesystem boot;boot.files=SPIFFS.files;assert(Writer::recover(&boot,"/contacts3",presence));assert(boot.files.at("/contacts3")==next);
 }
 reset(next);SPIFFS.files["/contacts3.bak"]=old;
 {Writer w(&SPIFFS,"/contacts3",presence,true);begin(w,true);write(w,last);finish(w,true);}
 assert(SPIFFS.files.at("/contacts3")==last&&SPIFFS.files.at("/contacts3.bak")==next);
#endif
}
void faultsAndCrash(){
 const auto old=image(304,1),next=image(608,2);
 for(bool deferred:{false,true})for(unsigned fault:{0U,1U,2U}) {
  reset(old);
  {
   Writer w(&SPIFFS,"/contacts3",presence DEFER_BEGIN);begin(w,true);write(w,next);
   if(fault)SPIFFS.fail_rename=fault;
   Progress result=Progress::Pending;unsigned n=0;
   while(result==Progress::Pending){assert(++n<2000);result=w.serviceCommit(true,8,deferred);}
   assert(result==(fault?Progress::Failed:Progress::Succeeded));
  }
  assert(SPIFFS.files.at("/contacts3")== (fault?old:next));
  const auto snapshots=SPIFFS.rename_snapshots;
  for(const auto& snapshot:snapshots){FakeFilesystem boot;boot.files=snapshot;assert(Writer::recover(&boot,"/contacts3",presence));const auto& bytes=boot.files.at("/contacts3");assert(bytes==old||bytes==next);}
 }
}
void counts(){
#if defined(ESP32_PLATFORM)
 for(bool deferred:{false,true})for(bool coalesce:{false,true}) {
  reset(image(152,9));const auto next=image(347*152,3);
  Writer w(&SPIFFS,"/contacts3",presence,true);begin(w,coalesce);write(w,next);
  assert(finish(w,deferred)==108);assert(SPIFFS.files.at("/contacts3")==next);
  assert(SPIFFS.backend_writes==(coalesce?106U:211U));
  assert(SPIFFS.largest_backend_write==(coalesce?502U:251U));
  assert(SPIFFS.reads==825&&SPIFFS.backend_reads==104);
 }
 reset(image(152,9));Writer w(&SPIFFS,"/contacts3",presence);assert(w);write(w,image(347*152));
 assert(finish(w,false,1)==829&&SPIFFS.backend_writes==211&&SPIFFS.backend_reads==413);
#endif
}
int main(int argc,char**argv){const std::string mode=argc>1?argv[1]:"all";if(mode=="contracts")contracts();else if(mode=="retire")retirement();else if(mode=="cancel")repeatedAndCancel();else if(mode=="faults")faultsAndCrash();else if(mode=="counts")counts();else assert(false);}
