"""Reproduce official VQF full causal 6D wrapper fidelity checks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
import vqf


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import canonical_input_sha256, canonical_json_sha256, run_trial  # noqa: E402
from external_benchmarks.adapters.vqf_full_6d import VQFFull6DAdapter  # noqa: E402


RATE_HZ = 100
DT = 1.0 / RATE_HZ
GRAVITY = 9.80665
TIMESTAMP_INTERVAL_NS = 10_000_000
CONFIG = {"sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1}, "timestamp_unit": "ns"}


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


def axis_quaternion(axis, angle):
    sine = math.sin(angle / 2.0)
    return (math.cos(angle / 2.0), *(component * sine for component in axis))


def tilted_yaw_sequence(count, yaw_rate):
    tilt = axis_quaternion((1.0, 0.0, 0.0), math.radians(35.0))
    accels, gyros = [], []
    for index in range(count):
        yaw = axis_quaternion((0.0, 0.0, 1.0), yaw_rate * index / RATE_HZ)
        q_world_from_body = quaternion_multiply(yaw, tilt)
        inverse = (q_world_from_body[0], *(-value for value in q_world_from_body[1:]))
        accels.append(quaternion_rotate(inverse, (0.0, 0.0, GRAVITY)))
        gyros.append(quaternion_rotate(inverse, (0.0, 0.0, yaw_rate)))
    return accels, gyros


def known_sequences():
    sequences = {
        "stationary": ([(0.0, 0.0, GRAVITY)] * 500, [(0.0, 0.0, 0.0)] * 500),
        "yaw_only": ([(0.0, 0.0, GRAVITY)] * 500, [(0.0, 0.0, 0.25)] * 500),
        "tilted_stationary": tilted_yaw_sequence(600, 0.0),
        "tilted_yaw": tilted_yaw_sequence(800, 0.35),
        "constant_rate": ([(0.0, 0.0, GRAVITY)] * 500, [(0.2, -0.1, 0.3)] * 500),
    }
    varying_accels, varying_gyros = [], []
    for index in range(500):
        time_s = index / RATE_HZ
        varying_gyros.append((0.1 * math.sin(time_s), -0.05 * math.cos(0.5 * time_s), 0.1 + 0.25 * time_s / 5.0))
        varying_accels.append((0.6 * math.sin(0.4 * time_s), -0.3 * math.cos(0.3 * time_s), GRAVITY + 0.2 * math.sin(0.2 * time_s)))
    sequences["slowly_varying_rate"] = varying_accels, varying_gyros

    pulse_accels, pulse_gyros = [], []
    for index in range(250):
        pulse_accels.append((1.3 if 50 <= index < 150 else 0.0, 0.0, GRAVITY))
        pulse_gyros.append((0.0, 0.0, 0.4))
    sequences["acceleration_pulse_during_rotation"] = pulse_accels, pulse_gyros
    return sequences


def trial_for(name, accels, gyros):
    samples = [
        {
            "timestamp": index * TIMESTAMP_INTERVAL_NS,
            "accel_mps2": [float(value) for value in accel],
            "gyro_rad_s": [float(value) for value in gyro],
            "valid": True,
        }
        for index, (accel, gyro) in enumerate(zip(accels, gyros))
    ]
    # The raw fixture artifact is exactly this canonical vector payload; no
    # optical truth, training data, or real sensor data is involved.
    source_sha = hashlib.sha256(
        json.dumps(samples, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": f"vqf-b3-{name}",
        "source_id": "deterministic-synthetic-vqf-fidelity-fixture",
        "source_artifact_sha256": source_sha,
        "sensor_set": "gyro_accel_6d",
        "timebase": {
            "timestamp_unit": "ns",
            "sampling_mode": "uniform",
            "nominal_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
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


def quaternion_geodesic_rad(left, right):
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    left = left / np.linalg.norm(left)
    right = right / np.linalg.norm(right)
    relative = quaternion_multiply((left[0], -left[1], -left[2], -left[3]), right)
    return 2.0 * math.atan2(math.sqrt(sum(value * value for value in relative[1:])), abs(relative[0]))


def evaluate_sequence(name, accels, gyros):
    if len(accels) != len(gyros) or not accels:
        raise ValueError(f"invalid synthetic sequence {name}")
    trial = trial_for(name, accels, gyros)
    adapter = VQFFull6DAdapter()
    output = run_trial(adapter, trial, CONFIG)
    adapter_quats = np.asarray([row["orientation"]["quaternion_wxyz"] for row in output["samples"]], dtype=np.float64)

    official_cpp = vqf.VQF(DT)
    cpp_quats, cpp_bias = [], []
    py_filter = vqf.PyVQF(DT)
    py_quats = []
    for accel, gyro in zip(accels, gyros):
        accel_array = np.asarray(accel, dtype=np.float64)
        gyro_array = np.asarray(gyro, dtype=np.float64)
        official_cpp.update(gyro_array, accel_array)
        cpp_quats.append(np.asarray(official_cpp.getQuat6D()).copy())
        bias, sigma = official_cpp.getBiasEstimate()
        cpp_bias.append((np.asarray(bias).copy(), float(sigma), bool(official_cpp.getRestDetected())))
        py_filter.update(gyro_array, accel_array)
        py_quats.append(np.asarray(py_filter.getQuat6D()).copy())
    cpp_quats = np.asarray(cpp_quats, dtype=np.float64)
    py_quats = np.asarray(py_quats, dtype=np.float64)

    official_batch = vqf.VQF(DT).updateBatch(
        np.ascontiguousarray(gyros, dtype=np.float64),
        np.ascontiguousarray(accels, dtype=np.float64),
    )
    batch_quats = np.asarray(official_batch["quat6D"], dtype=np.float64)
    adapter_cpp_error = [quaternion_geodesic_rad(a, b) for a, b in zip(adapter_quats, cpp_quats)]
    python_error = [quaternion_geodesic_rad(a, b) for a, b in zip(py_quats, cpp_quats)]
    batch_error = [quaternion_geodesic_rad(a, b) for a, b in zip(batch_quats, cpp_quats)]
    direct_bias, direct_sigma, direct_rest = cpp_bias[-1]
    adapter_diag = adapter.diagnostics()
    if not np.array_equal(adapter_quats, cpp_quats):
        raise RuntimeError(f"adapter output did not match official C++ wrapper output for {name}")

    trajectory_checks = {}
    if name in {"tilted_stationary", "tilted_yaw"}:
        q_final = cpp_quats[-1]
        estimated_up_body = quaternion_rotate((q_final[0], -q_final[1], -q_final[2], -q_final[3]), (0.0, 0.0, 1.0))
        actual_up_body = np.asarray(accels[-1], dtype=np.float64)
        actual_up_body /= np.linalg.norm(actual_up_body)
        trajectory_checks["final_gravity_tilt_error_rad"] = math.acos(
            float(np.clip(np.dot(estimated_up_body, actual_up_body), -1.0, 1.0))
        )
    if name == "tilted_yaw":
        expected_final = quaternion_multiply(axis_quaternion((0.0, 0.0, 1.0), 0.35 * (len(cpp_quats) - 1) / RATE_HZ), cpp_quats[0])
        trajectory_checks["relative_heading_integration_error_rad"] = quaternion_geodesic_rad(expected_final, cpp_quats[-1])

    return {
        "sequence_id": name,
        "sample_count": len(trial["samples"]),
        "sample_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
        "timestamp_unit": "ns",
        "source_artifact_sha256": trial["source_artifact_sha256"],
        "canonical_input_sha256": canonical_input_sha256(trial),
        "config_sha256": output["config_sha256"],
        "adapter_vs_official_cpp_streaming_max_geodesic_rad": max(adapter_cpp_error),
        "official_python_vs_official_cpp_streaming_max_geodesic_rad": max(python_error),
        "official_cpp_batch_vs_streaming_max_geodesic_rad": max(batch_error),
        "official_cpp_batch_vs_streaming_max_abs_quaternion_component": float(np.max(np.abs(batch_quats - cpp_quats))),
        "trajectory_checks": trajectory_checks,
        "last_gyroscope_bias_estimate_rad_s": [float(value) for value in direct_bias],
        "last_gyroscope_bias_std_rad_s": direct_sigma,
        "last_rest_detected": direct_rest,
        "adapter_last_gyroscope_bias_estimate_rad_s": adapter_diag["gyroscope_bias_rad_s"],
        "adapter_last_gyroscope_bias_std_rad_s": adapter_diag["gyroscope_bias_uncertainty_std_rad_s"],
        "accelerometer_bias_available": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write machine-readable JSON result to this file (stdout by default)")
    args = parser.parse_args()

    installed_vqf_version = importlib.metadata.version("vqf")
    if installed_vqf_version != "2.1.2":
        raise RuntimeError(f"expected pinned vqf==2.1.2, found {installed_vqf_version}")
    if np.__version__ != "2.0.2":
        raise RuntimeError(f"expected pinned numpy==2.0.2, found {np.__version__}")

    manifest_path = ROOT / "external_benchmarks" / "adapters" / "vqf_full_6d_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    adapter_path = ROOT / "external_benchmarks" / "adapters" / "vqf_full_6d.py"
    adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()
    if manifest["source_fidelity"]["adapter_sha256"] != adapter_sha:
        raise RuntimeError("adapter SHA-256 does not match the versioned manifest")

    sequences = [evaluate_sequence(name, accels, gyros) for name, (accels, gyros) in known_sequences().items()]
    result = {
        "report_schema": "org.marcusfunt.vqf_b3_fidelity.v1",
        "algorithm": "official VQF full causal 6D",
        "upstream_revision": manifest["source_fidelity"]["source_revision"],
        "license": manifest["source_fidelity"]["license"],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "vqf_package": installed_vqf_version,
        "adapter_sha256": adapter_sha,
        "implementation_sha256": manifest["source_fidelity"]["implementation_sha256"],
        "settings": {
            "sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
            "timestamp_interval_ns": TIMESTAMP_INTERVAL_NS,
            "all_vqf_parameters": "official defaults",
            "official_default_parameters": dict(vqf.VQF(DT).params),
            "magnetometer_supplied": False,
            "aid_supplied": False,
            "output_getter": "getQuat6D",
            "execution_mode": "causal_online",
        },
        "sequences": sequences,
        "interpretation": {
            "batch_vs_streaming": "The official C++ updateBatch path matched its per-sample update path within the recorded floating-point deltas.",
            "python_vs_cpp": "Official PyVQF and the official C++-backed VQF wrapper are separate official implementations; deltas quantify numerical fidelity only.",
            "yaw": "Six-axis yaw is startup-gauge relative; no absolute or magnetic heading was supplied.",
            "bias": "Only VQF's gyro-bias estimate, its uncertainty, and rest state are reported; VQF has no accelerometer-bias output.",
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
