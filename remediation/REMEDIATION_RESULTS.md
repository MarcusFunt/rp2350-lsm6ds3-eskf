# ESKF remediation delivery status

**Program status: INCOMPLETE.** The stacked software work is documented below, but PR2 and PR3 acceptance gates remain open because of reproducible estimator/statistical failures. PR4C target/resource CI is pending. No Pico 2 + original LSM6DS3 hardware capture was available. Firmware remains experimental and is not qualified for control.

## Milestone status

| Milestone | Branch / reference | Host and target checks | Gate / remaining blocker |
|---|---|---|---|
| PR1 evidence baseline | `test/eskf-remediation-pr1`, `b749a8a` | Baseline/reproduction and locked paired seed evidence recorded | Evidence milestone complete; historical targets and hardware remain reference-only |
| PR2 math and recovery | `fix/eskf-math-recovery`, `cde0fe8` | Bundle A/B/C host and sanitizer suites pass; no target cross-build was recorded for PR2 | **OPEN**: LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation, and held-out false-hint/zero-dwell coverage gaps remain. See [PR2 results](PR2_RESULTS.md) and [root-cause records](ROOT_CAUSES.md). |
| PR3 statistics and reports | `test/eskf-statistics-benchmarks`, latest evidence commit `02dfab5` | Protocol v3, scenario codegen, runtime, math oracle, host/sanitizer checks and pinned CI smoke pass. Development, held-out and final-confirmation sets each ran 100 seeds across eight scenarios at nominal 208 Hz baseline IMU-only/unknown-start/no-aid. A separate 4-seed development pilot covers all rate, stress, startup, calibration and aid profiles. | **OPEN**: 4,478 of 7,200 primary rows are incomplete/failed; only 4 of 900 primary vibration rows complete. The four-seed pilot adds 4,032 rows, 2,916 incomplete/failed, and zero complete stress rows; it is exploratory, not 100-seed acceptance. Alternative estimator variants and 100-seed coverage on the other axes remain `NOT_RUN`. See [PR3 status](PR3_STATUS.md) and [factor pilot](PR3_FACTOR_PILOT.md). |
| PR4A FIFO and acquisition | `fix/eskf-fifo-timing`, latest stack head `5aabb83` | Bundle C host/sanitizer and direct/FIFO/binary-FIFO ARM builds pass in pinned CI run [42922199617](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42922199617). Direct/FIFO/binary `.text/.data/.bss`: `77,940/0/25,560`, `80,048/0/25,548`, `71,244/0/25,548` B. | Software gate pass; physical FIFO, timestamp quality and loss behavior remain **BLOCKED_HARDWARE**. |
| PR4B calibration/aiding/health | `fix/eskf-calibration-aiding-health`, latest stack head `b1d32cd` | Bundle A/B/C host/sanitizer and all three ARM variants pass in pinned CI run [42925544474](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42925544474). | Software gate pass; physical calibration, aiding source, control timing and accuracy remain **BLOCKED_HARDWARE**. |
| PR4C logging/resources/report | `fix/eskf-logging-resources-report`, current branch | Local Bundle A/B/C host/sanitizer suites and PR3 protocol/math tests pass. Pinned CI map/stack-use/resource report is pending. | **PENDING CI**; hardware performance and full stack headroom remain unmeasured. See [PR4C status](PR4C_STATUS.md) and [resource ledger](RESOURCE_BUDGETS.md). |

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
| PR3 scenario protocol v1/v2/v3 validators and codegen tests | PASS |
| PR3 protocol runtime and tilt-NEES oracle tests | PASS |

The current PR4C commit SHA and pinned cross-build/resource artifacts are added after publication/CI. Synthetic results and target builds do not replace physical acceptance measurements.

## Explicit unresolved items

- PR2/PR3 known statistical and estimator-behavior failures are visible and have not been waived.
- No independent live aid is wired into the firmware, and IMU-only yaw/position observability is limited.
- No board, sensor, controller deadline, or hardware capture exists for physical accuracy, FIFO loss, interrupt timing, stack watermark, or deadline evidence.
- Compiler per-function stack records and a map are not whole-call-chain or device stack-headroom measurements.
- The firmware stays **experimental** pending hardware and application-specific qualification.
