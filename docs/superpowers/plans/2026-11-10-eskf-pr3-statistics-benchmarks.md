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
- [x] Protocol v1 and v2 remain immutable. Protocol v2 freezes the paired-bootstrap method and exact per-trial RNG derivation. A 100-seed v2 development run exposed that its vibration measurement disturbance started during stationary startup; protocol v3 now supersedes v2 with a required `start_s=2.0`, while preserving v2 artifacts as superseded evidence. Version validation, malformed start-time rejection, and v3 codegen/runtime tests pass.

### Task 2: Generate shared, data-driven scenario inputs

- Make the versioned protocol drive truth and sample generation for all eight scenarios, rates, stress modes, and declared timestamp schedules.
- Reuse one generated input stream per trial across estimator variants and preserve raw samples only once.
- Add deterministic golden checks and strict provenance validation.
- [x] Protocol v3 generates fixed 128-byte records with truth, physical/reported/nominal timestamps, biases, IMU, independent heading and oracle heading. Each stream carries the protocol SHA; the evaluator rejects malformed v3 headers, bad grids, nonfinite records, disordered timestamps and out-of-split seeds. Paired gravity-policy runs reuse one file and are tied to its SHA-256. Deterministic regeneration and PSD sample-variance tests pass. V1/v2 validation remains covered.

### Task 3: Add failure-aware, tiered evaluation

- Record a fixed expected time grid and expected/produced/valid/missing/stale/rejected counts, unavailable duration, faults, resets, recovery times, and completion status for every trial.
- Keep summary metrics for all trials, selected sample diagnostics, and full covariance/raw capture only for failure-oracle runs.
- Keep IMU-only, external startup knowledge, calibration, independent aid, and simulator-oracle aid orthogonal.
- [x] The stream evaluator reports the fixed denominator, propagated/valid/missing/unavailable/stale/covariance-valid counts, recovery intervals, resets/faults/rejections, health, conditional attitude/navigation/bias errors, tilt NEES and NIS for three ESKF gravity policies. Selected sample traces join truth, state, bias, covariance and update chronology; full covariance is captured only at a first failure. Fixed-gain Mahony and gyro-only attitude references run on the same streams, with navigation/covariance applicability explicit.

### Task 4: Validate statistics and uncertainty metrics

- Independently verify tilt NEES, NIS, covariance validity, noise discretization, and nonfinite-state failure behavior.
- Use at least 100 deterministic seeds for primary distributions, with separate development, held-out, and untouched final-confirmation sets.
- Report per-trial distributions and paired confidence intervals with the method and assumptions stated.
- [~] The analytic yaw-gauge tilt-NEES check, two-sided-PSD noise test, and deterministic paired-bootstrap summarizer pass. V5 development seeds 4001–4100, held-out seeds 9001–9100, and final-confirmation seeds 10001–10100 each have complete 208 Hz nominal baseline distributions and preserved reports. The four-seed development factor pilot covers all rates, stress levels and startup/aiding profiles, but all 2,016 ESKF stress rows fail startup alignment; these added factors lack 100-seed acceptance coverage. PR3 remains open.

### Task 5: Reproduce reports and PR3 gate evidence

- Provide one clean-checkout command for data, summaries, plots, and provenance checks.
- Produce machine-readable reports and reproducible time-series/distribution figures.
- Preserve PR1 held-out artifacts and prior confirmations unchanged; record exact commit/config/input/output hashes.
- Keep the PR3 pass gate OPEN until the handoff's pass criteria and an independent branch review are complete.
- [~] One clean-checkout command builds the generator/evaluator, writes shared streams and hashes, summarizes paired rows, and emits the machine-readable report and five aggregate SVGs. Checked-in v5 trial CSVs regenerate their JSON summaries and aggregate figures with stable source labels and repository paths. PR3 remains OPEN for the unresolved stress startup failure, 100-seed coverage of added factors, upstream PR2 findings, and independent review.

## Current negative findings and limits

- Superseded v3 stress evidence: the static 3x-noise seed-4001 smoke stream produced zero propagated samples in the 14-second fixed evaluation window. V5 development factor results reproduce a broader stress startup failure. No startup threshold was tuned from these results.
- Protocol-v2 vibration disturbance was active before its two-second startup completed. The v2 100-seed result is preserved unchanged as superseded evidence; protocol v3 starts that disturbance at 2.0 seconds. V3 development vibration availability increased to 0.724/0.736/0.808 (Conservative/Legacy/ConfirmedOnly) but no policy completed all 100 trials. The v3 held-out set has 0/2/0 complete trials. This fixes the simulator startup defect, not the estimator covariance failures.
- V5 nominal 208 Hz baseline development, held-out, and final-confirmation runs each have zero incomplete rows among 4,000 estimator rows. The v5 development factor pilot has 2,016 incomplete rows, all ESKF stress rows. Fixed expected denominators remain visible. Any estimator revision informed by v5 acceptance results requires a new untouched confirmation seed set.
- In the v3 seed-4001 `slow_yaw`, 200 Hz, nominal, UNKNOWN/OFF/NONE run, `eskf_confirmed_only` propagated and reported operationally current state on all 2,801 expected samples, but only 1,576 covariance matrices passed Cholesky positive-definiteness. The v5 FP64 covariance revision passes all 20,973,600 ESKF covariance checks in its three primary splits. This closes the observed host covariance defect for tested cases; target resource impact is pending.
- The v5 selected static stress reproducer remains in `Aligning` for 3,328/3,328 samples across all three policies, with zero propagated states and zero covariance failures. The exact init predicate identifies 659 adjacent-acceleration step failures against the 0.20 m/s² limit and a longest stable run of 35 versus 80 required samples; accel-norm and gyro-norm gates pass. Keep the correction OPEN until robust motion rejection and an untouched confirmation are verified.
- PR2 remains OPEN for the documented LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation and missing held-out false-hint/zero-dwell coverage. PR3 has not resolved these issues.
