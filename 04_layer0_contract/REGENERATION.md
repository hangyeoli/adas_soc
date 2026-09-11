# Layer 0 보정 bias 재생성 절차

작성일: 2026-08-04
대상: `doc/request.md` §2.2 — "weight/model 버전이 바뀔 때 보정 bias를 함께 재생성하는 절차"
스크립트: `python/regen_layer0_contract.py`

---

## 1. 왜 절차가 필요한가

Layer 0만 DDR 계약이 "골든 모델의 바이트 그대로"가 아닙니다. 골든 모델과 `conv_engine`
사이에 변환 두 개가 있고, **둘 다 weight에서 유도됩니다.**

```text
s         = u - 128                              ← PS가 프레임마다 수행
bias'[oc] = bias[oc] + 128 * sum(w[oc,:,:,:])    ← 이 스크립트가 파일에 구워 넣음
```

두 가지가 문제입니다.

1. **둘은 짝입니다.** 한쪽만 적용해도 컴파일 오류도, 예외도, 크래시도 나지 않습니다.
   그럴듯해 보이는 틀린 feature map이 나옵니다.
2. **보정항이 weight의 함수입니다.** 따라서 **weight blob이 바뀌면 기존 보정 bias는
   그 즉시 무효**입니다. 파일 크기도 그대로(64B)고 형식도 그대로라서, 낡은 bias를
   계속 쓰고 있어도 아무것도 알려주지 않습니다.

이 문서와 스크립트는 "재생성을 기억해야 하는 일"을 없애기 위한 것입니다.

---

## 2. 언제 돌려야 하는가

| 상황 | 재생성 필요 |
| --- | --- |
| weight 재양자화 / 재학습 / fine-tune | **필수** |
| `model_manifest.json`의 offset·requant 값 변경 | **필수** |
| 샘플 입력 프레임(`input_uint8.bin`) 교체 | 입력·기대출력만 (bias는 불변) |
| HLS 코드 변경 | 불필요 (계약은 그대로) |
| Vivado 재빌드 | 불필요 |

판단이 애매하면 그냥 `--check`를 돌리십시오. 몇 초 안에 끝나고 드리프트가 있으면 알려줍니다.

---

## 3. 실행

```bash
# 현재 전달본이 지금의 골든 모델과 일치하는지 검사만 (아무것도 쓰지 않음)
python3 python/regen_layer0_contract.py --check

# 재생성 (검증 통과 시에만 파일을 씀)
python3 python/regen_layer0_contract.py

# 골든 트리가 다른 곳에 있을 때
python3 python/regen_layer0_contract.py --golden-dir /path/to/darknet_golden
```

필요한 것은 **numpy뿐**입니다. torch도 Vitis도 필요 없습니다.

입력으로 읽는 것 (`--golden-dir` 하위):

```text
artifacts/int8/model_manifest.json          offset, requant, activation
artifacts/int8/weight.bin                   layer 0 슬라이스 432 B
artifacts/int8/bias.bin                     layer 0 슬라이스 64 B
artifacts/int8_layers_sample/input_uint8.bin + input_manifest.json
artifacts/int8_layers_sample/layer_00.bin   + manifest.json   ← 검증 기준
```

출력 (기본 `forteammate/03_layer0_contract/`):

| 파일 | 크기 | 내용 |
| --- | ---: | --- |
| `layer00_weights.bin` | 432 B | int8 OIHW (16×3×3×3) |
| `layer00_bias.bin` | 64 B | **보정된** int32 × 16 |
| `layer00_input.bin` | 447,180 B | 290×514×3 NHWC signed int8, 사전 패딩 완료 |
| `layer00_expected_output.bin` | 2,359,296 B | 288×512×16 NHWC int8 |

---

## 4. 자체 검증 — 이 절차의 핵심

**스크립트는 재생성한 산출물로 Layer 0을 실제로 다시 계산해서 골든 덤프(`layer_00.bin`)와
byte 단위로 비교하고, 하나라도 다르면 파일을 쓰지 않고 중단합니다.**

틀린 보정 bias는 파일이 없는 것보다 나쁩니다. 없으면 즉시 알지만, 틀리면 탐지 결과가 조금씩
어긋날 뿐이라 한참 뒤에나 드러납니다. 그래서 경고가 아니라 hard stop으로 만들었습니다.

conv 수식(`conv2d_exact_nhwc`, `apply_activation`)은 다시 구현하지 않고
`hls/conv_engine_requant/python/real_layers.py`에서 import합니다. 원래 전달본을 만든 바로
그 코드이므로 스크립트가 그것과 갈라질 수 없습니다.

### 검증이 실제로 잡는 것 (2026-08-04 실측)

일부러 망가뜨려 확인한 결과:

| 조작 | mismatch | 결과 |
| --- | ---: | --- |
| weight 1개 변경 + 기존 bias 유지 | 55,650 / 2,359,296 | 잡힘 |
| 보정 없는 골든 원본 bias 사용 | 1,879,853 / 2,359,296 | 잡힘 |
| 테두리를 `-128` 대신 `0`으로 패딩 | 22,839 / 2,359,296 | 잡힘 |

첫 번째가 이 문서가 존재하는 이유 그 자체입니다 — **weight를 바꾸고 bias를 안 바꾼 경우.**

세 번째 22,839는 `real_layers.py:108` 주석에 기록된 값과 정확히 일치합니다(테두리 링
픽셀 수). 재현이 원본과 동일함을 보여주는 부수적 증거입니다.

---

## 5. 재생성 후 해야 할 일

산출물이 바뀌면(`CHANGED`) 스크립트가 알려주지만, 여기에도 남겨둡니다.

1. **`forteammate/CHECKSUMS.sha256` 재생성**

   ```bash
   cd forteammate && find . -type f ! -name CHECKSUMS.sha256 -print0 \
     | sort -z | xargs -0 sha256sum > CHECKSUMS.sha256
   ```

2. **PS 담당에게 bias 체크섬 변경을 알릴 것.** 낡은 bias blob을 계속 쓰면 조용히 틀립니다.
   회신 문서 `doc/reply_to_request_2026-08-04.md` §2.2의 체크섬 표도 갱신.

3. **`model_manifest.json`이 함께 바뀌었다면 descriptor도 재생성**

   ```bash
   python3 python/export_runtime_descriptor.py
   ```

   (그쪽도 manifest의 offset·requant를 교차 검증하므로, 불일치가 있으면 역시 중단합니다.)

---

## 6. 현재 상태 (2026-08-04)

```text
$ python3 python/regen_layer0_contract.py --check
  bias correction 128*sum(w) per oc: min=-2944 max=640
  verifying bit-exact against golden layer_00 dump ...
  OK - 2,359,296/2,359,296 bytes match
  layer00_weights.bin  432 B          unchanged
  layer00_bias.bin      64 B          unchanged
  layer00_input.bin    447,180 B      unchanged
  layer00_expected_output.bin  2,359,296 B  unchanged
  check OK
```

전달본 4개 파일 전부가 현재 골든 모델에서 재현됩니다. 즉 `forteammate/03_layer0_contract/`의
바이트는 출처가 확인된 것이며, 손으로 만든 일회성 산출물이 아닙니다.

---

## 부록. `real_layers.py`를 직접 쓰지 않는 이유

request.md §9에서 지적하신 대로 `real_layers.py`는 `python_teammate/darknet_golden`
sibling 경로를 하드코딩합니다. 이 저장소에서는 그 경로가 실제로 존재해서 동작하지만,
**`.py` 파일만 전달받은 쪽에서는 동작하지 않습니다** — `forteammate/03_layer0_contract/`에
넣어드린 사본이 그 경우입니다.

그래서 이 스크립트는 `--golden-dir`로 경로를 받고, 수식만 `real_layers.py`에서 import합니다.
경로 문제는 해결하면서 계산의 단일 정본은 유지하는 구성입니다.

또한 `real_layers.py`는 13개 conv 레이어를 전부 처리하는 스크립트라 Layer 0 계약만 필요할
때 돌리기에는 무겁습니다. 이 스크립트는 Layer 0만 다룹니다.
