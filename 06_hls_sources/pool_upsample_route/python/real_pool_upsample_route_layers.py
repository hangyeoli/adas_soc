#!/usr/bin/env python3
"""
real_pool_upsample_route_layers.py

This project's own copy of conv_engine_requant/python/real_layers.py's
pattern (deliberately NOT shared/imported - see that file's project's
README.md provenance section for why each isolated project folder in this
codebase is self-contained), extended to the 3 op types conv_engine never
implemented: MaxPool, Upsample, Route/concat (RTL_HANDOFF_KO.md section 6).

For each real maxpool/upsample/route layer in the network this:
  1. loads its real input(s) from the PRECEDING/named layer's real dump
     (artifacts/int8_layers_sample/layer_{idx}.bin) - maxpool/upsample take
     input from the immediately preceding manifest index; route takes input
     from its explicit "sources" list (model_manifest.json)
  2. runs an INDEPENDENT numpy re-implementation of each engine's exact math
     (own round_shift/saturate, not imported from conv_engine_requant's
     script or from quantization.py) and diffs against the real
     layer_{idx}.bin dump, bit-exact, BEFORE trusting anything
  3. writes HW/real_pool_upsample_route_data.h - embedded C arrays +
     RealMaxpoolCfg[]/RealUpsampleCfg[]/RealRouteCfg[] tables, consumed by
     pool_upsample_route_tb.cpp's real-layer suite

NOTE: model_manifest.json's maxpool/upsample layer entries carry only
{index, type, output_scale, output_bits} - no pool size/stride/factor
field. STRIDE_PAD_TABLE / UPSAMPLE_INDICES below hardcode those per
RTL_HANDOFF_KO.md section 7, matching maxpool_engine.h/upsample_engine.h's
own header comment on this same gap.

Usage:
    python3 real_pool_upsample_route_layers.py
Requires: numpy only (no torch, no Vitis).
"""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DARKNET_DIR = HERE.parents[2] / "python_teammate" / "darknet_golden"
INT8_DIR = DARKNET_DIR / "artifacts" / "int8"
SAMPLE_DIR = DARKNET_DIR / "artifacts" / "int8_layers_sample"
HW_DIR = HERE.parent / "HW"

# RTL_HANDOFF_KO.md section 7's execution-order table: every maxpool layer
# index -> (stride, pad_right, pad_bottom). Layer 11 is the sole stride-1 +
# padded case; every other maxpool layer is stride-2, no padding.
MAXPOOL_STRIDE_PAD = {
    1: (2, 0, 0),
    3: (2, 0, 0),
    5: (2, 0, 0),
    7: (2, 0, 0),
    9: (2, 0, 0),
    11: (1, 1, 1),
}
UPSAMPLE_INDICES = [19]
ROUTE_INDICES = [17, 20]


# ---------------------------------------------------------------------------
# Independent re-implementations - own round_shift/saturate, not shared with
# conv_engine_requant/python/real_layers.py's copy or route_concat_engine.cpp.
# ---------------------------------------------------------------------------

def round_shift(x: np.ndarray, s: int) -> np.ndarray:
    if s == 0:
        return x
    half = np.int64(1) << (s - 1)
    magnitude = np.abs(x)
    rounded = (magnitude + half) >> np.int64(s)
    return np.where(x < 0, -rounded, rounded)


def saturate_i8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, -128, 127).astype(np.int8)


def ref_maxpool(x_hwc: np.ndarray, stride: int, pad_right: int, pad_bottom: int) -> np.ndarray:
    """Pad right/bottom with -128 (matching maxpool_engine's MAXPOOL_PAD_VALUE),
    then take a strided 2x2-window max via 4 plain slices - equivalent to,
    but far simpler than, indexing each output pixel's window directly."""
    h, w, ch = x_hwc.shape
    x_pad = np.pad(x_hwc, ((0, pad_bottom), (0, pad_right), (0, 0)),
                    mode="constant", constant_values=-128).astype(np.int64)
    out_h = (h + pad_bottom - 2) // stride + 1
    out_w = (w + pad_right - 2) // stride + 1
    out = np.full((out_h, out_w, ch), -128, dtype=np.int64)
    for dy in range(2):
        for dx in range(2):
            window = x_pad[dy: dy + stride * out_h: stride, dx: dx + stride * out_w: stride, :]
            out = np.maximum(out, window)
    return out.astype(np.int8)


def ref_upsample(x_hwc: np.ndarray) -> np.ndarray:
    return np.repeat(np.repeat(x_hwc, 2, axis=0), 2, axis=1)


def ref_route_concat(src0_hwc: np.ndarray, src1_hwc, src0_requant, src1_requant) -> np.ndarray:
    def apply(x, requant):
        if requant is None:
            return x.astype(np.int64)
        mult, shift = requant
        scaled = x.astype(np.int64) * np.int64(mult)
        return round_shift(scaled, shift)

    parts = [apply(src0_hwc, src0_requant)]
    if src1_hwc is not None:
        parts.append(apply(src1_hwc, src1_requant))
    out = np.concatenate(parts, axis=2)
    return saturate_i8(out)


# ---------------------------------------------------------------------------
# Data loading (subset of conv_engine_requant/python/real_layers.py's own
# loaders, re-derived independently here rather than imported)
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    with open(INT8_DIR / "model_manifest.json") as f:
        return json.load(f)


_SAMPLE_MANIFEST = None


def load_real_activation_nchw(layer_index: int) -> np.ndarray:
    global _SAMPLE_MANIFEST
    if _SAMPLE_MANIFEST is None:
        with open(SAMPLE_DIR / "manifest.json") as f:
            _SAMPLE_MANIFEST = {e["layer"]: e for e in json.load(f)}
    entry = _SAMPLE_MANIFEST[layer_index]
    assert entry["layout"] == "NCHW" and entry["dtype"] == "int8", (
        f"layer {layer_index} sample: unexpected layout/dtype {entry['layout']}/{entry['dtype']}"
    )
    shape = entry["shape"]  # [1, C, H, W]
    raw = np.fromfile(SAMPLE_DIR / entry["file"], dtype=np.int8).reshape(shape)
    return raw[0]  # (C,H,W)


def chw_to_hwc(x_chw: np.ndarray) -> np.ndarray:
    return np.transpose(x_chw, (1, 2, 0))


# ---------------------------------------------------------------------------
# Per-op-type processing
# ---------------------------------------------------------------------------

def process_maxpool(idx: int) -> dict:
    stride, pad_right, pad_bottom = MAXPOOL_STRIDE_PAD[idx]
    input_hwc = chw_to_hwc(load_real_activation_nchw(idx - 1))
    expected_hwc = chw_to_hwc(load_real_activation_nchw(idx))

    computed = ref_maxpool(input_hwc, stride, pad_right, pad_bottom)
    mismatches = int(np.sum(computed != expected_hwc))
    return {
        "index": idx, "op": "maxpool",
        "img_h": input_hwc.shape[0], "img_w": input_hwc.shape[1], "ch": input_hwc.shape[2],
        "stride": stride, "pad_right": pad_right, "pad_bottom": pad_bottom,
        "input_hwc": input_hwc.astype(np.int8), "expected_hwc": expected_hwc.astype(np.int8),
        "mismatches": mismatches, "total": computed.size,
    }


def process_upsample(idx: int) -> dict:
    input_hwc = chw_to_hwc(load_real_activation_nchw(idx - 1))
    expected_hwc = chw_to_hwc(load_real_activation_nchw(idx))

    computed = ref_upsample(input_hwc)
    mismatches = int(np.sum(computed != expected_hwc))
    return {
        "index": idx, "op": "upsample",
        "img_h": input_hwc.shape[0], "img_w": input_hwc.shape[1], "ch": input_hwc.shape[2],
        "input_hwc": input_hwc.astype(np.int8), "expected_hwc": expected_hwc.astype(np.int8),
        "mismatches": mismatches, "total": computed.size,
    }


def process_route(manifest: dict, layer_meta_by_index: dict, idx: int) -> dict:
    layer = layer_meta_by_index[idx]
    assert layer["type"] == "route"
    sources = layer["sources"]
    src_requant_by_source = {sr["source"]: sr for sr in layer["source_requantization"]}

    src0_idx = sources[0]
    src0_hwc = chw_to_hwc(load_real_activation_nchw(src0_idx))
    sr0 = src_requant_by_source[src0_idx]
    src0_requant = None if sr0["operation"] == "passthrough" else (
        sr0["requant_multiplier"], sr0["requant_right_shift"]
    )

    src1_hwc = None
    src1_requant = None
    if len(sources) > 1:
        src1_idx = sources[1]
        src1_hwc = chw_to_hwc(load_real_activation_nchw(src1_idx))
        sr1 = src_requant_by_source[src1_idx]
        src1_requant = None if sr1["operation"] == "passthrough" else (
            sr1["requant_multiplier"], sr1["requant_right_shift"]
        )

    expected_hwc = chw_to_hwc(load_real_activation_nchw(idx))
    computed = ref_route_concat(src0_hwc, src1_hwc, src0_requant, src1_requant)
    mismatches = int(np.sum(computed != expected_hwc))

    return {
        "index": idx, "op": "route",
        "img_h": src0_hwc.shape[0], "img_w": src0_hwc.shape[1],
        "ch0": src0_hwc.shape[2], "ch1": (src1_hwc.shape[2] if src1_hwc is not None else 0),
        "src0_hwc": src0_hwc.astype(np.int8),
        "src1_hwc": (src1_hwc.astype(np.int8) if src1_hwc is not None else np.zeros((0,), dtype=np.int8)),
        "src0_requant": src0_requant, "src1_requant": src1_requant,
        "expected_hwc": expected_hwc.astype(np.int8),
        "mismatches": mismatches, "total": computed.size,
    }


# ---------------------------------------------------------------------------
# C header generation
# ---------------------------------------------------------------------------

def _c_array_i8(name: str, arr: np.ndarray, values_per_line: int = 20) -> str:
    flat = arr.astype(np.int8).flatten()
    if flat.size == 0:
        return f"static const int8_t {name}[1] = {{ 0 }};\n"
    lines = []
    for i in range(0, len(flat), values_per_line):
        chunk = flat[i:i + values_per_line]
        lines.append(", ".join(str(int(v)) for v in chunk))
    body = ",\n    ".join(lines)
    return f"static const int8_t {name}[{len(flat)}] = {{\n    {body}\n}};\n"


def write_header(maxpool_results: list, upsample_results: list, route_results: list) -> None:
    parts = [
        "/* Auto-generated by python/real_pool_upsample_route_layers.py - do\n"
        " * not edit by hand. Real per-layer test data (input/expected) from\n"
        " * the teammate's YOLOv3-tiny-ADAS golden model\n"
        " * (python_teammate/darknet_golden/), for\n"
        " * pool_upsample_route_tb.cpp's real-layer verification suite. */\n"
        "#pragma once\n#include <cstdint>\n#include <cstddef>\n\n"
        f"#define NUM_REAL_MAXPOOL_LAYERS {len(maxpool_results)}\n"
        f"#define NUM_REAL_UPSAMPLE_LAYERS {len(upsample_results)}\n"
        f"#define NUM_REAL_ROUTE_LAYERS {len(route_results)}\n"
    ]

    for i, r in enumerate(maxpool_results):
        tag = f"REAL_MAXPOOL{i:02d}"
        parts.append(_c_array_i8(f"{tag}_INPUT", r["input_hwc"]))
        parts.append(_c_array_i8(f"{tag}_EXPECTED", r["expected_hwc"]))
    for i, r in enumerate(upsample_results):
        tag = f"REAL_UPSAMPLE{i:02d}"
        parts.append(_c_array_i8(f"{tag}_INPUT", r["input_hwc"]))
        parts.append(_c_array_i8(f"{tag}_EXPECTED", r["expected_hwc"]))
    for i, r in enumerate(route_results):
        tag = f"REAL_ROUTE{i:02d}"
        parts.append(_c_array_i8(f"{tag}_SRC0", r["src0_hwc"]))
        parts.append(_c_array_i8(f"{tag}_SRC1", r["src1_hwc"]))
        parts.append(_c_array_i8(f"{tag}_EXPECTED", r["expected_hwc"]))

    parts.append(
        "struct RealMaxpoolCfg {\n"
        "    const char *name;\n"
        "    unsigned img_h, img_w, ch, stride, pad_right, pad_bottom;\n"
        "    const int8_t *input;    size_t input_size;\n"
        "    const int8_t *expected; size_t expected_size;\n"
        "};\n\n"
        "struct RealUpsampleCfg {\n"
        "    const char *name;\n"
        "    unsigned img_h, img_w, ch;\n"
        "    const int8_t *input;    size_t input_size;\n"
        "    const int8_t *expected; size_t expected_size;\n"
        "};\n\n"
        "struct RealRouteCfg {\n"
        "    const char *name;\n"
        "    unsigned img_h, img_w, ch0, ch1;\n"
        "    uint8_t src0_requant_enable; int32_t src0_requant_multiplier; uint8_t src0_requant_shift;\n"
        "    uint8_t src1_requant_enable; int32_t src1_requant_multiplier; uint8_t src1_requant_shift;\n"
        "    const int8_t *src0;     size_t src0_size;\n"
        "    const int8_t *src1;     size_t src1_size;\n"
        "    const int8_t *expected; size_t expected_size;\n"
        "};\n\n"
    )

    mp_rows = []
    for i, r in enumerate(maxpool_results):
        tag = f"REAL_MAXPOOL{i:02d}"
        mp_rows.append(
            f'    {{ "real-maxpool{i:02d} (manifest idx {r["index"]})", '
            f'{r["img_h"]}, {r["img_w"]}, {r["ch"]}, {r["stride"]}, {r["pad_right"]}, {r["pad_bottom"]}, '
            f'{tag}_INPUT, {r["input_hwc"].size}, {tag}_EXPECTED, {r["expected_hwc"].size} }},'
        )
    parts.append(
        f"static const RealMaxpoolCfg REAL_MAXPOOL_LAYERS[NUM_REAL_MAXPOOL_LAYERS > 0 ? NUM_REAL_MAXPOOL_LAYERS : 1] = {{\n"
        + "\n".join(mp_rows) + "\n};\n\n"
    )

    up_rows = []
    for i, r in enumerate(upsample_results):
        tag = f"REAL_UPSAMPLE{i:02d}"
        up_rows.append(
            f'    {{ "real-upsample{i:02d} (manifest idx {r["index"]})", '
            f'{r["img_h"]}, {r["img_w"]}, {r["ch"]}, '
            f'{tag}_INPUT, {r["input_hwc"].size}, {tag}_EXPECTED, {r["expected_hwc"].size} }},'
        )
    parts.append(
        f"static const RealUpsampleCfg REAL_UPSAMPLE_LAYERS[NUM_REAL_UPSAMPLE_LAYERS > 0 ? NUM_REAL_UPSAMPLE_LAYERS : 1] = {{\n"
        + "\n".join(up_rows) + "\n};\n\n"
    )

    rt_rows = []
    for i, r in enumerate(route_results):
        tag = f"REAL_ROUTE{i:02d}"
        s0_en, s0_mult, s0_shift = (1, r["src0_requant"][0], r["src0_requant"][1]) if r["src0_requant"] else (0, 0, 0)
        s1_en, s1_mult, s1_shift = (1, r["src1_requant"][0], r["src1_requant"][1]) if r["src1_requant"] else (0, 0, 0)
        rt_rows.append(
            f'    {{ "real-route{i:02d} (manifest idx {r["index"]})", '
            f'{r["img_h"]}, {r["img_w"]}, {r["ch0"]}, {r["ch1"]}, '
            f'{s0_en}, {s0_mult}, {s0_shift}, {s1_en}, {s1_mult}, {s1_shift}, '
            f'{tag}_SRC0, {r["src0_hwc"].size}, {tag}_SRC1, {r["src1_hwc"].size}, '
            f'{tag}_EXPECTED, {r["expected_hwc"].size} }},'
        )
    parts.append(
        f"static const RealRouteCfg REAL_ROUTE_LAYERS[NUM_REAL_ROUTE_LAYERS > 0 ? NUM_REAL_ROUTE_LAYERS : 1] = {{\n"
        + "\n".join(rt_rows) + "\n};\n"
    )

    out_path = HW_DIR / "real_pool_upsample_route_data.h"
    out_path.write_text("\n".join(parts))
    print(f"Wrote {out_path}")


def main() -> None:
    manifest = load_manifest()
    layer_meta_by_index = {entry["index"]: entry for entry in manifest["layers"]}

    maxpool_results = [process_maxpool(idx) for idx in sorted(MAXPOOL_STRIDE_PAD)]
    upsample_results = [process_upsample(idx) for idx in UPSAMPLE_INDICES]
    route_results = [process_route(manifest, layer_meta_by_index, idx) for idx in ROUTE_INDICES]

    all_results = maxpool_results + upsample_results + route_results
    for r in all_results:
        status = "PASS (bit-exact)" if r["mismatches"] == 0 else "FAIL"
        print(f"{r['op']:8s} layer {r['index']:2d}: mismatches={r['mismatches']}/{r['total']}  {status}")

    n_fail = sum(1 for r in all_results if r["mismatches"] != 0)
    if n_fail:
        print(f"\n{n_fail}/{len(all_results)} layers FAILED bit-exact verification against "
              f"real int8_layers_sample data - DO NOT trust this data until every layer passes.")
        raise SystemExit(1)

    print(f"\nAll {len(all_results)} real maxpool/upsample/route layers verified bit-exact. "
          f"Writing HW/real_pool_upsample_route_data.h...")
    write_header(maxpool_results, upsample_results, route_results)


if __name__ == "__main__":
    main()
