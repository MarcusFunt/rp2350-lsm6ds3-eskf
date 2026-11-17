"""Smoke checks for the native B9 ESKF replay interface."""

from __future__ import annotations

import csv
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "b9_eskf_replay.cpp"


class EskfReplaySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="b9-eskf-replay-")
        cls.executable = Path(cls.temp_dir.name) / "b9_eskf_replay"
        subprocess.run(
            [
                os.environ.get("CXX", "g++"),
                "-std=c++17",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                "-Werror",
                str(SOURCE),
                "-o",
                str(cls.executable),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def _write_samples(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(
                ["sample_index", "timestamp_us", "valid", "ax", "ay", "az", "gx", "gy", "gz"]
            )
            for index in range(1, 121):
                writer.writerow([index, 1_000_000 + 3_500 * (index - 1), 1, 0, 0, 9.80665, 0, 0, 0])
            writer.writerow([121, 1_000_000 + 3_500 * 120, 1, 0, 0, 9.80665, 0, 0, math.radians(500)])

    def _run(self, profile: str, input_path: Path, output_path: Path) -> list[dict[str, str]]:
        subprocess.run(
            [str(self.executable), str(input_path), str(output_path), profile],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        with output_path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def test_default_range_latches_while_broad_range_accepts_and_reports_diagnostics(self) -> None:
        base = Path(self.temp_dir.name)
        input_path = base / "samples.csv"
        self._write_samples(input_path)
        default_rows = self._run("lsm6ds3", input_path, base / "default.csv")
        broad_rows = self._run("broad", input_path, base / "broad.csv")

        self.assertEqual(len(default_rows), 121)
        self.assertEqual(len(broad_rows), 121)
        default_fault = default_rows[-1]
        broad_high_rate = broad_rows[-1]
        self.assertEqual(default_fault["health"], "Fault")
        self.assertEqual(default_fault["reset_required"], "true")
        self.assertEqual(default_fault["output_valid"], "false")
        self.assertEqual(broad_high_rate["health"], "Nominal")
        self.assertEqual(broad_high_rate["reset_required"], "false")
        self.assertEqual(broad_high_rate["output_valid"], "true")
        self.assertAlmostEqual(float(default_fault["max_gyro_axis_rps"]), 0.98 * math.radians(245), places=5)
        self.assertAlmostEqual(float(broad_high_rate["max_gyro_axis_rps"]), 0.98 * math.radians(2000), places=4)
        for field in ("gravity_reason", "gravity_attempted", "gravity_accepted", "gravity_nis", "cov_theta_xx", "gyro_bias_z"):
            self.assertIn(field, broad_high_rate)


if __name__ == "__main__":
    unittest.main()
