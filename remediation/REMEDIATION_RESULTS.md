# ESKF remediation delivery status

**Program status: INCOMPLETE.** The stacked software work is documented below, but PR2 and PR3 acceptance gates remain open because of reproducible estimator/statistical failures. PR4C host/target builds and resource artifacts passed in pinned CI at head `54f3ebb`. No Pico 2 + original LSM6DS3 hardware capture was available. Firmware remains experimental and is not qualified for control.

## Milestone status

| Milestone | Branch / reference | Host and target checks | Gate / remaining blocker |
|---|---|---|---|
| PR1 evidence baseline | `test/eskf-remediation-pr1`, `b749a8a` | Baseline/reproduction and locked paired seed evidence recorded | Evidence milestone complete; historical targets and hardware remain reference-only |
| PR2 math and recovery | `fix/eskf-math-recovery`, `4d023d0` | Full stacked host/sanitizer and target builds pass in the latest PR4C CI run | **OPEN**: LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation, and held-out false-hint/zero-dwell coverage gaps remain. See [PR2 results](PR2_RESULTS.md) and [root-cause records](ROOT_CAUSES.md). |
| PR3 statistics and reports | `test/eskf-statistics-benchmarks`, latest evidence commit `2d59ebb` | Protocol-v5 baseline, codegen/runtime, analytic tilt, summary and line-ending checks pass. Development, held-out and final-confirmation sets each ran 100 seeds across eight scenarios at nominal 208 Hz baseline IMU-only/unknown-start/no-aid. | **OPEN**: Primary nominal sets have zero incomplete rows, but the four-seed factor pilot has 2,016 incomplete ESKF stress rows (0/672 complete per policy). The acceleration-step initialization defect remains open; full-factor acceptance, PR2 behavior, and hardware validation are not complete. See [PR3 status](PR3_STATUS.md) and [factor pilot](PR3_FACTOR_PILOT.md). |
| PR4A FIFO and acquisition | `fix/eskf-fifo-timing`, stack head `90fe4f1` | Latest cumulative PR4C CI run [42948475410](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410) passed all three target builds | Software checks pass; physical FIFO, timestamp quality and loss behavior remain **BLOCKED_HARDWARE**. |
| PR4B calibration/aiding/health | `fix/eskf-calibration-aiding-health`, stack head `a690c34` | Latest cumulative PR4C CI run [42948475410](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410) passed host checks and all three target builds | Software checks pass; physical calibration, aiding source, control timing and accuracy remain **BLOCKED_HARDWARE**. |
| PR4C logging/resources/report | `fix/eskf-logging-resources-report`, head `54f3ebb` | Pinned SDK 2.2.0 run [42948475410](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410) passed host and three target builds; artifact [13824515631](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948475410/artifacts/13824515631) contains maps, `.su`, ELF/BIN/UF2, and JSON. Largest per-function frame is 9,496 B in `Eskf15::predict`. | Software verification PASS; hardware performance and whole-call-chain stack headroom remain unmeasured. See [PR4C status](PR4C_STATUS.md) and [resource ledger](RESOURCE_BUDGETS.md). |

## Test evidence from the PR4C source tree

Run commands from a clean checkout with Bash, GCC/Clang C++17, Python 3, and the pinned Pico SDK for the target builds:

| Command | Result |
|---|---|
| `./tools/run_bundle_a_checks.sh` | PASS |
| `./tools/run_bundle_b_checks.sh` | PASS |
| `./tools/run_bundle_c_checks.sh` | PASS; v1/v2 replay and one injected sequence/drop provenance check |
| `BUNDLE_A_SANITIZERS=1 ./tools/run_bundle_a_checks.sh` | PASS |
| `BUNDLE_B_SANITIZERS=1 ./tools/run_bundle_b_checks.sh` | PASS |
| `BUNDLE_C_SANITIZERS=1 ./tools/run_bundle_c_checks.sh` | PASS |
| PR3 scenario protocol v1–v5 validators, codegen and cross-platform line-ending checks | PASS |
| PR3 protocol runtime, summary portability and tilt-NEES oracle tests | PASS |
| `python3 tests/test_firmware_resource_report.py` | PASS; function names retain C++ scopes and argument lists |

Current PR4C source head: `54f3ebbfa45e8453562064c6dc348fbe2a3e86f0`. The pinned CI artifact reports direct/FIFO/binary flash images of `87,724/90,356/80,160 B`, static `.data + .bss` of `36,172/36,136/36,140 B`, and `9,496 B` largest per-function frames in `Eskf15::predict`. Synthetic results and target builds do not replace physical acceptance measurements.

## Explicit unresolved items

- PR2/PR3 known statistical and estimator-behavior failures are visible and have not been waived.
- No independent live aid is wired into the firmware, and IMU-only yaw/position observability is limited.
- No board, sensor, controller deadline, or hardware capture exists for physical accuracy, FIFO loss, interrupt timing, stack watermark, or deadline evidence.
- Compiler per-function stack records and a map are not whole-call-chain or device stack-headroom measurements.
- The firmware stays **experimental** pending hardware and application-specific qualification.
