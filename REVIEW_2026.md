# Sensor Fusion 2026 report → RP2350 / LSM6DS3 engineering audit

Review basis: **Sensor Fusion for Attitude and Navigation — Research-Expanded Publication Edition, 7 November 2026**, 35 pages, uploaded by the user. This document distinguishes **report recommendations** from **verified code changes** and **work requiring hardware evidence**.

## Architecture decision

The report's executive decision (p. 3) recommends a deterministic ESKF for control-centric vehicles, with optional external aiding. For navigation-centric robots it recommends a *graph-owned* tightly-coupled local smoother with high-rate IMU prediction. Independent full ESKF and independent VIO/graph pipelines must not blindly fuse IMU-derived pose outputs as statistically independent (pp. 12, 14–16). **Decision:** RP2350 remains a single authoritative on-board ESKF. A separate companion VIO can supply carefully managed external measurements later, but it is not fused in this revision. No fictitious graph backend has been added.

## Prioritized findings and applied changes

| Rank | Report basis | Defect in previous firmware | Applied change | Verification / residual limitation |
|---|---|---|---|---|
| P0 | pp. 6, 10, 23: accelerometers measure specific force; motion/gravity ambiguity | First valid acceleration vector immediately set tilt | 80-sample quasi-static startup gate; explicit `Aligning` state | Synthetic moving-start fixture passes; constant acceleration remains fundamentally ambiguous |
| P0 | pp. 16, 22–23: correct measurement time and health | Aiding APIs accepted any implicitly 'current' input | `_at(AidingStamp)` position/velocity/heading/ZUPT/ZARU, source/calibration IDs, reject future/stale (>1ms) | Host tests pass; no historical rewind, cross-core aid queue or VIO correlation handling |
| P0 | pp. 22–23: sample gaps, saturation, numerical integrity | Long gaps were ignored without growing uncertainty | gap detection, heuristic extra covariance, stale state timestamp preserved, saturation fault, sticky health | Host tests pass; outage motion cannot be reconstructed |
| P1 | pp. 6, 10, 11: gravity vector is not unrestricted attitude reference | Three-axis magnitude gravity pseudo-update | Normalized two-DOF direction update; tangent-space bias Jacobian | Synthetic 10° tilt test passes; false-gravity under steady acceleration still possible |
| P1 | pp. 13, 23, 28–29: numerical robustness, NIS/NEES | Inverse innovation covariance via Gauss-Jordan; reject count only | SPD Cholesky innovation solve, NIS exposure, covariance PD diagnostic, acceptance/reject counts | Synthetic covariance check passes; NEES requires independent truth and is not implemented |
| P1 | pp. 15–16: timebase, provenance and state publication | No availability vs estimate timestamp distinction | state-time vs received-time, publication time, source/timebase/calibration metadata, max processing time, output age | Instrumented in C++; hardware timing remains unmeasured |
| P1 | pp. 28–31: replay and reproducible tests | Tests existed but no CSV replay executable | Offline deterministic sample replay, synthetic fixture, expanded host tests | Passes host tests; fixture not actual IMU dataset |

## Explicitly NOT implemented

- **FIFO and lossless IMU acquisition:** raw SPI register snapshots can be overwritten under CPU/USB load; PIO edge counts do not reconstruct missing sensor measurements (pp. 20, 26–29).
- **Coning/sculling/scrolling corrections:** the report derives their importance (p. 7) for high dynamic multi-axis motion. The current estimator uses simple per-sample quaternion exponential and midpoint integration; test against a high-rate reference before extending.
- **Calibration and noise identification:** actual LSM6DS3 Allan deviation, thermal bias, axis misalignment, per-sample calibration ID and real uncertainty scaling are not measured (pp. 20, 22, 28).
- **Delayed fusion of out-of-sequence camera/encoder measurements:** report requires synchronized clocks and bounded replay with covariance ownership (pp. 15–16, 22, 30). The implementation correctly rejects stale data instead of applying them at the wrong state time. This is protective, not a complete multisensor solution.
- **Observability-consistent VIO/MSCKF or factor graph:** outside the scope of Cortex-M33 six-axis module; report provides conditional recommendations, not a requirement to put an optimizer in this MCU (pp. 3, 11–16).
- **NEES/real accuracy validation and hardware acceptance:** no independent ground truth or physical RP2350 tests have been performed. Tests here validate code behavior, not demonstrated state-estimation accuracy.
- **Automatic safe flight controller behavior:** filter exposes health but cannot independently enforce motor/controller shutdown, controller reset coordination or safe estimator arbitration (p. 23).

## Remaining scientific risk

The dominant **physics risk** is treating a quasi-static accelerometer as gravity during motion; the gate is heuristic. The dominant **integration risk** is stale/correlated external aiding. The dominant **hardware risk** is dropped and overwritten IMU samples with an unverified PIO/software-epoch timestamp. The dominant **statistics risk** is default noise assumptions not validated by measured Allan deviation, NIS/NEES or external truth.

## Acceptance gates for the next revision

1. Full Pico SDK cross-build, then measured GPIO/PIO/SPI event intervals and DMA latency with a logic analyzer; report p50/p99/max age and missed samples.
2. Test LSM6DS3 FIFO on watermark and overflow under intentionally delayed DMA/USB load. Reject stale samples rather than associating a newer register snapshot with an older edge.
3. 10–30-minute stationary logs across temperatures; compare Allan-deviation-fitted continuous noise densities and discrete covariance scales.
4. Controlled multi-axis rotation, sustained lateral acceleration and coning-like trajectories with independent attitude ground truth; compare baseline Mahony versus ESKF at matched sensor timestamps.
5. Independent external aiding with correct frames and calibration, timebase offset/drift tracking, delayed-state buffer and covariance-consistent updates; measure NIS/NEES against physical truth before claiming improved navigation.
6. Fault injection (missing samples, saturation, frozen sensor, reversed clock, duplicate frames, overload) and explicit control-side safe-mode integration.

No tests in this package meet those physical/hardware gates yet.
