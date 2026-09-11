"""Small, strict parser for the Darknet cfg subset used by YOLOv3-tiny."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


def parse_cfg(path: str | Path) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                if current is not None:
                    blocks.append(current)
                current = {"type": line[1:-1].strip()}
                continue
            if current is None or "=" not in line:
                raise ValueError(f"Malformed cfg line {line_number}: {raw_line.rstrip()}")
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
    if current is not None:
        blocks.append(current)
    if not blocks or blocks[0]["type"] not in {"net", "network"}:
        raise ValueError("Darknet cfg must start with [net]")
    return blocks


def int_list(value: str) -> List[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class DarknetConfig:
    path: Path
    blocks: List[Dict[str, str]]

    @classmethod
    def load(cls, path: str | Path) -> "DarknetConfig":
        cfg_path = Path(path).resolve()
        return cls(cfg_path, parse_cfg(cfg_path))

    @property
    def net(self) -> Dict[str, str]:
        return self.blocks[0]

    @property
    def layers(self) -> List[Dict[str, str]]:
        return self.blocks[1:]

    @property
    def width(self) -> int:
        return int(self.net["width"])

    @property
    def height(self) -> int:
        return int(self.net["height"])

    @property
    def channels(self) -> int:
        return int(self.net.get("channels", 3))

    @property
    def letter_box(self) -> bool:
        return bool(int(self.net.get("letter_box", "0")))

    def resolve_route(self, layer_index: int, value: str) -> List[int]:
        return [item if item >= 0 else layer_index + item for item in int_list(value)]

    def output_channels(self) -> List[int]:
        channels: List[int] = []
        current = self.channels
        for index, block in enumerate(self.layers):
            kind = block["type"]
            if kind == "convolutional":
                current = int(block["filters"])
            elif kind == "route":
                refs = self.resolve_route(index, block["layers"])
                if any(ref < 0 or ref >= index for ref in refs):
                    raise ValueError(f"Invalid route at layer {index}: {refs}")
                current = sum(channels[ref] for ref in refs)
            elif kind not in {"maxpool", "upsample", "yolo"}:
                raise ValueError(f"Unsupported Darknet layer type: {kind}")
            channels.append(current)
        return channels
