import hashlib
import os
import math
import statistics
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


GENERATOR = os.environ.get("PR3_INPUT_GENERATOR")


@unittest.skipUnless(GENERATOR, "set PR3_INPUT_GENERATOR to the compiled PR3 input generator")
class Pr3InputGeneratorTests(unittest.TestCase):
    def run_generator(self, path, split, scenario, rate, stress, seed):
        return subprocess.run(
            [GENERATOR, str(path), split, scenario, str(rate), stress, str(seed)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_generation_is_deterministic_and_has_fixed_record_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.bin"
            second = Path(directory) / "second.bin"
            for output in (first, second):
                result = self.run_generator(output, "development", "static", 0, "nominal", 4001)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            first_bytes = first.read_bytes()
            self.assertEqual(first_bytes, second.read_bytes())
            self.assertEqual(len(first_bytes), 128 + 3200 * 128)
            self.assertEqual(first_bytes[:8], b"PR3INP03")
            self.assertEqual(struct.unpack_from("<9I", first_bytes, 8)[:8], (3, 0, 0, 0, 4001, 3200, 128, 3200))
            self.assertEqual(first_bytes[44:108].decode("ascii"), hashlib.sha256(
                (Path(__file__).resolve().parents[1] / "benchmarks/scenarios/pr3_scenarios_protocol_v3.json").read_bytes()
            ).hexdigest())

    def test_generation_rejects_seed_from_wrong_frozen_split(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wrong-split.bin"
            result = self.run_generator(output, "development", "static", 0, "nominal", 5001)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_irregular_stressed_scenario_timestamps_are_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jitter.bin"
            result = self.run_generator(output, "development", "timing_jitter", 2, "stress", 4002)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = output.read_bytes()
            timestamps = [struct.unpack_from("<Q", data, 128 + i * 128 + 12)[0] for i in range(3200)]
            intervals = [right - left for left, right in zip(timestamps, timestamps[1:])]
            self.assertGreaterEqual(min(intervals), 4700)
            self.assertLessEqual(max(intervals), 5000)

    def test_white_noise_sample_std_matches_two_sided_psd_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "noise.bin"
            result = self.run_generator(output, "development", "static", 0, "nominal", 4001)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = output.read_bytes()
            accel_residuals = [[], [], []]
            gyro_residuals = [[], [], []]
            for i in range(3200):
                offset = 128 + i * 128
                biases = struct.unpack_from("<6f", data, offset + 68)
                accel = struct.unpack_from("<3f", data, offset + 92)
                gyro = struct.unpack_from("<3f", data, offset + 104)
                for axis in range(3):
                    expected_accel = biases[axis] + (9.80665 if axis == 2 else 0.0)
                    accel_residuals[axis].append(accel[axis] - expected_accel)
                    gyro_residuals[axis].append(gyro[axis] - biases[axis])
            expected_accel_std = 0.0015 * math.sqrt(200)
            expected_gyro_std = 0.00025 * math.sqrt(200)
            for axis in range(3):
                self.assertAlmostEqual(statistics.pstdev(accel_residuals[axis]) / expected_accel_std, 1.0, delta=0.06)
                self.assertAlmostEqual(statistics.pstdev(gyro_residuals[axis]) / expected_gyro_std, 1.0, delta=0.06)


if __name__ == "__main__":
    unittest.main()
