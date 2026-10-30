/*
 * Loop form of the ref10 scalar arithmetic in sc.c. The 21-bit limbs,
 * folding coefficients, and carry order are unchanged. Small STM32
 * Companion images cannot afford the unrolled reduction and multiply-add.
 * All loop bounds and memory addresses depend only on public limb indices;
 * scalar values never select a branch or an array index.
 */

static void sc_unpack(int64_t *limbs, const unsigned char *bytes, int count) {
    const int size = count == 24 ? 64 : 32;
    int i;
    for (i = 0; i < count; ++i) {
        const int start = (i * 21) >> 3;
        const int shift = (i * 21) & 7;
        uint32_t word = 0;
        int j;
        for (j = 0; j < 4 && start + j < size; ++j)
            word |= (uint32_t)bytes[start + j] << (j * 8);
        word >>= shift;
        /* The last limb retains every remaining input bit, as in ref10. */
        limbs[i] = (int64_t)(i == count - 1 ? word : word & 2097151);
    }
}

static void sc_carry(int64_t *limbs, int first, int last, int step, int rounded) {
    int i;
    for (i = first; i <= last; i += step) {
        const int64_t value = (limbs[i] + (rounded ? 1048576 : 0)) >> 21;
        limbs[i + 1] += value;
        /* A carry can be negative; multiplication avoids a signed left shift. */
        limbs[i] -= value * 2097152;
    }
}

static void sc_fold(int64_t *limbs, int first, int last) {
    static const int32_t coefficients[6] = {666643, 470296, 654183, -997805, 136657, -683901};
    int i;
    for (i = first; i >= last; --i) {
        int j;
        for (j = 0; j < 6; ++j)
            limbs[i - 12 + j] += limbs[i] * coefficients[j];
        limbs[i] = 0;
    }
}

static void sc_reduce_limbs(unsigned char *out, int64_t limbs[24]) {
    int i;
    sc_fold(limbs, 23, 18);
    sc_carry(limbs, 6, 16, 2, 1);
    sc_carry(limbs, 7, 15, 2, 1);
    sc_fold(limbs, 17, 12);
    sc_carry(limbs, 0, 10, 2, 1);
    sc_carry(limbs, 1, 11, 2, 1);
    sc_fold(limbs, 12, 12);
    sc_carry(limbs, 0, 11, 1, 0);
    sc_fold(limbs, 12, 12);
    sc_carry(limbs, 0, 10, 1, 0);
    /* Encode the same 256 low bits as ref10's byte assignments. */
    for (i = 0; i < 32; ++i) {
        const int index = (i * 8) / 21;
        const int shift = (i * 8) % 21;
        uint64_t word = (uint64_t)limbs[index] >> shift;
        if (shift > 13 && index < 11)
            word |= (uint64_t)limbs[index + 1] << (21 - shift);
        out[i] = (unsigned char)word;
    }
}

void sc_reduce(unsigned char *s) {
    int64_t limbs[24];
    sc_unpack(limbs, s, 24);
    sc_reduce_limbs(s, limbs);
}

void sc_muladd(unsigned char *s, const unsigned char *a, const unsigned char *b, const unsigned char *c) {
    int64_t aa[12], bb[12], limbs[24] = {0};
    int i, j;
    /* Read all inputs before writing the result; s may alias a, b, or c. */
    sc_unpack(aa, a, 12);
    sc_unpack(bb, b, 12);
    sc_unpack(limbs, c, 12);
    for (i = 0; i < 12; ++i)
        for (j = 0; j < 12; ++j)
            limbs[i + j] += aa[i] * bb[j];
    sc_carry(limbs, 0, 22, 2, 1);
    sc_carry(limbs, 1, 21, 2, 1);
    sc_reduce_limbs(s, limbs);
}
