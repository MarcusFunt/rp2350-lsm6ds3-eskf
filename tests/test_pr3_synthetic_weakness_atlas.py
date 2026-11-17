"""Contract checks for selected PR3 v5 mechanism traces."""

from __future__ import annotations

import unittest

from tools.pr3_synthetic_weakness_atlas import (
    REQUIRED_GRAVITY_FIELDS,
    REQUIRED_STATE_FIELDS,
    SCENARIOS,
    validate_archive_rows,
    validate_paired_archive_rows,
    validate_trace_alignment,
)


def archive_row(scenario: str, stress: str, estimator: str, digest: str) -> dict[str, str]:
    return {
        "seed_split": "development",
        "scenario": scenario,
        "rate_mode": "uniform_208hz",
        "stress_mode": stress,
        "seed": "4001",
        "estimator": estimator,
        "sensor_input": "IMU_ONLY",
        "startup_knowledge": "UNKNOWN",
        "startup_gyro_bias_calibration": "OFF",
        "runtime_aid": "NONE",
        "input_sha256": digest,
        "expected": "2913",
        "produced": "2913",
        "valid": "2913",
        "availability": "1",
        "tilt_rms_deg": "3.0",
        "tilt_p95_deg": "4.0",
        "tilt_max_deg": "5.0",
        "attitude_rms_deg": "3.0",
        "yaw_rms_deg": "1.0",
        "position_rms_m": "0.1",
        "velocity_rms_m_s": "0.1",
        "accel_bias_error_m_s2": "0.01",
        "gyro_bias_error_rad_s": "0.001",
        "tilt_nees_mean": "0.04" if estimator.startswith("eskf") else "",
        "nis_mean": "0.9" if estimator.startswith("eskf") else "",
        "health_end": "Nominal",
    }


class PR3SyntheticWeaknessContractTests(unittest.TestCase):
    def test_selection_covers_the_three_requested_scenarios(self) -> None:
        self.assertEqual(SCENARIOS, ("maneuver", "timing_jitter", "compound_motion"))

    def test_archive_selection_requires_exact_estimator_rows_and_one_shared_input(self) -> None:
        digest = "a" * 64
        rows = [archive_row("maneuver", "nominal", name, digest) for name in (
            "eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"
        )]
        selected = validate_archive_rows(rows, "maneuver", "nominal", 4001)
        self.assertEqual(set(selected), {row["estimator"] for row in rows})
        with self.assertRaisesRegex(ValueError, "share input hash"):
            validate_archive_rows(rows[:-1] + [{**rows[-1], "input_sha256": "b" * 64}], "maneuver", "nominal", 4001)

    def test_nominal_stress_archive_pair_requires_same_trial_cell_and_distinct_inputs(self) -> None:
        nominal = [archive_row("timing_jitter", "nominal", name, "a" * 64) for name in (
            "eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"
        )]
        stress = [archive_row("timing_jitter", "stress", name, "b" * 64) for name in (
            "eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"
        )]
        validate_paired_archive_rows(nominal, stress)
        with self.assertRaisesRegex(ValueError, "distinct input hashes"):
            validate_paired_archive_rows(nominal, [dict(row, input_sha256="a" * 64) for row in stress])

    def test_trace_alignment_preserves_state_covariance_and_gravity_diagnostics(self) -> None:
        sample = {
            "sample_index": "1", "reported_timestamp_us": "1004807", "physical_timestamp_us": "1004807",
            **{name: "0" for name in REQUIRED_STATE_FIELDS},
        }
        gravity = {
            "sample_index": "1", "reported_timestamp_us": "1004807",
            **{name: "0" for name in REQUIRED_GRAVITY_FIELDS},
        }
        validate_trace_alignment([sample], [gravity], expected_samples=1)
        with self.assertRaisesRegex(ValueError, "timestamp alignment"):
            validate_trace_alignment([sample], [{**gravity, "reported_timestamp_us": "1004808"}], expected_samples=1)
        missing = dict(gravity)
        del missing["gravity_reason"]
        with self.assertRaisesRegex(ValueError, "diagnostic fields"):
            validate_trace_alignment([sample], [missing], expected_samples=1)

    def test_trace_alignment_rejects_missing_or_duplicate_sample_indices(self) -> None:
        sample = {"sample_index": "1", "reported_timestamp_us": "1004807", **{name: "0" for name in REQUIRED_STATE_FIELDS}}
        gravity = {"sample_index": "1", "reported_timestamp_us": "1004807", **{name: "0" for name in REQUIRED_GRAVITY_FIELDS}}
        with self.assertRaisesRegex(ValueError, "sample count"):
            validate_trace_alignment([sample], [gravity], expected_samples=2)
        with self.assertRaisesRegex(ValueError, "sample indices"):
            validate_trace_alignment([sample, sample], [gravity, gravity], expected_samples=2)


if __name__ == "__main__":
    unittest.main()
