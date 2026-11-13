"""Run deterministic RIANN source, model, causality, reset, and runtime checks."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from riann import RIANN, __version__ as RIANN_VERSION


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from external_benchmarks.api import canonical_input_sha256, run_trial  # noqa: E402
from external_benchmarks.adapters.riann_pretrained_6d import (  # noqa: E402
    MODEL_SHA256,
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
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


def quaternion_rotate(quaternion, vector):
    inverse = (quaternion[0], *(-value for value in quaternion[1:]))
    return quaternion_multiply(
        quaternion_multiply(quaternion, (0.0, *vector)), inverse
    )[1:]


def quaternion_geodesic_rad(left, right):
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    left /= np.linalg.norm(left)
    right /= np.linalg.norm(right)
    relative = quaternion_multiply(
        (left[0], *(-value for value in left[1:])), right
    )
    return 2.0 * math.atan2(
        math.sqrt(sum(value * value for value in relative[1:])), abs(relative[0])
    )


def tilted_yaw_sequence(count, *, tilt_deg=35.0, yaw_rate=0.0):
    angle = math.radians(tilt_deg)
    tilt = (math.cos(angle / 2.0), math.sin(angle / 2.0), 0.0, 0.0)
    accels, gyros = [], []
    for index in range(count):
        yaw_angle = yaw_rate * index / RATE_HZ
        yaw = (math.cos(yaw_angle / 2.0), 0.0, 0.0, math.sin(yaw_angle / 2.0))
        q_world_from_body = quaternion_multiply(yaw, tilt)
        q_body_from_world = (q_world_from_body[0], *(-v for v in q_world_from_body[1:]))
        accels.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, GRAVITY)))
        gyros.append(quaternion_rotate(q_body_from_world, (0.0, 0.0, yaw_rate)))
    return accels, gyros


def known_sequences():
    sequences = {
        "stationary": (
            [(0.0, 0.0, GRAVITY)] * 300,
            [(0.0, 0.0, 0.0)] * 300,
        ),
        "yaw_only": (
            [(0.0, 0.0, GRAVITY)] * 300,
            [(0.0, 0.0, 0.25)] * 300,
        ),
        "tilted_stationary": tilted_yaw_sequence(1000, tilt_deg=35.0),
        "tilted_world_yaw": tilted_yaw_sequence(800, tilt_deg=35.0, yaw_rate=0.35),
        "constant_rotation": (
            [(0.0, 0.0, GRAVITY)] * 400,
            [(0.2, -0.1, 0.3)] * 400,
        ),
    }
    varying_accels, varying_gyros = [], []
    for index in range(500):
        time_s = index / RATE_HZ
        varying_gyros.append(
            (0.1 * math.sin(time_s), -0.05 * math.cos(0.5 * time_s), 0.1 + 0.25 * time_s / 5.0)
        )
        varying_accels.append(
            (0.6 * math.sin(0.4 * time_s), -0.3 * math.cos(0.3 * time_s), GRAVITY + 0.2 * math.sin(0.2 * time_s))
        )
    sequences["slowly_varying_rate"] = varying_accels, varying_gyros
    pulse_accels, pulse_gyros = [], []
    for index in range(250):
        pulse_accels.append((2.5 if 40 <= index < 120 else 0.0, 0.0, GRAVITY))
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
        "trial_id": f"riann-b5-{name}",
        "source_id": "deterministic-synthetic-riann-b5-fixture",
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


def create_official_cpu_model(model_path):
    model = RIANN(str(model_path))
    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.use_deterministic_compute = True
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    model.session = ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    return model


def compare_sequence(name, accels, gyros, config, batch_model):
    trial = make_trial(name, accels, gyros)
    output = run_trial(RIANNPretrained6DAdapter(), trial, config)
    streaming = np.asarray(
        [row["orientation"]["quaternion_wxyz"] for row in output["samples"]], dtype=np.float64
    )
    batch_accels = np.asarray([row["accel_mps2"] for row in trial["samples"]], dtype=np.float32)
    batch_gyros = np.asarray([row["gyro_rad_s"] for row in trial["samples"]], dtype=np.float32)
    batch = batch_model.predict(batch_accels, batch_gyros, fs=RATE_HZ)
    geodesic = [quaternion_geodesic_rad(a, b) for a, b in zip(streaming, batch)]
    maximum_component_delta = float(np.max(np.abs(streaming - batch)))
    norm_error = float(np.max(np.abs(np.linalg.norm(streaming, axis=1) - 1.0)))
    sign_jumps = int(np.count_nonzero(np.sum(streaming[1:] * streaming[:-1], axis=1) < 0.0))
    checks = {}
    if name == "tilted_stationary":
        up_world = quaternion_rotate(streaming[-1], batch_accels[-1])
        up_world /= np.linalg.norm(up_world)
        checks["final_gravity_axis_error_rad"] = math.acos(float(np.clip(up_world[2], -1.0, 1.0)))
    return {
        "training_exposure": TRAINING_EXPOSURE,
        "trial_id": trial["trial_id"],
        "sequence_id": name,
        "sample_count": len(trial["samples"]),
        "sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
        "timestamp_unit": "ns",
        "source_artifact_sha256": trial["source_artifact_sha256"],
        "canonical_input_sha256": canonical_input_sha256(trial),
        "config_sha256": output["config_sha256"],
        "same_trial_values_used_for_batch": True,
        "official_batch_vs_streaming_max_geodesic_rad": max(geodesic),
        "official_batch_vs_streaming_max_abs_component": maximum_component_delta,
        "streaming_max_quaternion_norm_error": norm_error,
        "streaming_signed_quaternion_jumps": sign_jumps,
        "trajectory_checks": checks,
    }


def streaming_chunk_checks(config):
    accels, gyros = tilted_yaw_sequence(900, tilt_deg=42.0, yaw_rate=0.29)
    model_resource = importlib.resources.files("riann").joinpath("riann.onnx")
    with importlib.resources.as_file(model_resource) as model_path:
        model = create_official_cpu_model(model_path)
        whole, _ = model.predict_sequence(
            np.asarray(accels, dtype=np.float32), np.asarray(gyros, dtype=np.float32), fs=RATE_HZ
        )
        chunks = []
        ranges = ((0, 211), (211, 580), (580, len(accels)))
        for chunk_index, (start, stop) in enumerate(ranges):
            chunk, _ = model.predict_sequence(
                np.asarray(accels[start:stop], dtype=np.float32),
                np.asarray(gyros[start:stop], dtype=np.float32),
                fs=RATE_HZ if chunk_index == 0 else None,
                reset_state=chunk_index == 0,
            )
            chunks.append(chunk)
        chunked = np.concatenate(chunks, axis=0)
        full_trial = make_trial("prefix-full", accels, gyros)
        prefix_trial = make_trial("prefix-short", accels[:211], gyros[:211])
        full_adapter = run_trial(RIANNPretrained6DAdapter(), full_trial, config)
        prefix_adapter = run_trial(RIANNPretrained6DAdapter(), prefix_trial, config)
        prefix_match = full_adapter["samples"][:211] == prefix_adapter["samples"]
    return {
        "stateful_chunks_vs_single_stream_max_abs_component": float(np.max(np.abs(chunked - whole))),
        "causal_prefix_211_of_900_exact_match": prefix_match,
        "training_exposure": TRAINING_EXPOSURE,
    }


def reset_and_determinism_checks(config):
    target_accels, target_gyros = tilted_yaw_sequence(240, tilt_deg=27.0, yaw_rate=0.16)
    other_accels, other_gyros = tilted_yaw_sequence(200, tilt_deg=58.0, yaw_rate=-0.23)
    target = make_trial("reset-target", target_accels, target_gyros)
    other = make_trial("reset-other", other_accels, other_gyros)
    adapter = RIANNPretrained6DAdapter()
    first = run_trial(adapter, target, config)
    repeat = run_trial(adapter, target, config)
    interleaved = RIANNPretrained6DAdapter()
    run_trial(interleaved, other, config)
    after_other = run_trial(interleaved, target, config)
    return {
        "repeated_after_reset_exact_match": first["samples"] == repeat["samples"],
        "interleaved_reset_exact_match": first["samples"] == after_other["samples"],
        "training_exposure": TRAINING_EXPOSURE,
    }


def runtime_measurements(config, model_path, warmup_samples=100, measured_samples=1500):
    adapter_started = time.perf_counter_ns()
    adapter = RIANNPretrained6DAdapter()
    initialization_ms = (time.perf_counter_ns() - adapter_started) / 1e6
    adapter.reset(config)
    accel = (0.0, 0.0, GRAVITY)
    gyro = (0.13, -0.07, 0.21)
    for index in range(warmup_samples):
        adapter.step(index * INTERVAL_NS, accel, gyro)
    per_step_ns = []
    start_index = warmup_samples
    for index in range(start_index, start_index + measured_samples):
        start_ns = time.perf_counter_ns()
        adapter.step(index * INTERVAL_NS, accel, gyro)
        per_step_ns.append(time.perf_counter_ns() - start_ns)

    model = create_official_cpu_model(model_path)
    accels = np.tile(np.asarray(accel, dtype=np.float32), (measured_samples, 1))
    gyros = np.tile(np.asarray(gyro, dtype=np.float32), (measured_samples, 1))
    model.predict(accels[:warmup_samples], gyros[:warmup_samples], fs=RATE_HZ)
    batch_ms = []
    for _ in range(5):
        start_ns = time.perf_counter_ns()
        model.predict(accels, gyros, fs=RATE_HZ)
        batch_ms.append((time.perf_counter_ns() - start_ns) / 1e6)

    per_step_us = np.asarray(per_step_ns, dtype=np.float64) / 1e3
    return {
        "host_platform": platform.platform(),
        "host_processor": platform.processor(),
        "onnx_providers": adapter._model.session.get_providers(),
        "adapter_initialization_ms_including_two_session_constructions": initialization_ms,
        "per_step": {
            "warmup_samples_excluded": warmup_samples,
            "measured_samples": measured_samples,
            "median_us": float(np.median(per_step_us)),
            "p95_us": float(np.percentile(per_step_us, 95)),
            "maximum_us": float(np.max(per_step_us)),
        },
        "official_batch_predict": {
            "sequence_samples": measured_samples,
            "repeats": len(batch_ms),
            "median_total_ms": float(np.median(batch_ms)),
            "median_us_per_sample": float(np.median(batch_ms) * 1000.0 / measured_samples),
        },
        "scope": "Desktop CPU timing only; not RP2350 latency or memory qualification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "external_benchmarks" / "riann_b5_smoke.json",
        help="write machine-readable smoke evidence here",
    )
    args = parser.parse_args()

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
        "riann": RIANN_VERSION,
    }
    expected_versions = {
        "python": "3.11.4",
        "numpy": "2.3.2",
        "onnxruntime": "1.22.1",
        "riann": "0.2.0",
    }
    if versions != expected_versions:
        raise RuntimeError(f"expected pinned runtime {expected_versions}, found {versions}")

    adapter_path = ROOT / "external_benchmarks" / "adapters" / "riann_pretrained_6d.py"
    manifest_path = ROOT / "external_benchmarks" / "adapters" / "riann_pretrained_6d_manifest_v1.json"
    lock_path = ROOT / "external_benchmarks" / "references" / "riann_b5_provenance_lock.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()
    if manifest["source_fidelity"]["adapter_sha256"] != adapter_sha:
        raise RuntimeError("adapter source SHA-256 does not match its manifest")
    if manifest["source_fidelity"]["model_sha256"] != MODEL_SHA256:
        raise RuntimeError("adapter manifest model SHA-256 does not match its pinned model")
    if lock["upstream_commit"] != manifest["source_fidelity"]["source_revision"]:
        raise RuntimeError("manifest source revision does not match the provenance lock")
    if lock["model"]["sha256"] != MODEL_SHA256:
        raise RuntimeError("model digest does not match the provenance lock")
    model_resource = importlib.resources.files("riann").joinpath("riann.onnx")
    if not model_resource.is_file():
        raise RuntimeError("official RIANN package model file is missing")
    with importlib.resources.as_file(model_resource) as model_path:
        model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if model_sha != MODEL_SHA256:
            raise RuntimeError(f"expected RIANN model SHA-256 {MODEL_SHA256}, found {model_sha}")
        config = default_config()
        started = time.perf_counter_ns()
        batch_model = create_official_cpu_model(model_path)
        batch_session_initialization_ms = (time.perf_counter_ns() - started) / 1e6
        sequence_results = [
            compare_sequence(name, accels, gyros, config, batch_model)
            for name, (accels, gyros) in known_sequences().items()
        ]
        runtime = runtime_measurements(config, model_path)
    chunk_checks = streaming_chunk_checks(config)
    isolation = reset_and_determinism_checks(config)
    result = {
        "report_schema": "org.marcusfunt.riann_b5_smoke.v1",
        "algorithm": "official pretrained RIANN, causal 6D ONNX model",
        "training_exposure": TRAINING_EXPOSURE,
        "source_revision": manifest["source_fidelity"]["source_revision"],
        "implementation_sha256": manifest["source_fidelity"]["implementation_sha256"],
        "adapter_sha256": adapter_sha,
        "model_sha256": model_sha,
        "license": manifest["source_fidelity"]["license"],
        "runtime_versions": versions,
        "numpy_wheel_sha256": lock["runtime"]["numpy_wheel"]["sha256"],
        "onnxruntime_wheel_sha256": lock["runtime"]["onnxruntime_wheel"]["sha256"],
        "cpu_session_configuration": lock["runtime"]["session_options"],
        "providers": ["CPUExecutionProvider"],
        "input_profile": {
            "sampling_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
            "timestamp_interval_ns": INTERVAL_NS,
            "accelerometer": "m/s^2 specific force",
            "gyroscope": "rad/s",
            "sensor_set": "gyro_accel_6d",
            "magnetometer_supplied": False,
            "independent_heading_supplied": False,
            "execution_mode": "causal_online",
        },
        "sequence_count": len(sequence_results),
        "total_samples": sum(row["sample_count"] for row in sequence_results),
        "sequences": [annotate_riann_result(row) for row in sequence_results],
        "chunk_and_causality": chunk_checks,
        "reset_and_determinism": isolation,
        "batch_session_initialization_ms": batch_session_initialization_ms,
        "runtime": runtime,
        "interpretation": {
            "batch_vs_stream": "Official RIANN.predict_step was called once per B1 sample. Official RIANN.predict consumed the same serialized input values as a full-sequence batch. Small differences are reported as float32 execution-order effects.",
            "state": "RIANN uses an explicit hidden tensor of shape (2,1,1,200); reset_state() zeros it. predict() resets for its batch call and restores the previous online hidden state.",
            "yaw": "Six-axis yaw is unobservable startup-gauge relative; there is no magnetic or independent heading aid.",
            "training_exposure": "Every per-sequence result is wrapped with BROAD_USED_IN_DEVELOPMENT. BROAD is not an unseen generalization test for this pretrained model.",
            "scope": "Synthetic adapter fidelity and desktop CPU runtime checks only; no BROAD scoring, retraining, model conversion, or RP2350 validation.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "sequence_count": result["sequence_count"],
        "total_samples": result["total_samples"],
        "training_exposure": TRAINING_EXPOSURE,
        "max_batch_stream_geodesic_rad": max(
            row["official_batch_vs_streaming_max_geodesic_rad"]
            for row in sequence_results
        ),
        "causal_prefix_exact": chunk_checks["causal_prefix_211_of_900_exact_match"],
        "reset_deterministic": isolation["repeated_after_reset_exact_match"],
        "interleaved_reset_exact": isolation["interleaved_reset_exact_match"],
        "adapter_step_median_us": runtime["per_step"]["median_us"],
        "adapter_step_p95_us": runtime["per_step"]["p95_us"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
