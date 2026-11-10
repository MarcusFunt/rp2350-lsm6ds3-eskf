# PR 2 — Numerical model and recovery results

**Branch:** `fix/eskf-math-recovery` stacked on PR 1 `b749a8aa0e40718ab7b163cad29d9c550b088265`

**Candidate source freeze:** `60b967b0d1e8480bade505dbe3beb788ee442da9`
**Current result:** code and test gates pass; the paired confirmation run passes input/denominator validation. The overall PR 2 pass gate remains **OPEN** because the LegacyHeuristic yaw/bias trade-off and synthetic-heading-aid degradation remain unresolved. Dependent performance claims are blocked.

## Changes

- Replaced the first-order attitude covariance reset with the exact SO(3) right Jacobian for the right-multiplicative quaternion injection. The 15-state filter, state ordering, public aiding interfaces, and heap-free estimator structure remain intact.
- Added an independent FP64 finite-difference reset check and an FP64 Joseph-update/covariance-reset oracle.
- An external stationary assertion is now usable only while the current sample passes the existing accel-norm, gyro, and accel-step checks. Contradictions increment `external_stationary_conflicts()` and suppress gravity and heuristic zero-rate aiding for that sample.
- Clarified that `Health` reports alignment/continuity/numeric/input status and `control_state_valid()` reports freshness/availability; neither certifies accuracy, observability, or control suitability.
- Added sign, yaw-model, gravity-tangent, changing-bias, slow-yaw, false-hint, and repeated reset/reinitialization regressions.
- Added paired PR 1 comparison and Bundle B comparison runners. The Bundle B reader compensates for the existing malformed optional CSV tail without misreporting absent Legacy/Mahony gyro-bias values.

## Verification

The parent baseline A/B/C host and sanitizer suites passed before PR 2 changes. After the candidate freeze and confirmation run, all six host and sanitizer commands passed again:

| Command | Result | Log |
|---|---|---|
| `./tools/run_bundle_a_checks.sh` | PASS | [Bundle A host log](evidence/pr2_bundle_a_confirmation_host.log) |
| `BUNDLE_A_SANITIZERS=1 ./tools/run_bundle_a_checks.sh` | PASS | [Bundle A sanitizer log](evidence/pr2_bundle_a_confirmation_sanitizers.log) |
| `./tools/run_bundle_b_checks.sh` | PASS | [Bundle B host log](evidence/pr2_bundle_b_confirmation_host.log) |
| `BUNDLE_B_SANITIZERS=1 ./tools/run_bundle_b_checks.sh` | PASS | [Bundle B sanitizer log](evidence/pr2_bundle_b_confirmation_sanitizers.log) |
| `./tools/run_bundle_c_checks.sh` | PASS | [Bundle C host log](evidence/pr2_bundle_c_confirmation_host.log) |
| `BUNDLE_C_SANITIZERS=1 ./tools/run_bundle_c_checks.sh` | PASS | [Bundle C sanitizer log](evidence/pr2_bundle_c_confirmation_sanitizers.log) |

The independent reset oracle reports an attitude correction of `0.042196347 rad`. Its exact-reset block error is `7.09947786e-6`, compared with `2.20535708e-4` for the old first-order reset. The global maximum covariance difference to the FP64 oracle is `0.00026823457` at `(1,1)`; that residual remains within the oracle's declared tolerance and is not hidden by the reset-block comparison.

The false-hint regression rejects 300 samples with 0.4 g lateral acceleration and 160 samples with 0.18 rad/s rotation, with zero gravity updates. A plausible 0.2 g wrong initial gravity direction remains more than `0.15 rad` wrong IMU-only after 500 samples while health/availability remain nominal; verified static aiding recovers below `0.06 rad`. Sustained in-tolerance acceleration still causes ambiguous gravity aiding, as expected from six-axis observability limits.

For slow yaw with a linearly changing gyro bias, both filters remained available. Maximum yaw error was `0.0300 rad` IMU-only and `0.0013 rad` with 120 independent heading updates. This demonstrates that heading aiding helps this particular level slow-yaw case; it does not promise general heading-aid performance.

## Development comparison and candidate selection

The frozen configuration is [pr2_confirmation_protocol_v2.json](../benchmarks/scenarios/pr2_confirmation_protocol_v2.json), SHA-256 `bfcc898a3af18cb7a5a0f47f1af1a89b51dcc74033fa2ea002e5bd24881b7d57`. It contains four scenarios, three noisy modes, seeds `101–116` for development, and seeds `2001–2016` for one untouched confirmation run. PR 1 held-out seeds `1001–1016` had already been inspected and were excluded from candidate selection.

The PR 1 development comparison contains 192 streams, 3,456 estimator rows, and 460,800 input records. Parent and candidate sample files matched byte-for-byte with SHA-256 `0cbd28d02f8405619f65c2df9391e9689e13c3f5caa4b3cf7c09d3d43a02fcca`. The paired report is [pr2_candidate_comparison_protocol_v2.csv](../benchmarks/reports/pr2_candidate_comparison_protocol_v2.csv).

| Mode, 192 trials each | PR 1 parent | PR 2 candidate | Paired availability / final-health changes |
|---|---:|---:|---:|
| Conservative, `IMU_ONLY`, `UNKNOWN`, tilt RMS mean | 0.096197° | 0.096196° | 0 / 0 |
| Conservative, `IMU_ONLY`, `UNKNOWN`, yaw RMS mean | 0.541892° | 0.542317° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY`, `UNKNOWN`, tilt RMS mean | 3.993426° | 3.660764° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY`, `UNKNOWN`, yaw RMS mean | 1.814867° | 2.015686° | 0 / 0 |
| LegacyHeuristic, `IMU_ONLY`, `UNKNOWN`, final gyro-bias error mean | 0.006051 rad/s | 0.007705 rad/s | 0 / 0 |

On the existing six Bundle B scenarios (5 trials each, seed `20261111`), Conservative availability did not change. Mean Conservative yaw-RMS delta was `-0.001175°` without verified startup bias and `+0.000897°` with verified startup bias. LegacyHeuristic mean yaw-RMS deltas were `+1.131979°` and `+1.233798°`; the largest individual increases were `18.073327°` and `13.529648°`. Paired outputs are [startup bias off](../benchmarks/reports/pr2_bundle_b_no_startup_bias_protocol_v2.csv) and [verified startup bias](../benchmarks/reports/pr2_bundle_b_verified_startup_bias_protocol_v2.csv).

The exact reset correction was selected for its independent mathematical validation and negligible Conservative-default change. The LegacyHeuristic trade-off was retained as an open finding; no changes were tuned to the PR 1 held-out seeds.

## Untouched confirmation

After candidate freeze and pre-registration in [pr2_candidate_protocol_v2.json](../benchmarks/manifests/pr2_candidate_protocol_v2.json), seeds `2001–2016` were run **once** against the PR 1 parent and frozen PR 2 source. The run command was:

```bash
tools/run_pr2_comparison.sh \
  /mnt/c/Users/marcu/rp2350-eskf-pr1 \
  /mnt/c/Users/marcu/rp2350-eskf-pr2 \
  confirmation /tmp/pr2-confirmation-2001-2016
```

The validator passed: 192 streams, 460,800 40-byte records, 3,456 paired rows, 2,001 expected evaluation samples per row (6,915,456 total expected estimator-samples), zero incomplete rows, zero stale rows, zero availability differences, and zero final-health differences. Parent/candidate sample-file SHA-256 was `6c5236898431d30ed0201798148a42f515ce47af234d566ed8ee5b581e5361e3`.

The preserved artifacts are:

- [Paired confirmation report](../benchmarks/reports/pr2_confirmation_comparison_protocol_v2.csv), SHA-256 `88988a836a29b29019dd705f4f8511bb88f0c46670f03bc8537f13bb11ddff3a`.
- [Shared raw IMU/heading records](../benchmarks/reports/pr2_confirmation_imu_samples_protocol_v2.bin), SHA-256 `6c5236898431d30ed0201798148a42f515ce47af234d566ed8ee5b581e5361e3`.
- [Sample index](../benchmarks/reports/pr2_confirmation_sample_index_protocol_v2.csv), SHA-256 `bf6eef118c18ddea8b09c52218c9ac5f7b78d28871389266e051babc616bd300`.

On confirmation, the Conservative `IMU_ONLY/UNKNOWN` means changed from `0.102904°` to `0.102903°` tilt RMS and `0.575054°` to `0.575557°` yaw RMS; paired availability and health stayed identical. LegacyHeuristic tilt RMS improved (`3.954709°→3.699982°`), while yaw RMS (`1.703670°→1.815770°`) and final gyro-bias error (`0.006154→0.007253 rad/s`) worsened. The largest per-trial yaw-RMS increase was `4.191749°`.

The synthetic heading aid still degrades pure-roll performance on the confirmation set. With Conservative policy and 16 seeds, mean tilt/yaw RMS was `0.210836°/0.973115°` for `IMU_ONLY` and `3.636263°/1.922513°` with the 1 Hz synthetic independent-heading stream. This is an open aid/covariance interaction; the simulator heading is not physical sensor validation.

No code was tuned after this confirmation run. The set is now exposed and any revision would require a new disjoint confirmation list.

## Root causes and remaining gate

See [ROOT_CAUSE_MATRIX.md](ROOT_CAUSE_MATRIX.md) for atomic issues, categories, and dispositions. PR 2 fixes the reset Jacobian and the obvious stationary-hint contradiction. The constant-acceleration/gravity ambiguity and absolute-yaw gauge are physical limitations. LegacyHeuristic trajectory changes, synthetic-heading-aid degradation, and the Bundle B CSV field-shift remain open findings.

The host/source and paired-data gates pass. The overall PR 2 pass gate remains **OPEN** because severe LegacyHeuristic and synthetic-heading-aid behavior is not explained or fixed. PR 3 performance-certification claims should not treat these paths as resolved. No physical LSM6DS3/Pico 2 validation was performed.

The ARM cross-build is `NOT_RUN`: `arm-none-eabi-g++` is unavailable and `PICO_SDK_PATH` is unset. See [RESOURCE_BUDGETS.md](RESOURCE_BUDGETS.md); the prior `c397fec` CI size numbers do not measure this branch.
