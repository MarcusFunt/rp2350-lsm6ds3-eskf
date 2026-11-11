#!/usr/bin/env python3
"""Join a selected PR3 estimator trace with its shared input and emit audit plots."""

import argparse
import csv
import hashlib
import json
import math
import struct
from pathlib import Path


COLORS = {"eskf_conservative": "#2563eb", "eskf_legacy": "#dc2626", "eskf_confirmed_only": "#059669"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unrotate(q, vector):
    w, x, y, z = q
    q = (w, -x, -y, -z)
    vx, vy, vz = vector
    tx = 2.0 * (q[2] * vz - q[3] * vy)
    ty = 2.0 * (q[3] * vx - q[1] * vz)
    tz = 2.0 * (q[1] * vy - q[2] * vx)
    return (
        vx + q[0] * tx + q[2] * tz - q[3] * ty,
        vy + q[0] * ty + q[3] * tx - q[1] * tz,
        vz + q[0] * tz + q[1] * ty - q[2] * tx,
    )


def norm(values):
    return math.sqrt(sum(value * value for value in values))


def tilt_error_deg(estimate, truth):
    left = unrotate(estimate, (0.0, 0.0, 1.0))
    right = unrotate(truth, (0.0, 0.0, 1.0))
    cosine = sum(a * b for a, b in zip(left, right)) / (norm(left) * norm(right))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def shared_truth(input_path):
    data = Path(input_path).read_bytes()
    if data[:8] != b"PR3INP03" or len(data) < 128:
        raise ValueError("input is not a PR3INP03 stream")
    count = struct.unpack_from("<I", data, 28)[0]
    if len(data) != 128 + count * 128:
        raise ValueError("input length does not match its record count")
    records = {}
    for index in range(1, count + 1):
        offset = 128 + (index - 1) * 128
        record_index = struct.unpack_from("<I", data, offset)[0]
        if record_index != index:
            raise ValueError("input sample indices are not contiguous")
        truth_q = struct.unpack_from("<4f", data, offset + 28)
        truth_ba = struct.unpack_from("<3f", data, offset + 68)
        truth_bg = struct.unpack_from("<3f", data, offset + 80)
        records[index] = (truth_q, truth_ba, truth_bg)
    return records


def render(series, output, title, ylabel, *, log10=False):
    width, height = 1120, 520
    left, top, plot_w, plot_h = 92, 70, 950, 350
    points = {}
    for name, values in series.items():
        valid = [(x, math.log10(max(y, 1e-18)) if log10 else y) for x, y in values if math.isfinite(x) and math.isfinite(y)]
        if valid:
            points[name] = valid
    if not points:
        raise ValueError(f"no finite values to plot for {title}")
    xs = [point[0] for values in points.values() for point in values]
    ys = [point[1] for values in points.values() for point in values]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    if ylo == yhi:
        ylo -= 1.0
        yhi += 1.0
    pad = 0.04 * (yhi - ylo)
    ylo -= pad
    yhi += pad
    def sx(value):
        return left + (value - xlo) / max(1e-12, xhi - xlo) * plot_w
    def sy(value):
        return top + plot_h - (value - ylo) / max(1e-12, yhi - ylo) * plot_h
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="92" y="34" font-family="sans-serif" font-size="21" font-weight="bold">{title}</text>',
        '<text x="92" y="54" font-family="sans-serif" font-size="12">PR3 v5 development trace; seed 4001; slow_yaw; 208 Hz nominal</text>',
    ]
    for tick in range(6):
        value = ylo + (yhi - ylo) * tick / 5
        yy = sy(value)
        label = f"10^{value:.1f}" if log10 else f"{value:.3g}"
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_w}" y2="{yy:.1f}" stroke="#d1d5db"/>')
        elements.append(f'<text x="{left-10}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{label}</text>')
    for name, values in points.items():
        path = " ".join(("M" if i == 0 else "L") + f"{sx(x):.2f},{sy(y):.2f}" for i, (x, y) in enumerate(values))
        elements.append(f'<path d="{path}" fill="none" stroke="{COLORS[name]}" stroke-width="1.5"/>')
    for i, name in enumerate(points):
        x = left + i * 235
        elements.append(f'<line x1="{x}" y1="470" x2="{x+18}" y2="470" stroke="{COLORS[name]}" stroke-width="3"/>')
        elements.append(f'<text x="{x+24}" y="474" font-family="sans-serif" font-size="12">{name}</text>')
    elements.append(f'<text x="{left+plot_w/2:.1f}" y="505" text-anchor="middle" font-family="sans-serif" font-size="13">Trial time (s)</text>')
    elements.append(f'<text transform="translate(22 {top+plot_h/2:.1f}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13">{ylabel}</text>')
    elements.append('</svg>')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("\n".join(elements) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="shared PR3INP03 stream")
    parser.add_argument("--trace", required=True, type=Path, help="selected PR3 sample diagnostics CSV")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    truth = shared_truth(args.input)
    series = {name: {"tilt": [], "gyro_bias": [], "accel_bias": [], "covariance": [], "gravity_updates": []} for name in COLORS}
    cumulative = {name: 0 for name in COLORS}
    with args.trace.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            name = row["estimator"]
            if name not in series:
                continue
            index = int(row["sample_index"])
            if index not in truth:
                raise ValueError(f"trace sample {index} is absent from shared input")
            truth_q, truth_ba, truth_bg = truth[index]
            time_s = float(row["nominal_time_s"])
            estimate_q = tuple(float(row[f"orientation_{axis}"]) for axis in "wxyz")
            estimate_ba = tuple(float(row[f"accel_bias_{axis}"]) for axis in "xyz")
            estimate_bg = tuple(float(row[f"gyro_bias_{axis}"]) for axis in "xyz")
            series[name]["tilt"].append((time_s, tilt_error_deg(estimate_q, truth_q)))
            series[name]["gyro_bias"].append((time_s, norm(a-b for a, b in zip(estimate_bg, truth_bg))))
            series[name]["accel_bias"].append((time_s, norm(a-b for a, b in zip(estimate_ba, truth_ba))))
            diagonal = [float(row[f"cov_theta_{axis}{axis}"]) for axis in range(3)]
            series[name]["covariance"].append((time_s, max(diagonal)))
            cumulative[name] += int(row["gravity_updates_delta"])
            series[name]["gravity_updates"].append((time_s, float(cumulative[name])))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plots = {
        "tilt": ("tilt_error", "PR3 world-yaw-invariant tilt error", "Tilt error (degrees)", False),
        "gyro_bias": ("gyro_bias_error", "PR3 gyro-bias estimation error", "Gyro bias error (rad/s)", False),
        "accel_bias": ("accel_bias_error", "PR3 accel-bias estimation error", "Accelerometer bias error (m/s²)", False),
        "covariance": ("attitude_covariance", "PR3 attitude covariance diagonal", "Largest attitude covariance diagonal (log scale)", True),
        "gravity_updates": ("gravity_updates", "PR3 gravity update chronology", "Cumulative accepted gravity updates", False),
    }
    artifacts = {}
    for metric, (filename, title, ylabel, log10) in plots.items():
        destination = args.output_dir / f"pr3_{filename}.svg"
        render({name: values[metric] for name, values in series.items()}, destination, title, ylabel, log10=log10)
        artifacts[destination.name] = sha256(destination)
    manifest = {
        "classification": "selected development diagnostic; not acceptance statistics",
        "input_sha256": sha256(args.input),
        "trace_sha256": sha256(args.trace),
        "diagnostic_plot_sha256": artifacts,
        "metric_note": "Tilt is the angle between estimated and true body-frame gravity vectors and is invariant to world yaw. Bias error uses truth from the paired shared input. Attitude covariance plot shows the largest diagonal element on a log scale.",
    }
    (args.output_dir / "diagnostic_figures_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"PASS generated {len(artifacts)} diagnostic figures from {args.trace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
