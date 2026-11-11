#!/usr/bin/env python3
"""Validate paired PR3 summaries and emit distributions, bootstrap CIs, and SVG."""

import argparse
import csv
import html
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path


BOOTSTRAP_SEED = 20261110
BOOTSTRAP_REPLICATES = 10000


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[int(q * (len(ordered) - 1))]


def paired_bootstrap(differences):
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(differences)
    mean = statistics.fmean(differences) if differences else None
    samples = []
    if n:
        for _ in range(BOOTSTRAP_REPLICATES):
            samples.append(statistics.fmean(differences[rng.randrange(n)] for _ in range(n)))
        samples.sort()
    return {
        "n_pairs": n,
        "mean_difference": mean,
        "ci95_percentile": [quantile(samples, 0.025), quantile(samples, 0.975)] if samples else None,
        "method": f"paired percentile bootstrap, {BOOTSTRAP_REPLICATES} resamples, seed {BOOTSTRAP_SEED}; CI for mean difference, not an individual-run bound",
    }


def box_svg(groups, destination):
    width, height = 1160, 620
    left, top, plot_w, plot_h = 90, 70, 1010, 440
    maximum = max((max(values) for values in groups.values() if values), default=1.0)
    maximum = max(1.0, math.ceil(maximum / 5.0) * 5.0)
    colors = {"eskf_conservative": "#2563eb", "eskf_legacy": "#dc2626", "eskf_confirmed_only": "#059669", "mahony": "#7c3aed", "gyro_only": "#d97706"}
    scenarios = sorted({key[0] for key in groups})
    models = list(colors)
    def y(value):
        return top + plot_h - value / maximum * plot_h
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="90" y="34" font-family="sans-serif" font-size="22" font-weight="bold">PR3 tilt RMS by scenario</text>',
        '<text x="90" y="54" font-family="sans-serif" font-size="12">Synthetic host characterization; 208 Hz nominal, nominal stress; PR2 gate remains OPEN</text>',
    ]
    for tick in range(6):
        value = maximum * tick / 5
        yy = y(value)
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_w}" y2="{yy:.1f}" stroke="#d1d5db"/>')
        elements.append(f'<text x="{left-12}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.0f}</text>')
    group_w = plot_w / max(1, len(scenarios))
    model_offset = {model: (i - 1) * 20 for i, model in enumerate(models)}
    for scenario_index, scenario in enumerate(scenarios):
        center = left + group_w * (scenario_index + 0.5)
        elements.append(f'<text x="{center:.1f}" y="{top+plot_h+24}" text-anchor="middle" font-family="sans-serif" font-size="10">{html.escape(scenario)}</text>')
        for model in models:
            values = groups.get((scenario, model), [])
            if not values:
                continue
            offset = model_offset[model]
            x = center + offset
            lo, q1, med, q3, hi = [quantile(values, q) for q in (0, .25, .5, .75, 1)]
            color = colors[model]
            elements.append(f'<line x1="{x}" y1="{y(lo):.1f}" x2="{x}" y2="{y(hi):.1f}" stroke="{color}" stroke-width="2"/>')
            elements.append(f'<line x1="{x-6}" y1="{y(lo):.1f}" x2="{x+6}" y2="{y(lo):.1f}" stroke="{color}"/>')
            elements.append(f'<line x1="{x-6}" y1="{y(hi):.1f}" x2="{x+6}" y2="{y(hi):.1f}" stroke="{color}"/>')
            elements.append(f'<rect x="{x-7}" y="{y(q3):.1f}" width="14" height="{max(1,y(q1)-y(q3)):.1f}" fill="{color}" fill-opacity=".24" stroke="{color}"/>')
            elements.append(f'<line x1="{x-7}" y1="{y(med):.1f}" x2="{x+7}" y2="{y(med):.1f}" stroke="{color}" stroke-width="2"/>')
    for i, model in enumerate(models):
        x = left + i * 190
        elements.append(f'<rect x="{x}" y="560" width="12" height="12" fill="{colors[model]}"/>')
        elements.append(f'<text x="{x+18}" y="571" font-family="sans-serif" font-size="12">{model}</text>')
    elements.append('<text transform="translate(22 320) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13">Tilt RMS (degrees), conditional on valid state</text>')
    elements.append('</svg>')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(elements) + "\n", encoding="utf-8")


def metric_box_svg(groups, destination, title, ylabel, *, maximum=None):
    width, height = 1160, 620
    left, top, plot_w, plot_h = 90, 70, 1010, 440
    colors = {"eskf_conservative": "#2563eb", "eskf_legacy": "#dc2626", "eskf_confirmed_only": "#059669", "mahony": "#7c3aed", "gyro_only": "#d97706"}
    scenarios = sorted({key[0] for key in groups})
    models = list(colors)
    observed_max = max((max(values) for values in groups.values() if values), default=1.0)
    if maximum is None:
        maximum = max(1.0, math.ceil(observed_max / 5.0) * 5.0)
    else:
        maximum = max(maximum, observed_max)
    minimum = min((min(values) for values in groups.values() if values), default=0.0)
    minimum = min(0.0, minimum)
    span = max(1e-12, maximum - minimum)
    def y(value):
        return top + plot_h - (value - minimum) / span * plot_h
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="90" y="34" font-family="sans-serif" font-size="22" font-weight="bold">{html.escape(title)}</text>',
        '<text x="90" y="54" font-family="sans-serif" font-size="12">Synthetic host characterization; 208 Hz nominal; PR2 gate remains OPEN</text>',
    ]
    for tick in range(6):
        value = minimum + span * tick / 5
        yy = y(value)
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_w}" y2="{yy:.1f}" stroke="#d1d5db"/>')
        elements.append(f'<text x="{left-12}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.3g}</text>')
    group_w = plot_w / max(1, len(scenarios))
    model_offset = {model: (i - 2) * 16 for i, model in enumerate(models)}
    for scenario_index, scenario in enumerate(scenarios):
        center = left + group_w * (scenario_index + 0.5)
        elements.append(f'<text x="{center:.1f}" y="{top+plot_h+24}" text-anchor="middle" font-family="sans-serif" font-size="10">{html.escape(scenario)}</text>')
        for model in models:
            values = groups.get((scenario, model), [])
            if not values:
                continue
            x = center + model_offset[model]
            lo, q1, med, q3, hi = [quantile(values, q) for q in (0, .25, .5, .75, 1)]
            color = colors[model]
            elements.append(f'<line x1="{x}" y1="{y(lo):.1f}" x2="{x}" y2="{y(hi):.1f}" stroke="{color}" stroke-width="2"/>')
            elements.append(f'<rect x="{x-6}" y="{y(q3):.1f}" width="12" height="{max(1,y(q1)-y(q3)):.1f}" fill="{color}" fill-opacity=".24" stroke="{color}"/>')
            elements.append(f'<line x1="{x-6}" y1="{y(med):.1f}" x2="{x+6}" y2="{y(med):.1f}" stroke="{color}" stroke-width="2"/>')
    for i, model in enumerate(models):
        x = left + i * 190
        elements.append(f'<rect x="{x}" y="560" width="12" height="12" fill="{colors[model]}"/>')
        elements.append(f'<text x="{x+18}" y="571" font-family="sans-serif" font-size="12">{model}</text>')
    elements.append(f'<text transform="translate(22 320) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13">{html.escape(ylabel)}</text>')
    elements.append('</svg>')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(elements) + "\n", encoding="utf-8")


def summarize(input_path, output_dir, *, report_source=None, figure_prefix="pr3", figure_path_prefix="figures/"):
    with input_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    required = {"scenario", "rate_mode", "stress_mode", "seed", "estimator", "input_sha256", "config_sha256", "expected", "produced", "valid", "control_valid", "covariance_valid", "missing", "unavailable", "complete_run", "tilt_rms_deg", "pr2_gate_status"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"summary is empty or missing required columns: {sorted(required-set(rows[0] if rows else []))}")
    protocol_versions = {int(row["protocol_version"]) for row in rows}
    if len(protocol_versions) != 1:
        raise ValueError(f"summary must contain one evaluation protocol version, got {sorted(protocol_versions)}")

    configs = defaultdict(list)
    output_groups = defaultdict(list)
    tilt_plot_groups = defaultdict(list)
    figure_columns = {"yaw_rms_deg": "yaw_rms.svg", "availability": "availability.svg",
        "tilt_nees_mean": "tilt_nees_mean.svg", "nis_mean": "nis_mean.svg"}
    figure_groups = {column: defaultdict(list) for column in figure_columns}
    failures = []
    seeds_by_group = defaultdict(set)
    for row in rows:
        key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["sensor_input"], row["startup_knowledge"], row["startup_gyro_bias_calibration"], row["runtime_aid"])
        configs[key].append(row)
        seeds_by_group[key].add(int(row["seed"]))
        value = number(row["tilt_rms_deg"])
        output_groups[(key, row["estimator"])].append(value)
        if row["rate_mode"] == "uniform_208hz" and row["stress_mode"] == "nominal" and row["sensor_input"] == "IMU_ONLY" and row["startup_knowledge"] == "UNKNOWN" and row["startup_gyro_bias_calibration"] == "OFF" and row["runtime_aid"] == "NONE":
            if value is not None:
                tilt_plot_groups[(row["scenario"], row["estimator"])].append(value)
        for column in figure_columns:
            metric = number(row.get(column))
            if metric is not None:
                figure_groups[column][(row["scenario"], row["estimator"])].append(metric)
        if row["complete_run"].lower() != "true" or value is None:
            failures.append({"scenario": row["scenario"], "rate_mode": row["rate_mode"], "stress_mode": row["stress_mode"], "seed": int(row["seed"]), "estimator": row["estimator"], "expected": int(row["expected"]), "produced": int(row["produced"]), "valid": int(row["valid"]), "control_valid": int(row["control_valid"]), "covariance_valid": int(row["covariance_valid"]), "missing": int(row["missing"]), "unavailable": int(row["unavailable"])})

    distributions = []
    for (key, estimator), values in output_groups.items():
        finite_values = [v for v in values if v is not None]
        trial_rows = [r for r in configs[key] if r["estimator"] == estimator]
        metric_columns = {
            "tilt_rms_deg": "tilt_rms_deg", "attitude_rms_deg": "attitude_rms_deg",
            "yaw_rms_deg": "yaw_rms_deg", "position_rms_m": "position_rms_m",
            "velocity_rms_m_s": "velocity_rms_m_s", "tilt_nees_mean": "tilt_nees_mean",
            "tilt_nees_coverage95": "tilt_nees_coverage95", "nis_mean": "nis_mean",
            "tilt_p95_deg": "tilt_p95_deg", "tilt_max_deg": "tilt_max_deg",
            "accel_bias_error_m_s2": "accel_bias_error_m_s2", "gyro_bias_error_rad_s": "gyro_bias_error_rad_s",
        }
        metric_distributions = {}
        for label, column in metric_columns.items():
            samples = [x for row in trial_rows if (x := number(row.get(column))) is not None]
            metric_distributions[label] = {
                "finite_trial_count": len(samples), "mean": statistics.fmean(samples) if samples else None,
                "median": quantile(samples, .5), "p95": quantile(samples, .95), "max": max(samples) if samples else None,
            }
        distributions.append({
            "scenario": key[0], "rate_mode": key[1], "stress_mode": key[2], "sensor_input": key[3],
            "startup_knowledge": key[4], "startup_gyro_bias_calibration": key[5], "runtime_aid": key[6],
            "estimator": estimator, "trial_count": len(values), "finite_metric_count": len(finite_values),
            "covariance_applicable": trial_rows[0].get("covariance_applicable", "true").lower() == "true",
            "navigation_applicable": trial_rows[0].get("navigation_applicable", "true").lower() == "true",
            "complete_count": sum(r["complete_run"].lower() == "true" for r in trial_rows),
            "availability_mean": statistics.fmean(float(r["availability"]) for r in trial_rows),
            "metric_distributions": metric_distributions,
            "tilt_rms_deg": {"mean": statistics.fmean(finite_values) if finite_values else None,
                "median": quantile(finite_values, .5), "p95": quantile(finite_values, .95), "max": max(finite_values) if finite_values else None},
        })

    paired = []
    pair_keys = defaultdict(dict)
    for row in rows:
        key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["seed"], row["sensor_input"], row["startup_knowledge"], row["startup_gyro_bias_calibration"], row["runtime_aid"])
        pair_keys[key][row["estimator"]] = row
    model_names = ("eskf_conservative", "eskf_legacy", "eskf_confirmed_only", "mahony", "gyro_only")
    model_pairs = tuple((model_names[i], model_names[j]) for i in range(len(model_names)) for j in range(i + 1, len(model_names)))
    for left, right in model_pairs:
        grouped = defaultdict(list)
        mismatches = 0
        matched = 0
        for key, values in pair_keys.items():
            if left not in values or right not in values:
                continue
            a, b = values[left], values[right]
            matched += 1
            if a["input_sha256"] != b["input_sha256"] or a["config_sha256"] != b["config_sha256"]:
                mismatches += 1
                continue
            delta = number(a["tilt_rms_deg"])
            other = number(b["tilt_rms_deg"])
            cohort = key[:3] + key[4:]
            grouped[cohort].append(None if delta is None or other is None else delta - other)
        for cohort, deltas in grouped.items():
            valid_deltas = [d for d in deltas if d is not None]
            result = paired_bootstrap(valid_deltas)
            result.update({"left_estimator": left, "right_estimator": right, "difference_definition": "left tilt RMS minus right tilt RMS", "matched_trials": len(deltas), "invalid_pairs": len(deltas)-len(valid_deltas), "input_or_config_hash_mismatches": mismatches, "scenario": cohort[0], "rate_mode": cohort[1], "stress_mode": cohort[2], "sensor_input": cohort[3], "startup_knowledge": cohort[4], "startup_gyro_bias_calibration": cohort[5], "runtime_aid": cohort[6]})
            paired.append(result)

    minimum_seed_count = min((len(seeds) for seeds in seeds_by_group.values()), default=0)
    report = {
        "report_protocol": f"pr3_summary_v{next(iter(protocol_versions))}",
        "source_summary": report_source or input_path.name,
        "trial_row_count": len(rows),
        "input_stream_count": len({row["input_sha256"] for row in rows}),
        "minimum_seed_count_per_factor_group": minimum_seed_count,
        "distribution_groups": distributions,
        "paired_confidence_intervals": paired,
        "incomplete_or_failed_trials": failures,
        "pr2_gate_status": "OPEN",
        "pr3_gate_status": "OPEN_FOR_FULL_FACTOR_ACCEPTANCE_AND_INDEPENDENT_REVIEW" if failures or minimum_seed_count < 100 or max(protocol_versions) >= 5 else "OPEN_INDEPENDENT_REVIEW_REQUIRED",
        "limitations": ["Synthetic host inputs only; no physical sensor or RP2350 performance claims.", "The v5 primary acceptance coverage is the nominal IMU-only/unknown-start baseline; other rate, stress, startup, calibration and runtime-aid factors lack 100-seed held-out/final coverage.", "Mahony and gyro-only are attitude-only reference estimators; navigation states, covariance, and NEES/NIS are not applicable and are explicitly marked.", "The reference Mahony uses fixed proportional and integral gains of 1.0 and 0.05; its heading correction gain is fixed at 0.25. These comparison baselines are not tuned products.", "Tilt NEES and gravity NIS are consistency diagnostics because simulator truth, propagated IMU and gravity pseudo-measurements are not fully independent."],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = output_dir / "figures"
    figure_names = [f"{figure_prefix}_tilt_rms.svg"]
    box_svg(tilt_plot_groups, figure_dir / figure_names[0])
    metric_titles = {
        "yaw_rms_deg": ("PR3 yaw RMS by scenario", "Yaw RMS (degrees), conditional on valid state", None),
        "availability": ("PR3 attitude availability by scenario", "Available finite attitude outputs / expected samples", 1.0),
        "tilt_nees_mean": ("PR3 mean tilt NEES by scenario", "Per-trial mean 2D tilt NEES; consistency diagnostic", None),
        "nis_mean": ("PR3 mean NIS by scenario", "Per-trial mean NIS; consistency diagnostic", None),
    }
    for column, filename in figure_columns.items():
        title, ylabel, maximum = metric_titles[column]
        output_name = f"{figure_prefix}_{filename}"
        figure_names.append(output_name)
        metric_box_svg(figure_groups[column], figure_dir / output_name, title, ylabel, maximum=maximum)
    report["figures"] = [f"{figure_path_prefix}{name}" for name in figure_names]
    (output_dir / "pr3_summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"PASS PR3 summary: {len(rows)} trial rows, {len(failures)} incomplete trials, min seeds/group={minimum_seed_count}; gate remains OPEN")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report-source", help="stable source label stored in the JSON report")
    parser.add_argument("--figure-prefix", default="pr3", help="prefix for generated SVG filenames")
    parser.add_argument("--figure-path-prefix", default="figures/", help="stable figure paths stored in the JSON report")
    args = parser.parse_args()
    try:
        summarize(args.input, args.output_dir, report_source=args.report_source,
            figure_prefix=args.figure_prefix, figure_path_prefix=args.figure_path_prefix)
    except (OSError, ValueError, KeyError) as error:
        print(f"FAIL PR3 summary validation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
