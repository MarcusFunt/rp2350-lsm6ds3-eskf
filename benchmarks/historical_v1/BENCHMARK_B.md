# Bundle B: synthetic estimator comparison

Source CSV: `bundle_b_verified_startup_bias.csv`. Results are simulated, not measured on RP2350 hardware.

| Scenario | Estimator | Trials | Mean tilt RMS (deg) | Between-trial SD (deg) | Mean yaw RMS (deg) | Valid fraction |
|---|---|---:|---:|---:|---:|---:|
| lateral_accel | eskf_conservative | 8 | 0.262 | 0.111 | 1.287 | 1.000 |
| lateral_accel | eskf_legacy | 8 | 12.448 | 0.531 | 19.963 | 1.000 |
| lateral_accel | mahony | 8 | 8.109 | 0.020 | 0.177 | 1.000 |
| maneuver | eskf_conservative | 8 | 0.404 | 0.332 | 0.485 | 1.000 |
| maneuver | eskf_legacy | 8 | 0.404 | 0.332 | 0.485 | 1.000 |
| maneuver | mahony | 8 | 2.291 | 0.013 | 1.912 | 1.000 |
| slow_yaw | eskf_conservative | 8 | 0.125 | 0.022 | 1.215 | 1.000 |
| slow_yaw | eskf_legacy | 8 | 0.128 | 0.020 | 1.883 | 1.000 |
| slow_yaw | mahony | 8 | 0.125 | 0.017 | 0.104 | 1.000 |
| static | eskf_conservative | 8 | 0.133 | 0.018 | 0.972 | 1.000 |
| static | eskf_legacy | 8 | 0.135 | 0.019 | 1.300 | 1.000 |
| static | mahony | 8 | 0.131 | 0.023 | 0.283 | 1.000 |
| timing_jitter | eskf_conservative | 8 | 0.805 | 0.587 | 1.177 | 1.000 |
| timing_jitter | eskf_legacy | 8 | 0.805 | 0.587 | 1.177 | 1.000 |
| timing_jitter | mahony | 8 | 2.280 | 0.020 | 1.963 | 1.000 |
| vibration | eskf_conservative | 8 | 0.455 | 0.236 | 0.978 | 1.000 |
| vibration | eskf_legacy | 8 | 0.455 | 0.236 | 0.978 | 1.000 |
| vibration | mahony | 8 | 1.120 | 0.012 | 0.324 | 1.000 |

## Interpretation limits

- The initial 2 seconds are truly stationary by scenario definition; optional startup bias calibration uses that known fact. This is not an IMU-only stationarity detector.
- The truth state is propagated independently of the estimators. All three estimators receive identical sensor samples within each trial.
- Trial means are means of per-run RMS values, not pooled sample-level RMS; the standard deviation represents variation between random seeds.
- Tilt NEES uses the world-horizontal 2D projection and excludes unobservable yaw. With gravity aiding reusing the same IMU data, ideal chi-squared NEES/NIS expectations may not apply exactly.
- A simulator can detect coding mistakes and model assumptions; it cannot establish accuracy or latency on actual LSM6DS3/RP2350 hardware.

## Scope and warnings

- `eskf_legacy` differs from `eskf_conservative` only in gravity update policy; both use the same propagation, process noise and optional verified-stationary startup calibration.
- Mahony is an explicitly documented constant-gain (`Kp=1.0`, `Ki=0.05`) implementation with unconditional accelerometer direction correction; it is not tuned to optimize each scenario, and an adaptive Mahony baseline may perform differently.
- Model parameters and simulated noise densities were chosen for a synthetic example, not fitted from an LSM6DS3 Allan-deviation run. This benchmark measures software behavior under those assumptions, not real sensor performance.
- Distinguishing tilt from sustained acceleration without independent aiding is physically unobservable. The conservative gate may refuse legitimate gravity corrections when its current tilt estimate is already wrong.
- Startup bias calibration requires an independently verified stationary window, which was supplied by the synthetic ground truth here. The code does not claim to detect stillness reliably from the IMU alone.
- A simulator with scripted motion cannot prove controller stability or robust real-world performance. Re-run these comparisons against hardware logs and an independent reference once available.
