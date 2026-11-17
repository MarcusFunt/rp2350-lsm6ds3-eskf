# Production Readiness Evidence Ledger

Status: **candidate not frozen**. This ledger separates checked-in historical evidence, current working-tree checks, and missing physical qualification. It is not a production approval.

## Source and worktree identity

| Item | Record |
|---|---|
| Repository | `MarcusFunt/rp2350-lsm6ds3-eskf` |
| Starting revision for this execution | `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973` on `main` |
| Candidate source SHA | Not assigned; current worktree has required, uncommitted changes. Record the commit and CI run only after committing and validating the complete candidate. |
| Release tag | None; do not tag while requirements and hardware gates are open. |
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
| Existing CI run [`44055946078`](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/44055946078) | Pass: `host-tests` and `pico2-cross-build`. | Exact head was starting revision `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973`, not this dirty candidate. Pico SDK 2.2.0 target job built the standard Pico 2 image and experimental FIFO path. This is historical build evidence only. |
| Local Pico target build | Not run. | `PICO_SDK_PATH`, Ninja, and the Arm cross compiler are unavailable in this session's local build environment. CI must validate the committed candidate. |
| B9 matched-interval BROAD atlas | Manifest status `PASS`; 39 paired BROAD trials have identical valid ESKF/VQF masks. VQF tilt RMS is lower on all 39 trials (reported means about 0.69° versus 4.27° with BROAD-specific range limits). | [`B9_REFERENCE_BASELINE.md`](../../remediation/analysis/b9_reference_baseline/B9_REFERENCE_BASELINE.md); manifest binds it to the broad atlas and synthetic weakness source artifacts. This does not establish a universal estimator winner or a product limit. |
| Synthetic estimator weaknesses | Existing report covers maneuver, timing jitter, and compound motion with state/covariance/update diagnostics. | [`PR3_SYNTHETIC_WEAKNESSES_B9.md`](../../remediation/analysis/pr3_synthetic_weaknesses_b9/PR3_SYNTHETIC_WEAKNESSES_B9.md). Synthetic-only evidence; product acceptance limits are absent. |
| Gravity-aiding policy candidate | Rejected: held-out mean paired tilt RMS regressed by 1.399° (95% interval +1.264° to +1.533°); maneuver, timing-jitter and stop/start include regressions. | [`PR3_GRAVITY_GATE_ABLATIONS.md`](../../remediation/analysis/pr3_gravity_gate_ablations/PR3_GRAVITY_GATE_ABLATIONS.md) and [`PR3_GRAVITY_GATE_BROAD_VALIDATION.md`](../../remediation/analysis/pr3_gravity_gate_ablations/PR3_GRAVITY_GATE_BROAD_VALIDATION.md). Keep the existing conservative gate. |
| Fault lifecycle | Host lifecycle evidence passes; fault latch and stale-output protections are retained. | Candidate settings did not add faults or stale output in the documented tests. Device fault injection remains outstanding. |

The B9 reference manifest reports `PASS` and binds its results to the baseline commit above and to the BROAD and synthetic evidence manifests. The gravity-gate manifest reports `PASS` for 44 diagnostic results and binds its run artifacts to the same baseline lock. These manifests establish artifact integrity, not product acceptance.

The repository's Windows Git configuration enables automatic CRLF conversion. `.gitattributes` now keeps the hash-manifested B9/gravity-gate report trees at LF and compressed `.gz` traces byte-preserved so a checkout does not invalidate their recorded SHA-256 values.

## Current gate map

| Gate | Status | Owner / remaining evidence |
|---|---|---|
| Product limits and use boundary | `OPEN` | Product owner: confirm exact consumer/use environment and approve numeric accuracy, freshness, motion/range, startup/recovery, temperature, uptime, and resource/deadline limits. |
| Candidate source and CI | `OPEN` | Firmware owner: commit the reviewed working tree, run host/sanitizer and pinned target CI on that source, then record the resulting SHA and artifacts. |
| Estimator selection | `OPEN` | Product/estimator owners: compare candidates on predeclared limits, including fresh held-out seeds and availability; current evidence has no universal winner. |
| Calibration and exact sensor identity | `OPEN` | Hardware/calibration owner: verify the board and original sensor, collect calibration and uncertainty over the use envelope, and assign a validated nonzero calibration ID. Current identity calibration ID is 0. |
| Acquisition and timestamps | `BLOCKED_HARDWARE` | Hardware owner: physical DRDY/SPI/DMA/FIFO captures and loss/uncertainty analysis on the production board and sensor. FIFO remains disabled by default. |
| On-device timing, memory margin and soak | `BLOCKED_HARDWARE` | Firmware/hardware owner: measured end-to-end age, fusion latency, stack high-water, queue margin, missed deadlines, and temperature-aware soak against approved limits. |
| Fault/reset/stale behavior | `OPEN` host; `BLOCKED_HARDWARE` device | Firmware owner: keep host regressions and protections; repeat fault injection on the exact device and verify consumer-visible health/freshness/reset behavior. |
| Independent review and release package | `OPEN` | Named independent reviewer and release owner; source review, traceability, provenance, calibration/configuration identity, update/rollback and sign-offs. |
| Stage 2 system safety | `OPEN` if actuator/control use applies | System owner: hazard analysis, safe-state behavior, end-to-end deadline and system fault evidence. Otherwise formally document Stage 2 as not applicable to the delivered sensor module. |

## Historical status reconciliation

Older `remediation/ROOT_CAUSES.md`, `PR2_RESULTS.md`, `PR3_STATUS.md`, and `PR4C_STATUS.md` are retained as dated investigation records. Their statements describe their own evaluation stage and should not be edited to imply this candidate was tested. In particular, a statement that a target cross-build had not yet run in an earlier PR remains historically true for that snapshot; the later CI run above proves a subsequent parent revision built, but says nothing about the uncommitted candidate.

## Freeze decision

No release baseline commit/tag is declared here. The range-profile implementation has host regression coverage, but Task 1 numeric limits are still open and current-source target CI has not run. After a reviewed candidate commit and successful CI, record its exact SHA and workflow URL above; a baseline tag remains inappropriate until the product and physical gates are resolved.
