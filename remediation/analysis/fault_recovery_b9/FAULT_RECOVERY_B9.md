# B9 — ESKF range configuration and fault recovery

Date: 2026-11-17

## Recommendation

Keep the existing fault latches and stale-state invalidation. The BROAD atlas supports a different ESKF range profile for BROAD data, but it does not support changing the production LSM6DS3 settings: BROAD was recorded with a sensor configured for ±2000°/s and ±16g, while this firmware is configured for ±245°/s and ±4g.

Set `max_gyro_axis_rps` and `max_accel_axis_mps2` from the actual sensor model and its active full-scale register setting. `Eskf15` compares each axis independently against 98% of those configured limits. Do not infer a larger range from a large vector norm, a different dataset, or an assumed sensor variant. The B9 BROAD replay used 1960°/s and 15.68g limits with its 3500 µs sample period; the LSM6DS3 defaults remained unchanged.

## Observed lifecycle

| Event after initialization | Filter behavior | Can propagation resume without `reset()`? | `control_state_valid()` / runtime output |
|---|---|---|---|
| Duplicate or regressing timestamp | Reject that sample, mark `Degraded`, retain the last received and propagated timestamps, and do not set `reset_required`. | Yes, when a later timestamp is strictly newer and its interval is within the prediction limit. Health remains degraded. | The rejected sample leaves the prior state timestamp in place. After a later current propagation, `control_state_valid()` can be true; runtime output remains unavailable because health is not `Nominal`. |
| Short gap, above 1.7 expected periods and no more than 25 ms | Propagate using the current sample as a zero-order-hold input, inflate uncertainty, and mark `Degraded`; do not set `reset_required`. | Yes; subsequent samples propagate, but health does not return to `Nominal` automatically. | A current filter state can be control-valid, but runtime output is unavailable while degraded. Reset and alignment are needed to restore nominal runtime availability. |
| Gap longer than 25 ms, or prediction interval at or below 0.1 ms | Mark `Fault`, latch `reset_required`, advance the last-received timestamp but leave the propagated state timestamp unchanged. | No. Later samples are ignored while the reset latch is set. | `control_state_valid()` is false. Runtime health withholds output and reports the reset/freshness/estimator flags as applicable. |
| Configured per-axis range exceedance | Do not propagate the clipped sample; mark `Fault` and latch `reset_required`. If initialized, the last-received timestamp can move forward while the state timestamp remains at the last valid propagation. | No. A later in-range sample cannot reconstruct the motion hidden by clipping. | Invalid immediately after the fault, even though the stored quaternion is finite. The older state must not be published as current. |
| Non-finite IMU sample | Mark `Fault`; after initialization, latch `reset_required`. | No after an initialized-state fault. | Invalid and unavailable until explicit reset and reinitialization. |
| Explicit `reset()` | Clear state, covariance history, clocks, health/fault counters, and initialization windows. The filter retains the `Settings` supplied at construction. | It starts a new alignment sequence; it does not continue the previous pose. | Output remains unavailable while aligning. It becomes available only after fresh nominal output, current timestamps, verified calibration, and no reset latch. |

`control_state_valid()` indicates a current, initialized, non-faulted filter state. The runtime-health contract is stricter: it also requires fresh sensor and publication times, a verified calibration ID, `Health::Nominal`, and no reset latch. That distinction is intentional for degraded-but-current states.

## Recovery decision

- **Recoverable for propagation, still degraded:** a duplicate/regressing timestamp or a short gap can be followed by valid samples without losing the ability to propagate. The current health state does not automatically become nominal, so downstream runtime output remains unavailable until an explicit reset and startup alignment.
- **Unrecoverable without reinitialization:** long prediction gaps, non-finite measurements, and configured range exceedances latch reset. In each case the filter cannot claim that it observed the missing or clipped motion.
- **Range mismatch:** correct the caller's settings only when the actual sensor and active full-scale setting justify the change. A range setting changes protective limits; it is not an estimator tuning parameter. BROAD's range profile belongs only to those BROAD records.
- **Stale output:** consumers must gate on `control_state_valid()`, `state_timestamp_us()`, runtime-health availability, and their own freshness deadline. Never republish the last finite quaternion after a fault as though it describes the latest sensor time.

No production recovery-policy change was supported by this evidence. The tests confirm the current latching/reset behavior; the only configuration difference is a replay-only range profile for the differently configured BROAD sensor.

## Validation

The native lifecycle test covers a recoverable short gap, a duplicate timestamp, a default-range 500°/s latch, stale-state invalidation, no implicit fault recovery, reset plus re-alignment, BROAD-range acceptance, a long-gap latch, a non-finite sample, and runtime-health availability after nominal reinitialization.

Commands run:

```sh
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -I. tests/test_b9_fault_recovery.cpp -o /tmp/test_b9_fault_recovery
/tmp/test_b9_fault_recovery
python -m unittest discover -s tests -p test_b9_eskf_replay.py -v
```

Both commands passed. Native Windows validation also passed with MSYS2 UCRT64 `g++ 16.2.0`: `python -m unittest discover -s tests -p test_b9_eskf_replay.py -v` and a direct compile/run of `tests/test_b9_fault_recovery.cpp`. The compiler is installed at `C:\msys64\ucrt64\bin\g++.exe`; that directory is saved in the user PATH. `eskf15.hpp` and `runtime_health.hpp` were not changed for this milestone.
