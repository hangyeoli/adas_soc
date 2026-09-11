######################################################################
# RPi 40핀 헤더 UART0 핀 제약 (RPU <-> Raspberry Pi 통신용)
#
# 물리 핀: RPi 헤더 8번(GPIO14/TXD), 10번(GPIO15/RXD)
# 출처: KR260 공개 Pmod/RPi 핀아웃 프로젝트(Hackster, Whitney Knitter)의
#       XDC "Special Functions" 주석부에서 확인된 패키지 핀 매핑
#
# 주의: 아래 포트 이름(UART_0_0_txd / UART_0_0_rxd)은 이 프로젝트의
#       HDL wrapper 기준 이름입니다. 본인 프로젝트에서 make_bd_intf_pins_external
#       실행 후 실제로 생성된 포트 이름이 다르면 (예: UART_0_0_1_txd 등)
#       아래 get_ports 안의 이름을 그 이름으로 바꿔야 합니다.
#       (uart_reset_irq_setup.tcl 스크립트 마지막에 실제 이름 출력하는
#        get_bd_ports 명령이 포함되어 있습니다.)
#
# 실제 라즈베리파이 보드에 연결할 때는 TX/RX를 교차 배선해야 합니다:
#   KR260 TXD(핀8) -> RPi RXD(핀10)
#   KR260 RXD(핀10) -> RPi TXD(핀8)
#   + 공통 GND
######################################################################

set_property PACKAGE_PIN W14 [get_ports {UART_0_0_txd}]
set_property IOSTANDARD LVCMOS33 [get_ports {UART_0_0_txd}]

set_property PACKAGE_PIN W13 [get_ports {UART_0_0_rxd}]
set_property IOSTANDARD LVCMOS33 [get_ports {UART_0_0_rxd}]
