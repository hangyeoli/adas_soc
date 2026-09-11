# YOLOv3-tiny INT8 RTL 인수인계 및 요구사항

## 전달할 때 보낼 메시지

> ADAS 5-class YOLOv3-tiny의 INT8 Python 골든모델과 검증 벡터입니다.  
> `artifacts_additional_ft_corrected_focus_v2/int8/model_manifest.json`을 기준 명세로 사용해 주세요. 입력은 RGB UINT8
> 512x288 NCHW이고, Conv weight는 signed INT8 OIHW, bias는 signed INT32입니다.
> 샘플 입력과 모든 레이어의 기대 출력은 `artifacts_additional_ft_corrected_focus_v2/int8_layers/`에 있습니다.
> 기준 weights: `adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights`, SHA-256 `4d78ebf6d6d08e28057983dbaf3091210c80175717a4c49f2112af4f392f4cd6`, calibration percentile=100.0.
> RTL 시뮬레이션 결과를 레이어별 `.bin`과 비교하여 mismatch 0을 맞춰 주세요.
> FPGA에서는 두 raw YOLO head까지만 출력하면 되고 sigmoid/exp, box decode, NMS는
> 소프트웨어에서 처리할 예정입니다.

## 1. 작업 범위

KR260 PL에서 다음 연산을 처리하는 INT8 YOLOv3-tiny inference 엔진을 구현합니다.

- Conv 3x3 / 1x1, stride 1, zero padding
- INT32 bias add
- LeakyReLU
- 정수 requantization, rounding, INT8 saturation
- MaxPool 2x2 stride 2 및 2x2 stride 1
- Nearest-neighbor Upsample x2
- Route와 channel concat
- 최종 raw YOLO head 두 개 출력

RTL 범위에 포함하지 않는 항목:

- 이미지 디코딩 및 512x288 resize
- sigmoid, exp와 anchor 기반 box decode
- confidence filtering, NMS, mAP 계산

## 2. 기준 파일

기준 경로:

```text
/mnt/d/fpga_project/yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2
```

| 파일 | 내용 |
|---|---|
| `int8/model_manifest.json` | 최종 기준 명세. 레이어 형상, scale, binary offset, multiplier/shift |
| `int8/weight.bin` | 8,672,688 bytes, signed INT8, OIHW |
| `int8/bias.bin` | 12,976 bytes, little-endian signed INT32 |
| `int8/requant.bin` | 120 bytes, little-endian INT32 multiplier/shift. 반드시 manifest offset 사용 |
| `int8/scale.bin` | 156 bytes, little-endian float32. 분석용이며 RTL 계산에는 불필요 |
| `int8/model_int8.npz` | Python에서 weight/bias를 확인할 때 사용 |
| `int8_layers/input_uint8.bin` | 샘플 입력, header 없는 UINT8 NCHW |
| `int8_layers/layer_XX.bin` | 각 레이어의 기대 출력, header 없는 signed INT8 NCHW |
| `int8_layers/manifest.json` | 레이어 dump 형상과 scale |
| `int8_decoded.npy` | PS 후처리 검증용 INT8 decode 결과, float32 `(1,2160,10)` |

`model_manifest.json`의 byte offset과 shape가 다른 문서보다 우선합니다.

## 3. 입출력 규약

### 입력

```text
shape       = [1, 3, 288, 512]
layout      = NCHW, W가 가장 빠르게 증가
dtype       = UINT8
color       = RGB
scale       = 1/255
zero point  = 0
```

샘플 검증 시에는 `input_uint8.bin`을 그대로 입력해야 합니다. 실제 시스템에서 resize와
RGB 변환은 PS/전처리 블록이 담당합니다.

### 출력

```text
첫 번째 raw head  = layer 15/16, [1, 30, 9, 16], signed INT8
두 번째 raw head  = layer 22/23, [1, 30, 18, 32], signed INT8
```

5개 클래스이므로 head channel은 `3 anchors x (5 + 5 classes) = 30`입니다. 출력은
sigmoid/exp 적용 전 raw tensor입니다.

## 4. Binary 배치 순서

Weight는 OIHW C-order입니다.

```text
weight[o][i][ky][kx]
```

`kx`가 가장 빠르고 그다음 `ky`, input channel, output channel 순입니다. Feature map은
NCHW C-order이며 `W -> H -> C -> N` 순으로 증가합니다. RTL 내부에서 별도 packing을
사용해도 되지만, 입력 로더와 시뮬레이션 출력 변환 결과는 이 순서와 일치해야 합니다.

## 5. 반드시 일치시킬 정수 연산

Zero point는 모두 0입니다. Conv 계산 순서는 다음과 같습니다.

```text
acc = sum(input_q * weight_q) + bias_q

if activation == leaky and acc < 0:
    acc = round_shift(acc * 13, 7)

out_q = saturate_int8(round_shift(acc * multiplier, right_shift))
```

`multiplier`와 `right_shift`는 각 Conv의 manifest 값을 사용합니다. signed rounding은
nearest, 정확히 절반이면 0에서 먼 방향입니다.

```text
round_shift(x, s) = sign(x) * ((abs(x) + 2^(s-1)) >> s)
```

- LeakyReLU는 `0.1` 대신 정확히 `13/128`을 사용합니다.
- LeakyReLU는 requantization 전에 accumulator에 적용합니다.
- 출력은 `[-128, 127]`로 포화합니다.
- 마지막 head Conv의 activation은 linear이므로 LeakyReLU를 적용하지 않습니다.
- BN은 이미 weight/bias에 융합되어 있으므로 RTL BatchNorm은 필요 없습니다.
- manifest의 최대 accumulator bound는 74,421,303이므로 signed 32-bit 누산 범위 안입니다.
  중간 곱셈 `acc * multiplier`에는 충분히 넓은 비트폭을 사용해야 합니다.

## 6. MaxPool, Route, Upsample 규칙

- MaxPool은 비교 연산이므로 입력 scale을 그대로 유지합니다.
- Layer 11의 2x2 stride-1 MaxPool은 오른쪽과 아래에 한 칸 padding합니다.
- MaxPool padding 값은 signed INT8 `-128`로 처리합니다.
- Upsample은 nearest-neighbor 단순 2배 복제이며 scale을 유지합니다.
- Layer 17 Route는 layer 13을 그대로 통과시킵니다.
- Layer 20 concat 순서는 `[layer 19, layer 8]`, 즉 128채널 뒤에 256채널을 붙여
  총 384채널입니다.
- Layer 20의 두 입력은 manifest의 `source_requantization` multiplier/shift로 각각
  requantize한 뒤 concat합니다.

## 7. 네트워크 실행 순서

| Layer | 연산 | 출력 CHW |
|---:|---|---:|
| 0 | Conv3x3 + Leaky | 16x288x512 |
| 1 | MaxPool s2 | 16x144x256 |
| 2 | Conv3x3 + Leaky | 32x144x256 |
| 3 | MaxPool s2 | 32x72x128 |
| 4 | Conv3x3 + Leaky | 64x72x128 |
| 5 | MaxPool s2 | 64x36x64 |
| 6 | Conv3x3 + Leaky | 128x36x64 |
| 7 | MaxPool s2 | 128x18x32 |
| 8 | Conv3x3 + Leaky, route 보관 | 256x18x32 |
| 9 | MaxPool s2 | 256x9x16 |
| 10 | Conv3x3 + Leaky | 512x9x16 |
| 11 | MaxPool s1 | 512x9x16 |
| 12 | Conv3x3 + Leaky | 1024x9x16 |
| 13 | Conv1x1 + Leaky, route 보관 | 256x9x16 |
| 14 | Conv3x3 + Leaky | 512x9x16 |
| 15 | Conv1x1 linear, head 1 | 30x9x16 |
| 17 | Route layer 13 | 256x9x16 |
| 18 | Conv1x1 + Leaky | 128x9x16 |
| 19 | Upsample x2 | 128x18x32 |
| 20 | Concat layer 19, 8 | 384x18x32 |
| 21 | Conv3x3 + Leaky | 256x18x32 |
| 22 | Conv1x1 linear, head 2 | 30x18x32 |

Layer 16과 23은 YOLO 표시용 pass-through이므로 별도 하드웨어 연산이 없습니다.

## 8. 검증 및 완료 조건

검증은 한 번에 전체 출력만 보지 말고 layer 0부터 순서대로 수행합니다.

```text
RTL output layer XX
vs
int8_layers/layer_XX.bin
```

필수 완료 조건:

1. 샘플 입력에서 모든 구현 레이어의 형상과 element 수 일치
2. 모든 레이어의 signed INT8 mismatch count가 0
3. 최종 두 raw head가 Python dump와 bit-exact 일치
4. weight/bias/requant offset 적용 내역 제출
5. 시뮬레이션 비교 로그와 mismatch 검사 스크립트 제출
6. 합성 후 timing, LUT/FF/BRAM/URAM/DSP 사용량과 예상 latency/FPS 제출

±1 오차 허용을 기본으로 하지 않습니다. 차이가 발생하면 먼저 signed rounding, saturation,
LeakyReLU 순서, Route concat 순서와 stride-1 MaxPool padding을 확인해 주세요.

## 9. Python 재현 명령

```bash
cd /mnt/d/fpga_project
export PYTHONPATH=/mnt/d/fpga_project/yolo_tiny

./yolo_env/bin/python -m darknet_golden int8 \
  --cfg darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg \
  --weights adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/yolov3-tiny-adas-5class-balanced-512x288_best.weights \
  --package-dir yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8 \
  --image adas_dataset_yolov3_tiny_5class_balanced_512x288/images/val/bdd_014f813e-f026867d.jpg \
  --compare \
  --compare-report yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/compare.json \
  --dump-dir yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8_layers \
  --decoded-out yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2/int8_decoded.npy
```

Python 구현 기준 코드는 `darknet_golden/quantization.py`의 `Int8GoldenModel.forward()`입니다.
