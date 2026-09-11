#!/usr/bin/env python3
"""
real_layers.py

Step 2 (+ step 6's independent check) of REAL_WEIGHTS_PLAN.md: extract
conv_engine's 13 real convolutional layers from the teammate's finished
golden model (python_teammate/darknet_golden/), instead of golden_model.py's
synthetic 3-layer placeholder.

For each real conv layer this:
  1. slices its real weight/bias/requant params out of
     artifacts/int8/{weight,bias}.bin + model_manifest.json
  2. takes its real input from the PRECEDING layer's real dump
     (artifacts/int8_layers_sample/layer_{index-1}.bin - already reflects
     whatever maxpool/route/upsample produced, so this project does NOT
     need to implement those to get a correct real input - see
     REAL_WEIGHTS_PLAN.md's "Why the missing layer types don't block this")
  3. transposes NCHW -> NHWC (conv_engine's layout) for every feature map
  4. for layer index 0 ONLY: applies the u-128 input shift + matching
     +128*sum(w) bias correction derived in REAL_WEIGHTS_PLAN.md's
     "RESOLVED" section, since layer 0's real input is genuinely unsigned
     UINT8 [0,255] and conv_engine's act_t is signed ap_int<8>
  5. runs an INDEPENDENT numpy re-implementation of conv_engine.cpp's exact
     math (round_shift/saturate/apply_activation - not a reuse of
     quantization.py's own functions) and diffs the result against the
     real layer_{index}.bin dump, bit-exact, BEFORE trusting anything
  6. writes layerNN_input.bin / weights.bin / bias.bin (int32) /
     expected_output.bin - same filenames/convention golden_model.py used,
     so export_sw_headers.py needs the least possible change to consume
     this instead (export_sw_headers.py itself is NOT updated by this
     script - that's REAL_WEIGHTS_PLAN.md step 3, separate work)

Usage:
    python3 real_layers.py
Requires: numpy only (no torch, no Vitis) - see REAL_WEIGHTS_PLAN.md step 6
for why an independent-of-torch implementation is deliberate here, not
just an environment constraint.
"""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DARKNET_DIR = HERE.parents[2] / "python_teammate" / "darknet_golden"
INT8_DIR = DARKNET_DIR / "artifacts" / "int8"
SAMPLE_DIR = DARKNET_DIR / "artifacts" / "int8_layers_sample"

# The 13 conv-type layer indices in model_manifest.json's 24-layer network -
# see REAL_WEIGHTS_PLAN.md's layer table. Every other index (maxpool/route/
# upsample/yolo) is never turned into a conv_engine() call; it's only ever
# the SOURCE of some conv layer's real input dump.
CONV_LAYER_INDICES = [0, 2, 4, 6, 8, 10, 12, 13, 14, 15, 18, 21, 22]


# ---------------------------------------------------------------------------
# Independent re-implementation of conv_engine.cpp's exact math. Deliberately
# NOT reusing quantization.py's round_divide_by_pot_signed/apply_multiplier -
# the whole point of this check is verifying THIS project's understanding of
# conv_engine.cpp against real ground truth, not just confirming the golden
# model agrees with itself.
# ---------------------------------------------------------------------------

def round_shift(x: np.ndarray, s: int) -> np.ndarray:
    """Mirrors conv_engine.cpp's round_shift(): round half away from zero,
    then arithmetic-shift right by s. x must already be int64."""
    if s == 0:
        return x
    half = np.int64(1) << (s - 1)
    magnitude = np.abs(x)
    rounded = (magnitude + half) >> np.int64(s)
    return np.where(x < 0, -rounded, rounded)


def saturate_i8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, -128, 127).astype(np.int8)


def apply_activation(acc: np.ndarray, leaky_relu_enable: bool,
                      requant_multiplier: int, requant_shift: int) -> np.ndarray:
    """Mirrors conv_engine.cpp's apply_activation(): LeakyReLU(13/128) on the
    raw accumulator (if enabled), then per-layer requantize + INT8 saturate.
    `acc` must already be int64 (bias already added)."""
    acc = acc.astype(np.int64)
    post_leaky = acc.copy()
    if leaky_relu_enable:
        negative = acc < 0
        post_leaky[negative] = round_shift(acc[negative] * np.int64(13), 7)
    scaled = post_leaky.astype(np.int64) * np.int64(requant_multiplier)
    return saturate_i8(round_shift(scaled, requant_shift))


def conv2d_exact_nhwc(x_nhwc: np.ndarray, w_oihw: np.ndarray, bias: np.ndarray,
                       k: int, pad: int, pad_value: int = 0) -> np.ndarray:
    """Exact-integer convolution (stride=1 only, matching conv_engine.h's
    design limit), NHWC in -> NHWC-shaped raw accumulator out (pre-
    activation, bias already added). Uses an im2col + matmul in int64 -
    exact because every value here is a small integer (see
    model_manifest.json's accumulator_bound, all far under 2**53).

    `pad_value` matters ONLY for layer 0: the golden model always zero-pads
    in the RAW UNSIGNED (u) domain ("outside the image" = u=0), but layer
    0's `x_nhwc` here is already `s = u-128`-shifted (see the RESOLVED
    section / process_layer() below) - so "outside" must be padded with
    `s = 0-128 = -128`, not 0, or the shift identity silently breaks at
    every border pixel (found by a real bit-exact-check failure: 22,839/
    2,359,296 mismatches, matching the border-ring pixel count almost
    exactly - see REAL_WEIGHTS_PLAN.md's implementation notes). Every other
    (non-layer-0) call uses the default `pad_value=0`, which is correct
    there because those inputs are already genuinely signed (post-
    `saturate_int8`), so "outside" really is 0 in their domain too.

    x_nhwc: (H, W, IN_CH) int64
    w_oihw: (OUT_CH, IN_CH, K, K) int64
    bias:   (OUT_CH,) int64
    returns (OUT_H, OUT_W, OUT_CH) int64
    """
    h, w, in_ch = x_nhwc.shape
    out_ch = w_oihw.shape[0]
    x_pad = np.pad(x_nhwc, ((pad, pad), (pad, pad), (0, 0)),
                    mode="constant", constant_values=pad_value)
    out_h = h + 2 * pad - k + 1
    out_w = w + 2 * pad - k + 1

    # sliding_window_view over the H,W axes of an (Hp, Wp, IN_CH) array with
    # window (k, k) on axis=(0, 1) yields (out_h, out_w, IN_CH, k, k) - the
    # trailing (IN_CH, k, k) matches w_oihw's (IN_CH, K, K) axis order
    # exactly (both C-then-KY-then-KX), so flattening both the same way
    # lines up correctly for the matmul below.
    patches = np.lib.stride_tricks.sliding_window_view(x_pad, (k, k), axis=(0, 1))
    patches_flat = patches.reshape(out_h * out_w, in_ch * k * k)
    weight_flat = w_oihw.reshape(out_ch, in_ch * k * k)

    acc = patches_flat.astype(np.int64) @ weight_flat.T.astype(np.int64)
    acc = acc.reshape(out_h, out_w, out_ch) + bias.astype(np.int64)
    return acc


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    with open(INT8_DIR / "model_manifest.json") as f:
        return json.load(f)


def load_weight_bias(layer: dict) -> tuple[np.ndarray, np.ndarray]:
    """Real weight (OIHW int8) and bias (int32) slices for one conv layer,
    sliced directly out of weight.bin/bias.bin at the manifest's offsets -
    no reshape needed for either (conv_engine.h's layouts already match)."""
    weight_bytes = np.memmap(INT8_DIR / "weight.bin", dtype=np.int8, mode="r")
    bias_bytes = np.memmap(INT8_DIR / "bias.bin", dtype=np.int8, mode="r")

    w_off = layer["weight_offset_bytes"]
    w_size = layer["weight_size_bytes"]
    weight = np.array(weight_bytes[w_off:w_off + w_size]).reshape(layer["weight_shape"])

    b_off = layer["bias_offset_bytes"]
    b_size = layer["bias_size_bytes"]
    bias = np.array(bias_bytes[b_off:b_off + b_size]).view("<i4").copy()
    assert bias.size == layer["output_channels"], (
        f"layer {layer['index']}: bias.bin slice decoded to {bias.size} int32 "
        f"values, expected {layer['output_channels']} (out_ch)"
    )
    return weight, bias


def load_real_activation_nchw(layer_index: int) -> tuple[np.ndarray, float]:
    """Real activation dump for `layer_index` (the OUTPUT of whatever ran at
    that index - conv, maxpool, route, upsample, all alike), as int64 NCHW
    (batch dim squeezed out), plus its quantization scale (for reference
    only - conv_engine's own math never uses the scale, only the integer
    values + requant_multiplier/shift, but it's useful for sanity printing).
    `layer_index == -1` is a sentinel for the network's real raw input
    (input_uint8.bin), which is UINT8 not INT8 - see `load_real_input0`."""
    with open(SAMPLE_DIR / "manifest.json") as f:
        sample_manifest = {e["layer"]: e for e in json.load(f)}
    entry = sample_manifest[layer_index]
    assert entry["layout"] == "NCHW" and entry["dtype"] == "int8", (
        f"layer {layer_index} sample: unexpected layout/dtype {entry['layout']}/{entry['dtype']} "
        "- REAL_WEIGHTS_PLAN.md's NCHW/int8 assumption no longer holds, stop and re-check"
    )
    shape = entry["shape"]  # [1, C, H, W]
    raw = np.fromfile(SAMPLE_DIR / entry["file"], dtype=np.int8).reshape(shape)
    return raw[0].astype(np.int64), float(entry["scale"])  # drop batch dim -> (C,H,W)


def load_real_input0_uint8_nchw() -> np.ndarray:
    with open(SAMPLE_DIR / "input_manifest.json") as f:
        entry = json.load(f)
    assert entry["layout"] == "NCHW" and entry["dtype"] == "uint8" and entry["zero_point"] == 0, (
        f"input_uint8.bin: unexpected format {entry} - REAL_WEIGHTS_PLAN.md's "
        "assumptions no longer hold, stop and re-check"
    )
    shape = entry["shape"]  # [1, 3, 288, 512]
    raw = np.fromfile(SAMPLE_DIR / entry["file"], dtype=np.uint8).reshape(shape)
    return raw[0].astype(np.int64)  # (3, H, W), values in [0, 255]


def chw_to_hwc(x_chw: np.ndarray) -> np.ndarray:
    """NCHW's per-sample (C,H,W) -> conv_engine's NHWC (H,W,C)."""
    return np.transpose(x_chw, (1, 2, 0))


# ---------------------------------------------------------------------------
# Main per-layer extraction + verification
# ---------------------------------------------------------------------------

def process_layer(manifest: dict, layer_meta_by_index: dict, conv_index: int) -> dict:
    layer = layer_meta_by_index[conv_index]
    assert layer["type"] == "convolutional"

    weight_oihw, bias = load_weight_bias(layer)
    in_ch, out_ch, k, pad = (
        layer["input_channels"], layer["output_channels"], layer["kernel"], layer["padding"],
    )
    requant_multiplier = layer["requant_multiplier"]
    requant_shift = layer["requant_right_shift"]
    leaky = layer["activation"] == "leaky"
    if layer["activation"] not in ("leaky", "linear"):
        raise ValueError(f"layer {conv_index}: unexpected activation {layer['activation']!r}")

    # ---- real input, HWC, already the correct domain for conv_engine's
    # signed act_t in every case EXCEPT layer 0 (see the u-128 shift below).
    if conv_index == 0:
        u_chw = load_real_input0_uint8_nchw()  # (3,H,W) uint-domain values in [0,255]
        s_chw = u_chw - 128  # RESOLVED section's zero-point shift: u = s + 128
        s_hwc = chw_to_hwc(s_chw)
        # conv_engine's hardware ALWAYS zero-pads (act_t=0 for out-of-bounds
        # taps) - fixed, shared across every layer, not something a single
        # call can override. In the shifted domain, hardware's "0" pad value
        # represents u=128, not u=0 - wrong for boundary output pixels,
        # where only SOME kernel taps are in-bounds (interior pixels, where
        # every tap is in-bounds, were already correct - this only affects
        # the image's border ring). A per-output-channel bias correction
        # alone cannot fix this: the amount of "missing" padding contribution
        # varies PER PIXEL near the border, not just per channel. Found by a
        # real conv_engine_tb.cpp C-sim run: 31,269/2,359,296 mismatches
        # (~1.3%, all border pixels) even after the interior-only bias fix
        # below - the Python check's own `pad_value=-128` (in
        # conv2d_exact_nhwc, superseded by this) had silently assumed a
        # padding value hardware can't actually produce.
        #
        # Fix: pre-pad the EXPORTED input buffer itself with the correct
        # value (s=-128, representing u=0) and call conv_engine with pad=0
        # for this layer - padding is now baked into the DRAM buffer conv_
        # engine reads, not something its own (always-zero) internal padding
        # needs to supply. Every output pixel (border or interior) now reads
        # its FULL kernel from real buffer contents, so the uniform bias
        # correction below (over the full kernel sum) is correct everywhere,
        # not just in the interior.
        input_hwc = np.pad(s_hwc, ((pad, pad), (pad, pad), (0, 0)),
                            mode="constant", constant_values=-128)
        conv_pad = 0  # padding is baked into input_hwc above, not conv_engine's own
        # Matching bias correction: bias'[oc] = bias[oc] + 128 * sum_{ic,ky,kx} w[oc,ic,ky,kx]
        bias = bias + 128 * weight_oihw.astype(np.int64).sum(axis=(1, 2, 3))
    else:
        prev_chw, _ = load_real_activation_nchw(conv_index - 1)
        input_hwc = chw_to_hwc(prev_chw)
        conv_pad = pad

    assert input_hwc.shape[2] == in_ch, (
        f"layer {conv_index}: real input has {input_hwc.shape[2]} channels, "
        f"manifest says in_ch={in_ch} - offset/index mismatch, stop and re-check"
    )

    # ---- independent re-computation, using ONLY conv_engine.cpp's own
    # formula (never quantization.py's functions) ----
    acc = conv2d_exact_nhwc(input_hwc, weight_oihw.astype(np.int64), bias, k, conv_pad)
    computed_hwc = apply_activation(acc, leaky, requant_multiplier, requant_shift)

    # ---- real expected output, for bit-exact comparison ----
    real_chw, out_scale = load_real_activation_nchw(conv_index)
    expected_hwc = chw_to_hwc(real_chw).astype(np.int8)

    assert computed_hwc.shape == expected_hwc.shape, (
        f"layer {conv_index}: computed shape {computed_hwc.shape} != "
        f"real expected shape {expected_hwc.shape}"
    )
    mismatches = int(np.sum(computed_hwc != expected_hwc))
    total = computed_hwc.size

    return {
        "index": conv_index,
        "img_h": input_hwc.shape[0], "img_w": input_hwc.shape[1],
        "in_ch": in_ch, "out_ch": out_ch, "k": k, "pad": conv_pad,
        "leaky_relu_enable": leaky,
        "requant_multiplier": requant_multiplier, "requant_shift": requant_shift,
        "input_hwc": input_hwc.astype(np.int8),
        "weight_oihw": weight_oihw,
        "bias_i32": bias.astype(np.int32),
        "expected_hwc": expected_hwc,
        "mismatches": mismatches,
        "total": total,
        "out_scale": out_scale,
    }


HW_DIR = HERE.parent / "HW"


def _c_array_i8(name: str, arr: np.ndarray, values_per_line: int = 20) -> str:
    flat = arr.astype(np.int8).flatten()
    lines = []
    for i in range(0, len(flat), values_per_line):
        chunk = flat[i:i + values_per_line]
        lines.append(", ".join(str(int(v)) for v in chunk))
    body = ",\n    ".join(lines)
    return f"static const int8_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"


def _c_array_i32(name: str, arr: np.ndarray, values_per_line: int = 12) -> str:
    flat = arr.astype(np.int32).flatten()
    lines = []
    for i in range(0, len(flat), values_per_line):
        chunk = flat[i:i + values_per_line]
        lines.append(", ".join(str(int(v)) for v in chunk))
    body = ",\n    ".join(lines)
    return f"static const int32_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"


def write_hw_testbench_header(results: list) -> None:
    """Writes HW/real_layers_data.h - the C-sim-testbench-side twin of
    layers_meta.json/network_*.h (REAL_WEIGHTS_PLAN.md step 7): every real
    layer's input/weights/bias/expected embedded as C++ arrays, plus a
    RealLayerCfg descriptor table conv_engine_tb.cpp's real-layer suite
    loops over. Embedded (like SW/network_weights.h), NOT read from
    layerNN_*.bin at C-sim runtime - Vitis HLS's C-sim working directory is
    not guaranteed to make a relative path back to python/ resolve
    correctly, and embedding avoids that fragility entirely at the cost of
    duplicating this data's storage (SW gets its own embedded copy too, via
    export_sw_headers.py - the two are independent, not shared)."""
    parts = [
        "/* Auto-generated by python/real_layers.py - do not edit by hand.\n"
        " * Real per-layer test data (input/weights/bias/expected) from the\n"
        " * teammate's YOLOv3-tiny-ADAS golden model\n"
        " * (python_teammate/darknet_golden/), for conv_engine_tb.cpp's\n"
        " * real-layer verification suite - see REAL_WEIGHTS_PLAN.md step 7.\n"
        " * Independent of SW/network_*.h (export_sw_headers.py) - same\n"
        " * source data, separately embedded for the C-sim testbench. */\n"
        "#pragma once\n#include <cstdint>\n#include <cstddef>\n\n"
        f"#define NUM_REAL_LAYERS {len(results)}\n"
    ]

    for i, r in enumerate(results):
        tag = f"REAL_LAYER{i:02d}"
        parts.append(_c_array_i8(f"{tag}_INPUT", r["input_hwc"]))
        parts.append(_c_array_i8(f"{tag}_WEIGHTS", r["weight_oihw"].astype(np.int8)))
        parts.append(_c_array_i32(f"{tag}_BIAS", r["bias_i32"]))
        parts.append(_c_array_i8(f"{tag}_EXPECTED", r["expected_hwc"]))

    parts.append(
        "struct RealLayerCfg {\n"
        "    const char *name;\n"
        "    unsigned img_h, img_w, in_ch, out_ch, k, pad;\n"
        "    bool leaky_relu_enable;\n"
        "    int32_t requant_multiplier;\n"
        "    unsigned requant_shift;\n"
        "    const int8_t  *input;    size_t input_size;\n"
        "    const int8_t  *weights;  size_t weights_size;\n"
        "    const int32_t *bias;     size_t bias_size;\n"
        "    const int8_t  *expected; size_t expected_size;\n"
        "};\n\n"
    )

    rows = []
    for i, r in enumerate(results):
        tag = f"REAL_LAYER{i:02d}"
        rows.append(
            f'    {{ "real-layer{i:02d} (manifest idx {r["index"]})", '
            f'{r["img_h"]}, {r["img_w"]}, {r["in_ch"]}, {r["out_ch"]}, {r["k"]}, {r["pad"]}, '
            f'{"true" if r["leaky_relu_enable"] else "false"}, '
            f'{r["requant_multiplier"]}, {r["requant_shift"]}, '
            f'{tag}_INPUT, {r["input_hwc"].size}, '
            f'{tag}_WEIGHTS, {r["weight_oihw"].size}, '
            f'{tag}_BIAS, {r["bias_i32"].size}, '
            f'{tag}_EXPECTED, {r["expected_hwc"].size} }},'
        )
    parts.append(
        f"static const RealLayerCfg REAL_LAYERS[NUM_REAL_LAYERS] = {{\n"
        + "\n".join(rows) + "\n};\n"
    )

    (HW_DIR / "real_layers_data.h").write_text("\n".join(parts))
    total_bytes = sum(
        r["input_hwc"].nbytes + r["weight_oihw"].nbytes + r["bias_i32"].nbytes + r["expected_hwc"].nbytes
        for r in results
    )
    print(f"Wrote {HW_DIR / 'real_layers_data.h'} ({total_bytes} bytes of embedded data, "
          f"{len(results)} layers)")


def main() -> None:
    manifest = load_manifest()
    layer_meta_by_index = {entry["index"]: entry for entry in manifest["layers"]}

    results = []
    for idx in CONV_LAYER_INDICES:
        r = process_layer(manifest, layer_meta_by_index, idx)
        status = "PASS (bit-exact)" if r["mismatches"] == 0 else "FAIL"
        print(f"layer {idx:2d}: in {r['img_h']}x{r['img_w']}x{r['in_ch']:4d} -> "
              f"out {r['img_h']-r['k']+1+2*r['pad']}x{r['img_w']-r['k']+1+2*r['pad']}x{r['out_ch']:4d} "
              f"(k={r['k']}, act={'leaky' if r['leaky_relu_enable'] else 'linear'})  "
              f"mismatches={r['mismatches']}/{r['total']}  {status}")
        results.append(r)

    n_fail = sum(1 for r in results if r["mismatches"] != 0)
    if n_fail:
        print(f"\n{n_fail}/{len(results)} layers FAILED bit-exact verification against "
              f"real int8_layers_sample data - DO NOT proceed to write .bin files or trust "
              f"this data until every layer passes. See REAL_WEIGHTS_PLAN.md's step 6.")
        raise SystemExit(1)

    print(f"\nAll {len(results)} real conv layers verified bit-exact against "
          f"int8_layers_sample/. Writing layerNN_*.bin files...")

    for i, r in enumerate(results):
        tag = f"layer{i:02d}"
        r["input_hwc"].tofile(HERE / f"{tag}_input.bin")
        r["weight_oihw"].astype(np.int8).tofile(HERE / f"{tag}_weights.bin")
        r["bias_i32"].tofile(HERE / f"{tag}_bias.bin")  # int32 - see REAL_WEIGHTS_PLAN.md step 3
        r["expected_hwc"].tofile(HERE / f"{tag}_expected_output.bin")
        print(f"  {tag}: manifest layer {r['index']:2d}  "
              f"in_ch={r['in_ch']:4d} out_ch={r['out_ch']:4d} k={r['k']} pad={r['pad']}  "
              f"leaky_relu_enable={int(r['leaky_relu_enable'])}  "
              f"requant_multiplier={r['requant_multiplier']}  requant_shift={r['requant_shift']}")

    # layers_meta.json - read by export_sw_headers.py (REAL_WEIGHTS_PLAN.md
    # step 3) instead of `from golden_model import NETWORK`: golden_model.py's
    # NETWORK was a plain (img_h,img_w,in_ch,out_ch,k,pad) tuple list with no
    # room for per-layer requant_multiplier/requant_shift/leaky_relu_enable -
    # real layers need all three, so export_sw_headers.py now reads this
    # richer, real-data-derived file instead. Written in the same per-layer
    # order as the layerNN_*.bin files above (layers_meta[i] <-> layerNN).
    layers_meta = [
        {
            "img_h": r["img_h"], "img_w": r["img_w"],
            "in_ch": r["in_ch"], "out_ch": r["out_ch"],
            "k": r["k"], "stride": 1, "pad": r["pad"],
            "requant_multiplier": r["requant_multiplier"],
            "requant_shift": r["requant_shift"],
            "leaky_relu_enable": int(r["leaky_relu_enable"]),
            "source_manifest_index": r["index"],
        }
        for r in results
    ]
    with open(HERE / "layers_meta.json", "w") as f:
        json.dump(layers_meta, f, indent=2)

    write_hw_testbench_header(results)

    print(f"\nDone. NUM_LAYERS={len(results)}. Wrote layers_meta.json "
          f"(per-layer shape/requant/activation, read by export_sw_headers.py), "
          f"layer{{NN}}_*.bin (same filename convention golden_model.py's "
          f"placeholder output used), and HW/real_layers_data.h (for "
          f"conv_engine_tb.cpp's real-layer C-sim suite, REAL_WEIGHTS_PLAN.md "
          f"step 7).")


if __name__ == "__main__":
    main()
