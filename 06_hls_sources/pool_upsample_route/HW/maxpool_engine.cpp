#include "maxpool_engine.h"
#include <cassert>

void maxpool_engine(
    const pack4_t *ifmap,
    pack4_t       *ofmap,
    uint16_t img_h, uint16_t img_w, uint16_t ch,
    uint8_t  stride,
    uint8_t  pad_right, uint8_t pad_bottom
) {
    // depth= is now in 32-bit WORDS, not int8 elements - the total byte
    // footprint each port can address is unchanged (MAX_CH_WORDS is
    // MAX_CH/4), it is only the unit of the pointer that changed.
#pragma HLS INTERFACE m_axi port=ifmap offset=slave bundle=RD_BUS depth=MAX_IMG_W*MAX_IMG_W*MAX_CH_WORDS
#pragma HLS INTERFACE m_axi port=ofmap offset=slave bundle=WR_BUS depth=MAX_IMG_W*MAX_IMG_W*MAX_CH_WORDS

#pragma HLS INTERFACE s_axilite port=ifmap      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ofmap      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_h      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_w      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ch         bundle=CTRL
#pragma HLS INTERFACE s_axilite port=stride     bundle=CTRL
#pragma HLS INTERFACE s_axilite port=pad_right  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=pad_bottom bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return     bundle=CTRL

#ifndef __SYNTHESIS__
    assert(img_h <= MAX_IMG_W && "img_h exceeds MAX_IMG_W - see maxpool_engine.h");
    assert(img_w <= MAX_IMG_W && "img_w exceeds MAX_IMG_W - see maxpool_engine.h");
    assert(ch <= MAX_CH && "ch exceeds MAX_CH - see maxpool_engine.h");
    // New in the pack4 variant: every pixel must occupy a whole number of
    // 32-bit words, so the next pixel's channel 0 always starts on a word
    // boundary and a whole-word store can never clobber a neighbour. Every
    // real maxpool layer has ch in {16,32,64,128,256,512}. See pack4.h for
    // why a remainder tail is deliberately not supported.
    assert((ch % PACK4_LANES) == 0 &&
           "ch must be a multiple of 4 in the pack4 variant - see pack4.h");
    assert((stride == 1 || stride == 2) && "stride must be 1 or 2 - see RTL_HANDOFF_KO.md section 6");
    assert(pad_right <= 1 && pad_bottom <= 1 && "pad_right/pad_bottom must each be 0 or 1");
    // RTL_HANDOFF_KO.md section 7 only ever pairs stride=1 with padding
    // (layer 11) and stride=2 with no padding (every other maxpool layer) -
    // asserting this combination catches a misprogrammed layer descriptor
    // loudly in sim rather than silently computing the wrong output shape.
    assert(!(stride == 2 && (pad_right != 0 || pad_bottom != 0)) &&
           "stride=2 must not be combined with padding - see RTL_HANDOFF_KO.md section 6/7");
    // NOT asserted: stride==2 with an odd img_h/img_w. Every real stride=2
    // layer happens to be even (RTL_HANDOFF_KO.md section 7), but an odd
    // dimension is not an invalid config - out_h/out_w's integer division
    // below just drops the last row/column, well-defined truncation
    // behavior, not undefined/garbage output. See the testbench's
    // MP-C config, which deliberately exercises exactly this case.
    // (Odd SPATIAL dims stay supported; only odd CHANNEL counts do not.)
#else
    (void)0;
#endif

    const unsigned out_h = (img_h + (unsigned)pad_bottom - 2u) / stride + 1u;
    const unsigned out_w = (img_w + (unsigned)pad_right  - 2u) / stride + 1u;

    // Channels per pixel expressed in beats. Every loop below counts in
    // these units, which is the entire speedup: the trip count of each
    // inner loop drops by 4x while II stays at 1.
    const unsigned ch_words = (unsigned)ch / PACK4_LANES;

ROW_LOOP:
    for (unsigned r_out = 0; r_out < out_h; r_out++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_IMG_W
    COL_LOOP:
        for (unsigned c_out = 0; c_out < out_w; c_out++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_IMG_W
            // Deliberately not pipelined at this level - see
            // conv_engine.cpp's ROW_LOOP/COL_LOOP for the same reasoning:
            // the parallelism knob is the inner channel loop's PIPELINE
            // II=1, not this level.

            // 4 running maxima per entry, one per lane. Same total bits as
            // the baseline's act_t maxval[MAX_CH], just addressed by word.
            pack4_t maxval[MAX_CH_WORDS];

        MAXPOOL_INIT:
            for (unsigned w = 0; w < ch_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_CH_WORDS
                maxval[w] = PACK4_ALL_MINUS_128;
            }

            // Fixed 2x2 window - dy/dx are compile-time constants (0,1),
            // not unrolled over a runtime bound, so this is 4 literal
            // passes, each independently PIPELINE'd over the channel loop.
            for (unsigned dy = 0; dy < 2; dy++) {
                for (unsigned dx = 0; dx < 2; dx++) {
                    unsigned in_r = r_out * stride + dy;
                    unsigned in_c = c_out * stride + dx;
                    // Upper-bound check only: padding is right/bottom-only
                    // (RTL_HANDOFF_KO.md section 6), so unlike conv_engine's
                    // symmetric pad there is no lower-bound underflow case
                    // to guard against here.
                    bool in_bounds = (in_r < img_h) && (in_c < img_w);

                MAXPOOL_UPDATE:
                    for (unsigned w = 0; w < ch_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_CH_WORDS
                        // if/else (not a ternary selecting the read),
                        // matching conv_engine.cpp's READ_CH convention -
                        // keeps the m_axi read conditionally EXECUTED, not
                        // just conditionally selected, so padding
                        // positions never issue a garbage-address AXI
                        // transaction.
                        if (in_bounds) {
                            pack4_t v = ifmap[((unsigned)in_r * img_w + in_c) * ch_words + w];
                            pack4_t m = maxval[w];
                            pack4_t nm = 0;
                        MAXPOOL_LANES:
                            for (unsigned lane = 0; lane < PACK4_LANES; lane++) {
#pragma HLS UNROLL
                                // 4 independent int8 comparators in one
                                // cycle. UNROLL (not PIPELINE) because the
                                // lanes are the WIDTH of a single beat -
                                // they must all retire together for this
                                // loop to keep II=1 over `w`.
                                act_t a = pack4_get(v, lane);
                                act_t b = pack4_get(m, lane);
                                // Explicit if/else rather than a ternary,
                                // matching route_concat_engine.cpp's
                                // round_shift() convention for ap_int
                                // operands.
                                if (a > b) {
                                    pack4_set(nm, lane, a);
                                } else {
                                    pack4_set(nm, lane, b);
                                }
                            }
                            maxval[w] = nm;
                        }
                    }
                }
            }

        MAXPOOL_WRITE:
            for (unsigned w = 0; w < ch_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_CH_WORDS
                ofmap[((unsigned)r_out * out_w + c_out) * ch_words + w] = maxval[w];
            }
        }
    }
}
