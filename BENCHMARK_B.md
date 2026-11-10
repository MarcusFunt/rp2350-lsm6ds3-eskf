# Bundle B: synthetic estimator comparison

Source CSV: `bundle_b_verified_startup_bias.csv`. Schema v2; metric definition v2; truth integration v2.
These are host-side synthetic results, not measured RP2350 or LSM6DS3 performance.

The checked-in eight-trial intervals are preliminary descriptive uncertainty under the stated simulator assumptions; they are not real-world accuracy bounds.

Each cell summarizes the arithmetic mean of per-trial RMS values with a two-sided 95% Student-t confidence interval and sample SD across trials. Missing values remain explicit.

## Per-trial RMS summary

| Scenario | Profile | Startup bias | Estimator | Trials | Tilt RMS mean [95% CI], deg | Tilt SD, deg | Yaw RMS mean [95% CI], deg | Yaw SD, deg | Valid fraction | Invalid samples |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| compound_motion | nominal | true | eskf_conservative | 8 | 0.425 [0.288, 0.562] (n=8) | 0.164 | 1.478 [0.476, 2.480] (n=8) | 1.199 | 1.0000 | 0 |
| compound_motion | nominal | true | eskf_legacy | 8 | 1.567 [1.088, 2.046] (n=8) | 0.573 | 9.590 [6.115, 13.065] (n=8) | 4.156 | 1.0000 | 0 |
| compound_motion | nominal | true | mahony | 8 | 15.861 [15.856, 15.866] (n=8) | 0.006 | 9.110 [9.013, 9.206] (n=8) | 0.115 | 1.0000 | 0 |
| compound_motion | stress | true | eskf_conservative | 8 | 0.904 [0.777, 1.031] (n=8) | 0.152 | 2.244 [1.393, 3.096] (n=8) | 1.018 | 1.0000 | 0 |
| compound_motion | stress | true | eskf_legacy | 8 | 1.993 [1.529, 2.456] (n=8) | 0.554 | 9.709 [6.145, 13.272] (n=8) | 4.262 | 1.0000 | 0 |
| compound_motion | stress | true | mahony | 8 | 15.844 [15.839, 15.849] (n=8) | 0.006 | 9.505 [9.405, 9.605] (n=8) | 0.120 | 1.0000 | 0 |
| lateral_accel | nominal | true | eskf_conservative | 8 | 0.261 [0.169, 0.354] (n=8) | 0.111 | 1.287 [0.617, 1.956] (n=8) | 0.801 | 1.0000 | 0 |
| lateral_accel | nominal | true | eskf_legacy | 8 | 12.448 [12.004, 12.892] (n=8) | 0.531 | 19.963 [-2.478, 42.404] (n=8) | 26.843 | 1.0000 | 0 |
| lateral_accel | nominal | true | mahony | 8 | 8.109 [8.092, 8.126] (n=8) | 0.020 | 0.177 [0.108, 0.246] (n=8) | 0.083 | 1.0000 | 0 |
| lateral_accel | stress | true | eskf_conservative | 8 | 0.392 [0.312, 0.472] (n=8) | 0.096 | 1.637 [0.989, 2.284] (n=8) | 0.774 | 1.0000 | 0 |
| lateral_accel | stress | true | eskf_legacy | 8 | 12.615 [12.362, 12.869] (n=8) | 0.303 | 20.449 [-0.300, 41.198] (n=8) | 24.819 | 1.0000 | 0 |
| lateral_accel | stress | true | mahony | 8 | 8.209 [8.192, 8.226] (n=8) | 0.021 | 0.564 [0.452, 0.676] (n=8) | 0.134 | 1.0000 | 0 |
| maneuver | nominal | true | eskf_conservative | 8 | 0.249 [0.170, 0.327] (n=8) | 0.094 | 0.530 [0.023, 1.037] (n=8) | 0.607 | 1.0000 | 0 |
| maneuver | nominal | true | eskf_legacy | 8 | 0.249 [0.170, 0.327] (n=8) | 0.094 | 0.530 [0.023, 1.037] (n=8) | 0.607 | 1.0000 | 0 |
| maneuver | nominal | true | mahony | 8 | 2.795 [2.792, 2.798] (n=8) | 0.004 | 1.940 [1.905, 1.975] (n=8) | 0.042 | 1.0000 | 0 |
| maneuver | stress | true | eskf_conservative | 8 | 0.485 [0.435, 0.534] (n=8) | 0.059 | 1.434 [0.890, 1.979] (n=8) | 0.651 | 1.0000 | 0 |
| maneuver | stress | true | eskf_legacy | 8 | 0.485 [0.435, 0.534] (n=8) | 0.059 | 1.434 [0.890, 1.979] (n=8) | 0.651 | 1.0000 | 0 |
| maneuver | stress | true | mahony | 8 | 2.848 [2.844, 2.852] (n=8) | 0.005 | 2.465 [2.420, 2.511] (n=8) | 0.054 | 1.0000 | 0 |
| slow_yaw | nominal | true | eskf_conservative | 8 | 0.124 [0.106, 0.143] (n=8) | 0.022 | 1.212 [0.598, 1.826] (n=8) | 0.734 | 1.0000 | 0 |
| slow_yaw | nominal | true | eskf_legacy | 8 | 0.127 [0.110, 0.144] (n=8) | 0.021 | 1.881 [1.101, 2.661] (n=8) | 0.933 | 1.0000 | 0 |
| slow_yaw | nominal | true | mahony | 8 | 0.125 [0.111, 0.139] (n=8) | 0.017 | 0.104 [0.024, 0.185] (n=8) | 0.096 | 1.0000 | 0 |
| slow_yaw | stress | true | eskf_conservative | 8 | 0.392 [0.369, 0.415] (n=8) | 0.028 | 2.378 [1.285, 3.470] (n=8) | 1.307 | 1.0000 | 0 |
| slow_yaw | stress | true | eskf_legacy | 8 | 0.393 [0.369, 0.417] (n=8) | 0.029 | 3.699 [1.925, 5.473] (n=8) | 2.122 | 1.0000 | 0 |
| slow_yaw | stress | true | mahony | 8 | 0.345 [0.332, 0.358] (n=8) | 0.016 | 0.391 [0.292, 0.490] (n=8) | 0.119 | 1.0000 | 0 |
| static | nominal | true | eskf_conservative | 8 | 0.133 [0.117, 0.148] (n=8) | 0.018 | 0.972 [0.492, 1.452] (n=8) | 0.574 | 1.0000 | 0 |
| static | nominal | true | eskf_legacy | 8 | 0.135 [0.119, 0.150] (n=8) | 0.019 | 1.300 [0.804, 1.796] (n=8) | 0.594 | 1.0000 | 0 |
| static | nominal | true | mahony | 8 | 0.130 [0.111, 0.149] (n=8) | 0.023 | 0.283 [0.150, 0.415] (n=8) | 0.159 | 1.0000 | 0 |
| static | stress | true | eskf_conservative | 8 | 0.368 [0.343, 0.394] (n=8) | 0.030 | 3.899 [2.044, 5.753] (n=8) | 2.218 | 1.0000 | 0 |
| static | stress | true | eskf_legacy | 8 | 0.377 [0.333, 0.422] (n=8) | 0.053 | 6.453 [3.090, 9.816] (n=8) | 4.023 | 1.0000 | 0 |
| static | stress | true | mahony | 8 | 0.348 [0.335, 0.361] (n=8) | 0.016 | 0.329 [0.135, 0.522] (n=8) | 0.231 | 1.0000 | 0 |
| stop_start | nominal | true | eskf_conservative | 8 | 0.332 [0.252, 0.412] (n=8) | 0.096 | 2.273 [1.075, 3.472] (n=8) | 1.434 | 1.0000 | 0 |
| stop_start | nominal | true | eskf_legacy | 8 | 1.407 [1.383, 1.431] (n=8) | 0.029 | 21.705 [16.894, 26.516] (n=8) | 5.755 | 1.0000 | 0 |
| stop_start | nominal | true | mahony | 8 | 1.946 [1.942, 1.949] (n=8) | 0.004 | 0.454 [0.360, 0.548] (n=8) | 0.112 | 1.0000 | 0 |
| stop_start | stress | true | eskf_conservative | 8 | 0.609 [0.561, 0.657] (n=8) | 0.058 | 8.096 [6.092, 10.101] (n=8) | 2.398 | 1.0000 | 0 |
| stop_start | stress | true | eskf_legacy | 8 | 1.516 [1.486, 1.545] (n=8) | 0.036 | 20.458 [16.070, 24.846] (n=8) | 5.249 | 1.0000 | 0 |
| stop_start | stress | true | mahony | 8 | 1.995 [1.992, 1.998] (n=8) | 0.004 | 0.473 [0.436, 0.510] (n=8) | 0.044 | 1.0000 | 0 |
| timing_jitter | nominal | true | eskf_conservative | 8 | 0.256 [0.185, 0.328] (n=8) | 0.085 | 1.216 [0.509, 1.922] (n=8) | 0.845 | 1.0000 | 0 |
| timing_jitter | nominal | true | eskf_legacy | 8 | 0.256 [0.185, 0.328] (n=8) | 0.085 | 1.216 [0.509, 1.922] (n=8) | 0.845 | 1.0000 | 0 |
| timing_jitter | nominal | true | mahony | 8 | 2.798 [2.796, 2.801] (n=8) | 0.003 | 1.994 [1.931, 2.056] (n=8) | 0.075 | 1.0000 | 0 |
| timing_jitter | stress | true | eskf_conservative | 8 | 0.538 [0.491, 0.586] (n=8) | 0.057 | 1.829 [1.236, 2.422] (n=8) | 0.710 | 1.0000 | 0 |
| timing_jitter | stress | true | eskf_legacy | 8 | 0.538 [0.491, 0.586] (n=8) | 0.057 | 1.829 [1.236, 2.422] (n=8) | 0.710 | 1.0000 | 0 |
| timing_jitter | stress | true | mahony | 8 | 2.851 [2.847, 2.855] (n=8) | 0.005 | 2.535 [2.453, 2.617] (n=8) | 0.098 | 1.0000 | 0 |
| vibration | nominal | true | eskf_conservative | 8 | 0.235 [0.104, 0.365] (n=8) | 0.156 | 0.998 [0.298, 1.698] (n=8) | 0.837 | 1.0000 | 0 |
| vibration | nominal | true | eskf_legacy | 8 | 0.235 [0.104, 0.365] (n=8) | 0.156 | 0.998 [0.298, 1.698] (n=8) | 0.837 | 1.0000 | 0 |
| vibration | nominal | true | mahony | 8 | 1.155 [1.148, 1.162] (n=8) | 0.008 | 0.355 [0.237, 0.474] (n=8) | 0.142 | 1.0000 | 0 |
| vibration | stress | true | eskf_conservative | 8 | 0.410 [0.306, 0.514] (n=8) | 0.124 | 1.493 [0.678, 2.308] (n=8) | 0.975 | 1.0000 | 0 |
| vibration | stress | true | eskf_legacy | 8 | 0.410 [0.306, 0.514] (n=8) | 0.124 | 1.493 [0.678, 2.308] (n=8) | 0.975 | 1.0000 | 0 |
| vibration | stress | true | mahony | 8 | 1.260 [1.253, 1.267] (n=8) | 0.009 | 0.995 [0.831, 1.159] (n=8) | 0.196 | 1.0000 | 0 |

## Run provenance

- Seed: `20261110`; 8 trials per scenario/profile; schedule v1 (`base_seed + 1009*trial_id + 103*scenario_name_length; version 1 preserves legacy offsets`).
- Simulator rate and duration: 200 Hz, 16 s; truth integration v2; startup bias: true; profiles: nominal, stress.
- Compiler: `11.4.0`; Git SHA: `85e6d22ca3475885a1958ac8f8669868e8c331ec`; working tree: `dirty`.
- C++ standard library: `libstdc++-20230528`.
- Sensor configuration hash (FNV-1a 64): `38b5cfb223616126`.

## Paired differences

Estimator delta is `model A minus model B`; negative values mean A had lower error. Stress delta is `stress minus nominal`; positive values mean higher error under stress. A pair is included only when its `valid_mask` matches exactly. Mask mismatches are reported and excluded.

| Comparison | Scenario | Profile | Estimator/metric | Mean delta [95% CI] | SD | Pairs | Missing | Mask mismatches |
|---|---|---|---|---:|---:|---:|---:|---:|
| estimator | compound_motion | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | -1.141 [-1.665, -0.618] (n=8) | 0.626 | 8 | 0 | 0 |
| estimator | compound_motion | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | -8.112 [-12.032, -4.192] (n=8) | 4.689 | 8 | 0 | 0 |
| estimator | compound_motion | nominal | eskf_conservative − mahony / tilt_rms_deg | -15.436 [-15.571, -15.301] (n=8) | 0.161 | 8 | 0 | 0 |
| estimator | compound_motion | nominal | eskf_conservative − mahony / yaw_rms_deg | -7.632 [-8.641, -6.623] (n=8) | 1.207 | 8 | 0 | 0 |
| estimator | compound_motion | nominal | eskf_legacy − mahony / tilt_rms_deg | -14.294 [-14.777, -13.812] (n=8) | 0.577 | 8 | 0 | 0 |
| estimator | compound_motion | nominal | eskf_legacy − mahony / yaw_rms_deg | 0.480 [-2.953, 3.913] (n=8) | 4.106 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | -1.089 [-1.574, -0.604] (n=8) | 0.580 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | -7.465 [-11.040, -3.889] (n=8) | 4.276 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_conservative − mahony / tilt_rms_deg | -14.940 [-15.066, -14.814] (n=8) | 0.150 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_conservative − mahony / yaw_rms_deg | -7.261 [-8.087, -6.434] (n=8) | 0.989 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_legacy − mahony / tilt_rms_deg | -13.851 [-14.318, -13.384] (n=8) | 0.558 | 8 | 0 | 0 |
| estimator | compound_motion | stress | eskf_legacy − mahony / yaw_rms_deg | 0.204 [-3.310, 3.717] (n=8) | 4.203 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | -12.186 [-12.642, -11.730] (n=8) | 0.546 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | -18.676 [-41.091, 3.739] (n=8) | 26.812 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_conservative − mahony / tilt_rms_deg | -7.848 [-7.932, -7.763] (n=8) | 0.101 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_conservative − mahony / yaw_rms_deg | 1.110 [0.416, 1.803] (n=8) | 0.830 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_legacy − mahony / tilt_rms_deg | 4.339 [3.889, 4.789] (n=8) | 0.538 | 8 | 0 | 0 |
| estimator | lateral_accel | nominal | eskf_legacy − mahony / yaw_rms_deg | 19.786 [-2.653, 42.225] (n=8) | 26.840 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | -12.223 [-12.512, -11.934] (n=8) | 0.346 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | -18.813 [-39.579, 1.954] (n=8) | 24.840 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_conservative − mahony / tilt_rms_deg | -7.817 [-7.882, -7.751] (n=8) | 0.078 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_conservative − mahony / yaw_rms_deg | 1.073 [0.453, 1.693] (n=8) | 0.742 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_legacy − mahony / tilt_rms_deg | 4.407 [4.150, 4.663] (n=8) | 0.307 | 8 | 0 | 0 |
| estimator | lateral_accel | stress | eskf_legacy − mahony / yaw_rms_deg | 19.886 [-0.858, 40.629] (n=8) | 24.812 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_conservative − mahony / tilt_rms_deg | -2.547 [-2.626, -2.467] (n=8) | 0.095 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_conservative − mahony / yaw_rms_deg | -1.410 [-1.916, -0.904] (n=8) | 0.605 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_legacy − mahony / tilt_rms_deg | -2.547 [-2.626, -2.467] (n=8) | 0.095 | 8 | 0 | 0 |
| estimator | maneuver | nominal | eskf_legacy − mahony / yaw_rms_deg | -1.410 [-1.916, -0.904] (n=8) | 0.605 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_conservative − mahony / tilt_rms_deg | -2.363 [-2.414, -2.312] (n=8) | 0.061 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_conservative − mahony / yaw_rms_deg | -1.031 [-1.571, -0.491] (n=8) | 0.646 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_legacy − mahony / tilt_rms_deg | -2.363 [-2.414, -2.312] (n=8) | 0.061 | 8 | 0 | 0 |
| estimator | maneuver | stress | eskf_legacy − mahony / yaw_rms_deg | -1.031 [-1.571, -0.491] (n=8) | 0.646 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | -0.003 [-0.007, 0.001] (n=8) | 0.005 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | -0.669 [-1.167, -0.171] (n=8) | 0.595 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_conservative − mahony / tilt_rms_deg | -0.000 [-0.016, 0.016] (n=8) | 0.019 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_conservative − mahony / yaw_rms_deg | 1.108 [0.513, 1.703] (n=8) | 0.712 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_legacy − mahony / tilt_rms_deg | 0.003 [-0.014, 0.019] (n=8) | 0.019 | 8 | 0 | 0 |
| estimator | slow_yaw | nominal | eskf_legacy − mahony / yaw_rms_deg | 1.777 [1.002, 2.552] (n=8) | 0.926 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | -0.001 [-0.010, 0.009] (n=8) | 0.011 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | -1.322 [-2.343, -0.300] (n=8) | 1.222 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_conservative − mahony / tilt_rms_deg | 0.047 [0.029, 0.066] (n=8) | 0.022 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_conservative − mahony / yaw_rms_deg | 1.987 [0.929, 3.045] (n=8) | 1.266 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_legacy − mahony / tilt_rms_deg | 0.048 [0.030, 0.066] (n=8) | 0.022 | 8 | 0 | 0 |
| estimator | slow_yaw | stress | eskf_legacy − mahony / yaw_rms_deg | 3.308 [1.557, 5.060] (n=8) | 2.095 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | -0.002 [-0.006, 0.001] (n=8) | 0.004 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | -0.328 [-0.472, -0.184] (n=8) | 0.172 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_conservative − mahony / tilt_rms_deg | 0.003 [-0.020, 0.026] (n=8) | 0.027 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_conservative − mahony / yaw_rms_deg | 0.689 [0.150, 1.228] (n=8) | 0.645 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_legacy − mahony / tilt_rms_deg | 0.005 [-0.019, 0.029] (n=8) | 0.029 | 8 | 0 | 0 |
| estimator | static | nominal | eskf_legacy − mahony / yaw_rms_deg | 1.018 [0.464, 1.571] (n=8) | 0.662 | 8 | 0 | 0 |
| estimator | static | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | -0.009 [-0.034, 0.016] (n=8) | 0.030 | 8 | 0 | 0 |
| estimator | static | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | -2.554 [-4.468, -0.640] (n=8) | 2.290 | 8 | 0 | 0 |
| estimator | static | stress | eskf_conservative − mahony / tilt_rms_deg | 0.020 [0.003, 0.038] (n=8) | 0.021 | 8 | 0 | 0 |
| estimator | static | stress | eskf_conservative − mahony / yaw_rms_deg | 3.570 [1.678, 5.462] (n=8) | 2.263 | 8 | 0 | 0 |
| estimator | static | stress | eskf_legacy − mahony / tilt_rms_deg | 0.029 [-0.007, 0.065] (n=8) | 0.043 | 8 | 0 | 0 |
| estimator | static | stress | eskf_legacy − mahony / yaw_rms_deg | 6.124 [2.679, 9.569] (n=8) | 4.121 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | -1.075 [-1.160, -0.990] (n=8) | 0.102 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | -19.431 [-23.896, -14.967] (n=8) | 5.340 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_conservative − mahony / tilt_rms_deg | -1.614 [-1.693, -1.534] (n=8) | 0.095 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_conservative − mahony / yaw_rms_deg | 1.820 [0.614, 3.025] (n=8) | 1.442 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_legacy − mahony / tilt_rms_deg | -0.539 [-0.564, -0.514] (n=8) | 0.030 | 8 | 0 | 0 |
| estimator | stop_start | nominal | eskf_legacy − mahony / yaw_rms_deg | 21.251 [16.449, 26.053] (n=8) | 5.743 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | -0.907 [-0.960, -0.854] (n=8) | 0.063 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | -12.362 [-18.103, -6.620] (n=8) | 6.868 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_conservative − mahony / tilt_rms_deg | -1.386 [-1.433, -1.339] (n=8) | 0.056 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_conservative − mahony / yaw_rms_deg | 7.623 [5.623, 9.623] (n=8) | 2.392 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_legacy − mahony / tilt_rms_deg | -0.479 [-0.508, -0.451] (n=8) | 0.034 | 8 | 0 | 0 |
| estimator | stop_start | stress | eskf_legacy − mahony / yaw_rms_deg | 19.985 [15.584, 24.386] (n=8) | 5.264 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_conservative − mahony / tilt_rms_deg | -2.542 [-2.616, -2.469] (n=8) | 0.088 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_conservative − mahony / yaw_rms_deg | -0.778 [-1.456, -0.100] (n=8) | 0.811 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_legacy − mahony / tilt_rms_deg | -2.542 [-2.616, -2.469] (n=8) | 0.088 | 8 | 0 | 0 |
| estimator | timing_jitter | nominal | eskf_legacy − mahony / yaw_rms_deg | -0.778 [-1.456, -0.100] (n=8) | 0.811 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_conservative − mahony / tilt_rms_deg | -2.313 [-2.362, -2.264] (n=8) | 0.059 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_conservative − mahony / yaw_rms_deg | -0.706 [-1.232, -0.181] (n=8) | 0.629 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_legacy − mahony / tilt_rms_deg | -2.313 [-2.362, -2.264] (n=8) | 0.059 | 8 | 0 | 0 |
| estimator | timing_jitter | stress | eskf_legacy − mahony / yaw_rms_deg | -0.706 [-1.232, -0.181] (n=8) | 0.629 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_conservative − mahony / tilt_rms_deg | -0.920 [-1.046, -0.795] (n=8) | 0.150 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_conservative − mahony / yaw_rms_deg | 0.642 [-0.137, 1.422] (n=8) | 0.932 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_legacy − mahony / tilt_rms_deg | -0.920 [-1.046, -0.795] (n=8) | 0.150 | 8 | 0 | 0 |
| estimator | vibration | nominal | eskf_legacy − mahony / yaw_rms_deg | 0.642 [-0.137, 1.422] (n=8) | 0.932 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_conservative − eskf_legacy / tilt_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_conservative − eskf_legacy / yaw_rms_deg | 0.000 [0.000, 0.000] (n=8) | 0.000 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_conservative − mahony / tilt_rms_deg | -0.850 [-0.949, -0.752] (n=8) | 0.118 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_conservative − mahony / yaw_rms_deg | 0.498 [-0.390, 1.385] (n=8) | 1.062 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_legacy − mahony / tilt_rms_deg | -0.850 [-0.949, -0.752] (n=8) | 0.118 | 8 | 0 | 0 |
| estimator | vibration | stress | eskf_legacy − mahony / yaw_rms_deg | 0.498 [-0.390, 1.385] (n=8) | 1.062 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / tilt_rms_deg | 0.236 [0.214, 0.257] (n=8) | 0.025 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / yaw_rms_deg | 2.927 [0.959, 4.895] (n=8) | 2.354 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / tilt_rms_deg | 0.218 [0.209, 0.227] (n=8) | 0.011 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / yaw_rms_deg | 0.046 [-0.183, 0.276] (n=8) | 0.274 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / tilt_rms_deg | 0.243 [0.200, 0.285] (n=8) | 0.051 | 8 | 0 | 0 |
| stress_minus_nominal | static | stress - nominal | stress − nominal / yaw_rms_deg | 5.153 [1.716, 8.590] (n=8) | 4.111 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / tilt_rms_deg | 0.268 [0.253, 0.283] (n=8) | 0.018 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / yaw_rms_deg | 1.165 [-0.119, 2.449] (n=8) | 1.536 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / tilt_rms_deg | 0.221 [0.217, 0.225] (n=8) | 0.005 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / yaw_rms_deg | 0.287 [0.134, 0.439] (n=8) | 0.182 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / tilt_rms_deg | 0.266 [0.244, 0.287] (n=8) | 0.026 | 8 | 0 | 0 |
| stress_minus_nominal | slow_yaw | stress - nominal | stress − nominal / yaw_rms_deg | 1.818 [0.299, 3.337] (n=8) | 1.817 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / tilt_rms_deg | 0.131 [0.036, 0.225] (n=8) | 0.113 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / yaw_rms_deg | 0.350 [0.026, 0.674] (n=8) | 0.388 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / tilt_rms_deg | 0.100 [0.099, 0.100] (n=8) | 0.000 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / yaw_rms_deg | 0.387 [0.302, 0.471] (n=8) | 0.101 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / tilt_rms_deg | 0.167 [-0.056, 0.390] (n=8) | 0.267 | 8 | 0 | 0 |
| stress_minus_nominal | lateral_accel | stress - nominal | stress − nominal / yaw_rms_deg | 0.487 [-1.938, 2.912] (n=8) | 2.901 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / tilt_rms_deg | 0.236 [0.169, 0.304] (n=8) | 0.081 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / yaw_rms_deg | 0.905 [0.822, 0.987] (n=8) | 0.098 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / tilt_rms_deg | 0.053 [0.052, 0.054] (n=8) | 0.001 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / yaw_rms_deg | 0.525 [0.514, 0.537] (n=8) | 0.014 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / tilt_rms_deg | 0.236 [0.169, 0.304] (n=8) | 0.081 | 8 | 0 | 0 |
| stress_minus_nominal | maneuver | stress - nominal | stress − nominal / yaw_rms_deg | 0.905 [0.822, 0.987] (n=8) | 0.098 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / tilt_rms_deg | 0.175 [0.086, 0.264] (n=8) | 0.107 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / yaw_rms_deg | 0.495 [0.157, 0.833] (n=8) | 0.404 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / tilt_rms_deg | 0.105 [0.104, 0.106] (n=8) | 0.001 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / yaw_rms_deg | 0.640 [0.586, 0.694] (n=8) | 0.065 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / tilt_rms_deg | 0.175 [0.086, 0.264] (n=8) | 0.107 | 8 | 0 | 0 |
| stress_minus_nominal | vibration | stress - nominal | stress − nominal / yaw_rms_deg | 0.495 [0.157, 0.833] (n=8) | 0.404 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / tilt_rms_deg | 0.282 [0.245, 0.319] (n=8) | 0.044 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / yaw_rms_deg | 0.613 [0.130, 1.097] (n=8) | 0.578 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / tilt_rms_deg | 0.053 [0.051, 0.054] (n=8) | 0.002 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / yaw_rms_deg | 0.542 [0.522, 0.561] (n=8) | 0.023 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / tilt_rms_deg | 0.282 [0.245, 0.319] (n=8) | 0.044 | 8 | 0 | 0 |
| stress_minus_nominal | timing_jitter | stress - nominal | stress − nominal / yaw_rms_deg | 0.613 [0.130, 1.097] (n=8) | 0.578 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / tilt_rms_deg | 0.277 [0.239, 0.315] (n=8) | 0.045 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / yaw_rms_deg | 5.823 [3.186, 8.460] (n=8) | 3.154 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / tilt_rms_deg | 0.049 [0.047, 0.052] (n=8) | 0.003 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / yaw_rms_deg | 0.020 [-0.102, 0.141] (n=8) | 0.145 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / tilt_rms_deg | 0.109 [0.099, 0.118] (n=8) | 0.011 | 8 | 0 | 0 |
| stress_minus_nominal | stop_start | stress - nominal | stress − nominal / yaw_rms_deg | -1.247 [-5.547, 3.054] (n=8) | 5.144 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / tilt_rms_deg | 0.479 [0.429, 0.529] (n=8) | 0.060 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / yaw_rms_deg | 0.766 [0.276, 1.256] (n=8) | 0.586 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / tilt_rms_deg | -0.017 [-0.017, -0.017] (n=8) | 0.000 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / yaw_rms_deg | 0.395 [0.391, 0.399] (n=8) | 0.005 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / tilt_rms_deg | 0.426 [0.400, 0.452] (n=8) | 0.031 | 8 | 0 | 0 |
| stress_minus_nominal | compound_motion | stress - nominal | stress − nominal / yaw_rms_deg | 0.119 [-0.197, 0.434] (n=8) | 0.377 | 8 | 0 | 0 |

## Availability and diagnostics

Unavailable estimates remain in the report through `expected`, `valid`, and `invalid` counts; they are never converted to zero. Uninitialized, invalid-output, degraded, and faulted sample totals are recorded where the estimator exposes those states. NEES/NIS also report diagnostic sample counts and coverage relative to valid estimates. They are diagnostics: gravity aiding reuses IMU data, so independent-noise chi-square coverage assumptions are not rigorous.

| Scenario | Profile | Estimator | NEES mean | NEES samples / valid | NEES sample coverage | NEES below 95% bound | NIS mean | NIS samples / valid | NIS sample coverage |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| compound_motion | nominal | eskf_conservative | 0.014 | 22408 / 22408 | 1.0000 | 1.0000 | 0.030 | 100 / 22408 | 0.0045 |
| compound_motion | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| compound_motion | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| compound_motion | stress | eskf_conservative | 0.044 | 22408 / 22408 | 1.0000 | 1.0000 | 0.031 | 99 / 22408 | 0.0044 |
| compound_motion | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| compound_motion | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| lateral_accel | nominal | eskf_conservative | 0.004 | 22408 / 22408 | 1.0000 | 1.0000 | 0.002 | 296 / 22408 | 0.0132 |
| lateral_accel | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| lateral_accel | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| lateral_accel | stress | eskf_conservative | 0.024 | 22408 / 22408 | 1.0000 | 1.0000 | 0.003 | 296 / 22408 | 0.0132 |
| lateral_accel | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| lateral_accel | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| maneuver | nominal | eskf_conservative | 0.004 | 22408 / 22408 | 1.0000 | 1.0000 | 0.005 | 8 / 22408 | 0.0004 |
| maneuver | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| maneuver | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| maneuver | stress | eskf_conservative | 0.013 | 22408 / 22408 | 1.0000 | 1.0000 | 0.004 | 8 / 22408 | 0.0004 |
| maneuver | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| maneuver | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| slow_yaw | nominal | eskf_conservative | 0.004 | 22408 / 22408 | 1.0000 | 1.0000 | 0.002 | 1072 / 22408 | 0.0478 |
| slow_yaw | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| slow_yaw | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| slow_yaw | stress | eskf_conservative | 0.047 | 22408 / 22408 | 1.0000 | 1.0000 | 0.004 | 1072 / 22408 | 0.0478 |
| slow_yaw | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| slow_yaw | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| static | nominal | eskf_conservative | 0.005 | 22408 / 22408 | 1.0000 | 1.0000 | 0.002 | 1072 / 22408 | 0.0478 |
| static | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| static | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| static | stress | eskf_conservative | 0.041 | 22408 / 22408 | 1.0000 | 1.0000 | 0.005 | 1072 / 22408 | 0.0478 |
| static | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| static | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| stop_start | nominal | eskf_conservative | 0.021 | 22408 / 22408 | 1.0000 | 1.0000 | 0.013 | 648 / 22408 | 0.0289 |
| stop_start | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| stop_start | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| stop_start | stress | eskf_conservative | 0.103 | 22408 / 22408 | 1.0000 | 1.0000 | 0.015 | 648 / 22408 | 0.0289 |
| stop_start | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| stop_start | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| timing_jitter | nominal | eskf_conservative | 0.003 | 22408 / 22408 | 1.0000 | 1.0000 | 0.003 | 8 / 22408 | 0.0004 |
| timing_jitter | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| timing_jitter | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| timing_jitter | stress | eskf_conservative | 0.013 | 22408 / 22408 | 1.0000 | 1.0000 | 0.003 | 8 / 22408 | 0.0004 |
| timing_jitter | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| timing_jitter | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| vibration | nominal | eskf_conservative | 0.003 | 22408 / 22408 | 1.0000 | 1.0000 | 0.004 | 8 / 22408 | 0.0004 |
| vibration | nominal | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| vibration | nominal | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| vibration | stress | eskf_conservative | 0.006 | 22408 / 22408 | 1.0000 | 1.0000 | 0.004 | 8 / 22408 | 0.0004 |
| vibration | stress | eskf_legacy | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |
| vibration | stress | mahony | N/A | 0 / 22408 | 0.0000 | N/A | N/A | 0 / 22408 | 0.0000 |

## Sensor profile assumptions

The nominal model retains the benchmark white-noise and random-walk equations. Stress terms are synthetic engineering assumptions, not measured or calibrated LSM6DS3 characteristics. Per sample: ideal motion → axis scale/misalignment → initial and random-walk bias plus thermal bias and white noise → clipping → quantization → one shared `Imu` record for all estimators. The reported gyro-bias error compares against additive injected bias; scale and cross-axis errors can also affect the estimate.

| Sensor parameter | Value | Unit |
|---|---|---|
| Accelerometer scale/misalignment matrix | `[[1.004,0.0012,-0.0008],[-0.001,0.997,0.0009],[0.0007,-0.0011,1.002]]` | dimensionless |
| Gyroscope scale/misalignment matrix | `[[1.005,-0.0011,0.0008],[0.001,0.997,-0.0007],[-0.0008,0.0012,1.003]]` | dimensionless |
| Temperature ramp | 0 to +6.000 over 14.000 s, beginning at 2.000 s | °C |
| Temperature bias coefficients, accel | `[0.012,-0.008,0.015]` | m/s²/°C |
| Temperature bias coefficients, gyro | `[0.00045,-0.00025,0.00035]` | rad/s/°C |
| Per-axis clipping limit, accel | ±60.000 | m/s² |
| Per-axis clipping limit, gyro | ±10.000 | rad/s |
| Quantization step, accel | 0.005000 | m/s²/count |
| Quantization step, gyro | 0.000250 | rad/s/count |
| White-noise density, accel | 0.001500 | m/s²/√Hz |
| White-noise density, gyro | 0.000250 | rad/s/√Hz |
| Bias random walk, accel | 0.000080 | m/s²/√s |
| Bias random walk, gyro | 0.000030 | rad/s/√s |

The limits are deliberately illustrative and are not sensor full-scale specifications. Ordinary scenarios should remain below them; saturation behavior is tested with isolated extreme input.

## Metric and interpretation limits

- Metric definition v2 computes inclination from gravity/up vectors in the body frame. The historical v1 `tilt_rms_deg` used world-frame body-Z-axis deviation and can include common world-yaw error, so v1 and v2 RMS values are not directly comparable.
- Yaw RMS is relative to the synthetic initial yaw gauge. Gravity alone cannot observe absolute yaw or heading.
- The initial 2 s are stationary by the known scenario definition. This is not an IMU-only detector. Startup bias calibration is opt-in.
- The host simulator runs at 200 Hz for 16 s. Target firmware configures the IMU at 208 Hz; this benchmark does not claim hardware timing or accuracy.
- Truth integration v2 uses midpoint angular rates. This changes some time-varying-rotation accelerometer samples relative to the historical endpoint-rate v1 simulator even though the six original Gaussian draw sequences are preserved. Historical v1/v2 performance values are therefore not directly comparable.
- Translation is represented by acceleration commands for specific-force generation; position and velocity are not part of this attitude benchmark.
- A simulator can expose code defects and model assumptions. It cannot establish physical attitude accuracy, controller safety, or actual RP2350/LSM6DS3 timing.


## Plots

### verified startup bias

#### nominal profile

- Tilt RMS: [SVG](benchmarks/plots/verified_startup_bias/tilt_rms_nominal.svg)
- Yaw RMS: [SVG](benchmarks/plots/verified_startup_bias/yaw_rms_nominal.svg)

#### stress profile

- Tilt RMS: [SVG](benchmarks/plots/verified_startup_bias/tilt_rms_stress.svg)
- Yaw RMS: [SVG](benchmarks/plots/verified_startup_bias/yaw_rms_stress.svg)
