#!/usr/bin/env python3
"""Validate paired six-scenario Bundle B summaries for PR 2."""
import csv
import sys
from pathlib import Path

KEYS = ("scenario", "model", "seed", "startup_bias")
METRICS = (
    "expected", "valid", "tilt_rms_deg", "tilt_p95_deg", "tilt_max_deg",
    "yaw_rms_deg", "tilt_nees_mean", "tilt_nees_coverage95", "gravity_nis_mean",
    "gyro_bias_error_rps", "gravity_applied", "gravity_suppressed",
)


def load(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        rows = []
        for raw in reader:
            if len(raw) == len(header):
                row = dict(zip(header, raw))
            elif len(raw) == len(header)-1 and raw[2] in ("eskf_legacy", "mahony"):
                # When NEES has no samples, the frozen writer omits the
                # coverage field. Restore that missing slot before parsing the
                # optional tail so NIS, bias, and gravity counters stay aligned.
                repaired = raw[:12] + [""] + raw[12:]
                row = dict(zip(header, repaired))
            else:
                raise ValueError(f"malformed Bundle B row in {path}: {len(raw)} columns")
            rows.append(row)
    result = {}
    for row in rows:
        key = tuple(row[field] for field in KEYS)
        if key in result:
            raise ValueError(f"duplicate row in {path}: {key}")
        if int(row["valid"]) != int(row["expected"]):
            raise ValueError(f"availability differs from fixed denominator in {path}: {key}")
        result[key] = row
    if len(result) != 90:
        raise ValueError(f"expected 90 rows in {path}, got {len(result)}")
    return result


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: compare_pr2_bundle_b.py BASELINE.csv CANDIDATE.csv OUTPUT.csv")
    baseline, candidate, output = map(Path, sys.argv[1:])
    base, cand = load(baseline), load(candidate)
    if base.keys() != cand.keys():
        raise ValueError("baseline and candidate Bundle B keys differ")
    fields = [*KEYS]
    for metric in METRICS:
        fields.extend((f"baseline_{metric}", f"candidate_{metric}"))
        if metric not in ("expected",):
            fields.append(f"delta_{metric}")
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key in sorted(base):
            b, c = base[key], cand[key]
            row = dict(zip(KEYS, key))
            for metric in METRICS:
                bv, cv = b[metric], c[metric]
                row[f"baseline_{metric}"] = bv
                row[f"candidate_{metric}"] = cv
                if metric != "expected":
                    row[f"delta_{metric}"] = (
                        "" if not bv or not cv else f"{float(cv)-float(bv):.8g}"
                    )
            writer.writerow(row)
    print(f"PASS paired Bundle B comparison: {len(base)} rows; fixed availability; source and seed pairing verified by runner")


if __name__ == "__main__":
    main()
