# PR3 statistical characterization status

## Gate

**PR3: OPEN. PR2: OPEN.** The work here characterizes the accepted PR2 candidate and does not remediate or waive its known yaw/bias, synthetic-heading-aid, or false-hint/zero-dwell risks. All measurements are synthetic host simulations.

## Protocol and generator

- Protocol v1 remains unchanged as superseded evidence. Protocol v2 preregisters the paired percentile-bootstrap method (10,000 resamples, PRNG seed 20261110) and exact FNV-1a derivation for separate sensor and independent-heading random streams before any held-out or final-confirmation use.
- `tools/run_pr3_benchmarks.py` validates the protocol, builds the host generator/evaluator, generates one shared binary input per scenario/rate/stress/seed, and writes a per-trial summary, JSON provenance manifest, JSON report, and SVG figure.
- Binary inputs include truth, nominal/physical/reported timestamps, biases, IMU values, and independent/oracle heading values. Each file records the protocol digest; paired estimator rows share the input digest.
- The evaluator runs the three ESKF gravity policies: `eskf_conservative`, `eskf_legacy`, and `eskf_confirmed_only`. Protocol-listed Mahony and gyro-only estimates are **NOT_RUN**. Selected diagnostic traces and full failure-oracle covariance output are **NOT_IMPLEMENTED**.

## Current evidence

- Protocol validator, generated scenario runtime, exact NEES yaw-gauge reference, deterministic input regeneration, sample-noise PSD conversion, fixed-denominator evaluator, provenance checks, paired summary, bootstrap interval, and SVG output have smoke tests.
- The development seed `4001` static/200 Hz nominal smoke run produced 2,801 expected/propagated/valid samples for all three ESKF policies. It is a pipeline check only and does not establish statistical confidence.
- The development seed `4001` slow-yaw/200 Hz nominal run found 1,225 samples where `eskf_confirmed_only` covariance failed the positive-definite check while its operational state remained current. This remains open for PR2-level mathematical investigation.
- A static 3x-white-noise smoke input did not initialize any estimator within the declared startup interval. This is retained as a negative characterization result; startup thresholds were not changed.
- The 100-seed development distributions, 100-seed held-out distributions, untouched final-confirmation run, full PR3 factor matrix, and independent review are **NOT_RUN**.

## Reproduction

```sh
python3 tests/test_pr3_scenario_protocol.py
python3 tests/test_pr3_scenario_codegen.py
python3 tools/run_pr3_benchmarks.py --split development --first-seed 4001 --last-seed 4001 --scenarios static --rate-modes uniform_208hz --stress-modes nominal --profiles baseline --output-dir /tmp/pr3-smoke
```

Run broader seed/scenario/rate/stress selections by changing the command arguments. Do not use held-out or final-confirmation outputs for estimator selection. Physical sensor behavior, RP2350 timing, FIFO reliability, and control safety remain unverified.
