/*
 * network_run_full.c
 *
 * conv_engine_requant/README.md item 5: bare-metal bring-up test that
 * sequences the REAL YOLOv3-tiny-ADAS network END TO END across all 4 IPs
 * (conv_engine + pool_upsample_route's maxpool_engine/upsample_engine/
 * route_concat_engine), unlike network_run.c (this same folder), which
 * only ever proves conv_engine's 13 conv layers are individually correct
 * against isolated golden-model inputs - see that file's header comment.
 * That file is left untouched; this is a separate application (separate
 * main()), not a rewrite of it.
 *
 * model_manifest.json has 24 layers (indices 0-23). Layers 16 and 23 are
 * "yolo" (anchor-box decode) - pure SW postprocessing on the detection
 * heads' int8 output, no hardware engine implements them, and nothing
 * downstream in the graph consumes their output as input - so this file
 * sequences the other 22 (13 conv + 6 maxpool + 1 upsample + 2 route),
 * verifying each of layers 15 and 22's real output against the golden
 * model is exactly "this backbone/head math ran correctly on real
 * hardware"; yolo decode itself is a separate, later piece of work (see
 * top-level SW/README.md - this whole file is still bring-up, not that
 * final integration).
 *
 * Graph (see model_manifest.json, cross-checked against
 * conv_engine_requant/python/layers_meta.json's shape/channel ordering and
 * pool_upsample_route/python/real_pool_upsample_route_layers.py's own
 * MAXPOOL_STRIDE_PAD/UPSAMPLE_INDICES/ROUTE_INDICES tables):
 *
 *   0:conv 1:maxpool 2:conv 3:maxpool 4:conv 5:maxpool 6:conv 7:maxpool
 *   8:conv 9:maxpool 10:conv 11:maxpool(stride1+pad) 12:conv 13:conv
 *   14:conv 15:conv [16:yolo, SKIP] 17:route(<-13) 18:conv 19:upsample
 *   20:route(<-19,8) 21:conv 22:conv [23:yolo, SKIP]
 *
 * Buffer plan: ONE static DDR buffer per PRODUCED manifest layer (indexed
 * BY manifest index directly, 0..22 - indices 16/23 simply unused rather
 * than remapped, trading 2 wasted slots for "buffer index == manifest
 * index" being true everywhere, which is much easier to audit against the
 * graph above than a compacted 0..21 mapping would be). No ping-pong reuse
 * - every buffer lives for the whole run. This matters for real: layer 8's
 * output is consumed twice, once immediately by layer 9 (maxpool) and
 * again much later by route 20 (as its 2nd source) - ping-ponging just 2
 * buffers (as conv_engine_requant's own conv_layer1-era code once did, see
 * network_run.c's header comment on why THAT was abandoned) would silently
 * overwrite layer 8's output before route 20 ever reads it. One buffer per
 * layer makes that class of bug structurally impossible instead of
 * something to get right by careful reuse bookkeeping.
 *
 * Sizing every buffer at NETWORK_LAYERS' own MAX_OFMAP_ELEMS (the largest
 * single conv output, layer 0's 288x512x16) rather than each op's tight
 * real size: confirmed by hand against every op below that it's the global
 * max across all 22 real outputs (spatial shrinks much faster than channel
 * count grows after layer 0), so one uniform size is a safe upper bound,
 * not a guess - and avoids exactly the kind of manual per-layer byte-offset
 * arithmetic that has already caused a silent hardware bug once in this
 * codebase (see SW/conv_engine_hw_driver.h's header comment). 22 x
 * MAX_OFMAP_ELEMS is ~54MB total DDR - trivial against the KR260's DRAM,
 * so there is no real reason to tighten this.
 *
 * Verification strategy differs by op type, using whatever ground truth
 * each op's own already-verified header already carries:
 *   - conv steps: EXPECTED_CHECKSUM[]/SPOT_*[] from network_expected.h
 *     (same checksum + 16-spot-check strength network_run.c already uses).
 *   - maxpool/upsample/route steps: pool_upsample_route/HW/
 *     real_pool_upsample_route_data.h embeds each layer's FULL expected
 *     output array (not just a checksum) - byte-for-byte memcmp against
 *     that, which is strictly stronger verification than the conv steps
 *     get, for free, since the data was already there.
 *
 * Cache handling follows network_run.c's own established rule (learned
 * from the conv_layer1 code review, see that file's header comment): flush
 * any buffer the CPU itself just wrote before an accelerator reads it via
 * m_axi, invalidate a buffer before the CPU itself reads it. Applied here:
 *   - Flush weights/bias (every conv step) and the real input image (layer
 *     0 only - every other step's "input" is a buffer a HARDWARE engine
 *     wrote, which the CPU never touched, so it needs no flush before the
 *     NEXT engine reads it).
 *   - Invalidate a buffer immediately before THIS FILE's own verification
 *     read of it (checksum/memcmp) - never needed before a downstream
 *     engine's read, for the same reason (no CPU write happened in
 *     between).
 *
 * The pool_upsample_route SW drivers this file calls into
 * (maxpool_engine_hw_driver.h / upsample_engine_hw_driver.h /
 * route_concat_engine_hw_driver.h) now carry real, Package-IP-confirmed
 * register offsets (2026-07-29, `run_hls.bat package` in
 * hls/pool_upsample_route/ - see those files' own header comments for the
 * before/after numbers, including a real +0x04 offset bug that guessing
 * caught in route_concat_engine's). conv_engine_hw_driver.h's own offsets
 * are likewise Package-IP-confirmed, but from an OLDER export that
 * predates this project's `_requant` fork - see that file's header
 * comment and this project's README.md "Next steps" item 3 for the
 * caveat on re-confirming it. Either way, this file still cannot run on
 * real hardware yet - it needs `xparameters.h` from an actual generated
 * Vitis platform (XSA), which needs a real Vivado bitstream build first,
 * not just Package IP.
 */

#include <stdint.h>
#include <string.h>

#include "xil_cache.h"

#include "conv_engine_hw_driver.h"
#include "network_layers.h"    /* NETWORK_LAYERS[], layer_cfg_t, NUM_LAYERS, MAX_OFMAP_ELEMS, MAX_ACCUM_ELEMS */
#include "network_weights.h"   /* WEIGHTS_BLOB[], BIAS_BLOB[] */
#include "network_input.h"     /* INPUTS_BLOB[] - only index 0 (the real image) is used here */
#include "network_expected.h"  /* EXPECTED_CHECKSUM[]/SPOT_OFFSET[]/SPOT_COUNT[]/SPOT_INDEX_BLOB[]/SPOT_VALUE_BLOB[], indexed by NETWORK_LAYERS position */

/* Relative paths across the 2 HLS projects - see this file's header
 * comment on why these 2 IPs' worth of headers live in a sibling project
 * folder instead of being copied in here. A real Vitis SW project would
 * more likely add pool_upsample_route/{HW,SW} as extra include paths in
 * its project settings instead of relying on ../../ - either works; this
 * is the simpler one to keep correct by inspection in source form. */
#include "../../pool_upsample_route/SW/maxpool_engine_hw_driver.h"
#include "../../pool_upsample_route/SW/upsample_engine_hw_driver.h"
#include "../../pool_upsample_route/SW/route_concat_engine_hw_driver.h"
#include "../../pool_upsample_route/HW/real_pool_upsample_route_data.h" /* REAL_MAXPOOL_LAYERS[]/REAL_UPSAMPLE_LAYERS[]/REAL_ROUTE_LAYERS[] */

#define NUM_MANIFEST_LAYERS 24  /* model_manifest.json indices 0-23 */

/* One buffer per PRODUCED manifest layer (16/23 are yolo - unused slots,
 * see header comment). accum_buf is conv_engine's own DDR scratch (see
 * conv_engine.h's note on that parameter) - shared across every conv step
 * since they run strictly sequentially, never concurrently. */
static int8_t  g_layer_buf[NUM_MANIFEST_LAYERS][MAX_OFMAP_ELEMS] __attribute__((aligned(64)));
static int32_t accum_buf[MAX_ACCUM_ELEMS] __attribute__((aligned(64)));

typedef enum { OP_CONV, OP_MAXPOOL, OP_UPSAMPLE, OP_ROUTE } op_kind_t;

typedef struct {
    op_kind_t kind;
    unsigned  manifest_index;  /* for logging only */
    int       sub_idx;         /* index into NETWORK_LAYERS[] / REAL_MAXPOOL_LAYERS[] /
                                 * REAL_UPSAMPLE_LAYERS[] / REAL_ROUTE_LAYERS[], per kind */
    int       in_buf;          /* OP_CONV/OP_MAXPOOL/OP_UPSAMPLE input buffer index;
                                 * -1 for manifest index 0 (reads INPUTS_BLOB directly) */
    int       src0_buf;        /* OP_ROUTE only */
    int       src1_buf;        /* OP_ROUTE only; -1 if source 1 absent (layer 17) */
    int       out_buf;
} full_op_t;

#define NUM_FULL_OPS 22

static const full_op_t NETWORK_FULL_OPS[NUM_FULL_OPS] = {
    { .kind=OP_CONV,     .manifest_index= 0, .sub_idx= 0, .in_buf=-1, .src0_buf=-1, .src1_buf=-1, .out_buf= 0 },
    { .kind=OP_MAXPOOL,  .manifest_index= 1, .sub_idx= 0, .in_buf= 0, .src0_buf=-1, .src1_buf=-1, .out_buf= 1 },
    { .kind=OP_CONV,     .manifest_index= 2, .sub_idx= 1, .in_buf= 1, .src0_buf=-1, .src1_buf=-1, .out_buf= 2 },
    { .kind=OP_MAXPOOL,  .manifest_index= 3, .sub_idx= 1, .in_buf= 2, .src0_buf=-1, .src1_buf=-1, .out_buf= 3 },
    { .kind=OP_CONV,     .manifest_index= 4, .sub_idx= 2, .in_buf= 3, .src0_buf=-1, .src1_buf=-1, .out_buf= 4 },
    { .kind=OP_MAXPOOL,  .manifest_index= 5, .sub_idx= 2, .in_buf= 4, .src0_buf=-1, .src1_buf=-1, .out_buf= 5 },
    { .kind=OP_CONV,     .manifest_index= 6, .sub_idx= 3, .in_buf= 5, .src0_buf=-1, .src1_buf=-1, .out_buf= 6 },
    { .kind=OP_MAXPOOL,  .manifest_index= 7, .sub_idx= 3, .in_buf= 6, .src0_buf=-1, .src1_buf=-1, .out_buf= 7 },
    { .kind=OP_CONV,     .manifest_index= 8, .sub_idx= 4, .in_buf= 7, .src0_buf=-1, .src1_buf=-1, .out_buf= 8 },  /* buf 8 reused by route 20 (src1) */
    { .kind=OP_MAXPOOL,  .manifest_index= 9, .sub_idx= 4, .in_buf= 8, .src0_buf=-1, .src1_buf=-1, .out_buf= 9 },
    { .kind=OP_CONV,     .manifest_index=10, .sub_idx= 5, .in_buf= 9, .src0_buf=-1, .src1_buf=-1, .out_buf=10 },
    { .kind=OP_MAXPOOL,  .manifest_index=11, .sub_idx= 5, .in_buf=10, .src0_buf=-1, .src1_buf=-1, .out_buf=11 }, /* stride1+pad, see REAL_MAXPOOL_LAYERS[5] */
    { .kind=OP_CONV,     .manifest_index=12, .sub_idx= 6, .in_buf=11, .src0_buf=-1, .src1_buf=-1, .out_buf=12 },
    { .kind=OP_CONV,     .manifest_index=13, .sub_idx= 7, .in_buf=12, .src0_buf=-1, .src1_buf=-1, .out_buf=13 }, /* buf 13 reused by route 17 (src0) */
    { .kind=OP_CONV,     .manifest_index=14, .sub_idx= 8, .in_buf=13, .src0_buf=-1, .src1_buf=-1, .out_buf=14 },
    { .kind=OP_CONV,     .manifest_index=15, .sub_idx= 9, .in_buf=14, .src0_buf=-1, .src1_buf=-1, .out_buf=15 }, /* detection head 1 input (yolo 16, SW-only, not run here) */
    { .kind=OP_ROUTE,    .manifest_index=17, .sub_idx= 0, .in_buf=-1, .src0_buf=13, .src1_buf=-1, .out_buf=17 }, /* single-source passthrough of layer 13 */
    { .kind=OP_CONV,     .manifest_index=18, .sub_idx=10, .in_buf=17, .src0_buf=-1, .src1_buf=-1, .out_buf=18 },
    { .kind=OP_UPSAMPLE, .manifest_index=19, .sub_idx= 0, .in_buf=18, .src0_buf=-1, .src1_buf=-1, .out_buf=19 },
    { .kind=OP_ROUTE,    .manifest_index=20, .sub_idx= 1, .in_buf=-1, .src0_buf=19, .src1_buf= 8, .out_buf=20 }, /* concat [layer19, layer8] */
    { .kind=OP_CONV,     .manifest_index=21, .sub_idx=11, .in_buf=20, .src0_buf=-1, .src1_buf=-1, .out_buf=21 },
    { .kind=OP_CONV,     .manifest_index=22, .sub_idx=12, .in_buf=21, .src0_buf=-1, .src1_buf=-1, .out_buf=22 }, /* detection head 2 input (yolo 23, SW-only, not run here) */
};

static uint32_t checksum_i8(const int8_t *buf, uint32_t n)
{
    uint32_t sum = 0;
    for (uint32_t i = 0; i < n; i++) sum += (uint8_t)buf[i];
    return sum;
}

/* Same check as network_run.c's check_layer() - checksum + 16-spot-check,
 * indexed by NETWORK_LAYERS position (conv_idx), not manifest index. */
static int verify_conv(unsigned manifest_index, int conv_idx, const int8_t *out_buf, uint32_t n)
{
    uint32_t sum = checksum_i8(out_buf, n);
    uint32_t expected_checksum = EXPECTED_CHECKSUM[conv_idx];
    uint32_t spot_off = SPOT_OFFSET[conv_idx];
    uint32_t spot_count = SPOT_COUNT[conv_idx];

    int ok = (sum == expected_checksum);
    xil_printf("  manifest layer %u (conv): checksum = 0x%08lx (expected 0x%08lx) %s\r\n",
               manifest_index, (unsigned long)sum, (unsigned long)expected_checksum,
               ok ? "OK" : "MISMATCH");

    for (uint32_t i = 0; i < spot_count; i++) {
        uint32_t idx = SPOT_INDEX_BLOB[spot_off + i];
        int8_t expected_val = SPOT_VALUE_BLOB[spot_off + i];
        if (out_buf[idx] != expected_val) {
            xil_printf("  manifest layer %u spot check FAIL at idx=%lu: hw=%d expected=%d\r\n",
                       manifest_index, (unsigned long)idx, out_buf[idx], expected_val);
            ok = 0;
        }
    }
    return ok;
}

/* Stronger than verify_conv() above: real_pool_upsample_route_data.h
 * embeds each layer's FULL expected output, not just a checksum, so this
 * is an exact byte-for-byte compare. */
static int verify_exact(unsigned manifest_index, const char *what,
                         const int8_t *out_buf, uint32_t n,
                         const int8_t *expected, uint32_t expected_n)
{
    if (n != expected_n) {
        xil_printf("  manifest layer %u (%s): SIZE MISMATCH hw=%lu expected=%lu\r\n",
                   manifest_index, what, (unsigned long)n, (unsigned long)expected_n);
        return 0;
    }
    int ok = (memcmp(out_buf, expected, n) == 0);
    xil_printf("  manifest layer %u (%s): %s\r\n", manifest_index, what,
               ok ? "OK (bit-exact)" : "MISMATCH");
    return ok;
}

int main(void)
{
    xil_printf("network_run_full: real 24-layer YOLOv3-tiny-ADAS bring-up "
               "starting (%d hardware ops, layers 16/23 are SW-only yolo "
               "decode, not run here)...\r\n", NUM_FULL_OPS);

    if (conv_engine_wait_idle("main:init") != 0
        || maxpool_engine_wait_idle("main:init") != 0
        || upsample_engine_wait_idle("main:init") != 0
        || route_concat_engine_wait_idle("main:init") != 0) {
        xil_printf("FAIL: not every engine reached idle\r\n");
        return -1;
    }

    int all_ok = 1;

    for (unsigned i = 0; i < NUM_FULL_OPS; i++) {
        const full_op_t *op = &NETWORK_FULL_OPS[i];
        int8_t *dst = g_layer_buf[op->out_buf];
        int step_ok = 1;

        switch (op->kind) {
        case OP_CONV: {
            const layer_cfg_t *L = &NETWORK_LAYERS[op->sub_idx];
            uint32_t out_h = (uint32_t)L->img_h + 2u * L->pad - L->k + 1u;
            uint32_t out_w = (uint32_t)L->img_w + 2u * L->pad - L->k + 1u;
            uint32_t ifmap_bytes = (uint32_t)L->img_h * L->img_w * L->in_ch;
            uint32_t ofmap_bytes = out_h * out_w * L->out_ch;
            const int8_t *src = (op->in_buf < 0) ? &INPUTS_BLOB[L->input_offset]
                                                  : g_layer_buf[op->in_buf];
            const int8_t  *weights = &WEIGHTS_BLOB[L->weight_offset];
            const int32_t *bias    = &BIAS_BLOB[L->bias_offset];

            /* Only manifest layer 0's input is CPU-written compile-time
             * data (the real image) - every other conv step's input is a
             * buffer a HARDWARE engine wrote, needing no CPU flush (see
             * this file's header comment). Weights/bias are always
             * CPU-resident compile-time data, so always flushed. */
            if (op->in_buf < 0) Xil_DCacheFlushRange((UINTPTR)src, ifmap_bytes);
            Xil_DCacheFlushRange((UINTPTR)weights, (uint32_t)L->in_ch * L->k * L->k * L->out_ch);
            Xil_DCacheFlushRange((UINTPTR)bias, (uint32_t)L->out_ch * sizeof(int32_t));
            Xil_DCacheInvalidateRange((UINTPTR)dst, ofmap_bytes);

            conv_engine_set_addrs((uint64_t)(uintptr_t)src, (uint64_t)(uintptr_t)weights,
                                   (uint64_t)(uintptr_t)bias, (uint64_t)(uintptr_t)dst,
                                   (uint64_t)(uintptr_t)accum_buf);
            conv_engine_set_shape(L->img_h, L->img_w, L->in_ch, L->out_ch,
                                   L->k, L->stride, L->pad);
            conv_engine_set_quant(L->requant_multiplier, L->requant_shift, L->leaky_relu_enable);
            conv_engine_start();
            if (conv_engine_wait_done("main:conv") != 0) { xil_printf("FAIL: manifest layer %u never completed\r\n", op->manifest_index); return -1; }

            step_ok = verify_conv(op->manifest_index, op->sub_idx, dst, ofmap_bytes);
            break;
        }
        case OP_MAXPOOL: {
            const struct RealMaxpoolCfg *R = &REAL_MAXPOOL_LAYERS[op->sub_idx];
            const int8_t *src = g_layer_buf[op->in_buf];
            uint32_t ofmap_bytes = (uint32_t)R->expected_size;

            Xil_DCacheInvalidateRange((UINTPTR)dst, ofmap_bytes);
            maxpool_engine_set_addrs((uint64_t)(uintptr_t)src, (uint64_t)(uintptr_t)dst);
            maxpool_engine_set_shape((uint16_t)R->img_h, (uint16_t)R->img_w, (uint16_t)R->ch,
                                      (uint8_t)R->stride, (uint8_t)R->pad_right, (uint8_t)R->pad_bottom);
            maxpool_engine_start();
            if (maxpool_engine_wait_done("main:maxpool") != 0) { xil_printf("FAIL: manifest layer %u never completed\r\n", op->manifest_index); return -1; }

            step_ok = verify_exact(op->manifest_index, "maxpool", dst, ofmap_bytes,
                                    R->expected, (uint32_t)R->expected_size);
            break;
        }
        case OP_UPSAMPLE: {
            const struct RealUpsampleCfg *R = &REAL_UPSAMPLE_LAYERS[op->sub_idx];
            const int8_t *src = g_layer_buf[op->in_buf];
            uint32_t ofmap_bytes = (uint32_t)R->expected_size;

            Xil_DCacheInvalidateRange((UINTPTR)dst, ofmap_bytes);
            upsample_engine_set_addrs((uint64_t)(uintptr_t)src, (uint64_t)(uintptr_t)dst);
            upsample_engine_set_shape((uint16_t)R->img_h, (uint16_t)R->img_w, (uint16_t)R->ch);
            upsample_engine_start();
            if (upsample_engine_wait_done("main:upsample") != 0) { xil_printf("FAIL: manifest layer %u never completed\r\n", op->manifest_index); return -1; }

            step_ok = verify_exact(op->manifest_index, "upsample", dst, ofmap_bytes,
                                    R->expected, (uint32_t)R->expected_size);
            break;
        }
        case OP_ROUTE: {
            const struct RealRouteCfg *R = &REAL_ROUTE_LAYERS[op->sub_idx];
            const int8_t *src0 = g_layer_buf[op->src0_buf];
            const int8_t *src1 = (op->src1_buf >= 0) ? g_layer_buf[op->src1_buf] : (const int8_t *)0;
            uint32_t ofmap_bytes = (uint32_t)R->expected_size;

            Xil_DCacheInvalidateRange((UINTPTR)dst, ofmap_bytes);
            route_concat_engine_set_addrs((uint64_t)(uintptr_t)src0,
                                           src1 ? (uint64_t)(uintptr_t)src1 : 0,
                                           (uint64_t)(uintptr_t)dst);
            route_concat_engine_set_shape((uint16_t)R->img_h, (uint16_t)R->img_w,
                                           (uint16_t)R->ch0, (uint16_t)R->ch1);
            route_concat_engine_set_quant(R->src0_requant_enable, R->src0_requant_multiplier, R->src0_requant_shift,
                                           R->src1_requant_enable, R->src1_requant_multiplier, R->src1_requant_shift);
            route_concat_engine_start();
            if (route_concat_engine_wait_done("main:route") != 0) { xil_printf("FAIL: manifest layer %u never completed\r\n", op->manifest_index); return -1; }

            step_ok = verify_exact(op->manifest_index, "route", dst, ofmap_bytes,
                                    R->expected, (uint32_t)R->expected_size);
            break;
        }
        }

        if (!step_ok) all_ok = 0;
    }

    if (all_ok) {
        xil_printf("PASS: all %d real hardware ops matched the golden model "
                   "(layers 15/22 = the 2 detection heads' real int8 output, "
                   "bit-exact end to end)\r\n", NUM_FULL_OPS);
        return 0;
    }
    xil_printf("FAIL: one or more ops mismatched\r\n");
    return -1;
}
