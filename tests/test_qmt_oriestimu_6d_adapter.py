"""Tests for the optional author-maintained qmt Seel/OriEstIMU adapter."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
    import qmt
except ModuleNotFoundError:
    np = None
    qmt = None
    HAS_QMT_REFERENCE = False
else:
    HAS_QMT_REFERENCE = True


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import ContractError, check_reset_isolation, run_trial  # noqa: E402
from external_benchmarks.adapters.qmt_oriestimu_6d import (  # noqa: E402
    DEFAULT_PARAMETERS,
    SeelOriEstIMU6DAdapter,
    default_config,
)


RATE_HZ = 100
DT = 1.0 / RATE_HZ
GRAVITY = 9.80665
INTERVAL_NS = 10_000_000


def quaternion_multiply(left, right):
    w, x, y, z = left
    a, b, c, d = right
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


def quaternion_rotate(quaternion, vector):
    inverse = (quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3])
    rotated = quaternion_multiply(quaternion_multiply(quaternion, (0.0, *vector)), inverse)
    return rotated[1:]


def quaternion_conjugate(quaternion):
    return (quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3])


def quaternion_geodesic_rad(left, right):
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    left = left / np.linalg.norm(left)
    right = right / np.linalg.norm(right)
    relative = quaternion_multiply(quaternion_conjugate(left), right)
    return 2.0 * math.atan2(math.sqrt(sum(value * value for value in relative[1:])), abs(relative[0]))


def make_trial(accels, gyros, *, trial_id="qmt-fixture", rate_hz=RATE_HZ):
    assert len(accels) == len(gyros) and accels
    interval = round(1_000_000_000 / rate_hz)
    samples = [
        {
            "timestamp": index * interval,
            "accel_mps2": [float(value) for value in accel],
            "gyro_rad_s": [float(value) for value in gyro],
            "valid": True,
        }
        for index, (accel, gyro) in enumerate(zip(accels, gyros))
    ]
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": trial_id,
        "source_id": "qmt-b4-deterministic-fixture",
        "source_artifact_sha256": "a" * 64,
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


def tilted_yaw_sequence(count, *, tilt_deg=35.0, yaw_rate=0.0, rate_hz=RATE_HZ):
    tilt_angle = math.radians(tilt_deg)
    tilt = (math.cos(tilt_angle / 2), math.sin(tilt_angle / 2), 0.0, 0.0)
    accels, gyros = [], []
    for index in range(count):
        yaw_angle = yaw_rate * index / rate_hz
        yaw = (math.cos(yaw_angle / 2), 0.0, 0.0, math.sin(yaw_angle / 2))
        q_world_from_body = quaternion_multiply(yaw, tilt)
        q_body_from_world = quaternion_conjugate(q_world_from_body)
        accels.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, GRAVITY)))
        gyros.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, yaw_rate)))
    return accels, gyros


def synthetic_sequences():
    sequences = {
        "stationary": ([(0.0, 0.0, GRAVITY)] * 300, [(0.0, 0.0, 0.0)] * 300),
        "yaw_only": ([(0.0, 0.0, GRAVITY)] * 300, [(0.0, 0.0, 0.25)] * 300),
        "tilted_stationary": tilted_yaw_sequence(1000, tilt_deg=35.0),
        "tilted_world_yaw": tilted_yaw_sequence(800, tilt_deg=35.0, yaw_rate=0.35),
        "constant_rotation": ([(0.0, 0.0, GRAVITY)] * 400, [(0.2, -0.1, 0.3)] * 400),
    }
    varying_accels, varying_gyros = [], []
    for index in range(500):
        time_s = index / RATE_HZ
        varying_gyros.append((0.1 * math.sin(time_s), -0.05 * math.cos(0.5 * time_s), 0.1 + 0.25 * time_s / 5.0))
        varying_accels.append((0.6 * math.sin(0.4 * time_s), -0.3 * math.cos(0.3 * time_s), GRAVITY + 0.2 * math.sin(0.2 * time_s)))
    sequences["slowly_varying_rate"] = varying_accels, varying_gyros

    pulse_accels, pulse_gyros = [], []
    for index in range(250):
        pulse_accels.append((3.0 if 40 <= index < 120 else 0.0, 0.0, GRAVITY))
        pulse_gyros.append((0.0, 0.0, 0.4))
    sequences["acceleration_pulse"] = pulse_accels, pulse_gyros
    return sequences


def direct_batch(accels, gyros, config):
    params = dict(config["parameters"])
    params["Ts"] = config["sampling_rate_hz"]["denominator"] / config["sampling_rate_hz"]["numerator"]
    params["initQuat"] = np.asarray(params["initQuat"], dtype=np.float64)
    params["initBias"] = np.asarray(params["initBias"], dtype=np.float64)
    return qmt.oriEstIMU(
        np.ascontiguousarray(gyros, dtype=np.float64),
        np.ascontiguousarray(accels, dtype=np.float64),
        mag=None,
        params=params,
    )


@unittest.skipUnless(HAS_QMT_REFERENCE, "install the pinned qmt B4 reference dependencies")
class QmtOriEstIMUAdapterTests(unittest.TestCase):
    def test_manifest_identifies_official_seel_not_vqf_as_causal_six_axis(self):
        manifest = SeelOriEstIMU6DAdapter.manifest
        self.assertEqual(manifest["adapter_id"], "official.qmt.oriEstIMU")
        self.assertEqual(manifest["variant_id"], "seel_oriestimu_6d_causal_block_defaults_reset_v0.2.4")
        self.assertNotEqual(manifest["adapter_id"], "official.vqf")
        self.assertEqual(manifest["execution_mode"], "causal_online")
        self.assertEqual(manifest["supported_sensor_sets"], ["gyro_accel_6d"])
        self.assertEqual(manifest["supported_aid_types"], [])
        self.assertEqual(manifest["initialization"]["orientation_source"], "identity")

    def test_default_parameter_set_is_the_documented_streaming_block_set(self):
        block = qmt.OriEstIMUBlock(DT)
        self.assertEqual(block.params, {"tauAcc": 2.0, "tauMag": 2.0, "zeta": 0.0, "accRating": 1.0})
        self.assertEqual(DEFAULT_PARAMETERS["tauAcc"], 2.0)
        self.assertEqual(DEFAULT_PARAMETERS["tauMag"], 2.0)
        self.assertEqual(DEFAULT_PARAMETERS["zeta"], 0.0)
        self.assertEqual(DEFAULT_PARAMETERS["accRating"], 1.0)
        self.assertEqual(DEFAULT_PARAMETERS["initQuat"], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(DEFAULT_PARAMETERS["initBias"], [0.0, 0.0, 0.0])

    def test_stationary_and_tilted_gravity_align_in_enu(self):
        stationary = make_trial(*synthetic_sequences()["stationary"], trial_id="stationary")
        result = run_trial(SeelOriEstIMU6DAdapter(), stationary, default_config())
        np.testing.assert_array_equal(result["samples"][-1]["orientation"]["quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])

        accels, gyros = synthetic_sequences()["tilted_stationary"]
        tilted = make_trial(accels, gyros, trial_id="tilted-stationary")
        tilted_result = run_trial(SeelOriEstIMU6DAdapter(), tilted, default_config())
        q_final = np.asarray(tilted_result["samples"][-1]["orientation"]["quaternion_wxyz"])
        tilt = math.radians(35.0)
        q_truth = (math.cos(tilt / 2), math.sin(tilt / 2), 0.0, 0.0)
        self.assertLess(quaternion_geodesic_rad(q_final, q_truth), math.radians(0.01))
        estimated_up_world = quaternion_rotate(q_final, accels[-1])
        estimated_up_world = np.asarray(estimated_up_world) / np.linalg.norm(estimated_up_world)
        self.assertLess(math.acos(float(np.clip(estimated_up_world[2], -1.0, 1.0))), math.radians(0.01))

    def test_shared_runner_rejects_aids_and_strictly_checks_config_and_timestamps(self):
        trial = make_trial(*synthetic_sequences()["stationary"][:], trial_id="aid-rejection")
        trial["samples"][1]["aid"] = {
            "kind": "independent_heading",
            "value_rad": 0.1,
            "units": "rad",
            "source_id": "heading-fixture",
            "reference_frame": "ENU",
            "independence": "independent_of_imu",
        }
        with self.assertRaises(ContractError):
            run_trial(SeelOriEstIMU6DAdapter(), trial, default_config())

        adapter = SeelOriEstIMU6DAdapter()
        with self.assertRaises(ContractError):
            adapter.reset({**default_config(), "tauAcc": 1.0})
        adapter.reset(default_config())
        adapter.step(0, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        with self.assertRaises(ContractError):
            adapter.step(INTERVAL_NS + 2, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))

    def test_streaming_and_batch_match_on_identical_synthetic_sequences(self):
        config = default_config()
        for name, (accels, gyros) in synthetic_sequences().items():
            with self.subTest(sequence=name):
                trial = make_trial(accels, gyros, trial_id=f"batch-parity-{name}")
                result = run_trial(SeelOriEstIMU6DAdapter(), trial, config)
                streaming = np.asarray([row["orientation"]["quaternion_wxyz"] for row in result["samples"]])
                batch = direct_batch(accels, gyros, config)
                np.testing.assert_array_equal(streaming, batch)
                np.testing.assert_allclose(np.linalg.norm(streaming, axis=1), 1.0, atol=1e-12)
                self.assertTrue(np.all(streaming[:, 0] >= -1e-14))

    def test_pure_yaw_integrates_without_claiming_an_absolute_heading(self):
        accels, gyros = synthetic_sequences()["yaw_only"]
        result = run_trial(SeelOriEstIMU6DAdapter(), make_trial(accels, gyros), default_config())
        observed = np.asarray(result["samples"][-1]["orientation"]["quaternion_wxyz"])
        # qmt calls one fixed-Ts update for every sample, including the first.
        angle = gyros[0][2] * len(gyros) * DT
        expected = (math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2))
        self.assertLess(quaternion_geodesic_rad(observed, expected), 1e-12)
        self.assertEqual(result["samples"][-1]["orientation"]["yaw_gauge"], "unobservable_startup")

    def test_prefix_is_causal_and_reset_recreates_all_upstream_state(self):
        target_accels, target_gyros = tilted_yaw_sequence(100, tilt_deg=60.0)
        target = make_trial(target_accels, target_gyros, trial_id="target")
        full = run_trial(SeelOriEstIMU6DAdapter(), target, default_config())
        prefix = make_trial(target_accels[:40], target_gyros[:40], trial_id="prefix")
        prefix_result = run_trial(SeelOriEstIMU6DAdapter(), prefix, default_config())
        self.assertEqual(full["samples"][:40], prefix_result["samples"])

        other_accels = [(5.0, 0.0, GRAVITY)] * 100
        other_gyros = [(0.4, -0.1, 0.2)] * 100
        interleaved = make_trial(other_accels, other_gyros, trial_id="interleaved")
        check_reset_isolation(SeelOriEstIMU6DAdapter, target, interleaved, default_config())

    def test_upstream_command_reset_alone_retains_warmup_counter(self):
        """Pin the upstream reset limitation that the adapter avoids by recreating the block."""
        target_accels, target_gyros = tilted_yaw_sequence(100, tilt_deg=60.0)
        preceding_accels = [(5.0, 0.0, GRAVITY)] * 100
        preceding_gyros = [(0.4, -0.1, 0.2)] * 100

        def run_block(block, accels, gyros):
            zero_mag = np.zeros(3, dtype=np.float64)
            return np.asarray([
                block.step(np.asarray(gyro), np.asarray(accel), zero_mag)
                for accel, gyro in zip(accels, gyros)
            ])

        reused = qmt.OriEstIMUBlock(DT)
        reused.command(["reset"])
        run_block(reused, preceding_accels, preceding_gyros)
        reused.command(["reset"])
        reused_after_reset = run_block(reused, target_accels, target_gyros)

        fresh = qmt.OriEstIMUBlock(DT)
        fresh.command(["reset"])
        fresh_target = run_block(fresh, target_accels, target_gyros)
        maximum_error = max(quaternion_geodesic_rad(a, b) for a, b in zip(reused_after_reset, fresh_target))
        self.assertGreater(maximum_error, 0.1)


if __name__ == "__main__":
    unittest.main()
