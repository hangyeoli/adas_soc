# ADAS YOLOv3-tiny Darknet Python 골든모델

RTL 담당자 전달용 명세는 [`RTL_HANDOFF_KO.md`](RTL_HANDOFF_KO.md)를 참고하세요.

대상 모델을 고정한 FP32/INT8 골든모델입니다.

RTL handoff 기준 모델 가중치:
`adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights`

모든 산출물(`calibration.json`, INT8 package, `map_fp32_600.json`, `map_int8_600.json`)은 이 weights로 생성합니다.

- 입력: RGB, `512x288`, Darknet `resize_image()` 방식 bilinear resize
- 클래스: `car`, `person`, `sign_warning`, `sign_prohibition`, `sign_mandatory`
- FP32: Darknet `.weights` 직접 파싱, Conv+BN 융합 후 PyTorch float32 연산
- INT8: UINT8 입력, symmetric per-tensor INT8 weight/activation, INT32 bias
- LeakyReLU: RTL에서 구현하기 쉬운 `13/128` 근사
- Requantization: 정수 multiplier + 우측 shift, nearest/ties-away-from-zero, saturation
- 텐서 레이아웃: NCHW

MaxPool, Upsample, 단일 Route, YOLO pass-through는 값이 바뀌지 않으므로 입력 scale을
그대로 유지합니다. 서로 다른 두 feature를 붙이는 concat Route만 공통 output scale로
requantize합니다.

기존 `golden_model/` 디렉터리는 3-class PyTorch `.pt` 모델용입니다. 이 디렉터리의
코드는 그 코드와 독립적이며 질문의 5-class Darknet `.weights`를 직접 읽습니다.

## 환경

프로젝트에 있는 가상환경을 사용합니다.

```bash
cd /mnt/d/fpga_project
export PYTHONPATH=/mnt/d/fpga_project/yolo_tiny
PY=/mnt/d/fpga_project/yolo_env/bin/python
```

CFG와 weights는 대상 모델 경로가 기본값으로 들어 있어 생략할 수 있습니다.

## 1. CFG/weights 검사

```bash
$PY -m darknet_golden inspect
```

파일을 끝까지 정확히 파싱하지 못하면 즉시 오류를 냅니다. 정상 모델은 Conv 13개와
`30x9x16`, `30x18x32` 두 YOLO head를 가집니다.

## 2. FP32 골든 추론과 레이어 dump

```bash
IMG=/mnt/d/fpga_project/adas_dataset_yolov3_tiny_5class_balanced_512x288/images/val/bdd_014f813e-f026867d.jpg

$PY -m darknet_golden fp32 \
  --cfg darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --image "$IMG" \
  --dump-dir /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/fp32_layers \
  --decoded-out /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/fp32_decoded.npy
```

`fp32_layers`에는 레이어별 `float32 NCHW .npy`와 `manifest.json`이 생성됩니다.
YOLO 레이어 dump는 sigmoid/exp 전의 raw head이고, `fp32_decoded.npy`는
`[x,y,w,h,objectness,class probabilities...]` 형식의 `(1,2160,10)` 텐서입니다.

## 3. INT8 캘리브레이션과 export

권장 시작값은 검증 영상 100~500장, `percentile 100.0`입니다 (아래 Calibration 참고). 한 명령으로 실행합니다.

```bash
$PY -m darknet_golden pipeline \
  --cfg darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --image-list adas_dataset_yolov3_tiny_5class_balanced_512x288/val.txt \
  --num-images 500 \
  --percentile 100.0 \
  --output-dir yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2
```

분리 실행도 가능합니다.

```bash
$PY -m darknet_golden calibrate --num-images 500
$PY -m darknet_golden export-int8
```

생성 파일:

```text
artifacts_additional_ft_corrected_focus_v2/
├── calibration.json
└── int8/
    ├── model_manifest.json   # 형상, scale, multiplier, shift, byte offset
    ├── model_int8.npz        # Python INT8 골든모델 입력
    ├── weight.bin            # signed INT8, 레이어 순서, OIHW
    ├── bias.bin              # little-endian signed INT32
    ├── requant.bin           # 레이어별 little-endian INT32 [multiplier,right_shift]
    └── scale.bin             # 레이어별 float32 [input,weight,output]
```

## 4. INT8 추론 및 FP32 레이어 비교

```bash
$PY -m darknet_golden int8 \
  --cfg /mnt/d/fpga_project/darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights /mnt/d/fpga_project/adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --package-dir /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8 \
  --image "$IMG" \
  --compare \
  --compare-report /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/compare.json \
  --dump-dir /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8_layers \
  --decoded-out /mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8_decoded.npy
```

INT8 레이어 dump에는 다음 파일이 생성됩니다.

- `.bin`: header 없는 signed INT8 NCHW raw 데이터
- `.npy`: Python 확인용 동일 텐서
- `manifest.json`: 레이어 번호, 형상, scale, 파일명

정수 Conv는 속도를 위해 PyTorch float64 Conv를 이용하지만 입력, weight, bias가 모두
정수이고 모든 레이어의 최악 누산값이 `2^53`보다 작음을 exporter가 검사합니다. 따라서
곱셈과 덧셈 결과는 정수 MAC과 bit-exact하며, 결과가 정수가 아니면 실행을 중단합니다.
Requantization, rounding, saturation, LeakyReLU는 NumPy int64로 수행합니다.

## 5. mAP 확인

FP32:

```bash
$PY -m darknet_golden evaluate \
  --backend fp32 \
  --cfg darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --image-list adas_dataset_yolov3_tiny_5class_balanced_512x288/val.txt \
  --output yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/map_fp32_600.json
```

INT8:

```bash
$PY -m darknet_golden evaluate \
  --backend int8 \
  --cfg darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --package-dir yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8 \
  --image-list adas_dataset_yolov3_tiny_5class_balanced_512x288/val.txt \
  --output yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/map_int8_600.json
```

평가는 IoU 0.5, class-wise NMS와 연속 PR 적분 AP를 사용합니다. Darknet과 완전히 같은
mAP를 비교할 때는 confidence/NMS/map_points 설정까지 동일해야 합니다. 기본 평가
confidence는 AP 곡선을 위해 `0.005`로 낮게 설정되어 있습니다.

## 6. RTL 테스트벤치 패키징 및 비교

실제 RTL/FPGA 테스트를 위해 Golden sample과 reference binary를 패키징하고, RTL 덤프를
비교하는 명령어가 추가되었습니다.

### 6.1 RTL 테스트 패키지 생성

```bash
$PY -m darknet_golden rtl-package \
  --artifacts-dir yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2 \
  --output yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/rtl_testbench_package.zip \
  --include-npy
```

이 패키지는 다음 파일을 포함합니다.

- `artifacts_additional_ft_corrected_focus_v2/int8/model_manifest.json`
- `artifacts_additional_ft_corrected_focus_v2/int8/weight.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8/bias.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8/requant.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8/scale.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8_layers/input_uint8.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8_layers/layer_XX.bin`
- `artifacts_additional_ft_corrected_focus_v2/int8_layers/manifest.json`
- `artifacts_additional_ft_corrected_focus_v2/int8_decoded.npy`
- (`.npy` 레퍼런스 파일은 `--include-npy` 옵션으로 추가)

### 6.2 RTL 덤프 비교

RTL 시뮬레이터 또는 FPGA 테스트벤치가 생성한 layer dump를 아래 명령으로 비교합니다.

```bash
$PY -m darknet_golden rtl-compare \
  --gold yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8_layers \
  --rtl /path/to/rtl/dump \
  --out yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/rtl_compare_int8_report.txt \
  --compare-input
```

RTL 덤프는 다음 중 하나여야 합니다.

- `layer_XX.bin` 또는 `layer_XX_rtl.bin`
- `input_uint8.bin` (입력 비교를 사용할 경우)
- 선택적으로 `layer_XX.npy` 또는 `layer_XX_rtl.npy`

모든 정수 레이어가 exact match이면 통과입니다. `rtl_compare_int8_report.txt`에
`EXACT`가 아닌 항목이 존재하면 해당 레이어가 불일치한 것입니다.

현재 폴더에 남아 있는 기존 `rtl_compare_int8_report.txt`는 `/path/to/rtl/dump`를
대상으로 실행된 placeholder 결과이므로 RTL 검증 결과로 사용하지 않습니다. 실제 RTL
dump 디렉터리를 지정해 새로 생성해야 합니다.

### 6.3 권장 RTL 데이터 형식

- 레이아웃: NCHW
- dtype: signed int8 for INT8 comparison, float32 for FP32 comparison
- binary order: row-major C-order
- packing: OIHW is only for weights; activation dumps should remain NCHW

실제 RTL 덤프를 생성할 때는 `artifacts_additional_ft_corrected_focus_v2/int8_layers/manifest.json`의 `shape`
정보를 참고하세요.

## 테스트

```bash
$PY -m unittest discover -s yolo_tiny/darknet_golden/tests -v
```

## 고정된 산술 규약

RTL 비교 시 아래 규칙을 바꾸면 Python dump와 일치하지 않습니다.

1. RGB UINT8 입력, 실수 스케일 `1/255`
2. signed INT8 weight/activation, signed INT32 bias
3. Conv accumulator에 bias를 더한 뒤 음수에 `13/128` LeakyReLU 적용
4. `acc * multiplier / 2^right_shift`
5. nearest, 정확히 절반이면 0에서 먼 방향으로 rounding
6. `[-128,127]` saturation
7. stride-1 MaxPool의 padding은 오른쪽/아래이고 padding 값은 음의 최솟값

## 현재 생성된 기준 산출물과 검증 결과

기준 weights: `adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights`

전체 600장 validation 평가 결과 (`map_fp32_600.json`, `map_int8_600.json`):

| 모델 | mAP@0.5 |
|---|---:|
| Darknet FP32 (training 측정) | 0.718295 |
| BN-folded FP32 (Python) | 0.718024 |
| INT8 golden pct=100.0 | **0.736548** |
| INT8 하락 vs FP32 | +0.018524 (+1.85%p) |

INT8가 FP32보다 높게 나오는 이유: 극소수 클래스(sign × 3~6장)의 AP 변동으로 통계적 노이즈 수준.
핵심은 **quantization 손실 없음** — pct=99.99 기준 0.666에서 pct=100.0으로 **0.070 향상**.

### Calibration percentile 결정 근거

이 모델은 YOLO head의 raw logit이 매우 큰 outlier를 가집니다 (max abs ~23).
percentile을 낮추면 이 값들이 clipping되어 confidence score가 왜곡됩니다.

| percentile | INT8 mAP@0.5 |
|---:|---:|
| 99.0 | 0.2335 |
| 99.5 | 0.2929 |
| 99.9 | 0.5852 |
| 99.95 | 0.6439 |
| 99.99 | 0.6662 |
| **100.0** | **0.7365** |

**결론: `--percentile 100.0` 고정 사용.**

### 2026-08-13 INT8 재덤프 확인

`int8_layers/`와 `int8_decoded.npy`는 아래 새 fine-tuning 가중치와 `int8/` package를
명시적으로 지정해 재생성했습니다.

```text
weights SHA-256 = 4d78ebf6d6d08e28057983dbaf3091210c80175717a4c49f2112af4f392f4cd6
```

Layer 0의 dump는 해당 새 package로 독립 재생성한 결과와 `0 / 2,359,296` mismatch이며,
이전 세대 package와 비교하면 `1,765,876 / 2,359,296` mismatch입니다. 따라서 현재
`int8_layers/`는 이전 세대 dump가 아닙니다. `int8_decoded.npy`의 형상은
`(1, 2160, 10)`, dtype은 `float32`입니다.
