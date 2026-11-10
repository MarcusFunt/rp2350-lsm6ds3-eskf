# PR3 statistical characterization status

## Gate

**PR3: OPEN. PR2: OPEN.** Results are synthetic host simulations and do not waive the known LegacyHeuristic yaw/bias regressions, synthetic-heading degradation, false-hint/zero-dwell coverage gaps, or covariance failures. The corrected protocol and estimator candidate are frozen. Development, held-out, and final-confirmation outputs are exposed; no tuning was performed from held-out or final-confirmation results.

## Protocol and generator

- Protocol v1 and v2 remain unchanged. Protocol v2 froze paired percentile bootstrap intervals and independent FNV-1a sensor/heading RNG streams.
- Protocol v2 omitted a disturbance start time for vibration. Its generator applied the 43 Hz additive accelerometer disturbance from the first sample, including the intended two-second stationary startup; all three ESKF policies remained in Aligning. The full v2 output is preserved and superseded by protocol v3.
- Protocol v3 adds `measurement_disturbances.start_s = 2.0` for vibration and leaves the estimator, seeds, noise, truth, and scoring unchanged. Its SHA-256 is `1fd3998d99a5d58ea8dd5b6149a38aad0ec90fa56a1d722ccf77280e9dc21cca`. The validator requires that exact start time; codegen gates only the v3 vibration disturbance. Input records use `PR3INP03` and carry the v3 protocol hash.
- Each command builds one generator and evaluator, creates one shared stream per trial, evaluates three ESKF policies on identical inputs, and emits CSV, JSON, provenance manifest, and SVG. Mahony and gyro-only, selected diagnostic traces, and full failure-oracle covariance capture are not implemented.

## Frozen run evidence

| Run | Seeds and conditions | Rows / shared inputs | Incomplete or failed | Vibration result | Evidence |
|---|---|---:|---:|---|---|
| Superseded v2 development | 4001–4100; 208 Hz nominal; baseline profile | 2,400 / 800 | 1,499 | 0% availability and 0/100 complete for each policy | [v2 report](../benchmarks/reports/pr3_protocol_v2_dev100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v2_dev100_208_nominal.json), [figure](../benchmarks/figures/pr3_protocol_v2_dev100_208_nominal.svg) |
| v3 development | 4001–4100; 208 Hz nominal; baseline profile | 2,400 / 800 | 1,499 | Conservative: 72.40% availability, 0/100 complete; Legacy: 73.64%, 0/100; ConfirmedOnly: 80.77%, 0/100 | [v3 report](../benchmarks/reports/pr3_protocol_v3_dev100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v3_dev100_208_nominal.json), [figure](../benchmarks/figures/pr3_protocol_v3_dev100_208_nominal.svg) |
| v3 held-out | 5001–5100; 208 Hz nominal; baseline profile | 2,400 / 800 | 1,492 | Conservative: 70.65% availability, 0/100 complete; Legacy: 77.87%, 2/100; ConfirmedOnly: 81.02%, 0/100 | [v3 held-out report](../benchmarks/reports/pr3_protocol_v3_heldout100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v3_heldout100_208_nominal.json), [figure](../benchmarks/figures/pr3_protocol_v3_heldout100_208_nominal.svg) |
| v3 final confirmation | 6001–6100; 208 Hz nominal; baseline profile | 2,400 / 800 | 1,487 | Conservative: 72.47% availability, 1/100 complete; Legacy: 76.71%, 1/100; ConfirmedOnly: 81.46%, 0/100 | [v3 final report](../benchmarks/reports/pr3_protocol_v3_final100_208_nominal_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v3_final100_208_nominal.json), [figure](../benchmarks/figures/pr3_protocol_v3_final100_208_nominal.svg) |

For paired mean differences, the report uses the preregistered 10,000-resample paired percentile bootstrap. Its 95% interval is not an individual-run bound. The evaluation window fixes 2,913 expected samples per 208 Hz trial; incomplete runs remain in the denominator.

## Remaining findings and limits

- **Fixed simulation defect:** v3 applies the vibration disturbance only after the stationary startup. Vibration availability is no longer zero, but near-total trial incompleteness remains; this is an estimator/output-validity failure signal, not a reason to change the simulation again.
- **Covariance validity:** across the v3 development, held-out, and final-confirmation splits, only 4 of 900 vibration estimator rows are complete (0/0/0, 0/2/0, and 1/1/0 by split for Conservative/Legacy/ConfirmedOnly). The three full 2,400-row runs contain 4,478 incomplete/failed rows of 7,200. The run summaries retain valid/covariance-valid counts and do not discard failed samples.
- **Slow-yaw diagnostic:** the seed-4001 200 Hz nominal case previously found 1,225 of 2,801 `eskf_confirmed_only` samples with non-positive-definite covariance while operational state remained current. This remains an unresolved implementation risk.
- **Stress startup:** the static 3x-white-noise seed-4001 smoke input did not initialize an estimator within the declared startup interval. No thresholds were tuned.
- These runs cover only baseline IMU-only/unknown-startup/no-aid at 208 Hz nominal. Other rates, stress modes, and startup/aid factors are **NOT_RUN**. Mahony/gyro-only comparisons, selected diagnostic traces, full failure-oracle covariance capture, and broad factor coverage remain outstanding. The untouched final-confirmation split is recorded above.
- Physical sensor behavior, RP2350 timing, FIFO reliability, resource measurements for the revised firmware, and control suitability remain unverified or **BLOCKED_HARDWARE**.

## Reproduction

Run from a clean checkout of the named source commit. The run manifest records compiler, protocol, generator/evaluator hashes, source SHA, seed split, per-input hashes, and `working_tree_dirty_at_run`.

```sh
python3 tools/run_pr3_benchmarks.py --split development --first-seed 4001 --last-seed 4100 --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir benchmarks/generated/pr3_dev100_208_nominal_v3 --source-commit 21782bb102203e5f807a72eddb97085ce1a9b13c --tree-dirty no
python3 tools/run_pr3_benchmarks.py --split held_out --first-seed 5001 --last-seed 5100 --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir benchmarks/generated/pr3_heldout100_208_nominal_v3 --source-commit e75f94713fba54cc83e66132c105e31f39a19a98 --tree-dirty no
python3 tools/run_pr3_benchmarks.py --split final_confirmation --first-seed 6001 --last-seed 6100 --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir benchmarks/generated/pr3_final100_208_nominal_v3 --source-commit 763f026216c0511ad3dde9d5b591a336a155a688 --tree-dirty no
```

The v1/v2/v3 protocol and codegen tests plus Bundle A/B/C checks passed for this branch. All three v3 seed splits are now exposed; allocate new disjoint seeds before any further tuning. The current PR3 and PR2 gates remain open.
