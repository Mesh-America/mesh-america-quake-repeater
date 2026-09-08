/* A profile may require runtime space beyond a successful static-data link.
 * __HeapBase/__HeapLimit come from the framework's nrf52_common.ld and exclude
 * SoftDevice RAM, static data and the main stack. The reserve includes all
 * dynamic allocations; it is not a measurement of free heap after startup.
 */
PROVIDE(__mesh_nrf52_min_heap_size = 0);
ASSERT(__HeapLimit >= __HeapBase, "Invalid nRF52 runtime heap boundaries")
ASSERT(__HeapLimit - __HeapBase >= __mesh_nrf52_min_heap_size,
       "nRF52 runtime heap reserve too small; reduce static tables or buffers")
