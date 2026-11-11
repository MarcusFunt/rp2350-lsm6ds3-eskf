# PR4C logging, resource evidence and runtime hooks

## Gate

**PR4C software implementation gate: PASS at source head `54f3ebbfa45e8453562064c6dc348fbe2a3e86f0`. Hardware qualification: BLOCKED. PR2 and PR3 algorithm/statistical gates remain OPEN.** Pinned CI passed host validation and all three target builds. This branch is stacked on PR4B head `a690c343ef374b8727f094370c74250220b667b8`, which includes the latest PR3 evidence and portability fix. All target measurements reported here distinguish compiler/build evidence from on-device measurements.

## Changes

- Binary log records are version 2, remain fixed at 64 bytes, and add an explicit `dropped_records_before` field while retaining CRC-32. Header and record decoders accept version 1; replay checks each record against its header version.
- Replay reports sequence gaps and explicit dropped-record totals and rejects timestamp/sequence reversal, calibration mismatch, CRC damage, and truncation. The generated fixture contains one intentional sequence gap and one corresponding explicit drop count.
- Binary USB logging remains an opt-in debug transport on Pico stdio. It counts samples skipped while disconnected, sends a fresh header after reconnect, and places accumulated skips on the next successful record. Pico stdio's write callback does not expose partial completion; timeouts while connection state remains active cannot be counted precisely. The output can block and is not a lossless logger.
- Added fixed-size 32-bin log2 latency histograms with bucket-upper-bound p50/p95/p99 and exact observed maximum. Text diagnostics sample ESKF process time, SPI transfer time, per-edge acquisition service, IRQ-to-main dispatch latency, sample timestamp-to-publication age, queue occupancy after successful insertions, sample-period service overruns, and core-1 stack high-water. A consumer can drain between queue insertion and occupancy sampling, so queue peaks are sampled diagnostics rather than an atomic exact maximum.
- The 4,808 µs threshold is a provisional 208 Hz sample service interval, not a controller deadline. Core-0 stack watermark, complete call-chain stack requirements, physical jitter, and real queue behavior remain unmeasured.
- All target variants now emit linker maps and GCC `-fstack-usage` records in CI. `tools/report_firmware_resources.py` reports distinct `.text`, `.rodata`, `.data`, `.bss` sections, binary flash image/capacity/headroom, main RAM capacity remaining after `.data + .bss`, and the largest individual function frame estimate. Heap use and whole-path stack headroom are not inferred from these figures.
- The first target report exposed a parser defect: C++ `::` scopes and argument lists with commas were truncating the reported function name. A regression test verifies full GCC `.su` signature parsing, including Windows drive paths; the correction is included in the current source and its report names were verified in the follow-up CI artifact.

## Verification

- Bundle C host checks cover v1/v2 record compatibility, version-2 loss metadata, one injected sequence gap, calibration mismatch, CRC rejection, truncated-record rejection, and resource-report parser regression tests.
- Local Bundle A/B/C host and sanitizer suites pass on the corrected source; the resource-report parser regression tests pass as part of Bundle C.
- Pinned Pico SDK 2.2.0 run [42948475410](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410) passed host validation and direct-register, FIFO, and binary-FIFO ARM builds at the source head above. Artifact [13824515631](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410/artifacts/13824515631) contains linker maps, `.su`, ELF/BIN/UF2, and JSON resource reports.
- The latest CI artifact reports direct/FIFO/binary flash images of `87,724/90,356/80,160 B`, static `.data + .bss` of `36,172/36,136/36,140 B`, and largest per-function frames of `9,496 B`. Corrected JSON and raw `.su` records identify the largest frame as `void inertial::Eskf15::predict(inertial::Vec3, inertial::Vec3, float)` on all three variants. Core 1 is assigned a 16,384-byte stack, leaving `6,888 B` after that single frame before nested calls, interrupts, or other stack use; actual high-water and whole-call-chain requirements remain unmeasured.
- Physical LSM6DS3/Pico 2 timing, stack high-water, acquisition loss, and controller freshness remain `NOT_MEASURED_ON_DEVICE` / `BLOCKED_HARDWARE`.

## Acceptance status

PR4C software verification is complete for the recorded host and pinned target builds, with reports/maps/stack-use artifacts available. Hardware performance and release suitability remain blocked. The complete remediation program remains incomplete while PR2/PR3 gates are open.
