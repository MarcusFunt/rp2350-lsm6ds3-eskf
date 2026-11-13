"""Standalone orientation and trial-scoring utilities for external benchmarks.

Quaternion inputs are scalar-first ``q_world_from_body`` rotations in a
right-handed ENU world. All angular functions return radians. This module is
host-side math only and has no dependency on the firmware or adapter API.
"""

from __future__ import annotations

import math
import random
import re
import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MetricError(ValueError):
    """Raised when metric inputs are malformed or cannot be paired safely."""


Quaternion = tuple[float, float, float, float]
Vector3 = tuple[float, float, float]


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MetricError(f"{label} must be a finite number")
    return float(value)


def _normalize_quaternion(value: Sequence[float], label: str = "quaternion") -> Quaternion:
    if isinstance(value, (str, bytes)) or len(value) != 4:
        raise MetricError(f"{label} must contain four scalar-first values")
    w, x, y, z = (_finite_number(component, f"{label}[{i}]") for i, component in enumerate(value))
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 1e-12:
        raise MetricError(f"{label} must have nonzero norm")
    return (w / norm, x / norm, y / norm, z / norm)


def _multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def _conjugate(q: Quaternion) -> Quaternion:
    return (q[0], -q[1], -q[2], -q[3])


def _rotate(q: Quaternion, vector: Vector3) -> Vector3:
    # q * [0,v] * conjugate(q), simplified for a unit quaternion.
    w, x, y, z = q
    vx, vy, vz = vector
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + y * tz - z * ty,
        vy + w * ty + z * tx - x * tz,
        vz + w * tz + x * ty - y * tx,
    )


def rotate_body_to_world(quaternion_wxyz: Sequence[float], vector_body: Sequence[float]) -> Vector3:
    """Actively rotate a body-frame vector to ENU using ``q_world_from_body``."""
    q = _normalize_quaternion(quaternion_wxyz)
    if isinstance(vector_body, (str, bytes)) or len(vector_body) != 3:
        raise MetricError("vector_body must contain three values")
    vector = tuple(_finite_number(v, f"vector_body[{i}]") for i, v in enumerate(vector_body))
    return _rotate(q, vector)  # type: ignore[arg-type]


def gravity_direction_body(quaternion_wxyz: Sequence[float]) -> Vector3:
    """Return unit down-gravity ``(0,0,-1)`` in the body frame for ENU ``q_WB``."""
    q = _normalize_quaternion(quaternion_wxyz)
    return _rotate(_conjugate(q), (0.0, 0.0, -1.0))


def geodesic_error_rad(estimate_wxyz: Sequence[float], truth_wxyz: Sequence[float]) -> float:
    """Sign-invariant shortest SO(3) angle between two orientations."""
    estimate = _normalize_quaternion(estimate_wxyz, "estimate_wxyz")
    truth = _normalize_quaternion(truth_wxyz, "truth_wxyz")
    relative = _multiply(estimate, _conjugate(truth))
    vector_norm = math.sqrt(math.fsum(component * component for component in relative[1:]))
    if vector_norm <= 1e-15:
        return 0.0
    return 2.0 * math.atan2(vector_norm, abs(relative[0]))


def gravity_tilt_error_rad(estimate_wxyz: Sequence[float], truth_wxyz: Sequence[float]) -> float:
    """Angle between estimated and true gravity directions in the body frame.

    This metric discards global yaw by design. It is well-defined for all
    normalized orientations and does not require an absolute heading source.
    """
    estimate_down = gravity_direction_body(estimate_wxyz)
    truth_down = gravity_direction_body(truth_wxyz)
    dot = sum(a * b for a, b in zip(estimate_down, truth_down))
    cross = (
        estimate_down[1] * truth_down[2] - estimate_down[2] * truth_down[1],
        estimate_down[2] * truth_down[0] - estimate_down[0] * truth_down[2],
        estimate_down[0] * truth_down[1] - estimate_down[1] * truth_down[0],
    )
    sine = math.sqrt(math.fsum(component * component for component in cross))
    return math.atan2(sine, min(1.0, max(-1.0, dot)))


def heading_rad(quaternion_wxyz: Sequence[float], *, singular_tolerance: float = 1e-10) -> float | None:
    """ENU azimuth of body +X, or ``None`` when its horizontal projection is singular."""
    tolerance = _finite_number(singular_tolerance, "singular_tolerance")
    if not 0.0 < tolerance < 1.0:
        raise MetricError("singular_tolerance must be between zero and one")
    forward = rotate_body_to_world(quaternion_wxyz, (1.0, 0.0, 0.0))
    if math.hypot(forward[0], forward[1]) <= tolerance:
        return None
    return math.atan2(forward[1], forward[0])


def _wrap_pi(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def absolute_heading_error_rad(
    estimate_wxyz: Sequence[float],
    truth_wxyz: Sequence[float],
    *,
    source: str | None,
) -> float | None:
    """Return wrapped absolute-yaw error only with a declared absolute datum.

    ``source`` must identify an independent heading reference, calibrated
    magnetic reference, or supplied initial yaw. With no source, absolute yaw
    is unobservable and the result is N/A (``None``).
    """
    estimate_heading = heading_rad(estimate_wxyz)
    truth_heading = heading_rad(truth_wxyz)
    if source is None:
        return None
    if not isinstance(source, str) or not source.strip():
        raise MetricError("absolute heading source must be a nonempty identifier")
    if estimate_heading is None or truth_heading is None:
        return None
    return _wrap_pi(estimate_heading - truth_heading)


def relative_heading_drift_rad(
    estimates_wxyz: Sequence[Sequence[float]],
    truths_wxyz: Sequence[Sequence[float]],
    *,
    alignment_index: int = 0,
) -> tuple[float | None, ...]:
    """Return heading error after removing the declared startup yaw gauge.

    Each error is wrapped to ``[-pi, pi]`` after subtracting the wrapped yaw
    difference at ``alignment_index``. Singular samples are N/A. The alignment
    sample itself must have defined headings in both streams.
    """
    if len(estimates_wxyz) != len(truths_wxyz) or not estimates_wxyz:
        raise MetricError("estimate and truth sequences must have the same nonzero length")
    if isinstance(alignment_index, bool) or not isinstance(alignment_index, int) or not 0 <= alignment_index < len(estimates_wxyz):
        raise MetricError("alignment_index is outside the heading sequence")
    raw: list[float | None] = []
    for estimate, truth in zip(estimates_wxyz, truths_wxyz):
        eh, th = heading_rad(estimate), heading_rad(truth)
        raw.append(None if eh is None or th is None else _wrap_pi(eh - th))
    initial = raw[alignment_index]
    if initial is None:
        raise MetricError("heading gauge cannot be aligned at a singular sample")
    return tuple(None if error is None else _wrap_pi(error - initial) for error in raw)


def to_project_frame(q_broad_from_body: Sequence[float], q_project_from_broad: Sequence[float]) -> Quaternion:
    """Convert BROAD-frame ``q_BB`` to project ``q_PB`` via explicit ``q_PBROAD``."""
    q_project_broad = _normalize_quaternion(q_project_from_broad, "q_project_from_broad")
    q_broad_body = _normalize_quaternion(q_broad_from_body, "q_broad_from_body")
    return _normalize_quaternion(_multiply(q_project_broad, q_broad_body))


def from_project_frame(q_project_from_body: Sequence[float], q_project_from_broad: Sequence[float]) -> Quaternion:
    """Convert project ``q_PB`` back to BROAD ``q_BB`` with the same frame map."""
    q_project_broad = _normalize_quaternion(q_project_from_broad, "q_project_from_broad")
    q_project_body = _normalize_quaternion(q_project_from_body, "q_project_from_body")
    return _normalize_quaternion(_multiply(_conjugate(q_project_broad), q_project_body))


@dataclass(frozen=True)
class ErrorSummary:
    count: int
    rms: float | None
    p95: float | None
    maximum: float | None


def _lower_order_quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return sorted(values)[int(q * (len(values) - 1))]


def summarize_errors(values: Sequence[float | None]) -> ErrorSummary:
    """Summarize absolute finite error samples using PR3's lower P95 statistic."""
    finite: list[float] = []
    for index, value in enumerate(values):
        if value is None:
            continue
        finite.append(abs(_finite_number(value, f"values[{index}]")))
    if not finite:
        return ErrorSummary(0, None, None, None)
    return ErrorSummary(
        count=len(finite),
        rms=math.sqrt(math.fsum(value * value for value in finite) / len(finite)),
        p95=_lower_order_quantile(finite, 0.95),
        maximum=max(finite),
    )


@dataclass(frozen=True)
class AvailabilitySummary:
    expected_count: int
    valid_count: int
    availability: float | None
    longest_outage_s: float
    recovery_time_s: float | None
    segments: Mapping[str, "AvailabilitySummary"]


@dataclass(frozen=True)
class SegmentScoreSummary:
    error: ErrorSummary
    availability: AvailabilitySummary


@dataclass(frozen=True)
class TrialScoreSummary:
    error: ErrorSummary
    availability: AvailabilitySummary
    segments: Mapping[str, SegmentScoreSummary]


def _bool_mask(values: Sequence[bool], label: str, count: int) -> tuple[bool, ...]:
    if len(values) != count or any(not isinstance(value, bool) for value in values):
        raise MetricError(f"{label} must be a boolean mask with {count} entries")
    return tuple(values)


def _outage_duration(
    times: Sequence[float], expected: Sequence[bool], valid: Sequence[bool], start: float, end: float
) -> float:
    longest = 0.0
    index = 0
    while index < len(times):
        if not expected[index] or valid[index]:
            index += 1
            continue
        first = index
        while index + 1 < len(times) and expected[index + 1] and not valid[index + 1]:
            index += 1
        last = index
        outage_start = start if first == 0 else times[first]
        outage_end = end if last == len(times) - 1 else times[last + 1]
        longest = max(longest, outage_end - outage_start)
        index += 1
    return longest


def _recovery_time(
    times: Sequence[float],
    expected: Sequence[bool],
    valid: Sequence[bool],
    errors: Sequence[float | None] | None,
    *,
    event_time: float,
    threshold: float,
    dwell: float,
    max_gap: float | None,
) -> float | None:
    if errors is None:
        raise MetricError("errors are required when recovery is requested")
    if len(errors) != len(times):
        raise MetricError("errors must match the timestamp count")
    if max_gap is not None:
        max_gap = _finite_number(max_gap, "max_sample_gap_s")
        if max_gap <= 0.0:
            raise MetricError("max_sample_gap_s must be positive when supplied")
    run_start: float | None = None
    previous_good: float | None = None
    for index, time_s in enumerate(times):
        error = errors[index]
        good_error = error is not None and abs(_finite_number(error, f"errors[{index}]")) <= threshold
        good = expected[index] and valid[index] and good_error and time_s >= event_time
        if not good or (previous_good is not None and max_gap is not None and time_s - previous_good > max_gap):
            run_start = None
        if good:
            if run_start is None:
                run_start = time_s
            if time_s - run_start >= dwell:
                return run_start - event_time
            previous_good = time_s
        else:
            previous_good = None
    return None


def availability_summary(
    timestamps_s: Sequence[float],
    expected_mask: Sequence[bool],
    valid_mask: Sequence[bool],
    *,
    errors: Sequence[float | None] | None = None,
    segment_start_s: float | None = None,
    segment_end_s: float | None = None,
    recovery_event_time_s: float | None = None,
    recovery_error_threshold: float | None = None,
    recovery_dwell_s: float = 0.0,
    max_sample_gap_s: float | None = None,
    segment_bounds: Mapping[str, tuple[float, float]] | None = None,
) -> AvailabilitySummary:
    """Count expected/valid outputs and wall-time outages for a trial or segment.

    Times are sample instants in seconds. An invalid run starts at its first
    invalid expected instant (or the segment start if it leads) and ends at
    the next expected instant after the run (or the segment end if it trails).
    Segment bounds are half-open ``[start,end)``. Recovery is the delay from an
    event to the start of the first expected, valid, below-threshold run whose
    sample timestamps span ``recovery_dwell_s``; optional max gap breaks a run.
    """
    times = tuple(_finite_number(value, f"timestamps_s[{i}]") for i, value in enumerate(timestamps_s))
    if not times or any(b <= a for a, b in zip(times, times[1:])):
        raise MetricError("timestamps_s must be nonempty and strictly increasing")
    count = len(times)
    expected = _bool_mask(expected_mask, "expected_mask", count)
    valid = _bool_mask(valid_mask, "valid_mask", count)
    if errors is not None:
        if len(errors) != count:
            raise MetricError("errors must match the timestamp count")
        for index, value in enumerate(errors):
            if value is not None:
                _finite_number(value, f"errors[{index}]")
    if any(v and not e for e, v in zip(expected, valid)):
        raise MetricError("a valid output cannot be marked as not expected")
    start = times[0] if segment_start_s is None else _finite_number(segment_start_s, "segment_start_s")
    if segment_end_s is None:
        if len(times) == 1:
            raise MetricError("segment_end_s is required for a single-sample trial")
        cadence = statistics.median(b - a for a, b in zip(times, times[1:]))
        end = times[-1] + cadence
    else:
        end = _finite_number(segment_end_s, "segment_end_s")
    if start > times[0] or end < times[-1] or end <= start:
        raise MetricError("segment bounds must contain all sample instants and have positive duration")
    if max_sample_gap_s is not None:
        max_sample_gap_s = _finite_number(max_sample_gap_s, "max_sample_gap_s")
        if max_sample_gap_s <= 0.0:
            raise MetricError("max_sample_gap_s must be positive when supplied")

    expected_count = sum(expected)
    valid_count = sum(expected_i and valid_i for expected_i, valid_i in zip(expected, valid))
    recovery_time = None
    if recovery_event_time_s is not None:
        if recovery_error_threshold is None:
            raise MetricError("recovery_error_threshold is required with recovery_event_time_s")
        event_time = _finite_number(recovery_event_time_s, "recovery_event_time_s")
        threshold = _finite_number(recovery_error_threshold, "recovery_error_threshold")
        if threshold < 0.0:
            raise MetricError("recovery_error_threshold must be nonnegative")
        dwell = _finite_number(recovery_dwell_s, "recovery_dwell_s")
        if dwell < 0.0:
            raise MetricError("recovery_dwell_s must be nonnegative")
        recovery_time = _recovery_time(
            times, expected, valid, errors,
            event_time=event_time, threshold=threshold, dwell=dwell, max_gap=max_sample_gap_s,
        )
    elif recovery_error_threshold is not None or errors is not None and recovery_dwell_s != 0.0:
        raise MetricError("recovery settings require recovery_event_time_s")

    segment_results: dict[str, AvailabilitySummary] = {}
    for name, bounds in (segment_bounds or {}).items():
        if not isinstance(name, str) or not name:
            raise MetricError("segment names must be nonempty strings")
        if len(bounds) != 2:
            raise MetricError(f"segment {name!r} bounds must be (start_s, end_s)")
        seg_start, seg_end = (_finite_number(bounds[0], f"segment {name}.start"), _finite_number(bounds[1], f"segment {name}.end"))
        if seg_end <= seg_start:
            raise MetricError(f"segment {name!r} must have positive duration")
        indices = [i for i, time_s in enumerate(times) if seg_start <= time_s < seg_end]
        if not indices:
            segment_results[name] = AvailabilitySummary(0, 0, None, 0.0, None, {})
            continue
        first, last = indices[0], indices[-1]
        segment_errors = None if errors is None else errors[first:last + 1]
        child_end = seg_end if last == len(times) - 1 else min(seg_end, times[last + 1])
        segment_results[name] = availability_summary(
            times[first:last + 1], expected[first:last + 1], valid[first:last + 1],
            errors=segment_errors,
            segment_start_s=seg_start,
            segment_end_s=child_end,
        )

    return AvailabilitySummary(
        expected_count=expected_count,
        valid_count=valid_count,
        availability=valid_count / expected_count if expected_count else None,
        longest_outage_s=_outage_duration(times, expected, valid, start, end),
        recovery_time_s=recovery_time,
        segments=segment_results,
    )


def trial_score_summary(
    timestamps_s: Sequence[float],
    errors: Sequence[float | None],
    expected_mask: Sequence[bool],
    valid_mask: Sequence[bool],
    *,
    segment_start_s: float | None = None,
    segment_end_s: float | None = None,
    recovery_event_time_s: float | None = None,
    recovery_error_threshold: float | None = None,
    recovery_dwell_s: float = 0.0,
    max_sample_gap_s: float | None = None,
    segment_bounds: Mapping[str, tuple[float, float]] | None = None,
) -> TrialScoreSummary:
    """Return error and availability metrics for a whole trial and named segments.

    Error percentiles and maxima include only expected, valid outputs; each
    signed error is converted to its absolute magnitude before aggregation.
    """
    if len(errors) != len(timestamps_s):
        raise MetricError("errors must match the timestamp count")
    for index, value in enumerate(errors):
        if value is not None:
            _finite_number(value, f"errors[{index}]")
    availability = availability_summary(
        timestamps_s, expected_mask, valid_mask,
        errors=errors,
        segment_start_s=segment_start_s,
        segment_end_s=segment_end_s,
        recovery_event_time_s=recovery_event_time_s,
        recovery_error_threshold=recovery_error_threshold,
        recovery_dwell_s=recovery_dwell_s,
        max_sample_gap_s=max_sample_gap_s,
        segment_bounds=segment_bounds,
    )
    expected = _bool_mask(expected_mask, "expected_mask", len(timestamps_s))
    valid = _bool_mask(valid_mask, "valid_mask", len(timestamps_s))
    trial_errors = summarize_errors(
        [value if expected[i] and valid[i] else None for i, value in enumerate(errors)]
    )
    segment_scores: dict[str, SegmentScoreSummary] = {}
    for name, bounds in (segment_bounds or {}).items():
        start, end = bounds
        indices = [i for i, t in enumerate(timestamps_s) if start <= t < end]
        local_error = summarize_errors(
            [errors[i] if expected[i] and valid[i] else None for i in indices]
        )
        segment_scores[name] = SegmentScoreSummary(local_error, availability.segments[name])
    return TrialScoreSummary(trial_errors, availability, segment_scores)


@dataclass(frozen=True)
class TrialObservation:
    """One independent trial/seed result and the input-stream identity it used."""

    trial_id: str
    seed: int
    input_sha256: str
    value: float


@dataclass(frozen=True)
class PairedStatistics:
    n_pairs: int
    mean_difference: float | None
    sample_sd: float | None
    ci95: tuple[float, float] | None
    differences: tuple[float, ...]
    bootstrap_replicates: int
    bootstrap_seed: int


def paired_trial_statistics(
    baseline: Sequence[TrialObservation],
    candidate: Sequence[TrialObservation],
    *,
    bootstrap_replicates: int = 10_000,
    bootstrap_seed: int = 20261110,
) -> PairedStatistics:
    """Paired candidate-minus-baseline bootstrap over unique trial/seed units.

    Each observation must already be one trial/seed summary (never one sample).
    Matching keys and canonical input hashes are required; no incomplete pairs
    are silently dropped. The percentile convention matches PR3 summaries.
    """
    if isinstance(bootstrap_replicates, bool) or not isinstance(bootstrap_replicates, int) or bootstrap_replicates < 1:
        raise MetricError("bootstrap_replicates must be a positive integer")
    if isinstance(bootstrap_seed, bool) or not isinstance(bootstrap_seed, int):
        raise MetricError("bootstrap_seed must be an integer")

    def index(rows: Sequence[TrialObservation], label: str) -> dict[tuple[str, int], TrialObservation]:
        result: dict[tuple[str, int], TrialObservation] = {}
        for row in rows:
            if not isinstance(row, TrialObservation):
                raise MetricError(f"{label} entries must be TrialObservation values")
            if not isinstance(row.trial_id, str) or not row.trial_id.strip():
                raise MetricError(f"{label} trial_id must be nonempty")
            if isinstance(row.seed, bool) or not isinstance(row.seed, int) or row.seed < 0:
                raise MetricError(f"{label} seed must be a nonnegative integer")
            if not isinstance(row.input_sha256, str) or not _SHA256.fullmatch(row.input_sha256):
                raise MetricError(f"{label} input_sha256 must be lowercase SHA-256")
            _finite_number(row.value, f"{label} value")
            key = (row.trial_id, row.seed)
            if key in result:
                raise MetricError(f"duplicate {label} trial/seed pair: {key}")
            result[key] = row
        return result

    baseline_by_key = index(baseline, "baseline")
    candidate_by_key = index(candidate, "candidate")
    if not baseline_by_key or baseline_by_key.keys() != candidate_by_key.keys():
        raise MetricError("baseline and candidate must contain the same nonempty trial/seed pairs")
    differences: list[float] = []
    for key in sorted(baseline_by_key):
        base, current = baseline_by_key[key], candidate_by_key[key]
        if base.input_sha256 != current.input_sha256:
            raise MetricError(f"input hash mismatch for paired trial/seed {key}")
        differences.append(float(current.value) - float(base.value))
    mean = statistics.fmean(differences)
    rng = random.Random(bootstrap_seed)
    bootstrap_means = sorted(
        statistics.fmean(differences[rng.randrange(len(differences))] for _ in differences)
        for _ in range(bootstrap_replicates)
    )
    ci = (_lower_order_quantile(bootstrap_means, 0.025), _lower_order_quantile(bootstrap_means, 0.975))
    return PairedStatistics(
        n_pairs=len(differences),
        mean_difference=mean,
        sample_sd=statistics.stdev(differences) if len(differences) > 1 else None,
        ci95=(ci[0], ci[1]),  # nonempty because replicates >= 1
        differences=tuple(differences),
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
    )


__all__ = [
    "AvailabilitySummary", "ErrorSummary", "MetricError", "PairedStatistics", "SegmentScoreSummary",
    "TrialObservation", "TrialScoreSummary",
    "absolute_heading_error_rad", "availability_summary", "from_project_frame", "geodesic_error_rad",
    "gravity_direction_body", "gravity_tilt_error_rad", "heading_rad", "paired_trial_statistics",
    "relative_heading_drift_rad", "rotate_body_to_world", "summarize_errors", "to_project_frame",
    "trial_score_summary",
]
