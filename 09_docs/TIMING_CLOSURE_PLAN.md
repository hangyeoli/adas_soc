# 200 MHz 타이밍 클로저 분석 및 수정 계획

**대상**: `D:/final_project/hls/cnn_accel_bringup` (system_bringup_wrapper)
**디바이스**: xck26-sfvc784-2LV-c (KV260, speed grade -2LV)
**분석 기준 리포트**: `cnn_accel_bringup.runs/impl_1/system_bringup_wrapper_timing_summary_routed.rpt` (2026-08-05 15:46, Routed)
**작성일**: 2026-08-05

---

## 0. 요약

`conv_engine_bringup` / `yolo_sys`가 아니라 **`hls/cnn_accel_bringup`** 프로젝트가 타이밍을 미충족합니다.
PL 클럭을 100 MHz → 200 MHz로 올리면서 **21 ps** 차이로 놓쳤습니다.

| 프로젝트 | clk_pl_0 | WNS | TNS | Failing EP | 상태 |
|---|---|---|---|---|---|
| `conv_engine_bringup` | 10.0 ns (100 MHz) | +2.233 | 0.000 | 0 | MET |
| `yolo_sys` | 10.0 ns (100 MHz) | +1.715 | 0.000 | 0 | MET |
| **`hls/cnn_accel_bringup`** | **5.0 ns (200 MHz)** | **−0.021** | **−0.305** | **35** | **VIOLATED** |

- Hold는 클린: WHS **+0.010** / THS 0.000 / 0 failing
- Pulse width 클린: WPWS **+1.000** / 0 failing
- 실측 Fmax = 1 / (5.0 + 0.021) = **199.16 MHz**

> 참고: 위반 endpoint 35개는 모두 MAC 데이터패스의 **실제 setup 위반**입니다. false path가 아니므로 waive는 선택지가 아닙니다.

---

## 1. 실패 경로 위치

실패 endpoint 35개는 **전부 `conv_engine_0` 내부**이며, 사실상 하나의 모듈에 집중되어 있습니다.

```
system_bringup_i/conv_engine_0/inst/
  grp_conv_engine_Pipeline_MAC_REDUCE_MAC_KY_MAC_KX_fu_2559/
    add_ln952_*_reg_*_reg[19]     <- 대다수
    add_ln953_*_reg_*_reg[*]
```

`add_ln952` / `add_ln953` = **`HW/conv_engine.cpp:952-953`**, 즉 TREE_L3(이진 트리 리덕션 마지막 단)의 출력 레지스터입니다.

```cpp
// conv_engine.cpp:949-953
TREE_L3:
    for (unsigned i = 0; i < 2; i++) {
#pragma HLS UNROLL
        lo3[i] = lo2[2 * i] + lo2[2 * i + 1];   // <- add_ln952
        hi3[i] = hi2[2 * i] + hi2[2 * i + 1];   // <- add_ln953
    }
```

상위 10개 경로 중 8개가 위 패턴이고, 나머지 2개는 URAM 주소 경로입니다:

```
grp_conv_engine_Pipeline_WINDOW_TAIL_FILL_WINDOW_TAIL_FILL_STEP_fu_2277/ic_step_fu_234_reg[0]/C
  -> .../ram_reg_uram_1/ADDR_A[6]      (slack -0.017, route 3.186 / 3.981 = 80%)
```

physopt 로그가 개선한 net 목록도 동일 계층에 집중되어 있습니다
(`add_ln952_*`, `scan_and_compute.../ram_reg_*/SPO|DPO`, `mul_*/DSP_A_B_DATA.B_ALU<0>`).

---

## 2. Worst path (−0.021 ns) 예산 분해

```
Requirement                        5.000 ns
  Data Path Delay                  4.728    (logic 1.766 = 37.4% / route 2.962 = 62.6%)
  Clock Path Skew                 -0.207    (DCD 2.966 - SCD 3.358 + CPR 0.185)
  Clock Uncertainty               -0.129    (TSJ 0.071, DJ 0.248, PE 0.000)
  Setup (Setup_DFF_SLICEM_C_D)    +0.043
                                  --------
  arrival  8.085 / required 8.065
  Slack                           -0.021
```

- **Logic Levels: 11** — `CARRY8 x4, LUT3 x2, LUT4 x2, LUT5 x1, LUT6 x2`
- Source FF: `SLICE_X53Y108`, Destination FF: `SLICE_X32Y168` (클럭 리전을 가로지름)
- Clock net delay: source 3.091 ns / destination 2.750 ns (BUFG_PS, **fanout 54,972**)

### 한 클럭 안에 들어있는 것 (conv_engine.cpp:770~957)

```
empty_105_reg_34099_pp0_iter3_reg  (= `if (ic < ic_count)` 술어 FF, fo=21)   <- 경로 시작
  -> LUT3  (add_ln953_128_reg[18]_i_15)                    0.136
  -> LUT6  (add_ln953_2_reg[18]_i_11)          net fo=68   0.654  <-- 고팬아웃
  -> LUT4  (add_ln952_reg[19]_i_101)           net fo=136  0.623  <-- 고팬아웃
  -> mul_24s_8s_32_1_1_U542 : LUT4 -> CARRY8 -> CARRY8     net    0.628
  -> mul_24s_8s_32_1_1_U540 : LUT3 -> LUT5 -> LUT6 -> CARRY8 -> CARRY8
  -> add_ln952_2_reg_39440_reg[19]/D                       <- TREE_L3 레지스터
```

즉 **16-lane guard mux + TREE_L1 + TREE_L2 + TREE_L3 가 전부 한 파이프라인 스테이지**에 묶여
CARRY8 체인 4단을 5 ns 안에 통과해야 하는 구조입니다.

**주목**: 경로 위 단 3개 net(0.654 + 0.623 + 0.628 = **1.905 ns**)이 전체 데이터패스의 **40%** 를 차지하며,
그중 둘은 fanout 68 / 136 입니다.

---

## 3. 근본 원인

### 원인 A — HLS가 타이밍 예산을 100% 소진한 채 넘겨줌

`conv_engine_prj/solution1/syn/report/conv_engine_csynth.rpt`:

```
+--------+---------+----------+------------+
|  Clock |  Target | Estimated| Uncertainty|
+--------+---------+----------+------------+
|ap_clk  |  5.00 ns|  3.650 ns|     1.35 ns|
+--------+---------+----------+------------+
```

`3.650 = 5.00 − 1.35` — **정확히 예산 경계**에 스케줄링했다는 뜻입니다.
uncertainty 1.35 ns(기본값 27%)는 route가 데이터패스의 63~70%를 먹는 이 설계에서는 부족했습니다.

### 원인 B — DSP48E2에 내부 파이프라인 레지스터가 하나도 없음

`conv_engine_Pipeline_MAC_REDUCE_MAC_KY_MAC_KX_csynth.rpt`:

```
| Instance                | Module            | BRAM_18K| DSP| FF| LUT | URAM|
| mul_24s_8s_32_1_1_U522  | mul_24s_8s_32_1_1 |        0|   1|  0|   40|    0|
| mul_24s_8s_32_1_1_U523  | mul_24s_8s_32_1_1 |        0|   1|  0|   40|    0|
  ...                                                        ^^^^ FF = 0
```

`conv_engine.cpp:860`의 `ap_int<33> product = x * packed;`가 DSP에 매핑은 됐지만
**AREG/BREG/MREG/PREG를 하나도 쓰지 않는 순수 조합 DSP**입니다.

physopt 로그가 이를 확인해 줍니다:
```
INFO: [Physopt 32-952] Improved path group WNS = -0.059. Processed net:
  .../mul_24s_8s_32_1_1_U716/tmp_product/DSP_A_B_DATA.B_ALU<0>
```

### 원인 C — URAM 100% 포화 → 배치 확산 → route/skew 폭증

`system_bringup_wrapper_utilization_placed.rpt`:

```
| Site Type      |  Used | Available | Util% |
| CLB LUTs       | 54648 |    117120 | 46.66 |
| CLB Registers  | 39890 |    234240 | 17.03 |
| CARRY8         |  3665 |     14640 | 25.03 |
| Block RAM Tile |     5 |       144 |  3.47 |   <-- 거의 안 씀
| URAM           |    64 |        64 |100.00 |   <-- 포화
| DSPs           |   329 |      1248 | 26.36 |
```

URAM 컬럼을 전부 쓰기 때문에 `conv_engine_0`이 `SLICE_X27~X53`, `Y108~Y168`로 클럭 리전을 걸쳐 퍼졌고,
그 결과:

- **클럭 스큐만 −0.207 ns** — 미달분(−0.021)의 약 10배.
  소스/데스티네이션 clock insertion delay가 3.091 vs 2.750으로 0.341 ns 벌어짐
- route가 데이터패스의 62.6~80%를 차지
- Router congestion: North 88.26% / South 90.05% (effective congestion level 1 — 심각하진 않음)

### 부수 원인 — post-route phys_opt 미실행

`impl_1/`에 `.post_route_phys_opt_design.begin.rst` / `.end.rst` 파일이 없습니다
(Vivado 기본 전략에서 이 스텝은 비활성). 라우터 내부 physical synthesis(Phase 14)만 돌아
**−0.122 → −0.021** 까지 끌어온 상태이고, 독립 post-route physopt 단계는 아직 쓰지 않은 카드입니다.

```
INFO: [Route 35-57]   Estimated Timing Summary | WNS=-0.122 | TNS=-5.120 |
INFO: [Physopt 32-668] Current Timing Summary  | WNS=-0.108 | TNS=-3.907 |
INFO: [Physopt 32-669] Post Physical Optimization Timing Summary | WNS=-0.021 | TNS=-0.305 |
```

---

## 4. 수정 계획

### Tier A — Vivado 설정만 변경 (소스 무수정 / 재구현 ~1시간 / 예상 +0.05~0.15 ns)

−0.021 ns면 이것만으로 닫힐 가능성이 있습니다.
다만 **seed 의존적인 "마진 없는 통과"** 이므로 Tier B도 함께 진행할 것을 권장합니다.

```tcl
# --- post-route phys_opt 활성화 (현재 미실행 - 가장 확실한 free lever) ---
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED true            [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveExplore [get_runs impl_1]

# --- 고팬아웃 net(fo=68/136)이 경로의 40%를 먹고 있으므로 fanout opt 강화 ---
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true                        [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveFanoutOpt     [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE  ExtraTimingOpt            [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE  AggressiveExplore         [get_runs impl_1]

# --- 로그상 place/route가 2 CPU로만 돌았음 (QoR가 아닌 런타임 개선) ---
set_param general.maxThreads 8

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
```

또는 전략 통째로 교체:
```tcl
set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
```

---

### Tier B — HLS 데이터패스 수정 (진짜 해결책 / 반나절)

#### B1. DSP 내부 파이프라인 레지스터 사용 — **최우선 권장**

`HW/conv_engine.cpp:860`

```cpp
// 변경 전
ap_int<33> product = x * packed;

// 변경 후
ap_int<33> product = x * packed;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=2
```

DSP의 MREG/PREG를 켜서 곱셈기를 fabric 논리와 양쪽 모두에서 절연합니다.
`latency=2`로 먼저 시도하고 부족하면 `3`으로 올립니다.

- **예상 이득**: +0.3 ~ 0.6 ns
- **비용**: 파이프라인 깊이 +2 사이클 (II=1 유지), FF 소폭 증가
- **원인 B의 직접 처방**

#### B2. HLS clock uncertainty 상향

`run_hls.tcl:113` 부근

```tcl
create_clock -period $CLOCK_NS -name default
set_clock_uncertainty 2.0     ;# 기본 1.35 (27%) -> 2.0 (40%)
```

HLS 스케줄러가 TREE_L1 / TREE_L2 / TREE_L3 사이에 레지스터를 삽입하도록 강제합니다.

- **예상 이득**: +0.5 ~ 1.0 ns
- **비용**: 파이프라인 +1~2단. MAC_REDUCE는 II=1이고 trip count가 최대 `8×3×3 = 72`이므로 스루풋 손실 3% 미만
- **원인 A의 직접 처방**
- 검증 지표: 재합성 후 `conv_engine_csynth.rpt`의 Estimated가 **3.0 ns 이하**로 떨어지는지 확인

#### B3. `ic < ic_count` guard를 크리티컬 스테이지에서 제거

Worst path의 **시작점**이 바로 이 술어 레지스터(`empty_105_reg_34099_pp0_iter3_reg`)이고,
CARRY8 체인에 닿기 전에 LUT 3단(0.136 + 0.654 + 0.623 = 1.413 ns)을 먹습니다.

`conv_engine.cpp:825-843` 주석에 따르면 이 guard가 존재하는 유일한 이유는
"`window[]` / `wtile_packed[]`의 `ic >= ic_count` 영역에 이전 ic_tile의 stale 데이터가 남아 있어서"입니다.
**로드 시점에 0으로 채우면 guard 자체가 불필요**해집니다 (0 기여 = guard와 산술적으로 동일).

- `LOAD_WTILE` / `SHIFT_WINDOW`에서 `ic ∈ [ic_count, MAX_IN_CH)` 구간을 0-fill
- `conv_engine.cpp:844-899`의 `if (ic < ic_count)` 분기 제거, `lo0[t] / hi0[t]`를 무조건 대입

- **예상 이득**: +0.3 ~ 0.5 ns
- **비용**: 로드 루프 사이클 소폭 증가 (MAC 루프 대비 무시할 수준)
- **주의**: `conv_engine_tb.cpp`의 config-F가 `ic_count % TR != 0` 케이스를 정확히 커버하므로 반드시 C-sim으로 회귀 확인

#### B4. (선택) TREE_L1을 DSP 포스트애더로 매핑

`acc_lo` / `acc_hi`에는 이미 동일 pragma가 걸려 있습니다 (`conv_engine.cpp:757-758`).

```cpp
TREE_L1:
    for (unsigned i = 0; i < 8; i++) {
#pragma HLS UNROLL
        lo1[i] = lo0[2 * i] + lo0[2 * i + 1];
        hi1[i] = hi0[2 * i] + hi0[2 * i + 1];
    }
#pragma HLS BIND_OP variable=lo1 op=add impl=dsp
#pragma HLS BIND_OP variable=hi1 op=add impl=dsp
```

CARRY8 한 단이 크리티컬 스테이지에서 빠집니다. DSP는 26%만 쓰므로 여유가 있습니다.

- **주의**: DSP가 멀리 배치되면 오히려 route가 나빠질 수 있음. **반드시 실측 후 채택/폐기 판단**

---

### Tier C — 배치 개선 (route 63% / skew 0.207 ns 공략)

#### C1. URAM 압력 해소 — **비용 대비 효과 최상**

URAM 100% / BRAM 3.47%라는 극단적 불균형이 배치 확산의 구조적 원인입니다.

`conv_engine.cpp:349`
```cpp
#pragma HLS BIND_STORAGE variable=line_buf type=RAM_1P impl=URAM
```

`line_buf` 중 일부(또는 한 차원)를 `impl=BRAM`으로 돌리면 URAM 컬럼이 풀려 배치 자유도가 크게 올라갑니다.
BRAM은 144타일 중 5개만 쓰고 있어 여유가 충분합니다.

- **예상 이득**: 클럭 스큐 −0.207 ns 중 상당 부분 + route 지연을 동시에 회수
- **비용**: BRAM 사용량 증가, 레이턴시 특성 변화 가능 (BRAM은 URAM과 read latency가 다를 수 있으므로 cosim 확인 필요)

#### C2. (C1으로 부족할 때만) Pblock으로 conv_engine 국소화

```tcl
create_pblock pblock_conv
add_cells_to_pblock [get_pblocks pblock_conv] \
    [get_cells system_bringup_i/conv_engine_0]
resize_pblock [get_pblocks pblock_conv] -add {CLOCKREGION_X0Y0:CLOCKREGION_X1Y3}
```

- **주의**: LUT가 이미 46.66%이므로 **느슨하게 시작**할 것.
  과도하게 조이면 congestion(현재 global max 88~90%)이 터져 오히려 악화됩니다.
- 실제 디바이스 플로어플랜을 보고 URAM/DSP 컬럼 위치에 맞춰 사이징해야 합니다.

---

### Tier D — 폴백 (성능 양보)

- 실측 Fmax = **199.16 MHz**. `pl_clk0`을 **195 MHz**로만 낮춰도 통과합니다.
- 안전하게 **187.5 MHz (5.333 ns)** 면 여유가 넉넉하지만 스루풋 6.25% 손실.
  README의 30 FPS 게이트와 충돌하는지 먼저 확인 필요.
- **waive는 불가**: 35개 실패 endpoint는 MAC 데이터패스의 진짜 setup 위반입니다.

---

## 5. 권장 실행 순서

| 단계 | 작업 | 목표 | 예상 소요 |
|---|---|---|---|
| 1 | **Tier A** 적용 후 재구현 | 통과 여부 확인 (마진 없는 통과라도) | ~1.5 h |
| 2 | **B1 + B2** 동시 적용 → HLS 재합성 | `csynth.rpt` Estimated ≤ 3.0 ns | ~1 h |
| 3 | `rebuild_conv.tcl` 방식으로 IP 교체 → 재구현 | **WNS ≥ +0.5 ns** 확보 | ~1.5 h |
| 4 | 부족 시 **B3 → C1** 순차 적용 | 추가 마진 | 반나절 |
| 5 | 그래도 부족하면 **C2 → Tier D** | 최후 수단 | — |

> `yolo_sys/rebuild_conv.tcl`에 IP 재수출 → OOC 재합성 → impl → XSA 재생성 흐름이
> 이미 작성되어 있으므로, `cnn_accel_bringup`에 맞게 경로만 바꿔 재사용하면 됩니다.

---

## 6. 검증용 명령

```tcl
open_checkpoint D:/final_project/hls/cnn_accel_bringup/cnn_accel_bringup.runs/impl_1/system_bringup_wrapper_routed.dcp

# 실패 endpoint 전체 목록 (35개)
report_timing_summary -delay_type max -max_paths 40 -slack_lesser_than 0

# 어떤 계층이 문제인지 정량화
report_timing -to [get_cells -hier -filter {NAME =~ *MAC_REDUCE*add_ln95*}] \
              -max_paths 40 -sort_by group

# route 지배 여부 / congestion 원인 분석
report_design_analysis -timing -congestion -complexity -max_paths 20

# 배치 확산 확인 (worst path cell들의 물리 위치)
report_timing -max_paths 1 -nworst 1 -path_type full_clock_expanded

# 고팬아웃 net 확인 (경로의 40%를 차지한 net들)
report_high_fanout_nets -timing -load_types -max_nets 30

# DSP 내부 레지스터 사용 여부 확인 (B1 적용 후)
get_property USE_MULT [get_cells -hier -filter {REF_NAME =~ DSP*}]
report_property [lindex [get_cells -hier -filter {NAME =~ *mul_24s_8s_32_1_1*tmp_product*}] 0]
```

---

## 7. 참고 파일 경로

| 내용 | 경로 |
|---|---|
| 타이밍 리포트 (routed) | `hls/cnn_accel_bringup/cnn_accel_bringup.runs/impl_1/system_bringup_wrapper_timing_summary_routed.rpt` |
| 사용률 리포트 | `hls/cnn_accel_bringup/cnn_accel_bringup.runs/impl_1/system_bringup_wrapper_utilization_placed.rpt` |
| impl 실행 로그 | `hls/cnn_accel_bringup/cnn_accel_bringup.runs/impl_1/runme.log` |
| HLS 합성 리포트 | `hls/conv_engine_requant_merged/conv_engine_prj/solution1/syn/report/conv_engine_csynth.rpt` |
| MAC_REDUCE 리포트 | `.../report/conv_engine_Pipeline_MAC_REDUCE_MAC_KY_MAC_KX_csynth.rpt` |
| HLS 소스 | `hls/conv_engine_requant_merged/HW/conv_engine.cpp` (MAC_REDUCE: 770~957행) |
| HLS 헤더 | `hls/conv_engine_requant_merged/HW/conv_engine.h` (PE_OC=32, TR=16, partial_t=ap_int<28>) |
| HLS 빌드 스크립트 | `hls/conv_engine_requant_merged/run_hls.tcl` (CLOCK_NS=5.0) |
| IP 재빌드 스크립트 (참고) | `yolo_sys/rebuild_conv.tcl` |
