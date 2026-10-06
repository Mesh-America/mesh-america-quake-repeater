#include <atomic>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <string>
#include <vector>
using String = std::string;
constexpr int HTTP_GET=0, HTTP_POST=1, U_FLASH=0, U_SPIFFS=100;
constexpr unsigned UPDATE_SIZE_UNKNOWN=~0U;
constexpr int pdPASS=1;
constexpr int ERR_OK=0;
#define async_tcp_log_d(...) ((void)0)
#define pdMS_TO_TICKS(value) (value)
const char ELEGANT_HTML[] = "page";
const unsigned ELEGANT_HTML_SIZE=sizeof(ELEGANT_HTML);
int Serial=0;
bool in_network_callback=false;
struct Esp {
  int restarts=0;
  void restart() { assert(!in_network_callback); ++restarts; }
} ESP;
void yield() { assert(!in_network_callback); }
void delay(unsigned) { assert(!in_network_callback); }
void vTaskDelay(unsigned) { assert(!in_network_callback); }
void vTaskDelete(void*) {}
using Task = void (*)(void*);
Task pending_task=nullptr;
bool allow_task=true;
int xTaskCreate(Task task, const char*, unsigned, void*, unsigned, void*) {
  if (!allow_task) return 0;
  assert(!pending_task); pending_task=task; return pdPASS;
}
@REBOOT_STATE@
struct Parameter { String text="valid"; String value() { return text; } };
struct Response {
  int code;
  String body;
  void addHeader(const char*, const char*) {}
};
unsigned fixture_now=0;
struct Client {
  unsigned _rx_timeout=0, _rx_last_packet=fixture_now;
  bool closed=false;
  std::vector<unsigned> timeout_changes;
  std::function<void()> disconnected;
  void setRxTimeout(unsigned seconds) { _rx_timeout=seconds; timeout_changes.push_back(seconds); }
  void received() { _rx_last_packet=fixture_now; }
  void _close() { closed=true; if (disconnected) disconnected(); }
  int poll() {
    const unsigned now=fixture_now;
@RX_TIMEOUT@
    return ERR_OK;
  }
};
void accept(Client* c) {
@ACCEPT_TIMEOUT@
}
struct Request {
  void* _tempObject=nullptr;
  bool md5_present=true, authorized=true, sent=false;
  int code=0;
  String body;
  Response* queued_response=nullptr;
  std::function<void()> disconnected;
  Parameter md5;
  Client connection;
  Request() { accept(&connection); }
  ~Request() { free(_tempObject); delete queued_response; }
  Client* client() { return &connection; }
  bool authenticate(const char*, const char*) { return authorized; }
  void requestAuthentication() { send(401,"text/plain","unauthorized"); }
  bool hasParam(const char*, bool) { return md5_present; }
  Parameter* getParam(const char*, bool) { return &md5; }
  Response* beginResponse(int code, const char*, const char* text) { return new Response{code,text}; }
  Response* beginResponse_P(int code, const char*, const char* text, unsigned) { return new Response{code,text}; }
  void send(Response* response) { delete queued_response; queued_response=response; code=response->code; body=response->body; }
  void send(int status, const char*, const char* text) { send(new Response{status,text}); }
  void send(int status, const char*, const String& text) { send(new Response{status,text}); }
  Response* getResponse() const { return queued_response; }
  void flush_response() { assert(queued_response); sent=true; connection.setRxTimeout(0); }
  bool isSent() const { return sent; }
  void onDisconnect(std::function<void()> fn) { disconnected=fn; connection.disconnected=fn; }
};
using AsyncWebServerRequest=Request;
static AsyncWebServerRequest* ota_upload_owner=nullptr;
using AsyncWebServerResponse=Response;
struct AsyncWebServer {
  std::function<void(Request*)> completion;
  std::function<void(Request*,String,size_t,uint8_t*,size_t,bool)> upload;
  template<class F> void on(const char*, int, F) {}
  template<class F,class U> void on(const char*, int method, F callback, U chunks) {
    assert(method==HTTP_POST); completion=callback; upload=chunks;
  }
};
struct UpdateFake {
  bool error=false, fail_begin=false, fail_end=false, fail_write=false;
  int aborts=0, writes=0;
  bool hasError() const { return error; }
  bool setMD5(const char* md5) { return String(md5)=="valid"; }
  bool begin(unsigned, int) { error=fail_begin; return !error; }
  size_t write(uint8_t*, size_t size) { ++writes; error=fail_write; return fail_write ? size-1 : size; }
  bool end(bool) { error=fail_end; return !error; }
  void abort() { error=true; ++aborts; }
  // A connected USB host which does not drain TX can block raw Serial. Every
  // upload error path must complete without attempting that raw print.
  void printError(int) { assert(false && "Raw USB printing can block OTA callbacks"); }
} Update;
struct AsyncElegantOtaClass {
  AsyncWebServer* _server=nullptr;
  bool _authRequired=false;
  String _username, _password, _id="fixture";
  void begin(AsyncWebServer*, const char*, const char*);
  void restart();
  bool setEnabled(bool);
};
@BEGIN@
@RESTART@

int main() {
  AsyncWebServer server;
  AsyncElegantOtaClass ota;
  ota.begin(&server,"","");
  auto complete=[&](Request& request) {
    in_network_callback=true;
    server.completion(&request); request.flush_response();
    in_network_callback=false;
  };
  auto upload=[&](Request& request) {
    uint8_t data[8]={};
    in_network_callback=true;
    server.upload(&request,"firmware",0,data,sizeof(data),true);
    in_network_callback=false;
  };
#ifdef TEST_OTA_BODY_TIMEOUT
  {
  uint8_t chunk[4]={};
  auto receive=[&](Request& request,size_t index,bool final) {
    assert(!request.connection.closed);
    request.connection.received();
    in_network_callback=true;
    server.upload(&request,"firmware",index,chunk,sizeof(chunk),final);
    in_network_callback=false;
  };
  auto idle=[&](Request& request,unsigned ms) {
    fixture_now+=ms;
    in_network_callback=true; request.connection.poll(); in_network_callback=false;
  };
  Request ordinary;
  assert(ordinary.connection._rx_timeout==3);
  idle(ordinary,4000);
  assert(ordinary.connection.closed && !ota_upload_owner);
  Request admitted;
  receive(admitted,0,false);
  assert(ota_upload_owner==&admitted && !admitted.sent
      && admitted.connection.timeout_changes==std::vector<unsigned>({3,30}));
  Request concurrent;
  upload(concurrent);
  assert(!concurrent.isSent() && concurrent.getResponse()
      && concurrent.connection.timeout_changes==std::vector<unsigned>({3}));
  complete(concurrent);
  assert(concurrent.code==409 && ota_upload_owner==&admitted
      && concurrent.connection.timeout_changes==std::vector<unsigned>({3,0}));
  Request untouched;
  assert(untouched.connection._rx_timeout==3);
  idle(admitted,4000);
  assert(!admitted.connection.closed && ota_upload_owner==&admitted);
  idle(admitted,25999);
  assert(!admitted.connection.closed);
  idle(admitted,1);
  assert(admitted.connection.closed && Update.aborts==1 && !ota_upload_owner
      && !ota_upload_busy.load() && !pending_task && ESP.restarts==0);
  Request missing_md5;
  missing_md5.md5_present=false;
  upload(missing_md5);
  assert(!missing_md5.isSent() && missing_md5.getResponse()
      && missing_md5.connection.timeout_changes==std::vector<unsigned>({3}));
  complete(missing_md5);
  assert(missing_md5.code==400
      && missing_md5.connection.timeout_changes==std::vector<unsigned>({3,0})
      && !ota_upload_owner && !ota_upload_busy.load());
  Request bad_md5;
  bad_md5.md5.text="invalid";
  upload(bad_md5); complete(bad_md5);
  assert(bad_md5.code==400 && !ota_upload_owner && !ota_upload_busy.load()
      && bad_md5.connection.timeout_changes==std::vector<unsigned>({3,0}));
  ota.begin(&server,"admin","password");
  Request unauthorized;
  unauthorized.authorized=false;
  upload(unauthorized); complete(unauthorized);
  assert(unauthorized.code==401 && !ota_upload_owner && !ota_upload_busy.load()
      && unauthorized.connection.timeout_changes==std::vector<unsigned>({3,0}));
  ota.begin(&server,"","");
  Request successful;
  receive(successful,0,false);
  idle(successful,4000);
  assert(!successful.connection.closed && ota_upload_owner==&successful);
  receive(successful,sizeof(chunk),true);
  complete(successful);
  assert(successful.code==200 && successful.body=="OK"
      && successful.connection._rx_timeout==0 && !pending_task);
  in_network_callback=true; successful.disconnected(); in_network_callback=false;
  assert(pending_task && !ota_upload_owner);
  auto task=pending_task; pending_task=nullptr; task(nullptr);
  assert(ESP.restarts==1);
  return 0;
  }
#endif
  // A POST without an actual completed upload cannot report OK or reboot.
  Request empty;
  complete(empty);
  assert(empty.code>=400 && !pending_task && ESP.restarts==0);
  Request invalid;
  invalid.md5_present=false;
  upload(invalid); complete(invalid);
  assert(invalid.code==400 && !pending_task && ESP.restarts==0);
  Request begin_failed;
  Update.fail_begin=true;
  upload(begin_failed); complete(begin_failed);
  assert(begin_failed.code==400 && begin_failed.body=="OTA could not begin"
      && !ota_upload_owner && !ota_upload_busy.load() && Update.aborts==0
      && !pending_task && ESP.restarts==0);
  Update.fail_begin=false;
  Request corrupt;
  Update.fail_end=true;
  upload(corrupt); complete(corrupt);
  assert(corrupt.code==400 && !pending_task && ESP.restarts==0);
  in_network_callback=true; corrupt.disconnected(); in_network_callback=false;
  assert(Update.aborts==1 && ota_upload_owner==nullptr);
  Update.fail_end=false;
  Request partial;
  uint8_t chunk[4]={};
  server.upload(&partial,"firmware",0,chunk,sizeof(chunk),false);
  assert(!ota.setEnabled(false)); // An admitted upload keeps its listener alive.
  Request concurrent;
  upload(concurrent); complete(concurrent);
  assert(concurrent.code==409 && ota_upload_owner==&partial);
  in_network_callback=true; partial.disconnected(); in_network_callback=false;
  assert(Update.aborts==2 && ota_upload_owner==nullptr && ESP.restarts==0);
  assert(ota.setEnabled(false));
  Request stopped;
  upload(stopped); complete(stopped);
  assert(stopped.code==503 && !ota_upload_owner && !pending_task);
  assert(ota.setEnabled(true));
  Request write_failed;
  Update.fail_write=true;
  server.upload(&write_failed,"firmware",0,chunk,sizeof(chunk),false);
  assert(!write_failed.isSent() && write_failed.getResponse()
      && write_failed.code==400 && write_failed.body=="OTA flash write failed");
  const int writes_after_error=Update.writes;
  server.upload(&write_failed,"firmware",sizeof(chunk),chunk,sizeof(chunk),true);
  assert(Update.writes==writes_after_error);
  server.upload(&write_failed,"firmware",0,chunk,sizeof(chunk),false);
  assert(Update.writes==writes_after_error && write_failed.code==400
      && write_failed.body=="OTA flash write failed");
  complete(write_failed);
  assert(write_failed.code==400 && write_failed.body=="OTA flash write failed"
      && !pending_task);
  in_network_callback=true; write_failed.disconnected(); in_network_callback=false;
  assert(Update.aborts==3 && !ota_upload_owner && !ota_upload_busy.load());
  Update.fail_write=false;
  Request valid;
  upload(valid); complete(valid);
  assert(valid.code==200 && valid.disconnected && !pending_task && ESP.restarts==0);
  // The response drains before disconnect; its callback only schedules work.
  in_network_callback=true; valid.disconnected(); in_network_callback=false;
  assert(pending_task && ESP.restarts==0);
  auto task=pending_task; pending_task=nullptr; task(nullptr);
  assert(ESP.restarts==1);
}
