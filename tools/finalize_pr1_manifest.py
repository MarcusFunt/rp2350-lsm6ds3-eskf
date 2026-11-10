#!/usr/bin/env python3
"""Validate PR 1 baseline artifacts, hash each shared sample stream, and freeze provenance."""
import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
from pathlib import Path


RECORD_BYTES = 40
RECORD_COUNT = 2400
EXPECTED_SAMPLES = 2001
VARIANTS_PER_TRIAL = 18


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    windows_git = shutil.which("git.exe")
    if platform.system() == "Linux" and windows_git:
        windows_root = subprocess.check_output(["wslpath", "-m", str(root)], text=True).strip()
        command = [windows_git, "-C", windows_root, *args]
        return subprocess.check_output(command, text=True).strip()
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"PR1 artifact validation failed: {message}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "benchmarks" / "reports"
    manifest_dir = root / "benchmarks" / "manifests"
    scenario_path = root / "benchmarks" / "scenarios" / "pr1_core_regressions_protocol_v2.json"
    summary_path = report_dir / "pr1_baseline_protocol_v2.csv"
    trace_path = report_dir / "pr1_representative_traces_protocol_v2.csv"
    index_path = report_dir / "pr1_sample_index_protocol_v2.csv"
    samples_path = report_dir / "pr1_imu_samples_protocol_v2.bin"
    manifest_path = manifest_dir / "pr1_baseline_protocol_v2.json"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    with scenario_path.open(encoding="utf-8") as stream:
        scenario_config = json.load(stream)
    ensure(scenario_config["evaluation_protocol_version"] == 2, "scenario protocol must be v2")

    with summary_path.open(newline="", encoding="utf-8") as stream:
        summary_rows = list(csv.DictReader(stream))
    with index_path.open(newline="", encoding="utf-8") as stream:
        index_rows = list(csv.DictReader(stream))
    with trace_path.open(newline="", encoding="utf-8") as stream:
        trace_rows = list(csv.DictReader(stream))

    ensure(len(index_rows) == 292, f"expected 292 shared input streams, found {len(index_rows)}")
    ensure(len(summary_rows) == 292 * VARIANTS_PER_TRIAL,
           f"expected {292 * VARIANTS_PER_TRIAL} summary rows, found {len(summary_rows)}")
    ensure(len(trace_rows) == 21 * EXPECTED_SAMPLES,
           f"expected {21 * EXPECTED_SAMPLES} representative rows, found {len(trace_rows)}")
    ensure(all(int(row["evaluation_protocol_version"]) == 2 for row in summary_rows),
           "summary contains a non-v2 row")
    ensure(all(int(row["expected"]) == EXPECTED_SAMPLES for row in summary_rows),
           "summary denominator changed")
    ensure(all(int(row["record_count"]) == RECORD_COUNT for row in index_rows),
           "sample stream length changed")

    required_noisy = {
        (scenario, noise, split)
        for scenario in ("pure_roll", "lateral_accel_0p2g", "slow_yaw")
        for noise in ("accel_only", "gyro_only", "combined")
        for split in ("development", "held_out")
    }
    groups = {}
    for row in summary_rows:
        key = (row["scenario"], row["noise_mode"], row["seed_split"], int(row["seed"]))
        groups.setdefault(key, []).append(row)
    ensure(all(len(rows) == VARIANTS_PER_TRIAL for rows in groups.values()),
           "each input stream must have the full 18 estimator/provenance variants")
    observed_cells = {(scene, noise, split) for scene, noise, split, _ in groups}
    ensure(required_noisy.issubset(observed_cells), "a required scenario/noise/split cell is missing")
    for scene, noise, split in required_noisy:
        seeds = {seed for s, n, sp, seed in groups if (s, n, sp) == (scene, noise, split)}
        expected = set(range(101, 117)) if split == "development" else set(range(1001, 1017))
        ensure(seeds == expected, f"wrong frozen seeds for {scene}/{noise}/{split}: {sorted(seeds)}")
    for scenario in ("static", "pure_roll", "lateral_accel_0p2g", "slow_yaw"):
        ensure((scenario, "clean", "reference", 0) in groups,
               f"missing noise-free reference for {scenario}")

    clean_lateral = [row for row in trace_rows
                     if row["scenario"] == "lateral_accel_0p2g"
                     and row["noise_mode"] == "clean"
                     and row["seed_split"] == "reference"
                     and row["seed"] == "0"]
    ensure(len(clean_lateral) == 3 * EXPECTED_SAMPLES,
           "clean lateral-acceleration trace must contain all three gravity policies")
    clean_lateral_reference = [row for row in clean_lateral if row["estimator"] == "Conservative"]
    ensure(len(clean_lateral_reference) == EXPECTED_SAMPLES,
           "clean lateral-acceleration Conservative reference trace is missing samples")
    assert_close = lambda value, expected, tolerance, label: ensure(
        abs(float(value) - expected) <= tolerance,
        f"{label}: expected {expected}, found {value}")
    for row in clean_lateral_reference:
        assert_close(row["truth_qw"], 1.0, 1e-5, "noise-free lateral truth qw")
        for key in ("truth_qx", "truth_qy", "truth_qz"):
            assert_close(row[key], 0.0, 1e-5, f"noise-free lateral truth {key}")
        t = float(row["time_s"])
        if 2.0 <= t < 8.0:
            assert_close(row["imu_ax"], 0.2 * 9.80665, 1e-4, "0.2 g lateral input")
            assert_close(row["imu_az"], 9.80665, 1e-4, "gravity input")
    at_end = [row for row in clean_lateral_reference if float(row["time_s"]) == 12.0]
    ensure(len(at_end) == 1, "clean lateral truth endpoint is missing")
    assert_close(at_end[0]["truth_px"], 42.0 * 0.2 * 9.80665,
                 0.01, "independent 12 s lateral truth position")

    input_groups = {}
    for row in trace_rows:
        key = (row["scenario"], row["noise_mode"], row["seed_split"], row["seed"], row["timestamp_us"])
        signature = tuple(row[f"imu_{axis}"] for axis in ("ax", "ay", "az", "gx", "gy", "gz"))
        if key in input_groups:
            ensure(input_groups[key] == signature, "estimators did not receive identical IMU samples")
        else:
            input_groups[key] = signature
        for field in ("truth_qw", "truth_qx", "truth_qy", "truth_qz", "imu_ax", "imu_ay", "imu_az",
                      "imu_gx", "imu_gy", "imu_gz", "estimate_qw", "estimate_qx", "estimate_qy",
                      "estimate_qz", "state_age_us"):
            ensure(row[field] != "" and math.isfinite(float(row[field])),
                   f"required trace field {field} is missing/non-finite")
        if row["nis"] == "":
            ensure(row["nis_source"] == "", "undefined NIS must serialize as empty with no source")
        else:
            ensure(math.isfinite(float(row["nis"])) and row["nis_source"] != "",
                   "defined NIS must be finite and have a source label")

    sample_size = samples_path.stat().st_size
    ensure(sample_size == len(index_rows) * RECORD_COUNT * RECORD_BYTES,
           f"sample stream has {sample_size} bytes, inconsistent with index")
    enriched = []
    expected_offset = 0
    with samples_path.open("rb") as sample_file:
        for row in index_rows:
            offset = int(row["offset_bytes"])
            count = int(row["record_count"])
            record_bytes = int(row["record_bytes"])
            ensure(offset == expected_offset, "sample streams contain an offset gap or overlap")
            ensure(record_bytes == RECORD_BYTES, "raw record size is not 40 bytes")
            sample_file.seek(offset)
            data = sample_file.read(count * record_bytes)
            ensure(len(data) == count * record_bytes, "short sample stream")
            timestamps = [int.from_bytes(data[i:i + 8], "little")
                          for i in range(0, len(data), record_bytes)]
            ensure(all(a < b for a, b in zip(timestamps, timestamps[1:])),
                   f"non-monotonic timestamps in {row['trial_id']}")
            ensure(timestamps[0] == 1_005_000 and timestamps[-1] == 13_000_000,
                   f"timestamp endpoints changed in {row['trial_id']}")
            enriched.append({**row, "sample_sha256": hashlib.sha256(data).hexdigest()})
            expected_offset += len(data)

    with index_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(enriched[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(enriched)

    base_sha = git(root, "merge-base", "HEAD", "origin/main")
    head_sha = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current")
    core_sha256 = sha256(root / "eskf15.hpp")
    compiler_version = subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]
    scenario_hash = sha256(scenario_path)
    manifest = {
        "schema_version": 1,
        "evaluation_protocol_version": 2,
        "status": "FROZEN_PRECHANGE_BASELINE",
        "pinned_baseline_sha": base_sha,
        "benchmark_source_sha": head_sha,
        "branch": branch,
        "estimator_core_sha256": core_sha256,
        "scenario_config": {
            "path": str(scenario_path.relative_to(root)).replace("\\", "/"),
            "sha256": scenario_hash,
        },
        "command": "bash ./tools/run_pr1_baseline.sh",
        "compile_command": "g++ -std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror tools/pr1_baseline.cpp -o ${TMPDIR}/pr1_baseline",
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "compiler": compiler_version,
            "sdk": "Pico SDK 2.2.0 was not used for host simulation",
        },
        "matrix": {
            "scenarios": 4,
            "shared_imu_streams": len(index_rows),
            "estimator_and_provenance_rows": len(summary_rows),
            "representative_trace_rows": len(trace_rows),
            "expected_samples_per_trial": EXPECTED_SAMPLES,
            "noise_free_reference_trials": 4,
            "development_seeds_per_noisy_motion_cell": 16,
            "held_out_seeds_per_noisy_motion_cell": 16,
            "noise_modes": ["clean", "accel_only", "gyro_only", "combined"],
            "gravity_policies": ["Conservative", "LegacyHeuristic", "ConfirmedOnly"],
            "input_modes": ["IMU_ONLY", "TRUSTED_AIDED"],
        },
        "artifacts": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in (summary_path, trace_path, index_path, samples_path)
        },
        "sample_streams": [
            {"trial_id": row["trial_id"], "sha256": row["sample_sha256"],
             "offset_bytes": int(row["offset_bytes"]),
             "record_count": int(row["record_count"]),
             "record_bytes": int(row["record_bytes"])}
            for row in enriched
        ],
        "pico2_baseline_ci": {
            "status": "PASS_CI_ON_PINNED_BASELINE",
            "workflow_run_id": 42816672377,
            "workflow_url": "https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42816672377",
            "head_sha": "c397fec8f5df3fb612ea6aa92547d484e9e48c06",
            "cross_build_job_id": 129831387144,
            "sdk_version": "2.2.0",
            "direct_register_sections_bytes": {"text": 79092, "data": 0, "bss": 25552, "text_data_bss_sum": 104644},
            "direct_uf2_sha256": "504980b01bf219105d14d9ac72fce19075bf666b962bc198ddcba079a446b0d0",
            "fifo_and_binary_variants": "cross-build passed; separate size output not emitted",
            "stack_usage": "NOT_RECORDED_BY_BASELINE_CI",
        },
        "limitations": [
            "Historical generator and exact old noise/time histories are unavailable; these are explicit recreated scenarios, not byte-for-byte historical reproductions.",
            "The TRUSTED_AIDED branch uses a synthetic independent heading-sensor proxy; it is not physical hardware evidence.",
            "No estimator equations were changed in this baseline; estimator source is pinned by eskf15.hpp SHA-256.",
            "The small seed sets are smoke/regression gates, not statistical certification.",
        ],
    }
    with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"PASS PR1 artifact validation: {len(summary_rows)} summary rows, {len(trace_rows)} trace rows, {len(index_rows)} hashed sample streams")
    print(f"summary_sha256={manifest['artifacts'][summary_path.name]['sha256']}")
    print(f"sample_stream_sha256={manifest['artifacts'][samples_path.name]['sha256']}")
    print(f"manifest={manifest_path.relative_to(root)}")


if __name__ == "__main__":
    main()
