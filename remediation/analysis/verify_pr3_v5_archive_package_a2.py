#!/usr/bin/env python3
"""Read-only integrity and independent aggregate audit for packaged PR3 v5 archives."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

SOURCE_COMMIT = "02c61fe7c4b93d591b042c69b08cfe20a6277722"
PROTOCOL_SHA256 = "1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800"
SPLITS = {
    "dev": ("development", 4001, 4100),
    "heldout": ("held_out", 9001, 9100),
    "final": ("final_confirmation", 10001, 10100),
}
GROUP_FIELDS = (
    "scenario", "rate_mode", "stress_mode", "sensor_input", "startup_knowledge",
    "startup_gyro_bias_calibration", "runtime_aid", "estimator",
)
PROFILE_FIELDS = (
    "sensor_input", "startup_knowledge", "startup_gyro_bias_calibration", "runtime_aid",
)
SOURCE_PATHS = {
    "generator_source_sha256": "tools/pr3_generate_inputs.cpp",
    "evaluator_source_sha256": "tools/pr3_evaluate_stream.cpp",
    "header_codegen_source_sha256": "tools/pr3_generate_scenario_header.py",
    "summarizer_source_sha256": "tools/summarize_pr3_benchmarks.py",
    "runner_source_sha256": "tools/run_pr3_benchmarks.py",
}
PUBLISHED_PROFILES = {
    "Unknown startup, no calibration or aid; nominal":
        ("IMU_ONLY", "UNKNOWN", "OFF", "NONE", "nominal"),
    "Unknown startup, no calibration or aid; stress":
        ("IMU_ONLY", "UNKNOWN", "OFF", "NONE", "stress"),
    "Verified stationary startup + gyro-bias calibration; nominal":
        ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", "ON", "NONE", "nominal"),
    "Verified stationary startup + gyro-bias calibration; stress":
        ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", "ON", "NONE", "stress"),
    "Same calibrated startup + independent synthetic heading; nominal":
        ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", "ON", "INDEPENDENT_MEASUREMENT", "nominal"),
    "Same calibrated startup + independent synthetic heading; stress":
        ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", "ON", "INDEPENDENT_MEASUREMENT", "stress"),
    "Same calibrated startup + simulator-oracle heading; nominal":
        ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", "ON", "SIMULATOR_ORACLE", "nominal"),
    "Same calibrated startup + simulator-oracle heading; stress":
        ("IMU_WITH_SYNTHETIC_HEADING", "EXTERNALLY_VERIFIED_STATIC", "ON", "SIMULATOR_ORACLE", "stress"),
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fd:
        for block in iter(lambda: fd.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_text_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def git_blob_sha256(repo: Path, revision: str, relpath: str) -> str:
    data = subprocess.check_output(
        ["git", "cat-file", "blob", f"{revision}:{relpath}"], cwd=repo
    )
    return sha256_bytes(data)


def parse_plan_archive_hashes(plan_text: str) -> list[str]:
    match = re.search(
        r"Their observed compressed SHA-256 values, in that order, are:\s*```[^\n]*\n(.*?)\n```",
        plan_text,
        re.S,
    )
    require(match is not None, "could not locate the plan's archive checksum block")
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def parse_plan_final_aggregates(plan_text: str) -> dict[str, tuple[float, float, float]]:
    marker = "### 1.4 Results audited from the final-confirmation archive"
    require(marker in plan_text, "could not locate the published final-archive aggregate table")
    section = plan_text.split(marker, 1)[1].split("\n### ", 1)[0]
    result = {}
    for line in section.splitlines():
        if not line.startswith("|") or "startup" not in line.lower():
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", " ".join(cells[1:]))]
        if len(values) == 3:
            result[cells[0].replace("**", "")] = tuple(values)
    require(len(result) == 8, f"expected 8 published aggregate rows, found {len(result)}")
    return result


def audit_split(repo: Path, generated_root: Path, plan_hash: str, short: str,
                split: str, first_seed: int, last_seed: int) -> dict[str, object]:
    stem = f"pr3_protocol_v5_{short}100_all_factors_postfix"
    archive = repo / "benchmarks/reports" / f"{stem}_trials.csv.gz"
    manifest_path = repo / "benchmarks/manifests" / f"{stem}.json"
    summary_path = repo / "benchmarks/reports" / f"{stem}_summary.json"
    protocol_path = repo / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"
    generated = generated_root / stem
    generated_manifest_path = generated / "pr3_run_manifest.json"
    generated_summary_path = generated / "pr3_summary.json"
    generated_csv_path = generated / "pr3_trial_summaries.csv"

    for path in (archive, manifest_path, summary_path, protocol_path,
                 generated_manifest_path, generated_summary_path, generated_csv_path):
        require(path.is_file(), f"required evidence file is missing: {path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated_manifest = json.loads(generated_manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    generated_summary = json.loads(generated_summary_path.read_text(encoding="utf-8"))

    archive_sha = sha256_file(archive)
    uncompressed_sha = hashlib.sha256()
    with gzip.open(archive, "rb") as fd:
        for block in iter(lambda: fd.read(1024 * 1024), b""):
            uncompressed_sha.update(block)
    uncompressed_sha = uncompressed_sha.hexdigest()
    generated_csv_sha = sha256_file(generated_csv_path)
    summary_sha = canonical_text_sha256(summary_path)

    require(archive_sha == manifest["packaged_trial_csv_gz_sha256"], f"archive/manifest hash mismatch: {archive}")
    require(uncompressed_sha == manifest["summary_csv_sha256"], f"decompressed CSV/manifest hash mismatch: {archive}")
    require(generated_csv_sha == manifest["summary_csv_sha256"], f"generated CSV/manifest hash mismatch: {generated_csv_path}")
    require(uncompressed_sha == generated_csv_sha, f"archive payload differs from generated CSV: {archive}")
    require(summary_sha == manifest["summary_report_sha256"], f"summary/manifest hash mismatch: {summary_path}")
    require(manifest["packaged_trial_csv_gz_path"] == f"benchmarks/reports/{stem}_trials.csv.gz", f"wrong packaged archive path: {manifest_path}")
    require(manifest["protocol_version"] == 5 and manifest["split"] == split, f"wrong protocol/split: {manifest_path}")
    require(manifest["source_commit"] == SOURCE_COMMIT and generated_manifest["source_commit"] == SOURCE_COMMIT, f"source commit mismatch: {manifest_path}")
    require(manifest["protocol_sha256"] == PROTOCOL_SHA256 and generated_manifest["protocol_sha256"] == PROTOCOL_SHA256, f"protocol identity mismatch: {manifest_path}")
    require(manifest["working_tree_dirty_at_run"] is False and generated_manifest["working_tree_dirty_at_run"] is False, f"dirty source provenance: {manifest_path}")
    require(manifest["seed_range_inclusive"] == [first_seed, last_seed], f"wrong seed range: {manifest_path}")
    require(git_blob_sha256(repo, SOURCE_COMMIT, "benchmarks/scenarios/pr3_scenarios_protocol_v5.json") == PROTOCOL_SHA256, "protocol Git blob identity mismatch")
    require(canonical_text_sha256(protocol_path) == PROTOCOL_SHA256, "protocol working-copy content differs after line-ending normalization")

    for field, relpath in SOURCE_PATHS.items():
        require(git_blob_sha256(repo, SOURCE_COMMIT, relpath) == manifest[field], f"frozen source hash mismatch: {relpath}")
    require(canonical_text_sha256(repo / "tools/verify_pr3_full_factor_evidence.py") == manifest["verification_source_sha256"], "recorded verifier source hash mismatch")
    require(canonical_text_sha256(repo / "tools/package_pr3_full_factor_evidence.py") == manifest["packaging_source_sha256"], "recorded packager source hash mismatch")

    tracked_inputs = manifest["input_streams"]
    generated_inputs = generated_manifest["input_streams"]
    require(len(tracked_inputs) == len(generated_inputs) == 4800, f"input manifest count mismatch: {split}")
    require(tracked_inputs == generated_inputs, f"packaged manifest differs from run manifest input inventory: {split}")
    manifest_streams = {}
    for item in tracked_inputs:
        key = (item["scenario"], item["rate_mode"], item["stress_mode"], str(item["seed"]))
        require(key not in manifest_streams, f"duplicate manifest stream: {key}")
        require(item["split"] == split, f"wrong split on input stream: {key}")
        manifest_streams[key] = item["sha256"]

    rows = 0
    incomplete = 0
    group_counts: Counter[tuple[str, ...]] = Counter()
    stream_counts: Counter[tuple[str, ...]] = Counter()
    stream_hashes: dict[tuple[str, ...], set[str]] = defaultdict(set)
    expected_by_rate: dict[str, set[int]] = defaultdict(set)
    covariance_expected: Counter[str] = Counter()
    covariance_valid: Counter[str] = Counter()
    profiles = set()
    scenarios, rates, stress_modes, seeds, estimators = set(), set(), set(), set(), set()
    final_rows: list[dict[str, str]] = []

    with gzip.open(archive, "rt", newline="", encoding="utf-8") as fd:
        reader = csv.DictReader(fd)
        require(reader.fieldnames is not None and "input_sha256" in reader.fieldnames, f"CSV schema missing input hash: {archive}")
        for row in reader:
            rows += 1
            scenarios.add(row["scenario"])
            rates.add(row["rate_mode"])
            stress_modes.add(row["stress_mode"])
            seeds.add(int(row["seed"]))
            estimators.add(row["estimator"])
            profiles.add(tuple(row[field] for field in PROFILE_FIELDS))
            group_counts[tuple(row[field] for field in GROUP_FIELDS)] += 1
            stream_key = (row["scenario"], row["rate_mode"], row["stress_mode"], row["seed"])
            stream_counts[stream_key] += 1
            stream_hashes[stream_key].add(row["input_sha256"])
            if row["complete_run"].lower() != "true":
                incomplete += 1
            expected = int(row["expected"])
            expected_by_rate[row["rate_mode"]].add(expected)
            if row["estimator"].startswith("eskf_"):
                covariance_expected[row["estimator"]] += expected
                covariance_valid[row["estimator"]] += int(row["covariance_valid"])
            if split == "final_confirmation":
                final_rows.append(row)

    require(rows == 168000, f"expected 168,000 archived rows; found {rows}: {split}")
    require(len(scenarios) == 8 and len(rates) == 3 and len(stress_modes) == 2 and len(seeds) == 100 and len(estimators) == 5, f"factor cardinality mismatch: {split}")
    require((min(seeds), max(seeds)) == (first_seed, last_seed), f"seed range mismatch in CSV: {split}")
    require(len(profiles) == 7, f"expected seven declared profiles: {split}")
    require(len(group_counts) == 1680 and set(group_counts.values()) == {100}, f"factor groups not balanced at 100: {split}")
    require(len(stream_counts) == 4800 and set(stream_counts.values()) == {35}, f"expected 4,800 shared streams with 35 estimator/profile rows each: {split}")
    require(set(stream_hashes) == set(manifest_streams), f"CSV and manifest stream identities differ: {split}")
    require(all(len(hashes) == 1 and next(iter(hashes)) == manifest_streams[key] for key, hashes in stream_hashes.items()), f"CSV input hashes disagree with manifest: {split}")
    require(not incomplete, f"incomplete rows found: {incomplete} in {split}")
    require(dict(expected_by_rate) == {"uniform_200hz": {2801}, "uniform_208hz": {2913}, "irregular_208hz": {2913}}, f"unexpected sample counts: {dict(expected_by_rate)}")
    require(set(covariance_expected) == {"eskf_conservative", "eskf_legacy", "eskf_confirmed_only"}, f"ESKF policy set mismatch: {split}")
    require(all(covariance_expected[name] == covariance_valid[name] == 96622400 for name in covariance_expected), f"covariance count mismatch: {split}")
    require(summary["trial_row_count"] == 168000 and len(summary["distribution_groups"]) == 1680, f"tracked summary counts mismatch: {split}")
    require(len(summary["paired_confidence_intervals"]) == 3360 and not summary["incomplete_or_failed_trials"], f"tracked summary completeness mismatch: {split}")
    require(len(summary["figures"]) == 210 and len(set(Path(name).name for name in summary["figures"])) == 210, f"tracked figure inventory mismatch: {split}")
    require(len(generated_summary["figures"]) == 210, f"generated figure inventory mismatch: {split}")

    figure_hashes = manifest["additional_figure_sha256"]
    for name in summary["figures"]:
        basename = Path(name).name
        expected_sha = manifest["figure_sha256"] if basename == Path(summary["figures"][0]).name else figure_hashes.get(basename)
        require(expected_sha is not None, f"figure absent from manifest: {basename}")
        figure = repo / "benchmarks/figures" / basename
        require(figure.is_file() and canonical_text_sha256(figure) == expected_sha, f"packaged figure hash mismatch: {figure}")

    return {
        "split": split,
        "seed_range": [first_seed, last_seed],
        "archive_sha256": archive_sha,
        "plan_sha256": plan_hash,
        "plan_hash_length": len(plan_hash),
        "plan_archive_hash_matches": plan_hash == archive_sha,
        "manifest_archive_hash_matches": True,
        "decompressed_csv_sha256": uncompressed_sha,
        "manifest_csv_hash_matches": True,
        "summary_sha256": summary_sha,
        "manifest_summary_hash_matches": True,
        "protocol_and_source_identities": "PASS",
        "shared_streams": len(stream_counts),
        "stream_hashes_match_manifest": True,
        "rows": rows,
        "factor_groups": len(group_counts),
        "trials_per_group": 100,
        "profiles": len(profiles),
        "incomplete_rows": incomplete,
        "covariance_checks_per_eskf": {
            name: {"valid": covariance_valid[name], "expected": covariance_expected[name]}
            for name in sorted(covariance_expected)
        },
        "paired_intervals": len(summary["paired_confidence_intervals"]),
        "checked_in_figures_hashed": len(summary["figures"]),
    }, final_rows


def audit_published_aggregates(plan: dict[str, tuple[float, float, float]],
                               final_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    checks = []
    for label, profile in PUBLISHED_PROFILES.items():
        sensor_input, startup, calibration, aid, stress = profile
        matching = [row for row in final_rows
                    if (row["sensor_input"], row["startup_knowledge"],
                        row["startup_gyro_bias_calibration"], row["runtime_aid"],
                        row["stress_mode"]) == profile]
        for estimator in ("eskf_conservative", "mahony"):
            selected = [row for row in matching if row["estimator"] == estimator]
            require(len(selected) == 2400, f"expected 2,400 final trials for {label}/{estimator}, got {len(selected)}")
            metric = fmean(float(row["tilt_rms_deg"]) for row in selected)
            expected = plan[label][0 if estimator == "eskf_conservative" else 1]
            checks.append({"configuration": label, "metric": f"{estimator} tilt_rms_deg",
                           "published": expected, "independent": metric,
                           "rounded_to_4dp_matches": round(metric, 4) == expected})
            require(round(metric, 4) == expected, f"published tilt aggregate mismatch for {label}/{estimator}")
        conservative = [row for row in matching if row["estimator"] == "eskf_conservative"]
        yaw = fmean(float(row["yaw_rms_deg"]) for row in conservative)
        expected_yaw = plan[label][2]
        checks.append({"configuration": label, "metric": "eskf_conservative yaw_rms_deg",
                       "published": expected_yaw, "independent": yaw,
                       "rounded_to_4dp_matches": round(yaw, 4) == expected_yaw})
        require(round(yaw, 4) == expected_yaw, f"published yaw aggregate mismatch for {label}")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--generated-root", type=Path, required=True,
                        help="existing generated run directories; read-only")
    parser.add_argument("--plan", type=Path, required=True,
                        help="full technical plan containing the published hashes and aggregate table")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    generated_root = args.generated_root.resolve()
    plan_text = args.plan.read_text(encoding="utf-8")
    plan_hashes = parse_plan_archive_hashes(plan_text)
    require(len(plan_hashes) == 3, f"expected three documented archive hashes, found {len(plan_hashes)}")
    published = parse_plan_final_aggregates(plan_text)

    source_commit_ok = subprocess.run(
        ["git", "cat-file", "-e", f"{SOURCE_COMMIT}^{{commit}}"], cwd=repo
    ).returncode == 0
    require(source_commit_ok, f"source commit unavailable: {SOURCE_COMMIT}")
    source_file_hashes = {
        field: git_blob_sha256(repo, SOURCE_COMMIT, path)
        for field, path in SOURCE_PATHS.items()
    }
    results = []
    final_rows = []
    for i, (short, (split, first_seed, last_seed)) in enumerate(SPLITS.items()):
        result, rows = audit_split(repo, generated_root, plan_hashes[i], short, split, first_seed, last_seed)
        results.append(result)
        if split == "final_confirmation":
            final_rows = rows
    aggregate_checks = audit_published_aggregates(published, final_rows)
    print(json.dumps({
        "source_commit": SOURCE_COMMIT,
        "source_commit_available": source_commit_ok,
        "frozen_source_hashes": source_file_hashes,
        "archive_splits": results,
        "published_final_aggregate_checks": aggregate_checks,
        "aggregate_checks_passed": len(aggregate_checks),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()