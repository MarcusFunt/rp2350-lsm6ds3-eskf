import unittest

from tools import pr3_failure_atlas as atlas


def trace_row(index, *, nominal=None, physical=None, digest="a" * 64, covariance_min="0.00005"):
    return {
        "sample_index": str(index),
        "nominal_time_s": str(nominal if nominal is not None else index / 200.0),
        "physical_time_s": str(physical if physical is not None else index / 200.0),
        "input_sha256": digest,
        "tilt_error_deg": "0.1",
        "tilt_cov_trace": "0.0002",
        "tilt_cov_eigen_min": covariance_min,
        "tilt_cov_eigen_max": "0.00015",
        "tilt_nees_observable_2d": "0.3",
        "covariance_positive_definite": "true",
        "health": "Nominal",
        "gravity_attempted": "false",
        "gravity_accepted": "false",
        "gravity_reason": "candidate_dwell_incomplete",
    }


class FailureAtlasTraceQualityTests(unittest.TestCase):
    def test_valid_monotonic_trace_passes_quality_gate(self):
        atlas.validate_trace_quality([trace_row(1, covariance_min="0.00005"), trace_row(2, covariance_min="0.00005")], 2, "a" * 64)

    def test_missing_sample_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "row count"):
            atlas.validate_trace_quality([trace_row(1)], 2, "a" * 64)

    def test_reordered_or_duplicate_index_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "indices"):
            atlas.validate_trace_quality([trace_row(1), trace_row(1)], 2, "a" * 64)

    def test_nonmonotonic_physical_clock_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "physical sample time"):
            atlas.validate_trace_quality([trace_row(1, physical=1.0), trace_row(2, physical=0.9)], 2, "a" * 64)

    def test_wrong_raw_input_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "raw-input hash"):
            atlas.validate_trace_quality([trace_row(1, digest="b" * 64)], 1, "a" * 64)

    def test_nonfinite_or_missing_covariance_is_rejected(self):
        row = trace_row(1)
        row["tilt_cov_trace"] = ""
        with self.assertRaisesRegex(ValueError, "absent or nonfinite"):
            atlas.validate_trace_quality([row], 1, "a" * 64)

    def test_negative_projected_covariance_eigenvalue_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "projected covariance"):
            atlas.validate_trace_quality([trace_row(1, covariance_min="-0.1")], 1, "a" * 64)

    def test_unrecognized_covariance_status_is_rejected(self):
        row = trace_row(1)
        row["covariance_positive_definite"] = "unknown"
        with self.assertRaisesRegex(ValueError, "validity flag"):
            atlas.validate_trace_quality([row], 1, "a" * 64)

    def test_motion_regime_thresholds_are_classification_only(self):
        self.assertEqual(atlas.classify_motion_regime(1.99, 1.0, 1.0), "startup_static")
        self.assertEqual(atlas.classify_motion_regime(2.0, 0.0, 0.0), "quiescent_or_coast")
        self.assertEqual(atlas.classify_motion_regime(3.0, 0.02, 0.0), "rotation_dominant")
        self.assertEqual(atlas.classify_motion_regime(3.0, 0.0, 0.1), "translation_dominant")
        self.assertEqual(atlas.classify_motion_regime(3.0, 0.02, 0.1), "compound")

    def test_nominal_stress_pair_requires_distinct_inputs_and_same_cell(self):
        nominal = {"scenario": "static", "rate_mode": "uniform_200hz", "seed": 4001,
            "raw_input_sha256": "a" * 64, "sample_count": 3200}
        stress = {**nominal, "raw_input_sha256": "b" * 64}
        atlas.validate_paired_trace_records(nominal, stress)
        with self.assertRaisesRegex(ValueError, "distinct hashes"):
            atlas.validate_paired_trace_records(nominal, {**stress, "raw_input_sha256": "a" * 64})
        with self.assertRaisesRegex(ValueError, "pairing keys"):
            atlas.validate_paired_trace_records(nominal, {**stress, "seed": 4002})


if __name__ == "__main__":
    unittest.main()
