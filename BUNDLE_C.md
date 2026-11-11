# Bundle C — calibration, aiding contract, FIFO mock and binary replay

Date: 2026-11-10. Implementation for the **original** ST LSM6DS3 (`WHO_AM_I=0x69`), Pico 2/RP2350. Bundle C retains Bundle A and Bundle B and contains no physical hardware validation.

## 1. Calibration (`calibration.hpp`)

A versioned `SensorCalibration` defines:

- `calibration_id`, `version`, and `source_id` (0 means deliberately *uncalibrated*).
- Proper orthonormal `body_from_sensor` rotation `R_BS` (right-handed; determinant +1).
- Independently estimated scale and cross-axis terms in `accel_correction`, `gyro_correction`.
- Fixed offline biases and linear temperature coefficients in SI units, plus reference temperature.
- Validation of finite coefficients, proper rotation, and positive determinant of correction matrices. The correction matrices are not assumed orthogonal.

The transformation is `a_B = R_BS * M_a * (a_S - b_a0 - k_a (T-T0))`; similarly for the gyroscope. If temperature compensation is requested but no temperature is supplied, the code rejects the sample instead of substituting room temperature. No real device calibration has been collected: firmware uses **identity**, `calibration_id=0`, and temperature compensation disabled. ESKF bias states model the remaining residual biases and must not receive the same fixed calibration twice.

To deploy a real calibration: edit/replace the firmware's `g_calibration`, update the ESKF settings `calibration_id`, and change `CALIBRATION_VERSION` consistently. Validate actual units, sensor-to-body axes, test orientation, ODR/FS, temperature and expected noise.

## 2. Aiding (`aiding.hpp`)

`AidingMeasurement` carries source ID, calibration ID, timebase ID, measurement interval, capture/publication timestamps, physical frame (world ENU or body FLU), measurement kind, isotropic one-sigma uncertainty, source provenance and validity. `AidingRouter` applies explicit checks and calls ESKF `*_at()` APIs.

- Reject wrong reference frame, wrong timebase, calibration mismatch, non-finite input, duplicate or out-of-order data, invalid intervals, and future/stale capture timestamps.
- Refuse measurements marked `CorrelatedOrFused`: a VIO pose made from this same IMU stream is **not an independent sensor measurement**.
- The router supports external independent world position, world velocity, heading, explicitly verified zero-rate, and explicitly verified zero-velocity constraints. It does *not* add delayed replay or heterogeneous anisotropic covariance matrices.
- Source monotonicity is tracked in a fixed eight-slot array with no dynamic allocation; source IDs should identify distinct measurement streams.
- The ESKF still permits only nearly contemporaneous aiding (<=1 ms) and does not yet implement Bundle D's historical state buffer. Source timebases and frames are explicit rather than silently converted.

The router is ready for integration into a future external sensor transport. No new camera, ToF or encoder input is connected in the current firmware.

## 3. Original LSM6DS3 FIFO (`lsm6ds3_fifo.hpp`)

A mockable register `Bus` interface isolates sensor logic from RP2350 SDK code. The driver configures FIFO bypass flush, gyro+accelerometer without decimation (`FIFO_CTRL3=0x09`), FIFO ODR 208 Hz and continuous mode (`FIFO_CTRL5=0x2E`). Each complete pair consists of **six 16-bit words**: Gx, Gy, Gz, Ax, Ay, Az. It reads FIFO status and current FIFO_PATTERN, returns at most 32 complete frames per call, and resets the FIFO on full/overrun or unexpected pattern. The RP2350's alternate SPI adapter is compiled when `RP2350_USE_FIFO=ON`.

Important limitations:

- `RP2350_USE_FIFO` is **OFF by default** pending hardware testing. Legacy direct-register SPI DMA remains active by default.
- The alternate FIFO adapter currently uses bounded **blocking SPI**, not DMA. CPU/SPI worst-case timing and burst throughput must be checked on hardware.
- Backlogged frame timestamps are reconstructed from a PIO DRDY anchor using nominal 208 Hz intervals. They are **not** accurate independent sample timestamps; actual sensor ODR variation, dropped DRDY edges, anchor age and FIFO write/read races require measurement. Backfilled frames are flagged in the binary log.
- After a detected FIFO full, overrun, or misaligned pattern, the driver **flushes data** and reports the loss. Do not claim lossless operation after such faults.
- The mock interface faithfully tests expected register sequences and FIFO pattern, but mock bus behavior cannot prove actual SPI rounding semantics. ST AN4650 §8 specifies that consecutive FIFO output words are read through the FIFO_DATA_OUT_L/H ports.
- This FIFO code is for **LSM6DS3**, not tagged LSM6DSOX/DSO/DS3TR-C variants without validation.

## 4. Binary capture/replay (`binary_log.hpp`, `tools/binary_log_tool.cpp`)

Deterministic fixed-size records are encoded little-endian, with version, capture and publication timestamps, source/timebase/calibration metadata in a 32-byte file header, plus per-record sequence, flags, six physical SI channels, optional temperature and CRC32. Each record is 64 bytes. Version 2 records also carry `dropped_records_before`; the reader remains compatible with version 1 records and headers. No ABI padding or host-endian dumping. Replay writes sequence gaps and explicit dropped-record counts to CSV and totals both in its summary.

On a development PC:

```bash
./tools/run_bundle_c_checks.sh
# Generated tool in /tmp/rp2350_bundle_c_checks/binary_log_tool:
/tmp/rp2350_bundle_c_checks/binary_log_tool generate /tmp/example.bin
/tmp/rp2350_bundle_c_checks/binary_log_tool replay /tmp/example.bin 1234 > /tmp/estimates.csv
```

`RP2350_STREAM_BINARY_LOG=ON` optionally sends a binary header and record stream over Pico USB CDC. It is explicitly **debug only**: `putchar_raw` can stall acquisition. When the host is disconnected, skipped sample records are counted and the logger retries a fresh header after reconnect; the next written record carries the pending count. Pico stdio does not report partial write completion, so a timeout while the connection still appears active cannot be exactly counted. Record CRCs, sequence gaps and strict replay/truncation checks expose corrupt or incomplete captures, but this is not a production-grade, persistent, lossless logger. Console text diagnostics are disabled while binary mode is selected.

In text-diagnostic mode, `main.cpp` reports fixed-memory log2 histogram upper bounds for ESKF process duration, SPI transfer duration, per-edge acquisition service duration, IRQ-to-main dispatch latency, and sample timestamp-to-publication age. It also reports queue occupancy sampled immediately after successful inserts, sample-period service overruns, and a sentinel-derived high-water estimate for the dedicated core-1 stack. A consumer may drain a queue between insertion and occupancy sampling, so reported queue peaks are observed samples rather than atomic exact maxima. Histogram percentiles are bucket upper bounds, not exact quantiles. The 4,808 µs overrun threshold is the nominal 208 Hz sensor service interval only; it is **not a controller deadline**. Core-0 stack watermark and all physical measurements remain unavailable until a board run.

## Verification

- `tools/run_bundle_a_checks.sh`: existing estimator mathematical/fixture tests.
- `tools/run_bundle_b_checks.sh`: motion/Monte Carlo comparison.
- `tools/run_bundle_c_checks.sh`: calibration, matrix validation, temperature gate, aiding frame/time/calibration/provenance checks, mock FIFO configuration/overrun/pattern recovery, version-1/2 log compatibility, loss provenance, CRC/corruption/truncation, and 1,200-sample replay.
- `BUNDLE_C_SANITIZERS=1 ./tools/run_bundle_c_checks.sh`: ASan/UBSan host checks.
- GitHub Actions builds both legacy and `RP2350_USE_FIFO=ON` firmware variants using a pinned Pico SDK. No hardware accuracy or timing result is implied.

## Remaining Bundle D candidates

Delayed-state IMU buffering and replay; physical wheel/ToF residuals with non-isotropic covariances; camera/IMU timebase calibration; source correlations and non-independent loose VIO aiding; persistent nonblocking logging with loss counters; actual measured sensor-temperature acquisition; real calibration datasets, PLL/clock drift checks, logic-analyzer/host timestamp validation.
