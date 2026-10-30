#include "NrfRadioIrqObserver.h"

#if MESH_HIL_IRQ_TIMING
namespace mesh { namespace irqobserver {
extern "C" {
volatile Counter mesh_hil_irq_counters[SourceCount] = {};
volatile uint32_t mesh_hil_irq_selected[TaskKindCount + 2] = {};
volatile Capture mesh_hil_radio_irqs = {
    0x4d434952, 2, sizeof(Capture), 0, SourceCount, 0, 0, 0, 0, 0, {}};
}
std::atomic<uint32_t> revision{0};
Work work;
} }

// These are ordinary C handlers. Do not wrap SVC/PendSV: their naked
// context-switch assembly requires the original exception LR/PSP contract.
// Final ELF vectors/calls must be checked; weak aliases or LTO can bypass
// a linker wrapper. No priority, masking, task, USB or device policy changes.
#define MESH_OBSERVE_IRQ(symbol, source) \
extern "C" void __real_##symbol(void); \
extern "C" void __wrap_##symbol(void) { \
  const uint32_t started = mesh::irqobserver::clock(); \
  __real_##symbol(); \
  mesh::irqobserver::record(mesh::irqobserver::source, mesh::irqobserver::clock() - started); \
}
MESH_OBSERVE_IRQ(RTC1_IRQHandler, Rtc1)
MESH_OBSERVE_IRQ(GPIOTE_IRQHandler, Gpiote)
MESH_OBSERVE_IRQ(UARTE0_UART0_IRQHandler, Uart0)
MESH_OBSERVE_IRQ(UARTE1_IRQHandler, Uart1)
MESH_OBSERVE_IRQ(POWER_CLOCK_IRQHandler, PowerClock)
MESH_OBSERVE_IRQ(USBD_IRQHandler, Usb)
MESH_OBSERVE_IRQ(SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler, Twim0Spim0)
#undef MESH_OBSERVE_IRQ

extern "C" void __real_vTaskSwitchContext(void);
extern "C" void __wrap_vTaskSwitchContext(void) {
  const uint32_t started = mesh::irqobserver::clock();
  __real_vTaskSwitchContext();
  const uint32_t cycles = mesh::irqobserver::clock() - started;
  // In the pinned SDK this is a non-blocking name lookup from the newly
  // selected TCB. It uses no critical section or RTOS state mutation.
  mesh::irqobserver::record(mesh::irqobserver::Scheduler, cycles, pcTaskGetName(nullptr));
}
#endif
