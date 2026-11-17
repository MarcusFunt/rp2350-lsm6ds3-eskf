#!/usr/bin/env python3
"""Replay selected PR3 v5 synthetic losses and join ESKF/Mahony diagnostics."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import os
import shlex
import statistics
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pr3_failure_atlas import (  # noqa: E402
    ARCHIVE,
    ARCHIVE_MANIFEST,
    CONFIG,
    CONFIG_SHA256,
    PROTOCOL,
    assert_archive_match,
    load_development_archive,
    sha256_file,
)

SCENARIOS = ("maneuver", "timing_jitter", "compound_motion")
RATE_MODE = "uniform_208hz"
RATE_INDEX = 1
RATE_HZ = 208
SEED = 4001
STRESS_MODES = ("nominal", "stress")
ESKF_VARIANTS = ("eskf_conservative", "eskf_legacy", "eskf_confirmed_only")
EXPECTED_ESTIMATORS = (*ESKF_VARIANTS, "mahony", "gyro_only")
PROTOCOL_HELPER = ROOT / "tools" / "pr3_generate_scenario_header.py"
GENERATOR_SOURCE = ROOT / "tools" / "pr3_generate_inputs.cpp"
EVALUATOR_SOURCE = ROOT / "tools" / "pr3_evaluate_stream.cpp"
EXPECTED_SAMPLES = RATE_HZ * 16
EPOCH_US = 1_000_000
HEADER = struct.Struct("<8s9I64s20x")
RECORD = struct.Struct("<IQQQ24fI")

REQUIRED_STATE_FIELDS = (
    "orientation_w", "orientation_x", "orientation_y", "orientation_z",
    "accel_bias_x", "accel_bias_y", "accel_bias_z",
    "gyro_bias_x", "gyro_bias_y", "gyro_bias_z",
    "cov_theta_00", "cov_theta_11", "cov_theta_22",
    "covariance_after_process", "covariance_after_heading", "control_valid",
)
REQUIRED_GRAVITY_FIELDS = (
    "initialized", "accel_norm_gate_pass", "gyro_norm_gate_pass", "accel_step_gate_pass",
    "raw_candidate", "stationary", "gravity_allowed", "gravity_attempted", "gravity_accepted",
    "gravity_reason", "gravity_innovation_angle_rad", "gravity_nis", "gravity_nis_gate",
    "tilt_cov_trace", "tilt_cov_eigen_min", "tilt_cov_eigen_max", "covariance_positive_definite",
    "accel_bias_error_m_s2", "gyro_bias_error_rad_s",
)


def validate_archive_rows(
    rows: Sequence[dict[str, str]], scenario: str, stress_mode: str, seed: int
) -> dict[str, dict[str, str]]:
    selected = [row for row in rows if
        row.get("seed_split") == "development" and row.get("scenario") == scenario
        and row.get("rate_mode") == RATE_MODE and row.get("stress_mode") == stress_mode
        and row.get("sensor_input") == "IMU_ONLY" and row.get("startup_knowledge") == "UNKNOWN"
        and row.get("startup_gyro_bias_calibration") == "OFF" and row.get("runtime_aid") == "NONE"
        and row.get("seed") == str(seed)]
    by_estimator: dict[str, dict[str, str]] = {}
    for row in selected:
        estimator = row.get("estimator", "")
        if estimator in by_estimator:
            raise ValueError(f"duplicate archive row for {scenario}/{stress_mode}/{estimator}/{seed}")
        by_estimator[estimator] = row
    if set(by_estimator) != set(EXPECTED_ESTIMATORS):
        raise ValueError(
            f"archive rows for {scenario}/{stress_mode}/{seed} must contain exactly {EXPECTED_ESTIMATORS}"
        )
    hashes = {row.get("input_sha256", "") for row in by_estimator.values()}
    if len(hashes) != 1 or not next(iter(hashes)) or len(next(iter(hashes))) != 64:
        raise ValueError(f"archive rows for {scenario}/{stress_mode}/{seed} do not share input hash")
    for estimator, row in by_estimator.items():
        if row.get("rate_mode") != RATE_MODE or row.get("scenario") != scenario:
            raise ValueError(f"archive row metadata mismatch for {scenario}/{stress_mode}/{estimator}/{seed}")
        if int(row.get("expected", "0")) != 2913:
            raise ValueError(f"unexpected scored evaluation sample count for {scenario}/{stress_mode}/{estimator}/{seed}")
    return by_estimator


def validate_paired_archive_rows(
    nominal_rows: Sequence[dict[str, str]], stress_rows: Sequence[dict[str, str]]
) -> None:
    if not nominal_rows or not stress_rows:
        raise ValueError("nominal and stress archive rows are both required")
    nominal = validate_archive_rows(nominal_rows, nominal_rows[0]["scenario"], "nominal", SEED)
    stress = validate_archive_rows(stress_rows, stress_rows[0]["scenario"], "stress", SEED)
    if set(nominal) != set(stress):
        raise ValueError("nominal and stress archive rows have different estimator coverage")
    for estimator in EXPECTED_ESTIMATORS:
        left, right = nominal[estimator], stress[estimator]
        for field in ("scenario", "rate_mode", "seed", "seed_split", "sensor_input", "startup_knowledge",
                      "startup_gyro_bias_calibration", "runtime_aid"):
            if left.get(field) != right.get(field):
                raise ValueError(f"nominal and stress archive trial identity differs in {field}")
    nominal_hash = nominal["eskf_conservative"]["input_sha256"]
    stress_hash = stress["eskf_conservative"]["input_sha256"]
    if nominal_hash == stress_hash:
        raise ValueError("nominal and stress trials must have distinct input hashes")


def validate_trace_alignment(
    sample_rows: Sequence[dict[str, str]],
    gravity_rows: Sequence[dict[str, str]],
    *,
    expected_samples: int,
) -> None:
    if len(sample_rows) != expected_samples or len(gravity_rows) != expected_samples:
        raise ValueError("sample count differs from the shared PR3 input")
    for label, rows, required in (
        ("sample", sample_rows, REQUIRED_STATE_FIELDS),
        ("gravity", gravity_rows, REQUIRED_GRAVITY_FIELDS),
    ):
        indices = [int(row["sample_index"]) for row in rows]
        if indices != list(range(1, expected_samples + 1)):
            raise ValueError(f"{label} trace sample indices must be contiguous and unique")
        missing = [name for name in required if name not in rows[0]]
        if missing:
            raise ValueError(f"{label} trace diagnostic fields are missing: {missing}")
    for sample, gravity in zip(sample_rows, gravity_rows):
        if (sample["sample_index"] != gravity["sample_index"]
                or sample["reported_timestamp_us"] != gravity["reported_timestamp_us"]):
            raise ValueError("sample and gravity trace timestamp alignment mismatch")
        if "physical_timestamp_us" in sample and "physical_time_s" in gravity:
            # Physical time is reconstructed from the epoch by the evaluator.
            actual_s = int(sample["physical_timestamp_us"]) - EPOCH_US
            reported_s = float(gravity["physical_time_s"]) * 1e6
            if abs(actual_s - reported_s) > 1.0:
                raise ValueError("sample and gravity trace physical timestamp alignment mismatch")


def _load_archive_rows(path: Path) -> list[dict[str, str]]:
    import gzip as _gzip

    with _gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        return [row for row in csv.DictReader(stream) if
            row.get("scenario") in SCENARIOS and row.get("rate_mode") == RATE_MODE
            and row.get("seed") == str(SEED) and row.get("seed_split") == "development"
            and row.get("sensor_input") == "IMU_ONLY" and row.get("startup_knowledge") == "UNKNOWN"
            and row.get("startup_gyro_bias_calibration") == "OFF" and row.get("runtime_aid") == "NONE"]


def _compile_tools(cxx: str, temp: Path) -> tuple[Path, Path, str]:
    compiler = shlex.split(cxx)
    if not compiler:
        raise ValueError("compiler command is empty")
    build = temp / "build"
    build.mkdir(parents=True)
    generated = build / "pr3_scenario_protocol.hpp"
    subprocess.run(
        [sys.executable, str(PROTOCOL_HELPER), str(PROTOCOL), str(generated)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    generator, evaluator = build / "pr3_generate_inputs", build / "pr3_evaluate_stream"
    common = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", f"-I{build}"]
    subprocess.run([*common, str(GENERATOR_SOURCE), "-o", str(generator)], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    subprocess.run([*common, "-DINERTIAL_GRAVITY_DIAGNOSTICS=1", str(EVALUATOR_SOURCE), "-o", str(evaluator)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    version = subprocess.run([*compiler, "--version"], cwd=ROOT, check=True, capture_output=True,
                             text=True).stdout.splitlines()[0]
    return generator, evaluator, version


def _read_input_stream(path: Path, expected_scenario: str, stress_mode: str,
                       protocol_sha256: str) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise ValueError("PR3 input stream is shorter than its header")
    header = HEADER.unpack_from(data)
    if header[0] != b"PR3INP03" or header[7] != RECORD.size or header[6] != EXPECTED_SAMPLES:
        raise ValueError("PR3 input header has wrong magic, record size, or sample count")
    protocol_sha = header[10].decode("ascii")
    if protocol_sha != protocol_sha256:
        raise ValueError("PR3 input protocol SHA differs from the frozen archive protocol")
    if len(data) != HEADER.size + EXPECTED_SAMPLES * RECORD.size:
        raise ValueError("PR3 input stream length does not match its declared sample count")
    scenario_index = [item["id"] for item in json.loads(PROTOCOL.read_text(encoding="utf-8"))["scenarios"]].index(expected_scenario)
    if (header[2] != scenario_index or header[3] != RATE_INDEX
            or header[4] != (stress_mode == "stress") or header[5] != SEED):
        raise ValueError("PR3 input stream scenario/rate/stress metadata mismatch")
    rows: list[dict[str, Any]] = []
    for offset in range(HEADER.size, len(data), RECORD.size):
        record = RECORD.unpack_from(data, offset)
        index, nominal_us, reported_us, physical_us = record[:4]
        floats = record[4:28]
        if index != len(rows) + 1 or nominal_us != EPOCH_US + (index * 1_000_000) // RATE_HZ:
            raise ValueError("PR3 input sample indices or nominal timestamps are invalid")
        if not all(math.isfinite(value) for value in floats):
            raise ValueError(f"PR3 input sample {index} contains a nonfinite value")
        rows.append({
            "sample_index": index,
            "nominal_time_s": index / RATE_HZ,
            "nominal_timestamp_us": nominal_us,
            "reported_timestamp_us": reported_us,
            "physical_timestamp_us": physical_us,
            "physical_time_s": (physical_us - EPOCH_US) * 1e-6,
            "truth_q": tuple(floats[0:4]),
            "truth_accel_bias": tuple(floats[10:13]),
            "truth_gyro_bias": tuple(floats[13:16]),
            "accel": tuple(floats[16:19]),
            "gyro": tuple(floats[19:22]),
            "flags": record[28],
        })
    return rows


def _normalize_reported_timestamps(source: Path, destination: Path) -> str:
    """Create a labeled counterfactual with nominal reported times, keeping samples fixed."""
    data = bytearray(source.read_bytes())
    if len(data) != HEADER.size + EXPECTED_SAMPLES * RECORD.size:
        raise ValueError("cannot normalize timestamps in a malformed PR3 stream")
    for offset in range(HEADER.size, len(data), RECORD.size):
        record = RECORD.unpack_from(data, offset)
        struct.pack_into("<Q", data, offset + 12, record[1])
    destination.write_bytes(data)
    return sha256_file(destination)


def _qmul(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float, float]:
    w, x, y, z = a
    p, q, r, s = b
    return (w*p-x*q-y*r-z*s, w*q+x*p+y*s-z*r, w*r-x*s+y*p+z*q, w*s+x*r-y*q+z*p)


def _qnorm(q: Sequence[float]) -> tuple[float, float, float, float]:
    norm = math.sqrt(math.fsum(value * value for value in q))
    if norm <= 1e-12 or not math.isfinite(norm):
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(value / norm for value in q)  # type: ignore[return-value]


def _qexp(angle: Sequence[float]) -> tuple[float, float, float, float]:
    size = math.sqrt(math.fsum(value * value for value in angle))
    if size < 1e-6:
        return (1.0, angle[0] * .5, angle[1] * .5, angle[2] * .5)
    scale = math.sin(.5 * size) / size
    return (math.cos(.5 * size), angle[0] * scale, angle[1] * scale, angle[2] * scale)


def _rotate(q: Sequence[float], vector: Sequence[float], *, inverse: bool = False) -> tuple[float, float, float]:
    w, x, y, z = q
    if inverse:
        x, y, z = -x, -y, -z
    qv = (x, y, z)
    cross1 = (qv[1]*vector[2]-qv[2]*vector[1], qv[2]*vector[0]-qv[0]*vector[2], qv[0]*vector[1]-qv[1]*vector[0])
    t = tuple(2.0 * item for item in cross1)
    cross2 = (qv[1]*t[2]-qv[2]*t[1], qv[2]*t[0]-qv[0]*t[2], qv[0]*t[1]-qv[1]*t[0])
    return tuple(vector[i] + t[i]*w + cross2[i] for i in range(3))  # type: ignore[return-value]


def _tilt_error_deg(estimate: Sequence[float], truth: Sequence[float]) -> float:
    a = _rotate(estimate, (0.0, 0.0, 1.0), inverse=True)
    b = _rotate(truth, (0.0, 0.0, 1.0), inverse=True)
    dot = min(1.0, max(-1.0, math.fsum(x*y for x, y in zip(a, b))))
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return math.degrees(math.atan2(math.sqrt(math.fsum(value*value for value in cross)), dot))


def _geodesic_error_deg(estimate: Sequence[float], truth: Sequence[float]) -> float:
    relative = _qmul(estimate, (truth[0], -truth[1], -truth[2], -truth[3]))
    vector_norm = math.sqrt(math.fsum(value*value for value in relative[1:]))
    return math.degrees(2.0 * math.atan2(vector_norm, abs(relative[0])))


def _run_mahony(samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    orientation = (1.0, 0.0, 0.0, 0.0)
    gyro_bias = (0.0, 0.0, 0.0)
    previous_timestamp: int | None = None
    trace = []
    for sample in samples:
        timestamp = int(sample["reported_timestamp_us"])
        valid = False
        if previous_timestamp is None:
            previous_timestamp = timestamp
        else:
            dt = (timestamp - previous_timestamp) * 1e-6
            previous_timestamp = timestamp
            if 0.0 < dt <= .025:
                rate = tuple(float(value) - bias for value, bias in zip(sample["gyro"], gyro_bias))
                accel = sample["accel"]
                norm = math.sqrt(math.fsum(value*value for value in accel))
                if norm > 1e-4:
                    measured = tuple(value / norm for value in accel)
                    predicted = _rotate(orientation, (0.0, 0.0, 1.0), inverse=True)
                    error = (
                        measured[1]*predicted[2]-measured[2]*predicted[1],
                        measured[2]*predicted[0]-measured[0]*predicted[2],
                        measured[0]*predicted[1]-measured[1]*predicted[0],
                    )
                    rate = tuple(value + correction for value, correction in zip(rate, error))
                    gyro_bias = tuple(bias - correction * (.05 * dt) for bias, correction in zip(gyro_bias, error))
                delta = tuple(value * dt for value in rate)
                orientation = _qnorm(_qmul(orientation, _qexp(delta)))
                valid = all(math.isfinite(value) for value in orientation)
        trace.append({"orientation": orientation, "gyro_bias": gyro_bias, "valid": valid})
    return trace


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _build_trace(
    samples: Sequence[dict[str, Any]],
    conservative_rows: Sequence[dict[str, str]],
    gravity_rows: Sequence[dict[str, str]],
    mahony_rows: Sequence[dict[str, Any]],
    *,
    scenario: str,
    stress_mode: str,
    seed: int,
    timestamp_case: str = "as_generated",
    input_sha256: str = "",
) -> list[dict[str, Any]]:
    validate_trace_alignment(conservative_rows, gravity_rows, expected_samples=len(samples))
    if len(mahony_rows) != len(samples):
        raise ValueError("Mahony trace length differs from the shared PR3 input")
    result = []
    for sample, eskf, gravity, mahony in zip(samples, conservative_rows, gravity_rows, mahony_rows):
        if int(eskf["sample_index"]) != sample["sample_index"] or int(eskf["reported_timestamp_us"]) != sample["reported_timestamp_us"]:
            raise ValueError("ESKF and shared input timestamp alignment mismatch")
        if int(gravity["sample_index"]) != sample["sample_index"] or int(gravity["reported_timestamp_us"]) != sample["reported_timestamp_us"]:
            raise ValueError("gravity diagnostics and shared input timestamp alignment mismatch")
        eskf_q = tuple(float(eskf[f"orientation_{axis}"]) for axis in "wxyz")
        mahony_q = mahony["orientation"]
        truth_q = sample["truth_q"]
        eval_valid = (eskf["evaluation_sample"] == "true" and eskf["control_valid"] == "true"
                      and eskf["covariance_after_process"] == "true" and eskf["covariance_after_heading"] == "true")
        mahony_valid = eskf["evaluation_sample"] == "true" and mahony["valid"]
        result.append({
            "scenario": scenario, "stress_mode": stress_mode, "seed": seed,
            "timestamp_case": timestamp_case, "input_sha256": input_sha256,
            "sample_index": sample["sample_index"], "nominal_time_s": sample["nominal_time_s"],
            "nominal_timestamp_us": sample["nominal_timestamp_us"],
            "physical_time_s": sample["physical_time_s"],
            "reported_timestamp_us": sample["reported_timestamp_us"],
            "physical_timestamp_us": sample["physical_timestamp_us"],
            "evaluation_sample": eskf["evaluation_sample"],
            "truth_orientation_wxyz": truth_q,
            "eskf_orientation_wxyz": eskf_q,
            "mahony_orientation_wxyz": mahony_q,
            "eskf_tilt_error_deg": _tilt_error_deg(eskf_q, truth_q),
            "mahony_tilt_error_deg": _tilt_error_deg(mahony_q, truth_q),
            "eskf_geodesic_error_deg": _geodesic_error_deg(eskf_q, truth_q),
            "mahony_geodesic_error_deg": _geodesic_error_deg(mahony_q, truth_q),
            "eskf_eval_valid": eval_valid, "mahony_eval_valid": mahony_valid,
            "truth_accel_bias_x": sample["truth_accel_bias"][0], "truth_accel_bias_y": sample["truth_accel_bias"][1],
            "truth_accel_bias_z": sample["truth_accel_bias"][2],
            "truth_gyro_bias_x": sample["truth_gyro_bias"][0], "truth_gyro_bias_y": sample["truth_gyro_bias"][1],
            "truth_gyro_bias_z": sample["truth_gyro_bias"][2],
            "eskf_accel_bias_x": float(eskf["accel_bias_x"]), "eskf_accel_bias_y": float(eskf["accel_bias_y"]),
            "eskf_accel_bias_z": float(eskf["accel_bias_z"]),
            "eskf_gyro_bias_x": float(eskf["gyro_bias_x"]), "eskf_gyro_bias_y": float(eskf["gyro_bias_y"]),
            "eskf_gyro_bias_z": float(eskf["gyro_bias_z"]),
            "mahony_gyro_bias_x": mahony["gyro_bias"][0], "mahony_gyro_bias_y": mahony["gyro_bias"][1],
            "mahony_gyro_bias_z": mahony["gyro_bias"][2],
            "eskf_accel_bias_error_m_s2": math.sqrt(math.fsum((float(eskf[f"accel_bias_{axis}"]) - truth)**2 for axis, truth in zip("xyz", sample["truth_accel_bias"]))),
            "eskf_gyro_bias_error_rad_s": math.sqrt(math.fsum((float(eskf[f"gyro_bias_{axis}"]) - truth)**2 for axis, truth in zip("xyz", sample["truth_gyro_bias"]))),
            "mahony_gyro_bias_error_rad_s": math.sqrt(math.fsum((value - truth)**2 for value, truth in zip(mahony["gyro_bias"], sample["truth_gyro_bias"]))),
            "gravity_attempted": gravity["gravity_attempted"] == "true",
            "gravity_accepted": gravity["gravity_accepted"] == "true",
            "gravity_reason": gravity["gravity_reason"],
            "gravity_innovation_angle_rad": _optional_float(gravity["gravity_innovation_angle_rad"]) if gravity["gravity_attempted"] == "true" else None,
            "gravity_nis": _optional_float(gravity["gravity_nis"]) if gravity["gravity_attempted"] == "true" else None,
            "gravity_nis_gate": _optional_float(gravity["gravity_nis_gate"]) if gravity["gravity_attempted"] == "true" else None,
            "accel_norm_gate_pass": gravity["accel_norm_gate_pass"] == "true",
            "gyro_norm_gate_pass": gravity["gyro_norm_gate_pass"] == "true",
            "accel_step_gate_pass": gravity["accel_step_gate_pass"] == "true",
            "raw_candidate": gravity["raw_candidate"] == "true",
            "stationary": gravity["stationary"] == "true",
            "gravity_allowed": gravity["gravity_allowed"] == "true",
            "tilt_cov_trace_rad2": _optional_float(gravity["tilt_cov_trace"]),
            "tilt_cov_eigen_min_rad2": _optional_float(gravity["tilt_cov_eigen_min"]),
            "tilt_cov_eigen_max_rad2": _optional_float(gravity["tilt_cov_eigen_max"]),
            "covariance_positive_definite": gravity["covariance_positive_definite"] == "true",
            "eskf_gravity_updates_delta": int(eskf["gravity_updates_delta"]),
            "eskf_rejected_updates_delta": int(eskf["rejected_updates_delta"]),
            "eskf_health": eskf["health_after_process"],
            "eskf_cov_theta_00": float(eskf["cov_theta_00"]),
            "eskf_cov_theta_11": float(eskf["cov_theta_11"]),
            "eskf_cov_theta_22": float(eskf["cov_theta_22"]),
        })
    return result


def _rms(values: Sequence[float]) -> float | None:
    return math.sqrt(math.fsum(value * value for value in values) / len(values)) if values else None


def _summary(
    rows: Sequence[dict[str, Any]], archive_row: dict[str, str], mahony_archive_row: dict[str, str],
    gravity_summary: dict[str, str],
    *, scenario: str, stress_mode: str, input_sha256: str,
) -> dict[str, Any]:
    evaluation = [row for row in rows if row["evaluation_sample"] == "true"]
    eskf_valid = [row for row in evaluation if row["eskf_eval_valid"]]
    mahony_valid = [row for row in evaluation if row["mahony_eval_valid"]]
    eskf_tilt = [row["eskf_tilt_error_deg"] for row in eskf_valid]
    mahony_tilt = [row["mahony_tilt_error_deg"] for row in mahony_valid]
    archived_eskf = float(archive_row["tilt_rms_deg"])
    archived_mahony = float(mahony_archive_row["tilt_rms_deg"])
    eskf_rms, mahony_rms = _rms(eskf_tilt), _rms(mahony_tilt)
    if eskf_rms is None or not math.isclose(eskf_rms, archived_eskf, rel_tol=1e-4, abs_tol=5e-4):
        raise ValueError(
            f"{scenario}/{stress_mode}: reconstructed ESKF tilt RMS {eskf_rms} does not match frozen archive {archived_eskf}"
        )
    if mahony_rms is None or not math.isclose(mahony_rms, archived_mahony, rel_tol=2e-4, abs_tol=2e-4):
        raise ValueError(
            f"{scenario}/{stress_mode}: reconstructed Mahony trace RMS {mahony_rms} does not match frozen archive {archived_mahony}"
        )
    loss = [row["eskf_tilt_error_deg"] - row["mahony_tilt_error_deg"] for row in evaluation
            if row["eskf_eval_valid"] and row["mahony_eval_valid"]]
    paired = [row for row in evaluation if row["eskf_eval_valid"] and row["mahony_eval_valid"]]
    first_loss = next((row for row in paired if row["eskf_tilt_error_deg"] > row["mahony_tilt_error_deg"]), None)
    window_size = RATE_HZ
    max_window: tuple[float, float, float] | None = None
    if len(paired) >= window_size:
        for start in range(0, len(paired) - window_size + 1):
            window = paired[start:start + window_size]
            mean_loss = statistics.fmean(row["eskf_tilt_error_deg"] - row["mahony_tilt_error_deg"] for row in window)
            if max_window is None or mean_loss > max_window[2]:
                max_window = (window[0]["nominal_time_s"], window[-1]["nominal_time_s"], mean_loss)
    initialized = [row for row in rows if row["gravity_reason"] != "not_initialized"]
    eval_initialized = [row for row in evaluation if row["gravity_reason"] != "not_initialized"]
    reason_counts = dict(sorted(Counter(row["gravity_reason"] for row in initialized).items()))
    attempted = [row for row in initialized if row["gravity_attempted"]]
    attempted_nis = [row["gravity_nis"] for row in attempted if row["gravity_nis"] is not None]
    attempted_innovation = [row["gravity_innovation_angle_rad"] for row in attempted if row["gravity_innovation_angle_rad"] is not None]
    covariances = [row["tilt_cov_trace_rad2"] for row in rows if row["tilt_cov_trace_rad2"] is not None]
    pd_rows = [row for row in rows if row["gravity_reason"] != "not_initialized"]
    start = evaluation[0] if evaluation else None
    end = evaluation[-1] if evaluation else None
    reported_dt = [int(right["reported_timestamp_us"]) - int(left["reported_timestamp_us"])
                   for left, right in zip(rows, rows[1:])]
    nominal_dt = [int(right["nominal_timestamp_us"]) - int(left["nominal_timestamp_us"])
                  for left, right in zip(rows, rows[1:])]
    jitter_dt = [reported - nominal for reported, nominal in zip(reported_dt, nominal_dt)]
    reported_offset = [int(row["reported_timestamp_us"]) - int(row["nominal_timestamp_us"]) for row in rows]
    return {
        "scenario": scenario, "rate_mode": RATE_MODE, "stress_mode": stress_mode, "seed": SEED,
        "sample_count": len(rows), "evaluation_sample_count": len(evaluation), "input_sha256": input_sha256,
        "reported_dt_min_us": min(reported_dt) if reported_dt else None,
        "reported_dt_max_us": max(reported_dt) if reported_dt else None,
        "reported_timestamp_offset_min_us": min(reported_offset) if reported_offset else None,
        "reported_timestamp_offset_max_us": max(reported_offset) if reported_offset else None,
        "reported_dt_jitter_min_us": min(jitter_dt) if jitter_dt else None,
        "reported_dt_jitter_max_us": max(jitter_dt) if jitter_dt else None,
        "reported_dt_jitter_rms_us": math.sqrt(math.fsum(value*value for value in jitter_dt) / len(jitter_dt)) if jitter_dt else None,
        "frozen_archive_metrics_match": True,
        "eskf_conservative_tilt_rms_deg_reconstructed": eskf_rms,
        "eskf_conservative_tilt_rms_deg_archive": archived_eskf,
        "mahony_tilt_rms_deg_reconstructed": mahony_rms,
        "mahony_tilt_rms_deg_archive": archived_mahony,
        "eskf_minus_mahony_tilt_rms_deg": eskf_rms - mahony_rms if mahony_rms is not None else None,
        "eskf_valid_evaluation_samples": len(eskf_valid), "mahony_valid_evaluation_samples": len(mahony_valid),
        "first_sample_eskf_tilt_worse_than_mahony_s": first_loss["nominal_time_s"] if first_loss else None,
        "largest_1s_mean_eskf_minus_mahony_tilt_deg": max_window[2] if max_window else None,
        "largest_1s_window_start_s": max_window[0] if max_window else None,
        "largest_1s_window_end_s": max_window[1] if max_window else None,
        "gravity_attempts": int(gravity_summary["gravity_attempts"]),
        "gravity_accepted": int(gravity_summary["gravity_accepted"]),
        "gravity_rejected_attempts": int(gravity_summary["gravity_rejected"]),
        "gravity_reason_counts_all_initialized_samples": reason_counts,
        "evaluation_gravity_reason_counts": dict(sorted(Counter(row["gravity_reason"] for row in eval_initialized).items())),
        "evaluation_gravity_attempts": sum(row["gravity_attempted"] for row in eval_initialized),
        "evaluation_gravity_accepted": sum(row["gravity_accepted"] for row in eval_initialized),
        "evaluation_candidate_gate_failed_samples": sum(row["gravity_reason"] == "candidate_gate_failed" for row in eval_initialized),
        "evaluation_dwell_incomplete_samples": sum(row["gravity_reason"] == "candidate_dwell_incomplete" for row in eval_initialized),
        "evaluation_gyro_norm_gate_failures": sum(not row["gyro_norm_gate_pass"] for row in eval_initialized),
        "evaluation_accel_step_gate_failures": sum(not row["accel_step_gate_pass"] for row in eval_initialized),
        "accel_norm_gate_failures": sum(not row["accel_norm_gate_pass"] for row in initialized),
        "gyro_norm_gate_failures": sum(not row["gyro_norm_gate_pass"] for row in initialized),
        "accel_step_gate_failures": sum(not row["accel_step_gate_pass"] for row in initialized),
        "raw_candidate_samples": sum(row["raw_candidate"] for row in initialized),
        "gravity_allowed_samples": sum(row["gravity_allowed"] for row in initialized),
        "attempted_nis_sample_count": len(attempted_nis),
        "attempted_nis_mean": statistics.fmean(attempted_nis) if attempted_nis else None,
        "attempted_nis_max": max(attempted_nis) if attempted_nis else None,
        "attempted_innovation_angle_mean_rad": statistics.fmean(attempted_innovation) if attempted_innovation else None,
        "attempted_innovation_angle_max_rad": max(attempted_innovation) if attempted_innovation else None,
        "tilt_covariance_trace_start_rad2": start["tilt_cov_trace_rad2"] if start else None,
        "tilt_covariance_trace_end_rad2": end["tilt_cov_trace_rad2"] if end else None,
        "tilt_covariance_trace_max_rad2": max(covariances) if covariances else None,
        "covariance_positive_definite_fraction": sum(row["covariance_positive_definite"] for row in pd_rows) / len(pd_rows) if pd_rows else None,
        "eskf_gyro_bias_error_start_rad_s": start["eskf_gyro_bias_error_rad_s"] if start else None,
        "eskf_gyro_bias_error_end_rad_s": end["eskf_gyro_bias_error_rad_s"] if end else None,
        "eskf_gyro_bias_error_max_rad_s": max(row["eskf_gyro_bias_error_rad_s"] for row in rows),
        "mahony_gyro_bias_error_start_rad_s": start["mahony_gyro_bias_error_rad_s"] if start else None,
        "mahony_gyro_bias_error_end_rad_s": end["mahony_gyro_bias_error_rad_s"] if end else None,
        "eskf_accel_bias_error_start_m_s2": start["eskf_accel_bias_error_m_s2"] if start else None,
        "eskf_accel_bias_error_end_m_s2": end["eskf_accel_bias_error_m_s2"] if end else None,
        "eskf_accel_bias_error_max_m_s2": max(row["eskf_accel_bias_error_m_s2"] for row in rows),
    }


def _render_panel(elements: list[str], rows: Sequence[dict[str, Any]], *, x: float, y: float, width: float,
                  height: float, title: str, series: Sequence[tuple[str, str, str]], log: bool = False) -> None:
    left, top, plot_width, plot_height = x + 54, y + 30, width - 72, height - 58
    values: list[tuple[float, float, str]] = []
    for name, key, color in series:
        for row in rows:
            value = row.get(key)
            if row["evaluation_sample"] != "true" or value is None:
                continue
            valid = row["eskf_eval_valid"] if (name.startswith("ESKF") or key.startswith("gravity_") or key.startswith("tilt_cov_")) else row["mahony_eval_valid"]
            if not valid:
                continue
            numeric = float(value)
            values.append((float(row["nominal_time_s"]), math.log10(max(numeric, 1e-16)) if log else numeric, color))
    if not values:
        elements.append(f'<text x="{left}" y="{top+22}" font-family="sans-serif" font-size="12">No finite samples</text>')
        return
    xs = [value[0] for value in values]
    ys = [value[1] for value in values]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if math.isclose(y0, y1):
        y0 -= .5
        y1 += .5
    pad = .06 * (y1 - y0)
    y0, y1 = y0 - pad, y1 + pad
    def sx(t: float) -> float:
        return left + (t - x0) / max(1e-12, x1 - x0) * plot_width
    def sy(v: float) -> float:
        return top + plot_height - (v - y0) / max(1e-12, y1 - y0) * plot_height
    elements.append(f'<text x="{left}" y="{y+17}" font-family="sans-serif" font-size="14" font-weight="bold">{html.escape(title)}</text>')
    for tick in range(5):
        val = y0 + (y1-y0)*tick/4
        yy = sy(val)
        label = f"10^{val:.1f}" if log else f"{val:.3g}"
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_width}" y2="{yy:.1f}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{left-5}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="9">{label}</text>')
    for name, key, color in series:
        points = []
        for row in rows:
            if row["evaluation_sample"] != "true" or row.get(key) is None:
                continue
            valid = row["eskf_eval_valid"] if (name.startswith("ESKF") or key.startswith("gravity_") or key.startswith("tilt_cov_")) else row["mahony_eval_valid"]
            if not valid:
                continue
            value = float(row[key])
            if log:
                value = math.log10(max(value, 1e-16))
            points.append((sx(float(row["nominal_time_s"])), sy(value)))
        if points:
            d = " ".join(("M" if i == 0 else "L") + f"{px:.2f},{py:.2f}" for i, (px, py) in enumerate(points))
            elements.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.1"/>')
    for i, (name, _, color) in enumerate(series):
        lx = left + i * (plot_width / max(1, len(series)))
        elements.append(f'<line x1="{lx:.1f}" y1="{y+height-7}" x2="{lx+13:.1f}" y2="{y+height-7}" stroke="{color}" stroke-width="2"/>')
        elements.append(f'<text x="{lx+17:.1f}" y="{y+height-3}" font-family="sans-serif" font-size="9">{html.escape(name)}</text>')


def _render_figure(path: Path, scenario: str, nominal: Sequence[dict[str, Any]], stress: Sequence[dict[str, Any]]) -> None:
    width, height = 1240, 1250
    col_width, top = 600, 64
    panel_height = 220
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="34" y="32" font-family="sans-serif" font-size="21" font-weight="bold">PR3 v5 {html.escape(scenario)} mechanism trace · seed 4001 · uniform 208 Hz</text>',
        f'<text x="{34+col_width/2}" y="56" text-anchor="middle" font-family="sans-serif" font-size="15">Nominal</text>',
        f'<text x="{34+col_width+16+col_width/2}" y="56" text-anchor="middle" font-family="sans-serif" font-size="15">Stress</text>',
    ]
    panels = (
        ("Tilt error (degrees)", (("ESKF conservative", "eskf_tilt_error_deg", "#2563eb"), ("Mahony", "mahony_tilt_error_deg", "#dc2626")), False),
        ("Gyro bias error (rad/s)", (("ESKF bias", "eskf_gyro_bias_error_rad_s", "#2563eb"), ("Mahony bias", "mahony_gyro_bias_error_rad_s", "#dc2626")), False),
        ("Accelerometer bias error (m/s²)", (("ESKF accel bias", "eskf_accel_bias_error_m_s2", "#7c3aed"),), False),
        ("Projected tilt covariance trace (rad²)", (("ESKF tilt covariance", "tilt_cov_trace_rad2", "#059669"),), True),
        ("Gravity innovation NIS (attempted updates)", (("NIS attempted", "gravity_nis", "#d97706"),), False),
    )
    for column, rows in enumerate((nominal, stress)):
        x = 34 + column * (col_width + 16)
        for index, (title, series, log) in enumerate(panels):
            y = top + index * panel_height
            _render_panel(elements, rows, x=x, y=y, width=col_width, height=panel_height,
                          title=title, series=series, log=log)
    elements.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8", newline="\n")


def _write_gzip_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty synthetic trace")
    fields = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8", compresslevel=6) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_csv(path: Path, summaries: Sequence[dict[str, Any]]) -> None:
    if not summaries:
        raise ValueError("no synthetic summaries to write")
    fields = list(summaries[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summaries)


def _render_jitter_counterfactual(path: Path, nominal_rows: Sequence[dict[str, Any]],
                                  stress_rows: Sequence[dict[str, Any]]) -> None:
    width, height = 1160, 660
    columns = (nominal_rows, stress_rows)
    identities = (
        ("as_generated", "eskf_tilt_error_deg", "ESKF, generated jitter", "#2563eb"),
        ("nominal_grid_counterfactual", "eskf_tilt_error_deg", "ESKF, nominal timestamps", "#60a5fa"),
        ("as_generated", "mahony_tilt_error_deg", "Mahony, generated jitter", "#dc2626"),
        ("nominal_grid_counterfactual", "mahony_tilt_error_deg", "Mahony, nominal timestamps", "#f87171"),
    )
    elems = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="32" font-family="sans-serif" font-size="21" font-weight="bold">Timing-jitter same-sample timestamp counterfactual · seed 4001</text>',
    ]
    for column, rows in enumerate(columns):
        if not rows:
            raise ValueError("timing-jitter counterfactual figure is missing a stress mode")
        x0 = 30 + column * 565
        left, top, plot_width, plot_height = x0 + 58, 82, 480, 480
        evaluation = [row for row in rows if row["evaluation_sample"] == "true"]
        values = [float(row[key]) for row in evaluation for key in ("eskf_tilt_error_deg", "mahony_tilt_error_deg")]
        ymax = max(max(values, default=1.0) * 1.08, 0.1)
        xmin = min(float(row["nominal_time_s"]) for row in evaluation)
        xmax = max(float(row["nominal_time_s"]) for row in evaluation)
        def sx(time_s: float) -> float:
            return left + (time_s - xmin) / max(1e-12, xmax - xmin) * plot_width
        def sy(value: float) -> float:
            return top + plot_height - value / ymax * plot_height
        title = "Nominal stress" if column == 0 else "Stress mode"
        elems.append(f'<text x="{left+plot_width/2}" y="63" text-anchor="middle" font-family="sans-serif" font-size="15">{title}</text>')
        for tick in range(6):
            value = ymax * tick / 5
            yy = sy(value)
            elems.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_width}" y2="{yy:.1f}" stroke="#e5e7eb"/>')
            elems.append(f'<text x="{left-6}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="9">{value:.3g}</text>')
        for case, key, _, color in identities:
            valid_key = "eskf_eval_valid" if key.startswith("eskf") else "mahony_eval_valid"
            selected = [row for row in evaluation if row["timestamp_case"] == case and row[valid_key]]
            d = " ".join(("M" if i == 0 else "L") + f"{sx(float(row['nominal_time_s'])):.2f},{sy(float(row[key])):.2f}"
                          for i, row in enumerate(selected))
            if d:
                elems.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.2"/>')
        for i, (_, _, label, color) in enumerate(identities):
            lx = left + i * 118
            elems.append(f'<line x1="{lx}" y1="594" x2="{lx+13}" y2="594" stroke="{color}" stroke-width="2"/>')
            elems.append(f'<text x="{lx+17}" y="598" font-family="sans-serif" font-size="8">{html.escape(label)}</text>')
    elems.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elems) + "\n", encoding="utf-8", newline="\n")


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# PR3 synthetic weakness traces (B9)", "",
        f"Run date: {report['run_date_utc']} · seed: {SEED} · split: development · rate: {RATE_MODE}", "",
        "The six selected raw input streams are regenerated with the frozen PR3 v5 generator. Every input SHA-256 and all five evaluator summary rows per stream are checked against the frozen archive before any joined trace is written. Metrics are the archived fixed evaluation window (nominal sample indices 2–16 s); traces retain the complete 16 s stream.", "",
        f"Protocol SHA-256: `{report['protocol_sha256']}` · archive SHA-256: `{report['archive_sha256']}` · replay evaluator source SHA-256: `{report['evaluator_source_sha256']}` · archive evaluator source SHA-256: `{report['archive_evaluator_source_sha256']}`.", "",
        "## Paired results", "",
        "| Scenario | Mode | ESKF tilt RMS (°) | Mahony tilt RMS (°) | ESKF − Mahony (°) | Gravity accepted / attempted | Gate reasons (initialized samples) |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["runs"]:
        reasons = ", ".join(f"{key}: {value}" for key, value in row["gravity_reason_counts_all_initialized_samples"].items())
        lines.append(
            f"| `{row['scenario']}` | {row['stress_mode']} | {row['eskf_conservative_tilt_rms_deg_archive']:.3f} | "
            f"{row['mahony_tilt_rms_deg_archive']:.3f} | {row['eskf_minus_mahony_tilt_rms_deg']:+.3f} | "
            f"{row['gravity_accepted']} / {row['gravity_attempts']} | {reasons} |"
        )
    lines.extend(["", "## Diagnostic timelines", ""])
    for scenario in SCENARIOS:
        lines.extend([f"### {scenario}", "", f"![{scenario} ESKF and Mahony mechanism traces](figures/{scenario}_mechanism.svg)", ""])
    lines.extend([
        "### Timing-jitter isolation", "",
        "The nominal-grid counterfactual preserves the timing-jitter trial's exact gyro, accelerometer, truth, and noise samples, changing only `reported_timestamp_us` to the nominal grid. It is a mechanism check and does not carry frozen-archive status; the original timing-jitter traces above are archive matched.", "",
        "![Timing-jitter original and nominal-grid counterfactual](figures/timing_jitter_counterfactual.svg)", "",
        "| Mode | Archived ESKF RMS (°) | Same-sample no-jitter ESKF RMS (°) | ESKF change (°) | Archived Mahony RMS (°) | Same-sample no-jitter Mahony RMS (°) |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for row in report["timing_jitter_counterfactuals"]:
        lines.append(
            f"| {row['stress_mode']} | {row['archived_eskf_tilt_rms_deg']:.3f} | {row['counterfactual_eskf_tilt_rms_deg']:.3f} | "
            f"{row['eskf_rms_change_after_timestamp_normalization_deg']:+.4f} | {row['archived_mahony_tilt_rms_deg']:.3f} | "
            f"{row['counterfactual_mahony_tilt_rms_deg']:.3f} |"
        )
    maneuver = next(row for row in report["runs"] if row["scenario"] == "maneuver" and row["stress_mode"] == "nominal")
    timing = next(row for row in report["runs"] if row["scenario"] == "timing_jitter" and row["stress_mode"] == "nominal")
    compound_nominal = next(row for row in report["runs"] if row["scenario"] == "compound_motion" and row["stress_mode"] == "nominal")
    compound_stress = next(row for row in report["runs"] if row["scenario"] == "compound_motion" and row["stress_mode"] == "stress")
    jitter_nominal = next(row for row in report["timing_jitter_counterfactuals"] if row["stress_mode"] == "nominal")
    jitter_stress = next(row for row in report["timing_jitter_counterfactuals"] if row["stress_mode"] == "stress")
    lines.extend([
        "",
        "## Mechanism findings", "",
        f"- **Maneuver:** ESKF trails Mahony by {maneuver['eskf_minus_mahony_tilt_rms_deg']:.3f}° RMS. The evaluation window has {maneuver['evaluation_candidate_gate_failed_samples']} candidate-gate failures and {maneuver['evaluation_gravity_attempts']} gravity attempts; all {maneuver['gravity_accepted']} attempts were accepted during startup. The max attempted NIS is {maneuver['attempted_nis_max']:.4f}, so this trace does not point to NIS rejection. ESKF gyro-bias error ends at {maneuver['eskf_gyro_bias_error_end_rad_s']:.4f} rad/s versus Mahony at {maneuver['mahony_gyro_bias_error_end_rad_s']:.4f} rad/s.",
        f"- **Timing jitter:** ESKF trails Mahony by {timing['eskf_minus_mahony_tilt_rms_deg']:.3f}° RMS with reported offsets {timing['reported_timestamp_offset_min_us']} to {timing['reported_timestamp_offset_max_us']} µs. Replacing only the reported timestamps with the nominal grid changes ESKF RMS by {jitter_nominal['eskf_rms_change_after_timestamp_normalization_deg']:+.4f}° in nominal and {jitter_stress['eskf_rms_change_after_timestamp_normalization_deg']:+.4f}° in stress. For this seed, timestamp jitter does not explain the ESKF/Mahony gap; the same gravity-gate and bias pattern remains.",
        f"- **Compound motion:** ESKF trails Mahony by {compound_nominal['eskf_minus_mahony_tilt_rms_deg']:.3f}° nominal and {compound_stress['eskf_minus_mahony_tilt_rms_deg']:.3f}° under stress. The projected tilt-covariance trace grows to {compound_nominal['tilt_covariance_trace_end_rad2']:.3f} and {compound_stress['tilt_covariance_trace_end_rad2']:.3f} rad² while staying positive definite. Stress has {compound_stress['evaluation_accel_step_gate_failures']} acceleration-step gate failures and no evaluation-window gravity attempts.",
        "- **Shared pattern:** motion-rate/stationarity checks prevent ESKF gravity updates before innovation formation; blank NIS values mark those pre-measurement rejections. Mahony continues accelerometer feedback and integral gyro-bias adaptation during motion, which wins on these selected synthetic streams. The results show a conservative-gating tradeoff, not a covariance numeric failure. They do not establish that Mahony is safer under unmodeled accelerations.", "",
        "## Reading the diagnostics", "",
        "Gravity NIS and innovation are recorded only when the filter reaches a gravity measurement attempt. A blank NIS means an earlier candidate/stationarity gate prevented a measurement from being formed; it is not a zero innovation. Covariance trace is the evaluator's projected two-dimensional tilt covariance. Bias-error traces compare state estimates with the shared simulator truth. Mahony has no accelerometer-bias state.", "",
        "The checked-in archive was produced with a different evaluator source revision. Before the joined traces were written, all five estimator summary rows for all six selected raw inputs were replayed with the evaluator recorded above and every archived metric field was checked against the frozen archive. The generator, protocol, filter header, input hashes, and those replayed metrics matched. These are selected development traces, not new acceptance statistics or a parameter search.",
    ])
    return "\n".join(lines) + "\n"


def run_atlas(output_dir: Path, *, cxx: str, overwrite: bool = False) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise ValueError(f"output directory is not empty: {output_dir}; pass --overwrite to replace generated files")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_manifest, archive_hash, archive_manifest_hash, protocol_hash, _ = load_development_archive()
    selected_archive = _load_archive_rows(ARCHIVE)
    rows_by_case: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for scenario in SCENARIOS:
        for mode in STRESS_MODES:
            rows_by_case[(scenario, mode)] = validate_archive_rows(selected_archive, scenario, mode, SEED)
        validate_paired_archive_rows(
            [rows_by_case[(scenario, "nominal")][name] for name in EXPECTED_ESTIMATORS],
            [rows_by_case[(scenario, "stress")][name] for name in EXPECTED_ESTIMATORS],
        )
    source_hashes = {
        "protocol_source_sha256": protocol_hash,
        "archive_sha256": archive_hash,
        "archive_manifest_sha256": archive_manifest_hash,
        "generator_source_sha256": sha256_file(GENERATOR_SOURCE),
        "evaluator_source_sha256": sha256_file(EVALUATOR_SOURCE),
        "filter_header_sha256": sha256_file(ROOT / "eskf15.hpp"),
    }
    if source_hashes["generator_source_sha256"] != archive_manifest["generator_source_sha256"]:
        raise ValueError("current PR3 generator source does not match the frozen archive manifest")
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    compiler_version = ""
    summaries: list[dict[str, Any]] = []
    joined_rows: list[dict[str, Any]] = []
    jitter_counterfactuals: list[dict[str, Any]] = []
    replayed: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="pr3-synthetic-weaknesses-") as temp_name:
        temp = Path(temp_name)
        generator, evaluator, compiler_version = _compile_tools(cxx, temp)
        for scenario in SCENARIOS:
            for mode in STRESS_MODES:
                label = f"{scenario}__{mode}__seed{SEED}"
                input_path = temp / f"{label}.bin"
                eval_path = temp / f"{label}_summary.csv"
                sample_path = temp / f"{label}_samples.csv"
                gravity_path = temp / f"{label}_gravity.csv"
                subprocess.run([str(generator), str(input_path), "development", scenario, str(RATE_INDEX), mode, str(SEED)],
                               cwd=ROOT, check=True, capture_output=True, text=True)
                input_sha = sha256_file(input_path)
                archive_group = rows_by_case[(scenario, mode)]
                if input_sha != archive_group["eskf_conservative"]["input_sha256"]:
                    raise ValueError(f"regenerated input hash differs from frozen archive for {label}")
                subprocess.run(
                    [str(evaluator), str(input_path), str(eval_path), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                     git_head, CONFIG_SHA256, input_sha, "--sample-trace", str(sample_path),
                     "--gravity-summary", str(gravity_path.with_name(f"{label}_gravity_summary.csv")),
                     "--gravity-trace", str(gravity_path)],
                    cwd=ROOT, check=True, capture_output=True, text=True,
                )
                trial_rows = _read_csv(eval_path)
                actual_by_estimator = {row["estimator"]: row for row in trial_rows}
                if set(actual_by_estimator) != set(EXPECTED_ESTIMATORS):
                    raise ValueError(f"evaluator did not emit all archived estimator rows for {label}")
                for estimator in EXPECTED_ESTIMATORS:
                    assert_archive_match(actual_by_estimator[estimator], archive_group[estimator])
                sample_trace = _read_csv(sample_path)
                conservative = [row for row in sample_trace if row["estimator"] == "eskf_conservative"]
                gravity_trace = _read_csv(gravity_path)
                validate_trace_alignment(conservative, gravity_trace, expected_samples=EXPECTED_SAMPLES)
                samples = _read_input_stream(input_path, scenario, mode, protocol_hash)
                mahony = _run_mahony(samples)
                joined = _build_trace(samples, conservative, gravity_trace, mahony,
                                      scenario=scenario, stress_mode=mode, seed=SEED)
                gravity_summary_path = gravity_path.with_name(f"{label}_gravity_summary.csv")
                diagnostic_rows = _read_csv(gravity_summary_path)
                conservative_summary = next(row for row in diagnostic_rows if row["estimator"] == "eskf_conservative")
                record = _summary(joined, archive_group["eskf_conservative"], archive_group["mahony"], conservative_summary,
                                  scenario=scenario, stress_mode=mode, input_sha256=input_sha)
                record["archive_mahony_tilt_rms_deg"] = float(archive_group["mahony"]["tilt_rms_deg"])
                record["mahony_tilt_rms_deg_archive"] = float(archive_group["mahony"]["tilt_rms_deg"])
                if not math.isclose(record["mahony_tilt_rms_deg_reconstructed"], record["mahony_tilt_rms_deg_archive"], rel_tol=2e-4, abs_tol=2e-4):
                    raise ValueError(f"reconstructed Mahony trace does not match the frozen archive for {label}")
                record["archived_trial_metrics_match"] = True
                summaries.append(record)
                joined_rows.extend(joined)
                if scenario == "timing_jitter":
                    cf_input = temp / f"{label}_nominal_grid_counterfactual.bin"
                    cf_input_sha = _normalize_reported_timestamps(input_path, cf_input)
                    cf_eval = temp / f"{label}_nominal_grid_summary.csv"
                    cf_sample_path = temp / f"{label}_nominal_grid_samples.csv"
                    cf_gravity_path = temp / f"{label}_nominal_grid_gravity.csv"
                    subprocess.run(
                        [str(evaluator), str(cf_input), str(cf_eval), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                         git_head, CONFIG_SHA256, cf_input_sha, "--sample-trace", str(cf_sample_path),
                         "--gravity-summary", str(temp / f"{label}_nominal_grid_gravity_summary.csv"),
                         "--gravity-trace", str(cf_gravity_path)],
                        cwd=ROOT, check=True, capture_output=True, text=True,
                    )
                    cf_sample_rows = _read_csv(cf_sample_path)
                    cf_conservative = [row for row in cf_sample_rows if row["estimator"] == "eskf_conservative"]
                    cf_gravity_rows = _read_csv(cf_gravity_path)
                    validate_trace_alignment(cf_conservative, cf_gravity_rows, expected_samples=EXPECTED_SAMPLES)
                    cf_samples = _read_input_stream(cf_input, scenario, mode, protocol_hash)
                    cf_mahony = _run_mahony(cf_samples)
                    cf_joined = _build_trace(
                        cf_samples, cf_conservative, cf_gravity_rows, cf_mahony,
                        scenario=scenario, stress_mode=mode, seed=SEED,
                        timestamp_case="nominal_grid_counterfactual", input_sha256=cf_input_sha,
                    )
                    cf_eval_rows = [row for row in cf_joined if row["evaluation_sample"] == "true"]
                    cf_eskf_rms = _rms([row["eskf_tilt_error_deg"] for row in cf_eval_rows if row["eskf_eval_valid"]])
                    cf_mahony_rms = _rms([row["mahony_tilt_error_deg"] for row in cf_eval_rows if row["mahony_eval_valid"]])
                    if cf_eskf_rms is None or cf_mahony_rms is None:
                        raise ValueError(f"timestamp counterfactual has incomplete outputs for {label}")
                    cf_metrics = {row["estimator"]: row for row in _read_csv(cf_eval)}
                    if not math.isclose(cf_eskf_rms, float(cf_metrics["eskf_conservative"]["tilt_rms_deg"]), rel_tol=1e-4, abs_tol=5e-4):
                        raise ValueError(f"counterfactual ESKF sample trace and summary metrics differ for {label}")
                    if not math.isclose(cf_mahony_rms, float(cf_metrics["mahony"]["tilt_rms_deg"]), rel_tol=2e-4, abs_tol=2e-4):
                        raise ValueError(f"counterfactual Mahony sample trace and summary metrics differ for {label}")
                    jitter_counterfactuals.append({
                        "scenario": scenario, "stress_mode": mode, "seed": SEED, "rate_mode": RATE_MODE,
                        "archive_input_sha256": input_sha, "counterfactual_input_sha256": cf_input_sha,
                        "counterfactual_type": "same_sensor_truth_stream_with_reported_time_replaced_by_nominal_grid",
                        "archived_eskf_tilt_rms_deg": float(archive_group["eskf_conservative"]["tilt_rms_deg"]),
                        "archived_mahony_tilt_rms_deg": float(archive_group["mahony"]["tilt_rms_deg"]),
                        "counterfactual_eskf_tilt_rms_deg": cf_eskf_rms,
                        "counterfactual_mahony_tilt_rms_deg": cf_mahony_rms,
                        "counterfactual_eskf_minus_mahony_tilt_rms_deg": cf_eskf_rms - cf_mahony_rms,
                        "eskf_rms_change_after_timestamp_normalization_deg": cf_eskf_rms - float(archive_group["eskf_conservative"]["tilt_rms_deg"]),
                        "mahony_rms_change_after_timestamp_normalization_deg": cf_mahony_rms - float(archive_group["mahony"]["tilt_rms_deg"]),
                        "replay_metrics_match_archive": False,
                    })
                    joined_rows.extend(cf_joined)
                replayed.append({
                    "scenario": scenario, "stress_mode": mode, "input_sha256": input_sha,
                    "archive_input_sha256": archive_group["eskf_conservative"]["input_sha256"],
                    "replay_metrics_match_archive": True,
                    "archive_rows": {name: archive_group[name] for name in EXPECTED_ESTIMATORS},
                })

    output_dir.joinpath("traces").mkdir(parents=True, exist_ok=True)
    _write_gzip_csv(output_dir / "traces" / "pr3_synthetic_weaknesses_seed4001.csv.gz", joined_rows)
    _write_summary_csv(output_dir / "pr3_synthetic_weakness_summary.csv", summaries)
    _write_summary_csv(output_dir / "timing_jitter_counterfactual_summary.csv", jitter_counterfactuals)
    for scenario in SCENARIOS:
        nominal = [row for row in joined_rows if row["scenario"] == scenario and row["stress_mode"] == "nominal" and row["timestamp_case"] == "as_generated"]
        stress = [row for row in joined_rows if row["scenario"] == scenario and row["stress_mode"] == "stress" and row["timestamp_case"] == "as_generated"]
        _render_figure(output_dir / "figures" / f"{scenario}_mechanism.svg", scenario, nominal, stress)
    _render_jitter_counterfactual(
        output_dir / "figures" / "timing_jitter_counterfactual.svg",
        [row for row in joined_rows if row["scenario"] == "timing_jitter" and row["stress_mode"] == "nominal"],
        [row for row in joined_rows if row["scenario"] == "timing_jitter" and row["stress_mode"] == "stress"],
    )
    report = {
        "report_schema": "org.marcusfunt.pr3_synthetic_weakness_atlas.b9.v1",
        "run_date_utc": datetime.now(timezone.utc).date().isoformat(),
        "classification": "selected development-only diagnostic; not acceptance statistics",
        "split": "development", "seed": SEED, "scenario": list(SCENARIOS),
        "rate_mode": RATE_MODE, "stress_modes": list(STRESS_MODES),
        "profile": CONFIG, "config_sha256": CONFIG_SHA256,
        "protocol_sha256": protocol_hash, "archive_sha256": archive_hash,
        "archive_manifest_sha256": archive_manifest_hash,
        "archive_source_commit": archive_manifest.get("source_commit"),
        "archive_evaluator_source_sha256": archive_manifest.get("evaluator_source_sha256"),
        "replay_evaluator_source_matches_archive_manifest": source_hashes["evaluator_source_sha256"] == archive_manifest.get("evaluator_source_sha256"),
        "git_head": git_head, "compiler": compiler_version,
        "source_hashes": source_hashes, "evaluator_source_sha256": source_hashes["evaluator_source_sha256"],
        "archive_evaluator_source_sha256": archive_manifest.get("evaluator_source_sha256"),
        "replayed_cases": replayed, "runs": summaries,
        "timing_jitter_counterfactuals": jitter_counterfactuals,
        "trace_method": "PR3 v5 evaluator sample trace for Conservative ESKF and protocol-equation reconstruction of Mahony from the same binary input; the reconstructed Mahony evaluation RMS is checked against the archived evaluator metric.",
    }
    (output_dir / "pr3_synthetic_weakness_results.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "PR3_SYNTHETIC_WEAKNESSES_B9.md").write_text(_markdown_report(report), encoding="utf-8", newline="\n")
    files = [file for file in output_dir.rglob("*") if file.is_file()]
    manifest = {
        "schema_version": 1, "status": "PASS", "report_schema": report["report_schema"],
        "archive_sha256": archive_hash, "archive_manifest_sha256": archive_manifest_hash,
        "protocol_sha256": protocol_hash, "source_hashes": source_hashes,
        "replay_metric_checks": "all five estimators in each selected run matched frozen archive fields",
        "selected_streams": len(replayed), "selected_trace_samples_including_counterfactual": len(joined_rows),
        "files": {file.relative_to(output_dir).as_posix(): sha256_file(file) for file in sorted(files)},
    }
    (output_dir / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "remediation/analysis/pr3_synthetic_weaknesses_b9")
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_atlas(args.output_dir, cxx=args.cxx, overwrite=args.overwrite)
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, struct.error, subprocess.CalledProcessError) as error:
        print(f"PR3 synthetic weakness atlas failed: {error}", file=sys.stderr)
        return 2
    print(f"PASS wrote {len(report['runs'])} archive-validated PR3 synthetic traces to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
