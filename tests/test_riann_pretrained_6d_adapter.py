"""Tests for the official pretrained RIANN causal 6D benchmark adapter."""

from __future__ import annotations

import importlib.resources
import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
    import onnxruntime as ort
    from riann import RIANN
except ModuleNotFoundError:
    np = None
    ort = None
    RIANN = None
    HAS_RIANN_RUNTIME = False
else:
    HAS_RIANN_RUNTIME = True


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import ContractError, check_reset_isolation, run_trial  # noqa: E402
from external_benchmarks.adapters.riann_pretrained_6d import (  # noqa: E402
    TRAINING_EXPOSURE,
    RIANNPretrained6DAdapter,
    annotate_riann_result,
    default_config,
)


RATE_HZ = 100
DT = 1.0 / RATE_HZ
GRAVITY = 9.80665
INTERVAL_NS = 10_000_000


def quaternion_multiply(left, right):
    w, x, y, z = left
    a, b, c, d = right
    return np.array(
        [
            w * a - x * b - y * c - z * d,
            w * b + x * a + y * d - z * c,
            w * c - x * d + y * a + z * b,
            w * d + x * c - y * b + z * a,
        ],
        dtype=np.float64,
    )


def quaternion_rotate(quaternion, vector):
    inverse = quaternion * np.array([1.0, -1.0, -1.0, -1.0])
    return quaternion_multiply(quaternion_multiply(quaternion, np.r_[0.0, vector]), inverse)[1:]


def quaternion_geodesic_rad(left, right):
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    left = left / np.linalg.norm(left)
    right = right / np.linalg.norm(right)
    relative = quaternion_multiply(left * np.array([1.0, -1.0, -1.0, -1.0]), right)
    return 2.0 * math.atan2(np.linalg.norm(relative[1:]), abs(float(relative[0])))


def make_trial(accels, gyros, *, trial_id="riann-fixture", rate_hz=RATE_HZ):
    assert len(accels) == len(gyros) and len(accels) > 0
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
        "source_id": "riann-b5-deterministic-synthetic-fixture",
        "source_artifact_sha256": "b" * 64,
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
    tilt = np.array([math.cos(tilt_angle / 2.0), math.sin(tilt_angle / 2.0), 0.0, 0.0])
    accels, gyros = [], []
    for index in range(count):
        yaw_angle = yaw_rate * index / rate_hz
        yaw = np.array([math.cos(yaw_angle / 2.0), 0.0, 0.0, math.sin(yaw_angle / 2.0)])
        q_world_from_body = quaternion_multiply(yaw, tilt)
        q_body_from_world = q_world_from_body * np.array([1.0, -1.0, -1.0, -1.0])
        accels.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, GRAVITY)))
        gyros.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, yaw_rate)))
    return np.asarray(accels), np.asarray(gyros)


def stationary_sequence(count=160):
    return (
        np.tile([0.0, 0.0, GRAVITY], (count, 1)),
        np.zeros((count, 3), dtype=np.float64),
    )


def official_model():
    model_path = importlib.resources.files("riann").joinpath("riann.onnx")
    return RIANN(str(model_path))


@unittest.skipUnless(HAS_RIANN_RUNTIME, "install the pinned RIANN B5 reference dependencies")
class RIANNPretrainedAdapterTests(unittest.TestCase):
    def test_manifest_pins_official_causal_six_axis_model_and_exposure(self):
        manifest = RIANNPretrained6DAdapter.manifest
        self.assertEqual(manifest["adapter_id"], "official.riann")
        self.assertEqual(manifest["implementation_version"], "riann-0.2.0")
        self.assertEqual(manifest["execution_mode"], "causal_online")
        self.assertEqual(manifest["supported_sensor_sets"], ["gyro_accel_6d"])
        self.assertEqual(manifest["supported_aid_types"], [])
        self.assertEqual(manifest["source_fidelity"]["classification"], "official_unmodified")
        self.assertEqual(
            manifest["source_fidelity"]["model_sha256"],
            "9a38dc4c40dd6c31ef12558337e7affa5382476bbd594fdea3c347f10a67f3d8",
        )
        self.assertEqual(TRAINING_EXPOSURE, "BROAD_USED_IN_DEVELOPMENT")

    def test_runtime_uses_only_deterministic_single_thread_cpu_execution(self):
        adapter = RIANNPretrained6DAdapter()
        session = adapter._model.session
        options = session.get_session_options()
        self.assertEqual(session.get_providers(), ["CPUExecutionProvider"])
        self.assertEqual(options.execution_mode, ort.ExecutionMode.ORT_SEQUENTIAL)
        self.assertEqual(options.intra_op_num_threads, 1)
        self.assertEqual(options.inter_op_num_threads, 1)
        self.assertTrue(options.use_deterministic_compute)

    def test_adapter_emits_official_unit_quaternions_and_gravity_aligned_tilt(self):
        accels, gyros = tilted_yaw_sequence(1000, tilt_deg=35.0)
        bundle = run_trial(
            RIANNPretrained6DAdapter(),
            make_trial(accels, gyros, trial_id="tilted-static"),
            default_config(),
        )
        quaternions = np.asarray(
            [row["orientation"]["quaternion_wxyz"] for row in bundle["samples"]]
        )
        np.testing.assert_allclose(np.linalg.norm(quaternions, axis=1), 1.0, atol=1e-3)
        self.assertTrue(np.all(np.sum(quaternions[1:] * quaternions[:-1], axis=1) >= 0.0))
        estimated_up_world = quaternion_rotate(quaternions[-1], accels[-1])
        estimated_up_world /= np.linalg.norm(estimated_up_world)
        tilt_error = math.acos(float(np.clip(estimated_up_world[2], -1.0, 1.0)))
        self.assertLess(tilt_error, math.radians(0.2))
        self.assertEqual(bundle["samples"][-1]["orientation"]["yaw_gauge"], "unobservable_startup")

    def test_streaming_matches_official_predict_step_and_batch_within_float32_tolerance(self):
        accels, gyros = tilted_yaw_sequence(300, tilt_deg=28.0, yaw_rate=0.18)
        trial = make_trial(accels, gyros, trial_id="official-parity")
        adapter = RIANNPretrained6DAdapter()
        bundle = run_trial(adapter, trial, default_config())
        adapter_quaternions = np.asarray(
            [row["orientation"]["quaternion_wxyz"] for row in bundle["samples"]]
        )

        reference = official_model()
        reference.set_sampling_rate(RATE_HZ)
        reference_step = np.asarray(
            [
                reference.predict_step(acc.astype(np.float32), gyr.astype(np.float32)).copy()
                for acc, gyr in zip(accels, gyros)
            ]
        )
        reference_batch = reference.predict(
            accels.astype(np.float32), gyros.astype(np.float32), fs=RATE_HZ
        )
        np.testing.assert_array_equal(adapter_quaternions, reference_step)
        maximum_batch_error = max(
            quaternion_geodesic_rad(step, batch)
            for step, batch in zip(adapter_quaternions, reference_batch)
        )
        self.assertLess(maximum_batch_error, 1e-4)

    def test_chunked_stateful_steps_match_one_continuous_stream(self):
        accels, gyros = tilted_yaw_sequence(360, tilt_deg=48.0, yaw_rate=0.31)
        reference = official_model()
        whole, _ = reference.predict_sequence(accels, gyros, fs=RATE_HZ, reset_state=True)
        first, _ = reference.predict_sequence(
            accels[:120], gyros[:120], fs=RATE_HZ, reset_state=True
        )
        second, _ = reference.predict_sequence(
            accels[120:250], gyros[120:250], fs=None, reset_state=False
        )
        third, _ = reference.predict_sequence(
            accels[250:], gyros[250:], fs=None, reset_state=False
        )
        chunked = np.concatenate((first, second, third), axis=0)
        np.testing.assert_array_equal(chunked, whole)

        hidden_before_batch = reference.hidden_state.copy()
        reference.predict(accels, gyros, fs=RATE_HZ)
        np.testing.assert_array_equal(reference.hidden_state, hidden_before_batch)

    def test_official_predict_step_retains_and_reset_state_clears_gru_hidden_state(self):
        reference = official_model()
        reference.set_sampling_rate(RATE_HZ)
        initial = reference.hidden_state.copy()
        acc = np.asarray([0.0, 0.0, GRAVITY], dtype=np.float32)
        gyr = np.asarray([0.1, -0.2, 0.3], dtype=np.float32)
        reference.predict_step(acc, gyr)
        after_one = reference.hidden_state.copy()
        reference.predict_step(acc, gyr)
        after_two = reference.hidden_state.copy()
        self.assertFalse(np.array_equal(initial, after_one))
        self.assertFalse(np.array_equal(after_one, after_two))
        reference.reset_state()
        np.testing.assert_array_equal(reference.hidden_state, initial)

    def test_reset_isolates_hidden_state_and_repeated_cpu_runs_are_deterministic(self):
        target_accels, target_gyros = tilted_yaw_sequence(180, tilt_deg=31.0, yaw_rate=0.22)
        other_accels, other_gyros = tilted_yaw_sequence(220, tilt_deg=62.0, yaw_rate=-0.27)
        target = make_trial(target_accels, target_gyros, trial_id="reset-target")
        other = make_trial(other_accels, other_gyros, trial_id="reset-other")
        config = default_config()
        check_reset_isolation(RIANNPretrained6DAdapter, target, other, config)

        adapter = RIANNPretrained6DAdapter()
        first = run_trial(adapter, target, config)
        second = run_trial(adapter, target, config)
        self.assertEqual(first["samples"], second["samples"])

    def test_adapter_requires_uniform_time_and_rejects_unavailable_aids(self):
        adapter = RIANNPretrained6DAdapter()
        adapter.reset(default_config())
        adapter.step(0, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        with self.assertRaises(ContractError):
            adapter.step(INTERVAL_NS + 2, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        with self.assertRaises(ContractError):
            adapter.step(2 * INTERVAL_NS, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0), {"kind": "independent_heading"})
        with self.assertRaises(ContractError):
            adapter.reset(default_config(sampling_rate_numerator=40))
        with self.assertRaises(ContractError):
            adapter.reset({**default_config(), "timestamp_unit": "seconds"})

    def test_every_report_result_is_wrapped_with_broad_training_exposure(self):
        result = annotate_riann_result({"trial_id": "synthetic-0", "tilt_rms_rad": 0.0})
        self.assertEqual(result["training_exposure"], "BROAD_USED_IN_DEVELOPMENT")
        self.assertEqual(result["result"]["trial_id"], "synthetic-0")
        self.assertEqual(result["schema_id"], "org.marcusfunt.external_benchmarks.riann_result")


if __name__ == "__main__":
    unittest.main()
