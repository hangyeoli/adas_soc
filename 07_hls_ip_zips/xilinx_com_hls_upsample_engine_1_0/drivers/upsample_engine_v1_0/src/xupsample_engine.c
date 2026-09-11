// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xupsample_engine.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XUpsample_engine_CfgInitialize(XUpsample_engine *InstancePtr, XUpsample_engine_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Ctrl_BaseAddress = ConfigPtr->Ctrl_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XUpsample_engine_Start(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL) & 0x80;
    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XUpsample_engine_IsDone(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XUpsample_engine_IsIdle(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XUpsample_engine_IsReady(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XUpsample_engine_EnableAutoRestart(XUpsample_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL, 0x80);
}

void XUpsample_engine_DisableAutoRestart(XUpsample_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_AP_CTRL, 0);
}

void XUpsample_engine_Set_ifmap(XUpsample_engine *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IFMAP_DATA, (u32)(Data));
    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IFMAP_DATA + 4, (u32)(Data >> 32));
}

u64 XUpsample_engine_Get_ifmap(XUpsample_engine *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IFMAP_DATA);
    Data += (u64)XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IFMAP_DATA + 4) << 32;
    return Data;
}

void XUpsample_engine_Set_ofmap(XUpsample_engine *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_OFMAP_DATA, (u32)(Data));
    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_OFMAP_DATA + 4, (u32)(Data >> 32));
}

u64 XUpsample_engine_Get_ofmap(XUpsample_engine *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_OFMAP_DATA);
    Data += (u64)XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_OFMAP_DATA + 4) << 32;
    return Data;
}

void XUpsample_engine_Set_img_h(XUpsample_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IMG_H_DATA, Data);
}

u32 XUpsample_engine_Get_img_h(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IMG_H_DATA);
    return Data;
}

void XUpsample_engine_Set_img_w(XUpsample_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IMG_W_DATA, Data);
}

u32 XUpsample_engine_Get_img_w(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IMG_W_DATA);
    return Data;
}

void XUpsample_engine_Set_ch(XUpsample_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_CH_DATA, Data);
}

u32 XUpsample_engine_Get_ch(XUpsample_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_CH_DATA);
    return Data;
}

void XUpsample_engine_InterruptGlobalEnable(XUpsample_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_GIE, 1);
}

void XUpsample_engine_InterruptGlobalDisable(XUpsample_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_GIE, 0);
}

void XUpsample_engine_InterruptEnable(XUpsample_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IER);
    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IER, Register | Mask);
}

void XUpsample_engine_InterruptDisable(XUpsample_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IER);
    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IER, Register & (~Mask));
}

void XUpsample_engine_InterruptClear(XUpsample_engine *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XUpsample_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_ISR, Mask);
}

u32 XUpsample_engine_InterruptGetEnabled(XUpsample_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_IER);
}

u32 XUpsample_engine_InterruptGetStatus(XUpsample_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XUpsample_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XUPSAMPLE_ENGINE_CTRL_ADDR_ISR);
}

