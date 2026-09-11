#!/usr/bin/env bash
# run_hls.sh
# Headless Vitis HLS run for pool_upsample_route: C-sim + C-synthesis
# (+ optional co-simulation with --cosim) for all 3 engines
# (maxpool_engine/upsample_engine/route_concat_engine), driven via
# run_hls.tcl - same structure/conventions as
# conv_engine_requant/run_hls.sh, adapted for 3 solutions in one project
# instead of 1.
#
# Usage (from this directory, hls/pool_upsample_route/):
#   bash run_hls.sh                     # C-sim + C-synthesis only, all 3 engines (fast)
#   bash run_hls.sh --cosim             # also runs co-simulation for all 3 (slow)
#   bash run_hls.sh --package           # also runs Package IP for all 3
#   bash run_hls.sh --cosim --package   # both (any order)
#
# Prerequisites: `vitis_hls` must be on PATH - source Vitis's settings
# script first, e.g.:
#   source /tools/Xilinx/Vitis/2024.2/settings64.sh
#
# Exit code: 0 = all 3 solutions' csim+csynth (+cosim if requested)
# completed AND each printed its own "ALL CONFIGS PASS"; 1 otherwise. A
# failure isolated to one engine does not stop the other two from running -
# see run_hls.tcl's per-solution `catch` blocks - so this script always
# reports a per-solution breakdown, not just one pass/fail bit.

set -uo pipefail   # NOT -e: vitis_hls's exit code is checked explicitly below

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGDIR="$SCRIPT_DIR/hls_logs"
mkdir -p "$LOGDIR"

if [ -t 1 ]; then
    C_RED='\033[0;31m'; C_GRN='\033[0;32m'; C_YLW='\033[1;33m'; C_RST='\033[0m'
else
    C_RED=''; C_GRN=''; C_YLW=''; C_RST=''
fi

step() { printf "\n${C_YLW}==> %s${C_RST}\n" "$*"; }
pass() { printf "${C_GRN}PASS${C_RST}  %s\n" "$*"; }
fail() { printf "${C_RED}FAIL${C_RST}  %s\n" "$*"; }

if ! command -v vitis_hls >/dev/null 2>&1; then
    fail "vitis_hls not found on PATH"
    printf "       source Vitis's settings script first, e.g.:\n"
    printf "       source /tools/Xilinx/Vitis/2024.2/settings64.sh\n"
    exit 1
fi

COSIM=0
PACKAGE=0
for arg in "$@"; do
    case "$arg" in
        --cosim)   COSIM=1 ;;
        --package) PACKAGE=1 ;;
    esac
done
if [ "$COSIM" -eq 1 ] && [ "$PACKAGE" -eq 1 ]; then
    step "Running vitis_hls (C-sim + C-synthesis + co-simulation + Package IP, all 3 engines) - this is slow"
elif [ "$COSIM" -eq 1 ]; then
    step "Running vitis_hls (C-sim + C-synthesis + co-simulation, all 3 engines) - this is slow"
elif [ "$PACKAGE" -eq 1 ]; then
    step "Running vitis_hls (C-sim + C-synthesis + Package IP, all 3 engines)"
else
    step "Running vitis_hls (C-sim + C-synthesis only, all 3 engines; pass --cosim and/or --package to also run co-simulation / Package IP)"
fi

LOG="$LOGDIR/run_hls.log"
[ "$COSIM" -eq 1 ]   && export RUN_HLS_COSIM=1
[ "$PACKAGE" -eq 1 ] && export RUN_HLS_PACKAGE=1
vitis_hls -f run_hls.tcl >"$LOG" 2>&1
RC=$?

if [ "$RC" -ne 0 ]; then
    fail "vitis_hls exited with status $RC - see $LOG"
    tail -40 "$LOG"
    exit 1
fi

overall_fail=0

# 3 solutions -> expect each marker exactly 3 times. Counting occurrences,
# not just checking "any", since a bug isolated to one engine (2/3 PASS)
# must not be reported as an overall PASS.
# Anchored to start-of-line: run_hls.tcl's own announcement line
# ("==> [sol] C Simulation - expect \"ALL CONFIGS PASS\" ...") contains
# the same substring mid-line and would otherwise double the count
# (6/3 instead of 3/3) against pool_upsample_route_tb.cpp's bare
# `printf("ALL CONFIGS PASS\n")` output.
csim_count=$(grep -c "^ALL CONFIGS PASS" "$LOG" || true)
if [ "$csim_count" -eq 3 ]; then
    pass "C simulation - all 3 engines printed ALL CONFIGS PASS"
else
    fail "C simulation: only $csim_count/3 engines printed ALL CONFIGS PASS - see $LOG"
    grep -E "MISMATCH|FAIL|Assertion|assert|C-SIM ERROR" "$LOG" | head -20 || true
    overall_fail=1
fi

# "Finished Command csynth_design" (not a bare substring) mirrors
# conv_engine_requant/run_hls.sh's own reasoning: that phrase also appears
# the moment synthesis STARTS ("Running: csynth_design"), which would
# false-positive PASS even if synthesis stalled or errored partway through.
csynth_count=$(grep -ci "Finished Command csynth_design" "$LOG" || true)
if [ "$csynth_count" -eq 3 ]; then
    pass "C synthesis - all 3 engines completed - see pool_upsample_route_prj/solution_*/syn/report/*_csynth.rpt for LUT/DSP/BRAM/FF numbers"
else
    fail "C synthesis: only $csynth_count/3 engines completed - see $LOG"
    grep -E "C-SYNTH ERROR" "$LOG" | head -20 || true
    overall_fail=1
fi

if [ "$COSIM" -eq 1 ]; then
    cosim_count=$(grep -ci "Finished Command cosim_design\|co-simulation finished: PASS" "$LOG" || true)
    if [ "$cosim_count" -ge 3 ]; then
        pass "C/RTL co-simulation - all 3 engines"
    else
        fail "C/RTL co-simulation: fewer than 3 engines confirmed - see $LOG"
        grep -E "COSIM ERROR" "$LOG" | head -20 || true
        overall_fail=1
    fi
fi

if [ "$PACKAGE" -eq 1 ]; then
    # No confirmed log marker for export_design's own success message yet
    # (unlike csim/csynth/cosim above) - check for the export directory
    # itself instead, once per solution.
    package_count=0
    for sol in maxpool upsample route_concat; do
        [ -d "$SCRIPT_DIR/pool_upsample_route_prj/solution_$sol/impl/ip" ] && package_count=$((package_count + 1))
    done
    if [ "$package_count" -eq 3 ]; then
        pass "Package IP - all 3 engines exported - see pool_upsample_route_prj/solution_*/impl/ip/"
    else
        fail "Package IP: only $package_count/3 engines exported - see $LOG"
        grep -E "PACKAGE-IP ERROR" "$LOG" | head -20 || true
        overall_fail=1
    fi
fi

printf "\n========================================\n"
if [ "$overall_fail" -eq 0 ]; then
    printf "${C_GRN}  pool_upsample_route HLS run complete (all 3 engines)${C_RST}\n"
else
    printf "${C_RED}  One or more engines did not confirm success - see $LOG${C_RST}\n"
fi
printf "  Full reports: %s/pool_upsample_route_prj/solution_{maxpool,upsample,route_concat}/\n" "$SCRIPT_DIR"
printf "========================================\n\n"

exit "$overall_fail"
