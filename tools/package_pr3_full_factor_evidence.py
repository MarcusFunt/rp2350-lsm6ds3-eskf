#!/usr/bin/env python3
"""Package generated PR3 full-factor runs as deterministic tracked evidence.

Run this after ``tools/run_pr3_benchmarks.py`` has completed all three 100-seed
splits. It compresses the trial CSVs and copies the summaries, manifests, and
figures into their versioned repository locations. It never evaluates trials.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "dev": ("pr3_protocol_v5_dev100_all_factors_postfix", "development"),
    "heldout": ("pr3_protocol_v5_heldout100_all_factors_postfix", "held_out"),
    "final": ("pr3_protocol_v5_final100_all_factors_postfix", "final_confirmation"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package(root: Path, generated_root: Path) -> list[dict[str, object]]:
    reports = root / "benchmarks/reports"
    manifests = root / "benchmarks/manifests"
    figures = root / "benchmarks/figures"
    for directory in (reports, manifests, figures):
        directory.mkdir(parents=True, exist_ok=True)

    results = []
    for short, (run_name, expected_split) in RUNS.items():
        run_dir = generated_root / run_name
        csv_path = run_dir / "pr3_trial_summaries.csv"
        summary_path = run_dir / "pr3_summary.json"
        manifest_path = run_dir / "pr3_run_manifest.json"
        if not all(path.is_file() for path in (csv_path, summary_path, manifest_path)):
            raise FileNotFoundError(f"incomplete run output: {run_dir}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["split"] != expected_split:
            raise ValueError(f"unexpected split in {manifest_path}: {manifest['split']}")
        if len(manifest["input_streams"]) != 4800:
            raise ValueError(f"unexpected input count in {manifest_path}")
        if sha256(csv_path) != manifest["summary_csv_sha256"]:
            raise ValueError(f"CSV hash mismatch in {run_dir}")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["trial_row_count"] != 168000 or len(summary["figures"]) != 210:
            raise ValueError(f"unexpected summary dimensions in {run_dir}")

        base = f"pr3_protocol_v5_{short}100_all_factors_postfix"
        csv_rel = f"benchmarks/reports/{base}_trials.csv.gz"
        csv_gz_path = root / csv_rel
        with csv_path.open("rb") as source, csv_gz_path.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0, compresslevel=9) as compressed:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)

        packaged_figure_names = []
        for old_ref in summary["figures"]:
            name = Path(old_ref).name
            source = run_dir / "figures" / name
            destination = figures / name
            expected_hash = manifest["figure_sha256"] if not packaged_figure_names else manifest["additional_figure_sha256"].get(name)
            if not source.is_file() or not expected_hash or sha256(source) != expected_hash:
                raise ValueError(f"figure hash/missing mismatch: {source}")
            shutil.copyfile(source, destination)
            packaged_figure_names.append(name)

        summary["source_summary"] = csv_rel
        summary["figures"] = [f"benchmarks/figures/{name}" for name in packaged_figure_names]
        summary_out = reports / f"{base}_summary.json"
        summary_out.write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n",
            encoding="utf-8", newline="\n",
        )

        manifest["summary_source_label"] = csv_rel
        manifest["figure_path_prefix"] = "benchmarks/figures/"
        manifest["packaged_trial_csv_gz_path"] = csv_rel
        manifest["packaged_trial_csv_gz_sha256"] = sha256(csv_gz_path)
        manifest["packaging_source_sha256"] = sha256(Path(__file__))
        manifest["verification_source_sha256"] = sha256(ROOT / "tools/verify_pr3_full_factor_evidence.py")
        manifest["summary_report_sha256"] = sha256(summary_out)
        manifest_out = manifests / f"{base}.json"
        manifest_out.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

        results.append({
            "split": expected_split,
            "trial_csv_sha256": manifest["summary_csv_sha256"],
            "archive_sha256": manifest["packaged_trial_csv_gz_sha256"],
            "summary_sha256": manifest["summary_report_sha256"],
            "manifest_sha256": sha256(manifest_out),
            "input_streams": len(manifest["input_streams"]),
            "figures": len(packaged_figure_names),
            "manifest": f"benchmarks/manifests/{base}.json",
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generated-root", type=Path, default=ROOT / "benchmarks/generated",
        help="directory containing the three completed full-factor run outputs",
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    results = package(args.repository_root.resolve(), args.generated_root.resolve())
    for result in results:
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
