# B9 BROAD Failure Atlas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a timestamp-matched BROAD comparison, explain the three specified PR3 synthetic losses with diagnostics, and validate the ESKF fault/reinitialization contract.

**Architecture:** A Python HDF5/VQF orchestrator writes one normalized sample stream per trial and invokes a small C++ replay of the production `Eskf15`. The orchestrator retains default-range and BROAD-range ESKF outputs, computes paired metrics only on common valid movement timestamps, and writes compact evidence and SVGs. A second analysis driver reuses the frozen PR3 v5 generator/evaluator to produce selected sample traces for the three synthetic cases.

**Tech Stack:** Python 3.10+, `h5py`, NumPy 2.0.2, VQF 2.1.2, C++17/g++, standard-library CSV/JSON/SVG.

**Spec:** `docs/superpowers/specs/2026-11-17-b9-broad-and-recovery-design.md`

## Global Constraints

- Do not modify production LSM6DS3 range defaults.
- Use only 6D gyro/accelerometer inputs for both estimators.
- Score motion only where the official BROAD `movement` flag is true.
- Keep every paired score on the exact valid timestamp intersection and report both availability masks.
- Use PR3 v5 development seed 4001 only for selected mechanism traces; keep acceptance evidence immutable.
- Keep downloaded BROAD raw data outside the repository and cite its source revision/license.

## Review Focus

- HDF5 trials with malformed, non-finite, or shape-mismatched arrays must fail with a trial-specific error.
- Input range checks are per sensor axis and distinguish a true configured-range exceedance from a vector-norm event.
- ESKF initialization samples and VQF outputs are not paired until both estimators have a valid orientation at the same timestamp.
- A faulted ESKF output with an old state timestamp must be marked unavailable, even if its last quaternion is finite.
- Missing diagnostic values remain blank/null; they are never converted to zero for plots or summaries.

---

### Task 1: Add the native ESKF replay and fault contract checks

**Files:**
- Create: `tools/b9_eskf_replay.cpp`
- Create: `tests/test_b9_fault_recovery.cpp`

**Interfaces:**
- Replay consumes a CSV of ordered `(sample_index, timestamp_us, valid, accel_xyz_mps2, gyro_xyz_rad_s)` records and emits one row per input with quaternion validity, health, reset requirement, state timestamp, bias, attitude covariance diagonal, and gravity innovation/gate diagnostics.
- Range profile is a closed CLI choice: both profiles use BROAD's `expected_period_us=3500`; `lsm6ds3` preserves the default axis limits, while `broad` applies `±0.98*2000°/s` and `±0.98*16g`.

- [x] Write the C++ contract checks for default-range latch, no implicit recovery, stale output invalidation, reset/re-alignment, and BROAD-range acceptance of 500°/s.
- [x] Compile and run the new test against the current header to record the expected lifecycle behavior.
- [x] Write a smoke test for the replay input/output row count, per-axis range profile, and diagnostic fields.
- [x] Implement the replay CLI with the production filter and `INERTIAL_GRAVITY_DIAGNOSTICS` enabled.
- [x] Re-run the recovery and replay checks; verify the production header remains unchanged.

### Task 2: Build the BROAD matched-interval atlas

**Files:**
- Create: `scripts/run_b9_broad_failure_atlas.py`
- Create: `tests/test_b9_broad_failure_atlas.py`
- Create: `remediation/analysis/b9_broad_failure_atlas/`

**Interfaces:**
- CLI accepts `--dataset-dir` (official `data_hdf5` directory), `--output-dir`, compiler path, and optional trial filters.
- Per-trial output records the raw HDF5 SHA-256, VQF B3 identity/config, ESKF settings/range profile, exact valid timestamp counts, movement-only paired scores, first fault, and range-crossing counts.

- [x] Write failing tests for strict sample/timestamp validation, exact intersection masks, first-common-sample yaw gauge alignment, and no scoring outside movement or estimator validity masks.
- [x] Implement the HDF5 loader and timestamp/sample validation for all required BROAD arrays.
- [x] Run official VQF 6D and the native ESKF on the exact same ordered gyro/accelerometer records.
- [x] Preserve the default-range ESKF as a fault control and use the documented BROAD full-scale only for the corrected comparison.
- [x] Generate per-trial summary CSV/JSON, range-fault inventory, and orientation-error SVGs for all 39 trials, with detailed traces only for selected high-rate failures.
- [x] Run the loader/matching tests and the complete 39-trial experiment; independently verify sample counts, hashes, and movement masks.

### Task 3: Add selected traces for the three synthetic weaknesses

**Files:**
- Create: `tools/pr3_synthetic_weakness_atlas.py`
- Create: `tests/test_pr3_synthetic_weakness_atlas.py`
- Create: `remediation/analysis/pr3_synthetic_weaknesses_b9/`

**Interfaces:**
- CLI defaults to `maneuver,timing_jitter,compound_motion`, seed 4001, uniform 208 Hz, nominal/stress, and writes selected ESKF/Mahony traces, mechanism summaries, and SVG figures.
- Input hashes and trial metrics must match the frozen PR3 v5 development archive before traces are reported.

- [x] Write failing checks for scenario coverage, archive pairing, trace row/timestamp alignment, and preservation of gate/NIS/bias/covariance fields.
- [x] Reuse the protocol v5 generator/evaluator without modifying frozen protocol or archive artifacts.
- [x] Join truth and shared ESKF/Mahony sample outputs; calculate time-aligned tilt/geodesic errors and bias errors.
- [x] Summarize accepted/rejected gravity updates, rejection reasons, NIS, covariance growth, and first/maximum loss windows.
- [x] Generate per-case diagnostic plots and a short report distinguishing confirmed mechanisms from hypotheses.
- [x] Verify each selected input hash and trial metric against the archive and run the focused Python checks.

### Task 4: Document and verify recovery decisions

**Files:**
- Create: `remediation/analysis/fault_recovery_b9/FAULT_RECOVERY_B9.md`
- Modify: `README.md` only if the final result changes user-facing runtime guidance.

- [x] Use the Task 1 results to classify invalid timestamp, recoverable short gap, long gap, non-finite sample, configured-range exceedance, reset, and stale-publication behavior.
- [x] Explain that a new full-scale setting must match the sensor that produced the data and that `reset()` preserves settings while restarting alignment.
- [x] Verify runtime-health output is unavailable on fault/stale state and becomes available only after fresh, current, nominal, calibrated output.
- [x] Record tests/commands and state explicitly whether any production recovery code change was supported by the evidence.
