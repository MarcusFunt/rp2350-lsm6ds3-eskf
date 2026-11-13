# B5: Official pretrained RIANN causal 6D fidelity

## Pinned reference and data exposure

This host-only adapter uses the official
[`daniel-om-weber/riann` release `v0.2.0`](https://github.com/daniel-om-weber/riann/tree/v0.2.0),
source commit `7639f1ed2e1d48e6ed34e340ce0a6eed6e1bafa3`, under Apache-2.0.
The pinned PyPI wheel is `riann-0.2.0-py3-none-any.whl`, SHA-256
`e7292f567630ce3b30c031c49dde9c9d1e98769efc6d513cdeb52b243743022d`. Its
packaged `riann/riann.onnx` is 1,471,345 bytes with SHA-256
`9a38dc4c40dd6c31ef12558337e7affa5382476bbd594fdea3c347f10a67f3d8`. The
adapter verifies the installed inference source files and model bytes before
creating the session. It passes an explicit packaged model path because the
upstream no-argument constructor can fall back to working-directory paths when
installed outside the source checkout.

The runtime lock is CPython 3.11.4, NumPy 2.3.2 and ONNX Runtime 1.22.1, with
all Python dependency versions pinned in
[`requirements-riann-b5-win-cp311.lock.txt`](../../external_benchmarks/references/requirements-riann-b5-win-cp311.lock.txt).
Inference uses only `CPUExecutionProvider`, sequential execution, one intra-op
and inter-op thread, deterministic compute, and `ORT_ENABLE_ALL` graph
optimization. The complete artifact and API provenance is in
[`riann_b5_provenance_lock.json`](../../external_benchmarks/references/riann_b5_provenance_lock.json).

The adapter calls the official `RIANN.predict_step` once per sample with
accelerometer in m/s² specific force and gyro in rad/s. It passes a configured
uniform sample rate from 50 through 500 Hz; the model receives `dt=1/fs` on each
step. The allowed range follows the paper's evaluated time-aware-network
training range. Input trials use the B1 canonical body and ENU frame. Output is
the model's raw scalar-first quaternion, without per-trial truth alignment or
renormalization. The synthetic gravity test confirms that it rotates measured
body-frame specific force toward ENU up. No magnetic or independent heading
input is used, so yaw remains startup-gauge relative.

The official GRU hidden state has shape `(2,1,1,200)` and starts at zero.
`predict_step` carries that state between calls; `reset_state()` restores zeros.
The official `predict()` path processes a whole sequence from reset state and
restores any pre-existing streaming state afterward. Stateful chunks can carry
the same hidden state by disabling reset on subsequent chunks.

The pretrained model's exposure is represented as
`training_exposure=BROAD_USED_IN_DEVELOPMENT` on each B5 result envelope and
sequence summary. The original [RIANN paper](https://doi.org/10.3390/ai2030028)
states that BROAD and TUM-VI were used for training and hyperparameter
optimization. Any future BROAD result is useful as a same-data reference, not
as RIANN's unseen-data generalization score. This step does not score BROAD or
claim any external performance.

## Synthetic parity and state results

The smoke run processed seven 100 Hz sequences (3,550 samples total):
stationary, yaw-only, 35° tilted stationary, tilted world-yaw, constant rate,
slowly varying rate, and acceleration pulse. Every per-sequence record in
[`riann_b5_smoke.json`](riann_b5_smoke.json) carries the training exposure,
source artifact hash, canonical input hash, config hash, sample count, and
same-trial batch-input assertion.

| Synthetic sequence | Samples | Max batch/stream geodesic difference (rad) | Max norm deviation | Signed jumps |
|---|---:|---:|---:|---:|
| Stationary | 300 | `8.60e-7` | `2.22e-16` | 0 |
| Yaw-only | 300 | `5.10e-7` | `3.33e-16` | 0 |
| Tilted stationary, 35° | 1,000 | `5.57e-7` | `2.22e-16` | 0 |
| Tilted world-yaw | 800 | `6.33e-7` | `2.22e-16` | 0 |
| Constant rotation | 400 | `6.71e-7` | `2.22e-16` | 0 |
| Slowly varying rate | 500 | `1.27e-6` | `2.22e-16` | 0 |
| Acceleration pulse | 250 | `1.68e-6` | `2.22e-16` | 0 |

The adapter's streaming samples matched the official `predict_step` output
componentwise in the differential test. The largest full-sequence `predict()`
versus streaming difference was `1.6811e-6 rad` (`8.3931e-7` maximum component
difference), consistent with float32 execution-order variation. Maximum
quaternion norm deviation was `3.33e-16` when evaluated in float64; no signed
quaternion jumps occurred in these fixtures. The tilted stationary sequence
ended with gravity-axis error `0.001517 rad` (`0.0869°`). These are synthetic
functional checks, not accuracy claims on recorded data.

Chunking a 900-sample stream into 211/369/320-sample stateful calls matched the
single streaming run exactly (`0` component difference). A separate 211-sample
prefix also matched the first 211 outputs of the full sequence exactly, which
checks causal behavior. Resetting and replaying the same trial was
componentwise exact; inserting a different trial before reset produced the
same target output. Repeated CPU inference after reset was deterministic in
this pinned run (`0` output difference).

## Desktop CPU timing

On Windows 10 build 26200, Intel64 family/model 6/183, the measured streaming
path took median `54.2 µs` per sample, P95 `62.7 µs`, and maximum `146.1 µs`
over 1,500 timed calls after a 100-sample warm-up. Batch `predict()` had median
`21.23 ms` for 1,500 samples (`14.15 µs/sample`) over five runs. Adapter
initialization, including two ONNX session constructions (upstream class
constructor plus explicit CPU session), measured `9.10 ms`; separate batch
session initialization measured `12.10 ms`. These are host Python/ORT timings,
not RP2350 latency. Peak process memory and MCU feasibility were not measured.

## Reproduction commands

```bash
python -m venv .venv-riann-b5
# Activate the environment using the platform's normal command, then:
python -m pip install -r external_benchmarks/references/requirements-riann-b5-win-cp311.lock.txt
python -m unittest tests.test_riann_pretrained_6d_adapter -v
python -m unittest tests.test_external_benchmark_contract tests.test_external_benchmark_metrics tests.test_riann_pretrained_6d_adapter -v
python scripts/run_riann_b5_smoke.py --output docs/external_benchmarks/riann_b5_smoke.json
```

The environment and model lock are for Windows x86-64 CPython 3.11.4. Other
platforms, other inference runtimes, BROAD performance, and hardware execution
remain unvalidated. No retraining, model conversion, or RP2350 port was done.
