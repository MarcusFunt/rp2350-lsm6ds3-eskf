# Resource budgets — PR 1 baseline and PR 2 status

## Firmware baseline evidence

The available pinned RP2350 CI run is for the pre-PR-1 `origin/main` commit `c397fec8f5df3fb612ea6aa92547d484e9e48c06`, with Pico SDK 2.2.0. Its direct-register configuration built successfully. `arm-none-eabi-size` reported `.text=79,092`, `.data=0`, and `.bss=25,552` bytes (reported section sum 104,644 bytes). The run also built FIFO and binary-log variants, but did not emit their individual section sizes. The CI did not record compiler stack-use output or physical stack high-water.

Evidence: [pinned CI run](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42816672377), cross-build job `129831387144`; the manifest records the direct UF2 SHA-256 and toolchain version.

| Configuration / metric | Baseline value | PR 1 value | Status |
|---|---:|---:|---|
| Direct-register `.text` | 79,092 B | Not measured on PR 1 branch | Baseline verified; branch cross-build not run |
| Direct-register `.data` | 0 B | Not measured on PR 1 branch | Baseline verified; branch cross-build not run |
| Direct-register `.bss` | 25,552 B | Not measured on PR 1 branch | Baseline verified; branch cross-build not run |
| FIFO and binary-log section sizes | Not emitted | Not measured | `NOT_RECORDED` |
| Compiler stack-use estimate | Not recorded | Not measured | `NOT_RECORDED` |
| Heap/dynamic allocation audit | Not measured in this step | Not measured | `NOT_RECORDED` |
| ESKF execution/acquisition latency and stack high-water | No board measurements | No board measurements | `NOT_MEASURED_ON_DEVICE` / `BLOCKED_HARDWARE` |

PR 1 changes host-only tools, tests and documentation; no firmware source or estimator equations changed. A zero firmware size delta is therefore expected from source scope, but has not been measured and is not reported as a build result. The Windows/WSL environment used for host checks did not have `arm-none-eabi-g++` or `PICO_SDK_PATH`, so the branch itself was not cross-built.

## Provisional constraints

The frozen simulation cadence is 200 Hz (5 ms), which defines the host scenario timestep only; it does not establish an on-device deadline budget. This PR does not set an acceptable timing or stack limit because the controller freshness requirement, task/core allocation, interrupt load, and board-level stack allocation have not been measured. The ledger remains provisional until those requirements and hardware evidence are supplied.

Before any firmware optimization or resource claim, measure all direct/FIFO/binary configurations with the pinned SDK, save map files and section sizes, enable `-fstack-usage` where supported, and audit allocation paths. On hardware, record process time p50/p95/p99/max, acquisition and end-to-end age, queue peaks/drops, deadline misses, and per-context stack high-water. Host wall-clock measurements are not a substitute for those values.

## PR 2 branch status

PR 2 is stacked on PR 1 commit `b749a8aa0e40718ab7b163cad29d9c550b088265`. The latest candidate/evaluator freeze is `55eed3252e3e2af72bd61be66aa14501d9f17399`. This branch changes the ESKF covariance reset and gravity bias Jacobians, guards contradictory external stationary hints, and adds one conflict diagnostic counter; it does not change sensor transport or firmware scheduling. A target-resource delta is **not measured**. The PR 1 CI size numbers above belong to `c397fec`, not this branch.

| PR 2 metric | Status | Evidence / limitation |
|---|---|---|
| RP2350 `.text`, `.rodata`, `.data`, `.bss` and map file | `NOT_RUN` | `arm-none-eabi-g++` is unavailable and `PICO_SDK_PATH` is unset in this environment. No host size result is substituted. |
| Compiler stack-use estimate | `NOT_RUN` | Requires the pinned ARM build and `-fstack-usage`; no estimate is inferred from host tests. |
| Heap/dynamic-allocation audit | `NOT_RUN` | PR 2 adds no estimator-owned dynamic allocation by inspection, but a complete target/link audit was not executed. |
| ESKF/acquisition latency and stack high-water | `NOT_MEASURED_ON_DEVICE` | Requires the Pico 2, the original LSM6DS3, and workload instrumentation. |

The fixed covariance reset evaluates trigonometric coefficients for nonzero correction vectors, and the finite-innovation gravity Jacobian normalizes the measured direction; no embedded timing or flash/RAM impact is claimed. The software checks ran under host GCC 11.4.0 in WSL2 and do not establish target deadlines or hardware reliability.

## PR 4A status — FIFO acquisition and reconstructed timestamps

PR4A is stacked on PR3 base `a9e58286eb320687ae53959052c466a5da18feaa`. It changes the opt-in FIFO drain in `main.cpp` and adds fixed-size FIFO timestamp/capacity helpers. The direct-register DMA branch remains the default. Host measurements below are test-run evidence only, not RP2350 resource measurements.

| Configuration / metric | PR 1 reference | PR4A result | Status |
|---|---:|---:|---|
| Direct-register `.text/.data/.bss` | `79,092/0/25,552 B` at `c397fec` | `77,940/0/25,560 B` | `PASS` pinned CI |
| FIFO `.text/.data/.bss` | Not emitted | `80,048/0/25,548 B` | `PASS` pinned CI |
| Binary FIFO `.text/.data/.bss` | Not emitted | `71,244/0/25,548 B` | `PASS` pinned CI |
| Compiler stack-use estimates | Not recorded | `-fstack-usage` not yet enabled | `NOT_RECORDED` |
| FIFO drain and ESKF duration | No board measurements | No Pico 2/LSM6DS3 available | `NOT_MEASURED_ON_DEVICE` |
| DRDY-to-publication latency, queue peaks/drops, FIFO age | No board measurements | Telemetry counters are present; no physical capture | `BLOCKED_HARDWARE` |

Pinned Pico SDK 2.2.0 CI run [42922199617](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42922199617) built the stacked PR4A merge commit `7984be8f55dd23453f0786933003bc414785936e` (PR4A head `610dfde6de4ded783414d81f17b67897ad28f64a`). `arm-none-eabi-size` reports the values above. At the same commit/configuration, FIFO adds 2,108 bytes of `text` and uses 12 fewer bytes of `bss` than direct-register; `text` includes read-only data in this tool output, so `.rodata` is not separately reported. The direct-register `.text` total is 1,152 bytes lower than the historical `c397fec` baseline, while `.bss` is 8 bytes higher; this is a cumulative stacked comparison and does not isolate PR4A. The workflow does not yet produce link maps or `-fstack-usage` output. No host binary size is substituted. See [PR4A status](PR4A_STATUS.md) and [hardware validation](HARDWARE_VALIDATION.md).
