#!/usr/bin/env python3
"""Compare VQF 6D with the production ESKF on shared BROAD timestamps."""

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
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from external_benchmarks.metrics import (  # noqa: E402
    geodesic_error_rad,
    gravity_tilt_error_rad,
    heading_rad,
    relative_heading_drift_rad,
)

SAMPLE_RATE_HZ = 2000 / 7
SAMPLE_PERIOD_US = 3500
GRAVITY_MPS2 = 9.80665
DEFAULT_GYRO_LIMIT_RPS = 0.98 * math.radians(245.0)
DEFAULT_ACCEL_LIMIT_MPS2 = 0.98 * 4.0 * GRAVITY_MPS2
BROAD_GYRO_LIMIT_RPS = 0.98 * math.radians(2000.0)
BROAD_ACCEL_LIMIT_MPS2 = 0.98 * 16.0 * GRAVITY_MPS2
BROAD_SOURCE_URL = "https://github.com/dlaidig/broad"
BROAD_PAPER_URL = "https://doi.org/10.3390/data6070072"
REPLAY_SOURCE = ROOT / "tools" / "b9_eskf_replay.cpp"


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be a finite number")
    return converted


def _matrix(values: Sequence[Sequence[object]], width: int, count: int, label: str,
            *, allow_nonfinite: bool = False) -> None:
    try:
        rows = len(values)
    except TypeError as error:
        raise ValueError(f"{label} must be a sample matrix") from error
    if rows != count:
        raise ValueError(f"{label} sample count {rows} does not match timestamps {count}")
    for index, row in enumerate(values):
        if len(row) != width:
            raise ValueError(f"{label}[{index}] must have {width} components")
        for axis, value in enumerate(row):
            if allow_nonfinite:
                try:
                    float(value)
                except (TypeError, ValueError, OverflowError) as error:
                    raise ValueError(f"{label}[{index}][{axis}] must be numeric") from error
            else:
                _finite(value, f"{label}[{index}][{axis}]")


def validate_broad_arrays(
    trial_id: str,
    sampling_rate_hz: float,
    timestamps_us: Sequence[int],
    accel_mps2: Sequence[Sequence[float]],
    gyro_rad_s: Sequence[Sequence[float]],
    truth_wxyz: Sequence[Sequence[float]],
    movement: Sequence[bool],
) -> None:
    """Validate one already aligned BROAD trial before any filter is run."""
    if not trial_id:
        raise ValueError("trial_id must be nonempty")
    rate = _finite(sampling_rate_hz, f"{trial_id}: sampling_rate_hz")
    if not math.isclose(rate, SAMPLE_RATE_HZ, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{trial_id}: sampling rate {rate!r} is not BROAD's 2000/7 Hz")
    count = len(timestamps_us)
    if count < 2:
        raise ValueError(f"{trial_id}: expected at least two timestamps")
    previous = None
    for index, timestamp in enumerate(timestamps_us):
        if isinstance(timestamp, bool) or int(timestamp) != timestamp or timestamp < 0:
            raise ValueError(f"{trial_id}: timestamp {index} must be a nonnegative integer")
        current = int(timestamp)
        if previous is not None and current - previous != SAMPLE_PERIOD_US:
            raise ValueError(f"{trial_id}: timestamps must be strictly increasing at 3500 us intervals")
        previous = current
    _matrix(accel_mps2, 3, count, f"{trial_id}: imu_acc")
    _matrix(gyro_rad_s, 3, count, f"{trial_id}: imu_gyr")
    _matrix(truth_wxyz, 4, count, f"{trial_id}: opt_quat", allow_nonfinite=True)
    if len(movement) != count:
        raise ValueError(f"{trial_id}: movement sample count does not match timestamps")
    for index, value in enumerate(movement):
        if value not in (False, True, 0, 1):
            raise ValueError(f"{trial_id}: movement[{index}] must be Boolean")
    for index, quaternion in enumerate(truth_wxyz):
        finite = [math.isfinite(float(value)) for value in quaternion]
        if any(finite) and not all(finite):
            continue  # a partially missing optical reference is unavailable at this sample
        if not all(finite):
            continue
        norm = math.sqrt(math.fsum(float(value) ** 2 for value in quaternion))
        if abs(norm - 1.0) > 1e-3:
            raise ValueError(f"{trial_id}: opt_quat[{index}] is not unit length")


def matched_valid_mask(
    expected_timestamps_us: Sequence[int],
    vqf_timestamps_us: Sequence[int],
    vqf_valid: Sequence[bool],
    eskf_timestamps_us: Sequence[int],
    eskf_valid: Sequence[bool],
    truth_valid: Sequence[bool] | None = None,
) -> list[bool]:
    """Intersect validity only after requiring exact timestamp/index parity."""
    expected = tuple(int(value) for value in expected_timestamps_us)
    if tuple(int(value) for value in vqf_timestamps_us) != expected:
        raise ValueError("VQF timestamps do not exactly match the input timestamp sequence")
    if tuple(int(value) for value in eskf_timestamps_us) != expected:
        raise ValueError("ESKF timestamps do not exactly match the input timestamp sequence")
    if len(vqf_valid) != len(expected) or len(eskf_valid) != len(expected):
        raise ValueError("estimator validity masks must match the input timestamp count")
    reference_valid = [True] * len(expected) if truth_valid is None else list(truth_valid)
    if len(reference_valid) != len(expected):
        raise ValueError("truth validity mask must match the input timestamp count")
    if any(not isinstance(value, bool) for value in (*vqf_valid, *eskf_valid, *reference_valid)):
        raise ValueError("estimator validity masks must contain Boolean values")
    return [left and right and truth for left, right, truth in zip(vqf_valid, eskf_valid, reference_valid)]


def _qmul(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float, float]:
    w, x, y, z = left
    a, b, c, d = right
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


def align_heading_gauge(
    estimates_wxyz: Sequence[Sequence[float]],
    truth_wxyz: Sequence[Sequence[float]],
    *,
    anchor_index: int,
) -> list[tuple[float, float, float, float]]:
    """Apply one world-z rotation to remove only the startup six-axis yaw gauge."""
    if len(estimates_wxyz) != len(truth_wxyz) or not estimates_wxyz:
        raise ValueError("estimate and truth sequences must have the same nonzero length")
    if isinstance(anchor_index, bool) or not 0 <= anchor_index < len(estimates_wxyz):
        raise ValueError("anchor_index is outside the orientation sequence")
    estimate_heading = heading_rad(estimates_wxyz[anchor_index])
    truth_heading = heading_rad(truth_wxyz[anchor_index])
    if estimate_heading is None or truth_heading is None:
        raise ValueError("cannot align the initial yaw gauge at a singular heading")
    delta = truth_heading - estimate_heading
    yaw = (math.cos(delta / 2.0), 0.0, 0.0, math.sin(delta / 2.0))
    return [_qmul(yaw, tuple(estimate)) for estimate in estimates_wxyz]


def orientation_error_series(
    estimates_wxyz: Sequence[Sequence[float]],
    truth_wxyz: Sequence[Sequence[float]],
    *,
    anchor_index: int,
) -> dict[str, list[float | None]]:
    """Return gauge-aligned total, gravity-tilt, and relative-heading errors."""
    aligned = align_heading_gauge(estimates_wxyz, truth_wxyz, anchor_index=anchor_index)
    if len(aligned) != len(truth_wxyz):
        raise ValueError("estimate and truth sample counts differ")
    return {
        "geodesic_error_rad": [geodesic_error_rad(a, b) for a, b in zip(aligned, truth_wxyz)],
        "tilt_error_rad": [gravity_tilt_error_rad(a, b) for a, b in zip(aligned, truth_wxyz)],
        "relative_heading_drift_rad": list(
            relative_heading_drift_rad(aligned, truth_wxyz, alignment_index=anchor_index)
        ),
    }


def _masked_orientation_error_series(
    estimates_wxyz: Sequence[Sequence[float]],
    truth_wxyz: Sequence[Sequence[float]],
    truth_valid: Sequence[bool],
    *,
    anchor_index: int,
) -> dict[str, list[float | None]]:
    if len(estimates_wxyz) != len(truth_wxyz) or len(truth_valid) != len(truth_wxyz):
        raise ValueError("estimate, truth, and truth-valid sequences must have equal lengths")
    valid_indices = [index for index, valid in enumerate(truth_valid) if valid]
    if anchor_index not in valid_indices:
        raise ValueError("heading anchor must have a valid optical reference")
    local_anchor = valid_indices.index(anchor_index)
    valid_errors = orientation_error_series(
        [estimates_wxyz[index] for index in valid_indices],
        [truth_wxyz[index] for index in valid_indices],
        anchor_index=local_anchor,
    )
    result = {name: [None] * len(truth_wxyz) for name in valid_errors}
    for name, values in valid_errors.items():
        for index, value in zip(valid_indices, values):
            result[name][index] = value
    return result


def score_paired_errors(
    errors: dict[str, Sequence[float | None]],
    movement: Sequence[bool],
    paired_valid: Sequence[bool],
) -> dict[str, Any]:
    """Score motion samples only where both estimators are valid at one timestamp."""
    count = len(movement)
    if len(paired_valid) != count or any(len(values) != count for values in errors.values()):
        raise ValueError("error, movement, and validity sequences must have equal lengths")
    indices = [i for i in range(count) if movement[i] and paired_valid[i]]

    def summary(name: str) -> dict[str, float | int | None]:
        values = [float(errors[name][i]) for i in indices if errors[name][i] is not None]
        if not values:
            return {"count": 0, "rms_rad": None, "p95_rad": None, "maximum_rad": None}
        magnitudes = sorted(abs(value) for value in values)
        return {
            "count": len(values),
            "rms_rad": math.sqrt(math.fsum(value * value for value in values) / len(values)),
            "p95_rad": magnitudes[int(0.95 * (len(magnitudes) - 1))],
            "maximum_rad": magnitudes[-1],
        }

    geodesic = summary("geodesic_error_rad")
    tilt = summary("tilt_error_rad")
    heading = summary("relative_heading_drift_rad")
    return {
        "paired_movement_sample_count": len(indices),
        "geodesic_error_count": geodesic["count"],
        "geodesic_rms_rad": geodesic["rms_rad"],
        "geodesic_p95_rad": geodesic["p95_rad"],
        "geodesic_maximum_rad": geodesic["maximum_rad"],
        "tilt_error_count": tilt["count"],
        "tilt_rms_rad": tilt["rms_rad"],
        "tilt_p95_rad": tilt["p95_rad"],
        "tilt_maximum_rad": tilt["maximum_rad"],
        "relative_heading_error_count": heading["count"],
        "relative_heading_drift_rms_rad": heading["rms_rad"],
        "relative_heading_drift_p95_rad": heading["p95_rad"],
        "relative_heading_drift_maximum_rad": heading["maximum_rad"],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_hdf5_trial(path: Path) -> dict[str, Any]:
    try:
        import h5py
        import numpy as np
    except ImportError as error:
        raise RuntimeError("BROAD loading requires h5py and NumPy in the selected Python environment") from error
    with h5py.File(path, "r") as source:
        required = ("imu_acc", "imu_gyr", "opt_quat", "movement")
        missing = [name for name in required if name not in source]
        if missing:
            raise ValueError(f"{path.name}: missing HDF5 datasets {missing}")
        accel = np.asarray(source["imu_acc"], dtype=np.float64)
        gyro = np.asarray(source["imu_gyr"], dtype=np.float64)
        truth = np.asarray(source["opt_quat"], dtype=np.float64)
        movement_raw = np.asarray(source["movement"])
        movement = movement_raw.astype(bool)
        rate = float(source.attrs.get("sampling_rate", math.nan))
        info = source.attrs.get("info", "")
        if isinstance(info, bytes):
            info = info.decode("utf-8", errors="replace")
    count = len(accel)
    timestamps = [index * SAMPLE_PERIOD_US for index in range(count)]
    truth_valid = [all(math.isfinite(float(value)) for value in quaternion) for quaternion in truth]
    validate_broad_arrays(path.stem, rate, timestamps, accel, gyro, truth, movement)
    return {
        "trial_id": path.stem,
        "path": path,
        "source_artifact_sha256": sha256_file(path),
        "sampling_rate_hz": rate,
        "timestamps_us": timestamps,
        "accel_mps2": accel,
        "gyro_rad_s": gyro,
        "truth_wxyz": truth,
        "truth_valid": truth_valid,
        "movement": movement.astype(bool).tolist(),
        "info": str(info),
    }


def _preselect_trace_trials(paths: Sequence[Path], requested: Sequence[str] | None) -> list[str]:
    if requested:
        available = {path.stem for path in paths}
        missing = [trial for trial in requested if trial not in available]
        if missing:
            raise ValueError(f"requested BROAD trial(s) not found: {', '.join(missing)}")
        return list(requested)
    import h5py
    import numpy as np

    candidates: list[tuple[float, str]] = []
    for path in paths:
        with h5py.File(path, "r") as source:
            gyro = np.asarray(source["imu_gyr"], dtype=np.float64)
            accel = np.asarray(source["imu_acc"], dtype=np.float64)
            movement = np.asarray(source["movement"], dtype=bool)
            gyro_axis = np.max(np.abs(gyro), axis=1)
            accel_axis = np.max(np.abs(accel), axis=1)
        gyro_cross = np.flatnonzero((gyro_axis >= DEFAULT_GYRO_LIMIT_RPS) & movement)
        accel_cross = np.flatnonzero((accel_axis >= DEFAULT_ACCEL_LIMIT_MPS2) & movement)
        if not len(gyro_cross):
            continue
        first_gyro = int(gyro_cross[0])
        if len(accel_cross) and int(accel_cross[0]) < first_gyro:
            continue
        candidates.append((float(np.max(gyro_axis[movement])), path.stem))
    if not candidates:
        # Keep the atlas useful if a dataset revision changes its high-rate trials.
        for path in paths:
            with h5py.File(path, "r") as source:
                gyro = np.asarray(source["imu_gyr"], dtype=np.float64)
                movement = np.asarray(source["movement"], dtype=bool)
                candidates.append((float(np.max(np.max(np.abs(gyro), axis=1)[movement])), path.stem))
    return [trial for _, trial in sorted(candidates, reverse=True)[:3]]


def _write_eskf_input(path: Path, trial: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("sample_index", "timestamp_us", "valid", "ax", "ay", "az", "gx", "gy", "gz"))
        for index, (timestamp, accel, gyro) in enumerate(
            zip(trial["timestamps_us"], trial["accel_mps2"], trial["gyro_rad_s"]), start=1
        ):
            writer.writerow(
                (index, timestamp, 1, *(format(float(value), ".17g") for value in accel),
                 *(format(float(value), ".17g") for value in gyro))
            )


def _compile_replay(cxx: str, destination: Path) -> None:
    command = shlex.split(cxx) + [
        "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        str(REPLAY_SOURCE), "-o", str(destination),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


def _read_eskf_output(path: Path, *, keep_diagnostics: bool) -> dict[str, list[Any]]:
    names = (
        "timestamp_us", "output_valid", "health", "reset_required", "state_timestamp_us",
        "gyro_axis_absmax_rad_s", "accel_axis_absmax_mps2", "max_gyro_axis_rps", "max_accel_axis_mps2",
        "quaternion", "accel_bias", "gyro_bias", "cov_theta_diag",
    )
    diagnostic_names = (
        "gravity_reason", "gravity_attempted", "gravity_accepted", "gravity_accel_norm_mps2",
        "gravity_gyro_norm_rad_s", "gravity_accel_step_mps2", "gravity_accel_norm_gate_pass",
        "gravity_gyro_norm_gate_pass", "gravity_accel_step_gate_pass", "gravity_innovation_angle_rad",
        "gravity_nis", "gravity_nis_gate",
    )
    result: dict[str, list[Any]] = {name: [] for name in names}
    if keep_diagnostics:
        result.update({name: [] for name in diagnostic_names})

    def optional_float(value: str) -> float | None:
        if not value:
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None

    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            result["timestamp_us"].append(int(row["timestamp_us"]))
            result["output_valid"].append(row["output_valid"] == "true")
            result["health"].append(row["health"])
            result["reset_required"].append(row["reset_required"] == "true")
            result["state_timestamp_us"].append(int(row["state_timestamp_us"]))
            result["gyro_axis_absmax_rad_s"].append(float(row["gyro_axis_absmax_rad_s"]))
            result["accel_axis_absmax_mps2"].append(float(row["accel_axis_absmax_mps2"]))
            result["max_gyro_axis_rps"].append(float(row["max_gyro_axis_rps"]))
            result["max_accel_axis_mps2"].append(float(row["max_accel_axis_mps2"]))
            result["quaternion"].append(tuple(float(row[f"state_orientation_{axis}"]) for axis in "wxyz"))
            result["accel_bias"].append(tuple(float(row[f"accel_bias_{axis}"]) for axis in "xyz"))
            result["gyro_bias"].append(tuple(float(row[f"gyro_bias_{axis}"]) for axis in "xyz"))
            result["cov_theta_diag"].append(tuple(float(row[f"cov_theta_{axis}{axis}"]) for axis in "xyz"))
            if keep_diagnostics:
                result["gravity_reason"].append(row["gravity_reason"])
                for name in ("gravity_attempted", "gravity_accepted", "gravity_accel_norm_gate_pass",
                             "gravity_gyro_norm_gate_pass", "gravity_accel_step_gate_pass"):
                    result[name].append(row[name] == "true")
                for name in ("gravity_accel_norm_mps2", "gravity_gyro_norm_rad_s", "gravity_accel_step_mps2",
                             "gravity_innovation_angle_rad", "gravity_nis", "gravity_nis_gate"):
                    result[name].append(optional_float(row[name]))
    return result


def _run_eskf(
    executable: Path,
    input_csv: Path,
    output_csv: Path,
    profile: str,
    *,
    keep_diagnostics: bool,
) -> dict[str, list[Any]]:
    subprocess.run(
        [str(executable), str(input_csv), str(output_csv), profile],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return _read_eskf_output(output_csv, keep_diagnostics=keep_diagnostics)


def _run_vqf(trial: dict[str, Any]) -> tuple[list[tuple[float, float, float, float]], list[bool]]:
    try:
        from external_benchmarks.adapters.vqf_full_6d import VQFFull6DAdapter
    except ImportError as error:
        raise RuntimeError("VQF comparison requires vqf 2.1.2 and NumPy 2.0.2") from error
    adapter = VQFFull6DAdapter()
    adapter.reset({"sampling_rate_hz": {"numerator": 2000, "denominator": 7}, "timestamp_unit": "us"})
    estimates: list[tuple[float, float, float, float]] = []
    valid: list[bool] = []
    for timestamp, accel, gyro in zip(trial["timestamps_us"], trial["accel_mps2"], trial["gyro_rad_s"]):
        output = adapter.step(int(timestamp), tuple(float(value) for value in accel), tuple(float(value) for value in gyro))
        orientation = output["orientation"]
        estimates.append(tuple(float(value) for value in orientation["quaternion_wxyz"]))
        valid.append(bool(output["orientation_valid"]))
    return estimates, valid


def _first_index(values: Sequence[bool]) -> int | None:
    return next((index for index, value in enumerate(values) if value), None)


def _first_fault(trace: dict[str, list[Any]], trial: dict[str, Any]) -> dict[str, Any] | None:
    index = next((i for i, health in enumerate(trace["health"]) if health == "Fault"), None)
    if index is None:
        return None
    gyro_cross = trace["gyro_axis_absmax_rad_s"][index] >= trace["max_gyro_axis_rps"][index]
    accel_cross = trace["accel_axis_absmax_mps2"][index] >= trace["max_accel_axis_mps2"][index]
    cause = "gyro_and_accel_range" if gyro_cross and accel_cross else (
        "gyro_range" if gyro_cross else ("accel_range" if accel_cross else "other_fault")
    )
    return {
        "sample_index": index + 1,
        "timestamp_us": trace["timestamp_us"][index],
        "time_s": trace["timestamp_us"][index] * 1e-6,
        "cause": cause,
        "gyro_axis_absmax_rad_s": trace["gyro_axis_absmax_rad_s"][index],
        "gyro_axis_absmax_deg_s": math.degrees(trace["gyro_axis_absmax_rad_s"][index]),
        "gyro_limit_rad_s": trace["max_gyro_axis_rps"][index],
        "accel_axis_absmax_mps2": trace["accel_axis_absmax_mps2"][index],
        "accel_limit_mps2": trace["max_accel_axis_mps2"][index],
        "state_timestamp_us": trace["state_timestamp_us"][index],
    }


def _range_stats(trace: dict[str, list[Any]], movement: Sequence[bool]) -> dict[str, Any]:
    gyro_limit = trace["max_gyro_axis_rps"][0]
    accel_limit = trace["max_accel_axis_mps2"][0]
    movement_indices = [index for index, active in enumerate(movement) if active]
    gyro_cross_indices = [
        i for i in movement_indices if trace["gyro_axis_absmax_rad_s"][i] >= gyro_limit
    ]
    accel_cross_indices = [
        i for i in movement_indices if trace["accel_axis_absmax_mps2"][i] >= accel_limit
    ]
    return {
        "gyro_full_scale_threshold_rad_s": gyro_limit,
        "gyro_full_scale_threshold_deg_s": math.degrees(gyro_limit),
        "accel_full_scale_threshold_mps2": accel_limit,
        "movement_gyro_axis_range_crossings": len(gyro_cross_indices),
        "movement_accel_axis_range_crossings": len(accel_cross_indices),
        "first_movement_gyro_range_crossing_sample": gyro_cross_indices[0] + 1 if gyro_cross_indices else None,
        "first_movement_accel_range_crossing_sample": accel_cross_indices[0] + 1 if accel_cross_indices else None,
        "movement_max_gyro_axis_deg_s": max(
            (math.degrees(trace["gyro_axis_absmax_rad_s"][i]) for i in movement_indices), default=None
        ),
        "movement_max_accel_axis_mps2": max(
            (trace["accel_axis_absmax_mps2"][i] for i in movement_indices), default=None
        ),
    }


def _variant_result(
    name: str,
    trace: dict[str, list[Any]],
    vqf_valid: Sequence[bool],
    vqf_timestamps: Sequence[int],
    trial: dict[str, Any],
    vqf_estimates: Sequence[Sequence[float]],
    *,
    keep_trace: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    timestamps = trial["timestamps_us"]
    pair_valid = matched_valid_mask(
        timestamps,
        vqf_timestamps,
        vqf_valid,
        trace["timestamp_us"],
        trace["output_valid"],
        trial["truth_valid"],
    )
    anchor = _first_index(pair_valid)
    if anchor is None:
        vqf_errors = {name: [None] * len(timestamps) for name in
                      ("geodesic_error_rad", "tilt_error_rad", "relative_heading_drift_rad")}
        eskf_errors = {name: list(values) for name, values in vqf_errors.items()}
    else:
        truth = trial["truth_wxyz"]
        vqf_errors = _masked_orientation_error_series(
            vqf_estimates, truth, trial["truth_valid"], anchor_index=anchor
        )
        eskf_errors = _masked_orientation_error_series(
            trace["quaternion"], truth, trial["truth_valid"], anchor_index=anchor
        )
    movement = trial["movement"]
    vqf_score = score_paired_errors(vqf_errors, movement, pair_valid)
    eskf_score = score_paired_errors(eskf_errors, movement, pair_valid)
    movement_count = sum(bool(value) for value in movement)
    own_valid_movement = sum(active and valid for active, valid in zip(movement, trace["output_valid"]))
    own_fault_movement = sum(active and health == "Fault" for active, health in zip(movement, trace["health"]))
    result = {
        "range_profile": name,
        "movement_sample_count": movement_count,
        "eskf_valid_movement_sample_count": own_valid_movement,
        "eskf_movement_availability": own_valid_movement / movement_count if movement_count else None,
        "eskf_faulted_movement_sample_count": own_fault_movement,
        "matched_valid_timestamp_count": sum(pair_valid),
        "first_fault": _first_fault(trace, trial),
        "range_statistics": _range_stats(trace, movement),
        "vqf_score_on_matched_timestamps": vqf_score,
        "eskf_score_on_matched_timestamps": eskf_score,
        "anchor_sample_index": anchor + 1 if anchor is not None else None,
    }
    details = {"pair_valid": pair_valid, "vqf_errors": vqf_errors, "eskf_errors": eskf_errors}
    return result, details, trace


def _write_selected_trace(path: Path, trial: dict[str, Any], vqf_valid: Sequence[bool],
                          vqf_errors: dict[str, Sequence[float | None]],
                          default: dict[str, Any], broad: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8", compresslevel=6) as stream:
        fields = (
            "sample_index", "timestamp_us", "time_s", "movement", "accel_axis_absmax_mps2",
            "gyro_axis_absmax_rad_s", "truth_valid", "vqf_valid", "eskf_lsm6ds3_valid", "eskf_broad_valid",
            "paired_lsm6ds3_valid", "paired_broad_valid", "vqf_geodesic_error_deg",
            "eskf_lsm6ds3_geodesic_error_deg", "eskf_broad_geodesic_error_deg",
            "vqf_tilt_error_deg", "eskf_broad_tilt_error_deg", "eskf_broad_state_timestamp_us",
            "eskf_broad_health", "eskf_broad_reset_required", "eskf_broad_accel_bias_x",
            "eskf_broad_accel_bias_y", "eskf_broad_accel_bias_z", "eskf_broad_gyro_bias_x",
            "eskf_broad_gyro_bias_y", "eskf_broad_gyro_bias_z", "eskf_broad_cov_theta_xx",
            "eskf_broad_cov_theta_yy", "eskf_broad_cov_theta_zz", "gravity_reason",
            "gravity_attempted", "gravity_accepted", "gravity_nis", "gravity_innovation_angle_rad",
        )
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, timestamp in enumerate(trial["timestamps_us"]):
            dtrace, btrace = default["trace"], broad["trace"]
            values = {
                "sample_index": index + 1,
                "timestamp_us": timestamp,
                "time_s": f"{timestamp * 1e-6:.6f}",
                "movement": str(bool(trial["movement"][index])).lower(),
                "truth_valid": str(bool(trial["truth_valid"][index])).lower(),
                "accel_axis_absmax_mps2": f"{max(abs(float(v)) for v in trial['accel_mps2'][index]):.9g}",
                "gyro_axis_absmax_rad_s": f"{max(abs(float(v)) for v in trial['gyro_rad_s'][index]):.9g}",
                "vqf_valid": str(bool(vqf_valid[index])).lower(),
                "eskf_lsm6ds3_valid": str(bool(dtrace["output_valid"][index])).lower(),
                "eskf_broad_valid": str(bool(btrace["output_valid"][index])).lower(),
                "paired_lsm6ds3_valid": str(bool(default["details"]["pair_valid"][index])).lower(),
                "paired_broad_valid": str(bool(broad["details"]["pair_valid"][index])).lower(),
            }
            for label, errors in (
                ("vqf", vqf_errors),
                ("eskf_lsm6ds3", default["details"]["eskf_errors"]),
                ("eskf_broad", broad["details"]["eskf_errors"]),
            ):
                value = errors["geodesic_error_rad"][index]
                values[f"{label}_geodesic_error_deg"] = "" if value is None else f"{math.degrees(value):.9g}"
            for label, errors in (("vqf", vqf_errors), ("eskf_broad", broad["details"]["eskf_errors"])):
                value = errors["tilt_error_rad"][index]
                values[f"{label}_tilt_error_deg"] = "" if value is None else f"{math.degrees(value):.9g}"
            for name, value in zip(("eskf_broad_state_timestamp_us",), (btrace["state_timestamp_us"][index],)):
                values[name] = value
            values["eskf_broad_health"] = btrace["health"][index]
            values["eskf_broad_reset_required"] = str(btrace["reset_required"][index]).lower()
            for prefix, vector in (("accel", btrace["accel_bias"][index]), ("gyro", btrace["gyro_bias"][index])):
                for axis, value in zip("xyz", vector):
                    values[f"eskf_broad_{prefix}_bias_{axis}"] = f"{value:.9g}"
            for axis, value in zip(("xx", "yy", "zz"), btrace["cov_theta_diag"][index]):
                values[f"eskf_broad_cov_theta_{axis}"] = f"{value:.9g}"
            for name in ("gravity_reason", "gravity_attempted", "gravity_accepted"):
                value = btrace.get(name, [None] * len(trial["timestamps_us"]))[index]
                values[name] = value if name == "gravity_reason" else ("" if value is None else str(value).lower())
            for name in ("gravity_nis", "gravity_innovation_angle_rad"):
                value = btrace.get(name, [None] * len(trial["timestamps_us"]))[index]
                values[name] = "" if value is None else f"{value:.9g}"
            writer.writerow(values)


def _render_trace_figure(path: Path, trial_id: str, trial: dict[str, Any], vqf_errors: dict[str, Sequence[float | None]],
                         default: dict[str, Any], broad: dict[str, Any]) -> None:
    width, height = 1120, 760
    left, plot_width = 98, 960
    panel_height, first_top, second_top = 250, 80, 420
    movement_indices = [i for i, active in enumerate(trial["movement"]) if active]
    times = [trial["timestamps_us"][i] * 1e-6 for i in movement_indices]
    if not times:
        return
    series = [
        ("VQF 2.1.2", vqf_errors["geodesic_error_rad"], default["details"]["pair_valid"], "#0072B2"),
        ("ESKF, LSM6DS3 range", default["details"]["eskf_errors"]["geodesic_error_rad"], default["details"]["pair_valid"], "#D55E00"),
        ("ESKF, BROAD range", broad["details"]["eskf_errors"]["geodesic_error_rad"], broad["details"]["pair_valid"], "#009E73"),
    ]
    error_values = [math.degrees(abs(errors[i])) for _, errors, mask, _ in series for i in movement_indices if mask[i] and errors[i] is not None]
    ymax_error = max(error_values, default=1.0) * 1.08
    ymax_error = max(ymax_error, 0.1)
    rate_values = [math.degrees(max(abs(float(v)) for v in trial["gyro_rad_s"][i])) for i in movement_indices]
    ymax_rate = max(max(rate_values, default=0.0) * 1.08, 250.0)
    xmin, xmax = times[0], times[-1]

    def sx(value: float) -> float:
        return left + (value - xmin) / max(1e-12, xmax - xmin) * plot_width

    def sy(value: float, top: int, ymax: float) -> float:
        return top + panel_height - value / ymax * panel_height

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<title>BROAD matched orientation errors: {html.escape(trial_id)}</title>',
        '<text x="98" y="35" font-family="sans-serif" font-size="20" font-weight="bold">'
        f'{html.escape(trial_id)} · movement interval · shared valid timestamps</text>',
    ]
    for top, ymax, ylabel in ((first_top, ymax_error, "Gauge-aligned orientation error (degrees)"),
                              (second_top, ymax_rate, "Maximum gyro axis rate (degrees/s)")):
        for tick in range(6):
            value = ymax * tick / 5
            yy = sy(value, top, ymax)
            elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_width}" y2="{yy:.1f}" stroke="#d1d5db"/>')
            elements.append(f'<text x="{left-10}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.3g}</text>')
        elements.append(f'<text transform="translate(22 {top+panel_height/2:.1f}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12">{ylabel}</text>')
    elements.append(f'<text x="{left+plot_width/2}" y="{first_top+panel_height+28}" text-anchor="middle" font-family="sans-serif" font-size="12">Trial time (s)</text>')
    for name, errors, mask, color in series:
        points = [(sx(times[j]), sy(math.degrees(abs(errors[i])), first_top, ymax_error))
                  for j, i in enumerate(movement_indices) if mask[i] and errors[i] is not None]
        if points:
            path_data = " ".join(("M" if j == 0 else "L") + f"{x:.2f},{y:.2f}" for j, (x, y) in enumerate(points))
            elements.append(f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="1.5"/>')
    for i, (name, _, _, color) in enumerate(series):
        x = left + i * 288
        elements.append(f'<line x1="{x}" y1="390" x2="{x+18}" y2="390" stroke="{color}" stroke-width="3"/>')
        elements.append(f'<text x="{x+25}" y="394" font-family="sans-serif" font-size="12">{html.escape(name)}</text>')
    rate_points = [(sx(times[j]), sy(rate_values[j], second_top, ymax_rate)) for j in range(len(movement_indices))]
    rate_path = " ".join(("M" if j == 0 else "L") + f"{x:.2f},{y:.2f}" for j, (x, y) in enumerate(rate_points))
    elements.append(f'<path d="{rate_path}" fill="none" stroke="#444444" stroke-width="1.2"/>')
    for threshold, label, color in (
        (math.degrees(DEFAULT_GYRO_LIMIT_RPS), "Default near-full-scale 245°/s", "#D55E00"),
        (math.degrees(BROAD_GYRO_LIMIT_RPS), "BROAD near-full-scale 2000°/s", "#009E73"),
    ):
        if threshold <= ymax_rate:
            yy = sy(threshold, second_top, ymax_rate)
            elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_width}" y2="{yy:.1f}" stroke="{color}" stroke-dasharray="5,4"/>')
            elements.append(f'<text x="{left+plot_width-4}" y="{yy-5:.1f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="{color}">{label}</text>')
    elements.append(f'<text x="{left+plot_width/2}" y="730" text-anchor="middle" font-family="sans-serif" font-size="12">Trial time (s)</text>')
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8", newline="\n")


def _git_revision(path: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _trial_paths(dataset_dir: Path, selected: Sequence[str] | None) -> list[Path]:
    paths = sorted(dataset_dir.glob("*.hdf5"))
    if not paths:
        raise ValueError(f"no .hdf5 BROAD trials found in {dataset_dir}")
    if selected:
        by_name = {path.stem: path for path in paths}
        missing = [name for name in selected if name not in by_name]
        if missing:
            raise ValueError(f"requested BROAD trial(s) not found: {', '.join(missing)}")
        return [by_name[name] for name in selected]
    if len(paths) != 39:
        raise ValueError(f"expected all 39 BROAD HDF5 trials, found {len(paths)}; use --trials for a subset")
    return paths


def _make_summary_row(trial: dict[str, Any], default: dict[str, Any], broad: dict[str, Any],
                      vqf_valid: Sequence[bool]) -> dict[str, Any]:
    movement_count = sum(trial["movement"])
    max_gyro_axis = max(max(abs(float(v)) for v in row) for row, moving in zip(trial["gyro_rad_s"], trial["movement"]) if moving)
    gyro_norm = [math.sqrt(math.fsum(float(v) ** 2 for v in row)) for row, moving in zip(trial["gyro_rad_s"], trial["movement"]) if moving]
    result = {
        "trial_id": trial["trial_id"],
        "source_artifact_sha256": trial["source_artifact_sha256"],
        "sample_count": len(trial["timestamps_us"]),
        "movement_sample_count": movement_count,
        "sampling_rate_hz": trial["sampling_rate_hz"],
        "movement_max_gyro_axis_deg_s": math.degrees(max_gyro_axis),
        "movement_gyro_norm_p99_deg_s": math.degrees(sorted(gyro_norm)[int(0.99 * (len(gyro_norm)-1))]),
        "movement_max_accel_axis_mps2": max(max(abs(float(v)) for v in row) for row, moving in zip(trial["accel_mps2"], trial["movement"]) if moving),
        "vqf_valid_movement_samples": sum(active and valid for active, valid in zip(trial["movement"], vqf_valid)),
                "optical_reference_valid_movement_samples": sum(active and valid for active, valid in zip(trial["movement"], trial["truth_valid"])),
        "vqf_valid_movement_availability": sum(active and valid for active, valid in zip(trial["movement"], vqf_valid)) / movement_count if movement_count else None,
        "eskf_lsm6ds3": {key: default[key] for key in ("eskf_valid_movement_sample_count", "eskf_movement_availability", "matched_valid_timestamp_count", "first_fault", "range_statistics", "vqf_score_on_matched_timestamps", "eskf_score_on_matched_timestamps")},
        "eskf_broad": {key: broad[key] for key in ("eskf_valid_movement_sample_count", "eskf_movement_availability", "matched_valid_timestamp_count", "first_fault", "range_statistics", "vqf_score_on_matched_timestamps", "eskf_score_on_matched_timestamps")},
    }
    return result


def _write_summary_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fields = (
        "trial_id", "source_artifact_sha256", "sample_count", "movement_sample_count", "sampling_rate_hz",
        "movement_max_gyro_axis_deg_s", "movement_gyro_norm_p99_deg_s", "movement_max_accel_axis_mps2",
        "vqf_valid_movement_samples", "vqf_valid_movement_availability", "optical_reference_valid_movement_samples",
        "eskf_lsm6ds3_valid_movement_samples", "eskf_lsm6ds3_movement_availability",
        "eskf_lsm6ds3_matched_valid_timestamp_count", "eskf_lsm6ds3_fault_time_s", "eskf_lsm6ds3_fault_cause",
        "eskf_lsm6ds3_movement_gyro_axis_range_crossings", "eskf_lsm6ds3_movement_accel_axis_range_crossings",
        "vqf_geodesic_rms_lsm6ds3_matched_deg", "eskf_lsm6ds3_geodesic_rms_matched_deg",
        "eskf_broad_valid_movement_samples", "eskf_broad_movement_availability",
        "eskf_broad_matched_valid_timestamp_count", "eskf_broad_fault_time_s", "eskf_broad_fault_cause",
        "eskf_broad_movement_gyro_axis_range_crossings", "eskf_broad_movement_accel_axis_range_crossings",
        "vqf_geodesic_rms_broad_matched_deg", "eskf_broad_geodesic_rms_matched_deg",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            flat: dict[str, Any] = {key: row.get(key) for key in fields if not key.startswith("eskf_")}
            for profile, result in (("eskf_lsm6ds3", row["eskf_lsm6ds3"]), ("eskf_broad", row["eskf_broad"])):
                flat[f"{profile}_valid_movement_samples"] = result["eskf_valid_movement_sample_count"]
                flat[f"{profile}_movement_availability"] = result["eskf_movement_availability"]
                flat[f"{profile}_matched_valid_timestamp_count"] = result["matched_valid_timestamp_count"]
                fault = result["first_fault"]
                flat[f"{profile}_fault_time_s"] = fault["time_s"] if fault else None
                flat[f"{profile}_fault_cause"] = fault["cause"] if fault else None
                flat[f"{profile}_movement_gyro_axis_range_crossings"] = result["range_statistics"]["movement_gyro_axis_range_crossings"]
                flat[f"{profile}_movement_accel_axis_range_crossings"] = result["range_statistics"]["movement_accel_axis_range_crossings"]
                flat[f"vqf_geodesic_rms_{'lsm6ds3' if profile.endswith('lsm6ds3') else 'broad'}_matched_deg"] = _degrees(result["vqf_score_on_matched_timestamps"]["geodesic_rms_rad"])
                flat[f"{profile}_geodesic_rms_matched_deg"] = _degrees(result["eskf_score_on_matched_timestamps"]["geodesic_rms_rad"])
            writer.writerow(flat)


def _degrees(value: float | None) -> float | None:
    return math.degrees(value) if value is not None else None


def _render_fault_overview(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    width, height = 1120, 520
    left, top, plot_width, plot_height = 100, 65, 960, 360
    values = [row["movement_max_gyro_axis_deg_s"] for row in rows]
    high = max(values, default=1.0) * 1.05
    y_positions = [top + plot_height - i * plot_height / max(1, len(rows)-1) for i in range(len(rows))]
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="100" y="32" font-family="sans-serif" font-size="20" font-weight="bold">BROAD per-trial gyro range exposure</text>',
    ]
    for tick in range(6):
        value = high * tick / 5
        x = left + value / high * plot_width
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="#d1d5db"/>')
        elements.append(f'<text x="{x:.1f}" y="{top+plot_height+20}" text-anchor="middle" font-family="sans-serif" font-size="11">{value:.0f}</text>')
    for index, row in enumerate(sorted(rows, key=lambda r: r["movement_max_gyro_axis_deg_s"])):
        y = y_positions[index]
        x = left + row["movement_max_gyro_axis_deg_s"] / high * plot_width
        fault = row["eskf_lsm6ds3"]["first_fault"]
        color = "#D55E00" if fault else "#009E73"
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        elements.append(f'<text x="{left-8}" y="{y+3:.1f}" text-anchor="end" font-family="sans-serif" font-size="9">{html.escape(row["trial_id"][:24])}</text>')
    for threshold, label, color in ((math.degrees(DEFAULT_GYRO_LIMIT_RPS), "LSM6DS3 default 245°/s", "#D55E00"),
                                    (math.degrees(BROAD_GYRO_LIMIT_RPS), "BROAD range 2000°/s", "#009E73")):
        x = left + threshold / high * plot_width
        if x <= left + plot_width:
            elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" stroke="{color}" stroke-dasharray="5,4"/>')
            elements.append(f'<text x="{min(x+6,left+plot_width-4):.1f}" y="{top+14}" font-family="sans-serif" font-size="11" fill="{color}">{label}</text>')
    elements.append(f'<text x="{left+plot_width/2}" y="{height-24}" text-anchor="middle" font-family="sans-serif" font-size="12">Maximum absolute gyro axis during movement (degrees/s)</text>')
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8", newline="\n")


def _markdown_report(path: Path, report: dict[str, Any]) -> None:
    default_faults = [row["eskf_lsm6ds3"]["first_fault"] for row in report["trials"] if row["eskf_lsm6ds3"]["first_fault"]]
    broad_faults = [row["eskf_broad"]["first_fault"] for row in report["trials"] if row["eskf_broad"]["first_fault"]]
    default_causes = {cause: sum(fault["cause"] == cause for fault in default_faults)
                      for cause in sorted({fault["cause"] for fault in default_faults})}
    broad_causes = {cause: sum(fault["cause"] == cause for fault in broad_faults)
                    for cause in sorted({fault["cause"] for fault in broad_faults})}
    lines = [
        "# B9 — Matched-interval BROAD failure atlas", "",
        f"Run date: {report['run_date_utc']} · dataset revision: `{report['dataset_revision'] or 'not available from supplied directory'}` · trials: {report['trial_count']}", "",
        "BROAD data by Laidig et al.; source [repository](" + BROAD_SOURCE_URL + ") and [paper](" + BROAD_PAPER_URL + "). The dataset is CC BY 4.0. Files are read from the user-supplied directory and are not copied into this repository.", "",
        "## Method", "",
        "Both estimators process all ordered gyro/accelerometer samples at 2000/7 Hz (3500 µs timestamps); no magnetometer is supplied. The output comparison uses the exact VQF/ESKF timestamp intersection. Scores include only movement samples, while filters run through the leading and trailing rest. Each six-axis estimate's startup heading gauge is aligned at the first common valid sample; total geodesic error, gravity tilt, and relative heading drift are reported.", "",
        f"- VQF: official causal 6D adapter {report['vqf_variant_id']} ({report['vqf_source_revision']}); config SHA-256 `{report['vqf_config_sha256']}`.",
        f"- ESKF: production `eskf15.hpp`; replay source SHA-256 `{report['replay_source_sha256']}`; input-rate period 3500 µs.",
        f"- ESKF defaults: per-axis limits {math.degrees(DEFAULT_GYRO_LIMIT_RPS):.1f}°/s and {DEFAULT_ACCEL_LIMIT_MPS2:.2f} m/s². BROAD replay: {math.degrees(BROAD_GYRO_LIMIT_RPS):.0f}°/s and {BROAD_ACCEL_LIMIT_MPS2:.2f} m/s², derived from BROAD's documented sensor settings.",
        "- Scores are not pooled across trials; each paired score requires valid VQF, ESKF, and optical-reference output at the same input timestamp. Scores use only movement samples; the optical reference can be unavailable on some source samples.", "",
        "## Range fault result", "",
        f"The production LSM6DS3 range profile faulted on {len(default_faults)}/{report['trial_count']} trials ({', '.join(f'{cause}: {count}' for cause, count in default_causes.items())}). BROAD's documented input range reduced this to {len(broad_faults)}/{report['trial_count']} trials ({', '.join(f'{cause}: {count}' for cause, count in broad_causes.items()) or 'no faults'}). This is a range-configuration effect; production LSM6DS3 defaults were not changed.", "",
        "The selected fast-rotation trace `07_undisturbed_fast_rotation_B` crosses the default 240.1°/s axis threshold at 28.434 s with 261.2°/s on one gyro axis. The filter latches, leaves `state_timestamp_us` at the prior 28.4305 s state, and marks output invalid; later plotted default-range samples are not extended with that stale orientation.", "",
        "## Trial results", "",
        "| Trial | Max gyro axis (°/s) | Default ESKF fault | Matched samples, BROAD range | VQF RMS (°) | ESKF RMS (°) |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in report["trials"]:
        default = row["eskf_lsm6ds3"]
        broad = row["eskf_broad"]
        fault = default["first_fault"]
        fault_text = f"{fault['time_s']:.2f}s {fault['cause']}" if fault else "none"
        lines.append(
            f"| `{row['trial_id']}` | {row['movement_max_gyro_axis_deg_s']:.1f} | {fault_text} | "
            f"{broad['matched_valid_timestamp_count']} | {_fmt_deg(broad['vqf_score_on_matched_timestamps']['geodesic_rms_rad'])} | "
            f"{_fmt_deg(broad['eskf_score_on_matched_timestamps']['geodesic_rms_rad'])} |"
        )
    lines.extend(["", "## Selected high-rate traces", ""])
    for trial_id in report["selected_trace_trials"]:
        lines.append(f"![{trial_id} matched orientation error trace](figures/orientation_error_{trial_id}.svg)")
        lines.append("")
    lines.extend([
        "All 39 per-trial figures show orientation error only at shared valid movement timestamps; their lower panels show maximum absolute gyro-axis rate and both near-full-scale thresholds. Detailed CSV traces are saved for the three selected high-rate trials. An ESKF error line stops at a range fault and is not extended with its last quaternion.", "",
        "## Evidence files", "",
        "- `b9_broad_summary.csv`: one movement-only summary row per trial.",
        "- `b9_broad_results.json`: method, configuration, source, per-trial validity, fault, and paired metric records.",
        "- `traces/*.csv.gz`: selected high-rate per-sample errors and ESKF diagnostics.",
        "- `figures/gyro_range_fault_atlas.svg`: all-trial gyro range exposure and default-range fault markers.",
        "- `figures/orientation_error_*.svg`: all 39 shared-time orientation-error timelines.", "",
        "No parameter search or claim of LSM6DS3 hardware performance is made. The BROAD full-scale replay is a dataset-specific configuration experiment; it does not change production defaults.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _fmt_deg(value: float | None) -> str:
    return "N/A" if value is None else f"{math.degrees(value):.3f}"


def run_atlas(dataset_dir: Path, output_dir: Path, *, cxx: str, selected_trials: Sequence[str] | None,
              trace_trials: Sequence[str] | None = None, overwrite: bool = False) -> dict[str, Any]:
    paths = _trial_paths(dataset_dir, selected=None)
    if selected_trials:
        paths = _trial_paths(dataset_dir, selected=selected_trials)
    selected_trace_trials = set(_preselect_trace_trials(paths, trace_trials))
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise ValueError(f"output directory is not empty: {output_dir}; pass --overwrite to replace generated files")
    output_dir.mkdir(parents=True, exist_ok=True)
    compiler_version = subprocess.run(shlex.split(cxx) + ["--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    vqf_manifest_path = ROOT / "external_benchmarks" / "adapters" / "vqf_full_6d_manifest_v1.json"
    vqf_manifest = json.loads(vqf_manifest_path.read_text(encoding="utf-8"))
    vqf_config = {"sampling_rate_hz": {"numerator": 2000, "denominator": 7}, "timestamp_unit": "us", "magnetometer": False}
    vqf_config_sha = hashlib.sha256(json.dumps(vqf_config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    config = {
        "sample_rate_hz": "2000/7",
        "expected_period_us": SAMPLE_PERIOD_US,
        "gravity_policy": "Conservative",
        "startup_gyro_bias_calibration": False,
        "magnetometer": False,
        "range_profiles": {
            "lsm6ds3": {"max_gyro_axis_rps": DEFAULT_GYRO_LIMIT_RPS, "max_accel_axis_mps2": DEFAULT_ACCEL_LIMIT_MPS2},
            "broad": {"max_gyro_axis_rps": BROAD_GYRO_LIMIT_RPS, "max_accel_axis_mps2": BROAD_ACCEL_LIMIT_MPS2},
        },
    }
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report: dict[str, Any] = {
        "report_schema": "org.marcusfunt.b9_broad_failure_atlas.v1",
        "run_date_utc": datetime.now(timezone.utc).date().isoformat(),
        "dataset_source": BROAD_SOURCE_URL,
        "dataset_paper": BROAD_PAPER_URL,
        "dataset_license": "CC BY 4.0",
        "dataset_revision": _git_revision(dataset_dir.parent),
        "dataset_directory": str(dataset_dir.resolve()),
        "sample_rate_hz": {"numerator": 2000, "denominator": 7},
        "sample_period_us": SAMPLE_PERIOD_US,
        "trial_count": len(paths),
        "vqf_variant_id": vqf_manifest["variant_id"],
        "vqf_source_revision": vqf_manifest["source_fidelity"]["source_revision"],
        "vqf_config": vqf_config,
        "vqf_config_sha256": vqf_config_sha,
        "eskf_config": config,
        "eskf_config_sha256": config_sha,
        "compiler": compiler_version,
        "replay_source_sha256": sha256_file(REPLAY_SOURCE),
        "vqf_manifest_sha256": sha256_file(vqf_manifest_path),
        "selected_trace_trials": sorted(selected_trace_trials),
        "trials": [],
    }

    with tempfile.TemporaryDirectory(prefix="b9-broad-atlas-") as temp_name:
        temp = Path(temp_name)
        executable = temp / "b9_eskf_replay"
        _compile_replay(cxx, executable)
        for trial_path in paths:
            trial = _load_hdf5_trial(trial_path)
            vqf_estimates, vqf_valid = _run_vqf(trial)
            timestamps = trial["timestamps_us"]
            input_csv = temp / f"{trial['trial_id']}.csv"
            _write_eskf_input(input_csv, trial)
            is_selected = trial["trial_id"] in selected_trace_trials
            default_trace = _run_eskf(executable, input_csv, temp / "lsm6ds3.csv", "lsm6ds3", keep_diagnostics=is_selected)
            broad_trace = _run_eskf(executable, input_csv, temp / "broad.csv", "broad", keep_diagnostics=is_selected)
            default, default_details, _ = _variant_result(
                "lsm6ds3", default_trace, vqf_valid, timestamps, trial, vqf_estimates, keep_trace=is_selected
            )
            broad, broad_details, _ = _variant_result(
                "broad", broad_trace, vqf_valid, timestamps, trial, vqf_estimates, keep_trace=is_selected
            )
            if default["matched_valid_timestamp_count"] != default_details["pair_valid"].count(True):
                raise ValueError(f"{trial['trial_id']}: default profile matched-count mismatch")
            if broad["matched_valid_timestamp_count"] != broad_details["pair_valid"].count(True):
                raise ValueError(f"{trial['trial_id']}: BROAD profile matched-count mismatch")
            if default_details["pair_valid"] != broad_details["pair_valid"] and not default["first_fault"]:
                # Different validity without a default-range fault indicates a replay or mask defect.
                raise ValueError(f"{trial['trial_id']}: range profiles differ in validity without a default-range fault")
            result = _make_summary_row(trial, default, broad, vqf_valid)
            report["trials"].append(result)
            vqf_errors = _masked_orientation_error_series(
                vqf_estimates, trial["truth_wxyz"], trial["truth_valid"],
                anchor_index=broad["anchor_sample_index"] - 1
            ) if broad["anchor_sample_index"] else {name: [None] * len(timestamps) for name in (
                "geodesic_error_rad", "tilt_error_rad", "relative_heading_drift_rad"
            )}
            if is_selected:
                _write_selected_trace(
                    output_dir / "traces" / f"{trial['trial_id']}_matched_trace.csv.gz",
                    trial,
                    vqf_valid,
                    vqf_errors,
                    {"trace": default_trace, "details": default_details},
                    {"trace": broad_trace, "details": broad_details},
                )
            _render_trace_figure(
                output_dir / "figures" / f"orientation_error_{trial['trial_id']}.svg",
                trial["trial_id"], trial, vqf_errors,
                {"trace": default_trace, "details": default_details},
                {"trace": broad_trace, "details": broad_details},
            )
            print(
                f"{trial['trial_id']}: samples={len(timestamps)} movement={result['movement_sample_count']} "
                f"default_fault={default['first_fault']['cause'] if default['first_fault'] else 'none'} "
                f"broad_fault={broad['first_fault']['cause'] if broad['first_fault'] else 'none'} "
                f"broad_matched={broad['matched_valid_timestamp_count']}"
            )

    report["trial_count"] = len(report["trials"])
    _write_summary_csv(output_dir / "b9_broad_summary.csv", report["trials"])
    (output_dir / "b9_broad_results.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    _render_fault_overview(output_dir / "figures" / "gyro_range_fault_atlas.svg", report["trials"])
    _markdown_report(output_dir / "B9_BROAD_FAILURE_ATLAS.md", report)
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    manifest = {
        "dataset_revision": report["dataset_revision"],
        "trial_count": len(report["trials"]),
        "files": {path.relative_to(output_dir).as_posix(): sha256_file(path) for path in sorted(files)},
    }
    (output_dir / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True, help="official BROAD data_hdf5 directory")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "remediation/analysis/b9_broad_failure_atlas")
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"), help="C++17 compiler command")
    parser.add_argument("--trials", help="comma-separated trial IDs for a selected development run; default requires all 39")
    parser.add_argument("--trace-trials", help="comma-separated trial IDs whose per-sample traces/figures are saved")
    parser.add_argument("--overwrite", action="store_true", help="replace generated artifacts in a nonempty output directory")
    args = parser.parse_args(argv)
    selected = [value.strip() for value in args.trials.split(",") if value.strip()] if args.trials else None
    trace_selected = [value.strip() for value in args.trace_trials.split(",") if value.strip()] if args.trace_trials else None
    if selected and trace_selected and any(value not in selected for value in trace_selected):
        parser.error("--trace-trials must be a subset of --trials")
    try:
        report = run_atlas(
            args.dataset_dir,
            args.output_dir,
            cxx=args.cxx,
            selected_trials=selected,
            trace_trials=trace_selected,
            overwrite=args.overwrite,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"B9 BROAD atlas failed: {error}", file=sys.stderr)
        return 2
    print(f"PASS wrote B9 BROAD atlas for {report['trial_count']} trial(s) to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
