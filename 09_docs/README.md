# PL → PS 전달 패키지

작성일: 2026-08-03
대상: `doc/request.md` (PS 담당 작성, 2026-08-03) 회신용
빌드 기준: Vivado 프로젝트 `yolo_sys`, implementation 완료 2026-07-30 11:43

---

## 빌드 식별자 (request.md §3, §4의 build ID 요청)

| 항목 | SHA-256 |
| --- | --- |
| `system_bringup_wrapper.xsa` | `9ea27e097fb778cb34bf1b7ea2805adf5ca04fd58e75c5a8df8f5f35b141aeff` |
| `system_bringup_wrapper.bit` | `871babf85f73f748d74e38d8ca5dd735c3661d7936f55cb1b1e5edf2852427d5` |

**XSA 내부에 포함된 `.bit`와 `01_xsa_bitstream/system_bringup_wrapper.bit`는 바이트 단위로 동일함**
(위 bit 체크섬이 양쪽 모두에 해당). 즉 XSA / bitstream / 이 패키지의 레지스터 헤더는
전부 같은 implementation run 산출물임.

전체 파일 체크섬은 `CHECKSUMS.sha256` 참조.

---

## 폴더 구성

### `01_xsa_bitstream/` — request.md §4
* `system_bringup_wrapper.xsa` — PetaLinux Device Tree / UIO 노드 생성용
* `system_bringup_wrapper.bit` — 보드 적재용 (XSA 내부 사본과 동일)

### `02_register_map/` — request.md §3
* `x{conv,maxpool,upsample,route_concat}_engine_hw.h`
  → **Vitis 자동 생성 레지스터 정본.** 손으로 관리하던 `*_hw_driver.h`의
  07-24 `+0x04`, 07-29 `route_concat` 오프셋 같은 동기화 오류가 원천적으로 없음.
  Linux UIO 구현은 이 헤더를 기준으로 할 것.
* `ADDRESS_MAP.md` — base address / range, m_axi ↔ HP 포트 연결, data width,
  클럭, 인터럽트 연결 상태
* `linux_ref/` — Xilinx 생성 `x*.h` / `x*_linux.c` / `x*_sinit.c`.
  UIO 기반 mmap 접근 구현 시 참고용

### `03_layer0_contract/` — request.md §2.2, §2.3
Layer 0의 UINT8→signed INT8 변환과 사전 패딩 계약의 실물.

| 파일 | 크기 | 내용 |
| --- | ---: | --- |
| `layer00_input.bin` | 447,180 B | **290 × 514 × 3, NHWC, signed INT8.** `s = u - 128` 적용 후 상하좌우를 `-128`로 1픽셀 사전 패딩한 것. `conv_engine`은 이 버퍼를 `pad=0`으로 읽음 |
| `layer00_bias.bin` | 64 B | **보정된 bias, int32 × 16.** `bias'[oc] = bias[oc] + 128 * sum(w[oc,:,:,:])`. 골든 원본 bias가 아니라 이 파일을 써야 함 |
| `layer00_weights.bin` | 432 B | int8, OIHW (16×3×3×3) |
| `layer00_expected_output.bin` | 2,359,296 B | Layer 0 출력 288×512×16 NHWC int8. 전처리+Layer0 검증용 |
| `real_layers.py` | — | 위 변환을 수행하는 원본 스크립트. `u-128`은 L229, 사전 패딩은 L254-255, bias 보정은 L258 |
| `REGENERATION.md` | — | **weight/model 버전 변경 시 재생성 절차** (§2.2 요청 항목, 2026-08-04 추가) |

> `real_layers.py`는 `python_teammate/darknet_golden` sibling 경로를 하드코딩하고 있어
> **이 패키지 안에서는 그대로 실행되지 않음** (request.md §9 지적 사항). 여기서는
> **변환 규칙의 참조 문서**로 첨부한 것이며, 위 `.bin` 파일들이 실제 산출물임.
>
> 재생성이 필요할 때는 `REGENERATION.md`가 안내하는
> `python/regen_layer0_contract.py`를 쓸 것 — 골든 트리 경로를 `--golden-dir` 인자로
> 받으므로 위 경로 문제가 없고, 재생성 결과를 골든 덤프와 bit-exact 비교해서 통과할
> 때만 파일을 씀. **위 4개 `.bin`은 전부 이 스크립트로 재현됨을 확인함**
> (2,359,296/2,359,296 일치, 2026-08-04).

### `04_golden_heads/` — request.md §2.4
두 raw head의 기대 출력. **HLS 도메인(NHWC)으로 저장되어 있음** — 골든 `.bin`의
NCHW가 아니므로 골든과 비교하려면 NHWC→NCHW transpose 후 비교할 것.

| 파일 | 크기 | shape | dequant scale |
| --- | ---: | --- | ---: |
| `head1_layer15_9x16x30_nhwc_int8.bin` | 4,320 B | `[9][16][30]` NHWC int8 | `0.21446585467481238` |
| `head2_layer22_18x32x30_nhwc_int8.bin` | 17,280 B | `[18][32][30]` NHWC int8 | `0.2062814967838798` |

크기는 request.md §2.4가 물어본 4,320 B / 17,280 B와 일치함.

### `05_layer_config/`
* `network_layers.h` — Conv 13개의 shape / kernel / stride / pad / requant / offset.
  `NETWORK_LAYERS[0]`이 `img_h=290, img_w=514, pad=0`인 것이 위 §2.3 계약과 대응.
  `weight_offset`은 int8 element 단위(=byte), `bias_offset`은 int32 element 단위(byte는 ×4).
* `layers_meta.json` — 같은 정보의 JSON 형태
* `*_hw_driver.h` 4종 — 기존에 전달했던 손관리 헤더. **정본은 `02_register_map/x*_hw.h`이며,
  이 파일들은 대조용으로만 포함함**

---

### `06_runtime_descriptor/` — request.md §6.3 **(2026-08-04 추가)**
* `network_descriptor.json` — 22-op runtime descriptor, 25,864 B.
  **90MB 검증 헤더 없이** PS 런타임이 전체 체인을 실행하는 데 필요한 설정값 전부.
  요청하신 필드는 모두 포함되어 있고, offset은 전부 byte로 통일. buffer lifetime
  (`free_after_op`)은 계산해서 넣음
* `README.md` — 요청 필드 ↔ JSON 위치 매핑표, 재생성 방법, 교차 검증 내역

생성 스크립트는 저장소의 `python/export_runtime_descriptor.py` (stdlib만 필요).

---

## 아직 포함되지 않은 것 (별도 작업 필요)

request.md에서 요청했으나 이 패키지로 답할 수 없는 항목:

* **§9 전체 22-op 체인 bit-exact 검증 결과** — 레이어별 mismatch 0 로그 미첨부.
  개별 op 검증은 모두 통과했으나 **22개를 이어 실행한 적이 없음** (보드 미확보).
  **남은 유일한 미제공 항목**
* **§7 인터럽트** — 현재 비트스트림은 인터럽트 미연결 (상세는 `ADDRESS_MAP.md` §4).
  필요 시 BD 수정 + 재빌드 필요

## 성능 관련 정정 (request.md §11)

인용하신 **16.5fps는 이미 100MHz 기준 수치가 맞음** (구현된 `ap_clk` = 99.999MHz).
다만 그 값은 **datapath 효율 100% 가정의 이론 상한**이며, 같은 산정표의 현실적 가정
(효율 40%)에서는 **약 6.6fps**임.

출처: `doc/plan_no_board_verification_and_perf.md` §0.4
(2.32 GMACs/frame, `PE_OC=24 × TR=16` = 384 MACs/cycle 기준)

| Clock | Peak | 100% 효율 | 40% 효율 (현실적) |
| --- | --- | ---: | ---: |
| **100MHz (현재 빌드)** | 38.4 GMAC/s | 16.5 fps | **~6.6 fps** |
| 200MHz | 76.8 GMAC/s | 33.1 fps | ~13.2 fps |

**효율 수치는 실측된 적이 없는 유일한 변수**이며, 실제 PL 처리량은 6.6~16.5fps
사이 어딘가일 가능성이 높음. request.md §1에서 16.5fps를 전제로 PS 큐를 설계 중이신
것으로 보이는데, **하한을 6.6fps로 잡고 설계하는 편이 안전함**. 실측은 아직 수행 전.

또한 §11이 질문한 포트 공유 구조는 다음과 같음: **8개 마스터가 `smartconnect_hp0`
하나를 거쳐 HP0 단일 포트로 수렴**하며, `conv_engine`의 `RD_BUS2`만 HP1로 분리됨.
모든 인터페이스가 32bit이므로 개별 상한은 약 400MB/s이고, HP0는 8-way 공유임.
