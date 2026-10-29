#include <cassert>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <helpers/bridges/RS232UartUtils.h>

using IRQn_Type = int;
struct NRF_UARTE_Type {
  uint32_t INTENCLR = 0, EVENTS_RXTO = 0, EVENTS_TXSTOPPED = 0;
  uint32_t TASKS_STOPRX = 0, TASKS_STOPTX = 0, ENABLE = 0;
  struct { uint32_t TXD = 0, RXD = 0, RTS = 0, CTS = 0; } PSEL;
};
constexpr uint32_t UARTE_INTENSET_ENDRX_Msk = 1, UARTE_INTENSET_ENDTX_Msk = 2;
constexpr uint32_t UARTE_ENABLE_ENABLE_Disabled = 0;
const uint32_t g_ADigitalPinMap[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9};
static NRF_UARTE_Type* peripheral = nullptr;
static bool hardware_completes = false;
static unsigned stops = 0, yields = 0, deleted = 0, null_deletes = 0;
void NVIC_DisableIRQ(IRQn_Type) { ++stops; }
void yield() {
  // Disabled hardware does not promise stop events. Bound the regression
  // instead of hanging a test process inside the real core's stop loop.
  if (hardware_completes) {
    peripheral->EVENTS_RXTO = peripheral->EVENTS_TXSTOPPED = 1;
  } else if (++yields == 3) {
    throw std::runtime_error("unstarted UART stop wait");
  }
}
void vSemaphoreDelete(void* semaphore) {
  // FreeRTOS vQueueDelete asserts a non-null queue. Even an optimistic
  // disabled-peripheral completion cannot make end() valid before begin().
  if (!semaphore) {
    ++null_deletes;
    throw std::runtime_error("FreeRTOS null semaphore assertion");
  }
  ++deleted;
}
struct Uart {
  NRF_UARTE_Type* nrfUart = nullptr;
  IRQn_Type IRQn = 0;
  uint8_t uc_pinRX = 0, uc_pinTX = 0, uc_hwFlow = 0;
  void* _end_tx_sem = nullptr;
  bool _begun = false;
  struct { unsigned clears = 0; void clear() { ++clears; } } rxBuffer;
  Uart(NRF_UARTE_Type*, IRQn_Type, uint8_t, uint8_t);
  void end();
  void setPins(uint8_t, uint8_t);
  // The public accessor's body is the real Uart.h contract.
  operator bool ()
  {
    return _begun;
  }
  // UART start is an explicit I/O boundary, not an emulation of baud/DMA.
  void startForTest() {
    assert(!_begun && !_end_tx_sem);
    nrfUart->ENABLE = 8;
    nrfUart->PSEL.RXD = uc_pinRX;
    nrfUart->PSEL.TXD = uc_pinTX;
    _end_tx_sem = this;
    _begun = true;
  }
};
#include "core_uart.inc"

int main() try {
  NRF_UARTE_Type registers;
  peripheral = &registers;
  Uart uart(&registers, 1, 0, 1);
  assert(!uart && !uart._end_tx_sem && !registers.ENABLE);

  // Negative controls exercise the frozen end() precondition itself. They
  // prove why a harmless-looking unconditional stop is not valid cleanup.
  bool failed = false;
  try { uart.end(); }
  catch (const std::runtime_error&) { failed = true; }
  assert(failed && yields == 3 && stops == 1 && !deleted && !null_deletes);
  hardware_completes = true;
  failed = false;
  try { uart.end(); }
  catch (const std::runtime_error&) { failed = true; }
  assert(failed && stops == 2 && !deleted && null_deletes == 1);

  // Fresh first enable and an already-stopped standby resume do not call
  // end(), touch the stop IRQ, or delete a semaphore that was never created.
  for (unsigned retry = 0; retry < 2; ++retry) {
    mesh::bridge::prepareNrfUart(uart, uint8_t(2), uint8_t(3));
    assert(!uart && !uart._end_tx_sem && stops == 2 && !deleted);
    assert(null_deletes == 1 && uart.uc_pinRX == 2 && uart.uc_pinTX == 3);
  }

  // A begun UART still must finish stop before pin remapping. All four PSEL
  // values and the semaphore reflect the actual core's complete shutdown.
  for (unsigned cycle = 0; cycle < 100; ++cycle) {
    uart.startForTest();
    assert(uart && registers.ENABLE == 8 && uart._end_tx_sem);
    const uint8_t rx = uint8_t(cycle % 4 + 2), tx = uint8_t(cycle % 4 + 6);
    mesh::bridge::prepareNrfUart(uart, rx, tx);
    assert(!uart && !uart._end_tx_sem && !registers.ENABLE);
    assert(deleted == cycle + 1 && stops == cycle + 3 && null_deletes == 1);
    assert(registers.PSEL.RXD == UINT32_MAX && registers.PSEL.TXD == UINT32_MAX);
    assert(registers.PSEL.RTS == UINT32_MAX && registers.PSEL.CTS == UINT32_MAX);
    assert(uart.uc_pinRX == rx && uart.uc_pinTX == tx);
    const unsigned stopped = stops, freed = deleted;
    mesh::bridge::prepareNrfUart(uart, rx, tx);
    assert(!uart && stops == stopped && deleted == freed);
  }
  puts("PASS: nRF UART lifecycle; fresh/stopped guards and 100 running remaps");
} catch (const std::exception& error) {
  std::fprintf(stderr, "%s\n", error.what());
  return 2;
}
