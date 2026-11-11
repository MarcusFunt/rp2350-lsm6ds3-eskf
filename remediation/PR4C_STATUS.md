# PR4C logging, resource evidence and runtime hooks

## Gate

**PR4C source/build implementation: pinned target builds passed on the parent source revision; the resource-report parser correction in the current revision is awaiting CI. Hardware qualification: BLOCKED. PR2 and PR3 algorithm/statistical gates remain OPEN.** This branch is stacked on the updated PR4B branch at `b1d32cd7f1fadcb98ce139ded2cd2028dac22fa5`, which includes the latest PR3 factor-pilot evidence. All target measurements reported here distinguish compiler/build evidence from on-device measurements.

## Changes

- Binary log records are version 2, remain fixed at 64 bytes, and add an explicit `dropped_records_before` field while retaining CRC-32. Header and record decoders accept version 1; replay checks each record against its header version.
- Replay reports sequence gaps and explicit dropped-record totals and rejects timestamp/sequence reversal, calibration mismatch, CRC damage, and truncation. The generated fixture contains one intentional sequence gap and one corresponding explicit drop count.
- Binary USB logging remains an opt-in debug transport on Pico stdio. It counts samples skipped while disconnected, sends a fresh header after reconnect, and places accumulated skips on the next successful record. Pico stdio's write callback does not expose partial completion; timeouts while connection state remains active cannot be counted precisely. The output can block and is not a lossless logger.
- Added fixed-size 32-bin log2 latency histograms with bucket-upper-bound p50/p95/p99 and exact observed maximum. Text diagnostics sample ESKF process time, SPI transfer time, per-edge acquisition service, IRQ-to-main dispatch latency, sample timestamp-to-publication age, queue occupancy after successful insertions, sample-period service overruns, and core-1 stack high-water. A consumer can drain between queue insertion and occupancy sampling, so queue peaks are sampled diagnostics rather than an atomic exact maximum.
- The 4,808 µs threshold is a provisional 208 Hz sample service interval, not a controller deadline. Core-0 stack watermark, complete call-chain stack requirements, physical jitter, and real queue behavior remain unmeasured.
- All target variants now emit linker maps and GCC `-fstack-usage` records in CI. `tools/report_firmware_resources.py` reports distinct `.text`, `.rodata`, `.data`, `.bss` sections, binary flash image/capacity/headroom, main RAM capacity remaining after `.data + .bss`, and the largest individual function frame estimate. Heap use and whole-path stack headroom are not inferred from these figures.
- The first target report exposed a parser defect: C++ `::` scopes and argument lists with commas were truncating the reported function name. A regression test now verifies full GCC `.su` signature parsing, including Windows drive paths; the corrected parser is in the current revision and awaits pinned CI rerun.

## Verification

- Bundle C host checks cover v1/v2 record compatibility, version-2 loss metadata, one injected sequence gap, calibration mismatch, CRC rejection, truncated-record rejection, and resource-report parser regression tests.
- Local Bundle A/B/C host and sanitizer suites passed on the implementation before the report-parser correction; the new parser unit tests pass locally. The Bundle C suite is being rerun with the correction.
- Pinned Pico SDK 2.2.0 run [42930179012](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42930179012) passed host tests and direct-register, FIFO, and binary-FIFO ARM builds on PR4C head `0929a5528ef9ed19801fb1c08a1d81661abc2fa3`; it uploaded linker maps, `.su`, ELF/BIN/UF2, and JSON resource reports. A latest-revision rerun is pending.
- That CI artifact reports direct/FIFO/binary flash images of `78,324/80,956/69,384 B`, static `.data + .bss` of `35,268/35,232/34,348 B`, and largest per-function frames of `7,560 B`. Raw `.su` files identify the largest frame as `Eskf15::predict`; core 1 is assigned a 16,384-byte stack. This leaves `8,824 B` before nested calls, interrupts, or other stack use; actual high-water and whole-call-chain requirements remain unmeasured.
- Physical LSM6DS3/Pico 2 timing, stack high-water, acquisition loss, and controller freshness remain `NOT_MEASURED_ON_DEVICE` / `BLOCKED_HARDWARE`.

## Acceptance status

PR4C may be considered software-verified after the latest resource-parser revision passes host/sanitizer checks and the three target variants, with reports/maps/stack-use artifacts available. Hardware performance and release suitability remain blocked. The complete remediation program remains incomplete while PR2/PR3 gates are open.
