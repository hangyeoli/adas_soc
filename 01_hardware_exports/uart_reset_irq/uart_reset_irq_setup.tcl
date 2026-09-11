# =====================================================================
# UART0/UART1 + aresetn + interrupt 배선 스크립트
# PS request(2).md 확인 요청 대응용 (2026-08-05/06 작업)
#
# 사용법: 본인 system_bringup(또는 동일 구조) BD를 열어놓은 상태에서
#         Tcl Console에 아래 변수만 프로젝트에 맞게 수정 후 전체 붙여넣기.
#
# 주의: IP 인스턴스 이름이 이 프로젝트(conv_engine_0, maxpool_engine_0,
#       upsample_engine_0, route_concat_engine_0, zynq_ultra_ps_e_0)와
#       다를 수 있음 — 아래 변수에서 본인 프로젝트 이름으로 바꿀 것.
#       모르겠으면: get_bd_cells 로 전체 목록 먼저 확인.
# =====================================================================

# ---- 여기부터 본인 프로젝트에 맞게 수정 ----
set ZYNQ_PS       zynq_ultra_ps_e_0
set CONV_ENGINE   conv_engine_0
set MAXPOOL       maxpool_engine_0
set UPSAMPLE      upsample_engine_0
set ROUTE_CONCAT  route_concat_engine_0
# ---- 여기까지 ----

# === 1. UART0 / UART1 설정 ===
# UART1 = MIO36-37 (실제 콘솔, carrier board preset.xml 기준 확인됨)
# UART0 = EMIO (RPi 40핀 헤더로 빼서 RPU<->RPi 통신용 — PS 요청서와 반대 매핑,
#               자세한 이유는 같이 전달한 설명 참고)
set_property -dict [list \
    CONFIG.PSU__UART1__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__UART1__PERIPHERAL__IO {MIO 36 .. 37} \
    CONFIG.PSU__UART0__PERIPHERAL__ENABLE {1} \
    CONFIG.PSU__UART0__PERIPHERAL__IO {EMIO} \
] [get_bd_cells $ZYNQ_PS]

# UART0 EMIO 인터페이스 포트를 top-level로 노출
# (주의: 이미 UART_0_0 같은 이름의 external port가 있으면 자동으로 _1 등으로
#  붙을 수 있음 — 실행 후 아래 확인 명령어로 실제 포트 이름 꼭 체크할 것)
make_bd_intf_pins_external [get_bd_intf_pins $ZYNQ_PS/UART_0]

# === 2. aresetn 연결 (smartconnect_hp0) ===
# rst_ps8_0_99M (Processor System Reset IP)이 이미 있다는 전제.
# 없으면 먼저 추가: create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps8_0_99M
connect_bd_net [get_bd_pins rst_ps8_0_99M/interconnect_aresetn] [get_bd_pins smartconnect_hp0/aresetn]

# === 3. interrupt 배선 (xlconcat) ===
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 xlconcat_irq
set_property -dict [list CONFIG.NUM_PORTS {4}] [get_bd_cells xlconcat_irq]

connect_bd_net [get_bd_pins $CONV_ENGINE/interrupt]  [get_bd_pins xlconcat_irq/In0]
connect_bd_net [get_bd_pins $MAXPOOL/interrupt]      [get_bd_pins xlconcat_irq/In1]
connect_bd_net [get_bd_pins $UPSAMPLE/interrupt]     [get_bd_pins xlconcat_irq/In2]
connect_bd_net [get_bd_pins $ROUTE_CONCAT/interrupt] [get_bd_pins xlconcat_irq/In3]

connect_bd_net [get_bd_pins xlconcat_irq/dout] [get_bd_pins $ZYNQ_PS/pl_ps_irq0]

# === 4. 저장 + 검증 ===
save_bd_design
validate_bd_design

# === 5. UART0 top-level 포트 이름 확인 (다음 XDC 작업에 필요) ===
puts "===== UART0 EMIO top-level ports (XDC에 이 이름 그대로 써야 함) ====="
get_bd_ports -filter {NAME =~ "*UART*"}
