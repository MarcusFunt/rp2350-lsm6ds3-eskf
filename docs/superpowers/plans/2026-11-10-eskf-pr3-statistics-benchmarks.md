# PR3 Plan: Statistical Characterization and Reproducible Benchmarks

**Base:** PR2 `cde0fe81c1cc64c6706acaabbced9d65d6ca059d` on branch `test/eskf-statistics-benchmarks`.
**Source specification:** `C:/Users/marcu/Downloads/ESKF_Remediation_Agent_Handoff_Revised_v2_2.md`, PR3 section.
**Status:** In progress. PR2's gate remains OPEN; PR3 may characterize the frozen PR2 behavior, but must not imply that unresolved PR2 risks are fixed.

## Global constraints

- Preserve PR1 and PR2 evidence, frozen manifests, and hashes. New PR3 results use a new protocol and clearly identified synthetic approximations.
- Compare algorithms on identical per-trial IMU samples, timestamps, truth, and declared startup/runtime information.
- Separate sensor input, startup knowledge, startup calibration, and runtime aid. Report availability beside conditional accuracy.
- Do not tune estimator behavior against held-out or final confirmation seeds. If inspected results inform a revision, preserve them as exposed and allocate a new untouched confirmation set.
- Keep hardware claims blocked; synthetic results do not establish physical sensor or control suitability.

## Ruling

PR2's pass gate is OPEN for repeated LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation, and missing held-out coverage of false-hint/zero-dwell guards. PR3 will initially build independent benchmark specification and characterization infrastructure; it will not tune around or reclassify those findings. The cost if this ruling is wrong is that PR3's reports could be mistaken for certification despite unresolved failure modes, so every report must carry the open-gate status and list these risks.

## Tasks

### Task 1: Version the PR3 protocol and scenario specification

- Define the eight required scenarios with explicit body/world frame conventions, truth equations, durations, phase transitions, and any additive disturbance.
- Define nominal/stress transforms separately, fixed nominal rate modes (200 Hz and 208 Hz), and one deterministic irregular timestamp rule using integer microseconds.
- State the white-noise spectral convention and sample conversion, bias random-walk model, factor labels, and per-trial provenance fields.
- Freeze disjoint development, held-out, and final-confirmation seed ranges before new runs; keep prior seed sets untouched.
- Add a schema validator and tests that reject missing or inconsistent protocol fields.
- [x] Protocol v1 and schema validator committed with eight scenario definitions, three sampling modes, explicit noise/stress/factor contracts, and disjoint 100-seed ranges. The four CI golden seed IDs are frozen, but their output artifacts are not generated yet. Eight validator tests pass.

### Task 2: Generate shared, data-driven scenario inputs

- Make the versioned protocol drive truth and sample generation for all eight scenarios, rates, stress modes, and declared timestamp schedules.
- Reuse one generated input stream per trial across estimator variants and preserve raw samples only once.
- Add deterministic golden checks and strict provenance validation.

### Task 3: Add failure-aware, tiered evaluation

- Record a fixed expected time grid and expected/produced/valid/missing/stale/rejected counts, unavailable duration, faults, resets, recovery times, and completion status for every trial.
- Keep summary metrics for all trials, selected sample diagnostics, and full covariance/raw capture only for failure-oracle runs.
- Keep IMU-only, external startup knowledge, calibration, independent aid, and simulator-oracle aid orthogonal.

### Task 4: Validate statistics and uncertainty metrics

- Independently verify tilt NEES, NIS, covariance validity, noise discretization, and nonfinite-state failure behavior.
- Use at least 100 deterministic seeds for primary distributions, with separate development, held-out, and untouched final-confirmation sets.
- Report per-trial distributions and paired confidence intervals with the method and assumptions stated.

### Task 5: Reproduce reports and PR3 gate evidence

- Provide one clean-checkout command for data, summaries, plots, and provenance checks.
- Produce machine-readable reports and reproducible time-series/distribution figures.
- Preserve PR1 held-out artifacts and prior confirmations unchanged; record exact commit/config/input/output hashes.
- Keep the PR3 pass gate OPEN until the handoff's pass criteria and an independent branch review are complete.
