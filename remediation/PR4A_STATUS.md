# PR4A FIFO and acquisition status

## Gate

**PR4A host and target build gates: PASS. Physical validation: BLOCKED — hardware required.** The FIFO implementation remains behind `RP2350_USE_FIFO=ON`; direct-register DMA remains the default path. FIFO timestamps are reconstructed estimates, not sensor-provided timestamps.

The updated PR4A branch head `29c2fc5` includes PR3 head `02c61fe`, including the startup-alignment correction and its post-fix baseline stress evidence. PR3 accuracy/full-factor and PR2 acceptance gates remain open and are not changed by this FIFO work.

## Changes

- Added `lsm6ds3::reconstruct_timestamps()`: a 208 Hz backfill uses integer `floor(frames_back * 1,000,000 / rate_hz)`, checks ranges and underflow, and rejects non-monotonic results.
- Added `snapshot_capacity()`. Each bounded FIFO drain reads no more than the frame count reported by the first status snapshot. Frames arriving during the drain are left for the next DRDY edge.
- Replaced the hardcoded 4,808 µs offset with rational backfill. Status, overrun/full, bus, and invalid-timestamp paths now resynchronize or flush where possible. Software-discarded observed frames and timestamp failures are included in debug counters.
- The console labels backfilled time and exposes FIFO reset, bus-error, backfill, observed-discard, and timestamp-error counters. The FIFO path still uses blocking SPI and has not been enabled by default.
- The original LSM6DS3 [AN4650 FIFO note](https://community.st.com/ysqtg83639/attachments/ysqtg83639/mems-sensors-forum/21052/2/AN4650.PDF) defines `DIFF_FIFO` in 16-bit words, describes the 6-word `Gx,Gy,Gz,XLx,XLy,XLz` pattern for equal-rate gyro and accelerometer, and recommends synchronizing SPI status reads to DRDY or watermark. The tests and current configuration use that original-chip pattern. This is not a claim of hardware qualification.

## Verification

- Test-first timestamp helper check: expected missing `reconstruct_timestamps()` API at base; implemented and then passed exact 208 Hz rational offsets, chunk continuation, monotonicity, null/zero/range/underflow checks.
- Mock FIFO checks pass for complete signed samples, partial-word wait, pattern flush, FIFO full/overrun flags, bus read/write errors, capacity truncation, and a 50-frame original snapshot with five later arrivals left unread.
- Bundle A/B/C host and sanitizer suites passed. Bundle C was rerun after the final FIFO fault-path test additions.
- Pinned Pico SDK 2.2.0 CI run [42922199617](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42922199617) passed host/sanitizer checks and all direct-register, FIFO, and binary-FIFO builds on the earlier PR4A snapshot. Updated stack head `90fe4f1725ce188090946badfecde70ec15f0c87` also passed host and target jobs in cumulative run [42948466371](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948466371). `arm-none-eabi-size` reported direct `77,940/0/25,560 B`, FIFO `80,048/0/25,548 B`, and binary-FIFO `71,244/0/25,548 B` for `.text/.data/.bss`. The direct-register comparison to the historical `c397fec` reference is cumulative; it is not a PR4A-only delta. Separate `.rodata`, link maps and `-fstack-usage` remain unrecorded. See [resource budgets](RESOURCE_BUDGETS.md).
- The updated PR4A head passed all host and three target jobs in pinned cumulative PR4C run [42957404275](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275). Current stack resource figures and maps are recorded in [resource budgets](RESOURCE_BUDGETS.md); they include PR3 startup-window state and the later PR4 changes.
- Relative to preceding PR3 CI direct-register size (`77,884/0/25,552 B` on merge commit `f718113f31c25604f6d93b6c05c30e87e08792a8`), PR4A adds `56 B text`, `0 B data`, and `8 B bss`. PR3 CI did not record FIFO or binary-FIFO sizes, so those isolated deltas are unavailable.
- No physical Pico 2/LSM6DS3 was available. FIFO loss, actual edge alignment, interrupt/acquisition latency, and controller suitability remain blocked; see [hardware validation](HARDWARE_VALIDATION.md).

## Remaining risk

The host mock cannot verify electrical timing, the sensor's live FIFO status/pattern transitions, SPI throughput under load, or PIO edge alignment. If the FIFO path is built on hardware, compare DRDY, FIFO status, and sample identity with a logic analyzer and retain the raw trace. Keep the path experimental until this is complete.
