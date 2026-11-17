# PR3 ESKF gravity-gate ablations

Date: 2026-11-17 · protocol v5 · development seed 4001 · uniform 208 Hz.

Frozen reference: B9 commit `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973`; [baseline lock](../b9_reference_baseline/B9_REFERENCE_BASELINE.md). This analysis replays the exact B9 maneuver and compound-motion nominal/stress inputs. The four input hashes match the frozen B9 rows.

## Method

Eleven temporary ESKF setting variants replay the same four streams. Gyro-rate, adjacent acceleration-step and dwell gates are varied one at a time, followed by three combined rate+dwell candidates. Overrides activate at reported timestamp 3,000,000 µs, the 2 s start of the fixed B9 score window; all earlier samples retain B9 settings. The step-dependent soft-noise scale is pinned at 0.20 m/s² while the step candidate gate changes. Production `eskf15.hpp` and gravity policy are unchanged.

ESKF and Mahony orientation RMS use the same 2,913 sample evaluation window (2–16 s inclusive). Gate, innovation, covariance and bias diagnostics below use those same samples. NIS and innovation are blank when no gravity update was attempted. The temporary filter patch SHA-256 is `67e928641b3868876de9be15b4dbb414aa649438baae1b9f4540b39601b8b5bb`.

All baseline ESKF and Mahony metrics reproduce B9 within 0.0002°, and Mahony metrics remain identical across the variants.

## Aggregate comparison

| Variant | Mean ESKF RMS (°) | Mean Mahony RMS (°) | Mean ESKF−Mahony (°) | Eval accepted / attempted | Angle rejects | NIS rejects | Candidate-gate failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 4.792 | 2.500 | +2.291 | 0 / 0 | 0 | 0 | 11652 |
| `gyro_0p24` | 4.792 | 2.500 | +2.291 | 0 / 10 | 10 | 0 | 11188 |
| `gyro_0p48` | 6.465 | 2.500 | +3.965 | 150 / 177 | 27 | 0 | 4522 |
| `gyro_0p96` | 8.573 | 2.500 | +6.073 | 193 / 274 | 81 | 0 | 1111 |
| `step_0p40` | 4.792 | 2.500 | +2.291 | 0 / 0 | 0 | 0 | 11652 |
| `step_0p80` | 4.792 | 2.500 | +2.291 | 0 / 0 | 0 | 0 | 11652 |
| `dwell_17` | 4.792 | 2.500 | +2.291 | 0 / 0 | 0 | 0 | 11652 |
| `dwell_7` | 4.792 | 2.500 | +2.291 | 0 / 0 | 0 | 0 | 11652 |
| `rate_0p48_dwell_17` | 6.670 | 2.500 | +4.169 | 151 / 180 | 29 | 0 | 4522 |
| `rate_0p48_dwell_7` | 6.179 | 2.500 | +3.679 | 155 / 184 | 29 | 0 | 4522 |
| `rate_0p96_dwell_7` | 7.590 | 2.500 | +5.090 | 201 / 281 | 80 | 0 | 1111 |

## Per-cell gate ablations

The first eight variants isolate one gate at a time. Error, update, innovation, covariance and bias values use the scored window.

| Variant | Case | ESKF RMS (°) | Mahony RMS (°) | ESKF Δ from B9 (°) | Accepted / attempted | Angle/NIS rejects | Innovation max (rad) | Covariance end (rad²) | Gyro-bias end (rad/s) | Accel-bias error end (m/s²) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `baseline` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `baseline` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 0 | 0 / 0 | — | 0.4757 | 0.0183 | 0.032 |
| `baseline` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `gyro_0p24` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `gyro_0p24` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `gyro_0p24` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 10 | 10 / 0 | 0.195 | 0.4757 | 0.0183 | 0.032 |
| `gyro_0p24` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `gyro_0p48` | maneuver / nominal | 12.927 | 2.967 | +9.055 | 33 / 60 | 27 / 0 | 0.437 | 0.0993 | 0.0651 | 0.266 |
| `gyro_0p48` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `gyro_0p48` | compound_motion / nominal | 2.864 | 2.032 | -2.362 | 117 / 117 | 0 / 0 | 0.056 | 0.0014 | 0.0073 | 0.713 |
| `gyro_0p48` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `gyro_0p96` | maneuver / nominal | 21.470 | 2.967 | +17.599 | 56 / 137 | 81 / 0 | 0.748 | 0.0396 | 0.0940 | 0.314 |
| `gyro_0p96` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `gyro_0p96` | compound_motion / nominal | 2.753 | 2.032 | -2.473 | 137 / 137 | 0 / 0 | 0.051 | 0.0012 | 0.0144 | 0.609 |
| `gyro_0p96` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `step_0p40` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `step_0p40` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `step_0p40` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 0 | 0 / 0 | — | 0.4757 | 0.0183 | 0.032 |
| `step_0p40` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `step_0p80` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `step_0p80` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `step_0p80` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 0 | 0 / 0 | — | 0.4757 | 0.0183 | 0.032 |
| `step_0p80` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `dwell_17` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `dwell_17` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `dwell_17` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 0 | 0 / 0 | — | 0.4757 | 0.0183 | 0.032 |
| `dwell_17` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |
| `dwell_7` | maneuver / nominal | 3.872 | 2.967 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2120 | 0.0182 | 0.033 |
| `dwell_7` | maneuver / stress | 3.199 | 2.973 | +0.000 | 0 / 0 | 0 / 0 | — | 0.2775 | 0.0205 | 0.034 |
| `dwell_7` | compound_motion / nominal | 5.226 | 2.032 | +0.000 | 0 / 0 | 0 / 0 | — | 0.4757 | 0.0183 | 0.032 |
| `dwell_7` | compound_motion / stress | 6.871 | 2.029 | +0.000 | 0 / 0 | 0 / 0 | — | 0.8712 | 0.0204 | 0.032 |

## Candidate gravity-aiding policies

These three combined candidates retain the Conservative innovation-angle and NIS checks. The joined candidate trace exposes per-sample attitude, innovation, covariance and bias effects.

| Policy | Case | ESKF RMS (°) | Accepted / attempted | Angle rejects | Innovation mean / max (rad) | NIS mean / max | Covariance start / end / max (rad²) | Gyro-bias start → end (rad/s) | Accel-bias error start → end (m/s²) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `rate_0p48_dwell_17` | maneuver / nominal | 13.754 | 34 / 63 | 29 | 0.196 / 0.464 | 0.332 / 0.931 | 0.0037 / 0.0974 / 0.0974 | 0.0182 → 0.0702 | 0.033 → 0.270 |
| `rate_0p48_dwell_17` | maneuver / stress | 3.199 | 0 / 0 | 0 | — | — | 0.0638 / 0.2775 / 0.3104 | 0.0205 → 0.0205 | 0.033 → 0.034 |
| `rate_0p48_dwell_17` | compound_motion / nominal | 2.855 | 117 / 117 | 0 | 0.027 / 0.052 | 0.143 / 0.491 | 0.0035 / 0.0014 / 0.0216 | 0.0183 → 0.0086 | 0.033 → 0.702 |
| `rate_0p48_dwell_17` | compound_motion / stress | 6.871 | 0 / 0 | 0 | — | — | 0.0638 / 0.8712 / 0.8712 | 0.0205 → 0.0204 | 0.032 → 0.032 |
| `rate_0p48_dwell_7` | maneuver / nominal | 13.913 | 34 / 63 | 29 | 0.196 / 0.470 | 0.323 / 0.938 | 0.0037 / 0.0974 / 0.0974 | 0.0182 → 0.0711 | 0.033 → 0.268 |
| `rate_0p48_dwell_7` | maneuver / stress | 2.933 | 1 / 1 | 0 | 0.024 / 0.024 | 0.005 / 0.005 | 0.0638 / 0.2223 / 0.2223 | 0.0205 → 0.0211 | 0.033 → 0.034 |
| `rate_0p48_dwell_7` | compound_motion / nominal | 2.907 | 118 / 118 | 0 | 0.027 / 0.056 | 0.148 / 0.553 | 0.0035 / 0.0015 / 0.0210 | 0.0183 → 0.0093 | 0.033 → 0.695 |
| `rate_0p48_dwell_7` | compound_motion / stress | 4.965 | 2 / 2 | 0 | 0.042 / 0.070 | 0.014 / 0.021 | 0.0638 / 0.0866 / 0.4683 | 0.0205 → 0.0149 | 0.032 → 0.031 |
| `rate_0p96_dwell_7` | maneuver / nominal | 20.312 | 58 / 138 | 80 | 0.257 / 0.697 | 0.323 / 0.708 | 0.0037 / 0.0402 / 0.0402 | 0.0182 → 0.0867 | 0.033 → 0.388 |
| `rate_0p96_dwell_7` | maneuver / stress | 2.933 | 1 / 1 | 0 | 0.024 / 0.024 | 0.005 / 0.005 | 0.0638 / 0.2223 / 0.2223 | 0.0205 → 0.0211 | 0.033 → 0.034 |
| `rate_0p96_dwell_7` | compound_motion / nominal | 2.706 | 138 / 138 | 0 | 0.029 / 0.054 | 0.173 / 0.639 | 0.0035 / 0.0013 / 0.0043 | 0.0183 → 0.0139 | 0.033 → 0.608 |
| `rate_0p96_dwell_7` | compound_motion / stress | 4.411 | 4 / 4 | 0 | 0.036 / 0.063 | 0.023 / 0.043 | 0.0638 / 0.0698 / 0.2295 | 0.0205 → 0.0111 | 0.032 → 0.025 |

## Findings

The B9 conservative gate formed zero gravity measurements across the four scored cells: all 2,913 samples per cell failed candidate eligibility, with the gyro-rate gate failing throughout. The 14 accepted updates seen in each nominal baseline run occurred before scoring. Baseline has no evaluation-window innovation or NIS values; those are unmeasured, not zero.

Changing the acceleration-step threshold or dwell alone had no scored-window effect. With the default 0.12 rad/s gyro limit, all motion samples still failed candidate eligibility. Raising the gyro limit to 0.24 rad/s opened 10 attempts in compound-motion nominal; all 10 failed the Conservative innovation-angle check.

Relaxing gyro rate to 0.48 or 0.96 rad/s opened the gate but degraded maneuver nominal: ESKF RMS increased from 3.872° to 12.927° or 21.470° in the one-at-a-time runs. Twenty-seven or 81 attempts were rejected by the innovation-angle check; accepted updates also harmed the state. End gyro-bias error rose from 0.0182 to 0.0651 or 0.0940 rad/s, and accelerometer-bias error rose from 0.033 to 0.266 or 0.314 m/s². NIS rejected none.

Compound-motion nominal improved from 5.226° to 2.864° or 2.753° under the same gyro relaxations, but stayed behind Mahony at 2.032°. ESKF accelerometer-bias error ended at 0.713 or 0.609 m/s². Covariance remained positive definite. The global relaxation therefore helps compound nominal and harms maneuver nominal; it is not safe to promote. Stress cases gain only one to four accepted updates with the combined short-dwell policies and retain larger orientation error.

The traces point to a measurement-model problem under dynamic acceleration, not covariance loss. The baseline gate blocks gravity before innovation formation, while indiscriminately opening the gate can make the gravity direction absorb linear acceleration into attitude and accelerometer bias. No candidate is promoted to production. A safer follow-up is an orientation-only gravity correction or a motion-aware acceleration rejection policy on these same cells, followed by more seeds and scenarios.

## Artifacts

- `evaluation_gate_ablation_diagnostics.csv` and `.json`: scored-window gate, innovation, covariance and bias summaries for all 44 variant/cell combinations.
- `candidate_policy_diagnostics.csv` and `.json`: B9 baseline versus three candidates across the same four cells.
- `traces/gravity_gate_candidate_seed4001.csv.gz`: per-sample paired orientation errors, bias state, covariance, innovation and gate outcomes for the combined candidates.
- `pr3_gravity_gate_ablation_results.json` and `pr3_gravity_gate_ablation_summary.csv`: replay metrics, whole-run counters, B9 input checks and source hashes.
- `run_gate_ablation.py` and `summarize_gate_ablation.py`: reproducible WSL replay and report generation.

This is selected development-seed simulation evidence. The frozen B9 reference files remain unchanged; no hardware validation is implied.
