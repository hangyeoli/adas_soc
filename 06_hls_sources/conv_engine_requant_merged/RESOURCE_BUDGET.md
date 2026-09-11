# conv_engine resource budget

This is the calculation that should exist *before* picking `PE_OC`/`TR` in
`HW/conv_engine.h`, not after. The previous revision picked `PE_OC=4` with no
reduction-level parallelism as an arbitrary "safe, conservative" starting
number — that was a mistake, not a hedge: checked against the real target
(30 FPS, §3.3 of `doc/planning_기획서.md`), it was roughly **100x too slow**.
A resource budget exists specifically to catch this kind of error before it's
buried in RTL. This document is not exhaustive engineering — it's the
back-of-envelope pass a real engineer does first, to know whether the design
direction is even in the right ballpark before spending synthesis cycles on
it.

## 1. What the chip actually has

Source: AMD Kria K26 SOM Data Sheet (DS987) — the XCK26 device
(XCK26-SFVC784-2LV) on the K26 SOM used by SK-KR260-G.

| Resource | Total on XCK26 |
|---|---|
| DSP slices | 1,248 |
| CLB LUTs | 117,120 |
| CLB flip-flops | 234,240 |
| Block RAM (BRAM36-equivalent) | 144 blocks / 5.1 Mb |
| UltraRAM | 64 blocks |

These are **whole-chip** numbers. `conv_engine` has to share this budget with
everything else in the design — AXI interconnect fabric, the PS-side
peripherals' PL-side logic (if any), and whatever RPU/IPI-related PL logic
Phase 2 eventually adds (`doc/planning_기획서.md` §7). None of that has been
sized yet, so treating 100% of any resource as "available to conv_engine" is
already wrong before considering timing closure. Real designs also lose
achievable frequency (and sometimes fail to route at all) well before 100%
utilization of any single resource — DSPs are the classic example, since
they're arranged in fixed columns on the die and congestion around them gets
worse than the percentage number suggests, but §4 below found LUTs to be the
actual pressure point for *this* design, not DSPs. **A conservative rule of
thumb: don't plan past ~60-70% of any single resource for one IP in a first
design iteration** — current LUT utilization (92%, §4) is already well past
that line with no other PL logic accounted for yet.

## 2. Sizing backwards from the FPS target, not forwards from "safe"

`doc/planning_기획서.md` §3.3 sets the Phase 1 gate at **30 FPS or better**,
measured with a real camera. Working backward from that:

- 30 FPS → **33.3 ms/frame** total budget (for the whole pipeline; assume
  convolution compute dominates, which is typical).
- Assume a **200 MHz** PL clock — a safe, commonly-achievable target for a
  first Vitis HLS design on this device class (250-300 MHz is often reachable
  with more timing-closure effort, but isn't assumed here). → **6.68M cycles
  per frame**.

### How many MACs does one frame actually need?

This is the number that's genuinely unknown right now, because Phase 0 (the
class-scope / anchor-box decision, `doc/planning_기획서.md` §6.2) hasn't
happened yet. The reference point available today is literature: the
standard 20-class YOLOv2-tiny at 416×416 is commonly cited around **~3.5
GFLOPs (~1.75 GMACs)** per frame. Phase 1's actual network is very likely
*smaller* than this — the plan explicitly scopes Phase 1 down to "표지판이다/
아니다" or a 3-category detector (§6.2), and calls the resulting accelerator
structure simpler as a direct consequence. **Treat 1.75 GMACs as a
conservative upper bound for sizing, not a confirmed number** — replace it
once Phase 0's actual layer list exists.

### Required throughput

```
1.75e9 MACs / 6.68e6 cycles ≈ 262 MACs/cycle, at 100% engine utilization
```

100% utilization never happens: `conv_engine`'s oc-tile re-scan strategy
(re-reading `ifmap` from DDR once per output-channel tile, `HW/conv_engine.cpp`
`OC_TILE` loop) means the accelerator spends real cycles on weight-tile
reload and pipeline fill/drain that don't produce a MAC each cycle. Without a
real cosimulation trace this efficiency number cannot be pinned down — a
placeholder **derating factor of 2-5x** is used below as a plausible range,
not a measured one.

| Assumed engine efficiency | Raw parallel MACs needed |
|---|---|
| 50% (optimistic) | ~524 |
| 33% (moderate) | ~786 |
| 20% (pessimistic, first cut) | ~1,310 |

## 3. What this means for `PE_OC` / `TR`

`conv_engine.cpp` gets `PE_OC × TR` raw parallel INT8 multiplies (`PE_OC`
output channels in parallel, `TR` reduction terms unrolled per channel) —
assume **1 DSP per INT8 multiply** (Vitis HLS does not automatically pack two
INT8 multiplies into one DSP48E2 without deliberate, hand-written packing
logic that this design does not attempt — see §5, "not done here").

**Update (2026-07-23, post-packing): `PE_OC=20`, `TR=16` → 320 raw MACs,
confirmed by real synthesis + cosim** — see the new bullet in §5,
"Raising `PE_OC` after packing", for the full before/after numbers
(`PE_OC=24` was tried first and overshot LUT to 103%; `PE_OC=20` fits at
89% and passed cosim bit-exact — actual passing `cosim_design` run,
2026-07-23 15:07 KST, `conv_engine_prj/solution1/sim/report/conv_engine_cosim.rpt`,
Verilog RTL: Pass, 185,798 clock cycles; earlier cosim attempts, run through
the separate Unified-IDE component project instead of `run_hls.tcl`, hit the
SIGSEGV documented in `TROUBLESHOOTING.md` §11 and never completed — this is
the first run that actually did). Everything below this point was written
against the original `PE_OC=16` choice and is kept as-is for the historical
reasoning trail - the LUT-vs-DSP conclusion (LUT is the binding constraint,
not DSP) still holds and is exactly what determined how far `PE_OC` could
go.

Original choice: **`PE_OC=16`, `TR=16` → 256 DSPs (≈20.5% of 1,248)**.

This is a deliberate middle position, not a computed answer to "will this hit
30 FPS":

- It is **64x more parallel** than the previous `PE_OC=4`/no-reduction-unroll
  design (4 DSPs) — that number was simply wrong for the stated requirement,
  not just cautious.
- Against the required-throughput table above, 256 raw MACs/cycle is **short
  of even the optimistic 524-MAC estimate** — meaning, on the current
  (unconfirmed) 1.75 GMAC/frame assumption, this design likely does **not**
  reach 30 FPS yet. That's an honest, load-bearing finding, not a hedge:
  either (a) Phase 1's real network turns out to need meaningfully fewer than
  1.75 GMACs (plausible, per §6.2's reduced scope), (b) `PE_OC`/`TR` need to
  go higher once real numbers exist, or (c) both.
- It leaves **3-4x DSP headroom** (1,248 vs. 256) to scale up once real
  synthesis timing and the actual Phase 0 network size are known, without
  redesigning the tiling structure — `PE_OC` and `TR` are the two knobs to
  raise. **Caveat added after real synthesis (§4): DSP headroom is not the
  binding constraint on raising `PE_OC`/`TR` anymore.** LUT utilization at the
  *current* `PE_OC=16`/`TR=16` is already 92% (108,294 / 117,120) — every
  additional PE lane or reduction term adds more `wtile`/`window` partition
  instances (and their per-instance port-arbitration overhead, per §4) on top
  of an already-tight LUT budget. Raising these knobs to chase 30 FPS will
  very likely hit the LUT ceiling before the DSP one; re-check §4's LUT
  accounting, not just this section's DSP count, before raising either.

**Do not treat 30 FPS as assured by this design.** This section exists so
that risk is visible now, in a document, instead of being discovered after
a full board bring-up.

## 4. Other resources at this parallelism

**Corrected twice now, both times only after actually running synthesis —
not by inspection.** First correction (Vitis HLS 2021.1 run, see
conv_engine.cpp's "FIX (found from a real Vitis HLS 2021.1 run)" comments):
the original table below assumed `window`/`line_buf`/`px` would be accessed
through fully unrolled, compile-time-constant indices, so `complete`
partitioning was "free." That was wrong — `in_ch` is a runtime parameter,
and Vitis HLS's synthesis log said so directly: *"Cannot unroll loop
'SHIFT_WINDOW' ... cannot completely unroll a loop with a variable trip
count"*, followed by *"Completely partitioning array 'window.V' accessed
through non-constant indices ... may result in long runtime and suboptimal
QoR due to large multiplexers."* All affected arrays became `cyclic(TR)`
partitioned on the `in_ch` dimension, not `complete`.

**Second correction (2024.2 run, first C synthesis to actually complete):**
the table below *still* had `window` and `wtile` `complete`-partitioned on
their `ky`/`kx` (K,K) dimensions, on the same "will be accessed through a
compile-time-constant index" assumption - except no loop touching either
array's K,K dimension (`load_weight_tile`'s or `SHIFT_WINDOW`'s `ky`/`kx`
loops, or the read side's `MAC_KY`/`MAC_KX`) was ever `UNROLL`ed; all of
them are plain `PIPELINE II=1` loops. So that partitioning bought no
parallelism at all, while multiplying `window`'s instance count 9x (16 ->
144) and `wtile`'s 9x (256 -> 2,304). The 2024.2 csynth report's
Multiplexer detail table showed the cost directly: 17,713 LUT for window's
144 instances and 60,264 LUT for wtile's 2,304 (each instance paying a
fixed ~27 LUT of address/ce/we port-arbitration overhead to share itself
between its one writer and one reader) - 78,000 of the design's 182,022
total LUTs, on a device with only 117,120 available (155% utilization,
i.e. this would not have fit). Both arrays' K,K partitioning has been
removed; see the "FIX 2" comment on window's declaration in
conv_engine.cpp.

| Buffer | Size | Partition scheme | Approx. registers/BRAM |
|---|---|---|---|
| `window[MAX_IN_CH][MAX_K][MAX_K]` | 128×3×3 | cyclic(16) on IN_CH only | 16 instances (each internally addressed over K,K) |
| `wtile[PE_OC][MAX_IN_CH][MAX_K][MAX_K]` | 16×128×3×3 | complete on PE_OC, cyclic(16) on IN_CH | 256 instances (each internally addressed over K,K) |
| `line_buf[MAX_IN_CH][MAX_K-1][MAX_IMG_W]` | 128×2×416 | cyclic(16) on IN_CH, complete on K | 32 BRAMs, 416 elements each |
| `px[MAX_IN_CH]` | 128 | cyclic(16) | 16 registers |

`line_buf`'s K (row) dimension is left `complete` and is NOT the same
mistake as window/wtile's K,K removal above: it only doubles the instance
count (32 vs 16), and the 2024.2 report confirmed its actual cost is
negligible (613 LUT total, vs. window/wtile's tens of thousands) - it isn't
worth touching just for symmetry.

**Third correction, and this one changes the document's own conclusion:**
§2-3 above (written before any synthesis ran) assumed DSPs would be the
binding constraint, on the reasoning that DSPs are the scarce, fixed-column
resource and everything else was "not a meaningful fraction of the budget."
The actual post-fix csynth report (after removing the K,K partitioning
above) shows:

| Resource | Used | Available | % |
|---|---|---|---|
| BRAM_18K | 67 | 288 | 23% |
| DSP | 267 | 1,248 | 21% |
| FF | 50,445 | 234,240 | 21% |
| LUT | 108,294 | 117,120 | **92%** |

**LUT, not DSP, is the binding constraint for this design**, and by a wide
margin — at 92% it's already past this document's own "don't plan past
60-70% for one IP" rule (§1), with zero other PL logic (camera-capture DMA,
AXI interconnect, anything Phase 2 adds) accounted for yet. This directly
weakens §3's "leaves 3-4x DSP headroom to scale up `PE_OC`/`TR`" conclusion:
DSP headroom is real, but LUT headroom to support raising those knobs
further is not — see the caveat added to that bullet in §3.

The underlying lesson (why this was missed twice): per-partition
control/port-arbitration LUT cost scales with *instance count*, independent
of how few bits each instance holds — FF/BRAM-only accounting (what this
table originally tracked) cannot see that cost. It has to be checked against
an actual synthesis report's Multiplexer detail table, not estimated from
array sizes alone.

## 5. Explicitly deferred (not because it's hard, but because it's
   unverifiable without synthesis feedback right now)

- **INT8 DSP packing** (2 MACs per DSP48E2 via manual bit-packing) — **done,
  in this folder** (`conv_engine_int8pack/`, an isolated copy of the
  original `hls/conv_engine/`; see `TROUBLESHOOTING.md` §6-9 for the full
  path there, including a real carry-correction bug caught by an exhaustive
  self-test and a BRAM regression traced and fixed via `BIND_STORAGE`).
  Confirmed by re-synthesis, correctness verified bit-exact against 8 C-sim
  configs:

  | Resource | Before packing | After packing (final) |
  |---|---|---|
  | BRAM_18K | 67 (23%) | 67 (23%) |
  | DSP | 267 (21%) | 141 (11%) |
  | FF | 50,445 (21%) | 37,173 (15%) |
  | LUT | 108,294 (92%) | 86,986 (74%) |

  An improvement on every resource axis - LUT down 18 points (the actual
  goal), DSP and FF both roughly halved or better, BRAM unchanged.

  **2:1 is the ceiling for this technique, not a step toward higher ratios.**
  A natural-seeming follow-up (pack 4 weights per DSP instead of 2, given
  the DSP headroom this freed) turns out to be physically infeasible, not
  just harder: the packed operand's minimum width is `16(N-1)+8` bits (`16`
  forced by the 8-bit operand sizes, independent of `N`), which already
  exceeds DSP48E2's 27-bit multiplier input port at **N=3 (41 bits needed)**,
  let alone N=4 (57 bits) - 2-way's 25-bit packed operand fitting with only
  2 bits of margin was already close to this wall, not far from it. There's
  a second, independent failure on the output side too (N=4's product would
  need 65 bits against the DSP's 48-bit accumulator). This isn't a carry-
  logic/correctness problem (the `+1`-if-negative correction from §8 *does*
  generalize cleanly to N fields) - it's pure bit-capacity, and it's fatal
  regardless of how carefully the math is done. Real alternatives for going
  beyond 2:1 INT8-MAC density exist (sub-INT8 precision, Winograd-style
  algorithmic MAC-count reduction) but both are materially different,
  larger undertakings than a wider version of this packing scheme - not
  attempted here.
- **Raising `PE_OC` after packing** — done. With DSP at only 11% and LUT at
  74% post-packing (previous bullet), LUT headroom (not DSP) was the open
  question for how far `PE_OC` could go; `TR` was left at 16 since it must
  stay a power-of-2 divisor of `MAX_IN_CH=128`, so its only next step (32)
  doubles parallelism outright with no intermediate point to check LUT
  scaling against. `PE_OC` has no such constraint (even-only), so it was the
  knob raised, one step at a time, each confirmed by real re-synthesis:

  | `PE_OC` (`TR=16`) | raw MACs | LUT | DSP | FF | Fits XCK26? |
  |---|---|---|---|---|---|
  | 16 (packed baseline) | 256 | 86,986 (74%) | 141 (11%) | 37,173 (15%) | yes |
  | 24 (first try) | 384 | 121,566 (**103%**) | 207 (16%) | 52,265 (22%) | **no** |
  | **20 (shipped)** | 320 | 104,577 (89%) | 175 (14%) | 44,750 (19%) | yes |

  `PE_OC=24` was the natural first guess (1.5x) but overshot the device's
  117,120-LUT budget outright - would not place/route. The two real data
  points (16→86,986; 24→121,566) gave a marginal cost of ≈270 LUT per raw
  MAC of parallelism, extrapolating back to `PE_OC≈20` for an ~85-90% LUT
  target - confirmed almost exactly right by the actual `PE_OC=20`
  synthesis (89%). `PE_OC=20` also passed C-sim (all 8 configs) and
  **co-simulation bit-exact** (config-A-cosim, 4096 output values, RTL vs.
  golden model) - not just a synthesis estimate. Concrete evidence: the
  `cosim_design` run that actually passed is dated 2026-07-23 15:07 KST,
  report at `conv_engine_prj/solution1/sim/report/conv_engine_cosim.rpt`
  (Verilog RTL: Pass, 185,798 clock cycles for the 16×16×3→16×16×16 shape);
  three earlier attempts, run through the separate Unified-IDE component
  project (`conv_engine_prj/conv_engine_prj/`) rather than `run_hls.tcl`,
  all failed with the SIGSEGV in `TROUBLESHOOTING.md` §11 and never reached
  a PASS/FAIL verdict - this section's claim was written aspirationally
  before that gap was noticed and closed.
  Both `PE_OC=24` and `PE_OC=20` (and the original `PE_OC=16`) report
  `Loop Constraint Status: All loop constraints were NOT satisfied` in the
  csynth log - checked against the *original, cosim-confirmed* `PE_OC=16`
  packed baseline's own log and it says the same thing there, so this is a
  pre-existing property of the packed design (likely from the runtime-
  parameterized loop bounds, which Vitis HLS can't fully verify II/latency
  against at compile time), not something `PE_OC=20` introduced.
  Estimated Fmax was identical (273.97 MHz) at `PE_OC=16`, `20`, and `24` -
  the critical path is evidently dominated by something parallelism-
  independent (plausibly the packed-multiply/unpack logic itself).
- **Trying 250 MHz at `PE_OC=20`** — tried, reverted. Raising `CLOCK_NS`
  5.0→4.0 in `run_hls.tcl` (200→250 MHz target) at `PE_OC=20` does **not**
  combine for free with the parallelism increase above - it competes for
  the same LUT budget instead:

  | `CLOCK_NS` | Target | LUT | FF | Estimated Fmax |
  |---|---|---|---|---|
  | 5.0 (shipped) | 200 MHz | 104,577 (89%) | 44,750 (19%) | 273.97 MHz |
  | 4.0 (tried) | 250 MHz | **119,320 (101%)** | **91,990 (39%)** | 342.47 MHz |

  Vitis HLS met the tighter 4ns constraint by scheduling more/deeper
  pipeline (retiming) registers - FF more than doubled - and that extra
  register/control-logic cost pushed LUT over the device's 117,120 budget,
  even though the resulting design's own Fmax estimate (342 MHz) is
  comfortably above the 250 MHz target itself. Back-of-envelope: at the
  ~270-LUT-per-raw-MAC rate from the `PE_OC` experiment above, the ~14,700
  extra LUT this retiming cost is roughly equivalent to giving up ~55 raw
  MACs of parallelism (`PE_OC=20`→`~16`) - and `256 raw MACs × 250 MHz` is
  the *same* 64 GMAC/s peak as `320 raw MACs × 200 MHz`, meaning clock and
  `PE_OC` may be trading against the same LUT budget roughly 1-for-1 here,
  not stacking. Reverted `CLOCK_NS` to 5.0 (200 MHz), keeping the
  cosim-confirmed `PE_OC=20`/200 MHz combination as the shipped config.
  Untried: whether `PE_OC=16` at `CLOCK_NS=4.0` actually fits (would test
  the "roughly 1-for-1 trade" hypothesis directly instead of just inferring
  it), and whether a smaller clock step (e.g. `CLOCK_NS=4.5`, ~222 MHz) at
  `PE_OC=20` finds a combination that fits with headroom to spare instead of
  jumping straight to the 250 MHz extreme.
- **Weight-tile double buffering** (ping-pong `wtile` so the next tile loads
  while the current tile computes — `doc/planning_기획서.md` §9 calls this
  out as intended methodology). `HW/conv_engine.cpp` is structured with
  `load_weight_tile()` and `scan_and_compute()` as separate functions
  specifically so this can be added later by wrapping them in
  `#pragma HLS DATAFLOW` with ping-pong buffers, without restructuring the
  algorithm.

  **Tried 2026-07-23, reverted - real, non-silent failure, not the
  "silently sequential" risk this section originally worried about:**
  moved `wtile_packed`/`btile` from `static` (declared once in
  `conv_engine()`) to non-`static` locals declared inside the `OC_TILE` loop
  body (required for Vitis HLS's automatic ping-pong inference), removed
  `#pragma HLS INLINE` from both functions (DATAFLOW requires separate
  processes), and added `#pragma HLS DATAFLOW` to `OC_TILE`. C-synthesis
  failed outright, before ever reaching the ping-pong question:

  ```
  WARNING: [HLS 214-110] As the loop bound is not a constant or function
  argument, the compiler may not successfully process the dataflow loop
  (num_oc_tiles, a runtime-computed local)
  WARNING: [HLS 200-471] Dataflow form checks found 1 issue(s)
  ERROR: [HLS 200-1013] Bundled bus interface 'RD_BUS' on ports 'ifmap,
  weights, bias' failed dataflow checking: it cannot read data in multiple
  processes.
  ```

  `ifmap`, `weights`, and `bias` share one AXI bundle (`RD_BUS`, in
  `conv_engine()`'s `INTERFACE m_axi` pragmas) - fine when
  `load_weight_tile()` (reads weights/bias) and `scan_and_compute()` (reads
  ifmap) ran strictly sequentially, but DATAFLOW means they're meant to run
  concurrently, and Vitis HLS hard-requires one process per AXI bundle. The
  real fix is splitting `ifmap` onto its own bundle (weights/bias can stay
  together - both are only ever read by `load_weight_tile()`) - but that's
  a genuine interface change (one more physical AXI master port on the IP),
  not a pragma-only tweak: it would also require updating `README.md`'s AMBA
  interface map and, later, `vivado/create_bd.tcl`'s wiring to match.
  Reverted rather than take on that scope now, given the actual
  double-buffering payoff is still unmeasured (existing test configs didn't
  even exercise multiple `OC_TILE` iterations at `PE_OC=20` until the config-B
  fix alongside this attempt - see `conv_engine_tb.cpp`).

  The `num_oc_tiles`-is-not-a-constant warning is a separate, second risk
  worth remembering if this is retried: even after fixing the AXI bundle
  split, Vitis HLS is explicit that a non-constant DATAFLOW loop bound *may*
  still not schedule correctly - this would need checking again, not assumed
  fixed by the bundle change alone.

## 6. What would make this a real number instead of an estimate

1. Phase 0 finalizes the actual Phase 1 layer list → recompute §2's MAC total
   for real, replacing the 1.75 GMAC literature placeholder. Still open -
   `roadmap_yolov3_tiny_adas.md` Phase 3 already did this for the YOLOv3-
   tiny-ADAS network specifically (2.32 GMACs/frame), but that supersedes
   this document's §2 only once Phase 0 §0's scope question (this doc's
   YOLOv2-tiny assumption vs. the roadmap's YOLOv3-tiny-ADAS target) is
   actually resolved, not before.
2. ~~`conv_engine_tb.cpp` passes C-sim → C Synthesis gives a real DSP/BRAM/LUT
   count for `PE_OC=16, TR=16`~~ - **done**, and then re-done for
   `PE_OC=20` (§5, "Raising `PE_OC` after packing") once packing freed
   enough LUT to make raising it worthwhile.
3. ~~Co-simulation gives a real cycle count for a known config~~ - **done**
   for `PE_OC=20`, confirmed by an actual passing `cosim_design` run
   (2026-07-23 15:07 KST, `conv_engine_prj/solution1/sim/report/conv_engine_cosim.rpt`,
   185,798 clock cycles) - only for `conv_engine_tb.cpp`'s small
   `config-A-cosim` shape (16×16×3→16×16×16). No passing cosim log for
   `PE_OC=16` exists anywhere in this repo (the three logged attempts, all
   through the separate Unified-IDE component project, failed with the
   SIGSEGV in `TROUBLESHOOTING.md` §11) - treat any earlier claim of a
   `PE_OC=16` cosim pass as unverified, not confirmed. This confirms
   *correctness*, not yet the 20-50% efficiency guess in §2.
   Replacing that guess needs a cosim (or board) run at a real Phase-1-scale
   layer, which hasn't been done - the small cosim shape was deliberately
   chosen to keep RTL simulation time reasonable (see
   `conv_engine_tb.cpp`'s comment on why only one config gets
   `pad_to_full_depth=true`), not because it's representative of real
   throughput.

   **Update (2026-08-03/04): done.** Real-layer cosim via
   `RUN_HLS_COSIM_LAYER` (see `conv_engine_tb.cpp`'s `run_real_layer_cosim()`
   and `doc/conv_engine_requant_troubleshooting.md` §23-§24) measured layer 3
   (36×64×64→128, k=3, a normal backbone conv) at **10,205,377 cycles** for
   169,869,312 MACs - **4.3% delivered/peak efficiency** against
   `PE_OC=24×TR=16`'s 384 raw MACs/cycle, and layer 9 (9×16×512→30, k=1, the
   detection head) at 855,307 cycles for 2,211,840 MACs - 0.67% (atypical:
   `out_ch=30` tiles badly against `PE_OC=24`). Both are far below this
   section's own 20-50% guess range - see
   `doc/plan_no_board_verification_and_perf.md` §0.4's 2026-08-04 update for
   the full network-wide FPS consequence (~0.72 FPS projected, not the
   6.6-16.5 FPS this document's guess implied).

   Later the same day, the finish-path fix those measurements exposed
   (TROUBLESHOOTING.md §25: 24 serialized calls/position into a
   non-pipelined activation/accum instance, fixed by phase-split pipelined
   lane loops) brought layer 3 to **4,165,741 cycles = 10.6% efficiency**
   (2.45x) and layer 9 to 357,289 (2.39x), bit-exact, clock estimate and
   LUT unchanged-or-better - projected ~1.76 FPS at 100 MHz.

## 7. Input-channel tiling (2026-07-23) - not yet synthesis-confirmed

Added once comparing this engine against the real YOLOv3-tiny-ADAS golden
model (`python_teammate/darknet_golden`) showed 8 of its 13 conv layers need
`in_ch` up to 1024, far past the untiled `MAX_IN_CH=128` this whole document
was written against - see `README.md`'s provenance note for the full design
(new `IC_TILE` loop, `MAX_TOTAL_IN_CH=1024`, the `accum` DDR scratch buffer
sized `[out_h][out_w][PE_OC]`). `MAX_IMG_W` was also raised 416->512 in the
same pass (the real network's `width=512`).

**What's confirmed:** functional correctness only, via `g++` against Vitis's
standalone `ap_int.h` (`conv_engine_tb.cpp` configs I/J/K - a 2-tile
remainder case, a 2-tile exact case, and both `oc_tile`/`ic_tile` tiling at
once - all bit-exact against an independent reference).

**What's NOT confirmed, and should not be assumed free:**

- **Real LUT/DSP/BRAM/FF impact.** `window`/`wtile_packed` are unchanged in
  size (still `MAX_IN_CH`=128-wide), so the on-chip datapath itself shouldn't
  cost more - but the new `IC_TILE` loop's control logic, the `accum` m_axi
  port and its read-modify-write addressing, and `line_buf`'s wider column
  dimension (416->512 elements/instance, from the `MAX_IMG_W` bump) are all
  unmeasured. This document's own §4 already found that "the on-chip arrays
  didn't change size" is not a reliable predictor of LUT cost by itself
  (control/addressing overhead scales with structure, not just data width) -
  don't assume this is free just because it looks structurally similar to
  the accepted `OC_TILE` pattern.
- **Real DDR bandwidth cost.** The oc-tile-only re-scan cost this document's
  "engine efficiency" derating factor (§2) already accounts for is now
  multiplied by `num_ic_tiles` too, for any layer where it's >1. Worst case
  in the real network: layer 13 (in_ch=1024, out_ch=256) is 8 ic_tiles × 13
  oc_tiles = 104 total image re-scans, plus `accum`'s own read-modify-write
  traffic on top of that (extra DDR reads AND writes per non-final
  `ic_tile`, not just the `ifmap` re-read this document already discounted
  for). This could meaningfully worsen the FPS shortfall §3 already flagged
  as unresolved - not measured, and not something to assume "probably fine"
  given §3's own honest finding that even the base design likely falls short
  of 30 FPS before this cost is added.
- **Whether the new `accum` m_axi port on `WR_BUS`** (shared with `ofmap`,
  not a new physical AXI master - see `conv_engine.h`'s AMBA interface note)
  actually behaves as intended under real burst inference, given it's now
  read AND written (unlike `ofmap`, which is write-only) - `hls_compile.log`
  should be checked for burst-related warnings the same way TROUBLESHOOTING
  #4's `READ_CH`/`LOAD_WTILE` burst-pattern lesson already applies elsewhere
  in this file.

Re-synthesize (`run_hls.bat`/`run_hls.sh`, no `--cosim` needed yet) and
check the real numbers before trusting any of the above as "probably fine."

**Update - first real synthesis came back at 100% LUT (117,473 / 117,120,
over budget by 353), same root cause as TROUBLESHOOTING.md §15:**

| Resource | requant baseline (before this section's changes) | tiling, first attempt |
|---|---|---|
| BRAM_18K | 67 (23%) | 70 (24%) |
| DSP | 181 (14%) | 181 (14%) |
| FF | 47,448 (20%) | 54,190 (23%) |
| **LUT** | **106,638 (91%)** | **117,473 (100%, over)** |
| Estimated Fmax | 250.55 MHz | 265.65 MHz (improved, not worsened) |

DSP staying flat confirms `IC_TILE` adds no new MAC hardware, as designed.
The LUT jump (+10,835) traced to the same mistake §15 already made once:
`accumulate_or_finish()` (this section's new accum-DDR read-modify-write
wrapper) had `#pragma HLS INLINE` on the reasoning that "it's just address
arithmetic, cheap regardless of replication" - wrong for the same reason
§15's initial `apply_activation()` guess was wrong, just with a different
expensive primitive: the `accum[...]` access is an m_axi (DDR) read, and
Vitis doesn't appear to auto-share AXI read-port address-generation/
arbitration logic across inlined copies any more than it shared #15's
variable-shift mux - all 20 `PE_PAIR_LOOP` call sites got their own copy.
`apply_activation()` itself stayed correctly shared (`grp_apply_activation_
fu_7497`, one instance in the csynth Instance table) - confirming that fix
still holds; this was a new instance of the same category of mistake, not a
regression of the earlier fix.

**Fix applied** (same pattern as §15): removed `#pragma HLS INLINE` from
`accumulate_or_finish()`. Re-verified functionally unaffected via the same
`g++` + standalone `ap_int.h` build (`ALL CONFIGS PASS`, including new
configs I/J/K, unchanged) - **now re-confirmed by a real csynth AND cosim
run, see §11's 2026-07-24 update** (that run used the current `PE_OC=24`,
not the `PE_OC=16` this section was written against, so the LUT numbers
aren't directly comparable here - but it's the same code path and IS the
real confirmation this section was waiting on).

## 8. LUT reduction, Levers 1-2 (2026-07-24) - functionally verified, LUT impact NOT yet re-synthesized

Full analysis and remaining levers (3: loop-structure consolidation, 4: `PE_OC`
reduction) in `LUT_REDUCTION_PLAN.md`. This section covers what was actually
implemented this session against the most recent real csynth baseline
(`conv_engine_prj/solution1/syn/report/conv_engine_csynth.rpt`):

| Resource | Baseline (this csynth report) | % |
|---|---|---|
| BRAM_18K | 136 | 47% |
| DSP | 183 | 14% |
| FF | 47,401 | 20% |
| **LUT** | **107,733** | **91%** |

Instance/Multiplexer table breakdown of that 107,733: `MAC_KY_MAC_KX` x 160
instances (`PE_PAIRS`=10 x `TR`=16, all `UNROLL`ed) = 65,600 LUT (61% of the
whole design), with roughly half of each 410-LUT lane being pure ky/kx loop
bookkeeping rather than the MAC itself; the top-level Multiplexer table's
largest line items are the `acc_lo`/`acc_hi` loop-exit registers, 512 LUT x
20 instances (10 pairs x lo/hi) - a mux/register sized directly off `acc_lo`/
`acc_hi`'s declared bit width (`accum_t`, `ap_int<32>`), even though the real
per-ic_tile-pass value it holds never gets remotely that large.

**Lever 1 (implemented): narrowed `acc_lo`/`acc_hi`/`contrib_lo`/
`contrib_hi`** (the loop-carried reduction variables inside `PE_PAIR_LOOP`'s
160x-replicated `MAC_IC`/`MAC_KY`/`MAC_KX` body) from `accum_t`
(`ap_int<32>`) to a new, narrower `partial_t` (`ap_int<28>`, `conv_engine.h`).
`accum_t` itself is UNCHANGED (still `ap_int<32>`) - it still sizes the
DDR-resident `accum` scratch buffer and the `accumulate_or_finish()`/
`apply_activation()` interface, both of which carry a running cross-ic_tile
total, not just one tile's partial sum; `partial_t` widens back to `accum_t`
automatically (safe, no truncation) at the `accumulate_or_finish()` call
boundary.

Width derivation, cross-checked two independent ways rather than picked by
inspection:
- **Documented bound**: `python_teammate/darknet_golden/artifacts/int8/
  model_manifest.json`'s per-layer `accumulator_bound` field (the golden
  model's own weight-conditioned worst-case figure) - largest across all 13
  real conv layers is 74,576,608 (manifest layer index 12, in_ch=512 ->
  out_ch=1024, k=3). `2^27 = 134,217,728` covers that with ~1.8x headroom,
  not a knife-edge fit - `ap_int<28>` is the minimum width satisfying it.
- **Empirical measurement**: computed the actual max `|per-ic_tile partial
  sum, bias included|` directly from `python/layer00..12_*.bin` (the real
  input/weight/bias data `python/real_layers.py` extracted from the golden
  model), tiled the same way `conv_engine.cpp`'s `IC_TILE` loop tiles
  (chunks of `MAX_IN_CH`=128 channels, not the full untiled per-layer sum -
  a tiled partial sum could in principle exceed the full sum's magnitude if
  later channels' contributions have opposite sign, so it's the tiled value,
  not the untiled one, that has to fit). Result: 264,099 (layer 6 again,
  matching the documented-bound layer) - needs only 20 bits, far under 28.
  Both checks point at the same worst layer and agree `ap_int<28>` is
  generous, not tight, for real data while still tracking the model's own
  documented worst case rather than overfitting to one calibration image.

**Lever 2 (implemented): `#pragma HLS BIND_OP ... op=add impl=dsp`** on
`acc_lo`/`acc_hi`'s accumulation, to move that add off LUT fabric onto
DSP48E2 (14% utilized, plenty of headroom) instead.

**Verification actually performed:** a working Xilinx toolchain WAS found
on this machine (`/mnt/c/Xilinx/Vitis_HLS/2021.1/include/ap_int.h`), so
Levers 1-2 were compiled for real (not just reasoned about) via:
```
g++ -std=c++11 -O2 -I /mnt/c/Xilinx/Vitis_HLS/2021.1/include \
    conv_engine.cpp conv_engine_tb.cpp -o conv_engine_tb
```
`ALL CONFIGS PASS` and `ALL REAL LAYERS PASS` - every synthetic
`conv_engine_tb.cpp` config (A through K, A-cosim) AND all 13 real conv
layers (`real-layer00`..`real-layer12`, bit-exact against the real golden
model's expected output) passed unchanged after both levers, both before
and after adding Lever 2's `BIND_OP` pragma on top of Lever 1's narrowing.

**Update - real csynth run completed (2026-07-24, `run_hls.bat` on the
Windows side, user-executed):** C-sim inside the actual Vitis HLS
toolchain independently re-confirmed `ALL CONFIGS PASS` / `ALL REAL LAYERS
PASS` (matching the g++-against-standalone-`ap_int.h` result above, now
via the real compiler instead). C-synthesis result:

| Resource | Before (baseline, this section's earlier table) | After Levers 1+2 | Delta |
|---|---|---|---|
| BRAM_18K | 136 (47%) | 136 (47%) | 0 |
| DSP | 183 (14%) | 187 (14%) | +4 |
| FF | 47,401 (20%) | 46,024 (19%) | -1,377 |
| **LUT** | **107,733 (91%)** | **105,723 (90%)** | **-2,010 (-1.9%)** |
| Loop Constraint Status | "All loop constraints were NOT satisfied" (pre-existing, §5) | **"All loop constraints were satisfied"** | improved |
| Estimated clock | (not recorded for this exact baseline) | 3.808 ns (≈262.6 MHz) vs. 5.00 ns target | comfortable margin, no violation |

Per-lane detail (`conv_engine_Pipeline_MAC_KY_MAC_KX_csynth.rpt`): one
`MAC_KY_MAC_KX` lane dropped 410 -> 398 LUT (-12/lane x 160 lanes =
-1,920 LUT) - **essentially the entire measured LUT reduction is
attributable to Lever 1** (the `partial_t` narrowing). Lever 2's `BIND_OP`
barely engaged: DSP rose by only +4 (not the ~20-40 that binding all
20 `acc_lo`/`acc_hi` loop-carried adders, 10 pairs x lo/hi, across DSP would
suggest), and the top-level Multiplexer LUT total (16,388) was unchanged
before/after even though individual `acc_lo`/`acc_hi` loop-exit lcssa
registers did shrink (512 -> 448 LUT each, matching the 32->28 bit ratio
exactly) - some other multiplexer entries evidently grew to offset it, or
the pragma only partially took effect (`vitis_hls.log` logged no
warning/error about the `BIND_OP` pragma either way, so the tool accepted
it silently without fully honoring it for every instance).

**Honest assessment: smaller than this document's own back-of-envelope
estimate** (`LUT_REDUCTION_PLAN.md` guessed 3,000-5,000 LUT from Lever 1
alone) **- real measured combined effect of both levers is -2,010 LUT
(-1.9%), leaving the design at 90%, still above the 85% target and this
document's own 60-70% "safe" line (§1).** Both levers are free (no DSP/FF
regression worth worrying about, no throughput cost, Loop Constraint
Status improved rather than regressed) so there's no reason to revert
either, but **Levers 1+2 alone do not close the gap.**

## 9. Levers 3+4 (2026-07-24) - implemented together at the user's explicit
   choice, functionally verified, LUT impact NOT yet re-synthesized

After §8's Levers 1+2 landed at 90% (short of the 85% target), the user was
asked whether to try Lever 3 (loop consolidation) alone first and add
Lever 4 (`PE_OC` cut) only if still short, or apply both together
unconditionally. The user chose **both together** - explicitly accepting
Lever 4's quoted ~20% throughput cost even if Lever 3 alone might have been
enough, in exchange for higher confidence of hitting the target in one
round-trip.

**Lever 4: `PE_OC` 20 -> 16** (`conv_engine.h`) - `PE_PAIRS` 10 -> 8, raw
parallel MACs 320 -> 256, a real ~20% parallelism/throughput cut. Not a new,
unvalidated value - matches the earlier "packed baseline" already confirmed
by real csynth + cosim (§5's "Raising PE_OC after packing" table, 86,986
LUT/74% - a different code shape than today's, so that exact figure will
NOT reproduce, but 16 is a known-safe parallelism level, not a guess).

**Lever 3: MAC reduction loop nest inverted** (`conv_engine.cpp`,
`scan_and_compute()`). Before: `PE_PAIR_LOOP(UNROLL, PE_PAIRS-way) ->
MAC_IC(UNROLL factor=TR) -> MAC_KY(seq) -> MAC_KX(seq, PIPELINE II=1)` -
the genuinely-sequential ky/kx pipeline was nested INSIDE two UNROLLed
dimensions, so Vitis synthesized `PE_PAIRS x TR` (160 at PE_OC=20, 128 at
PE_OC=16) fully independent copies of the ky/kx loop's own FSM/counter/
address-generation logic, not just of the MAC arithmetic - §8 measured this
loop-bookkeeping overhead at roughly half of each lane's 398-410 LUT.
After: `MAC_REDUCE(seq, PIPELINE II=1, over ic_step x ky x kx) ->
PE_PAIR_LOOP(UNROLL) -> MAC_TR(UNROLL)` - ky/kx (and a new explicit
`ic_step` dimension replacing the old MAC_IC loop's implicit partial-UNROLL
remainder handling) is now the single outer sequential/pipelined loop, with
PE_PAIRS x TR spatial parallelism UNROLLed INSIDE one pipeline stage
instead of wrapping it - same total MAC/unpack operation count and same
per-cycle spatial parallelism, but (in principle) one shared FSM instead of
128-160 copies of it.

Structural consequences of the inversion:
- `acc_lo`/`acc_hi` became `partial_t[PE_PAIRS]` arrays (`complete`-
  partitioned), not per-`j` locals - they must now survive the entire
  combined reduction loop (all `ic_step`/`ky`/`kx` iterations) since
  `PE_PAIR_LOOP` is nested inside it rather than wrapping it. Bias init
  moved into its own small `PE_PAIR_INIT` `UNROLL` loop; the final
  `accumulate_or_finish()` calls moved into a new `PE_PAIR_FINISH` `UNROLL`
  loop that runs once after the whole reduction completes (they can't run
  per-pair mid-reduction anymore, since a pair's sum isn't finished until
  every iteration has run for it).
- The `if (lo_valid || hi_valid) { ... }` guard that used to wrap each
  pair's entire MAC computation was removed - it never saved hardware area
  even before this change (`out_ch` is a runtime parameter, so Vitis always
  had to synthesize every `PE_PAIRS` lane's multiply/unpack/accumulate
  logic regardless; the guard only gated whether results got WRITTEN, via
  `accumulate_or_finish()`'s own `lo_valid`/`hi_valid` checks, which are
  unchanged). Removing it only changes C-SIMULATION wall-clock time
  (invalid pairs' now-unconditional computation reads stale, unused
  `wtile_packed[j][...]` data left over from a prior `oc_tile` pass and
  discards the result, same as hardware always implicitly did) - it does
  not change synthesized area or functional output.
- An explicit `if (ic < ic_count)` guard replaces the old partial-`UNROLL`
  loop's implicit remainder handling for `ic_count` not a multiple of `TR`
  - required because `window[]`/`wtile_packed[]` beyond `ic_count` hold
  stale data from a previous `ic_tile` pass, not zeros (same reasoning as
  the pre-existing `SHIFT_WINDOW`/`READ_CH` bound-by-`ic_count` code this
  file already had).
- `contrib_hi`/`contrib_lo` were also switched from `accum_t` to
  `partial_t` while rewriting this block - **completing Lever 1**, which
  had only narrowed `acc_lo`/`acc_hi`'s own declaration in §8 and left
  `contrib_hi`/`contrib_lo` at 32-bit (`accum_t`) by oversight. This may
  account for some of §8's smaller-than-expected measured LUT win, though
  that hasn't been isolated by a dedicated re-run.

**Verification performed:** `g++ -std=c++11 -O2 -I
/mnt/c/Xilinx/Vitis_HLS/2021.1/include conv_engine.cpp conv_engine_tb.cpp`
- `ALL CONFIGS PASS` and `ALL REAL LAYERS PASS`, including the edge cases
most likely to expose a loop-restructuring bug: config-F (`in_ch` not a
multiple of `TR`, exercises the new explicit `ic < ic_count` guard),
config-H (`out_ch` straddles a pe-pair boundary), and config-I/J/K
(`ic_tile`/`oc_tile` multi-pass boundaries) all passed bit-exact, alongside
all 13 real conv layers against the real golden model's expected output.

**What is explicitly NOT verified: the actual LUT/DSP numbers, or whether
the loop inversion actually produces 1 shared `MAC_KY_MAC_KX`-equivalent
instance instead of `PE_PAIRS x TR` copies of it.** This is a real, open
question, not a formality - Vitis HLS's own scheduler could in principle
still replicate control logic for reasons not obvious from the source
(e.g. if it can't prove `PE_PAIR_LOOP`/`MAC_TR`'s UNROLLed bodies are
identical enough to share address-generation hardware). **Re-run
`run_hls.bat` and check `conv_engine_csynth.rpt`'s Instance table** - look
specifically for how many `MAC_KY_MAC_KX`-style pipeline-function instances
exist (expect 1 now, not 128) and compare the new LUT/DSP/FF/BRAM totals
against §8's post-Lever-1+2 baseline (105,723 LUT, 90%) before trusting
this delivered the win it was written for.

## 10. Lever 3, round 2 (2026-07-24) - real csynth found a severe timing
    regression the LUT number alone hid; fixed with a tree reduction

**Real csynth run (user-executed `run_hls.bat`) confirmed the loop
inversion's LUT win, dramatically:**

| Resource | §8 baseline (Levers 1+2, PE_OC=20) | §9 first Lever 3+4 attempt | Delta |
|---|---|---|---|
| BRAM_18K | 136 (47%) | 136 (47%) | 0 |
| DSP | 187 (14%) | 156 (12%) | -31 |
| FF | 46,024 (19%) | 24,615 (10%) | -21,409 |
| **LUT** | **105,723 (90%)** | **61,484 (52%)** | **-44,239 (-42%)** |

The Instance table confirmed the mechanism directly: exactly **1**
`conv_engine_Pipeline_MAC_REDUCE_MAC_KY_MAC_KX` instance exists (not
`PE_PAIRS x TR` = 128 copies), at 29,791 LUT total - the entire MAC
datapath for all 128 lanes, replacing what was 160 (then would-have-been
128) separate ~400-LUT-each lane copies. C-sim inside the real Vitis HLS
toolchain also re-confirmed `ALL CONFIGS PASS` / `ALL REAL LAYERS PASS`.

**But: `WARNING: [HLS 200-871] Estimated clock period (21.231 ns) exceeds
the target (target clock period: 5.000 ns...)` - a ~4.2x timing
violation** (Estimated Fmax ~47 MHz vs. the ~263 MHz §8's design achieved).
**This would have been a genuine regression if shipped as-is** - LUT
utilization looked fantastic, but the design could no longer run anywhere
close to its 200 MHz target, so real achievable throughput (raw MACs/sec)
would have gotten far WORSE despite more raw parallelism per cycle, not
better. This is exactly the kind of thing a resource-utilization number
alone cannot catch - only checking the Timing/Performance Estimates
section of the same report would surface it, which is why this document
insists on checking latency/Fmax, not just the utilization table, after
every csynth run.

**Root cause, from `vitis_hls.log`'s own critical-path dump**
(`WARNING: [HLS 200-1016] The critical path in module
'conv_engine_Pipeline_MAC_REDUCE_MAC_KY_MAC_KX'...`): a chain of 16
sequential `(add, select)` pairs on `acc_hi`, each ~0.975ns + ~0.325ns =
~1.3ns, totaling ~20.8ns - matching the reported 21.231ns almost exactly.
This came from how the first Lever 3 attempt wrote the TR-way reduction:
`MAC_TR: for (t=0; t<TR; t++) #pragma HLS UNROLL { if (ic<ic_count) {
... acc_lo[j] += contrib_lo; } }` - all 16 UNROLLed `t`-lanes wrote `+=`
into the SAME loop-carried `acc_lo[j]`/`acc_hi[j]` register, each ALSO
gated by an `if` (compiling to a select/mux), forcing a genuine 16-deep
SEQUENTIAL dependency chain inside one `PIPELINE II=1` iteration's
combinational logic. This is fundamentally different from how the
pre-Lever-3 design achieved the same TR-way parallelism: there, `ic` was
UNROLLed as an OUTER loop (not feeding a single per-cycle accumulate), so
HLS's own automatic reduction-variable handling combined the TR unrolled
lanes via an implicit balanced adder tree (the original code's own comment
said as much: "combined into acc_lo/acc_hi via the adder trees HLS inserts
automatically for loop-carried reduction variables") - Lever 3's rewrite
accidentally traded that automatic tree for a hand-written serial chain by
moving the `+=` inside the UNROLLed loop instead of after it.

**Fix applied** (same commit as this section, before ever showing the
55,484-LUT "win" to the user as final): restructured `PE_PAIR_LOOP`'s body
in `conv_engine.cpp` so the TR-way combine is an explicit **balanced
binary tree**, not a chain. Each `t`-lane now writes its contribution (or 0,
if `ic >= ic_count`) into an independent array slot (`lo0[t]`/`hi0[t]`,
`complete`-partitioned, all 16 writes independent/parallel, no shared
register) - THEN four explicit UNROLLed tree levels (`TREE_L1`/`TREE_L2`/
`TREE_L3`, 16->8->4->2->1, `log2(16)=4` levels of PARALLEL adds) combine
them - and only the FINAL combined value gets added into the loop-carried
`acc_lo[j]`/`acc_hi[j]`, restoring the "one add per cycle into the
persistent accumulator" cadence the pre-Lever-3 design always had.
Hardcoded to `TR==16` (`static_assert`-enforced) rather than written as a
generic runtime-bounded loop, matching this file's established preference
for explicit code over a clever construct whose UNROLL/scheduling behavior
would need its own separate synthesis confirmation.

**Verification performed:** same `g++`-against-standalone-`ap_int.h` build
- `ALL CONFIGS PASS` / `ALL REAL LAYERS PASS`, unchanged, confirming the
tree-reduction rewrite is still bit-exact against every synthetic config
and all 13 real conv layers.

**What is explicitly NOT verified yet: whether the tree reduction actually
fixes the timing violation, and whether it costs back some of the LUT win.**
A 4-level balanced tree plus one final accumulate is a much shallower
critical path than a 16-deep chain in principle, but this has NOT been
confirmed by a real csynth run at the time of writing this section - **the
very next thing to do is re-run `run_hls.bat` one more time** and check
two things in the fresh `conv_engine_csynth.rpt`/`vitis_hls.log`: (1) the
Timing/Performance Estimates section - the estimated clock period should
drop back toward ~5ns (not still be double-digit ns), and (2) the
Utilization Estimates table - LUT will likely rise somewhat from the
61,484 figure above (the tree's own intermediate registers/muxes aren't
free), the open question is by how much, and whether it's still
comfortably under the 85% target. Do not treat either the 52%-LUT number
or the tree-reduction fix as final until both are re-confirmed by an
actual run - this section exists specifically because trusting a metric
that "looked done" without checking the adjacent one (timing) once already
produced a result that would have been a real regression if shipped.

**Update - re-run confirmed (2026-07-24, same session, user-executed
`run_hls.bat` again): the tree-reduction fix worked, and cost nothing.**

| Resource | §9 broken-timing attempt | §10 tree-reduction fix | Delta |
|---|---|---|---|
| BRAM_18K | 136 (47%) | 136 (47%) | 0 |
| DSP | 156 (12%) | 156 (12%) | 0 |
| FF | 24,615 (10%) | 26,571 (11%) | +1,956 |
| **LUT** | **61,484 (52%)** | **58,651 (50%)** | **-2,833 (LUT went DOWN, not up)** |
| Estimated clock | 21.231 ns (4.2x over target, broken) | **3.650 ns** (under the 5.00 ns target) | fixed |
| Estimated Fmax | ~47 MHz | **~273.97 MHz** | restored, and slightly BETTER than §8's pre-Lever-3 baseline (~262.6 MHz) |
| `MAC_REDUCE_MAC_KY_MAC_KX` pipelining | Depth=4, II=1 (but didn't meet timing) | Depth=6, II=1 (meets timing) | 2 more pipeline stages, same II - a one-time latency/fill cost, not a recurring throughput cost |
| Loop Constraint Status | satisfied | satisfied | unchanged |
| C-sim (real Vitis toolchain) | ALL CONFIGS PASS / ALL REAL LAYERS PASS | ALL CONFIGS PASS / ALL REAL LAYERS PASS | unchanged |

The extra 2 pipeline stages (Depth 4->6) is exactly the mechanism that
fixed timing - HLS spread the shallower tree-reduction's combinational
work across 2 more cycles instead of trying to cram it (or the broken
version's 16-deep chain) into one, while `Final II = 1` stayed unchanged -
so this costs a few extra cycles of one-time pipeline *latency* (fill/drain,
paid once per `scan_and_compute()` call, not per output pixel), not
recurring *throughput*. LUT dropping further (not rising, as the §9 write-
up worried it might) suggests the tree's own registers/muxes cost less
than the broken chain's `select` operations did.

**Final state, this session's full LUT reduction effort (§8-§10 combined):**

| Resource | Original baseline | Final (Levers 1-4) | Change |
|---|---|---|---|
| BRAM_18K | 136 (47%) | 136 (47%) | 0 |
| DSP | 183 (14%) | 156 (12%) | -27 |
| FF | 47,401 (20%) | 26,571 (11%) | -20,830 |
| **LUT** | **107,733 (91%)** | **58,651 (50%)** | **-49,082 (-45.6%)** |
| Estimated Fmax | (not recorded for this exact baseline) | ~273.97 MHz | comfortably clears the 200 MHz target |

Comfortably under this document's own §1 "don't plan past 60-70%" rule,
with real margin now available for other PL logic (camera-capture DMA, AXI
interconnect, Phase 2 additions) that had none before this effort. Real
achievable throughput (raw MACs/cycle x Fmax) is unchanged or slightly
better than before Lever 3/4 at the peak-parallelism setting, and the
`PE_OC=20->16` cut (Lever 4) is the only piece of this that costs real
parallelism (~20% fewer raw MACs/cycle) - Levers 1-3 were genuinely free.

**RTL-confirmed (`run_hls.bat cosim`, same session, immediately after):**
`cosim_design` (`config-A-cosim`'s shape) came back `*** C/RTL
co-simulation finished: PASS ***` (Verilog, 127,795 cycles - fewer than
the pre-Lever-3/4 `PE_OC=20` baseline's 185,798 cycles, §3, consistent
with `PE_OC=16`'s ~20% lower raw-MAC parallelism on the same fixed shape).
This is the last verification tier this project uses (C-sim -> csynth
resource/timing estimates -> RTL cosim) - all three now confirm Levers
1-4 together, not just C-sim/estimates. See `TROUBLESHOOTING.md` §21 for
the full write-up (including the timing regression this section's first
attempt hit and how it was fixed).

## 11. Raising `PE_OC` back up (16->24), same session - quantifying what Lever 4 actually cost, and re-testing a previously-rejected value now that Lever 3 removed the reason it was rejected - **real csynth/cosim confirmed 2026-07-24, see update at end of this section**

**Why revisit this at all:** with Levers 1-3 confirmed and Lever 4's
`PE_OC=16` landing at LUT 50% / DSP 12% (§10), there was real,
quantifiable headroom left unused. Rather than just eyeballing "there's
room," the actual cost of Lever 4's `PE_OC=20->16` cut was computed
directly from the real 13-layer network (`python/layers_meta.json`), not
estimated:

| `PE_OC` | Total `(oc_tile x ic_tile)` DDR re-scan passes, all 13 real layers | Raw MACs/cycle |
|---|---|---|
| 20 (original) | 508 | 320 |
| 16 (Lever 4) | **619 (+21.9%)** | 256 (-20%) |
| 24 (this change) | **428 (-15.7% vs. 20, -30.9% vs. 16)** | 384 (+20% vs. 20, +50% vs. 16) |

Lever 4 was a real, compounding throughput cost - not just "20% fewer raw
MACs" but *also* 22% more DDR re-scan passes across the real network,
since fewer `PE_OC` lanes means more `oc_tile`s per layer. `PE_OC=24`
reverses both, and by more than Lever 4 cost - if it fits.

**Why 24 specifically, and why re-testing it isn't just repeating a past
mistake:** `PE_OC=24` was tried once before, in the OLD (pre-Lever-3) loop
structure, and came back at 121,566 LUT (103%, would not place/route -
§5's "Raising `PE_OC` after packing" table). Re-trying a number a
previous entry in this exact document already rejected needs the same
justification TROUBLESHOOTING.md §18 already established for a different
pragma: don't just assume the old rejection still holds, but don't ignore
*why* it was rejected either. Here, the "why" is directly addressed: the
old rejection's entire cost was per-`PE_PAIR_LOOP`-lane replicated ky/kx
loop-control overhead (~130-200 LUT/lane, paid `PE_PAIRS x TR` times over)
- exactly the cost category Lever 3 eliminated by sharing one
`MAC_REDUCE` instance across every lane (TROUBLESHOOTING.md §21). A rough
linear estimate from the single current data point (`PE_PAIRS=8`'s
`MAC_REDUCE` module itself measured at 29,791 LUT, §10, ~3,724 LUT/pair
average) puts `PE_PAIRS=12` (this change, `PE_OC=24`) around ~73,500 LUT
(~63%) - comfortably under both the 85% target and this document's own
60-70% "safe" line (§1).

**This estimate is explicitly NOT trustworthy on its own** - it's a linear
extrapolation from ONE data point, the exact same kind of reasoning that
was wrong by a wide margin the first time `PE_OC=16->24` was tried in this
document (§5: a "roughly 270 LUT/raw-MAC" linear guess from
`PE_OC=16`->`24` badly undershot the real jump to 103% LUT, in the OLD
structure - there is no guarantee this NEW structure's scaling is any more
linear than the old one turned out to be). Verified so far: `g++`-against-
standalone-`ap_int.h` C-sim, `ALL CONFIGS PASS` / `ALL REAL LAYERS PASS`
unchanged (confirms `PE_OC` has no effect on functional correctness, only
on `num_oc_tiles` - it says nothing about area or timing). **Now confirmed
by real synthesis - see the update immediately below.** (Original plan
was: re-run `run_hls.bat` and check the real LUT/DSP/Fmax numbers in a
fresh `conv_engine_csynth.rpt` before trusting this estimate; if it
overshot the 85% target (or, worse, repeated §5's
"over 100%, would not place/route" outcome), back off - this document's
own two-point extrapolation method (§5: measure at two values, compute
real marginal LUT/raw-MAC, solve for the target) is the fallback if a
single real data point at `PE_OC=24` disagreed with the linear estimate
above.)

**Update (2026-07-24 16:16-16:50 KST) - confirmed by real csynth AND
cosim** (`run_hls.bat cosim`, full run: C-sim, C-synth, C/RTL cosim in one
`vitis_hls` invocation):

| Resource | Linear estimate (this section, above) | Real csynth result |
|---|---|---|
| BRAM_18K | (not estimated) | 136 (47%) |
| DSP | (not estimated) | 219 (17%) |
| FF | (not estimated) | 34,073 (14%) |
| **LUT** | ~73,500 (~63%) | **77,252 (65%)** |

The linear estimate undershot by ~5%, same direction as every other
extrapolation in this document so far - close enough to trust for this
change, but consistent with this section's own warning that a one-point
linear guess is not reliable in general. **Comfortably under both the 85%
target and the 60-70% "safe" line (§1)** - `PE_OC=24` is confirmed, not
just estimated.

C-sim: `ALL CONFIGS PASS` (A-K) and `ALL REAL LAYERS PASS` (all 13 real
YOLOv3-tiny-ADAS layers, bit-exact against the golden model). Cosim:
`config-A-cosim` PASS, bit-exact against RTL (`COSIM CONFIG PASS`,
`C/RTL co-simulation finished: PASS`). This is also the confirmation run
for §7's input-channel tiling (`IC_TILE`), which up to now only had
functional (`g++`) verification, not a real Vitis C-sim/csynth/cosim
pass - see `README.md`'s provenance item 3.

**Still not measured:** real DDR bandwidth / achieved FPS against the
30 FPS target (§2-3's shortfall question), and the worst-case layer's
88-pass `(oc_tile, ic_tile)` re-scan cost (layer 13) specifically - cosim
here only exercised `config-A-cosim` (single-tile). Package IP and
`vivado/create_bd.tcl` are the next steps (`README.md`'s "Next steps").
above.
