import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scenarios" / "pr3_scenarios_protocol_v1.json"
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


if __name__ == "__main__":
    unittest.main()
