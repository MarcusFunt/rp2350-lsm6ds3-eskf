#!/usr/bin/env python3
"""Summarize synthetic results, preserving run-to-run variability."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def read(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    versions = {row.get('evaluation_protocol_version', '') for row in rows}
    if versions != {'2'}:
        raise ValueError('This summarizer requires evaluation protocol v2; protocol-v1 results are superseded for tilt metrics')
    expected = {'static', 'slow_yaw', 'lateral_accel', 'maneuver', 'vibration', 'timing_jitter'}
    if {r['scenario'] for r in rows} != expected:
        raise ValueError('Missing benchmark scenario(s)')
    return rows


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['scenario'], row['model'])].append(row)
    output = []
    for (scene, model), group in sorted(groups.items()):
        def mean(col):
            vals = [float(r[col]) for r in group if r[col] and math.isfinite(float(r[col]))]
            return statistics.mean(vals) if vals else None
        output.append({
            'scenario': scene, 'model': model, 'trials': len(group),
            'tilt_rms_mean_deg': mean('tilt_rms_deg'),
            'tilt_rms_between_trial_sd_deg': statistics.stdev(float(r['tilt_rms_deg']) for r in group) if len(group)>1 else 0,
            'tilt_p95_mean_deg': mean('tilt_p95_deg'),
            'yaw_rms_mean_deg': mean('yaw_rms_deg'),
            'tilt_nees_mean': mean('tilt_nees_mean'),
            'tilt_nees_coverage95_mean': mean('tilt_nees_coverage95'),
            'gravity_nis_mean': mean('gravity_nis_mean'),
            'valid_fraction': statistics.mean(int(r['valid'])/int(r['expected']) for r in group),
        })
    return output


def markdown(summary, source):
    lines = ['# Bundle B: synthetic estimator comparison', '',
             f'Source CSV: `{source}`. Results are simulated, not measured on RP2350 hardware.', '',
             '| Scenario | Estimator | Trials | Mean tilt RMS (deg) | Between-trial SD (deg) | Mean yaw RMS (deg) | Valid fraction |',
             '|---|---|---:|---:|---:|---:|---:|']
    for row in summary:
        lines.append(f"| {row['scenario']} | {row['model']} | {row['trials']} | "
                     f"{row['tilt_rms_mean_deg']:.3f} | {row['tilt_rms_between_trial_sd_deg']:.3f} | "
                     f"{row['yaw_rms_mean_deg']:.3f} | {row['valid_fraction']:.3f} |")
    lines.extend(['', '## Interpretation limits', '',
                  '- The initial 2 seconds are truly stationary by scenario definition; optional startup bias calibration uses that known fact. This is not an IMU-only stationarity detector.',
                  '- The truth state is propagated independently of the estimators. All three estimators receive identical sensor samples within each trial.',
                  '- Trial means are means of per-run RMS values, not pooled sample-level RMS; the standard deviation represents variation between random seeds.',
                  '- Tilt NEES uses the world-horizontal 2D projection and excludes unobservable yaw. With gravity aiding reusing the same IMU data, ideal chi-squared NEES/NIS expectations may not apply exactly.',
                  '- A simulator can detect coding mistakes and model assumptions; it cannot establish accuracy or latency on actual LSM6DS3/RP2350 hardware.', ''])
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('csv')
    parser.add_argument('--markdown')
    parser.add_argument('--json')
    args=parser.parse_args()
    summary=summarize(read(args.csv))
    if args.markdown: Path(args.markdown).write_text(markdown(summary, Path(args.csv).name), encoding='utf-8')
    if args.json: Path(args.json).write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    if not args.markdown and not args.json:print(markdown(summary, Path(args.csv).name))

if __name__=='__main__':main()
