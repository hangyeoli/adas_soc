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
#include "xroute_concat_engine.h"

extern XRoute_concat_engine_Config XRoute_concat_engine_ConfigTable[];

#ifdef SDT
XRoute_concat_engine_Config *XRoute_concat_engine_LookupConfig(UINTPTR BaseAddress) {
	XRoute_concat_engine_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XRoute_concat_engine_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XRoute_concat_engine_ConfigTable[Index].Ctrl_BaseAddress == BaseAddress) {
			ConfigPtr = &XRoute_concat_engine_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XRoute_concat_engine_Initialize(XRoute_concat_engine *InstancePtr, UINTPTR BaseAddress) {
	XRoute_concat_engine_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XRoute_concat_engine_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XRoute_concat_engine_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XRoute_concat_engine_Config *XRoute_concat_engine_LookupConfig(u16 DeviceId) {
	XRoute_concat_engine_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XROUTE_CONCAT_ENGINE_NUM_INSTANCES; Index++) {
		if (XRoute_concat_engine_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XRoute_concat_engine_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XRoute_concat_engine_Initialize(XRoute_concat_engine *InstancePtr, u16 DeviceId) {
	XRoute_concat_engine_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XRoute_concat_engine_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XRoute_concat_engine_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

