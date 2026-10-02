/* Standalone ABI stub for a feature-preservation unit test, not firmware. */
typedef struct { unsigned marker; } CRYS_ECPKI_Domain_t;
typedef enum {
  CRYS_ECPKI_DomainID_secp192r1 = 0,
  CRYS_ECPKI_DomainID_secp256r1 = 8,
  CRYS_ECPKI_DomainID_Invalid = 255
} CRYS_ECPKI_DomainID_t;
