// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XUPSAMPLE_ENGINE_H
#define XUPSAMPLE_ENGINE_H

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
#include "xupsample_engine_hw.h"

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
} XUpsample_engine_Config;
#endif

typedef struct {
    u64 Ctrl_BaseAddress;
    u32 IsReady;
} XUpsample_engine;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XUpsample_engine_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XUpsample_engine_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XUpsample_engine_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XUpsample_engine_ReadReg(BaseAddress, RegOffset) \
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
int XUpsample_engine_Initialize(XUpsample_engine *InstancePtr, UINTPTR BaseAddress);
XUpsample_engine_Config* XUpsample_engine_LookupConfig(UINTPTR BaseAddress);
#else
int XUpsample_engine_Initialize(XUpsample_engine *InstancePtr, u16 DeviceId);
XUpsample_engine_Config* XUpsample_engine_LookupConfig(u16 DeviceId);
#endif
int XUpsample_engine_CfgInitialize(XUpsample_engine *InstancePtr, XUpsample_engine_Config *ConfigPtr);
#else
int XUpsample_engine_Initialize(XUpsample_engine *InstancePtr, const char* InstanceName);
int XUpsample_engine_Release(XUpsample_engine *InstancePtr);
#endif

void XUpsample_engine_Start(XUpsample_engine *InstancePtr);
u32 XUpsample_engine_IsDone(XUpsample_engine *InstancePtr);
u32 XUpsample_engine_IsIdle(XUpsample_engine *InstancePtr);
u32 XUpsample_engine_IsReady(XUpsample_engine *InstancePtr);
void XUpsample_engine_EnableAutoRestart(XUpsample_engine *InstancePtr);
void XUpsample_engine_DisableAutoRestart(XUpsample_engine *InstancePtr);

void XUpsample_engine_Set_ifmap(XUpsample_engine *InstancePtr, u64 Data);
u64 XUpsample_engine_Get_ifmap(XUpsample_engine *InstancePtr);
void XUpsample_engine_Set_ofmap(XUpsample_engine *InstancePtr, u64 Data);
u64 XUpsample_engine_Get_ofmap(XUpsample_engine *InstancePtr);
void XUpsample_engine_Set_img_h(XUpsample_engine *InstancePtr, u32 Data);
u32 XUpsample_engine_Get_img_h(XUpsample_engine *InstancePtr);
void XUpsample_engine_Set_img_w(XUpsample_engine *InstancePtr, u32 Data);
u32 XUpsample_engine_Get_img_w(XUpsample_engine *InstancePtr);
void XUpsample_engine_Set_ch(XUpsample_engine *InstancePtr, u32 Data);
u32 XUpsample_engine_Get_ch(XUpsample_engine *InstancePtr);

void XUpsample_engine_InterruptGlobalEnable(XUpsample_engine *InstancePtr);
void XUpsample_engine_InterruptGlobalDisable(XUpsample_engine *InstancePtr);
void XUpsample_engine_InterruptEnable(XUpsample_engine *InstancePtr, u32 Mask);
void XUpsample_engine_InterruptDisable(XUpsample_engine *InstancePtr, u32 Mask);
void XUpsample_engine_InterruptClear(XUpsample_engine *InstancePtr, u32 Mask);
u32 XUpsample_engine_InterruptGetEnabled(XUpsample_engine *InstancePtr);
u32 XUpsample_engine_InterruptGetStatus(XUpsample_engine *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
