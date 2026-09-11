# conv_engine — shared, time-multiplexed convolution engine

## This folder's provenance and scope

`conv_engine_requant/` is an isolated copy of `hls/conv_engine_int8pack/`
(itself an isolated copy of `hls/conv_engine/` - see that folder's
`TROUBLESHOOTING.md` for why each experiment gets its own copy rather than
branching in place), made to fix a specific, concrete mismatch: the engine's
INT8-packed conv datapath (PE_OC=20/TR=16, cosim-confirmed - see
`RESOURCE_BUDGET.md`) is real and reusable, but its activation/output math
did not match the actual target network's quantization scheme at all.

That target network is `python_teammate/darknet_golden/` - a real, finished
YOLOv3-tiny-ADAS 5-class INT8 golden model with an exact per-layer spec in
`darknet_golden/RTL_HANDOFF_KO.md` and
`darknet_golden/artifacts/int8/model_manifest.json`. Comparing that spec
against the inherited engine found several concrete gaps:

1. **Requantization/LeakyReLU math - fixed.** The inherited engine used a
   fixed `acc>=0 ? acc : acc>>3` in place of real per-layer requantization -
   not close to `RTL_HANDOFF_KO.md` section 5's `saturate_int8(round_shift(
   acc * multiplier, right_shift))`, and not the right LeakyReLU ratio either
   (`1/8` vs the spec's exact `13/128`). Fixed here: `conv_engine.cpp` now
   takes `requant_multiplier`/`requant_shift`/`leaky_relu_enable` as new
   per-call scalar parameters (one `conv_engine()` call is still exactly one
   layer, so these are registers, not a DDR table - software reads them from
   `model_manifest.json` per layer, same as it already does for
   `k`/`stride`/`pad`) and implements the exact round-half-away-from-zero
   formula. Bias is now `bias_t` (`ap_int<32>`, was `weight_t`/`ap_int<8>`)
   to match the golden model's `bias.bin`. Real cosim run (2026-07-23 15:07
   KST originally, then a second pass after fixing a LUT regression - see
   `TROUBLESHOOTING.md` §15): PASS, bit-exact.
2. **`MAX_IMG_W=416` vs. the real network's `width=512` - fixed.** Bumped to
   512 (covers both `width=512` and `height=288`). A single-constant bump,
   no structural change - the real cost is `line_buf`'s column dimension
   (416 -> 512 elements/instance), not yet confirmed against a synthesis
   report for this specific change in isolation (it was raised in the same
   pass as item 3 below; see that item's synthesis numbers for the combined
   effect).
3. **`MAX_IN_CH=128`, not tiled, vs. the real network's max in_ch=1024 -
   fixed.** 8 of the real network's 13 conv layers (not just layer 13 - also
   10, 12, 14, 15, 18, 21, 22) have `in_ch > 128`. Input-channel tiling
   added: `MAX_IN_CH` (128) is now purely the on-chip tile width (window/
   wtile_packed unchanged), and a new `MAX_TOTAL_IN_CH=1024` bounds the real
   `in_ch` parameter, tiled via a new `IC_TILE` loop nested inside `OC_TILE`
   in `conv_engine()`. Needs a DDR scratch buffer (`accum`, new top-level
   parameter, `[out_h][out_w][PE_OC]` - see `conv_engine.h`'s doc comment on
   it) to carry each output pixel's running pre-activation sum across
   `ic_tile` passes; LeakyReLU/requantize/saturate only applies once, on the
   LAST `ic_tile`. `oc_tile` stays the OUTER loop specifically so `accum`
   only ever needs to hold one `oc_tile`'s worth of channels (`PE_OC`, not
   `out_ch`). Verified via `g++` against Vitis's standalone `ap_int.h`
   (`conv_engine_tb.cpp` configs I/J/K, added for this: a 2-tile remainder
   case, a 2-tile exact case, and both `oc_tile`/`ic_tile` tiling at once -
   all PASS, bit-exact) - **now confirmed by a real Vitis C-sim, csynth,
   and cosim run** (2026-07-24 16:16-16:50 KST, `run_hls.bat cosim`, at
   the current `PE_OC=24`/`TR=16`): C-sim PASS on every config A-K plus
   all 13 real YOLOv3-tiny-ADAS layers bit-exact (`ALL REAL LAYERS PASS`,
   `ALL CONFIGS PASS`); csynth LUT 77,252 (65%), DSP 219 (17%), FF 34,073
   (14%), BRAM 136 (47%) - see `RESOURCE_BUDGET.md` §11's confirmation
   note; cosim `config-A-cosim` PASS, bit-exact against RTL.
4. **MaxPool (5 layers), Upsample (1 layer), Route/concat with per-source
   requantization (2 layers) - now implemented as a separate sibling
   project, `hls/pool_upsample_route/`.** Not fixed here; this engine only
   ever did Conv. `RTL_HANDOFF_KO.md`'s own recommended structure (one
   reusable Conv engine + separate small pooling/upsample/route units + a
   layer sequencer) matches this project's existing architecture
   philosophy, so the 3 new ops became 3 separate HLS IPs there rather than
   being folded into `conv_engine`. Status as of 2026-07-27: all 3 engines
   verified via g++ against Vitis's standalone `ap_int.h` (20 synthetic
   configs + all 9 real maxpool/upsample/route layers from
   `python_teammate/darknet_golden/`, bit-exact) - real Vitis HLS
   csim/csynth/cosim confirmation, SW drivers, and `vivado/create_bd.tcl`
   integration are still pending there (see that project's own README.md
   "Scope of this pass").
5. **`python/golden_model.py`'s placeholder 3-layer `NETWORK` and
   `SW/network_run.c`'s driver** still target that placeholder, not the real
   24-layer ADAS network - `network_run.c` has prominent comments on why it
   would currently produce all-zero output if pointed at the new quant
   registers, and why `accum_buf` there is only a generously-oversized
   stand-in, not a properly sized buffer (the placeholder network's own
   generator, `python/export_sw_headers.py`, computes neither yet).

Items 4-5 are follow-up work, most naturally each its own further isolated
copy of this folder, matching the pattern that produced this one.

---

This module replaces the "one dedicated HLS IP per layer" approach that
`hls/conv_layer1/` represents, once the network grows past a couple of
layers. Instead of instantiating a separate fixed-function pipeline per
layer — which does not fit the KR260's DSP budget once channel counts reach
YOLOv2-tiny scale (see the conversation that led here: a rough estimate put
`conv_layer1` alone, with only 16 output channels, at ~100+ DSPs already) —
**one single IP is reused for every conv layer**, reconfigured and re-run
once per layer by software.

`conv_layer1/` is not deleted or superseded as a *learning* artifact — it's
still the per-layer HLS walkthrough `doc/hls_study_plan.md` is built around,
and its code-review findings (cache-flush discipline, the leaky-ReLU
ordering) fed directly into this module. It's just no longer the
architecture that ships.

## Folder structure

```
conv_engine/
├── HW/
│   ├── conv_engine.h/.cpp     the shared engine (runtime-parameterized geometry)
│   └── conv_engine_tb.cpp     tests TWO different configs, not one - see below
├── SW/
│   ├── conv_engine_hw_driver.h  AXI4-Lite driver (geometry + 5 DDR addresses - see "AMBA Interface Map" below)
│   ├── network_run.c            loops over every layer, reprogramming + re-triggering
│   ├── network_layers.h/weights.h/input.h/expected.h  (generated)
├── python/
│   ├── golden_model.py         generates a NETWORK (list of layers), chained
│   └── export_sw_headers.py    exports the layer descriptor table + blobs
└── vivado/
    └── create_bd.tcl           PS <-> conv_engine only - no AXI DMA IP needed
```

## Why this is a bigger change than it looks

Every layer's input and output feature map now lives in DDR, not a live
AXI4-Stream from a producer — because the engine gets reconfigured *between*
layers, it can't stay "in the middle of a stream." Even the very first
layer's camera frame has to land in a DDR buffer (via the existing V4L2/DMA
capture path) before this engine reads it the same way it reads any other
layer's input. One genuine upside: since every port is now `m_axi` (DDR)
instead of `AXI4-Stream`, **no AXI DMA IP exists in this design at all** —
compare `vivado/create_bd.tcl` here to `conv_layer1/vivado/create_bd.tcl`.

## AMBA Interface Map

`conv_engine.cpp`'s `INTERFACE` pragmas (and several comments elsewhere in
this fork - `conv_engine.h`'s doc comment on `weights_hi`, the `TRIED AND
REJECTED` DATAFLOW note in `conv_engine.cpp`) point here for the full port
list. Five physical interfaces total: one AXI4-Lite control bundle and four
AXI4 (`m_axi`) master ports.

| Bundle | Protocol | Ports | Direction | Vivado wiring (`vivado/create_bd.tcl`) |
|---|---|---|---|---|
| `CTRL` | AXI4-Lite (`s_axilite`) | all geometry scalars (`img_h`/`img_w`/.../`leaky_relu_enable`) + all five DDR base-address registers below + `ap_start`/`ap_done`/`ap_idle`/`ap_ready` | in/out | PS `M_AXI_HPM0_FPD` |
| `RD_BUS` | AXI4 (`m_axi`) | `ifmap`, `weights`, `bias` | read | PS `S_AXI_HP0_FPD` |
| `RD_BUS2` | AXI4 (`m_axi`) | `weights_hi` | read | PS `S_AXI_HP1_FPD` |
| `WR_BUS` | AXI4 (`m_axi`) | `ofmap` (write), `accum` (read **and** write - see `conv_engine.h`'s note on it) | read/write | PS `S_AXI_HP0_FPD` (shared with `RD_BUS`) |

`RD_BUS2`/`weights_hi` is the odd one out and worth explaining on its own:
it is **not** a distinct DDR buffer software allocates - it's a second
physical AXI4 master port that reads the exact same DRAM region as
`weights` on `RD_BUS`. It exists purely so `LOAD_W_IC`
(`load_weight_tile()`'s innermost loop) can issue two reads of `weights[]`
in the same cycle (one per physical port) instead of serializing them -
without it, that loop measured `achieved II=2` against a `target II=1`
(`TROUBLESHOOTING.md` §16). Software never sees a separate `weights_hi`
argument: `SW/conv_engine_hw_driver.h`'s `conv_engine_set_addrs()` takes
the usual five pointers (`ifmap`/`weights`/`bias`/`ofmap`/`accum`) and
internally programs `weights`'s address into *both* `RD_BUS`'s and
`RD_BUS2`'s base-address registers, so there is no caller-facing way to
(accidentally) point the two ports at different data.

`RD_BUS2` is wired to a separate HP port (`S_AXI_HP1_FPD`, not `S_AXI_HP0_FPD`)
specifically so the two reads have independent paths into the PS's memory
interconnect, not just independent HLS-side bundles that still contend for
one HP port downstream.

`RD_BUS`/`WR_BUS` being shared bundles is why weight-tile double buffering
(`#pragma HLS DATAFLOW` around `load_weight_tile()`/`scan_and_compute()`
running concurrently) is not implemented - Vitis HLS requires each `m_axi`
bundle be read by only one process inside a `DATAFLOW` region, and
`ifmap`/`weights`/`bias` sharing `RD_BUS` while being read by two different
(would-be-concurrent) functions fails that check outright. See
`TROUBLESHOOTING.md` §14 for the real error and what a from-scratch fix
would need (splitting `ifmap` onto its own bundle too, a further physical
port - not attempted).

## Design decisions and their trade-offs

See **`../RESOURCE_BUDGET.md`** for the numbers behind `PE_OC`/`TR` — they're
now sized backward from the real XCK26 DSP budget (1,248 slices) and the 30
FPS target, not picked as an arbitrary "safe" small number. That document
also contains an honest, load-bearing finding: at the current parameters,
back-of-envelope math suggests this design may still fall short of 30 FPS on
a full-scale reference network. Read it before assuming these numbers are
"done."

| Decision | What it means | Trade-off |
|---|---|---|
| Output channels are **tiled** (`PE_OC=24` computed in parallel per pass, `HW/conv_engine.h`) | The image is re-scanned from DDR once per `ceil(out_ch/PE_OC)` tile | More DDR bandwidth per layer than a single-pass design, in exchange for bounded on-chip area regardless of `out_ch` |
| Input channels **are now tiled** (`IC_TILE`, nested inside `OC_TILE`) — `window`/`line_buf`/`wtile_packed` still hold only `MAX_IN_CH`=128 channels at once, but a layer's real `in_ch` can go up to `MAX_TOTAL_IN_CH`=1024 | The image is now re-scanned once per `(oc_tile, ic_tile)` pair instead of once per `oc_tile` — see the provenance note at the top of this file for the full design (the new `accum` DDR scratch buffer, why `oc_tile` stays the outer loop, etc.) | More DDR bandwidth again, on top of the oc-tile re-scan cost already below — for a layer needing both (e.g. the real network's layer 13, 8 ic_tiles × 11 oc_tiles at `PE_OC=24` = 88 passes over the image) — cosim (2026-07-24) confirmed `config-A-cosim` (single ic_tile/oc_tile) bit-exact against RTL; the 88-pass worst-case layer itself is still not separately profiled for DDR bandwidth |
| MAC reduction **is** unrolled (`UNROLL factor=TR=16` on the input-channel loop, `PIPELINE II=1` on the K×K loop inside it) | `PE_OC × TR` = 384 DSPs total (~30.8% of the 1,248-slice budget) | 96x more parallel than an earlier, unbudgeted draft of this design that used no reduction unroll at all (~4 DSPs) — that draft was roughly 100x too slow for the 30 FPS target, not merely "conservative." See `RESOURCE_BUDGET.md` §2-3/§11 for the latest throughput accounting |
| `stride` accepted as a parameter but **only stride=1 implemented**, enforced by a simulation-only `assert()` | Matches YOLOv2-tiny's conv layers (all stride 1; downsampling is a separate max-pool op) | Max-pooling is explicitly out of scope for this engine — it's a different, much simpler operation (windowed max, no weights) that would need its own small IP if/when the network needs it |
| NHWC layout kept (same as `conv_layer1`) despite oc-tiling causing strided (non-burst-contiguous) output writes | Simpler, compatible with the existing convention | Burst efficiency on `ofmap` writes is not great when `num_oc_tiles > 1` — a known, deferred profiling target, not something hand-optimized away here |
| `load_weight_tile()`/`scan_and_compute()` split into separate, forced-`INLINE` functions | Sets up a clean seam for weight-tile double buffering later (`#pragma HLS DATAFLOW` + ping-pong buffers) without restructuring the algorithm | Double buffering itself is deliberately **not** implemented yet — Vitis HLS's DATAFLOW scheduling has real, tool-specific failure modes only checkable against an actual schedule report; attempting it blind risks code that looks like double buffering but doesn't behave like it |
| Simulation-only bounds `assert()`s on every runtime parameter (`img_h`, `in_ch`, `k`, `stride`, ...) | Misconfiguration from software fails loudly in C-sim instead of silently indexing out of bounds | Compiles out entirely in synthesis (`__SYNTHESIS__` guard) — zero hardware cost, but also zero protection once running on the board; SW must still not misconfigure it |

The numeric choices above ARE now validated against a real synthesis
report (2026-07-24, `PE_OC=24`/`TR=16`): LUT 77,252 (65%), DSP 219 (17%),
FF 34,073 (14%), BRAM 136 (47%) — see `RESOURCE_BUDGET.md` §11's
confirmation note for the full csynth/cosim numbers. LUT is the tightest
resource at 65%; the 30 FPS throughput question §2-3 raised is still not
separately re-measured against these final numbers.

## What's still a placeholder pending Phase 0

`python/golden_model.py`'s `NETWORK` list is a 3-layer stand-in, **not** the
real Phase 1 traffic-sign network — it exists to exercise the multi-layer
chaining machinery (this script, `export_sw_headers.py`, `network_run.c`)
now, without waiting on the class-scope/anchor-box decision
`doc/planning_기획서.md` §6.2 defers to Phase 0. Once that's decided, replace
`NETWORK` with the real layer list and re-derive `MAX_IN_CH`/`MAX_OUT_CH` in
`conv_engine.h` from it — nothing else in this module depends on the
specific placeholder numbers.

## Verification plan — what's covered, what isn't, and why

**Covered by `conv_engine_tb.cpp` (runs today, in any C++ compiler, no Vitis
needed to at least sanity-check the reference math):**

| Config | What it exercises |
|---|---|
| A | Baseline, `out_ch == PE_OC` (24) exactly (one full tile) |
| B | `out_ch=30`, not a multiple of `PE_OC=24` — the OC_TILE loop actually running more than once, ending on a partial tile |
| C | `k=1` (1×1 conv, `pad=0`), linear (no LeakyReLU) activation — the detection-head layer shape; catches off-by-one bugs in the `k-1`/`k-2` window-fill logic that `k=3`-only tests can't reach, and the "skip LeakyReLU" branch no other config exercises |
| D | `in_ch=1`, `out_ch=1` — degenerate case for both the `TR`-wide reduction unroll and the `PE_OC`-wide channel tiling |
| E | `in_ch == MAX_IN_CH` (128) exactly — single `ic_tile`, and a multiple of `TR` (no remainder) |
| F | `in_ch=20`, not a multiple of `TR=16` — the reduction unroll's automatic remainder handling on a runtime-bounded trip count |
| G | Non-square image (`img_h != img_w`) |
| H | `out_ch=17` straddles a PE_PAIR boundary after a preceding full tile (INT8 DSP-packing edge case) |
| I | `in_ch=129=MAX_IN_CH+1` — smallest case forcing 2 `ic_tiles` (128 full + 1 remainder); first config to exercise `accum`'s DDR read-modify-write path at all |
| J | `in_ch=256=2×MAX_IN_CH` — exactly 2 full `ic_tiles`, no remainder (paired with I the way E/F pair for the `TR` axis) |
| K | `in_ch=150` (2 `ic_tiles`) **and** `out_ch=25` (2 `oc_tiles`) at once — the real network's layer-13 shape, scaled down; the only config that can catch a bug in `accum` being reused correctly across `oc_tiles` |

**Deliberately not automated** (see the comment block at the end of
`conv_engine_tb.cpp`): `stride != 1` and `in_ch > MAX_TOTAL_IN_CH` are
guarded by `assert()` and are expected to abort the program — checked
manually, not folded into the pass/fail sequence above, since a failing
assert would stop every later config in the same run. Note `in_ch >
MAX_IN_CH` alone is no longer this case — input-channel tiling (configs
I/J/K) handles that correctly now.

**Not verifiable without the real tool, regardless of how much test code
exists:**
- Whether `PIPELINE II=1` actually achieves II=1 on the MAC reduction, or
  Vitis HLS schedules it differently (a synthesis-report question, not a
  C-sim question — C-sim proves functional correctness, not timing).
- Real DSP/BRAM/LUT/FF counts for `PE_OC=16, TR=16` against
  `RESOURCE_BUDGET.md`'s estimate.
- Whether `apply_bd_automation` in `vivado/create_bd.tcl` actually resolves
  as written (same caveat as `conv_layer1`'s script — untested against a
  live Vivado instance).
- Anything about real achieved FPS, which needs a real cosim trace or board
  measurement, not an estimate (`RESOURCE_BUDGET.md` §2's honest gap).

## Running it headlessly (no GUI needed)

`run_hls.tcl` drives Vitis HLS's own Tcl API in batch mode — the same
headless-automation idea `mnist_fpga_ver11.0.0/run_regression.bat` uses for
the RTL sim tools, just for `vitis_hls` instead of `xvlog`/`xelab`/`xsim`.
Three ways to run it, pick whichever matches your setup:

**Windows, `run_hls.bat`** (mirrors `run_regression.bat`'s structure —
auto-detects `vitis_hls`, falling back to searching `C:\Xilinx\Vitis\<ver>\`
if it's not already on `PATH`, e.g. if this isn't run from a "Vitis HLS
Command Prompt" shortcut):
```
run_hls.bat            :: C-sim + C-synthesis
run_hls.bat cosim       :: also runs co-simulation (slower)
```

**Linux/WSL/Git Bash, `run_hls.sh`** (mirrors `run_regression.sh`):
```
source /tools/Xilinx/Vitis/2024.2/settings64.sh   # or wherever it's installed
bash run_hls.sh            # C-sim + C-synthesis
bash run_hls.sh --cosim    # also runs co-simulation (slower)
```

**Either OS, directly**, if you already have a shell with `vitis_hls` on
`PATH` (e.g. the Vitis HLS Command Prompt shortcut) and don't need the
PASS/FAIL log parsing:
```
vitis_hls -f run_hls.tcl
vitis_hls -f run_hls.tcl --cosim
```

Targets **Vitis HLS 2024.2**, matching `doc/planning_기획서.md` §12.1's
toolchain choice. `xck26-sfvc784-2LV-c` (the part string) is confirmed to
resolve correctly via `set_part` — verified during early bring-up on Vitis
HLS 2021.1 before switching to 2024.2. `run_hls.bat`'s `findstr` patterns
and `run_hls.sh`'s `grep` patterns for "synthesis completed"/"cosim passed"
are still best-effort — written without a log from a run that actually
reached completion to check exact wording against (early runs hung on a
license issue before getting that far) — if either script reports FAIL but
`conv_engine_prj\solution1\`'s own reports look clean, the pattern is
probably what's wrong, not the run.

## Next steps

1. ~~Run `run_hls.sh`/`run_hls.bat` — expect all configs A-G to print PASS,
   then "ALL CONFIGS PASS".~~ **Done (2026-07-24).** All configs A-K plus
   all 13 real YOLOv3-tiny-ADAS layers passed bit-exact.
2. ~~C Synthesis: check the actual DSP/BRAM numbers against
   `RESOURCE_BUDGET.md`'s estimate.~~ **Done (2026-07-24).** LUT 77,252
   (65%), DSP 219 (17%), FF 34,073 (14%), BRAM 136 (47%) at the current
   `PE_OC=24`/`TR=16` — see `RESOURCE_BUDGET.md` §11. The 30 FPS
   throughput question itself is still not separately re-measured against
   these final numbers.
3. ~~Co-simulation~~ **Done (2026-07-24)** — `config-A-cosim` PASS,
   bit-exact against RTL (`run_hls.bat cosim`). ~~Package IP~~ **Done
   (2026-07-29)** — `run_hls.tcl`/`run_hls.bat`/`run_hls.sh` gained a
   `package`/`--package`/`RUN_HLS_PACKAGE=1` mode this session (mirrors
   `pool_upsample_route/run_hls.bat`'s) and `run_hls.bat package` produced
   a real `conv_engine_prj/solution1/impl/ip/` (`ip_catalog` format,
   `component.xml` + `drivers/conv_engine_v1_0/`) - the format Vivado's IP
   catalog / `create_bd.tcl`'s `ip_repo_paths` actually needs, which this
   project never had before (the older `impl/misc`/`impl/verilog`/
   `impl/vhdl` export predating the `_requant` fork was RTL-only, no
   `component.xml`). Diffed against `SW/conv_engine_hw_driver.h`'s
   existing REG_* offsets: byte-for-byte identical, including every
   requant-fork register - see that file's own header comment. Next:
   `vivado/create_bd.tcl` to confirm PS integration (still an unverified
   draft against a live Vivado session).
4. Once real hardware bring-up (`SW/network_run.c`) passes on the 3-layer
   placeholder network, swap in the real Phase 1 layer list once Phase 0
   finalizes it, and recompute `RESOURCE_BUDGET.md` §2 against the real MAC
   count instead of the literature placeholder.
5. Provenance item 4 above (MaxPool/Upsample/Route/concat units) is no
   longer unstarted: `hls/pool_upsample_route/` implements all 3 as
   separate HLS IPs, csim+csynth+cosim confirmed bit-exact (2026-07-29,
   see that project's own README.md). `SW/network_run_full.c` (this
   folder, new) sequences the real 24-layer network end to end across all
   4 IPs (22 hardware ops - layers 16/23 are SW-only yolo decode, not run
   there), verifying every intermediate buffer against the golden model,
   not just the final output. It cannot run on real hardware yet: it
   depends on `pool_upsample_route/SW/*_hw_driver.h`'s register offsets
   (unfilled placeholders pending that project's own Package IP run - see
   its "Next steps" item 3) and on both projects' `vivado/create_bd.tcl`
   bring-up designs actually being built in Vivado (bitstream + XSA, not
   yet done for either project - Package IP itself hasn't been run for
   `conv_engine_requant` either, see item 3 above). `network_run.c` (this
   folder) is left as-is, still useful on its own as the conv-only,
   isolated-per-layer check it always was.
