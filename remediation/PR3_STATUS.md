# PR3 statistical characterization status

## Gate status

**Primary v5 benchmark gate: PASS for the declared 208 Hz nominal baseline distributions. The post-fix candidate also passes development nominal parity and held-out/final baseline stress completion and covariance checks. Full-factor data coverage: PASS for the declared matrix. Accuracy/consistency acceptance and independent review: OPEN. PR2 gate: OPEN.** These runs are synthetic host simulations and do not establish hardware performance or control suitability.

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

## Initial factor pilot — pre-fix candidate

The original four-seed development pilot ran the pre-fix v5 candidate across all eight scenarios, three sampling modes, both stress transforms and seven startup/sensor/calibration/runtime-aid profiles. It produced 192 shared streams and 6,720 rows. All 2,016 incomplete rows were ESKF stress rows: each ESKF policy completed 672 / 672 nominal rows and 0 / 672 stress rows. Mahony and gyro-only produced finite attitude outputs for all 1,344 rows each, but they do not estimate navigation or covariance. The stress failure was isolated to the consecutive-sample initialization acceleration-step gate: in the selected static stress reproducer, 659 / 3,327 adjacent steps exceeded the 0.20 m/s² limit and the longest stable run was 35 samples, below the 80-sample initialization requirement. The correction and subsequent confirmation are recorded below; this original pilot remains immutable. See [factor pilot report](PR3_FACTOR_PILOT.md), [CSV](../benchmarks/reports/pr3_protocol_v5_factor_pilot_dev4_trials.csv), and [manifest](../benchmarks/manifests/pr3_protocol_v5_factor_pilot_dev4.json).

## Post-fix candidate validation

The startup correction is commit `e1bc064aa4a20d396905090abcf920d12991937c`; factor-aware Student-t interval reporting is commit `7547bf64413c99bda17950c7512e43e703cd969d`. Protocol v5 remains unchanged. The post-fix four-seed all-factor replay produced 192 streams and 6,720 rows: all ESKF stress rows completed (672 / 672 per policy), and nominal rows matched the prior pilot. That replay is exploratory; the separate 100-seed full-factor development, held-out and final-confirmation runs now provide the untouched coverage described below.

## Full-factor 100-seed coverage

The frozen post-fix source is `02c61fe7c4b93d591b042c69b08cfe20a6277722`; protocol v5 SHA-256 is `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`. Each disjoint split covers 8 scenarios × 3 rate modes × 2 stress modes × 7 declared profiles × 5 estimators: 4,800 shared input streams, 168,000 trial rows, 1,680 groups of exactly 100 trials, 3,360 paired intervals and 210 figures. The profiles keep startup knowledge, startup gyro-bias calibration, sensor input and runtime aid in separate fields; they are seven declared combinations, not a Cartesian product. All 4,800 generated inputs per split match their manifest hashes. Every split has zero incomplete trials and each ESKF policy passes all 96,622,400 expected covariance checks.

| Split | Seeds | Streams / rows / groups | Incomplete | Covariance checks per ESKF policy | Trial CSV SHA-256 | Compressed CSV SHA-256 | Summary JSON SHA-256 | Manifest and SHA-256 |
|---|---|---:|---:|---:|---|---|---|---|
| Development | 4001–4100 | 4,800 / 168,000 / 1,680 | 0 | 96,622,400 / 96,622,400 | `43fa2cafd0887bba51cb29c41d2fde2add8f66d29a9b95dbf716ee8f2705f793` | `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755` | `b9baf199017ddae5e6be50740e1f021cdcdce7ff2cea447184cca3be8c6504dc` | [manifest](../benchmarks/manifests/pr3_protocol_v5_dev100_all_factors_postfix.json), `394278986dd83fad6f43799194d0ec4f3f407381eb5b761aa1ac5a22ffd2d22c` |
| Held-out | 9001–9100 | 4,800 / 168,000 / 1,680 | 0 | 96,622,400 / 96,622,400 | `96cebf6ecf839ec0ab68d8efee9c26088180a2aafa79850ed307a61757d2eae3` | `c6d47a1b72036213abf12e66a1ef45a976ecb1fdc24b1083ef3381ad0ee72b9d` | `b6320d093ca124741559602e6068213c281ff0e7c411110343e5986d2411c421` | [manifest](../benchmarks/manifests/pr3_protocol_v5_heldout100_all_factors_postfix.json), `7a7279bf8734e7db484336fb40a245915c8e4196dd31c2295d3b843302baa520` |
| Final confirmation | 10001–10100 | 4,800 / 168,000 / 1,680 | 0 | 96,622,400 / 96,622,400 | `2399f460e89ff17a3132c9ac15df3f9e7998ddd6508a2481e0ff2043cbb6a1ff` | `d67d9688f604349e2f7a260a4101c4713370764371b5654585a8b4c3275e3f2f` | `e2cc1f54307358edff9f15f9893b26d57e3eb63e0fb685470275946e0dd8ad58` | [manifest](../benchmarks/manifests/pr3_protocol_v5_final100_all_factors_postfix.json), `2b7c0735279bb3e16421f1fb3ca82d3885688e4ed2f452d28aec2ed9016e8f81` |

Trial CSV archives are in `benchmarks/reports/`; the three manifests retain protocol, source, factor, seed, input-stream and report hashes; all 630 SVGs are in `benchmarks/figures/`. The simple mean of per-trial tilt RMS across all factor rows and three splits is 1.2814° nominal / 2.9517° stress for Conservative ESKF, 2.5128° / 2.9824° for Legacy ESKF, and 2.1981° / 2.9615° for ConfirmedOnly. The same averages for Mahony are 2.4479° / 2.4486° and for gyro-only 2.7848° / 2.8759°. These aggregate means are descriptive, not pooled per-sample errors or acceptance thresholds; startup and aid profiles differ. The earlier baseline-profile held-out/final stress runs still show conservative ESKF mean trial tilt RMS around 4.64–4.66° and yaw RMS around 10.30°, and the factor reports expose poor stress cases. This coverage does not cure the estimator-quality findings.

The independent verifier confirmed the split sizes, 4,800/4,800 input hashes, 1,680 groups with exactly 100 rows each, zero incomplete trials, 3,360 paired intervals, 210 figures, and all covariance totals. Final-confirmation hashes are recorded above. The generated raw streams remain reproducible from the frozen protocol, source commit and seed ranges; each manifest records the stream hashes.

Reproduce the final split from the current PR3 evidence branch with the frozen protocol and factor arguments. The benchmark candidate/source identity stamped in the manifest remains `02c61fe7c4b93d591b042c69b08cfe20a6277722`; the later branch changes add only evidence, verification and packaging files, not estimator code.

```bash
python3 tools/run_pr3_benchmarks.py --protocol benchmarks/scenarios/pr3_scenarios_protocol_v5.json --split final_confirmation --first-seed 10001 --last-seed 10100 --scenarios static,slow_yaw,lateral_accel,maneuver,vibration,timing_jitter,stop_start,compound_motion --rate-modes uniform_200hz,uniform_208hz,irregular_208hz --stress-modes nominal,stress --profiles baseline,heading_sensor,external_static,truth_static,startup_bias,independent_heading,oracle_heading --output-dir benchmarks/generated/pr3_protocol_v5_final100_all_factors_postfix --source-commit 02c61fe7c4b93d591b042c69b08cfe20a6277722 --tree-dirty no
python3 tools/verify_pr3_full_factor_evidence.py benchmarks/generated/pr3_protocol_v5_final100_all_factors_postfix
python3 tools/package_pr3_full_factor_evidence.py
```

For development, use `--split development --first-seed 4001 --last-seed 4100 --output-dir benchmarks/generated/pr3_protocol_v5_dev100_all_factors_postfix`; for held-out, use `--split held_out --first-seed 9001 --last-seed 9100 --output-dir benchmarks/generated/pr3_protocol_v5_heldout100_all_factors_postfix`. Keep the rest of the arguments identical. Run the verifier against each generated split before packaging. The verifier checks all input/figure hashes, factor balance, completion and covariance totals. The package script then checks recorded CSV/figure hashes and publishes the report paths; it does not rerun trials.

The 100-seed development nominal rerun covered eight scenarios at 208 Hz with the baseline profile. It reproduced all 4,000 prior v5 development trial rows on every field other than commit SHA. Held-out and final-confirmation baseline stress runs use disjoint seeds and provide untouched post-fix confirmation:

| Run | Seeds | Streams / rows | Incomplete | ESKF covariance checks | Conservative ESKF mean trial tilt/yaw RMS | Trial CSV SHA-256 | Summary SHA-256 | Evidence |
|---|---|---:|---:|---:|---:|---|---|---|
| Development nominal parity | 4001–4100 | 800 / 4,000 | 0 | 2,330,400 / 2,330,400 per ESKF policy | 1.9078° / 10.4381° | `9f3c1d20309bec7422a2bccd85af170702c47dcf60612194ec66675ac670b4b7` | `ba9e07383c9e50522f553db5cb61831d6ea2a97e35e2c9b46b949192b60e9089` | [report](../benchmarks/reports/pr3_protocol_v5_dev100_candidate_7547bf6_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_dev100_candidate_7547bf6_208_nominal.json) |
| Held-out stress | 9001–9100 | 800 / 4,000 | 0 | 2,330,400 / 2,330,400 per ESKF policy | 4.6589° / 10.3060° | `0c0ee2b9ba643e6fd7e43fa548caa0f8e08f58639b05154027015979890208f7` | `7bedf1026ed31896d121faecbe32e3058a0802a6272e183e5a7587dfebe49278` | [report](../benchmarks/reports/pr3_protocol_v5_heldout100_208_stress_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_heldout100_208_stress.json) |
| Final confirmation stress | 10001–10100 | 800 / 4,000 | 0 | 2,330,400 / 2,330,400 per ESKF policy | 4.6382° / 10.2986° | `502dcf5e0888ec9d36f624c0bde7113e843f7955f9fbe266cbb2f8a7dc7b6cf5` | `7c798979ffd2c671ef75d94fcf707f97e11cf5ae0a26f0ae3dffe9751500a601` | [report](../benchmarks/reports/pr3_protocol_v5_final100_208_stress_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_final100_208_stress.json) |

Each run covers eight scenarios at uniform 208 Hz, IMU-only input, unknown startup, calibration off and no runtime aid. All five estimators completed 800 / 800 stress trials with availability 1.0; each ESKF policy passed all 2,330,400 covariance-valid sample checks in each split. This fixes the stress-startup availability failure for the declared baseline profile, but does not establish stress accuracy or consistency: conservative ESKF mean per-trial tilt RMS is about 4.64–4.66° and yaw RMS about 10.30° across the eight scenarios. In the 100 static trials, conservative tilt RMS mean was 5.4034° (held-out; sample SD 0.3362°, 95% Student-t CI [5.3367°, 5.4701°]) and 5.3788° (final; sample SD 0.4213°, CI [5.2952°, 5.4624°]). The reports include sample counts, sample SDs, two-sided 95% Student-t intervals and per-run hashes. Raw input streams are regenerated and verified against manifest hashes. See [development nominal report](../benchmarks/reports/pr3_protocol_v5_dev100_candidate_7547bf6_208_nominal_summary.json), [held-out stress report](../benchmarks/reports/pr3_protocol_v5_heldout100_208_stress_summary.json), and [final stress report](../benchmarks/reports/pr3_protocol_v5_final100_208_stress_summary.json).

## Root-cause outcome and limits

The observed loss of covariance positive-definiteness under long single-precision propagation is classified as `CONFIRMED_IMPLEMENTATION_DEFECT` / `FIXED` for the tested cases. Before the FP64 revision, the slow-yaw development reproducer passed covariance checks for 1,576 / 2,801 ConfirmedOnly samples. The v5 development, held-out and final sets all passed every ESKF covariance check. See [root-cause records](ROOT_CAUSES.md).

The declared 100-seed full-factor matrix is now covered at 200 Hz, 208 Hz, and irregular 208 Hz, under nominal and stress transforms, across eight scenarios and seven declared startup/sensor/calibration/aiding profiles. This closes the previously missing PR3 factor-coverage work; it does not close the accuracy or consistency acceptance gate. PR3 remains open because ESKF stress accuracy/consistency is poor, PR2 LegacyHeuristic yaw/bias and synthetic-heading-aid behavior remain unresolved, held-out false-hint/zero-dwell cases are missing, and independent review has not been recorded. Physical sensor accuracy, FIFO integrity, RP2350 timing, stack high-water and control suitability remain **BLOCKED_HARDWARE**.

The 800 shared input streams per primary split are regenerated on demand rather than checked into Git; their SHA-256 values and exact commands are in the manifests. The selected diagnostic stream is checked in at `benchmarks/inputs/pr3_protocol_v5_dev_slow_yaw_seed4001.bin`.

## Reproduction

From a clean checkout, run one of the exact commands recorded in its manifest. For example:

```bash
python3 tools/run_pr3_benchmarks.py --protocol benchmarks/scenarios/pr3_scenarios_protocol_v5.json --split held_out --first-seed 9001 --last-seed 9100 --scenarios static,slow_yaw,lateral_accel,maneuver,vibration,timing_jitter,stop_start,compound_motion --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir benchmarks/generated/pr3_protocol_v5_heldout100_208_nominal --source-commit 3efd3f89e244e152364773fb26cfb0c5749dce3d --tree-dirty no --summary-source-label benchmarks/reports/pr3_protocol_v5_heldout100_208_nominal_trials.csv --figure-prefix pr3_protocol_v5_heldout100_208_nominal --figure-path-prefix benchmarks/figures/
```
