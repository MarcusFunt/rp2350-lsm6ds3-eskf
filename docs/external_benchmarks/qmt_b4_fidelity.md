# B4: Official Seel/OriEstIMU causal 6D fidelity

## Reference and configuration

This adapter wraps the author-maintained `qmt.OriEstIMUBlock` from
[`dlaidig/qmt`](https://github.com/dlaidig/qmt), release `v0.2.4`, source
commit `0fa8d32eb461e14d78e9ddbd569664ea59bcea19`, under MIT. It is the
Seel/Ruppin OriEstIMU implementation. It is distinct from the VQF estimator
and the B3 adapter. The qmt algorithm source is not vendored or modified.

The adapter is host-side and independent of production firmware. It accepts
only causal, uniformly sampled gyro-plus-accelerometer (6D) input, makes one
official streaming `step` call per sample, supplies neither magnetometer nor
independent heading aid, and emits scalar-first body-to-world quaternion in
ENU. Input gyro is rad/s; acceleration is m/s² specific force; timestamps are
integer ns or us and must match the configured uniform rate. Yaw is
startup-gauge relative because gravity cannot observe rotation about gravity.

The selected primary variant is predeclared from the official streaming block
constructor defaults: `tauAcc=2 s`, `tauMag=2 s`, `zeta=0`, and `accRating=1`.
The adapter explicitly resets to identity `initQuat=[1,0,0,0]` and zero
`initBias`. `Ts` is the reciprocal of configured sample rate, in seconds.
`tauMag` is unused in 6D; `zeta=0` disables bias adaptation. The official
batch-function defaults differ (`tauAcc=1 s`, `tauMag=3 s`, with unspecified
initial quaternion/bias), so the parity run passes the streaming parameter set
and reset state explicitly. This is a fidelity comparison, not parameter
tuning. The complete source, wheel, dependency, and implementation-file hashes
are in
[`qmt_oriestimu_v0.2.4_provenance_lock.json`](../../external_benchmarks/references/qmt_oriestimu_v0.2.4_provenance_lock.json).

The public Cython `OriEstIMUBlock.step` signature requires a magnetometer
array. The adapter passes a zero 3-vector for the no-magnetometer path. In the
pinned C++ source this sentinel skips magnetic correction; the official batch
wrapper's `mag=None` creates the same zero sentinel. It is not a magnetic
measurement or a heading aid.

The official reset command sets the quaternion to identity and gyro bias to
zero, but source inspection shows `resetEstimation` does not clear
`validAccDataCount` or its acceleration-rating window. Thus calling only
`command(["reset"])` on a reused block does not reproduce a new trial's startup
behavior. The adapter creates a fresh upstream block on every `reset(config)`
and then issues that official reset command.

## Synthetic fidelity results

The pinned environment is CPython 3.11.4, NumPy 1.26.4, qmt 0.2.4, and VQF
2.1.2 (a qmt dependency). The qmt CPython 3.11 Windows wheel failed to import
with NumPy 2.0.2 due to its compiled NumPy ABI, so the reproducible lock pins
NumPy 1.26.4. No firmware, BROAD data, real sensor data, or hardware was used.

Seven deterministic sequences (3,550 samples total) were serialized as B1
trials. Both the B1 online runner and qmt batch function consumed the exact
same values reconstructed from each serialized trial; each source artifact
hash, canonical input hash, and config hash is recorded in
[`qmt_b4_fidelity.json`](qmt_b4_fidelity.json).

| Synthetic sequence | Samples | Max streaming/batch geodesic error (rad) | Max quaternion norm error | Additional check |
|---|---:|---:|---:|---|
| Stationary | 300 | 0 | 0 | exact rest identity |
| Yaw-only | 300 | 0 | 0 | gyro-integrated yaw error `2.44e-15 rad` |
| Tilted stationary, 35° | 1,000 | 0 | `1.11e-16` | final attitude and gravity-axis error `1.81e-5 rad` (`0.00104°`) |
| Tilted world yaw | 800 | `1.24e-16` | `2.22e-16` | component outputs identical |
| Constant rotation | 400 | `1.11e-16` | `2.22e-16` | component outputs identical |
| Slowly varying rate | 500 | `1.11e-16` | `1.11e-16` | component outputs identical |
| Acceleration pulse | 250 | `1.37e-17` | `1.11e-16` | component outputs identical |

All seven streams had exact componentwise streaming/batch quaternion equality;
the largest geodesic computation was `1.24e-16 rad`, floating-point roundoff.
The maximum unit-norm deviation was `2.22e-16`. Processing the first 200
samples of the 800-sample tilted-yaw trajectory as a separate trial produced
the exact same output prefix, confirming causal behavior for this fixture.
This verifies implementation fidelity on synthetic inputs, not estimator
accuracy on a public or held-out dataset.

## Reset and state isolation result

After a 100-sample preceding trial, reusing an upstream block and issuing only
`command(["reset"])` changed the following 100-sample, 60° tilted target
trajectory by a maximum geodesic distance of `0.9423724533 rad` (about 54°)
relative to a new block. The adapter's fresh-block reset produced exact
componentwise equality with a separate fresh adapter (`0` maximum component
difference). The isolated reset test covers this upstream defect and the
adapter's correction without changing qmt itself.

## Commands

From the repository root with the pinned optional dependencies installed:

```bash
python -m unittest tests.test_qmt_oriestimu_6d_adapter -v
python scripts/run_qmt_b4_smoke.py --output docs/external_benchmarks/qmt_b4_fidelity.json
python -m unittest tests.test_external_benchmark_contract tests.test_external_benchmark_metrics tests.test_vqf_full_6d_adapter tests.test_qmt_oriestimu_6d_adapter -v
```

The smoke command verifies package versions, adapter digest, batch/stream
parity, quaternion norms and synthetic geometry, causal prefix equality, and
reset isolation, then writes the machine-readable per-sequence evidence. The
qmt wheel and lock were validated on Windows CPython 3.11; other platforms and
Python versions have not been validated. No BROAD result or hardware validation
is claimed.
