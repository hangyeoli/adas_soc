#include "route_concat_engine.h"
#include <cassert>

// ---------------------------------------------------------------------------
// Copied bit-for-bit from conv_engine_requant/HW/conv_engine.cpp (see that
// file's own comments for the full derivation) - re-sync here if that
// formula ever changes. Matches RTL_HANDOFF_KO.md section 5 exactly:
// round_shift(x, s) = sign(x) * ((abs(x) + 2^(s-1)) >> s), ties away from
// zero. Deliberately NOT shared via a common header across these two
// isolated project folders - see conv_engine_requant/README.md's
// provenance section for why each isolated copy in this codebase is
// self-contained by design.
//
// UNCHANGED by the pack4 variant. This is the point of keeping the math in
// its own function: packing changes only how many of these run per beat (4
// instead of 1), never what any one of them computes, so the packed engine
// stays bit-exact against the same golden data with no re-derivation.
// ---------------------------------------------------------------------------
static act_t saturate(ap_int<64> v) {
    if (v > 127)  return (act_t)127;
    if (v < -128) return (act_t)-128;
    return (act_t)v;
}

static ap_int<64> round_shift(ap_int<64> x, ap_uint<6> s) {
#pragma HLS INLINE
    if (s == 0) return x;
    ap_int<64> half = (ap_int<64>)1 << (s - 1);
    // Explicit if/else with an explicit ap_int<64> cast on each return -
    // NOT a ternary. See conv_engine.cpp's round_shift() comment: ap_int's
    // bit-growth makes a ternary here a real build error, not just a style
    // choice.
    if (x >= 0) {
        return (ap_int<64>)((x + half) >> s);
    } else {
        return (ap_int<64>)(-(((-x) + half) >> s));
    }
}

// Call-site count changed with pack4: the baseline had 2 call sites
// (SRC0_COPY/SRC1_COPY), neither under an UNROLL. Now each of those sites
// sits inside a PACK4_LANES-wide `#pragma HLS UNROLL` lane loop, so there
// are 8 instantiations rather than 2 - i.e. this IS now the
// "UNROLL'd call site" case conv_engine.cpp's apply_activation() comment
// warns about, where INLINE duplicates real hardware.
//
// Keeping INLINE anyway, deliberately: the duplication is exactly the
// point. The 4 lanes of a beat must all requantize in the SAME cycle for
// the enclosing loop to hold II=1, which is the entire speedup - sharing
// one requant unit across the 4 lanes would serialize the beat back to
// II=4 and give up the win. The cost is 4x the requant logic per source
// loop; the measured 4-IP implementation (37.81% LUT) is where that budget
// comes from. Re-check LUT/DSP in this variant's own csynth report rather
// than assuming the baseline's numbers still hold.
static act_t apply_source_requant(act_t v, bool enable, int32_t multiplier, unsigned shift) {
#pragma HLS INLINE
    if (!enable) {
        return v;
    }
    ap_int<64> scaled = (ap_int<64>)v * (ap_int<64>)multiplier;
    return saturate(round_shift(scaled, shift));
}

void route_concat_engine(
    const pack4_t *src0, const pack4_t *src1,
    pack4_t       *ofmap,
    uint16_t img_h, uint16_t img_w,
    uint16_t ch0, uint16_t ch1,
    uint8_t  src0_requant_enable, int32_t src0_requant_multiplier, uint8_t src0_requant_shift,
    uint8_t  src1_requant_enable, int32_t src1_requant_multiplier, uint8_t src1_requant_shift
) {
    // src0 and src1 share one physical AXI master port (RD_BUS): they are
    // read sequentially per output pixel below, never concurrently - same
    // "costs no new physical AXI master port since nothing here runs under
    // DATAFLOW" reasoning conv_engine.cpp uses for sharing ofmap/accum on
    // one WR_BUS.
    //
    // depth= is now in 32-bit WORDS, not int8 elements - same total
    // addressable byte footprint as the baseline, different pointer unit.
#pragma HLS INTERFACE m_axi port=src0  offset=slave bundle=RD_BUS depth=MAX_ROUTE_W*MAX_ROUTE_W*MAX_ROUTE_SRC_CH_WORDS
#pragma HLS INTERFACE m_axi port=src1  offset=slave bundle=RD_BUS depth=MAX_ROUTE_W*MAX_ROUTE_W*MAX_ROUTE_SRC_CH_WORDS
#pragma HLS INTERFACE m_axi port=ofmap offset=slave bundle=WR_BUS depth=MAX_ROUTE_W*MAX_ROUTE_W*MAX_ROUTE_TOTAL_CH_WORDS

#pragma HLS INTERFACE s_axilite port=src0  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src1  bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ofmap bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_h bundle=CTRL
#pragma HLS INTERFACE s_axilite port=img_w bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ch0   bundle=CTRL
#pragma HLS INTERFACE s_axilite port=ch1   bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src0_requant_enable    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src0_requant_multiplier bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src0_requant_shift      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src1_requant_enable    bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src1_requant_multiplier bundle=CTRL
#pragma HLS INTERFACE s_axilite port=src1_requant_shift      bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL

#ifndef __SYNTHESIS__
    assert(img_h <= MAX_ROUTE_W && "img_h exceeds MAX_ROUTE_W - see route_concat_engine.h");
    assert(img_w <= MAX_ROUTE_W && "img_w exceeds MAX_ROUTE_W - see route_concat_engine.h");
    assert(ch0 <= MAX_ROUTE_SRC_CH && "ch0 exceeds MAX_ROUTE_SRC_CH - see route_concat_engine.h");
    assert(ch1 <= MAX_ROUTE_SRC_CH && "ch1 exceeds MAX_ROUTE_SRC_CH - see route_concat_engine.h");
    assert((unsigned)ch0 + (unsigned)ch1 <= MAX_ROUTE_TOTAL_CH &&
           "ch0+ch1 exceeds MAX_ROUTE_TOTAL_CH - see route_concat_engine.h");
    // New in the pack4 variant. ch0 in particular is load-bearing beyond
    // the usual whole-word-per-pixel rule: src1's channels start at output
    // channel offset ch0, so a ch0 that is not a multiple of 4 would make
    // SRC1_COPY's very first output land mid-word, and its whole-word store
    // would clobber the last of src0's channels. See pack4.h.
    assert((ch0 % PACK4_LANES) == 0 &&
           "ch0 must be a multiple of 4 in the pack4 variant - see pack4.h");
    assert((ch1 % PACK4_LANES) == 0 &&
           "ch1 must be a multiple of 4 in the pack4 variant - see pack4.h");
    assert(src0_requant_shift <= 48 && "src0_requant_shift implausibly large for round_shift's ap_int<64>");
    assert(src1_requant_shift <= 48 && "src1_requant_shift implausibly large for round_shift's ap_int<64>");
    assert(!(ch1 == 0 && src1_requant_enable) &&
           "src1_requant_enable set but ch1==0 (source 1 absent) - see route_concat_engine.h");
#else
    (void)0;
#endif

    const unsigned out_ch = (unsigned)ch0 + (unsigned)ch1;

    // All three arrays in beats. ch0_words doubles as src1's starting word
    // offset inside ofmap, which is only a valid whole-word offset because
    // of the ch0 % 4 assert above.
    const unsigned ch0_words   = (unsigned)ch0 / PACK4_LANES;
    const unsigned ch1_words   = (unsigned)ch1 / PACK4_LANES;
    const unsigned out_ch_words = out_ch / PACK4_LANES;

ROW_LOOP:
    for (unsigned r = 0; r < img_h; r++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_ROUTE_W
    COL_LOOP:
        for (unsigned c = 0; c < img_w; c++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_ROUTE_W
            const unsigned pixel_idx = r * img_w + c;

        SRC0_COPY:
            // src0's channels land FIRST in the output (RTL_HANDOFF_KO.md
            // section 6: layer 20's concat order is [layer19, layer8]).
            for (unsigned w = 0; w < ch0_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=MAX_ROUTE_SRC_CH_WORDS
                pack4_t v = src0[pixel_idx * ch0_words + w];
                pack4_t o = 0;
            SRC0_LANES:
                for (unsigned lane = 0; lane < PACK4_LANES; lane++) {
#pragma HLS UNROLL
                    pack4_set(o, lane,
                              apply_source_requant(pack4_get(v, lane),
                                                   src0_requant_enable,
                                                   src0_requant_multiplier,
                                                   src0_requant_shift));
                }
                ofmap[pixel_idx * out_ch_words + w] = o;
            }

        SRC1_COPY:
            // Zero-trip when ch1==0 (layer 17's single-source case) -
            // ordinary geometry, no special-casing needed here.
            for (unsigned w = 0; w < ch1_words; w++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=0 max=MAX_ROUTE_SRC_CH_WORDS
                pack4_t v = src1[pixel_idx * ch1_words + w];
                pack4_t o = 0;
            SRC1_LANES:
                for (unsigned lane = 0; lane < PACK4_LANES; lane++) {
#pragma HLS UNROLL
                    pack4_set(o, lane,
                              apply_source_requant(pack4_get(v, lane),
                                                   src1_requant_enable,
                                                   src1_requant_multiplier,
                                                   src1_requant_shift));
                }
                ofmap[pixel_idx * out_ch_words + ch0_words + w] = o;
            }
        }
    }
}
