import csv
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


GENERATOR = os.environ.get("PR3_INPUT_GENERATOR")
EVALUATOR = os.environ.get("PR3_EVALUATOR")


@unittest.skipUnless(GENERATOR and EVALUATOR, "set PR3_INPUT_GENERATOR and PR3_EVALUATOR to compiled tools")
class Pr3EvaluatorTests(unittest.TestCase):
    def test_fixed_denominator_paired_rows_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "static.bin"
            generated = subprocess.run(
                [GENERATOR, str(samples), "development", "static", "0", "nominal", "4001"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            input_sha = hashlib.sha256(samples.read_bytes()).hexdigest()
            output = root / "summary.csv"
            evaluated = subprocess.run(
                [EVALUATOR, str(samples), str(output), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                 "a" * 40, "b" * 64, input_sha],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(evaluated.returncode, 0, evaluated.stdout + evaluated.stderr)
            with output.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["estimator"] for row in rows], ["eskf_conservative", "eskf_legacy", "eskf_confirmed_only"])
            for row in rows:
                self.assertEqual(row["input_sha256"], input_sha)
                self.assertEqual(row["expected"], "2801")
                self.assertEqual(row["produced"], row["expected"])
                self.assertEqual(row["missing"], "0")
                self.assertEqual(row["control_valid"], row["expected"])
                self.assertEqual(row["tilt_nees_count"], row["valid"])
                self.assertEqual(row["pr2_gate_status"], "OPEN")

    def test_unverified_startup_calibration_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "static.bin"
            subprocess.run([GENERATOR, str(samples), "development", "static", "0", "nominal", "4001"], check=True)
            output = root / "must-not-exist.csv"
            result = subprocess.run(
                [EVALUATOR, str(samples), str(output), "development", "IMU_ONLY", "UNKNOWN", "1", "NONE",
                 "a" * 40, "b" * 64, "c" * 64],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
