# B6: Canonical 6D Mahony and Madgwick fidelity

## Reference source and fidelity classification

B6 pins the maintained [`Mayitzin/ahrs` v0.4.0](https://github.com/Mayitzin/ahrs/tree/v0.4.0)
package at commit `6a94a803fdb87d7a1f757906b9282b524764a7f1`, with wheel
SHA-256 `7be83963d8021ae326d20b646c05a2218401e559f645bb5c2e40ff7dd54245d7`.
The `mahony.py` and `madgwick.py` source payloads byte-match the pinned Git
blobs. The package is MIT licensed. Its equation and API documentation records
the original parameter defaults and rad/s, m/s², and seconds units
([Mahony](https://ahrs.readthedocs.io/en/v0.4.0/filters/mahony.html),
[Madgwick](https://ahrs.readthedocs.io/en/v0.4.0/filters/madgwick.html));
x-io maintains the [original algorithm resources](https://x-io.co.uk/open-source-imu-and-ahrs-algorithms/).

The benchmark adapters implement the documented 6D equations in float64 and
are classified `faithful_reimplementation`, not `official_unmodified`. That
distinction is deliberate: the pinned Python methods return immediately when
gyro norm is exactly zero, skipping valid gravity feedback. The B6 adapters
preserve the canonical correction in that case. They also skip a mathematically
zero Madgwick gradient instead of normalizing a zero vector. The pinned package
is used as a differential source, not silently presented as identical on those
edge cases. Every source and project code hash is in
[`canonical_ahrs_b6_provenance_lock.json`](../../external_benchmarks/references/canonical_ahrs_b6_provenance_lock.json).

## Fixed configurations and conventions

| Variant ID | Fixed parameters | State |
|---|---|---|
| `mahony_reference_6d_ahrs_0.4.0_kp1.0_ki0.3_v1` | `kP=1.0 s⁻¹`, `kI=0.3 s⁻²` | Quaternion and gyro-bias estimate |
| `madgwick_reference_6d_ahrs_0.4.0_beta0.033_v1` | `β=0.033 rad/s` | Quaternion; 6D IMU variant has no integral bias state |
| `pr3_v5_mahony_internal_historical_v1` | Existing PR3 `kP=1.0`, `kI=0.05` | Historical replay only |

Both canonical adapters use the same B1 causal 6D contract: accelerometer in
m/s² specific force, gyro in rad/s, uniform declared timestamps, scalar-first
body-to-world quaternion in ENU, and no heading or magnetometer aid. The
default starting quaternion is identity; it selects an arbitrary startup yaw
gauge and does not make yaw observable. The first timestamp seeds the sample
clock; subsequent samples integrate with their measured interval. `reset`
clears the quaternion, sample clock and algorithm state. B1 hashes the complete
configuration, and each adapter also exposes a configuration identity.

For Mahony, the 6D residual is measured-up crossed with predicted body-up;
`b_dot = -kI * residual` and corrected angular rate is
`gyro - b + kP * residual`. The signed bias estimate is retained across samples.
Madgwick integrates the quaternion gyro derivative plus the normalized 6D
gravity-objective gradient scaled by β. `None` or accelerometer norm at or below
`1e-12 m/s²` skips accelerometer feedback while integrating valid gyro input;
non-finite or malformed vectors fail closed. These choices are declared in
the adapter source and tests.

## Pinned-source differential

On one 120-sample, 100 Hz synthetic input (SHA-256
`b4f4e0ceda9b0e3316ba2a2d1c52c6af19c8fe18eab9be41dc6edd9f9280b2e7`), the B6
equations matched the maintained package update methods on every nonzero-gyro
step:

| Comparison | Maximum quaternion component difference | Maximum geodesic difference |
|---|---:|---:|
| Mahony | `2.22e-16` | `3.50e-17 rad` |
| Madgwick | `2.22e-16` | `2.06e-17 rad` |

Separate tests confirm that the upstream package holds its quaternion on an
exact-zero gyro sample even when the accelerometer is tilted; the B6 equation
implementation still applies gravity feedback. The source difference is
therefore explicit and reproducible.

## Same-input comparison with repository history

The historical `mahony` in PR3 v5 is now identified in new output as
`mahony_internal_historical`. Its B1 manifest points to the original
`AttitudeBaseline` in `tools/pr3_evaluate_stream.cpp` and records the source
SHA-256. The [alias registry](../../external_benchmarks/adapters/mahony_variant_aliases_b6_v1.json)
maps only that PR3 v5 profile; frozen v1–v5 artifacts retain their stored label.
The historical replay uses the PR3 no-startup-calibration, no-heading profile.

The smoke run applies each exact same input hash to the canonical references and
the historical replay. The table reports the maximum per-sample quaternion
separation under the shared identity startup gauge. It describes disagreement
between algorithms, not accuracy or independent sample-level statistical
evidence.

| Synthetic stream | Samples | Mahony vs historical max | Madgwick vs historical max | Mahony vs Madgwick max |
|---|---:|---:|---:|---:|
| 25° tilted stationary, zero gyro | 1,000 | `0.06433 rad` | `0.25803 rad` | `0.31702 rad` |
| Constant 0.45 rad/s body roll | 1,000 | `0.000663 rad` | `0.004313 rad` | `0.004310 rad` |
| Stationary with 0.08 rad/s gyro bias | 1,000 | `0.05230 rad` | `0.08992 rad` | `0.14080 rad` |
| Lateral acceleration pulse | 800 | `0.03971 rad` | `0.11932 rad` | `0.14999 rad` |

They nearly agree during the constant-rate rotation because gyro propagation
dominates and all three start from the same orientation. They separate more on
the zero-rate tilt and acceleration pulse because Mahony's proportional and
integral feedback, Madgwick's gradient descent, and the historical baseline's
fixed `kI=0.05` use different correction rules. During constant gyro bias,
canonical Mahony estimates gyro bias with `kI=0.3`; Madgwick's 6D IMU mode has
no integral bias state. The acceleration pulse illustrates that neither
canonical reference in this step rejects sustained non-gravitational
acceleration.

The historical replay is a float64 Python reimplementation of the
`AttitudeBaseline` equations in the pinned PR3 C++ source. No C++ compiler was
available in the execution environment, so direct binary differential
validation of that replay was not run. The source hash is pinned, and
comparisons remain synthetic development evidence only.

## Reproduction

From the repository root, with Windows x86-64 CPython 3.11.4:

```powershell
python -m venv .venv-canonical-ahrs-b6
.\.venv-canonical-ahrs-b6\Scripts\Activate.ps1
python -m pip install --require-hashes -r external_benchmarks/references/requirements-canonical-ahrs-b6-win-cp311.lock.txt
python -m unittest tests.test_canonical_ahrs6d_adapters -v
python -m unittest tests.test_external_benchmark_contract tests.test_external_benchmark_metrics tests.test_canonical_ahrs6d_adapters
python scripts/run_canonical_ahrs_b6_smoke.py --output docs/external_benchmarks/canonical_ahrs_b6_smoke.json
```

No sealed trial was used for parameter choice or tuning. No BROAD scoring,
hardware validation, firmware port, or RP2350 resource measurement is included.
