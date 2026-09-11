#!/usr/bin/env python3
"""
Generate the SW bring-up headers for conv_engine from real_layers.py's
per-layer .bin artifacts + layers_meta.json in this directory.

Run real_layers.py first:
    python3 real_layers.py
    python3 export_sw_headers.py

Unlike hls/conv_layer1/python/export_sw_headers.py (one layer -> one set of
headers), this generates a NETWORK-wide descriptor table plus concatenated
weight/bias blobs, because SW/network_run.c drives all layers through the
same conv_engine hardware by looping over this table and reprogramming the
engine's registers each iteration (see ../README.md).

Reads `layers_meta.json` (written by real_layers.py) instead of importing
`NETWORK` from golden_model.py - golden_model.py's NETWORK was a plain
(img_h,img_w,in_ch,out_ch,k,pad) tuple list with no room for the real
per-layer requant_multiplier/requant_shift/leaky_relu_enable this script
now also needs to emit (see REAL_WEIGHTS_PLAN.md step 3). golden_model.py
itself still exists (unmodified) for anyone who wants the old synthetic
placeholder network, but this script no longer uses it.
"""

import json
import random
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SW_DIR = HERE.parent / "SW"

with open(HERE / "layers_meta.json") as f:
    NETWORK = json.load(f)

SPOT_CHECK_COUNT = 16
SPOT_CHECK_SEED = 7

# Must match conv_engine.h's PE_OC exactly - MAX_ACCUM_ELEMS below sizes
# SW/network_run.c's accum_buf, and accum is only ever [out_h][out_w][PE_OC]
# (see conv_engine.h's note on the `accum` parameter), not [out_h][out_w]
# [out_ch]. No mechanism here parses conv_engine.h automatically (same
# placeholder-register-offset caveat as SW/conv_engine_hw_driver.h) - if
# PE_OC ever changes there, it must be updated here too, or MAX_ACCUM_ELEMS
# silently undersizes accum_buf for any layer with out_ch > this value's
# old setting.
# Updated 20->16->24 (2026-07-24, same session): 20->16 was Lever 4
# (LUT_REDUCTION_PLAN.md); that drifted out of sync with conv_engine.h for
# a while, caught during a board-independent readiness pass, not by any
# tool (TROUBLESHOOTING.md #22 - this file's own comment predicted exactly
# that drift). 16->24 followed once Lever 3's loop-consolidation showed
# PE_OC=16 was leaving real LUT headroom (and real throughput) on the
# table - see conv_engine.h's own comment on `PE_OC` for the full
# reasoning. This value going UP (not down) this time means the reverse,
# actually-dangerous drift direction is the live risk now: if this constant
# is left stale at a SMALLER value than the real hardware's `PE_OC`,
# `MAX_ACCUM_ELEMS` below would silently undersize `accum_buf` - real DRAM
# corruption on real hardware, not a crash. Re-check this value by hand
# against conv_engine.h's PE_OC every time either file changes; nothing
# enforces the two staying in sync automatically.
PE_OC = 24


def c_array_i8(name: str, arr: np.ndarray, values_per_line: int = 20) -> str:
    flat = arr.astype(np.int8).flatten()
    lines = []
    for i in range(0, len(flat), values_per_line):
        chunk = flat[i:i + values_per_line]
        lines.append(", ".join(str(int(v)) for v in chunk))
    body = ",\n    ".join(lines)
    return f"static const int8_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"


def c_array_i32(name: str, arr: np.ndarray, values_per_line: int = 12) -> str:
    flat = arr.astype(np.int32).flatten()
    lines = []
    for i in range(0, len(flat), values_per_line):
        chunk = flat[i:i + values_per_line]
        lines.append(", ".join(str(int(v)) for v in chunk))
    body = ",\n    ".join(lines)
    return f"static const int32_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"


def main():
    SW_DIR.mkdir(exist_ok=True)

    num_layers = len(NETWORK)
    weight_blobs = []
    bias_blobs = []
    input_blobs = []
    weight_offsets = []
    bias_offsets = []
    input_offsets = []
    w_off = 0
    b_off = 0
    in_off = 0

    max_ifmap_elems = 0
    max_ofmap_elems = 0
    max_accum_elems = 0

    layer_rows = []       # one row per layer for the descriptor table
    checksums = []        # one uint32 per layer, indexed by layer number
    spot_indices = []     # flattened across all layers - see spot_offsets/spot_counts
    spot_values = []
    spot_offsets = []     # element offset into the flattened spot arrays, per layer
    spot_counts = []      # element count, per layer

    rng = random.Random(SPOT_CHECK_SEED)

    for i, layer in enumerate(NETWORK):
        img_h, img_w = layer["img_h"], layer["img_w"]
        in_ch, out_ch = layer["in_ch"], layer["out_ch"]
        k, pad = layer["k"], layer["pad"]
        requant_multiplier = layer["requant_multiplier"]
        requant_shift = layer["requant_shift"]
        leaky_relu_enable = layer["leaky_relu_enable"]

        tag = f"layer{i:02d}"
        weights = np.fromfile(HERE / f"{tag}_weights.bin", dtype=np.int8)
        # bias is int32 (real_layers.py, matching conv_engine.h's bias_t /
        # the golden model's real bias.bin - NOT int8 like the old
        # golden_model.py placeholder wrote).
        bias = np.fromfile(HERE / f"{tag}_bias.bin", dtype=np.int32)
        # Every layer's own real input (real_layers.py wrote one per layer,
        # from the teammate's actual int8_layers_sample dumps - NOT just
        # layer 0). Unlike golden_model.py's placeholder network, these 13
        # real layers do NOT chain through conv_engine()'s own DDR output -
        # maxpool/route/upsample run between most of them in the real
        # network and are not implemented here (see REAL_WEIGHTS_PLAN.md),
        # so each layer's real input must be loaded fresh instead.
        layer_input = np.fromfile(HERE / f"{tag}_input.bin", dtype=np.int8)
        expected = np.fromfile(HERE / f"{tag}_expected_output.bin", dtype=np.int8)

        assert weights.size == out_ch * in_ch * k * k, f"{tag}: weights.bin size mismatch"
        assert bias.size == out_ch, f"{tag}: bias.bin size mismatch"
        assert layer_input.size == img_h * img_w * in_ch, f"{tag}: input.bin size mismatch"

        weight_blobs.append(weights)
        bias_blobs.append(bias)
        input_blobs.append(layer_input)
        weight_offsets.append(w_off)
        bias_offsets.append(b_off)
        input_offsets.append(in_off)
        w_off += weights.size
        b_off += bias.size  # element offset into BIAS_BLOB (int32_t elements, not bytes)
        in_off += layer_input.size

        out_h = img_h + 2 * pad - k + 1
        out_w = img_w + 2 * pad - k + 1
        max_ifmap_elems = max(max_ifmap_elems, img_h * img_w * in_ch)
        max_ofmap_elems = max(max_ofmap_elems, out_h * out_w * out_ch)
        # accum is only ever [out_h][out_w][PE_OC], never [out_h][out_w]
        # [out_ch] - see conv_engine.h's note on the `accum` parameter.
        max_accum_elems = max(max_accum_elems, out_h * out_w * PE_OC)

        layer_rows.append(
            f"    {{ .img_h={img_h}, .img_w={img_w}, .in_ch={in_ch}, "
            f".out_ch={out_ch}, .k={k}, .stride=1, .pad={pad}, "
            f".weight_offset={weight_offsets[i]}, .bias_offset={bias_offsets[i]}, "
            f".input_offset={input_offsets[i]}, "
            f".requant_multiplier={requant_multiplier}, .requant_shift={requant_shift}, "
            f".leaky_relu_enable={leaky_relu_enable} }},"
        )

        checksum = int(np.sum(expected.astype(np.uint8), dtype=np.uint64)) & 0xFFFFFFFF
        checksums.append(checksum)

        count = min(SPOT_CHECK_COUNT, expected.size)
        indices = sorted(rng.sample(range(expected.size), count))
        values = [int(expected[idx]) for idx in indices]
        spot_offsets.append(len(spot_indices))
        spot_counts.append(count)
        spot_indices.extend(indices)
        spot_values.extend(values)

    # ---- network_layers.h ----------------------------------------------------
    layers_h = (
        "/* Auto-generated by python/export_sw_headers.py - do not edit by hand. */\n"
        "#pragma once\n#include <stdint.h>\n\n"
        f"#define NUM_LAYERS {num_layers}\n"
        f"#define MAX_IFMAP_ELEMS {max_ifmap_elems}\n"
        f"#define MAX_OFMAP_ELEMS {max_ofmap_elems}\n"
        f"/* accum scratch buffer sizing - see conv_engine.h's note on the\n"
        f" * `accum` parameter and this script's PE_OC constant (kept in sync\n"
        f" * with conv_engine.h by hand, same caveat as\n"
        f" * SW/conv_engine_hw_driver.h's REG_* offsets). */\n"
        f"#define MAX_ACCUM_ELEMS {max_accum_elems}\n\n"
        "typedef struct {\n"
        "    uint16_t img_h, img_w, in_ch, out_ch;\n"
        "    uint8_t  k, stride, pad;\n"
        "    uint32_t weight_offset; /* element offset into WEIGHTS_BLOB */\n"
        "    uint32_t bias_offset;   /* element offset into BIAS_BLOB (int32_t elements) */\n"
        "    uint32_t input_offset;  /* element offset into INPUTS_BLOB - this layer's OWN\n"
        "                             * real input, NOT the previous layer's conv_engine()\n"
        "                             * output (see network_run.c) */\n"
        "    int32_t  requant_multiplier;\n"
        "    uint8_t  requant_shift;\n"
        "    uint8_t  leaky_relu_enable; /* 0 = linear (detection-head layers), 1 = LeakyReLU(13/128) */\n"
        "} layer_cfg_t;\n\n"
        f"static const layer_cfg_t NETWORK_LAYERS[NUM_LAYERS] = {{\n"
        + "\n".join(layer_rows) + "\n};\n"
    )
    (SW_DIR / "network_layers.h").write_text(layers_h)

    # ---- network_weights.h ----------------------------------------------------
    all_weights = np.concatenate(weight_blobs)
    all_bias = np.concatenate(bias_blobs)
    weights_h = (
        "/* Auto-generated by python/export_sw_headers.py - do not edit by hand. */\n"
        "#pragma once\n#include <stdint.h>\n\n"
        + c_array_i8("WEIGHTS_BLOB", all_weights)
        + "\n"
        # int32, not int8 - matches conv_engine.h's bias_t (ap_int<32>) and
        # the real golden model's bias.bin, unlike the old placeholder
        # golden_model.py's int8 bias.
        + c_array_i32("BIAS_BLOB", all_bias)
    )
    (SW_DIR / "network_weights.h").write_text(weights_h)

    # ---- network_input.h -------------------------------------------------------
    # Every layer's own real input, concatenated (INPUTS_BLOB) - NOT just
    # layer 0's. These 13 real conv layers do not chain through conv_engine's
    # own DDR output (see the note on `layer_input`/`input_offset` above) -
    # network_run.c must load each layer's slice of INPUTS_BLOB fresh before
    # that layer's conv_engine_set_addrs() call.
    all_inputs = np.concatenate(input_blobs)
    input_h = (
        "/* Auto-generated by python/export_sw_headers.py - do not edit by hand.\n"
        " * Every layer's own real input (see layer_cfg_t's input_offset) -\n"
        " * these real layers do NOT chain through conv_engine's own output. */\n"
        "#pragma once\n#include <stdint.h>\n\n"
        + c_array_i8("INPUTS_BLOB", all_inputs, values_per_line=32)
    )
    (SW_DIR / "network_input.h").write_text(input_h)

    # ---- network_expected.h ----------------------------------------------------
    # Flattened, indexable-by-layer-number tables, NOT per-layer L{i}-suffixed
    # named constants (EXPECTED_CHECKSUM_L0, SPOT_INDEX_L0[], ... - the old
    # format, which needed a hand-written switch/case per layer in
    # network_run.c's check_layer() and did not scale past a handful of
    # layers - this file's own comment already flagged that exact spot as
    # the place to revisit "if NUM_LAYERS grows much further". It just did
    # (3 -> 13, see REAL_WEIGHTS_PLAN.md). EXPECTED_CHECKSUM[i],
    # SPOT_OFFSET[i]/SPOT_COUNT[i] (into the single flattened SPOT_INDEX/
    # SPOT_VALUE arrays) are indexed directly by the network_run.c loop
    # variable instead.
    checksum_arr = np.array(checksums, dtype=np.uint32)
    spot_offset_arr = np.array(spot_offsets, dtype=np.uint32)
    spot_count_arr = np.array(spot_counts, dtype=np.uint32)
    spot_index_arr = np.array(spot_indices, dtype=np.uint32)
    spot_value_arr = np.array(spot_values, dtype=np.int8)

    def c_array_u32(name: str, arr: np.ndarray, values_per_line: int = 12) -> str:
        flat = arr.astype(np.uint32).flatten()
        lines = []
        for i in range(0, len(flat), values_per_line):
            chunk = flat[i:i + values_per_line]
            lines.append(", ".join(f"{int(v)}u" for v in chunk))
        body = ",\n    ".join(lines)
        return f"static const uint32_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"

    expected_h = (
        "/* Auto-generated by python/export_sw_headers.py - do not edit by hand.\n"
        " * Per-layer checksum + spot checks, indexed BY LAYER NUMBER (not by\n"
        " * per-layer named constants), so a failure can be localized to the\n"
        " * layer that diverged instead of only knowing the final output is\n"
        " * wrong. SPOT_INDEX_BLOB/SPOT_VALUE_BLOB are flattened across all\n"
        " * layers - use SPOT_OFFSET[i]/SPOT_COUNT[i] to find layer i's slice. */\n"
        "#pragma once\n#include <stdint.h>\n\n"
        + c_array_u32("EXPECTED_CHECKSUM", checksum_arr)
        + "\n"
        + c_array_u32("SPOT_OFFSET", spot_offset_arr)
        + "\n"
        + c_array_u32("SPOT_COUNT", spot_count_arr)
        + "\n"
        + c_array_u32("SPOT_INDEX_BLOB", spot_index_arr)
        + "\n"
        + c_array_i8("SPOT_VALUE_BLOB", spot_value_arr)
    )
    (SW_DIR / "network_expected.h").write_text(expected_h)

    print(f"Wrote {SW_DIR / 'network_layers.h'} ({num_layers} layers)")
    print(f"Wrote {SW_DIR / 'network_weights.h'} "
          f"({all_weights.size} weight bytes + {all_bias.size} int32 bias values "
          f"= {all_weights.size + all_bias.size * 4} bytes of data)")
    print(f"Wrote {SW_DIR / 'network_input.h'} ({all_inputs.size} bytes, {num_layers} layers' worth)")
    print(f"Wrote {SW_DIR / 'network_expected.h'} "
          f"({num_layers} layers x up to {SPOT_CHECK_COUNT} spot checks)")
    print(f"Buffer sizing: max_ifmap_elems={max_ifmap_elems}, "
          f"max_ofmap_elems={max_ofmap_elems}, max_accum_elems={max_accum_elems} "
          f"(PE_OC={PE_OC})")


if __name__ == "__main__":
    main()
