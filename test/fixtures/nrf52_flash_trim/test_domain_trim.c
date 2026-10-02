#include <assert.h>
#include <stddef.h>
#include "crys_ecpki_domain.h"

static const CRYS_ECPKI_Domain_t p256 = {256};
static unsigned calls;

const CRYS_ECPKI_Domain_t *SaSi_ECPKI_GetSecp256r1DomainP(void) {
  ++calls;
  return &p256;
}

extern const CRYS_ECPKI_Domain_t *__wrap_CRYS_ECPKI_GetEcDomain(CRYS_ECPKI_DomainID_t);

int main(void) {
  assert(__wrap_CRYS_ECPKI_GetEcDomain(CRYS_ECPKI_DomainID_secp256r1) == &p256);
  assert(calls == 1);
  assert(__wrap_CRYS_ECPKI_GetEcDomain(CRYS_ECPKI_DomainID_secp192r1) == NULL);
  assert(__wrap_CRYS_ECPKI_GetEcDomain(CRYS_ECPKI_DomainID_Invalid) == NULL);
  assert(calls == 1);
  return 0;
}
