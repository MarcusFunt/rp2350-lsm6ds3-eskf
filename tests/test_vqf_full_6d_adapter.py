"""Official VQF causal 6D adapter conformance and fidelity tests.

Run with the pinned optional dependencies from
``external_benchmarks/requirements-vqf-b3.txt`` installed.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
    import vqf
except ModuleNotFoundError:  # Optional B3 reference dependency.
    np = None
    vqf = None
    HAS_PINNED_VQF = False
else:
    HAS_PINNED_VQF = True


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import ContractError, check_reset_isolation, run_trial  # noqa: E402
from external_benchmarks.adapters.vqf_full_6d import VQFFull6DAdapter  # noqa: E402


RATE_HZ = 100
DT = 1.0 / RATE_HZ
TIMESTAMP_STEP_NS = 10_000_000
GRAVITY = 9.80665
CONFIG = {"sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1}, "timestamp_unit": "ns"}


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_rotate(q, vector):
    conjugate = (q[0], -q[1], -q[2], -q[3])
    rotated = quat_multiply(quat_multiply(q, (0.0, *vector)), conjugate)
    return rotated[1:]


def q_axis(axis, angle):
    scale = math.sin(angle / 2.0)
    return (math.cos(angle / 2.0), *(component * scale for component in axis))


def make_trial(accels, gyros, *, trial_id="vqf-fixture", rate_hz=RATE_HZ):
    assert len(accels) == len(gyros) and accels
    interval = round(1_000_000_000 / rate_hz)
    samples = [
        {
            "timestamp": index * interval,
            "accel_mps2": list(accel),
            "gyro_rad_s": list(gyro),
            "valid": True,
        }
        for index, (accel, gyro) in enumerate(zip(accels, gyros))
    ]
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": trial_id,
        "source_id": "vqf-deterministic-fixture",
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


def stationary_trial(count=100, *, accel=(0.0, 0.0, GRAVITY), gyro=(0.0, 0.0, 0.0), trial_id="stationary"):
    return make_trial([accel] * count, [gyro] * count, trial_id=trial_id)


def run_direct_cpp(accels, gyros, *, rate_hz=RATE_HZ):
    direct = vqf.VQF(1.0 / rate_hz)
    outputs = []
    diagnostics = []
    for accel, gyro in zip(accels, gyros):
        direct.update(np.asarray(gyro, dtype=np.float64), np.asarray(accel, dtype=np.float64))
        outputs.append(np.asarray(direct.getQuat6D()).copy())
        bias, sigma = direct.getBiasEstimate()
        diagnostics.append((np.asarray(bias).copy(), float(sigma), bool(direct.getRestDetected())))
    return np.asarray(outputs), diagnostics


def tilted_yaw_sequence(count=600, *, rate_hz=RATE_HZ, tilt_x_deg=35.0, yaw_rate=0.0):
    """Synthesize gravity and gyro in body axes for a world-vertical yaw."""
    tilt = q_axis((1.0, 0.0, 0.0), math.radians(tilt_x_deg))
    accels, gyros = [], []
    for index in range(count):
        yaw = q_axis((0.0, 0.0, 1.0), yaw_rate * index / rate_hz)
        q_world_from_body = quat_multiply(yaw, tilt)
        accels.append(quat_rotate((q_world_from_body[0], *(-x for x in q_world_from_body[1:])), (0.0, 0.0, GRAVITY)))
        gyro_body = quat_rotate((q_world_from_body[0], *(-x for x in q_world_from_body[1:])), (0.0, 0.0, yaw_rate))
        gyros.append(gyro_body)
    return accels, gyros


@unittest.skipUnless(HAS_PINNED_VQF, "install external_benchmarks/requirements-vqf-b3.txt")
class VQFFull6DAdapterTests(unittest.TestCase):
    def test_manifest_pins_official_causal_6d_only_variant(self):
        manifest = VQFFull6DAdapter.manifest
        self.assertEqual(manifest["adapter_id"], "official.vqf")
        self.assertEqual(manifest["variant_id"], "vqf_full_6d_causal_v2.1.2")
        self.assertEqual(manifest["execution_mode"], "causal_online")
        self.assertEqual(manifest["supported_sensor_sets"], ["gyro_accel_6d"])
        self.assertEqual(manifest["supported_aid_types"], [])
        self.assertEqual(manifest["source_fidelity"]["classification"], "official_unmodified")
        self.assertEqual(manifest["output_convention"]["rotation_direction"], "body_to_world")

    def test_common_runner_produces_valid_stationary_quaternion_and_no_bias_claim(self):
        trial = stationary_trial()
        adapter = VQFFull6DAdapter()
        result = run_trial(adapter, trial, CONFIG)
        self.assertEqual(result["sample_count"], len(trial["samples"]))
        self.assertTrue(all(row["orientation_valid"] for row in result["samples"]))
        self.assertTrue(all("bias" not in row for row in result["samples"]))
        q = np.asarray(result["samples"][-1]["orientation"]["quaternion_wxyz"])
        np.testing.assert_allclose(q, (1.0, 0.0, 0.0, 0.0), atol=1e-12)
        diagnostics = adapter.diagnostics()
        self.assertIn("gyroscope_bias_rad_s", diagnostics)
        self.assertIn("gyroscope_bias_uncertainty_std_rad_s", diagnostics)
        self.assertNotIn("accelerometer_bias_mps2", diagnostics)

    def test_step_is_exactly_the_official_get_quat_6d_result(self):
        accels = [(0.0, 0.0, GRAVITY)] * 80
        gyros = [(0.01, -0.03, 0.2)] * 80
        trial = make_trial(accels, gyros)
        result = run_trial(VQFFull6DAdapter(), trial, CONFIG)
        direct, _ = run_direct_cpp(accels, gyros)
        observed = np.asarray([row["orientation"]["quaternion_wxyz"] for row in result["samples"]])
        np.testing.assert_array_equal(observed, direct)

    def test_aid_is_rejected_instead_of_using_heading_or_magnetometer(self):
        trial = stationary_trial(count=3)
        trial["samples"][1]["aid"] = {
            "kind": "independent_heading",
            "value_rad": 0.3,
            "units": "rad",
            "source_id": "independent-heading-fixture",
            "reference_frame": "ENU",
            "independence": "independent_of_imu",
        }
        with self.assertRaises(ContractError):
            run_trial(VQFFull6DAdapter(), trial, CONFIG)

    def test_reset_reinitializes_rates_and_prevents_inter_trial_state_leakage(self):
        adapter = VQFFull6DAdapter()
        first = stationary_trial(count=4)
        run_trial(adapter, first, CONFIG)
        second_rate_config = {"sampling_rate_hz": {"numerator": 200, "denominator": 1}, "timestamp_unit": "ns"}
        second = make_trial([(0.0, 0.0, GRAVITY)] * 5, [(0.0, 0.0, 0.1)] * 5, rate_hz=200)
        run_trial(adapter, second, second_rate_config)
        with self.assertRaises(ContractError):
            adapter.step(50_000_000, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        interleaved = make_trial(
            [(0.0, 0.0, GRAVITY)] * 5,
            [(0.0, 0.0, 0.1)] * 5,
            trial_id="interleaved",
            rate_hz=RATE_HZ,
        )
        check_reset_isolation(VQFFull6DAdapter, stationary_trial(7, trial_id="target"), interleaved, CONFIG)

    def test_config_and_timestamp_contract_is_strict(self):
        adapter = VQFFull6DAdapter()
        with self.assertRaises(ContractError):
            adapter.reset({"sampling_rate_hz": {"numerator": 0, "denominator": 1}, "timestamp_unit": "ns"})
        with self.assertRaises(ContractError):
            adapter.reset({**CONFIG, "mag_enabled": True})
        adapter.reset(CONFIG)
        adapter.step(0, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        with self.assertRaises(ContractError):
            adapter.step(TIMESTAMP_STEP_NS + 2, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))
        with self.assertRaises(ContractError):
            adapter.reset({"sampling_rate_hz": {"numerator": 10**12, "denominator": 1}, "timestamp_unit": "ns"})
        with self.assertRaises(ContractError):
            adapter.step(TIMESTAMP_STEP_NS * 2, (0.0, 0.0, GRAVITY), (0.0, 0.0, 0.0))

    def test_tilted_stationary_sequence_converges_to_gravity_without_heading_claim(self):
        accels, gyros = tilted_yaw_sequence()
        trial = make_trial(accels, gyros, trial_id="tilted-static")
        result = run_trial(VQFFull6DAdapter(), trial, CONFIG)
        q = np.asarray(result["samples"][-1]["orientation"]["quaternion_wxyz"])
        estimated_up_body = quat_rotate((q[0], *(-q[1:])), (0.0, 0.0, 1.0))
        actual_up_body = np.asarray(accels[-1]) / GRAVITY
        tilt_error = math.acos(float(np.clip(np.dot(estimated_up_body, actual_up_body), -1.0, 1.0)))
        self.assertLess(tilt_error, math.radians(1.0))
        self.assertEqual(result["samples"][-1]["orientation"]["yaw_gauge"], "unobservable_startup")

    def test_world_vertical_yaw_preserves_tilt_and_integrates_relative_heading(self):
        yaw_rate = 0.35
        accels, gyros = tilted_yaw_sequence(count=800, yaw_rate=yaw_rate)
        trial = make_trial(accels, gyros, trial_id="tilted-world-yaw")
        result = run_trial(VQFFull6DAdapter(), trial, CONFIG)
        quats = np.asarray([row["orientation"]["quaternion_wxyz"] for row in result["samples"]])
        up_body = np.asarray([quat_rotate((q[0], *(-q[1:])), (0.0, 0.0, 1.0)) for q in quats])
        observed_up = up_body[-1]
        actual_up = np.asarray(accels[-1]) / GRAVITY
        tilt_error = math.acos(float(np.clip(np.dot(observed_up, actual_up), -1.0, 1.0)))
        self.assertLess(tilt_error, math.radians(2.0))
        expected_final = quat_multiply(q_axis((0.0, 0.0, 1.0), yaw_rate * (len(quats) - 1) / RATE_HZ), quats[0])
        relative = quat_multiply(
            (expected_final[0], -expected_final[1], -expected_final[2], -expected_final[3]),
            quats[-1],
        )
        heading_integration_error = 2.0 * math.atan2(math.sqrt(sum(value * value for value in relative[1:])), abs(relative[0]))
        self.assertLess(heading_integration_error, math.radians(0.02))
        # 6D VQF has no absolute yaw reference; the gauge remains startup-relative.
        self.assertTrue(all(row["orientation"]["yaw_gauge"] == "unobservable_startup" for row in result["samples"]))

    def test_acceleration_and_constant_rotation_keep_outputs_finite_and_unit(self):
        count = 250
        accels, gyros = [], []
        for index in range(count):
            # Sustained horizontal specific-force disturbance plus constant body z rotation.
            accels.append((1.3 if 50 <= index < 150 else 0.0, 0.0, GRAVITY))
            gyros.append((0.0, 0.0, 0.4))
        result = run_trial(VQFFull6DAdapter(), make_trial(accels, gyros, trial_id="rotation-accel"), CONFIG)
        quats = np.asarray([row["orientation"]["quaternion_wxyz"] for row in result["samples"]])
        self.assertTrue(np.isfinite(quats).all())
        np.testing.assert_allclose(np.linalg.norm(quats, axis=1), 1.0, atol=1e-12)

    def test_cpp_streaming_matches_official_python_streaming(self):
        scenarios = {
            "stationary": ([(0.0, 0.0, GRAVITY)] * 500, [(0.0, 0.0, 0.0)] * 500),
            "yaw_only": ([(0.0, 0.0, GRAVITY)] * 500, [(0.0, 0.0, 0.25)] * 500),
            "tilted_yaw": tilted_yaw_sequence(count=800, yaw_rate=0.35),
            "constant_rate": ([(0.0, 0.0, GRAVITY)] * 500, [(0.2, -0.1, 0.3)] * 500),
        }
        varying_accels, varying_gyros = [], []
        for index in range(500):
            time_s = index / RATE_HZ
            varying_gyros.append((0.1 * math.sin(time_s), -0.05 * math.cos(0.5 * time_s), 0.1 + 0.25 * time_s / 5.0))
            varying_accels.append((0.6 * math.sin(0.4 * time_s), -0.3 * math.cos(0.3 * time_s), GRAVITY + 0.2 * math.sin(0.2 * time_s)))
        scenarios["slowly_varying_rate"] = (varying_accels, varying_gyros)

        for name, (accels, gyros) in scenarios.items():
            with self.subTest(scenario=name):
                cpp, _ = run_direct_cpp(accels, gyros)
                py = vqf.PyVQF(DT)
                python = []
                for accel, gyro in zip(accels, gyros):
                    py.update(np.asarray(gyro), np.asarray(accel))
                    python.append(np.asarray(py.getQuat6D()).copy())
                python = np.asarray(python)
                dot = np.abs(np.sum(cpp * python, axis=1))
                geodesic = 2.0 * np.arctan2(np.sqrt(np.maximum(0.0, 1.0 - dot * dot)), np.clip(dot, 0.0, 1.0))
                self.assertLess(float(np.max(geodesic)), 2e-6)

    def test_cpp_batch_matches_its_streaming_update(self):
        accels, gyros = tilted_yaw_sequence(count=300, yaw_rate=0.17)
        streaming, _ = run_direct_cpp(accels, gyros)
        batch_filter = vqf.VQF(DT)
        batch = batch_filter.updateBatch(
            np.ascontiguousarray(gyros, dtype=np.float64),
            np.ascontiguousarray(accels, dtype=np.float64),
        )
        batch_q = np.asarray(batch["quat6D"])
        dot = np.abs(np.sum(streaming * batch_q, axis=1))
        geodesic = 2.0 * np.arccos(np.clip(dot, -1.0, 1.0))
        self.assertLessEqual(float(np.max(geodesic)), 1e-7)

    def test_offline_variant_is_not_used_by_the_online_adapter(self):
        self.assertIsNotNone(vqf.offlineVQF)
        self.assertEqual(VQFFull6DAdapter.manifest["execution_mode"], "causal_online")
        self.assertFalse(hasattr(VQFFull6DAdapter, "offlineVQF"))


if __name__ == "__main__":
    unittest.main()
