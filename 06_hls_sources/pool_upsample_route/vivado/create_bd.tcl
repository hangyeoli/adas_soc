# create_bd.tcl
#
# Builds the bring-up block design for pool_upsample_route's 3 packaged HLS
# IPs (maxpool_engine, upsample_engine, route_concat_engine) against a
# Zynq UltraScale+ MPSoC PS - same style/caveats as
# conv_engine_requant/vivado/create_bd.tcl (draft, not run against a live
# Vivado instance - verify apply_bd_automation calls interactively), just
# for 3 IPs from ONE Vitis HLS project (3 solutions) instead of 1.
#
# Like conv_engine, none of these 3 IPs have AXI4-Stream ports or need AXI
# DMA - every port is either AXI4-Lite (control/geometry registers) or AXI4
# (m_axi, reading/writing DDR directly). SW/network_run_full.c only ever
# pokes AXI-Lite registers and calls Xil_DCache*Range().
#
# ---------------------------------------------------------------------------
# Prerequisites (do these in Vitis HLS BEFORE sourcing this script):
#   1. All 3 engines passed C Simulation, C Synthesis, C/RTL Co-simulation
#      (`run_hls.bat cosim` / `bash run_hls.sh --cosim` - CONFIRMED done,
#      2026-07-29, all 3 bit-exact against C-sim, see ../README.md).
#   2. "Package IP" was run for all 3 solutions (`run_hls.bat package` /
#      `bash run_hls.sh --package`). Each solution exports independently -
#      note the 3 export directories (each
#      pool_upsample_route_prj/solution_<name>/impl/ip) and set
#      IP_REPO_PATHS below to them.
#
# How to run: same as conv_engine_requant/vivado/create_bd.tcl - open/target
# a project with the KR260 board files installed, then in the Tcl Console,
# `source create_bd.tcl` (any cwd - IP_REPO_PATHS below is anchored to this
# script's own file location via [info script], not Vivado's working
# directory - see that other script's "BUG FIXED" note for why a bare
# relative path here would have been fragile by accident of cwd, not by
# design, even though the path segments themselves were already correct).
# This was written against 2024.2 syntax but not run against a live Vivado
# instance, so treat the apply_bd_automation calls as a draft to verify
# interactively.
#
# This script only builds pool_upsample_route's OWN 3-IP bring-up design -
# it does not also add conv_engine (that IP lives in a separate HLS project
# and gets its own bring-up BD, conv_engine_requant/vivado/create_bd.tcl).
# Combining all 4 IPs into one final system BD is
# conv_engine_requant/README.md item 5's job (see
# SW/network_run_full.c) once each has bring-up-confirmed on its own.
# ---------------------------------------------------------------------------

set BD_NAME       "pool_upsample_route_bringup"
set SCRIPT_DIR    [file dirname [file normalize [info script]]]
set IP_REPO_PATHS [list \
    "$SCRIPT_DIR/../pool_upsample_route_prj/solution_maxpool/impl/ip" \
    "$SCRIPT_DIR/../pool_upsample_route_prj/solution_upsample/impl/ip" \
    "$SCRIPT_DIR/../pool_upsample_route_prj/solution_route_concat/impl/ip" \
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

# ---- HP-port allocation decision ------------------------------------------
# conv_engine_requant already claims HP0 (its RD_BUS+WR_BUS) and HP1 (its
# RD_BUS2, split off HP0 specifically to fix a real measured II=2 timing
# issue - see conv_engine_requant/vivado/create_bd.tcl). These 3 new IPs
# add 6 more m_axi masters (2 each - see maxpool_engine.h/upsample_engine.h/
# route_concat_engine.h's own "PS integration / AXI port count" notes).
#
# All 6 are routed onto the SAME HP0 port as conv_engine's masters below,
# not spread across HP2/HP3, for one concrete reason: RTL_HANDOFF_KO.md's
# architecture is a single layer sequencer executing ONE engine at a time
# (network_run_full.c reprograms + ap_start's each engine in turn, waiting
# for ap_done before starting the next) - there is no concurrent traffic
# between any 2 of these 4 IPs to actually contend over a shared HP port,
# unlike conv_engine's RD_BUS2 split (that one fixed a REAL measured
# same-engine, same-call II regression, not a hypothetical one). Vivado's
# AXI SmartConnect (auto-inserted by apply_bd_automation) merges arbitrarily
# many masters onto one HP slave port for free; consolidating onto HP0 here
# is the simpler choice with no known cost, not a resource-count workaround
# - if profiling ever shows real contention (it shouldn't, given the
# single-engine-at-a-time execution model), splitting a given engine's
# masters onto HP2/HP3 instead is a 1-line change per apply_bd_automation
# call below, nothing else in the design depends on this choice.
# NOTE (2026-07-30, caught on a real Vivado run against conv_engine_requant's
# copy of this same block - see that project's vivado/TROUBLESHOOTING.md for
# the full story, §1-4): PSU__USE__S_AXI_HP0_FPD is not a real property on
# this IP version; the PS names this port internally as S_AXI_GP2. Also,
# conv_engine_requant's own m_axi ports are 32-bit against HP0/HP1's 128-bit
# default (DATA_WIDTH mismatch, §3) - these 3 engines' m_axi ports are
# expected to be the same 32-bit width (not yet confirmed against a live
# Vivado instance for THIS project), so narrow HP0 to match preemptively.
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {32} \
] [get_bd_cells zynq_ultra_ps_e_0]

# NOTE (2026-07-30): the apply_bd_automation calls below (for each engine's
# m_axi_RD_BUS/WR_BUS -> HP0) are EXPECTED to fail the same way
# conv_engine_requant's did (TROUBLESHOOTING.md §2 - "No valid slave
# interface could be found" / "Error found in procedure get_rule_options"),
# and even if one succeeds via direct connect, HP0 here has 6 masters
# sharing it (not 2) - §4's SmartConnect gap WILL recur, just with
# Number of Slave Interfaces = 6 instead of 2. Don't be surprised if this
# whole foreach loop needs to be replaced by manual drag-connects + one
# manually-added 6-slave AXI SmartConnect + assign_bd_address, same as that
# project's real fix.

# ---- Packaged HLS IPs ------------------------------------------------------
set mpe_vlnv [get_ipdefs -filter {NAME == "maxpool_engine" && VLNV =~ "xilinx.com:hls:*"}]
set mpe [create_bd_cell -type ip -vlnv $mpe_vlnv maxpool_engine_0]

set upe_vlnv [get_ipdefs -filter {NAME == "upsample_engine" && VLNV =~ "xilinx.com:hls:*"}]
set upe [create_bd_cell -type ip -vlnv $upe_vlnv upsample_engine_0]

set rce_vlnv [get_ipdefs -filter {NAME == "route_concat_engine" && VLNV =~ "xilinx.com:hls:*"}]
set rce [create_bd_cell -type ip -vlnv $rce_vlnv route_concat_engine_0]

# ---- AXI4-Lite control: PS GP0 -> each IP's CTRL bundle -------------------
foreach ip [list $mpe $upe $rce] {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/zynq_ultra_ps_e_0/M_AXI_HPM0_FPD" Clk "Auto"} \
        [get_bd_intf_pins ${ip}/s_axi_CTRL]
}

# ---- AXI4 (m_axi): every RD_BUS/WR_BUS -> HP0 (see the allocation note
# above for why all 6 land on one port instead of spreading across more).
foreach ip [list $mpe $upe $rce] {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/${ip}/m_axi_RD_BUS" Slave "/zynq_ultra_ps_e_0/S_AXI_HP0_FPD" Clk "Auto"} \
        [get_bd_intf_pins ${ip}/m_axi_RD_BUS]

    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/${ip}/m_axi_WR_BUS" Slave "/zynq_ultra_ps_e_0/S_AXI_HP0_FPD" Clk "Auto"} \
        [get_bd_intf_pins ${ip}/m_axi_WR_BUS]
}

# ---- Interrupts: not wired, same reasoning as conv_engine_requant -
# network_run_full.c polls ap_done directly.

validate_bd_design
save_bd_design

puts "pool_upsample_route bring-up block design '$BD_NAME' created (3 IPs,\
no AXI DMA - all I/O is m_axi + AXI-Lite, all 6 new masters on HP0 - see\
the HP-port allocation note above). Next: Create HDL Wrapper,\
synthesize/implement, generate bitstream, export platform (XSA) for Vitis."
