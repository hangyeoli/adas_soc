# run_hls.tcl
#
# Headless Vitis HLS batch script for pool_upsample_route - 3 independent
# top-level functions (maxpool_engine, upsample_engine, route_concat_engine)
# sharing ONE project, ONE add_files call, and THREE solutions (one per
# top function) - see hls/pool_upsample_route's implementation plan for why
# this is one project/3 solutions rather than 3 separate projects (lower
# add_files/open_project overhead, still produces 3 independently
# packageable IPs since Package IP operates per-solution regardless).
#
# Run via:
#   vitis_hls -f run_hls.tcl                        # C-sim + C-synthesis only
#   RUN_HLS_COSIM=1 vitis_hls -f run_hls.tcl         # also runs co-simulation (slow)
#   RUN_HLS_PACKAGE=1 vitis_hls -f run_hls.tcl       # also runs Package IP
#
# Cosim is selected through the RUN_HLS_COSIM *environment* variable, not a
# `vitis_hls` command-line argument - same reasoning (and the same real
# `ERROR: [HLS 200-101] Unknown option '--cosim'` finding) as
# conv_engine_requant/run_hls.tcl's header comment already documents; see
# that file/TROUBLESHOOTING.md for the full story. run_hls.sh/run_hls.bat
# set this variable before calling `vitis_hls -f run_hls.tcl`. RUN_HLS_PACKAGE
# follows the exact same convention, for the exact same reason (keep every
# vitis_hls invocation's CLI argv identical - `-f run_hls.tcl` only - so only
# the Tcl script's own env-var reads decide what runs).
#
# Package IP (`export_design`) needs csynth_design to have already run in
# THIS SAME invocation (same constraint `cosim_design` has - see
# conv_engine_requant/run_hls.tcl's "TRIED AND REJECTED" note), so it is not
# offered as a way to skip csim/csynth - it only ever adds an export step
# after them. Each solution's IP lands under
# pool_upsample_route_prj/solution_<name>/impl/ip - that's the IP_REPO_PATH
# each solution needs added to vivado/create_bd.tcl.
#
# Each solution's csim/csynth/cosim runs independently: a bug isolated to
# one engine (say, route_concat_engine) does not stop the other two
# solutions from running and being confirmed - see the `catch` blocks below
# and the final per-solution PASS/FAIL summary this script prints.
#
# Cosim needs a per-engine full-m_axi-depth call, since all 3 engines are
# compiled into the ONE shared testbench binary and cosim_design only ever
# RTL-simulates the FIRST call that binary's main() makes - see
# pool_upsample_route_tb.cpp's `--cosim-only=<engine>` argv handling
# (mirrors conv_engine_tb.cpp's own `--cosim-only` convention, parameterized
# over which engine this solution's top function is).
#
# Targets Vitis HLS 2024.2 - same PART/CLOCK_NS as conv_engine_requant's
# run_hls.tcl (same board/clock target, KR260/xck26-sfvc784-2LV-c, 200MHz).
# ---------------------------------------------------------------------------

set PART      "xck26-sfvc784-2LV-c"
set CLOCK_NS  5.0    ;# 200 MHz, matching conv_engine_requant/run_hls.tcl
set RUN_COSIM   [info exists ::env(RUN_HLS_COSIM)]
set RUN_PACKAGE [info exists ::env(RUN_HLS_PACKAGE)]

set SCRIPT_DIR [file dirname [file normalize [info script]]]
set HW_DIR     "$SCRIPT_DIR/HW"

open_project -reset pool_upsample_route_prj
add_files      "$HW_DIR/maxpool_engine.cpp"
add_files      "$HW_DIR/upsample_engine.cpp"
add_files      "$HW_DIR/route_concat_engine.cpp"
add_files -tb  "$HW_DIR/pool_upsample_route_tb.cpp"

# {solution_name  top_function         cosim_engine_tag}
set SOLUTIONS {
    {solution_maxpool       maxpool_engine      maxpool}
    {solution_upsample      upsample_engine     upsample}
    {solution_route_concat  route_concat_engine route}
}

set any_fail 0

foreach entry $SOLUTIONS {
    set sol_name  [lindex $entry 0]
    set top_func  [lindex $entry 1]
    set cosim_tag [lindex $entry 2]

    puts "\n============================================================"
    puts "==> \[$sol_name\] top=$top_func"
    puts "============================================================"

    open_solution -reset $sol_name
    set_part $PART
    create_clock -period $CLOCK_NS -name default
    set_top $top_func

    puts "\n==> \[$sol_name\] C Simulation - expect \"ALL CONFIGS PASS\"\
(see HW/pool_upsample_route_tb.cpp)"
    if {[catch {csim_design} csim_err]} {
        puts "\[$sol_name\] C-SIM ERROR: $csim_err"
        set any_fail 1
        continue
    }

    puts "\n==> \[$sol_name\] C Synthesis - check\
pool_upsample_route_prj/$sol_name/syn/report/${top_func}_csynth.rpt\
for LUT/DSP/BRAM/FF numbers"
    if {[catch {csynth_design} csynth_err]} {
        puts "\[$sol_name\] C-SYNTH ERROR: $csynth_err"
        set any_fail 1
        continue
    }

    if {$RUN_COSIM} {
        puts "\n==> \[$sol_name\] C/RTL Co-simulation\
(--cosim-only=$cosim_tag, full m_axi-depth buffers)"
        if {[catch {cosim_design -argv "--cosim-only=$cosim_tag"} cosim_err]} {
            puts "\[$sol_name\] COSIM ERROR: $cosim_err"
            set any_fail 1
            continue
        }
    } else {
        puts "\n==> \[$sol_name\] Skipping co-simulation (set RUN_HLS_COSIM=1 to also run it)"
    }

    if {$RUN_PACKAGE} {
        puts "\n==> \[$sol_name\] Package IP - exporting to\
pool_upsample_route_prj/$sol_name/impl/ip (see SW/*_hw_driver.h header\
comments for why the real generated x${top_func}_hw.h from this export,\
not a hand-guessed register map, is what those drivers must be built from)"
        if {[catch {export_design -rtl verilog -format ip_catalog} export_err]} {
            puts "\[$sol_name\] PACKAGE-IP ERROR: $export_err"
            set any_fail 1
            continue
        }
    } else {
        puts "\n==> \[$sol_name\] Skipping Package IP (set RUN_HLS_PACKAGE=1 to also run it)"
    }

    puts "\n==> \[$sol_name\] completed with no Tcl-level errors"
}

close_project

if {$any_fail} {
    puts "\nONE OR MORE SOLUTIONS FAILED (Tcl-level error) - see the per-solution log above"
    exit 1
}
puts "\nALL SOLUTIONS COMPLETED (no Tcl-level errors) - check each solution's own\
csim/csynth/cosim PASS markers above, same as conv_engine_requant's run_hls.tcl"
exit 0
