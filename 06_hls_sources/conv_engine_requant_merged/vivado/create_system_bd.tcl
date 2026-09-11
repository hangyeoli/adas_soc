# create_system_bd.tcl
#
# Builds the FULL system block design combining all 4 real HLS IPs for the
# YOLOv3-tiny-ADAS network: conv_engine (conv_engine_requant) + maxpool_engine
# + upsample_engine + route_concat_engine (pool_upsample_route). This is
# README.md item 5's "combine all 4 IPs into one system BD" step, done after
# both projects' individual bring-ups were independently confirmed
# (conv_engine_bringup and pool_upsample_route_bringup, both reached
# bitstream + Export Hardware on 2026-07-30 - see this folder's
# TROUBLESHOOTING.md §1-6 for the full debugging history this script's
# fixes are already informed by, so they're folded in up front instead of
# being rediscovered a third time).
#
# Prerequisites: Package IP already done for all 4 solutions (see each
# project's own README "Next steps" - this was true before either
# individual bring-up was attempted).
#
# How to run: open/target a Vivado project with KR260 board files
# installed (a NEW project is recommended, separate from
# conv_engine_bringup/pool_upsample_route_bringup's own per-project
# bring-up projects, to keep this as the one "real system" project going
# forward), then in the Tcl Console, `source create_system_bd.tcl`. Same
# 260-byte Windows path caveat as the individual scripts - see
# TROUBLESHOOTING.md §5, `subst` a short drive letter onto the project's
# parent folder before Generate Bitstream if this project's own path is
# long too.
#
# Fixes already folded in from TROUBLESHOOTING.md, confirmed working on TWO
# independent bring-ups already (both projects, same PS IP version) -
# nothing below should need re-debugging from scratch:
#   §1: HP-port "USE" properties are PSU__USE__S_AXI_GP2/GP3, not
#       ...HP0_FPD/HP1_FPD (the GUI-visible names).
#   §2: apply_bd_automation does not reliably work on any of these
#       HLS-packaged IPs' m_axi MASTER ports (tested with both
#       `-config {...}` and `-config [list ...]` forms - identical
#       failure either way, so it isn't a Tcl brace-quoting bug). Every
#       m_axi connection below is a direct `connect_bd_intf_net`, never
#       `apply_bd_automation`. `apply_bd_automation` DOES work fine for
#       the slave-side `s_axi_CTRL` connections - confirmed 3x now.
#   §3: HP0/HP1 narrowed to 32-bit DATA_WIDTH to match every engine's
#       m_axi ports (all 4 IPs' m_axi ports are 32-bit).
#   §4/§6: any HP port serving 2+ masters needs an explicit AXI
#       SmartConnect, sized to the real master count - HP0 here serves
#       8 masters (conv_engine's RD_BUS+WR_BUS, plus 2 each from the other
#       3 engines), HP1 serves only conv_engine's RD_BUS2 alone (single
#       master, direct connect, no SmartConnect needed for HP1).
# ---------------------------------------------------------------------------

set BD_NAME    "system_bringup"
set SCRIPT_DIR [file dirname [file normalize [info script]]]
set IP_REPO_PATHS [list \
    "$SCRIPT_DIR/../conv_engine_prj/solution1/impl/ip" \
    "$SCRIPT_DIR/../../pool_upsample_route/pool_upsample_route_prj/solution_maxpool/impl/ip" \
    "$SCRIPT_DIR/../../pool_upsample_route/pool_upsample_route_prj/solution_upsample/impl/ip" \
    "$SCRIPT_DIR/../../pool_upsample_route/pool_upsample_route_prj/solution_route_concat/impl/ip" \
]

set_property ip_repo_paths [list {*}[get_property ip_repo_paths [current_project]] {*}$IP_REPO_PATHS] [current_project]
update_ip_catalog

create_bd_design $BD_NAME
current_bd_design $BD_NAME

# ---- Zynq UltraScale+ MPSoC PS -------------------------------------------
set ps_vlnv [get_ipdefs -filter {NAME == "zynq_ultra_ps_e"}]
set ps [create_bd_cell -type ip -vlnv $ps_vlnv zynq_ultra_ps_e_0]

apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} [get_bd_cells zynq_ultra_ps_e_0]

set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0      {1} \
    CONFIG.PSU__USE__S_AXI_GP2      {1} \
    CONFIG.PSU__USE__S_AXI_GP3      {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {32} \
    CONFIG.PSU__SAXIGP3__DATA_WIDTH {32} \
] [get_bd_cells zynq_ultra_ps_e_0]

# ---- Packaged HLS IPs ------------------------------------------------------
set ce_vlnv  [get_ipdefs -filter {NAME == "conv_engine" && VLNV =~ "xilinx.com:hls:*"}]
set ce  [create_bd_cell -type ip -vlnv $ce_vlnv  conv_engine_0]

set mpe_vlnv [get_ipdefs -filter {NAME == "maxpool_engine" && VLNV =~ "xilinx.com:hls:*"}]
set mpe [create_bd_cell -type ip -vlnv $mpe_vlnv maxpool_engine_0]

set upe_vlnv [get_ipdefs -filter {NAME == "upsample_engine" && VLNV =~ "xilinx.com:hls:*"}]
set upe [create_bd_cell -type ip -vlnv $upe_vlnv upsample_engine_0]

set rce_vlnv [get_ipdefs -filter {NAME == "route_concat_engine" && VLNV =~ "xilinx.com:hls:*"}]
set rce [create_bd_cell -type ip -vlnv $rce_vlnv route_concat_engine_0]

# ---- AXI4-Lite control: PS GP0 -> each IP's CTRL bundle -------------------
foreach ip [list $ce $mpe $upe $rce] {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/zynq_ultra_ps_e_0/M_AXI_HPM0_FPD" Clk "Auto"} \
        [get_bd_intf_pins ${ip}/s_axi_CTRL]
}

# ---- HP0: conv_engine's RD_BUS/WR_BUS + all 3 engines' RD_BUS/WR_BUS ------
# (8 masters total) through one AXI SmartConnect.
set sc_vlnv [get_ipdefs -filter {NAME == "smartconnect"}]
set sc0 [create_bd_cell -type ip -vlnv $sc_vlnv smartconnect_hp0]
set_property CONFIG.NUM_SI {8} $sc0

set hp0_masters [list \
    ${ce}/m_axi_RD_BUS  ${ce}/m_axi_WR_BUS \
    ${mpe}/m_axi_RD_BUS ${mpe}/m_axi_WR_BUS \
    ${upe}/m_axi_RD_BUS ${upe}/m_axi_WR_BUS \
    ${rce}/m_axi_RD_BUS ${rce}/m_axi_WR_BUS \
]
set idx 0
foreach m $hp0_masters {
    set sN [format "S%02d_AXI" $idx]
    connect_bd_intf_net [get_bd_intf_pins $m] [get_bd_intf_pins ${sc0}/${sN}]
    incr idx
}
connect_bd_intf_net [get_bd_intf_pins ${sc0}/M00_AXI] [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# ---- HP1: conv_engine's RD_BUS2 alone - single master, no SmartConnect
# needed (mirrors conv_engine_bringup's own HP1 wiring).
connect_bd_intf_net [get_bd_intf_pins ${ce}/m_axi_RD_BUS2] [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP1_FPD]

# ---- Clocks: reuse the same PL clock already driving the working CTRL
# path for smartconnect_hp0's aclk and any HP-port aclk pins board preset
# left unconnected. Guard each with a "already connected?" check first -
# connect_bd_intf_net sometimes auto-wires a cell's aclk as a side effect
# (seen with smartconnect in the pool_upsample_route session), and
# re-connecting an already-correctly-wired pin errors instead of no-op'ing.
set clk_pin [get_bd_pins -of_objects [get_bd_nets -of_objects [get_bd_pins zynq_ultra_ps_e_0/maxihpm0_fpd_aclk]] -filter {DIR == O}]
foreach p {maxihpm1_fpd_aclk saxihp0_fpd_aclk saxihp1_fpd_aclk} {
    if {[llength [get_bd_nets -of_objects [get_bd_pins zynq_ultra_ps_e_0/$p]]] == 0} {
        connect_bd_net $clk_pin [get_bd_pins zynq_ultra_ps_e_0/$p]
    }
}
if {[llength [get_bd_nets -of_objects [get_bd_pins ${sc0}/aclk]]] == 0} {
    connect_bd_net $clk_pin [get_bd_pins ${sc0}/aclk]
}

# ---- Interrupts: not wired - network_run_full.c polls ap_done directly on
# each engine in turn, same as every individual bring-up.

assign_bd_address
validate_bd_design
save_bd_design

puts "system_bringup block design created: all 4 real HLS IPs (conv_engine,\
maxpool_engine, upsample_engine, route_concat_engine) wired to one Zynq\
UltraScale+ PS - HP0 via an 8-slave AXI SmartConnect, HP1 direct\
(conv_engine's RD_BUS2 only). Next: Create HDL Wrapper, generate bitstream,\
export platform (XSA) for Vitis - then bring up SW/network_run_full.c\
against real hardware."
