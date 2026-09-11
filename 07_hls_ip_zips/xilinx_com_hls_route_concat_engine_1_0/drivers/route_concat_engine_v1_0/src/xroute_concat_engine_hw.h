// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
// CTRL
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read/COR)
//        bit 7  - auto_restart (Read/Write)
//        bit 9  - interrupt (Read)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0 - enable ap_done interrupt (Read/Write)
//        bit 1 - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0 - ap_done (Read/TOW)
//        bit 1 - ap_ready (Read/TOW)
//        others - reserved
// 0x10 : Data signal of src0
//        bit 31~0 - src0[31:0] (Read/Write)
// 0x14 : Data signal of src0
//        bit 31~0 - src0[63:32] (Read/Write)
// 0x18 : reserved
// 0x1c : Data signal of src1
//        bit 31~0 - src1[31:0] (Read/Write)
// 0x20 : Data signal of src1
//        bit 31~0 - src1[63:32] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of ofmap
//        bit 31~0 - ofmap[31:0] (Read/Write)
// 0x2c : Data signal of ofmap
//        bit 31~0 - ofmap[63:32] (Read/Write)
// 0x30 : reserved
// 0x34 : Data signal of img_h
//        bit 15~0 - img_h[15:0] (Read/Write)
//        others   - reserved
// 0x38 : reserved
// 0x3c : Data signal of img_w
//        bit 15~0 - img_w[15:0] (Read/Write)
//        others   - reserved
// 0x40 : reserved
// 0x44 : Data signal of ch0
//        bit 15~0 - ch0[15:0] (Read/Write)
//        others   - reserved
// 0x48 : reserved
// 0x4c : Data signal of ch1
//        bit 15~0 - ch1[15:0] (Read/Write)
//        others   - reserved
// 0x50 : reserved
// 0x54 : Data signal of src0_requant_enable
//        bit 7~0 - src0_requant_enable[7:0] (Read/Write)
//        others  - reserved
// 0x58 : reserved
// 0x5c : Data signal of src0_requant_multiplier
//        bit 31~0 - src0_requant_multiplier[31:0] (Read/Write)
// 0x60 : reserved
// 0x64 : Data signal of src0_requant_shift
//        bit 7~0 - src0_requant_shift[7:0] (Read/Write)
//        others  - reserved
// 0x68 : reserved
// 0x6c : Data signal of src1_requant_enable
//        bit 7~0 - src1_requant_enable[7:0] (Read/Write)
//        others  - reserved
// 0x70 : reserved
// 0x74 : Data signal of src1_requant_multiplier
//        bit 31~0 - src1_requant_multiplier[31:0] (Read/Write)
// 0x78 : reserved
// 0x7c : Data signal of src1_requant_shift
//        bit 7~0 - src1_requant_shift[7:0] (Read/Write)
//        others  - reserved
// 0x80 : reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL                      0x00
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_GIE                          0x04
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER                          0x08
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_ISR                          0x0c
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_DATA                    0x10
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC0_DATA                    64
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_DATA                    0x1c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC1_DATA                    64
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_OFMAP_DATA                   0x28
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_OFMAP_DATA                   64
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_H_DATA                   0x34
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_IMG_H_DATA                   16
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_W_DATA                   0x3c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_IMG_W_DATA                   16
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH0_DATA                     0x44
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_CH0_DATA                     16
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH1_DATA                     0x4c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_CH1_DATA                     16
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_ENABLE_DATA     0x54
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC0_REQUANT_ENABLE_DATA     8
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_MULTIPLIER_DATA 0x5c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC0_REQUANT_MULTIPLIER_DATA 32
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_SHIFT_DATA      0x64
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC0_REQUANT_SHIFT_DATA      8
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_ENABLE_DATA     0x6c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC1_REQUANT_ENABLE_DATA     8
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_MULTIPLIER_DATA 0x74
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC1_REQUANT_MULTIPLIER_DATA 32
#define XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_SHIFT_DATA      0x7c
#define XROUTE_CONCAT_ENGINE_CTRL_BITS_SRC1_REQUANT_SHIFT_DATA      8

