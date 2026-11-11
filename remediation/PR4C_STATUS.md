# PR4C logging, resource evidence and runtime hooks

## Gate

**PR4C implementation gate: pending pinned CI and resource artifacts. Hardware qualification: BLOCKED. PR2 and PR3 algorithm/statistical gates remain OPEN.** This branch is stacked on the updated PR4B branch at `b1d32cd7f1fadcb98ce139ded2cd2028dac22fa5`, which includes the latest PR3 factor-pilot evidence. All target measurements reported here will distinguish compiler/build evidence from on-device measurements.

## Changes

- Binary log records are version 2, remain fixed at 64 bytes, and add an explicit `dropped_records_before` field while retaining CRC-32. Header and record decoders accept version 1; replay checks each record against its header version.
- Replay reports sequence gaps and explicit dropped-record totals and rejects timestamp/sequence reversal, calibration mismatch, CRC damage, and truncation. The generated fixture contains one intentional sequence gap and one corresponding explicit drop count.
- Binary USB logging remains an opt-in debug transport on Pico stdio. It counts samples skipped while disconnected, sends a fresh header after reconnect, and places accumulated skips on the next successful record. Pico stdio's write callback does not expose partial completion; timeouts while connection state remains active cannot be counted precisely. The output can block and is not a lossless logger.
- Added fixed-size 32-bin log2 latency histograms with bucket-upper-bound p50/p95/p99 and exact observed maximum. Text diagnostics sample ESKF process time, SPI transfer time, per-edge acquisition service, IRQ-to-main dispatch latency, sample timestamp-to-publication age, queue occupancy after successful insertions, sample-period service overruns, and core-1 stack high-water. A consumer can drain between queue insertion and occupancy sampling, so queue peaks are sampled diagnostics rather than an atomic exact maximum.
- The 4,808 µs threshold is a provisional 208 Hz sample service interval, not a controller deadline. Core-0 stack watermark, complete call-chain stack requirements, physical jitter, and real queue behavior remain unmeasured.
- All target variants now emit linker maps and GCC `-fstack-usage` records in CI. `tools/report_firmware_resources.py` reports distinct `.text`, `.rodata`, `.data`, `.bss` sections, binary flash image/capacity/headroom, main RAM capacity remaining after `.data + .bss`, and the largest individual function frame estimate. Heap use and whole-path stack headroom are not inferred from these figures.

## Verification

- Bundle C host checks pass for v1/v2 record compatibility, version-2 loss metadata, one injected sequence gap, calibration mismatch, CRC rejection, and truncated-record rejection.
- Bundle C sanitizer checks and full Bundle A/B/C suites are pending final local run.
- Pinned Pico SDK 2.2.0 direct-register, FIFO, and binary-FIFO builds and resource artifacts are pending PR4C CI.
- Physical LSM6DS3/Pico 2 timing, stack high-water, acquisition loss, and controller freshness remain `NOT_MEASURED_ON_DEVICE` / `BLOCKED_HARDWARE`.

## Acceptance status

PR4C may be considered software-verified only after host/sanitizer and all three target variants pass, and resource reports/maps/stack-use artifacts are available. Hardware performance and release suitability remain blocked. The complete remediation program remains incomplete while PR2/PR3 gates are open.
