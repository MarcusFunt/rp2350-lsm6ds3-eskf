# PR3 statistical characterization status

## Gate status

**Primary v5 benchmark gate: PASS for the declared 208 Hz nominal baseline distributions. Full-factor acceptance and independent review: OPEN. PR2 gate: OPEN.** The runs are synthetic host simulations and do not establish hardware performance or control suitability.

The frozen estimator candidate is `3efd3f89e244e152364773fb26cfb0c5749dce3d`. Protocol v5 SHA-256 is `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`. V5 preserves the v3 motion, noise, timestamp, scoring and RNG definitions; it adds exact attitude-only Mahony and gyro-only reference definitions and disjoint acceptance seeds. V1–v4 protocols and their evidence remain unchanged.

## V5 primary runs

Each split covers eight scenarios at uniform 208 Hz, nominal stress transform, IMU-only input, unknown startup, calibration off and no runtime aid. Each has 100 seeds, 800 shared input streams and 4,000 estimator rows (three ESKF policies plus Mahony and gyro-only). Every estimator completed all 800 trials. Each ESKF policy reported valid state and positive-definite covariance for all 2,330,400 expected samples in each split. The ESKF rows total 20,973,600 covariance-valid sample checks across all three splits.

| Split | Seeds | Incomplete rows | Estimator completion | Trial CSV SHA-256 | Summary JSON SHA-256 | Evidence |
|---|---|---:|---:|---|---|---|
| Development | 4001–4100 | 0 / 4,000 | 800 / 800 per estimator | `30709092ffcbecfd2a96bd524f9faed77bb6e1d68d2d965643d27ad2b294300b` | `696fcef287d596de2cca3dca6a1afc5e54752891ea52f9bdd871773f976bef58` | [report](../benchmarks/reports/pr3_protocol_v5_dev100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_dev100_208_nominal.json) |
| Held-out | 9001–9100 | 0 / 4,000 | 800 / 800 per estimator | `bfbe1e3d89635992b080370e677e8e7e00b65025d08a843d3e5ee4a7a83a7083` | `5728f19d2e05cf74020af856a49d30549e8de5c8f1d228a3696db5798a00e33e` | [report](../benchmarks/reports/pr3_protocol_v5_heldout100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_heldout100_208_nominal.json) |
| Final confirmation | 10001–10100 | 0 / 4,000 | 800 / 800 per estimator | `92b1d7a8c3797a6a9d96ee185f0f09ad319c9c4a1672e4d98dc7899314c367be` | `2d37ea5ca238faab63184c5f0114c7a64c9b510a4443df7b9d08322133cc6493` | [report](../benchmarks/reports/pr3_protocol_v5_final100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_final100_208_nominal.json) |

The simple mean of per-trial RMS values across all eight scenario groups is consistent across the three splits:

| Estimator | Tilt RMS mean | Yaw RMS mean | Covariance / navigation |
|---|---:|---:|---|
| Conservative ESKF | about 1.91° | about 10.5° | Provided |
| Legacy ESKF | about 3.18° | about 20.1° | Provided |
| ConfirmedOnly ESKF | about 4.65° | about 10.3° | Provided |
| Mahony reference | about 2.56° | about 9.84° | Not provided |
| Gyro-only reference | about 4.79° | about 10.67° | Not provided |

These are means of per-trial RMS metrics, not per-sample pooled RMS. Availability is reported separately. The low mean tilt NEES and gravity NIS remain consistency diagnostics requiring interpretation; gravity updates reuse accelerometer information, so ideal independent-measurement coverage is not claimed. ConfirmedOnly has poor tilt accuracy in several cases despite complete finite/covariance-valid output (held-out mean trial tilt RMS is about 5.35° in slow yaw and 6.90° in compound motion).

Five aggregate figures are generated for each primary set: tilt RMS, yaw RMS, finite-attitude availability, mean tilt NEES, and mean NIS. Selected development seed 4001 slow-yaw diagnostics add yaw-invariant tilt error, gyro/accelerometer bias error, attitude covariance diagonal, and gravity-update chronology figures. The [development diagnostic manifest](../benchmarks/manifests/pr3_protocol_v5_dev_slow_yaw_seed4001.json) ties these plots to its raw input and trace hashes.

## Updated factor pilot

A separate four-seed development pilot ran the v5 candidate across all eight scenarios, three sampling modes, both stress transforms and seven startup/sensor/calibration/runtime-aid profiles. It produced 192 shared streams and 6,720 rows. All 2,016 incomplete rows are ESKF stress rows: each ESKF policy completed 672 / 672 nominal rows and 0 / 672 stress rows. Mahony and gyro-only produced finite attitude outputs for all 1,344 rows each, but they do not estimate navigation or covariance. The stress failure is isolated to the consecutive-sample initialization acceleration-step gate: in the selected static stress reproducer, 659 / 3,327 adjacent steps exceed the 0.20 m/s² limit and the longest stable run is 35 samples, below the 80-sample initialization requirement. The fix remains open and was not tuned on these results. See [factor pilot report](PR3_FACTOR_PILOT.md), [CSV](../benchmarks/reports/pr3_protocol_v5_factor_pilot_dev4_trials.csv), and [manifest](../benchmarks/manifests/pr3_protocol_v5_factor_pilot_dev4.json).

## Root-cause outcome and limits

The observed loss of covariance positive-definiteness under long single-precision propagation is classified as `CONFIRMED_IMPLEMENTATION_DEFECT` / `FIXED` for the tested cases. Before the FP64 revision, the slow-yaw development reproducer passed covariance checks for 1,576 / 2,801 ConfirmedOnly samples. The v5 development, held-out and final sets all passed every ESKF covariance check. See [root-cause records](ROOT_CAUSES.md).

PR3 remains open for 100-seed held-out/final coverage outside the nominal baseline profile, poor ESKF accuracy/consistency in disclosed modes, unresolved PR2 LegacyHeuristic yaw/bias and synthetic-heading-aid behavior, missing held-out false-hint/zero-dwell coverage, and independent review. Physical sensor accuracy, FIFO integrity, RP2350 timing, stack high-water and control suitability remain **BLOCKED_HARDWARE**.

The 800 shared input streams per primary split are regenerated on demand rather than checked into Git; their SHA-256 values and exact commands are in the manifests. The selected diagnostic stream is checked in at `benchmarks/inputs/pr3_protocol_v5_dev_slow_yaw_seed4001.bin`.

## Reproduction

From a clean checkout, run one of the exact commands recorded in its manifest. For example:

```bash
python3 tools/run_pr3_benchmarks.py --protocol benchmarks/scenarios/pr3_scenarios_protocol_v5.json --split held_out --first-seed 9001 --last-seed 9100 --scenarios static,slow_yaw,lateral_accel,maneuver,vibration,timing_jitter,stop_start,compound_motion --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir benchmarks/generated/pr3_protocol_v5_heldout100_208_nominal --source-commit 3efd3f89e244e152364773fb26cfb0c5749dce3d --tree-dirty no --summary-source-label benchmarks/reports/pr3_protocol_v5_heldout100_208_nominal_trials.csv --figure-prefix pr3_protocol_v5_heldout100_208_nominal --figure-path-prefix benchmarks/figures/
```
