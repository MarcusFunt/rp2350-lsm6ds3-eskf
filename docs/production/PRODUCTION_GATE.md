# RP2350 Production Gate

Status: **OPEN**. This gate governs the two-stage release scope: estimator module first, then any downstream system that uses its output.

## Stage 1 — estimator module

The module may pass only when every applicable criterion has a named owner, a numeric or testable acceptance rule, and evidence tied to the release source SHA.

| Gate | Pass evidence | Current status |
|---|---|---|
| Product requirements | Approved use boundary, sensor/operating envelope, orientation and freshness limits, recovery expectations, temperature, uptime, and resource budgets. | `OPEN`; see [product requirements](PRODUCT_REQUIREMENTS.md). |
| Source and evidence baseline | Worktree changes attributed; current source and benchmark evidence reconciled; candidate passes required host and target checks. | `PASS` for engineering baseline `03b9c92a4ac0216619bdb10d0e208e02875964e4`; production traceability/package remains `OPEN`. See [evidence ledger](EVIDENCE_LEDGER.md). |
| Estimator selection | Predeclared paired comparison across full synthetic scenarios, fresh held-out seeds, all BROAD trials, and fault cases; every product-critical scenario meets the accepted limits. | `OPEN`; VQF wins BROAD tilt comparison but has known synthetic bias/lateral weaknesses; no universal selection is established. |
| Estimator software | Production-enabled algorithm modes have no unresolved correctness defects; covariance/health/observability claims match implementation; independent review findings are closed or scoped. | `OPEN`; PR2/PR3 accuracy/consistency and independent-review gates remain open. |
| Calibration and sensor profile | Exact device identity and register profile verified; measured bias, scale, axis, thermal, and noise model versioned; nonzero calibration ID used. | `OPEN`; firmware currently uses identity calibration and ID 0. |
| Acquisition integrity | Physical DRDY/SPI/DMA/FIFO captures show no unaccounted duplicate/reorder/drop; all resets, discards, and overruns are visible; timestamp uncertainty is bounded. | `BLOCKED_HARDWARE`; no physical capture recorded. |
| Target resources and timing | Current release SHA builds with pinned SDK/toolchain; device timing, end-to-end age, stack high-water, queue margins, and soak results meet approved limits. | `BLOCKED_HARDWARE`; historical cross-builds passed, but on-device values are absent. |
| Fault and stale-output handling | Host and device injection verifies latching, explicit reset/re-alignment, and immediate stale-output suppression for each required fault. | Host lifecycle evidence exists; device verification is `BLOCKED_HARDWARE`. Keep current protections. |
| Release review/package | Independent source/evidence review, requirements traceability, exact firmware/calibration/configuration hashes, update/rollback and recovery instructions, owner sign-offs. | `OPEN`; reviewer and release package not established. |

## Stage 2 — controller/actuator system

Stage 2 is required whenever estimator output affects an actuator or control decision. It cannot pass based on this repository's module tests alone. It requires, at minimum:

- System hazard analysis and approved safe behavior for invalid, stale, degraded, or reset-required estimates.
- End-to-end deadline and age budgets including acquisition, fusion, transport, controller scheduling, and actuator response.
- Tests showing each estimator fault produces the approved controller transition, with no reuse of stale orientation.
- System-level ground-truth and fault-injection evidence under the intended operating envelope.
- Independent approval from the system safety/quality owner.

If Stage 1 firmware is only a sensor module with no controller consumer, record that boundary and Stage 2 as out of scope for the module release; do not imply system safety approval.

## Gate decision rule

- `PASS`: every applicable Stage 1 criterion has current evidence tied to the release SHA and required approvals; Stage 2 is passed or explicitly not applicable to the delivered module.
- `OPEN`: work remains, a limit/owner is missing, or evidence is incomplete.
- `BLOCKED_HARDWARE`: the evidence requires a physical board/sensor or external reference that is unavailable.
- A historical CI pass, host replay, synthetic data set, or external benchmark cannot substitute for a physical timing/calibration/accuracy result.
