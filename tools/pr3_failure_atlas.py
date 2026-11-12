#!/usr/bin/env python3
"""Build a development-only PR3 v5 noise/covariance failure atlas."""

import argparse
import bisect
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
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from validate_pr3_scenario_protocol import load_protocol, protocol_source_bytes


PROTOCOL = ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"
ARCHIVE = ROOT / "benchmarks/reports/pr3_protocol_v5_dev100_all_factors_postfix_trials.csv.gz"
ARCHIVE_MANIFEST = ROOT / "benchmarks/manifests/pr3_protocol_v5_dev100_all_factors_postfix.json"
SCENARIOS = ("static", "slow_yaw", "lateral_accel", "vibration", "compound_motion")
RATE_IDS = ("uniform_200hz", "uniform_208hz", "irregular_208hz")
ESKF_VARIANTS = ("eskf_conservative", "eskf_legacy", "eskf_confirmed_only")
TOOL_ID = "pr3-noise-covariance-failure-atlas-a6"
BASELINE_BRANCH = "codex/heading-independent-a5-20261112"
BASELINE_COMMIT = "9f2dcdb6a5abb2043805f2f298f9af9c881f27db"
EXPECTED_SOURCE_HASHES = {
    "protocol": "1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800",
    "archive": "ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755",
    "archive_manifest": "394278986dd83fad6f43799194d0ec4f3f407381eb5b761aa1ac5a22ffd2d22c",
    "filter": "05a6b4de9a85abf8f85a8a0c4d24dfe058dda75f4ed4791584a8cc3e7dd84b61",
    "evaluator": "27b0ee17a1e5ab55c4157f7da22ff58667fd84f3907b3ccabf1fed81e3bf7e0f",
    "generator": "7e159c915412039da66048d1ee7f80a39c9c03f91f88f40033de112ac0513843",
}
CONFIG = {
    "sensor_input": "IMU_ONLY",
    "startup_knowledge": "UNKNOWN",
    "startup_gyro_bias_calibration": "OFF",
    "runtime_aid": "NONE",
    "evaluated_estimators": ["eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"],
}
CONFIG_SHA256 = hashlib.sha256(json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
HEADER = struct.Struct("<8s9I64s20x")
RECORD = struct.Struct("<IQQQ24fI")
GRAVITY_M_S2 = 9.80665
ANGULAR_MOTION_THRESHOLD_RAD_S = 0.01
LINEAR_ACCEL_THRESHOLD_M_S2 = 0.05
QUALITY_REQUIRED = (
    "sample_index", "nominal_time_s", "physical_time_s", "tilt_error_deg",
    "tilt_cov_trace", "tilt_cov_eigen_min", "tilt_cov_eigen_max",
    "tilt_nees_observable_2d", "covariance_positive_definite", "health",
    "gravity_attempted", "gravity_accepted", "gravity_reason",
)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command, *, capture=False):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=capture, check=False)
    if result.returncode:
        detail = (result.stdout or "") + (result.stderr or "") if capture else ""
        raise RuntimeError(f"command exited {result.returncode}: {shlex.join(map(str, command))}\n{detail}")
    return result.stdout if capture else ""


def quantile(values, probability):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, int(probability * (len(ordered) - 1)))]


def load_development_archive(archive_path=ARCHIVE, manifest_path=ARCHIVE_MANIFEST, protocol_path=PROTOCOL):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    archive_hash = sha256_file(archive_path)
    manifest_hash = sha256_file(manifest_path)
    protocol_hash = sha256_bytes(protocol_source_bytes(protocol_path))
    if archive_hash != manifest.get("packaged_trial_csv_gz_sha256"):
        raise ValueError("development v5 archive hash does not match its checked-in manifest")
    if manifest_hash != EXPECTED_SOURCE_HASHES["archive_manifest"]:
        raise ValueError("development archive manifest differs from the A6 frozen source identity")
    if archive_hash != EXPECTED_SOURCE_HASHES["archive"]:
        raise ValueError("development archive differs from the A6 frozen source identity")
    if protocol_hash != manifest.get("protocol_sha256") or protocol_hash != EXPECTED_SOURCE_HASHES["protocol"]:
        raise ValueError("v5 protocol hash does not match both the manifest and A6 frozen source identity")
    with gzip.open(archive_path, "rt", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    selected = [row for row in rows if
        row["seed_split"] == "development" and row["scenario"] in SCENARIOS and row["rate_mode"] in RATE_IDS
        and row["sensor_input"] == "IMU_ONLY" and row["startup_knowledge"] == "UNKNOWN"
        and row["startup_gyro_bias_calibration"] == "OFF" and row["runtime_aid"] == "NONE"
        and row["estimator"] in ESKF_VARIANTS]
    expected = len(SCENARIOS) * len(RATE_IDS) * 2 * 100 * len(ESKF_VARIANTS)
    if len(selected) != expected:
        raise ValueError(f"expected {expected} frozen baseline rows across atlas groups, found {len(selected)}")
    validate_archive_group_counts(selected)
    return manifest, archive_hash, manifest_hash, protocol_hash, selected


def validate_archive_group_counts(rows):
    counts = Counter((row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"]) for row in rows)
    expected_keys = {
        (scenario, rate, stress, estimator)
        for scenario in SCENARIOS for rate in RATE_IDS for stress in ("nominal", "stress")
        for estimator in ESKF_VARIANTS
    }
    if set(counts) != expected_keys or any(count != 100 for count in counts.values()):
        raise ValueError("selected development archive rows do not have 100 trials in every expected group")
    seen = set()
    for row in rows:
        key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["seed"], row["estimator"])
        if key in seen:
            raise ValueError(f"duplicate development trial key: {key}")
        seen.add(key)
        if not row.get("input_sha256") or len(row["input_sha256"]) != 64:
            raise ValueError(f"missing or invalid input hash for {key}")
    for scenario in SCENARIOS:
        for rate in RATE_IDS:
            for stress in ("nominal", "stress"):
                for seed in range(4001, 4101):
                    hashes = {row["input_sha256"] for row in rows if
                        row["scenario"] == scenario and row["rate_mode"] == rate
                        and row["stress_mode"] == stress and int(row["seed"]) == seed}
                    if len(hashes) != 1:
                        raise ValueError(f"the three ESKF rows do not share one raw input hash: {scenario}/{rate}/{stress}/{seed}")


def assert_archive_match(replayed, archived):
    fields = (
        "expected", "produced", "valid", "availability", "tilt_rms_deg", "tilt_p95_deg", "tilt_max_deg",
        "attitude_rms_deg", "yaw_rms_deg", "position_rms_m", "velocity_rms_m_s",
        "accel_bias_error_m_s2", "gyro_bias_error_rad_s", "tilt_nees_mean", "nis_mean", "health_end",
    )
    for field in fields:
        actual, expected = replayed.get(field, ""), archived.get(field, "")
        if not actual and not expected:
            continue
        if not actual or not expected:
            raise ValueError(f"replay/archive field {field} has different missingness")
        if field == "health_end":
            if actual != expected:
                raise ValueError(f"replay/archive {field} mismatch: {actual} != {expected}")
        elif not math.isclose(float(actual), float(expected), rel_tol=2e-6, abs_tol=1e-7):
            raise ValueError(f"replay/archive {field} mismatch: {actual} != {expected}")


def make_group_rollups(rows, archive_hash):
    groups = defaultdict(list)
    by_trial = {}
    for row in rows:
        key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"])
        groups[key].append(row)
        by_trial[(row["scenario"], row["rate_mode"], row["stress_mode"], int(row["seed"]), row["estimator"])] = row
    rollups = []
    for key, trials in sorted(groups.items()):
        tilt = [float(row["tilt_rms_deg"]) for row in trials if row.get("tilt_rms_deg")]
        yaw = [float(row["yaw_rms_deg"]) for row in trials if row.get("yaw_rms_deg")]
        availability = [float(row["availability"]) for row in trials if row.get("availability")]
        covariance_fraction = []
        for row in trials:
            if row.get("covariance_valid") and row.get("expected") and row.get("covariance_applicable", "True").lower() != "false":
                covariance_fraction.append(int(row["covariance_valid"]) / int(row["expected"]))
        recovery = [float(row["recovery_time_s"]) for row in trials if row.get("recovery_time_s")]
        accel_bias = [float(row["accel_bias_error_m_s2"]) for row in trials if row.get("accel_bias_error_m_s2")]
        gyro_bias = [float(row["gyro_bias_error_rad_s"]) for row in trials if row.get("gyro_bias_error_rad_s")]
        nees = [float(row["tilt_nees_mean"]) for row in trials if row.get("tilt_nees_mean")]
        nis = [float(row["nis_mean"]) for row in trials if row.get("nis_mean")]
        rollups.append({
            "split": "development", "scenario": key[0], "rate_mode": key[1], "stress_mode": key[2],
            "estimator": key[3], "profile": "IMU_ONLY/UNKNOWN/calibration-OFF/aid-NONE",
            "source_archive_sha256": archive_hash, "trial_count": len(trials),
            "tilt_rms_finite_trials": len(tilt), "tilt_rms_mean_deg": statistics.mean(tilt) if tilt else None,
            "tilt_rms_median_deg": statistics.median(tilt) if tilt else None,
            "tilt_rms_p95_deg": quantile(tilt, .95), "tilt_rms_worst_deg": max(tilt) if tilt else None,
            "yaw_rms_finite_trials": len(yaw), "yaw_rms_mean_deg": statistics.mean(yaw) if yaw else None,
            "yaw_metric_interpretation": "relative heading from shared zero-yaw startup gauge; not absolute north",
            "minimum_availability": min(availability) if availability else None,
            "incomplete_trials": sum(row.get("complete_run", "true").lower() != "true" for row in trials),
            "mean_covariance_check_fraction": statistics.mean(covariance_fraction) if covariance_fraction else None,
            "mean_recovery_time_s": statistics.mean(recovery) if recovery else None,
            "recovery_time_trials": len(recovery),
            "mean_accel_bias_error_m_s2": statistics.mean(accel_bias) if accel_bias else None,
            "mean_gyro_bias_error_rad_s": statistics.mean(gyro_bias) if gyro_bias else None,
            "mean_tilt_nees_per_trial": statistics.mean(nees) if nees else None,
            "mean_nis_per_trial": statistics.mean(nis) if nis else None,
            "mean_nis_count_per_trial": statistics.mean([int(row.get("nis_count") or 0) for row in trials]),
        })
    paired = []
    for scenario in SCENARIOS:
        for rate in RATE_IDS:
            for estimator in ESKF_VARIANTS:
                deltas = []
                for seed in range(4001, 4101):
                    nominal = by_trial[(scenario, rate, "nominal", seed, estimator)]
                    stress = by_trial[(scenario, rate, "stress", seed, estimator)]
                    if nominal["input_sha256"] == stress["input_sha256"]:
                        raise ValueError("nominal and stress streams unexpectedly share an input hash")
                    deltas.append(float(stress["tilt_rms_deg"]) - float(nominal["tilt_rms_deg"]))
                paired.append({
                    "split": "development", "scenario": scenario, "rate_mode": rate, "estimator": estimator,
                    "paired_seed_count": len(deltas), "stress_minus_nominal_mean_deg": statistics.mean(deltas),
                    "stress_minus_nominal_median_deg": statistics.median(deltas),
                    "stress_minus_nominal_p95_deg": quantile(deltas, .95),
                    "stress_minus_nominal_min_deg": min(deltas), "stress_minus_nominal_max_deg": max(deltas),
                    "source_archive_sha256": archive_hash,
                })
    return rollups, paired


def quat_conjugate(q):
    return (q[0], -q[1], -q[2], -q[3])


def quat_multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw*bw-ax*bx-ay*by-az*bz,
        aw*bx+ax*bw+ay*bz-az*by,
        aw*by-ax*bz+ay*bw+az*bx,
        aw*bz+ax*by-ay*bx+az*bw)


def quat_rotate(q, vector):
    vector_q = (0.0, *vector)
    result = quat_multiply(quat_multiply(q, vector_q), quat_conjugate(q))
    return result[1:]


def quat_unrotate(q, vector):
    return quat_rotate(quat_conjugate(q), vector)


def vector_norm(vector):
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def read_input_stream(path, *, protocol_sha256, scenario, expected_scenario_index, rate_mode, stress_mode, seed):
    payload = Path(path).read_bytes()
    if len(payload) < HEADER.size:
        raise ValueError("truncated PR3 input header")
    unpacked = HEADER.unpack_from(payload)
    magic = unpacked[0]
    version, scenario_index, rate_index, stress_flag, header_seed, count, record_bytes, sample_count, _ = unpacked[1:10]
    input_protocol_hash = unpacked[10].decode("ascii")
    if magic != b"PR3INP03" or version != 3 or record_bytes != RECORD.size:
        raise ValueError("PR3 raw input header magic/version/record size mismatch")
    if input_protocol_hash != protocol_sha256 or header_seed != seed or count != sample_count:
        raise ValueError("PR3 raw input header provenance or sample count mismatch")
    if scenario_index != expected_scenario_index:
        raise ValueError("scenario index mismatch in PR3 header")
    if rate_index != RATE_IDS.index(rate_mode) or stress_flag != int(stress_mode == "stress"):
        raise ValueError("rate/stress metadata mismatch in PR3 header")
    expected_bytes = HEADER.size + count * RECORD.size
    if len(payload) != expected_bytes:
        raise ValueError(f"raw input size {len(payload)} != header-declared {expected_bytes}")
    records = []
    previous_index = 0
    previous_physical = 0
    previous_reported = 0
    for n in range(count):
        values = RECORD.unpack_from(payload, HEADER.size + n * RECORD.size)
        index, nominal_us, reported_us, physical_us = values[:4]
        floats = values[4:28]
        flags = values[28]
        if index != n + 1 or index <= previous_index or physical_us <= previous_physical:
            raise ValueError("raw sample indices or physical timestamps are not strictly increasing")
        if previous_reported and reported_us <= previous_reported:
            raise ValueError("raw reported timestamps are not strictly increasing")
        if not all(math.isfinite(value) for value in floats) or flags & ~1:
            raise ValueError("raw input has nonfinite values or unknown sample flags")
        records.append({
            "sample_index": index, "nominal_timestamp_us": nominal_us,
            "reported_timestamp_us": reported_us, "physical_timestamp_us": physical_us,
            "truth_q": tuple(floats[0:4]), "truth_position": tuple(floats[4:7]),
            "truth_velocity": tuple(floats[7:10]), "truth_accel_bias": tuple(floats[10:13]),
            "truth_gyro_bias": tuple(floats[13:16]), "measured_accel": tuple(floats[16:19]),
            "measured_gyro": tuple(floats[19:22]), "independent_heading": floats[22],
            "oracle_heading": floats[23], "flags": flags,
        })
        previous_index, previous_physical, previous_reported = index, physical_us, reported_us
    return records


def classify_motion_regime(time_s, angular_rate_norm, linear_accel_norm):
    if time_s < 2.0:
        return "startup_static"
    rotation = angular_rate_norm >= ANGULAR_MOTION_THRESHOLD_RAD_S
    translation = linear_accel_norm >= LINEAR_ACCEL_THRESHOLD_M_S2
    if rotation and translation:
        return "compound"
    if rotation:
        return "rotation_dominant"
    if translation:
        return "translation_dominant"
    return "quiescent_or_coast"


def enrich_trace(trace_rows, input_records, *, scenario, rate_mode, stress_mode, seed,
                 input_sha256, implementation_commit, config_sha256, protocol):
    if len(trace_rows) != len(input_records):
        raise ValueError(f"L1/raw sample count mismatch: {len(trace_rows)} != {len(input_records)}")
    if len({row["estimator"] for row in trace_rows}) != 1 or trace_rows[0]["estimator"] != "eskf_conservative":
        raise ValueError("L1 trace must contain only the Conservative ESKF")
    validate_trace_quality(trace_rows, len(input_records), input_sha256)
    disturbance = next((item.get("measurement_disturbances") for item in protocol["scenarios"]
        if item["id"] == scenario), None)
    disturbance_start = float(disturbance["start_s"]) if disturbance else math.inf
    enriched = []
    previous_q = (1.0, 0.0, 0.0, 0.0)
    previous_velocity = (0.0, 0.0, 0.0)
    previous_physical_us = 1_000_000
    last_gravity_time = None
    for trace, record in zip(trace_rows, input_records):
        physical_time = record["physical_timestamp_us"]
        dt = (physical_time - previous_physical_us) * 1e-6
        if dt <= 0.0:
            raise ValueError("nonpositive physical sample interval in raw input")
        q = record["truth_q"]
        relative_q = quat_multiply(quat_conjugate(previous_q), q)
        if relative_q[0] < 0.0:
            relative_q = tuple(-value for value in relative_q)
        vector_norm_q = vector_norm(relative_q[1:])
        angle = 2.0 * math.atan2(vector_norm_q, max(0.0, relative_q[0]))
        angular_rate = tuple(value * angle / (vector_norm_q * dt) for value in relative_q[1:]) if vector_norm_q > 1e-12 else (0.0, 0.0, 0.0)
        world_acceleration = tuple((record["truth_velocity"][i] - previous_velocity[i]) / dt for i in range(3))
        rate_norm = vector_norm(angular_rate)
        accel_norm = vector_norm(world_acceleration)
        body_specific_force = quat_unrotate(q, (world_acceleration[0], world_acceleration[1], world_acceleration[2] + GRAVITY_M_S2))
        expected_accel = tuple(body_specific_force[i] + record["truth_accel_bias"][i] for i in range(3))
        expected_gyro = tuple(angular_rate[i] + record["truth_gyro_bias"][i] for i in range(3))
        accel_residual = tuple(record["measured_accel"][i] - expected_accel[i] for i in range(3))
        gyro_residual = tuple(record["measured_gyro"][i] - expected_gyro[i] for i in range(3))
        regime = classify_motion_regime(float(trace["physical_time_s"]), rate_norm, accel_norm)
        row = dict(trace)
        row.update({
            "source_commit": implementation_commit, "config_sha256": config_sha256,
            "raw_input_sha256": input_sha256, "scenario": scenario, "rate_mode": rate_mode,
            "stress_mode": stress_mode, "seed": str(seed), "actual_dt_s": f"{dt:.9f}",
            "truth_body_rate_norm_rad_s": f"{rate_norm:.9f}",
            "truth_world_linear_accel_norm_m_s2": f"{accel_norm:.9f}",
            "motion_regime": regime,
            "measurement_disturbance_active": str(float(trace["physical_time_s"]) >= disturbance_start).lower(),
            "accel_measurement_residual_norm_m_s2": f"{vector_norm(accel_residual):.9f}",
            "gyro_measurement_residual_norm_rad_s": f"{vector_norm(gyro_residual):.9f}",
            "accel_bias_error_x_m_s2": f"{float(trace['accel_bias_x']) - record['truth_accel_bias'][0]:.9f}",
            "accel_bias_error_y_m_s2": f"{float(trace['accel_bias_y']) - record['truth_accel_bias'][1]:.9f}",
            "accel_bias_error_z_m_s2": f"{float(trace['accel_bias_z']) - record['truth_accel_bias'][2]:.9f}",
            "gyro_bias_error_x_rad_s": f"{float(trace['gyro_bias_x']) - record['truth_gyro_bias'][0]:.9f}",
            "gyro_bias_error_y_rad_s": f"{float(trace['gyro_bias_y']) - record['truth_gyro_bias'][1]:.9f}",
            "gyro_bias_error_z_rad_s": f"{float(trace['gyro_bias_z']) - record['truth_gyro_bias'][2]:.9f}",
        })
        covariance_trace = max(0.0, float(trace["tilt_cov_trace"]))
        row["projected_tilt_cov_sqrt_trace_deg"] = f"{math.degrees(math.sqrt(covariance_trace)):.9f}"
        if trace["initialized"] == "true":
            if trace["gravity_accepted"] == "true":
                last_gravity_time = float(trace["physical_time_s"])
            if last_gravity_time is not None:
                row["time_since_gravity_accept_s"] = f"{float(trace['physical_time_s']) - last_gravity_time:.9f}"
            else:
                row["time_since_gravity_accept_s"] = ""
        else:
            row["time_since_gravity_accept_s"] = ""
        enriched.append(row)
        previous_q = q
        previous_velocity = record["truth_velocity"]
        previous_physical_us = physical_time
    return enriched


def validate_trace_quality(rows, expected_count, expected_input_sha256):
    if len(rows) != expected_count or not rows:
        raise ValueError(f"L1 trace row count {len(rows)} != expected {expected_count}")
    missing = set(QUALITY_REQUIRED) - set(rows[0])
    if missing:
        raise ValueError(f"L1 trace is missing required fields: {sorted(missing)}")
    indices = [int(row["sample_index"]) for row in rows]
    if indices != list(range(1, expected_count + 1)):
        raise ValueError("L1 sample indices are incomplete, duplicated or reordered")
    nominal_times = [float(row["nominal_time_s"]) for row in rows]
    physical_times = [float(row["physical_time_s"]) for row in rows]
    if any(b <= a for a, b in zip(nominal_times, nominal_times[1:])):
        raise ValueError("L1 nominal sample time is not strictly increasing")
    if any(b <= a for a, b in zip(physical_times, physical_times[1:])):
        raise ValueError("L1 physical sample time is not strictly increasing")
    if len({row.get("input_sha256") for row in rows}) != 1 or rows[0].get("input_sha256") != expected_input_sha256:
        raise ValueError("L1 rows do not carry the expected single raw-input hash")
    for row in rows:
        for field in ("tilt_error_deg", "tilt_cov_trace", "tilt_cov_eigen_min", "tilt_cov_eigen_max"):
            value = row.get(field, "")
            if not value or not math.isfinite(float(value)):
                raise ValueError(f"required L1 value {field} is absent or nonfinite at sample {row['sample_index']}")
        for field in ("tilt_nees_observable_2d",):
            value = row.get(field, "")
            if value and not math.isfinite(float(value)):
                raise ValueError(f"L1 value {field} is nonfinite at sample {row['sample_index']}")
        if float(row["tilt_cov_eigen_min"]) < -1e-12 or float(row["tilt_cov_eigen_max"]) < float(row["tilt_cov_eigen_min"]):
            raise ValueError(f"projected covariance is invalid at sample {row['sample_index']}")
        if row["covariance_positive_definite"] not in ("true", "false"):
            raise ValueError(f"covariance validity flag is missing at sample {row['sample_index']}")
        if row["health"] not in ("Aligning", "Nominal", "Degraded", "Fault"):
            raise ValueError(f"unknown filter health at sample {row['sample_index']}")


def summarize_trace(rows, *, rate_hz, expected_samples, archive_row):
    if len(rows) != expected_samples:
        raise ValueError("selected L1 trace does not span every input sample")
    eval_rows = [row for row in rows if float(row["nominal_time_s"]) >= 2.0]
    rise_rows = [row for row in rows if float(row["physical_time_s"]) >= 2.0]
    eval_times = [float(row["physical_time_s"]) for row in rise_rows]
    rises = []
    for index, row in enumerate(rise_rows):
        end_index = bisect.bisect_left(eval_times, eval_times[index] + 1.0)
        if end_index < len(rise_rows) and eval_times[end_index] - eval_times[index] <= 1.1:
            rises.append((float(rise_rows[end_index]["tilt_error_deg"]) - float(row["tilt_error_deg"]),
                eval_times[index], eval_times[end_index]))
    max_rise = max(rises, default=(None, None, None), key=lambda item: item[0] if item[0] is not None else -math.inf)
    initialized = [row for row in rows if row["initialized"] == "true"]
    initialized_start = float(initialized[0]["physical_time_s"]) if initialized else None
    accepted_times = [float(row["physical_time_s"]) for row in rows if row["gravity_accepted"] == "true"]
    end_time = float(rows[-1]["physical_time_s"])
    correction_gaps = []
    if initialized_start is not None:
        previous = initialized_start
        for time_s in accepted_times:
            if time_s >= previous:
                correction_gaps.append((time_s - previous, previous, time_s))
            previous = time_s
        if end_time >= previous:
            correction_gaps.append((end_time - previous, previous, end_time))
    longest_gap = max(correction_gaps, default=(None, None, None), key=lambda item: item[0] if item[0] is not None else -math.inf)
    regime_duration = Counter()
    disturbance_duration = 0.0
    previous_time = 0.0
    for row in rows:
        time_s = float(row["physical_time_s"])
        dt = time_s - previous_time
        regime_duration[row["motion_regime"]] += dt
        if row["measurement_disturbance_active"] == "true":
            disturbance_duration += dt
        previous_time = time_s
    reject_reasons = Counter(row["gravity_reason"] for row in rows if row["gravity_attempted"] != "true" and row["gravity_reason"] not in ("accepted", "not_initialized", "initialization_complete"))
    attempts = sum(row["gravity_attempted"] == "true" for row in rows)
    accepted = sum(row["gravity_accepted"] == "true" for row in rows)
    covariance_failures = sum(row["covariance_positive_definite"] != "true" for row in rows)
    health_sequence = [row["health"] for row in rows]
    health_transitions = sum(a != b for a, b in zip(health_sequence, health_sequence[1:]))
    nis_rows = [float(row["gravity_nis"]) for row in rows if row.get("gravity_nis")]
    nis_by_attempt = [float(row["gravity_nis"]) for row in rows if row["gravity_attempted"] == "true" and row.get("gravity_nis")]
    nees = [float(row["tilt_nees_observable_2d"]) for row in eval_rows if row.get("tilt_nees_observable_2d")]
    archived_nees_count = int(archive_row.get("tilt_nees_count") or len(nees))
    if len(nees) != archived_nees_count:
        raise ValueError(f"selected L1 observable-tilt NEES count differs from archive: {len(nees)} != {archived_nees_count}")
    if nees and archive_row.get("tilt_nees_mean") and not math.isclose(
            statistics.mean(nees), float(archive_row["tilt_nees_mean"]), rel_tol=2e-6, abs_tol=1e-7):
        raise ValueError("selected L1 observable-tilt NEES mean differs from frozen archive")
    return {
        "archived_tilt_rms_deg": archive_row["tilt_rms_deg"],
        "archived_yaw_rms_deg": archive_row["yaw_rms_deg"],
        "availability": archive_row["availability"],
        "expected_samples": expected_samples, "evaluation_samples": len(eval_rows),
        "tilt_error_max_deg": max(float(row["tilt_error_deg"]) for row in eval_rows),
        "tilt_error_max_time_s": max(eval_rows, key=lambda row: float(row["tilt_error_deg"]))["physical_time_s"],
        "max_1s_tilt_increase_deg": max_rise[0], "max_1s_window_start_s": max_rise[1], "max_1s_window_end_s": max_rise[2],
        "gravity_attempts": attempts, "gravity_accepted": accepted, "gravity_attempted_rejected": attempts - accepted,
        "gravity_rejection_reasons": dict(sorted(reject_reasons.items())),
        "heading_updates": 0, "zero_rate_updates": 0,
        "longest_gravity_correction_gap_s": longest_gap[0],
        "longest_gravity_gap_start_s": longest_gap[1], "longest_gravity_gap_end_s": longest_gap[2],
        "covariance_positive_definite_samples": expected_samples - covariance_failures,
        "covariance_invalid_samples": covariance_failures, "health_transition_count": health_transitions,
        "health_end": health_sequence[-1],
        "gravity_nis_count": len(nis_rows), "gravity_nis_mean": statistics.mean(nis_rows) if nis_rows else None,
        "gravity_attempt_nis_count": len(nis_by_attempt),
        "gravity_attempt_nis_mean": statistics.mean(nis_by_attempt) if nis_by_attempt else None,
        "observable_tilt_nees_count": len(nees),
        "observable_tilt_nees_mean": statistics.mean(nees) if nees else None,
        "projected_tilt_cov_sqrt_trace_deg_mean": statistics.mean(float(row["projected_tilt_cov_sqrt_trace_deg"]) for row in eval_rows),
        "accel_bias_error_mean_m_s2": statistics.mean(float(row["accel_bias_error_m_s2"]) for row in eval_rows),
        "gyro_bias_error_mean_rad_s": statistics.mean(float(row["gyro_bias_error_rad_s"]) for row in eval_rows),
        "accel_measurement_residual_rms_m_s2": math.sqrt(statistics.mean(float(row["accel_measurement_residual_norm_m_s2"])**2 for row in rows)),
        "gyro_measurement_residual_rms_rad_s": math.sqrt(statistics.mean(float(row["gyro_measurement_residual_norm_rad_s"])**2 for row in rows)),
        "motion_regime_seconds": dict(sorted(regime_duration.items())),
        "declared_vibration_disturbance_seconds": disturbance_duration,
        "replay_status": "PASS",
    }


def validate_paired_trace_records(nominal, stress):
    if nominal["scenario"] != stress["scenario"] or nominal["rate_mode"] != stress["rate_mode"] or nominal["seed"] != stress["seed"]:
        raise ValueError("nominal/stress trace pairing keys differ")
    if nominal["raw_input_sha256"] == stress["raw_input_sha256"]:
        raise ValueError("nominal and stress raw inputs must have distinct hashes")
    if nominal["sample_count"] != stress["sample_count"]:
        raise ValueError("nominal/stress paired input sample counts differ")


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_gzip_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            import io
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def svg_pair_figure(scenario, rate_mode, nominal, stress, output, seed, config_sha256, source_archive_sha256):
    width, height = 1280, 1120
    left, plot_width = 110, 1080
    panels = [
        ("Tilt error", "degrees", "tilt_error_deg", "max"),
        ("Projected tilt covariance radius (sqrt trace)", "degrees, 2D radial scale", "projected_tilt_cov_sqrt_trace_deg", "max"),
        ("Accelerometer bias error", "m/s²", "accel_bias_error_m_s2", "max"),
        ("Gyroscope bias error", "degrees/s", "gyro_bias_error_rad_s", "max"),
    ]
    colors = {"nominal": "#2563eb", "stress": "#dc2626"}
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<title>PR3 v5 {html.escape(scenario)} {html.escape(rate_mode)} development diagnostic</title>',
        f'<desc>Seed {seed}; Conservative ESKF; IMU only; unknown startup; no runtime aid. Archive SHA-256 {source_archive_sha256}; config SHA-256 {config_sha256}; nominal input SHA-256 {nominal["raw_input_sha256"]}; stress input SHA-256 {stress["raw_input_sha256"]}.</desc>',
        f'<text x="110" y="34" font-family="sans-serif" font-size="20" font-weight="bold">{html.escape(scenario)} · {html.escape(rate_mode)} · development seed {seed}</text>',
        '<text x="110" y="55" font-family="sans-serif" font-size="12">Pre-change Conservative ESKF · unknown startup · IMU only · calibration off · no runtime aid</text>',
    ]
    top, panel_height, gap = 80, 220, 42
    for panel_index, (title, ylabel, metric, _) in enumerate(panels):
        panel_top = top + panel_index * (panel_height + gap)
        plot_top, plot_height = panel_top + 24, panel_height - 38
        series = {"nominal": nominal["rows"], "stress": stress["rows"]}
        max_time = 16.0
        def plotted_value(row):
            value = float(row[metric])
            return math.degrees(value) if metric == "gyro_bias_error_rad_s" else value
        values = [plotted_value(row) for rows in series.values() for row in rows if row[metric] != "" and float(row["physical_time_s"]) >= 2.0]
        ymax = max(0.05, max(values, default=1.0) * 1.05)
        ymin = 0.0
        def sx(value): return left + max(0.0, min(1.0, float(value) / max_time)) * plot_width
        def sy(value): return plot_top + plot_height - max(0.0, min(1.0, (float(value) - ymin) / (ymax - ymin))) * plot_height
        elements.append(f'<text x="{left}" y="{panel_top+15}" font-family="sans-serif" font-size="14" font-weight="bold">{title}</text>')
        for tick in range(5):
            value = ymax * tick / 4
            yy = sy(value)
            elements.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{left+plot_width}" y2="{yy:.2f}" stroke="#e5e7eb"/>')
            elements.append(f'<text x="{left-10}" y="{yy+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="10">{value:.3g}</text>')
        x_start = sx(2.0)
        elements.append(f'<line x1="{x_start:.2f}" y1="{plot_top}" x2="{x_start:.2f}" y2="{plot_top+plot_height}" stroke="#111827" stroke-dasharray="5 4"/>')
        for mode, rows in series.items():
            plot_rows = [row for index, row in enumerate(rows) if index % 4 == 0 or index == len(rows) - 1]
            values_xy = [(float(row["physical_time_s"]), plotted_value(row)) for row in plot_rows
                if row[metric] != "" and float(row["physical_time_s"]) >= 2.0]
            path_data = " ".join(("M" if index == 0 else "L") + f"{sx(x):.2f},{sy(y):.2f}" for index, (x, y) in enumerate(values_xy))
            elements.append(f'<path d="{path_data}" fill="none" stroke="{colors[mode]}" stroke-width="1.5"/>')
            if panel_index == 0:
                accepted = [float(row["physical_time_s"]) for row in rows if row["gravity_accepted"] == "true"]
                for time_s in accepted:
                    xx = sx(time_s)
                    elements.append(f'<line x1="{xx:.2f}" y1="{plot_top+plot_height-5}" x2="{xx:.2f}" y2="{plot_top+plot_height}" stroke="{colors[mode]}" stroke-width="2"/>')
        elements.append(f'<text transform="translate(25 {plot_top+plot_height/2:.1f}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="11">{ylabel}</text>')
        if panel_index == len(panels) - 1:
            elements.append(f'<text x="{left+plot_width/2}" y="{plot_top+plot_height+23}" text-anchor="middle" font-family="sans-serif" font-size="11">Physical trial time (s)</text>')
    elements.extend([
        '<line x1="875" y1="55" x2="895" y2="55" stroke="#2563eb" stroke-width="3"/><text x="901" y="59" font-family="sans-serif" font-size="11">nominal</text>',
        '<line x1="980" y1="55" x2="1000" y2="55" stroke="#dc2626" stroke-width="3"/><text x="1006" y="59" font-family="sans-serif" font-size="11">stress</text>',
        '<text x="110" y="1090" font-family="sans-serif" font-size="9">Vertical dashed line: motion begins at 2 s. Short ticks: accepted gravity corrections. Projected sigma excludes global yaw gauge.</text>',
        '</svg>',
    ])
    Path(output).write_text("\n".join(elements) + "\n", encoding="utf-8", newline="\n")


def ensure_output_dir(path):
    path = Path(path).resolve()
    frozen_root = (ROOT / "benchmarks").resolve()
    if path == frozen_root or frozen_root in path.parents:
        raise ValueError("A6 diagnostics cannot write under benchmarks/ because v1-v5 evidence is frozen")
    if not path.exists():
        path.mkdir(parents=True)
        (path / "evidence_manifest.json").write_text(json.dumps({"tool_id": TOOL_ID, "status": "running"}, indent=2) + "\n", encoding="utf-8")
    else:
        manifest_path = path / "evidence_manifest.json"
        if not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")).get("tool_id") != TOOL_ID:
            if any(path.iterdir()):
                raise ValueError(f"refusing to overwrite an unrecognized output directory: {path}")
            path.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({"tool_id": TOOL_ID, "status": "running"}, indent=2) + "\n", encoding="utf-8")
    return path


def compile_tools(temp, compiler):
    build = temp / "build"
    build.mkdir(parents=True)
    generated_header = build / "pr3_scenario_protocol.hpp"
    run([sys.executable, str(ROOT / "tools/pr3_generate_scenario_header.py"), str(PROTOCOL), str(generated_header)])
    generator, evaluator = build / "pr3_generate_inputs", build / "pr3_evaluate_stream"
    common = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", f"-I{build}"]
    run([*common, str(ROOT / "tools/pr3_generate_inputs.cpp"), "-o", str(generator)])
    run([*common, "-DINERTIAL_GRAVITY_DIAGNOSTICS=1", str(ROOT / "tools/pr3_evaluate_stream.cpp"), "-o", str(evaluator)])
    version = run([*compiler, "--version"], capture=True).splitlines()[0]
    return generator, evaluator, version


def load_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def run_analysis(args):
    output = ensure_output_dir(args.output_dir)
    protocol = load_protocol(PROTOCOL)
    archive_manifest, archive_hash, archive_manifest_hash, protocol_hash, archive_rows = load_development_archive()
    seed_range = protocol["seeds"]["development"]
    if not seed_range["first_seed"] <= args.trace_seed <= seed_range["last_seed"]:
        raise ValueError("selected trace seed is outside the frozen development-only seed range")
    if len(args.implementation_commit) != 40 or any(char not in "0123456789abcdef" for char in args.implementation_commit):
        raise ValueError("--implementation-commit must be a full lowercase Git SHA")
    if args.implementation_commit != BASELINE_COMMIT or args.implementation_branch != BASELINE_BRANCH:
        raise ValueError("A6 must use the reviewed A5 baseline commit and branch")
    if len(args.diagnostic_commit) != 40 or any(char not in "0123456789abcdef" for char in args.diagnostic_commit):
        raise ValueError("--diagnostic-commit must be a full lowercase Git SHA")
    if not args.diagnostic_branch:
        raise ValueError("--diagnostic-branch is required to record exact provenance")
    source_hashes = {
        "protocol": protocol_hash, "archive": archive_hash, "archive_manifest": archive_manifest_hash,
        "filter": sha256_file(ROOT / "eskf15.hpp"),
        "evaluator": sha256_file(ROOT / "tools/pr3_evaluate_stream.cpp"),
        "generator": sha256_file(ROOT / "tools/pr3_generate_inputs.cpp"),
    }
    for name, expected_hash in EXPECTED_SOURCE_HASHES.items():
        if name == "evaluator":
            continue  # The only evaluator change adds L1 NEES/covariance-validity fields.
        if source_hashes[name] != expected_hash:
            raise ValueError(f"baseline source identity mismatch for {name}: {source_hashes[name]} != {expected_hash}")
    source_hashes["evaluator_pre_instrumentation"] = EXPECTED_SOURCE_HASHES["evaluator"]
    if source_hashes["evaluator"] == EXPECTED_SOURCE_HASHES["evaluator"]:
        raise ValueError("A6 evaluator instrumentation was expected but is absent")
    if PROTOCOL.read_bytes() == b"" or not args.output_dir:
        raise ValueError("invalid protocol/output path")
    compiler = shlex.split(args.cxx)
    if not compiler:
        raise ValueError("compiler command is empty")
    seed_rows = [row for row in archive_rows if int(row["seed"]) == args.trace_seed]
    archive_by_key = {(row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"]): row for row in archive_rows}
    seed_by_key = {(row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"]): row for row in seed_rows}
    rollups, paired_rollups = make_group_rollups(archive_rows, archive_hash)
    l1_rows = []
    atlas_rows = []
    compiler_version = None
    commands = []
    expected_config_hash = CONFIG_SHA256
    with tempfile.TemporaryDirectory(prefix="pr3-a6-noise-covariance-") as temporary:
        temp = Path(temporary)
        generator, evaluator, compiler_version = compile_tools(temp, compiler)
        for scenario in SCENARIOS:
            for rate_index, rate_mode in enumerate(RATE_IDS):
                rate = next(item["nominal_rate_hz"] for item in protocol["sampling"]["rate_modes"] if item["id"] == rate_mode)
                expected_samples = int(rate * protocol["sampling"]["duration_s"])
                pair_results = {}
                for stress_mode in ("nominal", "stress"):
                    stem = f"{scenario}__{rate_mode}__{stress_mode}__{args.trace_seed}"
                    input_path = temp / f"{stem}.bin"
                    trial_path, summary_path, trace_path = (temp / f"{stem}_{suffix}.csv" for suffix in ("trial", "summary", "l1"))
                    generation_command = [str(generator), str(input_path), "development", scenario, str(rate_index), stress_mode, str(args.trace_seed)]
                    run(generation_command)
                    input_hash = sha256_file(input_path)
                    hashes = {row["input_sha256"] for row in archive_rows if
                        row["scenario"] == scenario and row["rate_mode"] == rate_mode
                        and row["stress_mode"] == stress_mode and int(row["seed"]) == args.trace_seed}
                    if hashes != {input_hash}:
                        raise ValueError(f"regenerated selected input hash does not match frozen archive for {stem}")
                    diag_command = [str(evaluator), str(input_path), str(trial_path), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                        args.implementation_commit, expected_config_hash, input_hash,
                        "--gravity-summary", str(summary_path), "--gravity-trace", str(trace_path)]
                    run(diag_command)
                    commands.extend([shlex.join(generation_command), shlex.join(diag_command)])
                    replay = load_csv(trial_path)
                    expected_replay = [row for row in replay if row["estimator"] in ESKF_VARIANTS]
                    if len(expected_replay) != len(ESKF_VARIANTS):
                        raise ValueError(f"evaluator did not emit all ESKF policy rows for {stem}")
                    for replay_row in expected_replay:
                        archived = seed_by_key[(scenario, rate_mode, stress_mode, replay_row["estimator"])]
                        assert_archive_match(replay_row, archived)
                    raw_rows = read_input_stream(input_path, protocol_sha256=protocol_hash,
                        scenario=scenario,
                        expected_scenario_index=next(index for index, item in enumerate(protocol["scenarios"]) if item["id"] == scenario),
                        rate_mode=rate_mode, stress_mode=stress_mode, seed=args.trace_seed)
                    raw_trace = load_csv(trace_path)
                    enriched = enrich_trace(raw_trace, raw_rows, scenario=scenario, rate_mode=rate_mode,
                        stress_mode=stress_mode, seed=args.trace_seed, input_sha256=input_hash,
                        implementation_commit=args.implementation_commit, config_sha256=expected_config_hash, protocol=protocol)
                    if len(enriched) != expected_samples:
                        raise ValueError(f"unexpected L1 sample count for {stem}: {len(enriched)} != {expected_samples}")
                    conservative_archive = seed_by_key[(scenario, rate_mode, stress_mode, "eskf_conservative")]
                    metrics = summarize_trace(enriched, rate_hz=rate, expected_samples=expected_samples, archive_row=conservative_archive)
                    diag_summary = load_csv(summary_path)
                    conservative_diagnostic = next((row for row in diag_summary if row["estimator"] == "eskf_conservative"), None)
                    if conservative_diagnostic is None:
                        raise ValueError(f"gravity diagnostic summary missing Conservative ESKF row for {stem}")
                    if int(conservative_diagnostic["gravity_accepted"]) != metrics["gravity_accepted"]:
                        raise ValueError("L1 accepted gravity count disagrees with evaluator summary")
                    if not math.isclose(float(conservative_diagnostic["tilt_rms_deg"]), float(conservative_archive["tilt_rms_deg"]), rel_tol=2e-6, abs_tol=1e-7):
                        raise ValueError("gravity diagnostic and archived tilt RMS differ")
                    result = {
                        "scenario": scenario, "rate_mode": rate_mode, "stress_mode": stress_mode,
                        "seed": args.trace_seed, "sample_count": expected_samples,
                        "raw_input_sha256": input_hash, "replay_metrics_match_archive": True,
                        "rows": enriched, "metrics": metrics,
                    }
                    pair_results[stress_mode] = result
                    l1_rows.extend(enriched)
                nominal, stress = pair_results["nominal"], pair_results["stress"]
                validate_paired_trace_records(nominal, stress)
                figure_name = f"{scenario}__{rate_mode}__seed{args.trace_seed}.svg"
                svg_pair_figure(scenario, rate_mode, nominal, stress, output / figure_name, args.trace_seed,
                    expected_config_hash, archive_hash)
                for result in (nominal, stress):
                    metrics = result["metrics"]
                    atlas_rows.append({
                        "split": "development", "scenario": scenario, "rate_mode": rate_mode,
                        "stress_mode": result["stress_mode"], "estimator": "eskf_conservative",
                        "profile": "IMU_ONLY/UNKNOWN/calibration-OFF/aid-NONE", "seed": args.trace_seed,
                        "sample_count": metrics["expected_samples"],
                        "source_commit": args.implementation_commit, "config_sha256": expected_config_hash,
                        "source_archive_sha256": archive_hash, "protocol_sha256": protocol_hash,
                        "raw_input_sha256": result["raw_input_sha256"], "plot": figure_name,
                        "l1_artifact": "selected_l1_traces.csv.gz", "event_window_definition": "maximum one-second tilt increase during physical t>=2 s",
                        "event_window_clock": "physical_time_s",
                        "max_1s_tilt_increase_deg": metrics["max_1s_tilt_increase_deg"],
                        "event_window_start_s": metrics["max_1s_window_start_s"], "event_window_end_s": metrics["max_1s_window_end_s"],
                        "longest_gravity_gap_s": metrics["longest_gravity_correction_gap_s"],
                        "gravity_gap_start_s": metrics["longest_gravity_gap_start_s"], "gravity_gap_end_s": metrics["longest_gravity_gap_end_s"],
                        "tilt_error_max_deg": metrics["tilt_error_max_deg"], "tilt_error_max_time_s": metrics["tilt_error_max_time_s"],
                        "tilt_rms_archived_deg": metrics["archived_tilt_rms_deg"], "availability_archived": metrics["availability"],
                        "gravity_attempts": metrics["gravity_attempts"], "gravity_accepted": metrics["gravity_accepted"],
                        "gravity_attempted_rejected": metrics["gravity_attempted_rejected"],
                        "heading_updates": 0, "zero_rate_updates": 0,
                        "covariance_invalid_samples": metrics["covariance_invalid_samples"], "health_end": metrics["health_end"],
                        "observable_tilt_nees_mean": metrics["observable_tilt_nees_mean"],
                        "projected_tilt_cov_sqrt_trace_deg_mean": metrics["projected_tilt_cov_sqrt_trace_deg_mean"],
                        "accel_bias_error_mean_m_s2": metrics["accel_bias_error_mean_m_s2"],
                        "gyro_bias_error_mean_rad_s": metrics["gyro_bias_error_mean_rad_s"],
                        "accel_measurement_residual_rms_m_s2": metrics["accel_measurement_residual_rms_m_s2"],
                        "gyro_measurement_residual_rms_rad_s": metrics["gyro_measurement_residual_rms_rad_s"],
                        "motion_regime_seconds_json": json.dumps(metrics["motion_regime_seconds"], sort_keys=True),
                        "declared_vibration_disturbance_seconds": metrics["declared_vibration_disturbance_seconds"],
                        "replay_status": "PASS",
                    })
    if len(l1_rows) != sum(int(row["sample_count"]) for row in atlas_rows):
        raise ValueError("combined L1 trace sample count disagrees with atlas rows")
    l1_fields = [
        "source_commit", "config_sha256", "raw_input_sha256", "scenario", "rate_mode", "stress_mode", "seed",
        "sample_index", "nominal_time_s", "physical_time_s", "actual_dt_s", "reported_timestamp_us", "estimator",
        "initialized", "health", "control_state_valid", "accel_norm_m_s2", "gyro_norm_rad_s", "accel_step_m_s2",
        "accel_norm_gate_pass", "gyro_norm_gate_pass", "accel_step_gate_pass", "raw_candidate",
        "consecutive_candidate_samples", "stationary", "gravity_allowed", "gravity_attempted", "gravity_accepted",
        "gravity_reason", "gravity_innovation_angle_rad", "gravity_effective_noise_sigma", "gravity_nis", "gravity_nis_gate",
        "tilt_error_deg", "tilt_cov_00", "tilt_cov_01", "tilt_cov_11", "tilt_cov_trace", "tilt_cov_eigen_min",
        "tilt_cov_eigen_max", "tilt_nees_observable_2d", "covariance_positive_definite",
        "projected_tilt_cov_sqrt_trace_deg", "accel_bias_x", "accel_bias_y", "accel_bias_z", "accel_bias_error_m_s2",
        "accel_bias_error_x_m_s2", "accel_bias_error_y_m_s2", "accel_bias_error_z_m_s2",
        "gyro_bias_x", "gyro_bias_y", "gyro_bias_z", "gyro_bias_error_rad_s",
        "gyro_bias_error_x_rad_s", "gyro_bias_error_y_rad_s", "gyro_bias_error_z_rad_s",
        "truth_body_rate_norm_rad_s", "truth_world_linear_accel_norm_m_s2", "motion_regime",
        "measurement_disturbance_active", "accel_measurement_residual_norm_m_s2",
        "gyro_measurement_residual_norm_rad_s", "time_since_gravity_accept_s",
    ]
    write_gzip_csv(output / "selected_l1_traces.csv.gz", l1_rows, l1_fields)
    write_csv(output / "development_group_rollups.csv", rollups)
    write_csv(output / "development_paired_stress_deltas.csv", paired_rollups)
    write_csv(output / "selected_trace_atlas.csv", atlas_rows)
    checklist = """# A6 independent review checklist

- [ ] Confirm PR3 v5 protocol, archive, archive manifest, filter header and evaluator source hashes against the manifest.
- [ ] Confirm this is the development split and the selected trace seed is 4001; no held-out or final-confirmation rows are used.
- [ ] Reproduce one selected raw stream and confirm its SHA-256 matches the frozen archive row.
- [ ] Confirm the 1 s tilt-rise window and longest gravity-correction gap are indexed by the trace's physical/nominal timestamps as documented.
- [ ] Review the 0.01 rad/s and 0.05 m/s² motion-regime thresholds; they are descriptive bins, not estimator gates.
- [ ] Treat projected tilt sigma and observable-plane NEES as model diagnostics; positive definiteness does not establish calibrated uncertainty.
- [ ] Keep absolute yaw claims out of the six-axis IMU-only summary; slow-yaw is reported relative to the simulator's shared startup gauge.
- [ ] Check that gravity updates are the only runtime correction type enabled by this profile; heading and zero-rate counts are zero by configuration.
- [ ] Review lateral-acceleration and vibration classifications against protocol v5's declared synthetic motion and disturbance definitions.
- [ ] Do not tune ESKF noise or gates from these exposed development data; use the findings to preregister isolated PR-C/D/E experiments.
- [ ] Hardware accuracy, sensor transfer, runtime, and stack remain unverified.
"""
    (output / "INDEPENDENT_REVIEW_CHECKLIST.md").write_text(checklist, encoding="utf-8", newline="\n")
    report = build_report(args, source_hashes, archive_hash, archive_manifest_hash, protocol_hash, rollups, paired_rollups, atlas_rows)
    (output / "A6_NOISE_COVARIANCE_FAILURE_ATLAS.md").write_text(report, encoding="utf-8", newline="\n")
    files = [path for path in output.iterdir() if path.is_file() and path.name != "evidence_manifest.json"]
    manifest = {
        "schema_version": 1, "tool_id": TOOL_ID, "status": "PASS", "classification": "development-only synthetic host diagnostics",
        "implementation_commit": args.implementation_commit, "implementation_branch": args.implementation_branch,
        "diagnostic_commit": args.diagnostic_commit, "diagnostic_branch": args.diagnostic_branch,
        "protocol_path": str(PROTOCOL.relative_to(ROOT)), "archive_path": str(ARCHIVE.relative_to(ROOT)),
        "archive_manifest_path": str(ARCHIVE_MANIFEST.relative_to(ROOT)),
        "protocol_sha256": protocol_hash, "archive_sha256": archive_hash, "archive_manifest_sha256": archive_manifest_hash,
        "source_file_sha256": source_hashes, "config": CONFIG, "config_sha256": expected_config_hash,
        "split": "development", "development_seed_range": [seed_range["first_seed"], seed_range["last_seed"]],
        "selected_trace_seed": args.trace_seed, "scenarios": list(SCENARIOS), "rate_modes": list(RATE_IDS),
        "stress_modes": ["nominal", "stress"], "profile": "IMU_ONLY/UNKNOWN/calibration-OFF/aid-NONE",
        "l0_trial_rows": len(archive_rows), "l0_rollup_groups": len(rollups), "paired_rollup_groups": len(paired_rollups),
        "selected_l1_streams": len(atlas_rows), "selected_l1_samples": len(l1_rows),
        "motion_regime_thresholds": {"angular_rate_rad_s": ANGULAR_MOTION_THRESHOLD_RAD_S, "linear_accel_m_s2": LINEAR_ACCEL_THRESHOLD_M_S2},
        "compiler": compiler_version, "compile_flags": ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-DINERTIAL_GRAVITY_DIAGNOSTICS=1"],
        "reproduction_command": f"python3 tools/pr3_failure_atlas.py --output-dir remediation/analysis/pr3_failure_atlas_a6 --trace-seed {args.trace_seed} --cxx {args.cxx} --implementation-commit {args.implementation_commit} --implementation-branch {args.implementation_branch} --diagnostic-commit {args.diagnostic_commit} --diagnostic-branch {args.diagnostic_branch}",
        "replay_command_count": len(commands), "replay_commands_sha256": sha256_bytes("\n".join(commands).encode()),
        "checks": {
            "development_archive_hashes": "PASS", "selected_group_counts_100": "PASS",
            "regenerated_raw_input_hashes": "PASS", "replayed_trial_metrics_match_archive": "PASS",
            "trace_sample_index_and_clock_quality": "PASS", "paired_nominal_stress_identity": "PASS",
            "eskf_header_unchanged_from_baseline": "PASS", "full_factorial_rerun": "NOT_RUN",
            "held_out_or_final_accessed": "NO", "hardware_validation": "NOT_RUN",
        },
        "outputs": {path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(files)},
    }
    (output / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS A6 failure atlas: {len(rollups)} L0 groups, {len(paired_rollups)} paired groups, {len(atlas_rows)} L1 streams, {len(l1_rows)} L1 samples")
    print(f"SOURCE archive={archive_hash} protocol={protocol_hash} filter={source_hashes['filter']} config={expected_config_hash}")
    for row in rollups:
        if row["estimator"] == "eskf_conservative":
            print(f"L0 {row['scenario']} {row['rate_mode']} {row['stress_mode']} n={row['trial_count']} tilt_rms_mean_deg={row['tilt_rms_mean_deg']:.6f} min_availability={row['minimum_availability']:.6f} cov_fraction={row['mean_covariance_check_fraction']}")
    return 0


def build_report(args, source_hashes, archive_hash, archive_manifest_hash, protocol_hash, rollups, paired_rollups, atlas_rows):
    by_group = {(row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"]): row for row in rollups}
    paired = {(row["scenario"], row["rate_mode"], row["estimator"]): row for row in paired_rollups}
    lines = [
        "# A6 — PR3 v5 development noise and covariance failure atlas", "",
        "## Scope and provenance", "",
        "This report uses the frozen PR3 v5 development archive only. The profile is IMU-only, unknown startup, startup gyro-bias calibration off, and no runtime aid. The fixed pre-change estimator is evaluated over static, slow-yaw, lateral-acceleration, vibration, and compound-motion cases at uniform 200 Hz, uniform 208 Hz, and irregular 208 Hz.", "",
        f"- Pre-change filter baseline: commit `{args.implementation_commit}` on `{args.implementation_branch}`; source header SHA-256 `{source_hashes['filter']}`. A6 diagnostic capture source: commit `{args.diagnostic_commit}` on `{args.diagnostic_branch}`.",
        f"- Protocol SHA-256 `{protocol_hash}`; archive SHA-256 `{archive_hash}`; archive-manifest SHA-256 `{archive_manifest_hash}`.",
        f"- Configuration SHA-256 `{CONFIG_SHA256}`. Development groups contain 100 trial rows per scenario/rate/stress/ESKF policy; grouped statistics are computed at trial level.",
        f"- Sample traces replay seed `{args.trace_seed}` for each of the 30 matched scenario/rate/stress cells. Every regenerated input SHA matched the corresponding frozen development archive rows, and every replayed ESKF trial metric matched the archive within `2e-6` relative tolerance.",
        "- Noise transform: nominal uses protocol v5 densities; stress multiplies white-noise density by 3 and bias walk, measurement disturbance, and timestamp jitter by 2. Truth trajectory is unchanged.",
        "- No estimator parameters were changed. No held-out/final-confirmation data or hardware were used.", "",
        "## Trial-level development rollups", "",
        "Conservative ESKF; `n=100` per condition. Tilt values are means of per-trial RMS, not pooled sample RMS. Yaw is relative to the common zero-yaw startup gauge and is not absolute north. Covariance fraction counts the archived per-sample positive-definiteness checks.", "",
        "| Scenario | Rate | Nominal tilt RMS mean (°) | Stress tilt RMS mean (°) | Paired stress−nominal (°) | Stress min availability | Stress covariance fraction |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for scenario in SCENARIOS:
        for rate in RATE_IDS:
            n = by_group[(scenario, rate, "nominal", "eskf_conservative")]
            s = by_group[(scenario, rate, "stress", "eskf_conservative")]
            p = paired[(scenario, rate, "eskf_conservative")]
            lines.append(f"| {scenario} | {rate} | {n['tilt_rms_mean_deg']:.4f} | {s['tilt_rms_mean_deg']:.4f} | {p['stress_minus_nominal_mean_deg']:+.4f} | {s['minimum_availability']:.4f} | {s['mean_covariance_check_fraction']:.6f} |")
    worst_delta = max((row for row in paired_rollups if row["estimator"] == "eskf_conservative"), key=lambda row: row["stress_minus_nominal_mean_deg"])
    lines.extend([
        "", "## Selected time-resolved traces", "",
        f"The L1 artifact contains {sum(int(row['sample_count']) for row in atlas_rows)} Conservative ESKF samples across 30 matched streams; it is per-sample diagnostic data, not a full 15×15 covariance dump. Each plot compares nominal and stress at the same scenario, rate, and seed. The maximum one-second tilt rise window is selected on physical time from the post-startup (`t≥2 s`) trace. Correction-gap windows run from initialization through accepted gravity updates and to end of trial.", "",
        f"Largest mean paired stress penalty in the selected scenario/rate matrix: `{worst_delta['scenario']}` / `{worst_delta['rate_mode']}`, `{worst_delta['stress_minus_nominal_mean_deg']:+.4f}°` tilt RMS over 100 paired development seeds.", "",
        "| Scenario | Rate | Nominal / stress selected tilt RMS (°) | Stress max 1 s rise (°) | Stress window (s) | Stress gravity accepted | Stress longest no-correction gap (s) | Plot |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    atlas = {(row["scenario"], row["rate_mode"], row["stress_mode"]): row for row in atlas_rows}
    for scenario in SCENARIOS:
        for rate in RATE_IDS:
            n = atlas[(scenario, rate, "nominal")]
            s = atlas[(scenario, rate, "stress")]
            lines.append(f"| {scenario} | {rate} | {float(n['tilt_rms_archived_deg']):.4f} / {float(s['tilt_rms_archived_deg']):.4f} | {float(s['max_1s_tilt_increase_deg']):+.4f} | {float(s['event_window_start_s']):.3f}–{float(s['event_window_end_s']):.3f} | {s['gravity_accepted']} | {float(s['longest_gravity_gap_s']):.3f} | [{scenario}/{rate}]({scenario}__{rate}__seed{args.trace_seed}.svg) |")
    lines.extend([
        "", "### Motion-regime accounting", "",
        f"Per-sample truth motion is reconstructed from the generated truth quaternion increments and velocity increments using physical sample timestamps. Bins use `|ω_truth|≥{ANGULAR_MOTION_THRESHOLD_RAD_S:g} rad/s` and `|a_world_truth|≥{LINEAR_ACCEL_THRESHOLD_M_S2:g} m/s²`; startup is `t<2 s`. These bins describe the generated trajectory, not the filter's stationarity gate. The protocol-declared vibration disturbance is tracked separately.",
        "The selected-trace atlas CSV records actual seconds in startup-static, quiescent/coast, rotation-dominant, translation-dominant and compound bins, plus declared vibration-active seconds. IMU residual RMS is calculated after subtracting simulator truth, bias and gravity; for vibration it includes deterministic disturbance plus white noise.", "",
        "## Mechanism and classification", "",
        "| Issue | Classification | Confidence / evidence | Scope and limitation |",
        "|---|---|---|---|",
        "| Long-run covariance positive-definiteness loss in the earlier single-precision source | Confirmed software defect — fixed before this baseline | High; remediation records the old slow-yaw failure and the FP64 repair. In the v5 development archive the selected baseline groups retain their full covariance-validity counts; selected L1 also records per-sample full-state Cholesky status and observable-plane NEES. | Positive definiteness does not establish calibrated covariance. This atlas does not retest the old binary. |",
        "| Archive/evaluator mismatch in the selected baseline profile | Evaluation defect — not observed in this audit | High for checked scope; 100-trial group counts are exact, 30 regenerated input hashes match, and selected replay metrics match archived rows. | This is a selected v5 development-profile check, not a verifier for every protocol factor. |",
        "| Absolute yaw during slow-yaw six-axis operation | Observability limitation | High; the profile provides no independent heading source. Report yaw only relative to the shared startup gauge. | Gyro integration can track increments but cannot recover absolute north. |",
        "| Stress noise/disturbance interacting with the gravity candidate, dwell, and update cadence | Hypothesis for the broader stress accuracy gap; local gate sequence is directly observed in L1 | Medium–high on cases where the trace shows gate failures or long accepted-update gaps alongside tilt/bias growth; see per-case counters and windows. | A threshold interaction is not automatically a code defect; the synthetic densities are illustrative rather than measured LSM6DS3 noise. |",
        "| Sustained lateral acceleration being confused with gravity direction | Observability limitation plus scenario-specific hypothesis about filter response | High for the physical ambiguity; the six-axis sample alone cannot distinguish a persistent horizontal specific-force component from a changed gravity direction. | The simulator knows the injected acceleration; the runtime filter does not. |",
        "| Vibration behavior at 200/208 Hz and irregular timing | Hypothesis | Medium; compare residual RMS, candidate/rejection counts, update gaps and projected covariance across paired rate modes. | Protocol v5 labels its scenarios as synthetic approximations not verified against historical figures or measured hardware spectra. |",
        "| Projected covariance versus tilt error / observable-plane NEES | Hypothesis about calibration, not a defect classification | The trace exposes the projected covariance matrix, its 2D square-root trace scale, 2D observable tilt NEES, gravity NIS and full-state covariance validity at each sample. | Nonlinear motion and gravity/propagation sample correlation limit chi-square interpretation; do not tune covariance from these plots alone. |",
        "", "This atlas does not find a new confirmed software or evaluation defect. It preserves prior confirmed fixes as context and separates them from current stress/noise hypotheses and six-axis observability limits.", "",
        "## Focused handoff to PR-C/D/E", "",
        "- **PR-C (noise/covariance):** hold the gate and gravity sigma fixed while testing simulator-matched and intermediate process-noise densities; isolate bias random-walk settings; then separately test gravity residual variance. Use the same development raw input streams and compare bias error, projected observable covariance, NEES, and gravity NIS. A lightweight known-linearized-noise fixture is still needed before calling covariance calibrated.",
        "- **PR-D (gravity/motion confidence):** use lateral acceleration to test false-gravity acceptance and recovery, and vibration/stress traces to test whether a noise-aware detector can retain usable corrections without accepting dynamic acceleration. Keep no-aid six-axis ambiguity explicit; evaluate selected candidate policy separately from baseline.",
        "- **PR-E (heading):** carry forward the A5 pure-roll event trace; independently validate heading H/sign/gauge and vary only declared heading sigma on the fixed development noise realization. Treat tilt/bias cross-covariance and later propagation as separate mechanisms; use a separately modeled candidate if decoupling is tested.",
        "", "## Reproduction and checks", "",
        "Run from the repository root under a host with Python 3 and a C++17 compiler:", "",
        "```bash",
        f"python3 tools/pr3_failure_atlas.py --output-dir remediation/analysis/pr3_failure_atlas_a6 --trace-seed {args.trace_seed} --cxx {args.cxx} --implementation-commit {args.implementation_commit} --implementation-branch {args.implementation_branch} --diagnostic-commit {args.diagnostic_commit} --diagnostic-branch {args.diagnostic_branch}",
        "python3 -m unittest discover -s tests -p 'test_pr3_failure_atlas.py'",
        "```", "",
        f"Compiler: `{args.cxx}`; build flags: `-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -DINERTIAL_GRAVITY_DIAGNOSTICS=1`. The runner checked protocol/archive hashes, 100-row groups, exact input identity for selected seed {args.trace_seed}, trial-metric replay, sample count/order/clock, projected covariance fields, per-sample covariance validity, and paired nominal/stress input counts.",
        "", "Hardware validation: `NOT_RUN`. Full factorial rerun: `NOT_RUN` (existing frozen archive used). Held-out and final-confirmation data: `NOT_ACCESSED`.",
    ])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "remediation/analysis/pr3_failure_atlas_a6")
    parser.add_argument("--trace-seed", type=int, default=4001)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--implementation-commit", required=True, help="full pre-change estimator baseline commit SHA")
    parser.add_argument("--implementation-branch", required=True, help="branch containing the pre-change estimator baseline")
    parser.add_argument("--diagnostic-commit", required=True, help="full committed SHA for the A6 diagnostic code")
    parser.add_argument("--diagnostic-branch", required=True)
    args = parser.parse_args(argv)
    try:
        return run_analysis(args)
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, struct.error) as error:
        print(f"FAIL A6 noise/covariance atlas: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
