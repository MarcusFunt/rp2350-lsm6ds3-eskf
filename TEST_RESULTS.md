# Bundle A verification — 10 November 2026

This project is an experimental 15-state ESKF. Host tests and a Pico 2 ARM cross-build have passed, but hardware and physical estimator performance have **not** been validated.

## Reproducible source and CI

- Branch: `main`
- Initial Bundle A implementation: `f033166` (with follow-up CI packaging repairs)
- Verified GitHub Actions run: https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42809567575
- Host checks: **PASSED** (11 behavioral tests, 7,200 continuous dynamics Jacobian entries, gravity/heading finite differences, 42 non-negligible process-covariance entries against a separate double-precision reference, 1,200-sample synthetic CSV replay).
- Sanitized tests: **PASSED** (AddressSanitizer/UndefinedBehaviorSanitizer on the exercised host paths).
- Pico 2 ARM cross-build using pinned Raspberry Pi Pico SDK 2.2.0: **PASSED**. CI produced .elf, .bin, .uf2 artifacts.
- ARM `size` report from successful build: text 76,188 B; data 0 B; bss 25,472 B. These are linked-image section sizes, not measured runtime stack high-water.

## What Bundle A changed

- Continuous right-error dynamics and measurement linearizations independently checked by finite differences.
- Process noise includes position/velocity, attitude and bias cross-covariances, with a positive-weight three-node quadrature approximation.
- World-yaw covariance gauge is mapped to the body-error frame after tilted alignment.
- Long IMU gaps and saturated samples latch an invalid estimator state until explicit reset; no silent apparent return to current-time navigation.
- Fault state is included in telemetry rather than leaving an earlier healthy packet visible.

## Still unverified

No real Pico 2 or LSM6DS3 test has been performed. SPI electrical behavior, DMA/PIO timing, sensor noise coefficients, power, temperature, true maximum-latency performance, sensor calibration, live 6-DoF accuracy, and long-trajectory covariance consistency are not established. The noise settings are placeholders, and reset intentionally discards any previously estimated global/local pose.
