/*
 * upsample_engine_hw_driver.h
 *
 * AXI4-Lite driver for the upsample_engine HLS IP's control bundle ("CTRL"
 * in upsample_engine.cpp's INTERFACE pragmas).
 *
 * CONFIRMED (2026-07-29, `run_hls.bat package`): every REG_* offset below
 * is copied directly from the real generated
 * pool_upsample_route_prj/solution_upsample/impl/ip/drivers/
 * upsample_engine_v1_0/src/xupsample_engine_hw.h - not re-derived by hand.
 * See maxpool_engine_hw_driver.h's header comment (same folder) for why
 * this matters - the short version: conv_engine_requant/SW/
 * conv_engine_hw_driver.h (and this project's own
 * route_concat_engine_hw_driver.h) have documented real bugs from
 * hand-guessing this exact kind of register map, silent until caught by
 * diffing against the real generated header. Re-copy this whole block
 * again from a fresh xupsample_engine_hw.h after any change to
 * upsample_engine()'s parameter list (HW/upsample_engine.h) - a
 * reordered/added/removed argument shifts every offset after it.
 */

/*
 * CALLER OBLIGATIONS - new with the int8x4 packed engine (2026-08-04)
 * ------------------------------------------------------------------
 * The engine's m_axi ports now move 4 consecutive NHWC channels per AXI
 * beat instead of 1 (see HW/pack4.h). NOTHING IN THIS DRIVER CHANGED as a
 * result - the register map, the offsets, the port count and the meaning of
 * every value written below are all identical to the pre-packing engine,
 * and `ch` is still counted in CHANNELS, not words. The DDR byte layout is
 * unchanged too, because 4 consecutive int8 channels on this little-endian
 * platform already are the 4 bytes of one 32-bit word.
 *
 * But the engine now REQUIRES two things of its caller, and will produce
 * wrong output (not an error) if they are violated:
 *
 *   1. `ch` MUST be a multiple of 4.
 *      The only real upsample layer (manifest index 19) has ch=128.
 *
 *   2. `ifmap` and `ofmap` MUST be 4-byte aligned.
 *      Any ordinary allocator result, and any cacheline-aligned CMA
 *      buffer, already is.
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

#define UPE_BASE      XPAR_UPSAMPLE_ENGINE_0_S_AXI_CTRL_BASEADDR
#define UPE_REG(off)  (UPE_BASE + (uint32_t)(off))

/* ---- ap_ctrl_hs block-level control register (fixed offset for all HLS IP,
 * same as conv_engine_hw_driver.h - this one line is NOT a guess). */
#define REG_CTRL         0x00
#define CTRL_AP_START    (1u << 0)
#define CTRL_AP_DONE     (1u << 1)
#define CTRL_AP_IDLE     (1u << 2)
#define CTRL_AP_READY    (1u << 3)

/* ---- m_axi base-address registers - parameter order from
 * HW/upsample_engine.h: ifmap (RD_BUS), ofmap (WR_BUS). Each 64-bit pointer
 * -> 2 x 32-bit data registers (LO/HI) + 1 reserved register, same pattern
 * as conv_engine_hw_driver.h. */
#define REG_IFMAP_ADDR_LO    0x10
#define REG_IFMAP_ADDR_HI    0x14
/* 0x18 reserved */
#define REG_OFMAP_ADDR_LO    0x1c
#define REG_OFMAP_ADDR_HI    0x20
/* 0x24 reserved */

/* ---- scalar geometry registers - parameter order from
 * HW/upsample_engine.h: img_h, img_w, ch (uint16_t each - this is the
 * INPUT shape; ofmap is always exactly 2x each spatial dim, fixed 2x
 * nearest-neighbor, layer 19 only - see RTL_HANDOFF_KO.md section 7). */
#define REG_IMG_H    0x28
/* 0x2c reserved */
#define REG_IMG_W    0x30
/* 0x34 reserved */
#define REG_CH       0x38
/* 0x3c reserved */

/* Program one layer's DDR addresses. Call once per upsample layer before
 * upsample_engine_start() - see network_run_full.c. */
static inline void upsample_engine_set_addrs(uint64_t ifmap, uint64_t ofmap)
{
    Xil_Out32(UPE_REG(REG_IFMAP_ADDR_LO), (uint32_t)(ifmap & 0xffffffffu));
    Xil_Out32(UPE_REG(REG_IFMAP_ADDR_HI), (uint32_t)(ifmap >> 32));
    Xil_Out32(UPE_REG(REG_OFMAP_ADDR_LO), (uint32_t)(ofmap & 0xffffffffu));
    Xil_Out32(UPE_REG(REG_OFMAP_ADDR_HI), (uint32_t)(ofmap >> 32));
}

/* Program one layer's INPUT shape (img_h/img_w/ch) - output is always
 * (2*img_h)x(2*img_w)xch, caller must size/zero the ofmap buffer for that,
 * not img_h*img_w.
 *
 * `ch` is in CHANNELS (unchanged by packing) and must be a multiple of 4 -
 * see "CALLER OBLIGATIONS" at the top of this file. */
static inline void upsample_engine_set_shape(uint16_t img_h, uint16_t img_w, uint16_t ch)
{
    Xil_Out32(UPE_REG(REG_IMG_H), img_h);
    Xil_Out32(UPE_REG(REG_IMG_W), img_w);
    Xil_Out32(UPE_REG(REG_CH),    ch);
}

static inline void upsample_engine_start(void)
{
    Xil_Out32(UPE_REG(REG_CTRL), CTRL_AP_START);
}

static inline int upsample_engine_wait_idle(const char *where)
{
    uint32_t tmo = 10000000u;
    while ((Xil_In32(UPE_REG(REG_CTRL)) & CTRL_AP_IDLE) == 0u) {
        if (--tmo == 0u) {
            xil_printf("%s: upsample_engine ap_idle timeout\r\n", where);
            return -1;
        }
    }
    return 0;
}

static inline int upsample_engine_wait_done(const char *where)
{
    uint32_t tmo = 20000000u;
    while ((Xil_In32(UPE_REG(REG_CTRL)) & CTRL_AP_DONE) == 0u) {
        if (--tmo == 0u) {
            xil_printf("%s: upsample_engine ap_done timeout\r\n", where);
            return -1;
        }
    }
    return 0;
}
