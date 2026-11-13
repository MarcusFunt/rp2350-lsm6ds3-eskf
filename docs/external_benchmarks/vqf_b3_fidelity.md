# B3: Official VQF full causal 6D fidelity

## Reference and scope

This B3 baseline uses author-maintained VQF release `v2.1.2`, source commit
`86ba56bdd3158b9b05f9f9fe5596866ba326438c`, under the MIT license. The official
Python package provides the C++ implementation through its Cython
`vqf.VQF` binding and also provides the official pure-Python `vqf.PyVQF`
implementation. The adapter calls the C++-backed streaming API directly; it
does not copy or reimplement the algorithm. PyPI marks 2.1.2 as the latest
release at this step. The source distribution SHA-256 is
`2bf7134ffb181d518ac8c0855a239881c5a3e06e927605c351e72bbce1623233`; the
validated CPython 3.11 Windows x86-64 wheel SHA-256 is
`99eceab93e1cd671bdadbd344bd7115dc12d4b14ac99c64287a1f4cd02fd0211`.

The host adapter is independent of production firmware. Its only input mode is
causal, uniform 6D gyro-plus-accelerometer input. Every sample calls
`vqf.VQF.update(gyr, acc)` without magnetometer data and emits the official
`getQuat6D()` result. It never uses `getQuat9D`, `offlineVQF`, simulator truth,
or an independent heading. Output quaternions remain scalar-first, sensor/body
to ENU, with down gravity; yaw is startup-gauge relative and not absolute
north. Inputs use rad/s gyro, m/s² specific force, nanosecond or microsecond
timestamps and the rate configured on reset.

The sample run used CPython 3.11.4, NumPy 2.0.2 and `vqf` 2.1.2. All VQF
parameters were left at official defaults; the full parameter dictionary is
recorded in the JSON result and lock file. The sample rate was 100 Hz, with a
0.01 s period and 10,000,000 ns sample spacing. No real data, external dataset,
hardware, or ESKF code was involved.

## Fidelity results

The seven synthetic input sequences were replayed through the adapter, the
official C++-backed streaming class, official `PyVQF`, and the C++-backed
`updateBatch` path. Input and configuration hashes are recorded per sequence in
[`vqf_b3_fidelity.json`](vqf_b3_fidelity.json).

| Synthetic sequence | Samples | Max `PyVQF` vs C++ streaming error (rad) | Max C++ batch vs streaming error (rad) | Max batch quaternion component difference |
|---|---:|---:|---:|---:|
| Stationary | 500 | 0 | 0 | 0 |
| Yaw-only | 500 | 0 | 0 | 0 |
| Tilted stationary | 600 | 0 | 0 | 0 |
| Tilted world-yaw | 800 | 1.24e-16 | 1.24e-16 | 0 |
| Constant rate | 500 | 1.11e-16 | 1.11e-16 | 0 |
| Slowly varying rate | 500 | 5.56e-17 | 5.56e-17 | 0 |
| Acceleration pulse during rotation | 250 | 2.11e-17 | 6.94e-18 | 0 |

The adapter emitted componentwise identical quaternions to the official C++
wrapper at every sample. The largest reported geodesic comparison across the
three code paths was `1.24e-16 rad`, floating-point roundoff. C++ batch and
streaming quaternion components matched exactly for these inputs.

The tilted stationary output's final gravity-axis error was `2.10e-5 rad`
(`0.00120°`). In the 800-sample tilted world-yaw sequence, the final tilt error
was `1.70e-4 rad` (`0.00976°`) and the relative heading integration error
against the generated global-z rotation was also `1.70e-4 rad` (`0.00976°`).
These are deterministic functionality checks, not estimates of accuracy on
real sensor data.

The full filter reports a three-axis gyroscope bias estimate, bias uncertainty
and rest-detection state via `getBiasEstimate()` and `getRestDetected()`. The
adapter makes those values available only as adapter-specific diagnostics; it
does not fabricate an accelerometer-bias result or insert VQF-only fields into
the shared output record. VQF does not expose an accelerometer-bias estimate.
Bias values are algorithm-specific and have not been compared with ESKF states.

## Test and reproduction commands

From the repository root, after installing the pinned optional requirements:

```bash
python -m unittest tests.test_external_benchmark_contract tests.test_external_benchmark_metrics tests.test_vqf_full_6d_adapter -v
python scripts/run_vqf_b3_fidelity.py --output docs/external_benchmarks/vqf_b3_fidelity.json
```

The B3 tests cover stationary and tilted gravity alignment, yaw-only and
world-vertical yaw behavior, rotation with acceleration disturbance, aid
rejection, direct `getQuat6D()` parity, strict timestamp/rate configuration,
reset at a changed sample rate, inter-trial reset isolation, and C++ streaming
versus official Python and batch implementations. The report generator also
checks that the adapter source digest matches the versioned manifest.

No estimator tuning or external performance scoring was performed. OfflineVQF
is not a real-time variant and is excluded from this adapter and report.
