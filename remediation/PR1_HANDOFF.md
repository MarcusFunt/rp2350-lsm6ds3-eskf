# PR 1 handoff

## Gate status

- **Technical gate:** `TEST_GATE_PASS` for the A/B/C host and sanitizer suites, the frozen protocol-v2 artifact validator, and a clean-clone run of the new Bundle A/B regressions. The PR 1 branch ARM cross-build is `NOT_RUN`; only pinned baseline commit `c397fec` has cross-build CI evidence.
- **Review state:** Independent internal review complete with no blocking findings. No external PR review is available because the branch has not been published.
- **Remote state:** local branch only; no push, draft PR, or merge was performed.
- **Next dependency:** any later milestone must branch from the final reviewed PR 1 head reported by `git rev-parse HEAD`, not from `origin/main`, while PR 1 remains unmerged.

## Included in this first step

- Corrected the yaw-invariant tilt evaluator and versioned output as protocol v2.
- Added tests for the relative world-yaw tilt oracle and for rejecting protocol-v1 summaries.
- Froze a 4-scenario, 292-stream benchmark with disjoint 16-seed development and held-out sets, shared raw IMU inputs, representative traces, and hash-pinned provenance.
- Replayed 97 selected frozen streams through the pre-Bundle-B default core: the clean 0.2 g regression plus all noisy pure-roll development and held-out streams.
- Preserved the older protocol-v1 CSV/JSON hashes and classified the eight unprovenanced SVG figures as `HISTORICAL_UNREPRODUCED`.
- Added baseline, reproduction, issue, resource and evidence records under `remediation/`.

## Open investigations for later work

1. Trace legacy lateral-acceleration gravity gating, fictitious gyro-bias learning, and recovery rejection with per-sample residual/covariance evidence.
2. Define health and control-suitability semantics for large state error despite `Nominal` software status.
3. Diagnose pure-roll yaw tails and the synthetic trusted-heading result that worsens yaw/tilt; preserve the current held-out set and use untouched confirmation seeds after any held-out-informed tuning.
4. Recover original SVG source data if available; otherwise keep those plots historical and unreproduced.
5. Cross-build the PR 1 branch with the pinned Pico SDK and capture all variant size/stack evidence; perform actual latency, acquisition, and stack-high-water qualification only when hardware is available.

This handoff describes PR 1 only. It is not a statement that the full remediation program or physical validation is complete.
