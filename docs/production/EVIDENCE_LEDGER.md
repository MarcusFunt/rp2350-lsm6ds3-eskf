# Production Readiness Evidence Ledger

Status: **engineering source/evidence baseline frozen at `38403245e71a7eee987f8779b61f7a38bc779ac4`; production gate OPEN**. This ledger separates the tested source baseline, earlier experiment evidence, and missing physical qualification. It is not a production approval.

## Source and worktree identity

| Item | Record |
|---|---|
| Repository | `MarcusFunt/rp2350-lsm6ds3-eskf` |
| Starting revision for this execution | `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973` on `main` |
| Candidate source/evidence baseline SHA | `38403245e71a7eee987f8779b61f7a38bc779ac4`; this is a tested engineering baseline, not a production release. |
| Release tag | None; product requirements and physical gates remain open. |
| Scope | Stage 1 estimator module; Stage 2 controller/actuator system gate is separate. |

The starting tree was already dirty. These changes are preserved and attributed below; no reset or cleanup was performed.

| Worktree paths | Attribution and status |
|---|---|
| `CMakeLists.txt`, `main.cpp`, `lsm6ds3_config.hpp`, `tests/test_lsm6ds3_config.cpp` | Centralize the LSM6DS3 active range profile so register values, raw-unit conversion and ESKF range thresholds use the same configuration. The host regression checks the production profile and keeps BROAD replay limits distinct. |
| `tools/run_bundle_c_checks.sh` | Add the range configuration regression to standard Bundle C execution, including sanitizer mode. |
| `remediation/analysis/b9_reference_baseline/` | Matched-interval BROAD atlas, reference outputs, and hash manifest from the previous milestone. |
| `remediation/analysis/pr3_gravity_gate_ablations/` | Gravity-gate diagnostics, held-out trials, BROAD fast-rotation checks, fault candidate checks, and hash manifest from the previous milestone. |
| `docs/production/` | Current requirements, gate, and this evidence reconciliation. |
| `docs/superpowers/plans/2026-11-10-simulation-coverage-and-reporting.md`, `docs/superpowers/specs/2026-11-10-motion-scenario-expansion-design.md` | Earlier simulation coverage work records retained from the existing worktree. |
| `docs/superpowers/plans/2026-11-17-rp2350-production-readiness.md` | Current production readiness execution plan. |

`eskf15.hpp` is unchanged by the range-profile change. The existing fault latch, explicit reset/re-alignment behavior, and stale-output suppression remain in place.

## Evidence inventory

| Evidence | Result | Provenance and limit |
|---|---|---|
| Bundle A, B, C host checks | Pass, including sanitizer variants. | Run in WSL with GNU g++ 11.4.0 and CMake 3.22.1 against the dirty working tree. They are host software checks, not physical qualification. Bundle C now runs `tests/test_lsm6ds3_config.cpp`. |
| Bundle C range-profile regression | Pass in normal and sanitizer configurations. | Checks register profile, conversion scales, matching ESKF limits, and distinct BROAD profile limits. |
| Exact candidate CI run [`44130832213`](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/44130832213) | Pass on SHA `38403245e71a7eee987f8779b61f7a38bc779ac4`: `host-tests` and `pico2-cross-build`. | Host job passed Bundles A/B/C, protocol validation, and sanitizer checks. Pico SDK 2.2.0 built the standard direct-register, experimental FIFO, and binary-log/FIFO variants and uploaded ELF/UF2/map/resource artifacts. This is cross-build evidence, not on-device qualification. |
| Candidate firmware artifact archive | 2,306,990 bytes; SHA-256 `a5592062f5af92be7ef986c17ad04092153f16bb1c4db2e3bfb2000734fd4a20`. | GitHub artifact `rp2350-pico2-firmware`, run `44130832213`, expires 2027-02-15. Downloaded and hashed its UF2 and resource reports locally. |
| Historical CI run [`44055946078`](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/44055946078) | Pass on starting revision `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973`. | The earlier Pico SDK 2.2.0 host and target passes remain attributed to their historical source revision. |
| Local Pico target build | Not run. | `PICO_SDK_PATH`, Ninja, and the Arm cross compiler are unavailable in this session's local build environment; CI validated the candidate instead. |
| B9 matched-interval BROAD atlas | Manifest status `PASS`; 39 paired BROAD trials have identical valid ESKF/VQF masks. VQF tilt RMS is lower on all 39 trials (reported means about 0.69° versus 4.27° with BROAD-specific range limits). | [`B9_REFERENCE_BASELINE.md`](../../remediation/analysis/b9_reference_baseline/B9_REFERENCE_BASELINE.md); manifest binds it to the broad atlas and synthetic weakness source artifacts. This does not establish a universal estimator winner or a product limit. |
| Synthetic estimator weaknesses | Existing report covers maneuver, timing jitter, and compound motion with state/covariance/update diagnostics. | [`PR3_SYNTHETIC_WEAKNESSES_B9.md`](../../remediation/analysis/pr3_synthetic_weaknesses_b9/PR3_SYNTHETIC_WEAKNESSES_B9.md). Synthetic-only evidence; product acceptance limits are absent. |
| Gravity-aiding policy candidate | Rejected: held-out mean paired tilt RMS regressed by 1.399° (95% interval +1.264° to +1.533°); maneuver, timing-jitter and stop/start include regressions. | [`PR3_GRAVITY_GATE_ABLATIONS.md`](../../remediation/analysis/pr3_gravity_gate_ablations/PR3_GRAVITY_GATE_ABLATIONS.md) and [`PR3_GRAVITY_GATE_BROAD_VALIDATION.md`](../../remediation/analysis/pr3_gravity_gate_ablations/PR3_GRAVITY_GATE_BROAD_VALIDATION.md). Keep the existing conservative gate. |
| Fault lifecycle | Host lifecycle evidence passes; fault latch and stale-output protections are retained. | Candidate settings did not add faults or stale output in the documented tests. Device fault injection remains outstanding. |

The B9 reference manifest reports `PASS` and binds its results to the baseline commit above and to the BROAD and synthetic evidence manifests. The gravity-gate manifest reports `PASS` for 44 diagnostic results and binds its run artifacts to the same baseline lock. These manifests establish artifact integrity, not product acceptance.

Candidate target build outputs (all from SHA `38403245e71a7eee987f8779b61f7a38bc779ac4`):

| Variant | Flash image bytes | Static RAM data + bss bytes | Largest single frame | UF2 SHA-256 | Resource report SHA-256 |
|---|---:|---:|---:|---|---|
| Direct register | 88,148 | 36,196 | 9,496 B (`Eskf15::predict`) | `f30da406770a4b7257ef25fb2eaa729ed2360e9c471ba00f8bb19f541dd55c08` | `dcc4f2202dc1b25816033cb1b1e8235b7e5fae40bdf1a407445fd8352150bf46` |
| FIFO | 90,780 | 36,160 | 9,496 B (`Eskf15::predict`) | `80f0da09ef123215b6c895a1b3c749ca1267b10eceac95d784faa875fc3c0b79` | `5f47b7d0d7a05de171525f328f37b6adbb2d05b5c32afd5cd807920d4437343f` |
| Binary log + FIFO | 80,584 | 36,164 | 9,496 B (`Eskf15::predict`) | `c6c4d6353d582c48eb4b21c4dbbc6db2f253523bdd401c8f574562ceb52eba43` | `aefd8f8801df572b1393d255725a1aed4f2f3cacf9ef2ac921b2c5428d66616a` |

The frame values are compiler per-function estimates; they do not measure whole-call-chain stack use or device high-water. The target reports leave that qualification open.

The repository's Windows Git configuration enables automatic CRLF conversion. `.gitattributes` now keeps the hash-manifested B9/gravity-gate report trees at LF and compressed `.gz` traces byte-preserved so a checkout does not invalidate their recorded SHA-256 values.

## Current gate map

| Gate | Status | Owner / remaining evidence |
|---|---|---|
| Product limits and use boundary | `OPEN` | Product owner: confirm exact consumer/use environment and approve numeric accuracy, freshness, motion/range, startup/recovery, temperature, uptime, and resource/deadline limits. |
| Candidate source and CI | `PASS` for source/build checks on the engineering baseline; release traceability remains `OPEN`. | Firmware owner: SHA `38403245e71a7eee987f8779b61f7a38bc779ac4` passed local host/sanitizer runs and pinned target CI. Product/evidence acceptance, calibration, and device measurements remain open. |
| Estimator selection | `OPEN` | The matched BROAD atlas reports lower VQF tilt RMS on all 39 trials; synthetic evidence shows VQF weaknesses under stationary gyro bias and lateral acceleration. The full comparison for product limits, fresh held-out seeds, full attitude p95/maximum, and availability is not complete. Product/estimator owners must approve the acceptance matrix before selecting or promoting an algorithm. |
| Calibration and exact sensor identity | `OPEN` | Hardware/calibration owner: verify the board and original sensor, collect calibration and uncertainty over the use envelope, and assign a validated nonzero calibration ID. Current identity calibration ID is 0. |
| Acquisition and timestamps | `BLOCKED_HARDWARE` | Hardware owner: physical DRDY/SPI/DMA/FIFO captures and loss/uncertainty analysis on the production board and sensor. FIFO remains disabled by default. |
| On-device timing, memory margin and soak | `BLOCKED_HARDWARE` | Firmware/hardware owner: measured end-to-end age, fusion latency, stack high-water, queue margin, missed deadlines, and temperature-aware soak against approved limits. |
| Fault/reset/stale behavior | `OPEN` host; `BLOCKED_HARDWARE` device | Firmware owner: keep host regressions and protections; repeat fault injection on the exact device and verify consumer-visible health/freshness/reset behavior. |
| Independent review and release package | `OPEN` | Named independent reviewer and release owner; source review, traceability, provenance, calibration/configuration identity, update/rollback and sign-offs. |
| Stage 2 system safety | `OPEN` if actuator/control use applies | System owner: hazard analysis, safe-state behavior, end-to-end deadline and system fault evidence. Otherwise formally document Stage 2 as not applicable to the delivered sensor module. |

## Historical status reconciliation

Older `remediation/ROOT_CAUSES.md`, `PR2_RESULTS.md`, `PR3_STATUS.md`, and `PR4C_STATUS.md` are retained as dated investigation records. Their statements describe their own evaluation stage and should not be edited to imply this candidate was tested. In particular, a statement that a target cross-build had not yet run in an earlier PR remains historically true for that snapshot; run `44130832213` proves the engineering baseline built later. The analytical manifests remain bound to their recorded baseline revision `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973` and are not retroactively attributed to `38403245e71a7eee987f8779b61f7a38bc779ac4`.

## Freeze decision

Commit `38403245e71a7eee987f8779b61f7a38bc779ac4` is the source/evidence baseline for the next engineering milestone: the range-profile implementation and its regression are reviewed, host and sanitizer suites pass, and pinned target CI passed on the exact commit. It is not a production release baseline or estimator selection. No release tag is declared while Task 1 limits, calibration, hardware, and independent-review gates remain open.
