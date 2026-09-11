# pool_upsample_route — MaxPool / Upsample / Route(concat) HLS module

## This folder's provenance and scope

`pool_upsample_route/` is a new sibling project (not a copy) of
`hls/conv_engine_requant/`, created specifically to fill the gap that
project's `README.md` item 4 flagged: `conv_engine` only ever implements
Conv, but the real YOLOv3-tiny-ADAS network
(`python_teammate/darknet_golden/`) also needs MaxPool (5 layers), Upsample
(1 layer), and Route/concat with per-source requantization (2 layers)
between conv layers. Without these, the 24-layer network cannot run
end-to-end even though all 13 real conv layers are now csim+csynth+cosim
confirmed in `conv_engine_requant`.

Implemented as **3 separate, independent HLS IPs** (`maxpool_engine`,
`upsample_engine`, `route_concat_engine`) — matching
`python_teammate/darknet_golden/RTL_HANDOFF_KO.md`'s own recommended
architecture ("one reusable Conv engine + separate small pooling/upsample/
route units + a layer sequencer"), not folded into `conv_engine` itself.

Spec source of truth: `RTL_HANDOFF_KO.md` sections 6-7. Summary:
- **MaxPool**: 2x2, stride 2 (5 layers) or stride 1 with right/bottom
  padding using INT8 `-128` (layer 11 only, since it's already at the
  network's smallest spatial size). Preserves input scale — no requant math.
- **Upsample**: nearest-neighbor, fixed 2x (layer 19 only). Preserves
  scale — no requant math.
- **Route**: layer 17 = single-source passthrough (layer 13). Layer 20 =
  2-source concat `[layer19, layer8]` (128ch then 256ch → 384ch), each
  source **independently requantized** via its own `source_requantization`
  multiplier/shift (`model_manifest.json`) before concatenation.

**Known gap**: `model_manifest.json`'s `maxpool`/`upsample` layer entries
carry only `{index, type, output_scale, output_bits}` — no pool size/
stride/scale-factor field. Those are hardcoded per `RTL_HANDOFF_KO.md`
section 7's prose table (`maxpool_engine.h`'s header comment, and
`python/real_pool_upsample_route_layers.py`'s `MAXPOOL_STRIDE_PAD`/
`UPSAMPLE_INDICES` tables), not read from any JSON field. Route's
`sources`/`source_requantization` fields ARE present in the manifest and
are read from there.

## Scope of this pass

**Done, verified via g++ (no Vitis HLS needed for this):**
- 3 HLS engines (`HW/maxpool_engine.{h,cpp}`, `HW/upsample_engine.{h,cpp}`,
  `HW/route_concat_engine.{h,cpp}`) — synthesizable Vitis HLS C++.
- `HW/pool_upsample_route_tb.cpp` — 20 synthetic edge-case configs (8
  MaxPool, 5 Upsample, 7 Route) with independent reference implementations,
  plus a real-layer suite.
- `python/real_pool_upsample_route_layers.py` — extracts all 9 real
  maxpool/upsample/route layers (manifest indices 1,3,5,7,9,11,17,19,20)
  from `python_teammate/darknet_golden/artifacts/`, independently verifies
  each in numpy against the real golden-model dump (bit-exact), and
  generates `HW/real_pool_upsample_route_data.h`.
- **Verification result**: all 20 synthetic configs + all 9 real-layer
  configs `PASS` (`ALL CONFIGS PASS`), confirmed via:
  ```bash
  g++ -std=c++11 -O2 -I /mnt/c/Xilinx/Vitis/2024.2/include \
      HW/maxpool_engine.cpp HW/upsample_engine.cpp HW/route_concat_engine.cpp \
      HW/pool_upsample_route_tb.cpp -o pool_upsample_route_tb
  ./pool_upsample_route_tb
  ```
  This is C-sim-level correctness only (Vitis's own standalone `ap_int.h`,
  no Vitis HLS tool invoked) — **not yet a real csim/csynth/cosim run**.

**Handed off, NOT run by me (needs a Windows Vitis HLS install):**
- `run_hls.bat` / `run_hls.sh` / `run_hls.tcl` — one Vitis HLS project
  (`pool_upsample_route_prj`), 3 solutions (`solution_maxpool`,
  `solution_upsample`, `solution_route_concat`), one per engine. Same
  `RUN_HLS_COSIM` env-var convention as `conv_engine_requant/run_hls.bat`
  (not a CLI arg — see that project's own header comment for why). Usage:
  ```
  run_hls.bat            REM C-sim + C-synthesis only, all 3 engines
  run_hls.bat cosim       REM also runs co-simulation for all 3 (slow)
  ```
  A failure isolated to one engine does not block the other two — each
  solution's csim/csynth/cosim runs independently (`run_hls.tcl`'s `catch`
  blocks), and the wrapper scripts report a per-engine breakdown.

**Explicitly deferred (separate follow-up, not this pass):**
- `SW/` driver headers — need a real generated `x<ip>_hw.h` from an actual
  csynth+Package IP run first. `conv_engine_requant` already shipped one
  hand-guessed register map once and had to fix it from the real generated
  header (see that project's `SW/conv_engine_hw_driver.h` header comment) —
  not repeating that here.
- `vivado/create_bd.tcl` PS integration — needs real m_axi master-port
  counts from synthesis first, plus an open question on HP-port allocation
  (`conv_engine` already claims HP0/HP1; these 3 new IPs add up to 6 more
  masters — see the design notes in `HW/route_concat_engine.h`/
  `maxpool_engine.h` on bundle sharing).
- `conv_engine_requant/SW/network_run.c` / `layer_cfg_t` /
  `export_sw_headers.py` integration to actually sequence all 24 real
  layers together end-to-end (`conv_engine_requant/README.md` item 5,
  separate follow-up).

## Folder structure

```
pool_upsample_route/
├── HW/
│   ├── maxpool_engine.h/.cpp        2x2 stride-2 or stride-1(+pad) maxpool
│   ├── upsample_engine.h/.cpp       nearest-neighbor 2x upsample
│   ├── route_concat_engine.h/.cpp   1-2 source route/concat + per-source requant
│   ├── pool_upsample_route_tb.cpp   shared C-sim testbench, all 3 engines
│   └── real_pool_upsample_route_data.h   (generated, see python/)
├── python/
│   └── real_pool_upsample_route_layers.py   extracts + verifies real layer data
├── run_hls.bat / run_hls.sh / run_hls.tcl
└── README.md   (this file)
```

## Next steps

1. ~~Run `run_hls.bat` / `run_hls.sh` on a machine with Vitis HLS 2024.2~~
   **Done** — all 3 solutions' real C-sim confirmed `ALL CONFIGS PASS`,
   matching the g++ result above; `*_csynth.rpt` LUT/DSP/BRAM/FF numbers
   generated (these ops have no MAC-style parallelism knob, so no
   `RESOURCE_BUDGET.md`-style tuning was expected to be needed — still
   worth a numbers check, not covered by this pass).
2. ~~`run_hls.bat cosim`~~ **Done** — all 3 engines' RTL simulation
   confirmed bit-exact against C-sim (`COSIM 212-1000 *** C/RTL
   co-simulation finished: PASS ***` for maxpool, upsample, and
   route_concat).

   **Cycle counts (2026-08-04 re-run — the 2026-07-29 pass above never
   captured these, since `open_project -reset` in `run_hls.tcl` wipes
   `sim/report/` on the next non-cosim run):**
   `doc/plan_no_board_verification_and_perf.md` P1 needed real per-engine
   cycle counts, which were absent from every FPS projection until now.

   | Engine | Real layer (manifest idx) | Shape | Cycles | @ 100 MHz |
   |---|---|---|---|---|
   | `maxpool_engine` | 11 (smallest of 6 maxpools; stride1+pad) | 9×16×512 → 9×16×512 | 454,218 | 4.54 ms |
   | `upsample_engine` | 19 (only upsample in the network) | 9×16×128 → 18×32×128 | 100,983 | 1.01 ms |
   | `route_concat_engine` | 20 (larger of 2 routes, 2-source) | 18×32, 128+256→384 ch | 269,706 | 2.70 ms |

   `upsample_engine` runs exactly once in the real network, so its number is
   the complete per-frame contribution. `maxpool_engine` runs 6 times (only
   the smallest, idx 11, was measured — the other 5 have strictly larger
   input sizes: 2,359,296/1,179,648/589,824/294,912/147,456 vs. idx 11's
   73,728, halving each stage) and `route_concat_engine` runs twice (idx 17,
   a cheaper single-source passthrough, wasn't measured) — so the maxpool and
   route rows above are floors on those engines' total contribution, not
   the total. See `doc/plan_no_board_verification_and_perf.md` §2.1 for how
   this folds into the whole-network FPS picture alongside conv's own
   real-layer cosim numbers.

   Note: the first `run_hls.bat cosim` attempt reported a false `FAIL`
   (`6/3` engines) and then a batch parse error
   (`3 was unexpected at this time.`) on a second run — both were bugs in
   `run_hls.bat`'s own PASS/FAIL counting, not the HLS run itself: the
   `findstr` pattern for `ALL CONFIGS PASS` also matched `run_hls.tcl`'s
   own announcement line containing that substring (doubling the count),
   and `%COSIM_COUNT%` was read via percent-expansion inside the same
   parenthesized `if` block that sets it, which under
   `enabledelayedexpansion` resolves at parse time (before the `set` runs)
   instead of current value — fixed to `findstr /B` (anchor to line start)
   and `!COSIM_COUNT!` (delayed expansion) respectively; both
   `run_hls.bat`/`run_hls.sh` are fixed now.
3. ~~`SW/*_hw_driver.h`~~ **Done (2026-07-29)** - `run_hls.bat package` /
   `bash run_hls.sh --package` (added this session) ran for real
   (`export_design` per solution, to
   `pool_upsample_route_prj/solution_<name>/impl/ip`), and every REG_*
   offset in `SW/maxpool_engine_hw_driver.h`/`upsample_engine_hw_driver.h`/
   `route_concat_engine_hw_driver.h` is now copied from the real generated
   `x<ip>_hw.h` per engine, not guessed. Worth noting: `maxpool`/`upsample`'s
   offsets happened to exactly match this file's original hand-guessed
   placeholders, but `route_concat`'s did NOT - every offset from `img_h`
   onward was off by +0x04 (a forgotten reserved-register gap after the
   3rd pointer pair), caught only because those placeholders sat behind an
   `#error` until checked against the real header - see that file's own
   header comment for the exact before/after numbers. Same lesson
   `conv_engine_requant/SW/conv_engine_hw_driver.h` already learned once,
   now repeated and caught here too.

   `vivado/create_bd.tcl` (new) is written against those same real
   `impl/ip` export paths - the HP-port allocation question is resolved
   (all 6 new masters onto HP0 alongside conv_engine's, reasoning in the
   script - the layer-sequencer architecture never runs 2 engines
   concurrently, so there's no real contention to spread across more
   ports), but the script itself is still an unverified draft until a live
   Vivado session can source it (Package IP existing is a prerequisite for
   that, not the same thing as having run it).
4. `conv_engine_requant/SW/network_run_full.c` (new, separate file -
   `network_run.c` itself is untouched) sequences the real 24-layer network
   end-to-end across all 4 IPs (22 hardware ops; layers 16/23 are SW-only
   yolo decode, out of scope there too) - see that file's own header
   comment for the buffer plan and per-op-type verification strategy. Data
   flow/dispatch logic is done; it cannot run for real until item 3's
   driver headers have real offsets and both projects' Vivado bring-ups
   produce an actual bitstream/XSA - see `conv_engine_requant/README.md`
   item 5.
