/*
 * network_run.c
 *
 * Bare-metal bring-up test for conv_engine on the PS (Vitis standalone
 * application, APU). Drives the SAME conv_engine hardware through every
 * layer in NETWORK_LAYERS by reprogramming its registers and re-triggering
 * it once per layer.
 *
 * REAL_WEIGHTS_PLAN.md rewrite (2026-07-24): NETWORK_LAYERS is now the
 * teammate's real 13-conv-layer YOLOv3-tiny-ADAS golden model (see
 * python/real_layers.py), not the old 3-layer synthetic placeholder. This
 * changed the fundamental structure of this loop, not just the data size:
 *
 *   - NO MORE PING-PONG DDR CHAINING. The old version fed layer i+1's
 *     input from layer i's conv_engine() output (buf_a/buf_b, swapped each
 *     iteration) - correct only when every intervening step is itself a
 *     conv_engine() call. The real network has maxpool/route/upsample
 *     between most of these 13 conv layers, and this project does not
 *     implement those (see README.md item 4 / REAL_WEIGHTS_PLAN.md's
 *     "Explicitly OUT of scope"). Each layer's real input is instead its
 *     own teammate-verified sample (INPUTS_BLOB[L->input_offset...],
 *     already reflecting whatever maxpool/route/upsample would have
 *     produced), loaded fresh every iteration - independent per-layer
 *     checks, not a continuous pipeline. A PASS here proves conv_engine
 *     computes each real layer's math correctly against real data: it does
 *     NOT prove the full 24-layer network runs end-to-end (it can't, since
 *     6 of those 24 layers have no hardware implementation at all yet).
 *   - conv_engine_set_quant() is now actually called, once per layer, with
 *     that layer's real requant_multiplier/requant_shift/leaky_relu_enable
 *     (NETWORK_LAYERS' new fields, see network_layers.h). The previous
 *     version of this file never called it at all, leaving those registers
 *     at reset value 0 - meaning every layer's output silently collapsed
 *     to 0 via saturate(round_shift(acc*0, shift)). That placeholder-era
 *     bug is what this rewrite fixes; see this file's own git history for
 *     the original warning comment.
 *   - bias is now int32_t (BIAS_BLOB), matching conv_engine.h's bias_t and
 *     the real golden model's bias.bin - was int8_t, wide enough only for
 *     the old placeholder's synthetic bias values.
 *   - accum_buf is now sized from MAX_ACCUM_ELEMS (network_layers.h,
 *     computed as out_h*out_w*PE_OC across all real layers) instead of the
 *     old MAX_IFMAP_ELEMS stand-in, which happened to be large enough only
 *     by accident for the tiny placeholder network's shapes.
 *
 * Still no AXI DMA driver here (contrast conv_layer1_dma_driver.h) -
 * conv_engine reads/writes DDR directly via its own m_axi ports, so this
 * file only ever pokes AXI-Lite registers and does Xil_DCache*Range()
 * calls, no DMA transfer submission at all.
 *
 * Learned from the conv_layer1 code review: the CPU must flush any buffer
 * it just wrote before the accelerator reads it via m_axi (weights, bias,
 * and here also each layer's real input slice of INPUTS_BLOB), and must
 * invalidate a buffer the accelerator just wrote before the CPU reads it
 * (ofmap_buf, before check_layer()'s checksum/spot-check read).
 */

#include <stdint.h>

#include "xil_cache.h"

#include "conv_engine_hw_driver.h"
#include "network_layers.h"    /* NETWORK_LAYERS[], layer_cfg_t, NUM_LAYERS, MAX_*_ELEMS */
#include "network_weights.h"   /* WEIGHTS_BLOB[] (int8), BIAS_BLOB[] (int32) */
#include "network_input.h"     /* INPUTS_BLOB[] - every layer's own real input */
#include "network_expected.h"  /* EXPECTED_CHECKSUM[]/SPOT_OFFSET[]/SPOT_COUNT[]/SPOT_INDEX_BLOB[]/SPOT_VALUE_BLOB[] */

/* ofmap_buf is reused every iteration (no ping-pong needed now - see the
 * file header note on why layers no longer chain through it). accum_buf is
 * DDR scratch conv_engine owns entirely (see conv_engine.h's note on the
 * `accum` parameter) - software never initializes or reads it itself. */
static int8_t ofmap_buf[MAX_OFMAP_ELEMS] __attribute__((aligned(64)));
static int32_t accum_buf[MAX_ACCUM_ELEMS] __attribute__((aligned(64)));

static uint32_t checksum_i8(const int8_t *buf, uint32_t n)
{
    uint32_t sum = 0;
    for (uint32_t i = 0; i < n; i++) sum += (uint8_t)buf[i];
    return sum;
}

/* Data-driven, not a hand-written switch/case per layer (that was the old
 * design - see git history - and its own comment already flagged it as
 * needing to change once NUM_LAYERS grew past a handful; it just did, 3 ->
 * 13). EXPECTED_CHECKSUM[layer_idx] and SPOT_OFFSET[layer_idx]/
 * SPOT_COUNT[layer_idx] (into the flattened SPOT_INDEX_BLOB/SPOT_VALUE_BLOB)
 * are indexed directly - scales to any NUM_LAYERS with no code change. */
static int check_layer(unsigned layer_idx, const int8_t *out_buf, uint32_t n)
{
    uint32_t sum = checksum_i8(out_buf, n);
    uint32_t expected_checksum = EXPECTED_CHECKSUM[layer_idx];
    uint32_t spot_off = SPOT_OFFSET[layer_idx];
    uint32_t spot_count = SPOT_COUNT[layer_idx];

    int ok = (sum == expected_checksum);
    xil_printf("  layer %u checksum = 0x%08lx (expected 0x%08lx) %s\r\n",
               layer_idx, (unsigned long)sum, (unsigned long)expected_checksum,
               ok ? "OK" : "MISMATCH");

    for (uint32_t i = 0; i < spot_count; i++) {
        uint32_t idx = SPOT_INDEX_BLOB[spot_off + i];
        int8_t expected_val = SPOT_VALUE_BLOB[spot_off + i];
        if (out_buf[idx] != expected_val) {
            xil_printf("  layer %u spot check FAIL at idx=%lu: hw=%d expected=%d\r\n",
                       layer_idx, (unsigned long)idx, out_buf[idx], expected_val);
            ok = 0;
        }
    }
    return ok;
}

int main(void)
{
    xil_printf("conv_engine real-layer bring-up starting (%d layers)...\r\n", NUM_LAYERS);

    if (conv_engine_wait_idle("main:init") != 0) {
        xil_printf("FAIL: conv_engine never reached idle\r\n");
        return -1;
    }

    int all_ok = 1;

    for (unsigned i = 0; i < NUM_LAYERS; i++) {
        const layer_cfg_t *L = &NETWORK_LAYERS[i];
        uint32_t out_h = (uint32_t)L->img_h + 2u * L->pad - L->k + 1u;
        uint32_t out_w = (uint32_t)L->img_w + 2u * L->pad - L->k + 1u;
        uint32_t ifmap_bytes = (uint32_t)L->img_h * L->img_w * L->in_ch;
        uint32_t ofmap_bytes = out_h * out_w * L->out_ch;

        const int8_t  *src     = &INPUTS_BLOB[L->input_offset];
        const int8_t  *weights = &WEIGHTS_BLOB[L->weight_offset];
        const int32_t *bias    = &BIAS_BLOB[L->bias_offset];
        int8_t        *dst     = ofmap_buf;

        /* Flush everything the CPU wrote that the accelerator is about to
         * read via m_axi: this layer's real input slice, weight slice, and
         * bias slice (all `static const`, but still ordinary cached
         * memory - the accelerator's m_axi read sees DDR, not the CPU
         * cache, same as every other buffer here). Invalidate the output
         * buffer's range so the CPU's later checksum/spot-check read
         * doesn't see a stale cache line from a previous layer's write. */
        Xil_DCacheFlushRange((UINTPTR)src, ifmap_bytes);
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

        xil_printf("layer %u: %ux%ux%u -> %lux%lux%u (k=%u, leaky=%u)\r\n",
                   i, L->img_w, L->img_h, L->in_ch,
                   (unsigned long)out_w, (unsigned long)out_h, L->out_ch, L->k,
                   L->leaky_relu_enable);

        if (conv_engine_wait_done("main:layer") != 0) {
            xil_printf("FAIL: layer %u never completed\r\n", i);
            return -1;
        }

        if (!check_layer(i, dst, ofmap_bytes)) all_ok = 0;
    }

    if (all_ok) {
        xil_printf("PASS: all %d real layers matched the golden model bit-exact\r\n", NUM_LAYERS);
        return 0;
    }
    xil_printf("FAIL: one or more layers mismatched\r\n");
    return -1;
}
