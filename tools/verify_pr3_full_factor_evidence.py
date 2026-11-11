#!/usr/bin/env python3
"""Independently verify one generated PR3 100-seed all-factor run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


PROTOCOL_SHA256 = "1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800"
SOURCE_COMMIT = "02c61fe7c4b93d591b042c69b08cfe20a6277722"
GROUP_FIELDS = (
    "scenario", "rate_mode", "stress_mode", "sensor_input", "startup_knowledge",
    "startup_gyro_bias_calibration", "runtime_aid", "estimator",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(run_dir: Path) -> dict[str, object]:
    manifest_path = run_dir / "pr3_run_manifest.json"
    summary_path = run_dir / "pr3_summary.json"
    csv_path = run_dir / "pr3_trial_summaries.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert manifest["protocol_version"] == 5
    assert manifest["protocol_sha256"] == PROTOCOL_SHA256
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert len(manifest["input_streams"]) == 4800
    assert sha256(csv_path) == manifest["summary_csv_sha256"]
    assert sha256(summary_path) == manifest["summary_report_sha256"]

    for item in manifest["input_streams"]:
        input_path = run_dir / item["path"]
        if sha256(input_path) != item["sha256"]:
            raise ValueError(f"input SHA-256 mismatch: {input_path}")

    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 168000:
        raise ValueError(f"expected 168,000 trial rows, found {len(rows)}")
    if len({row["scenario"] for row in rows}) != 8:
        raise ValueError("scenario balance mismatch")
    if len({row["rate_mode"] for row in rows}) != 3:
        raise ValueError("sampling-rate balance mismatch")
    if len({row["stress_mode"] for row in rows}) != 2:
        raise ValueError("stress-mode balance mismatch")
    if len({row["seed"] for row in rows}) != 100:
        raise ValueError("seed count mismatch")

    profile_fields = (
        "sensor_input", "startup_knowledge", "startup_gyro_bias_calibration", "runtime_aid",
    )
    profiles = {tuple(row[field] for field in profile_fields) for row in rows}
    if len(profiles) != 7:
        raise ValueError(f"expected seven declared profiles, found {len(profiles)}")

    groups = Counter(tuple(row[field] for field in GROUP_FIELDS) for row in rows)
    if len(groups) != 1680 or set(groups.values()) != {100}:
        raise ValueError("factor groups are not balanced at 100 trials each")

    stream_hashes: dict[tuple[str, ...], set[str]] = defaultdict(set)
    config_hashes: dict[tuple[str, ...], set[str]] = defaultdict(set)
    expected_samples: dict[str, set[int]] = defaultdict(set)
    means: dict[tuple[str, str], list[float]] = defaultdict(list)
    covariance_expected: dict[str, int] = defaultdict(int)
    covariance_valid: dict[str, int] = defaultdict(int)
    incomplete = []
    for row in rows:
        stream_key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["seed"])
        config_key = stream_key + tuple(row[field] for field in profile_fields)
        stream_hashes[stream_key].add(row["input_sha256"])
        config_hashes[config_key].add(row["config_sha256"])
        expected_samples[row["rate_mode"]].add(int(row["expected"]))
        if row["complete_run"].lower() != "true":
            incomplete.append(row)
        if row["estimator"].startswith("eskf_"):
            covariance_expected[row["estimator"]] += int(row["expected"])
            covariance_valid[row["estimator"]] += int(row["covariance_valid"])
        if row["tilt_rms_deg"]:
            means[(row["estimator"], row["stress_mode"])].append(float(row["tilt_rms_deg"]))

    if any(len(values) != 1 for values in stream_hashes.values()):
        raise ValueError("paired estimator rows do not share the same input hash")
    if any(len(values) != 1 for values in config_hashes.values()):
        raise ValueError("identical profile rows do not share the same config hash")
    if len(incomplete) != 0:
        raise ValueError(f"found {len(incomplete)} incomplete trials")
    expected_by_rate = {
        "uniform_200hz": {2801}, "uniform_208hz": {2913}, "irregular_208hz": {2913},
    }
    if dict(expected_samples) != expected_by_rate:
        raise ValueError(f"unexpected expected-sample counts: {dict(expected_samples)}")
    for estimator, total in covariance_expected.items():
        if total != 96622400 or covariance_valid[estimator] != total:
            raise ValueError(f"covariance check mismatch for {estimator}")

    if summary["trial_row_count"] != len(rows):
        raise ValueError("summary trial count mismatch")
    if len(summary["distribution_groups"]) != 1680:
        raise ValueError("summary distribution count mismatch")
    if len(summary["paired_confidence_intervals"]) != 3360:
        raise ValueError("paired interval count mismatch")
    if summary["incomplete_or_failed_trials"]:
        raise ValueError("summary records incomplete trials")
    figure_names = [Path(ref).name for ref in summary["figures"]]
    if len(figure_names) != 210:
        raise ValueError("expected 210 figures")
    if len(set(figure_names)) != 210 or len(manifest["additional_figure_sha256"]) != 209:
        raise ValueError("manifest figure hash inventory is incomplete")
    if set(manifest["additional_figure_sha256"]) != set(figure_names[1:]):
        raise ValueError("manifest figure names do not match the summary")
    for name in figure_names:
        figure_path = run_dir / "figures" / name
        expected_hash = manifest["figure_sha256"] if name == figure_names[0] else manifest["additional_figure_sha256"].get(name)
        if expected_hash is None or sha256(figure_path) != expected_hash:
            raise ValueError(f"figure SHA-256 mismatch: {figure_path}")

    return {
        "split": manifest["split"],
        "seed_range": manifest["seed_range_inclusive"],
        "input_streams_and_hashes_verified": len(manifest["input_streams"]),
        "trial_rows": len(rows),
        "factor_groups": len(groups),
        "trials_per_group": sorted(set(groups.values())),
        "incomplete_trials": len(incomplete),
        "covariance_checks_per_eskf": {
            estimator: {"valid": covariance_valid[estimator], "expected": covariance_expected[estimator]}
            for estimator in sorted(covariance_expected)
        },
        "mean_trial_tilt_rms_by_estimator_and_stress": {
            f"{key[0]}|{key[1]}": statistics.fmean(values)
            for key, values in sorted(means.items())
        },
        "paired_intervals": len(summary["paired_confidence_intervals"]),
        "figures_and_hashes_verified": len(figure_names),
        "trial_csv_sha256": sha256(csv_path),
        "summary_sha256": sha256(summary_path),
        "run_manifest_sha256": sha256(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="generated run directory to verify")
    args = parser.parse_args()
    print(json.dumps(verify(args.run_dir.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
