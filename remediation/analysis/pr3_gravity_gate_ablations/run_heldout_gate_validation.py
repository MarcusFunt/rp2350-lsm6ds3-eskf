#!/usr/bin/env python3
"""Validate one frozen gravity-gate candidate over the complete v5 held-out set."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from validate_pr3_scenario_protocol import protocol_source_bytes

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"
ARCHIVE = ROOT / "benchmarks/reports/pr3_protocol_v5_heldout100_all_factors_postfix_trials.csv.gz"
ARCHIVE_MANIFEST = ROOT / "benchmarks/manifests/pr3_protocol_v5_heldout100_all_factors_postfix.json"
SCORE_START_US = 3_000_000
CANDIDATE_GYRO_LIMIT = 0.48
CANDIDATE_DWELL = 7
PROFILE = ("IMU_ONLY", "UNKNOWN", "OFF", "NONE")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path, env=None, capture=False) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=capture, check=False)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {shlex.join(command)}\n"
            f"{result.stdout or ''}\n{result.stderr or ''}"
        )
    return result.stdout if capture else ""


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_reference() -> tuple[dict, dict[tuple, dict[str, str]]]:
    manifest = json.loads(ARCHIVE_MANIFEST.read_text(encoding="utf-8"))
    if sha256(ARCHIVE) != manifest["packaged_trial_csv_gz_sha256"]:
        raise ValueError("held-out baseline archive hash does not match its manifest")
    protocol_hash = hashlib.sha256(protocol_source_bytes(PROTOCOL)).hexdigest()
    if protocol_hash != manifest["protocol_sha256"]:
        raise ValueError("held-out baseline archive uses a different v5 protocol")
    expected_cells = manifest["input_streams"]
    if len(expected_cells) != 4800:
        raise ValueError(f"expected 4800 held-out input hashes, found {len(expected_cells)}")
    baseline: dict[tuple, dict[str, str]] = {}
    with gzip.open(ARCHIVE, "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if (row["sensor_input"], row["startup_knowledge"], row["startup_gyro_bias_calibration"], row["runtime_aid"]) != PROFILE:
                continue
            if row["estimator"] not in ("eskf_conservative", "mahony"):
                continue
            key = (row["seed_split"], row["seed"], row["scenario"], row["rate_mode"], row["stress_mode"], row["estimator"])
            if key in baseline:
                raise ValueError(f"duplicate baseline reference row {key}")
            baseline[key] = row
    if len(baseline) != 4800 * 2:
        raise ValueError(f"expected 9600 paired ESKF/Mahony reference rows, found {len(baseline)}")
    return manifest, baseline


def compile_candidate(temp: Path, compiler: list[str]) -> tuple[Path, Path, Path, str]:
    build, source = temp / "build", temp / "source"
    build.mkdir(); source.mkdir()
    run([sys.executable, str(ROOT / "tools/pr3_generate_scenario_header.py"), str(PROTOCOL),
         str(build / "pr3_scenario_protocol.hpp")], cwd=ROOT)

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
    evaluator = (ROOT / "tools/pr3_evaluate_stream.cpp").read_text(encoding="utf-8")
    include = '#include "../eskf15.hpp"'
    if evaluator.count(include) != 1:
        raise ValueError("evaluator filter include changed; refusing an ambiguous experimental patch")
    (source / "evaluator.cpp").write_text(evaluator.replace(include, '#include "eskf15.hpp"'), encoding="utf-8")
    generator = build / "pr3_generate_inputs"
    baseline_executable = build / "pr3_evaluate_stream_baseline"
    executable = build / "pr3_evaluate_stream"
    flags = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
             f"-I{build}", f"-I{source}"]
    run([*flags, str(ROOT / "tools/pr3_generate_inputs.cpp"), "-o", str(generator)], cwd=ROOT)
    run([*flags, "-DINERTIAL_GRAVITY_DIAGNOSTICS=1", str(ROOT / "tools/pr3_evaluate_stream.cpp"),
         "-o", str(baseline_executable)], cwd=ROOT)
    run([*flags, "-DINERTIAL_GRAVITY_DIAGNOSTICS=1", str(source / "evaluator.cpp"), "-o", str(executable)], cwd=ROOT)
    return generator, baseline_executable, executable, hashlib.sha256(patched_header.encode()).hexdigest()


def summarize(rows_in: list[dict[str, object]], group_keys: tuple[str, ...]) -> list[dict[str, object]]:
    groups: dict[tuple, list[dict[str, object]]] = defaultdict(list)
    for row in rows_in:
        groups[tuple(row[key] for key in group_keys)].append(row)
    output = []
    for key, group in sorted(groups.items()):
        deltas = [float(row["tilt_rms_delta_deg"]) for row in group]
        mean = statistics.fmean(deltas)
        sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        ci_half = 1.984 * sd / math.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
        output.append({
            **dict(zip(group_keys, key)),
            "trial_count": len(group),
            "baseline_eskf_tilt_rms_mean_deg": statistics.fmean(float(r["baseline_eskf_tilt_rms_deg"]) for r in group),
            "candidate_eskf_tilt_rms_mean_deg": statistics.fmean(float(r["candidate_eskf_tilt_rms_deg"]) for r in group),
            "mean_paired_delta_deg": mean,
            "mean_paired_delta_ci95_low_deg": mean - ci_half,
            "mean_paired_delta_ci95_high_deg": mean + ci_half,
            "candidate_better_count": sum(delta < -1e-9 for delta in deltas),
            "candidate_worse_count": sum(delta > 1e-9 for delta in deltas),
            "candidate_fault_trials": sum(int(r["candidate_faults"]) > 0 for r in group),
            "mean_gravity_attempts": statistics.fmean(int(r["gravity_attempts"]) for r in group),
            "mean_gravity_accepted": statistics.fmean(int(r["gravity_accepted"]) for r in group),
            "mean_angle_rejections": statistics.fmean(int(r["conservative_angle_rejected"]) for r in group),
            "mean_nis_rejections": statistics.fmean(int(r["nis_gate_rejected"]) for r in group),
        })
    return output


def main() -> int:
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    if not compiler:
        raise ValueError("CXX cannot be empty")
    archive_manifest, baseline = load_reference()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    rate_index = {item["id"]: i for i, item in enumerate(protocol["sampling"]["rate_modes"])}
    expected_hash = {
        (item["split"], str(item["seed"]), item["scenario"], item["rate_mode"], item["stress_mode"]): item["sha256"]
        for item in archive_manifest["input_streams"]
    }
    if len(expected_hash) != 4800:
        raise ValueError("held-out input manifest does not contain 4800 unique cells")
    current_commit = run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture=True).strip()

    trial_rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pr3-heldout-gravity-candidate-") as name:
        temp = Path(name)
        generator, baseline_evaluator, candidate_evaluator, patch_sha = compile_candidate(temp, compiler)
        input_path = temp / "input.bin"
        baseline_trial_path, candidate_trial_path = temp / "baseline_trial.csv", temp / "candidate_trial.csv"
        baseline_gravity_path, candidate_gravity_path = temp / "baseline_gravity.csv", temp / "candidate_gravity.csv"
        cells = archive_manifest["input_streams"]
        for index, cell in enumerate(cells, start=1):
            split, scenario, mode, seed = cell["split"], cell["scenario"], cell["stress_mode"], int(cell["seed"])
            rate = cell["rate_mode"]
            run([str(generator), str(input_path), split, scenario, str(rate_index[rate]), mode, str(seed)], cwd=ROOT, capture=True)
            actual_sha = sha256(input_path)
            key_base = (split, str(seed), scenario, rate, mode)
            if actual_sha != cell["sha256"] or actual_sha != expected_hash[key_base]:
                raise ValueError(f"generated held-out input hash mismatch for {key_base}")
            config_sha = baseline[(split, str(seed), scenario, rate, mode, "eskf_conservative")]["config_sha256"]
            candidate_config = {"baseline_config_sha256": config_sha,
                                "gravity_gate_candidate": {"static_gyro_limit_rad_s": CANDIDATE_GYRO_LIMIT,
                                                            "static_min_samples": CANDIDATE_DWELL}}
            candidate_config_sha = hashlib.sha256(json.dumps(candidate_config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            base_command = [str(input_path), split, *PROFILE[:2], "0", PROFILE[3],
                            current_commit, config_sha, actual_sha]
            candidate_command = [str(input_path), split, *PROFILE[:2], "0", PROFILE[3],
                                 current_commit, candidate_config_sha, actual_sha]
            run([str(baseline_evaluator), base_command[0], str(baseline_trial_path), *base_command[1:],
                 "--gravity-summary", str(baseline_gravity_path)], cwd=ROOT)
            run([str(candidate_evaluator), candidate_command[0], str(candidate_trial_path), *candidate_command[1:],
                 "--gravity-summary", str(candidate_gravity_path)], cwd=ROOT)
            baseline_result = {row["estimator"]: row for row in rows(baseline_trial_path)}
            candidate_result = {row["estimator"]: row for row in rows(candidate_trial_path)}
            baseline_diagnostics = {row["estimator"]: row for row in rows(baseline_gravity_path)}
            candidate_diagnostics = {row["estimator"]: row for row in rows(candidate_gravity_path)}
            current_baseline = baseline_result["eskf_conservative"]
            candidate = candidate_result["eskf_conservative"]
            ref_eskf = baseline[(*key_base, "eskf_conservative")]
            if not math.isclose(float(baseline_result["mahony"]["tilt_rms_deg"]),
                                float(candidate_result["mahony"]["tilt_rms_deg"]), abs_tol=0.0002):
                raise ValueError(f"Mahony changed between current baseline and candidate for {key_base}")
            baseline_diag = baseline_diagnostics["eskf_conservative"]
            candidate_diag = candidate_diagnostics["eskf_conservative"]
            trial_rows.append({
                "seed_split": split, "seed": seed, "scenario": scenario, "rate_mode": rate, "stress_mode": mode,
                "input_sha256": actual_sha,
                "baseline_config_sha256": config_sha, "candidate_config_sha256": candidate_config_sha,
                "archived_eskf_tilt_rms_deg": float(ref_eskf["tilt_rms_deg"]),
                "baseline_eskf_tilt_rms_deg": float(current_baseline["tilt_rms_deg"]),
                "candidate_eskf_tilt_rms_deg": float(candidate["tilt_rms_deg"]),
                "tilt_rms_delta_deg": float(candidate["tilt_rms_deg"]) - float(current_baseline["tilt_rms_deg"]),
                "mahony_tilt_rms_deg": float(candidate_result["mahony"]["tilt_rms_deg"]),
                "baseline_eskf_availability": float(current_baseline["availability"]),
                "candidate_availability": float(candidate["availability"]),
                "baseline_faults": int(current_baseline["faults"]),
                "baseline_resets": int(current_baseline["resets"]),
                "baseline_stale": int(current_baseline["stale"]),
                "candidate_faults": int(candidate["faults"]), "candidate_resets": int(candidate["resets"]),
                "candidate_stale": int(candidate["stale"]), "candidate_health_end": candidate["health_end"],
                "baseline_accel_bias_error_m_s2": float(current_baseline["accel_bias_error_m_s2"]),
                "baseline_gyro_bias_error_rad_s": float(current_baseline["gyro_bias_error_rad_s"]),
                "candidate_accel_bias_error_m_s2": float(candidate["accel_bias_error_m_s2"]),
                "candidate_gyro_bias_error_rad_s": float(candidate["gyro_bias_error_rad_s"]),
                "baseline_gravity_attempts": int(baseline_diag["gravity_attempts"]),
                "baseline_gravity_accepted": int(baseline_diag["gravity_accepted"]),
                "gravity_attempts": int(candidate_diag["gravity_attempts"]), "gravity_accepted": int(candidate_diag["gravity_accepted"]),
                "conservative_angle_rejected": int(candidate_diag["conservative_angle_rejected"]),
                "nis_gate_rejected": int(candidate_diag["nis_gate_rejected"]),
                "candidate_gate_failed_samples": int(candidate_diag["candidate_gate_failed_samples"]),
                "candidate_dwell_incomplete_samples": int(candidate_diag["candidate_dwell_incomplete_samples"]),
            })
            input_path.unlink()
            if index % 200 == 0:
                print(f"processed {index}/{len(cells)} held-out cells", flush=True)

    trial_path = OUT / "heldout_rate_0p48_dwell_7_trials.csv"
    fields = list(trial_rows[0])
    with trial_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(trial_rows)

    grouped = {
        "overall": summarize(trial_rows, ()),
        "by_scenario": summarize(trial_rows, ("scenario",)),
        "by_scenario_rate_stress": summarize(trial_rows, ("scenario", "rate_mode", "stress_mode")),
    }
    summary = {
        "schema": "pr3.heldout_gravity_gate_candidate_validation.v1",
        "candidate": {"gyro_rate_limit_rad_s": CANDIDATE_GYRO_LIMIT, "dwell_samples": CANDIDATE_DWELL,
                      "acceleration_step_limit_m_s2": 0.20, "activation_reported_timestamp_us": SCORE_START_US},
        "protocol_sha256": hashlib.sha256(protocol_source_bytes(PROTOCOL)).hexdigest(), "heldout_archive_sha256": sha256(ARCHIVE),
        "heldout_manifest_sha256": sha256(ARCHIVE_MANIFEST), "candidate_header_patch_sha256": patch_sha,
        "baseline_filter_sha256": hashlib.sha256((ROOT / "eskf15.hpp").read_bytes()).hexdigest(),
        "baseline_evaluator_sha256": hashlib.sha256((ROOT / "tools/pr3_evaluate_stream.cpp").read_bytes()).hexdigest(),
        "baseline_commit": current_commit,
        "historical_archive_source_commit": archive_manifest["source_commit"],
        "runner_sha256": sha256(Path(__file__)), "input_cell_count": len(trial_rows),
        "input_hashes_verified": True, "paired_mahony_reference_rows_verified": len(trial_rows),
        "production_filter_modified": False, "fault_latch_modified": False, "stale_output_safeguards_modified": False,
        "paired_mean_delta_deg": grouped["overall"][0]["mean_paired_delta_deg"],
        "paired_mean_delta_ci95_deg": [grouped["overall"][0]["mean_paired_delta_ci95_low_deg"],
                                        grouped["overall"][0]["mean_paired_delta_ci95_high_deg"]],
        "candidate_better_trials": grouped["overall"][0]["candidate_better_count"],
        "candidate_worse_trials": grouped["overall"][0]["candidate_worse_count"],
        "candidate_fault_trials": grouped["overall"][0]["candidate_fault_trials"],
        "group_summaries": grouped,
    }
    (OUT / "heldout_rate_0p48_dwell_7_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("input_cell_count", "input_hashes_verified", "paired_mean_delta_deg",
          "paired_mean_delta_ci95_deg", "candidate_better_trials", "candidate_worse_trials", "candidate_fault_trials")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
