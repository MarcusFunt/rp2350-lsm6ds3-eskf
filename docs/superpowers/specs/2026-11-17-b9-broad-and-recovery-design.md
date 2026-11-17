# B9 BROAD Failure Atlas and ESKF Recovery Design

Date: 2026-11-17

## Intent

Compare the production ESKF with official causal VQF 6D on the same BROAD IMU samples, then use the estimator traces to explain the maneuver, timing-jitter, and compound-motion synthetic losses and to validate the existing protective fault lifecycle.

## Goals

- Replay all 39 BROAD trials through VQF 2.1.2 and the production `Eskf15` implementation.
- Compare orientation errors only at sample timestamps where both estimator outputs are valid; retain per-estimator availability and fault timing so the intersection cannot hide a dropout.
- Run the ESKF both with its production LSM6DS3 range defaults and with BROAD's documented ±2000°/s and ±16g input ranges. Use the second run for the full trajectory comparison and the first as a range-mismatch fault control.
- Plot shared-time orientation-error traces and identify the first range-triggering samples in high-rate trials.
- Replay PR3 v5 development seed 4001 for `maneuver`, `timing_jitter`, and `compound_motion`, comparing Conservative ESKF with Mahony and joining truth, state, covariance, gravity gate/rejection, innovation, and bias traces.
- Characterize recoverable gaps, latched input faults, explicit reset/reinitialization, configured input ranges, and stale output behavior without weakening the production fault policy.

## Non-goals and anti-goals

- Do not change the production LSM6DS3 range defaults based on BROAD; the dataset uses a different sensor and its input range is an experiment configuration only.
- Do not tune estimator noise or gravity thresholds against BROAD or the selected synthetic development seed.
- Do not score magnetometer data: both VQF and ESKF use gyro plus accelerometer only.
- Do not treat six-axis absolute yaw as observable. Align only the startup heading gauge, report gravity tilt separately, and use BROAD's movement annotation for trial-level scores.
- Do not classify every near-threshold input as a sensor defect without distinguishing the sensor's configured full scale from legitimate motion.
- Do not publish a stale ESKF state as current after a latched fault.
- Do not copy the BROAD HDF5 dataset into this repository.

## Approaches

1. **Extend the synthetic benchmark only.** This would provide state and gate traces but could not expose the mismatch between the firmware's ±245°/s, ±4g defaults and BROAD's recorded hardware range.
2. **Compare only VQF and ESKF on BROAD defaults.** This is simple, but the ESKF's false saturation latch would censor the later trajectory and obscure whether the loss is caused by estimator behavior or configuration.
3. **Use a shared-sample, dual-range atlas (selected).** Run official VQF 6D, the unmodified production ESKF settings, and a second ESKF configured from BROAD's documented sensor range. Score VQF and the range-correct ESKF on their exact valid timestamp intersection; show the default-range fault separately. Reuse the PR3 diagnostic evaluator for the three synthetic cases, then validate recovery through the existing runtime-health contract.

## Design decisions

- Read the official BROAD HDF5 files directly from a user-supplied dataset directory. The tool must validate required datasets, shapes, finite values, timestamps, sample rate, and the movement mask before running any estimator.
- Use exact rational sampling rate `2000/7 Hz`; derive common integer-microsecond timestamps at 3500 µs spacing. Run filters over each full trial, including the annotated initial and final rest sections; use `movement` only when computing motion scores.
- Use the existing official `VQFFull6DAdapter` and a small native replay program linked to the repository's `eskf15.hpp`. Keep range configuration in the replay command, not in production defaults.
- Emit compact per-trial summaries for all trials. Save detailed per-sample traces and orientation-error figures only for selected range-fault and high-rate cases so the repository does not absorb the full dataset.
- Align each estimator's startup yaw gauge at the first common valid sample. Compute total geodesic and gravity-tilt errors at every common valid timestamp; report their movement-only RMS plus each estimator's availability, first invalid time, and longest invalid span.
- For the PR3 synthetic replay, use seed 4001, 208 Hz, nominal and stress modes, and the Conservative ESKF/Mahony pair. Keep the archived development trial metrics as a context check; do not use the selected trace as independent acceptance evidence.
- Preserve the current fault classes: short gaps may propagate with degraded health; over-limit, non-finite, and unmodeled long-gap faults remain latched and require explicit reset. A reset starts alignment again and preserves the constructed settings. Consumers must gate on current state time, `control_state_valid()`, and runtime freshness.
- Attribute BROAD to Laidig et al., the official repository revision, and its CC BY 4.0 license in the report.

## Success criteria

- All 39 trials are loaded and replayed with identical ordered IMU samples for all three methods; reported paired scores count only the exact shared valid timestamps during movement.
- Default-range faults are linked to measured per-axis values and configured thresholds. The BROAD-range replay completes the expected valid comparison interval without changing the production LSM6DS3 defaults.
- The three synthetic cases include time-aligned error, state/bias, covariance, gravity gate/rejection, and NIS traces with a concise evidence-based cause assessment.
- Fault-recovery tests show which events remain usable, which latch, how explicit reset reinitializes, and how stale/faulted output is withheld.
- Every report states the dataset revision, source/license, code/config hashes, commands, and synthetic-versus-recorded evidence boundaries.
