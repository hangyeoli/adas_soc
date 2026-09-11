"""Host tests for input rejection and truthful comparison (no FPGA emulation)."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

if importlib.util.find_spec('fcntl') is None:
    sys.modules['fcntl'] = types.ModuleType('fcntl')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hardware


class ContractTests(unittest.TestCase):
    def test_real_export_matches_all_four_register_contracts(self):
        desc, regs = hardware.audit()
        self.assertEqual(len(desc['ops']), 22)
        self.assertEqual(set(regs), set(desc['engines']))

    def test_actual_bit_payload_converts_and_rejects_truncation(self):
        data = hardware.BIT.read_bytes()
        output = hardware.convert_bit(data)
        self.assertIn(b'\x66\x55\x99\xaa', output[:1024])
        with self.assertRaises(ValueError):
            hardware.convert_bit(data[:-4])

    def test_comparison_does_not_confuse_signed_bytes(self):
        result = hardware.compare(bytes([0, 128, 255, 127]), bytes([0, 127, 255, 128]))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], 2)
        self.assertEqual(result['first_mismatches'][0], {'offset': 1, 'actual': -128, 'expected': 127})

    def test_equal_checksum_is_not_enough_to_pass(self):
        result = hardware.compare(bytes([1, 2]), bytes([2, 1]))
        self.assertEqual(result['mismatches'], 2)

    def test_size_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            hardware.compare(b'abc', b'ab')

    def test_identical_reference_passes(self):
        data = (hardware.ROOT / '05_golden_heads/head1_layer15_9x16x30_nhwc_int8.bin').read_bytes()
        self.assertEqual(hardware.compare(data, data)['mismatches'], 0)

    def test_layout_conversion_preserves_pixel_channel_positions(self):
        # 2 channels, 1 row, 3 columns: RRR GGG -> RG RG RG.
        self.assertEqual(hardware.nchw_to_nhwc(bytes([1, 2, 3, 11, 12, 13]), 1, 3, 2), bytes([1, 11, 2, 12, 3, 13]))
        with self.assertRaises(ValueError):
            hardware.nchw_to_nhwc(b'12345', 1, 3, 2)

    def test_reference_layout_is_explicit_and_independent_of_actual_output(self):
        for index in (15, 22):
            data, info = hardware.reference_output(index)
            self.assertEqual(info['source_layout'], 'NCHW')
            self.assertEqual(info['comparison_layout'], 'NHWC')
            self.assertEqual(len(data), 4320 if index == 15 else 17280)


if __name__ == '__main__':
    unittest.main()
