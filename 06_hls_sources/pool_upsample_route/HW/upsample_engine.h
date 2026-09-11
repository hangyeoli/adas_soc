#ifndef UPSAMPLE_ENGINE_H
#define UPSAMPLE_ENGINE_H

#include <ap_int.h>
#include <stdint.h>
#include "pack4.h"

// ---------------------------------------------------------------------------
// Upsample engine - one of 3 small, independent HLS IPs (this one, plus
// maxpool_engine and route_concat_engine) filling the gap
// conv_engine_requant/README.md item 4 flagged. See maxpool_engine.h's
// header comment for the shared provenance/architecture rationale.
//
// Implements RTL_HANDOFF_KO.md section 6: nearest-neighbor upsample,
// fixed 2x (the real network only ever has one upsample layer, index 19,
// and RTL_HANDOFF_KO.md never varies the factor). Pure replication - it
// preserves the input's quantization scale exactly, so like maxpool_engine
// there is NO per-layer requantization math here.
//
// ---- PACK4 VARIANT ----
// int8x4-packed m_axi pointers (pack4_t = ap_uint<32>), 4 consecutive NHWC
// channels per beat. See pack4.h for the rationale and the ch % 4 == 0 /
// 4-byte-alignment contract. This engine benefits the most cleanly of the
// three: it is a pure copy with no per-element arithmetic, so the packed
// version never unpacks a lane at all - it moves whole 32-bit words
// end-to-end, and the 4 lanes are simply along for the ride. The baseline
// measured 1.37 cycles/output against a ~1.25 floor at 1 element/beat.
// ---------------------------------------------------------------------------

// Compile-time upper bounds, sized against the real network's only
// upsample layer (index 19: input 16x9x128) with 2x headroom - deliberately
// NOT conv_engine_requant's much larger MAX_IMG_W=512/MAX_IN_CH=1024, which
// would just waste m_axi depth= headroom for an op that never runs anywhere
// near full image resolution in this network.
const unsigned MAX_UPSAMPLE_IN_W = 32;
const unsigned MAX_UPSAMPLE_CH   = 256;

// Channel bound in 32-bit words - sizes the on-chip `px` pixel buffer and
// the m_axi depth= pragmas now that both are word-addressed.
const unsigned MAX_UPSAMPLE_CH_WORDS = MAX_UPSAMPLE_CH / PACK4_LANES;

typedef ap_int<8> act_t;

const unsigned UPSAMPLE_FACTOR = 2;

// ---------------------------------------------------------------------------
// Top-level function. NHWC, row-major, DDR-resident, matching
// conv_engine_requant's convention. ofmap must be sized
// [2*img_h][2*img_w][ch] by the caller.
//
// `ch` is still counted in CHANNELS, not words - the s_axilite register map
// and the software-visible meaning of every argument are unchanged from the
// baseline engine. It must now be a multiple of 4 (see pack4.h).
// ---------------------------------------------------------------------------
void upsample_engine(
    const pack4_t *ifmap,  // [img_h][img_w][ch/4], NHWC, DDR-resident
    pack4_t       *ofmap,  // [2*img_h][2*img_w][ch/4], NHWC, DDR-resident
    uint16_t img_h, uint16_t img_w, uint16_t ch
);

#endif // UPSAMPLE_ENGINE_H
