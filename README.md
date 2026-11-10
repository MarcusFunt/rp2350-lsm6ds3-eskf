# RP2350 + LSM6DS3 — report-audited 15-state ESKF (experimental)

**Target:** Raspberry Pi Pico 2 / RP2350 in ARM Cortex-M33 mode, Pico SDK 2.x, original ST LSM6DS3 (`WHO_AM_I=0x69`). This is a concrete revision of the previous example, informed by *Sensor Fusion for Attitude and Navigation*, Research-Expanded Edition (7 November 2026). See [`REVIEW_2026.md`](REVIEW_2026.md) for the audit and source mapping.

**Status:** Bundle A Pico 2 cross-build and host checks previously passed in GitHub Actions. Bundle B host tests, synthetic Monte Carlo comparisons and sanitizers pass locally; the revised firmware must pass a new Pico cross-build in CI. Real calibration, electrical timing and hardware-in-the-loop validation **have not been performed**. Do not use as a flight-safety controller.

## Files

| File | Purpose |
|---|---|
| `main.cpp` | SPI0 DMA acquisition, PIO gyro data-ready periods, dual-core queues, health/latency diagnostic stream |
| `drdy_period.pio` | Relative data-ready edge counter (software timebase anchor, not absolute timestamps) |
| `eskf15.hpp` | Heap-free 15-state ESKF and timestamp-aware aiding interface |
| `tests/test_eskf15.cpp` | Existing regression tests including uncertainty and failure handling |
| `tools/replay_imu_csv.cpp` | Offline timestamped CSV IMU replay |
| `tools/create_fixture.py` | Deterministic synthetic IMU fixture generator |
| `fixtures/stationary_then_yaw.csv` | Synthetic input trace; not measured IMU evidence |
| `REVIEW_2026.md` | Audit against the 7 November 2026 report; remaining risks |
| `tests/test_bundle_b.cpp` | Startup bias and motion-aware gravity regression tests |
| `tools/benchmark_bundle_b.cpp` | Shared synthetic IMU stream, ESKF/Mahony matched comparison and tilt NEES diagnostics |
| `tools/summarize_bundle_b.py` | Reproducible report/JSON summaries from per-seed CSV |
| `BENCHMARK_B.md` | Synthetic benchmark summary and interpretation limits |
| `benchmarks/` | Raw per-seed CSV and machine-readable summaries |

## Wiring (Pico 2)

| Pico 2 pin | Original LSM6DS3 breakout |
|---|---|
| GP16 | SDO / MISO |
| GP17 | CS |
| GP18 | SPC / SCK |
| GP19 | SDI / MOSI |
| GP20 | INT1 (gyro data-ready) |
| 3V3 / GND | VDD+VDDIO / GND (check breakout specifications) |

The software configures **208 Hz** gyro + accelerometer ODR, **±245 dps**, **±4 g**, SPI **8 MHz**. Samples are read from latest output registers by SPI DMA. The sensor FIFO is **not enabled**. Therefore this is **not lossless logging**, and `sample sequence` cannot prove the chip did not overwrite a sample.

## Build the firmware

Install Pico SDK 2.x, Ninja, CMake and an Arm `arm-none-eabi` C++ compiler. Set `PICO_SDK_PATH` to your checked-out SDK.

```bash
cmake -S . -B build -G Ninja -DPICO_BOARD=pico2
cmake --build build
```

Flash `build/rp2350_lsm6ds3_fusion.uf2` with BOOTSEL. USB diagnostics print roughly every 500 ms (when data are available). The firmware targets RP2350 ARM mode, not RISC-V.

**Optional debug-only raw sample CSV** (not for timing benchmarks):

```bash
cmake -S . -B build-raw -G Ninja -DPICO_BOARD=pico2 -DRP2350_STREAM_RAW_CSV=ON
cmake --build build-raw
```

With raw streaming, the USB serial console sends approximately 208 CSV lines/s. Serial output can block, cause missed sensor samples and alter the timing being measured. Use FIFO buffering/other logging for robust performance tests. Raw CSV and ordinary status output may be interleaved in the debug stream; only lines matching the 7-column numeric CSV format should be replayed.

## Reference frame, numerical state, ownership

- **World:** right-handed, Z up, `g_world=(0,0,-9.80665)` m/s². Local origin and initial yaw are arbitrary gauges, **not** an absolute position or north.
- **Body:** LSM6DS3 sensor axes. A stationary upright sensor reads about `(0,0,+g)` m/s²; all measurements use **m/s²** and **rad/s**.
- **Quaternion:** `(w,x,y,z)` body-to-world. Right-multiplicative attitude error.
- **Nominal:** `position (3), velocity (3), quaternion (4), accel bias (3), gyro bias (3)`.
- **15-element error order:** `[δp, δv, δθ, δba, δbg]` with 15×15 FP32 covariance.
- **Estimator authority:** one local ESKF, on core 1. No other filter or optimizer feeds corrections in this example.
- **Timebase:** PIO relative edge-period counter with first-edge **software** timestamp anchor. Not guaranteed synchronized to cameras, encoders or external clocks. `published_us` is MCU availability time; `state_timestamp_us()` is the last actual propagated sensor time.
- **Calibration:** no calibrated bias/noise/scale/axis/extrinsic model has been measured. `CALIBRATION_VERSION=0` and default `Settings::calibration_id=0` indicate uncalibrated engineering defaults; set nonzero versions after calibration.

## New behavior and its limits

1. **Initialization:** the filter requires 80 approximately stationary IMU readings (default ~0.38 s at 208 Hz) instead of initializing from one accelerometer vector. It still cannot distinguish rest from sustained linear acceleration purely from a six-axis IMU. It does not infer absolute yaw or preexisting velocity.
2. **Propagation:** quaternion exponential rotation, midpoint orientation for acceleration, second-order transition approximation and noise-driven 15×15 covariance growth. Coning/sculling corrections are **not** implemented.
3. **Gravity-direction update:** after a conservative quasi-stationary gate and a 0.08-radian innovation-angle limit (by default), the filter compares *normalized* accelerometer specific force to predicted up-direction, yielding at most 2 tilt constraints. It does not pretend to measure absolute yaw, translation, or force magnitude. Constant acceleration can still mimic gravity; turn this correction off or aid with other sensors during sustained maneuvering. Incomplete bias observability remains.
4. **Numerical update:** Cholesky innovation solve, NIS gating, Joseph covariance update, right-error reset Jacobian, symmetry enforcement and separately callable Cholesky covariance positive-definiteness diagnostic. The diagnostic does **not** prove filter consistency or observability.
5. **Health:** `Aligning`, `Nominal`, `Degraded`, `Fault`. Missing data and duplicate timestamps mark the filter degraded; near-full-scale ±4g/±245dps measurements mark it faulted. Outages cause heuristic covariance inflation. State remains degraded/faulted until explicit `reset()`—it never silently declares a faulted trajectory safe again. A larger application must implement actual recovery/arbitration.
6. **Gap time:** for skipped long intervals, the last received timestamp advances but `state_timestamp_us()` does **not** advance unless a prediction occurs. The filter latches `Fault` and refuses to resume propagation until an explicit `reset()`. Lost dynamics cannot be recovered automatically. Shorter gaps within the threshold still use a zero-order hold and degraded health.
7. **External aiding:** `_at()` APIs require a measurement timestamp approximately equal to the current propagated state time (default within 1 ms) and optional matching calibration ID. Stale/future aid is rejected; the code **does not** implement delayed-state rewind/replay, clock synchronization or cross-correlation-aware fusion of IMU-dependent VIO estimates.
8. **Provenance:** accepted aiding's source ID and timestamp can be queried. Source ownership, conditional-information accounting and covariance cross-correlations must be enforced by the **calling application** before accepting estimates from a shared-IMU VIO pipeline.
9. **Performance:** Core 1 tracks the longest observed `process()` execution time (`fusion_max_us`) and publication timestamps. A USB summary exposes fusion time, state age, NIS, aid counts, gap counts, saturations and queue drops. A missing gyro DRDY for over 100 ms also forces the **reported** health to `Fault` on core 0 even though core 1 cannot receive a missing sample. Consumers must independently apply their own estimate-age deadlines. This is instrumentation, **not** a measured control deadline bound.

**NIS threshold:** 16 for the three-component updates, 9 for heading (one component); these are configurable in source, not tuned against LSM6DS3 real noise or independent residual data. Use NIS plots and ground-truth-aligned NEES to tune. Baseline noise-density parameters in `Settings` are merely starting assumptions.

### External aiding example

Aiding data must be physically independent or have a justified correlation model. This API is for near-current measurements in the same **world** frame as the ESKF.

```cpp
inertial::Eskf15 filter;
filter.process({imu_timestamp_us, accel_mps2, gyro_rad_s});
// Once initialized and propagated to this same time:
inertial::AidingStamp stamp{
    filter.state_timestamp_us(), /*source_id=*/2, /*calibration_id=*/0
};
filter.update_velocity_world_at(stamp, {vx_world, vy_world, vz_world}, 0.10f);
filter.update_position_world_at(stamp, {px_world, py_world, pz_world}, 0.15f);
filter.update_heading_at(stamp, known_heading_rad, 0.05f);
```

The example firmware **does not yet wire these external updates to a cross-core queue**. Call these methods on the core that owns the ESKF, not from another core. For camera/VIO latency exceeding the 1 ms bound, the correct engineering work is synchronized measurement-time buffering and covariance-consistent delayed fusion/replay—not simply increasing `max_aiding_age_us`.

The old `update_position_world(...)`, `update_heading(...)` convenience methods remain for existing host code; they mean **measurement is current at the present state time**, and must never be used to mislabel old camera measurements as current.

## Run host-side tests and replay

```bash
g++ -std=c++17 -O2 -Wall -Wextra -pedantic tests/test_eskf15.cpp -o test_eskf15
./test_eskf15

g++ -std=c++17 -O2 -Wall -Wextra -pedantic tools/replay_imu_csv.cpp -o replay_imu
python3 tools/create_fixture.py
./replay_imu fixtures/stationary_then_yaw.csv > estimated.csv
```

Replay input: `timestamp_us,ax_mps2,ay_mps2,az_mps2,gx_rps,gy_rps,gz_rps`, with optional `#` metadata and a header. It expects gyro in radians/second and accelerometer in meters/second². The fixture is synthetic and cannot be used as evidence of on-hardware accuracy.

## Priority work remaining

1. Re-run Pico 2 cross-build on each revision; only Bundle A has a verified previous CI build.
2. Validate INT1 GPIO polarity, SPI waveform, DMA timing, and PIO period counter against a logic analyzer. Verify no sample duplication/overwrites.
3. Implement and test LSM6DS3 FIFO watermark, timestamp and overrun handling; quantify losslessness. Preserve a calibration hash, timebase ID, full raw sample identity and fault flags in recorded data.
4. Measure gyro/accelerometer noise and bias drift at multiple temperatures; calibrate axes/scales. Refit `Settings` and verify NIS/NEES with independent truth.
5. Add real synchronized wheel, camera/VIO, GNSS or magnetic-heading measurements, then implement **bounded delayed measurement update + replay** with a correct covariance contract. Treat correlation from shared IMU histories explicitly.
6. Benchmarks: loaded-core 99th/max execution time and control-age histogram; controlled tilt, acceleration, vibration, coning/sculling and fault-injection tests. Implement an explicit controller-safe degraded/fault behavior before autonomous deployment.

Report: *Sensor Fusion for Attitude and Navigation* (7 November 2026), especially pages 3, 6–8, 10–16, 22–23, 27–31. It provides engineering requirements, not proof this firmware is accurate or safe.

## Bundle A (November 2026): correctness and reliability

This revision implements the four software-only correctness priorities from the improvement backlog:

1. Pinned Pico SDK **2.2.0** CI cross-build for Raspberry Pi Pico 2 (RP2350), with host tests and generated UF2. Building the workflow is **not** a claim of electrical/hardware verification.
2. Independent double-precision finite-difference checking of the 15-state continuous error Jacobian and the gravity/yaw measurement models (`tests/test_math.cpp`); initial yaw gauge covariance is aligned to *world Z expressed in body-error coordinates* rather than always body Z.
3. A continuous-time 12-input noise model discretized using three-point positive-weight Gauss-Legendre quadrature and second-order local transition. Checks compare process covariance against an independent double-precision numerical integration (`tests/test_noise.cpp`). This is a local-time approximation, not an exact Van Loan exponential; physical noise-density parameters remain uncalibrated placeholders.
4. Long-gap and saturated-sample acquisition now cause an explicit fault latch requiring `filter.reset()` and reinitialization. The filter will not label an unintegrated interval as a valid current estimate. Shorter missing samples cause additional covariance inflation and degraded health. The core-1 telemetry path publishes invalid/fault status instead of displaying the previous healthy status indefinitely. A reset loses pre-reset pose/heading, and any downstream controller must handle that estimator discontinuity intentionally.

Run **all** hardware-free checks:

```sh
./tools/run_bundle_a_checks.sh
BUNDLE_A_SANITIZERS=1 ./tools/run_bundle_a_checks.sh
```

Cross-build locally when Pico SDK 2.2.0 and the ARM GNU toolchain are available:

```sh
export PICO_SDK_PATH=/path/to/pico-sdk
cmake -S . -B build -G Ninja -DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350
cmake --build build
```

The shipped firmware still reads the latest registers (not FIFO); PIO/SPI timing, electrical operation, real LSM6DS3 calibration, WCET, and physical estimator accuracy are unverified. An outage *shorter* than the latch threshold is integrated using the latest sample as a zero-order hold; this is only an approximation and remains flagged as degraded if a missing sample is detected. No camera/VIO delayed-state replay is implemented.

## Bundle B (November 2026): motion-aware fusion and synthetic benchmarks

**Gravity policy:** default `Settings::gravity_policy=GravityPolicy::Conservative`. It retains the low-motion detector but rejects unverified accelerometer directions more than 0.08 rad from expected gravity, and inflates the gravity measurement noise when the norm/step approach heuristic limits. This is deliberately conservative and may delay legitimate correction after a large orientation error. The 6-axis IMU **cannot** distinguish constant lateral acceleration from tilt in general. The baseline `LegacyHeuristic` and the strict `ConfirmedOnly` alternatives remain available. `set_external_stationary_confirmed(true)` may only be used when **independent evidence** establishes that the entire device is stationary; clear it as soon as that condition is no longer true.

**Startup gyro-bias estimation:** default **off**. Enable `Settings::startup_gyro_bias_calibration=true` and assert `set_external_stationary_confirmed(true)` for **every sample** of the startup alignment window, using an independent stationary condition. The filter rejects unstable gyro startup windows and retains a nonzero bias covariance floor. Slowly rotating hardware with no external stationary confirmation must not be calibrated as zero rate. This is not a self-calibration solution for a freely moving device.

The firmware still defaults to its normal operational configuration; no synthetic truth or reference sensor is injected on the RP2350. The simulator can provide a known verified-stationary window, which is only an idealized test condition.

Run software-only Bundle B validation, which also compares exact repeated runs:

```bash
./tools/run_bundle_a_checks.sh
./tools/run_bundle_b_checks.sh
BUNDLE_B_SANITIZERS=1 ./tools/run_bundle_b_checks.sh
```

Regenerate the checked-in Monte Carlo evidence (6 scenarios x 8 seeds x 3 variants per mode):

```bash
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror tools/benchmark_bundle_b.cpp -o benchmark_bundle_b
./benchmark_bundle_b --trials 8 --seed 20261110 --output benchmarks/bundle_b_no_startup_bias.csv
./benchmark_bundle_b --trials 8 --seed 20261110 --startup-bias --output benchmarks/bundle_b_verified_startup_bias.csv
python3 tools/summarize_bundle_b.py benchmarks/bundle_b_verified_startup_bias.csv --markdown BENCHMARK_B.md --json benchmarks/summary_verified_startup_bias.json
python3 tools/summarize_bundle_b.py benchmarks/bundle_b_no_startup_bias.csv --json benchmarks/summary_no_startup_bias.json
```

The simulator explicitly models sensor noise, bias random walk, a period of verified-stationary startup, synthetic motion and specific force, vibration and +-150 us timing-label perturbations. Its simplified timing jitter does not represent measured hardware. It reports causal attitude errors, missing estimates, gravity innovation statistics and **2-DOF horizontal-attitude NEES** (yaw is a gauge). The gravity pseudo-measurement shares the same sensor data as propagation; the usual independent Gaussian NIS/NEES chi-squared coverage assumptions do not exactly apply. See [BENCHMARK_B.md](BENCHMARK_B.md) for matched results and caveats.

## Bundle C (2026-11-10) — hardware-independent sensor interfaces

See [BUNDLE_C.md](BUNDLE_C.md) for the full design, assumptions, tests and limitations.

- **Calibration:** `calibration.hpp` defines versioned, sensor-to-body matrix corrections and optional temperature compensation. The shipped firmware uses identity calibration (`calibration_id=0`) because no real IMU calibration exists.
- **External measurement contract:** `aiding.hpp` provides timebase, frame, provenance, covariance and source ID checks. It deliberately refuses estimates that reuse correlated IMU data as independent evidence. Delayed replay is not implemented yet.
- **Mockable LSM6DS3 FIFO:** `lsm6ds3_fifo.hpp` implements explicit six-word patterns, overrun/pattern recovery and batched reads through an abstract register bus. Build the experimental FIFO firmware using `-DRP2350_USE_FIFO=ON`; this is **OFF** by default until physical testing.
- **Binary log and replay:** `binary_log.hpp` and `tools/binary_log_tool.cpp` provide CRC-protected versioned capture/replay. `-DRP2350_STREAM_BINARY_LOG=ON` enables a debug USB stream only; it can block and is not a lossless production logger.

Host regression: `./tools/run_bundle_c_checks.sh`, optionally `BUNDLE_C_SANITIZERS=1 ./tools/run_bundle_c_checks.sh`.
