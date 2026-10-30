#include "NrfRadioSpiStartupDiagHal.h"

#if MESH_HIL_SPI_STARTUP_DIAG
namespace mesh { namespace spistartup {
extern "C" {
volatile Capture mesh_hil_spi_startup = {
    0x4d435353, 2, sizeof(Capture), Idle,
    0, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX,
    0, 0, 0, UINT32_MAX, 0, UINT32_MAX, 0, 0,
    {UINT32_MAX, UINT32_MAX, UINT32_MAX}};
}
} }
#endif
