#!/usr/bin/env python3
"""Build and run reproducible PR3 paired characterization from a clean checkout."""

import argparse
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from validate_pr3_scenario_protocol import load_protocol


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v3.json"
PROFILES = {
    "baseline": ("IMU_ONLY", "UNKNOWN", False, "NONE"),
    "heading_sensor": ("IMU_WITH_SYNTHETIC_HEADING", "UNKNOWN", False, "NONE"),
    "external_static": ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", False, "NONE"),
    "truth_static": ("IMU_ONLY", "TRUTH_ORACLE_STATIC", False, "NONE"),
    "startup_bias": ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", True, "NONE"),
    "independent_heading": ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", True, "INDEPENDENT_MEASUREMENT"),
    "oracle_heading": ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", True, "SIMULATOR_ORACLE"),
}
def run(command, *, cwd=ROOT, capture=False):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=capture, check=False)
    if result.returncode:
        if capture:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise RuntimeError(f"command exited {result.returncode}: {shlex.join(map(str, command))}")
    return result.stdout if capture else ""


def compiler_version(compiler):
    result = subprocess.run([*compiler, "--version"], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.splitlines()[0] if result.returncode == 0 and result.stdout else "UNKNOWN"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL,
        help="versioned PR3 protocol JSON (defaults to the frozen v3 protocol)")
    parser.add_argument("--split", choices=("development", "held_out", "final_confirmation"), default="development")
    parser.add_argument("--first-seed", type=int)
    parser.add_argument("--last-seed", type=int)
    parser.add_argument("--scenarios")
    parser.add_argument("--rate-modes")
    parser.add_argument("--stress-modes", default="nominal,stress")
    parser.add_argument("--profiles", default="baseline")
    parser.add_argument("--output-dir")
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    parser.add_argument("--source-commit", default=os.environ.get("PR3_SOURCE_COMMIT"))
    parser.add_argument("--tree-dirty", choices=("yes", "no"), default=os.environ.get("PR3_TREE_DIRTY"))
    parser.add_argument("--sample-diagnostics", action="store_true",
        help="write per-sample state/covariance diagnostics for exactly one selected trial and profile")
    args = parser.parse_args()

    protocol_path = args.protocol.resolve()
    protocol = load_protocol(protocol_path)
    seeds = protocol["seeds"]
    if args.scenarios is None:
        args.scenarios = ",".join(s["id"] for s in protocol["scenarios"])
    if args.rate_modes is None:
        args.rate_modes = ",".join(m["id"] for m in protocol["sampling"]["rate_modes"])
    if args.output_dir is None:
        args.output_dir = str(ROOT / f"benchmarks/generated/pr3_protocol_v{protocol['protocol_version']}")
    seed_range = seeds[args.split]
    if args.first_seed is None:
        args.first_seed = seed_range["first_seed"]
    if args.last_seed is None:
        args.last_seed = min(args.first_seed + 3, seed_range["last_seed"])
    if not seed_range["first_seed"] <= args.first_seed <= args.last_seed <= seed_range["last_seed"]:
        parser.error(f"seed range must be inside frozen {args.split} range {seed_range['first_seed']}..{seed_range['last_seed']}")
    scenario_ids = args.scenarios.split(",")
    rate_ids = args.rate_modes.split(",")
    stress_modes = args.stress_modes.split(",")
    profiles = args.profiles.split(",")
    scenario_by_id = {s["id"]: i for i, s in enumerate(protocol["scenarios"])}
    rate_by_id = {m["id"]: i for i, m in enumerate(protocol["sampling"]["rate_modes"])}
    if not scenario_ids or any(value not in scenario_by_id for value in scenario_ids):
        parser.error("unknown or empty --scenarios selection")
    if not rate_ids or any(value not in rate_by_id for value in rate_ids):
        parser.error("unknown or empty --rate-modes selection")
    if not stress_modes or any(value not in ("nominal", "stress") for value in stress_modes):
        parser.error("--stress-modes must contain nominal and/or stress")
    if not profiles or any(value not in PROFILES for value in profiles):
        parser.error(f"--profiles must be selected from {', '.join(PROFILES)}")
    if args.sample_diagnostics and not (
        len(scenario_ids)==len(rate_ids)==len(stress_modes)==len(profiles)==1
        and args.first_seed==args.last_seed
    ):
        parser.error("--sample-diagnostics requires exactly one scenario, rate, stress mode, seed, and profile")

    output = Path(args.output_dir).resolve()
    input_dir = output / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    build_dir = output / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    compiler = shlex.split(args.cxx)
    if not compiler:
        parser.error("C++ compiler command is empty")
    header = build_dir / "pr3_scenario_protocol.hpp"
    run([sys.executable, str(ROOT / "tools/pr3_generate_scenario_header.py"), str(protocol_path), str(header)])
    generator = build_dir / "pr3_generate_inputs"
    evaluator = build_dir / "pr3_evaluate_stream"
    common = [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", f"-I{build_dir}"]
    run([*common, str(ROOT / "tools/pr3_generate_inputs.cpp"), "-o", str(generator)])
    run([*common, str(ROOT / "tools/pr3_evaluate_stream.cpp"), "-o", str(evaluator)])
    if args.source_commit:
        source_sha = args.source_commit
    else:
        source_sha = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    if args.tree_dirty:
        dirty = args.tree_dirty == "yes"
    else:
        dirty = bool(run(["git", "status", "--porcelain"], capture=True).strip())
    summary_path = output / "pr3_trial_summaries.csv"
    sample_trace_path = output / "pr3_sample_diagnostics.csv" if args.sample_diagnostics else None
    manifest = {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "source_commit": source_sha,
        "working_tree_dirty_at_run": dirty,
        "generator_source_sha256": hashlib.sha256((ROOT / "tools/pr3_generate_inputs.cpp").read_bytes()).hexdigest(),
        "evaluator_source_sha256": hashlib.sha256((ROOT / "tools/pr3_evaluate_stream.cpp").read_bytes()).hexdigest(),
        "header_codegen_source_sha256": hashlib.sha256((ROOT / "tools/pr3_generate_scenario_header.py").read_bytes()).hexdigest(),
        "compiler": compiler_version(compiler),
        "split": args.split,
        "seed_range_inclusive": [args.first_seed, args.last_seed],
        "scenarios": scenario_ids,
        "rate_modes": rate_ids,
        "stress_modes": stress_modes,
        "profiles": profiles,
        "input_streams": [],
        "classification": "SYNTHETIC_HOST_SIMULATION_ONLY; NOT_HARDWARE_QUALIFICATION",
        "pr2_gate_status": "OPEN",
    }
    with summary_path.open("w", newline="", encoding="utf-8") as summary_file:
        writer = None
        wrote_header = False
        for scenario in scenario_ids:
            for rate_id in rate_ids:
                rate_index = rate_by_id[rate_id]
                for stress in stress_modes:
                    for seed in range(args.first_seed, args.last_seed + 1):
                        stem = f"{scenario}__{rate_id}__{stress}__{seed}"
                        input_path = input_dir / f"{stem}.bin"
                        run([str(generator), str(input_path), args.split, scenario, str(rate_index), stress, str(seed)], capture=True)
                        input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
                        manifest["input_streams"].append({
                            "path": str(input_path.relative_to(output)),
                            "sha256": input_sha,
                            "scenario": scenario,
                            "rate_mode": rate_id,
                            "stress_mode": stress,
                            "split": args.split,
                            "seed": seed,
                        })
                        for profile in profiles:
                            sensor_input, startup, calibration, aid = PROFILES[profile]
                            config = {
                                "sensor_input": sensor_input,
                                "startup_knowledge": startup,
                                "startup_gyro_bias_calibration": "ON" if calibration else "OFF",
                                "runtime_aid": aid,
                                "evaluated_estimators": ["eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only"],
                            }
                            config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            trial_path = build_dir / "trial.csv"
                            evaluate_command=[str(evaluator), str(input_path), str(trial_path), args.split,
                                sensor_input, startup, "1" if calibration else "0", aid,
                                source_sha, config_sha, input_sha]
                            if sample_trace_path is not None:
                                evaluate_command.extend(["--sample-trace", str(sample_trace_path)])
                            run(evaluate_command, capture=True)
                            with trial_path.open(newline="", encoding="utf-8") as trial_file:
                                reader = csv.DictReader(trial_file)
                                if not wrote_header:
                                    writer = csv.DictWriter(summary_file, fieldnames=reader.fieldnames)
                                    writer.writeheader()
                                    wrote_header = True
                                for row in reader:
                                    writer.writerow(row)
        manifest_path = output / "pr3_run_manifest.json"
        if sample_trace_path is not None:
            covariance_trace_path = Path(str(sample_trace_path)+".first_failure_covariance.csv")
            manifest["sample_diagnostics"] = {
                "path": str(sample_trace_path.relative_to(output)),
                "sha256": hashlib.sha256(sample_trace_path.read_bytes()).hexdigest(),
                "first_failure_covariance_path": str(covariance_trace_path.relative_to(output)),
                "first_failure_covariance_sha256": hashlib.sha256(covariance_trace_path.read_bytes()).hexdigest(),
                "scope": "one selected development/held-out/confirmation trial; full covariance only at first failure per estimator",
            }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not wrote_header:
        raise RuntimeError("no trial summaries were generated")
    run([sys.executable, str(ROOT / "tools/summarize_pr3_benchmarks.py"),
        "--input", str(summary_path), "--output-dir", str(output)], capture=True)
    manifest["summary_csv_sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest["summary_report_sha256"] = hashlib.sha256((output / "pr3_summary.json").read_bytes()).hexdigest()
    manifest["figure_sha256"] = hashlib.sha256((output / "figures/pr3_tilt_rms.svg").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"PASS PR3 generated {len(manifest['input_streams'])} shared streams and paired summaries at {summary_path}")
    print(f"PR3 evidence manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL PR3 runner: {error}", file=sys.stderr)
        raise SystemExit(1)
