# conv_engine_requant — int8×4 packed `ifmap` (`pack4`), MERGED COPY

> **This is the merged deliverable**: `hls/conv_engine_requant` (current, with
> the §25 finish-path fix) **+** the int8×4 `ifmap` packing, delivered as a
> separate directory so the original tree was never modified.
>
> Only four files differ from `hls/conv_engine_requant`, all in `HW/`:
> `pack4.h` (new), `conv_engine.h`, `conv_engine.cpp`, `conv_engine_tb.cpp`.
> `SW/conv_engine_hw_driver.h` additionally gained a documentation-only
> "CALLER OBLIGATION" block (4-byte-aligned `ifmap`; **no** `in_ch % 4`
> requirement — see §3). A `diff -rq` against the baseline confirms nothing
> else changed.
>
> **Verified on this tree (2026-08-04), cosim deliberately skipped:**
> - `csim` — **ALL CONFIGS PASS** + **ALL REAL LAYERS PASS** (full battery:
>   12 synthetic configs + all 13 real golden layers, not the single-layer
>   mode).
> - `csynth` — clean.
> - **Package IP — exported**, `impl/ip` present.
> - **The generated `xconv_engine_hw.h` is byte-identical to the baseline's**
>   (`diff` clean) — the `s_axilite` register map really is unchanged, and
>   `SW/conv_engine_hw_driver.h`'s existing offsets remain correct.
> - Resources vs baseline: LUT 72,228 → 72,365 (**+137**), FF 33,954 →
>   33,288 (**−666**), DSP 218 → 221 (+3), BRAM 136 → 136.
>
> **Not run here:** cosim. The 1.36× in §6 was measured in
> `conv_engine_requant_pack4` on byte-identical `HW/` sources; re-run
> `RUN_HLS_COSIM_LAYER=3 run_hls.bat cosim` here if you want the number
> produced in this tree.
>
> **To adopt:** either use this directory directly, or copy its four `HW/`
> files and the `SW/` driver over `hls/conv_engine_requant` — **backing that
> tree's `HW/`+`SW/` up first, since the repo has no git.**

Originally developed in `hls/conv_engine_requant_pack4`, a working copy of
`hls/conv_engine_requant` taken 2026-08-04 **after** the finish-path fix
(TROUBLESHOOTING §25) landed, so it includes that work.

> An earlier copy of this directory existed and was an unmodified duplicate,
> created when I wrongly concluded conv was not worth packing. That
> conclusion came from a stale comment in `conv_engine.cpp`; see §2. The old
> copy was deleted and replaced with a fresh one from current sources.

## 1. What changed

Exactly one port: **`ifmap` is now `pack4_t*` (`ap_uint<32>`)** instead of
`act_t*` (`ap_int<8>`), carrying 4 consecutive NHWC channels per AXI beat.
`HW/pack4.h` is new and holds the type, the lane accessors, and the
rationale.

Nothing else was touched — `weights`, `weights_hi`, `bias`, `ofmap` and
`accum` keep their original element types, their bundles, and their pragmas.
The `s_axilite` register map is unchanged, and `in_ch` is still counted in
**channels**, not words.

## 2. Why — and the stale comment that said not to

`conv_engine.cpp`'s comment above `READ_CH` still claims READ_CH is
"12~139 against `SHIFT_WINDOW`'s 49~3554" and therefore a minority of
runtime. **That was true when written and is no longer.** `SHIFT_WINDOW` has
since been optimized roughly 70× to 2~51, which makes `READ_CH` the
**largest single term** in `COL_LOOP`:

| sub-block, one `COL_LOOP` scan position | cycles (min ~ max) | share of 411 |
|---|---|---|
| `READ_CH` (ifmap read) | 12 ~ **139** | **33.8%** |
| `MAC_REDUCE / MAC_KY / MAC_KX` | 7 ~ 78 | 19.0% |
| `WINDOW_ROW/COL_SHIFT` (old `SHIFT_WINDOW`) | 2 ~ 51 | 12.4% |
| `FINISH_WR` (ofmap write) | 13 ~ 36 | 8.8% |
| `WINDOW_TAIL_FILL` | 4 ~ 27 | 6.6% |
| `ACCUM_RD` | 4 ~ 27 | 6.6% |
| `ACCUM_WR` | 3 ~ 26 | 6.3% |
| `LINE_BUF_ROW_SHIFT` | 2 ~ 18 | 4.4% |
| `LINE_BUF_TAIL_FILL` | 3 ~ 10 | 2.4% |
| **`COL_LOOP` total** | 19 ~ **411** | |

The maxima sum to 412 against a reported max of 411, so they do essentially
co-occur — this is not unrelated bounds being added up.

**Fix the comment in the baseline tree.** Anyone reading it today would
conclude the read path is not worth touching, and that is now backwards.

## 3. The layer-0 problem, and why there are two paths

`in_ch % 4 == 0` holds for every real conv layer **except layer 0**, whose
input is RGB with `in_ch = 3`:

| layer | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `in_ch` | **3** | 16 | 32 | 64 | 128 | 256 | 512 | 1024 | 256 | 512 | 256 | 384 | 256 |

Rather than force layer 0's input to be re-laid-out as RGBX in DDR (and its
weights to gain a zero 4th input channel), `READ_CH` has two paths:

- **`READ_CH_WORDS`** — `in_ch % 4 == 0`. One beat per 4 channels. Every
  layer but layer 0.
- **`READ_CH_ELEMS`** — otherwise. One channel per beat, extracted from its
  containing word. Only layer 0 takes this, and its `READ_CH` trip count is
  3, so the speedup forgone there is worth nothing.

Keeping the slow path is what preserves the property that makes this
technique cheap: **no PS-side data change at all.** It costs almost nothing
in hardware (§5).

`ic_lo` is always a multiple of the ic_tile width `MAX_IN_CH` (128), so each
tile pass starts word-aligned and `ic_count` is a whole number of words
whenever `in_ch` is. That is asserted rather than assumed, since a future
`MAX_IN_CH` change could silently break the fast path.

## 4. Correctness

Verified by compiling the engine and testbench directly with `g++` against
the Vitis headers (35 s, versus a ~35 min Vitis round trip):

```bash
g++ -std=c++14 -O1 -w -I/mnt/c/Xilinx/Vitis/2024.2/include \
    -o tb_conv_pack4 HW/conv_engine.cpp HW/conv_engine_tb.cpp
./tb_conv_pack4      # -> ALL CONFIGS PASS / ALL REAL LAYERS PASS
```

**All 12 synthetic configs and all 13 real golden layers matched
bit-exactly**, plus both pack/unpack self-tests. Both paths are covered, and
not just incidentally:

- fast path: config-E (`in_ch=128`), config-F (20), config-J (256), and
  real layers 1–12.
- slow path: config-A (3), config-D (1), **config-I (129)** and
  **config-K (150)** — the last two are the important ones, since they
  exercise a non-multiple-of-4 `in_ch` *across multiple ic_tiles*, where a
  word-alignment mistake in the address arithmetic would show up.
- real-layer00 (`in_ch=3`) exercises the slow path against real golden data.

Vitis `csim` independently reported `COSIM CONFIG PASS` for layer 3.

The `reference_conv()` model and all golden arrays are left entirely
`int8_t`-based and unaware of the packing, so a PASS is evidence the packing
is bit-exact rather than evidence both sides share the same bug.

## 5. Cost

`csynth`, baseline vs packed, same part and clock:

| | baseline | packed | delta |
|---|---|---|---|
| LUT | 72,228 | 72,365 | **+137** |
| FF | 33,954 | 33,288 | **−666** |
| DSP | 218 | 221 | +3 |
| BRAM_18K | 136 | 136 | 0 |

Carrying both READ_CH paths is essentially free.

`READ_CH_WORDS` measures **4 ~ 35 cycles** against the baseline `READ_CH`'s
**12 ~ 139** — the expected 4× on the fast path, `II=1` held.

### Why `COL_LOOP`'s worst case did *not* improve

`COL_LOOP` max went 411 → 413. This is expected and not a regression:
csynth's worst case is taken over *all possible* `in_ch`, and the worst case
is the **slow** path (`READ_CH_ELEMS`, still 12~139) plus two cycles of
branch overhead. The fast path's 4~35 never appears in that bound.

**So the csynth top-line latency is the wrong number to judge this change
by.** Use the cosim result on a real layer, §6.

## 6. Measured result — layer 3 cosim

Layer 3 is `img 36×64`, `in_ch=64`, `out_ch=128`, `k=3`, `pad=1` — a fast-path
layer, and the same layer the baseline was measured on.

| | cycles | notes |
|---|---|---|
| baseline | 4,165,741 | post-finish-path-fix, `Pass` |
| **packed** | **3,074,383** | `Pass` |
| **saved** | **1,091,358** | **−26.2%, i.e. 1.36×** |

That is close to the ~23%-off-`COL_LOOP` predicted from the loop table, and
it is a real RTL measurement on real layer-3 weights and activations, not an
estimate.

### Extrapolating — carefully

Layer 3 is one of 13 conv layers and they do not all benefit equally: the
gain scales with how large `READ_CH` is relative to the rest of `COL_LOOP`,
which varies with `in_ch`. Layer 0 gains **nothing** (slow path).

If the whole network moved by layer 3's 26%, the post-finish-path-fix
~1.76 FPS would become roughly **2.3 FPS**. Treat that as an extrapolation
from a single layer, not a result. Measuring one more layer with a different
`in_ch` — layer 6 (`in_ch=512`) or layer 7 (`in_ch=1024`, k=1) — would bound
it properly, at ~35 min of cosim each.

### A pre-existing `run_hls.bat` quirk, not a regression

The run prints `FAIL  C simulation did not print ALL CONFIGS PASS`. This is
**not** caused by the packing. In `RUN_HLS_COSIM_LAYER` mode the testbench
deliberately runs only the one targeted layer and prints `COSIM CONFIG PASS`,
but `run_hls.bat` greps for `ALL CONFIGS PASS` regardless of mode. The
baseline tree's own log shows exactly the same thing — zero `ALL CONFIGS
PASS`, three `COSIM CONFIG PASS`. Worth fixing in the script so a real csim
failure is not masked by a false alarm everyone learns to ignore.

## 7. Not done / next

- **`ofmap` (`FINISH_WR`, 8.8%)** is the next same-technique candidate,
  deliberately left out so this change could be measured alone. Its lanes
  are consecutive output channels within `PE_OC`, contiguous in NHWC.
- **`weights` / `LOAD_WTILE`** is not worth it — max 1,165 cycles but it runs
  once per `oc_tile`, totalling 14,256 inside an `IC_TILE` whose max is
  108,600,361 (~0.013%), and it would disturb the `weights`/`weights_hi`
  port split that exists specifically to hold `II=1`.
- **The structural item is still the big one.** `MAC_REDUCE` is only 19% of
  `COL_LOOP`; everything else runs sequentially with it. Packing shrinks the
  data movement but does not overlap it. See
  `doc/action_items_2026-08-04_perf.md` item 4.
- **Package IP not re-run.** The register map should be identical (the
  `ifmap` pointer's width is a data-bus property, not an `s_axilite` one),
  but confirm against a generated `xconv_engine_hw.h` rather than assuming —
  the same check that was done for the pool engines.
- **`SW/conv_engine_hw_driver.h` needs the caller-obligation note** if this
  is merged: `ifmap` must be 4-byte aligned. There is no `in_ch % 4`
  requirement thanks to the slow path.

## 8. Merging back

Confined to `HW/`:

```
cp HW/pack4.h          ../conv_engine_requant/HW/
cp HW/conv_engine.h    ../conv_engine_requant/HW/
cp HW/conv_engine.cpp  ../conv_engine_requant/HW/
cp HW/conv_engine_tb.cpp ../conv_engine_requant/HW/
```

**Back up the baseline `HW/` first** — this repo is not under git. The pool
merge used `hls/pool_upsample_route/baseline_pre_pack4_2026-08-04/`; do the
same here.
