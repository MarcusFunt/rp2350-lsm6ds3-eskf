> Superseded by [the revised Bundle B implementation plan](2026-11-10-simulation-coverage-revised-implementation-plan.md), which the user selected on 2026-11-10.

# Simulation Coverage and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the synthetic IMU benchmark with two motion cases, a stress sensor profile, and confidence-interval summaries with SVG plots.

**Architecture:** Keep truth and sensor generation in the existing C++ benchmark. Run nominal and stress profiles through the same estimators with paired random seeds, add the profile to each CSV row, and extend the existing Python standard-library summarizer to group profiles and produce confidence intervals and optional SVG plots.

**Tech Stack:** C++17, Python 3 standard library, Bash validation script.

**Spec:** `docs/superpowers/specs/2026-11-10-motion-scenario-expansion-design.md`

## Global Constraints

- Keep the first 2 seconds as an independently verified stationary window.
- Keep all results synthetic and label profile values as illustrative, not calibrated LSM6DS3 characteristics.
- Keep a common generated IMU stream for all estimators in each trial/profile and propagate truth independently.
- Keep plots dependency-free by generating SVG with the Python standard library.
- Do not change estimator algorithms, navigation state, aiding behavior, or gravity-derived NEES/NIS interpretation.
- Keep startup bias calibration opt-in.

## Review Focus

- Unknown `--sensor-profile` values must fail with a usage error instead of silently selecting a profile; pin this in Task 4's CLI validation.
- The default `both` profile run must include every scenario/profile/estimator group exactly once per trial; pin row counts and keys in Task 4's existing validation script.
- Stress transforms must be deterministic and produce observable clipping in at least one intended stress case, while nominal runs retain the current sensor model; pin counters/profile isolation in Task 4's validation update.
- A one-trial summary must mark confidence intervals unavailable instead of emitting misleading finite bounds; pin this in Task 4's summary validation.
- SVG output must include labeled axes, estimator legend, and confidence intervals for every plotted group; pin file presence and SVG content checks in Task 4's validation update.

---

### Task 1: Add motion coverage

**Files:**
- Modify: `tools/benchmark_bundle_b.cpp`

**Interfaces:**
- `motion(const std::string& scenario, float t)` continues returning `Motion` and gains `stop_start` and `compound_motion` cases.
- The scenario iteration list contains the six existing names plus `stop_start` and `compound_motion`.

- [x] Add smooth bounded translation and rotation for `stop_start`, including distinct acceleration, hold, and settling intervals after the existing stationary startup.
- [x] Add simultaneous three-axis angular rate and linear acceleration for `compound_motion`, with bounded smooth envelopes and no motion before 2 seconds.
- [x] Add both names to the benchmark scenario list and ensure unknown scenario names still fail.

### Task 2: Add nominal and stress sensor profiles

**Files:**
- Modify: `tools/benchmark_bundle_b.cpp`

**Interfaces:**
- Add `enum class SensorProfile { Nominal, Stress };` and a stable name helper returning `nominal` or `stress`.
- Change the simulation entry point to accept a `SensorProfile` and return metrics tagged with that profile.
- Add `--sensor-profile nominal|stress|both` parsing; default to `both`, reject every other value, and retain `--trials`, `--seed`, `--output`, and `--startup-bias`.
- Add `sensor_profile`, `accel_clip_samples`, and `gyro_clip_samples` fields to the CSV output.

- [x] Define explicit source-configured stress constants with units for per-axis scale/alignment residuals, quantization steps, clipping limits, and temperature-to-bias coefficients/ramp.
- [x] Apply stress transforms in a documented stable order: scale/alignment, existing random bias/noise plus synthetic temperature-dependent bias, clipping, then quantization. Count accelerometer and gyro clipping samples once per generated stream.
- [x] Run selected profiles with the same seed for paired noise draws; feed each profile's single generated stream to all three estimators.
- [x] Emit each selected profile for all eight scenarios and preserve all existing metrics and arguments.

### Task 3: Add trial-level confidence intervals and SVG plots

**Files:**
- Modify: `tools/summarize_bundle_b.py`

**Interfaces:**
- Group rows by `(scenario, sensor_profile, model)` and require the eight named scenarios.
- Add 95% two-sided Student-t interval fields for the mean per-trial `tilt_rms_deg` and `yaw_rms_deg`; leave bounds unavailable for a single trial.
- Add optional `--plots-dir DIR`; when supplied, generate `tilt_rms_{profile}.svg` and `yaw_rms_{profile}.svg` for each sensor profile and add relative plot links to Markdown.

- [x] Implement a standard-library Student-t critical value helper for finite sample sizes (table values through 30 degrees of freedom and 1.96 above that) and return unavailable bounds for fewer than two trials.
- [x] Add profile and confidence interval bounds to JSON and render mean plus interval bounds in Markdown.
- [x] Generate dependency-free SVGs with scenario labels, units, estimator legend, and the same 95% intervals used in the summary.
- [x] Ensure missing, non-finite, and single-trial metrics remain representable as JSON `null` and readable Markdown.

### Task 4: Update validation, documentation, and generated evidence

**Files:**
- Modify: `tools/run_bundle_b_checks.sh`
- Modify: `README.md`
- Regenerate: `BENCHMARK_B.md`
- Regenerate: `benchmarks/bundle_b_no_startup_bias.csv`
- Regenerate: `benchmarks/bundle_b_verified_startup_bias.csv`
- Regenerate: `benchmarks/summary_no_startup_bias.json`
- Regenerate: `benchmarks/summary_verified_startup_bias.json`
- Create: `benchmarks/plots/tilt_rms_nominal.svg`
- Create: `benchmarks/plots/tilt_rms_stress.svg`
- Create: `benchmarks/plots/yaw_rms_nominal.svg`
- Create: `benchmarks/plots/yaw_rms_stress.svg`

**Interfaces:**
- The checked-in benchmark CSVs use 8 scenarios × 2 profiles × 3 estimator variants × 8 trials per startup mode.
- The summary command uses `--plots-dir benchmarks/plots` and the existing `--markdown` / `--json` destinations.

- [ ] Update the existing validation script to expect `trials × 8 × selected_profiles × 3` rows and to check full scenario/profile/model coverage, invalid profile rejection, deterministic repeats, stress clipping counters, one-trial null confidence bounds, and SVG labels/interval elements.
- [ ] Update README commands and caveats for the profile selector, default `both`, stress-model assumptions, added scenarios, interval interpretation, and generated plots.
- [ ] Build the host benchmark and regenerate both checked-in CSVs with seed `20261110`, 8 trials, and the `both` profile default; this command produces requested benchmark evidence, not a test run.
- [ ] Regenerate the summary JSON files, `BENCHMARK_B.md`, and four SVG plots from the two CSVs.
- [ ] Review generated report links, scenario/profile counts, and synthetic-data caveats in the artifacts.
