# KR260 Final Transfer Package

Prepared: 2026-09-11

This folder contains the files needed to move the current YOLOv3-tiny ADAS
PL/PS project to a KR260 bring-up environment. Generated HLS work directories,
Vivado caches, duplicate experiment trees, slides, and large intermediate
reports were intentionally left out.

## Quick Start

1. Pick the hardware export that matches the PS runtime you are bringing up:
   `system_bringup_wrapper.xsa` for the 4-IP shared-conv design, or
   `sys5_wrapper.xsa` for the 5-IP design that also contains `conv0_engine`.
2. Use `03_runtime_descriptor/network_descriptor.json` as the PS runtime
   sequencing contract for the 22 hardware ops.
3. Use the register headers in `02_register_map/` as the authoritative
   AXI4-Lite offsets. `xconv0_engine_hw.h` is included for the `sys5_wrapper`
   path.
4. Load model blobs from `08_golden_model/int8/` or compile the generated
   headers under `06_hls_sources/conv_engine_requant_merged/SW/`.
5. Use `04_layer0_contract/` and `05_golden_heads/` for first-board
   correctness checks.

## Folder Map

| Folder | Contents | Use |
| --- | --- | --- |
| `01_hardware_exports/` | XSA files, extracted bit/hwh files, routed timing/utilization reports, UART/IRQ Tcl and XDC | PetaLinux/Vitis platform, Linux overlay, and board wiring |
| `02_register_map/` | Generated `x*_hw.h` plus generated Linux driver skeletons | PS MMIO programming |
| `03_runtime_descriptor/` | 22-op JSON descriptor and README | End-to-end runtime sequencing |
| `04_layer0_contract/` | Layer-0 input/weight/bias/expected binaries | Preprocessing and first conv verification |
| `05_golden_heads/` | Final raw head reference binaries | End-to-end output sanity check |
| `06_hls_sources/` | Minimal HLS source trees for conv/maxpool/upsample/route | Rebuild or inspect HLS IP |
| `07_hls_ip_zips/` | Packaged HLS IP zip files | Vivado IP repository import |
| `08_golden_model/` | Golden model code, INT8 blobs, selected sample dumps | Reference model and model assets |
| `09_docs/` | Handoff notes and PS resource notes | Integration context |
| `10_verification_reports/` | C-sim/C-synth/Cosim reports where available | Verification evidence |

## Hardware Export Notes

- `system_bringup_wrapper.xsa` / `extracted_system_bringup_wrapper/`
  - SHA256: `5e9556a1aee699d385d6df86721d0fd9ce86cacd742d352cf472a0b17a783d44`
  - Documented in `09_docs/PS_전달_XSA_UART정정.md`.
  - Contains generated drivers for `conv_engine`, `maxpool_engine`,
    `upsample_engine`, and `route_concat_engine`.
  - Includes UART1 as console and UART0 routed through EMIO for the RPi header.
  - Interrupts for conv/maxpool/upsample/route_concat are documented as wired
    through `xlconcat` to `pl_ps_irq0`.

- `sys5_wrapper.xsa` / `extracted_sys5_wrapper/`
  - SHA256: `69b281a7e41f5719766f5335bfc722dea7c0dd09313010ec8560063857891dd6`
  - Contains `conv0_engine` plus the shared conv/maxpool/upsample/route IPs.
  - Use this when the PS side expects a dedicated layer-0 engine.

Standalone `.bit` and `.hwh` files have been extracted from both XSAs for
Linux overlay workflows. The original XSAs are still kept for Xilinx tools.

## Runtime Contract

`03_runtime_descriptor/network_descriptor.json` is the small PS-facing runtime
contract. It avoids the huge generated verification headers and uses byte
offsets consistently.

Important PS assumptions:

- AXI4-Lite control windows:
  - Conv: `0xA0000000`, 64 KiB
  - MaxPool: `0xA0010000`, 64 KiB
  - Upsample: `0xA0020000`, 64 KiB
  - Route/Concat: `0xA0030000`, 64 KiB
- Required contiguous DDR scratch:
  - `accum` scratch max: 14,155,776 bytes
  - model weights: 8,672,688 bytes
  - model bias: 12,976 bytes
- Keep cache ownership explicit for CPU-written input and PL-written heads.

See `09_docs/PS_RESOURCE_REQUIREMENTS.md` for the fuller PS checklist.

## Verification Files

Layer-0 contract:

- `04_layer0_contract/layer00_input.bin`: 290 x 514 x 3, NHWC, signed INT8,
  already padded by 1 pixel with `-128`.
- `04_layer0_contract/layer00_weights.bin`: OIHW INT8 weights.
- `04_layer0_contract/layer00_bias.bin`: corrected INT32 bias.
- `04_layer0_contract/layer00_expected_output.bin`: 288 x 512 x 16, NHWC INT8.

Final heads:

- `05_golden_heads/head1_layer15_9x16x30_nhwc_int8.bin`: 4,320 bytes.
- `05_golden_heads/head2_layer22_18x32x30_nhwc_int8.bin`: 17,280 bytes.

These head binaries were copied from
`darknet_golden/artifacts/int8_layers_sample/layer_15.bin` and `layer_22.bin`,
matching the scales documented in the original handoff README:

- head1 scale: `0.21446585467481238`
- head2 scale: `0.2062814967838798`

## What Was Excluded

- HLS build caches and generated work dirs such as `.autopilot`, `csim/build`,
  most `syn/verilog`, `syn/vhdl`, and `impl` trees.
- Duplicate `hls (1)` source copies.
- `conv_engine_wpack_ochoist/`, `oc_hoist_g2/`, and V5 experiment folders.
  Those are performance experiments or baseline archives, not required for
  KR260 bring-up. The relevant summary docs are preserved in `09_docs/`.
- Slides and Jetson/TurtleBot presentation material.
- The old 2026-08-04 packaged-folder checksum file, because this package was
  rebuilt on 2026-09-11 and has its own `CHECKSUMS.sha256`.

## Known Gaps

- Full KR260 board execution has still not been proven inside this workspace.
  The available evidence is HLS C-sim/C-synth/Cosim plus the exported XSA.
- Only `conv_engine` has a preserved `*_cosim.rpt` file in this package.
  The pool/upsample/route README documents cosim completion, but their cosim
  report files were not present in the current workspace.
- The runtime descriptor generator script mentioned in older notes was not
  present in the current workspace, so the descriptor itself is included as the
  contract artifact.
- If PS code expects a standalone `.bit`, re-export hardware from Vivado with
  bitstream or extract it from the XSA using the normal Xilinx flow.
