# ESKF remediation delivery status

**Program status: INCOMPLETE.** PR3 startup availability is corrected and the updated PR3/PR4 stack passes host, sanitizer, and pinned target CI, but PR2 and PR3 acceptance gates remain open because estimator accuracy/full-factor coverage findings persist. No Pico 2 + original LSM6DS3 hardware capture was available. Firmware remains experimental and is not qualified for control.

## Milestone status

| Milestone | Branch / reference | Host and target checks | Gate / remaining blocker |
|---|---|---|---|
| PR1 evidence baseline | `test/eskf-remediation-pr1`, `b749a8a` | Baseline/reproduction and locked paired seed evidence recorded | Evidence milestone complete; historical targets and hardware remain reference-only |
| PR2 math and recovery | `fix/eskf-math-recovery`, `4d023d0` | Full stacked host/sanitizer and target builds pass in the latest PR4C CI run | **OPEN**: LegacyHeuristic yaw/bias regressions, synthetic-heading-aid degradation, and held-out false-hint/zero-dwell coverage gaps remain. See [PR2 results](PR2_RESULTS.md) and [root-cause records](ROOT_CAUSES.md). |
| PR3 statistics and reports | `test/eskf-statistics-benchmarks`, evidence head `02c61fe` | Protocol-v5 development nominal rerun matches the previous 4,000 trial rows except commit SHA. Disjoint 100-seed held-out/final 208 Hz baseline stress runs each completed all 4,000 rows; each ESKF policy passed 2,330,400 covariance checks per split. PR3 CI [42957389682](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957389682) passed host, sanitizer and target jobs. | **OPEN**: Stress completion is fixed, but conservative ESKF mean per-trial RMS remains about 4.64–4.66° tilt and 10.30° yaw. 100-seed held-out/final coverage outside the baseline factors, broader accuracy/consistency acceptance, independent review, and PR2 behavior remain open. See [PR3 status](PR3_STATUS.md) and [factor pilot](PR3_FACTOR_PILOT.md). |
| PR4A FIFO and acquisition | `fix/eskf-fifo-timing`, updated stack head `29c2fc5` | PR4A CI [42957395985](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957395985) and cumulative PR4C CI [42957404275](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275) passed host, sanitizer, and three target builds | Software checks pass; physical FIFO, timestamp quality and loss behavior remain **BLOCKED_HARDWARE**. |
| PR4B calibration/aiding/health | `fix/eskf-calibration-aiding-health`, updated stack head `703895e` | PR4B CI [42957399541](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957399541) and cumulative PR4C CI [42957404275](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275) passed host, sanitizer, and three target builds | Software checks pass; physical calibration, aiding source, control timing and accuracy remain **BLOCKED_HARDWARE**. |
| PR4C logging/resources/report | `fix/eskf-logging-resources-report`, code head `efa6a62` | Pinned SDK 2.2.0 run [42957404275](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275) passed host/sanitizer and three target builds; artifact [13827657562](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275/artifacts/13827657562) contains maps, `.su`, ELF/BIN/UF2, and JSON. Largest per-function frame is 9,496 B in `Eskf15::predict`. | Software verification PASS; hardware performance and whole-call-chain stack headroom remain unmeasured. See [PR4C status](PR4C_STATUS.md) and [resource ledger](RESOURCE_BUDGETS.md). |

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
| PR3 scenario protocol v1–v5 validators and generated-header tests | PASS |
| PR3 protocol runtime, generator/evaluator, summary portability, factorized figures and Student-t intervals | PASS |
| `python3 tests/test_firmware_resource_report.py` | PASS; function names retain C++ scopes and argument lists |

Current PR4C code head: `efa6a62fbf8929eb85307582d937aa9ff3305308`. The pinned CI artifact reports direct/FIFO/binary flash images of `88,148/90,780/80,584 B`, static `.data + .bss` of `36,196/36,160/36,164 B`, and `9,496 B` largest per-function frames in `Eskf15::predict`. Synthetic results and target builds do not replace physical acceptance measurements.

## Explicit unresolved items

- PR2/PR3 known statistical and estimator-behavior failures are visible and have not been waived.
- No independent live aid is wired into the firmware, and IMU-only yaw/position observability is limited.
- No board, sensor, controller deadline, or hardware capture exists for physical accuracy, FIFO loss, interrupt timing, stack watermark, or deadline evidence.
- Compiler per-function stack records and a map are not whole-call-chain or device stack-headroom measurements.
- The firmware stays **experimental** pending hardware and application-specific qualification.
