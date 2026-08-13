# Pendulum-inspired optimization for DA-DAKA

## Scope

This layer is intentionally **outside the flight-control path**. It must not send
MAVLink, MAVROS setpoints, PX4 mode changes, Arm/Takeoff, or spray commands.
`mission_manager`, `distance_controller`, PX4 failsafes, and QGroundControl
priority remain unchanged.

The current laptop-AI branch already creates the two resource stages needed by
Pendulum: Pi-to-laptop video streaming is the network stage, and laptop detector
inference is the compute stage. The new code adds a safe optimization control
plane around those stages without coupling it to flight safety.

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

## Safety and integrity rules

1. Optimization is disabled by default.
2. Example accuracy values are deliberately `0.0`; they are not field data and
   cannot satisfy the default minimum-accuracy requirement.
3. `observe` mode only produces a recommendation/log. It does not reconfigure
   the stream or detector.
4. `apply` mode may only be connected to AI/encoder adapters after bench tests.
   It still must not be connected to PX4/MAVROS or Mission Manager mode changes.
5. Simultaneous network+compute bottlenecks return an explicit best-effort
   decision; the optimizer does not claim an accuracy guarantee in that state.
6. Detector-model accuracy and bitrate profiles must be measured on the actual
   dirt dataset and acrylic/solar-panel scene conditions before live use.

## Profiling workflow

For each candidate encoder bitrate and detector model/input size, record at
minimum:

- usable stream bitrate in Mbps;
- detector inference median and p95 in ms;
- end-to-end capture-to-result latency;
- dirt detection accuracy metric on a fixed validation set;
- scene category (static/good light, motion, glare/poor light).

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

The branch documents but does not yet contain the Raspberry Pi camera stream
producer/encoder control endpoint. Because of that, this change does **not**
pretend to alter H.264 bitrate at runtime. The scheduler output includes an
`encoder_profile` identifier so the future single stream producer can implement
that adapter without changing the optimizer or flight-control packages.

Likewise, model switching should be wired through a laptop-only detector pool
after the real ONNX model set exists. The optimizer already carries detector
backend, model path, and input dimensions in each demand point, but observe mode
keeps the current detector untouched.
