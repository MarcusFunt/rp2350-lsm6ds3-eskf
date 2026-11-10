# Simulation Coverage and Reporting Design

Date: 2026-11-10

## Intent

Improve the host-side IMU simulation in all three requested areas: exercise more varied motion, model additional sensor imperfections, and make Monte Carlo results easier to interpret. The benchmark is for developers comparing attitude estimators; it remains synthetic software evidence, not a claim about RP2350 or LSM6DS3 field accuracy.

## Goals

- Add smooth stop/start and compound 3D motion cases while retaining the six existing scenarios.
- Add a named stress sensor profile alongside the existing nominal profile. The stress profile models residual per-axis scale and alignment error, quantization, saturation, and slow temperature-related bias drift with clearly labeled illustrative parameters.
- Keep a common generated IMU stream for all estimators in each trial/profile and propagate truth independently.
- Report mean per-trial tilt and yaw RMS with between-trial uncertainty, and generate readable plots with confidence intervals.
- Preserve deterministic runs, the verified stationary startup interval, existing estimator variants, and the existing synthetic-results caveats.

## Non-goals and anti-goals

- Do not claim profile values represent calibrated LSM6DS3 characteristics; no calibration data is available in this repository.
- Do not change estimator algorithms, navigation state, aiding behavior, or the interpretation of gravity-derived NEES/NIS.
- Do not claim the synthetic scenarios establish hardware timing, physical accuracy, or controller stability.
- Do not add a plotting package dependency; generate SVG with the Python standard library.

## Approaches

1. **Expand motion scenarios only.** Small and low-risk, but leaves the sensor model and result interpretation unchanged.
2. **Add sensor stress modeling only.** Adds realism dimensions, but the values would still be assumptions and existing trajectories/reporting remain limited.
3. **Combine scenario coverage, named sensor profiles, and uncertainty plots (chosen by the user as all three directions).** This makes each change interpretable alongside the other two, at the cost of more benchmark rows and a broader update to reports and validation.

## Design and implementation calls

- Keep the six current scenarios and add `stop_start` and `compound_motion`; use smooth bounded motion envelopes and preserve the first 2 seconds as verified stationary.
- Keep the existing nominal sensor behavior. Add a `stress` profile with small, explicit, source-configured residual scale/alignment errors, finite quantization, clipping, and a smooth synthetic temperature ramp that changes bias. Use the same noise random stream discipline across profiles and estimators. Parameters are illustrative placeholders and must be named with units in code and report output.
- Add a profile selector with `nominal`, `stress`, and `both`; default to `both` for the improved benchmark. Include the profile in CSV and summary keys so groups never mix profiles. Keep all estimators on the same samples within each group.
- Preserve the current metrics and CSV measurements while adding the profile identifier. Add a two-sided 95% Student-t confidence interval for the mean of per-trial RMS values (not for pooled samples); with one trial, report the interval as unavailable.
- Extend `summarize_bundle_b.py` to summarize by scenario/profile/estimator and write SVG error-bar plots for tilt and yaw RMS without third-party dependencies. Markdown and JSON should include the interval bounds and link the plots when requested.
- Update the benchmark validation script, README, and checked-in generated CSV/summary artifacts to reflect 8 scenarios and 2 profiles. Preserve deterministic seeds and clearly distinguish nominal/stress assumptions.
- Keep startup bias calibration opt-in and continue marking its stationary window as independently verified synthetic ground truth.

## Constraints and choices left to the builder

- Use stable deterministic transforms and a documented operation order for bias, scale/alignment, clipping, and quantization.
- Choose conservative synthetic stress constants that visibly exercise the model but do not imply a datasheet value; describe each parameter and its units next to its definition.
- Use a compact SVG layout that remains legible for all eight scenario labels and three estimators.
- Keep existing command-line use working, except that the benchmark's default run now emits both sensor profiles; document this behavior.

## Success criteria

- Same seed, options, and profile produce byte-identical output; estimators in each trial/profile receive identical samples.
- Both new scenarios appear for all estimator/profile groups and retain an initial stationary window.
- The stress profile applies each modeled effect deterministically and is distinguishable in the output.
- Summary output includes per-trial uncertainty intervals and generates plots with labeled axes, legend, and intervals.
- Updated documentation and checked-in evidence retain the limitations that all results are synthetic and uncalibrated.
