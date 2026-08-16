# Branch consolidation record

The autonomous mission is consolidated on `main` through
`codex/autonomous-cleaning-mission`. Branches are removed only after the PR is
merged and the resulting `main` revision is verified.

| Source branch (audited tip) | Consolidated result |
|---|---|
| `agent/harden-distance-flight-safety` (`4d74a8e`) | Already an ancestor of the original `main`; retained in the current distance/mission safety code. |
| `agent/jazzy-tf-luna-support` (`2dc2783`) | Already an ancestor; TF-Luna serial, filtering and ROS Jazzy support remain in the final launch. |
| `codex/rpi-ros2-distance-control` (`8ea1f64`) | Already an ancestor; internal distance command topic and single MAVROS setpoint owner are retained. |
| `agent/real-spray-controller` (`7e240bd`) | Replaced by `spray_actuator.py` and `spray_controller_node.py`: mock/GPIO backends, fail-closed output gate, pulse/cooldown/count limits and emergency stop. |
| `agent/grid-prior-ai-demo` (`f6f79d8`) | Useful spray safeguards were retained. Its fixed five-panel coordinates and grid-order assumptions were deliberately replaced by metric multi-frame mapping and dynamic routing because the final panels are random. |
| `codex/laptop-ai-inference` (`f7c38b0`) | CUDA-only ONNX execution, runtime tuning, GPU preflight, FP16 conversion and benchmarking were adapted to the production binary-segmentation protocol-v2 worker. |
| `codex/pendulum-joint-optimization-review` (`520514c`) | Joint scheduler validation, Pareto selection, hysteresis, scene-change tests and observe/apply boundary documentation were retained. |
| `codex/pendulum-joint-optimization` (`0d03614`) | Observe-only joint optimizer, scene-change trigger, CUDA tools and camera diagnostics were retained. Single-target/QGC-assisted flight logic was replaced by the Pi-owned multi-panel FSM. |
| `audit/full-software-check-20260814` (`777b5dd`) | Replaced by `.github/workflows/full-software-audit.yml`, now running on PRs and `main`, with CPU tests plus a ROS 2 Jazzy build/test job. |
| `codex/dashboard-ai-tools` (`20c0905`) | The real mobile-camera diagnostic relay was moved to `tools/`. Mock telemetry and mock flight/spray commands were not connected to the aircraft because they would create a second, untrusted control path. Operational state is published through ROS topics. |

## Final control ownership

- Raspberry Pi 5 owns mission state, ARM/OFFBOARD/LOITER/LAND transitions and
  every MAVROS position/velocity setpoint.
- The laptop owns only video decoding and perception. Its packets are untrusted,
  validated and ignored when stale.
- QGC is not required to execute the mission. An external mode change is treated
  as a control override and aborts the autonomous sequence.
- Diagnostic camera tools and the Pendulum observer never arm, change PX4 mode,
  publish setpoints or trigger spray.

## Deliberately external deployment inputs

The following cannot be safely generated from source code: trained ONNX weights,
measured camera footprint/mounting transform, camera-to-nozzle offsets, GPIO
wiring/polarity, measured network/GPU optimizer profiles, and SITL/real-flight
acceptance evidence. Checked-in approvals and live-output gates remain false until
those artifacts are supplied and verified.
