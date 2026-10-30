#pragma once

namespace mesh {
namespace bridge {

template <typename UartType, typename PinType>
inline void prepareNrfUart(UartType& uart, PinType rx, PinType tx) {
  // Adafruit Uart::end() requires a begun peripheral and a live TX semaphore.
  // Its public bool reports that state; a fresh or already stopped UART must
  // not wait for stop events or delete an unallocated semaphore.
  if (uart) uart.end();
  uart.setPins(rx, tx);
}

} // namespace bridge
} // namespace mesh
