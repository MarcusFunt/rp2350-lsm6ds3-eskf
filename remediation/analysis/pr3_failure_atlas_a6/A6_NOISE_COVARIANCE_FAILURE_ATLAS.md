# A6 — PR3 v5 development noise and covariance failure atlas

## Scope and provenance

This report uses the frozen PR3 v5 development archive only. The profile is IMU-only, unknown startup, startup gyro-bias calibration off, and no runtime aid. The fixed pre-change estimator is evaluated over static, slow-yaw, lateral-acceleration, vibration, and compound-motion cases at uniform 200 Hz, uniform 208 Hz, and irregular 208 Hz.

- Pre-change filter baseline: commit `9f2dcdb6a5abb2043805f2f298f9af9c881f27db` on `codex/heading-independent-a5-20261112`; source header SHA-256 `05a6b4de9a85abf8f85a8a0c4d24dfe058dda75f4ed4791584a8cc3e7dd84b61`. A6 diagnostic capture source: commit `950ff10cb966705dad593a2290c96fa9962d0eef` on `codex/noise-covariance-atlas-a6-20261112`.
- Protocol SHA-256 `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`; archive SHA-256 `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755`; archive-manifest SHA-256 `394278986dd83fad6f43799194d0ec4f3f407381eb5b761aa1ac5a22ffd2d22c`.
- Configuration SHA-256 `d5846fd833a2df91d69293d7545ee34bb719f848e238dfdd2eaa9317d4215fdd`. Development groups contain 100 trial rows per scenario/rate/stress/ESKF policy; grouped statistics are computed at trial level.
- Sample traces replay seed `4001` for each of the 30 matched scenario/rate/stress cells. Every regenerated input SHA matched the corresponding frozen development archive rows, and every replayed ESKF trial metric matched the archive within `2e-6` relative tolerance.
- Noise transform: nominal uses protocol v5 densities; stress multiplies white-noise density by 3 and bias walk, measurement disturbance, and timestamp jitter by 2. Truth trajectory is unchanged.
- No estimator parameters were changed. No held-out/final-confirmation data or hardware were used.

## Trial-level development rollups

Conservative ESKF; `n=100` per condition. Tilt values are means of per-trial RMS, not pooled sample RMS. Yaw is relative to the common zero-yaw startup gauge and is not absolute north. Covariance fraction counts the archived per-sample positive-definiteness checks.

| Scenario | Rate | Nominal tilt RMS mean (°) | Stress tilt RMS mean (°) | Paired stress−nominal (°) | Stress min availability | Stress covariance fraction |
|---|---|---:|---:|---:|---:|---:|
| static | uniform_200hz | 0.1437 | 5.3092 | +5.1654 | 1.0000 | 1.000000 |
| static | uniform_208hz | 0.1415 | 5.4006 | +5.2591 | 1.0000 | 1.000000 |
| static | irregular_208hz | 0.1439 | 5.4240 | +5.2801 | 1.0000 | 1.000000 |
| slow_yaw | uniform_200hz | 0.1466 | 5.3499 | +5.2033 | 1.0000 | 1.000000 |
| slow_yaw | uniform_208hz | 0.1449 | 5.2922 | +5.1473 | 1.0000 | 1.000000 |
| slow_yaw | irregular_208hz | 0.1440 | 5.2933 | +5.1492 | 1.0000 | 1.000000 |
| lateral_accel | uniform_200hz | 1.1117 | 5.4126 | +4.3008 | 1.0000 | 1.000000 |
| lateral_accel | uniform_208hz | 1.0416 | 5.4192 | +4.3776 | 1.0000 | 1.000000 |
| lateral_accel | irregular_208hz | 1.0398 | 5.4177 | +4.3779 | 1.0000 | 1.000000 |
| vibration | uniform_200hz | 0.9529 | 2.7036 | +1.7508 | 1.0000 | 1.000000 |
| vibration | uniform_208hz | 0.9643 | 2.7163 | +1.7520 | 1.0000 | 1.000000 |
| vibration | irregular_208hz | 1.0108 | 2.6856 | +1.6748 | 1.0000 | 1.000000 |
| compound_motion | uniform_200hz | 5.2058 | 6.8794 | +1.6736 | 1.0000 | 1.000000 |
| compound_motion | uniform_208hz | 5.2235 | 6.9082 | +1.6847 | 1.0000 | 1.000000 |
| compound_motion | irregular_208hz | 5.1701 | 6.8392 | +1.6690 | 1.0000 | 1.000000 |

## Selected time-resolved traces

The L1 artifact contains 98560 Conservative ESKF samples across 30 matched streams; it is per-sample diagnostic data, not a full 15×15 covariance dump. Each plot compares nominal and stress at the same scenario, rate, and seed. The maximum one-second tilt rise window is selected on physical time from the post-startup (`t≥2 s`) trace. Correction-gap windows run from initialization through accepted gravity updates and to end of trial.

Largest mean paired stress penalty in the selected scenario/rate matrix: `static` / `irregular_208hz`, `+5.2801°` tilt RMS over 100 paired development seeds.

| Scenario | Rate | Nominal / stress selected tilt RMS (°) | Stress max 1 s rise (°) | Stress window (s) | Stress gravity accepted | Stress longest no-correction gap (s) | Plot |
|---|---|---:|---:|---:|---:|---:|---|
| static | uniform_200hz | 0.1261 / 5.4602 | +0.6582 | 9.275–10.275 | 0 | 15.600 | [static/uniform_200hz](static__uniform_200hz__seed4001.svg) |
| static | uniform_208hz | 0.1562 / 5.4622 | +0.6657 | 7.928–8.928 | 0 | 15.615 | [static/uniform_208hz](static__uniform_208hz__seed4001.svg) |
| static | irregular_208hz | 0.1358 / 5.4610 | +0.6551 | 13.846–14.846 | 0 | 15.615 | [static/irregular_208hz](static__irregular_208hz__seed4001.svg) |
| slow_yaw | uniform_200hz | 0.1087 / 5.3095 | +0.6694 | 3.265–4.270 | 0 | 15.600 | [slow_yaw/uniform_200hz](slow_yaw__uniform_200hz__seed4001.svg) |
| slow_yaw | uniform_208hz | 0.1420 / 5.4610 | +0.6637 | 7.750–8.750 | 0 | 15.615 | [slow_yaw/uniform_208hz](slow_yaw__uniform_208hz__seed4001.svg) |
| slow_yaw | irregular_208hz | 0.1457 / 5.4018 | +0.6719 | 12.572–13.572 | 0 | 15.615 | [slow_yaw/irregular_208hz](slow_yaw__irregular_208hz__seed4001.svg) |
| lateral_accel | uniform_200hz | 1.2631 / 5.2670 | +0.6811 | 12.780–13.780 | 0 | 15.600 | [lateral_accel/uniform_200hz](lateral_accel__uniform_200hz__seed4001.svg) |
| lateral_accel | uniform_208hz | 1.1550 / 5.3938 | +0.6565 | 14.279–15.279 | 0 | 15.615 | [lateral_accel/uniform_208hz](lateral_accel__uniform_208hz__seed4001.svg) |
| lateral_accel | irregular_208hz | 1.2478 / 5.4813 | +0.6830 | 11.765–12.765 | 0 | 15.615 | [lateral_accel/irregular_208hz](lateral_accel__irregular_208hz__seed4001.svg) |
| vibration | uniform_200hz | 0.9444 / 2.8031 | +0.8193 | 2.740–3.740 | 0 | 15.600 | [vibration/uniform_200hz](vibration__uniform_200hz__seed4001.svg) |
| vibration | uniform_208hz | 0.9785 / 2.8280 | +0.8087 | 2.870–3.870 | 0 | 15.615 | [vibration/uniform_208hz](vibration__uniform_208hz__seed4001.svg) |
| vibration | irregular_208hz | 0.9314 / 2.7642 | +0.8003 | 2.774–3.779 | 0 | 15.615 | [vibration/irregular_208hz](vibration__irregular_208hz__seed4001.svg) |
| compound_motion | uniform_200hz | 5.2927 / 7.0017 | +1.1778 | 14.100–15.100 | 0 | 15.600 | [compound_motion/uniform_200hz](compound_motion__uniform_200hz__seed4001.svg) |
| compound_motion | uniform_208hz | 5.2260 / 6.8707 | +1.1907 | 13.981–14.981 | 0 | 15.615 | [compound_motion/uniform_208hz](compound_motion__uniform_208hz__seed4001.svg) |
| compound_motion | irregular_208hz | 5.2950 / 6.8646 | +1.1719 | 13.279–14.283 | 0 | 15.615 | [compound_motion/irregular_208hz](compound_motion__irregular_208hz__seed4001.svg) |

### Motion-regime accounting

Per-sample truth motion is reconstructed from the generated truth quaternion increments and velocity increments using physical sample timestamps. Bins use `|ω_truth|≥0.01 rad/s` and `|a_world_truth|≥0.05 m/s²`; startup is `t<2 s`. These bins describe the generated trajectory, not the filter's stationarity gate. The protocol-declared vibration disturbance is tracked separately.
The selected-trace atlas CSV records actual seconds in startup-static, quiescent/coast, rotation-dominant, translation-dominant and compound bins, plus declared vibration-active seconds. IMU residual RMS is calculated after subtracting simulator truth, bias and gravity; for vibration it includes deterministic disturbance plus white noise.

## Mechanism and classification

| Issue | Classification | Confidence / evidence | Scope and limitation |
|---|---|---|---|
| Long-run covariance positive-definiteness loss in the earlier single-precision source | Confirmed software defect — fixed before this baseline | High; remediation records the old slow-yaw failure and the FP64 repair. In the v5 development archive the selected baseline groups retain their full covariance-validity counts; selected L1 also records per-sample full-state Cholesky status and observable-plane NEES. | Positive definiteness does not establish calibrated covariance. This atlas does not retest the old binary. |
| Archive/evaluator mismatch in the selected baseline profile | Evaluation defect — not observed in this audit | High for checked scope; 100-trial group counts are exact, 30 regenerated input hashes match, and selected replay metrics match archived rows. | This is a selected v5 development-profile check, not a verifier for every protocol factor. |
| Absolute yaw during slow-yaw six-axis operation | Observability limitation | High; the profile provides no independent heading source. Report yaw only relative to the shared startup gauge. | Gyro integration can track increments but cannot recover absolute north. |
| Stress noise/disturbance interacting with the gravity candidate, dwell, and update cadence | Hypothesis for the broader stress accuracy gap; local gate sequence is directly observed in L1 | Medium–high on cases where the trace shows gate failures or long accepted-update gaps alongside tilt/bias growth; see per-case counters and windows. | A threshold interaction is not automatically a code defect; the synthetic densities are illustrative rather than measured LSM6DS3 noise. |
| Sustained lateral acceleration being confused with gravity direction | Observability limitation plus scenario-specific hypothesis about filter response | High for the physical ambiguity; the six-axis sample alone cannot distinguish a persistent horizontal specific-force component from a changed gravity direction. | The simulator knows the injected acceleration; the runtime filter does not. |
| Vibration behavior at 200/208 Hz and irregular timing | Hypothesis | Medium; compare residual RMS, candidate/rejection counts, update gaps and projected covariance across paired rate modes. | Protocol v5 labels its scenarios as synthetic approximations not verified against historical figures or measured hardware spectra. |
| Projected covariance versus tilt error / observable-plane NEES | Hypothesis about calibration, not a defect classification | The trace exposes the projected covariance matrix, its 2D square-root trace scale, 2D observable tilt NEES, gravity NIS and full-state covariance validity at each sample. | Nonlinear motion and gravity/propagation sample correlation limit chi-square interpretation; do not tune covariance from these plots alone. |

This atlas does not find a new confirmed software or evaluation defect. It preserves prior confirmed fixes as context and separates them from current stress/noise hypotheses and six-axis observability limits.

## Focused handoff to PR-C/D/E

- **PR-C (noise/covariance):** hold the gate and gravity sigma fixed while testing simulator-matched and intermediate process-noise densities; isolate bias random-walk settings; then separately test gravity residual variance. Use the same development raw input streams and compare bias error, projected observable covariance, NEES, and gravity NIS. A lightweight known-linearized-noise fixture is still needed before calling covariance calibrated.
- **PR-D (gravity/motion confidence):** use lateral acceleration to test false-gravity acceptance and recovery, and vibration/stress traces to test whether a noise-aware detector can retain usable corrections without accepting dynamic acceleration. Keep no-aid six-axis ambiguity explicit; evaluate selected candidate policy separately from baseline.
- **PR-E (heading):** carry forward the A5 pure-roll event trace; independently validate heading H/sign/gauge and vary only declared heading sigma on the fixed development noise realization. Treat tilt/bias cross-covariance and later propagation as separate mechanisms; use a separately modeled candidate if decoupling is tested.

## Reproduction and checks

Run from the repository root under a host with Python 3 and a C++17 compiler:

```bash
python3 tools/pr3_failure_atlas.py --output-dir remediation/analysis/pr3_failure_atlas_a6 --trace-seed 4001 --cxx g++ --implementation-commit 9f2dcdb6a5abb2043805f2f298f9af9c881f27db --implementation-branch codex/heading-independent-a5-20261112 --diagnostic-commit 950ff10cb966705dad593a2290c96fa9962d0eef --diagnostic-branch codex/noise-covariance-atlas-a6-20261112
python3 -m unittest discover -s tests -p 'test_pr3_failure_atlas.py'
```

Compiler: `g++`; build flags: `-std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -DINERTIAL_GRAVITY_DIAGNOSTICS=1`. The runner checked protocol/archive hashes, 100-row groups, exact input identity for selected seed 4001, trial-metric replay, sample count/order/clock, projected covariance fields, per-sample covariance validity, and paired nominal/stress input counts.

Hardware validation: `NOT_RUN`. Full factorial rerun: `NOT_RUN` (existing frozen archive used). Held-out and final-confirmation data: `NOT_ACCESSED`.
