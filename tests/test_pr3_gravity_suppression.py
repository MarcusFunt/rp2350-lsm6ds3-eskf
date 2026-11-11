import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.pr3_gravity_suppression import pair_trial_rows, validate_forensic_scope


class Pr3GravitySuppressionTests(unittest.TestCase):
    def test_pairs_only_same_seed_and_estimator_nominal_stress_rows(self):
        rows = [
            {"seed": "4001", "stress_mode": "nominal", "estimator": "eskf_conservative", "tilt_rms_deg": "0.15"},
            {"seed": "4001", "stress_mode": "stress", "estimator": "eskf_conservative", "tilt_rms_deg": "5.40"},
            {"seed": "4001", "stress_mode": "nominal", "estimator": "eskf_legacy", "tilt_rms_deg": "0.16"},
            {"seed": "4001", "stress_mode": "stress", "estimator": "eskf_legacy", "tilt_rms_deg": "5.41"},
            {"seed": "4002", "stress_mode": "nominal", "estimator": "eskf_conservative", "tilt_rms_deg": "0.14"},
            {"seed": "4002", "stress_mode": "stress", "estimator": "eskf_conservative", "tilt_rms_deg": "5.38"},
        ]

        paired = pair_trial_rows(rows)

        self.assertEqual(len(paired), 3)
        first = next(row for row in paired if row["seed"] == "4001" and row["estimator"] == "eskf_conservative")
        self.assertAlmostEqual(first["stress_minus_nominal_tilt_rms_deg"], 5.25)
        self.assertEqual(first["pairing_key"], "development|static|uniform_208hz|4001|eskf_conservative")

    def test_pairing_rejects_missing_condition_or_duplicate_rows(self):
        with self.assertRaisesRegex(ValueError, "exactly one nominal and one stress"):
            pair_trial_rows([
                {"seed": "4001", "stress_mode": "nominal", "estimator": "eskf_conservative", "tilt_rms_deg": "0.15"},
            ])

        with self.assertRaisesRegex(ValueError, "duplicate trial key"):
            pair_trial_rows([
                {"seed": "4001", "stress_mode": "nominal", "estimator": "eskf_conservative", "tilt_rms_deg": "0.15"},
                {"seed": "4001", "stress_mode": "nominal", "estimator": "eskf_conservative", "tilt_rms_deg": "0.16"},
                {"seed": "4001", "stress_mode": "stress", "estimator": "eskf_conservative", "tilt_rms_deg": "5.40"},
            ])

    def test_forensic_capture_is_limited_to_one_development_stream_and_event(self):
        validate_forensic_scope(
            split="development", seed_count=1, scenario_count=1,
            rate_mode_count=1, stress_mode_count=1, profile_count=1,
            event_sample=135,
        )
        for options in (
            {"seed_count": 100},
            {"scenario_count": 8},
            {"rate_mode_count": 3},
            {"stress_mode_count": 2},
            {"profile_count": 7},
            {"event_sample": None},
        ):
            request = {
                "split": "development", "seed_count": 1, "scenario_count": 1,
                "rate_mode_count": 1, "stress_mode_count": 1, "profile_count": 1,
                "event_sample": 135,
            }
            request.update(options)
            with self.assertRaisesRegex(ValueError, "forensic capture requires one selected development stream and event"):
                validate_forensic_scope(**request)

        with self.assertRaisesRegex(ValueError, "forensic capture requires one selected development stream and event"):
            validate_forensic_scope(
                split="held_out", seed_count=1, scenario_count=1,
                rate_mode_count=1, stress_mode_count=1, profile_count=1,
                event_sample=135,
            )


if __name__ == "__main__":
    unittest.main()
