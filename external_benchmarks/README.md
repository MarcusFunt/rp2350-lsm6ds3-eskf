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
