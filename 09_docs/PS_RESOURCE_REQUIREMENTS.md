# PS Resource Requirements

> 기준: 2026-08-04 PL–PS 계약 및 22-op runtime descriptor
>
> 범위: PS 소프트웨어가 KR260에서 확보·관리·측정해야 하는 자원만 기록한다.

## 1. 요약

PS가 직접 관리하는 핵심 자원은 다음과 같다.

| 자원 | PS에서 하는 일 |
| --- | --- |
| APU CPU | 카메라 캡처, 전처리, MMIO 제어, polling, decode/NMS, 출력 |
| 외부 DDR | 입력·weight·bias·accum·feature map·head용 연속 buffer 확보 |
| CPU cache | CPU와 PL 사이 buffer ownership 전환 시 sync |
| AXI4-Lite MMIO | 네 HLS IP의 register mapping과 start/done/timeout 제어 |
| V4L2 buffer | USB camera frame 획득과 bounded latest-frame queue 관리 |
| Linux BSP | Device Tree/overlay, allocator, UIO 또는 driver binding 구성 |

BRAM, UltraRAM, DSP, LUT/FF의 선택과 utilization은 이 문서의 범위가 아니다. PS는 PL 내부 구현이 아니라 공개된 register·DDR·timing contract를 소비한다.

## 2. APU CPU

APU에서 실행되는 작업:

- V4L2 frame dequeue 및 YUYV→BGR 변환
- BGR→RGB, 512×288 direct resize, HLS input packing
- HLS IP register programming
- `AP_DONE` polling과 timeout 검사
- raw head dequantization, YOLO decode 및 class-wise NMS
- frame rendering/MJPEG 및 성능 계측

PL 연산 자체는 APU CPU cycle을 사용하지 않지만 polling과 cache sync는 CPU 시간을 사용한다. 다음 값을 분리해 측정한다.

- capture FPS
- preprocessing time
- accelerator wall time
- polling CPU time
- cache sync time
- decode/NMS time
- end-to-end frame age
- dropped frame count

## 3. 외부 DDR와 연속 메모리

현재 descriptor에서 재사용을 적용하지 않은 accelerator runtime 요구량은 29,927,308 B다. Linux에서 총량뿐 아니라 **가장 큰 단일 연속 block**을 확보할 수 있는지가 중요하다.

| 버퍼 | 크기 | PS 작업 |
| --- | ---: | --- |
| `accum` scratch | 14,155,776 B | 단일 연속 block 1개 할당, 모든 Conv가 재사용 |
| weights | 8,672,688 B | 초기화 시 1회 적재 |
| bias | 12,976 B | 초기화 시 1회 적재 |
| feature buffers | 최대 2,359,296 B/개 | descriptor lifetime에 맞춰 할당·재사용 |
| Layer-0 input | 447,180 B | 프레임마다 PS가 작성 |
| detection head 1 | 4,320 B | PL 완료 후 PS가 읽음 |
| detection head 2 | 17,280 B | PL 완료 후 PS가 읽음 |

Linux allocator 후보는 CMA, udmabuf, dma-buf 또는 reserved-memory다. 실보드에서 다음을 확인한 뒤 방식을 확정한다.

1. 최소 14,155,776 B 단일 연속 할당 성공 여부
2. 64-bit device/physical address 취득 가능 여부
3. CPU/device ownership sync API 제공 여부
4. mmap 및 process 종료 시 lifetime 정리 여부
5. boot 후 장시간 실행과 반복 할당에서의 안정성

필수 alignment는 4 B이고 4 KiB 정렬을 권장한다. PL에 전달하는 주소는 allocator가 보장한 실제 device address를 사용하며 임의의 DDR 물리 주소를 하드코딩하지 않는다.

## 4. Cache ownership

프레임마다 전체 30 MB를 sync하지 않는다. CPU가 실제로 접근하는 경계 buffer만 ownership을 전환한다.

| 시점/버퍼 | PS 접근 | 필요한 동작 |
| --- | --- | --- |
| 초기 weights/bias 적재 | CPU write → PL read | 최초 실행 전 device 방향 sync 1회 |
| CPU가 초기화·zero-fill한 영역 | CPU write → PL read/write | 최초 PL ownership 전달 전 sync 1회 |
| Layer-0 input 447,180 B | 프레임마다 CPU write → PL read | `AP_START` 전 device 방향 sync |
| 중간 feature/`accum` | CPU 접근 없음 | 정상 실행 중 op 사이 sync 없음 |
| heads 총 21,600 B | PL write → CPU read | `AP_DONE` 후 CPU 방향 sync |

정규 프레임당 sync 대상은 약 469 KB다. 디버깅 목적으로 중간 feature map을 CPU가 읽는 경우에만 해당 buffer에 CPU 방향 sync를 추가한다.

수동 cache instruction을 직접 호출하기보다 선택한 Linux DMA buffer API의 ownership 전환 semantics를 따른다.

## 5. AXI4-Lite MMIO

PS가 mapping할 control window:

| IP | 물리 base | mapping 범위 |
| --- | ---: | ---: |
| Conv | `0xA0000000` | 64 KiB |
| MaxPool | `0xA0010000` | 64 KiB |
| Upsample | `0xA0020000` | 64 KiB |
| Route/Concat | `0xA0030000` | 64 KiB |

PS는 generated `x*_hw.h`를 정본으로 사용한다. 64-bit pointer는 LO/HI register에 나누어 쓰며, `weights`와 `weights_hi`에는 동일한 device address를 쓴다.

현재 interrupt가 연결되지 않아 polling을 사용한다. polling loop count는 Linux scheduling과 CPU frequency에 따라 의미가 달라지므로 timeout은 `CLOCK_MONOTONIC` 또는 `std::chrono::steady_clock` 기반 wall-clock deadline으로 구현한다.

계산상 최대 단일 op는 40% 효율 가정에서 44.2 ms지만 실측값이 아니다. 초기 timeout은 수백 ms 범위의 설정 가능한 값으로 두고, timeout 발생 시 다음을 기록한다.

- op index, manifest index, kind
- 시작 시각과 경과시간
- `AP_CTRL` 값
- input/output device address
- descriptor 및 bitstream build ID

## 6. V4L2와 frame queue

현재 camera 입력은 `/dev/video0`, YUYV 640×480이다. V4L2 MMAP buffer는 kernel/camera driver가 관리하고, `cvtColor` 이후의 BGR frame은 APU 메모리를 사용한다.

PL 처리량은 계산상 약 6.6~16.5 fps이고 camera는 약 29 fps이므로 무제한 queue를 사용하지 않는다.

- queue depth는 1~2의 latest-frame 방식으로 시작
- 가득 차면 오래된 frame drop
- capture timestamp 유지
- processing FPS와 frame age 분리 측정
- drop count 기록
- 종료 시 대기 중인 producer/consumer 깨우기

## 7. Device Tree와 Linux 구성

PS가 관리할 BSP 항목:

- 네 AXI4-Lite control node의 `reg`
- UIO 또는 최종 platform driver binding
- 필요 시 CMA 크기 또는 reserved-memory node
- 64-bit address와 DMA mask 확인
- PL overlay 적용/제거 및 build ID 관리
- 현재 polling 구성과 향후 IRQ 추가 시 `interrupts` 반영

XSA, bitstream, generated header와 descriptor가 같은 build인지 checksum으로 확인한 뒤 적용한다.

## 8. 향후 RPU 자원

RPU 통합 단계에서는 다음 PS 자원이 추가된다.

- Cortex-R5F execution time과 bare-metal memory
- APU–RPU shared DDR 또는 OCM region
- cache ownership과 message sequence
- UART controller 및 TX/RX buffer
- timeout, heartbeat 및 fail-safe state

이 자원은 현재 APU–PL accelerator memory와 분리해 설계하고, shared-memory layout과 UART packet을 별도 contract로 관리한다.
