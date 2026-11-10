# Verification record (10 November 2026)

This is a test record for **code behavior**, not a measured sensor-performance study. Execution took place on a Linux x86_64 host, not the RP2350.

## Host commands executed successfully

```bash
./tools/run_host_checks.sh

g++ -std=c++17 -O1 -g -Wall -Wextra -Wpedantic \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  tests/test_eskf15.cpp -o test_sanitized
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 ./test_sanitized
```

Results: **nine host test cases passed**. AddressSanitizer and UndefinedBehaviorSanitizer reported no errors in the executed test cases. The deterministic CSV fixture contains 1,200 valid samples: 80 initialization readings, 1,120 propagated samples, 0 missing-gap detections, 0 saturation detections. Final synthetic yaw ≈**1.9635 rad**, matching the known imposed **5 s × π/8 rad/s** trajectory (within 0.025 rad).

## Not verified

Pico SDK cross-build (**SDK and `arm-none-eabi` toolchain unavailable in this environment**), RP2350 SRAM/stack high-water, absolute/relative timing accuracy, SPI/DMA/PIO waveform, LSM6DS3 register behavior on hardware, sensor noise calibration, estimator NEES and physical attitude accuracy. Do not interpret the host `max_process_us` instrumentation as having been benchmarked on the target.
