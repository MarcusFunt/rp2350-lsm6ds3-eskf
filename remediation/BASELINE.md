# PR 1 baseline

## Scope and provenance

This is the frozen, pre-mathematics baseline for the first remediation step. The execution branch is `test/eskf-remediation-pr1`, based on `origin/main` at `c397fec8f5df3fb612ea6aa92547d484e9e48c06` (verified 2026-11-10). The original checkout was left untouched, including its pre-existing untracked `docs/` files. Work was done in the separate `C:\Users\marcu\rp2350-eskf-pr1` worktree.

The estimator header `eskf15.hpp` was not changed. Its baseline SHA-256 is `2a04cb479ffade58d3c8f3522c4ee4e8b0b57dc038e4a73e95b164eadc296a04`. PR 1 changes the evaluator, benchmark harness, tests, and evidence only.

## Frozen benchmark

Run `bash ./tools/run_pr1_baseline.sh` to regenerate the protocol-v2 baseline, replay the frozen inputs through the historical default core, validate the results, and rewrite the manifest. The matrix uses a fixed 200 Hz sample period (5,000 µs), records from 1.005 s through 13 s, and scores the inclusive 2–12 s interval (2,001 samples per trial).

The four independent truth scenarios are `static`, `pure_roll`, `lateral_accel_0p2g`, and `slow_yaw`. The lateral case applies +0.2 g in world X from 2–8 s with zero true rotation, then coasts to 12 s. Its independently calculated 12 s position is 82.376 m in X. Pure roll uses 0.18 rad/s about body X from 2–8 s; slow yaw uses 0.035 rad/s about Z from 2–12 s.

There are 292 shared IMU streams: four clean references, and 16 development plus 16 held-out seeds for each of the three noisy motion cases (`pure_roll`, `lateral_accel_0p2g`, `slow_yaw`) and each noise mode (accelerometer-only, gyro-only, combined). Each stream is replayed through all 18 estimator/input/startup variants, producing 5,256 summary rows. All estimator variants consume the same raw IMU stream for a given trial. The disjoint held-out seeds are frozen and must not be used to tune PR 2 changes; after an acceptance result informs further tuning, use a new untouched confirmation set.

The summary includes availability and health as well as tilt RMS/p95/max, full attitude and yaw errors, position/velocity errors, bias errors, NIS, gravity-update outcomes, and aid counts. Twenty-one selected traces retain all 2,001 samples for clean lateral acceleration and combined-noise pure-roll, lateral, and slow-yaw trials across all three gravity policies (42,021 rows total). The raw binary stream, CSV index, each stream hash, input settings, scenario equations, and generated artifacts are pinned in [the manifest](../benchmarks/manifests/pr1_baseline_protocol_v2.json).

`IMU_ONLY` receives only accelerometer and gyro data. Startup knowledge (`UNKNOWN` or `EXTERNALLY_VERIFIED_STATIC`), startup bias calibration, and runtime aid are separate settings. `TRUSTED_AIDED` is currently an explicitly synthetic independent-heading proxy (truth yaw plus independent Gaussian noise, σ=0.04 rad); it is not hardware evidence and is not assumed to be an upper bound. The seed sets are regression gates, not statistical certification.

## Evaluator correction

Evaluation protocol v1 measured the angle between two world-frame body-up vectors. A relative world-yaw-only attitude change at nonzero tilt therefore produced a false tilt error. Protocol v2 measures the angle between the estimated and true body-frame gravity directions, `R_est⁻¹ world_up` and `R_true⁻¹ world_up`. A new test checks relative world-yaw invariance at nonzero pitch and roll, common global-yaw invariance, and retained full-attitude error. Its protocol-v1 counterexample is 22.697° despite zero true tilt difference. The four old checked-in Bundle B CSV/JSON results remain unchanged and are explicitly marked superseded by the [v1 manifest](../benchmarks/manifests/pr1_protocol_v1_superseded.json); the summarizer refuses to process unversioned/v1 CSVs as v2.

## Reproduced dynamic-gravity failure

The historical replay uses the exact pre-Bundle-B ESKF header from commit `e90c80eb47e5002738f4a16450714b3149798e28`, but feeds it the new frozen protocol-v2 clean lateral stream. This is an exact source replay on a transparent recreated input, not a claim that the original historical sample/noise history was recovered.

For `IMU_ONLY / UNKNOWN / calibration OFF / no runtime aid`, the historical default produced 2,001/2,001 valid samples, 14.570° tilt RMS, 18.462° p95, 19.182° maximum tilt, 48.049 m position RMS, 97.781 m position p95, and 109.031 m endpoint position error. It ended with a 0.025127 rad/s gyro-bias norm while health remained `Nominal`.

On the same clean lateral input, current `LegacyHeuristic` produced 14.839° tilt RMS (19.311° max), 50.132 m position RMS (101.826 m p95), and `Nominal` health. Current `Conservative` and `ConfirmedOnly` stayed level (0° measured tilt error), with 0.045585 m position RMS and 0.058842 m p95. This reproduces the old failure in the legacy policy and shows that the current default avoids this particular sustained-acceleration case. It does not prove six-axis IMU observability during arbitrary acceleration or resolve why legacy recovery learns a false bias and rejects later gravity evidence.

The historical handoff's earlier estimate (~19.175° false pitch and ~102.166 m X error at 12 s) is close but not identical: the original generator and exact noisy/time histories are unavailable. No byte-for-byte historical claim is made.

## Pure-roll noisy yaw characterization

The exact historical noisy-roll generator is unavailable. The new fixed seeds establish a repeatable comparison instead. The table reports per-seed yaw-RMS distributions and the largest single absolute yaw error across seeds, for `IMU_ONLY / UNKNOWN / calibration OFF / no aid`. Percentiles use the lower order statistic at `floor((n-1)p)`.

| Core | Noise | Split | Seeds | Median yaw RMS (°) | p95 yaw RMS (°) | Max yaw RMS (°) | Largest single yaw error (°) |
|---|---|---:|---:|---:|---:|---:|
| Historical default | Accelerometer | Development | 16 | 0.98 | 3.14 | 4.33 | 6.22 |
| Historical default | Accelerometer | Held out | 16 | 1.39 | 2.89 | 3.28 | 7.01 |
| Historical default | Gyro | Development | 16 | 0.08 | 0.19 | 0.23 | 0.62 |
| Historical default | Gyro | Held out | 16 | 0.07 | 0.11 | 0.18 | 0.37 |
| Historical default | Combined | Development | 16 | 0.93 | 2.28 | 2.56 | 5.46 |
| Historical default | Combined | Held out | 16 | 1.24 | 2.63 | 3.03 | 6.40 |
| Current Conservative | Accelerometer | Development | 16 | 0.77 | 2.12 | 2.49 | 4.40 |
| Current Conservative | Accelerometer | Held out | 16 | 0.69 | 1.66 | 1.82 | 3.61 |
| Current Conservative | Gyro | Development | 16 | 0.09 | 0.19 | 0.24 | 0.67 |
| Current Conservative | Gyro | Held out | 16 | 0.07 | 0.11 | 0.18 | 0.37 |
| Current Conservative | Combined | Development | 16 | 0.50 | 0.92 | 1.09 | 3.31 |
| Current Conservative | Combined | Held out | 16 | 0.79 | 1.29 | 1.76 | 4.31 |

These are results on the frozen recreated scenarios. They do not reconstruct the historical reported median of about 2.91° or maximum of about 11.32°.

## Checks and limits

All Bundle A/B/C host suites and all A/B/C sanitizer variants passed at source commit `c43c52671fa350cf8d095e93fa3b012331cd62f5`; canonical logs are listed in [the evidence index](evidence/README.md). The PR 1 baseline generator validated 5,256 rows, 42,021 trace rows, 292 hashed streams, timestamp ordering, sample counts, clean lateral truth, and serialized NIS semantics. The PR 1 host-only changes were not ARM cross-built. The existing pinned CI run verifies direct/FIFO/binary cross-builds on baseline `c397fec`; it is not a cross-build of this branch. No board/sensor validation was performed.

Eight external SVGs have no recoverable source CSV or generator in the inspected checkout and are `HISTORICAL_UNREPRODUCED`. They are not used as fresh quantitative evidence. Hardware timing, acquisition jitter, stack high-water, and sensor performance remain unmeasured.
