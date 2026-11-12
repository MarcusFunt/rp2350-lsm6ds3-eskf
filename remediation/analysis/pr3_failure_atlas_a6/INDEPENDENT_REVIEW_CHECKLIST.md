# A6 independent review checklist

- [ ] Confirm PR3 v5 protocol, archive, archive manifest, filter header and evaluator source hashes against the manifest.
- [ ] Confirm this is the development split and the selected trace seed is 4001; no held-out or final-confirmation rows are used.
- [ ] Reproduce one selected raw stream and confirm its SHA-256 matches the frozen archive row.
- [ ] Confirm the 1 s tilt-rise window and longest gravity-correction gap are indexed by the trace's physical/nominal timestamps as documented.
- [ ] Review the 0.01 rad/s and 0.05 m/s² motion-regime thresholds; they are descriptive bins, not estimator gates.
- [ ] Treat projected tilt sigma and observable-plane NEES as model diagnostics; positive definiteness does not establish calibrated uncertainty.
- [ ] Keep absolute yaw claims out of the six-axis IMU-only summary; slow-yaw is reported relative to the simulator's shared startup gauge.
- [ ] Check that gravity updates are the only runtime correction type enabled by this profile; heading and zero-rate counts are zero by configuration.
- [ ] Review lateral-acceleration and vibration classifications against protocol v5's declared synthetic motion and disturbance definitions.
- [ ] Do not tune ESKF noise or gates from these exposed development data; use the findings to preregister isolated PR-C/D/E experiments.
- [ ] Hardware accuracy, sensor transfer, runtime, and stack remain unverified.
