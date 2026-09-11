#ifndef ROUTE_CONCAT_ENGINE_H
#define ROUTE_CONCAT_ENGINE_H

#include <ap_int.h>
#include <stdint.h>
#include "pack4.h"

// ---------------------------------------------------------------------------
// Route/concat engine - one of 3 small, independent HLS IPs (this one, plus
// maxpool_engine and upsample_engine) filling the gap
// conv_engine_requant/README.md item 4 flagged. See maxpool_engine.h's
// header comment for the shared provenance/architecture rationale.
//
// Implements RTL_HANDOFF_KO.md section 6: Route, with 1 or 2 sources.
//   - Layer 17: pure passthrough of a single source (layer 13) - call with
//     ch1=0 (source 1 absent).
//   - Layer 20: channel-concat of 2 sources, [layer19, layer8] order
//     (layer19's channels land FIRST in the output), each source
//     INDEPENDENTLY requantized via its own model_manifest.json
//     source_requantization multiplier/shift BEFORE concatenation.
//
// Hardcoded to exactly 2 sources, not N-parameterized: the real network
// never needs more than 2 (layer 20 is the only multi-source route; layer
// 17 is single-source). Generalizing to N would add a runtime-bounded
// "which source" loop plus a multiplier/shift/enable array register file
// for zero real benefit in this network.
//
// Per-source requantization reuses conv_engine.cpp's exact
// saturate()/round_shift() formula (RTL_HANDOFF_KO.md section 5), copied
// bit-for-bit as file-local static functions in route_concat_engine.cpp -
// re-sync against conv_engine_requant/HW/conv_engine.cpp if that formula
// ever changes there.
//
// ---- PACK4 VARIANT ----
// int8x4-packed m_axi pointers (pack4_t = ap_uint<32>), 4 consecutive NHWC
// channels per beat. See pack4.h for the rationale and the alignment
// contract. This is the most expensive of the 3 engines to pack, because
// unlike maxpool (4 comparators) and upsample (nothing at all), the requant
// math is per-element: each beat now needs 4 parallel
// saturate(round_shift(v*multiplier, shift)) units per source loop rather
// than 1. That is a real LUT/DSP increase, paid for out of the headroom the
// measured 4-IP implementation reported (37.81% LUT, not the 92% csynth had
// predicted). The baseline measured 1.22 cycles/output against a ~1 floor.
//
// The new alignment contract is slightly stronger here than for the other
// two engines: BOTH ch0 % 4 == 0 and ch1 % 4 == 0 are required, because
// src1's channels start at output offset ch0 and must therefore begin on a
// whole-word boundary. Layer 17 (ch0=256, ch1=0) and layer 20 (ch0=128,
// ch1=256) both satisfy this.
//
// PS integration / AXI port count (see ../vivado/create_bd.tcl): only 2
// m_axi master ports total, not 3, despite having 3 pointer arguments -
// `src0` and `src1` share bundle=RD_BUS (one physical AXI4 master,
// internally arbitrated between the 2 sources; see
// route_concat_engine.cpp's INTERFACE pragmas), `ofmap` is bundle=WR_BUS.
// Same 2-master shape as maxpool_engine.h/upsample_engine.h, 6 total
// across the 3 new IPs. The pack4 change alters neither the port count nor
// the s_axilite register map.
// ---------------------------------------------------------------------------

// Compile-time upper bounds, sized against the real network's 2 route
// layers (17: 9x16, 1 source, 256ch; 20: 18x32, 2 sources, 128+256=384ch)
// with headroom, not conv_engine_requant's much larger bounds.
const unsigned MAX_ROUTE_W        = 64;   // 2x headroom over layer 20's real w=32
const unsigned MAX_ROUTE_SRC_CH   = 256;  // exact fit to layer 8/20's largest single source
const unsigned MAX_ROUTE_TOTAL_CH = 512;  // headroom over layer 20's real total=384

// The same two channel bounds in 32-bit words, for the m_axi depth=
// pragmas now that all 3 ports are word-addressed.
const unsigned MAX_ROUTE_SRC_CH_WORDS   = MAX_ROUTE_SRC_CH / PACK4_LANES;
const unsigned MAX_ROUTE_TOTAL_CH_WORDS = MAX_ROUTE_TOTAL_CH / PACK4_LANES;

typedef ap_int<8> act_t;

// ---------------------------------------------------------------------------
// Top-level function. NHWC, row-major, DDR-resident. src0/src1 share the
// same img_h/img_w (route/concat never changes spatial dims). ofmap is
// [img_h][img_w][ch0+ch1], src0's channels FIRST.
//
// src1 may be a dummy/unused address when ch1==0 (layer 17's case) - it is
// never dereferenced then, since the source-1 copy loop becomes a
// zero-trip loop via ordinary geometry (ch1==0), no special-casing needed
// in the loop structure itself.
//
// operation="passthrough" (model_manifest.json) -> requant_enable=0 (raw
// copy, no math at all - scale already matches, per RTL_HANDOFF_KO.md
// section 6).
// operation="requantize" -> requant_enable=1, apply
// saturate(round_shift((ap_int<64>)in*multiplier, shift)).
//
// ch0/ch1 are still counted in CHANNELS, not words - the register map and
// the software-visible meaning of every argument are unchanged from the
// baseline engine. Each must now be a multiple of 4 (see pack4.h).
// ---------------------------------------------------------------------------
void route_concat_engine(
    const pack4_t *src0, const pack4_t *src1,  // [img_h][img_w][ch0/4] / [img_h][img_w][ch1/4], NHWC
    pack4_t       *ofmap,                       // [img_h][img_w][(ch0+ch1)/4], NHWC
    uint16_t img_h, uint16_t img_w,
    uint16_t ch0, uint16_t ch1,             // ch1==0 => source 1 absent
    uint8_t  src0_requant_enable, int32_t src0_requant_multiplier, uint8_t src0_requant_shift,
    uint8_t  src1_requant_enable, int32_t src1_requant_multiplier, uint8_t src1_requant_shift
);

#endif // ROUTE_CONCAT_ENGINE_H
