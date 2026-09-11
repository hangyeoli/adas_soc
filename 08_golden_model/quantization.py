"""INT8 calibration, export and integer-domain golden inference."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping

import numpy as np
import torch
import torch.nn.functional as F

from .model import DarknetGoldenModel, ForwardResult


class ActivationCollector:
    """Bounded deterministic sampling of per-layer FP32 activations."""

    def __init__(self, max_samples: int = 200_000, samples_per_tensor: int = 8192, seed: int = 12345):
        self.max_samples = max_samples
        self.samples_per_tensor = samples_per_tensor
        self.seed = seed
        self._state: Dict[int, Dict[str, object]] = {}

    def update(self, layer_index: int, _block: Mapping[str, str], tensor: torch.Tensor) -> None:
        detached = tensor.detach()
        flat = detached.abs().reshape(-1)
        step = max(1, math.ceil(flat.numel() / self.samples_per_tensor))
        sample = flat[::step][: self.samples_per_tensor].float().cpu().numpy()
        minimum = float(detached.min().item())
        maximum = float(detached.max().item())
        state = self._state.setdefault(
            layer_index,
            {
                "samples": np.empty(0, dtype=np.float32),
                "min": minimum,
                "max": maximum,
                "absmax": max(abs(minimum), abs(maximum)),
                "tensors": 0,
            },
        )
        state["min"] = min(float(state["min"]), minimum)
        state["max"] = max(float(state["max"]), maximum)
        state["absmax"] = max(float(state["absmax"]), abs(minimum), abs(maximum))
        state["tensors"] = int(state["tensors"]) + 1
        combined = np.concatenate((state["samples"], sample))
        if combined.size > self.max_samples:
            rng = np.random.default_rng(self.seed + layer_index + 1009 * int(state["tensors"]))
            selected = rng.choice(combined.size, self.max_samples, replace=False)
            combined = combined[selected]
        state["samples"] = combined

    def report(self, percentile: float, activation_bits: int) -> Dict[str, object]:
        if not 0 < percentile <= 100:
            raise ValueError("percentile must be in (0, 100]")
        qmax = (1 << (activation_bits - 1)) - 1
        layers: Dict[str, object] = {}
        for index in sorted(self._state):
            state = self._state[index]
            samples = np.asarray(state["samples"])
            threshold = float(np.percentile(samples, percentile)) if samples.size else float(state["absmax"])
            threshold = max(threshold, 1.0e-12)
            layers[str(index)] = {
                "min": float(state["min"]),
                "max": float(state["max"]),
                "absmax": float(state["absmax"]),
                "percentile": percentile,
                "threshold": threshold,
                "scale": threshold / qmax,
                "bits": activation_bits,
                "sample_count": int(samples.size),
                "tensor_count": int(state["tensors"]),
            }
        return {"activation_bits": activation_bits, "percentile": percentile, "layers": layers}


def quantize_multiplier(real_multiplier: float) -> tuple[int, int]:
    """Represent a positive real value as multiplier / 2**right_shift."""
    if not math.isfinite(real_multiplier) or real_multiplier <= 0:
        raise ValueError(f"Invalid requantization multiplier: {real_multiplier}")
    significand, exponent = math.frexp(real_multiplier)
    multiplier = int(round(significand * (1 << 31)))
    if multiplier == 1 << 31:
        multiplier //= 2
        exponent += 1
    return multiplier, 31 - exponent


def round_divide_by_pot_signed(values: np.ndarray, shift: int) -> np.ndarray:
    """Round to nearest, ties away from zero, then divide by 2**shift."""
    values = values.astype(np.int64, copy=False)
    if shift < 0:
        return values << (-shift)
    if shift == 0:
        return values
    magnitude = np.abs(values)
    rounded = (magnitude + (1 << (shift - 1))) >> shift
    return np.where(values < 0, -rounded, rounded).astype(np.int64)


def apply_multiplier(values: np.ndarray, multiplier: int, right_shift: int) -> np.ndarray:
    product = values.astype(np.int64, copy=False) * np.int64(multiplier)
    return round_divide_by_pot_signed(product, right_shift)


def requantize_array(
    values: np.ndarray, source_scale: float, target_scale: float, bits: int = 8
) -> tuple[np.ndarray, int, int]:
    multiplier, right_shift = quantize_multiplier(source_scale / target_scale)
    output = apply_multiplier(values, multiplier, right_shift)
    qmin, qmax = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return np.clip(output, qmin, qmax).astype(np.int64), multiplier, right_shift


def _layer_scale(calibration: Mapping[str, object], index: int) -> float:
    try:
        return float(calibration["layers"][str(index)]["scale"])
    except KeyError as exc:
        raise ValueError(f"Calibration has no activation scale for layer {index}") from exc


def export_int8_package(
    model: DarknetGoldenModel,
    calibration: Mapping[str, object],
    output_dir: str | Path,
    *,
    weight_bits: int = 8,
    activation_bits: int = 8,
    leaky_numerator: int = 13,
    leaky_shift: int = 7,
) -> Path:
    """Quantize folded parameters and emit NPZ plus flat little-endian RTL files."""
    if weight_bits != 8 or activation_bits != 8:
        raise ValueError("This exporter currently supports signed INT8 weights/activations only")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    weight_blob = bytearray()
    bias_blob = bytearray()
    requant_blob = bytearray()
    scale_blob = bytearray()
    arrays: Dict[str, np.ndarray] = {}
    layers: List[Dict[str, object]] = []
    current_scale = 1.0 / 255.0  # input is exported as exact UINT8 RGB pixels
    layer_output_scales: Dict[int, float] = {}

    for index, block in enumerate(model.cfg.layers):
        kind = block["type"]
        target_scale = _layer_scale(calibration, index)
        # These operators do not alter numeric values, so retaining the source
        # scale avoids a pointless extra rounding stage. A concat route is the
        # only non-Conv operator that may need a new common scale.
        if kind in {"maxpool", "upsample", "yolo"}:
            target_scale = current_scale
        elif kind == "route":
            refs_for_scale = model.cfg.resolve_route(index, block["layers"])
            if len(refs_for_scale) == 1:
                target_scale = layer_output_scales[refs_for_scale[0]]
        entry: Dict[str, object] = {
            "index": index,
            "type": kind,
            "output_scale": target_scale,
            "output_bits": activation_bits,
        }
        if kind == "convolutional":
            conv = model.convolutions[index]
            qmax = (1 << (weight_bits - 1)) - 1
            weight_absmax = float(np.max(np.abs(conv.weight)))
            weight_scale = max(weight_absmax / qmax, 1.0e-12)
            qweight = np.clip(np.rint(conv.weight / weight_scale), -qmax, qmax).astype(np.int8)
            qbias64 = np.rint(conv.bias / (current_scale * weight_scale)).astype(np.int64)
            if np.any(qbias64 < np.iinfo(np.int32).min) or np.any(qbias64 > np.iinfo(np.int32).max):
                raise OverflowError(f"Layer {index} bias does not fit INT32")
            qbias = qbias64.astype("<i4")
            multiplier, right_shift = quantize_multiplier(current_scale * weight_scale / target_scale)

            weight_offset = len(weight_blob)
            bias_offset = len(bias_blob)
            requant_offset = len(requant_blob)
            scale_offset = len(scale_blob)
            weight_blob.extend(qweight.tobytes(order="C"))
            bias_blob.extend(qbias.tobytes(order="C"))
            requant_blob.extend(np.asarray([multiplier, right_shift], dtype="<i4").tobytes())
            scale_blob.extend(np.asarray([current_scale, weight_scale, target_scale], dtype="<f4").tobytes())
            arrays[f"layer_{index:02d}_weight"] = qweight
            arrays[f"layer_{index:02d}_bias"] = qbias

            max_input = 255 if index == 0 else 127
            accumulator_bound = (
                conv.in_channels * conv.kernel * conv.kernel * max_input * 127
                + int(np.max(np.abs(qbias64)))
            )
            if accumulator_bound >= 1 << 53:
                raise OverflowError(f"Layer {index} accumulator bound exceeds exact float64 integer range")
            entry.update(
                {
                    "input_scale": current_scale,
                    "input_channels": conv.in_channels,
                    "output_channels": conv.out_channels,
                    "kernel": conv.kernel,
                    "stride": conv.stride,
                    "padding": conv.padding,
                    "activation": conv.activation,
                    "weight_scale": weight_scale,
                    "weight_layout": "OIHW",
                    "weight_shape": list(qweight.shape),
                    "weight_offset_bytes": weight_offset,
                    "weight_size_bytes": qweight.nbytes,
                    "bias_offset_bytes": bias_offset,
                    "bias_size_bytes": qbias.nbytes,
                    "requant_offset_bytes": requant_offset,
                    "requant_multiplier": multiplier,
                    "requant_right_shift": right_shift,
                    "scale_offset_bytes": scale_offset,
                    "accumulator_bound": accumulator_bound,
                }
            )
        elif kind == "route":
            refs = model.cfg.resolve_route(index, block["layers"])
            entry["sources"] = refs
            source_requant = []
            for source_index in refs:
                source_scale = layer_output_scales[source_index]
                if source_scale == target_scale:
                    source_requant.append(
                        {
                            "source": source_index,
                            "source_scale": source_scale,
                            "operation": "passthrough",
                        }
                    )
                else:
                    multiplier, right_shift = quantize_multiplier(source_scale / target_scale)
                    requant_offset = len(requant_blob)
                    requant_blob.extend(np.asarray([multiplier, right_shift], dtype="<i4").tobytes())
                    source_requant.append(
                        {
                            "source": source_index,
                            "source_scale": source_scale,
                            "operation": "requantize",
                            "requant_offset_bytes": requant_offset,
                            "requant_multiplier": multiplier,
                            "requant_right_shift": right_shift,
                        }
                    )
            entry["source_requantization"] = source_requant
        elif kind == "yolo":
            entry.update(
                {
                    "mask": [int(x.strip()) for x in block["mask"].split(",")],
                    "anchors": [int(x.strip()) for x in block["anchors"].split(",")],
                    "classes": int(block["classes"]),
                }
            )
        elif kind not in {"maxpool", "upsample"}:
            raise ValueError(f"Unsupported layer {index}: {kind}")
        layers.append(entry)
        current_scale = target_scale
        layer_output_scales[index] = target_scale

    (output / "weight.bin").write_bytes(weight_blob)
    (output / "bias.bin").write_bytes(bias_blob)
    (output / "requant.bin").write_bytes(requant_blob)
    (output / "scale.bin").write_bytes(scale_blob)
    np.savez(output / "model_int8.npz", **arrays)
    manifest = {
        "format_version": 1,
        "network": {
            "width": model.cfg.width,
            "height": model.cfg.height,
            "channels": model.cfg.channels,
            "input_dtype": "uint8",
            "input_layout": "NCHW",
            "input_scale": 1.0 / 255.0,
            "classes": int(next(b["classes"] for b in model.cfg.layers if b["type"] == "yolo")),
        },
        "quantization": {
            "weight_bits": weight_bits,
            "activation_bits": activation_bits,
            "weight_granularity": "per_tensor_symmetric",
            "activation_granularity": "per_tensor_symmetric",
            "rounding": "nearest_ties_away_from_zero",
            "saturation": "signed_int8",
            "leaky_relu": f"{leaky_numerator}/2^{leaky_shift}",
            "accumulator": "signed_int64_reference; every layer bounded to fit signed_int32/float64 exact integer",
        },
        "files": {
            "weights": "weight.bin",
            "biases": "bias.bin",
            "requantization": "requant.bin",
            "scales": "scale.bin",
            "numpy_archive": "model_int8.npz",
        },
        "layers": layers,
    }
    manifest_path = output / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


@dataclass
class QuantizedTensor:
    values: np.ndarray
    scale: float
    bits: int = 8


@dataclass
class Int8ForwardResult:
    heads: List[QuantizedTensor]
    head_layer_indices: List[int]
    layers: Dict[int, QuantizedTensor] | None


def _integer_conv2d_exact(
    x: np.ndarray, weight: np.ndarray, bias: np.ndarray, stride: int, padding: int
) -> np.ndarray:
    """Accelerated exact integer MAC: float64 is exact because manifest bounds are <2**53."""
    tx = torch.from_numpy(np.ascontiguousarray(x)).to(torch.float64)
    tw = torch.from_numpy(np.ascontiguousarray(weight)).to(torch.float64)
    tb = torch.from_numpy(np.ascontiguousarray(bias.astype(np.int64))).to(torch.float64)
    result = F.conv2d(tx, tw, tb, stride=stride, padding=padding)
    rounded = torch.round(result)
    if not torch.equal(result, rounded):
        raise ArithmeticError("Exact integer convolution produced a non-integer float64 result")
    return rounded.to(torch.int64).cpu().numpy()


def _maxpool_int(x: np.ndarray, size: int, stride: int, total_padding: int) -> np.ndarray:
    before = total_padding // 2
    after = total_padding - before
    padded = np.pad(
        x,
        ((0, 0), (0, 0), (before, after), (before, after)),
        mode="constant",
        constant_values=np.iinfo(np.int64).min,
    )
    windows = np.lib.stride_tricks.sliding_window_view(padded, (size, size), axis=(2, 3))
    return windows[:, :, ::stride, ::stride].max(axis=(-1, -2))


class Int8GoldenModel:
    def __init__(self, float_model: DarknetGoldenModel, package_dir: str | Path):
        self.float_model = float_model
        self.cfg = float_model.cfg
        self.package_dir = Path(package_dir)
        self.manifest = json.loads((self.package_dir / "model_manifest.json").read_text(encoding="utf-8"))
        archive = np.load(self.package_dir / self.manifest["files"]["numpy_archive"])
        self.weights = {name: archive[name] for name in archive.files}
        self.layer_meta = {int(item["index"]): item for item in self.manifest["layers"]}
        quant = self.manifest["quantization"]
        fraction = quant["leaky_relu"].split("/2^")
        self.leaky_numerator = int(fraction[0])
        self.leaky_shift = int(fraction[1])

    @staticmethod
    def quantize_input(fp32_image: torch.Tensor | np.ndarray) -> QuantizedTensor:
        array = fp32_image.detach().cpu().numpy() if isinstance(fp32_image, torch.Tensor) else fp32_image
        pixels = np.clip(np.rint(array * 255.0), 0, 255).astype(np.int64)
        return QuantizedTensor(pixels, 1.0 / 255.0, 8)

    @staticmethod
    def _convert(source: QuantizedTensor, target_scale: float, bits: int = 8) -> QuantizedTensor:
        if source.scale == target_scale and source.bits == bits:
            return QuantizedTensor(source.values, source.scale, source.bits)
        values, _, _ = requantize_array(source.values, source.scale, target_scale, bits)
        return QuantizedTensor(values, target_scale, bits)

    def forward(self, image: torch.Tensor | np.ndarray, *, capture_layers: bool = False) -> Int8ForwardResult:
        x = self.quantize_input(image)
        outputs: Dict[int, QuantizedTensor] = {}
        captured: Dict[int, QuantizedTensor] | None = {} if capture_layers else None
        heads: List[QuantizedTensor] = []
        head_indices: List[int] = []

        for index, block in enumerate(self.cfg.layers):
            kind = block["type"]
            meta = self.layer_meta[index]
            target_scale = float(meta["output_scale"])
            if kind == "convolutional":
                weight = self.weights[f"layer_{index:02d}_weight"]
                bias = self.weights[f"layer_{index:02d}_bias"]
                acc = _integer_conv2d_exact(
                    x.values, weight, bias, int(meta["stride"]), int(meta["padding"])
                )
                if meta["activation"] == "leaky":
                    negative = acc < 0
                    acc = acc.copy()
                    acc[negative] = round_divide_by_pot_signed(
                        acc[negative] * self.leaky_numerator, self.leaky_shift
                    )
                values = apply_multiplier(
                    acc, int(meta["requant_multiplier"]), int(meta["requant_right_shift"])
                )
                values = np.clip(values, -128, 127).astype(np.int64)
                x = QuantizedTensor(values, target_scale)
            elif kind == "maxpool":
                size, stride = int(block["size"]), int(block["stride"])
                pooled = _maxpool_int(x.values, size, stride, int(block.get("padding", str(size - 1))))
                x = self._convert(QuantizedTensor(pooled, x.scale), target_scale)
            elif kind == "upsample":
                factor = int(block["stride"])
                values = np.repeat(np.repeat(x.values, factor, axis=2), factor, axis=3)
                x = self._convert(QuantizedTensor(values, x.scale), target_scale)
            elif kind == "route":
                refs = self.cfg.resolve_route(index, block["layers"])
                sources = [self._convert(outputs[ref], target_scale) for ref in refs]
                values = sources[0].values if len(sources) == 1 else np.concatenate([s.values for s in sources], 1)
                x = QuantizedTensor(values, target_scale)
            elif kind == "yolo":
                x = self._convert(x, target_scale)
                heads.append(x)
                head_indices.append(index)
            else:
                raise ValueError(f"Unsupported layer {index}: {kind}")
            outputs[index] = x
            if captured is not None:
                captured[index] = QuantizedTensor(x.values.copy(), x.scale, x.bits)
        return Int8ForwardResult(heads, head_indices, captured)

    def decode(self, result: Int8ForwardResult) -> torch.Tensor:
        float_result = ForwardResult(
            [torch.from_numpy(head.values.astype(np.float32) * head.scale) for head in result.heads],
            result.head_layer_indices,
        )
        return self.float_model.decode(float_result)


def dump_int8_layers(result: Int8ForwardResult, output_dir: str | Path) -> None:
    if result.layers is None:
        raise ValueError("forward() must be called with capture_layers=True")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, object]] = []
    for index, tensor in result.layers.items():
        array = tensor.values.astype(np.int8)
        filename = f"layer_{index:02d}.bin"
        (output / filename).write_bytes(array.tobytes(order="C"))
        np.save(output / f"layer_{index:02d}.npy", array)
        manifest.append(
            {
                "layer": index,
                "file": filename,
                "npy": f"layer_{index:02d}.npy",
                "shape": list(array.shape),
                "layout": "NCHW",
                "dtype": "int8",
                "scale": tensor.scale,
            }
        )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def dump_uint8_input(image: torch.Tensor | np.ndarray, output_dir: str | Path) -> None:
    """Dump the exact resized/quantized NCHW input used by Int8GoldenModel."""
    quantized = Int8GoldenModel.quantize_input(image)
    array = quantized.values.astype(np.uint8)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "input_uint8.bin").write_bytes(array.tobytes(order="C"))
    np.save(output / "input_uint8.npy", array)
    metadata = {
        "file": "input_uint8.bin",
        "npy": "input_uint8.npy",
        "shape": list(array.shape),
        "layout": "NCHW",
        "dtype": "uint8",
        "scale": quantized.scale,
        "zero_point": 0,
        "source_order": "RGB",
    }
    (output / "input_manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
