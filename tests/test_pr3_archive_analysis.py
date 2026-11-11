import csv
import gzip
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_pr3_archives import (  # noqa: E402
    CSV_COLUMNS,
    ESKF_ESTIMATORS,
    ESTIMATORS,
    EXPECTED_PROFILES,
    PROTOCOL_SHA256,
    AnalysisError,
    analyze_rows,
    iter_csv_rows,
    pair_trial_rows,
    trial_weighted_mean,
)


SPLIT = "development"
ARCHIVE_SHA256 = "a" * 64
SCENARIO = "static"
RATE_MODE = "uniform_200hz"
STRESS_MODE = "nominal"
STREAM = (SCENARIO, RATE_MODE, STRESS_MODE, 1)
PROFILE = EXPECTED_PROFILES[0]


def make_row(seed, profile, estimator, *, tilt=1.0, expected=10, input_hash=None):
    sensor_input, startup, calibration, aid = profile
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "protocol_version": "5",
            "protocol_sha256": PROTOCOL_SHA256,
            "input_sha256": input_hash or f"{seed:064x}",
            "config_sha256": "2" * 64,
            "commit_sha": "02c61fe7c4b93d591b042c69b08cfe20a6277722",
            "scenario": SCENARIO,
            "rate_mode": RATE_MODE,
            "stress_mode": STRESS_MODE,
            "seed_split": SPLIT,
            "seed": str(seed),
            "sensor_input": sensor_input,
            "startup_knowledge": startup,
            "startup_gyro_bias_calibration": calibration,
            "runtime_aid": aid,
            "estimator": estimator,
            "expected": str(expected),
            "produced": str(expected),
            "valid": str(expected),
            "missing": "0",
            "unavailable": "0",
            "unavailable_duration_s": "0",
            "recovery_time_s": "",
            "recovery_time_reason": "no_unavailability",
            "stale": "0",
            "control_valid": str(expected),
            "covariance_valid": str(expected if estimator in ESKF_ESTIMATORS else 0),
            "faults": "0",
            "resets": "0",
            "rejected": "0",
            "aid_accepted": "0",
            "aid_rejected": "0",
            "availability": "1.0",
            "tilt_rms_deg": str(tilt),
            "tilt_p95_deg": str(tilt),
            "tilt_max_deg": str(tilt),
            "attitude_rms_deg": str(tilt),
            "yaw_rms_deg": str(tilt + 1.0),
            "position_rms_m": "",
            "velocity_rms_m_s": "",
            "accel_bias_error_m_s2": "0.1" if estimator in ESKF_ESTIMATORS else "",
            "gyro_bias_error_rad_s": "0.01",
            "tilt_nees_mean": "0.5" if estimator in ESKF_ESTIMATORS else "",
            "tilt_nees_count": str(expected if estimator in ESKF_ESTIMATORS else 0),
            "tilt_nees_coverage95": "1.0" if estimator in ESKF_ESTIMATORS else "",
            "nis_mean": "0.25" if estimator in ESKF_ESTIMATORS else "",
            "nis_count": str(expected if estimator in ESKF_ESTIMATORS else 0),
            "max_state_age_us": "0",
            "health_end": "Nominal",
            "complete_run": "true",
            "covariance_applicable": "true" if estimator in ESKF_ESTIMATORS else "false",
            "navigation_applicable": "true" if estimator in ESKF_ESTIMATORS else "false",
            "pr2_gate_status": "OPEN",
        }
    )
    return row


def one_stream_rows(*, profiles=(PROFILE,), seeds=(1,)):
    rows = []
    for seed in seeds:
        for profile in profiles:
            for estimator in ESTIMATORS:
                rows.append(make_row(seed, profile, estimator))
    return rows


def analyze_fixture(rows, *, profiles=(PROFILE,), seeds=(1,), trials_per_group=1):
    expected_streams = {
        (SCENARIO, RATE_MODE, STRESS_MODE, seed) for seed in seeds
    }
    return analyze_rows(
        rows,
        split=SPLIT,
        archive_sha256=ARCHIVE_SHA256,
        expected_profiles=set(profiles),
        expected_stream_keys=expected_streams,
        expected_trials_per_group=trials_per_group,
    )


class Pr3ArchiveAnalysisTests(unittest.TestCase):
    def test_rejects_missing_seed_key(self):
        rows = one_stream_rows()
        rows[0]["seed"] = ""
        with self.assertRaisesRegex(AnalysisError, "missing.*seed"):
            analyze_fixture(rows)

    def test_rejects_duplicate_group_estimator_seed(self):
        rows = one_stream_rows()
        rows.append(dict(rows[0]))
        with self.assertRaisesRegex(AnalysisError, "duplicate.*trial key"):
            analyze_fixture(rows)

    def test_rejects_missing_trial_row(self):
        rows = [
            row
            for row in one_stream_rows()
            if not (row["estimator"] == "mahony" and row["seed"] == "1")
        ]
        with self.assertRaisesRegex(AnalysisError, "missing.*estimator"):
            analyze_fixture(rows)

    def test_rejects_wrong_csv_column_count(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "wrong_shape.csv.gz"
            with gzip.open(archive, "wt", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(CSV_COLUMNS)
                writer.writerow([""] * (len(CSV_COLUMNS) - 1))
            with self.assertRaisesRegex(AnalysisError, "wrong column count"):
                list(iter_csv_rows(archive))

    def test_rejects_nan_metric_instead_of_turning_it_into_zero(self):
        rows = one_stream_rows()
        rows[0]["tilt_rms_deg"] = "NaN"
        with self.assertRaisesRegex(AnalysisError, "non-finite.*tilt_rms_deg"):
            analyze_fixture(rows)

    def test_rejects_input_hash_mismatch_across_estimators(self):
        rows = one_stream_rows()
        mahony = next(row for row in rows if row["estimator"] == "mahony")
        mahony["input_sha256"] = "f" * 64
        with self.assertRaisesRegex(AnalysisError, "input SHA mismatch"):
            analyze_fixture(rows)

    def test_no_aid_yaw_is_exposed_as_relative_heading_rms(self):
        profiles = (PROFILE, EXPECTED_PROFILES[4])
        result = analyze_fixture(
            one_stream_rows(profiles=profiles),
            profiles=profiles,
        )
        group = next(
            item for item in result["groups"]
            if item["estimator"] == "eskf_conservative" and item["runtime_aid"] == "NONE"
        )
        self.assertEqual(group["yaw_metric_interpretation"], "relative heading RMS from shared zero-yaw startup gauge; not absolute north")
        self.assertEqual(group["relative_heading_rms_mean_deg"], group["yaw_rms_mean_deg"])
        independent = next(
            item for item in result["groups"]
            if item["estimator"] == "eskf_conservative"
            and item["runtime_aid"] == "INDEPENDENT_MEASUREMENT"
        )
        self.assertIsNone(independent["relative_heading_rms_mean_deg"])
        self.assertIn("synthetic independent heading", independent["yaw_metric_interpretation"])

    def test_rejects_incompatible_profile_pairing(self):
        rows = one_stream_rows()
        eskf = next(row for row in rows if row["estimator"] == "eskf_conservative")
        mahony = next(row for row in rows if row["estimator"] == "mahony")
        other_profile = EXPECTED_PROFILES[1]
        (
            mahony["sensor_input"],
            mahony["startup_knowledge"],
            mahony["startup_gyro_bias_calibration"],
            mahony["runtime_aid"],
        ) = other_profile
        with self.assertRaisesRegex(AnalysisError, "incompatible profile pairing"):
            pair_trial_rows([eskf, mahony])

    def test_rejects_wrong_profile_count_for_shared_stream(self):
        profiles = tuple(EXPECTED_PROFILES)
        rows = one_stream_rows(profiles=profiles)
        missing_profile = profiles[-1]
        rows = [
            row
            for row in rows
            if (
                row["sensor_input"],
                row["startup_knowledge"],
                row["startup_gyro_bias_calibration"],
                row["runtime_aid"],
            )
            != missing_profile
        ]
        with self.assertRaisesRegex(AnalysisError, "profile count|missing profile"):
            analyze_fixture(rows, profiles=profiles)

    def test_trial_means_do_not_weight_samples_as_independent_replicates(self):
        rows = one_stream_rows(seeds=(1, 2))
        for row in rows:
            if row["estimator"] == "eskf_conservative":
                if row["seed"] == "1":
                    row["tilt_rms_deg"] = "2"
                    row["expected"] = row["produced"] = row["valid"] = "2"
                    row["control_valid"] = row["covariance_valid"] = "2"
                else:
                    row["tilt_rms_deg"] = "8"
                    row["expected"] = row["produced"] = row["valid"] = "1000"
                    row["control_valid"] = row["covariance_valid"] = "1000"
        result = analyze_fixture(rows, seeds=(1, 2), trials_per_group=2)
        group = next(
            item for item in result["groups"]
            if item["estimator"] == "eskf_conservative"
        )
        self.assertEqual(group["trial_count"], 2)
        self.assertEqual(group["tilt_rms_mean_deg"], 5.0)

    def test_full_factor_mean_weights_trial_rows_not_group_means(self):
        # Group A has two trials and mean 2; group B has one trial and mean 9.
        self.assertAlmostEqual(trial_weighted_mean([[1.0, 3.0], [9.0]]), 13 / 3)


if __name__ == "__main__":
    unittest.main()
