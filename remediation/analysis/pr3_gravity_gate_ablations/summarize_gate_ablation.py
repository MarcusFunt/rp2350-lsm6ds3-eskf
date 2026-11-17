#!/usr/bin/env python3
"""Summarize scored-window diagnostics and render the PR3 gravity-gate report."""

from __future__ import annotations

import csv
import ast
import gzip
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
B9 = ROOT / "remediation/analysis/pr3_synthetic_weaknesses_b9"
CASES = ("maneuver", "compound_motion")
MODES = ("nominal", "stress")
CANDIDATES = ("rate_0p48_dwell_17", "rate_0p48_dwell_7", "rate_0p96_dwell_7")
EVALUATION_SAMPLES = 2913


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def avg(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def write_diagnostics_and_report() -> None:
    result = json.loads((OUT / "pr3_gravity_gate_ablation_results.json").read_text(encoding="utf-8"))
    result_by_key = {(row["variant_id"], row["scenario"], row["stress_mode"]): row for row in result["results"]}
    baseline = {
        (row["scenario"], row["stress_mode"]): row
        for row in rows(B9 / "pr3_synthetic_weakness_summary.csv")
        if row["scenario"] in CASES
    }
    trace_groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    trace_path = OUT / "traces/gravity_gate_candidate_seed4001.csv.gz"
    with gzip.open(trace_path, "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["evaluation_sample"].lower() == "true":
                trace_groups[(row["variant_id"], row["scenario"], row["stress_mode"])].append(row)

    diagnostic_rows: list[dict[str, object]] = []
    for (scenario, mode), row in sorted(baseline.items()):
        diagnostic_rows.append({
            "policy": "B9_baseline", "scenario": scenario, "stress_mode": mode,
            "eskf_tilt_rms_deg": float(row["eskf_conservative_tilt_rms_deg_archive"]),
            "mahony_tilt_rms_deg": float(row["mahony_tilt_rms_deg_archive"]),
            "eval_gravity_attempts": 0, "eval_gravity_accepted": 0,
            "eval_angle_rejected": 0, "eval_nis_rejected": 0,
            "eval_innovation_angle_mean_rad": None, "eval_innovation_angle_max_rad": None,
            "eval_nis_mean": None, "eval_nis_max": None,
            "tilt_cov_trace_start_rad2": float(row["tilt_covariance_trace_start_rad2"]),
            "tilt_cov_trace_end_rad2": float(row["tilt_covariance_trace_end_rad2"]),
            "tilt_cov_trace_max_rad2": float(row["tilt_covariance_trace_max_rad2"]),
            "covariance_positive_definite_fraction": float(row["covariance_positive_definite_fraction"]),
            "gyro_bias_error_start_rad_s": float(row["eskf_gyro_bias_error_start_rad_s"]),
            "gyro_bias_error_end_rad_s": float(row["eskf_gyro_bias_error_end_rad_s"]),
            "gyro_bias_error_max_rad_s": float(row["eskf_gyro_bias_error_max_rad_s"]),
            "accel_bias_error_start_m_s2": float(row["eskf_accel_bias_error_start_m_s2"]),
            "accel_bias_error_end_m_s2": float(row["eskf_accel_bias_error_end_m_s2"]),
            "accel_bias_error_max_m_s2": float(row["eskf_accel_bias_error_max_m_s2"]),
            "evaluation_sample_count": EVALUATION_SAMPLES,
            "input_sha256": row["input_sha256"],
            "gate_reason_counts": ast.literal_eval(row["evaluation_gravity_reason_counts"]),
        })

    for (policy, scenario, mode), trace in sorted(trace_groups.items()):
        if policy not in CANDIDATES:
            continue
        if len(trace) != EVALUATION_SAMPLES:
            raise ValueError(f"{policy}/{scenario}/{mode}: expected {EVALUATION_SAMPLES} scored trace rows")
        source = result_by_key[(policy, scenario, mode)]
        evaluation = source["evaluation_diagnostics"]
        attempts = [row for row in trace if row["gravity_attempted"].lower() == "true"]
        accepted = sum(row["gravity_accepted"].lower() == "true" for row in attempts)
        reasons = Counter(row["gravity_reason"] for row in trace if row["gravity_reason"])

        def values(field: str, *, attempted: bool = False) -> list[float]:
            selected = attempts if attempted else trace
            return [float(row[field]) for row in selected if row.get(field, "") != ""]

        gyro_bias = values("eskf_gyro_bias_error_rad_s")
        accel_bias = values("eskf_accel_bias_error_m_s2")
        cov = values("tilt_cov_trace_rad2")
        innovation = values("gravity_innovation_angle_rad", attempted=True)
        nis = values("gravity_nis", attempted=True)
        eskf_rms = math.sqrt(math.fsum(float(row["eskf_tilt_error_deg"]) ** 2 for row in trace) / len(trace))
        mahony_rms = math.sqrt(math.fsum(float(row["mahony_tilt_error_deg"]) ** 2 for row in trace) / len(trace))
        if abs(eskf_rms - float(source["eskf_tilt_rms_deg"])) > .002 or abs(mahony_rms - float(source["mahony_tilt_rms_deg"])) > .002:
            raise ValueError(f"{policy}/{scenario}/{mode}: joined trace RMS differs from replay summary")
        if (len(attempts), accepted) != (evaluation["gravity_attempts"], evaluation["gravity_accepted"]):
            raise ValueError(f"{policy}/{scenario}/{mode}: joined trace gate counts differ from replay summary")
        diagnostic_rows.append({
            "policy": policy, "scenario": scenario, "stress_mode": mode,
            "eskf_tilt_rms_deg": eskf_rms, "mahony_tilt_rms_deg": mahony_rms,
            "eval_gravity_attempts": len(attempts), "eval_gravity_accepted": accepted,
            "eval_angle_rejected": reasons.get("conservative_angle_gate_failed", 0) + reasons.get("conservative_angle_rejected", 0),
            "eval_nis_rejected": reasons.get("nis_rejected", 0),
            "eval_innovation_angle_mean_rad": avg(innovation),
            "eval_innovation_angle_max_rad": max(innovation, default=None),
            "eval_nis_mean": avg(nis), "eval_nis_max": max(nis, default=None),
            "tilt_cov_trace_start_rad2": cov[0], "tilt_cov_trace_end_rad2": cov[-1],
            "tilt_cov_trace_max_rad2": max(cov),
            "covariance_positive_definite_fraction": sum(row["covariance_positive_definite"].lower() == "true" for row in trace) / len(trace),
            "gyro_bias_error_start_rad_s": gyro_bias[0], "gyro_bias_error_end_rad_s": gyro_bias[-1],
            "gyro_bias_error_max_rad_s": max(gyro_bias),
            "accel_bias_error_start_m_s2": accel_bias[0], "accel_bias_error_end_m_s2": accel_bias[-1],
            "accel_bias_error_max_m_s2": max(accel_bias),
            "evaluation_sample_count": len(trace), "input_sha256": source["input_sha256"],
            "gate_reason_counts": dict(reasons),
        })

    diagnostic_rows.sort(key=lambda row: (row["scenario"], row["stress_mode"], row["policy"]))
    diagnostic = {
        "schema": "org.marcusfunt.pr3_gravity_gate_eval_diagnostics.v1",
        "evaluation_window_nominal_time_s": [2.0, 16.0], "endpoint_policy": "inclusive",
        "score_sample_count": EVALUATION_SAMPLES,
        "baseline_source": "frozen B9 synthetic weakness archive-matched summary",
        "candidate_source": "temporary time-gated replay, sample-joined gravity diagnostics",
        "rows": diagnostic_rows,
    }
    (OUT / "candidate_policy_diagnostics.json").write_text(json.dumps(diagnostic, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fields = list(diagnostic_rows[0])
    with (OUT / "candidate_policy_diagnostics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in diagnostic_rows:
            writer.writerow({**row, "gate_reason_counts": json.dumps(row["gate_reason_counts"], sort_keys=True)})

    variants = [row["id"] for row in result["variants"]]
    summary = []
    for variant in variants:
        selected = [row for row in result["results"] if row["variant_id"] == variant]
        details = [row["evaluation_diagnostics"] for row in selected]
        summary.append({
            "variant": variant,
            "mean_eskf": avg([float(row["eskf_tilt_rms_deg"]) for row in selected]),
            "mean_mahony": avg([float(row["mahony_tilt_rms_deg"]) for row in selected]),
            "mean_delta": avg([float(row["eskf_minus_mahony_tilt_rms_deg"]) for row in selected]),
            "accepted": sum(row["gravity_accepted"] for row in details),
            "attempted": sum(row["gravity_attempts"] for row in details),
            "angle": sum(row["conservative_angle_rejected"] for row in details),
            "nis": sum(row["nis_gate_rejected"] for row in details),
            "candidate_fail": sum(row["candidate_gate_failed_samples"] for row in details),
        })
    by_result = {(row["variant_id"], row["scenario"], row["stress_mode"]): row for row in result["results"]}
    by_diagnostic = {(row["policy"], row["scenario"], row["stress_mode"]): row for row in diagnostic_rows}

    lines = [
        "# PR3 ESKF gravity-gate ablations", "",
        "Date: 2026-11-17 · protocol v5 · development seed 4001 · uniform 208 Hz.", "",
        f"Frozen reference: B9 commit `{result['baseline_commit']}`; [baseline lock](../b9_reference_baseline/B9_REFERENCE_BASELINE.md). This analysis replays the exact B9 maneuver and compound-motion nominal/stress inputs. The four input hashes match the frozen B9 rows.", "",
        "## Method", "",
        "Eleven temporary ESKF setting variants replay the same four streams. Gyro-rate, adjacent acceleration-step and dwell gates are varied one at a time, followed by three combined rate+dwell candidates. Overrides activate at reported timestamp 3,000,000 µs, the 2 s start of the fixed B9 score window; all earlier samples retain B9 settings. The step-dependent soft-noise scale is pinned at 0.20 m/s² while the step candidate gate changes. Production `eskf15.hpp` and gravity policy are unchanged.", "",
        f"ESKF and Mahony orientation RMS use the same 2,913 sample evaluation window (2–16 s inclusive). Gate, innovation, covariance and bias diagnostics below use those same samples. NIS and innovation are blank when no gravity update was attempted. The temporary filter patch SHA-256 is `{result['source_hashes']['experiment_filter_patch_sha256']}`.", "",
        "All baseline ESKF and Mahony metrics reproduce B9 within 0.0002°, and Mahony metrics remain identical across the variants.", "",
        "## Aggregate comparison", "",
        "| Variant | Mean ESKF RMS (°) | Mean Mahony RMS (°) | Mean ESKF−Mahony (°) | Eval accepted / attempted | Angle rejects | NIS rejects | Candidate-gate failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(f"| `{row['variant']}` | {row['mean_eskf']:.3f} | {row['mean_mahony']:.3f} | {row['mean_delta']:+.3f} | {row['accepted']} / {row['attempted']} | {row['angle']} | {row['nis']} | {row['candidate_fail']} |")

    lines.extend([
        "", "## Per-cell gate ablations", "",
        "The first eight variants isolate one gate at a time. Error, update, innovation, covariance and bias values use the scored window.", "",
        "| Variant | Case | ESKF RMS (°) | Mahony RMS (°) | ESKF Δ from B9 (°) | Accepted / attempted | Angle/NIS rejects | Innovation max (rad) | Covariance end (rad²) | Gyro-bias end (rad/s) | Accel-bias error end (m/s²) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for variant in variants[:8]:
        for scenario in CASES:
            for mode in MODES:
                row = by_result[(variant, scenario, mode)]
                d = row["evaluation_diagnostics"]
                inv = "—" if d["innovation_angle_max_rad"] is None else f"{d['innovation_angle_max_rad']:.3f}"
                lines.append(f"| `{variant}` | {scenario} / {mode} | {row['eskf_tilt_rms_deg']:.3f} | {row['mahony_tilt_rms_deg']:.3f} | {row['eskf_rms_change_from_b9_deg']:+.3f} | {d['gravity_accepted']} / {d['gravity_attempts']} | {d['conservative_angle_rejected']} / {d['nis_gate_rejected']} | {inv} | {d['tilt_covariance_trace_end_rad2']:.4f} | {d['gyro_bias_error_end_rad_s']:.4f} | {d['accel_bias_error_end_m_s2']:.3f} |")

    lines.extend([
        "", "## Candidate gravity-aiding policies", "",
        "These three combined candidates retain the Conservative innovation-angle and NIS checks. The joined candidate trace exposes per-sample attitude, innovation, covariance and bias effects.", "",
        "| Policy | Case | ESKF RMS (°) | Accepted / attempted | Angle rejects | Innovation mean / max (rad) | NIS mean / max | Covariance start / end / max (rad²) | Gyro-bias start → end (rad/s) | Accel-bias error start → end (m/s²) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for policy in CANDIDATES:
        for scenario in CASES:
            for mode in MODES:
                row = by_diagnostic[(policy, scenario, mode)]
                inv = "—" if row["eval_innovation_angle_mean_rad"] is None else f"{row['eval_innovation_angle_mean_rad']:.3f} / {row['eval_innovation_angle_max_rad']:.3f}"
                nis = "—" if row["eval_nis_mean"] is None else f"{row['eval_nis_mean']:.3f} / {row['eval_nis_max']:.3f}"
                cov = f"{row['tilt_cov_trace_start_rad2']:.4f} / {row['tilt_cov_trace_end_rad2']:.4f} / {row['tilt_cov_trace_max_rad2']:.4f}"
                gyro = f"{row['gyro_bias_error_start_rad_s']:.4f} → {row['gyro_bias_error_end_rad_s']:.4f}"
                accel = f"{row['accel_bias_error_start_m_s2']:.3f} → {row['accel_bias_error_end_m_s2']:.3f}"
                lines.append(f"| `{policy}` | {scenario} / {mode} | {row['eskf_tilt_rms_deg']:.3f} | {row['eval_gravity_accepted']} / {row['eval_gravity_attempts']} | {row['eval_angle_rejected']} | {inv} | {nis} | {cov} | {gyro} | {accel} |")

    lines.extend([
        "", "## Findings", "",
        "The B9 conservative gate formed zero gravity measurements across the four scored cells: all 2,913 samples per cell failed candidate eligibility, with the gyro-rate gate failing throughout. The 14 accepted updates seen in each nominal baseline run occurred before scoring. Baseline has no evaluation-window innovation or NIS values; those are unmeasured, not zero.", "",
        "Changing the acceleration-step threshold or dwell alone had no scored-window effect. With the default 0.12 rad/s gyro limit, all motion samples still failed candidate eligibility. Raising the gyro limit to 0.24 rad/s opened 10 attempts in compound-motion nominal; all 10 failed the Conservative innovation-angle check.", "",
        "Relaxing gyro rate to 0.48 or 0.96 rad/s opened the gate but degraded maneuver nominal: ESKF RMS increased from 3.872° to 12.927° or 21.470° in the one-at-a-time runs. Twenty-seven or 81 attempts were rejected by the innovation-angle check; accepted updates also harmed the state. End gyro-bias error rose from 0.0182 to 0.0651 or 0.0940 rad/s, and accelerometer-bias error rose from 0.033 to 0.266 or 0.314 m/s². NIS rejected none.", "",
        "Compound-motion nominal improved from 5.226° to 2.864° or 2.753° under the same gyro relaxations, but stayed behind Mahony at 2.032°. ESKF accelerometer-bias error ended at 0.713 or 0.609 m/s². Covariance remained positive definite. The global relaxation therefore helps compound nominal and harms maneuver nominal; it is not safe to promote. Stress cases gain only one to four accepted updates with the combined short-dwell policies and retain larger orientation error.", "",
        "The traces point to a measurement-model problem under dynamic acceleration, not covariance loss. The baseline gate blocks gravity before innovation formation, while indiscriminately opening the gate can make the gravity direction absorb linear acceleration into attitude and accelerometer bias. No candidate is promoted to production. A safer follow-up is an orientation-only gravity correction or a motion-aware acceleration rejection policy on these same cells, followed by more seeds and scenarios.", "",
        "## Artifacts", "",
        "- `evaluation_gate_ablation_diagnostics.csv` and `.json`: scored-window gate, innovation, covariance and bias summaries for all 44 variant/cell combinations.",
        "- `candidate_policy_diagnostics.csv` and `.json`: B9 baseline versus three candidates across the same four cells.",
        "- `traces/gravity_gate_candidate_seed4001.csv.gz`: per-sample paired orientation errors, bias state, covariance, innovation and gate outcomes for the combined candidates.",
        "- `pr3_gravity_gate_ablation_results.json` and `pr3_gravity_gate_ablation_summary.csv`: replay metrics, whole-run counters, B9 input checks and source hashes.",
        "- `run_gate_ablation.py` and `summarize_gate_ablation.py`: reproducible WSL replay and report generation.", "",
        "This is selected development-seed simulation evidence. The frozen B9 reference files remain unchanged; no hardware validation is implied.", "",
    ])
    (OUT / "PR3_GRAVITY_GATE_ABLATIONS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"PASS diagnostics/report: {len(diagnostic_rows)} candidate/baseline rows, 44 gate rows, {len(lines)} report lines")


if __name__ == "__main__":
    write_diagnostics_and_report()
