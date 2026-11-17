"""Unit tests for BROAD input alignment and matched-interval scoring."""

from __future__ import annotations

import math
import unittest

from scripts.run_b9_broad_failure_atlas import (
    align_heading_gauge,
    matched_valid_mask,
    orientation_error_series,
    score_paired_errors,
    validate_broad_arrays,
)


def _qz(angle: float) -> tuple[float, float, float, float]:
    return math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2)


def _qx(angle: float) -> tuple[float, float, float, float]:
    return math.cos(angle / 2), math.sin(angle / 2), 0.0, 0.0


def _qmul(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    w, x, y, z = left
    a, b, c, d = right
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


class BroadAtlasContractTests(unittest.TestCase):
    def test_validates_aligned_broad_sensor_and_truth_arrays(self) -> None:
        validate_broad_arrays(
            "fixture",
            2000 / 7,
            [0, 3500, 7000],
            [[0, 0, 9.8]] * 3,
            [[0, 0, 0]] * 3,
            [[1, 0, 0, 0]] * 3,
            [False, True, True],
        )

    def test_rejects_broken_time_alignment_and_nonfinite_measurements(self) -> None:
        with self.assertRaisesRegex(ValueError, "timestamps"):
            validate_broad_arrays(
                "bad-time", 2000 / 7, [0, 3500, 3499], [[0, 0, 9.8]] * 3,
                [[0, 0, 0]] * 3, [[1, 0, 0, 0]] * 3, [False, True, True]
            )

    def test_optical_reference_gaps_are_validity_masked(self) -> None:
        validate_broad_arrays(
            "reference-gap", 2000 / 7, [0, 3500, 7000], [[0, 0, 9.8]] * 3,
            [[0, 0, 0]] * 3, [[1, 0, 0, 0], [math.nan] * 4, [1, 0, 0, 0]], [False, True, True]
        )
        self.assertEqual(
            matched_valid_mask(
                [0, 3500, 7000], [0, 3500, 7000], [True] * 3,
                [0, 3500, 7000], [True] * 3, [True, False, True]
            ),
            [True, False, True],
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_broad_arrays(
                "bad-imu", 2000 / 7, [0, 3500, 7000], [[0, 0, 9.8], [math.nan, 0, 0], [0, 0, 9.8]],
                [[0, 0, 0]] * 3, [[1, 0, 0, 0]] * 3, [False, True, True]
            )

    def test_intersects_exact_output_timestamps_and_validity_masks(self) -> None:
        mask = matched_valid_mask(
            [0, 3500, 7000], [0, 3500, 7000], [True, True, True],
            [0, 3500, 7000], [False, True, False]
        )
        self.assertEqual(mask, [False, True, False])
        with self.assertRaisesRegex(ValueError, "timestamp"):
            matched_valid_mask(
                [0, 3500], [0, 3500], [True, True], [0, 3501], [True, True]
            )

    def test_yaw_gauge_alignment_keeps_tilt_and_exposes_relative_heading_drift(self) -> None:
        truth = [_qz(0.2), _qz(0.2), _qz(0.2)]
        estimates = [_qz(1.1), _qz(1.1), _qmul(_qz(1.1), _qx(0.1))]
        aligned = align_heading_gauge(estimates, truth, anchor_index=1)
        errors = orientation_error_series(aligned, truth, anchor_index=1)
        self.assertAlmostEqual(errors["geodesic_error_rad"][1], 0.0, places=7)
        self.assertAlmostEqual(errors["tilt_error_rad"][1], 0.0, places=7)
        self.assertGreater(errors["tilt_error_rad"][2], 0.09)

    def test_scores_only_movement_samples_in_the_valid_timestamp_intersection(self) -> None:
        scores = score_paired_errors(
            {
                "geodesic_error_rad": [9.0, 1.0, 3.0, 9.0],
                "tilt_error_rad": [9.0, 1.0, 3.0, 9.0],
                "relative_heading_drift_rad": [9.0, 1.0, 3.0, 9.0],
            },
            [False, True, True, True],
            [False, True, True, False],
        )
        self.assertEqual(scores["paired_movement_sample_count"], 2)
        self.assertAlmostEqual(scores["geodesic_rms_rad"], math.sqrt(5.0), places=12)
        self.assertAlmostEqual(scores["tilt_rms_rad"], math.sqrt(5.0), places=12)


if __name__ == "__main__":
    unittest.main()
