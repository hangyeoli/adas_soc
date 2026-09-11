"""Darknet weight loader and BN-folded FP32 YOLOv3-tiny golden model."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F

from .config import DarknetConfig, int_list


@dataclass(frozen=True)
class DarknetHeader:
    major: int
    minor: int
    revision: int
    seen: int
    byte_count: int


@dataclass
class ConvLayer:
    index: int
    in_channels: int
    out_channels: int
    kernel: int
    stride: int
    padding: int
    activation: str
    batch_normalize: bool
    weight: np.ndarray
    bias: np.ndarray
    darknet_weight_offset: int


@dataclass
class ForwardResult:
    heads: List[torch.Tensor]
    head_layer_indices: List[int]
    layers: Dict[int, torch.Tensor] | None = None


def _read_darknet_payload(path: str | Path) -> tuple[DarknetHeader, np.ndarray]:
    raw = Path(path).read_bytes()
    if len(raw) < 16:
        raise ValueError(f"Not a Darknet weights file: {path}")
    major, minor, revision = np.frombuffer(raw, dtype="<i4", count=3).tolist()
    uses_seen64 = major < 1000 and minor < 1000 and major * 10 + minor >= 2
    if uses_seen64:
        seen = int(np.frombuffer(raw, dtype="<u8", count=1, offset=12)[0])
        header_bytes = 20
    else:
        seen = int(np.frombuffer(raw, dtype="<u4", count=1, offset=12)[0])
        header_bytes = 16
    payload_bytes = len(raw) - header_bytes
    if payload_bytes % 4:
        raise ValueError(f"Weight payload is not float32-aligned: {payload_bytes} bytes")
    payload = np.frombuffer(raw, dtype="<f4", offset=header_bytes).copy()
    return DarknetHeader(major, minor, revision, seen, header_bytes), payload


def _take(payload: np.ndarray, offset: int, count: int, name: str) -> tuple[np.ndarray, int]:
    end = offset + count
    if end > payload.size:
        raise ValueError(
            f"Darknet weights ended while reading {name}: need {count}, "
            f"only {payload.size - offset} float32 values remain"
        )
    return payload[offset:end], end


def load_darknet_convolutions(
    cfg: DarknetConfig, weights_path: str | Path
) -> tuple[DarknetHeader, Dict[int, ConvLayer]]:
    """Read Darknet serialization order and fold every Conv+BN into Conv+bias."""
    header, payload = _read_darknet_payload(weights_path)
    output_channels = cfg.output_channels()
    offset = 0
    convolutions: Dict[int, ConvLayer] = {}

    for index, block in enumerate(cfg.layers):
        if block["type"] != "convolutional":
            continue
        groups = int(block.get("groups", "1"))
        if groups != 1:
            raise ValueError(f"Grouped convolution is not supported (layer {index}, groups={groups})")
        in_channels = cfg.channels if index == 0 else output_channels[index - 1]
        out_channels = int(block["filters"])
        kernel = int(block["size"])
        bn = bool(int(block.get("batch_normalize", "0")))
        serialized_offset = offset

        bias_or_beta, offset = _take(payload, offset, out_channels, f"layer {index} bias/beta")
        if bn:
            gamma, offset = _take(payload, offset, out_channels, f"layer {index} BN gamma")
            mean, offset = _take(payload, offset, out_channels, f"layer {index} BN mean")
            variance, offset = _take(payload, offset, out_channels, f"layer {index} BN variance")
        weight_count = out_channels * in_channels * kernel * kernel
        weight_flat, offset = _take(payload, offset, weight_count, f"layer {index} convolution")
        weight = weight_flat.reshape(out_channels, in_channels, kernel, kernel)

        if bn:
            # Darknet inference uses sqrt(rolling_variance + 1e-5).
            scale = gamma / np.sqrt(variance + np.float32(1.0e-5))
            folded_weight = weight * scale[:, None, None, None]
            folded_bias = bias_or_beta - mean * scale
        else:
            folded_weight = weight
            folded_bias = bias_or_beta

        convolutions[index] = ConvLayer(
            index=index,
            in_channels=in_channels,
            out_channels=out_channels,
            kernel=kernel,
            stride=int(block.get("stride", "1")),
            padding=(kernel - 1) // 2 if int(block.get("pad", "0")) else 0,
            activation=block.get("activation", "linear"),
            batch_normalize=bn,
            weight=np.ascontiguousarray(folded_weight, dtype=np.float32),
            bias=np.ascontiguousarray(folded_bias, dtype=np.float32),
            darknet_weight_offset=serialized_offset,
        )

    if offset != payload.size:
        raise ValueError(
            f"CFG/weights mismatch: consumed {offset:,} of {payload.size:,} float32 values "
            f"({payload.size - offset:+,} remain)"
        )
    return header, convolutions


def _darknet_resize_chw(image: torch.Tensor, height: int, width: int) -> torch.Tensor:
    """Match Darknet resize_image(): bilinear interpolation with aligned corner pixels."""
    if image.shape[-2:] == (height, width):
        return image.clone()
    return F.interpolate(image, size=(height, width), mode="bilinear", align_corners=True)


def load_image(
    path: str | Path, cfg: DarknetConfig, force_letterbox: bool | None = None
) -> tuple[torch.Tensor, Dict[str, object]]:
    """Load BGR with OpenCV, convert to RGB/0..1 and apply Darknet test-time resize."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment error path
        raise RuntimeError("opencv-python is required to read images") from exc

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    source_h, source_w = rgb.shape[:2]
    chw = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float().unsqueeze(0) / 255.0
    use_letterbox = cfg.letter_box if force_letterbox is None else force_letterbox

    if not use_letterbox:
        output = _darknet_resize_chw(chw, cfg.height, cfg.width)
        meta = {
            "mode": "darknet_resize",
            "source_size": [source_w, source_h],
            "network_size": [cfg.width, cfg.height],
        }
        return output, meta

    if cfg.width / source_w < cfg.height / source_h:
        resized_w = cfg.width
        resized_h = source_h * cfg.width // source_w
    else:
        resized_h = cfg.height
        resized_w = source_w * cfg.height // source_h
    resized = _darknet_resize_chw(chw, resized_h, resized_w)
    output = torch.full((1, 3, cfg.height, cfg.width), 0.5, dtype=torch.float32)
    left = (cfg.width - resized_w) // 2
    top = (cfg.height - resized_h) // 2
    output[:, :, top : top + resized_h, left : left + resized_w] = resized
    meta = {
        "mode": "darknet_letterbox",
        "source_size": [source_w, source_h],
        "network_size": [cfg.width, cfg.height],
        "resized_size": [resized_w, resized_h],
        "padding": [left, top, cfg.width - resized_w - left, cfg.height - resized_h - top],
    }
    return output, meta


class DarknetGoldenModel:
    """CFG interpreter using folded float32 convolution parameters."""

    def __init__(
        self,
        cfg: DarknetConfig,
        header: DarknetHeader,
        convolutions: Mapping[int, ConvLayer],
        device: str | torch.device = "cpu",
    ) -> None:
        self.cfg = cfg
        self.header = header
        self.convolutions = dict(convolutions)
        self.device = torch.device(device)
        self._torch_params = {
            index: (
                torch.from_numpy(layer.weight).to(self.device),
                torch.from_numpy(layer.bias).to(self.device),
            )
            for index, layer in self.convolutions.items()
        }

    def forward(
        self,
        image: torch.Tensor,
        *,
        capture_layers: bool = False,
        callback: Callable[[int, Mapping[str, str], torch.Tensor], None] | None = None,
    ) -> ForwardResult:
        x = image.to(self.device, dtype=torch.float32)
        outputs: Dict[int, torch.Tensor] = {}
        captured: Dict[int, torch.Tensor] | None = {} if capture_layers else None
        heads: List[torch.Tensor] = []
        head_indices: List[int] = []

        with torch.inference_mode():
            for index, block in enumerate(self.cfg.layers):
                kind = block["type"]
                if kind == "convolutional":
                    layer = self.convolutions[index]
                    weight, bias = self._torch_params[index]
                    x = F.conv2d(x, weight, bias, stride=layer.stride, padding=layer.padding)
                    if layer.activation == "leaky":
                        x = F.leaky_relu(x, negative_slope=0.1)
                    elif layer.activation != "linear":
                        raise ValueError(f"Unsupported activation at layer {index}: {layer.activation}")
                elif kind == "maxpool":
                    size = int(block["size"])
                    stride = int(block["stride"])
                    total_pad = int(block.get("padding", str(size - 1)))
                    before = total_pad // 2
                    after = total_pad - before
                    x = F.pad(x, (before, after, before, after), value=-math.inf)
                    x = F.max_pool2d(x, kernel_size=size, stride=stride)
                elif kind == "upsample":
                    x = F.interpolate(x, scale_factor=int(block["stride"]), mode="nearest")
                elif kind == "route":
                    refs = self.cfg.resolve_route(index, block["layers"])
                    x = outputs[refs[0]] if len(refs) == 1 else torch.cat([outputs[ref] for ref in refs], 1)
                elif kind == "yolo":
                    heads.append(x)
                    head_indices.append(index)
                else:
                    raise ValueError(f"Unsupported layer {kind} at index {index}")

                outputs[index] = x
                if callback is not None:
                    callback(index, block, x)
                if captured is not None:
                    captured[index] = x.detach().cpu().clone()

        return ForwardResult(heads, head_indices, captured)

    def decode(self, result: ForwardResult) -> torch.Tensor:
        """Decode two raw YOLO tensors to normalized [x,y,w,h,obj,class...] rows."""
        decoded: List[torch.Tensor] = []
        for raw, layer_index in zip(result.heads, result.head_layer_indices):
            block = self.cfg.layers[layer_index]
            classes = int(block["classes"])
            mask = int_list(block["mask"])
            flat_anchors = int_list(block["anchors"])
            anchors = [(flat_anchors[2 * item], flat_anchors[2 * item + 1]) for item in mask]
            n, channels, height, width = raw.shape
            expected = len(anchors) * (classes + 5)
            if channels != expected:
                raise ValueError(f"YOLO layer {layer_index}: expected {expected} channels, got {channels}")

            pred = raw.reshape(n, len(anchors), classes + 5, height, width).permute(0, 1, 3, 4, 2)
            grid_y, grid_x = torch.meshgrid(
                torch.arange(height, device=raw.device, dtype=raw.dtype),
                torch.arange(width, device=raw.device, dtype=raw.dtype),
                indexing="ij",
            )
            anchor_tensor = torch.tensor(anchors, dtype=raw.dtype, device=raw.device)
            output = torch.empty_like(pred)
            output[..., 0] = (torch.sigmoid(pred[..., 0]) + grid_x) / width
            output[..., 1] = (torch.sigmoid(pred[..., 1]) + grid_y) / height
            output[..., 2] = torch.exp(pred[..., 2]) * anchor_tensor[:, None, None, 0] / self.cfg.width
            output[..., 3] = torch.exp(pred[..., 3]) * anchor_tensor[:, None, None, 1] / self.cfg.height
            output[..., 4:] = torch.sigmoid(pred[..., 4:])
            decoded.append(output.reshape(n, -1, classes + 5))
        return torch.cat(decoded, dim=1)

    def summary(self) -> List[Dict[str, object]]:
        channels = self.cfg.output_channels()
        rows: List[Dict[str, object]] = []
        height, width = self.cfg.height, self.cfg.width
        for index, block in enumerate(self.cfg.layers):
            kind = block["type"]
            if kind == "convolutional":
                kernel = int(block["size"])
                stride = int(block.get("stride", "1"))
                pad = (kernel - 1) // 2 if int(block.get("pad", "0")) else 0
                height = (height + 2 * pad - kernel) // stride + 1
                width = (width + 2 * pad - kernel) // stride + 1
            elif kind == "maxpool":
                size, stride = int(block["size"]), int(block["stride"])
                padding = int(block.get("padding", str(size - 1)))
                height = (height + padding - size) // stride + 1
                width = (width + padding - size) // stride + 1
            elif kind == "upsample":
                height *= int(block["stride"])
                width *= int(block["stride"])
            elif kind == "route":
                refs = self.cfg.resolve_route(index, block["layers"])
                source = rows[refs[0]]["shape"]
                height, width = int(source[1]), int(source[2])
            rows.append({"index": index, "type": kind, "shape": [channels[index], height, width]})
        return rows


def load_darknet_model(
    cfg_path: str | Path, weights_path: str | Path, device: str | torch.device = "cpu"
) -> DarknetGoldenModel:
    cfg = DarknetConfig.load(cfg_path)
    header, convolutions = load_darknet_convolutions(cfg, weights_path)
    return DarknetGoldenModel(cfg, header, convolutions, device=device)


def dump_fp32_layers(result: ForwardResult, output_dir: str | Path) -> None:
    if result.layers is None:
        raise ValueError("forward() must be called with capture_layers=True")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, object]] = []
    for index, tensor in result.layers.items():
        array = tensor.numpy().astype("<f4", copy=False)
        filename = f"layer_{index:02d}.npy"
        np.save(output / filename, array)
        manifest.append({"layer": index, "file": filename, "shape": list(array.shape), "dtype": "float32"})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
