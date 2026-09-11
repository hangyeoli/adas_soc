from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from darknet_golden.config import DarknetConfig
from darknet_golden.metrics import MeanAveragePrecision, postprocess
from darknet_golden.model import load_darknet_convolutions
from darknet_golden.quantization import (
    _integer_conv2d_exact,
    _maxpool_int,
    apply_multiplier,
    quantize_multiplier,
    round_divide_by_pot_signed,
)


ROOT = Path(__file__).resolve().parents[3]
CFG = ROOT / "darknet/cfg/yolov3-tiny-adas-5class-balanced-512x288.cfg"
WEIGHTS = (
    ROOT
    / "adas_dataset_yolov3_tiny_5class_balanced_512x288/backup/"
    "yolov3-tiny-adas-5class-balanced-512x288_best.weights"
)


class FixedPointTests(unittest.TestCase):
    def test_signed_rounding(self):
        values = np.asarray([-7, -5, -3, -1, 1, 3, 5, 7], dtype=np.int64)
        expected = np.asarray([-4, -3, -2, -1, 1, 2, 3, 4], dtype=np.int64)
        np.testing.assert_array_equal(round_divide_by_pot_signed(values, 1), expected)

    def test_quantized_multiplier(self):
        values = np.arange(-10000, 10001, 37, dtype=np.int64)
        for real_multiplier in (0.00031, 0.01, 0.3, 0.99, 1.5, 3.25):
            multiplier, right_shift = quantize_multiplier(real_multiplier)
            actual = apply_multiplier(values, multiplier, right_shift)
            expected = np.sign(values) * np.floor(np.abs(values * real_multiplier) + 0.5)
            self.assertLessEqual(int(np.max(np.abs(actual - expected))), 1)

    def test_integer_convolution(self):
        x = np.arange(1, 17, dtype=np.int64).reshape(1, 1, 4, 4)
        weight = np.ones((1, 1, 3, 3), dtype=np.int8)
        bias = np.asarray([3], dtype=np.int32)
        output = _integer_conv2d_exact(x, weight, bias, stride=1, padding=0)
        expected = np.asarray([[[[57, 66], [93, 102]]]], dtype=np.int64)
        np.testing.assert_array_equal(output, expected)

    def test_darknet_stride_one_maxpool_padding(self):
        x = np.asarray([[[[1, 2], [3, 4]]]], dtype=np.int64)
        output = _maxpool_int(x, size=2, stride=1, total_padding=1)
        np.testing.assert_array_equal(output, np.asarray([[[[4, 4], [4, 4]]]], dtype=np.int64))


class ModelIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(CFG.exists() and WEIGHTS.exists(), "ADAS model files are not present")
    def test_real_darknet_weights_are_consumed_exactly(self):
        cfg = DarknetConfig.load(CFG)
        header, layers = load_darknet_convolutions(cfg, WEIGHTS)
        self.assertEqual((header.major, header.minor, header.revision), (0, 2, 5))
        self.assertEqual(len(layers), 13)
        self.assertEqual(layers[0].weight.shape, (16, 3, 3, 3))
        self.assertEqual(layers[15].weight.shape, (30, 512, 1, 1))
        self.assertEqual(layers[22].weight.shape, (30, 256, 1, 1))


class MetricsTests(unittest.TestCase):
    def test_perfect_prediction_has_one_map(self):
        decoded = np.zeros((1, 10), dtype=np.float32)
        decoded[0, :4] = [0.5, 0.5, 0.2, 0.4]
        decoded[0, 4:] = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
        detections = postprocess(decoded, confidence=0.5)
        evaluator = MeanAveragePrecision(classes=5)
        evaluator.update(detections, {0: np.asarray([[0.4, 0.3, 0.6, 0.7]], dtype=np.float32)})
        self.assertAlmostEqual(evaluator.compute()["mAP"], 1.0)


if __name__ == "__main__":
    unittest.main()
