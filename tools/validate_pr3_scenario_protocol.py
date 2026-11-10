#!/usr/bin/env python3
"""Validate the frozen, data-driven PR3 scenario protocol."""

import json
import math
import string
import sys
from pathlib import Path


REQUIRED_SCENARIOS = (
    "static",
    "slow_yaw",
    "lateral_accel",
    "maneuver",
    "vibration",
    "timing_jitter",
    "stop_start",
    "compound_motion",
)
REQUIRED_RATE_MODES = ("uniform_200hz", "uniform_208hz", "irregular_208hz")
REQUIRED_FACTOR_VALUES = {
    "sensor_input": ("IMU_ONLY", "IMU_WITH_SYNTHETIC_HEADING"),
    "startup_knowledge": ("UNKNOWN", "EXTERNALLY_VERIFIED_STATIC", "TRUTH_ORACLE_STATIC"),
    "startup_gyro_bias_calibration": ("OFF", "ON"),
    "runtime_aid": ("NONE", "INDEPENDENT_MEASUREMENT", "SIMULATOR_ORACLE"),
}


class ProtocolValidationError(ValueError):
    pass


def _fail(message):
    raise ProtocolValidationError(message)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vector3(value, context):
    if not isinstance(value, list) or len(value) != 3 or not all(_number(x) for x in value):
        _fail(f"{context} must be a finite three-vector")


def _validate_terms(terms, context, units):
    if not isinstance(terms, list):
        _fail(f"{context} must be a list")
    for index, term in enumerate(terms):
        label = f"{context}[{index}]"
        if not isinstance(term, dict):
            _fail(f"{label} must be an object")
        if type(term.get("axis")) is not int or term["axis"] not in (0, 1, 2):
            _fail(f"{label}.axis must be 0, 1, or 2")
        amplitude = term.get("amplitude")
        if not _number(amplitude):
            _fail(f"{label}.amplitude must be finite")
        frequency_key = "angular_frequency_rad_s" if units == "angular_frequency_rad_s" else "frequency_hz"
        if not _number(term.get(frequency_key)) or term[frequency_key] <= 0:
            _fail(f"{label}.{frequency_key} must be positive and finite")
        if not _number(term.get("phase_rad")):
            _fail(f"{label}.phase_rad must be finite")


def _validate_profile(profile, duration_s, context):
    if not isinstance(profile, dict):
        _fail(f"{context} must be an object")
    kind = profile.get("kind")
    if kind == "piecewise_constant":
        segments = profile.get("segments")
        if not isinstance(segments, list) or not segments:
            _fail(f"{context}.segments must be a nonempty list")
        cursor = 0.0
        for index, segment in enumerate(segments):
            label = f"{context}.segments[{index}]"
            if not isinstance(segment, dict):
                _fail(f"{label} must be an object")
            start, end = segment.get("start_s"), segment.get("end_s")
            if not _number(start) or not _number(end) or abs(start - cursor) > 1e-9 or end <= start:
                _fail(f"{label} must continue the time partition without gaps or overlaps")
            _vector3(segment.get("body_rate_rad_s"), f"{label}.body_rate_rad_s")
            _vector3(segment.get("world_acceleration_m_s2"), f"{label}.world_acceleration_m_s2")
            cursor = end
        if abs(cursor - duration_s) > 1e-9:
            _fail(f"{context}.segments must cover the full trial duration")
    elif kind == "harmonic_after_start":
        start = profile.get("motion_start_s")
        if not _number(start) or not 0 <= start < duration_s:
            _fail(f"{context}.motion_start_s is outside the trial")
        _vector3(profile.get("body_rate_base_rad_s"), f"{context}.body_rate_base_rad_s")
        _vector3(profile.get("world_acceleration_base_m_s2"), f"{context}.world_acceleration_base_m_s2")
        _validate_terms(profile.get("body_rate_terms"), f"{context}.body_rate_terms", "angular_frequency_rad_s")
        _validate_terms(profile.get("world_acceleration_terms"), f"{context}.world_acceleration_terms", "angular_frequency_rad_s")
    else:
        _fail(f"{context}.kind must be piecewise_constant or harmonic_after_start")


def _validate_seeds(seeds, protocol_version):
    if not isinstance(seeds, dict):
        _fail("seeds must be an object")
    ranges = []
    for split in ("development", "held_out", "final_confirmation"):
        value = seeds.get(split)
        if not isinstance(value, dict):
            _fail(f"seeds.{split} is required")
        first, last = value.get("first_seed"), value.get("last_seed")
        if type(first) is not int or type(last) is not int or first < 0 or last < first:
            _fail(f"seeds.{split} must have a valid inclusive range")
        if last - first + 1 < 100:
            _fail(f"seeds.{split} must contain at least 100 seeds")
        expected_status = "FROZEN_RANGE" if protocol_version >= 2 else "FROZEN_UNRUN"
        if value.get("status") != expected_status:
            _fail(f"seeds.{split} must have status {expected_status}")
        ranges.append((split, first, last))
    for i, (left_name, left_first, left_last) in enumerate(ranges):
        for right_name, right_first, right_last in ranges[i + 1 :]:
            if max(left_first, right_first) <= min(left_last, right_last):
                _fail(f"seed ranges overlap: {left_name} and {right_name}")
    development = seeds["development"]
    golden = seeds.get("ci_golden_seeds")
    if not isinstance(golden, list) or not golden or any(
        type(seed) is not int or not development["first_seed"] <= seed <= development["last_seed"]
        for seed in golden
    ):
        _fail("ci_golden_seeds must be nonempty and a subset of development")
    expected_golden_status = "FROZEN_SEEDS" if protocol_version >= 2 else "FROZEN_SEEDS_ONLY_NO_OUTPUTS_YET"
    if seeds.get("ci_golden_status") != expected_golden_status:
        _fail(f"ci_golden_status must be {expected_golden_status}")


def validate_protocol(document):
    if not isinstance(document, dict):
        _fail("protocol root must be an object")
    version = document.get("protocol_version")
    if document.get("protocol") != "pr3_statistics_benchmarks" or version not in (1, 2, 3):
        _fail("protocol identifier/version must be pr3_statistics_benchmarks/1, /2, or /3")
    expected_status = "FROZEN_SPEC_READY" if version >= 2 else "FROZEN_SPEC_UNRUN"
    if document.get("status") != expected_status:
        _fail(f"protocol status must be {expected_status}")
    if version == 2 and (document.get("supersedes_protocol_version") != 1 or not document.get("protocol_revision_reason")):
        _fail("protocol v2 must identify the superseded protocol and revision reason")
    if version == 3 and (
        document.get("supersedes_protocol_version") != 2
        or not isinstance(document.get("protocol_revision_reason"), str)
        or "vibration" not in document["protocol_revision_reason"].lower()
        or "2.0 seconds" not in document["protocol_revision_reason"]
    ):
        _fail("protocol v3 must identify v2 as superseded and explain the vibration startup correction")
    if (
        not isinstance(document.get("base_commit"), str)
        or len(document["base_commit"]) != 40
        or any(char not in string.hexdigits for char in document["base_commit"])
    ):
        _fail("base_commit must be a full 40-character Git SHA")
    historical = document.get("historical_figure_reconstruction")
    if not isinstance(historical, str) or "NOT_VERIFIED" not in historical:
        _fail("historical figures must be labeled unverified approximations")

    frames = document.get("frames")
    required_frame_keys = ("world", "body", "orientation", "angular_rate", "linear_acceleration", "specific_force_equation")
    if not isinstance(frames, dict) or any(not frames.get(key) for key in required_frame_keys):
        _fail("frames must define world/body axes, orientation, units, and the specific-force equation")
    truth = document.get("truth_integration")
    if not isinstance(truth, dict) or any(not truth.get(key) for key in ("orientation", "velocity", "position")):
        _fail("truth_integration must define orientation, velocity, and position equations")

    sampling = document.get("sampling")
    if not isinstance(sampling, dict):
        _fail("sampling must be an object")
    if sampling.get("timestamp_unit") != "integer_microseconds" or sampling.get("sample_index_starts_at") != 1:
        _fail("sampling must use integer microseconds and one-based sample indices")
    duration = sampling.get("duration_s")
    if not _number(duration) or duration <= 0:
        _fail("sampling.duration_s must be positive and finite")
    window = sampling.get("evaluation_window_s_inclusive")
    if not isinstance(window, list) or len(window) != 2 or not all(_number(x) for x in window):
        _fail("evaluation_window_s_inclusive must contain two finite times")
    if window[0] < 0 or window[0] > window[1] or window[1] > duration:
        _fail("evaluation window must lie inside the fixed trial duration")
    modes = sampling.get("rate_modes")
    if not isinstance(modes, list) or tuple(mode.get("id") for mode in modes if isinstance(mode, dict)) != REQUIRED_RATE_MODES:
        _fail(f"rate_modes must be exactly {REQUIRED_RATE_MODES}")
    rates = {mode["id"]: mode.get("nominal_rate_hz") for mode in modes}
    if rates != {"uniform_200hz": 200, "uniform_208hz": 208, "irregular_208hz": 208}:
        _fail("sampling modes must cover uniform 200 Hz, uniform 208 Hz, and irregular 208 Hz")
    if any("floor(sample_index * 1000000 / nominal_rate_hz)" not in mode.get("timestamp_rule", "") for mode in modes[:2]):
        _fail("uniform timestamp rules must use integer-microsecond floor arithmetic")
    irregular = modes[2]
    jitter = irregular.get("jitter")
    if "round(" not in irregular.get("timestamp_rule", "") or not isinstance(jitter, dict):
        _fail("irregular_208hz must define a deterministic integer-microsecond jitter rule")
    if not all(_number(jitter.get(key)) for key in ("amplitude_us", "frequency_hz", "phase_rad")) or jitter["amplitude_us"] < 0 or jitter["frequency_hz"] <= 0:
        _fail("irregular sampling jitter parameters must be finite and valid")
    if not _number(sampling.get("minimum_allowed_inter_sample_dt_us")) or sampling["minimum_allowed_inter_sample_dt_us"] <= 0:
        _fail("minimum_allowed_inter_sample_dt_us must be positive")
    if sampling.get("scenario_jitter_composes_additively_with_rate_mode_jitter") is not True:
        _fail("scenario and rate-mode timestamp jitter composition must be explicit")

    noise = document.get("noise_model")
    if not isinstance(noise, dict) or "two-sided PSD" not in noise.get("white_noise_spectrum", ""):
        _fail("noise_model must state its two-sided PSD convention")
    if "sample_rate_hz" not in noise.get("sample_variance_rule", ""):
        _fail("noise_model must state the discrete sample variance conversion")
    for key in ("accelerometer_density_m_s2_per_sqrt_hz", "gyroscope_density_rad_s_per_sqrt_hz"):
        if not _number(noise.get(key)) or noise[key] < 0:
            _fail(f"noise_model.{key} must be nonnegative and finite")
    if not isinstance(noise.get("random_generator"), str) or "std::mt19937" not in noise["random_generator"]:
        _fail("noise_model.random_generator must declare the pinned deterministic standard-library generator")
    walk = noise.get("bias_random_walk")
    if not isinstance(walk, dict) or "sqrt(actual_dt_seconds)" not in walk.get("increment_std_rule", ""):
        _fail("bias random walk must define increments using each actual dt")

    stress = document.get("stress_transforms")
    if not isinstance(stress, dict) or not isinstance(stress.get("nominal"), dict) or not isinstance(stress.get("stress"), dict):
        _fail("stress_transforms must define nominal and stress configurations")
    transform_keys = (
        "accelerometer_white_noise_multiplier",
        "gyroscope_white_noise_multiplier",
        "bias_random_walk_multiplier",
        "measurement_disturbance_multiplier",
        "timestamp_jitter_multiplier",
        "truth_trajectory_multiplier",
    )
    for mode_name in ("nominal", "stress"):
        values = stress[mode_name]
        if any(not _number(values.get(key)) or values[key] <= 0 for key in transform_keys):
            _fail(f"stress_transforms.{mode_name} must define positive finite multipliers")
    if any(stress["nominal"][key] != 1 for key in transform_keys):
        _fail("nominal stress multipliers must all equal 1")
    for key in transform_keys:
        if key != "truth_trajectory_multiplier" and stress["stress"][key] < stress["nominal"][key]:
            _fail(f"stress multiplier {key} must not reduce the nominal disturbance")
    if stress["stress"]["truth_trajectory_multiplier"] != 1:
        _fail("stress must not change the truth trajectory")

    factors = document.get("factors")
    if not isinstance(factors, dict):
        _fail("factors must be an object")
    for key, required in REQUIRED_FACTOR_VALUES.items():
        values = factors.get(key)
        if not isinstance(values, list) or tuple(values) != required:
            _fail(f"factors.{key} must enumerate {required}")
    for key in ("independent_measurement_definition", "truth_oracle_definition", "startup_calibration_logging"):
        if not factors.get(key):
            _fail(f"factors.{key} is required")

    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list):
        _fail("scenarios must be a list")
    scenario_ids = [scenario.get("id") for scenario in scenarios if isinstance(scenario, dict)]
    if tuple(scenario_ids) != REQUIRED_SCENARIOS:
        _fail(f"scenarios must define each required scenario once in order: {REQUIRED_SCENARIOS}")
    ids = set(scenario_ids)
    scenario_by_id = {scenario["id"]: scenario for scenario in scenarios if isinstance(scenario, dict)}
    for scenario in scenarios:
        scenario_id = scenario["id"]
        context = f"scenario {scenario_id}"
        if scenario.get("approximation_status") != "NEW_APPROXIMATION_NOT_VERIFIED_AGAINST_HISTORICAL_SVG":
            _fail(f"{context} must be labeled as a new, unverified approximation")
        profile = scenario.get("truth_profile")
        if profile is None:
            reference = scenario.get("truth_profile_ref")
            if not isinstance(reference, str) or reference not in ids or reference == scenario_id:
                _fail(f"{context} must define a truth profile or a valid profile reference")
            if "truth_profile" not in scenario_by_id[reference]:
                _fail(f"{context} truth_profile_ref must point to a directly defined profile")
        else:
            _validate_profile(profile, duration, f"{context}.truth_profile")
        scenario_jitter = scenario.get("timestamp_jitter")
        if scenario_id == "timing_jitter" and scenario_jitter is None:
            _fail("scenario timing_jitter must define timestamp jitter")
        if scenario_jitter is not None:
            if (
                not isinstance(scenario_jitter, dict)
                or not _number(scenario_jitter.get("amplitude_us"))
                or not _number(scenario_jitter.get("frequency_hz"))
                or not _number(scenario_jitter.get("phase_rad"))
                or scenario_jitter["amplitude_us"] < 0
                or scenario_jitter["frequency_hz"] <= 0
            ):
                _fail(f"{context}.timestamp_jitter must define finite, nonnegative amplitude, positive frequency, and phase")
        disturbances = scenario.get("measurement_disturbances", {})
        if not isinstance(disturbances, dict):
            _fail(f"{context}.measurement_disturbances must be an object")
        if "start_s" in disturbances and (
            not _number(disturbances["start_s"])
            or not 0 <= disturbances["start_s"] <= duration
        ):
            _fail(f"{context}.measurement_disturbances.start_s must be inside the trial duration")
        for key in ("accelerometer_specific_force_terms", "gyroscope_rate_terms"):
            if key in disturbances:
                _validate_terms(disturbances[key], f"{context}.measurement_disturbances.{key}", "frequency_hz")
    if version == 3 and scenario_by_id["vibration"].get("measurement_disturbances", {}).get("start_s") != 2.0:
        _fail("protocol v3 vibration measurement_disturbances.start_s must equal 2.0 seconds")

    scenario_jitter_sources = [
        scenario["timestamp_jitter"]
        for scenario in scenarios
        if isinstance(scenario, dict) and isinstance(scenario.get("timestamp_jitter"), dict)
    ]
    jitter_scale = stress["stress"]["timestamp_jitter_multiplier"]
    minimum_dt = sampling["minimum_allowed_inter_sample_dt_us"]
    for mode in modes:
        sources = list(scenario_jitter_sources)
        if isinstance(mode.get("jitter"), dict):
            sources.append(mode["jitter"])
        rate = mode["nominal_rate_hz"]
        max_offset_change = sum(
            jitter_scale * (
                2.0 * source["amplitude_us"] * abs(math.sin(math.pi * source["frequency_hz"] / rate)) + 1.0
            )
            for source in sources
        )
        guaranteed_min_dt = math.floor(1000000 / rate) - math.ceil(max_offset_change)
        if guaranteed_min_dt < minimum_dt:
            _fail(
                "timestamp jitter cannot guarantee monotonic sample times above "
                f"minimum_allowed_inter_sample_dt_us for {mode['id']} (bound {guaranteed_min_dt} us)"
            )

    _validate_seeds(document.get("seeds"), version)
    if not isinstance(document.get("logging_tiers"), dict) or not isinstance(document.get("failure_scoring"), dict):
        _fail("logging_tiers and failure_scoring contracts are required")
    paired = document.get("paired_comparison")
    if not isinstance(paired, dict) or paired.get("same_per_trial_inputs_and_timestamps") is not True:
        _fail("paired comparison must require identical per-trial inputs and timestamps")
    method = paired.get("paired_interval_method")
    if not isinstance(method, str) or not method.strip():
        _fail("paired_comparison.paired_interval_method must be preregistered")
    if version >= 2 and ("paired percentile bootstrap" not in method.lower() or paired.get("paired_interval_confidence") != 0.95 or paired.get("paired_interval_replicates") != 10000 or paired.get("paired_interval_seed") != 20261110):
        _fail(f"PR3 protocol v{version} must freeze the 95% paired bootstrap method, 10,000 replicates, and seed 20261110")
    return document


def load_protocol(path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"cannot read protocol JSON: {error}")
    return validate_protocol(document)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: validate_pr3_scenario_protocol.py PROTOCOL.json", file=sys.stderr)
        return 2
    try:
        document = load_protocol(args[0])
    except ProtocolValidationError as error:
        print(f"FAIL protocol validation: {error}", file=sys.stderr)
        return 1
    print(f"PASS PR3 protocol v{document['protocol_version']}: {len(document['scenarios'])} scenarios, 3 sampling modes, three disjoint 100-seed ranges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
