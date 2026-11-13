# External estimator benchmark contract

This package defines a host-side interface for comparing estimators on one
shared input stream. It is independent of the production firmware: it imports
no RP2350, sensor-driver, or ESKF code and has no third-party Python runtime
dependency. No reference algorithms or datasets are installed by this package.

## Versioned records

- `schema/imu_trial_v1.schema.json` is one complete normalized trial, with a
  sample count, raw-source identifier/hash, declared sensor set, timestamps,
  units, frames, validity flags, and optional typed aid.
- `schema/adapter_manifest_v1.schema.json` records stable adapter/variant IDs,
  supported modes, initialization and warmup assumptions, reset semantics,
  output convention, source-fidelity class, source revision, implementation
  SHA-256, adapter SHA-256, optional model SHA-256, and license.
- `schema/estimator_output_v1.schema.json` records one output per input sample,
  the common canonical input hash, per-variant configuration hash, execution
  mode, and the adapter manifest used for the run.

The schemas use JSON Schema Draft 2020-12 and reject undeclared fields. The
Python API adds checks that require comparing records: sample-count agreement,
strict timestamp ordering and rate consistency, aid/sensor-set matching,
output/input identity, and output timestamp/index parity. SHA-256 values are
lowercase 64-character hexadecimal strings. Canonical hashes use sorted,
compact UTF-8 JSON with non-finite values forbidden. The raw artifact hash and
canonical trial input hash are distinct fields with distinct meanings.

## Units, frames, and attitude

Input acceleration is specific force in m/s²; gyroscope values are rad/s.
Timestamps are nonnegative integer nanoseconds or microseconds, declared once
in the timebase and repeated in the units block. Uniform rates use a reduced
rational `{numerator, denominator}` in Hz; irregular trials declare a null
nominal rate. Timestamps must strictly increase. The basic step API accepts
complete valid samples; an invalid/missing sensor record must be represented
by a different, explicitly versioned gap-aware protocol rather than silently
filled with zero.

The canonical body frame is right-handed sensor body. The world frame is ENU
(east, north, up), so gravity acceleration is `[0, 0, -9.80665]` m/s².
Accelerometer values are specific force: at rest they point opposite the
gravity vector expressed in the body frame.

Output quaternion `q_world_from_body` is scalar-first `[w,x,y,z]` and actively
rotates body-frame vectors into ENU world coordinates. A world-to-body
quaternion is not interchangeable; adapters must convert it before output.
Quaternion sign is geometrically equivalent (`q` and `-q` represent the same
rotation), and valid outputs must be finite and unit length within 1e-3.

Every valid orientation declares its yaw gauge:

- `unobservable_startup`: six-axis IMU-only yaw is an arbitrary startup gauge,
  not magnetic north.
- `independent_heading`: an explicitly declared heading aid is present in the
  trial and its source is independent of the IMU.
- `magnetic_reference`: a declared nine-axis magnetometer stream is present;
  this identifies the magnetic reference only when its calibration supports
  that interpretation.
- `provided_initial_yaw`: initialization used an explicit configured yaw.

The v1 input has two closed sensor modes. `gyro_accel_6d` accepts an optional
independent heading aid and forbids magnetometer data. `gyro_accel_mag_9d`
requires one body-frame magnetometer vector in µT at every sample. Each sample
has at most one aid record in v1; simultaneous independent heading plus 9D
magnetometer input requires a future schema version.

## Adapter API and execution modes

A causal online adapter implements:

```python
class FilterAdapter(Protocol):
    manifest: Mapping[str, object]

    def reset(self, config: Mapping[str, object]) -> None: ...

    def step(
        self,
        timestamp: int,
        accel_mps2: Sequence[float],
        gyro_rad_s: Sequence[float],
        aid: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]: ...
```

`run_trial(adapter, trial, config)` validates the declaration and input,
calls `reset(config)` once per trial, then calls `step` in timestamp order.
Every step must return orientation validity and status; the quaternion is null
when the orientation is invalid. Bias, covariance, navigation, and processing
time are optional and remain absent/N/A when unavailable. `check_reset_isolation`
replays a target trial fresh and after an intervening trial, rejecting output
differences that reveal retained state.

## Independent scoring math

`external_benchmarks.metrics` is pure Python host-side scoring code. It imports
no firmware or filter code and requires no third-party runtime packages. Its
quaternions are scalar-first `q_world_from_body` rotations into right-handed
ENU; angular results are radians.

- `gravity_tilt_error_rad` compares estimated and true gravity directions in
  the body frame. It ignores global yaw by construction, so it is usable with
  six-axis IMU-only estimates.
- `geodesic_error_rad` is the sign-invariant shortest SO(3) angle. `q` and
  `-q` represent the same rotation; identical estimate/truth scores exactly
  zero within floating point roundoff handling.
- `heading_rad` is the ENU azimuth of body +X; it returns `None` if that axis
  has a singular horizontal projection. Absolute heading error requires a
  declared reference source. With only accelerometer and gyroscope data,
  gravity constrains tilt but not rotation about gravity; initial yaw is a
  gauge and integrated yaw also accumulates unknown gyro bias. Such runs may
  report `relative_heading_drift_rad`, which removes the declared startup
  heading difference.
- `to_project_frame` and `from_project_frame` take an explicit
  `q_project_from_broad` mapping and compose it on the left. The improvement
  plan describes BROAD `opt_quat` as scalar-first ENU, already the project
  world frame; use identity for that mapping unless verified source metadata
  says otherwise. No frame conversion is guessed.
- `trial_score_summary` reports absolute error RMS, lower-order-statistic P95,
  maximum, expected/valid counts, availability, longest outage, optional
  recovery time, and the same error/availability statistics per named segment.
  P95 uses PR3's frozen convention `sorted[int(q * (n - 1))]`. Outage duration
  runs from the first invalid expected instant (or segment start for a leading
  outage) through the next sample instant, or segment end for a trailing
  outage. If no segment end is supplied, the final interval uses the median
  observed sample spacing; a one-sample trial requires an explicit end.
  Recovery time is measured to the start of the first valid, below-threshold
  run whose sample instants span the requested dwell; an optional maximum gap
  can break that run.
- `paired_trial_statistics` accepts exactly one metric summary per independent
  `(trial_id, seed)`, requires complete pairing and matching input SHA-256, and
  bootstraps paired mean differences over those trial/seed units. It never
  treats correlated samples within one trial as replicates.

The tilt oracle is cross-checked against PR3's body-frame gravity-angle
calculation and the official BROAD
[`broad_utils.py`](https://github.com/dlaidig/broad/blob/7e2f8189bb4a3ac91eae32c69b6bc87f08a6e2ad/example_code/broad_utils.py)
at source revision `7e2f8189bb4a3ac91eae32c69b6bc87f08a6e2ad`, specifically
`calculateErrorQuatEarth`, `calculateInclinationError`, and
`calculateTotalError`. BROAD optical quaternions are ENU and its reference uses
global relative error `q_est * inverse(q_truth)`; its inclination angle equals
the angle between gravity directions. The upstream functions were executed on
250 deterministic synthetic quaternion pairs. This checks metric geometry; it
does not claim BROAD dataset performance or reproduce a published aggregate
score.

`execution_mode` is part of the versioned adapter identity, never a plot label
chosen after scoring. `run_trial` accepts only `causal_online`. An adapter
declared `offline_batch` is rejected by the online runner and must be evaluated
as a separately labeled offline result; it cannot be presented as a causal
real-time comparison. Similarly, `run_trial` rejects undeclared 6D/9D modes,
unsupported sample rates/time units, and unsupported aids. Truth-based
initialization is refused by default and must be handled as a separately
labeled oracle experiment.

## Run the contract tests

From the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_external_benchmark_contract.py' -v
```

These tests use a small deterministic contract fixture only. They do not
download, install, or score VQF, Seel/qmt, RIANN, Mahony, or Madgwick.

## Official VQF full causal 6D reference (B3)

The optional [`official.vqf` adapter](adapters/vqf_full_6d.py) is independent of
production firmware and wraps the author-maintained `vqf.VQF` Cython binding to
its C++ implementation. It runs one `update(gyr, acc)` per timestamp, returns
only `getQuat6D()`, supplies no magnetometer or heading aid, and accepts only
uniformly sampled 6D trials. It does not use the acausal `offlineVQF` function.
VQF bias telemetry is available through the adapter's separate `diagnostics()`
method; the shared output contract stays unchanged because VQF does not report
accelerometer bias.

The exact source commit, MIT license, PyPI artifact hashes, supported host
runtime and official default parameters are pinned in
[`vqf_full_6d_v2.1.2_lock.json`](references/vqf_full_6d_v2.1.2_lock.json) and
the adapter manifest. The measured synthetic fidelity results and all sample,
input and configuration hashes are in
[`vqf_b3_fidelity.json`](../docs/external_benchmarks/vqf_b3_fidelity.json);
the method and interpretation are documented in
[`vqf_b3_fidelity.md`](../docs/external_benchmarks/vqf_b3_fidelity.md).

Run the pinned B3 tests in an isolated environment:

```bash
python -m venv .venv-vqf-b3
# Activate the environment using the platform's normal command, then:
python -m pip install -r external_benchmarks/requirements-vqf-b3.txt
python -m unittest tests.test_vqf_full_6d_adapter -v
python scripts/run_vqf_b3_fidelity.py --output docs/external_benchmarks/vqf_b3_fidelity.json
```

This optional environment does not add dependencies to the shared contract or
firmware. The reference fixture is synthetic and is not an external performance
benchmark.

## Official Seel/OriEstIMU causal 6D reference (B4)

The optional [`official.qmt.oriEstIMU` adapter](adapters/qmt_oriestimu_6d.py)
wraps the author-maintained Seel/OriEstIMU in `dlaidig/qmt` release `v0.2.4`.
It uses `qmt.OriEstIMUBlock` one sample at a time, with 6D gyro-plus-
accelerometer input, no magnetic or independent heading aid, and no offline
filter path. The [official function documentation](https://qmt.readthedocs.io/en/latest/python_functions.html)
defines `Ts` in seconds, `tauAcc` / `tauMag` in seconds, `zeta` as the bias
estimation strength, and `initQuat` / `initBias`; the
[block documentation](https://qmt.readthedocs.io/en/latest/python_blocks.html)
documents the streaming API and reset command. The implementation and artifact
hashes are recorded in
[`qmt_oriestimu_v0.2.4_provenance_lock.json`](references/qmt_oriestimu_v0.2.4_provenance_lock.json).

The predeclared B4 parameter set uses the official streaming block's constructor
defaults (`tauAcc=2 s`, `tauMag=2 s`, `zeta=0`, `accRating=1`), with an explicit
identity `initQuat` and zero `initBias` applied by the documented reset. The
official batch function has different defaults (`tauAcc=1 s`, `tauMag=3 s`),
so those same streaming parameters are passed explicitly for parity checks.
`tauMag` is unused in the 6D path. This set is fixed for fidelity testing and
was not tuned against any dataset.

The Cython streaming method requires a magnetometer array even in 6D mode. The
adapter passes a zero vector: inspection of the pinned official C++ path
confirms that this disables magnetic correction, matching the batch wrapper's
`mag=None` behavior. The output is scalar-first body-to-world ENU, with down
gravity and startup-gauge yaw.

The pinned source's `resetEstimation` resets quaternion and bias but does not
clear `validAccDataCount` or its acceleration-rating window. Reusing a block
with only `command(["reset"])` therefore retains startup history. The adapter
constructs a fresh official block on every trial reset before issuing that
command. The measured counterexample and the adapter isolation result are in
[`qmt_b4_fidelity.json`](../docs/external_benchmarks/qmt_b4_fidelity.json),
with interpretation in
[`qmt_b4_fidelity.md`](../docs/external_benchmarks/qmt_b4_fidelity.md).

To create the pinned Windows CPython 3.11 environment and reproduce the B4
checks:

```bash
python -m venv .venv-qmt-b4
# Activate the environment using the platform's normal command, then:
python -m pip install -r external_benchmarks/references/requirements-qmt-b4-win-cp311.lock.txt
python -m unittest tests.test_qmt_oriestimu_6d_adapter -v
python scripts/run_qmt_b4_smoke.py --output docs/external_benchmarks/qmt_b4_fidelity.json
```

The fidelity report is a deterministic synthetic/API check. It does not run
BROAD, make real-data performance claims, tune parameters, or validate hardware.

## Official pretrained RIANN causal 6D reference (B5)

The optional [`official.riann` adapter](adapters/riann_pretrained_6d.py) wraps
the official [`daniel-om-weber/riann` release `v0.2.0`](https://github.com/daniel-om-weber/riann/tree/v0.2.0)
and its packaged `riann.onnx` weights. The source commit, wheel hash, inference
source hashes, actual ONNX model hash, Python packages, and ONNX Runtime
configuration are pinned in
[`riann_b5_provenance_lock.json`](references/riann_b5_provenance_lock.json).
The 1,471,345-byte model is installed from the official wheel and hash-checked
at adapter initialization; no model is retrained, converted, or vendored in the
firmware repository.

The adapter calls the official `RIANN.predict_step` once for each valid sample.
It accepts only causal, uniformly sampled 6D gyro-plus-accelerometer data at
50–500 Hz, using m/s² specific force, rad/s, and scalar-first
body-to-world quaternion output. It rejects heading and magnetometer aids and
marks yaw as startup-gauge relative. ONNX Runtime is pinned to the CPU provider,
sequential execution, one intra-op and inter-op thread, deterministic compute,
and full graph optimization. The wrapper leaves raw quaternion values
unchanged; it rejects non-finite or non-unit output instead of silently
normalizing it.

RIANN training exposure is recorded as
`training_exposure=BROAD_USED_IN_DEVELOPMENT` on every B5 result envelope and
sequence summary. The RIANN paper reports that BROAD and TUM-VI were used for
training and hyperparameter optimization, so BROAD must not be described as an
unseen generalization test for this model. See the [original paper](https://doi.org/10.3390/ai2030028).
The shared B1 output record remains algorithm-neutral; RIANN-specific saved
results use the B5 envelope to carry this mandatory exposure label.

From the repository root, reproduce the pinned checks on Windows CPython 3.11:

```bash
python -m venv .venv-riann-b5
# Activate the environment using the platform's normal command, then:
python -m pip install -r external_benchmarks/references/requirements-riann-b5-win-cp311.lock.txt
python -m unittest tests.test_riann_pretrained_6d_adapter -v
python scripts/run_riann_b5_smoke.py --output docs/external_benchmarks/riann_b5_smoke.json
```

The [B5 fidelity report](../docs/external_benchmarks/riann_b5_fidelity.md)
summarizes same-input batch/stream differences, state/reset behavior, causality,
quaternion checks, and desktop CPU timings. The JSON report records per-trial
input hashes and exposure labels. These synthetic host checks are not BROAD
scores or RP2350 latency/memory qualification.

## Canonical Mahony and Madgwick 6D references (B6)

B6 adds versioned causal 6D `mahony_reference` and `madgwick_reference`
adapters using fixed, documented parameters. Their equations are faithfully
reimplemented from the pinned maintained
[`Mayitzin/ahrs` v0.4.0 source](https://github.com/Mayitzin/ahrs/tree/v0.4.0)
and checked differentially on identical nonzero-rate inputs. The manifests say
`faithful_reimplementation`; these are not described as official unmodified
author code. See the
[B6 fidelity report](../docs/external_benchmarks/canonical_ahrs_b6_fidelity.md)
and [provenance lock](references/canonical_ahrs_b6_provenance_lock.json).

The adapters use rad/s, m/s² specific force, uniform timing, scalar-first
body-to-world quaternions in ENU, and an unobservable startup yaw gauge. Missing
or near-zero acceleration skips gravity correction while gyro integration
continues; malformed non-finite vectors fail closed. Mahony retains its
integral gyro-bias state, while the 6D Madgwick variant does not claim one.

The historical PR3 v5 label `mahony` is displayed in new comparisons as
`mahony_internal_historical`, as mapped by
[`mahony_variant_aliases_b6_v1.json`](adapters/mahony_variant_aliases_b6_v1.json).
The mapping does not rewrite frozen v1–v5 evidence. The historical baseline is
not the canonical Mahony reference.

Reproduce the locked checks on Windows CPython 3.11.4:

```powershell
python -m venv .venv-canonical-ahrs-b6
.\.venv-canonical-ahrs-b6\Scripts\Activate.ps1
python -m pip install --require-hashes -r external_benchmarks/references/requirements-canonical-ahrs-b6-win-cp311.lock.txt
python -m unittest tests.test_canonical_ahrs6d_adapters -v
python scripts/run_canonical_ahrs_b6_smoke.py --output docs/external_benchmarks/canonical_ahrs_b6_smoke.json
```

The synthetic differential is a development check only. It does not tune on
sealed trials, score BROAD, validate firmware, or claim RP2350 performance.
