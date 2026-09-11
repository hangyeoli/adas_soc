// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xroute_concat_engine.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XRoute_concat_engine_CfgInitialize(XRoute_concat_engine *InstancePtr, XRoute_concat_engine_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Ctrl_BaseAddress = ConfigPtr->Ctrl_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XRoute_concat_engine_Start(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL) & 0x80;
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XRoute_concat_engine_IsDone(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XRoute_concat_engine_IsIdle(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XRoute_concat_engine_IsReady(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XRoute_concat_engine_EnableAutoRestart(XRoute_concat_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL, 0x80);
}

void XRoute_concat_engine_DisableAutoRestart(XRoute_concat_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_AP_CTRL, 0);
}

void XRoute_concat_engine_Set_src0(XRoute_concat_engine *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_DATA, (u32)(Data));
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_DATA + 4, (u32)(Data >> 32));
}

u64 XRoute_concat_engine_Get_src0(XRoute_concat_engine *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_DATA);
    Data += (u64)XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_DATA + 4) << 32;
    return Data;
}

void XRoute_concat_engine_Set_src1(XRoute_concat_engine *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_DATA, (u32)(Data));
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_DATA + 4, (u32)(Data >> 32));
}

u64 XRoute_concat_engine_Get_src1(XRoute_concat_engine *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_DATA);
    Data += (u64)XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_DATA + 4) << 32;
    return Data;
}

void XRoute_concat_engine_Set_ofmap(XRoute_concat_engine *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_OFMAP_DATA, (u32)(Data));
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_OFMAP_DATA + 4, (u32)(Data >> 32));
}

u64 XRoute_concat_engine_Get_ofmap(XRoute_concat_engine *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_OFMAP_DATA);
    Data += (u64)XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_OFMAP_DATA + 4) << 32;
    return Data;
}

void XRoute_concat_engine_Set_img_h(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_H_DATA, Data);
}

u32 XRoute_concat_engine_Get_img_h(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_H_DATA);
    return Data;
}

void XRoute_concat_engine_Set_img_w(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_W_DATA, Data);
}

u32 XRoute_concat_engine_Get_img_w(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IMG_W_DATA);
    return Data;
}

void XRoute_concat_engine_Set_ch0(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH0_DATA, Data);
}

u32 XRoute_concat_engine_Get_ch0(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH0_DATA);
    return Data;
}

void XRoute_concat_engine_Set_ch1(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH1_DATA, Data);
}

u32 XRoute_concat_engine_Get_ch1(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_CH1_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src0_requant_enable(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_ENABLE_DATA, Data);
}

u32 XRoute_concat_engine_Get_src0_requant_enable(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_ENABLE_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src0_requant_multiplier(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_MULTIPLIER_DATA, Data);
}

u32 XRoute_concat_engine_Get_src0_requant_multiplier(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_MULTIPLIER_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src0_requant_shift(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_SHIFT_DATA, Data);
}

u32 XRoute_concat_engine_Get_src0_requant_shift(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC0_REQUANT_SHIFT_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src1_requant_enable(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_ENABLE_DATA, Data);
}

u32 XRoute_concat_engine_Get_src1_requant_enable(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_ENABLE_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src1_requant_multiplier(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_MULTIPLIER_DATA, Data);
}

u32 XRoute_concat_engine_Get_src1_requant_multiplier(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_MULTIPLIER_DATA);
    return Data;
}

void XRoute_concat_engine_Set_src1_requant_shift(XRoute_concat_engine *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_SHIFT_DATA, Data);
}

u32 XRoute_concat_engine_Get_src1_requant_shift(XRoute_concat_engine *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_SRC1_REQUANT_SHIFT_DATA);
    return Data;
}

void XRoute_concat_engine_InterruptGlobalEnable(XRoute_concat_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_GIE, 1);
}

void XRoute_concat_engine_InterruptGlobalDisable(XRoute_concat_engine *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_GIE, 0);
}

void XRoute_concat_engine_InterruptEnable(XRoute_concat_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER);
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER, Register | Mask);
}

void XRoute_concat_engine_InterruptDisable(XRoute_concat_engine *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER);
    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER, Register & (~Mask));
}

void XRoute_concat_engine_InterruptClear(XRoute_concat_engine *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XRoute_concat_engine_WriteReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_ISR, Mask);
}

u32 XRoute_concat_engine_InterruptGetEnabled(XRoute_concat_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_IER);
}

u32 XRoute_concat_engine_InterruptGetStatus(XRoute_concat_engine *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XRoute_concat_engine_ReadReg(InstancePtr->Ctrl_BaseAddress, XROUTE_CONCAT_ENGINE_CTRL_ADDR_ISR);
}

