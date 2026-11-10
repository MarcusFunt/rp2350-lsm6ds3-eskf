# Historical Bundle B v1 evidence

These CSV, JSON, and Markdown files preserve the results checked in before the metric-definition correction. In v1, `tilt_rms_deg` measured the angle between the estimated and true body-Z axes expressed in the world frame. That value can include world-yaw disagreement and is not the v2 inclination metric. Do not compare v1 and v2 tilt RMS values as if they had the same definition.

The v1 sensor model and six-scenario results are retained as historical synthetic evidence only; they are not measured RP2350/LSM6DS3 accuracy. The v2 simulator also advances time-varying truth with midpoint angular rates rather than the v1 sample-end rate, so accelerometer samples can differ in rotating scenarios. The original Gaussian draw sequences are checked against the compiler-specific hash fixture in this directory; matching noise draws do not make v1 and v2 result rows directly comparable.
