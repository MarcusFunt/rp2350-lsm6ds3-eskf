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

PR 2 is stacked on PR 1 commit `b749a8aa0e40718ab7b163cad29d9c550b088265`. The latest candidate/evaluator freeze is `55eed3252e3e2af72bd61be66aa14501d9f17399`. This branch changes the ESKF covariance reset and gravity bias Jacobians, guards contradictory external stationary hints, and adds one conflict diagnostic counter; it does not change sensor transport or firmware scheduling. PR2 head `4d023d0` passed all three RP2350 target builds in pinned CI run [42948451978](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948451978). An isolated PR2 resource delta remains **not measured**; the latest cumulative PR4C measurements are below. The PR 1 CI size numbers above belong to `c397fec`, not this branch.

| PR 2 metric | Status | Evidence / limitation |
|---|---|---|
| RP2350 target builds | `PASS` | PR2 head built direct-register, FIFO and binary-FIFO variants in pinned CI run [42948451978](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42948451978). The final-stack resource report below includes PR2 but does not isolate its delta. |
| Compiler stack-use estimate | `PASS cumulative estimate` | Final stacked report: 9,496 B largest individual frame in `Eskf15::predict`; this is not a whole-call-chain bound. |
| Heap/dynamic-allocation audit | `NOT_MEASURED` | Target resource reports do not audit runtime allocation paths. |
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

The preceding pinned PR3 CI run [42922194992](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42922194992) built stacked merge commit `f718113f31c25604f6d93b6c05c30e87e08792a8` and reported direct-register `77,884/0/25,552 B`. Comparing that run with PR4A's `77,940/0/25,560 B` gives a direct-register PR4A cumulative delta of `+56 B text`, `0 B data`, and `+8 B bss`. The CI run uses merge commits, but the feature head delta is the PR4A commit range. PR3 CI did not print FIFO or binary-FIFO sizes, so an isolated sub-PR delta for those variants is unavailable.

## PR 4B status — calibration, aiding and runtime health

PR4B is stacked on PR4A `fix/eskf-fifo-timing` at `26315b4732b920356c279137c057f4e88b148632`. It adds a fixed calibration serialization format, transform conditioning checks, aid-age alignment, per-component aid metadata and runtime freshness/availability flags. Resource numbers below are pending the PR4B pinned CI run; they must be compared to the PR4A values above after that run.

| Configuration / metric | PR4A | PR4B | Status |
|---|---:|---:|---|
| Direct-register `.text/.data/.bss` | `77,940/0/25,560 B` | `78,948/0/25,568 B` | `PASS` pinned CI |
| FIFO `.text/.data/.bss` | `80,048/0/25,548 B` | `81,080/0/25,556 B` | `PASS` pinned CI |
| Binary FIFO `.text/.data/.bss` | `71,244/0/25,548 B` | `71,452/0/25,556 B` | `PASS` pinned CI |
| Separate `.rodata`, linker maps and compiler stack-use files | Not recorded | Pending | `NOT_RECORDED` |
| Heap/dynamic allocation audit | Not run | Not run | `NOT_RECORDED` |
| Hardware latency, queue high-water and stack high-water | Not measured | Not measured | `BLOCKED_HARDWARE` |

Pinned Pico SDK 2.2.0 run [42925544474](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42925544474) built stacked merge commit `a91abe5ec00028688afea554bad7d19be39f4d70` (PR4B head `5072de0bece33f4fafd62f9a1d76a1733d04b20`). Relative to PR4A, the direct/FIFO/binary `.text` deltas are `+1,008/+1,032/+208 B`; `.data` deltas are zero and `.bss` increases by 8 B for each. These are feature-branch cumulative deltas at the PR merge commits. Standard `size` aggregates read-only data into `text`; the cumulative PR4C report below emits section-level `.rodata`, linker maps and `-fstack-usage` evidence.

## PR 4C resource report method and target evidence

PR4C adds `-fstack-usage` to the firmware target and writes a linker map for each configured build directory. `tools/report_firmware_resources.py` uses `arm-none-eabi-size -A` to report separate `.text`, `.rodata`, `.data`, and `.bss` byte counts, binary image size and linker-map flash capacity/headroom, main-RAM capacity remaining after `.data + .bss`, and the largest individual compiler-reported function frame from the `.su` files. Pinned CI runs it for direct-register, FIFO, and binary-FIFO configurations and uploads each ELF, map, `.su` files, UF2/BIN, and JSON report.

Pinned Pico SDK 2.2.0 run [42957404275](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275) passed host tests and all three ARM build variants at cumulative PR4C source head `efa6a62fbf8929eb85307582d937aa9ff3305308`; artifact [13827657562](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42957404275/artifacts/13827657562) contains the reports and build products. Sizes below are from this artifact, which includes the PR3 startup-alignment correction. Unlike the older `arm-none-eabi-size` aggregate `text/data/bss` rows, this report separates `.text` from `.rodata` and includes initialized `.data`; do not compare the columns directly to the older aggregate values.

| Configuration | `.text` | `.rodata` | `.data` | `.bss` | Flash image | Flash remaining / 4 MiB | Static RAM `.data + .bss` | Main RAM remaining / 512 KiB | Largest per-function frame |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct-register | 72,648 B | 3,568 B | 11,324 B | 24,872 B | 88,148 B | 4,106,156 B | 36,196 B | 488,092 B | 9,496 B |
| FIFO | 75,276 B | 3,592 B | 11,300 B | 24,860 B | 90,780 B | 4,103,524 B | 36,160 B | 488,128 B | 9,496 B |
| Binary FIFO | 66,348 B | 2,324 B | 11,300 B | 24,864 B | 80,584 B | 4,113,720 B | 36,164 B | 488,124 B | 9,496 B |

The raw `.su` records and corrected JSON identify `void inertial::Eskf15::predict(inertial::Vec3, inertial::Vec3, float)` as the 9,496-byte frame in all three variants. This is 1,936 bytes larger than the prior artifact after the FP64 covariance change. Core 1 is allocated a 16,384-byte stack, so the largest single frame is 58.0% of that allocation and leaves 6,888 bytes before nested calls, interrupts, and other stack use. This per-function estimate is not a whole-call-chain bound. The JSON report's function-name parser initially truncated C++ qualified names; a regression test now covers namespace separators, comma-separated parameters, and Windows drive paths, and the fix is verified in the current pinned CI artifact.

These numbers are compile/link evidence, not measured usable headroom. Individual `.su` frames do not describe maximum whole-call-chain stack depth or dynamic stack effects. The linker map and static sections do not establish physical high-water. Only the dedicated core-1 stack has a sentinel watermark hook; core-0 stack high-water remains unmeasured. The 4,808 µs diagnostic service threshold is a provisional 208 Hz sample interval, not an application deadline. Heap use, hardware timing, and actual stack use remain unmeasured.
