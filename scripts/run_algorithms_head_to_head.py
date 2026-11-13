"""Run all installed causal 6D references on identical synthetic IMU trials.

The orchestrator uses separate pinned Python environments for VQF and RIANN,
while its current environment supplies qmt/OriEstIMU, the canonical filters,
and Matplotlib for figures. The --worker entry point is invoked once per
algorithm by the orchestrator.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from external_benchmarks.api import canonical_input_sha256, canonical_json_sha256, run_trial  # noqa: E402
from external_benchmarks.metrics import (  # noqa: E402
    geodesic_error_rad,
    gravity_tilt_error_rad,
    heading_rad,
    relative_heading_drift_rad,
    summarize_errors,
)

RATE_HZ = 100
GRAVITY = 9.80665
INTERVAL_NS = 10_000_000
REPORT_SCHEMA = "org.marcusfunt.algorithm_head_to_head_b1.v1"

VARIANTS = (
    "vqf",
    "oriestimu",
    "riann",
    "mahony_reference",
    "madgwick_reference",
    "mahony_internal_historical",
)
LABELS = {
    "vqf": "VQF 2.1.2",
    "oriestimu": "OriEstIMU 0.2.4",
    "riann": "RIANN 0.2.0†",
    "mahony_reference": "Mahony reference",
    "madgwick_reference": "Madgwick reference",
    "mahony_internal_historical": "Mahony internal historical",
}
COLORS = {
    "vqf": "#0072B2",
    "oriestimu": "#E69F00",
    "riann": "#009E73",
    "mahony_reference": "#CC79A7",
    "madgwick_reference": "#D55E00",
    "mahony_internal_historical": "#555555",
}


def _qmul(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, float, float, float]:
    w, x, y, z = left
    a, b, c, d = right
    return (
        w * a - x * b - y * c - z * d,
        w * b + x * a + y * d - z * c,
        w * c - x * d + y * a + z * b,
        w * d + x * c - y * b + z * a,
    )


def _qconj(q: tuple[float, ...]) -> tuple[float, float, float, float]:
    return q[0], -q[1], -q[2], -q[3]


def _rotate(q: tuple[float, ...], vector: tuple[float, float, float]) -> tuple[float, float, float]:
    rotated = _qmul(_qmul(q, (0.0, *vector)), _qconj(q))
    return rotated[1], rotated[2], rotated[3]


def _axis_quaternion(axis: tuple[float, float, float], angle: float) -> tuple[float, float, float, float]:
    magnitude = math.sqrt(math.fsum(value * value for value in axis))
    if magnitude == 0.0:
        return 1.0, 0.0, 0.0, 0.0
    scale = math.sin(angle / 2.0) / magnitude
    return math.cos(angle / 2.0), axis[0] * scale, axis[1] * scale, axis[2] * scale


def _specific_force(q_world_from_body: tuple[float, ...]) -> tuple[float, float, float]:
    # At rest the accelerometer measures world-up specific force expressed in body axes.
    return _rotate(_qconj(q_world_from_body), (0.0, 0.0, GRAVITY))


def _trial(trial_id: str, accel: list[tuple[float, float, float]], gyro: list[tuple[float, float, float]]) -> dict[str, Any]:
    if not accel or len(accel) != len(gyro):
        raise ValueError("synthetic fixture requires matching nonempty accelerometer and gyro arrays")
    samples = [
        {
            "timestamp": (index + 1) * INTERVAL_NS,
            "accel_mps2": [float(component) for component in accel[index]],
            "gyro_rad_s": [float(component) for component in gyro[index]],
            "valid": True,
        }
        for index in range(len(accel))
    ]
    source_bytes = json.dumps(samples, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": trial_id,
        "source_id": "all-algorithms-head-to-head-synthetic-v1",
        "source_artifact_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "sensor_set": "gyro_accel_6d",
        "timebase": {
            "timestamp_unit": "ns",
            "sampling_mode": "uniform",
            "nominal_rate_hz": {"numerator": RATE_HZ, "denominator": 1},
        },
        "frame_convention": {
            "body_frame": "sensor_body_right_handed",
            "world_frame": "ENU",
            "gravity_world_mps2": [0.0, 0.0, -GRAVITY],
            "accelerometer_quantity": "specific_force",
        },
        "units": {"timestamp": "ns", "accelerometer": "m/s^2", "gyroscope": "rad/s"},
        "sample_count": len(samples),
        "samples": samples,
    }


def _fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []

    count = 600
    q_static = _axis_quaternion((1.0, 0.0, 0.0), math.radians(25.0))
    fixtures.append(
        {
            "trial": _trial("static_25deg_roll", [_specific_force(q_static)] * count, [(0.0, 0.0, 0.0)] * count),
            "truth_wxyz": [list(q_static)] * count,
            "truth_note": "Constant 25 degree roll; identity startup yaw gauge; no sensor noise.",
        }
    )

    count = 800
    roll_rate = 0.45
    accels, gyros, truths = [], [], []
    for index in range(count):
        truth = _axis_quaternion((1.0, 0.0, 0.0), roll_rate * (index + 1) / RATE_HZ)
        truths.append(list(truth))
        accels.append(_specific_force(truth))
        gyros.append((roll_rate, 0.0, 0.0))
    fixtures.append(
        {
            "trial": _trial("constant_body_roll_0p45_rad_s", accels, gyros),
            "truth_wxyz": truths,
            "truth_note": "Analytic body-x rotation; gyro and gravity-consistent specific force are noise-free.",
        }
    )

    count = 1200
    q = (1.0, 0.0, 0.0, 0.0)
    accels, gyros, truths = [], [], []
    for index in range(count):
        t = (index + 1) / RATE_HZ
        omega = (0.16 * math.sin(0.7 * t), 0.12 * math.cos(0.45 * t), 0.10 + 0.06 * math.sin(0.3 * t))
        increment = _axis_quaternion(omega, math.sqrt(math.fsum(value * value for value in omega)) / RATE_HZ)
        q = _qmul(q, increment)
        truths.append(list(q))
        accels.append(_specific_force(q))
        gyros.append(omega)
    fixtures.append(
        {
            "trial": _trial("varying_three_axis_rotation", accels, gyros),
            "truth_wxyz": truths,
            "truth_note": "Analytic integrated three-axis body rate; ideal gyro and gravity-only specific force.",
        }
    )

    count = 1000
    fixtures.append(
        {
            "trial": _trial(
                "stationary_gyro_bias_0p08_rad_s",
                [(0.0, 0.0, GRAVITY)] * count,
                [(0.08, 0.0, 0.0)] * count,
            ),
            "truth_wxyz": [[1.0, 0.0, 0.0, 0.0]] * count,
            "truth_note": "Stationary identity attitude with a constant synthetic body-x gyro bias.",
        }
    )

    count = 800
    accels = []
    for index in range(count):
        lateral = 0.28 * GRAVITY if 200 <= index < 450 else 0.0
        accels.append((lateral, 0.0, GRAVITY))
    fixtures.append(
        {
            "trial": _trial("stationary_lateral_acceleration_pulse", accels, [(0.0, 0.0, 0.0)] * count),
            "truth_wxyz": [[1.0, 0.0, 0.0, 0.0]] * count,
            "truth_note": "Stationary identity attitude with a 0.28 g lateral acceleration pulse from 2.0 to 4.5 s.",
        }
    )
    return fixtures


def _adapter_and_config(key: str):
    rate = {"numerator": RATE_HZ, "denominator": 1}
    if key == "vqf":
        from external_benchmarks.adapters.vqf_full_6d import VQFFull6DAdapter

        return VQFFull6DAdapter(), {"sampling_rate_hz": rate, "timestamp_unit": "ns"}
    if key == "oriestimu":
        from external_benchmarks.adapters.qmt_oriestimu_6d import SeelOriEstIMU6DAdapter, default_config

        return SeelOriEstIMU6DAdapter(), default_config(sampling_rate_numerator=RATE_HZ)
    if key == "riann":
        from external_benchmarks.adapters.riann_pretrained_6d import RIANNPretrained6DAdapter, default_config

        return RIANNPretrained6DAdapter(), default_config(sampling_rate_numerator=RATE_HZ)
    from external_benchmarks.adapters.canonical_ahrs6d import (
        MadgwickReference6DAdapter,
        MahonyInternalHistoricalAdapter,
        MahonyReference6DAdapter,
        default_madgwick_config,
        default_mahony_config,
    )

    if key == "mahony_reference":
        return MahonyReference6DAdapter(), default_mahony_config()
    if key == "madgwick_reference":
        return MadgwickReference6DAdapter(), default_madgwick_config()
    if key == "mahony_internal_historical":
        return MahonyInternalHistoricalAdapter(), MahonyInternalHistoricalAdapter.default_config()
    raise ValueError(f"unknown variant key {key!r}")


def _worker(key: str, input_path: Path, output_path: Path) -> None:
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    adapter, config = _adapter_and_config(key)
    trial_results = []
    for trial in input_payload["trials"]:
        bundle = run_trial(adapter, trial, config)
        trial_results.append(
            {
                "trial_id": trial["trial_id"],
                "input_sha256": bundle["input_sha256"],
                "config_sha256": bundle["config_sha256"],
                "sample_count": bundle["sample_count"],
                "samples": bundle["samples"],
            }
        )
    result = {
        "variant_key": key,
        "adapter_manifest": adapter.manifest,
        "config": config,
        "runtime": {
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "vqf", "qmt", "riann", "onnxruntime", "matplotlib")
                if _has_package(name)
            },
        },
        "trials": trial_results,
    }
    output_path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _has_package(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _yaw_aligned_estimates(estimates: list[list[float]], truth: list[list[float]]) -> list[list[float]]:
    estimate_heading = heading_rad(estimates[0])
    truth_heading = heading_rad(truth[0])
    if estimate_heading is None or truth_heading is None:
        raise ValueError("cannot gauge-align heading at the first sample because it is singular")
    yaw_delta = truth_heading - estimate_heading
    yaw_rotation = (math.cos(yaw_delta / 2.0), 0.0, 0.0, math.sin(yaw_delta / 2.0))
    return [list(_qmul(yaw_rotation, tuple(q))) for q in estimates]


def _error_series(estimates: list[list[float]], truth: list[list[float]]) -> dict[str, list[float | None]]:
    aligned = _yaw_aligned_estimates(estimates, truth)
    tilt = [gravity_tilt_error_rad(estimate, target) for estimate, target in zip(estimates, truth)]
    geodesic = [geodesic_error_rad(estimate, target) for estimate, target in zip(aligned, truth)]
    heading = list(relative_heading_drift_rad(estimates, truth, alignment_index=0))
    return {"tilt_error_rad": tilt, "gauge_aligned_geodesic_error_rad": geodesic, "relative_heading_drift_rad": heading}


def _summary(values: list[float | None]) -> dict[str, Any]:
    result = summarize_errors(values)
    available = [abs(value) for value in values if value is not None]
    return {
        "available_sample_count": result.count,
        "rms_rad": result.rms,
        "p95_rad": result.p95,
        "maximum_rad": result.maximum,
        "final_rad": available[-1] if available else None,
    }


def _collect_results(fixtures: list[dict[str, Any]], worker_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_variant_trials = {
        key: {trial["trial_id"]: trial for trial in worker_outputs[key]["trials"]}
        for key in VARIANTS
    }
    trials = []
    for fixture in fixtures:
        trial = fixture["trial"]
        expected_hash = canonical_input_sha256(trial)
        results = []
        for key in VARIANTS:
            worker_trial = per_variant_trials[key][trial["trial_id"]]
            if worker_trial["input_sha256"] != expected_hash:
                raise RuntimeError(f"{key} received a different input stream for {trial['trial_id']}")
            if worker_trial["sample_count"] != trial["sample_count"] or len(worker_trial["samples"]) != trial["sample_count"]:
                raise RuntimeError(f"{key} returned a sample-count mismatch for {trial['trial_id']}")
            estimates = [sample["orientation"]["quaternion_wxyz"] for sample in worker_trial["samples"]]
            valid = [bool(sample["orientation_valid"]) for sample in worker_trial["samples"]]
            if not all(valid):
                raise RuntimeError(f"{key} returned invalid output on {trial['trial_id']}")
            truth = fixture["truth_wxyz"]
            errors = _error_series(estimates, truth)
            results.append(
                {
                    "variant_key": key,
                    "variant_id": worker_outputs[key]["adapter_manifest"]["variant_id"],
                    "label": LABELS[key],
                    "input_sha256": worker_trial["input_sha256"],
                    "config_sha256": worker_trial["config_sha256"],
                    "orientation_valid_sample_count": sum(valid),
                    "metrics": {name: _summary(values) for name, values in errors.items()},
                    "samples": {
                        "time_s": [(index + 1) / RATE_HZ for index in range(len(estimates))],
                        "estimated_quaternion_wxyz": estimates,
                        **errors,
                    },
                }
            )
        trials.append(
            {
                "trial_id": trial["trial_id"],
                "sample_count": trial["sample_count"],
                "sampling_rate_hz": RATE_HZ,
                "input_sha256": expected_hash,
                "truth_note": fixture["truth_note"],
                "results": results,
            }
        )
    algorithms = []
    for key in VARIANTS:
        manifest = worker_outputs[key]["adapter_manifest"]
        algorithms.append(
            {
                "variant_key": key,
                "label": LABELS[key],
                "variant_id": manifest["variant_id"],
                "adapter_id": manifest["adapter_id"],
                "implementation_version": manifest["implementation_version"],
                "source_fidelity": manifest["source_fidelity"],
                "training_exposure": "BROAD_USED_IN_DEVELOPMENT" if key == "riann" else None,
                "config": worker_outputs[key]["config"],
                "config_sha256": canonical_json_sha256(worker_outputs[key]["config"]),
                "runtime": worker_outputs[key]["runtime"],
            }
        )
    return {
        "report_schema": REPORT_SCHEMA,
        "title": "Causal six-axis algorithm head-to-head on deterministic synthetic streams",
        "evidence_class": "synthetic_development_only",
        "sampling_rate_hz": RATE_HZ,
        "sensor_set": "gyro_accel_6d",
        "aid_types": [],
        "units": {"time": "s", "accelerometer": "m/s^2 specific force", "gyroscope": "rad/s", "errors": "rad"},
        "methodology": {
            "same_input": "Each adapter receives the same B1 trial JSON; the input SHA-256 and sample count are checked before scoring.",
            "orientation_truth": "Analytic quaternions for synthetic fixtures; no recorded or BROAD trial data.",
            "tilt": "Gravity-axis angular error from B2; invariant to global yaw gauge.",
            "geodesic": "Quaternion geodesic after aligning each estimate's startup heading to truth at sample 0. This removes the unobservable 6D initial yaw gauge.",
            "heading": "B2 relative heading drift aligned at sample 0; no absolute yaw metric because no absolute heading aid is supplied.",
            "statistics": "Per-trial summaries only. Within-trial samples are correlated and are not treated as independent replicates; no population confidence interval is reported.",
            "parameters": "Each adapter uses its pinned documented defaults/versioned fixed configuration; no tuning on sealed trials.",
            "timing": "Runtime comparisons are omitted because adapters run in separate dependency environments.",
        },
        "algorithms": algorithms,
        "trial_count": len(trials),
        "total_samples_per_algorithm": sum(trial["sample_count"] for trial in trials),
        "trials": trials,
        "not_run": [
            {
                "algorithm": "production RP2350 ESKF",
                "status": "NOT_RUN",
                "reason": "No firmware-independent ESKF adapter is registered in the B1 benchmark API, and no C++ compiler is installed for the native PR3 runner.",
            }
        ],
    }


def _write_summary_csv(report: dict[str, Any], destination: Path) -> None:
    fields = (
        "trial_id",
        "variant_key",
        "variant_id",
        "input_sha256",
        "orientation_valid_sample_count",
        "tilt_rms_deg",
        "tilt_p95_deg",
        "tilt_max_deg",
        "geodesic_rms_deg",
        "geodesic_p95_deg",
        "heading_drift_max_deg",
    )
    with destination.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for trial in report["trials"]:
            for result in trial["results"]:
                tilt = result["metrics"]["tilt_error_rad"]
                geodesic = result["metrics"]["gauge_aligned_geodesic_error_rad"]
                heading = result["metrics"]["relative_heading_drift_rad"]
                to_degrees = lambda value: None if value is None else math.degrees(value)
                writer.writerow(
                    {
                        "trial_id": trial["trial_id"],
                        "variant_key": result["variant_key"],
                        "variant_id": result["variant_id"],
                        "input_sha256": result["input_sha256"],
                        "orientation_valid_sample_count": result["orientation_valid_sample_count"],
                        "tilt_rms_deg": to_degrees(tilt["rms_rad"]),
                        "tilt_p95_deg": to_degrees(tilt["p95_rad"]),
                        "tilt_max_deg": to_degrees(tilt["maximum_rad"]),
                        "geodesic_rms_deg": to_degrees(geodesic["rms_rad"]),
                        "geodesic_p95_deg": to_degrees(geodesic["p95_rad"]),
                        "heading_drift_max_deg": to_degrees(heading["maximum_rad"]),
                    }
                )


def _make_figures(report: dict[str, Any], output_dir: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    trials = report["trials"]
    subplot_count = len(trials)
    columns = 2
    rows = math.ceil(subplot_count / columns)
    figure_paths: list[str] = []

    for metric_name, title, ylabel, filename in (
        ("tilt_error_rad", "Gravity-axis tilt error", "Tilt error (degrees)", "head_to_head_tilt_error"),
        (
            "relative_heading_drift_rad",
            "Startup-yaw-aligned, wrapped heading drift",
            "Wrapped heading drift (degrees)",
            "head_to_head_heading_drift",
        ),
    ):
        fig = plt.figure(figsize=(18, 4.1 * rows))
        grid = fig.add_gridspec(rows, columns)
        axes = []
        for index in range(subplot_count):
            if index == subplot_count - 1 and subplot_count % columns:
                axes.append(fig.add_subplot(grid[index // columns, :]))
            else:
                axes.append(fig.add_subplot(grid[index // columns, index % columns]))
        for trial, ax in zip(trials, axes):
            for result in trial["results"]:
                values = result["samples"][metric_name]
                x = result["samples"]["time_s"]
                ax.plot(
                    x,
                    [np.nan if value is None else math.degrees(value) for value in values],
                    label=result["label"],
                    color=COLORS[result["variant_key"]],
                    linewidth=1.15,
                    alpha=0.9,
                )
            ax.set_title(trial["trial_id"].replace("_", " "))
            ax.set_xlabel("Time (s)")
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.25)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.suptitle(f"{title}: six causal 6D filters, identical 100 Hz synthetic inputs", fontsize=15, y=0.98)
        fig.tight_layout(rect=[0.02, 0.07, 0.78, 0.94])
        fig.legend(handles, labels, loc="center left", bbox_to_anchor=(0.80, 0.5), frameon=False)
        fig.text(
            0.5,
            0.015,
            "No magnetometer or heading aid. † RIANN pretrained model was developed with BROAD exposure. ESKF is not included.",
            ha="center",
            fontsize=9,
        )
        for extension in ("png", "svg"):
            path = figure_dir / f"{filename}.{extension}"
            fig.savefig(path, dpi=240, bbox_inches="tight")
            if extension == "svg":
                svg = path.read_text(encoding="utf-8")
                path.write_text("\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8")
            figure_paths.append(str(path.relative_to(output_dir)).replace("\\", "/"))
        plt.close(fig)

    metric_specs = (
        ("tilt_error_rad", "RMS tilt error (degrees)", "head_to_head_summary_tilt_rms"),
        ("gauge_aligned_geodesic_error_rad", "P95 gauge-aligned geodesic error (degrees)", "head_to_head_summary_geodesic_p95"),
    )
    short_trial_labels = ["Static\n25° roll", "Constant\nroll", "Varying\n3-axis", "Gyro\nbias", "Lateral\npulse"]
    for metric_name, title, filename in metric_specs:
        matrix = np.zeros((len(VARIANTS), len(trials)), dtype=float)
        for col, trial in enumerate(trials):
            for result in trial["results"]:
                row = VARIANTS.index(result["variant_key"])
                value = result["metrics"][metric_name]["rms_rad" if metric_name == "tilt_error_rad" else "p95_rad"]
                matrix[row, col] = math.degrees(value if value is not None else 0.0)
        fig, ax = plt.subplots(figsize=(12, 5.0))
        image = ax.imshow(matrix, aspect="auto", cmap="magma")
        ax.set_xticks(range(len(trials)), short_trial_labels)
        ax.set_yticks(range(len(VARIANTS)), [LABELS[key] for key in VARIANTS])
        ax.set_title(title)
        for row in range(matrix.shape[0]):
            for col in range(matrix.shape[1]):
                value = matrix[row, col]
                label = f"{value:.3f}" if 0.0 < value < 1.0 else f"{value:.2f}"
                ax.text(col, row, label, ha="center", va="center", color="white", fontsize=8)
        fig.colorbar(image, ax=ax, label="Degrees")
        fig.text(
            0.5,
            0.01,
            "Each cell summarizes one synthetic trial; values are not pooled across samples. † RIANN has BROAD training exposure.",
            ha="center",
            fontsize=9,
        )
        fig.tight_layout(rect=[0.01, 0.055, 0.98, 0.96])
        for extension in ("png", "svg"):
            path = figure_dir / f"{filename}.{extension}"
            fig.savefig(path, dpi=240, bbox_inches="tight")
            if extension == "svg":
                svg = path.read_text(encoding="utf-8")
                path.write_text("\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8")
            figure_paths.append(str(path.relative_to(output_dir)).replace("\\", "/"))
        plt.close(fig)
    return figure_paths


def _write_markdown_report(report: dict[str, Any], destination: Path) -> None:
    algorithm_headers = " | ".join(LABELS[key] for key in VARIANTS)
    header = f"| Trial | Samples | {algorithm_headers} |\n|---|---:|" + "---:|" * len(VARIANTS)
    rows = [header]
    for trial in report["trials"]:
        by_key = {result["variant_key"]: result for result in trial["results"]}
        values = [
            "N/A"
            if by_key[key]["metrics"]["tilt_error_rad"]["rms_rad"] is None
            else f"{math.degrees(by_key[key]['metrics']['tilt_error_rad']['rms_rad']):.3f}"
            for key in VARIANTS
        ]
        rows.append(f"| `{trial['trial_id']}` | {trial['sample_count']} | " + " | ".join(values) + " |")

    contents = [
        "# Synthetic algorithm head-to-head",
        "",
        f"Six causal 6D adapters processed five deterministic 100 Hz streams ({report['total_samples_per_algorithm']:,} samples per adapter). The same serialized input was replayed for each algorithm; each trial's input SHA-256 and sample count were checked before scoring.",
        "",
        "## Trial-level RMS gravity tilt error (degrees)",
        "",
        *rows,
        "",
        "These deterministic fixtures are development evidence. Per-sample outputs are correlated, so the table reports each trial separately without pooled confidence intervals.",
        "",
        "## Figures",
        "",
        "![Gravity-axis tilt error over time](figures/head_to_head_tilt_error.png)",
        "",
        "![Startup-yaw-aligned relative heading drift](figures/head_to_head_heading_drift.png)",
        "",
        "![Per-trial RMS gravity tilt error](figures/head_to_head_summary_tilt_rms.png)",
        "",
        "![Per-trial P95 gauge-aligned geodesic error](figures/head_to_head_summary_geodesic_p95.png)",
        "",
        "## Interpretation and limits",
        "",
        "- Tilt error is gravity-axis angular error. Geodesic error aligns each estimate's startup heading to the analytic truth at sample 0. Relative heading drift is startup-aligned and wrapped; absolute yaw is unobservable without an independent heading source.",
        "- RIANN is labeled `BROAD_USED_IN_DEVELOPMENT`; this run does not estimate its unseen-data generalization.",
        "- The historical internal Mahony implementation is labeled separately from canonical Mahony. VQF, OriEstIMU, RIANN, and canonical references use their pinned fixed configurations. No sealed trials were used for tuning.",
        "- The production RP2350 ESKF is not included: there is no registered firmware-independent ESKF adapter in the shared API, and the native PR3 C++ runner could not be built because a C++ compiler is unavailable.",
        "- No BROAD dataset score, sensor validation, hardware result, RP2350 resource or timing claim is made. Runtime comparisons are omitted because the algorithms ran in separate pinned dependency environments.",
        "",
        "## Reproduction",
        "",
        "Run the orchestrator from the qmt 0.2.4 environment (which includes Matplotlib), supplying the pinned VQF and RIANN Python environments:",
        "",
        "```powershell",
        "$pythonQmt = '<qmt-env>\\Scripts\\python.exe'",
        "$pythonVqf = '<vqf-env>\\Scripts\\python.exe'",
        "$pythonRiann = '<riann-env>\\Scripts\\python.exe'",
        "& $pythonQmt scripts/run_algorithms_head_to_head.py --runtime-python $pythonQmt --vqf-python $pythonVqf --riann-python $pythonRiann",
        "```",
        "",
        "The output JSON contains each versioned adapter identity, fixed config hash, runtime package versions, input hash, and per-trial metrics. The CSV contains one row per trial and adapter. The figures show per-sample traces generated during the run; rerun the command to reproduce the plotted series.",
    ]
    destination.write_text("\n".join(contents) + "\n", encoding="utf-8")


def _run_orchestrator(args: argparse.Namespace) -> int:
    fixtures = _fixtures()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_outputs: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="algorithm-head-to-head-") as temporary:
        temp = Path(temporary)
        input_path = temp / "shared_input_trials.json"
        input_path.write_text(
            json.dumps({"trials": [fixture["trial"] for fixture in fixtures]}, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        python_by_variant = {
            "vqf": str(args.vqf_python),
            "oriestimu": str(args.runtime_python),
            "riann": str(args.riann_python),
            "mahony_reference": str(args.runtime_python),
            "madgwick_reference": str(args.runtime_python),
            "mahony_internal_historical": str(args.runtime_python),
        }
        for key in VARIANTS:
            result_path = temp / f"{key}.json"
            command = [
                python_by_variant[key],
                str(Path(__file__).resolve()),
                "--worker",
                key,
                "--input",
                str(input_path),
                "--worker-output",
                str(result_path),
            ]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{key} worker failed with exit {completed.returncode}:\n{completed.stdout}\n{completed.stderr}"
                )
            worker_outputs[key] = json.loads(result_path.read_text(encoding="utf-8"))
            print(f"PASS worker {key}: {len(worker_outputs[key]['trials'])} trials")

    report = _collect_results(fixtures, worker_outputs)
    report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["figures"] = _make_figures(report, output_dir)
    json_path = output_dir / "algorithm_head_to_head_results.json"
    summary_report = {
        **report,
        "trials": [
            {
                **trial,
                "results": [{key: value for key, value in result.items() if key != "samples"} for result in trial["results"]],
            }
            for trial in report["trials"]
        ],
        "per_sample_outputs_persisted": False,
    }
    json_path.write_text(json.dumps(summary_report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    csv_path = output_dir / "algorithm_head_to_head_summary.csv"
    _write_summary_csv(report, csv_path)
    markdown_path = output_dir / "algorithm_head_to_head_report.md"
    _write_markdown_report(report, markdown_path)
    print(
        json.dumps(
            {
                "report": str(json_path),
                "summary_csv": str(csv_path),
                "markdown_report": str(markdown_path),
                "figure_count": len(report["figures"]),
                "trial_count": report["trial_count"],
                "total_samples_per_algorithm": report["total_samples_per_algorithm"],
                "all_input_hashes_identical": all(
                    len({result["input_sha256"] for result in trial["results"]}) == 1 for trial in report["trials"]
                ),
                "algorithms": [algorithm["variant_key"] for algorithm in report["algorithms"]],
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=VARIANTS)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--runtime-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--vqf-python", type=Path)
    parser.add_argument("--riann-python", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs/external_benchmarks/head_to_head_2026-11-13",
    )
    args = parser.parse_args()
    if args.worker:
        if args.input is None or args.worker_output is None:
            parser.error("--worker requires --input and --worker-output")
        _worker(args.worker, args.input, args.worker_output)
        return 0
    if args.vqf_python is None or args.riann_python is None:
        parser.error("orchestration requires --vqf-python and --riann-python")
    if not args.runtime_python.is_file() or not args.vqf_python.is_file() or not args.riann_python.is_file():
        parser.error("all supplied Python executable paths must exist")
    return _run_orchestrator(args)


if __name__ == "__main__":
    raise SystemExit(main())
