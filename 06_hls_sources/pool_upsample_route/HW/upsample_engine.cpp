#include "upsample_engine.h"
#include <cassert>

void upsample_engine(
    const pack4_t *ifmap,
    pack4_t       *ofmap,
    uint16_t img_h, uint16_t img_w, uint16_t ch
) {
    // depth= is now in 32-bit WORDS, not int8 elements - same total
    // addressable byte footprint as the baseline, different pointer unit.
#pragma HLS INTERFACE m_axi port=ifmap offset=slave bundle=RD_BUS depth=MAX_UPSAMPLE_IN_W*MAX_UPSAMPLE_IN_W*MAX_UPSAMPLE_CH_WORDS
#pragma HLS INTERFACE m_axi port=ofmap offset=slave bundle=WR_BUS depth=(2*MAX_UPSAMPLE_IN_W)*(2*MAX_UPSAMPLE_IN_W)*MAX_UPSAMPLE_CH_WORDS

#pragma HLS INTERFACE s_axilite port=ifmap bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ofmap bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_h bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_w bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ch    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL

#ifndef __SYNTHESIS__
    assert(img_h <= MAX_UPSAMPLE_IN_W && "img_h exceeds MAX_UPSAMPLE_IN_W - see upsample_engine.h");
    assert(img_w <= MAX_UPSAMPLE_IN_W && "img_w exceeds MAX_UPSAMPLE_IN_W - see upsample_engine.h");
    assert(ch <= MAX_UPSAMPLE_CH && "ch exceeds MAX_UPSAMPLE_CH - see upsample_engine.h");
    // New in the pack4 variant - see maxpool_engine.cpp's identical assert
    // and pack4.h for why a ch%4 tail is deliberately unsupported. The only
    // real upsample layer (index 19) has ch=128.
    assert((ch % PACK4_LANES) == 0 &&
           "ch must be a multiple of 4 in the pack4 variant - see pack4.h");
#else
    (void)0;
#endif

    const unsigned out_w = UPSAMPLE_FACTOR * (unsigned)img_w;

    // Channels per pixel in beats. Both the read loop and all 4 write loops
    // now run ch/4 iterations instead of ch, at the same II=1.
    const unsigned ch_words = (unsigned)ch / PACK4_LANES;

ROW_LOOP:
    for (unsigned r = 0; r < img_h; r++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_UPSAMPLE_IN_W
    COL_LOOP:
        for (unsigned c = 0; c < img_w; c++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_UPSAMPLE_IN_W
            pack4_t px[MAX_UPSAMPLE_CH_WORDS];

        UPSAMPLE_READ:
            for (unsigned w = 0; w < ch_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_UPSAMPLE_CH_WORDS
                px[w] = ifmap[((unsigned)r * img_w + c) * ch_words + w];
            }

            // Nearest-neighbor 2x: this one input pixel is replicated,
            // unchanged, to all 4 of its output positions - no averaging,
            // no interpolation (RTL_HANDOFF_KO.md section 6).
            //
            // Because replication is bit-for-bit, the packed engine never
            // needs pack4_get/pack4_set here at all: a 32-bit word holding
            // 4 channels is copied as one opaque beat. Nothing in this
            // engine is aware of the lane structure, which is why it is the
            // cheapest of the 3 to pack (no extra comparators, no extra
            // multipliers - strictly fewer loop iterations).
            for (unsigned dy = 0; dy < UPSAMPLE_FACTOR; dy++) {
                for (unsigned dx = 0; dx < UPSAMPLE_FACTOR; dx++) {
                    unsigned out_r = UPSAMPLE_FACTOR * r + dy;
                    unsigned out_c = UPSAMPLE_FACTOR * c + dx;
                UPSAMPLE_WRITE:
                    for (unsigned w = 0; w < ch_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_UPSAMPLE_CH_WORDS
                        ofmap[((unsigned)out_r * out_w + out_c) * ch_words + w] = px[w];
                    }
                }
            }
        }
    }
}
