#!/usr/bin/env python3
"""Replay PR3 v5 development static/208 Hz trials with host-only gravity diagnostics."""

import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from validate_pr3_scenario_protocol import load_protocol, protocol_source_bytes


PROTOCOL = ROOT / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"
ARCHIVE = ROOT / "benchmarks/reports/pr3_protocol_v5_dev100_all_factors_postfix_trials.csv.gz"
ARCHIVE_MANIFEST = ROOT / "benchmarks/manifests/pr3_protocol_v5_dev100_all_factors_postfix.json"
TOOL_ID = "pr3-gravity-suppression-a4"
L0_FIELDS = (
    "protocol_version", "protocol_sha256", "source_archive_sha256", "split", "scenario", "rate_mode",
    "stress_mode", "seed", "estimator", "sensor_input", "startup_knowledge",
    "startup_gyro_bias_calibration", "runtime_aid", "input_sha256", "generated_input_sha256",
    "archive_trial_match", "expected", "valid", "availability", "tilt_rms_deg", "tilt_p95_deg",
    "tilt_max_deg", "accel_bias_error_m_s2", "gyro_bias_error_rad_s", "health_end",
    "initialized_sample_index", "initialized_timestamp_us", "initialized_samples",
    "accel_norm_gate_failures", "gyro_norm_gate_failures", "accel_step_gate_failures",
    "raw_candidate_samples", "stationary_samples", "gravity_allowed_samples", "max_candidate_dwell",
    "candidate_gate_failed_samples", "candidate_dwell_incomplete_samples", "aid_cadence_pending_samples",
    "external_confirmation_required_samples", "gravity_attempts", "gravity_accepted", "gravity_rejected",
    "measurement_model_rejected", "debiased_acceleration_rejected", "conservative_angle_rejected",
    "invalid_noise_sigma_rejected", "innovation_covariance_rejected", "nis_gate_rejected",
    "nonfinite_correction_rejected", "archived_tilt_rms_deg", "archived_valid", "archived_health_end",
)
PAIR_FIELDS = (
    "split", "scenario", "rate_mode", "seed", "estimator", "pairing_key",
    "nominal_input_sha256", "stress_input_sha256", "nominal_tilt_rms_deg", "stress_tilt_rms_deg",
    "stress_minus_nominal_tilt_rms_deg", "nominal_gravity_attempts", "stress_gravity_attempts",
    "nominal_gravity_accepted", "stress_gravity_accepted", "nominal_max_candidate_dwell",
    "stress_max_candidate_dwell",
)


def sha256(path):
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


def pair_trial_rows(rows):
    """Pair nominal/stress summaries only when the seed and estimator match."""
    groups = {}
    for row in rows:
        required = ("seed", "stress_mode", "estimator", "tilt_rms_deg")
        if any(not row.get(field) for field in required):
            raise ValueError("trial row is missing a pairing key or tilt metric")
        mode = row["stress_mode"]
        if mode not in ("nominal", "stress"):
            raise ValueError(f"unknown stress condition {mode!r}")
        key_fields = (
            row.get("split", "development"), row.get("scenario", "static"),
            row.get("rate_mode", "uniform_208hz"), str(row["seed"]), row["estimator"],
        )
        key = tuple(key_fields)
        modes = groups.setdefault(key, {})
        if mode in modes:
            raise ValueError(f"duplicate trial key for {mode}: {'|'.join(key)}")
        modes[mode] = row
    paired = []
    for key, modes in sorted(groups.items()):
        if set(modes) != {"nominal", "stress"}:
            raise ValueError(f"pair key {'|'.join(key)} must have exactly one nominal and one stress trial")
        nominal, stress = modes["nominal"], modes["stress"]
        paired.append({
            "split": key[0], "scenario": key[1], "rate_mode": key[2], "seed": key[3],
            "estimator": key[4], "pairing_key": "|".join(key),
            "nominal_input_sha256": nominal.get("input_sha256", ""),
            "stress_input_sha256": stress.get("input_sha256", ""),
            "nominal_tilt_rms_deg": float(nominal["tilt_rms_deg"]),
            "stress_tilt_rms_deg": float(stress["tilt_rms_deg"]),
            "stress_minus_nominal_tilt_rms_deg": float(stress["tilt_rms_deg"]) - float(nominal["tilt_rms_deg"]),
            "nominal_gravity_attempts": int(nominal.get("gravity_attempts", 0)),
            "stress_gravity_attempts": int(stress.get("gravity_attempts", 0)),
            "nominal_gravity_accepted": int(nominal.get("gravity_accepted", 0)),
            "stress_gravity_accepted": int(stress.get("gravity_accepted", 0)),
            "nominal_max_candidate_dwell": int(nominal.get("max_candidate_dwell", 0)),
            "stress_max_candidate_dwell": int(stress.get("max_candidate_dwell", 0)),
        })
    return paired


def validate_forensic_scope(*, split, seed_count, scenario_count, rate_mode_count,
                            stress_mode_count, profile_count, event_sample):
    if (split != "development" or seed_count != 1 or scenario_count != 1 or rate_mode_count != 1
            or stress_mode_count != 1 or profile_count != 1 or not event_sample or event_sample < 1):
        raise ValueError("forensic capture requires one selected development stream and event")


def quantile(values, probability):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot compute a quantile from no trials")
    return ordered[int(probability * (len(ordered) - 1))]


def load_source_rows(archive_path, manifest_path, protocol_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    archive_digest = sha256(archive_path)
    protocol_digest = hashlib.sha256(protocol_source_bytes(protocol_path)).hexdigest()
    if archive_digest != manifest.get("packaged_trial_csv_gz_sha256"):
        raise ValueError("development v5 archive hash does not match its checked-in manifest")
    if protocol_digest != manifest.get("protocol_sha256"):
        raise ValueError("v5 protocol SHA-256 does not match its archive manifest")
    with gzip.open(archive_path, "rt", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    selected = [row for row in rows if
        row["scenario"] == "static" and row["rate_mode"] == "uniform_208hz"
        and row["sensor_input"] == "IMU_ONLY" and row["startup_knowledge"] == "UNKNOWN"
        and row["startup_gyro_bias_calibration"] == "OFF" and row["runtime_aid"] == "NONE"
        and row["estimator"].startswith("eskf_")]
    if len(selected) != 600:
        raise ValueError(f"expected 600 development static/208 Hz baseline ESKF rows, found {len(selected)}")
    return manifest, archive_digest, protocol_digest, selected


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
            raise ValueError(f"archive/replay field {field} has different missingness")
        if field == "health_end":
            if actual != expected:
                raise ValueError(f"archive/replay {field} mismatch: {actual} != {expected}")
        elif not math.isclose(float(actual), float(expected), rel_tol=2e-6, abs_tol=1e-7):
            raise ValueError(f"archive/replay {field} mismatch: {actual} != {expected}")


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def paired_rollups(paired_rows):
    summaries = []
    for estimator in ("eskf_conservative", "eskf_legacy", "eskf_confirmed_only"):
        selected = [row for row in paired_rows if row["estimator"] == estimator]
        for mode in ("nominal", "stress"):
            values = [row[f"{mode}_tilt_rms_deg"] for row in selected]
            summaries.append({
                "estimator": estimator, "condition": mode, "n": len(values),
                "mean_tilt_rms_deg": statistics.mean(values),
                "median_tilt_rms_deg": statistics.median(values),
                "p95_tilt_rms_deg": quantile(values, .95), "worst_tilt_rms_deg": max(values),
            })
        deltas = [row["stress_minus_nominal_tilt_rms_deg"] for row in selected]
        summaries.append({
            "estimator": estimator, "condition": "stress_minus_nominal_paired", "n": len(deltas),
            "mean_tilt_rms_deg": statistics.mean(deltas), "median_tilt_rms_deg": statistics.median(deltas),
            "p95_tilt_rms_deg": quantile(deltas, .95), "worst_tilt_rms_deg": max(deltas),
        })
    return summaries


def svg_trace_figure(trace_by_mode, output, seed):
    width, height = 1240, 1080
    panels = [
        ("Tilt error", "degrees", "tilt_error_deg", ()),
        ("Adjacent acceleration step", "m/s²", "accel_step_m_s2", ((.20, "step threshold 0.20", "#6b7280"),)),
        ("Consecutive stationary candidates", "samples", "consecutive_candidate_samples",
         ((35, "dwell threshold 35", "#7c3aed"), (55, "35 dwell + 21 aid cadence", "#dc2626"))),
        ("Cumulative accepted gravity updates", "updates", "gravity_updates_cumulative", ()),
    ]
    left, top, plot_w, panel_h, gap = 100, 75, 1080, 195, 55
    colors = {"nominal": "#2563eb", "stress": "#dc2626"}
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="100" y="38" font-family="sans-serif" font-size="21" font-weight="bold">PR3 v5 static / 208 Hz gravity suppression, development seed {seed}</text>',
        '<text x="100" y="58" font-family="sans-serif" font-size="12">Unknown startup · IMU only · no aiding · matching protocol settings and seed</text>',
    ]
    max_time = max(float(row["nominal_time_s"]) for rows in trace_by_mode.values() for row in rows)
    for panel_index, (title, ylabel, metric, thresholds) in enumerate(panels):
        panel_top = top + panel_index * (panel_h + gap)
        plot_top, plot_h = panel_top + 22, panel_h - 40
        if metric == "tilt_error_deg":
            ymin, ymax = 0.0, max(1.0, max(float(row[metric]) for rows in trace_by_mode.values() for row in rows) * 1.08)
        elif metric == "accel_step_m_s2":
            ymax = max(.25, max(float(row[metric]) for rows in trace_by_mode.values() for row in rows if row[metric]) * 1.05)
            ymin = 0.0
        elif metric == "consecutive_candidate_samples":
            ymin, ymax = 0.0, 60.0
        else:
            ymin = 0.0
            ymax = max(1.0, max(int(row["gravity_updates_cumulative"]) for rows in trace_by_mode.values() for row in rows) * 1.05)
        def sx(value): return left + max(0.0, min(1.0, value / max_time)) * plot_w
        def sy(value): return plot_top + plot_h - max(0.0, min(1.0, (value - ymin) / (ymax - ymin))) * plot_h
        elements.append(f'<text x="{left}" y="{panel_top+13}" font-family="sans-serif" font-size="14" font-weight="bold">{html.escape(title)}</text>')
        for tick in range(5):
            value = ymin + (ymax-ymin) * tick / 4
            yy = sy(value)
            elements.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{left+plot_w}" y2="{yy:.2f}" stroke="#e5e7eb"/>')
            elements.append(f'<text x="{left-10}" y="{yy+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="10">{value:.3g}</text>')
        for value, label, color in thresholds:
            if ymin <= value <= ymax:
                yy=sy(value)
                elements.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{left+plot_w}" y2="{yy:.2f}" stroke="{color}" stroke-dasharray="6 5"/>')
                elements.append(f'<text x="{left+plot_w-4}" y="{yy-4:.2f}" text-anchor="end" font-family="sans-serif" font-size="10" fill="{color}">{html.escape(label)}</text>')
        for mode, rows in trace_by_mode.items():
            if metric == "gravity_updates_cumulative":
                cumulative=0
                values=[]
                for row in rows:
                    cumulative += int(row["gravity_accepted"] == "true")
                    values.append((float(row["nominal_time_s"]), cumulative))
            else:
                values=[(float(row["nominal_time_s"]), float(row[metric])) for row in rows if row[metric] != ""]
            path=" ".join(("M" if i==0 else "L")+f"{sx(x):.2f},{sy(y):.2f}" for i,(x,y) in enumerate(values))
            elements.append(f'<path d="{path}" fill="none" stroke="{colors[mode]}" stroke-width="1.4"/>')
        elements.append(f'<text transform="translate(22 {plot_top+plot_h/2:.1f}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(ylabel)}</text>')
        if panel_index == len(panels)-1:
            elements.append(f'<text x="{left+plot_w/2}" y="{plot_top+plot_h+23}" text-anchor="middle" font-family="sans-serif" font-size="11">Trial time (s)</text>')
    elements.extend([
        '<line x1="930" y1="53" x2="950" y2="53" stroke="#2563eb" stroke-width="3"/><text x="956" y="57" font-family="sans-serif" font-size="11">nominal</text>',
        '<line x1="1030" y1="53" x2="1050" y2="53" stroke="#dc2626" stroke-width="3"/><text x="1056" y="57" font-family="sans-serif" font-size="11">stress</text>',
        '</svg>',
    ])
    Path(output).write_text("\n".join(elements)+"\n", encoding="utf-8", newline="\n")


def svg_paired_figure(paired_rows, output):
    rows=[row for row in paired_rows if row["estimator"]=="eskf_conservative"]
    width,height=1120,520
    left,top,plot_w,plot_h=90,65,960,365
    ymin,ymax=0.0,max(6.2,max(row["stress_tilt_rms_deg"] for row in rows)*1.05)
    def sx(index): return left+(index/(len(rows)-1))*plot_w
    def sy(value): return top+plot_h-(value-ymin)/(ymax-ymin)*plot_h
    elements=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="90" y="34" font-family="sans-serif" font-size="20" font-weight="bold">All 100 paired PR3 v5 development seeds · static / 208 Hz</text>',
        '<text x="90" y="53" font-family="sans-serif" font-size="12">Conservative ESKF · unknown startup · IMU only · same seed and configuration across nominal/stress</text>']
    for tick in range(6):
        val=ymin+(ymax-ymin)*tick/5; yy=sy(val)
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_w}" y2="{yy:.1f}" stroke="#e5e7eb"/>')
        elements.append(f'<text x="{left-9}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="10">{val:.3g}</text>')
    for index,row in enumerate(rows):
        x=sx(index); y0=sy(row["nominal_tilt_rms_deg"]); y1=sy(row["stress_tilt_rms_deg"])
        elements.append(f'<line x1="{x:.2f}" y1="{y0:.2f}" x2="{x:.2f}" y2="{y1:.2f}" stroke="#d1d5db" stroke-width="1"/>')
        elements.append(f'<circle cx="{x:.2f}" cy="{y0:.2f}" r="2.2" fill="#2563eb"/>')
        elements.append(f'<circle cx="{x:.2f}" cy="{y1:.2f}" r="2.2" fill="#dc2626"/>')
    elements.extend([
        f'<text transform="translate(20 {top+plot_h/2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="12">Trial tilt RMS (degrees)</text>',
        f'<text x="{left+plot_w/2}" y="475" text-anchor="middle" font-family="sans-serif" font-size="12">Development seed index (4001–4100)</text>',
        '<line x1="860" y1="51" x2="880" y2="51" stroke="#2563eb" stroke-width="3"/><text x="886" y="55" font-family="sans-serif" font-size="11">nominal</text>',
        '<line x1="960" y1="51" x2="980" y2="51" stroke="#dc2626" stroke-width="3"/><text x="986" y="55" font-family="sans-serif" font-size="11">stress</text>',
        '</svg>',
    ])
    Path(output).write_text("\n".join(elements)+"\n", encoding="utf-8", newline="\n")


def ensure_output_dir(path):
    path = Path(path).resolve()
    frozen_root=(ROOT/"benchmarks").resolve()
    if path==frozen_root or frozen_root in path.parents:
        raise ValueError("A4 diagnostics cannot write under benchmarks/ because v1-v5 evidence is frozen")
    if not path.exists():
        path.mkdir(parents=True)
        (path/"trace_manifest.json").write_text(
            json.dumps({"schema_version":1,"tool_id":TOOL_ID,"status":"running"},sort_keys=True)+"\n",
            encoding="utf-8",newline="\n")
        return path
    manifest_path=path/"trace_manifest.json"
    if not manifest_path.is_file():
        if any(path.iterdir()):
            raise ValueError(f"refusing to overwrite an existing unrecognized output directory: {path}")
        return path
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("tool_id") != TOOL_ID:
        raise ValueError(f"refusing to overwrite output directory owned by another tool: {path}")
    return path


def run_analysis(args):
    output=ensure_output_dir(args.output_dir)
    protocol=load_protocol(PROTOCOL)
    archive_manifest,archive_hash,protocol_hash,archive_rows=load_source_rows(ARCHIVE,ARCHIVE_MANIFEST,PROTOCOL)
    seed_range=protocol["seeds"]["development"]
    seeds=range(seed_range["first_seed"],seed_range["last_seed"]+1)
    if args.trace_seed is None:
        conservative={(row["stress_mode"],int(row["seed"])):float(row["tilt_rms_deg"])
            for row in archive_rows if row["estimator"]=="eskf_conservative"}
        args.trace_seed=max(seeds,key=lambda seed:conservative[("stress",seed)]-conservative[("nominal",seed)])
    if args.trace_seed not in seeds:
        raise ValueError(f"trace seed {args.trace_seed} is outside development seeds {seed_range['first_seed']}..{seed_range['last_seed']}")
    source_by_key={(row["stress_mode"],int(row["seed"]),row["estimator"]):row for row in archive_rows}
    input_hash_by_key={}
    for mode in ("nominal","stress"):
        for seed in seeds:
            matching=[row for row in archive_rows if row["stress_mode"]==mode and int(row["seed"])==seed]
            hashes={row["input_sha256"] for row in matching}
            if len(hashes)!=1 or len(matching)!=3:
                raise ValueError(f"development archive lacks one shared input hash for {mode} seed {seed}")
            input_hash_by_key[(mode,seed)]=next(iter(hashes))

    implementation_commit=run(["git","log","-1","--format=%H","--","eskf15.hpp","tools/pr3_evaluate_stream.cpp","tools/pr3_gravity_suppression.py"],capture=True).strip()
    if len(implementation_commit)!=40:
        raise ValueError("could not identify the committed A4 diagnostic implementation")
    compiler=shlex.split(args.cxx)
    if not compiler:
        raise ValueError("compiler command is empty")
    config={"sensor_input":"IMU_ONLY","startup_knowledge":"UNKNOWN",
        "startup_gyro_bias_calibration":"OFF","runtime_aid":"NONE",
        "evaluated_estimators":["eskf_conservative","eskf_legacy","eskf_confirmed_only","mahony","gyro_only"]}
    config_sha=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    selected_traces={mode:output/f"v5_dev_static208_seed{args.trace_seed}_{mode}_l1.csv" for mode in ("nominal","stress")}
    l0_rows=[]
    selected_input=None
    with tempfile.TemporaryDirectory(prefix="pr3-gravity-a4-") as temp_name:
        temp=Path(temp_name); build=temp/"build"; inputs=temp/"inputs"
        build.mkdir(); inputs.mkdir()
        generated_header=build/"pr3_scenario_protocol.hpp"
        run([sys.executable,str(ROOT/"tools/pr3_generate_scenario_header.py"),str(PROTOCOL),str(generated_header)])
        generator=build/"pr3_generate_inputs"; evaluator=build/"pr3_evaluate_stream"
        compiler_flags=[*compiler,"-std=c++17","-O2","-Wall","-Wextra","-Wpedantic","-Werror",f"-I{build}"]
        run([*compiler_flags,str(ROOT/"tools/pr3_generate_inputs.cpp"),"-o",str(generator)])
        run([*compiler_flags,"-DINERTIAL_GRAVITY_DIAGNOSTICS=1",str(ROOT/"tools/pr3_evaluate_stream.cpp"),"-o",str(evaluator)])
        for mode in ("nominal","stress"):
            rate_mode=1
            for seed in seeds:
                stem=f"static__uniform_208hz__{mode}__{seed}"
                input_path=inputs/f"{stem}.bin"
                run([str(generator),str(input_path),"development","static",str(rate_mode),mode,str(seed)])
                input_hash=sha256(input_path)
                if input_hash!=input_hash_by_key[(mode,seed)]:
                    raise ValueError(f"regenerated development input hash mismatch for {stem}: {input_hash} != {input_hash_by_key[(mode,seed)]}")
                if seed==args.trace_seed and mode=="nominal":
                    selected_input=input_path
                trial_path=temp/"trial.csv"; diag_path=temp/"gravity_summary.csv"
                command=[str(evaluator),str(input_path),str(trial_path),"development","IMU_ONLY","UNKNOWN","0","NONE",
                    implementation_commit,config_sha,input_hash,"--gravity-summary",str(diag_path)]
                trace_path=selected_traces[mode] if seed==args.trace_seed else None
                if trace_path:
                    command.extend(["--gravity-trace",str(trace_path)])
                run(command)
                with trial_path.open(newline="",encoding="utf-8") as stream:
                    trial_rows=list(csv.DictReader(stream))
                with diag_path.open(newline="",encoding="utf-8") as stream:
                    diag_rows=list(csv.DictReader(stream))
                if len(diag_rows)!=3:
                    raise ValueError(f"expected 3 ESKF diagnostic summary rows for {stem}")
                for diag in diag_rows:
                    estimator=diag["estimator"]
                    replayed=next(row for row in trial_rows if row["estimator"]==estimator)
                    archived=source_by_key[(mode,seed,estimator)]
                    assert_archive_match(replayed,archived)
                    item={field:diag.get(field,"") for field in diag.keys()}
                    item.update({
                        "source_archive_sha256":archive_hash,"input_sha256":input_hash,
                        "generated_input_sha256":input_hash,"archive_trial_match":"true",
                        "archived_tilt_rms_deg":archived["tilt_rms_deg"],
                        "archived_valid":archived["valid"],"archived_health_end":archived["health_end"],
                    })
                    l0_rows.append(item)
        if selected_input is None:
            raise ValueError("selected nominal replay input was not generated")
        nominal_trace=list(csv.DictReader(selected_traces["nominal"].open(newline="",encoding="utf-8")))
        first_accepted=next((int(row["sample_index"]) for row in nominal_trace
            if row["gravity_attempted"]=="true" and row["gravity_accepted"]=="true"),None)
        if first_accepted is None:
            raise ValueError("selected nominal development replay had no accepted gravity update for the L2 event")
        validate_forensic_scope(split="development",seed_count=1,scenario_count=1,rate_mode_count=1,
            stress_mode_count=1,profile_count=1,event_sample=first_accepted)
        forensic_path=output/f"v5_dev_static208_seed{args.trace_seed}_nominal_l2_covariance.csv"
        run([str(evaluator),str(selected_input),str(temp/"forensic_trial.csv"),"development","IMU_ONLY","UNKNOWN","0","NONE",
            implementation_commit,config_sha,input_hash_by_key[("nominal",args.trace_seed)],
            "--forensic-covariance",str(forensic_path),"--forensic-sample",str(first_accepted)])
        with forensic_path.open(newline="",encoding="utf-8") as stream:
            covariance_rows=list(csv.DictReader(stream))
        if len(covariance_rows)!=2 or {row["stage"] for row in covariance_rows}!={"before_sample","after_sample"}:
            raise ValueError("L2 forensic capture did not contain exactly the two covariance snapshots for its selected event")
        if any(int(row["sample_index"])!=first_accepted or row["estimator"]!="eskf_conservative" for row in covariance_rows):
            raise ValueError("L2 forensic capture escaped its selected estimator/event")

    l0_rows.sort(key=lambda row:(row["stress_mode"],int(row["seed"]),row["estimator"]))
    l0_path=output/"v5_dev_static208_l0_per_trial.csv"
    write_csv(l0_path,l0_rows,L0_FIELDS)
    paired_rows=pair_trial_rows(l0_rows)
    paired_path=output/"v5_dev_static208_l0_paired_deltas.csv"
    write_csv(paired_path,paired_rows,PAIR_FIELDS)
    rollups=paired_rollups(paired_rows)
    trace_by_mode={mode:list(csv.DictReader(selected_traces[mode].open(newline="",encoding="utf-8"))) for mode in ("nominal","stress")}
    rate_hz=next(item["nominal_rate_hz"] for item in protocol["sampling"]["rate_modes"] if item["id"]=="uniform_208hz")
    expected_samples=int(rate_hz*protocol["sampling"]["duration_s"])
    for mode,rows in trace_by_mode.items():
        if len(rows)!=expected_samples:
            raise ValueError(f"unexpected sample count in selected {mode} trace: {len(rows)} (expected {expected_samples})")
        if [int(row["sample_index"]) for row in rows]!=list(range(1,len(rows)+1)):
            raise ValueError(f"sample clock/index sequence is incomplete in selected {mode} trace")
        for row in rows:
            row["gravity_updates_cumulative"]=""
        cumulative=0
        for row in rows:
            cumulative+=int(row["gravity_accepted"]=="true")
            row["gravity_updates_cumulative"]=str(cumulative)
    trace_figure=output/f"v5_dev_static208_seed{args.trace_seed}_gravity_trace.svg"
    paired_figure=output/"v5_dev_static208_paired_seed_tilt.svg"
    svg_trace_figure(trace_by_mode,trace_figure,args.trace_seed)
    svg_paired_figure(paired_rows,paired_figure)
    summary={
        "schema_version":1,"tool_id":TOOL_ID,"classification":"synthetic host replay; development subset only",
        "protocol_version":protocol["protocol_version"],"protocol_sha256":protocol_hash,
        "source_archive_path":str(ARCHIVE.relative_to(ROOT)),"source_archive_sha256":archive_hash,
        "source_archive_manifest_sha256":sha256(ARCHIVE_MANIFEST),
        "implementation_commit":implementation_commit,
        "focused_condition":{"split":"development","scenario":"static","rate_mode":"uniform_208hz",
            "profile":"IMU_ONLY / UNKNOWN / calibration OFF / runtime aid NONE",
            "seed_range":[seed_range["first_seed"],seed_range["last_seed"]],"stress_modes":["nominal","stress"]},
        "l0_trial_rows":len(l0_rows),"l0_paired_rows":len(paired_rows),
        "all_replayed_input_hashes_match_archive":True,"all_eskf_trial_metrics_match_archive":True,
        "trace_seed":args.trace_seed,"trace_sample_rows_per_mode":len(trace_by_mode["nominal"]),
        "l2_forensic_event":{"sample_index":first_accepted,"event":"first accepted conservative gravity correction in nominal trace",
            "full_covariance_rows":2,"captured_estimator":"eskf_conservative"},
        "rollups":rollups,
        "interpretation":{"candidate_thresholds":"strict inequalities from Settings: accel norm within 6% of g, gyro norm < 0.12 rad/s, adjacent accel step < 0.20 m/s^2",
            "candidate_dwell_samples":35,"gravity_aid_cadence_samples":21,
            "first_attempt_requires_consecutive_candidates":55,
            "covariance_projection":"2x2 attitude covariance projected onto world-horizontal tilt directions; global-yaw gauge axis is excluded",
            "hardware_validation":"NOT_RUN"},
    }
    summary_path=output/"v5_dev_static208_summary.json"
    summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    selected_rollups={(r["estimator"],r["condition"]):r for r in rollups}
    conservative_nominal=selected_rollups[("eskf_conservative","nominal")]
    conservative_stress=selected_rollups[("eskf_conservative","stress")]
    conservative_delta=selected_rollups[("eskf_conservative","stress_minus_nominal_paired")]
    selected_l0=[row for row in l0_rows if int(row["seed"])==args.trace_seed and row["estimator"]=="eskf_conservative"]
    selected_nominal=next(row for row in selected_l0 if row["stress_mode"]=="nominal")
    selected_stress=next(row for row in selected_l0 if row["stress_mode"]=="stress")
    report_lines=[
        "# PR3 v5 gravity-correction suppression diagnostic",
        "",
        "This report uses only the checked-in v5 **development** archive and its development seed range. The focused comparison is static / uniform 208 Hz, unknown startup, IMU only, startup calibration off, and no runtime aid. Nominal and stress use the same seed, protocol, profile, and estimator settings; only the v5 stress transform changes.",
        "",
        "## Provenance and scope",
        "",
        f"- Archive SHA-256: `{archive_hash}`; manifest SHA-256: `{sha256(ARCHIVE_MANIFEST)}`.",
        f"- Protocol SHA-256: `{protocol_hash}`; all 200 regenerated stream hashes match the archived hashes.",
        f"- L0 contains {len(l0_rows)} estimator-trial rows for 100 matched development seeds × 2 noise modes × 3 ESKF policies. No held-out or final-confirmation seed was used.",
        f"- All {len(l0_rows)} replayed ESKF trial metric rows matched their frozen v5 archive rows within `2e-6` relative tolerance.",
        "- The generator and evaluator write only under an automatically created temporary directory; the frozen v5 archives, manifests, reports, figures, and historical traces were read-only.",
        "",
        "## Development static/208 Hz rollup",
        "",
        "| Conservative ESKF condition | n | Mean tilt RMS (°) | Median (°) | P95 (°) | Worst (°) | Total gravity attempts / accepts | Mean longest candidate run |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| Nominal | 100 | {conservative_nominal['mean_tilt_rms_deg']:.4f} | {conservative_nominal['median_tilt_rms_deg']:.4f} | {conservative_nominal['p95_tilt_rms_deg']:.4f} | {conservative_nominal['worst_tilt_rms_deg']:.4f} | {sum(int(r['nominal_gravity_attempts']) for r in paired_rows if r['estimator']=='eskf_conservative')} / {sum(int(r['nominal_gravity_accepted']) for r in paired_rows if r['estimator']=='eskf_conservative')} | {statistics.mean(int(r['max_candidate_dwell']) for r in l0_rows if r['estimator']=='eskf_conservative' and r['stress_mode']=='nominal'):.2f} |",
        f"| Stress | 100 | {conservative_stress['mean_tilt_rms_deg']:.4f} | {conservative_stress['median_tilt_rms_deg']:.4f} | {conservative_stress['p95_tilt_rms_deg']:.4f} | {conservative_stress['worst_tilt_rms_deg']:.4f} | {sum(int(r['stress_gravity_attempts']) for r in paired_rows if r['estimator']=='eskf_conservative')} / {sum(int(r['stress_gravity_accepted']) for r in paired_rows if r['estimator']=='eskf_conservative')} | {statistics.mean(int(r['max_candidate_dwell']) for r in l0_rows if r['estimator']=='eskf_conservative' and r['stress_mode']=='stress'):.2f} |",
        f"| Paired stress − nominal | 100 | mean {conservative_delta['mean_tilt_rms_deg']:+.4f} | median {conservative_delta['median_tilt_rms_deg']:+.4f} | P95 {conservative_delta['p95_tilt_rms_deg']:+.4f} | max {conservative_delta['worst_tilt_rms_deg']:+.4f} | | |",
        "",
        "## Exact gate sequence",
        "",
        f"Seed {args.trace_seed} initializes on sample {selected_stress['initialized_sample_index']} and remains `Nominal` with full availability in both conditions. Stress tilt RMS is `{selected_nominal['archived_tilt_rms_deg']}`° nominal versus `{selected_stress['archived_tilt_rms_deg']}`° stress in the frozen archive.",
        f"Nominal has `{selected_nominal['gravity_attempts']}` gravity attempts and `{selected_nominal['gravity_accepted']}` accepts; the first accepted correction is at sample {first_accepted}. Stress has `{selected_stress['gravity_attempts']}` attempts and `{selected_stress['gravity_accepted']}` accepts. Its maximum consecutive candidate dwell is {selected_stress['max_candidate_dwell']} samples.",
        "",
        "The failing gate is the stationary-candidate adjacent-acceleration-step threshold (`step < 0.20 m/s²`). The stress seed has 586 post-initialization step-gate failures; its maximum candidate run is 42. A gravity attempt requires 35 consecutive candidates to declare stationarity, then 21 further candidate samples to satisfy the 21-sample aid cadence. Therefore at least 55 consecutive candidates are required for the first attempt, and 42 is insufficient. Acceleration-norm and gyro-norm criteria pass throughout this selected stress replay. The filter initializes correctly and health remains `Nominal`; gravity corrections are absent because the stationary gate never remains open long enough to reach cadence.",
        "",
        "This identifies the gate interaction without changing thresholds or filter behavior. It does not claim that raising the step threshold is safe; the present prompt authorizes diagnosis and instrumentation only.",
        "",
        "## Artifacts and deterministic replay",
        "",
        "- `v5_dev_static208_l0_per_trial.csv`: one diagnostic summary row per development stream and ESKF policy (600 rows).",
        "- `v5_dev_static208_l0_paired_deltas.csv`: matched nominal/stress deltas by seed and ESKF policy (300 rows).",
        f"- `v5_dev_static208_seed{args.trace_seed}_nominal_l1.csv` and `v5_dev_static208_seed{args.trace_seed}_stress_l1.csv`: per-sample gates, bias states/errors, tilt error, yaw-gauge-invariant projected covariance, health, and update outcomes.",
        f"- `v5_dev_static208_seed{args.trace_seed}_nominal_l2_covariance.csv`: full 15×15 covariance immediately before and after the single selected accepted update at sample {first_accepted}.",
        f"- `v5_dev_static208_seed{args.trace_seed}_gravity_trace.svg` and `v5_dev_static208_paired_seed_tilt.svg`: selected causal timeline and all-seed paired comparison.",
        "",
        "Run under WSL from the repository root (g++ is required):",
        "",
        "```text",
        f"python3 tools/pr3_gravity_suppression.py --output-dir remediation/analysis/pr3_gravity_suppression_a4 --trace-seed {args.trace_seed}",
        "```",
        "",
        "The tool refuses a forensic request outside one development static/208 Hz unknown-startup IMU-only stream and one sample event. L2 capture is not exposed through the full-factor benchmark runner.",
        "",
        "All measurements are synthetic host simulation evidence. Hardware validation was not run.",
        "",
    ]
    report_path=output/"A4_GRAVITY_SUPPRESSION.md"
    report_path.write_text("\n".join(report_lines),encoding="utf-8",newline="\n")
    artifact_paths=[l0_path,paired_path,*selected_traces.values(),forensic_path,trace_figure,paired_figure,summary_path,report_path]
    outputs={path.name:{"sha256":sha256(path),"bytes":path.stat().st_size} for path in artifact_paths}
    compiler_version=run([*compiler,"--version"],capture=True).splitlines()[0]
    manifest={
        "schema_version":1,"tool_id":TOOL_ID,"implementation_commit":implementation_commit,
        "protocol_path":str(PROTOCOL.relative_to(ROOT)),"protocol_sha256":protocol_hash,
        "archive_path":str(ARCHIVE.relative_to(ROOT)),"archive_sha256":archive_hash,
        "archive_manifest_path":str(ARCHIVE_MANIFEST.relative_to(ROOT)),
        "archive_manifest_sha256":sha256(ARCHIVE_MANIFEST),
        "generator_source_sha256":sha256(ROOT/"tools/pr3_generate_inputs.cpp"),
        "evaluator_source_sha256":sha256(ROOT/"tools/pr3_evaluate_stream.cpp"),
        "filter_header_sha256":sha256(ROOT/"eskf15.hpp"),
        "analysis_tool_sha256":sha256(Path(__file__)),"compiler":compiler_version,
        "split":"development","scenario":"static","rate_mode":"uniform_208hz",
        "profile":"IMU_ONLY/UNKNOWN/calibration-OFF/aid-NONE","seed_range":[seed_range["first_seed"],seed_range["last_seed"]],
        "trace_seed":args.trace_seed,"forensic_sample_index":first_accepted,
        "forensic_covariance_snapshot_count":2,"l0_rows":len(l0_rows),"paired_rows":len(paired_rows),
        "outputs":outputs,
    }
    (output/"trace_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    print(f"PASS A4 gravity trace: {len(l0_rows)} trial rows, {len(paired_rows)} paired rows, L2 event sample {first_accepted}")
    for name,meta in outputs.items():
        print(f"SHA256 {meta['sha256']}  {name} ({meta['bytes']} bytes)")
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"remediation/analysis/pr3_gravity_suppression_a4")
    parser.add_argument("--trace-seed",type=int,help="development seed for L1/L2; defaults to largest frozen stress-minus-nominal tilt delta")
    parser.add_argument("--cxx",default=os.environ.get("CXX","c++"))
    args=parser.parse_args(argv)
    try:
        return run_analysis(args)
    except (OSError,ValueError,RuntimeError,KeyError,IndexError) as error:
        print(f"FAIL A4 gravity suppression analysis: {error}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
