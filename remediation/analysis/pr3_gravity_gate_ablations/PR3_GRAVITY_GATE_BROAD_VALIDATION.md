# PR3 gravity-gate candidate — broad validation

Date: 2026-11-17 · candidate: gyro threshold 0.48 rad/s, dwell 7 samples, unchanged 0.20 m/s² acceleration-step threshold.

## Decision

Do not promote this global gate relaxation. It improves several stationary and compound-motion groups, but it consistently harms maneuver, timing-jitter, and stop/start cases across the held-out seeds. The overall paired tilt RMS is materially worse. Fault latching and stale-output behavior passed with the candidate settings and remain unchanged in production.

## Synthetic held-out matrix

The current B9 default filter and the temporary candidate were compiled from the current source commit and replayed on each identical input. Candidate overrides began at reported timestamp 3,000,000 µs, matching the scored-window start used in the development ablation. The frozen v5 archive supplied the held-out protocol and input hashes; all 4,800 regenerated streams matched those hashes. This covers eight scenarios, three rate modes, nominal and stress modes, and seeds 9001–9100 (100 seeds per scenario/rate/stress group). The current-source baseline reproduced the archived ESKF tilt RMS exactly on all 4,800 cells, and baseline/candidate Mahony scores matched within 0.0002°.

Across 4,800 paired ESKF trials, mean candidate-minus-current-baseline tilt RMS was **+1.399°**. The conservative paired 95% interval was **+1.264° to +1.533°** (the calculation uses a 1.984 critical value). The candidate was better on 1,464 trials, worse on 1,121, and tied at the reported precision on 2,215. It caused no estimator fault trials or stale outputs beyond the current baseline.

| Scenario | Trials | Baseline ESKF mean (°) | Candidate ESKF mean (°) | Paired change (°) | 95% interval (°) |
|---|---:|---:|---:|---:|---:|
| static | 600 | 2.745 | 1.019 | −1.726 | [−1.894, −1.558] |
| slow yaw | 600 | 2.726 | 0.959 | −1.767 | [−1.935, −1.599] |
| lateral acceleration | 600 | 3.264 | 3.254 | −0.010 | [−0.011, −0.009] |
| compound motion | 600 | 6.058 | 4.729 | −1.330 | [−1.428, −1.231] |
| vibration | 600 | 1.840 | 1.840 | 0.000 | [0.000, 0.000] |
| maneuver | 600 | 3.459 | 8.347 | **+4.889** | [+4.493, +5.285] |
| timing jitter | 600 | 3.461 | 8.330 | **+4.869** | [+4.476, +5.262] |
| stop/start | 600 | 2.655 | 8.921 | **+6.266** | [+5.754, +6.777] |

The large held-out regressions reproduce the development-seed signal. Relaxing the gyro gate increases gravity-update opportunities, but the Conservative innovation-angle gate still rejects many measurements, and accepted dynamic measurements can pull attitude and bias away from truth. This is not a safe shared policy despite the static, slow-yaw, and compound-motion gains.

## BROAD fast rotation

All four BROAD fast-rotation trials were replayed against the production filter baseline and compared on the exact same VQF, ESKF, and optical-reference timestamps. BROAD's documented 2000°/s and 16 g range profile was retained. Each baseline replay reproduced the frozen B9 metric within 0.0002°, and candidate/baseline validity masks matched on every trial.

| Trial | Baseline tilt RMS (°) | Candidate tilt RMS (°) | Change (°) | Candidate gravity updates accepted during movement | Fault |
|---|---:|---:|---:|---:|---|
| `06_undisturbed_fast_rotation_A` | 3.727 | 3.304 | −0.423 | 0 | none |
| `07_undisturbed_fast_rotation_B` | 4.613 | 4.068 | −0.545 | 0 | none |
| `08_undisturbed_fast_rotation_with_breaks_A` | 24.460 | 24.591 | +0.131 | 0 | none |
| `09_undisturbed_fast_rotation_with_breaks_B` | 1.238 | 0.982 | −0.256 | 0 | none |

The candidate accepted more gravity updates during non-moving portions of these recordings, but **no candidate gravity update was accepted during movement**. These results do not show that relaxing the gate improves high-rate motion estimation; they show a small, mixed effect from updates outside movement.

## Fault injection and safeguards

The lifecycle test passed with both baseline settings and the candidate's 0.48 rad/s / 7-sample settings. It covered short-gap degradation, duplicate timestamps, a default-range 500°/s range fault, stale-state invalidation, explicit reset and re-alignment, BROAD-range acceptance, long-gap latching, and non-finite input. All five assertion groups passed in both runs. Candidate BROAD replays had identical validity masks and no fault; held-out candidate replays reported zero fault trials.

No fault latch, range check, reset lifecycle, runtime-health check, or stale-output safeguard was edited. Keep those protections as-is.

## Reproduction and evidence

- `run_heldout_gate_validation.py` reproduces both current-source held-out runs, verifies each generated stream against the frozen input hashes, and writes `heldout_rate_0p48_dwell_7_trials.csv` plus `heldout_rate_0p48_dwell_7_summary.json`. Each CSV row carries current baseline, candidate, and historical archived ESKF scores.
- `run_broad_gate_validation.py` replays all four BROAD fast-rotation trials and writes `broad_fast_rotation_gate_candidate.csv` plus `broad_fast_rotation_gate_candidate.json`.
- `validate_fault_gate_candidate.py` runs baseline and candidate-setting lifecycle checks and writes `fault_gate_candidate_validation.json`.
- The earlier development-seed ablations remain in `PR3_GRAVITY_GATE_ABLATIONS.md`; production `eskf15.hpp` was not changed by these experiments.

This is host simulation and replay evidence, not hardware qualification.
