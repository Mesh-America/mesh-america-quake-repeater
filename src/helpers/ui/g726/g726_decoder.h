#ifndef MESH_G726_EXPERIMENTAL_DECODER_H
#define MESH_G726_EXPERIMENTAL_DECODER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Experimental Sun G.72x decoder with LGPL FFmpeg MIX interpolation.
 * See g726_decoder.c and COPYING.LGPLv2.1 for attribution and license.
 * All fields have explicit MCU-width types; state and code require no heap. */
typedef struct {
    int32_t yl;
    int16_t yu, dms, dml, ap;
    int16_t a[2], b[6], pk[2], dq[6], sr[2];
    int8_t td;
} G726State;

void g726_init(G726State *state);
/* bits=2 for G.726-16; bits=3 for G.726-24. No packing or allocation here. */
int16_t g726_decode(G726State *state, uint8_t code, uint8_t bits);

#ifdef __cplusplus
}
#endif
#endif
