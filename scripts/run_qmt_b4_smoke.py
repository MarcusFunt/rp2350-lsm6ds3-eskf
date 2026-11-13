"""Run deterministic B4 parity, reset-isolation, and causal-prefix checks."""

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
import qmt


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import canonical_input_sha256, run_trial  # noqa: E402
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
    return quaternion_multiply(quaternion_multiply(quaternion, (0.0, *vector)), inverse)[1:]


def quaternion_geodesic_rad(left, right):
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    left = left / np.linalg.norm(left)
    right = right / np.linalg.norm(right)
    relative = quaternion_multiply((left[0], -left[1], -left[2], -left[3]), right)
    return 2.0 * math.atan2(math.sqrt(sum(value * value for value in relative[1:])), abs(relative[0]))


def tilted_yaw_sequence(count, *, tilt_deg=35.0, yaw_rate=0.0):
    tilt_angle = math.radians(tilt_deg)
    tilt = (math.cos(tilt_angle / 2.0), math.sin(tilt_angle / 2.0), 0.0, 0.0)
    accels, gyros = [], []
    for index in range(count):
        yaw_angle = yaw_rate * index / RATE_HZ
        yaw = (math.cos(yaw_angle / 2.0), 0.0, 0.0, math.sin(yaw_angle / 2.0))
        q_world_from_body = quaternion_multiply(yaw, tilt)
        q_body_from_world = (q_world_from_body[0], *(-value for value in q_world_from_body[1:]))
        accels.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, GRAVITY)))
        gyros.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, yaw_rate)))
    return accels, gyros


def known_sequences():
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


def make_trial(name, accels, gyros):
    samples = [
        {
            "timestamp": index * INTERVAL_NS,
            "accel_mps2": [float(value) for value in accel],
            "gyro_rad_s": [float(value) for value in gyro],
            "valid": True,
        }
        for index, (accel, gyro) in enumerate(zip(accels, gyros))
    ]
    source_sha = hashlib.sha256(
        json.dumps(samples, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": f"qmt-b4-{name}",
        "source_id": "deterministic-synthetic-qmt-fidelity-fixture",
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


def function_batch(trial, config):
    # Rebuild both streams from the exact serialized trial payload so the
    # batch and online paths demonstrably consume the same sample values.
    accels = [sample["accel_mps2"] for sample in trial["samples"]]
    gyros = [sample["gyro_rad_s"] for sample in trial["samples"]]
    parameters = dict(config["parameters"])
    parameters["Ts"] = config["sampling_rate_hz"]["denominator"] / config["sampling_rate_hz"]["numerator"]
    parameters["initQuat"] = np.asarray(parameters["initQuat"], dtype=np.float64)
    parameters["initBias"] = np.asarray(parameters["initBias"], dtype=np.float64)
    return qmt.oriEstIMU(
        np.ascontiguousarray(gyros, dtype=np.float64),
        np.ascontiguousarray(accels, dtype=np.float64),
        mag=None,
        params=parameters,
    )


def compare_sequence(name, accels, gyros, config):
    trial = make_trial(name, accels, gyros)
    adapter = SeelOriEstIMU6DAdapter()
    bundle = run_trial(adapter, trial, config)
    streaming = np.asarray([row["orientation"]["quaternion_wxyz"] for row in bundle["samples"]], dtype=np.float64)
    batch = np.asarray(function_batch(trial, config), dtype=np.float64)
    geodesic = [quaternion_geodesic_rad(a, b) for a, b in zip(streaming, batch)]
    component_delta = float(np.max(np.abs(streaming - batch)))
    if component_delta != 0.0:
        raise RuntimeError(f"official batch and streaming outputs differ for {name}")

    checks = {}
    if name == "tilted_stationary":
        angle = math.radians(35.0)
        q_truth = (math.cos(angle / 2.0), math.sin(angle / 2.0), 0.0, 0.0)
        checks["final_geodesic_to_synthetic_attitude_rad"] = quaternion_geodesic_rad(streaming[-1], q_truth)
        up_world = quaternion_rotate(streaming[-1], accels[-1])
        up_world = np.asarray(up_world, dtype=np.float64) / np.linalg.norm(up_world)
        checks["final_gravity_axis_error_rad"] = math.acos(float(np.clip(up_world[2], -1.0, 1.0)))
    if name == "yaw_only":
        expected_angle = gyros[0][2] * len(gyros) * DT  # one fixed-Ts update per input, including sample zero
        expected = (math.cos(expected_angle / 2.0), 0.0, 0.0, math.sin(expected_angle / 2.0))
        checks["yaw_integration_error_rad"] = quaternion_geodesic_rad(streaming[-1], expected)

    return {
        "sequence_id": name,
        "sample_count": len(trial["samples"]),
        "sample_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
        "timestamp_unit": "ns",
        "source_artifact_sha256": trial["source_artifact_sha256"],
        "canonical_input_sha256": canonical_input_sha256(trial),
        "batch_input_is_reconstructed_from_same_trial": True,
        "config_sha256": bundle["config_sha256"],
        "streaming_vs_batch_max_geodesic_rad": max(geodesic),
        "streaming_vs_batch_max_abs_quaternion_component": component_delta,
        "streaming_quaternion_max_norm_error": float(np.max(np.abs(np.linalg.norm(streaming, axis=1) - 1.0))),
        "streaming_min_scalar_component": float(np.min(streaming[:, 0])),
        "trajectory_checks": checks,
    }


def reset_counterexample(config):
    zero_mag = np.zeros(3, dtype=np.float64)
    previous_accels = [(5.0, 0.0, GRAVITY)] * 100
    previous_gyros = [(0.4, -0.1, 0.2)] * 100
    target_accels, target_gyros = tilted_yaw_sequence(100, tilt_deg=60.0)

    def run_block(block, accels, gyros):
        return np.asarray([
            block.step(np.asarray(gyro, dtype=np.float64), np.asarray(accel, dtype=np.float64), zero_mag)
            for accel, gyro in zip(accels, gyros)
        ])

    reused = qmt.OriEstIMUBlock(DT)
    reused.command(["reset"])
    run_block(reused, previous_accels, previous_gyros)
    reused.command(["reset"])
    after_command_reset = run_block(reused, target_accels, target_gyros)

    fresh = qmt.OriEstIMUBlock(DT)
    fresh.command(["reset"])
    fresh_target = run_block(fresh, target_accels, target_gyros)
    max_reset_difference = max(quaternion_geodesic_rad(a, b) for a, b in zip(after_command_reset, fresh_target))

    target_trial = make_trial("reset-target", target_accels, target_gyros)
    other_trial = make_trial("reset-interleaved", previous_accels, previous_gyros)
    fresh_adapter_result = run_trial(SeelOriEstIMU6DAdapter(), target_trial, config)
    after_other = SeelOriEstIMU6DAdapter()
    run_trial(after_other, other_trial, config)
    reused_adapter_result = run_trial(after_other, target_trial, config)
    adapter_delta = float(np.max(np.abs(
        np.asarray([row["orientation"]["quaternion_wxyz"] for row in fresh_adapter_result["samples"]])
        - np.asarray([row["orientation"]["quaternion_wxyz"] for row in reused_adapter_result["samples"]])
    )))
    return {
        "preceding_trial_samples": len(previous_accels),
        "target_trial_samples": len(target_accels),
        "target_tilt_deg": 60.0,
        "upstream_command_reset_vs_fresh_block_max_geodesic_rad": max_reset_difference,
        "adapter_recreated_reset_vs_fresh_max_abs_quaternion_component": adapter_delta,
        "adapter_trial_reset_isolation_pass": adapter_delta == 0.0,
    }


def causal_prefix_check(config):
    accels, gyros = tilted_yaw_sequence(800, tilt_deg=35.0, yaw_rate=0.35)
    full_trial = make_trial("prefix-full", accels, gyros)
    prefix_trial = make_trial("prefix-short", accels[:200], gyros[:200])
    full = run_trial(SeelOriEstIMU6DAdapter(), full_trial, config)
    prefix = run_trial(SeelOriEstIMU6DAdapter(), prefix_trial, config)
    return full["samples"][:200] == prefix["samples"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "external_benchmarks" / "qmt_b4_fidelity.json",
        help="write machine-readable fidelity evidence here",
    )
    args = parser.parse_args()

    qmt_version = importlib.metadata.version("qmt")
    numpy_version = np.__version__
    vqf_version = importlib.metadata.version("vqf")
    python_version = platform.python_version()
    if (python_version, qmt_version, numpy_version, vqf_version) != (
        "3.11.4", "0.2.4", "1.26.4", "2.1.2"
    ):
        raise RuntimeError(
            "expected pinned Python 3.11.4, qmt==0.2.4, numpy==1.26.4 and vqf==2.1.2; "
            f"found {python_version}, {qmt_version}, {numpy_version}, {vqf_version}"
        )

    manifest_path = ROOT / "external_benchmarks" / "adapters" / "qmt_oriestimu_6d_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance_path = ROOT / "external_benchmarks" / "references" / "qmt_oriestimu_v0.2.4_provenance_lock.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if manifest["source_fidelity"]["source_revision"] != provenance["upstream_commit"]:
        raise RuntimeError("adapter manifest source revision does not match the provenance lock")
    if manifest["source_fidelity"]["implementation_sha256"] != provenance["distribution"]["official_source_distribution_sha256"]:
        raise RuntimeError("adapter implementation digest does not match the official source distribution lock")
    adapter_path = ROOT / "external_benchmarks" / "adapters" / "qmt_oriestimu_6d.py"
    adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()
    if manifest["source_fidelity"]["adapter_sha256"] != adapter_sha:
        raise RuntimeError("adapter SHA-256 does not match the versioned manifest")

    config = default_config()
    sequence_results = [
        compare_sequence(name, accels, gyros, config)
        for name, (accels, gyros) in known_sequences().items()
    ]
    result = {
        "report_schema": "org.marcusfunt.qmt_b4_fidelity.v1",
        "algorithm": "official qmt Seel/Ruppin OriEstIMU, causal 6D",
        "upstream_revision": manifest["source_fidelity"]["source_revision"],
        "license": manifest["source_fidelity"]["license"],
        "python": python_version,
        "numpy": numpy_version,
        "scipy": importlib.metadata.version("scipy"),
        "qmt_package": qmt_version,
        "vqf_dependency": vqf_version,
        "adapter_sha256": adapter_sha,
        "implementation_sha256": manifest["source_fidelity"]["implementation_sha256"],
        "official_source_distribution_sha256": provenance["distribution"]["official_source_distribution_sha256"],
        "validated_wheel_sha256": provenance["distribution"]["validated_wheel"]["sha256"],
        "parameter_choice": {
            "selected_set": "OriEstIMUBlock documented constructor defaults; passed explicitly to qmt.oriEstIMU for batch parity",
            "Ts_seconds": DT,
            "tauAcc_seconds": 2.0,
            "tauMag_seconds_unused_in_6d": 2.0,
            "zeta": 0.0,
            "accRating": 1.0,
            "initQuat_wxyz": [1.0, 0.0, 0.0, 0.0],
            "initBias_rad_s": [0.0, 0.0, 0.0],
            "official_function_defaults_differ": {"tauAcc": 1.0, "tauMag": 3.0, "zeta": 0.0, "accRating": 1.0, "initQuat": None, "initBias": None},
            "tuned_parameters_used": False,
        },
        "input_profile": {
            "sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
            "timestamp_interval_ns": INTERVAL_NS,
            "gyro_units": "rad/s",
            "accelerometer_units": "m/s^2 specific force",
            "magnetometer_supplied": False,
            "aid_supplied": False,
            "execution_mode": "causal_online",
        },
        "causal_prefix_match": causal_prefix_check(config),
        "reset_semantics": reset_counterexample(config),
        "sequences": sequence_results,
        "interpretation": {
            "batch_and_streaming": "The qmt batch function and official streaming block call the same upstream C++ step; batch receives mag=None and streaming uses the documented zero-vector no-mag sentinel.",
            "initial_state": "The official streaming block reset command sets identity quaternion and zero gyro bias. A fresh block is created per trial because resetEstimation does not clear the C++ startup counter or accelerometer rating window.",
            "quaternion": "Scalar-first orientation of the sensor frame in ENU; six-axis yaw remains startup-gauge relative.",
            "bias": "zeta=0 is the documented default and disables gyro-bias adaptation; qmt's diagnostic bias is therefore the zero initialization for this parameterization.",
            "scope": "Synthetic fidelity and API checks only; no BROAD, external performance score, estimator tuning, or hardware run.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "sequence_count": len(sequence_results),
        "max_stream_batch_geodesic_rad": max(row["streaming_vs_batch_max_geodesic_rad"] for row in sequence_results),
        "max_stream_batch_component_delta": max(row["streaming_vs_batch_max_abs_quaternion_component"] for row in sequence_results),
        "upstream_reset_counterexample_rad": result["reset_semantics"]["upstream_command_reset_vs_fresh_block_max_geodesic_rad"],
        "adapter_reset_isolation_pass": result["reset_semantics"]["adapter_trial_reset_isolation_pass"],
        "causal_prefix_match": result["causal_prefix_match"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
