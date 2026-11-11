# PR4B calibration, aiding and control-health status

## Gate

**PR4B host, sanitizer and target cross-build gates: PASS. Physical validation: BLOCKED — hardware required.** This branch is stacked on PR4A commit `26315b4732b920356c279137c057f4e88b148632` (`fix/eskf-fifo-timing`). PR2/PR3 statistical acceptance findings remain open and are not hidden by these firmware-boundary changes.

## Changes

- Calibration matrices now reject non-finite, reflected, singular and relatively ill-conditioned transforms. Temperature-compensated calibration rejects missing/non-finite temperature; calibration without temperature compensation remains usable when the sensor has no temperature sample. Offline fixed offsets remain separate from ESKF residual bias states.
- Added a fixed 184-byte little-endian `SCAL` format with format/calibration/source versions, 40 FP32 values, reserved-flag checks, CRC-32, strict length checks and validated decode-before-assignment.
- `AidingRouter` now applies the estimator's configured maximum aiding age instead of its own hard-coded 1 ms limit. It still checks independent-source provenance, source/calibration/timebase, frame, capture/publication/interval ordering, future and stale captures, and per-source capture monotonicity.
- Accepted position/velocity/heading aid dimensions, last source and capture time are exposed. Runtime health separately reports sensor-edge freshness, estimate and publication freshness, calibration identity, nominal/fault/reset status, and whether heading or absolute position has ever received independent aiding.
- Console `output_available` means only current, calibrated, nominal, non-reset state availability. `Health` is no longer rewritten by the console to fold in stale status. The 100 ms diagnostic age stays provisional and is not a control deadline. A single calibration rejection no longer permanently latches output unavailable; freshness follows current inputs and estimate timestamps.

## Verification

- Test-first regressions observed the positive-determinant near-singular calibration acceptance, absent wire-format API, router rejection of a 2 ms aid despite a configured 4 ms age, and absent runtime-health API. Each was corrected and its regression now passes.
- Bundle A/B/C host suites passed in WSL2 with GCC 11.4.0.
- Bundle A/B/C sanitizer suites passed; Bundle C additionally covers calibration serialization CRC/version/truncation, missing-temperature behavior, source/frame/timebase/ordering/stale/correlated aids, configured aid age, missing sensor edge, stale cross-core publication, calibration validity, and unobservable yaw/position flags.
- Pinned Pico SDK 2.2.0 run [42925544474](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42925544474) passed host/sanitizer checks and direct-register, FIFO and binary-FIFO builds on merge commit `a91abe5ec00028688afea554bad7d19be39f4d70` (PR4B head `5072de0bece33f4fafd62f9a1d76a1733d04b20e`). `arm-none-eabi-size` reported direct `78,948/0/25,568 B`, FIFO `81,080/0/25,556 B`, and binary FIFO `71,452/0/25,556 B` for `.text/.data/.bss`. Separate `.rodata`, linker maps and stack-use files remain unrecorded pending PR4C tooling. See [resource budgets](RESOURCE_BUDGETS.md).
- On-device calibration accuracy, aiding transport/provenance and control suitability remain unmeasured without hardware and an application-specific controller contract.

## Remaining limits

The checked-in firmware does not yet ingest an independent physical aid, so aid source and observability metadata remain zero on-device. The runtime status does not certify attitude accuracy or safety. Absolute yaw and position remain unobservable until the required independent information is accepted. The physical calibration dataset, controller deadline and hardware timing remain unavailable.
