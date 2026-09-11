"""Command line entry point for the Darknet FP32/INT8 golden-model pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from .metrics import MeanAveragePrecision, label_path_for_image, load_yolo_labels, postprocess
from .model import dump_fp32_layers, load_darknet_model, load_image
from .quantization import (
    ActivationCollector,
    Int8GoldenModel,
    dump_int8_layers,
    dump_uint8_input,
    export_int8_package,
)
from .rtl_packager import compare_rtl_outputs, package_rtl_testbench


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CFG = ROOT / "darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg"
DEFAULT_WEIGHTS = (
    ROOT
    / "adas_dataset_yolov3_tiny_5class_balanced_512x288_additional_ft_corrected_focus_v2/backup/"
    "yolov3-tiny-adas-5class-balanced-512x288_best.weights"
)
DEFAULT_DATASET = ROOT / "adas_dataset_yolov3_tiny_5class_balanced_512x288"
DEFAULT_VAL = DEFAULT_DATASET / "val.txt"
DEFAULT_NAMES = DEFAULT_DATASET / "adas.names"
DEFAULT_ARTIFACTS = ROOT / "yolo_tiny/darknet_golden/artifacts_additional_ft_corrected_focus_v2"


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cfg", default=str(DEFAULT_CFG))
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    parser.add_argument("--device", default="cpu", help="cpu, cuda, cuda:0 ...")


def _image_paths(list_path: str | Path, limit: int | None) -> list[Path]:
    lines = [line.strip() for line in Path(list_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    paths = [Path(line) for line in lines]
    return paths if limit is None or limit <= 0 else paths[:limit]


def command_inspect(args: argparse.Namespace) -> None:
    model = load_darknet_model(args.cfg, args.weights, args.device)
    print(
        f"Darknet header: {model.header.major}.{model.header.minor}.{model.header.revision}, "
        f"seen={model.header.seen:,}, header={model.header.byte_count} bytes"
    )
    print(f"network: {model.cfg.width}x{model.cfg.height}x{model.cfg.channels}")
    print(f"{'idx':>3}  {'type':<14} {'shape (C,H,W)':<22}")
    for row in model.summary():
        print(f"{row['index']:>3}  {row['type']:<14} {str(tuple(row['shape'])):<22}")
    print(f"convolution layers: {len(model.convolutions)}")


def command_fp32(args: argparse.Namespace) -> None:
    model = load_darknet_model(args.cfg, args.weights, args.device)
    image, preprocess = load_image(args.image, model.cfg)
    result = model.forward(image, capture_layers=bool(args.dump_dir))
    decoded = model.decode(result).cpu().numpy()
    if args.dump_dir:
        dump_fp32_layers(result, args.dump_dir)
    if args.decoded_out:
        output = Path(args.decoded_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.save(output, decoded)
    detections = postprocess(decoded, args.confidence, args.nms)
    print(json.dumps({"preprocess": preprocess, "heads": [list(x.shape) for x in result.heads]}, indent=2))
    print(f"decoded={decoded.shape}, detections={len(detections)}")
    for item in detections[: args.show]:
        print(f"class={item.class_id} score={item.score:.6f} xyxy={item.box_xyxy.tolist()}")


def run_calibration(args: argparse.Namespace, model=None) -> tuple[object, dict]:
    model = model or load_darknet_model(args.cfg, args.weights, args.device)
    paths = _image_paths(args.image_list, args.num_images)
    if not paths:
        raise ValueError("No calibration images")
    collector = ActivationCollector(args.max_samples, args.samples_per_tensor)
    started = time.time()
    for number, path in enumerate(paths, 1):
        image, _ = load_image(path, model.cfg)
        model.forward(image, callback=collector.update)
        if number == 1 or number % args.progress == 0 or number == len(paths):
            print(f"calibration {number}/{len(paths)} ({time.time() - started:.1f}s)", flush=True)
    report = collector.report(args.percentile, args.activation_bits)
    report.update(
        {
            "cfg": str(Path(args.cfg).resolve()),
            "weights": str(Path(args.weights).resolve()),
            "image_list": str(Path(args.image_list).resolve()),
            "image_count": len(paths),
        }
    )
    return model, report


def command_calibrate(args: argparse.Namespace) -> None:
    _, report = run_calibration(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"saved: {output}")
    for index, stats in report["layers"].items():
        print(
            f"layer {int(index):02d}: range=[{stats['min']:.5g},{stats['max']:.5g}] "
            f"threshold={stats['threshold']:.5g} scale={stats['scale']:.8g}"
        )


def command_export(args: argparse.Namespace) -> None:
    model = load_darknet_model(args.cfg, args.weights, args.device)
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    manifest = export_int8_package(model, calibration, args.output_dir)
    print(f"saved: {manifest}")


def _compare_layers(fp32_result, int8_result) -> list[dict]:
    rows = []
    assert fp32_result.layers is not None and int8_result.layers is not None
    for index in fp32_result.layers:
        reference = fp32_result.layers[index].numpy().astype(np.float64)
        quantized = int8_result.layers[index]
        restored = quantized.values.astype(np.float64) * quantized.scale
        difference = np.abs(reference - restored)
        a, b = reference.reshape(-1), restored.reshape(-1)
        cosine = float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1.0e-30))
        rows.append(
            {
                "layer": index,
                "type": "",
                "shape": list(reference.shape),
                "cosine": cosine,
                "mae": float(difference.mean()),
                "max_abs": float(difference.max()),
                "saturation": float(np.mean((quantized.values <= -128) | (quantized.values >= 127))),
            }
        )
    return rows


def command_int8(args: argparse.Namespace) -> None:
    float_model = load_darknet_model(args.cfg, args.weights, args.device)
    integer_model = Int8GoldenModel(float_model, args.package_dir)
    image, _ = load_image(args.image, float_model.cfg)
    integer_result = integer_model.forward(image, capture_layers=bool(args.dump_dir or args.compare))
    if args.dump_dir:
        dump_uint8_input(image, args.dump_dir)
        dump_int8_layers(integer_result, args.dump_dir)
    decoded = integer_model.decode(integer_result).numpy()
    if args.decoded_out:
        output = Path(args.decoded_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.save(output, decoded)
    print(f"INT8 heads: {[list(item.values.shape) for item in integer_result.heads]}")
    print(f"decoded: {decoded.shape}, detections: {len(postprocess(decoded, args.confidence, args.nms))}")
    if args.compare:
        fp32_result = float_model.forward(image, capture_layers=True)
        rows = _compare_layers(fp32_result, integer_result)
        print(f"{'layer':>5} {'cosine':>10} {'MAE':>12} {'max abs':>12} {'sat%':>9}")
        for row in rows:
            print(
                f"{row['layer']:>5} {row['cosine']:>10.6f} {row['mae']:>12.6g} "
                f"{row['max_abs']:>12.6g} {100*row['saturation']:>8.4f}%"
            )
        if args.compare_report:
            output = Path(args.compare_report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def command_pipeline(args: argparse.Namespace) -> None:
    model, report = run_calibration(args)
    artifacts = Path(args.output_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    calibration_path = artifacts / "calibration.json"
    calibration_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = export_int8_package(model, report, artifacts / "int8")
    print(f"calibration: {calibration_path}")
    print(f"INT8 package: {manifest}")


def command_evaluate(args: argparse.Namespace) -> None:
    float_model = load_darknet_model(args.cfg, args.weights, args.device)
    integer_model = Int8GoldenModel(float_model, args.package_dir) if args.backend == "int8" else None
    classes = int(next(block["classes"] for block in float_model.cfg.layers if block["type"] == "yolo"))
    names = Path(args.names).read_text(encoding="utf-8").splitlines() if args.names else None
    evaluator = MeanAveragePrecision(classes, args.iou)
    paths = _image_paths(args.image_list, args.max_images)
    started = time.time()
    for number, path in enumerate(paths, 1):
        image, _ = load_image(path, float_model.cfg)
        if integer_model:
            decoded = integer_model.decode(integer_model.forward(image)).numpy()
        else:
            decoded = float_model.decode(float_model.forward(image)).cpu().numpy()
        detections = postprocess(decoded, args.confidence, args.nms)
        evaluator.update(detections, load_yolo_labels(label_path_for_image(path)))
        if number == 1 or number % args.progress == 0 or number == len(paths):
            print(f"evaluate {number}/{len(paths)} ({time.time() - started:.1f}s)", flush=True)
    report = evaluator.compute(names)
    report.update(
        {
            "backend": args.backend,
            "images": len(paths),
            "confidence_threshold": args.confidence,
            "nms_threshold": args.nms,
        }
    )
    print(json.dumps(report, indent=2, allow_nan=True))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, allow_nan=True), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="validate CFG/weights and print shapes")
    _add_model_arguments(inspect_parser)
    inspect_parser.set_defaults(func=command_inspect)

    fp32 = subparsers.add_parser("fp32", help="run folded FP32 golden inference")
    _add_model_arguments(fp32)
    fp32.add_argument("--image", required=True)
    fp32.add_argument("--dump-dir")
    fp32.add_argument("--decoded-out")
    fp32.add_argument("--confidence", type=float, default=0.25)
    fp32.add_argument("--nms", type=float, default=0.45)
    fp32.add_argument("--show", type=int, default=20)
    fp32.set_defaults(func=command_fp32)

    def add_calibration_arguments(target):
        _add_model_arguments(target)
        target.add_argument("--image-list", default=str(DEFAULT_VAL))
        target.add_argument("--num-images", type=int, default=500)
        target.add_argument("--percentile", type=float, default=100.0)
        target.add_argument("--activation-bits", type=int, default=8)
        target.add_argument("--max-samples", type=int, default=200_000)
        target.add_argument("--samples-per-tensor", type=int, default=8192)
        target.add_argument("--progress", type=int, default=10)

    calibrate = subparsers.add_parser("calibrate", help="collect activation scales")
    add_calibration_arguments(calibrate)
    calibrate.add_argument("--output", default=str(DEFAULT_ARTIFACTS / "calibration.json"))
    calibrate.set_defaults(func=command_calibrate)

    export = subparsers.add_parser("export-int8", help="create weight/bias/requant/scale binaries")
    _add_model_arguments(export)
    export.add_argument("--calibration", default=str(DEFAULT_ARTIFACTS / "calibration.json"))
    export.add_argument("--output-dir", default=str(DEFAULT_ARTIFACTS / "int8"))
    export.set_defaults(func=command_export)

    int8 = subparsers.add_parser("int8", help="run the integer-domain golden model")
    _add_model_arguments(int8)
    int8.add_argument("--package-dir", default=str(DEFAULT_ARTIFACTS / "int8"))
    int8.add_argument("--image", required=True)
    int8.add_argument("--dump-dir")
    int8.add_argument("--decoded-out")
    int8.add_argument("--compare", action="store_true")
    int8.add_argument("--compare-report")
    int8.add_argument("--confidence", type=float, default=0.25)
    int8.add_argument("--nms", type=float, default=0.45)
    int8.set_defaults(func=command_int8)

    pipeline = subparsers.add_parser("pipeline", help="calibrate and export in one command")
    add_calibration_arguments(pipeline)
    pipeline.add_argument("--output-dir", default=str(DEFAULT_ARTIFACTS))
    pipeline.set_defaults(func=command_pipeline)

    evaluate = subparsers.add_parser("evaluate", help="evaluate FP32 or INT8 mAP on YOLO labels")
    _add_model_arguments(evaluate)
    evaluate.add_argument("--backend", choices=("fp32", "int8"), default="fp32")
    evaluate.add_argument("--package-dir", default=str(DEFAULT_ARTIFACTS / "int8"))
    evaluate.add_argument("--image-list", default=str(DEFAULT_VAL))
    evaluate.add_argument("--names", default=str(DEFAULT_NAMES))
    evaluate.add_argument("--max-images", type=int, default=0)
    evaluate.add_argument("--confidence", type=float, default=0.005)
    evaluate.add_argument("--nms", type=float, default=0.45)
    evaluate.add_argument("--iou", type=float, default=0.5)
    evaluate.add_argument("--progress", type=int, default=10)
    evaluate.add_argument("--output")
    evaluate.set_defaults(func=command_evaluate)

    rtl_package = subparsers.add_parser(
        "rtl-package",
        help="Create an RTL testbench package from generated int8 artifacts",
    )
    rtl_package.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS))
    rtl_package.add_argument("--output", required=True)
    rtl_package.add_argument(
        "--include-npy",
        action="store_true",
        help="Include reference .npy layer dumps in the package",
    )
    rtl_package.set_defaults(func=lambda args: print(package_rtl_testbench(Path(args.artifacts_dir), Path(args.output), args.include_npy)))

    rtl_compare = subparsers.add_parser(
        "rtl-compare",
        help="Compare RTL layer outputs against generated int8 sample layer references",
    )
    rtl_compare.add_argument(
        "--gold",
        default=str(DEFAULT_ARTIFACTS / "int8_layers"),
        help="Golden int8 layer sample directory",
    )
    rtl_compare.add_argument("--rtl", required=True, help="RTL dump directory")
    rtl_compare.add_argument("--out", required=True, help="Path to write compare report")
    rtl_compare.add_argument(
        "--compare-input",
        action="store_true",
        help="Also compare the quantized input blob if available",
    )
    rtl_compare.set_defaults(func=lambda args: print(compare_rtl_outputs(Path(args.gold), Path(args.rtl), Path(args.out), args.compare_input)))

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if hasattr(args, "device") and str(args.device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA was requested but is not available: {args.device}")
    args.func(args)


if __name__ == "__main__":
    main()
