#!/usr/bin/env python3
"""Compare the frozen gravity-gate candidate on all BROAD fast-rotation trials."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DATA = Path(os.environ.get(
    "BROAD_HDF5_DIR",
    "/mnt/c/Users/marcu/AppData/Local/Temp/codex-broad-b9-20261117/data_hdf5",
))
TRIALS = (
    "06_undisturbed_fast_rotation_A",
    "07_undisturbed_fast_rotation_B",
    "08_undisturbed_fast_rotation_with_breaks_A",
    "09_undisturbed_fast_rotation_with_breaks_B",
)
BASELINE_REPORT = ROOT / "remediation/analysis/b9_broad_failure_atlas/b9_broad_results.json"
SCORE_START_US = 3_000_000
CANDIDATE_GYRO_LIMIT = 0.48
CANDIDATE_DWELL = 7

sys.path.insert(0, str(ROOT / "scripts"))
import run_b9_broad_failure_atlas as atlas  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compile_candidate(temp: Path, compiler: list[str]) -> tuple[Path, str, str]:
    source = temp / "candidate_source"
    source.mkdir()
    header = (ROOT / "eskf15.hpp").read_text(encoding="utf-8")
    insertion = "        const float an=imu.accel_mps2.norm();\n"
    override = f'''        if (imu.timestamp_us >= {SCORE_START_US}ull) {{
            config_.static_gyro_limit={CANDIDATE_GYRO_LIMIT}f;
            config_.static_min_samples={CANDIDATE_DWELL}u;
        }}
'''
    if header.count(insertion) != 1:
        raise ValueError("filter insertion point changed; refusing an ambiguous experimental patch")
    patched_header = "#include <cstdlib>\n" + header.replace(insertion, override + insertion)
    (source / "eskf15.hpp").write_text(patched_header, encoding="utf-8")
    replay = (ROOT / "tools/b9_eskf_replay.cpp").read_text(encoding="utf-8")
    include = '#include "../eskf15.hpp"'
    if replay.count(include) != 1:
        raise ValueError("BROAD replay include changed; refusing an ambiguous experimental patch")
    source_file = source / "b9_eskf_replay.cpp"
    patched_replay = replay.replace(include, '#include "eskf15.hpp"')
    source_file.write_text(patched_replay, encoding="utf-8")
    executable = temp / "b9_eskf_replay_candidate"
    command = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
               f"-I{source}", str(source_file), "-o", str(executable)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"candidate replay compilation failed:\n{result.stdout}\n{result.stderr}")
    return executable, hashlib.sha256(patched_header.encode()).hexdigest(), hashlib.sha256(patched_replay.encode()).hexdigest()


def score_common(baseline, candidate, trial):
    shared = [a and b for a, b in zip(baseline["pair_valid"], candidate["pair_valid"])]
    bscore = atlas.score_paired_errors(baseline["eskf_errors"], trial["movement"], shared)
    cscore = atlas.score_paired_errors(candidate["eskf_errors"], trial["movement"], shared)
    return shared, bscore, cscore


def main() -> int:
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    if not compiler:
        raise ValueError("CXX cannot be empty")
    if not DATA.is_dir():
        raise FileNotFoundError(f"BROAD HDF5 data directory not found: {DATA}")
    baseline_report = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    references = {row["trial_id"]: row for row in baseline_report["trials"]}
    paths = atlas._trial_paths(DATA, TRIALS)
    if len(paths) != len(TRIALS):
        raise ValueError(f"expected {len(TRIALS)} fast-rotation trials, got {len(paths)}")

    rows = []
    with tempfile.TemporaryDirectory(prefix="b9-broad-gravity-candidate-") as name:
        temp = Path(name)
        candidate_executable, patch_sha, candidate_replay_sha = compile_candidate(temp, compiler)
        baseline_executable = temp / "b9_eskf_replay_baseline"
        atlas._compile_replay(os.environ.get("CXX", "g++"), baseline_executable)
        for trial_path in paths:
            trial = atlas._load_hdf5_trial(trial_path)
            expected_hash = next(item["source_artifact_sha256"] for item in baseline_report["trials"]
                                 if item["trial_id"] == trial["trial_id"])
            if trial["source_artifact_sha256"] != expected_hash:
                raise ValueError(f"{trial['trial_id']}: BROAD source artifact differs from frozen B9")
            vqf_estimates, vqf_valid = atlas._run_vqf(trial)
            input_csv = temp / f"{trial['trial_id']}.csv"
            atlas._write_eskf_input(input_csv, trial)
            baseline_trace = atlas._run_eskf(baseline_executable, input_csv, temp / "baseline.csv", "broad", keep_diagnostics=True)
            candidate_trace = atlas._run_eskf(candidate_executable, input_csv, temp / "candidate.csv", "broad", keep_diagnostics=True)
            baseline_result, baseline_detail, _ = atlas._variant_result(
                "broad_baseline", baseline_trace, vqf_valid, trial["timestamps_us"], trial, vqf_estimates, keep_trace=False
            )
            candidate_result, candidate_detail, _ = atlas._variant_result(
                "broad_candidate", candidate_trace, vqf_valid, trial["timestamps_us"], trial, vqf_estimates, keep_trace=False
            )
            shared, bscore, cscore = score_common(baseline_detail, candidate_detail, trial)
            reference = references[trial["trial_id"]]["eskf_broad"]["eskf_score_on_matched_timestamps"]
            baseline_tilt_deg = math.degrees(bscore["tilt_rms_rad"])
            reference_tilt_deg = math.degrees(reference["tilt_rms_rad"])
            if bscore["tilt_error_count"] != reference["tilt_error_count"] or abs(baseline_tilt_deg-reference_tilt_deg) > 0.0002:
                raise ValueError(f"{trial['trial_id']}: rerun baseline failed frozen B9 metric reproduction")
            movement_indices = [i for i, active in enumerate(trial["movement"]) if active]
            attempted = sum(candidate_trace["gravity_attempted"][i] for i in movement_indices)
            accepted = sum(candidate_trace["gravity_accepted"][i] for i in movement_indices)
            baseline_attempted_all = sum(baseline_trace["gravity_attempted"])
            baseline_accepted_all = sum(baseline_trace["gravity_accepted"])
            candidate_attempted_all = sum(candidate_trace["gravity_attempted"])
            candidate_accepted_all = sum(candidate_trace["gravity_accepted"])
            first_fault = atlas._first_fault(candidate_trace, trial)
            rows.append({
                "trial_id": trial["trial_id"], "source_artifact_sha256": trial["source_artifact_sha256"],
                "sample_count": len(trial["timestamps_us"]), "movement_sample_count": sum(trial["movement"]),
                "max_movement_gyro_axis_deg_s": math.degrees(max(
                    max(abs(float(v)) for v in trial["gyro_rad_s"][i]) for i in movement_indices
                )),
                "baseline_broad_fault": baseline_result["first_fault"]["cause"] if baseline_result["first_fault"] else "none",
                "candidate_broad_fault": first_fault["cause"] if first_fault else "none",
                "baseline_valid_movement_samples": baseline_result["eskf_valid_movement_sample_count"],
                "candidate_valid_movement_samples": candidate_result["eskf_valid_movement_sample_count"],
                "shared_valid_movement_samples": bscore["paired_movement_sample_count"], "pair_mask_identical": baseline_detail["pair_valid"] == candidate_detail["pair_valid"],
                "baseline_tilt_rms_deg": baseline_tilt_deg, "candidate_tilt_rms_deg": math.degrees(cscore["tilt_rms_rad"]),
                "candidate_minus_baseline_tilt_rms_deg": math.degrees(cscore["tilt_rms_rad"]) - baseline_tilt_deg,
                "vqf_tilt_rms_deg_on_shared_timestamps": math.degrees(atlas.score_paired_errors(
                    baseline_detail["vqf_errors"], trial["movement"], shared
                )["tilt_rms_rad"]),
                "candidate_gravity_attempts_during_movement": int(attempted),
                "candidate_gravity_accepted_during_movement": int(accepted),
                "baseline_gravity_attempts_all_samples": int(baseline_attempted_all),
                "baseline_gravity_accepted_all_samples": int(baseline_accepted_all),
                "candidate_gravity_attempts_all_samples": int(candidate_attempted_all),
                "candidate_gravity_accepted_all_samples": int(candidate_accepted_all),
                "candidate_first_fault_time_s": first_fault["time_s"] if first_fault else None,
                "candidate_fault_state_timestamp_us": first_fault["state_timestamp_us"] if first_fault else None,
                "candidate_fault_withheld_output_samples": sum(
                    active and health == "Fault" and not valid
                    for active, health, valid in zip(trial["movement"], candidate_trace["health"], candidate_trace["output_valid"])
                ),
            })

    csv_path = OUT / "broad_fast_rotation_gate_candidate.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    summary = {
        "schema": "b9.broad_fast_rotation_gravity_gate_candidate.v1",
        "dataset_revision": baseline_report["dataset_revision"],
        "trial_ids": list(TRIALS),
        "candidate": {"gyro_rate_limit_rad_s": CANDIDATE_GYRO_LIMIT, "dwell_samples": CANDIDATE_DWELL,
                      "acceleration_step_limit_m_s2": 0.20, "activation_timestamp_us": SCORE_START_US},
        "range_profile": "BROAD documented ±2000 dps / ±16 g profile retained",
        "baseline_reproduced_from_frozen_B9": True,
        "candidate_filter_patch_sha256": patch_sha,
        "candidate_replay_source_sha256": candidate_replay_sha,
        "baseline_filter_sha256": sha256(ROOT / "eskf15.hpp"),
        "baseline_replay_source_sha256": sha256(ROOT / "tools/b9_eskf_replay.cpp"),
        "baseline_report_sha256": sha256(BASELINE_REPORT),
        "runner_sha256": sha256(Path(__file__)),
        "production_filter_modified": False,
        "fault_latch_modified": False,
        "stale_output_safeguards_modified": False,
        "all_pair_masks_identical": all(row["pair_mask_identical"] for row in rows),
        "trials": rows,
    }
    out = OUT / "broad_fast_rotation_gate_candidate.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"trial_count": len(rows), "all_pair_masks_identical": summary["all_pair_masks_identical"],
                      "trials": [{key: row[key] for key in ("trial_id", "baseline_tilt_rms_deg", "candidate_tilt_rms_deg",
                                 "candidate_minus_baseline_tilt_rms_deg", "candidate_broad_fault",
                                 "candidate_gravity_attempts_during_movement", "candidate_gravity_accepted_during_movement",
                                 "baseline_gravity_accepted_all_samples", "candidate_gravity_accepted_all_samples")}
                                 for row in rows]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
