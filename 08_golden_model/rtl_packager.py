"""RTL testbench package/export and comparison helpers for Darknet INT8 golden model."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import numpy as np


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_array(path: Path, dtype: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    if path.suffix == ".npy":
        arr = np.load(path)
    else:
        arr = np.fromfile(path, dtype=np.dtype(dtype))
        if shape is not None:
            arr = arr.reshape(shape)
    return arr


def package_rtl_testbench(artifacts_dir: Path, output: Path, include_npy: bool = False) -> Path:
    artifacts_dir = artifacts_dir.resolve()
    int8_dir = artifacts_dir / "int8"
    sample_dir = artifacts_dir / "int8_layers"
    if not int8_dir.exists() or not sample_dir.exists():
        raise FileNotFoundError(
            f"Expected artifacts structure: {int8_dir} and {sample_dir} must exist"
        )

    files_to_package = []

    # core RTL package files
    files_to_package.extend(
        [
            int8_dir / "model_manifest.json",
            int8_dir / "weight.bin",
            int8_dir / "bias.bin",
            int8_dir / "requant.bin",
            int8_dir / "scale.bin",
            sample_dir / "manifest.json",
            sample_dir / "input_uint8.bin",
            sample_dir / "input_manifest.json",
        ]
    )
    decoded_path = artifacts_dir / "int8_decoded.npy"
    if decoded_path.exists():
        files_to_package.append(decoded_path)

    for sample_file in sorted(sample_dir.glob("layer_*.bin")):
        files_to_package.append(sample_file)
        if include_npy:
            npy = sample_file.with_suffix(".npy")
            if npy.exists():
                files_to_package.append(npy)

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for path in files_to_package:
            if not path.exists():
                raise FileNotFoundError(f"Missing package file: {path}")
            arcname = path.relative_to(artifacts_dir)
            zipf.write(path, arcname)

    return output


def find_matching_rtl_file(rtl_dir: Path, base: str) -> Path | None:
    candidates = [
        rtl_dir / f"{base}.bin",
        rtl_dir / f"{base}_rtl.bin",
        rtl_dir / f"{base}.npy",
        rtl_dir / f"{base}_rtl.npy",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def compare_rtl_outputs(gold_dir: Path, rtl_dir: Path, report_path: Path, compare_input: bool = False) -> Path:
    gold_dir = gold_dir.resolve()
    rtl_dir = rtl_dir.resolve()
    report_lines: list[str] = []

    manifest_path = gold_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Golden manifest not found: {manifest_path}")
    manifest = load_json(manifest_path)

    if compare_input:
        input_manifest_path = gold_dir / "input_manifest.json"
        if input_manifest_path.exists():
            input_entry = load_json(input_manifest_path)
            _compare_single_file(
                gold_dir,
                rtl_dir,
                input_entry["file"],
                input_entry["dtype"],
                tuple(input_entry["shape"]),
                report_lines,
                label="input_uint8",
            )
        else:
            report_lines.append("INPUT_MANIFEST_MISSING: input_manifest.json not found in golden directory")

    for entry in manifest:
        base = Path(entry["file"]).stem
        _compare_single_file(
            gold_dir,
            rtl_dir,
            entry["file"],
            entry["dtype"],
            tuple(entry["shape"]),
            report_lines,
            label=base,
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return report_path


def _compare_single_file(
    gold_dir: Path,
    rtl_dir: Path,
    gold_file: str,
    dtype: str,
    shape: tuple[int, ...],
    report_lines: list[str],
    label: str,
) -> None:
    gold_path = gold_dir / gold_file
    if not gold_path.exists():
        report_lines.append(f"MISSING_GOLD: {gold_file}")
        return

    rtl_path = find_matching_rtl_file(rtl_dir, Path(gold_file).stem)
    if rtl_path is None:
        report_lines.append(
            f"MISSING_RTL: {label} (no {Path(gold_file).stem}[_rtl].bin/.npy found in {rtl_dir})"
        )
        return

    gold_array = read_array(gold_path, dtype, shape)
    rtl_array = read_array(rtl_path, dtype, shape)
    if gold_array.shape != rtl_array.shape:
        report_lines.append(
            f"SHAPE_MISMATCH: {label} gold={gold_array.shape} rtl={rtl_array.shape}"
        )
        return

    if np.issubdtype(gold_array.dtype, np.integer):
        eq = gold_array == rtl_array
        mismatch_count = int(np.size(eq) - int(np.count_nonzero(eq)))
        if mismatch_count == 0:
            report_lines.append(f"{label}: EXACT")
        else:
            diff = gold_array.astype(np.int32) - rtl_array.astype(np.int32)
            max_diff = int(np.max(np.abs(diff)))
            first_mismatch = np.argwhere(diff != 0)[0]
            report_lines.append(
                f"{label}: MISMATCH count={mismatch_count} max_diff={max_diff} first_pos={tuple(int(x) for x in first_mismatch)} "
                f"gold={int(gold_array[tuple(first_mismatch)])} rtl={int(rtl_array[tuple(first_mismatch)])}"
            )
    else:
        diff = np.abs(gold_array.astype(np.float32) - rtl_array.astype(np.float32))
        max_diff = float(np.max(diff))
        mean_diff = float(np.mean(diff))
        report_lines.append(
            f"{label}: float max_diff={max_diff:.6g} mean_diff={mean_diff:.6g}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    package_parser = subparsers.add_parser("package", help="Create an RTL testbench package archive")
    package_parser.add_argument("--artifacts-dir", required=True, help="darknet_golden artifacts root")
    package_parser.add_argument("--output", required=True, help="Output zip package path")
    package_parser.add_argument(
        "--include-npy",
        action="store_true",
        help="Include .npy reference files in the package",
    )
    package_parser.set_defaults(func=lambda args: package_rtl_testbench(Path(args.artifacts_dir), Path(args.output), args.include_npy))

    compare_parser = subparsers.add_parser("compare", help="Compare RTL dumps to golden int8 sample outputs")
    compare_parser.add_argument("--gold", required=True, help="Golden int8 sample directory")
    compare_parser.add_argument("--rtl", required=True, help="RTL dump directory")
    compare_parser.add_argument("--out", required=True, help="Output compare report path")
    compare_parser.add_argument(
        "--compare-input",
        action="store_true",
        help="Also compare input_uint8.bin against RTL input dump if available",
    )
    compare_parser.set_defaults(func=lambda args: compare_rtl_outputs(Path(args.gold), Path(args.rtl), Path(args.out), args.compare_input))

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if isinstance(result, Path):
        print(f"Wrote: {result}")


if __name__ == "__main__":
    main()
