/*
 * This source code is a product of Sun Microsystems, Inc. and is provided
 * for unrestricted use.  Users may copy or modify this source code without
 * charge.
 *
 * SUN SOURCE CODE IS PROVIDED AS IS WITH NO WARRANTIES OF ANY KIND INCLUDING
 * THE WARRANTIES OF DESIGN, MERCHANTIBILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE, OR ARISING FROM A COURSE OF DEALING, USAGE OR TRADE PRACTICE.
 *
 * Sun source code is provided with no support and without any obligation on
 * the part of Sun Microsystems, Inc. to assist in its use, correction,
 * modification or enhancement.
 *
 * SUN MICROSYSTEMS, INC. SHALL HAVE NO LIABILITY WITH RESPECT TO THE
 * INFRINGEMENT OF COPYRIGHTS, TRADE SECRETS OR ANY PATENTS BY THIS SOFTWARE
 * OR ANY PART THEREOF.
 *
 * In no event will Sun Microsystems, Inc. be liable for any lost revenue
 * or profits or other special, indirect and consequential damages, even if
 * Sun has been advised of the possibility of such damages.
 *
 * Sun Microsystems, Inc.
 * 2550 Garcia Avenue
 * Mountain View, California  94043
 */
/* Decoder-only adaptation for MeshCore experiments, 2026.
 * Common code and G.723-24 tables: Sun source at codec-g7xx commit
 * 2ebdfe0c76670c6f887542fd4c291afbab988cdc, src/g72x.c and src/g723_24.c.
 * G.726-16 tables: Marc Randolph's 16 kbps adaptation, libsndfile commit
 * b9103bd48b6c8fb517ae737fe3baee0c718b804c, src/G72x/g723_16.c.
 * Encoder, A-law/u-law conversion and heap/block interfaces are removed.
 * Sun fmult rounding (+0x30) is preserved. Negative left shifts are replaced
 * by multiplication. State widths are fixed, rather than native long/short.
 */
/* MIX interpolation adapted from FFmpeg n7.1 libavcodec/g726.c.
 * Copyright (c) 2004 Roman Shaposhnik.
 * The MIX adaptation is under GNU LGPL version 2.1 or (at your option) later.
 * This combined experimental source is distributed under that LGPL license;
 * the original Sun unrestricted-use notice is retained above.
 * See COPYING.LGPLv2.1 next to this source. No production codec change is made.
 * Corrected fractional MIX matches FFmpeg sample-for-sample; this does not
 * constitute independent ITU conformance qualification.
 */
#include "g726_decoder.h"

#if defined(MESH_G726_DECODER_TEST) || \
    (defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_G726_BITRATE))

static const int16_t power2[15] = {
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384
};
#if !defined(MESH_GPS_VOICE_G726_BITRATE) || MESH_GPS_VOICE_G726_BITRATE == 16
static const int16_t dqln16[4] = {116, 365, 365, 116};
static const int16_t wi16[4] = {-704, 14048, 14048, -704};
static const int16_t fi16[4] = {0, 0xe00, 0xe00, 0};
#endif
#if !defined(MESH_GPS_VOICE_G726_BITRATE) || MESH_GPS_VOICE_G726_BITRATE == 24
static const int16_t dqln24[8] = {-2048, 135, 273, 373, 373, 273, 135, -2048};
static const int16_t wi24[8] = {-128, 960, 4384, 18624, 18624, 4384, 960, -128};
static const int16_t fi24[8] = {0, 0x200, 0x400, 0xe00, 0xe00, 0x400, 0x200, 0};
#endif

static int quan(int value)
{
    int i;
    for (i = 0; i < 15; ++i)
        if (value < power2[i]) break;
    return i;
}

static int fmult(int an, int srn)
{
    int16_t anmag = (int16_t)(an > 0 ? an : ((-an) & 0x1fff));
    int16_t anexp = (int16_t)(quan(anmag) - 6);
    int16_t anmant = (int16_t)(anmag == 0 ? 32 : anexp >= 0
                              ? anmag >> anexp : anmag * (1 << -anexp));
    int16_t wanexp = (int16_t)(anexp + ((srn >> 6) & 15) - 13);
    int16_t wanmant = (int16_t)((anmant * (srn & 63) + 0x30) >> 4);
    int16_t retval = (int16_t)(wanexp >= 0
                               ? (wanmant * (1 << wanexp)) & 0x7fff
                               : wanmant >> -wanexp);
    return (an ^ srn) < 0 ? -retval : retval;
}

void g726_init(G726State *s)
{
    unsigned i;
    s->yl = 34816;
    s->yu = 544;
    s->dms = s->dml = s->ap = 0;
    for (i = 0; i < 2; ++i) {
        s->a[i] = s->pk[i] = 0;
        s->sr[i] = 32;
    }
    for (i = 0; i < 6; ++i) {
        s->b[i] = 0;
        s->dq[i] = 32;
    }
    s->td = 0;
}

static int predictor_zero(const G726State *s)
{
    int i, sezi = fmult(s->b[0] >> 2, s->dq[0]);
    for (i = 1; i < 6; ++i) sezi += fmult(s->b[i] >> 2, s->dq[i]);
    return sezi;
}

static int predictor_pole(const G726State *s)
{
    return fmult(s->a[1] >> 2, s->sr[1]) + fmult(s->a[0] >> 2, s->sr[0]);
}

static int step_size(const G726State *s)
{
    if (s->ap >= 256) return s->yu;
    /* Retain fractional yl before the final shift, rather than truncating it
     * first and applying the Sun reference's negative-difference rounding. */
    return (s->yl + (s->yu - (s->yl >> 6)) * (s->ap >> 2)) >> 6;
}

static int reconstruct(int sign, int dqln, int y)
{
    int16_t dql = (int16_t)(dqln + (y >> 2));
    int16_t dex, dqt, dq;
    if (dql < 0) return sign ? -32768 : 0;
    dex = (dql >> 7) & 15;
    dqt = 128 + (dql & 127);
    dq = (int16_t)((dqt * 128) >> (14 - dex));
    return sign ? dq - 32768 : dq;
}

static int magnitude(int value) { return value < 0 ? -value : value; }

static void update(int y, int wi, int fi, int dq, int sr, int dqsez, G726State *s)
{
    int cnt;
    int16_t mag, exp, a2p = 0, a1ul, pks1, fa1;
    int16_t ylint, ylfrac, thr1, thr2, dqthr, pk0;
    int8_t tr;
    pk0 = dqsez < 0 ? 1 : 0;
    mag = dq & 0x7fff;
    ylint = (int16_t)(s->yl >> 15);
    ylfrac = (s->yl >> 10) & 31;
    thr1 = (int16_t)((32 + ylfrac) * (1 << ylint));
    thr2 = ylint > 9 ? 31 * 1024 : thr1;
    dqthr = (thr2 + (thr2 >> 1)) >> 1;
    tr = s->td != 0 && mag > dqthr;

    s->yu = (int16_t)(y + ((wi - y) >> 5));
    if (s->yu < 544) s->yu = 544;
    else if (s->yu > 5120) s->yu = 5120;
    s->yl += s->yu + ((-s->yl) >> 6);

    if (tr) {
        s->a[0] = s->a[1] = 0;
        for (cnt = 0; cnt < 6; ++cnt) s->b[cnt] = 0;
    } else {
        pks1 = pk0 ^ s->pk[0];
        a2p = (int16_t)(s->a[1] - (s->a[1] >> 7));
        if (dqsez != 0) {
            fa1 = pks1 ? s->a[0] : (int16_t)-s->a[0];
            if (fa1 < -8191) a2p -= 256;
            else if (fa1 > 8191) a2p += 255;
            else a2p += fa1 >> 5;
            if (pk0 ^ s->pk[1]) {
                if (a2p <= -12160) a2p = -12288;
                else if (a2p >= 12416) a2p = 12288;
                else a2p -= 128;
            } else {
                if (a2p <= -12416) a2p = -12288;
                else if (a2p >= 12160) a2p = 12288;
                else a2p += 128;
            }
        }
        s->a[1] = a2p;
        s->a[0] -= s->a[0] >> 8;
        if (dqsez != 0) s->a[0] += pks1 == 0 ? 192 : -192;
        a1ul = 15360 - a2p;
        if (s->a[0] < -a1ul) s->a[0] = (int16_t)-a1ul;
        else if (s->a[0] > a1ul) s->a[0] = a1ul;
        for (cnt = 0; cnt < 6; ++cnt) {
            s->b[cnt] -= s->b[cnt] >> 8;
            if (dq & 0x7fff) s->b[cnt] += (dq ^ s->dq[cnt]) >= 0 ? 128 : -128;
        }
    }
    for (cnt = 5; cnt > 0; --cnt) s->dq[cnt] = s->dq[cnt - 1];
    if (mag == 0) s->dq[0] = dq >= 0 ? 32 : -992;
    else {
        exp = (int16_t)quan(mag);
        s->dq[0] = (int16_t)(exp * 64 + ((mag * 64) >> exp) - (dq >= 0 ? 0 : 1024));
    }
    s->sr[1] = s->sr[0];
    if (sr == 0) s->sr[0] = 32;
    else if (sr > 0) {
        exp = (int16_t)quan(sr);
        s->sr[0] = (int16_t)(exp * 64 + ((sr * 64) >> exp));
    } else if (sr > -32768) {
        mag = (int16_t)-sr;
        exp = (int16_t)quan(mag);
        s->sr[0] = (int16_t)(exp * 64 + ((mag * 64) >> exp) - 1024);
    } else s->sr[0] = -992;
    s->pk[1] = s->pk[0];
    s->pk[0] = pk0;
    s->td = !tr && a2p < -11776;
    s->dms += (fi - s->dms) >> 5;
    s->dml += (fi * 4 - s->dml) >> 7;
    if (tr) s->ap = 256;
    else if (y < 1536 || s->td == 1 || magnitude(s->dms * 4 - s->dml) >= (s->dml >> 3))
        s->ap += (512 - s->ap) >> 4;
    else s->ap += (-s->ap) >> 4;
}

int16_t g726_decode(G726State *s, uint8_t code, uint8_t bits)
{
    int16_t sezi, sei, sez, se, y, sr, dq, dqsez;
    const int16_t *dqln, *wi, *fi;
    int sign;
    if (bits == 2) {
#if !defined(MESH_GPS_VOICE_G726_BITRATE) || MESH_GPS_VOICE_G726_BITRATE == 16
        code &= 3;
        sign = code & 2;
        dqln = dqln16; wi = wi16; fi = fi16;
#else
        return 0;
#endif
    } else if (bits == 3) {
#if !defined(MESH_GPS_VOICE_G726_BITRATE) || MESH_GPS_VOICE_G726_BITRATE == 24
        code &= 7;
        sign = code & 4;
        dqln = dqln24; wi = wi24; fi = fi24;
#else
        return 0;
#endif
    } else return 0;
    sezi = (int16_t)predictor_zero(s);
    sez = sezi >> 1;
    sei = (int16_t)(sezi + predictor_pole(s));
    se = sei >> 1;
    y = (int16_t)step_size(s);
    dq = (int16_t)reconstruct(sign, dqln[code], y);
    sr = (int16_t)(dq < 0 ? se - (dq & 0x3fff) : se + dq);
    dqsez = (int16_t)(sr - se + sez);
    update(y, wi[code], fi[code], dq, sr, dqsez, s);
    return (int16_t)(sr * 4);
}


#endif /* experimental decoder only */
