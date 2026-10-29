#include "NrfRadioSpiReadProbe.h"

#if MESH_HIL_SPI_READ_PROBE
namespace mesh { namespace spireadprobe {
extern "C" {
volatile Capture mesh_hil_spi_read_probe = {
    0x4d435352, 1, sizeof(Capture), UINT32_MAX, 0, 0, 0, 0, {}};
}
} }
#endif
