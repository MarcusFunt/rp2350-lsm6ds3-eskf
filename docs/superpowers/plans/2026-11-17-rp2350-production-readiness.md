# RP2350 Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the RP2350 + original LSM6DS3 estimator firmware from experimental status to a release candidate with measured accuracy, calibrated inputs, qualified acquisition/timing, and verified fault behavior.

**Architecture:** Use the selected two-stage scope: first qualify this repository as an estimator module, then apply a separate system gate to any downstream controller or actuator integration. Freeze the current evidence, define application-specific limits before tuning, select the estimator from paired held-out evidence, and qualify the chosen implementation on physical hardware. Keep the existing fault latch and stale-output suppression throughout.

**Tech Stack:** C++17, Raspberry Pi Pico SDK 2.2.0, RP2350/Pico 2, original LSM6DS3 (`WHO_AM_I=0x69`), native GCC, Python benchmark/replay tools, logic analyzer, and independent attitude reference.

**Spec:** [REVIEW_2026.md](../../../REVIEW_2026.md), [HARDWARE_VALIDATION.md](../../../remediation/HARDWARE_VALIDATION.md), [PR3_STATUS.md](../../../remediation/PR3_STATUS.md), and [PR4C_STATUS.md](../../../remediation/PR4C_STATUS.md). Scope selected: estimator-module qualification followed by a separate system gate for controller or actuator use.

## Global Constraints

- Do not treat synthetic replay, BROAD data, host tests, or a target cross-build as physical hardware qualification.
- Keep the active LSM6DS3 profile at ±4 g and ±245°/s unless the actual sensor configuration and product requirements justify a change.
- Keep fault latches, explicit reset/re-alignment, and stale-output suppression; do not republish the last finite quaternion as current after a fault.
- Keep FIFO disabled by default until physical timing, loss, and reset behavior pass on the original LSM6DS3.
- Do not label yaw, position, or velocity as observable from the six-axis IMU alone.
- Do not freeze the estimator or numeric acceptance limits until intended use and measurable requirements are recorded.

## Review Focus

- **Dropped, duplicated, reordered, or overwritten samples:** require hardware sequence/timestamp evidence and explicit accounting for every discard, reset, and overrun.
- **Range mismatch or clipping:** test register readback, raw conversion, per-axis thresholds, and fault behavior at configured limits.
- **Startup during motion or apparent gravity from acceleration:** test false stationary hints, zero dwell, lateral acceleration, and wrong initial tilt.
- **Temperature and bias drift:** characterize real-device scale, bias, cross-axis error, and noise before setting calibration and covariance values.
- **Stale output and recovery:** verify frozen sensors, bad clocks, bus errors, and explicit reinitialization cannot expose an old state as current.

---

## Current Gate Snapshot

| Area | Current evidence | Gate status |
|---|---|---|
| Host software and target builds | Firmware SHA `03b9c92a4ac0216619bdb10d0e208e02875964e4` passed Bundle A/B/C, sanitizer and protocol checks plus pinned Pico SDK 2.2.0 direct-register, FIFO and binary-log/FIFO builds in CI run `44140505599`. | Engineering build pass; physical device qualification remains open. |
| Synthetic coverage | PR3 v5 full-factor development, held-out, and final sets cover eight scenarios, three rates, two stress modes, and seven profiles. Every expected covariance check passed. | Coverage pass; accuracy/consistency and independent review remain open. |
| Estimator choice | VQF beat ESKF tilt RMS on all 39 BROAD trials (mean 0.69° vs 4.27° using BROAD-specific range settings). VQF’s small synthetic head-to-head showed 8.615° on stationary gyro bias and 5.548° on lateral acceleration. | Promising, not a universal winner; require product-relevant paired acceptance before promotion. |
| ESKF gravity-gate candidate | The 0.48 rad/s / 7-sample relaxation regressed held-out mean tilt RMS by 1.399°; maneuver, timing-jitter, and stop/start regressed substantially. | Rejected; retain production gate. |
| Fault handling | Latch/reset/stale-output behavior passed host lifecycle tests and candidate-setting fault injection. | Host pass; retain and repeat on hardware. |
| Calibration | Firmware uses identity calibration and `calibration_id=0`. | Open; runtime output is intentionally not production-calibrated. |
| Acquisition and timing | Direct-register DMA is default; FIFO is opt-in. Physical SPI/DRDY/FIFO captures and loss measurements are absent. | Hardware blocked. |
| Resource budget | Prior image sizes and stack-use reports exist. ESKF’s largest individual frame is 9,496 B against a 16,384 B core-1 stack; call-chain and on-device high-water are unknown. | Build evidence only; define budgets and measure on device. |
| Source/evidence baseline | Firmware SHA `03b9c92a4ac0216619bdb10d0e208e02875964e4` implements the range profile, raw-range fault propagation, binary-log status replay, and regression tests; the evidence ledger ties it to the exact target run. Experiment manifests remain bound to their recorded earlier analysis baseline. | Engineering source snapshot is frozen and CI-verified; product limits, calibration, physical evidence and release approval remain open. |

## Tasks

### Task 1: Define the release target and measurable requirements

**Files:**
- Create: `docs/production/PRODUCT_REQUIREMENTS.md`
- Create: `docs/production/PRODUCTION_GATE.md`
- Reference: `README.md`, `REVIEW_2026.md`, `remediation/HARDWARE_VALIDATION.md`

**Interfaces:**
- Produces: an approved requirements table used by algorithm, hardware, and release gates.

- [x] Record the selected two-stage boundary: qualify the estimator module first, then apply a separate gate to controller/actuator use. Exact consumer, users, board/sensor identity, operating envelope, and deployment environment remain open.
- [ ] Set numeric limits for sample rate, orientation error (RMS/p95/maximum), output age, startup/alignment, recovery, uptime, temperature, and resource/deadline margins. Mark each value as required, measured, or provisional; do not derive acceptance numbers from the existing 100 ms diagnostic threshold.
- [x] Define observable output fields. Six-axis absolute yaw and IMU-only position/velocity remain unavailable unless an independent aid is specified.
- [ ] Define the production release gate as explicit pass/fail criteria with an owner for every threshold and a named independent reviewer.

**Acceptance:** no tuning or production claim proceeds with unresolved numeric limits or an unknown consumer safety role.

### Task 2: Reconcile evidence and freeze a release baseline

**Files:**
- Create: `docs/production/EVIDENCE_LEDGER.md`
- Modify: `remediation/ROOT_CAUSES.md`, `remediation/PR2_RESULTS.md`, `remediation/PR3_STATUS.md`, `remediation/PR4C_STATUS.md`, `README.md`
- Review without discarding: `main.cpp`, `CMakeLists.txt`, `lsm6ds3_config.hpp`, `tests/test_lsm6ds3_config.cpp`, current untracked B9 and gravity-gate evidence.

**Interfaces:**
- Consumes: Task 1 requirements.
- Produces: one source SHA, one evidence ledger, and an unambiguous list of open/closed gates.

- [x] Inventory the current worktree and attribute each existing modification/untracked file; preserve it and do not silently reset, overwrite, or include unrelated work.
- [x] Rerun Bundle A/B/C host checks on the current candidate worktree; record toolchain and results.
- [x] Run pinned target CI against exact engineering firmware SHA `03b9c92a4ac0216619bdb10d0e208e02875964e4` (run `44140505599`); record SDK, build variants, artifacts, resource estimates, and hashes.
- [x] Include `tests/test_lsm6ds3_config.cpp` in `tools/run_bundle_c_checks.sh` with the repository include path so range/register/conversion coupling is exercised in normal and sanitizer CI.
- [x] Resolve stale or conflicting status statements. Keep historical reports immutable and add a current summary that distinguishes historical build passes from the current release candidate.
- [x] Freeze engineering source/evidence baseline firmware commit `03b9c92a4ac0216619bdb10d0e208e02875964e4` after closing the raw-range and binary-replay review findings, validating the evidence manifests, and passing exact-source target CI. No production release tag is created.

**Acceptance:** all release artifacts identify the same source SHA; every gate is `PASS`, `OPEN`, or `BLOCKED` with evidence and an owner.

### Task 3: Select and integrate the production estimator

**Files:**
- Modify if selected: `main.cpp`, `CMakeLists.txt`, `FusionEstimate` publication and associated headers.
- Add/modify: pinned estimator source/license, algorithm regression tests, and benchmark manifests under `external_benchmarks/` and `remediation/analysis/`.

**Interfaces:**
- Consumes: Tasks 1–2 requirements and frozen baseline.
- Produces: one production estimator and a documented output/health contract.

- [ ] Before selecting, compare the current Conservative ESKF, VQF full 6D, and the existing Mahony reference on identical samples and valid timestamps across the complete synthetic set, fresh held-out seeds, all 39 BROAD trials, and fault cases. Retain BROAD’s sensor range only in BROAD replay configuration.
- [ ] Report tilt, full attitude with startup yaw gauge aligned, p95/max error, availability, timing sensitivity, startup/recovery, and fault/stale outcomes. Use the Task 1 limits; publish per-scenario results so gains cannot hide critical regressions.
- [ ] Decide whether ESKF-only state/covariance/nav telemetry is removed or retained as non-authoritative shadow output. VQF does not estimate ESKF position, velocity, accelerometer bias, or covariance.
- [ ] If VQF is selected, pin the official version and license, implement a fixed-rate/timestamp-gap wrapper, and test invalid timestamps, non-finite/range inputs, fault latch, reset/re-alignment, and stale-output withholding before wiring it into `core1_fusion()`.
- [ ] Do not promote the rejected ESKF gate relaxation. Keep the existing fault latch and stale-output behavior unless a replacement passes the same regression matrix and has a documented safety case.

**Acceptance:** the selected algorithm passes every predeclared performance and availability limit; no critical scenario is hidden by pooling or by intersecting away unavailable outputs.

### Task 4: Close estimator-specific software acceptance gaps

**Files:**
- Modify as needed: `eskf15.hpp`, `tests/test_pr2_recovery.cpp`, `tests/test_eskf15.cpp`, `tools/pr3_*`, `remediation/PR2_RESULTS.md`, `remediation/PR3_STATUS.md`.

**Interfaces:**
- Consumes: Task 3 estimator choice. ESKF-only findings are release-blocking only if ESKF remains in the production path.

- [ ] Add frozen held-out cases for false external-stationary hints and `static_min_samples=0`; pin expected rejection and no unintended gravity/zero-rate bias update.
- [ ] Resolve or explicitly exclude LegacyHeuristic yaw/bias regressions and synthetic heading-aid degradation from the production build; do not treat successful covariance checks as accuracy acceptance.
- [ ] Re-run the broad suite after any algorithm change using a fresh confirmation set, including maneuver, timing jitter, compound motion, stop/start, bias, lateral acceleration, vibration, and stress profiles.
- [ ] Obtain independent mathematical and code review of estimator equations, observability, covariance consistency, and failure behavior; close or disposition each PR2/PR3 open finding.

**Acceptance:** production-enabled modes have no open correctness defects; held-out accuracy/consistency gates pass their declared limits; review findings are closed or formally accepted with scope and rationale.

### Task 5: Calibrate the actual sensor and lock configuration

**Files:**
- Modify: `calibration.hpp`, `lsm6ds3_config.hpp`, `main.cpp`, `tests/test_lsm6ds3_config.cpp`, `remediation/HARDWARE_VALIDATION.md`.

**Interfaces:**
- Consumes: exact production board, sensor marking, Task 1 operating envelope, and Task 3 estimator.
- Produces: versioned sensor calibration and a verified register-to-units configuration.

- [ ] Measure gyro/accelerometer bias, scale, cross-axis alignment, temperature response, and noise for the production sensor/board over the operating range; collect stationary Allan-deviation data to set noise and bias-walk values.
- [ ] Create a versioned calibration record and manufacturing/replacement procedure. Set a nonzero calibration ID only for validated parameters; retain a loud invalid/unverified state otherwise.
- [ ] Verify active full-scale and ODR readback, raw-to-SI conversions, axis mapping, and per-axis fault thresholds against the exact LSM6DS3 configuration. Test unsupported profiles and boundary values.

**Acceptance:** independent calibration data and uncertainty are recorded and replayable; runtime health cannot report production availability with identity/unverified calibration.

### Task 6: Qualify acquisition and timestamp integrity on hardware

**Files:**
- Modify as needed: `main.cpp`, `drdy_period.pio`, `lsm6ds3_fifo.hpp`, `tests/test_bundle_c.cpp`, `remediation/HARDWARE_VALIDATION.md`.

**Interfaces:**
- Consumes: production board/sensor, locked range/ODR, and release timing limits.
- Produces: selected acquisition mode and physical capture evidence.

- [ ] Capture DRDY, chip-select, SPI clock, DMA service, and sequence/timestamp data with a logic analyzer under nominal load, host delay, and deliberate overload.
- [ ] Compare direct-register DMA and FIFO modes during rest, controlled rotation, acceleration, FIFO watermark, and overflow. Quantify reconstructed FIFO timestamp uncertainty against measured DRDY edges.
- [ ] Require zero unaccounted duplicate/reordered samples and explicit accounting of every missed edge, queue drop, FIFO discard/reset, or overrun. Confirm no old register snapshot is assigned to a newer edge.
- [ ] Keep FIFO disabled by default if it fails physical qualification; select the path that meets the Task 1 age/loss limits.

**Acceptance:** selected path passes the complete acquisition matrix on the exact sensor variant with raw captures, analysis commands, firmware SHA, and uncertainty bounds archived.

### Task 7: Measure target resource, timing, and soak behavior

**Files:**
- Modify: `.github/workflows/ci.yml`, `tools/report_firmware_resources.py`, `remediation/RESOURCE_BUDGETS.md`, `remediation/HARDWARE_VALIDATION.md`.

**Interfaces:**
- Consumes: selected algorithm, acquisition mode, SDK/toolchain, and Task 1 deadlines.
- Produces: release-specific flash/RAM/stack/timing budget and on-device measurements.

- [x] Build engineering firmware SHA `03b9c92a4ac0216619bdb10d0e208e02875964e4` with pinned Pico SDK 2.2.0 and ARM toolchain for direct-register, FIFO, and binary-log/FIFO variants; retain and hash ELF/UF2, map, `.su`, and resource reports. Production mode remains unselected.
- [ ] Measure core-0 and core-1 stack high-water, complete call-chain margin, fusion p50/p95/p99/max, end-to-end sample age, queue peaks/drops, missed deadlines, and idle/load behavior on hardware.
- [ ] Address the current ESKF estimate of a 9,496 B largest frame against a 16,384 B core-1 stack; static frame subtraction is not a whole-call-chain guarantee. Recompute budgets for the selected estimator.
- [ ] Run a temperature-aware, multi-hour soak with production logging configuration and verify reset, disconnect/reconnect, watchdog, and overload behavior.

**Acceptance:** all measured values meet Task 1 limits with documented margin; no production decision relies on host wall-clock or compiler frame estimates alone.

### Task 8: Validate faults, stale output, reset, and consumer behavior

**Files:**
- Modify: `runtime_health.hpp`, `main.cpp`, `tests/test_b9_fault_recovery.cpp`, `tests/test_bundle_c.cpp`, `remediation/analysis/fault_recovery_b9/FAULT_RECOVERY_B9.md`.

**Interfaces:**
- Consumes: selected estimator and hardware-qualified sample path.
- Produces: documented module-level fault and recovery contract.

- [ ] Retain tests for short gaps, duplicates/regressing time, overrange, long gap, non-finite input, bus failure, frozen sensor, queue overflow, explicit reset, and re-alignment.
- [ ] Verify every fault withholds current output immediately, leaves its state timestamp at the last valid sample, and prevents a prior finite quaternion from appearing fresh.
- [ ] Exercise the same cases on hardware and verify downstream consumers see health, freshness, reset-required, calibration ID, and observability metadata.
- [ ] If connected to a controller, add a separate system test proving controller transition to its approved safe mode on invalid/stale/reset-required output; module health alone is not a safety action.

**Acceptance:** fault behavior matches the contract in host and device tests; reset never silently restores old pose or nominal availability.

### Task 9: Independent release review and production handoff

**Files:**
- Create: `docs/production/RELEASE_CHECKLIST.md`, release manifest, calibration procedure, and operator/recovery guide.
- Modify: `README.md` and current remediation status summaries.

**Interfaces:**
- Consumes: all prior task evidence and final candidate SHA.
- Produces: signed gate decision and reproducible release package.

- [ ] Freeze a release candidate; rerun required host, sanitizer, benchmark, target-build, and on-device suites from that exact SHA.
- [ ] Obtain independent review of source, requirements traceability, test evidence, calibration, resource margins, failure handling, licenses, and build provenance.
- [ ] Package firmware binaries and hashes, source SHA, SDK/compiler versions, board/sensor revision, calibration ID, configuration, test/capture evidence, known limitations, update/rollback procedure, and owner sign-offs.
- [ ] Mark the module gate `PASS` only when every required criterion is met. If this firmware feeds an actuator, hold the system gate open until a separate controller hazard/safe-state and end-to-end deadline review passes.

**Acceptance:** another engineer can reproduce the release build, identify the exact sensor/calibration/configuration, and trace each production requirement to measured evidence and an approving owner.

## Execution Order and Decision Points

1. Complete Tasks 1–2 before tuning or claiming a production baseline.
2. Complete Task 3 before production algorithm integration; if no candidate meets limits, keep the firmware experimental and continue estimator work.
3. Run Tasks 4–8 in dependency order, allowing Tasks 5–7 to proceed in parallel once the exact sensor/board and release limits are fixed.
4. Complete Task 9 as the final gate. A module pass does not imply controller or actuator safety approval.

## Completion Gate

The current project is **not production-ready**. The gate can change to `PASS` only after requirements are numeric and owned; selected estimator evidence passes fresh held-out and recorded-data acceptance; calibration is measured and versioned; physical acquisition/timestamps and resource margins pass on the exact board/sensor; fault/stale/reset behavior passes on device; all required builds and independent reviews pass; and the release package is reproducible. Controller/actuator use requires the additional system gate described above.

## Native execution status — 2026-11-17

| Task | Status | Evidence / remaining work |
|---|---|---|
| 1. Product requirements | `OPEN` | Two-stage boundary and output observability are recorded. Numeric limits, exact user/environment, and named approvals remain open. No Pico/LSM6DS3 device was detected in this session. |
| 2. Evidence baseline | `PASS` for engineering source baseline | Firmware commit `03b9c92a4ac0216619bdb10d0e208e02875964e4`; native-session host/sanitizer and exact-source CI run `44140505599` passed. No production release tag. |
| 3. Estimator selection | `OPEN` | Existing BROAD and synthetic evidence is characterized; product limits and selection acceptance are still open, so no estimator is promoted. |
| 4. Estimator software gaps | `OPEN` | Existing targeted regressions pass; ESKF is not selected for production and independent mathematical/code review remains outstanding. |
| 5. Calibration | `BLOCKED_HARDWARE` | No validated physical device calibration or verified sensor identity/calibration ID. |
| 6. Acquisition | `BLOCKED_HARDWARE` | No production board/logic-analyzer capture or physical loss/timestamp evidence recorded. |
| 7. Resources and timing | `OPEN` build / `BLOCKED_HARDWARE` measurement | CI artifacts and estimates are recorded; stack high-water, end-to-end timing, queue margins, and soak require device measurements and product limits. |
| 8. Fault/recovery | `OPEN` host / `BLOCKED_HARDWARE` device | Host lifecycle protections remain and tests pass; physical injection and consumer behavior remain unverified. |
| 9. Release handoff | `OPEN` | Draft checklist exists; independent review, signoffs, final package, calibration and device evidence remain. Stage 2 is separate if controller/actuator use applies. |
