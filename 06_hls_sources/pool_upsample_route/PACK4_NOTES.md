# pool_upsample_route — int8×4 packing (`pack4`), MERGED

> **STATUS: merged and re-packaged, 2026-08-04.** This is the live
> `hls/pool_upsample_route` project — the packing described below is what
> these sources now do. Developed in `hls/pool_upsample_route_pack4` (a
> working copy made so it could proceed in parallel with the
> `conv_engine_requant` cosim occupying this tree), then merged here.
>
> **Post-merge verification, all on the merged tree:**
> - `csim` 3/3 `ALL CONFIGS PASS`, `csynth` 3/3, `Package IP` 3/3.
> - csynth latencies identical to the pack4 tree's (221,516,800 /
>   345,440 / 688,256), confirming the merge really took effect rather than
>   a stale build being re-reported.
> - **All three freshly generated `x*_hw.h` register maps are byte-identical
>   to the pre-merge baseline** (`diff` clean), which is the hard evidence
>   for §3's claim that the software interface is unchanged — not an
>   assumption.
> - Every `REG_*` offset in all three `SW/*_hw_driver.h` files was
>   re-checked against the newly generated headers and matches exactly,
>   including `route_concat`'s third pointer, which had historically been
>   off by +0x04 when hand-guessed.
>
> **Rollback:** the pre-merge sources and the pre-merge generated register
> maps are preserved in `baseline_pre_pack4_2026-08-04/`. This project is
> not under git, so that directory is the only copy — do not delete it until
> the design has been through a real implementation run. Restoring the
> baseline `route_concat_engine.{h,cpp}` from there is how you take the §7c
> "drop route back to baseline if LUT gets tight" option.

Everything outside `HW/` and `SW/` was untouched by the merge
(`run_hls.tcl`, `run_hls.bat`, `vivado/`, `python/`). The `SW/` change is
documentation only — the three driver headers gained a "CALLER OBLIGATIONS"
block recording §4's contract; no offset, no function, and no written value
changed.

---

## 1. What this changes

The three engines' `m_axi` pointers change type from `act_t` (`ap_int<8>`)
to `pack4_t` (`ap_uint<32>`), so each AXI beat carries **4 consecutive NHWC
channels instead of 1**. Every inner loop now counts in words (`ch/4`)
rather than channels, at the same `II=1`.

New file `HW/pack4.h` holds the type, the lane accessors, and the full
rationale. The three engines and the testbench are otherwise structurally
unchanged.

## 2. Why — the bottleneck was never the pipeline

All three engines had already reached `II=1` on every inner loop, and the
real-shape cosim measurements sat exactly on the "one element per beat"
floor:

| engine   | measured      | theoretical min at 1 elem/beat  |
|----------|---------------|---------------------------------|
| maxpool  | 6.16 c/output | 6 (4 window reads + init + write) |
| upsample | 1.37 c/output | ~1.25                           |
| route    | 1.22 c/output | ~1                               |

There is no pragma that improves this. The only lever is widening what a
beat carries, and NHWC (channel innermost) makes 4-channel packing the
natural grouping.

## 3. The finding that made this cheap

The original plan (§23-d, "32-bit ceiling") assumed packing was a
**system-level** change requiring both a PS-side data-layout change and a
wider `m_axi` in the block design. Checking the baseline's own synthesis
report shows neither is true:

```
maxpool_engine_csynth.rpt:
  |m_axi_RD_BUS_WDATA  |out| 32 | m_axi | RD_BUS | pointer|
  |m_axi_RD_BUS_WSTRB  |out|  4 | m_axi | RD_BUS | pointer|
```

**The AXI data bus was already 32 bits wide.** Declaring the port as
`ap_int<8>*` did not narrow the bus — it just meant 3 of every 4 byte lanes
went unused on every beat. Consequences:

1. **No block-design change.** `ap_uint<32>*` produces exactly the same port
   geometry. `vivado/create_bd.tcl` and the HP0/HP1 narrowing in
   `create_system_bd.tcl` §3 need no edit.
2. **No PS-side repacking, and no change to the DDR byte layout.** On this
   little-endian platform, 4 consecutive NHWC channels of an int8 array
   *already are* the 4 bytes of one 32-bit word, lowest channel in the
   lowest byte. The packing is a pure reinterpretation of the same bytes, so
   a buffer written by `conv_engine` (still int8-addressed) is a valid input
   to these engines with no conversion pass.
3. **No `s_axilite` register-map change.** Port count, bundle names, and the
   meaning of every scalar argument are unchanged — `ch`/`ch0`/`ch1` are
   still counted in **channels**, not words. The `SW/*_hw_driver.h` drivers
   need no functional edit.

So this is a local HLS change plus a calling contract, not a system-level
one.

## 4. What it does require (new contract)

Both are real narrowings versus the baseline, which accepted any channel
count. Both are `assert()`ed in every engine.

1. **`ch % 4 == 0`** on all three engines, and additionally **`ch0 % 4 == 0`**
   on `route_concat_engine` (src1's channels start at output offset `ch0`,
   so `ch0` must land on a word boundary or SRC1_COPY's first whole-word
   store would clobber the last of src0's channels).
2. **4-byte-aligned base pointers.** Any ordinary allocator result, and any
   cacheline-aligned CMA buffer, already satisfies this.

Every real YOLOv3-tiny-ADAS layer complies: maxpool sees
ch ∈ {16, 32, 64, 128, 256, 512}, upsample 128, route (ch0, ch1) = (256, 0)
and (128, 256).

A `ch % 4 != 0` tail is deliberately **not** supported: the write side
cannot store a partial word without a read-modify-write on the last word of
every pixel, which costs hardware and adds a hazard for a case this network
never produces.

## 5. Cost per engine

- **upsample** — free. Pure replication, so the packed engine never unpacks
  a lane at all; it moves whole 32-bit words end to end. Strictly fewer loop
  iterations, no added logic.
- **maxpool** — 4 int8 comparators per beat instead of 1. Cheap.
- **route** — 4 parallel `saturate(round_shift(v*multiplier, shift))` units
  per source loop instead of 1, i.e. 8 instantiations rather than 2. This is
  the real resource cost of the change. The lanes *must* retire in the same
  cycle to hold `II=1` — sharing one requant unit across the 4 lanes would
  serialize the beat back to `II=4` and give up the entire win. Budget comes
  from the measured 4-IP implementation (37.81% LUT, versus the 92% csynth
  had predicted). **Re-check this variant's own csynth LUT/DSP numbers
  rather than assuming the baseline's still hold.**

## 6. Verification status

| step | status |
|------|--------|
| C model, all 20 synthetic configs | **PASS** — bit-exact |
| C model, all 9 real golden layers | **PASS** — bit-exact |
| Vitis `csim`, all 3 solutions | **PASS** — 3/3 `ALL CONFIGS PASS` |
| Vitis `csynth`, all 3 solutions | **PASS** — `ALL SOLUTIONS COMPLETED`, `II=1` held everywhere |
| Vitis `cosim`, all 3 solutions | **PASS** — 3/3, real cycle counts in §7 |
| Package IP | **not yet run** |

The C model was validated by compiling the engines and testbench directly
with `g++` against the Vitis headers, which sidesteps needing the Vitis
install while it was busy:

```bash
g++ -std=c++14 -O1 -w -I/mnt/c/Xilinx/Vitis/2024.2/include \
    -o tb_pack4 maxpool_engine.cpp upsample_engine.cpp \
                route_concat_engine.cpp pool_upsample_route_tb.cpp
./tb_pack4        # -> ALL CONFIGS PASS
```

The `reference_*()` models in the testbench are deliberately left entirely
`int8_t`-based and completely unaware of the packing. That is what makes a
PASS evidence that the packing is *bit-exact*, rather than evidence that
both sides share the same packing bug.

### Testbench configs that changed

Nine synthetic configs used channel counts that are not multiples of 4 and
now use the next multiple up. **Each config still tests what it was written
to test** — only "channel count not a multiple of 4" is gone, and that is
now outside the supported contract rather than a case these configs cover.
In particular MP-C still has odd *spatial* dims (5×7), MP-B is still the
minimal single-output-pixel case, MP-G is still non-square.

| config | baseline ch | pack4 ch |
|--------|-------------|----------|
| MP-B   | 1           | 4        |
| MP-C   | 3           | 4        |
| MP-E   | 3           | 4        |
| MP-G   | 6           | 8        |
| UP-C   | 1           | 4        |
| UP-D   | 6           | 8        |
| RT-B   | ch0 13      | ch0 16   |
| RT-D   | ch0 10, ch1 7 | ch0 12, ch1 8 |
| RT-E   | ch0 5, ch1 5  | ch0 8, ch1 4  |

The real-layer suite is untouched — same golden data, same shapes.

## 7. Measured result

### 7a. C/RTL co-simulation — real layer shapes, real cycle counts

This is the authoritative measurement: RTL simulation of each engine's real
network shape, same `--cosim-only` configs the baseline was measured with.
All three report `Pass`.

| engine   | shape (cosim config)        | outputs   | baseline    | pack4       | speedup   |
|----------|-----------------------------|-----------|-------------|-------------|-----------|
| maxpool  | 9×16×512, stride 1 + pad (layer 11) | 73,728  | 454,218 c   | **121,512 c** | **3.74×** |
| upsample | 9×16×128 → 18×32×128 (layer 19)     | 73,728  | 100,983 c   | **33,585 c**  | **3.01×** |
| route    | 18×32, ch0 128 + ch1 256 (layer 20) | 221,184 | 269,706 c   | **106,122 c** | **2.54×** |

Per output element:

| engine   | baseline      | pack4        | 1-elem/beat floor |
|----------|---------------|--------------|-------------------|
| maxpool  | 6.16 c/output | **1.65**     | 6                 |
| upsample | 1.37 c/output | **0.456**    | ~1.25             |
| route    | 1.22 c/output | **0.480**    | ~1                |

All three are now *below* the old 1-element-per-beat floor, which is exactly
the point — that floor was a property of the 8-bit pointer type, not of the
hardware.

The speedups fall short of a clean 4× by increasing amounts (3.74 → 3.01 →
2.54) because each engine has fixed per-pixel loop-entry/exit overhead that
does not shrink with the iteration count. Dividing the iterations by 4 makes
that fixed cost a proportionally larger share, and route has the shortest
inner loops per pixel, so it feels this most.

### 7b. Whole-frame effect

Summed over every real layer of each type, at 100 MHz:

| engine   | outputs/frame | baseline  | pack4     | saved     |
|----------|---------------|-----------|-----------|-----------|
| maxpool  | 1,216,512 (6 layers) | 7.49M c ≈ **74.9 ms** | 2.01M c ≈ **20.1 ms** | 54.8 ms |
| upsample | 73,728 (1 layer)     | 0.10M c ≈ 1.01 ms     | 0.03M c ≈ 0.34 ms     | 0.67 ms |
| route    | 258,048 (2 layers)   | 0.31M c ≈ 3.15 ms     | 0.12M c ≈ 1.24 ms     | 1.91 ms |
| **total**|                      | **≈ 79.1 ms**         | **≈ 21.7 ms**         | **≈ 57.4 ms** |

Nearly all of the win is maxpool. This matters **only after conv improves** —
conv still dominates the frame at ~0.72 FPS measured, and this change does
not touch it.

### 7c. C synthesis — resources and worst-case latency

`csynth` numbers, baseline vs pack4, same part and same 5.00 ns clock. The
latency figures here are the top-level worst case at each engine's
compile-time bounds (not real shapes), so treat §7a as the performance
result and this table as the *resource* result.

| engine   | latency (max cycles) | speedup | LUT | FF | DSP | BRAM |
|----------|----------------------|---------|-----|-----|-----|------|
| maxpool  | 825,496,064 → **221,516,800** | **3.73×** | 4438 → **4275** (−4%) | 3863 → 3859 | 7 → 9 | 4 → 6 |
| upsample | 1,328,448 → **345,440** | **3.85×** | 3197 → **2898** (−9%) | 2669 → 2512 | 4 → 6 | 4 → 5 |
| route    | 2,261,120 → **688,256** | **3.29×** | 6094 → **11,244** (+84%) | 3899 → 5858 (+50%) | 12 → 25 | 3 → 4 |

`II=1` is held on every inner loop in all three engines — the gain is
entirely from each loop running ¼ as many iterations, exactly as intended.

### Reading these numbers

- **maxpool and upsample are unambiguous wins: faster *and* smaller.** LUT
  and FF both went *down*, because a quarter as many loop iterations means
  smaller loop-control and address arithmetic, and neither engine added any
  per-lane datapath worth speaking of (4 int8 comparators for maxpool,
  literally nothing for upsample). Take these two unconditionally.
- **route is a genuine trade-off.** +5,150 LUT and +13 DSP buys 2.54×, but
  route is a small fraction of the frame to begin with, so the packing saves
  only **1.9 ms** (§7b). Compare maxpool, which saves **54.8 ms** for
  *negative* LUT cost. If LUT gets tight when all IPs are placed together,
  **route is the one to drop back to the baseline engine** — the three
  engines are independent IPs and can be mixed freely.

Bear in mind HLS `csynth` was measured ~2.5× pessimistic on LUT/FF for this
design (the real 4-IP implementation reported 37.81% LUT where csynth
predicted 92%), so route's real cost is likely closer to ~2k LUT than 5k.
Confirm against a real implementation run before treating the LUT delta as a
blocker.

### Remaining unknown

Package IP has not been re-run for this variant. The exported IP's register
map should be identical to the baseline's (same `s_axilite` ports, same
bundles), but confirm against the generated `x*_hw.h` rather than assuming —
that is exactly the check the `SW/*_hw_driver.h` header comments already
insist on.

## 8. Merge — DONE (2026-08-04)

These seven files were copied from `hls/pool_upsample_route_pack4/HW/` into
this project's `HW/`:

```
pack4.h
maxpool_engine.h        maxpool_engine.cpp
upsample_engine.h       upsample_engine.cpp
route_concat_engine.h   route_concat_engine.cpp
pool_upsample_route_tb.cpp
```

Nothing in `run_hls.tcl`, `run_hls.bat`, `vivado/`, or `python/` differed,
so nothing there was touched. The three `SW/*_hw_driver.h` files gained a
documentation-only "CALLER OBLIGATIONS" block for §4's contract.

See the status banner at the top of this file for exactly what was verified
after the merge, and for where the rollback copy lives.

### What is still outstanding

- **Cosim was not re-run on the merged tree.** It was run on the pack4 tree
  (§7a) against byte-identical sources, and the merged tree's csynth
  latencies match that tree's exactly, so the measured 3.74×/3.01×/2.54×
  carry over. Re-run it here if you want the numbers produced in this
  project rather than inherited.
- **The `route` LUT decision is deferred to implementation** (§7c). Both
  engines are available: packed is live now, baseline is in
  `baseline_pre_pack4_2026-08-04/HW/`.
- **Vivado has not been re-run.** The IPs in
  `pool_upsample_route_prj/solution_*/impl/ip` are new; the block design
  needs to pick them up. No BD *edit* is needed (§3), but the IP repo does
  need to be re-scanned and the design re-implemented.

## 9. `conv_engine_requant` — not packed *yet*, but it should be

A copy exists at `hls/conv_engine_requant_pack4`, currently **unmodified**.

I initially concluded the lever did not apply to conv, on the strength of
the comment above `READ_CH` in `conv_engine.cpp` (~line 411), which says
`READ_CH` is 12–139 cycles against `SHIFT_WINDOW`'s 49–3554 and is therefore
a minority of runtime. **That comment is stale.** In the current csynth
report — generated 14:13 today, newer than `conv_engine.cpp`'s 13:46 mtime —
`SHIFT_WINDOW` has since been optimized roughly 70× to 2–51 cycles, and
`READ_CH` is now the **largest single term** in `COL_LOOP` at 139 of 411
cycles (33.8%), ahead of `MAC_REDUCE` at 78 (19%).

So packing conv's ifmap read is worth roughly **23% of conv**, which —
because conv is ~94% of the frame — is about **5× more wall-clock than this
entire pool-engine change**. It is the highest-value item outstanding.

Conv's 4.3% efficiency is *also* structurally a serialization problem
(`MAC_REDUCE` is only 19% of `COL_LOOP`; everything else runs sequentially
with it), and that part does need load/compute overlap rather than packing.
Both are captured in `doc/action_items_2026-08-04_perf.md`.
