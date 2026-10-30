#include "NrfRadioUsbIrqGuard.h"

#if MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
namespace mesh { namespace radiousb {
extern "C" {
volatile Capture mesh_hil_radio_usb_irq = {
    0x4d435255, 1, sizeof(Capture), DeadlineTicks,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
}
Work work;
} }

extern "C" void RTC2_IRQHandler(void) {
  mesh::radiousb::interrupt();
}
#endif
