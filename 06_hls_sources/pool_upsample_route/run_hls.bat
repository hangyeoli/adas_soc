@echo off
setlocal enabledelayedexpansion

:: run_hls.bat
:: Headless Vitis HLS run for pool_upsample_route: C-sim + C-synthesis
:: (+ optional co-simulation with the "cosim" argument) for all 3 engines
:: (maxpool_engine/upsample_engine/route_concat_engine), driven via
:: run_hls.tcl - same structure/conventions as
:: conv_engine_requant\run_hls.bat, adapted for 3 solutions in one project.
::
:: Usage (double-click, or from any cmd prompt - including a fresh one
:: where vitis_hls is not yet on PATH):
::   run_hls.bat                  C-sim + C-synthesis only, all 3 engines (fast)
::   run_hls.bat cosim            also runs co-simulation for all 3 (slow)
::   run_hls.bat package          also runs Package IP for all 3
::   run_hls.bat cosim package    both (either order)
::
:: A failure isolated to one engine does not stop the other two from
:: running - see run_hls.tcl's per-solution `catch` blocks - so this script
:: always reports a per-solution (3-engine) breakdown, not just one
:: pass/fail bit; see conv_engine_requant\run_hls.bat's own header comment
:: for the underlying vitis_hls-version/--cosim-argv gotchas this script
:: also guards against (RUN_HLS_COSIM env var, not a CLI arg; version pin
:: to 2024.2).

set "SCRIPT_DIR=%~dp0"
set "LOGDIR=%SCRIPT_DIR%hls_logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

where vitis_hls >nul 2>&1
if not errorlevel 1 goto vitis_ok
set VITIS_FOUND=0
for %%V in (2024.2 2024.1 2023.2 2023.1 2022.2 2022.1 2021.2 2021.1) do (
    if exist "C:\Xilinx\Vitis\%%V\settings64.bat" (
        call "C:\Xilinx\Vitis\%%V\settings64.bat" >nul 2>&1
        set VITIS_FOUND=1
    )
)
if "%VITIS_FOUND%"=="0" (
    echo ERROR: vitis_hls not in PATH and no install found under C:\Xilinx\Vitis\
    echo        Either run this from a "Vitis HLS Command Prompt" shortcut,
    echo        or edit the version list above to match where Vitis is
    echo        actually installed on this machine.
    exit /b 1
)
:vitis_ok

vitis_hls -version 2>nul | findstr /C:"2024.2" >nul 2>&1
if errorlevel 1 (
    if exist "C:\Xilinx\Vitis\2024.2\settings64.bat" (
        call "C:\Xilinx\Vitis\2024.2\settings64.bat" >nul 2>&1
    )
    vitis_hls -version 2>nul | findstr /C:"2024.2" >nul 2>&1
    if errorlevel 1 (
        echo ERROR: vitis_hls on PATH is not version 2024.2, and sourcing
        echo        C:\Xilinx\Vitis\2024.2\settings64.bat did not fix it.
        echo        This project's run_hls.tcl targets 2024.2 specifically.
        echo        Open a "Vitis HLS 2024.2 Command Prompt" shortcut instead
        echo        of a plain cmd/PowerShell, then re-run this script.
        exit /b 1
    )
)

:: Cosim/Package IP are selected via the RUN_HLS_COSIM/RUN_HLS_PACKAGE
:: environment variables, not vitis_hls command-line arguments - see
:: conv_engine_requant\run_hls.bat's header comment / TROUBLESHOOTING.md for
:: the real `ERROR: [HLS 200-101] Unknown option '--cosim'` finding this
:: works around. Both args are accepted in either order/combination:
:: `run_hls.bat`, `run_hls.bat cosim`, `run_hls.bat package`, or
:: `run_hls.bat cosim package`.
set "RUN_HLS_COSIM="
set "RUN_HLS_PACKAGE="
if /i "%~1"=="cosim"   (set "RUN_HLS_COSIM=1")
if /i "%~1"=="package" (set "RUN_HLS_PACKAGE=1")
if /i "%~2"=="cosim"   (set "RUN_HLS_COSIM=1")
if /i "%~2"=="package" (set "RUN_HLS_PACKAGE=1")

echo.
if defined RUN_HLS_COSIM (
    if defined RUN_HLS_PACKAGE (
        echo =^> Running vitis_hls ^(C-sim + C-synthesis + co-simulation + Package IP, all 3 engines^) - this is slow
    ) else (
        echo =^> Running vitis_hls ^(C-sim + C-synthesis + co-simulation, all 3 engines^) - this is slow
    )
) else (
    if defined RUN_HLS_PACKAGE (
        echo =^> Running vitis_hls ^(C-sim + C-synthesis + Package IP, all 3 engines^)
    ) else (
        echo =^> Running vitis_hls ^(C-sim + C-synthesis only, all 3 engines; pass "cosim" and/or "package" as arguments to also run co-simulation / Package IP^)
    )
)

set "LOG=%LOGDIR%\run_hls.log"
cd /d "%SCRIPT_DIR%"
call vitis_hls -f run_hls.tcl > "%LOG%" 2>&1
if errorlevel 1 (
    echo FAIL  vitis_hls exited with an error -- see %LOG%
    powershell -NoProfile -Command "Get-Content -Tail 40 -Path '%LOG%'"
    exit /b 1
)

set OVERALL_FAIL=0

:: 3 solutions -> expect each marker exactly 3 times. findstr /C /N counts
:: matching lines via `find /c`, not findstr itself - findstr has no
:: built-in occurrence-count flag. /B anchors to the start of the line so
:: this only matches pool_upsample_route_tb.cpp's own bare
:: `printf("ALL CONFIGS PASS\n")` output, not run_hls.tcl's
:: `==> [sol] C Simulation - expect "ALL CONFIGS PASS" ...` announcement
:: line, which contains the same substring mid-line and would otherwise
:: double the count (6/3 instead of 3/3).
for /f %%N in ('findstr /B /C:"ALL CONFIGS PASS" "%LOG%" ^| find /c /v ""') do set CSIM_COUNT=%%N
if "%CSIM_COUNT%"=="3" (
    echo PASS  C simulation -- all 3 engines printed ALL CONFIGS PASS
) else (
    echo FAIL  C simulation -- only %CSIM_COUNT%/3 engines printed ALL CONFIGS PASS -- see %LOG%
    findstr /C:"MISMATCH" /C:"FAIL" /C:"Assertion" /C:"C-SIM ERROR" "%LOG%"
    set OVERALL_FAIL=1
)

for /f %%N in ('findstr /I /C:"Finished Command csynth_design" "%LOG%" ^| find /c /v ""') do set CSYNTH_COUNT=%%N
if "%CSYNTH_COUNT%"=="3" (
    echo PASS  C synthesis -- all 3 engines completed -- see pool_upsample_route_prj\solution_*\syn\report\*_csynth.rpt
) else (
    echo FAIL  C synthesis -- only %CSYNTH_COUNT%/3 engines completed -- see %LOG%
    findstr /C:"C-SYNTH ERROR" "%LOG%"
    set OVERALL_FAIL=1
)

if defined RUN_HLS_COSIM (
    for /f %%N in ('findstr /I /C:"Finished Command cosim_design" /C:"co-simulation finished: PASS" "%LOG%" ^| find /c /v ""') do set COSIM_COUNT=%%N
    REM Use delayed-expansion !COSIM_COUNT! here, not percent-expansion.
    REM Percent-variables inside this whole if-block are substituted once,
    REM at parse time, before the `set` above ever runs - so the percent
    REM form would resolve to whatever COSIM_COUNT was BEFORE this block
    REM (empty, first time through), producing "if  GEQ 3 (", which cmd
    REM rejects with a stray "3 was unexpected at this time." parse error.
    if !COSIM_COUNT! GEQ 3 (
        echo PASS  C/RTL co-simulation -- all 3 engines
    ) else (
        echo FAIL  C/RTL co-simulation -- fewer than 3 engines confirmed -- see %LOG%
        findstr /C:"COSIM ERROR" "%LOG%"
        set OVERALL_FAIL=1
    )
)

if defined RUN_HLS_PACKAGE (
    :: No single log marker to count occurrences of here (export_design's
    :: own success message isn't a fixed string we've confirmed against a
    :: real run yet, unlike csim/csynth/cosim above) - check for the export
    :: directory itself instead, once per solution.
    set PACKAGE_COUNT=0
    if exist "%SCRIPT_DIR%pool_upsample_route_prj\solution_maxpool\impl\ip"       set /a PACKAGE_COUNT+=1
    if exist "%SCRIPT_DIR%pool_upsample_route_prj\solution_upsample\impl\ip"      set /a PACKAGE_COUNT+=1
    if exist "%SCRIPT_DIR%pool_upsample_route_prj\solution_route_concat\impl\ip"  set /a PACKAGE_COUNT+=1
    if !PACKAGE_COUNT! EQU 3 (
        echo PASS  Package IP -- all 3 engines exported -- see pool_upsample_route_prj\solution_*\impl\ip\
    ) else (
        echo FAIL  Package IP -- only !PACKAGE_COUNT!/3 engines exported -- see %LOG%
        findstr /C:"PACKAGE-IP ERROR" "%LOG%"
        set OVERALL_FAIL=1
    )
)

echo.
echo ========================================
if "%OVERALL_FAIL%"=="0" (
    echo   pool_upsample_route HLS run complete ^(all 3 engines^)
) else (
    echo   One or more engines did not confirm success -- see %LOG%
)
echo   Full reports: %SCRIPT_DIR%pool_upsample_route_prj\solution_{maxpool,upsample,route_concat}\
echo ========================================
echo.

exit /b %OVERALL_FAIL%
