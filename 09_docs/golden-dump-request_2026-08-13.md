# 골든 모델 재덤프 요청 (2026-08-13)

수신: 골든 모델 담당
대상: `darknet_golden/artifacts_additional_ft_corrected_focus_v2/`

## 요약

전이학습 모델의 **가중치는 채택했습니다.** 다만 같은 폴더의 `int8_layers/`
레이어 덤프가 이전 세대 값이라, 이 가중치에 대한 정답지가 없는 상태입니다.
아래 두 가지만 재실행 부탁드립니다.

1. `int8_layers/` 재덤프 (README 4절)
2. `int8_decoded.npy` 생성 (현재 폴더에 INT8 디코드 결과가 없음)

## 근거

`int8_layers/` 25개 파일이 이전 세대 덤프와 **sha256까지 완전히 동일**합니다.

```
input_uint8.bin  layer_00.bin ... layer_23.bin      → 25/25 IDENTICAL
```

레이어 0으로 교차 확인한 결과입니다 (레이어 0은 입력이 `input_uint8.bin`으로
명시적이라 가중치와 덤프를 격리할 수 있는 유일한 레이어입니다):

| 조합 | 불일치 |
|---|---|
| 신규 `int8/` 가중치 → `int8_layers/layer_00.bin` | 1,765,876 / 2,359,296 (74.85%) |
| **이전 세대 가중치** → `int8_layers/layer_00.bin` | **0 / 2,359,296** |

즉 덤프가 이전 세대 가중치로 만들어졌습니다. `map_int8_600.json`은 실제로
움직였으므로(0.7494 → 0.7365) 모델 자체는 새것이 맞습니다 — 덤프만 옛것입니다.

### 원인 추정

덤프 파일 시각은 `17:33`으로, `int8/*.bin`(`17:24`)보다 **뒤**입니다. 즉 덤프
명령이 실행은 됐는데 다른 가중치 파일을 읽은 것으로 보입니다. 문서 안에 가중치
경로가 두 가지로 적혀 있는 점이 의심됩니다:

```
README 상단      : .../backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights
RTL_HANDOFF 상단 : .../backup/best.weights
```

`--weights` 인자가 어느 쪽이었는지 확인 부탁드립니다.

### 그 외

- `rtl_testbench_package.zip`(8/11 생성)의 내용물은 전부 2026-07-15 타임스탬프로,
  이전 세대 데이터가 압축된 것입니다.
- `rtl_compare_int8_report.txt`는 `/path/to/rtl/dump` 플레이스홀더로 실행되어
  전 레이어 `MISSING_RTL` 입니다.
- README 6.1의 패키지 목록은 `int8_layers_sample/`을 가리키는데 실제 폴더명은
  `int8_layers/` 입니다.

## 요청 명령 (README 4절 그대로)

```bash
$PY -m darknet_golden int8 \
  --image "$IMG" \
  --compare \
  --compare-report .../artifacts_additional_ft_corrected_focus_v2/compare.json \
  --dump-dir     .../artifacts_additional_ft_corrected_focus_v2/int8_layers \
  --decoded-out  .../artifacts_additional_ft_corrected_focus_v2/int8_decoded.npy
```

`--decoded-out` 옵션명이 다르면 fp32 쪽과 동일한 방식으로 INT8 디코드 결과
`(1, 2160, 10)` 텐서만 저장해 주시면 됩니다. PS 후처리 검증(TB-P)이 이 파일
하나 때문에 막혀 있습니다.

## 그동안 우리 쪽 처리

`python/gen_reference_chain.py` 로 24개 op 전체를 NumPy로 돌려 기준값을 자체
생성해 쓰고 있습니다 (`int8_layers_generated/`). 이 생성기는 **이전 세대에서
팀 골든과 24레이어 전부 비트단위 일치**하는 것을 먼저 확인한 뒤 사용합니다:

```bash
python3 python/gen_reference_chain.py --artifacts artifacts \
        --verify-against int8_layers_sample     # → 24/24 bit-exact
```

다만 이건 독립적인 정답지가 아니라 임시방편입니다. 재덤프가 오면 생성값과
대조한 뒤 `int8_layers_generated/` 를 지우고 원래대로 돌아갑니다.

## 하드웨어 영향

**없습니다.** 재학습이 바꾸는 값(requant multiplier/shift, scale)은 전부
AXI4-Lite 레지스터로 들어가는 런타임 인자라 RTL 에 박히지 않습니다. 비트스트림·
XSA 재빌드 불필요, FPS·타이밍·면적 전부 불변입니다.

단, **PS 쪽에 전달할 변경 2건**이 있습니다:

1. 레이어 0 **보정 bias 가 바뀌었습니다** (`bias'[oc] = bias[oc] + 128*Σw`,
   가중치의 함수라 재학습 시 반드시 함께 갱신) — `forteammate/03_layer0_contract/`
2. 두 detection head 의 `output_scale` 이동
   (0.2145 → 0.2946, 0.2063 → 0.3722) — 디코딩에 직접 들어가는 값
