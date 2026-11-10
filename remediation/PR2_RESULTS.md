# PR 2 — Numerical model and recovery results

**Branch:** `fix/eskf-math-recovery`, stacked on PR 1 `b749a8aa0e40718ab7b163cad29d9c550b088265`.

**Current candidate:** revision 1, source/evaluator freeze `55eed3252e3e2af72bd61be66aa14501d9f17399`; candidate `eskf15.hpp` SHA-256 `0bbd516252edbc4a58799bc52bf80b17dada9bc8daade13f50b0657ba02bf05a`.

**Current result:** the revision-1 paired confirmation passed pairing, fixed-denominator, completeness, availability, and final-health checks. The overall PR 2 pass gate remains **OPEN** because LegacyHeuristic yaw/bias regressions and synthetic-heading-aid degradation persist. The false-runtime-hint and zero-dwell guards have targeted regressions but are not exercised by the frozen seed matrix. Dependent performance claims remain blocked.

## Changes

- Replaced the first-order attitude covariance reset with the exact SO(3) right Jacobian for right-multiplicative quaternion injection, with a Taylor expansion near zero.
- Corrected the gravity accelerometer-bias Jacobian to use the measured unit-vector tangent projector at finite innovation. The old predicted-direction projector matched only at zero residual.
- Guarded external stationary hints against current accel-norm, gyro, and accel-step contradictions; zero dwell now requires at least one consistent sample.
- Clarified that `Health` represents alignment/continuity/numeric/input status and `control_state_valid()` represents freshness/availability. Neither certifies accuracy, observability, or control suitability.
- Added independent FP64 reset and finite-innovation Jacobian checks; quaternion sign, gravity tangent, tilted heading, false-hint, zero-dwell, changing-bias, slow-yaw, and repeated-reinitialization regressions.
- Added paired comparison and diagnostic tools. PR 2 v3 corrects the Bundle B scenario metadata from the immutable v2 configuration; the actual Bundle B run set was `static`, `slow_yaw`, `lateral_accel`, `maneuver`, `vibration`, and `timing_jitter`.

## Verification

All six Bundle A/B/C host and sanitizer suites passed against the revision-1 source before confirmation:

| Command | Result | Log |
|---|---|---|
| `./tools/run_bundle_a_checks.sh` | PASS | [Bundle A host](evidence/pr2_revision1_bundle_a_host.log) |
| `BUNDLE_A_SANITIZERS=1 ./tools/run_bundle_a_checks.sh` | PASS | [Bundle A sanitizers](evidence/pr2_revision1_bundle_a_sanitizers.log) |
| `./tools/run_bundle_b_checks.sh` | PASS | [Bundle B host](evidence/pr2_revision1_bundle_b_host.log) |
| `BUNDLE_B_SANITIZERS=1 ./tools/run_bundle_b_checks.sh` | PASS | [Bundle B sanitizers](evidence/pr2_revision1_bundle_b_sanitizers.log) |
| `./tools/run_bundle_c_checks.sh` | PASS | [Bundle C host](evidence/pr2_revision1_bundle_c_host.log) |
| `BUNDLE_C_SANITIZERS=1 ./tools/run_bundle_c_checks.sh` | PASS | [Bundle C sanitizers](evidence/pr2_revision1_bundle_c_sanitizers.log) |

The reset oracle reports a `0.042196347 rad` correction. Exact-reset block error is `7.09947786e-6`, compared with `2.20535708e-4` for the previous first-order reset. The full posterior covariance differs from the independent FP64 oracle by at most `0.00026823457` at `(1,1)`, within the test's declared tolerance.

The first finite-innovation bias-Jacobian test failed as expected: at identity attitude with measured direction `(0.15, 0, sqrt(1−0.15²))`, the old `H[x,baz]` was zero while `−dr[x]/dba_z` is about `−0.01512 (m/s²)⁻¹`. The corrected measured-direction projector passes with maximum finite-difference error `3.023e-5`.

The false-hint regression rejects 300 samples with 0.4 g lateral acceleration and 160 samples with 0.18 rad/s rotation. A separate regression enables `heuristic_zero_rate` and `static_min_samples=0`; it first reproduced the bypass, then passed after zero dwell was clamped to one consistent sample. A plausible 0.2 g wrong initial gravity direction remains more than `0.15 rad` wrong IMU-only after 500 samples while health/availability remain nominal; verified static aiding recovers below `0.06 rad`. Constant in-tolerance acceleration remains ambiguous.

## Development comparison and diagnostics

The original candidate's PR 1 development and Bundle B comparisons remain preserved in [the v2 manifest](../benchmarks/manifests/pr2_candidate_protocol_v2.json) and [the original paired report](../benchmarks/reports/pr2_candidate_comparison_protocol_v2.csv). That candidate was frozen at `60b967b`; the v2 confirmation seeds are now exposed and were not reused.

Revision 1 was compared on the same 192 development streams (seeds `101–116`), with 460,800 identical 40-byte IMU/heading records, hash `0cbd28d02f8405619f65c2df9391e9689e13c3f5caa4b3cf7c09d3d43a02fcca`. The full paired rows and input are [here](../benchmarks/reports/pr2_revision1_development_comparison_protocol_v2.csv) and [here](../benchmarks/reports/pr2_revision1_development_imu_samples_protocol_v2.bin). The diagnostic extractor is `tools/pr2_development_diagnostics.py`; its selected per-sample traces and summary are [CSV](../benchmarks/reports/pr2_revision1_development_diagnostic_traces_protocol_v2.csv) and [JSON](../benchmarks/reports/pr2_revision1_development_diagnostics_protocol_v2.json).

| Mode, 192 trials each | PR 1 parent | Revision-1 candidate | Availability / final-health differences |
|---|---:|---:|---:|
| Conservative, `IMU_ONLY/UNKNOWN`, tilt RMS mean | 0.096197° | 0.096197° | 0 / 0 |
| Conservative, `IMU_ONLY/UNKNOWN`, yaw RMS mean | 0.541892° | 0.542303° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, tilt RMS mean | 3.993426° | 3.706208° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, yaw RMS mean | 1.814867° | 2.032017° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, final gyro-bias error mean | 0.006051 rad/s | 0.007769 rad/s | 0 / 0 |

The seed-101 representative traces are diagnostic examples, not population estimates. In `lateral_accel_0p2g`, `IMU_ONLY`, `LegacyHeuristic`, combined noise, externally verified static startup, and calibration off, the candidate accepted 55 gravity updates during the 2–8 s acceleration and rejected 36 during 8–12 s recovery. Candidate tilt grew from `0.040°` at 2 s to `14.265°` at 8 s and `20.045°` at 12 s, with `15.048°` tilt RMS; software health remained `Nominal`. The final estimated gyro-bias error components were approximately `(-0.00248, 0.02554, -0.02111) rad/s`. Across this trace, tilt error correlated with gyro-bias error at `r=-0.584` for x, `-0.241` for y, and `-0.596` for z. This indicates coupling, not proof of a unique cause. Accepted gravity NIS had mean `1.440` and maximum `11.375`; rejected-update NIS and vector innovations are not serialized by the frozen trace writer.

In seed-101 pure roll, 11/11 synthetic heading updates were accepted (mean NIS `1.480`, maximum `6.671`). Yet aided candidate tilt/yaw RMS was `1.633°/2.108°`, versus `0.121°/0.236°` for IMU-only. Accepted NIS alone does not explain the degradation. The trace also shows `Nominal` health and 2,001/2,001 valid outputs in both cases.

## Confirmation records

### Original v2 confirmation — exposed

The original candidate frozen at `60b967b` was run once on seeds `2001–2016`; its immutable report, input, and index remain in the v2 manifest. Pairing passed for 192 streams, 3,456 rows, 460,800 records, and 2,001 samples per row. The results exposed LegacyHeuristic yaw/bias regressions and synthetic-heading-aid degradation, which motivated a mathematically independent review and a revised candidate. They were not reused for selection or retesting.

### Revision-1 v3 confirmation — run once

The revised candidate/evaluator freeze is `55eed3252e3e2af72bd61be66aa14501d9f17399`; the disjoint seed/config pre-registration is commit `754ee5a`, and the run manifest was committed at `1078d7339e08edab620ef88ee07483c7e4a671c0` before execution. Config SHA-256 is `cbf3f2e7687dc5485065ce0ca6cf5126e7cecf8f8443de0f44366bff878b0aa5`. Seeds `3001–3016` were then run exactly once against PR 1 and the frozen revision-1 candidate:

```bash
tools/run_pr2_comparison.sh \
  /mnt/c/Users/marcu/rp2350-eskf-pr1 \
  /mnt/c/Users/marcu/rp2350-eskf-pr2 \
  confirmation_v3 /tmp/pr2-confirmation-v3-3001-3016
```

The validator passed: 192 streams, 460,800 identical 40-byte records (18,432,000 bytes), 3,456 paired rows, 2,001 expected samples per row (6,915,456 total), no incomplete or stale rows, and zero paired availability or final-health differences. Shared input SHA-256 is `465b24049f99c9efd14dfe07b4c3f52913d5ce83cf5c63848a77e8987c9ac597`.

The revision-1 results are [the paired report](../benchmarks/reports/pr2_revision1_confirmation_comparison_protocol_v3.csv), [shared raw samples](../benchmarks/reports/pr2_revision1_confirmation_imu_samples_protocol_v3.bin), and [sample index](../benchmarks/reports/pr2_revision1_confirmation_sample_index_protocol_v3.csv). Their hashes and full seed/config provenance are in [the revision-1 manifest](../benchmarks/manifests/pr2_candidate_revision1_protocol_v3.json). Source and evaluator code did not change after freeze.

| Mode, 192 trials each | PR 1 parent | Revision-1 candidate | Availability / final-health differences |
|---|---:|---:|---:|
| Conservative, `IMU_ONLY/UNKNOWN`, tilt RMS mean | 0.100345° | 0.100342° | 0 / 0 |
| Conservative, `IMU_ONLY/UNKNOWN`, yaw RMS mean | 0.541742° | 0.541823° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, tilt RMS mean | 3.962734° | 3.728872° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, yaw RMS mean | 1.818205° | 2.025161° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY/UNKNOWN`, final gyro-bias error mean | 0.006159 rad/s | 0.007627 rad/s | 0 / 0 |

The largest individual LegacyHeuristic yaw-RMS increase was `7.891650°` (combined-noise lateral acceleration, seed `3009`). The revised candidate's pure-roll/combined-noise UNKNOWN-startup results also retain the synthetic-aid regression: candidate-only IMU-only mean tilt/yaw RMS was `0.183151°/0.914459°`; with the synthetic 1 Hz heading aid it was `3.089862°/1.732602°` over 16 seeds. All 176 scheduled heading updates were accepted and none rejected.

The v3 matrix does not inject a false runtime stationary assertion or set `static_min_samples=0`. Those paths have deterministic targeted regressions, not held-out confirmation coverage; they remain explicitly open for acceptance.

## Root causes, remaining gate, and hardware

See [ROOT_CAUSES.md](ROOT_CAUSES.md) for the required detailed investigation and [ROOT_CAUSE_MATRIX.md](ROOT_CAUSE_MATRIX.md) for atomic classifications. The exact reset and finite-innovation bias Jacobian have independent math evidence and corrections. The visible stationary-hint contradiction and zero-dwell bypass have code corrections and targeted tests, but their acceptance coverage remains open. Sustained acceleration/gravity ambiguity and absolute yaw remain physical limits. LegacyHeuristic trajectory behavior and synthetic-heading-aid degradation remain unresolved software/model interactions.

The overall PR 2 pass gate is **OPEN**. PR 3 performance-certification claims should not treat the open LegacyHeuristic, heading-aid, false-hint acceptance, or zero-dwell acceptance paths as resolved. No physical LSM6DS3/Pico 2 validation was performed. The ARM cross-build is `NOT_RUN`: `arm-none-eabi-g++` is unavailable and `PICO_SDK_PATH` is unset; see [RESOURCE_BUDGETS.md](RESOURCE_BUDGETS.md).
