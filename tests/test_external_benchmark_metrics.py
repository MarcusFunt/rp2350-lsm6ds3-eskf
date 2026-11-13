"""Independent mathematical and accounting oracles for host-side scoring."""

import math
import random
import unittest

from external_benchmarks.api import gravity_direction_body as contract_gravity_direction_body
from external_benchmarks.metrics import (
    MetricError,
    TrialObservation,
    absolute_heading_error_rad,
    availability_summary,
    from_project_frame,
    geodesic_error_rad,
    gravity_direction_body,
    gravity_tilt_error_rad,
    heading_rad,
    paired_trial_statistics,
    relative_heading_drift_rad,
    rotate_body_to_world,
    summarize_errors,
    to_project_frame,
    trial_score_summary,
)


def axis_rotation(axis, angle):
    sine = math.sin(angle / 2.0)
    quaternion = [math.cos(angle / 2.0), 0.0, 0.0, 0.0]
    quaternion[axis + 1] = sine
    return tuple(quaternion)


def multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def assert_quaternion_rotation_equal(test, left, right, tolerance=1e-10):
    test.assertLessEqual(geodesic_error_rad(left, right), tolerance)


class OrientationOracleTests(unittest.TestCase):
    def test_identity_axis_rotations_and_sign_equivalence(self):
        identity = (1.0, 0.0, 0.0, 0.0)
        self.assertEqual(geodesic_error_rad(identity, identity), 0.0)
        self.assertEqual(geodesic_error_rad(identity, tuple(-v for v in identity)), 0.0)
        self.assertEqual(gravity_tilt_error_rad(identity, identity), 0.0)
        self.assertEqual(gravity_tilt_error_rad(identity, tuple(-v for v in identity)), 0.0)

        cases = (
            (0, math.pi / 2.0, (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            (0, -math.pi / 2.0, (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
            (1, math.pi / 2.0, (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
            (1, -math.pi / 2.0, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            (2, math.pi / 2.0, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            (2, -math.pi / 2.0, (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
        )
        for axis, angle, vector, expected in cases:
            with self.subTest(axis=axis, angle=angle):
                got = rotate_body_to_world(axis_rotation(axis, angle), vector)
                for actual, wanted in zip(got, expected):
                    self.assertAlmostEqual(actual, wanted, places=12)

    def test_global_yaw_is_invariant_for_tilt_but_not_full_attitude(self):
        tilted = multiply(axis_rotation(0, 0.43), axis_rotation(1, -0.31))
        yaw = axis_rotation(2, 1.17)
        yawed = multiply(yaw, tilted)
        self.assertLess(gravity_tilt_error_rad(yawed, tilted), 1e-12)
        self.assertGreater(geodesic_error_rad(yawed, tilted), 1.0)

    def test_frame_conversion_roundtrip_with_nontrivial_world_transform(self):
        q_broad_from_body = multiply(axis_rotation(0, -0.28), axis_rotation(2, 0.64))
        q_project_from_broad = multiply(axis_rotation(1, math.pi / 2), axis_rotation(2, -math.pi / 2))
        converted = to_project_frame(q_broad_from_body, q_project_from_broad)
        restored = from_project_frame(converted, q_project_from_broad)
        assert_quaternion_rotation_equal(self, restored, q_broad_from_body)
        identity_frame = (1.0, 0.0, 0.0, 0.0)  # BROAD opt_quat is documented as ENU.
        assert_quaternion_rotation_equal(
            self,
            from_project_frame(to_project_frame(q_broad_from_body, identity_frame), identity_frame),
            q_broad_from_body,
        )

    def test_heading_singularity_and_absolute_source_requirement(self):
        body_x_vertical = axis_rotation(1, math.pi / 2.0)
        self.assertIsNone(heading_rad(body_x_vertical))
        self.assertIsNone(absolute_heading_error_rad(body_x_vertical, (1.0, 0.0, 0.0, 0.0), source=None))
        with self.assertRaises(MetricError):
            absolute_heading_error_rad((1.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), source="")
        self.assertAlmostEqual(
            absolute_heading_error_rad(axis_rotation(2, 0.3), (1.0, 0.0, 0.0, 0.0), source="independent_heading"),
            0.3,
        )

    def test_relative_heading_drift_removes_startup_yaw_gauge(self):
        truth = [(1.0, 0.0, 0.0, 0.0)] * 3
        estimate = [axis_rotation(2, angle) for angle in (0.6, 0.8, 1.1)]
        drift = relative_heading_drift_rad(estimate, truth, alignment_index=0)
        self.assertAlmostEqual(drift[0], 0.0)
        self.assertAlmostEqual(drift[1], 0.2)
        self.assertAlmostEqual(drift[2], 0.5)
        with self.assertRaises(MetricError):
            relative_heading_drift_rad(estimate, truth[:-1], alignment_index=0)

    def test_identical_orientation_has_zero_error_and_broad_inclination_oracle_matches(self):
        rng = random.Random(20261113)
        for _ in range(250):
            def random_unit_quaternion():
                values = [rng.uniform(-1.0, 1.0) for _ in range(4)]
                norm = math.sqrt(sum(v * v for v in values))
                return tuple(v / norm for v in values)

            truth, estimate = random_unit_quaternion(), random_unit_quaternion()
            self.assertEqual(geodesic_error_rad(truth, truth), 0.0)
            self.assertEqual(geodesic_error_rad(truth, tuple(-v for v in truth)), 0.0)
            self.assertEqual(gravity_tilt_error_rad(truth, truth), 0.0)
            for actual, contract in zip(gravity_direction_body(truth), contract_gravity_direction_body(truth)):
                self.assertAlmostEqual(actual, contract, delta=1e-12)

            # Existing PR3 definitions: angle between q^-1*z gravity vectors,
            # and shortest rotation angle from estimate*conjugate(truth).
            pr3_estimate_up = tuple(-v for v in gravity_direction_body(estimate))
            pr3_truth_up = tuple(-v for v in gravity_direction_body(truth))
            gravity_dot = sum(a * b for a, b in zip(pr3_estimate_up, pr3_truth_up))
            pr3_tilt = math.acos(min(1.0, max(-1.0, gravity_dot)))
            relative_pr3 = multiply(estimate, (truth[0], -truth[1], -truth[2], -truth[3]))
            pr3_attitude = 2.0 * math.atan2(
                math.sqrt(sum(component * component for component in relative_pr3[1:])),
                abs(relative_pr3[0]),
            )
            self.assertAlmostEqual(gravity_tilt_error_rad(estimate, truth), pr3_tilt, delta=2e-7)
            self.assertAlmostEqual(geodesic_error_rad(estimate, truth), pr3_attitude, delta=2e-12)

            # Independent transcription of BROAD broad_utils.py's
            # calculateInclinationError(calculateErrorQuatEarth(est, truth)).
            relative = multiply(estimate, (truth[0], -truth[1], -truth[2], -truth[3]))
            broad_inclination = 2.0 * math.acos(min(1.0, math.sqrt(relative[0] ** 2 + relative[3] ** 2)))
            self.assertAlmostEqual(gravity_tilt_error_rad(estimate, truth), broad_inclination, delta=2e-7)


class TrialAccountingTests(unittest.TestCase):
    def test_error_summary_uses_pr3_lower_order_statistic_p95(self):
        result = summarize_errors(range(11))
        self.assertEqual(result.count, 11)
        self.assertAlmostEqual(result.rms, math.sqrt(35.0))
        self.assertEqual(result.p95, 9.0)  # sorted[int(.95 * (n - 1))]
        self.assertEqual(result.maximum, 10.0)
        signed = summarize_errors((-0.5, 0.2, -0.1))
        self.assertAlmostEqual(signed.maximum, 0.5)

    def test_availability_outage_recovery_and_segments(self):
        timestamps = (0.0, 1.0, 2.0, 3.0, 4.0)
        expected = (True,) * 5
        valid = (True, False, False, True, True)
        errors = (0.0, 4.0, 2.0, 0.1, 0.1)
        result = availability_summary(
            timestamps,
            expected,
            valid,
            errors=errors,
            segment_start_s=0.0,
            segment_end_s=5.0,
            recovery_event_time_s=1.0,
            recovery_error_threshold=0.5,
            recovery_dwell_s=1.0,
        )
        self.assertEqual((result.expected_count, result.valid_count), (5, 3))
        self.assertAlmostEqual(result.availability, 0.6)
        self.assertAlmostEqual(result.longest_outage_s, 2.0)
        self.assertAlmostEqual(result.recovery_time_s, 2.0)

        segments = availability_summary(
            timestamps,
            expected,
            valid,
            segment_bounds={"early": (0.0, 2.0), "late": (2.0, 5.0)},
        ).segments
        self.assertEqual(segments["early"].expected_count, 2)
        self.assertEqual(segments["early"].valid_count, 1)
        self.assertEqual(segments["late"].expected_count, 3)
        self.assertEqual(segments["late"].valid_count, 2)
        offset_segment = availability_summary(
            timestamps,
            expected,
            valid,
            segment_bounds={"offset": (1.5, 3.5)},
        ).segments["offset"]
        self.assertEqual((offset_segment.expected_count, offset_segment.valid_count), (2, 1))
        self.assertAlmostEqual(offset_segment.longest_outage_s, 1.5)

    def test_trial_score_reports_error_distribution_for_trial_and_segments(self):
        result = trial_score_summary(
            (0.0, 1.0, 2.0, 3.0, 4.0),
            (0.2, -0.5, 99.0, 0.1, 0.4),
            (True,) * 5,
            (True, False, False, True, True),
            segment_start_s=0.0,
            segment_end_s=5.0,
            segment_bounds={"early": (0.0, 2.0), "late": (2.0, 5.0)},
        )
        self.assertEqual(result.error.count, 3)
        self.assertAlmostEqual(result.error.maximum, 0.4)
        self.assertAlmostEqual(result.segments["early"].error.maximum, 0.2)
        self.assertAlmostEqual(result.segments["late"].error.maximum, 0.4)
        self.assertAlmostEqual(result.segments["early"].availability.availability, 0.5)
        self.assertAlmostEqual(result.segments["late"].availability.availability, 2.0 / 3.0)

    def test_no_recovery_is_unavailable_and_invalid_shapes_fail(self):
        result = availability_summary(
            (0.0, 1.0, 2.0),
            (True, True, True),
            (True, True, True),
            errors=(3.0, 2.0, 1.0),
            segment_start_s=0.0,
            segment_end_s=3.0,
            recovery_event_time_s=0.5,
            recovery_error_threshold=0.1,
            recovery_dwell_s=0.5,
        )
        self.assertIsNone(result.recovery_time_s)
        with self.assertRaises(MetricError):
            availability_summary((0.0,), (True,), (True, False))

    def test_paired_statistics_use_unique_trial_seed_pairs_and_same_inputs(self):
        baseline = [
            TrialObservation("trial-a", 1, "a" * 64, 2.0),
            TrialObservation("trial-a", 2, "b" * 64, 3.0),
            TrialObservation("trial-b", 1, "c" * 64, 5.0),
        ]
        candidate = [
            TrialObservation("trial-a", 1, "a" * 64, 1.0),
            TrialObservation("trial-a", 2, "b" * 64, 2.0),
            TrialObservation("trial-b", 1, "c" * 64, 4.0),
        ]
        result = paired_trial_statistics(baseline, candidate, bootstrap_replicates=200, bootstrap_seed=9)
        self.assertEqual(result.n_pairs, 3)
        self.assertEqual(result.differences, (-1.0, -1.0, -1.0))
        self.assertEqual(result.mean_difference, -1.0)
        self.assertEqual(result.ci95, (-1.0, -1.0))
        with self.assertRaises(MetricError):
            paired_trial_statistics(baseline, candidate[:-1])
        with self.assertRaises(MetricError):
            paired_trial_statistics(baseline, candidate + [candidate[0]])
        mismatched = list(candidate)
        mismatched[0] = TrialObservation("trial-a", 1, "f" * 64, 1.0)
        with self.assertRaises(MetricError):
            paired_trial_statistics(baseline, mismatched)


if __name__ == "__main__":
    unittest.main()
