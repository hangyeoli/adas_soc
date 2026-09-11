#!/usr/bin/env python3
"""
Golden model for conv_engine (the shared/time-multiplexed convolution
engine, see ../README.md for why this replaces one-IP-per-layer).

Unlike hls/conv_layer1/python/golden_model.py (one fixed layer shape), this
script generates test vectors for a WHOLE NETWORK: a list of layer_cfg dicts,
each with its own (img_h, img_w, in_ch, out_ch, k, pad). conv_engine is the
same hardware for every entry - only its runtime registers change - so the
golden model mirrors that by running the identical conv2d() function once
per layer, chaining output[i] -> input[i+1] exactly like the real engine
will via DDR.

Usage:
    python3 golden_model.py
Produces (next to this script):
    layerNN_input.bin, layerNN_weights.bin, layerNN_bias.bin,
    layerNN_expected_output.bin   for each layer NN in NETWORK (below)

export_sw_headers.py reads these and generates SW/network_layers.h (the
layer descriptor table) plus the per-layer weight/bias/expected-output data
consumed by SW/network_run.c.
"""

from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# NETWORK: placeholder layer list.
#
# TODO(Phase 0): this is NOT the final Phase 1 traffic-sign network - it is
# a small 3-layer stand-in (chosen to exercise channel growth and a
# non-multiple-of-PE_OC out_ch, same general intent as the multi-tile edge
# cases in conv_engine_tb.cpp) so the multi-layer chaining machinery (this
# script, export_sw_headers.py, SW/network_run.c) can be built and tested
# now, without waiting on the final class-scope/anchor-box decision that
# doc/planning_기획서.md 6.2 defers to Phase 0. Replace this list once that
# decision is made - nothing else in this file depends on these specific
# numbers.
NETWORK = [
    # (img_h, img_w, in_ch, out_ch, k, pad)
    (16, 16, 3, 8, 3, 1),
    (16, 16, 8, 16, 3, 1),
    (16, 16, 16, 6, 3, 1),  # out_ch=6, not a multiple of PE_OC=16 - see conv_engine.h
]

SEED = 42


def leaky_relu_shift(acc: np.ndarray, shift: int = 3) -> np.ndarray:
    return np.where(acc >= 0, acc, acc >> shift)


def saturate_i8(x: np.ndarray) -> np.ndarray:
    return np.clip(x, -128, 127).astype(np.int8)


def conv2d_golden(x: np.ndarray, w: np.ndarray, b: np.ndarray,
                   k: int, pad: int) -> np.ndarray:
    """
    x: (H, W, IN_CH) int8      w: (OUT_CH, IN_CH, K, K) int8      b: (OUT_CH,) int8
    returns: (H, W, OUT_CH) int8   (stride=1 only, matching conv_engine.h)
    """
    img_h, img_w, in_ch = x.shape
    out_ch = w.shape[0]

    x_i32 = x.astype(np.int32)
    w_i32 = w.astype(np.int32)
    b_i32 = b.astype(np.int32)

    x_pad = np.pad(x_i32, ((pad, pad), (pad, pad), (0, 0)), mode="constant")

    out_h = img_h + 2 * pad - k + 1
    out_w = img_w + 2 * pad - k + 1

    out = np.zeros((out_h, out_w, out_ch), dtype=np.int32)
    for oc in range(out_ch):
        acc = np.full((out_h, out_w), b_i32[oc], dtype=np.int32)
        for ic in range(in_ch):
            for ky in range(k):
                for kx in range(k):
                    patch = x_pad[ky:ky + out_h, kx:kx + out_w, ic]
                    acc += patch * w_i32[oc, ic, ky, kx]
        out[:, :, oc] = acc

    out = leaky_relu_shift(out)
    return saturate_i8(out)


def main():
    rng = np.random.default_rng(SEED)

    x = None  # chained from the previous layer's output, like the real system
    for i, (img_h, img_w, in_ch, out_ch, k, pad) in enumerate(NETWORK):
        if x is None:
            x = rng.integers(-20, 21, size=(img_h, img_w, in_ch), dtype=np.int8)
        else:
            assert x.shape == (img_h, img_w, in_ch), (
                f"layer {i}: previous layer's output shape {x.shape} does not "
                f"match this layer's declared input shape "
                f"{(img_h, img_w, in_ch)} - fix the NETWORK list above"
            )

        w = rng.integers(-5, 6, size=(out_ch, in_ch, k, k), dtype=np.int8)
        b = rng.integers(-4, 5, size=(out_ch,), dtype=np.int8)

        y = conv2d_golden(x, w, b, k, pad)

        tag = f"layer{i:02d}"
        x.tofile(OUT_DIR / f"{tag}_input.bin")
        w.tofile(OUT_DIR / f"{tag}_weights.bin")
        b.tofile(OUT_DIR / f"{tag}_bias.bin")
        y.tofile(OUT_DIR / f"{tag}_expected_output.bin")

        print(f"{tag}: in {x.shape} -> out {y.shape} "
              f"(k={k}, pad={pad}, out_ch={out_ch})")

        x = y  # chain: this layer's output feeds the next layer's input

    print("Done. Next: run export_sw_headers.py to generate "
          "SW/network_layers.h and the per-layer SW headers.")


if __name__ == "__main__":
    main()
