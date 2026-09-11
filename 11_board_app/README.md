# KR260 보드 검증 UI

Ubuntu의 실제 FPGA에 저장된 INT8 입력을 넣어 정답과 비교하고, USB 카메라 프레임을
실시간 추론하는 도구입니다. 저장 샘플 검증에는 카메라나 PyTorch, PYNQ가 필요하지 않습니다.

프로젝트 소개와 최초 설치 순서는 [프로젝트 README](../README.md)를 참고하세요.
아래 명령은 보드에 프로젝트와 필요한 시스템 구성요소가 준비된 상태에서 실행합니다.

## 실행

```bash
cd ~/KR260_ADAS_SoC
sudo apt-get update
sudo apt-get install -y python3 python3-opencv gcc make libc6-dev device-tree-compiler linux-headers-$(uname -r)
make -C 11_board_app/dma_bridge
sudo install -D -m 644 11_board_app/dma_bridge/kr260_dma.ko /lib/modules/$(uname -r)/extra/kr260_dma.ko
sudo depmod -a
sudo modprobe kr260_dma
sudo python3 11_board_app/hardware.py load
sudo python3 11_board_app/hardware.py layer0
sudo python3 11_board_app/hardware.py full
sudo cp 11_board_app/kr260-adas-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kr260-adas-ui
```

브라우저에서 `http://<KR260_IP>:8080`을 열면 상태와 결과를 볼 수 있습니다.
`<KR260_IP>`는 자신의 보드 IP로 바꾸세요.
실행 제어 키는 서버 첫 실행 시 생성됩니다.
`sudo cat 11_board_app/.control-token`으로 확인한 값을 UI의 제어 키에 입력하거나,
`http://<KR260_IP>:8080/#제어키`로 접속합니다. SSH 비밀번호는 저장하지 않습니다.

서비스는 부팅 시 UI만 실행합니다. FPGA는 UI의 **FPGA 로딩** 버튼으로 적재합니다.
현재 부팅과 다른 로딩 기록으로 하드웨어를 실행하지 않습니다.

## 실시간 카메라 추론

Pleomax UVC 카메라를 `/dev/video0`에 연결하고 UI의 **카메라 추론 시작**을 누릅니다.
입력은 `640×480 BGR → 중앙 640×360 crop → 512×288 resize → RGB → signed INT8 → 1픽셀 -128 padding`으로
변환됩니다. FPGA의 22개 연산 뒤 두 detection head를 decode하고 class별 NMS를 적용해 상자를 표시합니다.
카메라 캡처와 FPGA 실행은 분리되어 있으며, 처리 지연을 누적하지 않도록 항상 최신 프레임만 선택합니다.
현재 100 MHz 구성에서는 카메라가 약 27.6 fps로 들어오지만 전체 FPGA 추론은 약 1.3초/프레임이므로,
UI의 `건너뛴 캡처 프레임`은 오류가 아니라 의도한 최신 프레임 처리 결과입니다.

터미널에서는 다음과 같이 같은 경로를 실행할 수 있습니다.

```bash
sudo python3 11_board_app/camera.py
# 다른 터미널에서 정상 종료
sudo touch 11_board_app/results/camera.stop
```

## 검증 범위

- `system_bringup_wrapper.bit`의 SHA-256을 고정하고, 같은 export의 HWH와
  descriptor의 주소, generated header의 모든 제어 레지스터 offset을 대조합니다.
- 4-IP 구성(conv/maxpool/upsample/route)을 사용합니다. `sys5_wrapper`는 사용하지 않습니다.
- HWH에서 PS AXI 버스 폭을 읽어 AFI 설정을 생성합니다. 초기 보드 검증은 100 MHz입니다.
- Linux CMA heap `/dev/dma_heap/reserved`에서 버퍼를 할당하고 작은 kernel bridge에서
  DMA-BUF를 import/map합니다. 단일 연속 DMA segment와 low DDR 범위를 검사하며,
  fd가 열린 동안 mapping과 buffer 참조를 유지합니다. HP0/HP1의 직접 DDR 연결을 전제로 합니다.
  Ubuntu CMA mmap은 pagemap에서 PFN을 노출하지 않아 사용자 공간의 주소 추정을 사용하지 않습니다.
  커널 업데이트 후에는 위 module build/install 명령을 다시 실행해야 합니다.
- CPU 접근 전후 `DMA_BUF_IOCTL_SYNC`를 사용합니다. 임의 DDR 주소를 예약 없이 쓰지 않습니다.
- 22-op 전체 체인은 IP 완료 신호를 검사합니다. Layer 0과 두 detection head는
  전체 바이트를 정답 파일과 비교합니다. 나머지 중간 레이어의 정답 일치 검사는 포함하지 않습니다.
- Layer 0 불일치 시 전체 체인을 중단합니다. timeout은 IP당 5초입니다.
  timeout 후 FPGA를 재로딩하여 DMA를 정지시킨 뒤 메모리를 해제합니다.
  복구 실패 시 작업 프로세스가 메모리와 실행 lock을 계속 보유합니다.
- `accelerator_ms`는 각 IP 시작→완료의 wall-clock 합계이며 Python polling 지연을 포함합니다.
  카메라 FPS나 전체 앱 처리 FPS가 아닙니다.
- 결과는 `results/layer0.json`, `results/full.json`, `results/latest.json`에 저장됩니다.
  실제 출력은 `results/layer_00_actual.bin`, `layer_15_actual.bin`, `layer_22_actual.bin`입니다.
  UI의 결과 다운로드는 현재 상태와 보고서, 로그를 JSON으로 저장합니다.
- 실시간 결과는 `results/camera.json`과 `results/camera.jpg`에 원자적으로 갱신됩니다.

## 알려진 버전 차이 및 로딩 복구

**정답 head 파일의 레이아웃 표기 오류:** `05_golden_heads/*_nhwc_int8.bin`은 실제로
`08_golden_model/int8_layers_sample/layer_15.bin`, `layer_22.bin`과 동일한 NCHW bytes입니다.
`08_golden_model/quantization.py`의 `dump_int8_layers()`가 NCHW C-order로 저장함을 명시합니다.
검증기는 원본 golden sample의 SHA-256을 고정하고, [C,H,W] → [H,W,C] 순서로 변환한 뒤 비교합니다.
하드웨어 출력에 따라 레이아웃을 선택하지 않습니다. 보고서 `checks.*.reference`에 원본 hash,
원본/비교 레이아웃, shape를 기록합니다. 기존 전달 파일은 그대로 보존합니다.

기존 descriptor의 bitstream/XSA hash는 과거 export를 가리킵니다. 원본 descriptor는
수정하지 않고 실제 적재 bitstream hash와 descriptor hash를 각 보고서에 함께 기록합니다.
주소 및 레지스터 계약을 대조해도 수치 정확도를 보장하지 않으므로, 실제 정답 비교를 별도로 수행합니다.

Ubuntu 6.8.0-1015-xilinx에서 `xmutil` 기본 이미지의 DMA-BUF 로딩 flag `0x20`이
unload 이후에도 남았습니다. 이 상태로 firmware-name overlay를 적용한 첫 시도에서
`cma_heap_map_dma_buf → fpga_mgr_load` 경로의 kernel Oops가 발생했습니다.
로더는 firmware-name 로딩 직전에 `/sys/class/fpga_manager/fpga0/flags`를 `0`으로
명시적으로 초기화합니다. `operating`이나 overlay의 `applied`만으로 성공을 판단하지 않으며,
로딩 함수가 정상 반환하고 기록을 남긴 경우에만 실행을 허용합니다.

커널 Oops가 이미 발생한 경우 소프트웨어 재부팅이 종료 단계에서 멈출 수 있습니다.
전원을 껐다 켜서 커널 상태를 복구한 후 수정된 로더를 사용해야 합니다.

## 참고

- [Linux DMA heaps](https://docs.kernel.org/6.15/userspace-api/dma-buf-heaps.html)
- [Linux DMA buffer synchronization](https://www.kernel.org/doc/html/v5.15/driver-api/dma-buf.html)
- [AMD FPGA Manager programming](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/18841847/Solution+ZynqMP+PL+Programming)
- [AMD device tree generator: AFI width and fabric clock configuration](https://github.com/Xilinx/device-tree-xlnx/blob/master/device_tree/data/common_proc.tcl)
