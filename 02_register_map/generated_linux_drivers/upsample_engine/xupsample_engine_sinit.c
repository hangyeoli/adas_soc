// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef __linux__

#include "xstatus.h"
#ifdef SDT
#include "xparameters.h"
#endif
#include "xupsample_engine.h"

extern XUpsample_engine_Config XUpsample_engine_ConfigTable[];

#ifdef SDT
XUpsample_engine_Config *XUpsample_engine_LookupConfig(UINTPTR BaseAddress) {
	XUpsample_engine_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XUpsample_engine_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XUpsample_engine_ConfigTable[Index].Ctrl_BaseAddress == BaseAddress) {
			ConfigPtr = &XUpsample_engine_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XUpsample_engine_Initialize(XUpsample_engine *InstancePtr, UINTPTR BaseAddress) {
	XUpsample_engine_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XUpsample_engine_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XUpsample_engine_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XUpsample_engine_Config *XUpsample_engine_LookupConfig(u16 DeviceId) {
	XUpsample_engine_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XUPSAMPLE_ENGINE_NUM_INSTANCES; Index++) {
		if (XUpsample_engine_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XUpsample_engine_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XUpsample_engine_Initialize(XUpsample_engine *InstancePtr, u16 DeviceId) {
	XUpsample_engine_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XUpsample_engine_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XUpsample_engine_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

