"""Tests for canonical 6D Mahony/Madgwick and historical-baseline adapters."""

from __future__ import annotations

import math
import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np

try:
    from ahrs.filters import Madgwick as UpstreamMadgwick
    from ahrs.filters import Mahony as UpstreamMahony
except ImportError:  # pragma: no cover - exercised when optional parity lock is absent
    UpstreamMadgwick = None
    UpstreamMahony = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import (  # noqa: E402
    ContractError,
    canonical_input_sha256,
    check_reset_isolation,
    run_trial,
)
from external_benchmarks.adapters.canonical_ahrs6d import (  # noqa: E402
    HISTORICAL_VARIANT_ID,
    MadgwickReference6DAdapter,
    MahonyInternalHistoricalAdapter,
    MahonyReference6DAdapter,
    default_madgwick_config,
    default_mahony_config,
)
from external_benchmarks.adapters.canonical_ahrs6d_math import (  # noqa: E402
    quaternion_geodesic_rad,
    rotate_body_to_world,
)


RATE_HZ = 100
DT_NS = 10_000_000
GRAVITY = 9.80665


def make_trial(accels, gyros, *, trial_id="b6-fixture", rate_hz=RATE_HZ):
    assert len(accels) == len(gyros) and len(accels) > 0
    interval = round(1_000_000_000 / rate_hz)
    samples = [
        {
            "timestamp": (index + 1) * interval,
            "accel_mps2": [float(x) for x in accel],
            "gyro_rad_s": [float(x) for x in gyro],
            "valid": True,
        }
        for index, (accel, gyro) in enumerate(zip(accels, gyros))
    ]
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": trial_id,
        "source_id": "canonical-ahrs-b6-synthetic",
        "source_artifact_sha256": "c" * 64,
        "sensor_set": "gyro_accel_6d",
        "timebase": {
            "timestamp_unit": "ns",
            "sampling_mode": "uniform",
            "nominal_rate_hz": {"numerator": rate_hz, "denominator": 1},
        },
        "frame_convention": {
            "body_frame": "sensor_body_right_handed",
            "world_frame": "ENU",
            "gravity_world_mps2": [0.0, 0.0, -GRAVITY],
            "accelerometer_quantity": "specific_force",
        },
        "units": {"timestamp": "ns", "accelerometer": "m/s^2", "gyroscope": "rad/s"},
        "sample_count": len(samples),
        "samples": samples,
    }


def tilted_stationary(count, *, tilt_deg=30.0):
    angle = math.radians(tilt_deg)
    accel = (0.0, GRAVITY * math.sin(angle), GRAVITY * math.cos(angle))
    return [accel] * count, [(0.0, 0.0, 0.0)] * count


def trial_outputs(adapter_type, trial, config):
    return run_trial(adapter_type(), trial, config)


class CanonicalAHRS6DAdapterTests(unittest.TestCase):
    def test_manifests_distinguish_canonical_references_from_historical_internal(self):
        mahony = MahonyReference6DAdapter.manifest
        madgwick = MadgwickReference6DAdapter.manifest
        historical = MahonyInternalHistoricalAdapter.manifest
        self.assertEqual(mahony["adapter_id"], "mahony_reference")
        self.assertEqual(madgwick["adapter_id"], "madgwick_reference")
        self.assertEqual(historical["adapter_id"], HISTORICAL_VARIANT_ID)
        self.assertEqual(historical["source_fidelity"]["classification"], "internal_historical")
        self.assertEqual(mahony["source_fidelity"]["classification"], "faithful_reimplementation")
        self.assertEqual(madgwick["source_fidelity"]["classification"], "faithful_reimplementation")
        self.assertNotEqual(mahony["variant_id"], historical["variant_id"])
        self.assertNotEqual(madgwick["variant_id"], historical["variant_id"])
        self.assertEqual(mahony["supported_sensor_sets"], ["gyro_accel_6d"])
        self.assertEqual(madgwick["supported_aid_types"], [])
        self.assertEqual(mahony["output_convention"]["rotation_direction"], "body_to_world")
        implementation = ROOT / "external_benchmarks/adapters/canonical_ahrs6d_math.py"
        adapter_source = ROOT / "external_benchmarks/adapters/canonical_ahrs6d.py"
        historical_source = ROOT / "tools/pr3_evaluate_stream.cpp"
        self.assertEqual(
            hashlib.sha256(implementation.read_bytes()).hexdigest(),
            mahony["source_fidelity"]["implementation_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(adapter_source.read_bytes()).hexdigest(),
            madgwick["source_fidelity"]["adapter_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(historical_source.read_bytes()).hexdigest(),
            historical["source_fidelity"]["implementation_sha256"],
        )
        alias_registry = json.loads(
            (ROOT / "external_benchmarks/adapters/mahony_variant_aliases_b6_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(alias_registry["mappings"][0]["legacy_stored_label"], "mahony")
        self.assertEqual(alias_registry["mappings"][0]["display_variant_id"], HISTORICAL_VARIANT_ID)

    def test_gyro_sign_and_analytic_axis_rotation_for_both_filters(self):
        rate = (0.41, -0.27, 0.19)
        for adapter_type, config_factory in (
            (MahonyReference6DAdapter, default_mahony_config),
            (MadgwickReference6DAdapter, default_madgwick_config),
        ):
            with self.subTest(adapter=adapter_type.__name__):
                adapter = adapter_type()
                adapter.reset(config_factory())
                output = adapter.step(DT_NS, None, rate)
                np.testing.assert_array_equal(output["orientation"]["quaternion_wxyz"], [1, 0, 0, 0])
                for index in range(1, 101):
                    output = adapter.step((index + 1) * DT_NS, None, rate)
                angle = math.sqrt(sum(component * component for component in rate))
                duration = 1.0
                expected = [
                    math.cos(angle * duration / 2.0),
                    *(component / angle * math.sin(angle * duration / 2.0) for component in rate),
                ]
                self.assertLess(quaternion_geodesic_rad(output["orientation"]["quaternion_wxyz"], expected), 3e-5)
                self.assertTrue(all(math.isfinite(x) for x in output["orientation"]["quaternion_wxyz"]))

    def test_sample_rate_scaling_matches_same_physical_gyro_rotation(self):
        outputs = []
        for rate_hz, count, adapter_type, config_factory in (
            (100, 101, MahonyReference6DAdapter, default_mahony_config),
            (200, 201, MahonyReference6DAdapter, default_mahony_config),
            (100, 101, MadgwickReference6DAdapter, default_madgwick_config),
            (200, 201, MadgwickReference6DAdapter, default_madgwick_config),
        ):
            adapter = adapter_type()
            config = config_factory(sampling_rate_numerator=rate_hz)
            adapter.reset(config)
            interval = round(1_000_000_000 / rate_hz)
            output = None
            for index in range(count):
                output = adapter.step((index + 1) * interval, None, (0.0, 0.0, 0.8))
            outputs.append(output["orientation"]["quaternion_wxyz"])
        self.assertLess(quaternion_geodesic_rad(outputs[0], outputs[1]), 3e-5)
        self.assertLess(quaternion_geodesic_rad(outputs[2], outputs[3]), 3e-5)

    def test_configured_initial_orientation_and_microsecond_timebase(self):
        yaw_90 = (math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
        for adapter_type, config_factory in (
            (MahonyReference6DAdapter, default_mahony_config),
            (MadgwickReference6DAdapter, default_madgwick_config),
        ):
            adapter = adapter_type()
            adapter.reset(config_factory(timestamp_unit="us", initial_quaternion_wxyz=yaw_90))
            first = adapter.step(10_000, None, (0.0, 0.0, 0.0))
            second = adapter.step(20_000, None, (0.0, 0.0, 0.0))
            np.testing.assert_allclose(first["orientation"]["quaternion_wxyz"], yaw_90, atol=1e-15)
            np.testing.assert_allclose(second["orientation"]["quaternion_wxyz"], yaw_90, atol=1e-15)

    def test_accelerometer_feedback_sign_moves_body_to_world_tilt_toward_up(self):
        accels, gyros = tilted_stationary(2, tilt_deg=30.0)
        for adapter_type, config_factory in (
            (MahonyReference6DAdapter, default_mahony_config),
            (MadgwickReference6DAdapter, default_madgwick_config),
        ):
            with self.subTest(adapter=adapter_type.__name__):
                adapter = adapter_type()
                adapter.reset(config_factory())
                adapter.step(DT_NS, accels[0], gyros[0])
                output = adapter.step(2 * DT_NS, accels[1], gyros[1])
                q = output["orientation"]["quaternion_wxyz"]
                self.assertGreater(q[1], 0.0, "positive body roll must produce positive body-to-world qx")
                up_world = rotate_body_to_world(q, accels[1])
                self.assertGreater(up_world[2], accels[1][2])
                self.assertEqual(output["orientation"]["yaw_gauge"], "unobservable_startup")

    def test_invalid_accelerometer_skips_feedback_and_continues_gyro_integration(self):
        for adapter_type, config_factory in (
            (MahonyReference6DAdapter, default_mahony_config),
            (MadgwickReference6DAdapter, default_madgwick_config),
        ):
            with self.subTest(adapter=adapter_type.__name__):
                missing = adapter_type()
                zero = adapter_type()
                config = config_factory()
                missing.reset(config)
                zero.reset(config)
                missing.step(DT_NS, None, (0.0, 0.0, 0.0))
                zero.step(DT_NS, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
                a = missing.step(2 * DT_NS, None, (0.1, -0.2, 0.3))
                b = zero.step(2 * DT_NS, (0.0, 0.0, 0.0), (0.1, -0.2, 0.3))
                np.testing.assert_allclose(
                    a["orientation"]["quaternion_wxyz"],
                    b["orientation"]["quaternion_wxyz"],
                    rtol=0.0,
                    atol=1e-15,
                )
                self.assertTrue(a["orientation_valid"])

    def test_mahony_integral_bias_sign_and_bias_cancellation(self):
        adapter = MahonyReference6DAdapter()
        adapter.reset(default_mahony_config())
        gyro_bias = (0.12, 0.0, 0.0)
        accel_up = (0.0, 0.0, GRAVITY)
        output = adapter.step(DT_NS, accel_up, gyro_bias)
        for index in range(1, 6001):
            output = adapter.step((index + 1) * DT_NS, accel_up, gyro_bias)
        self.assertGreater(adapter.estimated_gyro_bias_rad_s[0], 0.0)
        self.assertAlmostEqual(adapter.estimated_gyro_bias_rad_s[0], gyro_bias[0], delta=0.01)
        self.assertLess(
            quaternion_geodesic_rad(output["orientation"]["quaternion_wxyz"], [1, 0, 0, 0]),
            math.radians(3.0),
        )

    def test_madgwick_imu_reference_does_not_claim_bias_state(self):
        adapter = MadgwickReference6DAdapter()
        adapter.reset(default_madgwick_config())
        self.assertFalse(hasattr(adapter, "estimated_gyro_bias_rad_s"))
        accel, gyro = tilted_stationary(2)
        adapter.step(DT_NS, accel[0], gyro[0])
        output = adapter.step(2 * DT_NS, accel[1], gyro[1])
        self.assertNotIn("bias", output)

    def test_exact_zero_gyro_keeps_gravity_feedback_per_canonical_equations(self):
        accel = (0.0, GRAVITY * 0.5, GRAVITY * math.sqrt(0.75))
        for adapter_type, config_factory in (
            (MahonyReference6DAdapter, default_mahony_config),
            (MadgwickReference6DAdapter, default_madgwick_config),
        ):
            adapter = adapter_type()
            adapter.reset(config_factory())
            adapter.step(DT_NS, accel, (0.0, 0.0, 0.0))
            output = adapter.step(2 * DT_NS, accel, (0.0, 0.0, 0.0))
            self.assertGreater(output["orientation"]["quaternion_wxyz"][1], 0.0)

    def test_configuration_identity_and_reset_clear_all_trial_state(self):
        accels, gyros = tilted_stationary(40)
        trial = make_trial(accels, gyros, trial_id="reset-target")
        other = make_trial(
            [(0.0, 0.0, GRAVITY)] * 50,
            [(0.2, -0.1, 0.3)] * 50,
            trial_id="reset-other",
        )
        config = default_mahony_config()
        adapter = MahonyReference6DAdapter()
        run_trial(adapter, trial, config)
        first_identity = adapter.configuration_identity
        changed = default_mahony_config(k_i=0.2)
        run_trial(adapter, trial, changed)
        self.assertNotEqual(first_identity, adapter.configuration_identity)
        check_reset_isolation(MahonyReference6DAdapter, trial, other, config)
        check_reset_isolation(MadgwickReference6DAdapter, trial, other, default_madgwick_config())

    def test_wrong_times_aids_nonfinite_samples_and_bad_initial_quaternions_fail_closed(self):
        adapter = MahonyReference6DAdapter()
        adapter.reset(default_mahony_config())
        adapter.step(DT_NS, (0.0, 0.0, GRAVITY), (0.01, 0.0, 0.0))
        for call in (
            lambda: adapter.step(DT_NS, (0.0, 0.0, GRAVITY), (0.01, 0.0, 0.0)),
            lambda: adapter.step(2 * DT_NS + 2, (0.0, 0.0, GRAVITY), (0.01, 0.0, 0.0)),
            lambda: adapter.step(2 * DT_NS, (0.0, 0.0, GRAVITY), (0.01, 0.0, 0.0), {"kind": "heading"}),
            lambda: adapter.step(2 * DT_NS, (float("nan"), 0.0, GRAVITY), (0.01, 0.0, 0.0)),
        ):
            with self.assertRaises(ContractError):
                call()
        with self.assertRaises(ContractError):
            adapter.reset(default_mahony_config(initial_quaternion_wxyz=(2.0, 0.0, 0.0, 0.0)))
        with self.assertRaises(ContractError):
            adapter.step(3 * DT_NS, None, (0.0, 0.0, 0.0))

    @unittest.skipUnless(UpstreamMahony and UpstreamMadgwick, "install canonical B6 parity lock")
    def test_nonzero_rate_differential_matches_maintained_ahrs_reference_equations(self):
        sample_count = 80
        times = np.arange(sample_count, dtype=np.float64) / RATE_HZ
        gyros = np.column_stack(
            (
                0.12 + 0.03 * np.sin(times),
                -0.08 + 0.02 * np.cos(0.7 * times),
                0.04 + 0.01 * np.sin(0.3 * times),
            )
        )
        accels = np.column_stack(
            (
                GRAVITY * (0.08 + 0.02 * np.sin(times)),
                GRAVITY * (0.12 * np.cos(times)),
                GRAVITY * np.sqrt(1.0 - (0.08 + 0.02 * np.sin(times)) ** 2 - (0.12 * np.cos(times)) ** 2),
            )
        )
        trial = make_trial(accels, gyros, trial_id="upstream-equation-parity")

        mahony_config = default_mahony_config()
        actual_mahony = trial_outputs(MahonyReference6DAdapter, trial, mahony_config)
        upstream_mahony = UpstreamMahony(
            k_P=mahony_config["k_p_s_inv"],
            k_I=mahony_config["k_i_s_inv2"],
            b0=np.asarray(mahony_config["initial_gyro_bias_rad_s"]),
        )
        expected_q = np.asarray(mahony_config["initial_quaternion_wxyz"], dtype=np.float64)
        expected = [expected_q.copy()]
        for accel, gyro in zip(accels[1:], gyros[1:]):
            expected_q = np.asarray(
                upstream_mahony.updateIMU(expected_q, gyro, accel, dt=1.0 / RATE_HZ), dtype=np.float64
            )
            expected.append(expected_q.copy())
        actual = np.asarray([row["orientation"]["quaternion_wxyz"] for row in actual_mahony["samples"]])
        np.testing.assert_allclose(actual, np.asarray(expected), rtol=0.0, atol=2e-12)

        madgwick_config = default_madgwick_config()
        actual_madgwick = trial_outputs(MadgwickReference6DAdapter, trial, madgwick_config)
        upstream_madgwick = UpstreamMadgwick(gain=madgwick_config["beta_rad_s"])
        expected_q = np.asarray(madgwick_config["initial_quaternion_wxyz"], dtype=np.float64)
        expected = [expected_q.copy()]
        for accel, gyro in zip(accels[1:], gyros[1:]):
            expected_q = np.asarray(
                upstream_madgwick.updateIMU(expected_q, gyro, accel, dt=1.0 / RATE_HZ), dtype=np.float64
            )
            expected.append(expected_q.copy())
        actual = np.asarray([row["orientation"]["quaternion_wxyz"] for row in actual_madgwick["samples"]])
        np.testing.assert_allclose(actual, np.asarray(expected), rtol=0.0, atol=2e-12)

        # The maintained package short-circuits exact-zero gyro before applying
        # accelerometer feedback. The B6 faithful reimplementation follows the
        # published update equations for that degenerate but valid sample too.
        tilted_accel = np.asarray([0.0, 0.5 * GRAVITY, math.sqrt(0.75) * GRAVITY])
        identity = np.asarray([1.0, 0.0, 0.0, 0.0])
        upstream_zero_mahony = UpstreamMahony(k_P=1.0, k_I=0.3)
        upstream_zero_madgwick = UpstreamMadgwick(gain=0.033)
        np.testing.assert_array_equal(
            np.asarray(upstream_zero_mahony.updateIMU(identity, np.zeros(3), tilted_accel, dt=1.0 / RATE_HZ)),
            identity,
        )
        np.testing.assert_array_equal(
            np.asarray(upstream_zero_madgwick.updateIMU(identity, np.zeros(3), tilted_accel, dt=1.0 / RATE_HZ)),
            identity,
        )

    def test_identical_input_differential_uses_historical_id_and_is_not_alias_of_canonical(self):
        accels, gyros = tilted_stationary(1000, tilt_deg=20.0)
        trial = make_trial(accels, gyros, trial_id="same-input-tilt-correction")
        config_by_adapter = (
            (MahonyReference6DAdapter, default_mahony_config()),
            (MadgwickReference6DAdapter, default_madgwick_config()),
            (MahonyInternalHistoricalAdapter, MahonyInternalHistoricalAdapter.default_config()),
        )
        bundles = [trial_outputs(adapter_type, trial, config) for adapter_type, config in config_by_adapter]
        self.assertEqual({bundle["input_sha256"] for bundle in bundles}, {canonical_input_sha256(trial)})
        self.assertEqual(
            [bundle["adapter_manifest"]["adapter_id"] for bundle in bundles],
            ["mahony_reference", "madgwick_reference", HISTORICAL_VARIANT_ID],
        )
        q_by_variant = [
            np.asarray([sample["orientation"]["quaternion_wxyz"] for sample in bundle["samples"]])
            for bundle in bundles
        ]
        mahony_vs_historical = max(
            quaternion_geodesic_rad(a, b) for a, b in zip(q_by_variant[0], q_by_variant[2])
        )
        madgwick_vs_historical = max(
            quaternion_geodesic_rad(a, b) for a, b in zip(q_by_variant[1], q_by_variant[2])
        )
        self.assertGreater(mahony_vs_historical, 1e-5)
        self.assertGreater(madgwick_vs_historical, 1e-5)
        self.assertNotEqual(bundles[0]["config_sha256"], bundles[2]["config_sha256"])


if __name__ == "__main__":
    unittest.main()
