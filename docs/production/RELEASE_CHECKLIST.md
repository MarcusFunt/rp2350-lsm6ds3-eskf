# Estimator Module Release Checklist

This is a release handoff template for the two-stage scope. Current decision: **NOT READY**. It does not replace the [product requirements](PRODUCT_REQUIREMENTS.md), [production gate](PRODUCTION_GATE.md), or [evidence ledger](EVIDENCE_LEDGER.md).

## Stage 1 — estimator module

### Product requirements and algorithm

- [ ] Named product owner approves the module use boundary and operating envelope.
- [ ] Numeric limits are approved for sample rate/jitter, tilt RMS/p95/maximum, output age, startup/recovery, temperature, uptime, and resource/deadline margins.
- [ ] Heading claim matches observability; absolute yaw is excluded unless an independent aid is specified.
- [ ] Estimator comparison is predeclared and paired across all required scenarios, held-out seeds, BROAD trials, and fault cases; every critical scenario meets its limit.
- [ ] Chosen estimator, version/license, health semantics, calibration requirements, and output contract are recorded.
- [ ] Independent estimator and implementation review is signed; every finding is closed or explicitly accepted with rationale.

### Sensor, firmware and evidence

- [ ] Exact Pico 2 board revision and original LSM6DS3 variant are recorded and physically verified.
- [ ] Versioned calibration is measured over the approved temperature/use envelope; calibration ID is nonzero only for validated values.
- [ ] Register readback, ODR/full-scale, axis mapping, raw conversion and per-axis fault thresholds match the approved sensor configuration.
- [ ] Release SHA passes host, sanitizer, pinned Pico SDK 2.2.0 target builds, and all required diagnostic/FIFO variants.
- [ ] Physical acquisition captures account for every missed edge, discard, duplicate, reorder, queue drop, FIFO reset and overrun; timestamp uncertainty is bounded.
- [ ] Device measurements of fusion latency, end-to-end sample age, stack high-water, queue margin, missed deadlines and soak behavior meet approved limits.
- [ ] On-device fault injection verifies latch, stale suppression, explicit reset, re-alignment, and consumer-visible health/freshness behavior.
- [ ] Release manifest contains source SHA, SDK/compiler, build flags, firmware hashes, board/sensor revision, calibration ID, configuration, test/capture evidence and known limitations.
- [ ] Update, rollback, service and recovery instructions are reproducible by another engineer.
- [ ] Product owner, firmware owner, hardware/calibration owner, and independent reviewer sign the gate decision.

## Stage 2 — controller or actuator system

Complete this additional gate whenever estimator output affects a control decision or actuator:

- [ ] System owner approves hazard analysis and safe response for invalid, stale, degraded, and reset-required estimates.
- [ ] End-to-end deadlines include acquisition, fusion, transport, scheduling and actuator response.
- [ ] System fault tests show stale or invalid estimates cannot be reused and the controller reaches the approved safe state.
- [ ] Ground-truth and fault-injection evidence covers the complete intended system envelope.
- [ ] Independent system safety/quality owner signs the system gate.

If Stage 2 does not apply to the delivered module, document the module boundary and obtain product-owner approval for that exclusion. Stage 1 passing alone does not approve an actuator system.
