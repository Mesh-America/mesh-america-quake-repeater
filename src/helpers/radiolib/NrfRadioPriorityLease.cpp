#include "NrfRadioPriorityLease.h"

#if MC_NRF_RADIO_PROFILE_PRIORITY
namespace mesh { namespace radiopriority {
extern "C" {
volatile Capture mesh_hil_radio_priority = {
    0x4d435250, 1, sizeof(Capture), DeadlineTicks, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0};
}
Work work = {};
} }
#endif
