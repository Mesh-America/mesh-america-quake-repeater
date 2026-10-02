/* Keep the exact P-256 domain used by Bluefruit Secure Connections. The
 * pinned CC310 archive's generic getter otherwise retains every legacy EC
 * curve table. MeshCore identity signatures use Edwards25519 via a different
 * API and are unaffected. Build-local linker wrapping is qualified by the
 * SDK archive hash in scripts/nrf52_flash_trim.py, never by MCU name alone.
 */
#if defined(MESH_NRF52_FLASH_TRIM) && MESH_NRF52_FLASH_TRIM
#include <stddef.h>
#include "crys_ecpki_domain.h"

extern const CRYS_ECPKI_Domain_t *SaSi_ECPKI_GetSecp256r1DomainP(void);

const CRYS_ECPKI_Domain_t *__wrap_CRYS_ECPKI_GetEcDomain(
    CRYS_ECPKI_DomainID_t domain_id) {
  if (domain_id != CRYS_ECPKI_DomainID_secp256r1) return NULL;
  return SaSi_ECPKI_GetSecp256r1DomainP();
}
#endif
