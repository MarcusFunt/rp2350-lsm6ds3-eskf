#!/usr/bin/env python3
"""Validate and pair baseline/candidate outputs from the PR 2 frozen runner."""
import csv
import hashlib
import math
import sys
from pathlib import Path

KEYS = (
    "evaluation_protocol_version", "scenario", "noise_mode", "seed_split", "seed",
    "input_mode", "startup_knowledge", "startup_calibration", "runtime_aid", "estimator",
)
METRICS = (
    "expected", "valid", "unavailable", "stale", "valid_fraction", "tilt_rms_deg",
    "tilt_p95_deg", "tilt_max_deg", "attitude_rms_deg", "yaw_rms_deg",
    "yaw_abs_p95_deg", "yaw_abs_max_deg", "position_rms_m", "position_p95_m",
    "velocity_rms_m_s", "gravity_nis_mean", "gravity_nis_count", "gravity_applied",
    "gravity_suppressed", "aid_accepted", "aid_rejected", "health_end",
    "max_state_age_us", "accel_bias_error_end_m_s2", "gyro_bias_error_end_rad_s",
)
EXPECTED_ROWS = 4 * 3 * 16 * 18
EXPECTED_RECORDS = 4 * 3 * 16 * 2400
RECORD_BYTES = 40
EXPECTED_INPUT_BYTES = EXPECTED_RECORDS * RECORD_BYTES


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        key = tuple(row[field] for field in KEYS)
        if key in result:
            raise ValueError(f"duplicate metric row in {path}: {key}")
        if int(row["expected"]) != 2001:
            raise ValueError(f"unexpected fixed denominator in {path}: {key}")
        if int(row["valid"]) + int(row["unavailable"]) != 2001:
            raise ValueError(f"availability does not reconcile in {path}: {key}")
        result[key] = row
    if len(result) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} rows in {path}; got {len(result)}")
    return result


def write_pairs(baseline, candidate, output, input_hash):
    base = load(baseline / "summary.csv")
    cand = load(candidate / "summary.csv")
    if base.keys() != cand.keys():
        raise ValueError("baseline and candidate metric keys differ")
    fields = [*KEYS, "input_samples_sha256"]
    for metric in METRICS:
        fields.extend((f"baseline_{metric}", f"candidate_{metric}"))
        if metric != "health_end":
            fields.append(f"delta_{metric}")
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key in sorted(base):
            b, c = base[key], cand[key]
            row = dict(zip(KEYS, key))
            row["input_samples_sha256"] = input_hash
            for metric in METRICS:
                bv, cv = b[metric], c[metric]
                row[f"baseline_{metric}"] = bv
                row[f"candidate_{metric}"] = cv
                if metric != "health_end":
                    if not bv or not cv:
                        row[f"delta_{metric}"] = ""
                    else:
                        row[f"delta_{metric}"] = f"{float(cv)-float(bv):.8g}"
            writer.writerow(row)


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: compare_pr2_results.py BASELINE_DIR CANDIDATE_DIR OUTPUT.csv")
    baseline, candidate, output = map(Path, sys.argv[1:])
    base_input, cand_input = baseline / "imu_samples.bin", candidate / "imu_samples.bin"
    if base_input.stat().st_size != EXPECTED_INPUT_BYTES:
        raise ValueError(f"unexpected baseline input bytes: {base_input.stat().st_size}")
    if cand_input.stat().st_size != EXPECTED_INPUT_BYTES:
        raise ValueError(f"unexpected candidate input bytes: {cand_input.stat().st_size}")
    base_hash, cand_hash = sha256(base_input), sha256(cand_input)
    if base_hash != cand_hash:
        raise ValueError(f"baseline/candidate sample hashes differ: {base_hash} != {cand_hash}")
    write_pairs(baseline, candidate, output, base_hash)
    print(f"PASS paired PR2 comparison: {EXPECTED_ROWS} rows; {EXPECTED_RECORDS} identical 40-byte inputs; sha256={base_hash}")


if __name__ == "__main__":
    main()
