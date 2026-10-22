#pragma once
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <cstdarg>
#include <vector>
#include <deque>
#include <cstring>
namespace udp_test {
struct Datagram { sockaddr_in source{}, target{}; std::vector<uint8_t> bytes; };
struct Socket { bool open = false; uint32_t ip = 0; uint16_t port = 0; std::deque<Datagram> rx; };
inline Socket sockets[64];
inline int next_socket = 0, opens = 0, receives = 0, sends = 0, receive_cap = 0;
inline uint32_t creating_ip = 0;
inline bool fail_send = false, fail_rcvbuf = false;
inline std::vector<Datagram> sent;
inline void inject(int index, const Datagram& packet) { sockets[index].rx.push_back(packet); }
}
inline int udpTestSocket(int, int, int) {
  const int fd = udp_test::next_socket++;
  if (fd >= 64) { errno = EMFILE; return -1; }
  udp_test::sockets[fd] = {}; udp_test::sockets[fd].open = true;
  udp_test::sockets[fd].ip = udp_test::creating_ip; ++udp_test::opens;
  return fd;
}
inline int udpTestClose(int fd) { udp_test::sockets[fd].open = false; udp_test::sockets[fd].rx.clear(); return 0; }
inline int udpTestFcntl(int, int, ...) { return 0; }
inline int udpTestSetsockopt(int, int, int, const void* value, socklen_t) {
  if (udp_test::fail_rcvbuf) { errno = ENOPROTOOPT; return -1; }
  udp_test::receive_cap = *static_cast<const int*>(value); return 0;
}
inline int udpTestBind(int fd, const sockaddr* address, socklen_t) {
  udp_test::sockets[fd].port = reinterpret_cast<const sockaddr_in*>(address)->sin_port; return 0;
}
inline int udpTestSendto(int fd, const void* bytes, size_t size, int, const sockaddr* address, socklen_t) {
  ++udp_test::sends;
  if (udp_test::fail_send) { udp_test::fail_send = false; errno = ENOMEM; return -1; }
  udp_test::Datagram message;
  message.source.sin_family = AF_INET; message.source.sin_port = udp_test::sockets[fd].port;
  message.source.sin_addr.s_addr = udp_test::sockets[fd].ip;
  message.target = *reinterpret_cast<const sockaddr_in*>(address);
  message.bytes.assign(static_cast<const uint8_t*>(bytes), static_cast<const uint8_t*>(bytes) + size);
  udp_test::sent.push_back(message);
  for (auto& socket : udp_test::sockets)
    if (socket.open && socket.ip == message.target.sin_addr.s_addr && socket.port == message.target.sin_port) {
      size_t queued = 0; for (const auto& item : socket.rx) queued += item.bytes.size();
      if (socket.rx.size() < 6 && queued + size <= 768) socket.rx.push_back(message);
    }
  return static_cast<int>(size);
}
inline int udpTestRecvfrom(int fd, void* out, size_t size, int, sockaddr* address, socklen_t* address_size) {
  ++udp_test::receives;
  auto& queue = udp_test::sockets[fd].rx;
  if (queue.empty()) { errno = EAGAIN; return -1; }
  const auto message = queue.front(); queue.pop_front();
  const size_t count = message.bytes.size() < size ? message.bytes.size() : size;
  memcpy(out, message.bytes.data(), count);
  memcpy(address, &message.source, sizeof(message.source)); *address_size = sizeof(message.source);
  return static_cast<int>(count);
}
#define socket udpTestSocket
#define close udpTestClose
#define fcntl udpTestFcntl
#define setsockopt udpTestSetsockopt
#define bind udpTestBind
#define sendto udpTestSendto
#define recvfrom udpTestRecvfrom
