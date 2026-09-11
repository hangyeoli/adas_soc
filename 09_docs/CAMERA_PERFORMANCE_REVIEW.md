# 카메라 통합 및 성능 점검

## 최종 실측 (2026-09-11)

아래 100프레임 수치는 V4L2 버퍼 1개인 기준 측정이다. 이후 캡처 개선으로 버퍼 4개를 적용했다.
단독 30프레임 비교는 1버퍼 3.84 fps, 4버퍼 7.11 fps였으며 순차 측정이라 조명/노출 변화가
영향을 줄 수 있다. 이는 FPGA throughput 증가의 증거는 아니다.

- 100프레임 FPGA 평균 1343.488 ms, P50 1343.137 ms, P95 1343.867 ms, P99 1351.903 ms.
- 전처리부터 서버 게시까지 평균 1368.725 ms, P95 1373.097 ms.
- OpenCV read 완료부터 게시까지 평균 1503.673 ms, P95 1622.156 ms. 센서 노출과 브라우저 지연 제외.
- 캡처 평균 3.792 fps, 누적 최신 프레임 skip 420. 최초 단독 기준 27.61 fps와 구분해야 한다.
- 시스템 CPU 평균 4.237%, 온도 평균 28.242°C, CMA free 484228 KiB.
- Top 3: 57.60%, Top 5: 71.77%. Conv 전체가 IP 시간의 약 90.2%.
- `audit_camera.py --fpga`: 실제 카메라 실행기의 FPGA head 두 개 byte-exact 통과,
  저장 샘플 자동차 3개 (score 0.6132, 0.4935, 0.3674).
- 실시간 카메라 장면: 100프레임 검출 0. 실제 장면의 올바른 BBox 검증은 미완료.

[22-op 전체 순위와 통계](../10_verification_reports/board_2026-09-11/latency-ranking.md),
[프레임별 CSV](../10_verification_reports/board_2026-09-11/benchmark.csv),
[FPGA 검출 계약 검사](../10_verification_reports/board_2026-09-11/camera-contract-fpga.json).

## 영상 표시 오류

4버퍼 변경 후 별도 20프레임 통합 시험에서 캡처 평균 7.042 fps, P50 7.491 fps,
FPGA 평균 1343.664 ms를 확인했다. OpenCV read 완료→게시 평균은 1439.680 ms였다.
100프레임 기준 시험과 표본 수가 다르므로 성능 비교 시 구분한다.
[개선 후 20프레임 결과](../10_verification_reports/board_2026-09-11/benchmark-buffer4-20frames.json).

UI는 인증 헤더로 JPEG를 가져와 `URL.createObjectURL()`로 표시하지만 서버 CSP의
`img-src`에 `blob:`이 없어 브라우저가 영상을 차단했다. 서버에 `blob:`을 허용했다.
클라이언트는 이미지 로딩 성공 후 영상을 표시하고 HTTP 오류를 빈 화면 대신 안내한다.
상태 조회 간격은 2초에서 1초로 줄이고 새 프레임만 가져온다. 이는 표시 지연 개선이며
FPGA 추론 속도를 높이는 변경은 아니다. 기존 토큰 인증을 유지한다.

## 고정된 입력/출력 계약

| 항목 | 계약 |
| --- | --- |
| 카메라 | OpenCV V4L2, BGR uint8, 640×480 |
| Crop | `frame[60:420, :]`, 640×360 |
| Resize | OpenCV INTER_LINEAR, 512×288 |
| 채널 | BGR → RGB |
| 골든 양자화 | UINT8 pixel, scale=1/255, zero point=0 |
| FPGA 전송 | `s = pixel - 128`, signed INT8 NHWC, 정규화 중복 적용 없음 |
| signed 표현 | 원래 값은 `(s+128)/255`; 대응 zero point=-128 |
| Border | 1픽셀 -128, 버퍼 290×514×3, Layer 0 hardware pad=0 |
| Layer 0 bias | `bias + 128 * sum(weights)` |
| Head | NHWC INT8 → layer별 output scale 곱하기 |
| Decode | sigmoid xy/objectness/class, exp wh, manifest anchor/mask |
| Score / NMS | objectness × 최대 class probability ≥ 0.25, class별 IoU 0.45 |

`python 11_board_app/audit_camera.py`는 골든 입력 바이트, 보정 bias, 구분 가능한 색의 crop,
독립적인 NCHW 디코더, NMS class 분리를 검사한다. 저장 샘플의 디코딩 결과는 자동차 3개다.
이 결과는 실시간 카메라의 객체 검출 정확도나 mAP 검증을 대체하지 않는다.

## 병목과 최적화 순서

저장 샘플 기준 상위 5개는 Conv 0, Conv 12, Conv 2, Conv 21, Pool 1이다.
100프레임 결과의 전체 순위와 단계별 통계는 검증 보고서의 `latency-ranking.md`에 기록한다.
IP 시작→AP_DONE 관측 시간은 FPGA 계산, DDR 대기, Python polling 지연을 포함한다.
`runtime_ms - fpga_total_ms`만으로 polling 비용을 계산할 수 없다.

소스의 `PE_OC=24`, `TR=16`은 이상적으로 384 INT8 MAC/반복이다. 두 MAC을 packing한
192 multiplier lane을 사용하지만 커널 위치와 channel tile은 반복하며, read/shift/MAC/finish가
모두 동시에 수행되는 구조는 아니다. 모든 Conv/Pool/Route/Upsample 출력은 DDR 버퍼다.
Conv는 output-channel tile마다 입력을 다시 읽고 input-channel tile 사이에는 INT32 accum
scratch를 DDR에 기록/재읽기한다. 따라서 단순히 MAC 수를 늘리는 것만으로 해결되지 않는다.
Descriptor의 전체 Conv 연산량은 약 2.321G MAC/프레임이다. 100 MHz × 384 MAC의
이론 peak는 38.4G MAC/s이나, 이것을 실제 지속 처리량으로 간주하면 안 된다.
22개 출력 버퍼 합계는 6,638,688 bytes이며 전체 DDR 트래픽은 반복 입력 읽기와 scratch
전송 때문에 이보다 크다. 버퍼 할당 합계는 정렬 전 29,927,308 bytes이다.

1. **Conv 0 전용 입력 경로:** 입력 3채널은 TR 16 중 3개, 출력 16채널은 PE 24 중 16개만
   유효하다. `READ_CH_ELEMS`는 같은 32-bit word를 채널마다 다시 읽을 수 있다. RGB 3채널
   순차 word 캐시/행 버퍼와 packed output burst를 먼저 별도 실험한다. 입력 padding과 보정
   bias 계약을 보존하고 경계/정답 비교를 통과한 뒤 합성한다.
2. **Conv 12:** OC/IC tile 반복 입력 읽기와 accum read/write를 AXI trace로 계량한다.
   MAC 병렬성 증가보다 read/compute/write의 겹침 및 tile 재사용을 비교한다.
3. **Pool 1:** 4픽셀 읽기 pass와 초기화/쓰기 loop가 각 출력 위치마다 반복된다.
   행 버퍼와 연속 burst, Conv 0→Pool 1 streaming fusion의 효과를 비교한다.
4. **자원 한계:** 포함된 2024.2 csynth는 Conv URAM 64/64, LUT 61%, DSP 17%다.
   BRAM/URAM에 중간 출력을 전부 넣을 수 있다고 가정하면 안 된다. 로컬 설치는 2021.1이므로
   동일한 합성 결과를 보장하지 않는다. 후보 변경은 csim/cosim, place-and-route, 새 bitstream,
   실제 전체 head 비교를 거친 뒤에만 성능 개선으로 보고한다.
5. IRQ는 우선순위가 낮다. 단독 polling A/B와 장치 cycle counter 없이는 절감량을 단정하지 않는다.

## 재측정

카메라 UI 작업을 중지한 뒤 보드에서:

```bash
sudo python3 11_board_app/camera.py --frames 100
python3 11_board_app/summarize_benchmark.py 11_board_app/results/benchmark.json
```

`benchmark.csv`는 프레임별 22-op latency, 입력 준비, 전처리, decode/NMS, JPEG 게시,
처리 시간, 출력 간격, capture FPS, skip 수, CMA 사용량, 시스템 CPU 사용률과 온도를 기록한다.
JSON은 평균/P50/P95/P99를 담는다. `processing_ms`는 선택한 프레임 전처리 시작부터
JSON 저장까지이며, 센서 노출·USB 대기·네트워크·브라우저 표시까지 포함한 진정한 end-to-end
시간은 아니다. JPEG/UI 항목은 서버 측 JPEG 인코딩/파일 게시 시간이다.
프레임 skip 수는 의도적으로 최신 프레임만 선택한 수이며 V4L2 드라이버 drop 수와 다르다.
`frame_available_to_publish_ms`는 OpenCV read 완료부터 서버 결과 게시까지이며,
센서 노출·카메라 내부 버퍼·브라우저 지연은 포함하지 않는다. CMA 사용량은 시스템 전체다.
