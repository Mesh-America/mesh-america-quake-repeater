#include <atomic>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <string>
using String = std::string;
constexpr int HTTP_GET=0, HTTP_POST=1, U_FLASH=0, U_SPIFFS=100;
constexpr unsigned UPDATE_SIZE_UNKNOWN=~0U;
constexpr int pdPASS=1;
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
  void addHeader(const char*, const char*) {}
};
struct Request {
  void* _tempObject=nullptr;
  bool md5_present=true, authorized=true, sent=false;
  int code=0;
  std::function<void()> disconnected;
  Parameter md5;
  ~Request() { free(_tempObject); }
  bool authenticate(const char*, const char*) { return authorized; }
  void requestAuthentication() { code=401; sent=true; }
  bool hasParam(const char*, bool) { return md5_present; }
  Parameter* getParam(const char*, bool) { return &md5; }
  Response* beginResponse(int code, const char*, const char*) { return new Response{code}; }
  Response* beginResponse_P(int code, const char*, const char*, unsigned) { return new Response{code}; }
  void send(Response* response) { code=response->code; sent=true; delete response; }
  void send(int status, const char*, const char*) { code=status; sent=true; }
  void send(int status, const char*, const String&) { code=status; sent=true; }
  bool isSent() const { return sent; }
  void onDisconnect(std::function<void()> fn) { disconnected=fn; }
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
  bool error=false, fail_end=false;
  int aborts=0;
  bool hasError() const { return error; }
  bool setMD5(const char* md5) { return String(md5)=="valid"; }
  bool begin(unsigned, int) { error=false; return true; }
  size_t write(uint8_t*, size_t size) { return size; }
  bool end(bool) { error=fail_end; return !error; }
  void abort() { error=true; ++aborts; }
  void printError(int) {}
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
    in_network_callback=true; server.completion(&request); in_network_callback=false;
  };
  auto upload=[&](Request& request) {
    uint8_t data[8]={};
    in_network_callback=true;
    server.upload(&request,"firmware",0,data,sizeof(data),true);
    in_network_callback=false;
  };
  // A POST without an actual completed upload cannot report OK or reboot.
  Request empty;
  complete(empty);
  assert(empty.code>=400 && !pending_task && ESP.restarts==0);
  Request invalid;
  invalid.md5_present=false;
  upload(invalid); complete(invalid);
  assert(invalid.code==400 && !pending_task && ESP.restarts==0);
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
  Request valid;
  upload(valid); complete(valid);
  assert(valid.code==200 && valid.disconnected && !pending_task && ESP.restarts==0);
  // The response drains before disconnect; its callback only schedules work.
  in_network_callback=true; valid.disconnected(); in_network_callback=false;
  assert(pending_task && ESP.restarts==0);
  auto task=pending_task; pending_task=nullptr; task(nullptr);
  assert(ESP.restarts==1);
}
