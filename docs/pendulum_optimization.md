# Pendulum-inspired optimization for DA-DAKA

## Scope

This layer is intentionally **outside the flight-control and spray-decision path**.
It must not send MAVLink, MAVROS setpoints, PX4 mode changes, Arm/Takeoff, or spray
commands. Its job is only to choose an efficient video/AI profile while preserving
the same downstream target-coordinate contract.

The cleaning control path is documented separately in
`docs/e2e_cleaning_pipeline.md`:

```text
panel detection -> dirt detection -> normalized target coordinate
-> Pi visual servo -> LiDAR distance control -> stop verification -> spray request
```

Pendulum may change bitrate/model settings used before the coordinate is produced,
but the Pi control nodes do not depend on Pendulum internals.

## Mapping from Pendulum to DA-DAKA

| Pendulum | DA-DAKA |
|---|---|
| Video bitrate | Pi encoder/stream profile bitrate |
| DNN complexity | ONNX detector/model/input profile |
| Network budget | usable Pi -> laptop video bandwidth |
| Compute budget | inference milliseconds available per frame |
| Accuracy requirement | profiled dirt-detection metric threshold |
| Demand curve | measured `{bitrate, inference_ms, accuracy}` profiles |
| Scheduler | `JointScheduler` |
| Scene-change trigger | `SceneChangeDetector` |

DA-DAKA currently has one video stream. Pendulum's multi-user max-cost-gradient
allocator is therefore unnecessary at this stage: selecting a cost-efficient
point on the single stream's Pareto frontier gives the intended trade-off with
less state and lower integration risk.

## Deployed compute target

The laptop inference target is Linux + NVIDIA GeForce RTX 5060 class hardware.
The production-oriented configuration is `laptop_ai/config/linux_rtx5060.yaml`,
documented in `docs/linux_rtx5060_gpu.md`.

The scheduler must not infer compute cost from GPU marketing specifications. Each
detector profile's `inference_ms` is measured on the deployed laptop using its
actual CUDA/TensorRT provider, FP16 model, preprocessing path, and warm cache. This
keeps the demand curve tied to the real system.

## Files

- `laptop_ai/laptop_ai/joint_optimizer.py`: demand points, Pareto frontier,
  network/compute budget selection, hysteresis, best-effort fallback.
- `laptop_ai/laptop_ai/scene_change.py`: low-overhead motion, histogram, and
  detection-centroid drift signal for re-evaluation.
- `laptop_ai/laptop_ai/optimizer_runtime.py`: rate-limited runtime state. Default
  mode is observe-only.
- `laptop_ai/laptop_ai/optimizer_cli.py`: evaluate a profiled curve without
  starting video inference.
- `laptop_ai/config/pendulum_optimization.yaml`: disabled example configuration.
- `laptop_ai/config/linux_rtx5060.yaml`: Linux NVIDIA production inference profile.

## Safety and integrity rules

1. Optimization is disabled by default.
2. Example accuracy values are deliberately `0.0`; they are not field data and
   cannot satisfy the default minimum-accuracy requirement.
3. `observe` mode only produces a recommendation/log. It does not reconfigure the
   stream or detector.
4. `apply` mode may only be connected to AI/encoder adapters after bench tests.
5. The optimizer must never connect to Pixhawk/MAVROS, Mission Manager state
   transitions, visual-servo velocity output, or the spray service.
6. Simultaneous network+compute bottlenecks return an explicit best-effort
   decision; the optimizer does not claim an accuracy guarantee in that state.
7. Detector-model accuracy and bitrate profiles must be measured on the actual
   dirt dataset and panel scene conditions before live use.
8. The RTX production profile uses `require_gpu: true`; loss of the CUDA provider
   is a startup failure instead of a silent CPU fallback.

## Profiling workflow

For each candidate encoder bitrate and detector model/input size, record at
minimum:

- usable stream bitrate in Mbps;
- detector inference median and p95 in ms;
- end-to-end capture-to-result latency;
- dirt detection accuracy metric on a fixed validation set;
- scene category (static/good light, motion, glare/poor light);
- execution provider and precision (for example CUDA FP16).

Only measured accuracy-satisfying points should be placed in the runtime demand
curve. Dominated points are removed automatically by `pareto_frontier()`.

Example dry evaluation:

```bash
cd laptop_ai
python -m laptop_ai.optimizer_cli \
  --config config/pendulum_optimization.yaml \
  --bandwidth-mbps 5 \
  --compute-ms 20
```

## What is deliberately not connected yet

The branch does not yet contain a Raspberry Pi runtime encoder-control endpoint,
so the optimizer does not pretend to alter H.264 bitrate live. The scheduler
output carries an `encoder_profile` identifier for a future adapter.

Likewise, live light/medium/heavy model switching should be added only after the
real ONNX model set has been validated. Neither future adapter should change the
E2E control contract: the control side continues to receive only validated target
coordinates and freshness metadata.
