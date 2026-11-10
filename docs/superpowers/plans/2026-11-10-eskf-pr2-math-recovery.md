# ESKF PR 2 Math and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the ESKF's right-error and measurement math, correct demonstrated covariance-reset and false-stationarity issues, and characterize recovery without claiming unobservable IMU-only states.

**Architecture:** Keep the existing 15-state, heap-free ESKF and public measurement APIs. Add independent FP64 math oracles and focused recovery tests; change only the attitude reset Jacobian and handling of externally asserted stationarity when the current IMU sample visibly contradicts it. Freeze the candidate before evaluating a new disjoint confirmation seed set.

**Tech Stack:** C++17 host tests, existing ESKF header, deterministic C++ simulation, Python CSV validation, GCC/G++ and existing Bundle A/B/C scripts.

**Spec:** `C:/Users/marcu/Downloads/ESKF_Remediation_Agent_Handoff_Revised_v2_2.md`, PR 2; parent branch/head `test/eskf-remediation-pr1` / `b749a8aa0e40718ab7b163cad29d9c550b088265`.

## Global Constraints

- Preserve the 15-state ESKF, right-multiplicative attitude-error convention, host determinism, heap-free embedded estimator, Pico 2/RP2350, and original LSM6DS3 support.
- Do not claim six-axis IMU observability of sustained acceleration versus gravity, absolute yaw, or absolute position.
- Keep PR 1 held-out seeds frozen. They have already been inspected and are exposed; use only development data during implementation and a new disjoint confirmation set after candidate freeze.
- Separate `IMU_ONLY`, externally verified startup, startup calibration, and runtime aid in every result.
- Report expected denominator, availability/fault counts, accuracy, and model limitations together.
- Do not modify firmware transport, FIFO, calibration hardware, or unrelated release paths in PR 2.
- Do not push, open a PR, or merge. Stack this branch on the verified PR 1 SHA.

## Review Focus

- Large right-error corrections must use a covariance reset consistent with quaternion injection; test at finite rotations and near zero.
- Quaternion sign changes and tilted yaw updates must preserve measurement residuals and Jacobians.
- A wrong initial tilt must not be claimed recoverable from IMU-only data; a separately verified stationary interval should recover tilt.
- A false external-stationary hint contradicted by obvious gyro/norm/step evidence must not force gravity or zero-rate updates; sustained in-tolerance acceleration remains unobservable.
- Repeated reset/reinitialization, slow yaw, changing bias, and outage/fault behavior must preserve finite state, covariance symmetry/PD, and explicit health meaning.

---

### Task 1: Right-error reset math and independent covariance oracle

**Files:**
- Modify: `eskf15.hpp`
- Create: `tests/test_eskf_reset_oracle.cpp`
- Modify: `tools/run_bundle_a_checks.sh`

**Interfaces:**
- Consumes: current public covariance diagnostics, `update_velocity_world_at`, and existing independent double quaternion helpers in `tests/test_math.cpp`.
- Produces: `Eskf15::attitude_reset_jacobian(Vec3 correction, float G[3][3])`, implementing the exact SO(3) right Jacobian used by the right-error covariance reset.

- [x] **Step 1: Write a failing independent reset test.** Numerically differentiate `log(Exp(-dθ) Exp(dθ+εeᵢ))/ε` in FP64 at zero, small, and finite corrections; compare against the reset Jacobian. Also compute an independent FP64 Joseph update plus reset for a propagated filter and compare all posterior covariance entries after a velocity update.
- [x] **Step 2: Run the focused test and verify RED.** The PR 1 first-order implementation failed the posterior covariance oracle: attitude correction 0.042196347 rad, global max covariance diff 0.00026823457, and the exact reset block exceeded the `2e-5` tolerance.
- [x] **Step 3: Implement the exact right Jacobian.** Use `I - ((1-cos θ)/θ²)[dθ]× + ((θ-sin θ)/θ³)[dθ]×²`, with a Taylor expansion around zero, and call it from the production covariance reset.
- [x] **Step 4: Run the focused oracle and Bundle A.** Both passed. FP64 finite differences passed; exact-reset block error was `7.10e-6` versus `2.21e-4` for first-order; all Bundle A tests passed.
- [x] **Step 5: Commit the math correction and oracle.**

### Task 2: Contradictory external-stationarity hints and tilt recovery

**Files:**
- Modify: `eskf15.hpp`
- Create: `tests/test_pr2_recovery.cpp`
- Modify: `tools/run_bundle_b_checks.sh`

**Interfaces:**
- Consumes: `GravityPolicy`, `set_external_stationary_confirmed`, `gravity_applied_updates`, `gravity_suppressed_updates`, state/health diagnostics.
- Produces: `external_stationary_conflicts()` diagnostic and a per-sample consistency gate: a trusted stationary assertion is usable only while the sample passes configured accel norm, gyro, and accel-step stationarity bounds.

- [x] **Step 1: Write failing regressions.** Covered obvious 0.4 g and fast-rotation hint conflicts, wrong initial tilt without/with verified static recovery, and in-tolerance constant acceleration.
- [x] **Step 2: Run the focused regressions and verify RED.** The PR 1 parent failed on the first false-hint assertion: gravity updates were applied despite 0.4 g lateral acceleration.
- [x] **Step 3: Implement the smallest safe consistency gate.** A supplied hint is usable only when the current sample passes configured accel-norm, gyro, and accel-step bounds. Conflicts are counted; constant in-tolerance acceleration remains ambiguous.
- [x] **Step 4: Run the focused regressions and Bundle B/C.** All focused regressions and normal Bundle B/C suites passed; confirmed recovery works and ambiguity remains explicit.
- [x] **Step 5: Document health semantics.** `Health` tracks alignment, continuity, and numeric/input faults; `control_state_valid()` indicates freshness/availability. Neither certifies accuracy, observability, or control safety. This is now stated beside the public API.
- [x] **Step 6: Commit the recovery guard, tests, and contract.**

### Task 3: Bias, yaw-gauge, sign, and lifecycle audit

**Files:**
- Modify: `tests/test_math.cpp`
- Modify: `tests/test_eskf15.cpp` or `tests/test_pr2_recovery.cpp`
- Modify: `remediation/ROOT_CAUSE_MATRIX.md`

**Interfaces:**
- Consumes: exact right-reset and stationarity-conflict APIs from Tasks 1–2.
- Produces: PR 2 evidence for right-error F/H, gravity tangent rank, quaternion sign invariance, yaw-gauge behavior, slow yaw, changing bias, restart, and false-hint limitations.

- [x] **Step 1: Add tests for quaternion `q` versus `-q`, tilted yaw finite differences, gravity Jacobian tangency/rank-two behavior, changing bias with and without trusted heading, slow yaw, and repeated reset/reinitialization.** Each test must assert availability separately from accuracy and keep yaw/position observability limitations explicit.
- [x] **Step 2: Run new tests first and inspect any failure.** Expected: existing finite-difference math remains within established tolerances; any failure is investigated before changing code.
- [x] **Step 3: Make only test-supported fixes, each with a new RED→GREEN cycle.** Do not convert a physical ambiguity into a software accuracy claim. No estimator change was justified by the audit tests; the exact reset and false-hint guard remain the only PR 2 algorithm changes.
- [x] **Step 4: Run the full A/B/C host and sanitizer suites.** Expected: all six commands pass.
- [ ] **Step 5: Commit the audit tests and root-cause updates.**

### Task 4: Development comparison, candidate freeze, and untouched confirmation

**Files:**
- Create: `benchmarks/scenarios/pr2_confirmation_protocol_v2.json`
- Create: `tools/pr2_confirmation.cpp` and a reproducible runner/validator if needed
- Create: `benchmarks/manifests/pr2_candidate_protocol_v2.json`
- Create: `benchmarks/reports/pr2_candidate_comparison_protocol_v2.csv`
- Create: `remediation/PR2_RESULTS.md`
- Modify: `remediation/ROOT_CAUSE_MATRIX.md`, `remediation/RESOURCE_BUDGETS.md`

**Interfaces:**
- Consumes: PR 1 frozen inputs/definitions and the candidate source SHA from Tasks 1–3.
- Produces: paired baseline/candidate metrics for all four PR 1 core scenarios, three noisy modes, development seeds 101–116 during development, and a new disjoint confirmation set (seeds 2001–2016) evaluated only after candidate freeze. Also compare the existing six Bundle B scenarios with a separately designated development seed.

- [x] **Step 1: Freeze the new confirmation seed list and scenario configuration without running it.** Hash and commit the configuration; record that PR 1 held-out seeds are exposed and excluded from candidate selection. Config SHA-256: `bfcc898a3af18cb7a5a0f47f1af1a89b51dcc74033fa2ea002e5bd24881b7d57`, commit `37ae832`.
- [x] **Step 2: Compare candidates only on development inputs and the existing six Bundle B scenarios.** Report paired availability, tilt/yaw/p95/max, bias, aid counts, and health for all relevant modes; select one candidate without looking at confirmation results. PR 1 development and Bundle B seed `20261111` comparisons are recorded; candidate selection is the independently validated exact-reset/stationarity-guard source. Legacy and synthetic-heading trade-offs remain open and disclosed.
- [ ] **Step 3: Commit the candidate SHA and evaluator before acceptance.**
- [ ] **Step 4: Run the new confirmation set once against the frozen PR 1 parent and candidate using identical raw inputs.** Validate sample hashes and expected denominators. Do not tune on this set. If results guide a revision, mark it exposed and require a new disjoint set.
- [ ] **Step 5: Run all six A/B/C host/sanitizer checks and available target builds.** Report branch ARM cross-build as `NOT_RUN` if the pinned SDK/toolchain remains unavailable; do not substitute the base CI result.
- [ ] **Step 6: Finalize PR 2 root-cause, resource, and stacked-branch handoff documents; commit the result.**
