# PR3 Plan: Statistical Characterization and Reproducible Benchmarks

**Base:** PR2 `cde0fe81c1cc64c6706acaabbced9d65d6ca059d` on branch `test/eskf-statistics-benchmarks`.
**Source specification:** `C:/Users/marcu/Downloads/ESKF_Remediation_Agent_Handoff_Revised_v2_2.md`, PR3 section.
**Status:** In progress; PR3 gate OPEN. PR2's gate remains OPEN; PR3 may characterize the frozen PR2 behavior, but must not imply that unresolved PR2 risks are fixed.

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
- [x] Protocol v1 remains immutable and is retained as superseded evidence. Protocol v2 freezes the same scenario model plus the paired-bootstrap method and exact per-trial RNG seed derivation before held-out/final runs. The four CI golden seed IDs remain fixed. Nine schema tests pass.

### Task 2: Generate shared, data-driven scenario inputs

- Make the versioned protocol drive truth and sample generation for all eight scenarios, rates, stress modes, and declared timestamp schedules.
- Reuse one generated input stream per trial across estimator variants and preserve raw samples only once.
- Add deterministic golden checks and strict provenance validation.
- [x] Protocol v2 generates fixed 128-byte records with truth, physical/reported/nominal timestamps, biases, IMU, independent heading and oracle heading. Each stream carries the protocol SHA; the evaluator rejects malformed headers, bad grids, nonfinite records, disordered timestamps and out-of-split seeds. Paired gravity-policy runs reuse one file and are tied to its SHA-256. Deterministic regeneration and PSD sample-variance tests pass.

### Task 3: Add failure-aware, tiered evaluation

- Record a fixed expected time grid and expected/produced/valid/missing/stale/rejected counts, unavailable duration, faults, resets, recovery times, and completion status for every trial.
- Keep summary metrics for all trials, selected sample diagnostics, and full covariance/raw capture only for failure-oracle runs.
- Keep IMU-only, external startup knowledge, calibration, independent aid, and simulator-oracle aid orthogonal.
- [~] The stream evaluator reports the fixed denominator, propagated/valid/missing/unavailable/stale/covariance-valid counts, recovery intervals, resets/faults/rejections, health, conditional attitude/navigation/bias errors, tilt NEES and NIS for three ESKF gravity policies. Diagnostic trace tiers are not implemented, and protocol-listed Mahony/gyro-only variants remain NOT_RUN.

### Task 4: Validate statistics and uncertainty metrics

- Independently verify tilt NEES, NIS, covariance validity, noise discretization, and nonfinite-state failure behavior.
- Use at least 100 deterministic seeds for primary distributions, with separate development, held-out, and untouched final-confirmation sets.
- Report per-trial distributions and paired confidence intervals with the method and assumptions stated.
- [~] An analytic yaw-gauge tilt-NEES check, two-sided-PSD noise test and deterministic percentile-bootstrap summarizer are implemented. The 100-seed primary distributions and untouched held-out/final-confirmation runs remain NOT_RUN.

### Task 5: Reproduce reports and PR3 gate evidence

- Provide one clean-checkout command for data, summaries, plots, and provenance checks.
- Produce machine-readable reports and reproducible time-series/distribution figures.
- Preserve PR1 held-out artifacts and prior confirmations unchanged; record exact commit/config/input/output hashes.
- Keep the PR3 pass gate OPEN until the handoff's pass criteria and an independent branch review are complete.
- [~] One command builds the generator/evaluator, writes shared streams and hashes, summarizes paired rows, emits JSON and SVG. The PR3 gate remains OPEN pending 100-seed runs, missing estimator variants/diagnostic tiers, completion of upstream PR2, and independent review.

## Current negative findings and limits

- Stress white-noise scaling can prevent startup initialization: the static 3x-noise seed-4001 smoke stream produced zero propagated samples in the 14-second fixed evaluation window. No startup threshold was tuned from this result.
- In the seed-4001 `slow_yaw`, 200 Hz, nominal, UNKNOWN/OFF/NONE run, `eskf_confirmed_only` propagated and reported operationally current state on all 2,801 expected samples, but only 1,576 covariance matrices passed Cholesky positive-definiteness; the other 1,225 are an open implementation risk. The other two gravity policies passed all covariance checks on that stream. This is a development diagnostic, not a held-out result.
- PR2 remains OPEN for the documented LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation and missing held-out false-hint/zero-dwell coverage. PR3 has not resolved these issues.
