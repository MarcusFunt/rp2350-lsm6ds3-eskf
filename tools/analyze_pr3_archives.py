#!/usr/bin/env python3
"""Read-only, trial-level analysis of the frozen PR3 v5 CSV archives."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


ANALYSIS_VERSION = 1
SOURCE_COMMIT = "02c61fe7c4b93d591b042c69b08cfe20a6277722"
PROTOCOL_SHA256 = "1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800"
CSV_COLUMNS = tuple(
    "protocol_version protocol_sha256 input_sha256 config_sha256 commit_sha "
    "scenario rate_mode stress_mode seed_split seed sensor_input startup_knowledge "
    "startup_gyro_bias_calibration runtime_aid estimator expected produced valid "
    "missing unavailable unavailable_duration_s recovery_time_s recovery_time_reason "
    "stale control_valid covariance_valid faults resets rejected aid_accepted aid_rejected "
    "availability tilt_rms_deg tilt_p95_deg tilt_max_deg attitude_rms_deg yaw_rms_deg "
    "position_rms_m velocity_rms_m_s accel_bias_error_m_s2 gyro_bias_error_rad_s "
    "tilt_nees_mean tilt_nees_count tilt_nees_coverage95 nis_mean nis_count "
    "max_state_age_us health_end complete_run covariance_applicable navigation_applicable "
    "pr2_gate_status".split()
)

GROUP_FIELDS = (
    "split",
    "scenario",
    "rate_mode",
    "stress_mode",
    "estimator",
    "sensor_input",
    "startup_knowledge",
    "startup_gyro_bias_calibration",
    "runtime_aid",
)
PROFILE_FIELDS = (
    "sensor_input",
    "startup_knowledge",
    "startup_gyro_bias_calibration",
    "runtime_aid",
)
STREAM_FIELDS = ("scenario", "rate_mode", "stress_mode", "seed")
ESKF_ESTIMATORS = (
    "eskf_conservative",
    "eskf_legacy",
    "eskf_confirmed_only",
)
ESTIMATORS = (*ESKF_ESTIMATORS, "mahony", "gyro_only")
SCENARIOS = (
    "static",
    "slow_yaw",
    "lateral_accel",
    "maneuver",
    "vibration",
    "timing_jitter",
    "stop_start",
    "compound_motion",
)
RATE_MODES = ("uniform_200hz", "uniform_208hz", "irregular_208hz")
STRESS_MODES = ("nominal", "stress")
EXPECTED_PROFILES = (
    ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", "OFF", "NONE"),
    ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", "ON", "NONE"),
    ("IMU_ONLY", "TRUTH_ORACLE_STATIC", "OFF", "NONE"),
    ("IMU_ONLY", "UNKNOWN", "OFF", "NONE"),
    (
        "IMU_WITH_SYNTHETIC_HEADING",
        "EXTERNALLY_VERIFIED_STATIC",
        "ON",
        "INDEPENDENT_MEASUREMENT",
    ),
    (
        "IMU_WITH_SYNTHETIC_HEADING",
        "EXTERNALLY_VERIFIED_STATIC",
        "ON",
        "SIMULATOR_ORACLE",
    ),
    ("IMU_WITH_SYNTHETIC_HEADING", "UNKNOWN", "OFF", "NONE"),
)
SPLITS = (
    ("development", "dev100", 4001, 4100),
    ("held_out", "heldout100", 9001, 9100),
    ("final_confirmation", "final100", 10001, 10100),
)

# Published in remediation/PR3_STATUS.md as simple per-trial means across the
# complete v5 factor matrix and all three historical splits.
PUBLISHED_FACTOR_MEANS = {
    ("eskf_conservative", "nominal"): 1.2814,
    ("eskf_conservative", "stress"): 2.9517,
    ("eskf_legacy", "nominal"): 2.5128,
    ("eskf_legacy", "stress"): 2.9824,
    ("eskf_confirmed_only", "nominal"): 2.1981,
    ("eskf_confirmed_only", "stress"): 2.9615,
    ("mahony", "nominal"): 2.4479,
    ("mahony", "stress"): 2.4486,
    ("gyro_only", "nominal"): 2.7848,
    ("gyro_only", "stress"): 2.8759,
}

OUTPUT_COLUMNS = (
    *GROUP_FIELDS,
    "source_archive_sha256",
    "trial_count",
    "tilt_rms_finite_trials",
    "tilt_rms_mean_deg",
    "tilt_rms_median_deg",
    "tilt_rms_p90_deg",
    "tilt_rms_p95_deg",
    "tilt_rms_worst_deg",
    "yaw_rms_finite_trials",
    "yaw_rms_mean_deg",
    "yaw_rms_median_deg",
    "yaw_rms_p95_deg",
    "yaw_rms_worst_deg",
    "relative_heading_rms_mean_deg",
    "relative_heading_rms_median_deg",
    "relative_heading_rms_p95_deg",
    "relative_heading_rms_worst_deg",
    "yaw_metric_interpretation",
    "mean_availability",
    "minimum_availability",
    "complete_trials",
    "incomplete_trials",
    "covariance_applicable",
    "mean_covariance_valid_checks_per_trial",
    "mean_covariance_check_fraction",
    "mean_recovery_time_s",
    "recovery_time_trials",
    "not_recovered_trials",
    "accel_bias_error_trials",
    "mean_accel_bias_error_m_s2",
    "gyro_bias_error_trials",
    "mean_gyro_bias_error_rad_s",
    "tilt_nees_trials",
    "mean_tilt_nees_per_trial",
    "mean_tilt_nees_coverage95",
    "mean_tilt_nees_sample_count_per_trial",
    "nis_trials",
    "mean_nis_per_trial",
    "mean_nis_count_per_trial",
    "paired_mahony_trials",
    "paired_tilt_trials",
    "paired_tilt_mean_delta_deg",
    "paired_tilt_median_delta_deg",
    "paired_tilt_p95_delta_deg",
    "paired_tilt_worst_delta_deg",
    "paired_yaw_mean_delta_deg",
)


class AnalysisError(ValueError):
    """Raised when an archive violates the locked PR3 v5 row/pairing contract."""


@dataclass(frozen=True)
class Trial:
    split: str
    scenario: str
    rate_mode: str
    stress_mode: str
    seed: int
    profile: tuple[str, str, str, str]
    estimator: str
    input_sha256: str
    metrics: Mapping[str, float | None]
    counts: Mapping[str, int]
    flags: Mapping[str, bool]
    recovery_time_s: float | None
    recovery_time_reason: str

    @property
    def stream_key(self) -> tuple[str, str, str, int]:
        return (self.scenario, self.rate_mode, self.stress_mode, self.seed)

    @property
    def base_group_key(self) -> tuple[str, ...]:
        return (
            self.split,
            self.scenario,
            self.rate_mode,
            self.stress_mode,
            *self.profile,
        )

    @property
    def group_key(self) -> tuple[str, ...]:
        return (
            self.split,
            self.scenario,
            self.rate_mode,
            self.stress_mode,
            self.estimator,
            *self.profile,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_canonical_text(path: Path) -> str:
    """Hash text after universal-newline normalization for cross-platform stability."""
    canonical = path.read_text(encoding="utf-8").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def iter_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield strict PR3 v5 CSV rows; reject both short and long records."""
    try:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise AnalysisError(f"{path}: compressed CSV is empty") from exc
            if len(header) != len(set(header)) or tuple(header) != CSV_COLUMNS:
                raise AnalysisError(f"{path}: wrong CSV shape or unsupported v5 header")
            for line_number, values in enumerate(reader, start=2):
                if len(values) != len(CSV_COLUMNS):
                    raise AnalysisError(
                        f"{path}:{line_number}: wrong column count {len(values)}; "
                        f"expected {len(CSV_COLUMNS)}"
                    )
                yield dict(zip(CSV_COLUMNS, values))
    except AnalysisError:
        raise
    except (OSError, EOFError, UnicodeDecodeError, csv.Error) as exc:
        raise AnalysisError(f"{path}: cannot read gzip CSV: {exc}") from exc


def _required_text(row: Mapping[str, str], field: str, line: int) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise AnalysisError(f"row {line}: missing key/value {field}")
    return value


def _integer(row: Mapping[str, str], field: str, line: int) -> int:
    value = _required_text(row, field, line)
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise AnalysisError(f"row {line}: invalid integer {field}={value!r}") from exc
    if parsed < 0:
        raise AnalysisError(f"row {line}: negative count {field}={parsed}")
    return parsed


def _optional_number(row: Mapping[str, str], field: str, line: int) -> float | None:
    value = row.get(field, "").strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise AnalysisError(f"row {line}: invalid numeric value {field}={value!r}") from exc
    if not math.isfinite(parsed):
        raise AnalysisError(f"row {line}: non-finite numeric value in {field}={value!r}")
    return parsed


def _boolean(row: Mapping[str, str], field: str, line: int) -> bool:
    value = _required_text(row, field, line).lower()
    if value not in ("true", "false"):
        raise AnalysisError(f"row {line}: invalid boolean {field}={value!r}")
    return value == "true"


def parse_trial(row: Mapping[str, str], split: str, line: int = 0) -> Trial:
    """Validate and normalize one archived per-seed summary row."""
    line = line or 1
    if set(row) != set(CSV_COLUMNS):
        raise AnalysisError(f"row {line}: wrong CSV shape or missing columns")
    if _integer(row, "protocol_version", line) != 5:
        raise AnalysisError(f"row {line}: expected protocol_version=5")
    if _required_text(row, "protocol_sha256", line).lower() != PROTOCOL_SHA256:
        raise AnalysisError(f"row {line}: protocol SHA-256 mismatch")
    if _required_text(row, "commit_sha", line).lower() != SOURCE_COMMIT:
        raise AnalysisError(f"row {line}: frozen source commit mismatch")
    if _required_text(row, "seed_split", line) != split:
        raise AnalysisError(f"row {line}: seed_split does not match archive split {split}")

    input_sha256 = _required_text(row, "input_sha256", line).lower()
    config_sha256 = _required_text(row, "config_sha256", line).lower()
    for field, value in (("input_sha256", input_sha256), ("config_sha256", config_sha256)):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise AnalysisError(f"row {line}: invalid SHA-256 in {field}")

    scenario = _required_text(row, "scenario", line)
    rate_mode = _required_text(row, "rate_mode", line)
    stress_mode = _required_text(row, "stress_mode", line)
    seed = _integer(row, "seed", line)
    if scenario not in SCENARIOS or rate_mode not in RATE_MODES or stress_mode not in STRESS_MODES:
        raise AnalysisError(f"row {line}: unexpected scenario/rate/stress key")

    profile = tuple(_required_text(row, field, line) for field in PROFILE_FIELDS)
    if len(profile) != 4:
        raise AnalysisError(f"row {line}: invalid profile key")
    estimator = _required_text(row, "estimator", line)
    if estimator not in ESTIMATORS:
        raise AnalysisError(f"row {line}: unexpected estimator {estimator!r}")

    counts = {
        field: _integer(row, field, line)
        for field in (
            "expected",
            "produced",
            "valid",
            "missing",
            "unavailable",
            "control_valid",
            "covariance_valid",
            "faults",
            "resets",
            "rejected",
            "aid_accepted",
            "aid_rejected",
            "stale",
            "tilt_nees_count",
            "nis_count",
            "max_state_age_us",
        )
    }
    if counts["expected"] <= 0:
        raise AnalysisError(f"row {line}: expected sample count must be positive")
    if any(counts[field] > counts["expected"] for field in ("produced", "valid", "control_valid")):
        raise AnalysisError(f"row {line}: sample count exceeds expected denominator")

    metrics = {
        field: _optional_number(row, field, line)
        for field in (
            "unavailable_duration_s",
            "availability",
            "tilt_rms_deg",
            "tilt_p95_deg",
            "tilt_max_deg",
            "attitude_rms_deg",
            "yaw_rms_deg",
            "position_rms_m",
            "velocity_rms_m_s",
            "accel_bias_error_m_s2",
            "gyro_bias_error_rad_s",
            "tilt_nees_mean",
            "tilt_nees_coverage95",
            "nis_mean",
        )
    }
    availability = metrics["availability"]
    if availability is None or not 0.0 <= availability <= 1.0:
        raise AnalysisError(f"row {line}: availability must be finite and in [0, 1]")
    expected_availability = counts["valid"] / counts["expected"]
    if not math.isclose(availability, expected_availability, abs_tol=1e-7, rel_tol=0.0):
        raise AnalysisError(f"row {line}: availability does not equal valid/expected")
    nees_coverage = metrics["tilt_nees_coverage95"]
    if nees_coverage is not None and not 0.0 <= nees_coverage <= 1.0:
        raise AnalysisError(f"row {line}: tilt NEES coverage must be in [0, 1]")

    flags = {
        field: _boolean(row, field, line)
        for field in ("complete_run", "covariance_applicable", "navigation_applicable")
    }
    recovery_time_s = _optional_number(row, "recovery_time_s", line)
    recovery_reason = row.get("recovery_time_reason", "").strip()
    if not recovery_reason:
        raise AnalysisError(f"row {line}: missing recovery_time_reason")
    if recovery_time_s is not None and recovery_time_s < 0.0:
        raise AnalysisError(f"row {line}: recovery time cannot be negative")

    return Trial(
        split=split,
        scenario=scenario,
        rate_mode=rate_mode,
        stress_mode=stress_mode,
        seed=seed,
        profile=profile,  # type: ignore[arg-type]
        estimator=estimator,
        input_sha256=input_sha256,
        metrics=metrics,
        counts=counts,
        flags=flags,
        recovery_time_s=recovery_time_s,
        recovery_time_reason=recovery_reason,
    )


def empirical_quantile(values: Sequence[float], q: float) -> float | None:
    """Use the frozen PR3 summary's lower order-statistic convention."""
    if not values:
        return None
    return sorted(values)[int(q * (len(values) - 1))]


def trial_weighted_mean(value_groups: Iterable[Iterable[float | None]]) -> float | None:
    """Average trial observations; group/sample sizes never become pseudo-n."""
    values = [value for group in value_groups for value in group if value is not None]
    return statistics.fmean(values) if values else None


def _metric_stats(values: Sequence[float | None], *, p90: bool = False) -> dict[str, float | int | None]:
    finite = [value for value in values if value is not None]
    result: dict[str, float | int | None] = {
        "n": len(finite),
        "mean": statistics.fmean(finite) if finite else None,
        "median": empirical_quantile(finite, 0.50),
        "p95": empirical_quantile(finite, 0.95),
        "worst": max(finite) if finite else None,
    }
    if p90:
        result["p90"] = empirical_quantile(finite, 0.90)
    return result


def _profile_from_row(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    return tuple(row.get(field, "").strip() for field in PROFILE_FIELDS)  # type: ignore[return-value]


def _pair_fields(row: Trial | Mapping[str, str]) -> tuple:
    if isinstance(row, Trial):
        return (
            row.split,
            row.scenario,
            row.rate_mode,
            row.stress_mode,
            row.seed,
            row.profile,
            row.estimator,
            row.input_sha256,
            row.metrics.get("tilt_rms_deg"),
            row.metrics.get("yaw_rms_deg"),
            row.metrics.get("availability"),
        )
    return (
        row.get("seed_split", ""),
        row.get("scenario", ""),
        row.get("rate_mode", ""),
        row.get("stress_mode", ""),
        int(row.get("seed", "0")),
        _profile_from_row(row),
        row.get("estimator", ""),
        row.get("input_sha256", "").lower(),
        _optional_number(row, "tilt_rms_deg", 0),
        _optional_number(row, "yaw_rms_deg", 0),
        _optional_number(row, "availability", 0),
    )


def pair_trial_rows(rows: Iterable[Trial | Mapping[str, str]]) -> dict[str, list[dict[str, float | int | str | None]]]:
    """Pair each ESKF policy with internal Mahony on identical trial keys."""
    indexed: dict[tuple[str, int], tuple] = {}
    profiles = set()
    contexts = set()
    for row in rows:
        (split, scenario, rate, stress, seed, profile, estimator, input_sha, tilt, yaw, availability) = _pair_fields(row)
        profiles.add(profile)
        contexts.add((split, scenario, rate, stress))
        key = (estimator, seed)
        if key in indexed:
            raise AnalysisError(f"duplicate trial key while pairing {key}")
        indexed[key] = (input_sha, tilt, yaw, availability)
    if len(profiles) > 1 or len(contexts) > 1:
        raise AnalysisError("incompatible profile pairing across estimator trials")

    paired: dict[str, list[dict[str, float | int | str | None]]] = {
        estimator: [] for estimator in ESKF_ESTIMATORS
    }
    for estimator in ESKF_ESTIMATORS:
        for (model, seed), (input_sha, tilt, yaw, availability) in indexed.items():
            if model != estimator:
                continue
            mahony = indexed.get(("mahony", seed))
            if mahony is None:
                raise AnalysisError(f"missing Mahony paired trial for {estimator}, seed {seed}")
            mahony_sha, mahony_tilt, mahony_yaw, mahony_availability = mahony
            if input_sha != mahony_sha:
                raise AnalysisError(f"input SHA mismatch in {estimator}/Mahony pair, seed {seed}")
            paired[estimator].append(
                {
                    "seed": seed,
                    "input_sha256": input_sha,
                    "tilt_delta_deg": None if tilt is None or mahony_tilt is None else tilt - mahony_tilt,
                    "yaw_delta_deg": None if yaw is None or mahony_yaw is None else yaw - mahony_yaw,
                    "availability_delta": (
                        None if availability is None or mahony_availability is None
                        else availability - mahony_availability
                    ),
                }
            )
    return paired


def _group_record(
    key: tuple[str, ...],
    trials: Sequence[Trial],
    archive_sha256: str,
    paired: Sequence[dict[str, float | int | str | None]] | None,
) -> dict[str, str | int | float | bool | None]:
    record: dict[str, str | int | float | bool | None] = dict(zip(GROUP_FIELDS, key))
    record["source_archive_sha256"] = archive_sha256
    record["trial_count"] = len(trials)
    tilt = _metric_stats([trial.metrics["tilt_rms_deg"] for trial in trials], p90=True)
    yaw = _metric_stats([trial.metrics["yaw_rms_deg"] for trial in trials])
    for name, stats in (("tilt_rms", tilt), ("yaw_rms", yaw)):
        record[f"{name}_finite_trials"] = stats["n"]
        record[f"{name}_mean_deg"] = stats["mean"]
        record[f"{name}_median_deg"] = stats["median"]
        record[f"{name}_p95_deg"] = stats["p95"]
        record[f"{name}_worst_deg"] = stats["worst"]
        if name == "tilt_rms":
            record["tilt_rms_p90_deg"] = stats["p90"]

    sensor_input, _startup, _calibration, runtime_aid = key[5:9]
    if runtime_aid == "NONE":
        record["yaw_metric_interpretation"] = (
            "relative heading RMS from shared zero-yaw startup gauge; not absolute north"
        )
        record["relative_heading_rms_mean_deg"] = yaw["mean"]
        record["relative_heading_rms_median_deg"] = yaw["median"]
        record["relative_heading_rms_p95_deg"] = yaw["p95"]
        record["relative_heading_rms_worst_deg"] = yaw["worst"]
    elif runtime_aid == "INDEPENDENT_MEASUREMENT":
        record["yaw_metric_interpretation"] = (
            "yaw RMS against synthetic independent heading truth; not physical north"
        )
        record["relative_heading_rms_mean_deg"] = None
        record["relative_heading_rms_median_deg"] = None
        record["relative_heading_rms_p95_deg"] = None
        record["relative_heading_rms_worst_deg"] = None
    else:
        record["yaw_metric_interpretation"] = (
            "yaw RMS against simulator-oracle heading; oracle case, not sensor performance"
        )
        record["relative_heading_rms_mean_deg"] = None
        record["relative_heading_rms_median_deg"] = None
        record["relative_heading_rms_p95_deg"] = None
        record["relative_heading_rms_worst_deg"] = None

    availability = [trial.metrics["availability"] for trial in trials]
    record["mean_availability"] = statistics.fmean(v for v in availability if v is not None)
    record["minimum_availability"] = min(v for v in availability if v is not None)
    incomplete = [
        trial for trial in trials
        if (
            not trial.flags["complete_run"]
            or trial.counts["missing"] > 0
            or trial.counts["unavailable"] > 0
            or trial.counts["produced"] != trial.counts["expected"]
            or trial.counts["valid"] != trial.counts["expected"]
        )
    ]
    record["complete_trials"] = len(trials) - len(incomplete)
    record["incomplete_trials"] = len(incomplete)

    covariance_applicable = all(trial.flags["covariance_applicable"] for trial in trials)
    if any(trial.flags["covariance_applicable"] != covariance_applicable for trial in trials):
        raise AnalysisError(f"mixed covariance applicability in group {key}")
    record["covariance_applicable"] = covariance_applicable
    if covariance_applicable:
        record["mean_covariance_valid_checks_per_trial"] = statistics.fmean(
            trial.counts["covariance_valid"] for trial in trials
        )
        denominator = sum(trial.counts["expected"] for trial in trials)
        record["mean_covariance_check_fraction"] = (
            sum(trial.counts["covariance_valid"] for trial in trials) / denominator
        )
    else:
        record["mean_covariance_valid_checks_per_trial"] = None
        record["mean_covariance_check_fraction"] = None

    recoveries = [trial.recovery_time_s for trial in trials if trial.recovery_time_s is not None]
    record["mean_recovery_time_s"] = statistics.fmean(recoveries) if recoveries else None
    record["recovery_time_trials"] = len(recoveries)
    record["not_recovered_trials"] = sum(
        trial.recovery_time_reason == "not_recovered_by_end" for trial in trials
    )

    accel_bias = _metric_stats([trial.metrics["accel_bias_error_m_s2"] for trial in trials])
    gyro_bias = _metric_stats([trial.metrics["gyro_bias_error_rad_s"] for trial in trials])
    record["accel_bias_error_trials"] = accel_bias["n"]
    record["mean_accel_bias_error_m_s2"] = accel_bias["mean"]
    record["gyro_bias_error_trials"] = gyro_bias["n"]
    record["mean_gyro_bias_error_rad_s"] = gyro_bias["mean"]

    nees = _metric_stats([trial.metrics["tilt_nees_mean"] for trial in trials])
    nees_coverage = _metric_stats([trial.metrics["tilt_nees_coverage95"] for trial in trials])
    nis = _metric_stats([trial.metrics["nis_mean"] for trial in trials])
    record["tilt_nees_trials"] = nees["n"]
    record["mean_tilt_nees_per_trial"] = nees["mean"]
    record["mean_tilt_nees_coverage95"] = nees_coverage["mean"]
    record["mean_tilt_nees_sample_count_per_trial"] = (
        statistics.fmean(trial.counts["tilt_nees_count"] for trial in trials)
        if covariance_applicable else None
    )
    record["nis_trials"] = nis["n"]
    record["mean_nis_per_trial"] = nis["mean"]
    record["mean_nis_count_per_trial"] = (
        statistics.fmean(trial.counts["nis_count"] for trial in trials) if nis["n"] else None
    )

    if paired is None:
        record.update(
            {
                "paired_mahony_trials": None,
                "paired_tilt_trials": None,
                "paired_tilt_mean_delta_deg": None,
                "paired_tilt_median_delta_deg": None,
                "paired_tilt_p95_delta_deg": None,
                "paired_tilt_worst_delta_deg": None,
                "paired_yaw_mean_delta_deg": None,
            }
        )
    else:
        tilt_deltas = [item["tilt_delta_deg"] for item in paired if item["tilt_delta_deg"] is not None]
        yaw_deltas = [item["yaw_delta_deg"] for item in paired if item["yaw_delta_deg"] is not None]
        record["paired_mahony_trials"] = len(paired)
        record["paired_tilt_trials"] = len(tilt_deltas)
        record["paired_tilt_mean_delta_deg"] = statistics.fmean(tilt_deltas) if tilt_deltas else None
        record["paired_tilt_median_delta_deg"] = empirical_quantile(tilt_deltas, 0.5)
        record["paired_tilt_p95_delta_deg"] = empirical_quantile(tilt_deltas, 0.95)
        record["paired_tilt_worst_delta_deg"] = max(tilt_deltas) if tilt_deltas else None
        record["paired_yaw_mean_delta_deg"] = statistics.fmean(yaw_deltas) if yaw_deltas else None
    return record


def analyze_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    split: str,
    archive_sha256: str,
    expected_profiles: set[tuple[str, str, str, str]] | None = None,
    expected_stream_keys: set[tuple[str, str, str, int]] | None = None,
    expected_trials_per_group: int = 100,
) -> dict[str, object]:
    """Analyze rows as independent per-seed trials and enforce complete pairing."""
    if not re.fullmatch(r"[0-9a-f]{64}", archive_sha256.lower()):
        raise AnalysisError("archive SHA-256 must be 64 lowercase hexadecimal characters")
    allowed_profiles = set(EXPECTED_PROFILES if expected_profiles is None else expected_profiles)
    if expected_trials_per_group <= 0:
        raise AnalysisError("expected_trials_per_group must be positive")

    grouped: dict[tuple[str, ...], list[Trial]] = defaultdict(list)
    by_base_group: dict[tuple[str, ...], list[Trial]] = defaultdict(list)
    seen_trial_keys: set[tuple[tuple[str, ...], int]] = set()
    stream_hashes: dict[tuple[str, str, str, int], str] = {}
    stream_profiles: dict[tuple[str, str, str, int], set[tuple[str, ...]]] = defaultdict(set)
    stream_estimators: dict[
        tuple[tuple[str, str, str, int], tuple[str, ...]], set[str]
    ] = defaultdict(set)
    factor_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    stream_keys_seen: set[tuple[str, str, str, int]] = set()

    for line, row in enumerate(rows, start=2):
        trial = parse_trial(row, split, line)
        stream_key = trial.stream_key
        stream_keys_seen.add(stream_key)
        if expected_stream_keys is not None and stream_key not in expected_stream_keys:
            raise AnalysisError(f"unexpected stream key {stream_key}")
        old_hash = stream_hashes.setdefault(stream_key, trial.input_sha256)
        if old_hash != trial.input_sha256:
            raise AnalysisError(f"input SHA mismatch across estimators/profiles for stream {stream_key}")
        stream_profiles[stream_key].add(trial.profile)
        stream_estimators[(stream_key, trial.profile)].add(trial.estimator)

        duplicate_key = (trial.group_key, trial.seed)
        if duplicate_key in seen_trial_keys:
            raise AnalysisError(f"duplicate trial key {duplicate_key}")
        seen_trial_keys.add(duplicate_key)
        grouped[trial.group_key].append(trial)
        by_base_group[trial.base_group_key].append(trial)
        tilt = trial.metrics["tilt_rms_deg"]
        if tilt is not None:
            factor_values[(trial.estimator, trial.stress_mode)].append(tilt)

    if not seen_trial_keys:
        raise AnalysisError("archive contains no trial rows")
    if expected_stream_keys is not None and stream_keys_seen != expected_stream_keys:
        missing = sorted(expected_stream_keys - stream_keys_seen)[:5]
        unexpected = sorted(stream_keys_seen - expected_stream_keys)[:5]
        raise AnalysisError(f"stream-key coverage mismatch; missing={missing}; unexpected={unexpected}")

    expected_models = set(ESTIMATORS)
    for stream_key in sorted(stream_keys_seen):
        found_profiles = stream_profiles[stream_key]
        if found_profiles != allowed_profiles:
            missing = sorted(allowed_profiles - found_profiles)
            extra = sorted(found_profiles - allowed_profiles)
            raise AnalysisError(
                f"wrong profile count for stream {stream_key}: found {len(found_profiles)}, "
                f"expected {len(allowed_profiles)}; missing={missing}; extra={extra}"
            )
        for profile in sorted(allowed_profiles):
            found_models = stream_estimators[(stream_key, profile)]
            if found_models != expected_models:
                missing = sorted(expected_models - found_models)
                extra = sorted(found_models - expected_models)
                raise AnalysisError(
                    f"missing or extra estimator key for stream {stream_key}, profile {profile}: "
                    f"missing={missing}; extra={extra}"
                )

    group_records: list[dict[str, str | int | float | bool | None]] = []
    paired_groups = 0
    pair_data_by_base: dict[tuple[str, ...], dict[str, list[dict[str, float | int | str | None]]]] = {}
    for base_key, trials in by_base_group.items():
        pair_data = pair_trial_rows(trials)
        pair_data_by_base[base_key] = pair_data
        paired_groups += 1
    for key, trials in grouped.items():
        if len(trials) != expected_trials_per_group:
            raise AnalysisError(
                f"wrong trial count for group {key}: found {len(trials)}, "
                f"expected {expected_trials_per_group}"
            )
        estimator = key[4]
        base_key = (key[0], key[1], key[2], key[3], *key[5:])
        paired = pair_data_by_base[base_key].get(estimator) if estimator in ESKF_ESTIMATORS else None
        group_records.append(_group_record(key, trials, archive_sha256.lower(), paired))

    group_records.sort(key=lambda record: tuple(str(record[field]) for field in GROUP_FIELDS))
    factor_means = []
    for estimator, stress_mode in sorted(factor_values):
        values = factor_values[(estimator, stress_mode)]
        factor_means.append(
            {
                "estimator": estimator,
                "stress_mode": stress_mode,
                "trial_count": len(values),
                "tilt_rms_mean_deg": trial_weighted_mean([values]),
                "tilt_rms_sum_deg": math.fsum(values),
            }
        )
    return {
        "split": split,
        "archive_sha256": archive_sha256.lower(),
        "trial_rows": len(seen_trial_keys),
        "stream_count": len(stream_keys_seen),
        "profile_count": len(allowed_profiles),
        "group_count": len(group_records),
        "paired_profile_groups": paired_groups,
        "groups": group_records,
        "factor_means": factor_means,
    }


def _same_number(left: object, right: object, tolerance: float = 1e-11) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def compare_with_published_summary(
    groups: Sequence[Mapping[str, object]], summary_path: Path
) -> dict[str, object]:
    published = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_rows = published.get("distribution_groups")
    if not isinstance(expected_rows, list):
        raise AnalysisError(f"published summary lacks distribution_groups: {summary_path}")
    key_fields = GROUP_FIELDS[1:]
    actual_by_key = {tuple(group[field] for field in GROUP_FIELDS[1:]): group for group in groups}
    expected_by_key = {
        tuple(group[field] for field in key_fields): group for group in expected_rows
    }
    if len(actual_by_key) != len(groups) or len(expected_by_key) != len(expected_rows):
        raise AnalysisError("duplicate group key while comparing published summary")
    if actual_by_key.keys() != expected_by_key.keys():
        missing = list(expected_by_key.keys() - actual_by_key.keys())[:3]
        extra = list(actual_by_key.keys() - expected_by_key.keys())[:3]
        raise AnalysisError(f"published report group keys differ; missing={missing}; extra={extra}")

    comparisons = 0
    max_abs_error = 0.0
    for key, actual in actual_by_key.items():
        reference = expected_by_key[key]
        metrics = reference.get("metric_distributions", {})
        checks = (
            (actual["trial_count"], reference.get("trial_count")),
            (actual["tilt_rms_finite_trials"], reference.get("finite_metric_count")),
            (actual["complete_trials"], reference.get("complete_count")),
            (actual["covariance_applicable"], reference.get("covariance_applicable")),
            (actual["mean_availability"], reference.get("availability_mean")),
            (actual["tilt_rms_mean_deg"], metrics.get("tilt_rms_deg", {}).get("mean")),
            (actual["tilt_rms_median_deg"], metrics.get("tilt_rms_deg", {}).get("median")),
            (actual["tilt_rms_p95_deg"], metrics.get("tilt_rms_deg", {}).get("p95")),
            (actual["tilt_rms_worst_deg"], metrics.get("tilt_rms_deg", {}).get("max")),
            (actual["yaw_rms_mean_deg"], metrics.get("yaw_rms_deg", {}).get("mean")),
            (actual["mean_accel_bias_error_m_s2"], metrics.get("accel_bias_error_m_s2", {}).get("mean")),
            (actual["mean_gyro_bias_error_rad_s"], metrics.get("gyro_bias_error_rad_s", {}).get("mean")),
            (actual["mean_tilt_nees_per_trial"], metrics.get("tilt_nees_mean", {}).get("mean")),
            (actual["mean_tilt_nees_coverage95"], metrics.get("tilt_nees_coverage95", {}).get("mean")),
            (actual["mean_nis_per_trial"], metrics.get("nis_mean", {}).get("mean")),
        )
        for actual_value, expected_value in checks:
            if not _same_number(actual_value, expected_value):
                raise AnalysisError(
                    f"published summary mismatch for {key}: {actual_value!r} != {expected_value!r}"
                )
            if actual_value is not None:
                max_abs_error = max(max_abs_error, abs(float(actual_value) - float(expected_value)))
            comparisons += 1
    if len(groups) != len(expected_rows):
        raise AnalysisError(f"published summary group count mismatch: {len(groups)} != {len(expected_rows)}")

    pair_key_fields = (
        "scenario",
        "rate_mode",
        "stress_mode",
        "sensor_input",
        "startup_knowledge",
        "startup_gyro_bias_calibration",
        "runtime_aid",
    )
    published_pairs = published.get("paired_confidence_intervals", [])
    expected_pairs = {}
    for pair in published_pairs:
        if pair.get("right_estimator") != "mahony" or pair.get("left_estimator") not in ESKF_ESTIMATORS:
            continue
        pair_key = (
            tuple(pair[field] for field in pair_key_fields),
            pair["left_estimator"],
        )
        if pair_key in expected_pairs:
            raise AnalysisError(f"duplicate published ESKF/Mahony pair key {pair_key}")
        expected_pairs[pair_key] = pair
    actual_eskf_groups = [group for group in groups if group["estimator"] in ESKF_ESTIMATORS]
    if len(expected_pairs) != len(actual_eskf_groups):
        raise AnalysisError(
            "published ESKF/Mahony pair count differs: "
            f"{len(expected_pairs)} != {len(actual_eskf_groups)}"
        )
    for actual in actual_eskf_groups:
        pair_context = tuple(actual[field] for field in pair_key_fields)
        expected = expected_pairs.get((pair_context, actual["estimator"]))
        if expected is None:
            raise AnalysisError(f"published ESKF/Mahony pair is missing for {pair_context}")
        pair_checks = (
            (actual["paired_mahony_trials"], expected.get("n_pairs")),
            (actual["paired_mahony_trials"], expected.get("matched_trials")),
            (actual["paired_tilt_trials"], expected.get("matched_trials")),
            (actual["paired_tilt_mean_delta_deg"], expected.get("mean_difference")),
            (0, expected.get("invalid_pairs")),
            (0, expected.get("input_or_config_hash_mismatches")),
        )
        for actual_value, expected_value in pair_checks:
            if not _same_number(actual_value, expected_value):
                raise AnalysisError(
                    f"published paired result mismatch for {pair_context}, "
                    f"{actual['estimator']}: {actual_value!r} != {expected_value!r}"
                )
            if actual_value is not None:
                max_abs_error = max(max_abs_error, abs(float(actual_value) - float(expected_value)))
            comparisons += 1
    return {
        "status": "PASS",
        "published_summary_sha256": sha256_canonical_text(summary_path),
        "matched_groups": len(groups),
        "matched_eskf_mahony_pairs": len(actual_eskf_groups),
        "compared_values": comparisons,
        "maximum_absolute_numeric_difference": max_abs_error,
    }


def _manifest_seed_range(manifest: Mapping[str, object], fallback: tuple[int, int]) -> tuple[int, int]:
    inclusive = manifest.get("seed_range_inclusive")
    if isinstance(inclusive, (list, tuple)) and len(inclusive) == 2:
        return int(inclusive[0]), int(inclusive[1])
    seeds = manifest.get("seeds")
    if isinstance(seeds, Mapping):
        first = seeds.get("first_seed")
        last = seeds.get("last_seed")
        if first is not None and last is not None:
            return int(first), int(last)
    return fallback


def _expected_stream_keys(first_seed: int, last_seed: int) -> set[tuple[str, str, str, int]]:
    return {
        (scenario, rate, stress, seed)
        for scenario, rate, stress, seed in product(
            SCENARIOS, RATE_MODES, STRESS_MODES, range(first_seed, last_seed + 1)
        )
    }


def analyze_archive(repo_root: Path, split: str, short: str, first_seed: int, last_seed: int) -> dict[str, object]:
    stem = f"pr3_protocol_v5_{short}_all_factors_postfix"
    archive_path = repo_root / "benchmarks/reports" / f"{stem}_trials.csv.gz"
    manifest_path = repo_root / "benchmarks/manifests" / f"{stem}.json"
    summary_path = repo_root / "benchmarks/reports" / f"{stem}_summary.json"
    for path in (archive_path, manifest_path, summary_path):
        if not path.is_file():
            raise AnalysisError(f"required v5 evidence file is missing: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_sha256 = sha256_file(archive_path)
    if archive_sha256 != manifest.get("packaged_trial_csv_gz_sha256"):
        raise AnalysisError(f"archive SHA-256 does not match manifest: {archive_path}")
    if (
        manifest.get("protocol_version") != 5
        or manifest.get("source_commit") != SOURCE_COMMIT
        or manifest.get("split") != split
    ):
        raise AnalysisError(f"manifest protocol/source identity mismatch: {manifest_path}")
    if manifest.get("protocol_sha256") != PROTOCOL_SHA256:
        raise AnalysisError(f"manifest protocol SHA-256 mismatch: {manifest_path}")
    if (
        manifest.get("scenarios") != list(SCENARIOS)
        or manifest.get("rate_modes") != list(RATE_MODES)
        or manifest.get("stress_modes") != list(STRESS_MODES)
    ):
        raise AnalysisError(f"manifest factor dimensions mismatch: {manifest_path}")
    manifest_seed_range = _manifest_seed_range(manifest, (first_seed, last_seed))
    if manifest_seed_range != (first_seed, last_seed):
        raise AnalysisError(f"unexpected seed range in {manifest_path}: {manifest_seed_range}")

    analysis = analyze_rows(
        iter_csv_rows(archive_path),
        split=split,
        archive_sha256=archive_sha256,
        expected_profiles=set(EXPECTED_PROFILES),
        expected_stream_keys=_expected_stream_keys(first_seed, last_seed),
        expected_trials_per_group=last_seed - first_seed + 1,
    )
    report_comparison = compare_with_published_summary(analysis["groups"], summary_path)
    analysis.update(
        {
            "archive_path": archive_path.relative_to(repo_root).as_posix(),
            "manifest_path": manifest_path.relative_to(repo_root).as_posix(),
            "summary_path": summary_path.relative_to(repo_root).as_posix(),
            "manifest_sha256": sha256_canonical_text(manifest_path),
            "report_comparison": report_comparison,
            "seed_range": [first_seed, last_seed],
        }
    )
    return analysis


def _profile_rollups(split_results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, ...], dict[str, object]] = {}
    for split_result in split_results:
        for row in split_result["groups"]:
            key = (
                row["split"],
                row["sensor_input"],
                row["startup_knowledge"],
                row["startup_gyro_bias_calibration"],
                row["runtime_aid"],
                row["stress_mode"],
                row["estimator"],
            )
            bucket = buckets.setdefault(
                key,
                {
                    "trial_count": 0,
                    "tilt_sum": 0.0,
                    "tilt_count": 0,
                    "yaw_sum": 0.0,
                    "yaw_count": 0,
                    "minimum_availability": 1.0,
                    "incomplete_trials": 0,
                    "paired_tilt_sum": 0.0,
                    "paired_tilt_count": 0,
                },
            )
            bucket["trial_count"] += row["trial_count"]
            tilt_count = row["tilt_rms_finite_trials"]
            if tilt_count and row["tilt_rms_mean_deg"] is not None:
                bucket["tilt_sum"] += row["tilt_rms_mean_deg"] * tilt_count
                bucket["tilt_count"] += tilt_count
            yaw_count = row["yaw_rms_finite_trials"]
            if yaw_count and row["yaw_rms_mean_deg"] is not None:
                bucket["yaw_sum"] += row["yaw_rms_mean_deg"] * yaw_count
                bucket["yaw_count"] += yaw_count
            bucket["minimum_availability"] = min(
                bucket["minimum_availability"], row["minimum_availability"]
            )
            bucket["incomplete_trials"] += row["incomplete_trials"]
            pair_count = row["paired_tilt_trials"] or 0
            if pair_count and row["paired_tilt_mean_delta_deg"] is not None:
                bucket["paired_tilt_sum"] += row["paired_tilt_mean_delta_deg"] * pair_count
                bucket["paired_tilt_count"] += pair_count

    result = []
    for key, bucket in sorted(buckets.items()):
        split, sensor, startup, calibration, aid, stress, estimator = key
        result.append(
            {
                "split": split,
                "sensor_input": sensor,
                "startup_knowledge": startup,
                "startup_gyro_bias_calibration": calibration,
                "runtime_aid": aid,
                "stress_mode": stress,
                "estimator": estimator,
                "trial_count": bucket["trial_count"],
                "mean_tilt_rms_deg": (
                    bucket["tilt_sum"] / bucket["tilt_count"] if bucket["tilt_count"] else None
                ),
                "mean_yaw_rms_deg": (
                    bucket["yaw_sum"] / bucket["yaw_count"] if bucket["yaw_count"] else None
                ),
                "minimum_availability": bucket["minimum_availability"],
                "incomplete_trials": bucket["incomplete_trials"],
                "paired_mahony_tilt_mean_delta_deg": (
                    bucket["paired_tilt_sum"] / bucket["paired_tilt_count"]
                    if bucket["paired_tilt_count"] else None
                ),
            }
        )
    return result


def _published_factor_checks(split_results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    totals: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
        lambda: {"sum": 0.0, "count": 0}
    )
    for split_result in split_results:
        for item in split_result["factor_means"]:
            key = (item["estimator"], item["stress_mode"])
            totals[key]["sum"] += item["tilt_rms_sum_deg"]
            totals[key]["count"] += item["trial_count"]
    checks = []
    for key, published in sorted(PUBLISHED_FACTOR_MEANS.items()):
        total = totals[key]
        actual = total["sum"] / total["count"]
        matches = f"{actual:.4f}" == f"{published:.4f}"
        checks.append(
            {
                "estimator": key[0],
                "stress_mode": key[1],
                "trial_count": total["count"],
                "recomputed_mean_tilt_rms_deg": actual,
                "published_mean_tilt_rms_deg": published,
                "matches_4dp": matches,
            }
        )
    return checks


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _markdown_report(
    split_results: Sequence[Mapping[str, object]],
    profile_rollups: Sequence[Mapping[str, object]],
    factor_checks: Sequence[Mapping[str, object]],
) -> str:
    lines = [
        "# PR3 v5 baseline archive analysis",
        "",
        f"Analysis schema version: `{ANALYSIS_VERSION}`. The analyzer reads the three frozen compressed v5 trial CSVs and does not regenerate their sensor streams or rerun the benchmark sweeps. No hardware test was run.",
        "",
        "## Archive and report checks",
        "",
        "| Split | Archive SHA-256 | Streams | Rows | Groups | Published summary comparison |",
        "|---|---|---:|---:|---:|---|",
    ]
    for result in split_results:
        comparison = result["report_comparison"]
        lines.append(
            f"| {result['split']} | `{result['archive_sha256']}` | {result['stream_count']:,} | "
            f"{result['trial_rows']:,} | {result['group_count']:,} | "
            f"{comparison['status']}: {comparison['matched_groups']:,} groups, "
            f"{comparison['compared_values']:,} values, "
            f"{comparison['matched_eskf_mahony_pairs']:,} ESKF/Mahony pairs |"
        )
    lines.extend(
        [
            "",
            "Each group in the CSV matrix has one row per seed (`n=100`); sensor samples are never treated as independent trials. The distribution quantile convention matches the frozen PR3 summarizer (`sorted[int(q * (n - 1))]`) so p90/p95 and lower median reproduce its reports. `tilt_rms_deg` and `yaw_rms_deg` are already trial-level RMS values in the source CSV.",
            "",
            "## Profile-separated headline rollups",
            "",
            "These rows average per-trial summaries across the 8 scenarios × 3 rate modes within one split, stress mode, and explicit profile. They are descriptive only; splits and profile classes remain separate. Positive ESKF-minus-Mahony tilt delta means higher ESKF tilt error.",
            "",
            "| Split | Stress | Profile | n | Conservative ESKF tilt mean (°) | Mahony tilt mean (°) | Paired ESKF−Mahony (°) | ESKF minimum availability |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    highlighted = {
        ("IMU_ONLY", "UNKNOWN", "OFF", "NONE"): "Unknown startup, six-axis/no aid",
        ("IMU_ONLY", "EXTERNALLY_VERIFIED_STATIC", "ON", "NONE"): "Verified stationary startup + gyro calibration",
        (
            "IMU_WITH_SYNTHETIC_HEADING",
            "EXTERNALLY_VERIFIED_STATIC",
            "ON",
            "INDEPENDENT_MEASUREMENT",
        ): "Synthetic independent heading aid",
        (
            "IMU_WITH_SYNTHETIC_HEADING",
            "EXTERNALLY_VERIFIED_STATIC",
            "ON",
            "SIMULATOR_ORACLE",
        ): "Simulator-oracle heading",
    }
    rollup_index = {
        (
            row["split"],
            row["sensor_input"],
            row["startup_knowledge"],
            row["startup_gyro_bias_calibration"],
            row["runtime_aid"],
            row["stress_mode"],
            row["estimator"],
        ): row
        for row in profile_rollups
    }
    for split, _short, _first, _last in SPLITS:
        for profile, label in highlighted.items():
            for stress in STRESS_MODES:
                conservative = rollup_index[(split, *profile, stress, "eskf_conservative")]
                mahony = rollup_index[(split, *profile, stress, "mahony")]
                lines.append(
                    f"| {split} | {stress} | {label} | {conservative['trial_count']:,} | "
                    f"{conservative['mean_tilt_rms_deg']:.4f} | {mahony['mean_tilt_rms_deg']:.4f} | "
                    f"{conservative['paired_mahony_tilt_mean_delta_deg']:.4f} | "
                    f"{conservative['minimum_availability']:.4f} |"
                )
    lines.extend(
        [
            "",
            "The full group matrix also keeps the other three declared profiles separate: verified startup without calibration, simulator-oracle startup, and unknown startup with synthetic-heading data present but runtime aid disabled.",
            "",
            "## Published cross-factor mean comparison",
            "",
            "This historical arithmetic mean pools equal-weight per-trial rows across all v5 scenarios, rates, profiles, and splits solely to reproduce the aggregate in `remediation/PR3_STATUS.md`; it is not a profile-level conclusion or an independent validation set.",
            "",
            "| Estimator | Stress mode | Trials | Recomputed tilt mean (°) | Published (°) | Match to 4 dp |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in factor_checks:
        lines.append(
            f"| {item['estimator']} | {item['stress_mode']} | {item['trial_count']:,} | "
            f"{item['recomputed_mean_tilt_rms_deg']:.4f} | "
            f"{item['published_mean_tilt_rms_deg']:.4f} | "
            f"{'PASS' if item['matches_4dp'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "- No runtime heading aid means yaw is reported as relative heading RMS in the shared zero-yaw startup gauge; it is not absolute north accuracy. Independent heading uses an independent **synthetic** measurement; simulator-oracle heading is explicitly an oracle case. The archived CSV contains only per-trial yaw RMS, so it cannot recover a per-sample drift rate or redo startup alignment.",
            "- Bias values are trial-final norm errors versus simulator truth. Missing baseline bias fields remain blank/N/A rather than zero.",
            "- `tilt_nees_mean` is a 2D tilt-subspace diagnostic. `nis_mean` pools the evaluator's accepted gravity and heading update NIS values where applicable; the CSV does not separate measurement families. Gravity corrections reuse accelerometer information, and temporal samples are correlated, so these columns do not establish ideal independent-sample chi-square coverage or calibrated uncertainty.",
            "- Covariance-valid sample counts describe numerical validity, not uncertainty calibration. Availability, incompleteness, and recovery are reported alongside error to expose easy-sample-only effects.",
            "- All results are synthetic host simulation evidence. Held-out and final-confirmation v5 data are exposed historical evidence, not untouched confirmation for future changes. This analysis does not close the estimator-quality or hardware-validation gates.",
            "",
            "## Reproduction",
            "",
            "Run from the repository root:",
            "",
            "```text",
            "python tools/analyze_pr3_archives.py --output-dir remediation/analysis",
            "```",
            "",
            "Verification commands run:",
            "",
            "```text",
            "python3 tests/test_pr3_archive_analysis.py",
            "python3 tests/test_pr3_summary.py",
            "python3 tools/analyze_pr3_archives.py --output-dir remediation/analysis",
            "```",
            "",
            "The existing summary regression test includes one temporary single-seed smoke fixture; it did not regenerate or replace any frozen v5 stream/archive.",
            "",
            "Only these three deterministic derived artifacts are written (replaced on rerun); the source `.csv.gz`, manifests, published summaries, protocol, and figures are opened read-only.",
            "",
        ]
    )
    return "\n".join(lines)


def analyze_repository(repo_root: Path, output_dir: Path) -> dict[str, object]:
    protocol_path = repo_root / "benchmarks/scenarios/pr3_scenarios_protocol_v5.json"
    if sha256_canonical_text(protocol_path) != PROTOCOL_SHA256:
        raise AnalysisError(f"protocol v5 SHA-256 mismatch: {protocol_path}")
    results = [
        analyze_archive(repo_root, split, short, first, last)
        for split, short, first, last in SPLITS
    ]
    factor_checks = _published_factor_checks(results)
    if len(factor_checks) != len(PUBLISHED_FACTOR_MEANS) or not all(
        item["matches_4dp"] for item in factor_checks
    ):
        raise AnalysisError("one or more published cross-factor means did not match to 4 decimals")
    profile_rollups = _profile_rollups(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "v5_baseline_matrix.csv"
    json_path = output_dir / "v5_baseline_matrix.json"
    markdown_path = output_dir / "v5_baseline_findings.md"
    group_rows = [group for result in results for group in result["groups"]]
    group_rows.sort(key=lambda row: tuple(str(row[field]) for field in GROUP_FIELDS))
    _write_csv(csv_path, group_rows)
    summary = {
        "analysis_schema_version": ANALYSIS_VERSION,
        "analysis_tool": "tools/analyze_pr3_archives.py",
        "protocol_version": 5,
        "protocol_sha256": PROTOCOL_SHA256,
        "frozen_source_commit": SOURCE_COMMIT,
        "independent_unit": "one per-seed trial summary row; sample counts are denominators/diagnostics, never replicate weights",
        "quantile_method": "sorted[int(q * (n - 1))], matching the existing PR3 summarizer",
        "archives": [
            {
                "split": result["split"],
                "path": result["archive_path"],
                "sha256": result["archive_sha256"],
                "manifest_path": result["manifest_path"],
                "manifest_sha256": result["manifest_sha256"],
                "summary_path": result["summary_path"],
                "rows": result["trial_rows"],
                "streams": result["stream_count"],
                "profiles": result["profile_count"],
                "groups": result["group_count"],
                "report_comparison": result["report_comparison"],
            }
            for result in results
        ],
        "group_matrix": {
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "row_count": len(group_rows),
            "group_key": list(GROUP_FIELDS),
        },
        "profile_rollups": profile_rollups,
        "published_cross_factor_mean_checks": factor_checks,
        "interpretation_caveats": [
            "Yaw is a relative startup-gauge score when runtime_aid is NONE; it is not absolute north accuracy.",
            "Independent heading is synthetic; simulator-oracle heading is kept separate and is not a sensor-performance result.",
            "Tilt NEES and pooled NIS are consistency diagnostics with correlated/reused data; they do not establish ideal independent-sample coverage.",
            "The source CSVs contain trial summaries, not sample-level output traces; drift rate and sample-level re-alignment cannot be recomputed here.",
            "All evidence is synthetic host simulation; no hardware validation is claimed.",
        ],
    }
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_path.write_text(
        _markdown_report(results, profile_rollups, factor_checks),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "group_count": len(group_rows),
        "output_csv": csv_path,
        "output_json": json_path,
        "output_markdown": markdown_path,
        "published_report_groups": sum(
            result["report_comparison"]["matched_groups"] for result in results
        ),
        "published_factor_checks": len(factor_checks),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "remediation/analysis",
        help="directory for the versioned CSV, JSON, and Markdown summaries",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    try:
        result = analyze_repository(args.repo_root.resolve(), args.output_dir.resolve())
    except (AnalysisError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL PR3 v5 archive analysis: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS PR3 v5 archive analysis v1: "
        f"{result['group_count']:,} grouped rows; "
        f"{result['published_report_groups']:,} published groups matched; "
        f"{result['published_factor_checks']} cross-factor means matched"
    )
    print(f"Wrote {result['output_csv']}")
    print(f"Wrote {result['output_json']}")
    print(f"Wrote {result['output_markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
