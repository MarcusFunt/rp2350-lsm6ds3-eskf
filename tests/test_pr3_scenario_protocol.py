import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v2.json"
PROTOCOL_V3 = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v3.json"
PROTOCOL_V4 = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v4.json"
PROTOCOL_V5 = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v5.json"
VALIDATOR = ROOT / "tools" / "validate_pr3_scenario_protocol.py"


class Pr3ScenarioProtocolTests(unittest.TestCase):
    def validate_document(self, document):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(document), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_committed_protocol_passes_schema_validation(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PROTOCOL)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_protocol_defines_all_eight_required_scenarios(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        scenario_ids = [scenario["id"] for scenario in document["scenarios"]]
        self.assertEqual(
            scenario_ids,
            [
                "static",
                "slow_yaw",
                "lateral_accel",
                "maneuver",
                "vibration",
                "timing_jitter",
                "stop_start",
                "compound_motion",
            ],
        )

    def test_protocol_freezes_required_sample_rate_and_factor_axes(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        self.assertEqual(
            [mode["id"] for mode in document["sampling"]["rate_modes"]],
            ["uniform_200hz", "uniform_208hz", "irregular_208hz"],
        )
        self.assertEqual(
            [mode["nominal_rate_hz"] for mode in document["sampling"]["rate_modes"]],
            [200, 208, 208],
        )
        self.assertIn("two-sided PSD", document["noise_model"]["white_noise_spectrum"])
        self.assertIn("startup_knowledge", document["factors"])
        self.assertIn("runtime_aid", document["factors"])
        self.assertEqual(document["protocol_version"], 2)
        self.assertIn("paired percentile bootstrap", document["paired_comparison"]["paired_interval_method"].lower())

    def test_protocol_v1_remains_valid_as_superseded_evidence(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v1.json")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_protocol_v2_remains_valid_as_superseded_evidence(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PROTOCOL)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_protocol_v3_starts_vibration_disturbance_after_stationary_startup(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PROTOCOL_V3)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(PROTOCOL_V3.read_text(encoding="utf-8"))
        vibration = next(s for s in document["scenarios"] if s["id"] == "vibration")
        self.assertEqual(document["protocol_version"], 3)
        self.assertEqual(document["supersedes_protocol_version"], 2)
        self.assertEqual(vibration["measurement_disturbances"]["start_s"], 2.0)

    def test_validator_rejects_disturbance_start_after_duration(self):
        document = json.loads(PROTOCOL_V3.read_text(encoding="utf-8"))
        vibration = next(s for s in document["scenarios"] if s["id"] == "vibration")
        vibration["measurement_disturbances"]["start_s"] = 17.0
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("start_s", result.stderr)

    def test_protocol_v3_requires_vibration_disturbance_start(self):
        document = json.loads(PROTOCOL_V3.read_text(encoding="utf-8"))
        vibration = next(s for s in document["scenarios"] if s["id"] == "vibration")
        del vibration["measurement_disturbances"]["start_s"]
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("start_s", result.stderr)

    def test_validator_rejects_missing_required_scenario(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        document["scenarios"] = [s for s in document["scenarios"] if s["id"] != "compound_motion"]
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scenario", result.stderr.lower())

    def test_validator_rejects_overlapping_seed_splits(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        document["seeds"]["held_out"]["first_seed"] = document["seeds"]["development"]["first_seed"]
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overlap", result.stderr.lower())

    def test_validator_rejects_timestamp_jitter_that_breaks_minimum_dt(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        document["sampling"]["rate_modes"][2]["jitter"]["amplitude_us"] = 500000
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("monotonic", result.stderr.lower())

    def test_validator_rejects_stress_that_reduces_noise(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        document["stress_transforms"]["stress"]["accelerometer_white_noise_multiplier"] = 0.5
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stress", result.stderr.lower())

    def test_validator_reports_malformed_optional_jitter_without_traceback(self):
        document = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        document["scenarios"][3]["timestamp_jitter"] = {"amplitude_us": 50}
        result = self.validate_document(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL protocol validation", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_protocol_v4_allocates_new_disjoint_acceptance_seeds(self):
        document = json.loads(PROTOCOL_V4.read_text(encoding="utf-8"))
        old = json.loads(PROTOCOL_V3.read_text(encoding="utf-8"))
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PROTOCOL_V4)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document["seeds"]["development"], old["seeds"]["development"])
        self.assertEqual(document["seeds"]["held_out"]["first_seed"], 7001)
        self.assertEqual(document["seeds"]["final_confirmation"]["first_seed"], 8001)
        self.assertEqual(document["scenarios"], old["scenarios"])
        self.assertEqual(document["noise_model"], old["noise_model"])

    def test_protocol_v5_allocates_new_disjoint_acceptance_seeds(self):
        document = json.loads(PROTOCOL_V5.read_text(encoding="utf-8"))
        old = json.loads(PROTOCOL_V4.read_text(encoding="utf-8"))
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PROTOCOL_V5)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document["protocol_version"], 5)
        self.assertEqual(document["supersedes_protocol_version"], 4)
        self.assertEqual(document["seeds"]["development"], old["seeds"]["development"])
        self.assertEqual(document["seeds"]["held_out"]["first_seed"], 9001)
        self.assertEqual(document["seeds"]["held_out"]["last_seed"], 9100)
        self.assertEqual(document["seeds"]["final_confirmation"]["first_seed"], 10001)
        self.assertEqual(document["seeds"]["final_confirmation"]["last_seed"], 10100)
        self.assertEqual(document["scenarios"], old["scenarios"])
        self.assertEqual(document["noise_model"], old["noise_model"])
        self.assertIn("gravity_rule", document["reference_estimator_definitions"]["mahony"])
        self.assertIn("propagation", document["reference_estimator_definitions"]["gyro_only"])


if __name__ == "__main__":
    unittest.main()
