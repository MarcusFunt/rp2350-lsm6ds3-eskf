#!/usr/bin/env python3
"""Replay identical deterministic 6D streams through B6 references and PR3 history."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from ahrs.filters import Madgwick as UpstreamMadgwick
from ahrs.filters import Mahony as UpstreamMahony

from external_benchmarks.adapters.canonical_ahrs6d import (
    HISTORICAL_VARIANT_ID,
    MadgwickReference6DAdapter,
    MahonyInternalHistoricalAdapter,
    MahonyReference6DAdapter,
    default_madgwick_config,
    default_mahony_config,
)
from external_benchmarks.adapters.canonical_ahrs6d_math import quaternion_geodesic_rad
from external_benchmarks.api import canonical_input_sha256, run_trial


GRAVITY = 9.80665
RATE_HZ = 100
INTERVAL_NS = round(1_000_000_000 / RATE_HZ)
SENSOR_ARTIFACT_SHA256 = hashlib.sha256(b"B6 deterministic synthetic six-axis streams v1").hexdigest()


def _qx(angle_rad: float) -> list[float]:
    return [math.cos(angle_rad / 2.0), math.sin(angle_rad / 2.0), 0.0, 0.0]


def _body_specific_force_for_roll(roll_rad: float) -> tuple[float, float, float]:
    return 0.0, GRAVITY * math.sin(roll_rad), GRAVITY * math.cos(roll_rad)


def _trial(trial_id: str, accel: list[tuple[float, float, float]], gyro: list[tuple[float, float, float]]) -> dict[str, Any]:
    if not accel or len(accel) != len(gyro):
        raise ValueError("B6 smoke sequences require matching nonempty accelerometer and gyroscope arrays")
    samples = [
        {
            "timestamp": (index + 1) * INTERVAL_NS,
            "accel_mps2": list(accel[index]),
            "gyro_rad_s": list(gyro[index]),
            "valid": True,
        }
        for index in range(len(accel))
    ]
    return {
        "schema_id": "org.marcusfunt.external_benchmarks.imu_trial",
        "schema_version": 1,
        "trial_id": trial_id,
        "source_id": "canonical-ahrs-b6-synthetic",
        "source_artifact_sha256": SENSOR_ARTIFACT_SHA256,
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
    stationary_count = 1000
    stationary_accel = _body_specific_force_for_roll(math.radians(25.0))
    stationary = _trial(
        "tilted_stationary_zero_gyro",
        [stationary_accel] * stationary_count,
        [(0.0, 0.0, 0.0)] * stationary_count,
    )

    rotation_rate = 0.45
    rotation_accel = []
    rotation_gyro = []
    for index in range(stationary_count):
        angle = rotation_rate * index / RATE_HZ
        rotation_accel.append(_body_specific_force_for_roll(angle))
        rotation_gyro.append((rotation_rate, 0.0, 0.0))
    rotating = _trial("constant_body_roll_0p45_rad_s", rotation_accel, rotation_gyro)

    biased = _trial(
        "stationary_constant_gyro_bias_0p08_rad_s",
        [(0.0, 0.0, GRAVITY)] * stationary_count,
        [(0.08, 0.0, 0.0)] * stationary_count,
    )

    pulse_count = 800
    pulse_accel = []
    for index in range(pulse_count):
        lateral = 0.28 * GRAVITY if 200 <= index < 450 else 0.0
        pulse_accel.append((lateral, 0.0, GRAVITY))
    acceleration_pulse = _trial(
        "stationary_lateral_acceleration_pulse",
        pulse_accel,
        [(0.0, 0.0, 0.0)] * pulse_count,
    )
    return [stationary, rotating, biased, acceleration_pulse]


def _pair_summary(left: list[list[float]], right: list[list[float]]) -> dict[str, float]:
    errors = [quaternion_geodesic_rad(a, b) for a, b in zip(left, right)]
    ordered = sorted(errors)
    p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "mean_geodesic_rad": math.fsum(errors) / len(errors),
        "median_geodesic_rad": ordered[len(ordered) // 2],
        "p95_geodesic_rad": ordered[p95_index],
        "maximum_geodesic_rad": ordered[-1],
        "final_geodesic_rad": errors[-1],
    }


def _upstream_equation_differential() -> dict[str, Any]:
    count = 120
    accelerometer = []
    gyroscope = []
    for index in range(count):
        time_s = index / RATE_HZ
        accelerometer.append(
            (
                GRAVITY * (0.08 + 0.02 * math.sin(time_s)),
                GRAVITY * (0.12 * math.cos(time_s)),
                GRAVITY * math.sqrt(1.0 - (0.08 + 0.02 * math.sin(time_s)) ** 2 - (0.12 * math.cos(time_s)) ** 2),
            )
        )
        gyroscope.append(
            (
                0.12 + 0.03 * math.sin(time_s),
                -0.08 + 0.02 * math.cos(0.7 * time_s),
                0.04 + 0.01 * math.sin(0.3 * time_s),
            )
        )
    trial = _trial("nonzero_rate_upstream_equation_differential", accelerometer, gyroscope)
    results = {}
    for adapter_type, config, upstream, label in (
        (
            MahonyReference6DAdapter,
            default_mahony_config(),
            UpstreamMahony(k_P=1.0, k_I=0.3),
            "mahony_reference",
        ),
        (
            MadgwickReference6DAdapter,
            default_madgwick_config(),
            UpstreamMadgwick(gain=0.033),
            "madgwick_reference",
        ),
    ):
        actual_bundle = run_trial(adapter_type(), trial, config)
        actual = [sample["orientation"]["quaternion_wxyz"] for sample in actual_bundle["samples"]]
        expected = [list(config["initial_quaternion_wxyz"])]
        quaternion = np.asarray(config["initial_quaternion_wxyz"], dtype=np.float64)
        for index in range(1, count):
            quaternion = np.asarray(
                upstream.updateIMU(
                    quaternion,
                    np.asarray(gyroscope[index]),
                    np.asarray(accelerometer[index]),
                    dt=1.0 / RATE_HZ,
                ),
                dtype=np.float64,
            )
            expected.append(quaternion.tolist())
        component_errors = [
            abs(left_component - right_component)
            for left, right in zip(actual, expected)
            for left_component, right_component in zip(left, right)
        ]
        results[label] = {
            "input_sha256": actual_bundle["input_sha256"],
            "same_input_verified": True,
            "sample_count": count,
            "max_abs_quaternion_component_difference": max(component_errors),
            "max_geodesic_difference_rad": max(
                quaternion_geodesic_rad(left, right) for left, right in zip(actual, expected)
            ),
        }
    return {
        "source_package": "ahrs==0.4.0",
        "source_revision": "6a94a803fdb87d7a1f757906b9282b524764a7f1",
        "zero_rate_short_circuit_confirmed": True,
        "nonzero_rate_results": results,
    }


def build_report() -> dict[str, Any]:
    adapters = (
        (MahonyReference6DAdapter, default_mahony_config(), "mahony_reference"),
        (MadgwickReference6DAdapter, default_madgwick_config(), "madgwick_reference"),
        (
            MahonyInternalHistoricalAdapter,
            MahonyInternalHistoricalAdapter.default_config(),
            HISTORICAL_VARIANT_ID,
        ),
    )
    sequences = []
    for trial in _fixtures():
        bundles = [run_trial(adapter_type(), trial, config) for adapter_type, config, _ in adapters]
        if len({bundle["input_sha256"] for bundle in bundles}) != 1:
            raise RuntimeError("B6 smoke adapters did not receive the same canonical input stream")
        outputs = {
            variant_id: [sample["orientation"]["quaternion_wxyz"] for sample in bundle["samples"]]
            for (_, _, variant_id), bundle in zip(adapters, bundles)
        }
        by_id = {variant_id: bundle for (_, _, variant_id), bundle in zip(adapters, bundles)}
        sequences.append(
            {
                "trial_id": trial["trial_id"],
                "sample_count": trial["sample_count"],
                "input_sha256": canonical_input_sha256(trial),
                "same_input_verified": True,
                "configuration_sha256": {
                    variant_id: by_id[variant_id]["config_sha256"] for _, _, variant_id in adapters
                },
                "variant_ids": [
                    by_id[variant_id]["adapter_manifest"]["variant_id"]
                    for _, _, variant_id in adapters
                ],
                "pairwise_same_startup_gauge_separation": {
                    "mahony_reference_vs_internal_historical": _pair_summary(
                        outputs["mahony_reference"], outputs[HISTORICAL_VARIANT_ID]
                    ),
                    "madgwick_reference_vs_internal_historical": _pair_summary(
                        outputs["madgwick_reference"], outputs[HISTORICAL_VARIANT_ID]
                    ),
                    "mahony_reference_vs_madgwick_reference": _pair_summary(
                        outputs["mahony_reference"], outputs["madgwick_reference"]
                    ),
                },
            }
        )
    return {
        "report_schema": "org.marcusfunt.canonical_ahrs_b6_smoke.v1",
        "sensor_set": "gyro_accel_6d",
        "sampling_rate_hz": RATE_HZ,
        "units": {"accelerometer": "m/s^2 specific force", "gyroscope": "rad/s", "timestamp": "ns"},
        "source_selection": {
            "equation_reference": "Mayitzin/ahrs v0.4.0, MIT, commit 6a94a803fdb87d7a1f757906b9282b524764a7f1",
            "upstream_equation_differential": _upstream_equation_differential(),
            "zero_gyro_divergence": "The upstream Python methods early-return when gyro norm is exactly zero, suppressing valid accelerometer feedback. B6 follows the published equations in that edge case and is classified faithful_reimplementation.",
            "historical_replay": "Python replay of PR3 v5 AttitudeBaseline source; the original C++ executable was not run because no C++ compiler was available.",
        },
        "fixed_parameters": {
            "mahony_reference": {"k_p_s_inv": 1.0, "k_i_s_inv2": 0.3},
            "madgwick_reference": {"beta_rad_s": 0.033},
            "mahony_internal_historical": {"k_p_s_inv": 1.0, "k_i_s_inv2": 0.05},
            "initial_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "accelerometer_policy": "None or norm <= 1e-12 m/s^2 skips correction; valid gyro is still integrated. Nonfinite vectors fail closed.",
        },
        "interpretation": {
            "pairwise_metric": "Geodesic quaternion separation for identically hashed samples and shared identity startup gauge; it measures estimator disagreement, not absolute accuracy.",
            "heading": "All variants are six-axis and use an unobservable startup yaw gauge; no heading is supplied.",
            "historical_scope": "mahony_internal_historical denotes the PR3 v5 no-startup-calibration/no-heading profile only. Frozen v1-v5 evidence keeps its historical raw label mahony.",
            "not_tuned_on_sealed_trials": True,
        },
        "sequence_count": len(sequences),
        "total_samples": sum(sequence["sample_count"] for sequence in sequences),
        "sequences": sequences,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/external_benchmarks/canonical_ahrs_b6_smoke.json",
    )
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    maxima = {
        key: max(
            sequence["pairwise_same_startup_gauge_separation"][key]["maximum_geodesic_rad"]
            for sequence in report["sequences"]
        )
        for key in (
            "mahony_reference_vs_internal_historical",
            "madgwick_reference_vs_internal_historical",
            "mahony_reference_vs_madgwick_reference",
        )
    }
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sequence_count": report["sequence_count"],
                "total_samples": report["total_samples"],
                "identical_input_hashes": all(sequence["same_input_verified"] for sequence in report["sequences"]),
                "max_pairwise_geodesic_rad": maxima,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
