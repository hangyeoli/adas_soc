// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XROUTE_CONCAT_ENGINE_H
#define XROUTE_CONCAT_ENGINE_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xroute_concat_engine_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Ctrl_BaseAddress;
} XRoute_concat_engine_Config;
#endif

typedef struct {
    u64 Ctrl_BaseAddress;
    u32 IsReady;
} XRoute_concat_engine;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XRoute_concat_engine_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XRoute_concat_engine_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XRoute_concat_engine_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XRoute_concat_engine_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XRoute_concat_engine_Initialize(XRoute_concat_engine *InstancePtr, UINTPTR BaseAddress);
XRoute_concat_engine_Config* XRoute_concat_engine_LookupConfig(UINTPTR BaseAddress);
#else
int XRoute_concat_engine_Initialize(XRoute_concat_engine *InstancePtr, u16 DeviceId);
XRoute_concat_engine_Config* XRoute_concat_engine_LookupConfig(u16 DeviceId);
#endif
int XRoute_concat_engine_CfgInitialize(XRoute_concat_engine *InstancePtr, XRoute_concat_engine_Config *ConfigPtr);
#else
int XRoute_concat_engine_Initialize(XRoute_concat_engine *InstancePtr, const char* InstanceName);
int XRoute_concat_engine_Release(XRoute_concat_engine *InstancePtr);
#endif

void XRoute_concat_engine_Start(XRoute_concat_engine *InstancePtr);
u32 XRoute_concat_engine_IsDone(XRoute_concat_engine *InstancePtr);
u32 XRoute_concat_engine_IsIdle(XRoute_concat_engine *InstancePtr);
u32 XRoute_concat_engine_IsReady(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_EnableAutoRestart(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_DisableAutoRestart(XRoute_concat_engine *InstancePtr);

void XRoute_concat_engine_Set_src0(XRoute_concat_engine *InstancePtr, u64 Data);
u64 XRoute_concat_engine_Get_src0(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src1(XRoute_concat_engine *InstancePtr, u64 Data);
u64 XRoute_concat_engine_Get_src1(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_ofmap(XRoute_concat_engine *InstancePtr, u64 Data);
u64 XRoute_concat_engine_Get_ofmap(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_img_h(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_img_h(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_img_w(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_img_w(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_ch0(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_ch0(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_ch1(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_ch1(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src0_requant_enable(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src0_requant_enable(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src0_requant_multiplier(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src0_requant_multiplier(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src0_requant_shift(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src0_requant_shift(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src1_requant_enable(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src1_requant_enable(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src1_requant_multiplier(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src1_requant_multiplier(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_Set_src1_requant_shift(XRoute_concat_engine *InstancePtr, u32 Data);
u32 XRoute_concat_engine_Get_src1_requant_shift(XRoute_concat_engine *InstancePtr);

void XRoute_concat_engine_InterruptGlobalEnable(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_InterruptGlobalDisable(XRoute_concat_engine *InstancePtr);
void XRoute_concat_engine_InterruptEnable(XRoute_concat_engine *InstancePtr, u32 Mask);
void XRoute_concat_engine_InterruptDisable(XRoute_concat_engine *InstancePtr, u32 Mask);
void XRoute_concat_engine_InterruptClear(XRoute_concat_engine *InstancePtr, u32 Mask);
u32 XRoute_concat_engine_InterruptGetEnabled(XRoute_concat_engine *InstancePtr);
u32 XRoute_concat_engine_InterruptGetStatus(XRoute_concat_engine *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
