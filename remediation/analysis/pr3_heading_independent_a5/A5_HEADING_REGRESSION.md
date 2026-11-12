# A5 — independent-heading regression forensic replay

## Scope and provenance

This is a host-only replay of the frozen PR1 protocol-v2 **development** stream `pure_roll/combined/development/101` through the current ESKF source. The stream has 2,400 records at 200 Hz. The replay runs all three aid modes over one decoded copy of each IMU record, with identical startup and filter settings.

- Current source baseline: `6a1e0a90e9349df9b830cc372cac3c594f29722d`; branch is recorded in `evidence_manifest.json`.
- Source input SHA-256: `b6643cce0bdc3a1095b772afdb7e970b366d155fbd9c8fb77c8b58d7d50cd551` (96,000-byte stream slice). Full frozen input archive SHA-256: `5a0534c469340b6675d767d3e80da4b6b812b779fb3ecf9a40c21b652d12b2c4`.
- PR1 protocol-v2 SHA-256: `a17547e0260f4da6bded86b2a7df5a92069add7f38df896d0ceffa5c5c5f20f7`; source truth trace SHA-256: `22932a21458a0e4d2cf56f0172120212b799b024b6de3d1bca5ca78982d4d04d`.
- Current PR1 generator source SHA-256: `65c4fd8bb6284a2a20ef39896cbcc33f800ddf95202c80a4fd4a6a622f3a4b4e`; source generator commit in its frozen manifest: `c43c52671fa350cf8d095e93fa3b012331cd62f5`.
- The current PR3 v5 protocol has no `pure_roll` scenario. This step follows the plan’s named pure-roll development reproducer using the preserved PR1/v2 development stream; no held-out or final-confirmation data were read or used.
- The existing PR1 trace’s truth quaternion and bias values were checked against the selected raw input’s timestamps/IMU values and the declared pure-roll trajectory. All aid modes were replayed by a single loop over the same input records.

## Heading source contract

- Independent heading: `wrap_pi(truth_yaw + N(0, 0.04 rad))`, separate seeded PRNG stream in the frozen PR1 generator. The selected stream’s truth yaw is zero for pure roll.
- Schedule: every 1 second from `t=2.0 s` through `t=12.0 s`, inclusive; 11 events at sample indices 400, 600, …, 2400.
- The independent and oracle replay use `sigma=0.04 rad` in the filter, matching the current PR3 evaluator’s heading weighting. The oracle measurement equals simulator truth yaw; it is a diagnostic oracle, not a physical sensor result.
- Startup: externally verified static for `t<2 s`; startup gyro-bias calibration off; Conservative gravity policy; PR1 protocol-v2 noise densities and bias walks.

## Measured results

| Configuration | Tilt RMS (°) | Tilt max (°) | Yaw RMS (°) | Accepted / rejected heading updates | Mean / max event NIS* | End accel / gyro bias error norm |
|---|---:|---:|---:|---:|---:|---:|
| No heading aid | 0.121387 | 0.197824 | 0.236269 | 0 / 0 | 0.0002 / 0.0015 | 0.00366273 m/s² / 0.000101941 rad/s |
| Independent noisy heading | 1.632661 | 4.772082 | 2.107726 | 11 / 0 | 1.4804 / 6.6706 | 0.00887424 m/s² / 0.0028659 rad/s |
| Simulator-oracle heading | 0.121030 | 0.205584 | 0.015781 | 11 / 0 | 0.0000 / 0.0001 | 0.00372587 m/s² / 0.000109502 rad/s |

The independent measurement sequence had realized mean `-0.012°`, sample standard deviation `2.991°` over 11 events, and maximum absolute error `7.143°`; the declared per-sample sigma is `0.04 rad` (`2.292°`).

These exact replays align with the rounded seed-101 values in the existing `remediation/PR2_RESULTS.md`: aided tilt/yaw RMS `1.633°/2.108°` and no-aid `0.121°/0.236°`.

`*` No-aid NIS is counterfactual: it uses the shared independent measurement to evaluate a hypothetical scalar update without applying it. Independent/oracle NIS is the production update statistic.

**Regression status:** reproduced. High for this development stream; independent heading has higher tilt RMS than both no-aid and simulator-oracle replay on identical IMU bytes.

### Event timing and coupling

- Independent-heading mean absolute immediate tilt change: `0.383884°`; maximum: `2.440133°`.
- Independent-heading mean absolute post-event-to-next-pre-update tilt change: `0.641424°`.
- The largest positive propagation increase is `+0.715896°` from t=`7 s` to `8 s`; the largest decrease is `-4.023542°` from t=`8 s` to `9 s` during rest recovery.
- At t=`7 s`, the accepted update injects gyro-bias correction `[-0.001820, +0.010921, +0.007101] rad/s`. Post-update gyro-bias error norm is `0.013410 rad/s` (about `0.768°/s`); during the following second of continued roll, tilt increases by `0.715896°`.
- Between t=8 and 9 s, the roll has stopped and the trace records `7` accepted gravity corrections while projected tilt decreases sharply. The trace therefore distinguishes harmful motion-phase drift from later rest recovery.
- No-aid mean absolute event-time change: `0.000000°`; oracle mean absolute event-time change: `0.003466°`.
- **High confidence for both stages:** accepted noisy-heading events create immediate tilt jumps, then part of the error grows during the next propagation interval. The largest event jump is +2.440° at t=7 s; the largest inter-event increase is +0.716° from t=7 to 8 s.
- The event sequence shows an immediate heading-induced tilt error and additional inter-event drift consistent with the injected gyro-bias error. The largest absolute inter-event change is a 4° decrease after the roll stops; it is gravity-aided recovery, not harmful error accumulation.
- Each event row records analytic production `H`, predicted scalar `S`, NIS, production NIS cross-check, all 15 elements of `K` and proposed/injected `dx`, pre/post quaternion, projected tilt, all bias components, and the full 3×3 `P(theta,ba)` and `P(theta,bg)` cross-blocks before and after the event.
- `no_heading_aid` event rows use the shared independent measurement as a **counterfactual diagnostic** to compute innovation/H/S/NIS/K/dx, but the production filter does not receive or apply it; injected `dx` is zero.

### Hypotheses and confidence

1. **Heading update changes tilt through full-state covariance coupling — high confidence for this trace.** The scalar observation’s gain has attitude and bias blocks logged at each accepted event; the observed event-time tilt deltas are listed above. This is a local causal observation, not a claim about all motion or noise realizations.
2. **Noisy independent aid is harmful for this selected stream — high confidence.** The paired tilt RMS values use identical IMU samples and controlled startup settings.
3. **Bias correction contributes to later propagation drift — moderate confidence for this trace.** The t=7 s update injects the recorded gyro-bias vector and the following roll interval adds `0.716°`; their scales are consistent, but no bias-only counterfactual was run.
4. **Heading sigma/gate mismatch or temporal correlation explains the regression — low confidence / unresolved.** This replay verifies the declared sigma and accepted/rejected NIS sequence; it does not calibrate a physical sensor distribution or perform a sigma sweep.
5. **A specific attitude–bias cross-block is the unique cause — low confidence / unresolved.** Cross-blocks and gain components are recorded, but covariance-zeroing and independent linear-algebra ablations belong to the later heading-correction work package and were not performed here.

## Figures and files

- `heading_events.svg`: measured/predicted yaw, wrapped event innovations with ±3σ, and scalar NIS with the production gate.
- `heading_tilt_response.svg`: event-to-event tilt response and accel/gyro bias-error trajectories.
- `heading_gain_crosscov.svg`: Kalman-gain norms by state block and attitude–bias covariance cross-block norms.
- `heading_events.csv`: 33 event rows (11 × 3 aid modes), including the finite-dimensional heading model and state injection details.
- `heading_trace.csv`: 6,003 short per-sample rows (2,001 samples × 3 modes) for the evaluation window, including true/estimated bias, projected tilt, gravity-update counts, and the event windows.
- `heading_replay_summary.csv`: trial metrics and end bias errors for the three matched runs.

## Reproduction and checks

Run from the repository root in a host environment with Python 3 and a C++17 compiler:

```bash
python3 tools/pr3_heading_forensics.py --output-dir remediation/analysis/pr3_heading_independent_a5 --seed 101 --cxx g++ --implementation-commit 6a1e0a90e9349df9b830cc372cac3c594f29722d --implementation-branch codex/heading-independent-a5-20261112
```

Compiler: `g++ (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0`. The runner compiled with `-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror`; compile, frozen-hash checks, trace alignment checks, event timing checks, production-vs-analytic NIS checks, and cross-mode IMU identity checks all passed.

No ESKF behavior/settings were changed in this step; no held-out/final data were accessed; no hardware validation was performed.
