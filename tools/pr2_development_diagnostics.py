#!/usr/bin/env python3
"""Extract and summarize the preregistered PR 2 representative development traces."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path


SELECTORS = (
    ("lateral_accel_0p2g", "IMU_ONLY", "LegacyHeuristic", "NONE"),
    ("lateral_accel_0p2g", "IMU_ONLY", "Conservative", "NONE"),
    ("pure_roll", "IMU_ONLY", "Conservative", "NONE"),
    ("pure_roll", "TRUSTED_AIDED", "Conservative", "independent_heading_1hz"),
    ("slow_yaw", "IMU_ONLY", "Conservative", "NONE"),
    ("slow_yaw", "TRUSTED_AIDED", "Conservative", "independent_heading_1hz"),
)
KEYS = (
    "evaluation_protocol_version", "scenario", "noise_mode", "seed_split", "seed",
    "input_mode", "startup_knowledge", "startup_calibration", "runtime_aid", "estimator",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pearson(xs, ys):
    if len(xs) < 2 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return None
    return statistics.correlation(xs, ys)


def quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def number(row, name):
    value = row.get(name, "")
    return float(value) if value else None


def load_selected(path):
    with path.open(newline="", encoding="utf-8") as stream:
        all_rows = list(csv.DictReader(stream))
    selected = {}
    for selector in SELECTORS:
        scenario, mode, estimator, aid = selector
        matches = [r for r in all_rows if
            (r["scenario"], r["input_mode"], r["estimator"], r["runtime_aid"]) == selector
            and r["noise_mode"] == "combined"
            and r["seed_split"] == "development" and r["seed"] == "101"
            and r["startup_knowledge"] == "EXTERNALLY_VERIFIED_STATIC"
            and r["startup_calibration"] == "OFF"]
        if len(matches) != 2001:
            raise ValueError(f"{path}: expected 2001 rows for {selector}, got {len(matches)}")
        matches.sort(key=lambda r: float(r["time_s"]))
        if matches[0]["time_s"] != "2.00000000" or matches[-1]["time_s"] != "12.00000000":
            raise ValueError(f"{path}: unexpected time window for {selector}")
        selected[selector] = matches
    return selected


def load_summaries(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return {tuple(row[k] for k in KEYS): row for row in rows}


def summarize(selector, rows, summary):
    scenario, mode, estimator, aid = selector
    times = [float(r["time_s"]) for r in rows]
    tilt = [float(r["tilt_error_deg"]) for r in rows]
    yaw = [float(r["euler_yaw_error_deg"]) for r in rows]
    bias_error = {
        axis: [float(r[f"estimate_bg{axis}"]) - float(r[f"truth_bg{axis}"]) for r in rows]
        for axis in "xyz"
    }
    # Scenario intervals come directly from the frozen PR 1 truth generator.
    in_motion = lambda t: 2.0 <= t < 8.0 if scenario != "slow_yaw" else 2.0 <= t <= 12.0
    motion_rows = [r for r, t in zip(rows, times) if in_motion(t)]
    recovery_rows = [r for r, t in zip(rows, times) if scenario != "slow_yaw" and 8.0 <= t <= 12.0]
    event_counts = Counter(r["gravity_event"] for r in rows)
    motion_events = Counter(r["gravity_event"] for r in motion_rows)
    recovery_events = Counter(r["gravity_event"] for r in recovery_rows)
    heading_nis = [float(r["nis"]) for r in rows if r["nis_source"] == "heading"]
    gravity_nis = [float(r["nis"]) for r in rows if r["nis_source"] == "gravity"]
    final = rows[-1]
    covariance_corr = None
    ptheta, pbg, p_cross = (number(final, n) for n in ("cov_theta_x", "cov_bg_x", "cov_theta_bg_x"))
    if ptheta is not None and pbg is not None and ptheta > 0 and pbg > 0 and p_cross is not None:
        covariance_corr = p_cross / math.sqrt(ptheta * pbg)
    summary_key = (
        "2", scenario, "combined", "development", "101", mode,
        "EXTERNALLY_VERIFIED_STATIC", "OFF", aid, estimator,
    )
    metric = summary.get(summary_key)
    if metric is None:
        raise ValueError(f"summary missing {summary_key}")
    return {
        "scenario": scenario, "input_mode": mode, "estimator": estimator,
        "runtime_aid": aid, "noise_mode": "combined", "seed": 101,
        "startup_knowledge": "EXTERNALLY_VERIFIED_STATIC", "startup_calibration": "OFF",
        "time_window_s": [2.0, 12.0], "rows": len(rows),
        "availability": {"valid": int(metric["valid"]), "unavailable": int(metric["unavailable"]),
                         "stale": int(metric["stale"]), "health_end": metric["health_end"]},
        "summary_metrics": {name: (float(metric[name]) if metric[name] else None) for name in (
            "tilt_rms_deg", "yaw_rms_deg", "gravity_nis_mean", "gravity_nis_count",
            "gravity_applied", "gravity_suppressed", "aid_accepted", "aid_rejected",
            "accel_bias_error_end_m_s2", "gyro_bias_error_end_rad_s")},
        "trace_metrics": {
            "tilt_error_deg": {"at_2s": tilt[0], "at_8s": next((float(r["tilt_error_deg"]) for r in rows if abs(float(r["time_s"])-8.0)<1e-6), None),
                               "at_12s": tilt[-1], "max": max(tilt), "rms": math.sqrt(statistics.mean(x*x for x in tilt))},
            "yaw_error_deg": {"max_abs": max(abs(x) for x in yaw), "rms": math.sqrt(statistics.mean(x*x for x in yaw))},
            "gravity_events_all": dict(event_counts), "gravity_events_motion": dict(motion_events),
            "gravity_events_recovery": dict(recovery_events),
            "gravity_accepted_nis": {"count": len(gravity_nis), "mean": statistics.mean(gravity_nis) if gravity_nis else None,
                                     "p95": quantile(gravity_nis, .95), "max": max(gravity_nis) if gravity_nis else None},
            "heading_accepted_nis": {"count": len(heading_nis), "mean": statistics.mean(heading_nis) if heading_nis else None,
                                     "p95": quantile(heading_nis, .95), "max": max(heading_nis) if heading_nis else None},
            "final_gyro_bias_error_xyz_rad_s": {axis: bias_error[axis][-1] for axis in "xyz"},
            "corr_tilt_error_vs_gyro_bias_error_xyz": {axis: pearson(tilt, bias_error[axis]) for axis in "xyz"},
            "final_x_attitude_gyro_bias_covariance_correlation": covariance_corr,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_dir", type=Path)
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("paired_comparison", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    baseline_trace = args.baseline_dir / "representative_traces.csv"
    candidate_trace = args.candidate_dir / "representative_traces.csv"
    baseline_summary = load_summaries(args.baseline_dir / "summary.csv")
    candidate_summary = load_summaries(args.candidate_dir / "summary.csv")
    baseline = load_selected(baseline_trace)
    candidate = load_selected(candidate_trace)
    trace_fields = list(baseline[next(iter(SELECTORS))][0])
    if trace_fields != list(candidate[next(iter(SELECTORS))][0]):
        raise ValueError("parent/candidate trace schemas differ")

    with args.output_csv.open("w", newline="", encoding="utf-8") as stream:
        fields = ["run_side", *trace_fields]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        for side, data in (("baseline", baseline), ("candidate", candidate)):
            for selector in SELECTORS:
                for row in data[selector]:
                    writer.writerow({"run_side": side, **row})

    diagnostics = {
        "protocol": "pr2_development_diagnostics_protocol_v2",
        "data_scope": "development only; combined noise, seed 101, externally verified static startup, bias calibration off",
        "input_trace_sha256": {"baseline": sha256(baseline_trace), "candidate": sha256(candidate_trace)},
        "paired_comparison_sha256": sha256(args.paired_comparison),
        "selected_trace_sha256": sha256(args.output_csv),
        "notes": [
            "Per-sample traces contain scalar NIS only for accepted gravity/heading updates; rejected-update vector innovations are not serialized.",
            "The recorded covariance cross block is theta_x versus gyro-bias_x only; empirical per-axis bias-error correlations are reported separately.",
            "The development traces are diagnostic examples, not population estimates; paired 16-seed summaries remain the comparison evidence.",
        ],
        "streams": {},
    }
    for selector in SELECTORS:
        label = "/".join(selector)
        diagnostics["streams"][label] = {
            "baseline": summarize(selector, baseline[selector], baseline_summary),
            "candidate": summarize(selector, candidate[selector], candidate_summary),
        }
    args.output_json.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS PR2 development diagnostics: {len(SELECTORS)} paired streams, 2001 rows/stream, "
          f"trace={args.output_csv.stat().st_size} bytes, json={args.output_json.stat().st_size} bytes")


if __name__ == "__main__":
    main()
