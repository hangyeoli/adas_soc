# 22-op runtime descriptor — request.md §6.3

생성일: 2026-08-04
생성 스크립트: `python/export_runtime_descriptor.py` (저장소 루트, stdlib만 사용)
대상 빌드: XSA `9ea27e09…`, bit `871babf8…` (2026-07-30 impl)

```
network_descriptor.json   25,864 B   22 ops / 22 buffers
```

요청하신 대로 **90MB짜리 검증 헤더 없이** PS 런타임이 전체 체인을 실행할 수 있는 설정값만
담았습니다. `real_layers_data.h`(66MB) + `real_pool_upsample_route_data.h`(24MB)에서
골든 검증 배열을 제외한 나머지입니다.

---

## 1. 요청 필드 매핑

| request.md §6.3 요청 필드 | JSON 위치 |
| --- | --- |
| op kind / manifest index | `ops[].kind`, `ops[].manifest_index` |
| input buffer index / source buffer 목록 | `ops[].input.buffer` (conv/pool/upsample), `ops[].src0.buffer` / `src1.buffer` (route) |
| output buffer index | `ops[].output.buffer` |
| dtype / signedness / layout / byte size / alignment | `buffers[]` 각 항목 |
| lifetime | `buffers[].consumed_by_ops`, `buffers[].free_after_op` |
| input/output H, W, C | `ops[].input.{h,w,c}`, `ops[].output.{h,w,c}` |
| kernel / stride / padding | `ops[].kernel`, `.stride`, `.padding` |
| maxpool stride / pad_right / pad_bottom | `ops[].stride`, `.pad_right`, `.pad_bottom` |
| upsample factor | `ops[].factor` |
| route source 및 channel 결합 순서 | `ops[].src0/src1`, `ops[].concat_order` |
| weight / bias offset | `ops[].weight_offset_bytes`, `.bias_offset_bytes` |
| conv requant multiplier / shift / leaky enable | `ops[].requant_multiplier`, `.requant_shift`, `.leaky_relu_enable` |
| route source별 requant enable / multiplier / shift | `ops[].src0.requant`, `.src1.requant` |
| output scale | `ops[].output_scale` |
| schema version / model version / artifact SHA-256 | `schema_version`, `source_sha256`, `bitstream` |

---

## 2. 읽으실 때 알아두실 것

### 2.1 offset은 전부 byte로 통일했습니다

§6.2에서 지적하신 대로 원본은 세 곳의 단위가 서로 달랐습니다
(`weight_offset` = int8 element, `bias_offset` = int32 element, manifest = byte).
**이 JSON은 전부 byte입니다.** `bias_offset_bytes`에 다시 4를 곱하지 마십시오.

### 2.2 버퍼 인덱스는 manifest index와 같습니다

`buffers[].buffer`는 그 값을 생산한 레이어의 manifest index입니다. 16과 23(yolo)은
하드웨어 op이 아니므로 버퍼도 없습니다. 즉 인덱스가 0..22 중 16이 빠진 형태입니다.

### 2.3 재사용 시 버퍼 8과 13을 주의하십시오

`free_after_op`이 이걸 위해 있습니다. 두 버퍼는 **바로 다음 op이 읽은 뒤에도 살아있어야
합니다.**

| 버퍼 | 생산 | 소비 | 해제 가능 시점 |
| ---: | ---: | --- | --- |
| 8 | op8 | op9, **op19(route 20의 src1)** | op19 이후 |
| 13 | op13 | op14, **op16(route 17의 src0)** | op16 이후 |

나머지 20개는 전부 다음 op이 유일한 소비자입니다. 이 값들은 손으로 적은 게 아니라
`in_buf`/`src0_buf`/`src1_buf` 연결을 훑어서 계산한 것입니다.

### 2.4 detection head 2개는 `is_detection_head: true`

버퍼 15(4,320B)와 22(17,280B)만 소비하는 op이 없습니다 — PS가 읽는 값이기 때문입니다.

### 2.5 register가 아닌 값

`window: 2` (maxpool)와 `factor: 2` (upsample)는 **HLS 컴파일 타임 상수**이며 레지스터가
아닙니다. 프로그래밍하실 필요 없고, 참고용으로만 넣었습니다. 나머지 필드는 전부 실제로
AXI4-Lite에 써야 하는 값입니다.

### 2.6 `accum`은 conv 공용 scratch 1개

`ops[].accum_bytes`는 그 conv이 실제로 쓰는 양이고, `memory.accum_scratch_bytes`
(14,155,776 B)가 **전체에서 하나만 잡으면 되는 크기**입니다. conv마다 따로 잡지 마십시오.

---

## 3. 메모리 요약 (`memory` 필드)

| 항목 | byte |
| --- | ---: |
| Layer 0 입력 (290×514×3, 사전 패딩 포함) | 447,180 |
| weight 전체 | 8,672,688 |
| bias 전체 | 12,976 |
| accum scratch (공용 1개) | 14,155,776 |
| 중간 feature map 22개 (재사용 없음) | 6,638,688 |
| **합계 (재사용 없음)** | **29,927,308** (약 29.9 MB) |

`free_after_op`을 이용해 재사용하시면 feature map 부분은 6.6MB보다 줄어듭니다. 다만
버퍼 8과 13의 장수명 제약(§2.3) 때문에 단순 ping-pong 2버퍼로는 줄일 수 없습니다.

---

## 4. 재생성 방법

```bash
python3 python/export_runtime_descriptor.py           # 기본 출력 경로
python3 python/export_runtime_descriptor.py -o out.json
```

stdlib만 필요합니다 — numpy도, Vitis도, 골든 아티팩트 디렉터리도 필요 없습니다.

스크립트는 값을 새로 계산하지 않고 아래 네 곳에서 읽어 모읍니다. 각 필드의 단일 정본이
어디인지가 `generated_from`에 기록되며, 그 파일들의 SHA-256이 `source_sha256`에
들어갑니다.

| 내용 | 정본 |
| --- | --- |
| op 순서 / 버퍼 연결 | `hls/conv_engine_requant/SW/network_run_full.c` |
| conv 설정 + offset | `hls/conv_engine_requant/SW/network_layers.h` |
| maxpool stride/pad, upsample/route 인덱스 | `hls/pool_upsample_route/python/real_pool_upsample_route_layers.py` |
| route source requant, output scale | `python_teammate/darknet_golden/artifacts/int8/model_manifest.json` |

### 교차 검증

스크립트는 아래를 검사하고, 하나라도 어긋나면 **JSON을 쓰지 않고 중단**합니다. 잘못된
descriptor는 컴파일 오류가 아니라 조용히 틀린 추론 결과로 나타나므로 의도적으로
엄격하게 했습니다.

* conv의 weight/bias offset과 requant 값을 `model_manifest.json`의 독립적인 값과 대조
* 모든 op의 선언된 입력 shape이 그 버퍼를 생산한 op의 출력 shape과 일치하는지
* route 두 소스의 spatial 크기 일치
* 모든 maxpool에 stride/pad 항목이 존재하는지
* 가장 큰 conv의 accum 요구량이 `MAX_ACCUM_ELEMS` 이내인지

---

## 5. 아직 아닌 것

* **이 값들은 하드웨어 실행으로 검증된 것이 아닙니다.** 22-op 체인은 아직 보드에서
  돌려본 적이 없습니다 (request.md §9 / 회신 문서 §9). 개별 op 검증은 통과했습니다.
* 실측 후 이 descriptor의 값이 바뀔 가능성은 낮지만, 바뀌면 `schema_version`을 올리고
  다시 전달드립니다.
