#!/usr/bin/env python3
"""Generate a deterministic C++ motion/timestamp header from PR3 protocol JSON."""

import hashlib
import json
import sys
from pathlib import Path

from validate_pr3_scenario_protocol import ProtocolValidationError, load_protocol


def _f(value):
    # Hexadecimal floating literals preserve the exact parsed binary value.
    return float(value).hex()


def _vec(value):
    return "{" + ", ".join(_f(component) for component in value) + "}"


def _terms(terms, frequency_key):
    return "{ " + ", ".join(
        "HarmonicTerm{" + ", ".join((
            str(term["axis"]), _f(term["amplitude"]),
            _f(term[frequency_key]), _f(term["phase_rad"]),
        )) + "}"
        for term in terms
    ) + " }"


def generate(document, protocol_bytes):
    digest = hashlib.sha256(protocol_bytes).hexdigest()
    scenarios = document["scenarios"]
    scenario_by_id = {scenario["id"]: scenario for scenario in scenarios}
    lines = [
        "// Generated from the frozen PR3 protocol. Do not edit by hand.",
        f"// protocol_sha256={digest}",
        "#pragma once",
        "#include <cmath>",
        "#include <cstdint>",
        "#include <cstring>",
        "namespace pr3_protocol {",
        "struct Vec3 { double x, y, z; };",
        "struct Motion { Vec3 body_rate_rad_s; Vec3 world_acceleration_m_s2; };",
        "struct HarmonicTerm { int axis; double amplitude, frequency, phase; };",
        "inline constexpr double kDurationS = " + _f(document["sampling"]["duration_s"]) + ";",
        "inline constexpr double kGravityMps2 = 9.80665;",
        "inline constexpr double kEpochUs = " + str(document["sampling"]["epoch_us"]) + ";",
        "inline constexpr std::int64_t kMinimumInterSampleDtUs = " + str(document["sampling"]["minimum_allowed_inter_sample_dt_us"]) + ";",
        "inline constexpr std::uint32_t kProtocolVersion = " + str(document["protocol_version"]) + ";",
        "inline constexpr const char* kProtocolSha256 = \"" + digest + "\";",
        "inline constexpr double kAccelDensity = " + _f(document["noise_model"]["accelerometer_density_m_s2_per_sqrt_hz"]) + ";",
        "inline constexpr double kGyroDensity = " + _f(document["noise_model"]["gyroscope_density_rad_s_per_sqrt_hz"]) + ";",
        "inline constexpr double kAccelWalk = " + _f(document["noise_model"]["bias_random_walk"]["accelerometer_walk_m_s2_per_sqrt_s"]) + ";",
        "inline constexpr double kGyroWalk = " + _f(document["noise_model"]["bias_random_walk"]["gyroscope_walk_rad_s_per_sqrt_s"]) + ";",
        "inline constexpr double kAccelInitialBias[] = {" + ", ".join(_f(x) for x in document["noise_model"]["initial_bias_m_s2_and_rad_s"]["accelerometer"]) + "};",
        "inline constexpr double kGyroInitialBias[] = {" + ", ".join(_f(x) for x in document["noise_model"]["initial_bias_m_s2_and_rad_s"]["gyroscope"]) + "};",
        "inline constexpr double kAccelNoiseStress = " + _f(document["stress_transforms"]["stress"]["accelerometer_white_noise_multiplier"]) + ";",
        "inline constexpr double kGyroNoiseStress = " + _f(document["stress_transforms"]["stress"]["gyroscope_white_noise_multiplier"]) + ";",
        "inline constexpr double kBiasWalkStress = " + _f(document["stress_transforms"]["stress"]["bias_random_walk_multiplier"]) + ";",
        "inline constexpr double kDisturbanceStress = " + _f(document["stress_transforms"]["stress"]["measurement_disturbance_multiplier"]) + ";",
        "inline constexpr double kTimestampStress = " + _f(document["stress_transforms"]["stress"]["timestamp_jitter_multiplier"]) + ";",
        "inline constexpr double kIndependentHeadingSigma = 0.04;",
        "inline constexpr std::uint32_t kDevelopmentFirstSeed = " + str(document["seeds"]["development"]["first_seed"]) + ";",
        "inline constexpr std::uint32_t kDevelopmentLastSeed = " + str(document["seeds"]["development"]["last_seed"]) + ";",
        "inline constexpr std::uint32_t kHeldOutFirstSeed = " + str(document["seeds"]["held_out"]["first_seed"]) + ";",
        "inline constexpr std::uint32_t kHeldOutLastSeed = " + str(document["seeds"]["held_out"]["last_seed"]) + ";",
        "inline constexpr std::uint32_t kConfirmationFirstSeed = " + str(document["seeds"]["final_confirmation"]["first_seed"]) + ";",
        "inline constexpr std::uint32_t kConfirmationLastSeed = " + str(document["seeds"]["final_confirmation"]["last_seed"]) + ";",
        "inline constexpr int kScenarioCount = " + str(len(scenarios)) + ";",
        "inline constexpr const char* kScenarioIds[] = {" + ", ".join('"' + s["id"] + '"' for s in scenarios) + "};",
        "inline constexpr int kRateHz[] = {" + ", ".join(str(m["nominal_rate_hz"]) for m in document["sampling"]["rate_modes"]) + "};",
        "inline constexpr const char* kRateIds[] = {" + ", ".join('"' + m["id"] + '"' for m in document["sampling"]["rate_modes"]) + "};",
        "inline int scenario_index(const char* id) {",
        "  for (int i=0; i<kScenarioCount; ++i) if (std::strcmp(id,kScenarioIds[i])==0) return i;",
        "  return -1;",
        "}",
        "inline Motion motion(int scenario, double t) {",
        "  switch (scenario) {",
    ]
    for i, scenario in enumerate(scenarios):
        profile_owner = scenario
        while "truth_profile" not in profile_owner:
            profile_owner = scenario_by_id[profile_owner["truth_profile_ref"]]
        profile = profile_owner["truth_profile"]
        lines.append(f"  case {i}: {{ // {scenario['id']}")
        if profile["kind"] == "piecewise_constant":
            for segment in profile["segments"]:
                lines.append(
                    f"    if (t >= {_f(segment['start_s'])} && t < {_f(segment['end_s'])}) "
                    f"return Motion{{{_vec(segment['body_rate_rad_s'])}, {_vec(segment['world_acceleration_m_s2'])}}};"
                )
        else:
            lines.extend([
                f"    if (t < {_f(profile['motion_start_s'])}) return Motion{{{_vec([0,0,0])}, {_vec([0,0,0])}}};",
                f"    Motion m{{{_vec(profile['body_rate_base_rad_s'])}, {_vec(profile['world_acceleration_base_m_s2'])}}};",
            ])
            for field, target, freq_key in (
                ("body_rate_terms", "body_rate_rad_s", "angular_frequency_rad_s"),
                ("world_acceleration_terms", "world_acceleration_m_s2", "angular_frequency_rad_s"),
            ):
                terms = profile[field]
                for term in terms:
                    component = "xyz"[term["axis"]]
                    member = "body_rate_rad_s" if target == "body_rate_rad_s" else "world_acceleration_m_s2"
                    lines.append(
                        f"    m.{member}.{component} += {_f(term['amplitude'])} * "
                        f"std::sin({_f(term[freq_key])} * t + {_f(term['phase_rad'])});"
                    )
            lines.append("    return m;")
        lines.append("    return Motion{{0,0,0},{0,0,0}};")
        lines.append("  }")
    lines.extend([
        "  default: return Motion{{0,0,0},{0,0,0}};",
        "  }",
        "}",
        "inline std::int64_t nominal_timestamp_us(std::uint64_t sample_index, int rate_hz) {",
        "  return static_cast<std::int64_t>(kEpochUs) + static_cast<std::int64_t>(sample_index * 1000000ULL / static_cast<unsigned>(rate_hz));",
        "}",
        "inline std::int64_t rate_jitter_us(int rate_mode, std::uint64_t sample_index, double multiplier=1.0) {",
    ])
    for i, mode in enumerate(document["sampling"]["rate_modes"]):
        jitter = mode.get("jitter")
        if jitter:
            lines.append(
                f"  if (rate_mode=={i}) return static_cast<std::int64_t>(std::llround({_f(jitter['amplitude_us'])} * multiplier * "
                f"std::sin(2.0 * 3.14159265358979323846 * {_f(jitter['frequency_hz'])} * sample_index / {mode['nominal_rate_hz']} + {_f(jitter['phase_rad'])})));"
            )
    lines.extend([
        "  (void)rate_mode; (void)sample_index; (void)multiplier; return 0;",
        "}",
        "inline std::int64_t scenario_jitter_us(int scenario, std::uint64_t sample_index, int rate_hz, double multiplier=1.0) {",
    ])
    for i, scenario in enumerate(scenarios):
        jitter = scenario.get("timestamp_jitter")
        if jitter:
            lines.append(
                f"  if (scenario=={i}) return static_cast<std::int64_t>(std::llround({_f(jitter['amplitude_us'])} * multiplier * "
                f"std::sin(2.0 * 3.14159265358979323846 * {_f(jitter['frequency_hz'])} * sample_index / rate_hz + {_f(jitter['phase_rad'])})));"
            )
    lines.extend([
        "  (void)scenario; (void)sample_index; (void)rate_hz; (void)multiplier; return 0;",
        "}",
        "inline double disturbance(int scenario, int axis, bool gyro, double t, double multiplier=1.0) {",
        "  double result=0.0;",
    ])
    for i, scenario in enumerate(scenarios):
        owner = scenario
        while "truth_profile" not in owner:
            owner = scenario_by_id[owner["truth_profile_ref"]]
        disturbance = owner.get("measurement_disturbances", {})
        for field, is_gyro in (("gyroscope_rate_terms", True), ("accelerometer_specific_force_terms", False)):
            for term in disturbance.get(field, []):
                lines.append(
                    f"  if (scenario=={i} && gyro=={str(is_gyro).lower()} && axis=={term['axis']}) "
                    f"result += {_f(term['amplitude'])} * multiplier * std::sin(2.0 * 3.14159265358979323846 * "
                    f"{_f(term['frequency_hz'])} * t + {_f(term['phase_rad'])});"
                )
    lines.extend(["  return result;", "}", "} // namespace pr3_protocol", ""])
    return "\n".join(lines)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: pr3_generate_scenario_header.py PROTOCOL.json OUTPUT.hpp", file=sys.stderr)
        return 2
    protocol_path, output_path = map(Path, args)
    try:
        protocol_bytes = protocol_path.read_bytes()
        document = load_protocol(protocol_path)
        rendered = generate(document, protocol_bytes)
    except (OSError, ProtocolValidationError) as error:
        print(f"FAIL protocol validation: {error}", file=sys.stderr)
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"PASS generated {output_path} from protocol sha256={hashlib.sha256(protocol_bytes).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
