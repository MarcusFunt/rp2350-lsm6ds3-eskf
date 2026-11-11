# Hardware validation plan and status

**Status: BLOCKED — no Pico 2/RP2350 board or original LSM6DS3 sensor was available.** Host simulations, mock-bus tests, and a cross-build do not establish physical timing, sample integrity, or control safety.

## Target and firmware variants

- Board: Raspberry Pi Pico 2 / RP2350, with the original LSM6DS3 (`WHO_AM_I=0x69`). Do not substitute a DSO, DSOX, or another FIFO implementation without checking its own documentation.
- Direct-register DMA build: default acquisition path and fallback.
- FIFO build: opt-in `RP2350_USE_FIFO=ON`; configured for 208 Hz continuous mode, gyro and accelerometer without decimation. FIFO times are reconstructed from the PIO DRDY anchor and nominal ODR.
- Binary FIFO logging build: debug-only USB output; not an acquisition timing qualification.

## Procedure when hardware is available

1. Record board revision, exact sensor marking, firmware SHA, Pico SDK/compiler versions, pin mapping, supply voltage, temperature, and configuration flags. Confirm the sensor ID before enabling acquisition.
2. Capture INT1/DRDY and SPI chip-select/clock with a logic analyzer while running the direct-register DMA build. Retain raw edge intervals and sample sequence counters as the comparison baseline.
3. Run the opt-in FIFO build first while stationary, then during controlled rotation and acceleration. Capture the PIO DRDY signal, SPI transactions, FIFO status words/pattern, FIFO reset/overrun/bus counters, discarded-frame count, sample timestamps, and sequence values.
4. Repeat at normal load, after an induced host-processing delay, and with a controlled SPI fault if it can be done without damaging the board. Verify that every discontinuity is reflected in the counters/sequence/ESKF gap state and that reset/restart begins from a documented FIFO bypass/continuous transition.
5. Run sustained soak captures and inspect for duplicate, missing, reordered, or stale samples. Compare reconstructed FIFO times with captured DRDY edges. Quantify the timestamp uncertainty; the FIFO data used here do not contain per-sample hardware timestamps.
6. Capture p50/p95/p99/max ESKF processing time, FIFO/SPI drain time, edge-to-publication age, queue peaks/drops, deadline misses, and stack high-water by execution context. Save the raw captures and the analysis command with the firmware SHA.

## Acceptance limits

Do not set a controller freshness deadline or timing margin until the intended controller period and RP2350 workload allocation are known. The existing 100 ms diagnostic stale-input threshold is provisional and is not a control deadline. For acquisition integrity, the required result is no unaccounted duplicate/reordering and explicit accounting for all observed software discards, queue drops, FIFO resets, and overrun conditions. Timing and timestamp acceptance limits remain **PROVISIONAL** until the application requirement and hardware captures exist.

## Results

| Item | Result | Evidence |
|---|---|---|
| Original LSM6DS3 FIFO pattern and register semantics | Reviewed against ST AN4650; mock coverage added | `lsm6ds3_fifo.hpp`, `tests/test_bundle_c.cpp` |
| Host FIFO/status/timestamp tests | PASS | PR4A Bundle C test output |
| RP2350 direct/FIFO/binary cross-build (PR4A head) | PASS | Pinned Pico SDK 2.2.0 run [42922199617](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42922199617), stacked merge commit `7984be8f55dd23453f0786933003bc414785936e` |
| RP2350 PR4B build | PASS | Pinned Pico SDK 2.2.0 run [42925544474](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42925544474), merge commit `a91abe5ec00028688afea554bad7d19be39f4d70` |
| PR4C runtime timing/queue hooks and sentinel stack estimate | Implemented; not measured | `main.cpp` debug status fields. Core-1 watermark is a software estimate; core-0 stack and physical timing are unavailable without board captures |
| PR4C section/map/stack-use reporting | PASS pinned CI | Run [42948475410](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410), artifact [13824515631](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410/artifacts/13824515631); reports/maps/`.su` for all three firmware variants. These are build estimates, not device measurements. |
| Physical FIFO/DRDY/SPI capture | NOT RUN | hardware unavailable |
| On-device timing, stack high-water, and long-run loss | NOT MEASURED | hardware unavailable |
