# DA-DAKA end-to-end cleaning path

## Control boundary

The laptop never sends flight or spray commands. Its responsibility ends at a
validated target coordinate. Raspberry Pi ROS 2 owns visual servoing, LiDAR
distance control, the single MAVROS velocity stream, and the final spray gate.
Pendulum-inspired optimization remains outside this safety/control path and may
only change the video/AI profile used to produce the same coordinate contract.

```text
Pi camera
  -> H.264 stream
Linux + RTX 5060 laptop
  -> panel ROI detection
  -> dirt inference inside panel ROI
  -> full-frame normalized dirt coordinate
  -> UDP JSON
Raspberry Pi
  -> ai_result_receiver (validation/freshness)
  -> visual_servo (XY correction)
  -> distance_controller (LiDAR Z correction)
  -> control_command_mixer (single MAVROS cmd_vel publisher)
  -> Pixhawk / PX4
  -> combined target reached
  -> cleaning_coordinator verifies actual vehicle stop
  -> spray_controller trigger
```

## Why command mixing is separate

The existing `distance_controller` historically publishes directly to
`/mavros/setpoint_velocity/cmd_vel`. A second visual-servo publisher on the same
topic would create a last-writer-wins race. The cleaning launch therefore remaps
the existing distance controller to `/distance_control/cmd_vel_z` and uses
`control_command_mixer` as the only cleaning-stack publisher to MAVROS.

The mixer publishes `/cleaning/target_reached` only when all of these are true:

- the distance command is fresh;
- the visual command is fresh;
- the AI target is valid;
- the dirt coordinate is currently aligned;
- the LiDAR distance controller reports its stable target reached.

Only `cleaning_mission.launch.py` remaps the Mission Manager's existing target
subscription to this stricter combined target. The legacy distance-only launch is
unchanged.

## Spray gate

`cleaning_coordinator` does not command flight. It requests one spray pulse only
when:

- Mission Manager is in `DISTANCE_CONTROL` or `TARGET_HOLD`;
- laptop AI heartbeat is healthy;
- the latest detection is valid and contains dirt;
- visual target is valid and aligned;
- `/cleaning/target_reached` is true;
- MAVROS-reported vehicle speed is below the configured stop threshold for the
  configured hold duration.

The repository still does not define the exact physical Pixhawk relay/servo/PWM
mapping for the nozzle. `spray_controller` is therefore deliberately fail-closed
and dry-run only. Replacing that endpoint with the bench-tested physical actuator
adapter does not require changes to AI, visual servo, distance control, or mission
logic.

## Running the ROS cleaning stack

After building and sourcing the ROS 2 workspace:

```bash
ros2 launch da_daka_control cleaning_mission.launch.py
```

Run the real TF-Luna source separately as required by the hardware setup. The
laptop AI process is also separate and sends validated UDP detection results to
the Pi receiver.

## Mandatory bench checks before propellers

1. Verify camera orientation and `horizontal_axis`, `vertical_axis`, and inversion
   signs with the vehicle unable to move.
2. Verify an AI heartbeat loss immediately drives mixer output to zero.
3. Verify stale/invalid detection never makes `/cleaning/target_reached` true.
4. Verify LiDAR target loss makes the combined target false.
5. Verify the spray service is still dry-run until the physical output mapping is
   explicitly implemented and tested.
