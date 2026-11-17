#!/usr/bin/env python3
"""Reproduce the focused PR3 v5 gravity-gate ablations on the frozen B9 cells."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import pr3_synthetic_weakness_atlas as atlas  # noqa: E402

SCENARIOS = ("maneuver", "compound_motion")
STRESS_MODES = ("nominal", "stress")
SEED = 4001
RATE_INDEX = 1
BASELINE_COMMIT = "630e0d8c33ef1ee2bf744a1e84b80b1fafcde973"
PROTOCOL_SHA = "1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800"
CONFIG_SHA = "d5846fd833a2df91d69293d7545ee34bb719f848e238dfdd2eaa9317d4215fdd"
SCORE_START_US = 3_000_000  # PR3 epoch (1 s) plus the 2 s evaluation start.
SCORE_SAMPLE_COUNT = 2913  # Both 2 s and 16 s endpoints are included by v5.

VARIANTS = (
    ("baseline", "baseline", .12, .20, 35),
    ("gyro_0p24", "gyro_only", .24, .20, 35),
    ("gyro_0p48", "gyro_only", .48, .20, 35),
    ("gyro_0p96", "gyro_only", .96, .20, 35),
    ("step_0p40", "step_only", .12, .40, 35),
    ("step_0p80", "step_only", .12, .80, 35),
    ("dwell_17", "dwell_only", .12, .20, 17),
    ("dwell_7", "dwell_only", .12, .20, 7),
    ("rate_0p48_dwell_17", "candidate_policy", .48, .20, 17),
    ("rate_0p48_dwell_7", "candidate_policy", .48, .20, 7),
    ("rate_0p96_dwell_7", "candidate_policy", .96, .20, 7),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(command)}\n{result.stdout}\n{result.stderr}")


def summarize_evaluation(trace: list[dict[str, str]]) -> dict[str, object]:
    rows = [row for row in trace if 2.0 <= float(row["nominal_time_s"]) <= 16.0]
    if len(rows) != SCORE_SAMPLE_COUNT:
        raise ValueError(f"expected {SCORE_SAMPLE_COUNT} scored rows, found {len(rows)}")
    attempts = [row for row in rows if row["gravity_attempted"] == "true"]
    accepted = sum(row["gravity_accepted"] == "true" for row in attempts)
    reasons = Counter(row["gravity_reason"] for row in rows if row["gravity_reason"])

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key, "") != ""]

    def attempted_values(key: str) -> list[float]:
        return [float(row[key]) for row in attempts if row.get(key, "") != ""]

    cov = values("tilt_cov_trace")
    gyro_bias = values("gyro_bias_error_rad_s")
    accel_bias = values("accel_bias_error_m_s2")
    return {
        "evaluation_sample_count": len(rows),
        "gravity_attempts": len(attempts),
        "gravity_accepted": accepted,
        "gravity_rejected": len(attempts) - accepted,
        "candidate_gate_failed_samples": reasons.get("candidate_gate_failed", 0),
        "candidate_dwell_incomplete_samples": reasons.get("candidate_dwell_incomplete", 0),
        "gyro_gate_failures": sum(row["gyro_norm_gate_pass"] == "false" for row in rows),
        "accel_step_gate_failures": sum(row["accel_step_gate_pass"] == "false" for row in rows),
        "conservative_angle_rejected": reasons.get("conservative_angle_rejected", 0) + reasons.get("conservative_angle_gate_failed", 0),
        "nis_gate_rejected": reasons.get("nis_rejected", 0),
        "gravity_reason_counts": dict(reasons),
        "innovation_angle_mean_rad": statistics.fmean(attempted_values("gravity_innovation_angle_rad")) if attempted_values("gravity_innovation_angle_rad") else None,
        "innovation_angle_max_rad": max(attempted_values("gravity_innovation_angle_rad"), default=None),
        "nis_mean": statistics.fmean(attempted_values("gravity_nis")) if attempted_values("gravity_nis") else None,
        "nis_max": max(attempted_values("gravity_nis"), default=None),
        "tilt_covariance_trace_start_rad2": cov[0],
        "tilt_covariance_trace_end_rad2": cov[-1],
        "tilt_covariance_trace_max_rad2": max(cov),
        "covariance_positive_definite_fraction": sum(row["covariance_positive_definite"] == "true" for row in rows) / len(rows),
        "gyro_bias_error_start_rad_s": gyro_bias[0],
        "gyro_bias_error_end_rad_s": gyro_bias[-1],
        "gyro_bias_error_max_rad_s": max(gyro_bias),
        "accel_bias_error_start_m_s2": accel_bias[0],
        "accel_bias_error_end_m_s2": accel_bias[-1],
        "accel_bias_error_max_m_s2": max(accel_bias),
    }


def main() -> int:
    parser_compiler = os.environ.get("CXX", "g++")
    compiler = shlex.split(parser_compiler)
    if not compiler:
        raise ValueError("CXX cannot be empty")
    old = json.loads((OUT / "pr3_gravity_gate_ablation_results.json").read_text(encoding="utf-8"))
    expected_inputs = {(row["scenario"], row["stress_mode"]): row["input_sha256"] for row in old["results"] if row["variant_id"] == "baseline"}
    b9_summary: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for archived in atlas._load_archive_rows(atlas.ARCHIVE):
        if archived["scenario"] not in SCENARIOS or archived["rate_mode"] != "uniform_208hz" or archived["seed"] != str(SEED):
            continue
        if archived["stress_mode"] not in STRESS_MODES or archived["estimator"] not in ("eskf_conservative", "mahony"):
            continue
        b9_summary.setdefault((archived["scenario"], archived["stress_mode"]), {})[archived["estimator"]] = archived

    run_rows: list[dict[str, object]] = []
    eval_rows: list[dict[str, object]] = []
    joined_candidate_rows: list[dict[str, object]] = []
    patch_sha = ""
    with tempfile.TemporaryDirectory(prefix="pr3-gravity-gate-b9-") as name:
        temp = Path(name)
        build, source = temp / "build", temp / "source"
        build.mkdir(); source.mkdir()
        run([sys.executable, str(ROOT / "tools/pr3_generate_scenario_header.py"),
             str(ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"),
             str(build / "pr3_scenario_protocol.hpp")], cwd=ROOT)

        header = (ROOT / "eskf15.hpp").read_text(encoding="utf-8")
        insertion = "        const float an=imu.accel_mps2.norm();\n"
        override = f'''        if (imu.timestamp_us >= {SCORE_START_US}ull) {{
            if (const char* value=std::getenv("PR3_ABLATION_GYRO_LIMIT")) config_.static_gyro_limit=std::strtof(value,nullptr);
            if (const char* value=std::getenv("PR3_ABLATION_STEP_LIMIT")) config_.static_accel_step_limit=std::strtof(value,nullptr);
            if (const char* value=std::getenv("PR3_ABLATION_DWELL")) config_.static_min_samples=static_cast<unsigned>(std::strtoul(value,nullptr,10));
        }}
'''
        if header.count(insertion) != 1:
            raise ValueError("filter insertion point changed; refusing an ambiguous experimental patch")
        ratio = "const float step_ratio=accel_step/config_.static_accel_step_limit;"
        if header.count(ratio) != 1:
            raise ValueError("step-noise normalization changed; refusing an ambiguous experimental patch")
        header = "#include <cstdlib>\n" + header.replace(insertion, override + insertion).replace(
            ratio, "const float step_ratio=accel_step/0.20f;")
        patch_sha = sha256_bytes(header.encode())
        (source / "eskf15.hpp").write_text(header, encoding="utf-8")
        evaluator = (ROOT / "tools/pr3_evaluate_stream.cpp").read_text(encoding="utf-8")
        evaluator = evaluator.replace('#include "../eskf15.hpp"', '#include "eskf15.hpp"')
        (source / "evaluator.cpp").write_text(evaluator, encoding="utf-8")
        flags = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", f"-I{build}", f"-I{source}"]
        generator, exe = build / "pr3_generate_inputs", build / "pr3_evaluate_stream"
        run([*flags, str(ROOT / "tools/pr3_generate_inputs.cpp"), "-o", str(generator)], cwd=ROOT)
        run([*flags, "-DINERTIAL_GRAVITY_DIAGNOSTICS=1", str(source / "evaluator.cpp"), "-o", str(exe)], cwd=ROOT)

        for scenario in SCENARIOS:
            for mode in STRESS_MODES:
                input_path = temp / f"{scenario}_{mode}.bin"
                run([str(generator), str(input_path), "development", scenario, str(RATE_INDEX), mode, str(SEED)], cwd=ROOT)
                input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
                if input_sha != expected_inputs[(scenario, mode)]:
                    raise ValueError(f"generated {scenario}/{mode} hash differs from frozen B9 input")

                for variant_id, kind, gyro_limit, step_limit, dwell in VARIANTS:
                    label = f"{variant_id}__{scenario}__{mode}"
                    trial_path, summary_path = temp / f"{label}.csv", temp / f"{label}_gravity_summary.csv"
                    trace_path = temp / f"{label}_gravity.csv"
                    command = [str(exe), str(input_path), str(trial_path), "development", "IMU_ONLY", "UNKNOWN", "0", "NONE",
                               BASELINE_COMMIT, CONFIG_SHA, input_sha, "--gravity-summary", str(summary_path), "--gravity-trace", str(trace_path)]
                    sample_path = None
                    if kind == "candidate_policy":
                        sample_path = temp / f"{label}_samples.csv"
                        command.extend(["--sample-trace", str(sample_path)])
                    env = os.environ.copy()
                    env.update({"PR3_ABLATION_GYRO_LIMIT": str(gyro_limit),
                                "PR3_ABLATION_STEP_LIMIT": str(step_limit),
                                "PR3_ABLATION_DWELL": str(dwell)})
                    run(command, cwd=ROOT, env=env)

                    summary = {row["estimator"]: row for row in read_csv(trial_path)}
                    diagnostics = {row["estimator"]: row for row in read_csv(summary_path)}
                    if "eskf_conservative" not in summary or "mahony" not in summary or "eskf_conservative" not in diagnostics:
                        raise ValueError(f"missing ESKF or Mahony result for {label}")
                    eskf_rms = float(summary["eskf_conservative"]["tilt_rms_deg"])
                    mahony_rms = float(summary["mahony"]["tilt_rms_deg"])
                    expected = b9_summary[(scenario, mode)]
                    if variant_id == "baseline":
                        for estimator, value in (("eskf_conservative", eskf_rms), ("mahony", mahony_rms)):
                            if abs(value - float(expected[estimator]["tilt_rms_deg"])) > .0002:
                                raise ValueError(f"baseline {label}/{estimator} does not reproduce frozen B9 metric")
                    elif abs(mahony_rms - float(expected["mahony"]["tilt_rms_deg"])) > .0002:
                        raise ValueError(f"Mahony changed across ESKF variants for {label}")

                    gravity_trace = read_csv(trace_path)
                    evaluation = summarize_evaluation(gravity_trace)
                    full = diagnostics["eskf_conservative"]
                    source_row = next(row for row in old["results"] if row["variant_id"] == variant_id and row["scenario"] == scenario and row["stress_mode"] == mode)
                    row = dict(source_row)
                    row.update({
                        "eskf_tilt_rms_deg": eskf_rms,
                        "mahony_tilt_rms_deg": mahony_rms,
                        "eskf_minus_mahony_tilt_rms_deg": eskf_rms - mahony_rms,
                        "eskf_rms_change_from_b9_deg": eskf_rms - float(expected["eskf_conservative"]["tilt_rms_deg"]),
                        "gravity_attempts": int(full["gravity_attempts"]),
                        "gravity_accepted": int(full["gravity_accepted"]),
                        "gravity_rejected": int(full["gravity_rejected"]),
                        "candidate_gate_failed_samples": int(full["candidate_gate_failed_samples"]),
                        "candidate_dwell_incomplete_samples": int(full["candidate_dwell_incomplete_samples"]),
                        "gyro_gate_failures": int(full["gyro_norm_gate_failures"]),
                        "accel_step_gate_failures": int(full["accel_step_gate_failures"]),
                        "conservative_angle_rejected": int(full["conservative_angle_rejected"]),
                        "nis_gate_rejected": int(full["nis_gate_rejected"]),
                        "gyro_bias_error_end_rad_s": float(full["gyro_bias_error_rad_s"]),
                        "accel_bias_error_end_m_s2": float(full["accel_bias_error_m_s2"]),
                        "evaluation_diagnostics": evaluation,
                        "source_report": "remediation/analysis/pr3_gravity_gate_ablations/PR3_GRAVITY_GATE_ABLATIONS.md",
                    })
                    run_rows.append(row)
                    eval_rows.append({"variant_id": variant_id, "variant_kind": kind, "scenario": scenario,
                                      "stress_mode": mode, "seed": SEED, "input_sha256": input_sha, **evaluation})

                    if sample_path is not None:
                        sample_trace = read_csv(sample_path)
                        conservative = [item for item in sample_trace if item["estimator"] == "eskf_conservative"]
                        atlas.validate_trace_alignment(conservative, gravity_trace, expected_samples=atlas.EXPECTED_SAMPLES)
                        samples = atlas._read_input_stream(input_path, scenario, mode, PROTOCOL_SHA)
                        mahony_trace = atlas._run_mahony(samples)
                        joined = atlas._build_trace(
                            samples, conservative, gravity_trace, mahony_trace,
                            scenario=scenario, stress_mode=mode, seed=SEED, input_sha256=input_sha,
                        )
                        for joined_row in joined:
                            joined_row["variant_id"] = variant_id
                        joined_candidate_rows.extend(joined)

    output = dict(old)
    output.update({
        "status": "PASS",
        "results": run_rows,
        "evaluation_window": {"nominal_time_s_inclusive": [2.0, 16.0], "samples_per_cell": SCORE_SAMPLE_COUNT,
                              "gate_overrides_start_at_reported_timestamp_us": SCORE_START_US},
        "evaluation_window_diagnostics": eval_rows,
        "temporary_experiment": {
            "gate_override_activation": "per reported sample timestamp >= 3000000 us (PR3 epoch plus the scored-window start)",
            "accel_step_soft_noise_scale_pinned_m_s2": .20,
            "production_filter_modified": False,
        },
        "source_hashes": {
            **old["source_hashes"],
            "experiment_filter_patch_sha256": patch_sha,
            "ablation_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "trace_join_helper_sha256": hashlib.sha256((ROOT / "tools/pr3_synthetic_weakness_atlas.py").read_bytes()).hexdigest(),
        },
        "step_noise_scale_pinned_m_s2": .20,
    })
    (OUT / "pr3_gravity_gate_ablation_results.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    csv_fields = [key for key in run_rows[0] if key != "evaluation_diagnostics"]
    with (OUT / "pr3_gravity_gate_ablation_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader(); writer.writerows(run_rows)
    eval_fields = [key for key in eval_rows[0] if key != "gravity_reason_counts"]
    with (OUT / "evaluation_gate_ablation_diagnostics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*eval_fields, "gravity_reason_counts"], lineterminator="\n")
        writer.writeheader()
        for item in eval_rows:
            writer.writerow({**item, "gravity_reason_counts": json.dumps(item["gravity_reason_counts"], sort_keys=True)})
    (OUT / "evaluation_gate_ablation_diagnostics.json").write_text(json.dumps(eval_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    candidate_trace = OUT / "traces/gravity_gate_candidate_seed4001.csv.gz"
    candidate_trace.parent.mkdir(parents=True, exist_ok=True)
    if not joined_candidate_rows:
        raise ValueError("candidate-policy sample traces were not captured")
    with gzip.open(candidate_trace, "wt", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(joined_candidate_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(joined_candidate_rows)
    print(f"PASS B9-matched gate ablations: {len(run_rows)} cells; baseline and Mahony checks passed; patch SHA-256 {patch_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
