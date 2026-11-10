# PR 1 failure reproduction

## Reproduce the frozen benchmark

From a clean checkout of this branch, run:

```bash
./tools/run_pr1_baseline.sh
```

This compiles the host baseline and a temporary replay executable for the exact pre-Bundle-B source revision, regenerates protocol-v2 raw samples and estimator outputs, and validates/updates the manifest. Requirements are Bash, GCC/G++ with C++17, and Python 3. The replay extracts `eskf15.hpp` from historical commit `e90c80eb47e5002738f4a16450714b3149798e28`; it does not copy that old header into the repository.

Primary artifacts:

- `benchmarks/manifests/pr1_baseline_protocol_v2.json`
- `benchmarks/reports/pr1_baseline_protocol_v2.csv`
- `benchmarks/reports/pr1_historical_default_protocol_v2.csv`
- `benchmarks/reports/pr1_representative_traces_protocol_v2.csv`
- `benchmarks/reports/pr1_sample_index_protocol_v2.csv`
- `benchmarks/reports/pr1_imu_samples_protocol_v2.bin`

The manifest records the base SHA, benchmark source SHA, estimator SHA-256, compiler/runtime, scenario hash, output hashes, and each raw stream hash. The frozen input profile is 200 Hz, 5,000 µs increments, 2,001 scored samples from 2 to 12 seconds, and shared raw samples across compared modes.

## Historical dynamic-gravity regression

The old core replay is `IMU_ONLY / UNKNOWN / OFF / NONE`: level initial attitude, zero true rotation, +0.2 g lateral acceleration from 2 to 8 seconds, then coast to 12 seconds. Truth position is independently calculated from the acceleration schedule. The frozen stream has 2,001 scored observations and protocol-v2 tilt is the angle between body-frame gravity directions.

| Core / policy | Tilt RMS (°) | Tilt p95 (°) | Tilt max (°) | Position RMS (m) | Position p95 (m) | Endpoint error (m) | Gyro-bias norm at end (rad/s) | Health |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Historical default, e90c80e | 14.570 | 18.462 | 19.182 | 48.049 | 97.781 | 109.031 | 0.025127 | Nominal |
| Current `LegacyHeuristic`, c397fec | 14.839 | 18.627 | 19.311 | 50.132 | 101.826 | 113.412 | 0.023875 error norm | Nominal |
| Current `Conservative`, c397fec | 0.000 | 0.000 | 0.000 | 0.0456 | 0.0588 | 0.0588 | 0 | Nominal |
| Current `ConfirmedOnly`, c397fec | 0.000 | 0.000 | 0.000 | 0.0456 | 0.0588 | 0.0588 | 0 | Nominal |

All rows use 2,001 expected samples. The current-policy values come from the shared-input v2 benchmark; the old row comes from replaying the same frozen lateral stream through the historical default. Policy comparisons are diagnostics, not proof of performance in general motion. The sustained acceleration/gravity ambiguity is unobservable from a six-axis IMU without assumptions or independent information.

## Noisy pure-roll replay

The frozen matrix includes 16 development and 16 held-out seeds for each of accelerometer-only, gyro-only, and combined noise, with the same noisy inputs replayed through historical and current cores. Per-seed historical yaw RMS medians are 0.98°/1.39° (accelerometer-only dev/held-out), 0.08°/0.07° (gyro-only), and 0.93°/1.24° (combined). The largest single absolute yaw error in the historical replay is 7.01°. Current Conservative's corresponding largest absolute errors are 4.40°, 0.67°, and 4.31° across dev/held-out cells. Details and percentiles are in [the baseline](BASELINE.md) and raw result CSV.

The handoff's original pure-roll report (~2.91° median and ~11.32° maximum yaw error) cannot be reproduced exactly because the former generator, CSV, and seed/time history are unavailable. The recreated run is explicitly not presented as an exact match.

## Evaluator regression

`./tools/run_bundle_a_checks.sh` executes `tests/test_benchmark_tilt_metric.cpp`. The test constructs a nonzero-tilt truth quaternion and applies a relative world-yaw-only rotation. Protocol v2 reports zero tilt error and retains nonzero full attitude error; protocol v1 reports 22.697° false tilt for the fixture. A common global world-yaw transform leaves the v2 tilt result unchanged.

`./tools/run_bundle_b_checks.sh` executes `tests/test_summarizer_protocol.py`. It verifies that a protocol-v1/unversioned CSV fails with a clear protocol-v2 error instead of being interpreted using the corrected metric.

The original test-first failures and subsequent passes are retained as `tilt_metric_red.log` / `tilt_metric_green.log` and `summarizer_protocol_red.log` / `summarizer_protocol_green.log` under `remediation/evidence/`.

## Runtime-aid diagnostic

The synthetic `TRUSTED_AIDED` heading proxy is not a physical sensor test. In combined-noise pure roll, default Conservative median yaw RMS changed from 0.80° to 1.68° on development seeds and from 0.90° to 1.80° on held-out seeds; median tilt RMS changed from 0.19° to 1.70° and 0.25° to 1.84°, respectively. All outputs were available and each trial had 11 aid updates. This is a negative result, not an acceptance upper bound; its model/filter interaction remains open for diagnosis.
