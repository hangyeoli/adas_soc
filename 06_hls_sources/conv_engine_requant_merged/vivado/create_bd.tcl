# create_bd.tcl
#
# Builds the bring-up block design for conv_engine:
#   Zynq UltraScale+ MPSoC PS <-> conv_engine (packaged HLS IP)
#
# Simpler than hls/conv_layer1/vivado/create_bd.tcl's design: conv_engine has
# no AXI4-Stream ports and needs no AXI DMA IP at all - every port is either
# AXI4-Lite (control/geometry registers) or AXI4 (m_axi, reading/writing DDR
# directly). This is a direct consequence of the shared-engine redesign (see
# ../README.md) - one real benefit of moving I/O from streaming to
# DDR-resident buffers is that the DMA choreography conv_layer1 needed
# (arm S2MM before ap_start, poll both DMA channels, etc.) simply does not
# exist here; SW/network_run.c only ever pokes AXI-Lite registers and calls
# Xil_DCache*Range().
#
# ---------------------------------------------------------------------------
# Prerequisites (do these in Vitis HLS BEFORE sourcing this script):
#   1. conv_engine.cpp/.h passed C Simulation (conv_engine_tb.cpp - both
#      config-A and config-B must PASS), C Synthesis, C/RTL Co-simulation.
#   2. "Package IP" was run (`run_hls.bat package` / `bash run_hls.sh
#      --package`, confirmed working 2026-07-29 - produces
#      conv_engine_prj/solution1/impl/ip/, component.xml + drivers/).
#
# How to run: same as conv_layer1/vivado/create_bd.tcl - open/target a
# project with the KR260 board files installed, then in the Tcl Console,
# `source create_bd.tcl` (any cwd - IP_REPO_PATH below is anchored to this
# script's own file location via [info script], not Vivado's working
# directory, so it does not matter where the Vivado project itself lives).
# Same caveat applies: this was written against 2024.2 syntax but not run
# against a live Vivado instance, so treat the apply_bd_automation calls
# as a draft to verify interactively.
#
# BUG FIXED (2026-07-29, caught on re-review, never actually run): this
# used to hardcode IP_REPO_PATH as the plain string "../solution1/impl/ip"
# - wrong on two counts. (1) It's missing the "conv_engine_prj/" path
# segment (the real export is conv_engine_prj/solution1/impl/ip, one level
# deeper) - even interpreted relative to this script's own directory,
# "../solution1/impl/ip" resolves to the sibling "solution1" that doesn't
# exist. (2) Vivado Tcl's `source` does not change the interpreter's
# working directory to the sourced script's location - a bare relative
# path is resolved against whatever Vivado's cwd happens to be when this
# runs, which is generally some OTHER directory (the Vivado project's own
# folder), not this vivado/ folder - so even a correctly-spelled relative
# path here would have been fragile by accident of cwd, not by design.
# Anchoring to [info script] (same idiom run_hls.tcl already uses for
# HW_DIR) fixes both at once.
# ---------------------------------------------------------------------------

set BD_NAME       "conv_engine_bringup"
set SCRIPT_DIR    [file dirname [file normalize [info script]]]
set IP_REPO_PATH  "$SCRIPT_DIR/../conv_engine_prj/solution1/impl/ip"

set_property ip_repo_paths [list {*}[get_property ip_repo_paths [current_project]] $IP_REPO_PATH] [current_project]
update_ip_catalog

create_bd_design $BD_NAME
current_bd_design $BD_NAME

# ---- Zynq UltraScale+ MPSoC PS -------------------------------------------
set ps_vlnv [get_ipdefs -filter {NAME == "zynq_ultra_ps_e"}]
set ps [create_bd_cell -type ip -vlnv $ps_vlnv zynq_ultra_ps_e_0]

apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} [get_bd_cells zynq_ultra_ps_e_0]

# NOTE (2026-07-30, caught on a real Vivado run): PSU__USE__S_AXI_HP0_FPD /
# HP1_FPD are NOT real properties on this IP version - Vivado raised
# CRITICAL WARNING "Parameter does not exist" for both, silently leaving HP0
# and HP1 disabled, which then made the m_axi_RD_BUS/RD_BUS2 automation
# below fail with "No valid slave interface could be found". The PS IP
# names these ports internally as S_AXI_GP2 (=HP0_FPD) / S_AXI_GP3
# (=HP1_FPD) - confirmed via `list_property [get_bd_cells
# zynq_ultra_ps_e_0]` showing PSU__USE__S_AXI_GP0..GP6 (all 0 after board
# preset) and no HP0/HP1-named toggle at all.
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__USE__S_AXI_GP3 {1} \
] [get_bd_cells zynq_ultra_ps_e_0]

# ---- Packaged conv_engine HLS IP ------------------------------------------
set ce_vlnv [get_ipdefs -filter {NAME == "conv_engine" && VLNV =~ "xilinx.com:hls:*"}]
set ce [create_bd_cell -type ip -vlnv $ce_vlnv conv_engine_0]

# ---- AXI4-Lite control: PS GP0 -> conv_engine's CTRL bundle ----------------
# (all geometry registers + the four m_axi base addresses live on this one
# bundle - see conv_engine.cpp's INTERFACE pragmas)
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/zynq_ultra_ps_e_0/M_AXI_HPM0_FPD" Clk "Auto"} \
    [get_bd_intf_pins ${ce}/s_axi_CTRL]

# ---- AXI4 (m_axi): RD_BUS (ifmap/weights/bias) and WR_BUS (ofmap/accum)
#      go to DDR through HP0.
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/${ce}/m_axi_RD_BUS" Slave "/zynq_ultra_ps_e_0/S_AXI_HP0_FPD" Clk "Auto"} \
    [get_bd_intf_pins ${ce}/m_axi_RD_BUS]

apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/${ce}/m_axi_WR_BUS" Slave "/zynq_ultra_ps_e_0/S_AXI_HP0_FPD" Clk "Auto"} \
    [get_bd_intf_pins ${ce}/m_axi_WR_BUS]

# ---- AXI4 (m_axi): RD_BUS2 (weights_hi) - a SECOND physical read port onto
# the same DRAM weight data as RD_BUS's `weights`, routed to its own HP port
# (HP1, not HP0) so it can actually issue a read on the same cycle as
# RD_BUS's `weights` read instead of arbitrating for the same HP port. Added
# specifically to fix LOAD_W_IC's real csynth-measured II=2 (target II=1) -
# see conv_engine.h/.cpp's notes on `weights_hi`. Software (network_run.c via
# SW/conv_engine_hw_driver.h's conv_engine_set_addrs()) programs this port's
# base-address register with the SAME address as `weights` - this is not a
# second copy of the weight data in DDR.
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/${ce}/m_axi_RD_BUS2" Slave "/zynq_ultra_ps_e_0/S_AXI_HP1_FPD" Clk "Auto"} \
    [get_bd_intf_pins ${ce}/m_axi_RD_BUS2]

# ---- Interrupts: not wired, same reasoning as conv_layer1 - network_run.c
# polls ap_done directly.

validate_bd_design
save_bd_design

puts "conv_engine bring-up block design '$BD_NAME' created (no AXI DMA IP -\
all I/O is m_axi + AXI-Lite). Next: Create HDL Wrapper, synthesize/implement,\
generate bitstream, export platform (XSA) for Vitis."
