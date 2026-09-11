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
// 0x10 : Data signal of ifmap
//        bit 31~0 - ifmap[31:0] (Read/Write)
// 0x14 : Data signal of ifmap
//        bit 31~0 - ifmap[63:32] (Read/Write)
// 0x18 : reserved
// 0x1c : Data signal of weights
//        bit 31~0 - weights[31:0] (Read/Write)
// 0x20 : Data signal of weights
//        bit 31~0 - weights[63:32] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of weights_hi
//        bit 31~0 - weights_hi[31:0] (Read/Write)
// 0x2c : Data signal of weights_hi
//        bit 31~0 - weights_hi[63:32] (Read/Write)
// 0x30 : reserved
// 0x34 : Data signal of bias
//        bit 31~0 - bias[31:0] (Read/Write)
// 0x38 : Data signal of bias
//        bit 31~0 - bias[63:32] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of ofmap
//        bit 31~0 - ofmap[31:0] (Read/Write)
// 0x44 : Data signal of ofmap
//        bit 31~0 - ofmap[63:32] (Read/Write)
// 0x48 : reserved
// 0x4c : Data signal of accum
//        bit 31~0 - accum[31:0] (Read/Write)
// 0x50 : Data signal of accum
//        bit 31~0 - accum[63:32] (Read/Write)
// 0x54 : reserved
// 0x58 : Data signal of img_h
//        bit 15~0 - img_h[15:0] (Read/Write)
//        others   - reserved
// 0x5c : reserved
// 0x60 : Data signal of img_w
//        bit 15~0 - img_w[15:0] (Read/Write)
//        others   - reserved
// 0x64 : reserved
// 0x68 : Data signal of in_ch
//        bit 15~0 - in_ch[15:0] (Read/Write)
//        others   - reserved
// 0x6c : reserved
// 0x70 : Data signal of out_ch
//        bit 15~0 - out_ch[15:0] (Read/Write)
//        others   - reserved
// 0x74 : reserved
// 0x78 : Data signal of k
//        bit 7~0 - k[7:0] (Read/Write)
//        others  - reserved
// 0x7c : reserved
// 0x80 : Data signal of stride
//        bit 7~0 - stride[7:0] (Read/Write)
//        others  - reserved
// 0x84 : reserved
// 0x88 : Data signal of pad
//        bit 7~0 - pad[7:0] (Read/Write)
//        others  - reserved
// 0x8c : reserved
// 0x90 : Data signal of requant_multiplier
//        bit 31~0 - requant_multiplier[31:0] (Read/Write)
// 0x94 : reserved
// 0x98 : Data signal of requant_shift
//        bit 7~0 - requant_shift[7:0] (Read/Write)
//        others  - reserved
// 0x9c : reserved
// 0xa0 : Data signal of leaky_relu_enable
//        bit 7~0 - leaky_relu_enable[7:0] (Read/Write)
//        others  - reserved
// 0xa4 : reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XCONV_ENGINE_CTRL_ADDR_AP_CTRL                 0x00
#define XCONV_ENGINE_CTRL_ADDR_GIE                     0x04
#define XCONV_ENGINE_CTRL_ADDR_IER                     0x08
#define XCONV_ENGINE_CTRL_ADDR_ISR                     0x0c
#define XCONV_ENGINE_CTRL_ADDR_IFMAP_DATA              0x10
#define XCONV_ENGINE_CTRL_BITS_IFMAP_DATA              64
#define XCONV_ENGINE_CTRL_ADDR_WEIGHTS_DATA            0x1c
#define XCONV_ENGINE_CTRL_BITS_WEIGHTS_DATA            64
#define XCONV_ENGINE_CTRL_ADDR_WEIGHTS_HI_DATA         0x28
#define XCONV_ENGINE_CTRL_BITS_WEIGHTS_HI_DATA         64
#define XCONV_ENGINE_CTRL_ADDR_BIAS_DATA               0x34
#define XCONV_ENGINE_CTRL_BITS_BIAS_DATA               64
#define XCONV_ENGINE_CTRL_ADDR_OFMAP_DATA              0x40
#define XCONV_ENGINE_CTRL_BITS_OFMAP_DATA              64
#define XCONV_ENGINE_CTRL_ADDR_ACCUM_DATA              0x4c
#define XCONV_ENGINE_CTRL_BITS_ACCUM_DATA              64
#define XCONV_ENGINE_CTRL_ADDR_IMG_H_DATA              0x58
#define XCONV_ENGINE_CTRL_BITS_IMG_H_DATA              16
#define XCONV_ENGINE_CTRL_ADDR_IMG_W_DATA              0x60
#define XCONV_ENGINE_CTRL_BITS_IMG_W_DATA              16
#define XCONV_ENGINE_CTRL_ADDR_IN_CH_DATA              0x68
#define XCONV_ENGINE_CTRL_BITS_IN_CH_DATA              16
#define XCONV_ENGINE_CTRL_ADDR_OUT_CH_DATA             0x70
#define XCONV_ENGINE_CTRL_BITS_OUT_CH_DATA             16
#define XCONV_ENGINE_CTRL_ADDR_K_DATA                  0x78
#define XCONV_ENGINE_CTRL_BITS_K_DATA                  8
#define XCONV_ENGINE_CTRL_ADDR_STRIDE_DATA             0x80
#define XCONV_ENGINE_CTRL_BITS_STRIDE_DATA             8
#define XCONV_ENGINE_CTRL_ADDR_PAD_DATA                0x88
#define XCONV_ENGINE_CTRL_BITS_PAD_DATA                8
#define XCONV_ENGINE_CTRL_ADDR_REQUANT_MULTIPLIER_DATA 0x90
#define XCONV_ENGINE_CTRL_BITS_REQUANT_MULTIPLIER_DATA 32
#define XCONV_ENGINE_CTRL_ADDR_REQUANT_SHIFT_DATA      0x98
#define XCONV_ENGINE_CTRL_BITS_REQUANT_SHIFT_DATA      8
#define XCONV_ENGINE_CTRL_ADDR_LEAKY_RELU_ENABLE_DATA  0xa0
#define XCONV_ENGINE_CTRL_BITS_LEAKY_RELU_ENABLE_DATA  8

