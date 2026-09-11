/*
 * route_concat_engine_hw_driver.h
 *
 * AXI4-Lite driver for the route_concat_engine HLS IP's control bundle
 * ("CTRL" in route_concat_engine.cpp's INTERFACE pragmas).
 *
 * CONFIRMED (2026-07-29, `run_hls.bat package`): every REG_* offset below
 * is copied directly from the real generated
 * pool_upsample_route_prj/solution_route_concat/impl/ip/drivers/
 * route_concat_engine_v1_0/src/xroute_concat_engine_hw.h - not re-derived
 * by hand. This file's ORIGINAL placeholder guess (2 data registers + 1
 * reserved per 64-bit pointer, 1 data register + 1 reserved per scalar,
 * same pattern as conv_engine_hw_driver.h) was WRONG from `img_h` onward -
 * it forgot the reserved register after the 3rd pointer pair (`ofmap`,
 * ending at 0x2c), so every offset from `img_h` on was off by +0x04
 * against the real header (guessed 0x30/0x38/0x40/0x48/0x50/0x58/0x60/
 * 0x68/0x70/0x78, real 0x34/0x3c/0x44/0x4c/0x54/0x5c/0x64/0x6c/0x74/0x7c) -
 * exactly the class of silent bug conv_engine_hw_driver.h's own header
 * comment already warned about, caught here before it ever reached real
 * hardware only because the #error this file used to have blocked it from
 * being used un-checked. Re-copy this whole block again from a fresh
 * xroute_concat_engine_hw.h after any change to route_concat_engine()'s
 * parameter list (HW/route_concat_engine.h) - a reordered/added/removed
 * argument shifts every offset after it.
 */

/*
 * CALLER OBLIGATIONS - new with the int8x4 packed engine (2026-08-04)
 * ------------------------------------------------------------------
 * The engine's m_axi ports now move 4 consecutive NHWC channels per AXI
 * beat instead of 1 (see HW/pack4.h). NOTHING IN THIS DRIVER CHANGED as a
 * result - the register map, the offsets, the port count and the meaning of
 * every value written below are all identical to the pre-packing engine,
 * and ch0/ch1 are still counted in CHANNELS, not words. The DDR byte layout
 * is unchanged too, because 4 consecutive int8 channels on this
 * little-endian platform already are the 4 bytes of one 32-bit word.
 *
 * But the engine now REQUIRES two things of its caller, and will produce
 * wrong output (not an error) if they are violated:
 *
 *   1. BOTH `ch0` AND `ch1` MUST be multiples of 4.
 *      This engine's rule is stricter than maxpool's/upsample's: src1's
 *      channels start at output channel offset ch0, so a ch0 that is not a
 *      multiple of 4 would make src1's first output land mid-word, and the
 *      whole-word store would clobber the last of src0's channels.
 *      Both real route layers comply - layer 17 is (ch0=256, ch1=0) and
 *      layer 20 is (ch0=128, ch1=256).
 *
 *   2. `src0`, `src1` and `ofmap` MUST be 4-byte aligned.
 *      Any ordinary allocator result, and any cacheline-aligned CMA
 *      buffer, already is. (src1's value is irrelevant when ch1=0, since
 *      it is never dereferenced then.)
 *
 * Both are assert()ed in the engine's C model, so a violation is caught
 * loudly in csim - but there is no hardware check at runtime, which is why
 * they are restated here at the point where software actually supplies the
 * values.
 */

#pragma once
#include <stdint.h>
#include "xparameters.h"
#include "xil_io.h"
#include "xil_printf.h"

#define RCE_BASE      XPAR_ROUTE_CONCAT_ENGINE_0_S_AXI_CTRL_BASEADDR
#define RCE_REG(off)  (RCE_BASE + (uint32_t)(off))

/* ---- ap_ctrl_hs block-level control register (fixed offset for all HLS IP,
 * same as conv_engine_hw_driver.h - this one line is NOT a guess). */
#define REG_CTRL         0x00
#define CTRL_AP_START    (1u << 0)
#define CTRL_AP_DONE     (1u << 1)
#define CTRL_AP_IDLE     (1u << 2)
#define CTRL_AP_READY    (1u << 3)

/* ---- m_axi base-address registers - parameter order from
 * HW/route_concat_engine.h: src0, src1 (both RD_BUS - two independent
 * s_axilite base-address registers sharing ONE physical m_axi master port,
 * see ../HW/route_concat_engine.cpp's bundle= pragmas), ofmap (WR_BUS).
 * Each 64-bit pointer -> 2 x 32-bit data registers (LO/HI) + 1 reserved
 * register, same pattern as conv_engine_hw_driver.h. */
#define REG_SRC0_ADDR_LO     0x10
#define REG_SRC0_ADDR_HI     0x14
/* 0x18 reserved */
#define REG_SRC1_ADDR_LO     0x1c
#define REG_SRC1_ADDR_HI     0x20
/* 0x24 reserved */
#define REG_OFMAP_ADDR_LO    0x28
#define REG_OFMAP_ADDR_HI    0x2c
/* 0x30 reserved */

/* ---- scalar registers - parameter order from HW/route_concat_engine.h:
 * img_h, img_w, ch0, ch1 (uint16_t each; ch1==0 means source 1 absent -
 * layer 17's single-source passthrough), then src0's
 * requant_enable/multiplier/shift, then src1's
 * requant_enable/multiplier/shift. */
#define REG_IMG_H                    0x34
/* 0x38 reserved */
#define REG_IMG_W                    0x3c
/* 0x40 reserved */
#define REG_CH0                      0x44
/* 0x48 reserved */
#define REG_CH1                      0x4c
/* 0x50 reserved */
#define REG_SRC0_REQUANT_ENABLE      0x54
/* 0x58 reserved */
#define REG_SRC0_REQUANT_MULTIPLIER  0x5c
/* 0x60 reserved */
#define REG_SRC0_REQUANT_SHIFT       0x64
/* 0x68 reserved */
#define REG_SRC1_REQUANT_ENABLE      0x6c
/* 0x70 reserved */
#define REG_SRC1_REQUANT_MULTIPLIER  0x74
/* 0x78 reserved */
#define REG_SRC1_REQUANT_SHIFT       0x7c
/* 0x80 reserved */

/* Program one layer's DDR addresses. For layer 17 (single-source
 * passthrough), pass src1=0 - the engine only reads src1 when ch1!=0 (see
 * route_concat_engine.cpp), so the address value itself is never
 * dereferenced, but pass 0 rather than an uninitialized pointer to keep
 * this call self-documenting at the call site. */
static inline void route_concat_engine_set_addrs(uint64_t src0, uint64_t src1, uint64_t ofmap)
{
    Xil_Out32(RCE_REG(REG_SRC0_ADDR_LO),  (uint32_t)(src0 & 0xffffffffu));
    Xil_Out32(RCE_REG(REG_SRC0_ADDR_HI),  (uint32_t)(src0 >> 32));
    Xil_Out32(RCE_REG(REG_SRC1_ADDR_LO),  (uint32_t)(src1 & 0xffffffffu));
    Xil_Out32(RCE_REG(REG_SRC1_ADDR_HI),  (uint32_t)(src1 >> 32));
    Xil_Out32(RCE_REG(REG_OFMAP_ADDR_LO), (uint32_t)(ofmap & 0xffffffffu));
    Xil_Out32(RCE_REG(REG_OFMAP_ADDR_HI), (uint32_t)(ofmap >> 32));
}

/* Program one layer's shape. Pass ch1=0 for layer 17's single-source
 * passthrough (per HW/route_concat_engine.h's own convention).
 *
 * ch0/ch1 are in CHANNELS (unchanged by packing) and BOTH must be multiples
 * of 4 - see "CALLER OBLIGATIONS" at the top of this file. */
static inline void route_concat_engine_set_shape(uint16_t img_h, uint16_t img_w,
                                                  uint16_t ch0, uint16_t ch1)
{
    Xil_Out32(RCE_REG(REG_IMG_H), img_h);
    Xil_Out32(RCE_REG(REG_IMG_W), img_w);
    Xil_Out32(RCE_REG(REG_CH0),   ch0);
    Xil_Out32(RCE_REG(REG_CH1),   ch1);
}

/* Program each source's independent per-source requantization
 * (model_manifest.json's route layer "source_requantization" list -
 * "passthrough" sources must pass enable=0; "requantize" sources pass
 * enable=1 with that source's own multiplier/shift). For layer 17
 * (single-source), pass enable=0/mult=0/shift=0 for source 1 - ignored
 * since ch1=0 means source 1 is absent. */
static inline void route_concat_engine_set_quant(uint8_t src0_requant_enable,
                                                  int32_t src0_requant_multiplier,
                                                  uint8_t src0_requant_shift,
                                                  uint8_t src1_requant_enable,
                                                  int32_t src1_requant_multiplier,
                                                  uint8_t src1_requant_shift)
{
    Xil_Out32(RCE_REG(REG_SRC0_REQUANT_ENABLE),     src0_requant_enable);
    Xil_Out32(RCE_REG(REG_SRC0_REQUANT_MULTIPLIER), (uint32_t)src0_requant_multiplier);
    Xil_Out32(RCE_REG(REG_SRC0_REQUANT_SHIFT),      src0_requant_shift);
    Xil_Out32(RCE_REG(REG_SRC1_REQUANT_ENABLE),     src1_requant_enable);
    Xil_Out32(RCE_REG(REG_SRC1_REQUANT_MULTIPLIER), (uint32_t)src1_requant_multiplier);
    Xil_Out32(RCE_REG(REG_SRC1_REQUANT_SHIFT),      src1_requant_shift);
}

static inline void route_concat_engine_start(void)
{
    Xil_Out32(RCE_REG(REG_CTRL), CTRL_AP_START);
}

static inline int route_concat_engine_wait_idle(const char *where)
{
    uint32_t tmo = 10000000u;
    while ((Xil_In32(RCE_REG(REG_CTRL)) & CTRL_AP_IDLE) == 0u) {
        if (--tmo == 0u) {
            xil_printf("%s: route_concat_engine ap_idle timeout\r\n", where);
            return -1;
        }
    }
    return 0;
}

static inline int route_concat_engine_wait_done(const char *where)
{
    uint32_t tmo = 20000000u;
    while ((Xil_In32(RCE_REG(REG_CTRL)) & CTRL_AP_DONE) == 0u) {
        if (--tmo == 0u) {
            xil_printf("%s: route_concat_engine ap_done timeout\r\n", where);
            return -1;
        }
    }
    return 0;
}
