# PR3 v5 gravity-correction suppression diagnostic

This report uses only the checked-in v5 **development** archive and its development seed range. The focused comparison is static / uniform 208 Hz, unknown startup, IMU only, startup calibration off, and no runtime aid. Nominal and stress use the same seed, protocol, profile, and estimator settings; only the v5 stress transform changes.

## Provenance and scope

- Archive SHA-256: `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755`; manifest SHA-256: `394278986dd83fad6f43799194d0ec4f3f407381eb5b761aa1ac5a22ffd2d22c`.
- Protocol SHA-256: `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`; all 200 regenerated stream hashes match the archived hashes.
- L0 contains 600 estimator-trial rows for 100 matched development seeds × 2 noise modes × 3 ESKF policies. No held-out or final-confirmation seed was used.
- All 600 replayed ESKF trial metric rows matched their frozen v5 archive rows within `2e-6` relative tolerance.
- The generator and evaluator write only under an automatically created temporary directory; the frozen v5 archives, manifests, reports, figures, and historical traces were read-only.

## Development static/208 Hz rollup

| Conservative ESKF condition | n | Mean tilt RMS (°) | Median (°) | P95 (°) | Worst (°) | Total gravity attempts / accepts | Mean longest candidate run |
|---|---:|---:|---:|---:|---:|---:|---:|
| Nominal | 100 | 0.1415 | 0.1433 | 0.1648 | 0.1735 | 15300 / 15300 | 3248.00 |
| Stress | 100 | 5.4006 | 5.4225 | 5.6540 | 5.7854 | 2 / 1 | 36.94 |
| Paired stress − nominal | 100 | mean +5.2591 | median +5.2847 | P95 +5.5083 | max +5.6152 | | |

## Exact gate sequence

Seed 4083 initializes on sample 80 and remains `Nominal` with full availability in both conditions. Stress tilt RMS is `0.17020972`° nominal versus `5.78541613`° stress in the frozen archive.
Nominal has `153` gravity attempts and `153` accepts; the first accepted correction is at sample 135. Stress has `0` attempts and `0` accepts. Its maximum consecutive candidate dwell is 42 samples.

The failing gate is the stationary-candidate adjacent-acceleration-step threshold (`step < 0.20 m/s²`). The stress seed has 586 post-initialization step-gate failures; its maximum candidate run is 42. A gravity attempt requires 35 consecutive candidates to declare stationarity, then 21 further candidate samples to satisfy the 21-sample aid cadence. Therefore at least 55 consecutive candidates are required for the first attempt, and 42 is insufficient. Acceleration-norm and gyro-norm criteria pass throughout this selected stress replay. The filter initializes correctly and health remains `Nominal`; gravity corrections are absent because the stationary gate never remains open long enough to reach cadence.

This identifies the gate interaction without changing thresholds or filter behavior. It does not claim that raising the step threshold is safe; the present prompt authorizes diagnosis and instrumentation only.

## Artifacts and deterministic replay

- `v5_dev_static208_l0_per_trial.csv`: one diagnostic summary row per development stream and ESKF policy (600 rows).
- `v5_dev_static208_l0_paired_deltas.csv`: matched nominal/stress deltas by seed and ESKF policy (300 rows).
- `v5_dev_static208_seed4083_nominal_l1.csv` and `v5_dev_static208_seed4083_stress_l1.csv`: per-sample gates, bias states/errors, tilt error, yaw-gauge-invariant projected covariance, health, and update outcomes.
- `v5_dev_static208_seed4083_nominal_l2_covariance.csv`: full 15×15 covariance immediately before and after the single selected accepted update at sample 135.
- `v5_dev_static208_seed4083_gravity_trace.svg` and `v5_dev_static208_paired_seed_tilt.svg`: selected causal timeline and all-seed paired comparison.

Run under WSL from the repository root (g++ is required):

```text
python3 tools/pr3_gravity_suppression.py --output-dir remediation/analysis/pr3_gravity_suppression_a4 --trace-seed 4083 --implementation-commit d34bd99ecb06906c7d1420f443963ca7def91d26
```

The tool refuses a forensic request outside one development static/208 Hz unknown-startup IMU-only stream and one sample event. L2 capture is not exposed through the full-factor benchmark runner.

All measurements are synthetic host simulation evidence. Hardware validation was not run.
