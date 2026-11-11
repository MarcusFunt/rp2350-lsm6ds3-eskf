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
            self.assertEqual([row["estimator"] for row in rows], ["eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"])
            for row in rows:
                self.assertEqual(row["input_sha256"], input_sha)
                self.assertEqual(row["expected"], "2801")
                self.assertEqual(row["produced"], row["expected"])
                self.assertEqual(row["missing"], "0")
                self.assertEqual(row["control_valid"], row["expected"])
                self.assertEqual(row["pr2_gate_status"], "OPEN")
                if row["estimator"].startswith("eskf_"):
                    self.assertEqual(row["covariance_applicable"], "true")
                    self.assertEqual(row["navigation_applicable"], "true")
                    self.assertEqual(row["tilt_nees_count"], row["valid"])
                else:
                    self.assertEqual(row["covariance_applicable"], "false")
                    self.assertEqual(row["navigation_applicable"], "false")
                    self.assertEqual(row["tilt_nees_count"], "0")
                    self.assertEqual(row["tilt_nees_mean"], "")

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

    def test_confirmed_only_slow_yaw_keeps_covariance_positive_definite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "slow_yaw.bin"
            generated = subprocess.run(
                [GENERATOR, str(samples), "development", "slow_yaw", "0", "nominal", "4001"],
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
            confirmed = next(row for row in rows if row["estimator"] == "eskf_confirmed_only")
            self.assertEqual(
                confirmed["covariance_valid"],
                confirmed["expected"],
                "development seed 4001 slow_yaw loses covariance positive-definiteness in ConfirmedOnly",
            )

    def test_covariance_stays_positive_in_static_maneuver_and_jitter_edges(self):
        cases = (("static", "4013"), ("maneuver", "4002"), ("timing_jitter", "4001"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for scenario, seed in cases:
                with self.subTest(scenario=scenario, seed=seed):
                    samples = root / f"{scenario}_{seed}.bin"
                    generated = subprocess.run(
                        [GENERATOR, str(samples), "development", scenario, "1", "nominal", seed],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
                    input_sha = hashlib.sha256(samples.read_bytes()).hexdigest()
                    output = root / f"{scenario}_{seed}.csv"
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
                    self.assertEqual(len(rows), 5)
                    for row in rows[:3]:
                        self.assertEqual(
                            row["covariance_valid"],
                            row["expected"],
                            f"{scenario} seed {seed} regressed covariance positive-definiteness in {row['estimator']}",
                        )

    def test_sample_trace_records_covariance_without_false_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "slow_yaw.bin"
            generated = subprocess.run(
                [GENERATOR, str(samples), "development", "slow_yaw", "0", "nominal", "4001"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            input_sha = hashlib.sha256(samples.read_bytes()).hexdigest()
            output = root / "summary.csv"
            trace = root / "sample_trace.csv"
            evaluated = subprocess.run(
                [EVALUATOR, str(samples), str(output), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                 "a" * 40, "b" * 64, input_sha, "--sample-trace", str(trace)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(evaluated.returncode, 0, evaluated.stdout + evaluated.stderr)
            with trace.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3 * 3200)
            confirmed = [row for row in rows if row["estimator"] == "eskf_confirmed_only"]
            self.assertTrue(all(row["covariance_after_process"] == "true" for row in confirmed))
            self.assertTrue(all(row["covariance_after_heading"] == "true" for row in confirmed))
            self.assertTrue(all(row["gravity_updates_delta"] == "0" for row in confirmed))
            evaluation_rows = [row for row in confirmed if row["evaluation_sample"] == "true"]
            self.assertTrue(all(row["control_valid"] == "true" for row in evaluation_rows))
            snapshot = Path(str(trace) + ".first_failure_covariance.csv")
            with snapshot.open(newline="", encoding="utf-8") as stream:
                snapshots = list(csv.DictReader(stream))
            self.assertEqual(snapshots, [])


if __name__ == "__main__":
    unittest.main()
